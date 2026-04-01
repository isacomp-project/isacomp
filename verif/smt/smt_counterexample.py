"""
Counterexample visualization and debugging for SMT verification failures.

This module parses SMT solver output when verification fails and presents
counterexamples in human-readable format with:
- Input values that trigger the failure
- Expected vs actual output values
- Highlighted differences in architectural state
- Analysis of likely root cause
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from typing import Dict, List, Tuple, Optional, Any
from core.resource_graph import ResourceGraph, Node
import re
import json


class CounterexampleParser:
    """Parses SMT solver model output and extracts variable assignments."""

    def __init__(self):
        self.model: Dict[str, Any] = {}

    def parse_z3_model(self, output: str) -> Dict[str, Any]:
        """
        Parse Z3 model output and extract variable assignments.

        Z3 model format:
        sat
        (model
          (define-fun var_name () (_ BitVec 32) #x00000010)
          (define-fun other_var () Bool true)
          ...
        )
        """
        self.model = {}

        # Extract the model section
        model_match = re.search(r'\(model\s+(.*?)\s*\)(?:\s*$)', output, re.DOTALL)
        if not model_match:
            return self.model

        model_content = model_match.group(1)

        # Parse define-fun statements
        pattern = r'\(define-fun\s+(\w+)\s+\(\)\s+(?:\(_\s+)?(\w+)(?:\s+\d+\))?\s+(#x[0-9a-fA-F]+|#b[01]+|true|false|\d+)\)'

        for match in re.finditer(pattern, model_content):
            var_name = match.group(1)
            var_type = match.group(2)
            value_str = match.group(3)

            # Parse the value based on type
            if var_type == 'BitVec':
                if value_str.startswith('#x'):
                    value = int(value_str[2:], 16)
                elif value_str.startswith('#b'):
                    value = int(value_str[2:], 2)
                else:
                    value = int(value_str)
            elif var_type == 'Bool':
                value = value_str == 'true'
            else:
                # Try to parse as integer
                try:
                    value = int(value_str)
                except:
                    value = value_str

            self.model[var_name] = value

        return self.model

    def parse_cvc5_model(self, output: str) -> Dict[str, Any]:
        """
        Parse CVC5 model output.

        CVC5 model format is similar to Z3 but may have slight differences.
        """
        # For now, CVC5 output is similar enough to Z3 that we can reuse the parser
        return self.parse_z3_model(output)


class CounterexampleVisualizer:
    """Visualizes counterexamples in human-readable format."""

    def __init__(self,
                 graph_pre: ResourceGraph,
                 graph_post: ResourceGraph,
                 model: Dict[str, Any],
                 name_prefix_pre: str = "pre_",
                 name_prefix_post: str = "post_"):
        self.graph_pre = graph_pre
        self.graph_post = graph_post
        self.model = model
        self.prefix_pre = name_prefix_pre
        self.prefix_post = name_prefix_post

    def _get_var_value(self, var_name: str) -> Optional[Any]:
        """Get value of a variable from the model."""
        return self.model.get(var_name)

    def _format_value(self, value: Any, width: int = 32) -> str:
        """Format a value for display (hex + decimal)."""
        if isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, int):
            # Format as hex with appropriate width
            hex_width = (width + 3) // 4  # Round up to nearest hex digit
            return f"0x{value:0{hex_width}x} ({value})"
        else:
            return str(value)

    def _extract_architectural_state(self, prefix: str) -> Dict[str, Any]:
        """Extract architectural state variables (rf, pc, etc.) from model."""
        state = {}

        for var_name, value in self.model.items():
            if var_name.startswith(prefix):
                # Remove prefix
                clean_name = var_name[len(prefix):]

                # Check if this is an input or output
                if clean_name.endswith('_in'):
                    state_name = clean_name[:-3]  # Remove _in
                    if state_name not in state:
                        state[state_name] = {}
                    state[state_name]['in'] = value
                elif clean_name.endswith('_out'):
                    state_name = clean_name[:-4]  # Remove _out
                    if state_name not in state:
                        state[state_name] = {}
                    state[state_name]['out'] = value

        return state

    def _identify_mismatches(self) -> List[Tuple[str, Any, Any]]:
        """
        Identify mismatches between pre and post graphs.

        Returns list of (state_name, pre_value, post_value) tuples.
        """
        mismatches = []

        pre_state = self._extract_architectural_state(self.prefix_pre)
        post_state = self._extract_architectural_state(self.prefix_post)

        # Compare outputs
        for state_name in pre_state:
            if state_name in post_state:
                pre_out = pre_state[state_name].get('out')
                post_out = post_state[state_name].get('out')

                if pre_out is not None and post_out is not None and pre_out != post_out:
                    mismatches.append((state_name, pre_out, post_out))

        return mismatches

    def _analyze_root_cause(self, mismatches: List[Tuple[str, Any, Any]]) -> str:
        """
        Analyze mismatches and suggest likely root cause.

        This is heuristic-based pattern matching.
        """
        if not mismatches:
            return "Unknown: No mismatches found in architectural state"

        analyses = []

        for state_name, expected, actual in mismatches:
            # Check for common patterns
            if 'pc' in state_name.lower():
                analyses.append(f"PC update incorrect (expected {self._format_value(expected, 32)}, got {self._format_value(actual, 32)})")
            elif 'rf' in state_name.lower() or 'r' in state_name.lower():
                analyses.append(f"Register file write to {state_name} incorrect")

                # Try to identify if it's an off-by-one or bit flip
                if isinstance(expected, int) and isinstance(actual, int):
                    diff = actual - expected
                    if abs(diff) == 1:
                        analyses.append("  → Likely off-by-one error")
                    elif bin(expected ^ actual).count('1') == 1:
                        bit_pos = (expected ^ actual).bit_length() - 1
                        analyses.append(f"  → Single bit flip at position {bit_pos}")
                    elif expected == 0:
                        analyses.append("  → Expected 0, but value written (missing write condition?)")
                    elif actual == 0:
                        analyses.append("  → Expected value, but 0 written (incorrect write condition?)")

        if analyses:
            return "\n".join(analyses)
        else:
            return "Architectural state mismatch detected"

    def visualize(self, colorize: bool = True) -> str:
        """
        Generate human-readable counterexample report.

        Args:
            colorize: Use ANSI color codes for terminal output

        Returns:
            Formatted counterexample report
        """
        # ANSI color codes
        if colorize:
            RED = '\033[91m'
            GREEN = '\033[92m'
            YELLOW = '\033[93m'
            BLUE = '\033[94m'
            RESET = '\033[0m'
            BOLD = '\033[1m'
        else:
            RED = GREEN = YELLOW = BLUE = RESET = BOLD = ''

        lines = []
        lines.append(f"\n{RED}{BOLD}❌ Verification FAILED - Counterexample found{RESET}\n")

        # Extract inputs (pre_ and post_ should have same inputs)
        pre_state = self._extract_architectural_state(self.prefix_pre)

        lines.append(f"{BOLD}Inputs:{RESET}")
        for state_name, values in sorted(pre_state.items()):
            if 'in' in values:
                # Determine width (try to infer from graph)
                width = 32  # default
                formatted = self._format_value(values['in'], width)
                lines.append(f"  {state_name:12s} = {formatted}")

        # Extract expected outputs (from pre graph)
        lines.append(f"\n{BOLD}Expected (pre-optimization):{RESET}")
        for state_name, values in sorted(pre_state.items()):
            if 'out' in values:
                width = 32
                formatted = self._format_value(values['out'], width)
                lines.append(f"  {state_name:12s} = {formatted}")

        # Extract actual outputs (from post graph)
        post_state = self._extract_architectural_state(self.prefix_post)
        mismatches = self._identify_mismatches()
        mismatch_names = {name for name, _, _ in mismatches}

        lines.append(f"\n{BOLD}Actual (post-optimization):{RESET}")
        for state_name, values in sorted(post_state.items()):
            if 'out' in values:
                width = 32
                formatted = self._format_value(values['out'], width)

                if state_name in mismatch_names:
                    lines.append(f"  {state_name:12s} = {formatted} {RED}❌ MISMATCH{RESET}")
                else:
                    lines.append(f"  {state_name:12s} = {formatted} {GREEN}✓{RESET}")

        # Analysis
        if mismatches:
            lines.append(f"\n{BOLD}{YELLOW}Analysis:{RESET}")
            root_cause = self._analyze_root_cause(mismatches)
            for line in root_cause.split('\n'):
                lines.append(f"  {line}")

        # Detailed mismatch breakdown
        if mismatches:
            lines.append(f"\n{BOLD}Detailed Mismatches:{RESET}")
            for state_name, expected, actual in mismatches:
                lines.append(f"\n  {BOLD}{state_name}{RESET}:")
                lines.append(f"    Expected: {self._format_value(expected, 32)}")
                lines.append(f"    Actual:   {self._format_value(actual, 32)}")

                if isinstance(expected, int) and isinstance(actual, int):
                    diff = actual - expected
                    lines.append(f"    Diff:     {diff:+d} (0x{diff:+x})")

                    # Show bit-level difference
                    xor = expected ^ actual
                    if xor != 0:
                        lines.append(f"    XOR:      {self._format_value(xor, 32)}")
                        lines.append(f"    Bits changed: {bin(xor).count('1')}")

        lines.append("")  # Blank line at end

        return "\n".join(lines)

    def export_json(self, filepath: str):
        """Export counterexample to JSON for programmatic analysis."""
        data = {
            'status': 'failed',
            'pre_state': self._extract_architectural_state(self.prefix_pre),
            'post_state': self._extract_architectural_state(self.prefix_post),
            'mismatches': [
                {
                    'state': name,
                    'expected': expected,
                    'actual': actual
                }
                for name, expected, actual in self._identify_mismatches()
            ],
            'raw_model': self.model
        }

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)


def parse_and_visualize_counterexample(
    solver_output: str,
    graph_pre: ResourceGraph,
    graph_post: ResourceGraph,
    solver: str = 'z3',
    colorize: bool = True
) -> str:
    """
    Convenience function to parse and visualize a counterexample.

    Args:
        solver_output: Raw output from SMT solver
        graph_pre: Pre-optimization resource graph
        graph_post: Post-optimization resource graph
        solver: Which solver was used ('z3' or 'cvc5')
        colorize: Whether to use ANSI colors

    Returns:
        Human-readable counterexample report
    """
    # Parse the model
    parser = CounterexampleParser()

    if solver == 'z3':
        model = parser.parse_z3_model(solver_output)
    elif solver == 'cvc5':
        model = parser.parse_cvc5_model(solver_output)
    else:
        raise ValueError(f"Unsupported solver: {solver}")

    if not model:
        return "No counterexample model found in solver output"

    # Visualize
    visualizer = CounterexampleVisualizer(graph_pre, graph_post, model)
    return visualizer.visualize(colorize=colorize)
