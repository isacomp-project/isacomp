"""
Mux Case Analyzer for flattening nested multiplexers.

This module provides utilities for analyzing mux and ternary nodes to extract
their cases (value, condition pairs), enabling deduplication and flattening
of nested mux structures into single flat muxes.

Example transformation:
    Before: pc_wr_mux with 6 branch ternaries + 2 jump destinations
    After:  pc_wr_mux with 4 inputs (branch_dest, jal_dest, jalr_dest, pc+4)
            where branch_dest is selected by OR of all branch conditions
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from .resource_graph import ResourceGraph, Node, Edge
import hashlib


def _get_load_prefixes_for_target(target_base: str) -> List[str]:
    """Get instruction prefixes that load/write a memory value directly to a target register.

    Used to filter group_members when a shared data node (like adc_abs_data) writes
    to a register mux. Only instructions that actually load memory to that register
    should be included in the select signal.

    Args:
        target_base: Base name of target register (e.g., 'A', 'X', 'Y', 'S')

    Returns:
        List of instruction prefixes that write memory loads to this target
    """
    # Map from target register to instruction prefixes that load memory values to it
    # For 6502: LDA loads to A, LDX to X, LDY to Y, PLA pops stack to A, etc.
    load_map = {
        'A': ['lda', 'pla'],           # LDA variants, PLA (pull accumulator)
        'X': ['ldx', 'tax', 'tsx'],    # LDX variants, TAX (transfer A to X), TSX (transfer S to X)
        'Y': ['ldy', 'tay'],           # LDY variants, TAY (transfer A to Y)
        'S': ['txs'],                   # TXS (transfer X to S)
        'flag_N': ['lda', 'ldx', 'ldy', 'pla', 'tax', 'tay', 'tsx', 'txa', 'tya',
                   'and', 'ora', 'eor', 'asl', 'lsr', 'rol', 'ror', 'inc', 'dec',
                   'inx', 'iny', 'dex', 'dey', 'cmp', 'cpx', 'cpy', 'bit', 'adc', 'sbc'],
        'flag_Z': ['lda', 'ldx', 'ldy', 'pla', 'tax', 'tay', 'tsx', 'txa', 'tya',
                   'and', 'ora', 'eor', 'asl', 'lsr', 'rol', 'ror', 'inc', 'dec',
                   'inx', 'iny', 'dex', 'dey', 'cmp', 'cpx', 'cpy', 'bit', 'adc', 'sbc'],
        'flag_C': ['asl', 'lsr', 'rol', 'ror', 'cmp', 'cpx', 'cpy', 'adc', 'sbc', 'sec', 'clc'],
        'flag_V': ['adc', 'sbc', 'bit', 'clv'],
    }

    # Return the prefixes for the target, or empty list if unknown target
    return load_map.get(target_base, [])


@dataclass
class MuxCase:
    """A single case in a mux/ternary.

    Represents one input to a multiplexer along with its selection condition.
    """
    value_node_id: str              # Node providing the value
    condition_node_id: Optional[str]  # Node providing the select condition (None for default)
    condition_inverted: bool = False  # True if condition should be inverted (for ternary false branch)
    source_instruction: str = 'shared'  # Which instruction this came from
    is_default: bool = False        # True if this is the "else"/default case
    original_mux_id: Optional[str] = None  # The mux/ternary this case came from
    gated_mux_index: Optional[int] = None  # Input index from gated write mux (reflects declared priority)
    from_aspect: Optional[str] = None  # Aspect file that produced this case (from gated write mux edge)

    def get_effective_condition(self, enable_node_id: Optional[str] = None) -> str:
        """Get the effective condition expression.

        Args:
            enable_node_id: Optional instruction enable node to AND with condition

        Returns:
            Condition expression string
        """
        if self.is_default:
            return "default"

        cond = self.condition_node_id
        if self.condition_inverted:
            cond = f"!{cond}"

        if enable_node_id:
            return f"({enable_node_id} && {cond})"
        return cond


@dataclass
class MuxAnalysis:
    """Complete analysis of a mux or ternary node.

    Contains all extracted cases and metadata about the mux structure.
    """
    mux_node_id: str                # ID of the mux/ternary being analyzed
    mux_type: str                   # 'ternary_op' or 'multiplexer'
    cases: List[MuxCase] = field(default_factory=list)
    target_node_id: Optional[str] = None  # What this mux assigns to (if known)
    source_instruction: str = 'shared'  # Instruction this mux belongs to

    def get_value_node_ids(self) -> Set[str]:
        """Get all unique value node IDs in this mux."""
        return {case.value_node_id for case in self.cases}

    def get_true_case(self) -> Optional[MuxCase]:
        """For ternaries, get the true branch case."""
        for case in self.cases:
            if not case.condition_inverted and not case.is_default:
                return case
        return None

    def get_false_case(self) -> Optional[MuxCase]:
        """For ternaries, get the false branch case."""
        for case in self.cases:
            if case.condition_inverted or case.is_default:
                return case
        return None


@dataclass
class ValueGroup:
    """A group of cases that share the same value (structurally equivalent).

    When multiple mux cases select the same value node, they can be merged
    by OR'ing their conditions together.
    """
    value_node_id: str              # The shared value node
    cases: List[MuxCase] = field(default_factory=list)
    structure_key: str = ''         # Structural hash for equivalence checking

    def get_merged_condition_parts(self) -> List[str]:
        """Get list of condition expressions to OR together."""
        parts = []
        for case in self.cases:
            if not case.is_default:
                parts.append(case.get_effective_condition())
        return parts


def analyze_ternary(graph: ResourceGraph, node: Node,
                    source_instruction: str = 'shared') -> MuxAnalysis:
    """Analyze a ternary_op node to extract its cases.

    A ternary `cond ? true_val : false_val` produces two cases:
    - true_val with condition=cond
    - false_val with condition=!cond (or as default)

    Args:
        graph: The resource graph
        node: The ternary_op node to analyze
        source_instruction: Instruction this ternary belongs to

    Returns:
        MuxAnalysis with the extracted cases
    """
    if node.data.get('type') != 'ternary_op':
        raise ValueError(f"Expected ternary_op, got {node.data.get('type')}")

    analysis = MuxAnalysis(
        mux_node_id=node.id,
        mux_type='ternary_op',
        source_instruction=source_instruction
    )

    # Find the three inputs: condition, true value, false value
    # Sort edges for deterministic selection
    condition_node = None
    true_node = None
    false_node = None

    for edge in sorted(node.incoming_edges, key=lambda e: (e.source.id, e.data.get('type', ''))):
        edge_type = edge.data.get('type', '')
        if edge_type == 'ternary_condition':
            condition_node = edge.source
        elif edge_type == 'ternary_true':
            true_node = edge.source
        elif edge_type == 'ternary_false':
            false_node = edge.source

    # Always debug ternary analysis for now
    for edge in sorted(node.incoming_edges, key=lambda e: e.source.id):
        print(f"  edge type={edge.data.get('type')}, source={edge.source.id}")

    if not all([condition_node, true_node, false_node]):
        print(f"Warning: Incomplete ternary {node.id}: cond={condition_node}, true={true_node}, false={false_node}")
        return analysis

    # Create case for true branch (condition is true)
    true_case = MuxCase(
        value_node_id=true_node.id,
        condition_node_id=condition_node.id,
        condition_inverted=False,
        source_instruction=source_instruction,
        is_default=False,
        original_mux_id=node.id
    )
    analysis.cases.append(true_case)

    # Create case for false branch (condition is false -> use as default)
    false_case = MuxCase(
        value_node_id=false_node.id,
        condition_node_id=condition_node.id,
        condition_inverted=True,
        source_instruction=source_instruction,
        is_default=True,  # False branch is effectively the default
        original_mux_id=node.id
    )
    analysis.cases.append(false_case)

    # Find target (what this ternary assigns to)
    for edge in node.outgoing_edges:
        if edge.data.get('type') == 'assignment':
            analysis.target_node_id = edge.target.id
            break

    return analysis


def analyze_mux(graph: ResourceGraph, node: Node,
                source_instruction: str = 'shared') -> MuxAnalysis:
    """Analyze a multiplexer node to extract its cases.

    Args:
        graph: The resource graph
        node: The multiplexer node to analyze
        source_instruction: Instruction this mux belongs to

    Returns:
        MuxAnalysis with the extracted cases
    """
    if node.data.get('type') != 'multiplexer':
        raise ValueError(f"Expected multiplexer, got {node.data.get('type')}")

    analysis = MuxAnalysis(
        mux_node_id=node.id,
        mux_type='multiplexer',
        source_instruction=source_instruction
    )

    # Collect inputs indexed by their input_index
    inputs_by_index: Dict[int, Tuple[Node, Optional[Node]]] = {}  # idx -> (value_node, select_node)
    aspect_by_index: Dict[int, Optional[str]] = {}  # idx -> from_aspect file path
    default_input = None
    is_gated = node.data.get('gated_write_mux', False)

    # Get select conditions stored in node data
    select_conditions = node.data.get('select_conditions', {})

    # Sort edges for deterministic order
    for edge in sorted(node.incoming_edges, key=lambda e: (e.source.id, e.data.get('type', ''))):
        edge_type = edge.data.get('type', '')

        if edge_type == 'mux_input':
            idx = edge.data.get('input_index', 0)
            if idx not in inputs_by_index:
                inputs_by_index[idx] = (edge.source, None)
            else:
                inputs_by_index[idx] = (edge.source, inputs_by_index[idx][1])
            # Collect aspect file from edge metadata
            fa = edge.data.get('from_aspect')
            if fa is not None:
                aspect_by_index[idx] = fa

        elif edge_type == 'mux_select':
            # Skip the global orthogon selector edge — it's the case
            # expression for Verilog generation, not a per-input condition.
            # Without this, it overwrites the per-variant condition for
            # input 0 (defaulting select_index to 0), breaking merging.
            if edge.data.get('orthogon_selector'):
                continue
            idx = edge.data.get('select_index', 0)
            if idx not in inputs_by_index:
                inputs_by_index[idx] = (None, edge.source)
            else:
                inputs_by_index[idx] = (inputs_by_index[idx][0], edge.source)

        elif edge_type == 'mux_default_input':
            default_input = edge.source

    # Create cases for each input
    for idx in sorted(inputs_by_index.keys()):
        value_node, select_node = inputs_by_index[idx]
        if value_node is None:
            continue

        # Get condition - either from select node or from stored conditions
        condition_id = None
        if select_node:
            condition_id = select_node.id
        elif idx in select_conditions:
            condition_id = select_conditions[idx]

        case = MuxCase(
            value_node_id=value_node.id,
            condition_node_id=condition_id,
            condition_inverted=False,
            source_instruction=source_instruction,
            is_default=False,
            original_mux_id=node.id,
            gated_mux_index=idx if is_gated else None,
            from_aspect=aspect_by_index.get(idx) if is_gated else None
        )
        analysis.cases.append(case)

    # Add default case if present
    if default_input:
        default_case = MuxCase(
            value_node_id=default_input.id,
            condition_node_id=None,
            condition_inverted=False,
            source_instruction=source_instruction,
            is_default=True,
            original_mux_id=node.id
        )
        analysis.cases.append(default_case)

    # Find target
    for edge in node.outgoing_edges:
        if edge.data.get('type') == 'assignment':
            analysis.target_node_id = edge.target.id
            break

    return analysis


def get_node_structure_key(graph: ResourceGraph, node_id: str,
                           depth: int = 2) -> str:
    """Compute a structural hash for a node to detect equivalence.

    Two nodes with the same structure key are structurally equivalent
    and can be merged in mux deduplication.

    Args:
        graph: The resource graph
        node_id: ID of the node to hash
        depth: How many levels of inputs to include in hash

    Returns:
        Hex string hash representing the node's structure
    """
    if node_id not in graph.nodes:
        return f"missing:{node_id}"

    node = graph.nodes[node_id]

    # Build structure string
    parts = [
        f"type:{node.data.get('type', 'unknown')}",
        f"op:{node.data.get('operator', '')}",
        f"id:{node_id}"  # Include ID for shared nodes
    ]

    # For shared nodes, ID is sufficient for matching
    if node.data.get('is_shared'):
        return hashlib.md5('|'.join(parts).encode()).hexdigest()[:12]

    # For non-shared nodes, recurse into inputs
    if depth > 0:
        input_keys = []
        for edge in sorted(node.incoming_edges, key=lambda e: e.source.id):
            if edge.data.get('type') in ['operand', 'assignment', 'data']:
                input_key = get_node_structure_key(graph, edge.source.id, depth - 1)
                input_keys.append(f"{edge.data.get('type')}:{input_key}")
        parts.append(f"inputs:[{','.join(sorted(input_keys))}]")

    return hashlib.md5('|'.join(parts).encode()).hexdigest()[:12]


def group_cases_by_value(graph: ResourceGraph,
                         cases: List[MuxCase]) -> Dict[str, ValueGroup]:
    """Group mux cases by their value node equivalence.

    Cases with structurally equivalent values can be merged by OR'ing
    their conditions.

    Args:
        graph: The resource graph
        cases: List of MuxCase to group

    Returns:
        Dict mapping value_node_id to ValueGroup
    """
    # First, compute structure keys for all values
    value_to_key: Dict[str, str] = {}
    for case in cases:
        if case.value_node_id not in value_to_key:
            key = get_node_structure_key(graph, case.value_node_id)
            value_to_key[case.value_node_id] = key

    # Group by structure key
    key_to_group: Dict[str, ValueGroup] = {}

    # Sort cases for deterministic grouping - the first case per key determines the group's value_node_id
    sorted_cases = sorted(cases, key=lambda c: (c.value_node_id or '', c.condition_node_id or '', c.source_instruction or ''))
    for case in sorted_cases:
        key = value_to_key[case.value_node_id]

        if key not in key_to_group:
            key_to_group[key] = ValueGroup(
                value_node_id=case.value_node_id,
                structure_key=key
            )

        key_to_group[key].cases.append(case)

    # Convert to value_node_id keyed dict (use first value node in each group)
    # Sort by structure_key for deterministic order
    result: Dict[str, ValueGroup] = {}
    for group in sorted(key_to_group.values(), key=lambda g: (g.structure_key or '', g.value_node_id or '')):
        result[group.value_node_id] = group

    return result


def find_isa_state_mux_sources(graph: ResourceGraph,
                                wr_node_id: str) -> List[Tuple[Node, str, Optional[dict]]]:
    """Find all nodes that assign to an ISA state write node.

    This function finds sources in two ways:
    1. Direct assignment edges to wr_node_id
    2. Collision nodes with original_id matching wr_node_id (e.g., beq_pc_wr with original_id=pc_wr)

    For collision nodes, we look at what feeds INTO them to get the actual value source.

    Args:
        graph: The resource graph
        wr_node_id: ID of the write node (e.g., 'pc_wr')

    Returns:
        List of (source_node, instruction_name, enable_expr) tuples.
        enable_expr is the condition from 'when' clause (e.g., is_satp), or None if unconditional.
    """
    sources = []

    # Method 1: Direct assignment edges to wr_node_id
    if wr_node_id in graph.nodes:
        wr_node = graph.nodes[wr_node_id]
        for edge in sorted(wr_node.incoming_edges, key=lambda e: (e.source.id, e.target.id)):
            if edge.data.get('type') == 'assignment':
                source = edge.source

                # Get enable condition from edge (from 'when' clause)
                enable_expr = edge.data.get('enable')

                # Determine instruction from node metadata or ID prefix
                instr = source.data.get('instruction', 'shared')
                if instr == 'shared':
                    # Try to infer from node ID prefix
                    for part in source.id.split('_'):
                        # Check if this could be an instruction prefix
                        # (heuristic: short lowercase string)
                        if part.islower() and len(part) <= 6:
                            instr = part
                            break

                sources.append((source, instr, enable_expr))

    # Method 2: Find collision nodes via original_id metadata
    # These are instruction-prefixed nodes like beq_pc_wr that have original_id=pc_wr
    for node_id, node in sorted(graph.nodes.items()):
        if node.data.get('original_id') == wr_node_id:
            # This is a collision node for our target (e.g., beq_pc_wr)
            # Find what feeds INTO this collision node - that's the actual value

            # Collect ALL assignment edges - different instructions may have different enable conditions
            # Each edge may have 'source_instruction' metadata identifying which instruction it came from
            assignment_edges = []
            for edge in sorted(node.incoming_edges, key=lambda e: (e.source.id, e.target.id)):
                if edge.data.get('type') == 'assignment':
                    assignment_edges.append(edge)

            if not assignment_edges:
                continue  # No incoming assignments, skip

            # Check group_members to determine which instructions use this node
            group_members = node.data.get('group_members', [])

            if group_members and len(group_members) > 0:
                # Multiple instructions share this collision node.
                # In merged graphs, ALL incoming edges apply to ALL group members
                # (that's what merging means - structurally identical instructions share nodes).
                # Each edge represents a different write condition (e.g., ITB fault → pc,
                # DTB fault → addr), and every group member needs ALL of them.
                #
                # First check if edges have source_instruction metadata for per-instruction matching.
                edges_have_instr_metadata = any(
                    edge.data.get('source_instruction') for edge in assignment_edges
                )

                if edges_have_instr_metadata:
                    # Per-instruction edges: match each edge to its specific instruction
                    for edge in assignment_edges:
                        instr = edge.data.get('source_instruction')
                        if instr and instr in group_members:
                            sources.append((edge.source, instr, edge.data.get('enable')))
                else:
                    # Shared edges: all edges apply to all group members
                    for edge in assignment_edges:
                        for instr in sorted(group_members):
                            sources.append((edge.source, instr, edge.data.get('enable')))
            else:
                # No group_members - extract instruction from node ID prefix
                if node_id.endswith('_' + wr_node_id):
                    prefix = node_id[:-len(wr_node_id)-1]
                    for edge in assignment_edges:
                        sources.append((edge.source, prefix, edge.data.get('enable')))

    return sources


def extract_all_cases_for_target(graph: ResourceGraph,
                                  wr_node_id: str,
                                  instruction_enables: Dict[str, str]) -> List[MuxCase]:
    """Extract all mux cases that ultimately assign to a target node.

    This recursively analyzes muxes and ternaries to extract all leaf cases.

    Args:
        graph: The resource graph
        wr_node_id: Target write node ID
        instruction_enables: Map of instruction name -> enable node ID

    Returns:
        List of all MuxCase that could assign to the target
    """
    sources = find_isa_state_mux_sources(graph, wr_node_id)
    all_cases = []

    for source_node, instr_name, enable_expr in sources:
        node_type = source_node.data.get('type', '')
        enable_id = instruction_enables.get(instr_name)

        # Build the effective enable condition: instruction_enable AND write_enable (from 'when' clause)
        if enable_id and enable_expr:
            effective_enable = f"{enable_id} && {enable_expr}"
        elif enable_id:
            effective_enable = enable_id
        elif enable_expr:
            effective_enable = enable_expr
        else:
            effective_enable = None

        if node_type == 'ternary_op':
            # Analyze ternary and extract its cases
            analysis = analyze_ternary(graph, source_node, instr_name)

            # Modify cases to include instruction enable in condition
            for case in analysis.cases:
                if effective_enable and not case.is_default:
                    # For true branch: enable && condition
                    case.condition_node_id = f"{effective_enable} && {case.condition_node_id}"
                elif effective_enable and case.is_default:
                    # For false branch: enable && !condition
                    case.condition_node_id = f"{effective_enable} && !{case.condition_node_id.replace('!', '')}"
                    case.is_default = False  # Now it's a regular case with explicit condition
                all_cases.append(case)

        elif node_type == 'multiplexer':
            # Analyze mux and extract its cases
            analysis = analyze_mux(graph, source_node, instr_name)

            for case in analysis.cases:
                if effective_enable and not case.is_default:
                    case.condition_node_id = f"{effective_enable} && {case.condition_node_id}"
                all_cases.append(case)

        else:
            # Direct assignment (not a mux/ternary)
            case = MuxCase(
                value_node_id=source_node.id,
                condition_node_id=effective_enable,
                condition_inverted=False,
                source_instruction=instr_name,
                is_default=False if effective_enable else True,
                original_mux_id=None
            )
            all_cases.append(case)

    return all_cases


def print_mux_analysis(analysis: MuxAnalysis) -> None:
    """Pretty print a mux analysis for debugging."""
    print(f"MuxAnalysis for {analysis.mux_node_id} ({analysis.mux_type}):")
    print(f"  Source instruction: {analysis.source_instruction}")
    print(f"  Target: {analysis.target_node_id}")
    print(f"  Cases ({len(analysis.cases)}):")
    for i, case in enumerate(analysis.cases):
        default_str = " [DEFAULT]" if case.is_default else ""
        inv_str = " (inverted)" if case.condition_inverted else ""
        print(f"    {i}: value={case.value_node_id}, cond={case.condition_node_id}{inv_str}{default_str}")
