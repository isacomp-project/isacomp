"""
Analyze instruction lengths from ISA specifications.

For variable-length instruction sets (like 6502, x86), this module
analyzes sequential PC assignments to determine each instruction's length.
"""

from typing import Dict, Optional, Tuple
from .resource_graph import ResourceGraph


def _extract_pc_increment(expr: dict, pc_name: str) -> Optional[int]:
    """
    Check if an expression is a PC increment pattern and extract the total increment.

    Handles both simple patterns like ``pc + 4`` and chained patterns produced when
    the parser collapses multiple sequential ``pc = pc + N`` assignments into a
    single expression such as ``(((pc + 2) + 2) + 2)``.

    Args:
        expr: Expression dictionary to analyze
        pc_name: Name of the program counter

    Returns:
        The total increment value if this is a pc + N chain, None otherwise
    """
    if not expr or not isinstance(expr, dict):
        return None

    if expr.get('type') == 'binary_op' and expr.get('operator') == '+':
        left = expr.get('left', {})
        right = expr.get('right', {})

        # Check for pc + N base case
        if left.get('type') == 'identifier' and left.get('name') == pc_name:
            if right.get('type') == 'literal':
                return right.get('value', 1)

        # Also check N + pc pattern (less common but valid)
        if right.get('type') == 'identifier' and right.get('name') == pc_name:
            if left.get('type') == 'literal':
                return left.get('value', 1)

        # Recurse into chained additions: (pc + M) + N  ->  M + N
        if right.get('type') == 'literal':
            sub = _extract_pc_increment(left, pc_name)
            if sub is not None:
                return sub + right.get('value', 0)
        if left.get('type') == 'literal':
            sub = _extract_pc_increment(right, pc_name)
            if sub is not None:
                return sub + left.get('value', 0)

    return None


def _trace_increment_via_graph(graph: ResourceGraph, node, pc_rd_id: str,
                               visited: set = None) -> Optional[int]:
    """
    Trace back through graph edges from a node to pc_rd, summing addition
    constants along the way.

    Handles patterns like:
        pc_plus_1 = pc + 1
        pc_plus_2 = pc_plus_1 + 1
    where pc_plus_2 traces back to pc_rd with total increment 2.

    Returns the total increment if the path is a chain of additions leading
    to pc_rd, or None if no such path exists.
    """
    if visited is None:
        visited = set()
    if node.id in visited:
        return None
    visited.add(node.id)

    # Base case: we reached pc_rd
    if node.id == pc_rd_id:
        return 0

    node_type = node.data.get('type')

    # For addition operations, find the two operands
    if node_type == 'operation' and node.data.get('operator') == '+':
        operands = [e.source for e in node.incoming_edges
                    if e.data.get('type') == 'operand']
        if len(operands) == 2:
            for i in range(2):
                other = 1 - i
                # Check if one operand is a literal
                if operands[other].data.get('type') == 'literal':
                    lit_val = operands[other].data.get('value')
                    if lit_val is not None:
                        # Recurse on the non-literal operand
                        sub = _trace_increment_via_graph(
                            graph, operands[i], pc_rd_id, visited)
                        if sub is not None:
                            return sub + lit_val

    # For var/wire nodes, follow through assignment edges
    if node_type in ('var', 'wire', 'register'):
        for edge in node.incoming_edges:
            if edge.data.get('type') == 'assignment':
                sub = _trace_increment_via_graph(
                    graph, edge.source, pc_rd_id, visited)
                if sub is not None:
                    return sub

    return None


def _extract_increment_from_ternary(expr: dict, pc_name: str) -> Optional[int]:
    """
    Extract PC increment from a ternary expression by checking both branches.

    For branch instructions like `pc = cond ? dest : pc + 4` or `pc = cond ? pc + 4 : dest`,
    we need to find which branch contains the sequential PC increment.

    Args:
        expr: Ternary expression dictionary
        pc_name: Name of the program counter

    Returns:
        The increment value if found in either branch, None otherwise
    """
    true_expr = expr.get('if_true', {})
    false_expr = expr.get('if_false', {})

    # Check false branch first (more common for branch instructions)
    increment = _extract_pc_increment(false_expr, pc_name)
    if increment is not None:
        return increment

    # Check true branch
    increment = _extract_pc_increment(true_expr, pc_name)
    if increment is not None:
        return increment

    # Recursively check nested ternaries
    if true_expr.get('type') == 'ternary_op':
        increment = _extract_increment_from_ternary(true_expr, pc_name)
        if increment is not None:
            return increment

    if false_expr.get('type') == 'ternary_op':
        increment = _extract_increment_from_ternary(false_expr, pc_name)
        if increment is not None:
            return increment

    return None


def _extract_increment_from_gated_mux(mux_node, pc_name: str) -> Optional[int]:
    """
    Extract PC increment from a gated write mux by examining the default input.

    When aspects (e.g., exception/interrupt handling) are merged into an instruction,
    the aspect_merger creates a priority multiplexer (gated write mux) that selects
    between the aspect's override value (e.g., exception handler PC) and the base
    instruction's default value (e.g., pc + N).

    The default input (mux_default_input edge) carries the base instruction's
    normal PC increment.  We look through the mux to find that pattern.

    Args:
        mux_node: The multiplexer node (must have gated_write_mux=True)
        pc_name: Name of the program counter

    Returns:
        The increment value from the default input if it's a pc + N pattern, None otherwise
    """
    for edge in mux_node.incoming_edges:
        if edge.data.get('type') == 'mux_default_input':
            default_source = edge.source
            default_type = default_source.data.get('type')
            default_expr = default_source.data.get('expression', {})

            if default_type == 'operation':
                return _extract_pc_increment(default_expr, pc_name)
            elif default_type == 'ternary_op':
                return _extract_increment_from_ternary(default_expr, pc_name)

    return None


def analyze_instruction_length(graph: ResourceGraph, pc_name: str = "pc") -> Optional[int]:
    """
    Analyze an instruction's PC increment pattern for deduplication.

    This analyzes pc = pc + N assignments to find instructions that can share
    PC increment logic. Returns None for instructions that don't use fixed
    PC increments (e.g., unconditional jumps like jal where pc = computed_dest).

    For variable-length ISAs (6502, x86), looks for patterns like:
        pc = pc + 1;  // Fetch opcode
        pc = pc + 1;  // Fetch immediate byte

    For fixed-length ISAs with branches, looks for:
        pc = cond ? branch_dest : pc + 4;

    Args:
        graph: ResourceGraph for a single instruction
        pc_name: Name of the program counter register (default "pc")

    Returns:
        Instruction length in bytes if a pc + N pattern is found, None otherwise
    """
    pc_wr_id = f"{pc_name}_wr"

    if pc_wr_id not in graph.nodes:
        # No PC write - might be a halt instruction or error
        print(f"Warning: No {pc_wr_id} node found in graph")
        return None

    pc_wr_node = graph.nodes[pc_wr_id]

    # Two-pass approach:
    # Pass 1: Check if the FINAL (non-intermediate) write is a pc + N pattern.
    #   If the final write is a computed destination (e.g. BSR's pc = target),
    #   return None even if intermediate writes were pc + N.
    # Pass 2: If the final write IS pc + N, sum ALL writes (including intermediate)
    #   to get the total instruction length.

    final_is_increment = False
    ternary_sources = []  # Collect ternary nodes for graph-based fallback
    for edge in pc_wr_node.incoming_edges:
        if edge.data.get('type') == 'assignment' and not edge.data.get('intermediate'):
            source = edge.source
            source_type = source.data.get('type')
            expr = source.data.get('expression', {})

            if source_type == 'operation':
                if _extract_pc_increment(expr, pc_name) is not None:
                    final_is_increment = True
            elif source_type in ['ternary', 'ternary_op']:
                value = _extract_increment_from_ternary(expr, pc_name)
                if value is not None:
                    final_is_increment = True
                else:
                    ternary_sources.append(source)
            elif source_type == 'multiplexer' and source.data.get('gated_write_mux'):
                # Look through gated write mux to the default input
                if _extract_increment_from_gated_mux(source, pc_name) is not None:
                    final_is_increment = True

    # Graph-based fallback for patterns like BEQ where local variables are used
    # instead of direct pc assignments:
    #   pc_plus_1 = pc + 1; pc_plus_2 = pc_plus_1 + 1;
    #   pc = cond ? branch_dest : pc_plus_2
    # Trace the ternary branch that leads back to pc_rd through additions.
    if not final_is_increment and ternary_sources:
        pc_rd_id = f"{pc_name}_rd"
        if pc_rd_id not in graph.nodes:
            pc_rd_id = pc_name
        for source in ternary_sources:
            for tern_edge in source.incoming_edges:
                etype = tern_edge.data.get('type', '')
                if etype in ('ternary_true', 'ternary_false'):
                    value = _trace_increment_via_graph(
                        graph, tern_edge.source, pc_rd_id)
                    if value is not None and value > 0:
                        final_is_increment = True
                        break
            if final_is_increment:
                break

    if not final_is_increment:
        return None

    # Final write is a pc + N pattern; sum ALL assignment edges (including
    # intermediate) to get the total instruction length.
    total_increment = 0
    for edge in pc_wr_node.incoming_edges:
        if edge.data.get('type') == 'assignment':
            source = edge.source
            source_type = source.data.get('type')
            expr = source.data.get('expression', {})

            if source_type == 'operation':
                value = _extract_pc_increment(expr, pc_name)
                if value is not None:
                    total_increment += value
            elif source_type in ['ternary', 'ternary_op']:
                value = _extract_increment_from_ternary(expr, pc_name)
                if value is not None:
                    total_increment += value
            elif source_type == 'multiplexer' and source.data.get('gated_write_mux'):
                value = _extract_increment_from_gated_mux(source, pc_name)
                if value is not None:
                    total_increment += value

    if total_increment > 0:
        return total_increment

    # If expression-based summing found nothing (e.g., graph-based fallback found
    # the pattern), use the graph tracer to compute the total
    if ternary_sources:
        pc_rd_id = f"{pc_name}_rd"
        if pc_rd_id not in graph.nodes:
            pc_rd_id = pc_name
        for source in ternary_sources:
            for tern_edge in source.incoming_edges:
                etype = tern_edge.data.get('type', '')
                if etype in ('ternary_true', 'ternary_false'):
                    value = _trace_increment_via_graph(
                        graph, tern_edge.source, pc_rd_id)
                    if value is not None and value > 0:
                        return value

    return None


def analyze_all_instruction_lengths(instruction_graphs: Dict[str, ResourceGraph],
                                    pc_name: str = "pc") -> Dict[str, int]:
    """
    Analyze instruction lengths for all instructions.

    Args:
        instruction_graphs: Dictionary mapping instruction names to their graphs
        pc_name: Name of the program counter register

    Returns:
        Dictionary mapping instruction names to their lengths in bytes
    """
    lengths = {}

    for instr_name, graph in instruction_graphs.items():
        length = analyze_instruction_length(graph, pc_name)
        lengths[instr_name] = length
        print(f"Instruction {instr_name}: {length} bytes")

    return lengths


def remove_intermediate_pc_writes(instruction_graphs: Dict[str, ResourceGraph],
                                   pc_name: str = "pc") -> None:
    """
    Remove dead intermediate PC writes from each instruction graph.

    The parser tags intermediate (non-final) assignment edges with
    'intermediate': True.  Variable-length instructions write PC multiple
    times (once per extension word fetch).  The instruction length analysis
    sums those edges, but the intermediate ones must be removed before
    merging to avoid conflicting mux entries for dead writes.

    Must be called AFTER analyze_instruction_length (which reads intermediate
    edges) but BEFORE merge_graphs.

    Args:
        instruction_graphs: Dictionary mapping instruction names to their graphs
        pc_name: Name of the program counter register
    """
    pc_wr_id = f"{pc_name}_wr"
    for instr_name, graph in instruction_graphs.items():
        if pc_wr_id not in graph.nodes:
            continue
        pc_wr_node = graph.nodes[pc_wr_id]
        intermediate_edges = [
            e for e in list(pc_wr_node.incoming_edges)
            if e.data.get('type') == 'assignment' and e.data.get('intermediate')
        ]
        for e in intermediate_edges:
            graph.remove_edge(e.id)
        if intermediate_edges:
            print(f"  {instr_name}: removed {len(intermediate_edges)} dead "
                  f"intermediate write(s) to {pc_wr_id}")


def get_max_instruction_length(instruction_lengths: Dict[str, int]) -> int:
    """
    Get the maximum instruction length across all instructions.

    Args:
        instruction_lengths: Dictionary mapping instruction names to lengths

    Returns:
        Maximum instruction length in bytes
    """
    if not instruction_lengths:
        return 1

    return max(instruction_lengths.values())
