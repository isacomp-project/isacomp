#!/usr/bin/env python3
"""
RISC-V ILA vs ISA Equivalence Test Suite

Comprehensive test script that compares all RISC-V .isa files against
corresponding ILA models to verify semantic equivalence.

This can be run as part of CI to detect:
- ILA model bugs
- ISA model bugs
- Equivalence checker regressions
"""

import sys
import os
from pathlib import Path
import subprocess
from typing import List, Tuple, Optional
from dataclasses import dataclass
import json

# Add project root and ila/ dir to path
project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.resource_graph import ResourceGraph
from riscv_smt_equivalence import RISCVSMTEquivalenceChecker


@dataclass
class TestResult:
    """Result of testing one instruction."""
    instruction: str
    isa_file: str
    ila_file: str
    status: str  # 'equivalent', 'not_equivalent', 'timeout', 'error', 'missing'
    details: str
    isa_nodes: int = 0
    ila_nodes: int = 0
    z3_time: float = 0.0


class RISCVEquivalenceTestSuite:
    """Test suite for RISC-V ILA vs ISA equivalence."""

    def __init__(self):
        self.project_root = project_root
        self.isa_dir = self.project_root / 'isa/riscv32'
        self.ila_dir = self.project_root / 'frontends' / 'ila' / 'test_data' / 'riscv' / 'individual'
        self.results: List[TestResult] = []

    def find_instruction_pairs(self) -> List[Tuple[str, Path, Path]]:
        """Find all ISA/ILA instruction pairs."""
        pairs = []

        # Find all .isa files
        isa_files = sorted(self.isa_dir.glob('*.isa'))

        for isa_file in isa_files:
            instruction = isa_file.stem
            ila_file = self.ila_dir / f'riscv_{instruction}.json'

            if ila_file.exists():
                pairs.append((instruction, isa_file, ila_file))
            else:
                # Record as missing
                self.results.append(TestResult(
                    instruction=instruction,
                    isa_file=str(isa_file),
                    ila_file=str(ila_file),
                    status='missing',
                    details=f"ILA file not found: {ila_file}"
                ))

        return pairs

    def test_instruction(self, instruction: str, isa_file: Path, ila_file: Path) -> TestResult:
        """Test one instruction for equivalence."""
        result = TestResult(
            instruction=instruction,
            isa_file=str(isa_file),
            ila_file=str(ila_file),
            status='error',
            details=""
        )

        try:
            # Load graphs
            isa_graph = ResourceGraph.from_isa_file(str(isa_file))
            ila_graph = ResourceGraph.from_ila_json_file(str(ila_file))

            result.isa_nodes = len(isa_graph.nodes)
            result.ila_nodes = len(ila_graph.nodes)

            # Create equivalence checker
            checker = RISCVSMTEquivalenceChecker(ila_graph, isa_graph, str(isa_file))

            # Generate SMT formula
            formula = checker.generate_smt_formula_with_regfile_mapping()

            # Save formula
            formula_file = f"/tmp/riscv_{instruction}_equivalence.smt2"
            with open(formula_file, 'w') as f:
                f.write(formula)

            # Run Z3
            import time
            start_time = time.time()
            z3_result = subprocess.run(
                ['z3', '-smt2', formula_file],
                capture_output=True,
                text=True,
                timeout=60
            )
            result.z3_time = time.time() - start_time

            output = z3_result.stdout.strip()

            # Check first line for sat/unsat (ignore subsequent error messages about models)
            first_line = output.split('\n')[0] if output else ''

            if first_line == 'unsat':
                result.status = 'equivalent'
                result.details = "✓ EQUIVALENT (UNSAT)"
            elif first_line == 'sat':
                result.status = 'not_equivalent'
                # Extract first few lines of counterexample
                lines = output.split('\n')[:10]
                result.details = f"✗ NOT EQUIVALENT (SAT)\n" + '\n'.join(lines)
            elif first_line.startswith('(error'):
                result.status = 'error'
                result.details = f"Z3 error: {output[:200]}"
            else:
                result.status = 'error'
                result.details = f"Unexpected Z3 output: {output[:100]}"

        except subprocess.TimeoutExpired:
            result.status = 'timeout'
            result.details = "Z3 timeout (60s)"
        except Exception as e:
            result.status = 'error'
            result.details = f"Exception: {str(e)[:200]}"

        return result

    def run_all_tests(self, filter_instructions: Optional[List[str]] = None) -> None:
        """Run equivalence tests on all instruction pairs."""
        pairs = self.find_instruction_pairs()

        # Filter if requested
        if filter_instructions:
            pairs = [(i, isa, ila) for i, isa, ila in pairs if i in filter_instructions]

        print(f"\n{'='*70}")
        print(f"RISC-V ILA vs ISA Equivalence Test Suite")
        print(f"{'='*70}")
        print(f"\nFound {len(pairs)} instruction pairs to test")
        print(f"ISA directory: {self.isa_dir}")
        print(f"ILA directory: {self.ila_dir}")
        print()

        # Run tests
        for i, (instruction, isa_file, ila_file) in enumerate(pairs, 1):
            print(f"[{i}/{len(pairs)}] Testing {instruction}...", end=' ', flush=True)

            result = self.test_instruction(instruction, isa_file, ila_file)
            self.results.append(result)

            # Print status
            if result.status == 'equivalent':
                print("✓ EQUIVALENT")
            elif result.status == 'not_equivalent':
                print("✗ NOT EQUIVALENT")
            elif result.status == 'timeout':
                print("⏱ TIMEOUT")
            elif result.status == 'error':
                print(f"✗ ERROR: {result.details[:50]}")

    def print_summary(self) -> None:
        """Print test summary."""
        print(f"\n{'='*70}")
        print("TEST SUMMARY")
        print(f"{'='*70}\n")

        # Count by status
        status_counts = {}
        for result in self.results:
            status_counts[result.status] = status_counts.get(result.status, 0) + 1

        print(f"Total instructions tested: {len(self.results)}")
        for status in ['equivalent', 'not_equivalent', 'timeout', 'error', 'missing']:
            if status in status_counts:
                print(f"  {status:20s}: {status_counts[status]:3d}")

        # Detailed results table
        print(f"\n{'='*70}")
        print("DETAILED RESULTS")
        print(f"{'='*70}\n")
        print(f"{'Instruction':<15} {'Status':<20} {'ISA':<6} {'ILA':<6} {'Time':<6}")
        print(f"{'-'*70}")

        for result in sorted(self.results, key=lambda r: r.instruction):
            status_symbol = {
                'equivalent': '✓',
                'not_equivalent': '✗',
                'timeout': '⏱',
                'error': '✗',
                'missing': '?'
            }.get(result.status, '?')

            time_str = f"{result.z3_time:.2f}s" if result.z3_time > 0 else "N/A"

            print(f"{result.instruction:<15} {status_symbol} {result.status:<18} "
                  f"{result.isa_nodes:>4}n {result.ila_nodes:>4}n {time_str:>6}")

        # Print failures
        failures = [r for r in self.results if r.status in ['not_equivalent', 'error']]
        if failures:
            print(f"\n{'='*70}")
            print("FAILURES AND ISSUES")
            print(f"{'='*70}\n")

            for result in failures:
                print(f"{result.instruction}:")
                print(f"  Status: {result.status}")
                # Print first 200 chars of details
                detail_lines = result.details.split('\n')[:3]
                for line in detail_lines:
                    print(f"  {line[:70]}")
                print()

    def save_json_report(self, output_file: str = '/tmp/riscv_equivalence_report.json') -> None:
        """Save results as JSON for CI integration."""
        report = {
            'test_suite': 'RISC-V ILA vs ISA Equivalence',
            'total_tests': len(self.results),
            'summary': {},
            'results': []
        }

        # Summary
        for result in self.results:
            status = result.status
            report['summary'][status] = report['summary'].get(status, 0) + 1

        # Individual results
        for result in self.results:
            report['results'].append({
                'instruction': result.instruction,
                'status': result.status,
                'isa_file': result.isa_file,
                'ila_file': result.ila_file,
                'isa_nodes': result.isa_nodes,
                'ila_nodes': result.ila_nodes,
                'z3_time': result.z3_time,
                'details': result.details[:500]  # Truncate details
            })

        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2)

        print(f"\nJSON report saved to: {output_file}")

    def get_exit_code(self) -> int:
        """Return exit code for CI: 0 if all pass, 1 if any failures."""
        failures = [r for r in self.results if r.status in ['not_equivalent', 'error', 'timeout']]
        return 0 if len(failures) == 0 else 1


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Test RISC-V ILA vs ISA equivalence for all instructions'
    )
    parser.add_argument(
        'instructions',
        nargs='*',
        help='Specific instructions to test (default: all)'
    )
    parser.add_argument(
        '--json',
        type=str,
        default='/tmp/riscv_equivalence_report.json',
        help='Output JSON report file'
    )
    parser.add_argument(
        '--ci',
        action='store_true',
        help='CI mode: exit with code 1 if any tests fail'
    )

    args = parser.parse_args()

    # Run test suite
    suite = RISCVEquivalenceTestSuite()
    suite.run_all_tests(filter_instructions=args.instructions if args.instructions else None)
    suite.print_summary()
    suite.save_json_report(args.json)

    # Exit with appropriate code for CI
    if args.ci:
        sys.exit(suite.get_exit_code())


if __name__ == '__main__':
    main()
