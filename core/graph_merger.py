"""
ResourceGraph merging for multiple instructions.

This module implements algorithms to merge ResourceGraphs from multiple
instructions, creating unified graphs with instruction decode logic.
"""

from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum
import copy
import re
from .resource_graph import ResourceGraph, Node, Edge
from .isa_parser import ISAParser
from .mux_utils import MuxBuilder, MuxType
from .mux_case_analyzer import (
    MuxCase, MuxAnalysis, ValueGroup,
    analyze_ternary, analyze_mux, group_cases_by_value,
    find_isa_state_mux_sources, get_node_structure_key
)
from .graph_optimizer import GraphOptimizer
from .graph_utils import deep_copy_graph
from .timing_utils import reinfer_timing, set_node_timing
from .instruction_decode_utils import InstructionDecodeBuilder
from opt.mux_deduplication import deduplicate_all_arch_state_muxes
from .instruction_length_analyzer import analyze_instruction_length, remove_intermediate_pc_writes


# ==============================================================================
# New Plan-Then-Execute Architecture Data Structures
# ==============================================================================

class SharingType(Enum):
    """Semantic classification of nodes in the merged graph."""
    ARCHITECTURAL_STATE = "architectural"  # Never duplicated (pc, rf, imem, dmem)
    FULLY_SHARED = "fully_shared"          # All instructions, unprefixed
    GROUPWISE_SHARED = "groupwise"         # Subset, may be prefixed
    INSTRUCTION_SPECIFIC = "specific"       # One instruction or collision


@dataclass
class GroupInfo:
    """Information about a groupwise sharing group."""
    group_id: str                          # e.g., "beq_imm" (prefixed) or "r1" (unprefixed)
    original_id: str                       # e.g., "imm" or "r1"
    member_instructions: Set[str]          # e.g., {'beq', 'bne', 'blt', 'bge', 'bltu', 'bgeu'}
    assignment_signature: str              # e.g., "{instr[31], instr[7], ...}"
    needs_prefix: bool                     # True if multiple assignment groups exist
    prefix_instruction: Optional[str]      # First alphabetically if prefixed


@dataclass
class NodeBuildPlan:
    """Complete specification for building one node in merged graph."""

    # Identity
    node_id: str                           # ID in merged graph (may be prefixed)
    original_id: str                       # ID in source instruction
    source_instruction: str                # Which instruction to copy from

    # Semantic classification
    sharing_type: SharingType              # Which tier
    group_info: Optional[GroupInfo] = None # If groupwise, which group

    # Dependency tracking
    dependencies: Set[str] = field(default_factory=set)  # Node IDs that must exist first
    dependency_tier_levels: Dict[str, SharingType] = field(default_factory=dict)  # Tier of each dependency

    # Special properties
    is_collision_dependent: bool = False   # Marked due to transitive collision
    needs_arch_state_split: bool = False   # Should be split to _rd/_wr

    # Metadata
    metadata: Dict = field(default_factory=dict)  # Additional node properties


@dataclass
class EdgeBuildPlan:
    """Specification for one edge."""
    source_id: str                         # Source node ID in merged graph
    target_id: str                         # Target node ID in merged graph
    edge_data: Dict = field(default_factory=dict)  # Edge metadata
    requires_remapping: bool = False       # True if group-specific remapping needed


@dataclass
class MuxInputPlan:
    """Specification for one input to a multiplexer."""
    source_id: str                         # Node ID providing the value
    select_condition: str                  # Verilog condition expression (e.g., "beq_enable && beq_res")
    source_instructions: List[str] = field(default_factory=list)  # Instructions using this input
    is_default: bool = False               # True if this is the default/fallback input


@dataclass
class MuxBuildPlan:
    """Specification for building a multiplexer node during plan execution.

    This replaces multiple instruction-specific assignments to a shared target
    with a single multiplexer that selects based on instruction enable signals
    and conditions.
    """
    mux_id: str                            # ID for the mux node (e.g., "pc_wr_merged_mux")
    target_id: str                         # Shared target being assigned (e.g., "pc_wr")
    inputs: List[MuxInputPlan] = field(default_factory=list)  # Non-default inputs
    default_input: Optional[MuxInputPlan] = None  # Default value when no select is active
    replaced_nodes: Set[str] = field(default_factory=set)  # Node IDs removed from tier 4

    # Metadata for tracking
    source_assignments: List[Tuple[str, str]] = field(default_factory=list)  # [(instr, node_id), ...]


# ==============================================================================
# Group Tracking Infrastructure (New Architecture)
# ==============================================================================

@dataclass
class StructuralGroup:
    """A group of instructions that share the same structural form of a node."""
    group_id: str              # Identifier (first instruction alphabetically, or "shared")
    instructions: Set[str]     # Instructions in this group
    structure_key: str         # Hash of the structural form
    is_collision: bool = False # True if this is one of multiple groups for same node_id


@dataclass
class NodeClassification:
    """Complete classification of one node_id across all instructions."""
    node_id: str                                    # Original node ID
    groups: List[StructuralGroup]                   # All structural groups for this node
    merged_ids: Dict[str, str] = field(default_factory=dict)  # group_id -> merged_node_id
    tier: Optional[SharingType] = None              # Assigned tier (set during tier assignment)
    is_architectural: bool = False                  # True for pc, rf, imem, dmem

    def get_merged_id(self, group_id: str) -> str:
        """Get the merged node ID for a group."""
        return self.merged_ids.get(group_id, self.node_id)

    def get_group_for_instruction(self, instr: str) -> Optional[StructuralGroup]:
        """Find which group an instruction belongs to."""
        for group in self.groups:
            if instr in group.instructions:
                return group
        return None

    def is_collision(self) -> bool:
        """True if this node has multiple structural groups (collision)."""
        return len(self.groups) > 1


class GroupTracker:
    """Central registry for group assignments and node remapping.

    This is the single source of truth for how nodes are classified into groups
    and how instruction-specific node references map to merged graph node IDs.
    """

    def __init__(self, instruction_names: List[str]):
        self.instruction_names = instruction_names
        self.num_instructions = len(instruction_names)

        # node_id -> NodeClassification
        self.classifications: Dict[str, NodeClassification] = {}

        # instruction -> node_id -> merged_node_id (computed from classifications)
        self._remapping_cache: Dict[str, Dict[str, str]] = {}
        self._cache_valid = False

    def add_classification(self, classification: NodeClassification) -> None:
        """Add a node classification and invalidate cache."""
        self.classifications[classification.node_id] = classification
        self._cache_valid = False

    def get_classification(self, node_id: str) -> Optional[NodeClassification]:
        """Get classification for a node."""
        return self.classifications.get(node_id)

    def get_merged_id(self, instr: str, node_id: str) -> str:
        """Get the merged graph node ID for an instruction's use of a node.

        This is the primary method for all node ID lookups in the new architecture.
        """
        if not self._cache_valid:
            self._rebuild_remapping_cache()

        return self._remapping_cache.get(instr, {}).get(node_id, node_id)

    def _rebuild_remapping_cache(self) -> None:
        """Rebuild the remapping cache from classifications."""
        self._remapping_cache = {instr: {} for instr in self.instruction_names}

        for node_id, classification in self.classifications.items():
            for group in classification.groups:
                merged_id = classification.merged_ids.get(group.group_id, node_id)
                for instr in group.instructions:
                    self._remapping_cache[instr][node_id] = merged_id

        self._cache_valid = True

    def get_all_merged_ids(self) -> Set[str]:
        """Get all unique merged node IDs across all classifications."""
        merged_ids = set()
        for classification in self.classifications.values():
            merged_ids.update(classification.merged_ids.values())
        return merged_ids

    def get_groups_for_tier(self, tier: SharingType) -> List[Tuple[str, StructuralGroup]]:
        """Get all (node_id, group) pairs assigned to a tier."""
        result = []
        for node_id, classification in self.classifications.items():
            if classification.tier == tier:
                for group in classification.groups:
                    result.append((node_id, group))
        return result

    def get_collision_nodes(self) -> List[str]:
        """Get node IDs that have structural collisions."""
        return [
            node_id for node_id, classification in self.classifications.items()
            if classification.is_collision()
        ]

    def debug_print(self, node_id: str = None) -> None:
        """Print debug info for classifications."""
        nodes = [node_id] if node_id else list(self.classifications.keys())
        for nid in nodes:
            if nid not in self.classifications:
                print(f"  {nid}: NOT CLASSIFIED")
                continue
            c = self.classifications[nid]
            print(f"  {nid}: {len(c.groups)} group(s), tier={c.tier}")
            for g in c.groups:
                merged = c.merged_ids.get(g.group_id, nid)
                print(f"    - {g.group_id}: {len(g.instructions)} instrs -> {merged}")


class GraphBuildPlan:
    """Complete plan for building merged graph with semantic awareness."""

    def __init__(self):
        # Nodes organized by tier for dependency ordering
        self.architectural_nodes: List[NodeBuildPlan] = []
        self.fully_shared_nodes: List[NodeBuildPlan] = []
        self.groupwise_shared_nodes: List[NodeBuildPlan] = []
        self.instruction_specific_nodes: List[NodeBuildPlan] = []

        # Group tracking
        self.sharing_groups: Dict[str, GroupInfo] = {}  # group_id → group info

        # Edges
        self.edges: List[EdgeBuildPlan] = []

        # Mux plans (Phase 4.5: merged muxes for shared targets)
        self.mux_plans: List[MuxBuildPlan] = []

        # Validation state
        self.validated: bool = False

    def get_all_nodes_ordered(self) -> List[NodeBuildPlan]:
        """Return nodes in dependency-safe order (tier 1 → 4)."""
        return (
            self.architectural_nodes +
            self.fully_shared_nodes +
            self.groupwise_shared_nodes +
            self.instruction_specific_nodes
        )

    def validate(self) -> None:
        """Validate plan correctness and dependency ordering."""
        # Implementation provided later in the file
        pass


# ==============================================================================
# Legacy Data Structures (to be deprecated)
# ==============================================================================

class InstructionDecodeInfo:
    """Information about instruction decode conditions."""

    def __init__(self, instruction_name: str):
        self.instruction_name = instruction_name
        self.assume_conditions: List[Tuple[str, str, str]] = []  # (field, op, value) - AND'd
        self.assume_or_groups: List[List[Tuple[str, str, str]]] = []  # groups of OR'd conditions
        self.decode_signal_node: Optional[str] = None  # Node ID of final decode signal (for ILA)

    def add_assume_condition(self, field_expr: str, operator: str, value: str):
        """Add an assume condition for instruction decode (AND'd with others)."""
        self.assume_conditions.append((field_expr, operator, value))

    def add_assume_or_group(self, conditions: list):
        """Add a group of conditions that should be OR'd together."""
        self.assume_or_groups.append(conditions)

    def __str__(self):
        parts = [f"{field} {op} {val}" for field, op, val in self.assume_conditions]
        for group in self.assume_or_groups:
            or_str = " || ".join(f"{f} {o} {v}" for f, o, v in group)
            parts.append(f"({or_str})")
        return f"{self.instruction_name}: {' && '.join(parts)}"


class ResourceGraphMerger:
    """Merges multiple ResourceGraphs with instruction decode logic."""

    def __init__(self, defines: dict = None):
        self.graphs: Dict[str, ResourceGraph] = {}
        self.decode_info: Dict[str, InstructionDecodeInfo] = {}
        self.instruction_nodes: Dict[str, str] = {}  # instruction_name -> instruction_node_id
        self.memory_constraints: Dict[str, int] = {}  # memory_name -> max_bit_width
        self.partially_shared_nodes: Dict[str, Set[str]] = {}  # node_id -> set of instruction names using it
        self.defines = defines or {}  # Preprocessor defines for ISA files
        self.pc_name = None  # PC register name for variable-length ISA support

    def add_instruction(self, name: str, file_path: str) -> bool:
        """Add an instruction from ISA, ILA JSON, or ResourceGraph file."""
        try:
            # Parse the file based on extension
            is_ila = False
            if file_path.endswith('.json'):
                # ILA JSON file
                graph = ResourceGraph.from_ila_json_file(file_path)
                is_ila = True
            elif file_path.endswith('.rgraph'):
                # Already-parsed ResourceGraph file
                graph = ResourceGraph.load_from_file(file_path)
                # Check if it's from ILA (has x0-x31 registers or 'pico' in path)
                is_ila = 'pico' in file_path or any(
                    n.data.get('name', '').startswith('x') and n.data.get('type') == 'isa_state'
                    for n in graph.nodes.values()
                )
            else:
                # ISA file
                graph = ResourceGraph.from_isa_file(file_path, defines=self.defines)

                # Skip empty graphs (preprocessor excluded all content via #ifdef)
                if len(graph.nodes) == 0:
                    print(f"Skipped instruction: {name} (empty after preprocessing)")
                    return True  # Return True so it's not treated as an error

            # Apply ILA transformations if needed
            if is_ila:
                from frontends.ila.ila_transformations import apply_ila_transformations
                apply_ila_transformations(graph, include_regfile=True)

            reinfer_timing(graph)

            # Find the instruction node (different for ISA vs ILA)
            instr_node_id = self._find_instruction_node(graph, file_path)

            # Extract decode information (pass graph and instruction node for ILA decode extraction)
            decode_info = self._extract_decode_info(name, file_path, graph, instr_node_id)

            self.graphs[name] = graph
            self.decode_info[name] = decode_info
            self.instruction_nodes[name] = instr_node_id

            print(f"Added instruction: {decode_info}")
            return True

        except Exception as e:
            print(f"Error adding instruction {name}: {e}")
            return False

    def _find_instruction_node(self, graph: ResourceGraph, file_path: str) -> str:
        """
        Find which node represents the instruction word in this graph.

        ISA graphs: Have an explicit 'instr' input node
        ILA graphs: The instruction is fetched as imem[pc] (array_access node)

        Returns:
            Node ID of the instruction node
        """
        # Check for ISA-style 'instr' node
        if 'instr' in graph.nodes:
            return 'instr'

        # For ILA graphs, find the imem[pc] or mem[pc] access
        # Pattern: array_access with imem/mem as base
        # ILA parser creates 'mem' node, some specs may use 'imem'
        mem_node = None
        for node in graph.nodes.values():
            if node.data.get('type') == 'isa_state' and node.data.get('name') in ['imem', 'mem']:
                mem_node = node
                break

        if mem_node:
            # Find array_access that reads from imem/mem (or mem_rd after splitting)
            for node_id, node in graph.nodes.items():
                if node.data.get('type') == 'array_access':
                    # Check if this accesses imem/mem or their split _rd variants
                    for edge in node.incoming_edges:
                        source = edge.source
                        # Check direct access or split state (_rd suffix)
                        if source == mem_node or (source.data.get('name') in ['imem', 'mem'] and source.id.endswith('_rd')):
                            # This is the instruction fetch
                            return node_id

        # Fallback - return empty string if not found
        # (decode logic creation will be skipped)
        return ''

    def _extract_decode_info(self, name: str, file_path: str, graph: ResourceGraph, instr_node_id: str) -> InstructionDecodeInfo:
        """Extract decode conditions from ISA or ILA file."""
        decode_info = InstructionDecodeInfo(name)

        if file_path.endswith('.rgraph'):
            # ILA resource graph file - extract decode by scanning for comparison nodes
            # Look for comparisons checking opcode/funct3/funct7 fields
            decode_comparisons = {}  # {(high, low): (node_id, value)}

            for node_id, node in graph.nodes.items():
                if node.data.get('operator') == '==':
                    # Check if this is a bit_slice == literal comparison
                    incoming = list(node.incoming_edges)
                    if len(incoming) == 2:
                        left = incoming[0].source
                        right = incoming[1].source

                        # Handle both orders: bit_slice == literal or literal == bit_slice
                        bitslice_node = None
                        literal_node = None
                        if left.data.get('type') == 'bit_slice' and right.data.get('type') == 'literal':
                            bitslice_node = left
                            literal_node = right
                        elif right.data.get('type') == 'bit_slice' and left.data.get('type') == 'literal':
                            bitslice_node = right
                            literal_node = left

                        if bitslice_node and literal_node:
                            bitslice = bitslice_node.data.get('bitslice')
                            value = literal_node.data.get('value')

                            if bitslice and value is not None:
                                # Check if this is one of the key decode fields
                                high, low = bitslice
                                if (high, low) in [(6, 0), (14, 12), (31, 25)]:
                                    # This is a decode comparison
                                    decode_comparisons[(high, low)] = (node_id, value)

                                    # Add to decode_info
                                    instr_ref = instr_node_id if instr_node_id else 'instr'
                                    left_expr = f"{instr_ref}[{high}:{low}]"
                                    decode_info.add_assume_condition(left_expr, '==', hex(value))

            # Find the decode signal node (should be the final AND combining all comparisons)
            # Store it for later use in creating decode_enable edges
            if decode_comparisons:
                # Find the final AND node that combines all decode comparisons
                # Strategy: find AND nodes fed by comparisons, then follow chain to instruction node
                decode_comparison_ids = {node_id for node_id, value in decode_comparisons.values()}

                # Build a set of all nodes in the decode chain
                decode_chain = set(decode_comparison_ids)
                changed = True
                while changed:
                    changed = False
                    for node_id, node in graph.nodes.items():
                        if node_id not in decode_chain and node.data.get('operator') == '&':
                            # Check if fed by decode chain
                            if any(e.source.id in decode_chain for e in node.incoming_edges):
                                decode_chain.add(node_id)
                                changed = True

                # Find the final node that feeds an instruction node
                for node_id in decode_chain:
                    node = graph.nodes[node_id]
                    for edge in node.outgoing_edges:
                        if edge.target.data.get('type') == 'instruction':
                            # This is the final decode signal
                            decode_info.decode_signal_node = node_id
                            break
                    if decode_info.decode_signal_node:
                        break

        elif file_path.endswith('.json'):
            # ILA JSON file - extract decode info from graph by following decode_condition edges
            # Find instruction nodes in the graph
            for node in graph.nodes.values():
                if node.data.get('type') == 'instruction':
                    # Find decode_condition edge
                    for edge in node.incoming_edges:
                        if edge.data.get('type') == 'decode_condition':
                            # Found decode node - extract conditions from it
                            decode_node = edge.source
                            self._extract_decode_conditions_from_node(decode_node, decode_info, graph, instr_node_id)
                            break
                    break
        else:
            # ISA file - read assume expressions from the parsed graph
            for assume_expr in getattr(graph, 'assume_expressions', []):
                self._extract_assume_conditions(assume_expr, decode_info)

        return decode_info

    def _extract_assume_conditions(self, expr: dict, decode_info):
        """Recursively extract == / != conditions from an assume expression.

        Handles simple conditions (instr == 0xA9) and OR-chained conditions
        (instr == 0xA9 | instr == 0xA5 | ...) used by orthogon instructions.
        """
        if expr.get('type') != 'binary_op':
            return
        op = expr.get('operator', '')
        if op in ('==', '!='):
            left_str = self._assume_expr_to_string(expr.get('left', {}))
            right_str = self._assume_expr_to_string(expr.get('right', {}))
            decode_info.add_assume_condition(left_str, op, right_str)
        elif op in ('|', '||'):
            # OR-chained conditions: collect all leaf conditions and add as an OR group
            or_conditions = []
            self._collect_or_conditions(expr, or_conditions)
            if or_conditions:
                decode_info.add_assume_or_group(or_conditions)
        elif op in ('&', '&&'):
            # AND-chained: recurse into both sides (each becomes its own condition)
            self._extract_assume_conditions(expr.get('left', {}), decode_info)
            self._extract_assume_conditions(expr.get('right', {}), decode_info)

    def _collect_or_conditions(self, expr: dict, conditions: list):
        """Collect all == / != leaf conditions from an OR tree."""
        if expr.get('type') != 'binary_op':
            return
        op = expr.get('operator', '')
        if op in ('==', '!='):
            left_str = self._assume_expr_to_string(expr.get('left', {}))
            right_str = self._assume_expr_to_string(expr.get('right', {}))
            conditions.append((left_str, op, right_str))
        elif op in ('|', '||'):
            self._collect_or_conditions(expr.get('left', {}), conditions)
            self._collect_or_conditions(expr.get('right', {}), conditions)

    @staticmethod
    def _assume_expr_to_string(expr: dict) -> str:
        """Convert a parsed assume AST expression back to a string for decode info.

        Handles the typical patterns found in assume statements:
          identifier, bit_slice, array_access, literal, sized_literal, binary_wildcard
        """
        if not expr:
            return ''
        t = expr.get('type', '')
        if t == 'identifier':
            return expr.get('name', '')
        elif t == 'literal':
            return str(expr.get('value', 0))
        elif t == 'sized_literal':
            fmt = expr.get('format', 'bin')
            w = expr.get('width', 0)
            digits = expr.get('original_digits', str(expr.get('value', 0)))
            fmt_char = {'bin': 'b', 'hex': 'h', 'dec': 'd'}.get(fmt, 'b')
            return f"{w}'{fmt_char}{digits}"
        elif t == 'binary_wildcard':
            return expr.get('original', '')
        elif t == 'bit_slice':
            target = ResourceGraphMerger._assume_expr_to_string(expr.get('target', {}))
            high, low = expr.get('range', (0, 0))
            return f"{target}[{high}:{low}]"
        elif t == 'array_access':
            target = ResourceGraphMerger._assume_expr_to_string(expr.get('target', {}))
            index = ResourceGraphMerger._assume_expr_to_string(expr.get('index', {}))
            return f"{target}[{index}]"
        elif t == 'binary_op':
            left = ResourceGraphMerger._assume_expr_to_string(expr.get('left', {}))
            right = ResourceGraphMerger._assume_expr_to_string(expr.get('right', {}))
            return f"({left} {expr.get('operator', '')} {right})"
        else:
            return str(expr.get('value', expr))

    def _extract_decode_conditions_from_node(self, node: 'Node', decode_info: InstructionDecodeInfo, graph: ResourceGraph, instr_node_id: str):
        """Recursively extract decode conditions from ILA decode node tree."""
        node_type = node.data.get('type')
        operator = node.data.get('operator')

        if node_type == 'operation' and operator == '==':
            # This is a comparison - extract the condition
            # Get operands (should be 2)
            operands = sorted(node.incoming_edges, key=lambda e: e.data.get('position', 0))
            if len(operands) == 2:
                left_node = operands[0].source
                right_node = operands[1].source

                # Check if this is "bitslice == constant"
                if left_node.data.get('type') == 'bit_slice' and right_node.data.get('type') == 'literal':
                    bitslice = left_node.data.get('bitslice')
                    value = right_node.data.get('value')

                    if bitslice and value is not None:
                        high, low = bitslice
                        # Use the actual instruction node ID (e.g. 'instr' for ISA, 'op_17' for ILA)
                        # For ISA compatibility, use 'instr' if no specific ID provided
                        instr_ref = instr_node_id if instr_node_id else 'instr'
                        left_expr = f"{instr_ref}[{high}:{low}]"
                        decode_info.add_assume_condition(left_expr, '==', str(value))

        elif node_type == 'operation' and operator == '&':
            # This is an AND - recurse into both operands
            for edge in node.incoming_edges:
                self._extract_decode_conditions_from_node(edge.source, decode_info, graph, instr_node_id)

    # ==========================================================================
    # New Group-Aware Classification Pipeline
    # ==========================================================================

    def _classify_with_groups(self) -> GroupTracker:
        """
        Classify all nodes using group-aware logic.

        This is the new comprehensive classification that replaces _analyze_node_sharing.
        It properly handles collisions by creating group-specific nodes, and propagates
        group structure to dependent nodes.

        Returns a GroupTracker with complete classification for all nodes.
        """
        instruction_names = list(self.graphs.keys())
        tracker = GroupTracker(instruction_names)

        print("Phase 1: Structural Analysis...")
        structural_groups = self._build_structural_groups()

        print("Phase 2: Node Classification...")
        self._classify_nodes_into_groups(tracker, structural_groups)

        print("Phase 3: Group Propagation...")
        self._propagate_groups_to_dependents(tracker)

        print("Phase 4: Tier Assignment...")
        self._assign_tiers(tracker)

        # Debug output
        collisions = tracker.get_collision_nodes()
        print(f"\nClassification Summary (GroupTracker):")
        print(f"  Total nodes classified: {len(tracker.classifications)}")
        print(f"  Collision nodes: {len(collisions)}")
        if collisions:
            print(f"  Collision examples: {collisions[:5]}")

        return tracker

    def _build_structural_groups(self) -> Dict[Tuple[any, str], List[Tuple[str, str, 'Node']]]:
        """
        Phase 1: Build structural groups.

        Groups nodes by (structure_key, node_id) to identify which instructions
        share the same structural form of each node.

        Returns: Dict[(struct_key, node_id)] -> List[(instr_name, node_id, node)]
        """
        # First pass: collect all (struct_key, node_id, instr, node) tuples
        raw_groups = {}  # struct_key -> List[(instr, node_id, node)]

        for instr_name, graph in self.graphs.items():
            for node_id, node in graph.nodes.items():
                struct_key = self._compute_node_structure_key(node, graph)
                if struct_key not in raw_groups:
                    raw_groups[struct_key] = []
                raw_groups[struct_key].append((instr_name, node_id, node))

        # Second pass: split by node_id to create (struct_key, node_id) groups
        structural_groups = {}
        for struct_key, instances in raw_groups.items():
            by_node_id = {}
            for instr_name, node_id, node in instances:
                if node_id not in by_node_id:
                    by_node_id[node_id] = []
                by_node_id[node_id].append((instr_name, node_id, node))

            for node_id, node_instances in by_node_id.items():
                combined_key = (struct_key, node_id)
                structural_groups[combined_key] = node_instances

        return structural_groups

    def _is_pc_related_operation(self, node_id: str, nodes: List['Node'], node_usage: Dict[str, Set[str]]) -> bool:
        """
        Check if a node is a PC-related operation that should be shared.

        For variable-length ISAs, operations involving only PC, literals, and other
        PC-related operations should be shared for deduplication.

        Returns True if the node should be force-shared as a PC-related operation.
        """
        if not self.pc_name or not nodes:
            return False

        # Only consider operations
        first_node = nodes[0]
        node_type = first_node.data.get('type')
        if node_type != 'operation':
            return False

        pc_rd = f"{self.pc_name}_rd"

        # Check if all operands are PC-related, literals, or already shared
        for node in nodes:
            for edge in node.incoming_edges:
                if edge.data.get('type') not in ['operand', 'left_operand', 'right_operand']:
                    continue

                operand_id = edge.source.id
                operand_node = edge.source

                # Check if operand is PC, a literal, or another PC-related node
                is_pc_related = (operand_id == pc_rd or
                                pc_rd in operand_id or
                                self.pc_name in operand_id)

                # Check if it's a literal
                operand_type = operand_node.data.get('type', '')
                is_literal = operand_type in ['literal', 'sized_literal']

                if not (is_pc_related or is_literal):
                    return False

        return True

    def _classify_nodes_into_groups(
        self,
        tracker: GroupTracker,
        structural_groups: Dict[Tuple[any, str], List[Tuple[str, str, 'Node']]]
    ) -> None:
        """
        Phase 2: Classify each node into groups.

        For each unique node_id, examine all structural groups that contain it.
        If multiple structures exist (collision), create separate StructuralGroups.
        """
        instruction_names = list(self.graphs.keys())
        num_instructions = len(instruction_names)

        # Build node_usage for later checks
        node_usage = {}
        for instr_name, graph in self.graphs.items():
            for node_id in graph.nodes:
                if node_id not in node_usage:
                    node_usage[node_id] = set()
                node_usage[node_id].add(instr_name)

        # Group structural_groups by node_id to detect collisions
        node_id_to_groups = {}  # node_id -> List[(struct_key, instrs, nodes)]
        for (struct_key, node_id), instances in structural_groups.items():
            if node_id not in node_id_to_groups:
                node_id_to_groups[node_id] = []
            instrs = set(i[0] for i in instances)
            nodes = [i[2] for i in instances]
            node_id_to_groups[node_id].append((struct_key, instrs, nodes))

        # Classify each node_id
        for node_id, groups in node_id_to_groups.items():
            # Check if this is architectural state
            is_arch = False
            for instr_name in instruction_names:
                if node_id in self.graphs[instr_name].nodes:
                    is_arch = self.graphs[instr_name].nodes[node_id].is_arch_state
                    break

            classification = NodeClassification(
                node_id=node_id,
                groups=[],
                merged_ids={},
                is_architectural=is_arch
            )

            is_collision = len(groups) > 1

            for struct_key, instrs, nodes in groups:
                # Determine group_id
                # SPECIAL HANDLING for variable-length ISAs:
                # PC-related operations should be shared even if not all instructions have them
                # This allows pc+1, pc+2, etc. to be deduplicated across instructions
                force_shared = False
                if len(groups) == 1 and self.pc_name:
                    force_shared = self._is_pc_related_operation(node_id, nodes, node_usage)
                    if force_shared:
                        print(f"  PC-related operation: {node_id} forced to shared")

                if len(groups) == 1 and (len(instrs) == num_instructions or force_shared):
                    # Fully shared - use "shared" as group_id
                    group_id = "shared"
                    merged_id = node_id
                elif len(groups) == 1:
                    # Partially shared, no collision - use first instruction as group_id
                    group_id = sorted(instrs)[0]
                    merged_id = node_id  # No prefix needed, no collision
                else:
                    # Collision - each group gets its own merged_id
                    group_id = sorted(instrs)[0]
                    merged_id = f"{group_id}_{node_id}"

                group = StructuralGroup(
                    group_id=group_id,
                    instructions=instrs,
                    structure_key=str(struct_key),
                    is_collision=is_collision
                )
                classification.groups.append(group)
                classification.merged_ids[group_id] = merged_id

                if is_collision:
                    print(f"  Collision: {node_id} in {sorted(instrs)} -> {merged_id}")

            tracker.add_classification(classification)

    def _propagate_groups_to_dependents(self, tracker: GroupTracker) -> None:
        """
        Phase 3: Propagate group structure to dependent nodes.

        When a node depends on a collision node, it inherits the group structure.
        For example, if `imm` has groups {i_type, b_type, s_type}, then
        `sign_ext_imm` (which depends on `imm`) must also be split by those groups.
        """
        instruction_names = list(self.graphs.keys())

        # Find all collision nodes
        collision_nodes = tracker.get_collision_nodes()
        if not collision_nodes:
            print("  No collisions to propagate")
            return

        print(f"  Propagating from {len(collision_nodes)} collision nodes...")

        # Build dependency graph: for each (instruction, node_id), what does it depend on?
        # This is PER-INSTRUCTION to properly track which instructions actually have each dependency
        # Only consider data dependency edges (not metadata or control edges)
        DATA_DEPENDENCY_EDGE_TYPES = {
            'assignment', 'operand', 'concat_element', 'concatenation_input',
            'ternary_condition', 'ternary_true', 'ternary_false',
            'mux_input', 'mux_default_input', 'mux_select', 'repetition_value', 'repetition_input',
            'left_operand', 'right_operand', 'bit_slice_source', 'bit_access'
        }

        instr_node_deps = {}  # instr -> {node_id -> Set[dep_node_id]}
        for instr_name, graph in self.graphs.items():
            instr_node_deps[instr_name] = {}
            for node_id, node in graph.nodes.items():
                if node_id not in instr_node_deps[instr_name]:
                    instr_node_deps[instr_name][node_id] = set()
                for edge in node.incoming_edges:
                    # Only consider edges that represent data dependencies
                    edge_type = edge.data.get('type') if edge.data else None
                    if edge_type in DATA_DEPENDENCY_EDGE_TYPES:
                        instr_node_deps[instr_name][node_id].add(edge.source.id)

        # Iteratively propagate until no changes
        changed = True
        iteration = 0
        while changed:
            changed = False
            iteration += 1

            for node_id, classification in sorted(tracker.classifications.items()):
                # Skip orthogon-derived nodes from collision propagation.
                # They should remain shared even when their inputs (like addr_sel)
                # are collisions.  A later step (_mux_shared_orthogon_inputs)
                # creates muxes for collision inputs to shared orthogon nodes.
                is_orthogon_node = False
                for instr_name, graph in self.graphs.items():
                    if node_id in graph.nodes:
                        if graph.nodes[node_id].data.get('from_orthogon'):
                            is_orthogon_node = True
                        break
                if is_orthogon_node:
                    continue

                # Find which collision nodes this node depends on, PER INSTRUCTION
                # We need to check each instruction individually to see if it actually has the dependency
                instrs_with_collision_deps = {}  # collision_dep_id -> set of instructions that depend on it

                # Check all instructions that have this node
                all_instrs_with_node = set()
                for group in classification.groups:
                    all_instrs_with_node |= group.instructions

                for instr in sorted(all_instrs_with_node):
                    if instr not in instr_node_deps or node_id not in instr_node_deps[instr]:
                        continue
                    deps = instr_node_deps[instr][node_id]
                    for dep_id in sorted(deps):
                        if dep_id in collision_nodes:
                            if dep_id not in instrs_with_collision_deps:
                                instrs_with_collision_deps[dep_id] = set()
                            instrs_with_collision_deps[dep_id].add(instr)

                if not instrs_with_collision_deps:
                    continue

                # This node depends on collision nodes in SOME instructions - check if we need to split further
                for collision_dep_id, instrs_with_dep in sorted(instrs_with_collision_deps.items()):
                    collision_classification = tracker.get_classification(collision_dep_id)
                    if not collision_classification:
                        continue

                    # For each of our current groups, check if the collision dependency
                    # splits those instructions further
                    new_groups = []
                    new_merged_ids = {}
                    needs_split = False

                    for our_group in classification.groups:
                        our_instrs = our_group.instructions

                        # Split our_instrs into:
                        # 1. Instructions that depend on the collision node (need to be split by collision groups)
                        # 2. Instructions that DON'T depend on the collision node (keep together in original group)
                        instrs_with_dep_in_group = our_instrs & instrs_with_dep
                        instrs_without_dep_in_group = our_instrs - instrs_with_dep

                        # Check how the collision dependency splits the instructions that ACTUALLY depend on it
                        sub_groups = []
                        for collision_group in collision_classification.groups:
                            overlap = collision_group.instructions & instrs_with_dep_in_group
                            if overlap:
                                # CRITICAL FIX: Use the first instruction from the OVERLAP as the group_id,
                                # not the collision_group's group_id. This ensures the group_id reflects
                                # the actual instructions in the sub-group, not the collision's naming.
                                # For example, when LDA instructions overlap with an "adc_abs" collision,
                                # the sub-group should be named "lda_abs", not "adc_abs".
                                sub_group_id = sorted(overlap)[0]
                                sub_groups.append((sub_group_id, overlap))

                        # Instructions that don't depend on the collision node at all stay together
                        # (they don't get split by this collision)
                        if instrs_without_dep_in_group:
                            # These instructions don't use the collision variant - assign proper group_id
                            # Use first instruction alphabetically (not "shared" since they'll become a collision group)
                            group_id = sorted(instrs_without_dep_in_group)[0]
                            sub_groups.append((group_id, instrs_without_dep_in_group))

                        if len(sub_groups) > 1:
                            # This group needs to be split
                            needs_split = True
                            for sub_group_id, sub_instrs in sub_groups:
                                merged_id = f"{sorted(sub_instrs)[0]}_{node_id}"
                                new_group = StructuralGroup(
                                    group_id=sub_group_id,
                                    instructions=sub_instrs,
                                    structure_key=our_group.structure_key,
                                    is_collision=True
                                )
                                new_groups.append(new_group)
                                new_merged_ids[sub_group_id] = merged_id
                        else:
                            # Keep this group as-is
                            # But update merged_id if needed
                            group_id = our_group.group_id
                            if len(classification.groups) > 1 or classification.is_collision():
                                merged_id = classification.merged_ids.get(group_id, f"{sorted(our_instrs)[0]}_{node_id}")
                            else:
                                merged_id = node_id
                            new_groups.append(our_group)
                            new_merged_ids[group_id] = merged_id

                    if needs_split:
                        # Successfully split
                        classification.groups = new_groups
                        classification.merged_ids = new_merged_ids
                        changed = True
                        print(f"    Split {node_id} into {len(new_groups)} groups (depends on {collision_dep_id})")
                        if node_id not in collision_nodes:
                            collision_nodes.append(node_id)
                        break

        print(f"  Propagation complete after {iteration} iteration(s)")

    def _assign_tiers(self, tracker: GroupTracker) -> None:
        """
        Phase 4: Assign tiers to each classification.

        Tier 1: Architectural state (only if not split by collision propagation)
        Tier 2: Fully shared (single group with all instructions)
        Tier 3: Group-shared (groups with 2+ instructions)
        Tier 4: Instruction-specific (groups with 1 instruction)

        Important: Architectural nodes that were split due to depending on collision
        nodes must be demoted to a lower tier to maintain proper dependency ordering.
        """
        instruction_names = list(self.graphs.keys())
        num_instructions = len(instruction_names)

        tier_counts = {t: 0 for t in SharingType}

        for node_id, classification in tracker.classifications.items():
            if classification.is_architectural:
                # Check if this arch node was split (has multiple groups)
                # If split, it must be demoted based on its dependencies
                if len(classification.groups) == 1 and len(classification.groups[0].instructions) == num_instructions:
                    # Not split, all instructions use same structure - keep as architectural
                    classification.tier = SharingType.ARCHITECTURAL_STATE
                    tier_counts[SharingType.ARCHITECTURAL_STATE] += 1
                elif len(classification.groups) == 1:
                    # Single group but not all instructions (some don't use this arch state)
                    # Still keep as architectural since it's not split
                    classification.tier = SharingType.ARCHITECTURAL_STATE
                    tier_counts[SharingType.ARCHITECTURAL_STATE] += 1
                else:
                    # Split into multiple groups due to collision propagation
                    # Must demote to lower tier for proper dependency ordering
                    has_multi_instr_group = any(len(g.instructions) > 1 for g in classification.groups)
                    if has_multi_instr_group:
                        classification.tier = SharingType.GROUPWISE_SHARED
                        tier_counts[SharingType.GROUPWISE_SHARED] += 1
                    else:
                        classification.tier = SharingType.INSTRUCTION_SPECIFIC
                        tier_counts[SharingType.INSTRUCTION_SPECIFIC] += 1
            elif len(classification.groups) == 1:
                group = classification.groups[0]
                if len(group.instructions) == num_instructions:
                    classification.tier = SharingType.FULLY_SHARED
                    tier_counts[SharingType.FULLY_SHARED] += 1
                elif len(group.instructions) > 1:
                    classification.tier = SharingType.GROUPWISE_SHARED
                    tier_counts[SharingType.GROUPWISE_SHARED] += 1
                else:
                    classification.tier = SharingType.INSTRUCTION_SPECIFIC
                    tier_counts[SharingType.INSTRUCTION_SPECIFIC] += 1
            else:
                # Multiple groups - determine tier based on group sizes
                # If all groups have 1 instruction -> instruction-specific
                # If any group has 2+ -> groupwise (will create multiple group-specific nodes)
                has_multi_instr_group = any(len(g.instructions) > 1 for g in classification.groups)
                if has_multi_instr_group:
                    classification.tier = SharingType.GROUPWISE_SHARED
                    tier_counts[SharingType.GROUPWISE_SHARED] += 1
                else:
                    classification.tier = SharingType.INSTRUCTION_SPECIFIC
                    tier_counts[SharingType.INSTRUCTION_SPECIFIC] += 1

        # Second pass: Enforce tier hierarchy
        # A node must be in the same or later tier than all its dependencies
        tier_order = {
            SharingType.ARCHITECTURAL_STATE: 0,
            SharingType.FULLY_SHARED: 1,
            SharingType.GROUPWISE_SHARED: 2,
            SharingType.INSTRUCTION_SPECIFIC: 3
        }
        tier_by_rank = {v: k for k, v in tier_order.items()}

        # Build dependency map
        node_deps = {}
        for instr_name, graph in self.graphs.items():
            for node_id, node in graph.nodes.items():
                if node_id not in node_deps:
                    node_deps[node_id] = set()
                for edge in node.incoming_edges:
                    node_deps[node_id].add(edge.source.id)

        # Iteratively demote until stable
        changed = True
        demotions = 0
        while changed:
            changed = False
            for node_id, classification in tracker.classifications.items():
                current_tier = classification.tier
                current_rank = tier_order[current_tier]

                # Check all dependencies
                deps = node_deps.get(node_id, set())
                for dep_id in deps:
                    dep_classification = tracker.get_classification(dep_id)
                    if not dep_classification:
                        continue

                    dep_tier = dep_classification.tier
                    dep_rank = tier_order[dep_tier]

                    # If dependency is in a later tier, demote this node
                    if dep_rank > current_rank:
                        classification.tier = tier_by_rank[dep_rank]
                        tier_counts[current_tier] -= 1
                        tier_counts[classification.tier] += 1
                        changed = True
                        demotions += 1
                        break  # Re-check after demotion

        if demotions > 0:
            print(f"  Tier enforcement: demoted {demotions} node(s)")

        print(f"  Tier assignment:")
        for tier, count in tier_counts.items():
            print(f"    {tier.value}: {count}")

    def _generate_build_plan_from_tracker(self, tracker: GroupTracker) -> GraphBuildPlan:
        """
        Phase 5: Generate build plan from GroupTracker.

        Creates NodeBuildPlans for each node/group combination and EdgeBuildPlans
        using the tracker's remapping.
        """
        plan = GraphBuildPlan()
        instruction_names = list(self.graphs.keys())

        # Track which merged_ids we've already planned (avoid duplicates)
        planned_ids = set()

        # Generate node plans by tier
        print("  Generating node plans...")

        for node_id, classification in tracker.classifications.items():
            tier = classification.tier

            for group in classification.groups:
                merged_id = classification.merged_ids.get(group.group_id, node_id)

                # Skip if already planned
                if merged_id in planned_ids:
                    continue
                planned_ids.add(merged_id)

                # Find source instruction (first in group)
                source_instr = sorted(group.instructions)[0]

                # Build dependencies using tracker remapping
                deps = set()
                if node_id in self.graphs[source_instr].nodes:
                    source_node = self.graphs[source_instr].nodes[node_id]
                    for edge in source_node.incoming_edges:
                        dep_id = edge.source.id
                        # Use tracker to get merged dep ID for this instruction
                        merged_dep = tracker.get_merged_id(source_instr, dep_id)
                        deps.add(merged_dep)

                # Create GroupInfo if this is a group
                group_info = None
                if len(group.instructions) > 1 and group.group_id != "shared":
                    group_info = GroupInfo(
                        group_id=group.group_id,
                        original_id=node_id,
                        member_instructions=group.instructions,
                        assignment_signature=group.structure_key,
                        needs_prefix=(merged_id != node_id),
                        prefix_instruction=source_instr if merged_id != node_id else None
                    )

                node_plan = NodeBuildPlan(
                    node_id=merged_id,
                    original_id=node_id,
                    source_instruction=source_instr,
                    sharing_type=tier,
                    group_info=group_info,
                    dependencies=deps,
                    is_collision_dependent=classification.is_collision(),
                    metadata={'group_instructions': list(group.instructions)}
                )

                # Add to appropriate tier list
                if tier == SharingType.ARCHITECTURAL_STATE:
                    plan.architectural_nodes.append(node_plan)
                elif tier == SharingType.FULLY_SHARED:
                    plan.fully_shared_nodes.append(node_plan)
                elif tier == SharingType.GROUPWISE_SHARED:
                    plan.groupwise_shared_nodes.append(node_plan)
                else:  # INSTRUCTION_SPECIFIC
                    plan.instruction_specific_nodes.append(node_plan)

        # Topologically sort each tier
        plan.architectural_nodes = self._topological_sort_tier(plan.architectural_nodes)
        plan.fully_shared_nodes = self._topological_sort_tier(plan.fully_shared_nodes)
        plan.groupwise_shared_nodes = self._topological_sort_tier(plan.groupwise_shared_nodes)
        plan.instruction_specific_nodes = self._topological_sort_tier(plan.instruction_specific_nodes)

        # Generate edge plans
        print("  Generating edge plans...")
        plan.edges = self._generate_edge_plans_from_tracker(tracker, planned_ids)

        # Validate
        print("  Validating...")
        self._validate_build_plan_from_tracker(plan, tracker, planned_ids)

        return plan

    def _generate_edge_plans_from_tracker(
        self,
        tracker: GroupTracker,
        planned_ids: Set[str]
    ) -> List[EdgeBuildPlan]:
        """Generate edge plans using GroupTracker remapping."""
        edges = []
        seen_edges = set()  # (source, target) pairs we've already added

        for instr_name, graph in self.graphs.items():
            # Iterate through all nodes and their outgoing edges
            for node_id, node in graph.nodes.items():
                for edge in node.outgoing_edges:
                    source_id = edge.source.id
                    target_id = edge.target.id

                    # Get merged IDs using tracker
                    merged_source = tracker.get_merged_id(instr_name, source_id)
                    merged_target = tracker.get_merged_id(instr_name, target_id)

                    # Skip if either endpoint not in plan
                    if merged_source not in planned_ids or merged_target not in planned_ids:
                        continue

                    # Skip duplicates
                    # Include position in key for concatenation inputs (allows multiple edges
                    # from same source at different positions, e.g., two 1'b1 literals)
                    # For mux_input edges: use original_enable as discriminator instead of
                    # input_index, because different instructions in the same collision group
                    # may assign different indices to the same condition due to
                    # non-deterministic set iteration order. original_enable uniquely
                    # identifies which conditional write this input corresponds to.
                    # For mux_select edges: source + target + type is sufficient since each
                    # condition node is unique.
                    edge_type = edge.data.get('type') if edge.data else None
                    edge_position = edge.data.get('position') if edge.data else None
                    edge_original_enable = repr(edge.data.get('original_enable')) if edge.data and edge.data.get('original_enable') else None
                    edge_key = (merged_source, merged_target, edge_type, edge_position, edge_original_enable)
                    if edge_key in seen_edges:
                        continue
                    seen_edges.add(edge_key)

                    edge_plan = EdgeBuildPlan(
                        source_id=merged_source,
                        target_id=merged_target,
                        edge_data=copy.deepcopy(edge.data),
                        requires_remapping=(source_id != merged_source or target_id != merged_target)
                    )
                    edges.append(edge_plan)

        return edges

    def _validate_build_plan_from_tracker(
        self,
        plan: GraphBuildPlan,
        tracker: GroupTracker,
        planned_ids: Set[str]
    ) -> None:
        """Validate build plan for dependency ordering."""
        # Build set of node IDs in order they'll be added
        added_ids = set()
        errors = []

        for node_plan in plan.get_all_nodes_ordered():
            # Check all dependencies exist before this node
            for dep_id in node_plan.dependencies:
                if dep_id not in added_ids:
                    # Check if it's an architectural state node (allowed to be missing in deps)
                    dep_classification = tracker.get_classification(dep_id)
                    if dep_classification and dep_classification.tier == SharingType.ARCHITECTURAL_STATE:
                        continue  # Arch state has no deps
                    errors.append(f"{node_plan.node_id} depends on {dep_id} which is not yet added")

            added_ids.add(node_plan.node_id)

        if errors:
            print(f"  Validation FAILED with {len(errors)} errors:")
            for e in errors[:10]:
                print(f"    - {e}")
            raise ValueError(f"Build plan validation failed: {errors[0]}")

        plan.validated = True
        print(f"  ✓ Build plan validated ({len(planned_ids)} nodes, {len(plan.edges)} edges)")

    # ==========================================================================
    # End of Group-Aware Classification Pipeline
    # ==========================================================================

    def merge_graphs(self, pc_name: str = None) -> ResourceGraph:
        """Merge all instruction graphs into a unified graph.

        Args:
            pc_name: Name of PC register for variable-length ISA support.
                     When provided, PC-related operations (pc+1, pc+2, etc.)
                     are marked as shared for deduplication across instructions.
        """
        if not self.graphs:
            raise ValueError("No graphs to merge")

        # Store pc_name for use in classification phases
        self.pc_name = pc_name

        print(f"Merging {len(self.graphs)} instruction graphs...")

        # Feature flag to use legacy merger (new architecture is now default)
        import os
        use_legacy_architecture = os.environ.get('ISACOMP_LEGACY_MERGER', '0') == '1'

        if not use_legacy_architecture:
            print("Using NEW plan-then-execute architecture with GroupTracker")
            return self._merge_graphs_new_architecture()

        # === LEGACY ARCHITECTURE (deprecated, use ISACOMP_LEGACY_MERGER=1 to enable) ===
        print("Using LEGACY build-rework-cleanup architecture (deprecated)")

        # Start with first graph as base
        instruction_names = list(self.graphs.keys())
        merged_graph = deep_copy_graph(self.graphs[instruction_names[0]])

        # Track nodes that can be shared vs instruction-specific
        shared_nodes = set()
        instruction_specific_nodes = {}

        # Analyze which nodes can be shared
        collision_dependents, node_remapping = self._analyze_node_sharing(shared_nodes, instruction_specific_nodes)

        # Mark all shared nodes (fully and partially shared) with is_shared=True
        # Also ensure all ISA state nodes are marked as shared
        print(f"\nMarking shared nodes...")
        print(f"  shared_nodes has {len(shared_nodes)} nodes")
        print(f"  merged_graph has {len(merged_graph.nodes)} nodes")
        for node_id in shared_nodes:
            if node_id in merged_graph.nodes:
                node = merged_graph.nodes[node_id]
                # True ISA state should already have is_arch_state=True from ISA parser
                # We add is_shared=True to all shared nodes (both ISA state and intermediate nodes)
                if not node.is_shared:
                    node.is_shared = True
                    print(f"  Marked {node_id} as shared (is_arch_state={node.is_arch_state})")
            else:
                print(f"  WARNING: {node_id} in shared_nodes but not in merged_graph!")

        # Also mark any ISA state nodes as shared (they should already be in shared_nodes, but be safe)
        for node_id, node in sorted(merged_graph.nodes.items()):
            if node.is_arch_state and not node.is_shared:
                node.is_shared = True
                print(f"  Marked ISA state {node_id} as shared")

        # Merge edges for fully shared nodes from all instructions
        # (The merged graph started with a copy of the first instruction, but fully shared nodes
        # may have different edges in different instructions)
        print(f"\nMerging edges for fully shared nodes from subsequent instructions...")
        fully_shared_nodes = shared_nodes - set(self.partially_shared_nodes.keys())
        for node_id in fully_shared_nodes:
            if node_id not in merged_graph.nodes:
                continue
            merged_node = merged_graph.nodes[node_id]

            # Collect all edges from all instructions for this shared node
            for instr_name in instruction_names[1:]:  # Skip first instruction (already in merged graph)
                source_graph = self.graphs[instr_name]
                if node_id not in source_graph.nodes:
                    continue
                source_node = source_graph.nodes[node_id]

                # Add outgoing edges that don't already exist
                for edge in source_node.outgoing_edges:
                    target_id = edge.target.id
                    if target_id in merged_graph.nodes:
                        # Check if this edge already exists
                        # Note: For concatenation inputs, we must also check position to allow
                        # multiple edges from the same source (e.g., two 1'b1 literals)
                        edge_type = edge.data.get('type')
                        edge_position = edge.data.get('position')
                        edge_exists = any(
                            e.target.id == target_id and
                            e.data.get('type') == edge_type and
                            e.data.get('position') == edge_position
                            for e in merged_node.outgoing_edges
                        )
                        if not edge_exists:
                            new_edge = Edge(merged_node, merged_graph.nodes[target_id],
                                          data=edge.data.copy() if edge.data else {})
                            merged_graph.add_edge(new_edge)
                            print(f"  Added edge {node_id} -> {target_id} (type={edge.data.get('type')}) from {instr_name}")

        # Add partially shared nodes that aren't in the first instruction's graph
        for node_id in sorted(self.partially_shared_nodes):
            if node_id not in merged_graph.nodes:
                # Find the first instruction that has this node and copy it
                using_instrs = self.partially_shared_nodes[node_id]
                source_instr = sorted(using_instrs)[0]  # Pick first alphabetically for consistency
                source_graph = self.graphs[source_instr]

                if node_id in source_graph.nodes:
                    source_node = source_graph.nodes[node_id]
                    new_node = Node(node_id, source_node.data.copy() if source_node.data else {}, is_shared=True)
                    merged_graph.add_node(new_node)
                    print(f"Added partially shared node '{node_id}' to merged graph from {source_instr} (is_shared=True)")

                    # Copy edges for this node
                    # Note: Sources/targets might be shared, partially shared, or instruction-specific
                    # We'll add edges now where possible; instruction-specific edges added later
                    for edge in source_node.incoming_edges:
                        source_edge_id = edge.source.id
                        # If source doesn't exist in merged graph, add it (e.g., bit slices that are part of concat)
                        if source_edge_id not in merged_graph.nodes:
                            source_type = edge.source.data.get('type')
                            # Only add simple intermediate nodes (bit slices, literals, etc.)
                            # Don't add complex nodes that might be instruction-specific
                            if source_type in ['bit_slice', 'literal', 'sized_literal']:
                                copy_node = Node(source_edge_id, edge.source.data.copy() if edge.source.data else {}, is_shared=True)
                                merged_graph.add_node(copy_node)
                                print(f"    Added missing source node '{source_edge_id}' for partially shared node '{node_id}'")

                                # For bit_slice nodes, also copy their incoming edges (e.g., from 'instr')
                                if source_type == 'bit_slice':
                                    for bit_slice_edge in edge.source.incoming_edges:
                                        bit_slice_source_id = bit_slice_edge.source.id
                                        # Check if the bit_slice's source exists in merged graph (e.g., 'instr')
                                        if bit_slice_source_id in merged_graph.nodes:
                                            bit_slice_new_edge = Edge(
                                                merged_graph.nodes[bit_slice_source_id],
                                                copy_node,
                                                data=bit_slice_edge.data.copy() if bit_slice_edge.data else {}
                                            )
                                            merged_graph.add_edge(bit_slice_new_edge)
                                            print(f"      Added edge from '{bit_slice_source_id}' to bit_slice '{source_edge_id}'")
                        # Try to connect if source exists in merged graph
                        if source_edge_id in merged_graph.nodes:
                            new_edge = Edge(merged_graph.nodes[source_edge_id], new_node,
                                          data=edge.data.copy() if edge.data else {})
                            merged_graph.add_edge(new_edge)

                    for edge in source_node.outgoing_edges:
                        target_edge_id = edge.target.id
                        # Try to connect if target exists in merged graph
                        if target_edge_id in merged_graph.nodes:
                            new_edge = Edge(new_node, merged_graph.nodes[target_edge_id],
                                          data=edge.data.copy() if edge.data else {})
                            merged_graph.add_edge(new_edge)

        # Add instruction-specific nodes (those unique to each instruction)
        # Must be done BEFORE creating decode logic so ILA decode signal nodes are present
        self._add_instruction_specific_nodes(merged_graph, instruction_specific_nodes, collision_dependents, node_remapping)

        # Second pass: Connect any missing edges for partially shared nodes
        # (Some edges might connect to instruction-specific nodes that were just added with prefixes)
        print(f"\nConnecting deferred edges for partially shared nodes...")
        for node_id in sorted(self.partially_shared_nodes):
            if node_id not in merged_graph.nodes:
                continue
            merged_node = merged_graph.nodes[node_id]
            using_instrs = self.partially_shared_nodes[node_id]

            # Try to add edges from each instruction that uses this node
            for instr_name in sorted(using_instrs):
                source_graph = self.graphs[instr_name]

                # For group-specific nodes, use the original_id to look up in source graph
                source_node_id = merged_node.data.get('original_id', node_id)

                if source_node_id not in source_graph.nodes:
                    continue
                source_node = source_graph.nodes[source_node_id]

                # Add any missing incoming edges
                for edge in source_node.incoming_edges:
                    source_edge_id = edge.source.id

                    # Try to find the actual source node ID in merged graph
                    # It might be: 1) unprefixed (shared), 2) prefixed (instruction-specific), 3) remapped (group-specific)
                    actual_source_id = None

                    # CRITICAL FIX: Don't use unprefixed version if it's in group_specific_replacements
                    # (these nodes have multiple assignment groups and must be accessed via prefixed versions)
                    use_unprefixed = source_edge_id in merged_graph.nodes
                    if hasattr(self, 'group_specific_replacements') and source_edge_id in self.group_specific_replacements:
                        use_unprefixed = False

                    # Also prefer instruction-specific versions (remapped or prefixed) over
                    # unprefixed shared versions when they exist. This prevents connecting to
                    # a shared node that was created by a different instruction group (e.g.,
                    # using andb_gbr_invdata_tlb_any_exception for ldcl_spc).
                    if use_unprefixed:
                        if source_edge_id in node_remapping.get(instr_name, {}):
                            remapped_id = node_remapping[instr_name][source_edge_id]
                            if remapped_id in merged_graph.nodes:
                                use_unprefixed = False
                        else:
                            prefixed_id = f"{instr_name}_{source_edge_id}"
                            if prefixed_id in merged_graph.nodes:
                                use_unprefixed = False

                    if use_unprefixed:
                        actual_source_id = source_edge_id
                    elif source_edge_id in node_remapping.get(instr_name, {}):
                        # Try remapped version (e.g., imm -> beq_imm)
                        remapped_id = node_remapping[instr_name][source_edge_id]
                        if remapped_id in merged_graph.nodes:
                            actual_source_id = remapped_id
                    else:
                        # Try prefixed version
                        prefixed_id = f"{instr_name}_{source_edge_id}"
                        if prefixed_id in merged_graph.nodes:
                            actual_source_id = prefixed_id

                    if actual_source_id:
                        # Check if this edge already exists
                        # Include position check for concatenation inputs
                        edge_type = edge.data.get('type') if edge.data else None
                        edge_position = edge.data.get('position') if edge.data else None
                        edge_exists = False
                        for existing_edge in merged_node.incoming_edges:
                            if (existing_edge.source.id == actual_source_id and
                                existing_edge.data.get('type') == edge_type and
                                existing_edge.data.get('position') == edge_position):
                                edge_exists = True
                                break

                        if not edge_exists:
                            new_edge = Edge(merged_graph.nodes[actual_source_id], merged_node,
                                          data=edge.data.copy() if edge.data else {})
                            merged_graph.add_edge(new_edge)
                            print(f"  Added deferred edge: {actual_source_id} -> {node_id}")

                # Add any missing outgoing edges
                for edge in source_node.outgoing_edges:
                    target_edge_id = edge.target.id

                    # Try to find the actual target node ID in merged graph
                    # It might be: 1) unprefixed (shared), 2) prefixed (instruction-specific), 3) remapped (group-specific)
                    actual_target_id = None

                    # CRITICAL FIX: Don't use unprefixed version if it's in group_specific_replacements
                    # (these nodes have multiple assignment groups and must be accessed via prefixed versions)
                    use_unprefixed = target_edge_id in merged_graph.nodes
                    if hasattr(self, 'group_specific_replacements') and target_edge_id in self.group_specific_replacements:
                        use_unprefixed = False

                    # Also prefer instruction-specific versions over unprefixed shared versions
                    if use_unprefixed:
                        if target_edge_id in node_remapping.get(instr_name, {}):
                            remapped_id = node_remapping[instr_name][target_edge_id]
                            if remapped_id in merged_graph.nodes:
                                use_unprefixed = False
                        else:
                            prefixed_id = f"{instr_name}_{target_edge_id}"
                            if prefixed_id in merged_graph.nodes:
                                use_unprefixed = False

                    if use_unprefixed:
                        actual_target_id = target_edge_id
                    elif target_edge_id in node_remapping.get(instr_name, {}):
                        # Try remapped version (e.g., imm -> beq_imm)
                        remapped_id = node_remapping[instr_name][target_edge_id]
                        if remapped_id in merged_graph.nodes:
                            actual_target_id = remapped_id
                    else:
                        # Try prefixed version
                        prefixed_id = f"{instr_name}_{target_edge_id}"
                        if prefixed_id in merged_graph.nodes:
                            actual_target_id = prefixed_id

                    if actual_target_id:
                        # Check if this edge already exists
                        # Include position check for concatenation inputs
                        edge_type = edge.data.get('type') if edge.data else None
                        edge_position = edge.data.get('position') if edge.data else None
                        edge_exists = False
                        for existing_edge in merged_node.outgoing_edges:
                            if (existing_edge.target.id == actual_target_id and
                                existing_edge.data.get('type') == edge_type and
                                existing_edge.data.get('position') == edge_position):
                                edge_exists = True
                                break

                        if not edge_exists:
                            new_edge = Edge(merged_node, merged_graph.nodes[actual_target_id],
                                          data=edge.data.copy() if edge.data else {})
                            merged_graph.add_edge(new_edge)
                            print(f"  Added deferred edge: {node_id} -> {actual_target_id}")

        # Clean up stale edges that reference removed nodes
        # (e.g., ternaries that reference unprefixed 'res' which was removed)
        print(f"\nCleaning up stale edges from removed nodes...")

        edges_to_remove = []
        for node_id, node in merged_graph.nodes.items():
            for edge in node.incoming_edges:
                # Check if the source node is actually in the graph (not just if an ID matches)
                source_id = edge.source.id
                if source_id not in merged_graph.nodes or merged_graph.nodes[source_id] is not edge.source:
                    edges_to_remove.append((node, edge))
                    print(f"  Removing stale edge: {source_id} -> {node_id} (source node removed/replaced)")
            for edge in node.outgoing_edges:
                # Check if the target node is actually in the graph (not just if an ID matches)
                target_id = edge.target.id
                if target_id not in merged_graph.nodes or merged_graph.nodes[target_id] is not edge.target:
                    edges_to_remove.append((node, edge))
                    print(f"  Removing stale edge: {node_id} -> {target_id} (target node removed/replaced)")

        for node, edge in edges_to_remove:
            merged_graph.remove_edge(edge)

        # Create instruction decode logic
        # For ILA: connects existing decode signal nodes to instruction_enable nodes
        # For ISA: creates new decode comparison nodes
        self._create_decode_logic(merged_graph)

        # Multiplex memory write ports when multiple instructions write to same memory
        # (Must be done BEFORE gating and cleanup, while assignment edges still exist)
        self._multiplex_memory_write_ports(merged_graph, instruction_specific_nodes)

        # Note: Memory read address muxing is now handled by the verilog generator
        # when it encounters multiple index edges on an array_access node

        # Gate instruction-specific operations with decode conditions
        self._gate_instruction_operations(merged_graph, instruction_specific_nodes)

        # Handle variable latency operations (wire up start/idle signals)
        self._handle_variable_latency_operations(merged_graph, instruction_specific_nodes)

        # Remove original instruction-specific nodes that have been superseded
        self._cleanup_superseded_nodes(merged_graph, instruction_specific_nodes)

        # Apply standard optimization passes using GraphOptimizer
        optimizer = GraphOptimizer(merged_graph)
        # Disable nested mux merging for now - it breaks conditional branches
        # TODO: Fix the optimization to properly handle ternary conditions
        # Disable alias propagation to preserve instruction-specific prefixed nodes
        # Must set enable_all=False to prevent default behavior from overriding
        optimizer.optimize(enable_all=False, merge_nested_muxes=False, propagate_aliases=False, split_arch_state=True)

        # Detect gated write muxes that need to be merged (after arch state splitting)
        # After splitting, we have instruction-specific gated muxes (e.g., add_pc_gated_mux, beq_pc_gated_mux)
        # all writing to the same _wr node (e.g., pc_wr). These need to be merged into a single unified mux.
        self._arch_state_wr_nodes_needing_mux = set()
        gated_mux_targets = {}  # target -> list of gated mux nodes

        for node_id, node in merged_graph.nodes.items():
            if node.data and node.data.get('gated_write_mux'):
                # This is a gated write mux - find what it writes to
                for edge in node.outgoing_edges:
                    if edge.data and edge.data.get('type') == 'assignment':
                        target_id = edge.target.id
                        if target_id not in gated_mux_targets:
                            gated_mux_targets[target_id] = []
                        gated_mux_targets[target_id].append(node_id)

        # Any target with multiple gated muxes needs merging
        for target_id, mux_list in gated_mux_targets.items():
            if len(mux_list) > 1:
                self._arch_state_wr_nodes_needing_mux.add(target_id)
                print(f"Detected {len(mux_list)} gated muxes writing to {target_id}: {mux_list[:5]}...")

        if self._arch_state_wr_nodes_needing_mux:
            print(f"Arch state _wr nodes needing mux: {self._arch_state_wr_nodes_needing_mux}")

        # Promote mem widths based on actual access patterns (after arch state splitting)
        self._promote_mem_widths(merged_graph)

        # Final cleanup: remove any remaining direct assignment edges that bypass multiplexers
        optimizer.cleanup_bypassed_edges()

        reinfer_timing(merged_graph)

        # Deduplicate common subexpressions in gated write muxes
        print("\nDeduplicating arch state muxes...")
        deduplicate_all_arch_state_muxes(merged_graph)

        print(f"Merged graph: {merged_graph}")
        return merged_graph

    def _compute_deep_assignment_signature(self, node, graph, visited=None):
        """Compute a deep signature for a node that includes variable assignment sources recursively.

        This ensures that expressions with same display_name but different variable bindings are distinguished.
        For example, {{20{imm[11]}}, imm} should have different signatures if imm=instr[31:20] vs imm={instr[31:25],instr[11:7]}.
        """
        if visited is None:
            visited = set()

        node_id = node.id
        if node_id in visited:
            return node_id  # Avoid infinite recursion

        node_type = node.data.get('type', '')
        display_name = node.data.get('display_name', node_id)

        # For variables, include their assignment sources
        if node_type == 'var':
            visited.add(node_id)
            var_sources = []
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'assignment':
                    src_sig = self._compute_deep_assignment_signature(edge.source, graph, visited)
                    var_sources.append(src_sig)
            if var_sources:
                return f"{display_name}[{','.join(sorted(var_sources))}]"
            else:
                return display_name

        # For operations/concatenations, include signatures of all operand variables
        elif node_type in ['operation', 'concatenation', 'repetition', 'ternary_op']:
            visited.add(node_id)
            operand_sigs = []
            for edge in node.incoming_edges:
                if edge.data.get('type') in ['operand', 'concat_element', 'concatenation_input', 'ternary_condition', 'ternary_true', 'ternary_false', 'repetition_value']:
                    src_sig = self._compute_deep_assignment_signature(edge.source, graph, visited)
                    operand_sigs.append(src_sig)
            if operand_sigs:
                return f"{display_name}({','.join(sorted(operand_sigs))})"
            else:
                return display_name

        # For other types, just use display name
        else:
            return display_name

    def _compute_node_structure_key(self, node, graph):
        """Compute a hashable key representing the node's structure.

        For variables, includes assignment sources. For expressions, includes operator and operand structure.
        For multiplexers, includes inputs, selects, and target to enable structural sharing.
        """
        node_type = node.data.get('type', '')

        if node_type == 'var':
            # Orthogon-derived var nodes use shallow keys so they can be
            # shared across instructions.  Key only by assignment source IDs.
            if node.data.get('from_orthogon'):
                sources = frozenset(
                    edge.source.id
                    for edge in node.incoming_edges
                    if edge.data.get('type') == 'assignment'
                )
                return ('var', sources, frozenset(), node.data.get('bit_width', 0), frozenset())

            # Variables: key by assignment sources AND enable conditions
            # This prevents merging nodes that have the same value but different
            # enable conditions on their writes (e.g., arm_bl's return_addr writes to
            # rf_svc_lr when (cond_pass & is_svc), but arm_swi's writes when (cond_pass))
            def _source_key_for_var(edge):
                """Get a source key that includes bit_slice range info to prevent
                merging vars assigned from different bit slices of the same source
                (e.g., instr[20:16] vs instr[25:21])."""
                src = edge.source
                name = src.data.get('display_name', src.id)
                if src.data.get('type') == 'bit_slice':
                    bitslice = src.data.get('bitslice')
                    if bitslice is None:
                        expr = src.data.get('expression', {})
                        bitslice = expr.get('range')
                    return (name, bitslice)
                return name
            sources = frozenset(
                _source_key_for_var(edge)
                for edge in node.incoming_edges
                if edge.data.get('type') == 'assignment'
            )
            # Include enable conditions from outgoing assignment edges
            # so nodes with different write conditions don't get merged
            # Also consider mux_input edges which have original_enable preserved
            # from when the aspect_merger created gated muxes
            def get_enable_str(edge):
                if edge.data.get('type') == 'assignment':
                    return str(edge.data.get('enable', None))
                elif edge.data.get('type') in ('mux_input', 'mux_default_input'):
                    # Use original_enable for mux inputs (preserved from aspect_merger)
                    return str(edge.data.get('original_enable', None))
                return None

            outgoing_enables = frozenset(
                enable_str
                for edge in node.outgoing_edges
                for enable_str in [get_enable_str(edge)]
                if enable_str is not None and edge.data.get('type') in ('assignment', 'mux_input', 'mux_default_input')
            )
            # Include bit_width so vars of different widths aren't merged.
            # This is critical for memory reads: an 8-bit byte read and a
            # 16-bit word read from the same address must stay separate so
            # the MemoryAccessTransform creates the correct selection mux
            # for each width.
            #
            # Also include enable conditions from INCOMING assignment edges
            # This is critical for ISA state writes like:
            #   pal_mode when (itb_fault) = 1       (ALU instructions)
            #   pal_mode when (load_any_fault) = 1   (load instructions)
            # Without this, both get the same structure key (same source '1')
            # and get merged into one group, losing the load_any_fault condition.
            incoming_enables = frozenset(
                str(edge.data.get('enable'))
                for edge in node.incoming_edges
                if edge.data.get('type') == 'assignment' and edge.data.get('enable') is not None
            )
            return ('var', sources, outgoing_enables, node.data.get('bit_width', 0), incoming_enables)
        elif node_type == 'multiplexer':
            # Orthogon muxes use a shallow key so the merger shares them.
            if node.data.get('orthogon_mux'):
                return ('orthogon_mux', node.data.get('orthogon_name', ''),
                        node.data.get('provides_name', ''),
                        node.data.get('num_inputs', 0))

            # Multiplexers: key by structural properties to enable sharing
            # This allows add_pc_gated_mux and and_pc_gated_mux to be recognized as identical

            # Get target (what this mux assigns to)
            target_ids = frozenset(
                edge.target.id
                for edge in node.outgoing_edges
                if edge.data and edge.data.get('type') == 'assignment'
            )

            # Get inputs with their indices
            inputs_by_idx = {}
            default_input_id = None
            for edge in node.incoming_edges:
                if edge.data and edge.data.get('type') == 'mux_input':
                    input_idx = edge.data.get('input_index', -1)
                    source_id = edge.source.data.get('display_name', edge.source.id)
                    inputs_by_idx.setdefault(input_idx, {})['value'] = source_id
                elif edge.data and edge.data.get('type') == 'mux_default_input':
                    # Include default input in structure key to distinguish gated muxes
                    # with different defaults (e.g., add's pc+4 vs jal's jump_dest)
                    default_input_id = edge.source.data.get('display_name', edge.source.id)

            # Get select conditions with their indices
            selects_by_idx = {}
            for edge in node.incoming_edges:
                if edge.data and edge.data.get('type') == 'mux_select':
                    select_idx = edge.data.get('select_index', -1)
                    cond_id = edge.source.id
                    selects_by_idx[select_idx] = cond_id

            # Create order-independent (value, condition) pairs by joining on index.
            # This is critical: the ISA parser may assign mux input indices
            # non-deterministically (e.g., due to set iteration order), so two
            # structurally identical muxes can have swapped indices:
            #   Mux A: idx 0 → (val=1, sel=take_interrupt), idx 1 → (val=1, sel=itb_fault)
            #   Mux B: idx 0 → (val=1, sel=itb_fault),      idx 1 → (val=1, sel=take_interrupt)
            # Using a frozenset of (value, condition) pairs makes the key identical
            # for both orderings, ensuring they land in the same collision group.
            all_indices = sorted(set(inputs_by_idx.keys()) | set(selects_by_idx.keys()))
            input_cond_pairs = frozenset(
                (inputs_by_idx.get(idx, {}).get('value', ''),
                 selects_by_idx.get(idx, ''))
                for idx in all_indices
            )
            # Also build the old-style sorted tuples for backward compatibility in the key
            inputs = tuple(sorted(
                (idx, inputs_by_idx[idx]['value'])
                for idx in inputs_by_idx
            ))
            if default_input_id:
                inputs = inputs + (('default', default_input_id),)
            selects = tuple(sorted(
                (idx, selects_by_idx[idx])
                for idx in selects_by_idx
            ))

            # Get default input - critical for gated muxes with different defaults
            # Without this, jal_pc_gated_mux (default=jump_dest) and add_pc_gated_mux
            # (default=pc+4) would be merged incorrectly
            default_source = None
            for edge in node.incoming_edges:
                if edge.data and edge.data.get('type') == 'mux_default_input':
                    source_node = edge.source

                    # For var nodes (like jump_dest), include their assignment source's display_name
                    # This distinguishes jal's jump_dest (pc+offset) from jalr's jump_dest (r1+imm)
                    # without fully recursing which can cause excessive splitting
                    source_type = source_node.data.get('type', '')
                    if source_type == 'var':
                        # Get the assignment source for this var to distinguish different definitions
                        var_sources = []
                        for var_edge in source_node.incoming_edges:
                            if var_edge.data and var_edge.data.get('type') == 'assignment':
                                var_sources.append(var_edge.source.data.get('display_name', var_edge.source.id))
                        if var_sources:
                            default_source = f"var:{source_node.id}={','.join(sorted(var_sources))}"
                        else:
                            default_source = source_node.id
                    elif source_type == 'ternary_op':
                        # For ternary default inputs (like res ? branch_dest : pc+4),
                        # include all operand sources to distinguish between branches
                        # This is critical for:
                        # - BEQ vs BNE: different conditions (r1==r2 vs r1!=r2)
                        # - BC vs BCLR: different true values (pc+offset vs LR)
                        def _get_ternary_operand_sig(operand_node):
                            op_type = operand_node.data.get('type', '')
                            if op_type == 'var':
                                var_sources = []
                                for var_edge in operand_node.incoming_edges:
                                    if var_edge.data and var_edge.data.get('type') == 'assignment':
                                        var_sources.append(var_edge.source.data.get('display_name', var_edge.source.id))
                                if var_sources:
                                    return f"var:{operand_node.id}={','.join(sorted(var_sources))}"
                                else:
                                    return operand_node.id
                            else:
                                return operand_node.data.get('display_name', operand_node.id)

                        cond_source = None
                        true_source = None
                        false_source = None
                        for tern_edge in source_node.incoming_edges:
                            if not tern_edge.data:
                                continue
                            tern_edge_type = tern_edge.data.get('type', '')
                            if tern_edge_type == 'ternary_condition':
                                cond_source = _get_ternary_operand_sig(tern_edge.source)
                            elif tern_edge_type == 'ternary_true':
                                true_source = _get_ternary_operand_sig(tern_edge.source)
                            elif tern_edge_type == 'ternary_false':
                                false_source = _get_ternary_operand_sig(tern_edge.source)
                        default_source = f"ternary:{source_node.id}[cond={cond_source},true={true_source},false={false_source}]"
                    else:
                        default_source = source_node.data.get('display_name', source_node.id)
                    break

            # Check if it's a gated write mux
            is_gated = node.data.get('gated_write_mux', False)

            # Use order-independent input_cond_pairs for the structure key.
            # This ensures muxes with identical (value, condition) pairs but
            # different index assignments are recognized as structurally equivalent.
            return ('multiplexer', target_ids, input_cond_pairs, is_gated, default_source)
        elif node_type in ('ternary_op', 'operation', 'concatenation', 'repetition', 'sign_extend', 'zero_extend'):
            display_name = node.data.get('display_name', '')
            is_from_orthogon = bool(node.data.get('from_orthogon'))

            def _get_operand_source_sig(source_node, depth=0):
                """Get a signature string for an operand source node.

                Recursively includes operand signatures for operation nodes that
                assign to var nodes, to distinguish e.g. taken=(src==imm) from
                taken=(result==0) which have the same operator but different inputs.
                """
                # Orthogon nodes use shallow signatures: addr_sel == literal
                # is the same structure regardless of how addr_sel is computed.
                if is_from_orthogon:
                    return source_node.id

                source_type = source_node.data.get('type', '')
                if source_type == 'var':
                    var_sources = []
                    for var_edge in source_node.incoming_edges:
                        if var_edge.data and var_edge.data.get('type') == 'assignment':
                            assign_src = var_edge.source
                            assign_type = assign_src.data.get('type', '')
                            # For operation/ternary sources, recurse into their operands
                            # to distinguish different computations with the same operator
                            if assign_type in ('operation', 'ternary_op') and depth < 2:
                                _pos = {'left': 0, 'unary': 0, 'right': 1, 'operand': 0}
                                op_sigs = []
                                for op_edge in sorted(assign_src.incoming_edges,
                                                      key=lambda e: (_pos.get(
                                                          (e.data.get('position', '') if e.data else ''),
                                                          e.data.get('operand_index', 99) if e.data else 99),
                                                          e.source.id)):
                                    op_sigs.append(_get_operand_source_sig(op_edge.source, depth + 1))
                                op_name = assign_src.data.get('display_name', assign_src.id)
                                var_sources.append(f"{op_name}({','.join(op_sigs)})")
                            else:
                                var_sources.append(assign_src.data.get('display_name', assign_src.id))
                    if var_sources:
                        return f"var:{source_node.id}={','.join(sorted(var_sources))}"
                    else:
                        return source_node.id
                else:
                    return source_node.data.get('display_name', source_node.id)

            if node_type != 'ternary_op':
                # Sort by edge position with deterministic tiebreaker (source node ID)
                # to avoid non-determinism from iterating incoming_edges (a set)
                _pos_order = {'left': 0, 'unary': 0, 'right': 1, 'operand': 0}
                operand_sigs = []
                for edge in sorted(node.incoming_edges,
                                   key=lambda e: (_pos_order.get(
                                       (e.data.get('position', '') if e.data else ''),
                                       e.data.get('position', 99) if e.data else 99),
                                       e.source.id)):
                    operand_sigs.append(_get_operand_source_sig(edge.source))
                operand_sigs = tuple(operand_sigs)
                return (node_type, display_name, operand_sigs)

            # Ternary operations: key by display_name PLUS all operand sources
            # This is critical for branch instructions where all have the same structure
            # (res ? branch_dest : pc+4) but different 'res' or 'branch_dest' values:
            # - BEQ: res = r1 == r2
            # - BNE: res = r1 != r2
            # - BC:  target = pc + sign_ext_bd (PC-relative)
            # - BCLR: target = {lr[63:2], 2'b00} (from LR)
            # Without including all operand sources, instructions with different
            # true/false values would merge into one using the wrong operand.

            # Extract condition, true, and false operand sources
            cond_source = None
            true_source = None
            false_source = None
            for edge in node.incoming_edges:
                edge_type = edge.data.get('type', '') if edge.data else ''
                if edge_type in ['ternary_condition', 'mux_select'] or edge.data.get('input_index') == 0:
                    cond_source = _get_operand_source_sig(edge.source)
                elif edge_type == 'ternary_true':
                    true_source = _get_operand_source_sig(edge.source)
                elif edge_type == 'ternary_false':
                    false_source = _get_operand_source_sig(edge.source)

            return (node_type, display_name, cond_source, true_source, false_source)
        elif node_type in ['literal', 'sized_literal']:
            return (node_type, node.data.get('value', ''))
        elif node_type == 'bit_slice':
            # Include bit range in structure key to distinguish different slices (e.g., [7:0] vs [15:0])
            # The range may be in 'bitslice' or in 'expression.range'
            bitslice = node.data.get('bitslice')
            if bitslice is None:
                expr = node.data.get('expression', {})
                bitslice = expr.get('range')
            return (node_type, bitslice, node.data.get('display_name', ''))
        elif node_type == 'isa_state':
            # ISA state nodes (like pc_wr, rf_wr): key by assignment sources AND
            # enable conditions on those assignments.
            # Different instructions may assign the same value to the same ISA state
            # but under different conditions (e.g., pal_mode when (itb_fault) = 1
            # vs pal_mode when (load_any_fault) = 1). Without including enables,
            # these get merged into one group, losing the broader condition.
            def _source_key_for_state(edge):
                src = edge.source
                name = src.data.get('display_name', src.id)
                if src.data.get('type') == 'bit_slice':
                    bitslice = src.data.get('bitslice')
                    if bitslice is None:
                        expr = src.data.get('expression', {})
                        bitslice = expr.get('range')
                    return (name, bitslice)
                return name
            sources = frozenset(
                _source_key_for_state(edge)
                for edge in node.incoming_edges
                if edge.data.get('type') == 'assignment'
            )
            incoming_enables = frozenset(
                str(edge.data.get('enable'))
                for edge in node.incoming_edges
                if edge.data.get('type') == 'assignment' and edge.data.get('enable') is not None
            )
            return ('isa_state', node.data.get('name', ''), sources, incoming_enables)
        else:
            # Other types: key by type and name
            return (node_type, node.data.get('name', ''))

    def _analyze_node_sharing(self, shared_nodes: Set[str], instruction_specific_nodes: Dict[str, Set[str]]):
        """Analyze which nodes can be shared between instructions based on structure, not just ID."""

        instruction_names = list(self.graphs.keys())
        num_instructions = len(instruction_names)

        # PERFORMANCE: Cache for shareability checks to avoid O(n²) recursion
        self._shareability_cache = {}

        # Track node ID remapping for group-specific nodes
        # e.g., {beq: {imm: beq_imm}, bne: {imm: beq_imm}, ...}
        node_remapping = {instr: {} for instr in self.graphs.keys()}

        # Group nodes by structure across all instructions
        # structure_key -> list of (instr_name, node_id, node)
        structural_groups_raw = {}

        for instr_name, graph in self.graphs.items():
            for node_id, node in graph.nodes.items():
                struct_key = self._compute_node_structure_key(node, graph)
                if struct_key not in structural_groups_raw:
                    structural_groups_raw[struct_key] = []
                structural_groups_raw[struct_key].append((instr_name, node_id, node))

        # CRITICAL FIX: Split structural groups by node_id
        # Problem: All bit slices have the same structure, so they get lumped together.
        # When we pick the "first" node_id from the group, the others are never classified!
        # Solution: Create separate groups for each unique (struct_key, node_id) pair
        structural_groups = {}
        for struct_key, instances in structural_groups_raw.items():
            # Group instances by node_id
            by_node_id = {}
            for instr_name, node_id, node in instances:
                if node_id not in by_node_id:
                    by_node_id[node_id] = []
                by_node_id[node_id].append((instr_name, node_id, node))

            # Create a separate structural group for each node_id
            for node_id, node_instances in by_node_id.items():
                # Use (struct_key, node_id) as the new key to ensure uniqueness
                combined_key = (struct_key, node_id)
                structural_groups[combined_key] = node_instances

        for instr_name in instruction_names:
            instruction_specific_nodes[instr_name] = set()

        # Build node_usage for dependency checking (still needed by _can_share_node_usage)
        node_usage = {}
        for instr_name, graph in self.graphs.items():
            for node_id in graph.nodes:
                if node_id not in node_usage:
                    node_usage[node_id] = set()
                node_usage[node_id].add(instr_name)

        # Process each structural group (now split by node_id)
        # Group by node_id to detect collisions (multiple structures with same ID)
        node_id_to_struct_keys = {}  # node_id -> set of struct_keys
        for combined_key, instances in structural_groups.items():
            struct_key, node_id = combined_key  # Unpack the combined key
            if node_id not in node_id_to_struct_keys:
                node_id_to_struct_keys[node_id] = set()
            node_id_to_struct_keys[node_id].add(struct_key)

        # Track which node_ids have been used to avoid duplicate processing
        # Pre-compute which node_ids have structural collisions (multiple struct_keys)
        # This is ORDER-INDEPENDENT, unlike the previous approach that depended on
        # dict iteration order (affected by Python hash randomization)
        collision_node_ids = set(
            nid for nid, skeys in node_id_to_struct_keys.items()
            if len(skeys) > 1
        )

        # Track nodes marked instruction-specific due to collision (for dependent marking later)
        collision_instruction_specific = {}  # node_id -> set of instructions

        for combined_key, instances in sorted(structural_groups.items(), key=lambda item: str(item[0])):
            struct_key, node_id = combined_key  # Unpack combined key

            # All instances have the same structure AND node_id - extract instructions and nodes
            using_instrs = set(i[0] for i in instances)
            nodes = [i[2] for i in instances]
            # Node_id is already consistent across instances (by construction)
            base_node_id = node_id

            # Check if this node_id has a structural collision (multiple structures with same ID)
            # ALL groups with a collision node_id become instruction-specific
            if base_node_id in collision_node_ids:
                # Collision! Mark all instances in this group as instruction-specific
                for instr_name in sorted(using_instrs):
                    instruction_specific_nodes[instr_name].add(base_node_id)
                print(f"Structural collision for {base_node_id} in {sorted(using_instrs)} - will use instruction prefixes")
                # Track for dependent marking (accumulate across all collision groups)
                if base_node_id not in collision_instruction_specific:
                    collision_instruction_specific[base_node_id] = set()
                collision_instruction_specific[base_node_id].update(using_instrs)
                continue

            # Use base_node_id for the rest of the logic
            num_using = len(using_instrs)

            if num_using == 1:
                # Only one instruction uses this structure - instruction-specific
                instr_name = list(using_instrs)[0]
                instruction_specific_nodes[instr_name].add(node_id)

            elif num_using == num_instructions:
                # All instructions use this structure - check for full sharing
                if self._can_share_node_usage(node_id, nodes, node_usage):
                    shared_nodes.add(node_id)
                    print(f"Fully shared: {node_id}")
                else:
                    # Can't share - mark as instruction-specific
                    for instr_name in sorted(using_instrs):
                        instruction_specific_nodes[instr_name].add(node_id)
                    print(f"Different usage patterns for {node_id} - making instruction-specific")

            else:
                # Multiple (but not all) instructions use this structure - partial sharing
                if self._can_share_node_usage(node_id, nodes, node_usage):
                    # Can be partially shared
                    self.partially_shared_nodes[node_id] = using_instrs
                    shared_nodes.add(node_id)
                    print(f"Partially shared: {node_id} (used by {num_using}/{num_instructions}: {sorted(using_instrs)})")
                else:
                    # Can't share - mark as instruction-specific
                    for instr_name in sorted(using_instrs):
                        instruction_specific_nodes[instr_name].add(node_id)
                    print(f"Cannot share {node_id} across {num_using} instructions - making instruction-specific")

        # Recursively mark all transitive dependents of collision nodes as instruction-specific
        # This ensures that bit slices and other nodes that depend on collision nodes are also instruction-specific
        # Track these so they don't get re-shared in _add_instruction_specific_nodes
        collision_dependents = set()  # Set of node_ids that depend on collision nodes
        print(f"\nMarking transitive dependents of collision nodes...")
        print(f"collision_instruction_specific has {len(collision_instruction_specific)} nodes")
        for nid, instrs in sorted(collision_instruction_specific.items()):
            if 'sign_ext_imm' in nid:
                print(f"  {nid}: {sorted(instrs)}")
        for node_id, using_instrs in sorted(collision_instruction_specific.items()):
            if node_id == 'sign_ext_imm':
                print(f"Processing sign_ext_imm for instructions: {sorted(using_instrs)}")
            for instr_name in sorted(using_instrs):
                graph = self.graphs[instr_name]
                if node_id not in graph.nodes:
                    if node_id == 'sign_ext_imm':
                        print(f"  {instr_name}: sign_ext_imm NOT in graph!")
                    continue

                # Recursively mark all transitive dependents
                visited = set()
                def mark_dependents_recursive(current_id):
                    if current_id in visited:
                        return
                    visited.add(current_id)
                    if current_id not in graph.nodes:
                        return
                    node = graph.nodes[current_id]
                    if node_id == 'sign_ext_imm' and current_id == 'sign_ext_imm':
                        print(f"  {instr_name}: sign_ext_imm has {len(node.outgoing_edges)} outgoing edges")
                    for edge in node.outgoing_edges:
                        dep_id = edge.target.id
                        dep_node = edge.target
                        if node_id == 'sign_ext_imm' and current_id == 'sign_ext_imm':
                            already_specific = dep_id in instruction_specific_nodes[instr_name]
                            print(f"  {instr_name}: sign_ext_imm -> {dep_id} (already instruction-specific: {already_specific})")

                        # NEVER mark architectural state nodes as instruction-specific
                        # Even though they may depend on collision nodes, they are shared write targets
                        # The multiplexing happens at the VALUE level, not by creating separate state nodes
                        if dep_node.is_arch_state:
                            print(f"  Skipping {dep_id} - architectural state must remain shared")
                            continue

                        # Mark as instruction-specific even if previously marked as partially shared
                        # (collision overrides partial sharing for this instruction)
                        if dep_id not in instruction_specific_nodes[instr_name]:
                            # CRITICAL FIX: If this dependent is used by other instructions (shared or partially shared),
                            # we must mark it as instruction-specific for ALL instructions, not just this one.
                            # Otherwise, we'll have a shared node that some instructions think is instruction-specific,
                            # leading to incorrect wiring in Verilog.

                            # Check if this dependent is used by other instructions
                            dep_used_by = node_usage.get(dep_id, set())
                            if len(dep_used_by) > 1:
                                # Used by multiple instructions - mark as instruction-specific for ALL of them
                                print(f"  Marking {dep_id} as instruction-specific in ALL {len(dep_used_by)} instructions (depends on collision node {node_id})")
                                for other_instr in dep_used_by:
                                    if dep_id not in instruction_specific_nodes[other_instr]:
                                        instruction_specific_nodes[other_instr].add(dep_id)
                                collision_dependents.add(dep_id)
                                # Remove from shared sets completely
                                if dep_id in self.partially_shared_nodes:
                                    del self.partially_shared_nodes[dep_id]
                                if dep_id in shared_nodes:
                                    shared_nodes.remove(dep_id)
                            else:
                                # Only used by this instruction - just mark it
                                instruction_specific_nodes[instr_name].add(dep_id)
                                collision_dependents.add(dep_id)  # Track for later
                                print(f"  Marking {dep_id} as instruction-specific in {instr_name} (depends on collision node {node_id})")
                                # Remove this instruction from partially shared set (but keep for other instructions)
                                if dep_id in self.partially_shared_nodes:
                                    if instr_name in self.partially_shared_nodes[dep_id]:
                                        self.partially_shared_nodes[dep_id].discard(instr_name)
                                        print(f"    Removed {instr_name} from partially shared set for {dep_id}")
                                        # If no instructions left, remove from shared_nodes
                                        if len(self.partially_shared_nodes[dep_id]) == 0:
                                            del self.partially_shared_nodes[dep_id]
                                            if dep_id in shared_nodes:
                                                shared_nodes.remove(dep_id)
                                            print(f"    No more instructions share {dep_id}, removed completely")
                        # Recursively mark dependents
                        mark_dependents_recursive(dep_id)

                if node_id == 'sign_ext_imm':
                    print(f"  {instr_name}: Calling mark_dependents_recursive for sign_ext_imm")
                mark_dependents_recursive(node_id)

        print(f"\nSharing summary:")
        print(f"  Fully shared: {len(shared_nodes) - len(self.partially_shared_nodes)}")
        print(f"  Partially shared: {len(self.partially_shared_nodes)}")
        print(f"  Instruction-specific: {sum(len(nodes) for nodes in instruction_specific_nodes.values())}")

        return collision_dependents, node_remapping

    def _nodes_structurally_identical(self, nodes: List[Node]) -> bool:
        """Check if nodes have identical structure (type, properties, etc.)"""
        if not nodes:
            return True

        first = nodes[0]
        for node in nodes[1:]:
            if (node.is_arch_state != first.is_arch_state or
                node.is_uarch_state != first.is_uarch_state or
                node.used_as_index != first.used_as_index or
                node.data.get('type') != first.data.get('type') or
                node.data.get('name') != first.data.get('name')):
                return False
        return True

    def _can_share_node_usage(self, node_id: str, nodes: List[Node], node_usage: Dict = None) -> bool:
        """Check if nodes can be shared based on their usage patterns and dependencies.

        Args:
            node_id: ID of the node being checked
            nodes: List of node instances across instructions
            node_usage: Map of node_id -> set of instruction names (for dependency checking)
        """
        # PERFORMANCE: Check cache to avoid redundant recursive checks
        if hasattr(self, '_shareability_cache'):
            using_instrs = tuple(sorted(node_usage.get(node_id, set()))) if node_usage else ()
            cache_key = (node_id, using_instrs)
            if cache_key in self._shareability_cache:
                return self._shareability_cache[cache_key]

        node_type = nodes[0].data.get('type')

        # Helper to cache and return result
        def cache_result(result):
            if hasattr(self, '_shareability_cache') and node_usage:
                using_instrs = tuple(sorted(node_usage.get(node_id, set())))
                cache_key = (node_id, using_instrs)
                self._shareability_cache[cache_key] = result
            return result

        # Variables need to check if they have the same incoming assignments
        if node_type == 'var':
            # Get assignment sources for each node
            assignment_sources = []
            for node in nodes:
                sources = set()
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'assignment':
                        # Use the source node's ID or display name
                        source_id = edge.source.data.get('display_name', edge.source.id)
                        sources.add(source_id)
                assignment_sources.append(sources)

            # If all nodes have the same assignment sources, they can be shared
            if assignment_sources:
                first_sources = assignment_sources[0]
                for i, sources in enumerate(assignment_sources[1:], 1):
                    if sources != first_sources:
                        # Different assignments - cannot share
                        return cache_result(False)

            return cache_result(True)

        # Literals and ISA state can usually be shared if structurally identical
        if node_type in ['literal', 'isa_state', 'bit_slice', 'array_access']:
            return cache_result(True)

        # Operations need special analysis - check dependencies
        if node_type == 'operation':
            # Check if the operation expression is identical
            first_expr = nodes[0].data.get('display_name', '')
            for node in nodes[1:]:
                if node.data.get('display_name', '') != first_expr:
                    return cache_result(False)
            # Don't return yet - need to check dependencies below

        # Check dependencies for all other node types (ternary, mux, etc.)
        # A node can only be shared if all its dependencies are also shareable
        if node_usage is not None:
            using_instrs = node_usage.get(node_id, set())

            # Check all dependencies (incoming edges)
            for node in nodes:
                for edge in node.incoming_edges:
                    dep_id = edge.source.id
                    dep_type = edge.source.data.get('type')

                    # Skip architectural state and literals - always shareable
                    if dep_type in ['isa_state', 'literal', 'sized_literal']:
                        continue

                    # Check if dependency is used by the same set of instructions
                    dep_using_instrs = node_usage.get(dep_id, set())

                    # Dependency must be used by at least the same instructions as this node
                    # (It's OK if dependency is used by MORE instructions - that means it's more shared)
                    if not using_instrs.issubset(dep_using_instrs):
                        # Dependency is not available in all instructions that use this node
                        return cache_result(False)

                    # Check if this dependency will itself be made instruction-specific
                    # IMPORTANT: Only check among the instructions that use THIS node, not all
                    # instructions that use the dependency (since the dependency might be used
                    # by other instructions with a different definition)
                    relevant_instrs = using_instrs  # Only check among instructions using this node
                    if dep_id in node_usage and len(relevant_instrs) > 1:
                        # Dependency is used by multiple instructions that also use this node
                        # Check if it would be shareable among those instructions
                        dep_nodes = [self.graphs[instr].nodes[dep_id] for instr in relevant_instrs if dep_id in self.graphs[instr].nodes]
                        if len(dep_nodes) > 1:
                            if not self._nodes_structurally_identical(dep_nodes):
                                # Dependency has different structure across these instructions
                                # So this node should also be instruction-specific
                                return cache_result(False)
                            if not self._can_share_node_usage(dep_id, dep_nodes, node_usage):
                                # Dependency cannot be shared among these instructions
                                # So neither can this node
                                return cache_result(False)

        # Other node types (like concatenation, repetition) can be shared if identical
        return cache_result(True)

    def _should_share_universal_operation(self, nodes: List[Node]) -> bool:
        """Check if an operation should be shared because it's used by all instructions identically."""
        if not nodes:
            return False

        first = nodes[0]

        # Only consider operations
        if first.data.get('type') != 'operation':
            return False

        # Check if the operations are functionally equivalent
        # Compare operator and operands, ignoring instruction-specific metadata
        first_operator = first.data.get('operator')
        first_display_name = first.data.get('display_name', '')

        for node in nodes[1:]:
            if (node.data.get('operator') != first_operator or
                node.data.get('display_name', '') != first_display_name):
                return False

        # Additional check: look at connectivity patterns
        # Universal operations should have the same input/output patterns
        first_incoming_types = sorted([e.data.get('type') for e in first.incoming_edges])
        first_outgoing_types = sorted([e.data.get('type') for e in first.outgoing_edges])

        for node in nodes[1:]:
            node_incoming_types = sorted([e.data.get('type') for e in node.incoming_edges])
            node_outgoing_types = sorted([e.data.get('type') for e in node.outgoing_edges])

            if (node_incoming_types != first_incoming_types or
                node_outgoing_types != first_outgoing_types):
                return False

        return True

    def _nodes_identical(self, nodes: List[Node]) -> bool:
        """Check if a list of nodes are identical and can be safely merged."""
        if not nodes:
            return True

        first = nodes[0]

        # NEVER share operations - they should always be instruction-specific
        if first.data.get('type') == 'operation':
            return False

        for node in nodes[1:]:
            if (node.is_arch_state != first.is_arch_state or
                node.is_uarch_state != first.is_uarch_state or
                node.used_as_index != first.used_as_index):
                return False

            # Check data equality (excluding instruction-specific expressions)
            if not self._data_equivalent(first.data, node.data):
                return False

        # Special check for array access nodes: don't merge reads with writes
        if all(node.data.get('type') == 'array_access' for node in nodes):
            access_patterns = [self._classify_array_access_pattern(node) for node in nodes]

            # All access patterns must be the same to merge
            if len(set(access_patterns)) > 1:
                return False

        return True

    def _classify_array_access_pattern(self, node: Node) -> str:
        """Classify array access as 'read', 'write', or 'read_write'."""

        incoming_types = [e.data.get('type') for e in node.incoming_edges]
        outgoing_types = [e.data.get('type') for e in node.outgoing_edges]

        has_incoming_assignment = 'assignment' in incoming_types
        has_outgoing_assignment = 'assignment' in outgoing_types

        if has_incoming_assignment and not has_outgoing_assignment:
            return 'write'
        elif has_outgoing_assignment and not has_incoming_assignment:
            return 'read'
        elif has_incoming_assignment and has_outgoing_assignment:
            return 'read_write'
        else:
            return 'index_only'  # Only array_index edges

    def _data_equivalent(self, data1: Dict, data2: Dict) -> bool:
        """Check if two node data dictionaries are equivalent for sharing."""
        if not data1 and not data2:
            return True
        if not data1 or not data2:
            return False

        # Check basic properties
        for key in ['type', 'name', 'display_name', 'bit_width', 'array_depth', 'is_memory']:
            if data1.get(key) != data2.get(key):
                return False

        # Don't compare expressions - they may be instruction-specific
        return True

    def _build_global_aspect_order(self):
        """Build global aspect ordering per state from ISA file priority declarations.

        Each instruction provides a partial order of aspects for each state
        (via :N priority syntax in gates clauses). We merge all partial orders
        into a global total order per state using topological sort.

        Stores result in self._aspect_order_per_state:
            {state_name: {aspect_file: rank}} where lower rank = higher priority.
        """
        from collections import defaultdict, deque

        # Collect per-instruction priority declarations: state -> instr -> [(aspect, priority)]
        per_instr_per_state = defaultdict(lambda: defaultdict(list))
        for instr_name, graph in self.graphs.items():
            for aspect_decl in graph.aspect_declarations:
                for state_name, priority in aspect_decl.get('prioritized_states', {}).items():
                    per_instr_per_state[state_name][instr_name].append(
                        (aspect_decl['file'], priority)
                    )

        self._aspect_order_per_state = {}
        for state_name, instrs in per_instr_per_state.items():
            # Collect pairwise constraints from all instructions:
            # If aspect A has lower priority number than B in any instruction,
            # then A has higher priority (A should come before B in the mux).
            constraints = set()  # (higher_priority_aspect, lower_priority_aspect)
            all_aspects = set()

            for instr_name, aspects in instrs.items():
                sorted_aspects = sorted(aspects, key=lambda x: x[1])
                all_aspects.update(a[0] for a in sorted_aspects)
                for i in range(len(sorted_aspects)):
                    for j in range(i + 1, len(sorted_aspects)):
                        constraints.add((sorted_aspects[i][0], sorted_aspects[j][0]))

            # Topological sort (Kahn's algorithm)
            adj = defaultdict(set)
            in_degree = {a: 0 for a in all_aspects}
            for higher, lower in constraints:
                if lower not in adj[higher]:
                    adj[higher].add(lower)
                    in_degree[lower] += 1

            queue = deque(sorted(a for a in all_aspects if in_degree[a] == 0))
            order = []
            while queue:
                node = queue.popleft()
                order.append(node)
                for neighbor in sorted(adj[node]):
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        queue.append(neighbor)

            if len(order) != len(all_aspects):
                print(f"WARNING: Cycle in aspect ordering for state {state_name}")
                order = sorted(all_aspects)

            self._aspect_order_per_state[state_name] = {
                aspect: rank for rank, aspect in enumerate(order)
            }

        if self._aspect_order_per_state:
            print(f"Global aspect ordering for {len(self._aspect_order_per_state)} states:")
            for state_name, order in sorted(self._aspect_order_per_state.items()):
                aspects_sorted = sorted(order.items(), key=lambda x: x[1])
                names = [f"{a.rsplit('/', 1)[-1]}:{r}" for a, r in aspects_sorted]
                print(f"  {state_name}: {' > '.join(names)}")

    def _mux_shared_orthogon_inputs(self, merged_graph: ResourceGraph, tracker: 'GroupTracker'):
        """Create muxes for collision inputs feeding shared orthogon nodes.

        When an orthogon node (e.g., addr_mode_imm_sel_match) is shared across
        instructions but its input (addr_sel) is instruction-specific (collision),
        multiple edges exist from different collision variants to the same shared
        node.  This method detects that pattern, creates a gated mux that selects
        the correct collision variant based on instruction enables, and replaces
        the fan-in with a single edge from the mux.
        """
        from collections import OrderedDict

        # Step 1: Find collision sources feeding shared orthogon nodes.
        # Group by the collision node's original_id so we create one mux per
        # unique collision input regardless of how many orthogon nodes use it.
        collision_groups = OrderedDict()  # original_id -> {'sources': {}, 'edges': []}

        for node_id, node in list(merged_graph.nodes.items()):
            if not node.data.get('from_orthogon'):
                continue

            for edge in list(node.incoming_edges):
                src = edge.source
                orig_id = src.data.get('original_id')
                if orig_id is None:
                    continue  # Not a collision node

                if orig_id not in collision_groups:
                    collision_groups[orig_id] = {'sources': OrderedDict(), 'edges': []}

                info = collision_groups[orig_id]
                if src.id not in info['sources']:
                    instrs = src.data.get('group_members',
                                          [src.data.get('instruction', '')])
                    info['sources'][src.id] = (src, set(instrs))
                info['edges'].append(edge)

        # Step 2: For each collision input with multiple sources, create a mux.
        mux_nodes = {}  # original_id -> mux_node
        for orig_id, info in collision_groups.items():
            sources = info['sources']
            if len(sources) <= 1:
                continue

            first_src = next(iter(sources.values()))[0]
            bit_width = first_src.data.get('bit_width')
            if bit_width is None:
                # Try to infer from bit_range
                br = first_src.data.get('bit_range')
                if br and len(br) == 2:
                    bit_width = br[0] - br[1] + 1
                else:
                    bit_width = 8

            mux_id = f"{orig_id}_shared_mux"
            mux_node = Node(
                node_id=mux_id,
                data={
                    'type': 'multiplexer',
                    'name': mux_id,
                    'display_name': f"{orig_id} (shared)",
                    'operation': 'priority_select',
                    'gated_write_mux': True,
                    'bit_width': bit_width,
                },
            )
            mux_node.is_shared = True
            merged_graph.add_node(mux_node)
            mux_nodes[orig_id] = mux_node

            # Add mux inputs from each collision source, gated by enables.
            for idx, (src_id, (src_node, instrs)) in enumerate(sources.items()):
                enable_nodes = []
                for instr in sorted(instrs):
                    enable_id = f"{instr}_enable"
                    if enable_id in merged_graph.nodes:
                        enable_nodes.append(merged_graph.nodes[enable_id])

                if len(enable_nodes) == 1:
                    select_node = enable_nodes[0]
                elif len(enable_nodes) > 1:
                    or_id = f"{mux_id}_sel{idx}_or"
                    or_node = Node(
                        or_id,
                        data={
                            'type': 'operation',
                            'operator': '||',
                            'bit_width': 1,
                        },
                    )
                    or_node.is_shared = True
                    merged_graph.add_node(or_node)
                    for i, en in enumerate(enable_nodes):
                        Edge(source=en, target=or_node,
                             data={'type': 'operand', 'operand_index': i})
                    select_node = or_node
                else:
                    select_node = None

                Edge(source=src_node, target=mux_node,
                     data={'type': 'mux_input', 'input_index': idx})

                if select_node:
                    Edge(source=select_node, target=mux_node,
                         data={'type': 'mux_select', 'select_index': idx})

            print(f"  Created {mux_id} ({len(sources)} inputs) "
                  f"for {len(info['edges'])} edges to orthogon nodes")

        if not mux_nodes:
            return

        # Step 3: Replace collision edges with single edges from the mux.
        for orig_id, info in collision_groups.items():
            if orig_id not in mux_nodes:
                continue

            mux_node = mux_nodes[orig_id]

            # Deduplicate: one edge per (target_node, edge_type, position_key)
            seen = set()
            for edge in info['edges']:
                target = edge.target
                edge_data = dict(edge.data) if edge.data else {}
                edge_type = edge_data.get('type', '')
                pos_key = (edge_data.get('operand_position', ''),
                           edge_data.get('operand_index', ''),
                           edge_data.get('orthogon_selector', False))

                # Remove the old edge from the collision variant
                merged_graph.remove_edge(edge.id)

                # Add new edge from mux to target (deduplicate)
                key = (target.id, edge_type, pos_key)
                if key not in seen:
                    Edge(source=mux_node, target=target, data=edge_data)
                    seen.add(key)

        print(f"  Muxed {len(mux_nodes)} collision inputs to shared orthogon nodes")

    def _create_decode_logic(self, graph: ResourceGraph):
        """Create instruction decode logic in the merged graph."""
        print("Creating instruction decode logic...")

        decode_builder = InstructionDecodeBuilder(graph)

        # Create decode enable signals for each instruction
        for instr_name, decode_info in self.decode_info.items():
            # Get the instruction node for this graph
            instr_node_id = self.instruction_nodes.get(instr_name, '')

            # Create decode enable node
            enable_node = decode_builder.create_instruction_enable_node(
                instr_name,
                decode_conditions=decode_info.assume_conditions
            )

            # Create decode logic based on assume conditions
            self._create_decode_comparisons(graph, enable_node, decode_info, instr_node_id)

    def _create_decode_comparisons(self, graph: ResourceGraph, enable_node: Node, decode_info: InstructionDecodeInfo, instr_node_id: str):
        """Create comparison nodes for instruction decode."""
        decode_builder = InstructionDecodeBuilder(graph)

        # Check if this is an ILA instruction with existing decode signal
        if decode_info.decode_signal_node:
            # ILA instruction - the decode comparisons already exist in the graph
            # Check both prefixed (instruction-specific) and unprefixed (shared) versions
            instr_name = decode_info.instruction_name
            prefixed_id = f"{instr_name}_{decode_info.decode_signal_node}"
            unprefixed_id = decode_info.decode_signal_node

            # Try prefixed first, then unprefixed
            decode_signal_node = graph.nodes.get(prefixed_id) or graph.nodes.get(unprefixed_id)
            decode_signal_node_id = prefixed_id if prefixed_id in graph.nodes else unprefixed_id

            if decode_signal_node:
                # Create a decode_enable edge from the decode signal to the enable node
                edge = Edge(
                    source=decode_signal_node,
                    target=enable_node,
                    edge_id=f"{decode_signal_node_id}_to_{enable_node.id}",
                    data={'type': 'decode_enable', 'label': 'decode_enable'}
                )
                graph.add_edge(edge)
                print(f"  Connected decode signal {decode_signal_node_id} to {enable_node.id}")
            else:
                print(f"  Warning: Could not find decode signal node {decode_signal_node_id} for {decode_info.instruction_name}")
        else:
            # ISA instruction - create new decode comparison nodes
            comparison_nodes = []

            # Get the instruction node once for all comparisons
            instr_node = graph.nodes.get(instr_node_id) if instr_node_id else None

            for field_expr, operator, value in decode_info.assume_conditions:
                # Parse field expression to AST
                field_ast = self._parse_field_expression(field_expr)

                # Determine the correct source node for this comparison.
                # For instr-based expressions (e.g., instr[15:6], instr), use the instr node.
                # For other variables (e.g., movem_l_d1_predec_mask, pal_mode), find their
                # node in the graph so the comparison gets wired to the correct signal.
                source_node = instr_node
                var_name = None
                if field_ast and field_ast.get('type') == 'identifier' and field_ast.get('name') != 'instr':
                    var_name = field_ast['name']
                elif field_ast and field_ast.get('type') == 'bit_slice':
                    base_name = field_ast['array']['name'] if 'array' in field_ast else None
                    if base_name and base_name != 'instr':
                        var_name = base_name

                if var_name:
                    # Try to find the variable node in the graph
                    # First, try the _rd read node (for ISA state variables)
                    var_node = graph.nodes.get(f"{var_name}_rd")
                    if not var_node:
                        # Try the exact name (for local vars)
                        var_node = graph.nodes.get(var_name)
                    if not var_node:
                        # Try with instruction name prefix (variables may be prefixed during merge)
                        instr_name = decode_info.instruction_name
                        var_node = graph.nodes.get(f"{instr_name}_{var_name}")
                    if not var_node:
                        # Search through all graph nodes for one matching this variable
                        for nid, node in graph.nodes.items():
                            if nid.endswith(f"_{var_name}") or nid == var_name:
                                var_node = node
                                break
                    if var_node:
                        source_node = var_node
                    else:
                        print(f"  WARNING: Could not find graph node for assume variable '{var_name}' (instr={decode_info.instruction_name})")

                # Check if value is a field reference (cross-instruction comparison)
                # e.g., "i1_instr[11:7]" instead of a literal like "7'b0110111"
                value_is_field_ref = ('[' in str(value) and ':' in str(value)
                                     and not str(value)[0].isdigit()
                                     and "'" not in str(value))

                if value_is_field_ref:
                    # Cross-instruction field comparison (e.g., i2_instr[19:15] == i1_instr[11:7])
                    # Create a two-operand comparison with bit-slice nodes on both sides
                    value_ast = self._parse_field_expression(value)
                    value_source_node = None
                    if value_ast and value_ast.get('type') == 'bit_slice':
                        val_base = value_ast['array']['name'] if 'array' in value_ast else None
                        if val_base:
                            # Look up the value's source node in the graph
                            for candidate_id in [val_base, f"{val_base}_rd",
                                                f"{decode_info.instruction_name}_{val_base}"]:
                                if candidate_id in graph.nodes:
                                    value_source_node = graph.nodes[candidate_id]
                                    break
                            if not value_source_node:
                                for nid, node in graph.nodes.items():
                                    if nid.endswith(f"_{val_base}") or nid == val_base:
                                        value_source_node = node
                                        break

                    if value_source_node and source_node:
                        # Create bit-slice nodes for both sides
                        left_slice = None
                        right_slice = None
                        if field_ast.get('type') == 'bit_slice':
                            lh = field_ast['high']['value'] if isinstance(field_ast.get('high'), dict) else field_ast.get('high', 0)
                            ll = field_ast['low']['value'] if isinstance(field_ast.get('low'), dict) else field_ast.get('low', 0)
                            left_slice = decode_builder.get_or_create_bitslice(source_node, lh, ll)
                        if value_ast.get('type') == 'bit_slice':
                            rh = value_ast['high']['value'] if isinstance(value_ast.get('high'), dict) else value_ast.get('high', 0)
                            rl = value_ast['low']['value'] if isinstance(value_ast.get('low'), dict) else value_ast.get('low', 0)
                            right_slice = decode_builder.get_or_create_bitslice(value_source_node, rh, rl)

                        if left_slice and right_slice:
                            # Create comparison node with two operand edges
                            sanitized_field = field_expr.replace('[', '_').replace(':', '_').replace(']', '')
                            sanitized_value = value.replace('[', '_').replace(':', '_').replace(']', '')
                            comp_id = f"{sanitized_field}_{operator.replace('==','eq').replace('!=','ne')}_{sanitized_value}"

                            if comp_id not in graph.nodes:
                                comp_data = {
                                    'type': 'comparison',
                                    'name': comp_id,
                                    'display_name': f"{field_expr} {operator} {value}",
                                    'operation': operator,
                                    'bit_width': 1,
                                }
                                comp_node = Node(comp_id, comp_data)
                                graph.add_node(comp_node)
                                # Wire both bit-slice nodes as operands
                                graph.add_edge(Edge(left_slice, comp_node,
                                    data={'type': 'operand'}))
                                graph.add_edge(Edge(right_slice, comp_node,
                                    data={'type': 'operand'}))
                            else:
                                comp_node = graph.nodes[comp_id]
                            comparison_nodes.append(comp_node)
                            continue
                        else:
                            print(f"  WARNING: Could not create bit-slice nodes for cross-instruction comparison: {field_expr} {operator} {value}")
                    else:
                        print(f"  WARNING: Could not find source nodes for cross-instruction comparison: {field_expr} {operator} {value}")

                # Create comparison node using builder (standard literal comparison)
                comp_node = decode_builder.create_decode_comparison(
                    enable_node.id,
                    field_expr,
                    operator,
                    value,
                    field_ast=field_ast,
                    source_node=source_node
                )
                comparison_nodes.append(comp_node)

            # Process OR groups: create OR gate for each group, add to comparison_nodes
            for group_idx, or_group in enumerate(decode_info.assume_or_groups):
                or_comp_nodes = []
                for field_expr, operator, value in or_group:
                    field_ast = self._parse_field_expression(field_expr)
                    source_node = instr_node
                    # For non-instr fields, find the source node
                    var_name = None
                    if field_ast and field_ast.get('type') == 'identifier' and field_ast.get('name') != 'instr':
                        var_name = field_ast['name']
                    if var_name:
                        var_node = graph.nodes.get(f"{var_name}_rd") or graph.nodes.get(var_name)
                        if var_node:
                            source_node = var_node
                    comp_node = decode_builder.create_decode_comparison(
                        enable_node.id,
                        field_expr,
                        operator,
                        value,
                        field_ast=field_ast,
                        source_node=source_node
                    )
                    or_comp_nodes.append(comp_node)

                if len(or_comp_nodes) == 1:
                    comparison_nodes.append(or_comp_nodes[0])
                elif len(or_comp_nodes) > 1:
                    # Create an OR gate combining all conditions in this group
                    or_id = f"{enable_node.id}_or_{group_idx}"
                    or_node = Node(or_id, {
                        'type': 'logical_or',
                        'name': or_id,
                        'operation': '||',
                        'bit_width': 1,
                    })
                    graph.add_node(or_node)
                    for comp_node in or_comp_nodes:
                        graph.add_edge(Edge(comp_node, or_node, data={'type': 'logic_input'}))
                    comparison_nodes.append(or_node)

            # Wire up decode logic using builder
            decode_builder.wire_decode_logic(comparison_nodes, enable_node)

    def _parse_field_expression(self, field_expr: str) -> Dict:
        """Parse field expression like 'instr[31:26]' or 'mem[op_13]_rd[31:26]' into AST."""
        if '[' not in field_expr:
            return {'type': 'identifier', 'name': field_expr}

        # Handle nested brackets (ILA case): mem[op_13]_rd[14:12]
        # Extract the LAST bracketed part as the slice
        last_open_bracket = field_expr.rfind('[')
        base = field_expr[:last_open_bracket]
        slice_part = field_expr[last_open_bracket + 1:].rstrip(']')

        if ':' in slice_part:
            high, low = slice_part.split(':', 1)
            return {
                'type': 'bit_slice',
                'array': {'type': 'identifier', 'name': base},
                'high': {'type': 'literal', 'value': int(high, 0)},
                'low': {'type': 'literal', 'value': int(low, 0)}
            }
        else:
            # Single bit access like instr[0] - treat as bit_slice with high == low
            # This ensures the Verilog generator handles it correctly for decode comparisons
            bit_index = int(slice_part, 0)
            return {
                'type': 'bit_slice',
                'array': {'type': 'identifier', 'name': base},
                'high': {'type': 'literal', 'value': bit_index},
                'low': {'type': 'literal', 'value': bit_index}
            }

    def _add_instruction_specific_nodes(self, merged_graph: ResourceGraph, instruction_specific_nodes: Dict[str, Set[str]], collision_dependents: Set[str] = None, node_remapping: Dict[str, Dict[str, str]] = None):
        """Add nodes that are unique to specific instructions (not creating duplicates of shared nodes)."""

        # First pass: identify nodes that appear in multiple instructions' specific sets
        # These might be shareable among a subset - check before creating prefixed versions
        node_instruction_count = {}
        for instr_name, node_ids in sorted(instruction_specific_nodes.items()):
            for node_id in sorted(node_ids):
                if node_id not in node_instruction_count:
                    node_instruction_count[node_id] = []
                node_instruction_count[node_id].append(instr_name)

        # Second pass: for nodes appearing in multiple instructions, check if they can actually share
        # Build a dummy node_usage dict for the recursive sharing check
        node_usage_for_check = {node_id: set(instrs) for node_id, instrs in node_instruction_count.items()}

        nodes_to_partially_share = {}  # node_id -> set of instructions

        # Initialize collision_dependents if not provided
        if collision_dependents is None:
            collision_dependents = set()

        # Initialize node_remapping if not provided
        if node_remapping is None:
            node_remapping = {instr: {} for instr in instruction_specific_nodes.keys()}

        for node_id, instr_list in list(node_instruction_count.items()):
            # Note: collision dependents CAN still be grouped if they have identical structure
            # For example, beq_sign_ext_imm and bge_sign_ext_imm may both depend on beq_imm
            # and should be grouped together

            if len(instr_list) > 1:
                # For variables, partition by assignment sources first
                # Filter to only instructions that actually have this node
                instr_list_with_node = [instr for instr in instr_list if node_id in self.graphs[instr].nodes]
                if not instr_list_with_node:
                    continue

                first_node = self.graphs[instr_list_with_node[0]].nodes[node_id]
                if first_node.data.get('type') == 'var':
                    # Group by assignment sources (including recursive checking of variable sources)
                    assignment_groups = {}
                    for instr in instr_list_with_node:
                        node = self.graphs[instr].nodes[node_id]
                        # Compute deep signature that includes variable assignment sources
                        source_signatures = []
                        for edge in node.incoming_edges:
                            if edge.data.get('type') == 'assignment':
                                sig = self._compute_deep_assignment_signature(edge.source, self.graphs[instr])
                                source_signatures.append(sig)
                        sources = frozenset(source_signatures)
                        if sources not in assignment_groups:
                            assignment_groups[sources] = []
                        assignment_groups[sources].append(instr)
                    # Check each group for partial sharing
                    #  If node_id is already partially shared from first pass, the remaining
                    # instructions can still share among themselves, but we need to track them
                    # separately to avoid prefixing
                    # IMPORTANT: If there are multiple assignment groups, each group needs a
                    # group-specific shared node (with prefix), not an unprefixed node
                    multiple_groups = len(assignment_groups) > 1

                    # If there are multiple assignment groups, remove the unprefixed version
                    # from partially_shared_nodes since it will be replaced by group-specific versions
                    partially_shared_instrs = set()
                    if multiple_groups and node_id in self.partially_shared_nodes:
                        partially_shared_instrs = self.partially_shared_nodes[node_id].copy()
                        del self.partially_shared_nodes[node_id]
                        print(f"  Removing unprefixed '{node_id}' from partially_shared (will use group-specific versions)")

                        # CRITICAL: Also check if partially-shared instructions form an additional assignment group
                        # that wasn't detected because they weren't in instruction_specific_nodes
                        if partially_shared_instrs and node_id in self.graphs[list(partially_shared_instrs)[0]].nodes:
                            first_instr = list(partially_shared_instrs)[0]
                            first_node_ps = self.graphs[first_instr].nodes[node_id]
                            if first_node_ps.data.get('type') == 'var':
                                # Compute signatures for partially-shared instructions
                                ps_groups = {}
                                for instr in partially_shared_instrs:
                                    if node_id in self.graphs[instr].nodes:
                                        node_ps = self.graphs[instr].nodes[node_id]
                                        source_sigs = []
                                        for edge in node_ps.incoming_edges:
                                            if edge.data.get('type') == 'assignment':
                                                sig = self._compute_deep_assignment_signature(edge.source, self.graphs[instr])
                                                source_sigs.append(sig)
                                        ps_sources = frozenset(source_sigs)
                                        if ps_sources not in ps_groups:
                                            ps_groups[ps_sources] = []
                                        ps_groups[ps_sources].append(instr)

                                # Add partially-shared groups to assignment_groups
                                for ps_sources, ps_instrs in ps_groups.items():
                                    if ps_sources not in assignment_groups:
                                        assignment_groups[ps_sources] = ps_instrs
                                        if node_id == 'imm':
                                            print(f"  Added partially-shared group for {node_id}: {len(ps_instrs)} instrs <- {ps_sources}")

                    for sources, group_instrs in assignment_groups.items():
                        # When there are multiple assignment groups, ALL groups need prefixes (even single-instruction groups)
                        # to avoid multiple drivers to the unprefixed node
                        process_as_group = len(group_instrs) > 1 or multiple_groups

                        if process_as_group:
                            nodes = [self.graphs[instr].nodes[node_id] for instr in group_instrs]
                            can_share = self._can_share_node_usage(node_id, nodes, node_usage_for_check) if len(group_instrs) > 1 else True

                            if can_share:
                                # These instructions can share (or it's a single-instruction group with multiple_groups=True)
                                # Remove from instruction-specific sets
                                for instr in group_instrs:
                                    instruction_specific_nodes[instr].discard(node_id)

                                # If there are multiple assignment groups, use group-specific prefix
                                # to avoid conflicts
                                if multiple_groups:
                                    group_prefix = sorted(group_instrs)[0]
                                    group_node_id = f"{group_prefix}_{node_id}"
                                    self.partially_shared_nodes[group_node_id] = set(group_instrs)
                                    print(f"Partially shared: {group_node_id} (used by {len(group_instrs)}/{len(self.graphs)}: {sorted(group_instrs)} - group-specific)")

                                    # CRITICAL: Add original node_id to group_specific_replacements to prevent
                                    # deferred edges from connecting to the unprefixed version
                                    if not hasattr(self, 'group_specific_replacements'):
                                        self.group_specific_replacements = set()
                                    self.group_specific_replacements.add(node_id)

                                    # Track remapping for edge copying
                                    for instr in group_instrs:
                                        node_remapping[instr][node_id] = group_node_id

                                    source_node = self.graphs[group_instrs[0]].nodes[node_id]
                                    new_data = source_node.data.copy() if source_node.data else {}
                                    new_data['original_id'] = node_id
                                    # Update the 'name' field to match the group-specific node ID for Verilog generation
                                    if 'name' in new_data:
                                        new_data['name'] = group_node_id
                                    new_node = Node(
                                        group_node_id, new_data,
                                        is_arch_state=source_node.is_arch_state,
                                        used_as_index=source_node.used_as_index,
                                        is_uarch_state=source_node.is_uarch_state,
                                        uarch_time=source_node.uarch_time,
                                        from_isa_spec=getattr(source_node, 'from_isa_spec', False),
                                        already_split=getattr(source_node, 'already_split', False)
                                    )
                                    merged_graph.add_node(new_node)

                                    # Copy edges for this group-specific node
                                    # NOTE: Only create edges when the source is NOT in merged graph
                                    # (i.e., needs to be created as a group-specific node).
                                    # When the source IS already in merged graph, skip the edge here
                                    # and let the deferred edge pass (which applies node_remapping
                                    # and group_specific_replacements) create the correct edge.
                                    for edge in source_node.incoming_edges:
                                        source_edge_id = edge.source.id
                                        if source_edge_id in merged_graph.nodes:
                                            # Skip - deferred edge pass will create correct edge
                                            # using node_remapping/group_specific_replacements
                                            pass
                                        else:
                                            # Source node not in merged graph yet
                                            # This can happen when the source is a bit_slice or operation
                                            # that's only used by this group of instructions
                                            # We need to add it to the merged graph as a shared node

                                            # Add the source node to the merged graph if it exists in any instruction graph
                                            # CRITICAL: Create a group-specific version since this source is only used by this group
                                            group_source_id = f"{group_prefix}_{source_edge_id}"
                                            for instr in group_instrs:
                                                if source_edge_id in self.graphs[instr].nodes:
                                                    src_node = self.graphs[instr].nodes[source_edge_id]
                                                    # Create a copy of the source node in merged graph WITH GROUP PREFIX
                                                    new_src_data = src_node.data.copy() if src_node.data else {}
                                                    new_src_data['original_id'] = source_edge_id
                                                    if 'name' in new_src_data:
                                                        new_src_data['name'] = group_source_id
                                                    new_src_node = Node(
                                                        group_source_id, new_src_data,
                                                        is_arch_state=src_node.is_arch_state,
                                                        used_as_index=src_node.used_as_index,
                                                        is_uarch_state=src_node.is_uarch_state,
                                                        uarch_time=src_node.uarch_time,
                                                        from_isa_spec=getattr(src_node, 'from_isa_spec', False),
                                                        already_split=getattr(src_node, 'already_split', False)
                                                    )
                                                    merged_graph.add_node(new_src_node)
                                                    self.partially_shared_nodes[group_source_id] = set(group_instrs)
                                                    if node_id in ['imm', 'sign_ext_imm']:
                                                        print(f"    Added missing group-specific source node {group_source_id} to merged graph")

                                                    # Track remapping so other nodes can find this group-specific version
                                                    for instr in group_instrs:
                                                        node_remapping[instr][source_edge_id] = group_source_id

                                                    # Mark original as having group-specific replacements
                                                    if not hasattr(self, 'group_specific_replacements'):
                                                        self.group_specific_replacements = set()
                                                    self.group_specific_replacements.add(source_edge_id)

                                                    # Now create the edge using the group-specific ID
                                                    new_edge = Edge(merged_graph.nodes[group_source_id], new_node,
                                                                  data=edge.data.copy() if edge.data else {})
                                                    merged_graph.add_edge(new_edge)

                                                    # Also copy incoming edges to this newly added source node
                                                    for src_edge in src_node.incoming_edges:
                                                        if src_edge.source.id in merged_graph.nodes:
                                                            src_new_edge = Edge(merged_graph.nodes[src_edge.source.id], new_src_node,
                                                                              data=src_edge.data.copy() if src_edge.data else {})
                                                            merged_graph.add_edge(src_new_edge)
                                                    break  # Only need to add once
                                    # Don't copy outgoing edges here - deferred edge pass handles them.

                                    # PROPAGATE GROUP-SPECIFIC SHARING TO DEPENDENT NODES
                                    # Now that we've created a group-specific node (e.g., beq_imm),
                                    # find all nodes in these instructions that depend on it (transitively)
                                    # and make them group-specific too (e.g., beq_imm[12:12], beq_sign_ext_imm, etc.)
                                    # Use iterative BFS to handle multi-level dependencies
                                    nodes_to_process = [node_id]  # Start with the newly created group-specific node
                                    processed = set()

                                    while nodes_to_process:
                                        current_node_id = nodes_to_process.pop(0)
                                        if current_node_id in processed:
                                            continue
                                        processed.add(current_node_id)

                                        # Find all nodes in the group that depend on current_node_id
                                        dependent_nodes_to_group = set()
                                        for instr in group_instrs:
                                            source_graph = self.graphs[instr]
                                            if current_node_id in source_graph.nodes:
                                                # Find all nodes that directly reference this node
                                                for edge in source_graph.nodes[current_node_id].outgoing_edges:
                                                    dep_node_id = edge.target.id
                                                    # Consider nodes that are:
                                                    # 1. Currently instruction-specific
                                                    # 2. Partially shared but need to be made group-specific because they depend on a group-specific node
                                                    is_instruction_specific = dep_node_id in instruction_specific_nodes.get(instr, set())
                                                    is_partially_shared_dependent = dep_node_id in self.partially_shared_nodes
                                                    if is_instruction_specific or is_partially_shared_dependent:
                                                        dependent_nodes_to_group.add(dep_node_id)

                                        # For each dependent node, check if all instructions in the group have it
                                        for dep_node_id in dependent_nodes_to_group:
                                            if dep_node_id in processed:
                                                continue
                                            # Skip nodes that were already marked as collision dependents (must stay instruction-specific)
                                            if dep_node_id in collision_dependents:
                                                continue
                                            # Check if all instructions in this group have this dependent node
                                            instrs_with_dep = [i for i in group_instrs if dep_node_id in self.graphs[i].nodes]
                                            if len(instrs_with_dep) == len(group_instrs):
                                                # All instructions in the group have this node - check if it can be group-shared
                                                dep_nodes = [self.graphs[i].nodes[dep_node_id] for i in instrs_with_dep]
                                                if self._nodes_structurally_identical(dep_nodes):
                                                    # Check if all incoming dependencies are sharable by this group
                                                    # If any dependency is instruction-specific (not in this group), skip
                                                    can_share = True
                                                    first_dep_node = self.graphs[instrs_with_dep[0]].nodes[dep_node_id]
                                                    for edge in first_dep_node.incoming_edges:
                                                        dep_source_id = edge.source.id
                                                        # Check if this dependency is instruction-specific
                                                        if dep_source_id in instruction_specific_nodes.get(instrs_with_dep[0], set()):
                                                            # This is instruction-specific - can't group-share the dependent
                                                            can_share = False
                                                            break
                                                        # Also check if this dependency has DIFFERENT values across instructions
                                                        # (e.g., 'res' for branches has different comparison operations)
                                                        if dep_source_id in self.graphs[instrs_with_dep[0]].nodes:
                                                            source_nodes_for_dep = []
                                                            for instr in instrs_with_dep:
                                                                if dep_source_id in self.graphs[instr].nodes:
                                                                    source_nodes_for_dep.append(self.graphs[instr].nodes[dep_source_id])
                                                            if len(source_nodes_for_dep) == len(instrs_with_dep):
                                                                if not self._nodes_structurally_identical(source_nodes_for_dep):
                                                                    # Dependency has different values across instructions
                                                                    can_share = False
                                                                    break

                                                    if not can_share:
                                                        continue  # Skip this dependent node

                                                    # Create group-specific node for this dependent
                                                    group_dep_node_id = f"{group_prefix}_{dep_node_id}"

                                                    # Remove from instruction-specific
                                                    for instr in instrs_with_dep:
                                                        instruction_specific_nodes[instr].discard(dep_node_id)

                                                    # Track remapping
                                                    for instr in instrs_with_dep:
                                                        node_remapping[instr][dep_node_id] = group_dep_node_id

                                                    # Create the node
                                                    dep_source_node = self.graphs[instrs_with_dep[0]].nodes[dep_node_id]
                                                    dep_new_data = dep_source_node.data.copy() if dep_source_node.data else {}
                                                    dep_new_data['original_id'] = dep_node_id
                                                    if 'name' in dep_new_data:
                                                        dep_new_data['name'] = group_dep_node_id

                                                    # For ternary nodes, update expression data to use group-prefixed identifiers
                                                    if dep_new_data.get('type') == 'ternary_op' and 'expression' in dep_new_data:
                                                        import copy
                                                        dep_new_data['expression'] = copy.deepcopy(dep_new_data['expression'])
                                                        expr = dep_new_data['expression']
                                                        # Helper to update identifier in an expression part
                                                        def update_identifier(expr_part):
                                                            if expr_part.get('type') == 'identifier':
                                                                name = expr_part['name']
                                                                if name in node_remapping.get(instrs_with_dep[0], {}):
                                                                    expr_part['name'] = node_remapping[instrs_with_dep[0]][name]
                                                        # Update all three parts of the ternary
                                                        update_identifier(expr.get('condition', {}))
                                                        update_identifier(expr.get('if_true', {}))
                                                        update_identifier(expr.get('if_false', {}))

                                                    dep_new_node = Node(
                                                        group_dep_node_id, dep_new_data,
                                                        is_arch_state=dep_source_node.is_arch_state,
                                                        used_as_index=dep_source_node.used_as_index,
                                                        is_uarch_state=dep_source_node.is_uarch_state,
                                                        uarch_time=dep_source_node.uarch_time,
                                                        from_isa_spec=getattr(dep_source_node, 'from_isa_spec', False),
                                                        already_split=getattr(dep_source_node, 'already_split', False)
                                                    )
                                                    merged_graph.add_node(dep_new_node)
                                                    self.partially_shared_nodes[group_dep_node_id] = set(instrs_with_dep)
                                                    print(f"  Propagated group sharing: {group_dep_node_id}")

                                                    # Process this node's dependents in the next iteration
                                                    nodes_to_process.append(dep_node_id)

                                                    # Track that we created a group-specific version of this node
                                                    # so we can remove the unprefixed version later
                                                    if not hasattr(self, 'group_specific_replacements'):
                                                        self.group_specific_replacements = set()
                                                    self.group_specific_replacements.add(dep_node_id)

                                # If node_id is not yet in merged graph, add it as partial sharing
                                elif node_id not in merged_graph.nodes:
                                    self.partially_shared_nodes[node_id] = set(group_instrs)
                                    print(f"Partially shared: {node_id} (used by {len(group_instrs)}/{len(self.graphs)}: {sorted(group_instrs)})")
                                    source_node = self.graphs[group_instrs[0]].nodes[node_id]
                                    new_data = source_node.data.copy() if source_node.data else {}
                                    new_node = Node(
                                        node_id, new_data,
                                        is_arch_state=source_node.is_arch_state,
                                        used_as_index=source_node.used_as_index,
                                        is_uarch_state=source_node.is_uarch_state,
                                        uarch_time=source_node.uarch_time,
                                        from_isa_spec=getattr(source_node, 'from_isa_spec', False),
                                        already_split=getattr(source_node, 'already_split', False)
                                    )
                                    merged_graph.add_node(new_node)
                                else:
                                    # Node exists - check if it has the same assignment sources
                                    existing_node = merged_graph.nodes[node_id]
                                    existing_sources = frozenset(
                                        edge.source.data.get('display_name', edge.source.id)
                                        for edge in existing_node.incoming_edges
                                        if edge.data.get('type') == 'assignment'
                                    )
                                    if existing_sources == sources:
                                        # Same sources - can share the existing node
                                        nodes_to_partially_share[node_id] = set(group_instrs)
                                        print(f"Additional sharing: {node_id} (used by {len(group_instrs)}/{len(self.graphs)}: {sorted(group_instrs)} - sharing existing node)")
                                    else:
                                        # Different sources - these instructions can share among themselves
                                        # but not with the existing node. Create a group-specific shared node.
                                        # Use a representative instruction name as prefix to avoid collision
                                        group_prefix = sorted(group_instrs)[0]  # e.g., 'auipc' for ['auipc', 'lui']
                                        group_node_id = f"{group_prefix}_{node_id}"

                                        # Remove from instruction-specific (already done above)
                                        # Add as a new partially-shared node with group prefix
                                        self.partially_shared_nodes[group_node_id] = set(group_instrs)
                                        print(f"Partially shared: {group_node_id} (used by {len(group_instrs)}/{len(self.graphs)}: {sorted(group_instrs)} - different from existing {node_id})")

                                        # Track remapping for edge copying
                                        for instr in group_instrs:
                                            node_remapping[instr][node_id] = group_node_id

                                        source_node = self.graphs[group_instrs[0]].nodes[node_id]
                                        new_data = source_node.data.copy() if source_node.data else {}
                                        new_data['original_id'] = node_id  # Track original for edge remapping
                                        # Update the 'name' field to match the group-specific node ID for Verilog generation
                                        if 'name' in new_data:
                                            new_data['name'] = group_node_id
                                        new_node = Node(
                                            group_node_id, new_data,
                                            is_arch_state=source_node.is_arch_state,
                                            used_as_index=source_node.used_as_index,
                                            is_uarch_state=source_node.is_uarch_state,
                                            uarch_time=source_node.uarch_time,
                                            from_isa_spec=getattr(source_node, 'from_isa_spec', False),
                                            already_split=getattr(source_node, 'already_split', False)
                                        )
                                        merged_graph.add_node(new_node)

                                        # Don't copy edges here - the deferred edge pass will create
                                        # correct edges using node_remapping/group_specific_replacements.
                                        # Early edge copying can connect to wrong shared nodes when
                                        # the correct instruction-specific version hasn't been created yet.

                                        # PROPAGATE GROUP-SPECIFIC SHARING TO DEPENDENT NODES (same as above)
                                        nodes_to_process = [node_id]
                                        processed = set()

                                        while nodes_to_process:
                                            current_node_id = nodes_to_process.pop(0)
                                            if current_node_id in processed:
                                                continue
                                            processed.add(current_node_id)

                                            dependent_nodes_to_group = set()
                                            for instr in group_instrs:
                                                source_graph = self.graphs[instr]
                                                if current_node_id in source_graph.nodes:
                                                    for edge in source_graph.nodes[current_node_id].outgoing_edges:
                                                        dep_node_id = edge.target.id
                                                        if dep_node_id in instruction_specific_nodes.get(instr, set()):
                                                            dependent_nodes_to_group.add(dep_node_id)

                                            for dep_node_id in dependent_nodes_to_group:
                                                if dep_node_id in processed:
                                                    continue
                                                instrs_with_dep = [i for i in group_instrs if dep_node_id in self.graphs[i].nodes]
                                                if len(instrs_with_dep) == len(group_instrs):
                                                    dep_nodes = [self.graphs[i].nodes[dep_node_id] for i in instrs_with_dep]
                                                    if self._nodes_structurally_identical(dep_nodes):
                                                        # Check if all incoming dependencies are sharable
                                                        can_share = True
                                                        first_dep_node = self.graphs[instrs_with_dep[0]].nodes[dep_node_id]
                                                        for edge in first_dep_node.incoming_edges:
                                                            dep_source_id = edge.source.id
                                                            if dep_source_id in instruction_specific_nodes.get(instrs_with_dep[0], set()):
                                                                can_share = False
                                                                break

                                                        if not can_share:
                                                            continue

                                                        group_dep_node_id = f"{group_prefix}_{dep_node_id}"

                                                        for instr in instrs_with_dep:
                                                            instruction_specific_nodes[instr].discard(dep_node_id)

                                                        for instr in instrs_with_dep:
                                                            node_remapping[instr][dep_node_id] = group_dep_node_id

                                                        dep_source_node = self.graphs[instrs_with_dep[0]].nodes[dep_node_id]
                                                        dep_new_data = dep_source_node.data.copy() if dep_source_node.data else {}
                                                        dep_new_data['original_id'] = dep_node_id
                                                        if 'name' in dep_new_data:
                                                            dep_new_data['name'] = group_dep_node_id

                                                        # For ternary nodes, update expression data to use group-prefixed identifiers
                                                        if dep_new_data.get('type') == 'ternary_op' and 'expression' in dep_new_data:
                                                            import copy
                                                            dep_new_data['expression'] = copy.deepcopy(dep_new_data['expression'])
                                                            expr = dep_new_data['expression']
                                                            # Helper to update identifier in an expression part
                                                            def update_identifier(expr_part):
                                                                if expr_part.get('type') == 'identifier':
                                                                    name = expr_part['name']
                                                                    if name in node_remapping.get(instrs_with_dep[0], {}):
                                                                        expr_part['name'] = node_remapping[instrs_with_dep[0]][name]
                                                            # Update all three parts of the ternary
                                                            update_identifier(expr.get('condition', {}))
                                                            update_identifier(expr.get('if_true', {}))
                                                            update_identifier(expr.get('if_false', {}))

                                                        dep_new_node = Node(
                                                            group_dep_node_id, dep_new_data,
                                                            is_arch_state=dep_source_node.is_arch_state,
                                                            used_as_index=dep_source_node.used_as_index,
                                                            is_uarch_state=dep_source_node.is_uarch_state,
                                                            uarch_time=dep_source_node.uarch_time,
                                                            from_isa_spec=getattr(dep_source_node, 'from_isa_spec', False),
                                                            already_split=getattr(dep_source_node, 'already_split', False)
                                                        )
                                                        merged_graph.add_node(dep_new_node)
                                                        self.partially_shared_nodes[group_dep_node_id] = set(instrs_with_dep)
                                                        print(f"  Propagated group sharing: {group_dep_node_id}")

                                                        nodes_to_process.append(dep_node_id)

                                                        # Track that we created a group-specific version of this node
                                                        if not hasattr(self, 'group_specific_replacements'):
                                                            self.group_specific_replacements = set()
                                                        self.group_specific_replacements.add(dep_node_id)

                                # Continue to next group (don't break - process all assignment groups)
                else:
                    # Not a variable - check all together
                    nodes = [self.graphs[instr].nodes[node_id] for instr in instr_list_with_node]
                    if self._nodes_structurally_identical(nodes) and self._can_share_node_usage(node_id, nodes, node_usage_for_check):
                        # These can be partially shared!
                        nodes_to_partially_share[node_id] = set(instr_list_with_node)
                        self.partially_shared_nodes[node_id] = set(instr_list_with_node)
                        print(f"Partially shared: {node_id} (used by {len(instr_list_with_node)}/{len(self.graphs)}: {sorted(instr_list_with_node)})")
                        # Remove from instruction-specific sets
                        for instr in instr_list_with_node:
                            instruction_specific_nodes[instr].discard(node_id)
                        # Add to merged graph if not already there
                        if node_id not in merged_graph.nodes:
                            source_node = self.graphs[instr_list_with_node[0]].nodes[node_id]
                            new_data = source_node.data.copy() if source_node.data else {}
                            new_node = Node(
                                node_id, new_data,
                                is_arch_state=source_node.is_arch_state,
                                used_as_index=source_node.used_as_index,
                                is_uarch_state=source_node.is_uarch_state,
                                uarch_time=source_node.uarch_time,
                                from_isa_spec=getattr(source_node, 'from_isa_spec', False),
                                already_split=getattr(source_node, 'already_split', False)
                            )
                            merged_graph.add_node(new_node)

        # Rebuild node_instruction_count after removing partially shared nodes
        node_instruction_count = {}
        for instr_name, node_ids in sorted(instruction_specific_nodes.items()):
            for node_id in sorted(node_ids):
                if node_id not in node_instruction_count:
                    node_instruction_count[node_id] = []
                node_instruction_count[node_id].append(instr_name)

        # Remove unprefixed nodes that will be replaced with prefixed versions
        # When a node appears in multiple instructions, we create ADD_node, ADDI_node, etc.
        # The original unprefixed 'node' from the base graph must be removed
        # BUT: Don't remove if it's partially shared (some instructions still need the unprefixed version)
        nodes_to_remove = []
        for node_id, instr_list in node_instruction_count.items():
            if len(instr_list) > 1 and node_id in merged_graph.nodes:
                # Check if this node is partially shared (meaning some instructions still need the unprefixed version)
                if node_id in self.partially_shared_nodes:
                    # This node is partially shared - keep the unprefixed version for those instructions
                    shared_instrs = self.partially_shared_nodes[node_id]
                    # Only remove if ALL instructions using this node are getting prefixed versions
                    if set(instr_list) == set(shared_instrs):
                        # All users are getting prefixed versions - safe to remove
                        nodes_to_remove.append(node_id)
                        print(f"Removing unprefixed node {node_id} (will be replaced by {', '.join([f'{i}_{node_id}' for i in instr_list])})")
                    else:
                        # Some instructions still need the unprefixed version
                        print(f"Keeping unprefixed node {node_id} (partially shared by {shared_instrs}, prefixed versions for {instr_list})")
                else:
                    # Not partially shared - safe to remove
                    nodes_to_remove.append(node_id)
                    print(f"Removing unprefixed node {node_id} (will be replaced by {', '.join([f'{i}_{node_id}' for i in instr_list])})")

        # Also remove unprefixed nodes that were replaced by group-specific versions
        if hasattr(self, 'group_specific_replacements'):
            for node_id in sorted(self.group_specific_replacements):
                if node_id in merged_graph.nodes and node_id not in nodes_to_remove:
                    nodes_to_remove.append(node_id)
                    print(f"Removing unprefixed node {node_id} (replaced by group-specific versions)")

        for node_id in nodes_to_remove:
            merged_graph.remove_node(node_id)

        for instr_name, node_ids in sorted(instruction_specific_nodes.items()):
            source_graph = self.graphs[instr_name]

            for node_id in sorted(node_ids):
                # Skip if this node doesn't actually exist in this instruction's graph
                if node_id not in source_graph.nodes:
                    continue
                source_node = source_graph.nodes[node_id]

                # Determine if this node appears in multiple instructions
                appears_in_multiple = len(node_instruction_count[node_id]) > 1

                if appears_in_multiple:
                    # This node appears in multiple instructions - use instruction prefix
                    prefixed_node_id = f"{instr_name}_{node_id}"

                    # Create a copy of the node with instruction prefix
                    new_data = source_node.data.copy() if source_node.data else {}
                    new_data['instruction'] = instr_name
                    # Update the name field to match the prefixed ID so Verilog generator uses the correct name
                    if 'name' in new_data:
                        new_data['name'] = prefixed_node_id
                    if 'display_name' in new_data:
                        new_data['display_name'] = prefixed_node_id

                    new_node = Node(
                        prefixed_node_id, new_data,
                        # Instruction-specific copies are NOT architectural state
                        # Only the shared version (without instruction prefix) is arch state
                        is_arch_state=False,
                        used_as_index=source_node.used_as_index,
                        is_uarch_state=source_node.is_uarch_state,
                        uarch_time=source_node.uarch_time,
                        from_isa_spec=getattr(source_node, 'from_isa_spec', False),
                        already_split=getattr(source_node, 'already_split', False)
                    )

                    merged_graph.add_node(new_node)
                    print(f"Added instruction-specific node: {prefixed_node_id} (from {instr_name})")
                else:
                    # This node is unique to this instruction - no prefix needed
                    # Only add if this node is NOT already in the merged graph
                    if node_id not in merged_graph.nodes:
                        # Create a copy of the node
                        new_data = source_node.data.copy() if source_node.data else {}
                        new_data['instruction'] = instr_name

                        new_node = Node(
                            node_id, new_data,
                            is_arch_state=source_node.is_arch_state,
                            used_as_index=source_node.used_as_index,
                            is_uarch_state=source_node.is_uarch_state,
                            uarch_time=source_node.uarch_time,
                            from_isa_spec=getattr(source_node, 'from_isa_spec', False),
                            already_split=getattr(source_node, 'already_split', False)
                        )

                        merged_graph.add_node(new_node)
                        print(f"Added instruction-specific node: {node_id} (from {instr_name})")

        # Now add edges for instruction-specific nodes
        for instr_name, node_ids in sorted(instruction_specific_nodes.items()):
            source_graph = self.graphs[instr_name]

            for node_id in sorted(node_ids):
                # Skip if this node doesn't actually exist in this instruction's graph
                if node_id not in source_graph.nodes:
                    continue
                source_node = source_graph.nodes[node_id]

                # Determine actual node ID in merged graph (might be prefixed)
                appears_in_multiple = len(node_instruction_count[node_id]) > 1
                if appears_in_multiple:
                    merged_node_id = f"{instr_name}_{node_id}"
                else:
                    merged_node_id = node_id

                if merged_node_id in merged_graph.nodes:  # Node exists in merged graph
                    merged_node = merged_graph.nodes[merged_node_id]

                    # Copy edges from source graph (avoiding duplicates)
                    for edge in source_node.incoming_edges:
                        source_id = edge.source.id
                        # Check if source node was remapped to a group-specific shared node
                        if source_id in node_remapping[instr_name]:
                            actual_source_id = node_remapping[instr_name][source_id]
                        # Check if source node might have been prefixed
                        elif source_id in node_instruction_count and len(node_instruction_count[source_id]) > 1:
                            actual_source_id = f"{instr_name}_{source_id}"
                        else:
                            actual_source_id = source_id

                        # If source doesn't exist, add it if it's a simple intermediate node
                        if actual_source_id not in merged_graph.nodes:
                            # Try to find the unprefixed version in the source graph
                            unprefixed_id = source_id
                            if unprefixed_id in source_graph.nodes:
                                source_type = source_graph.nodes[unprefixed_id].data.get('type')
                                # Add simple intermediate nodes that should be shared or instruction-specific
                                if source_type in ['bit_slice', 'literal', 'sized_literal', 'var']:
                                    # Create prefixed version if it appears in multiple instructions
                                    if unprefixed_id in node_instruction_count and len(node_instruction_count[unprefixed_id]) > 1:
                                        copy_node_id = f"{instr_name}_{unprefixed_id}"
                                    else:
                                        copy_node_id = unprefixed_id
                                    copy_node = Node(copy_node_id, source_graph.nodes[unprefixed_id].data.copy() if source_graph.nodes[unprefixed_id].data else {})
                                    merged_graph.add_node(copy_node)
                                    print(f"    Added missing source node '{copy_node_id}' for instruction-specific node '{merged_node_id}'")

                                    # For bit_slice nodes, also copy their incoming edges (e.g., from 'instr')
                                    if source_type == 'bit_slice':
                                        for bit_slice_edge in source_graph.nodes[unprefixed_id].incoming_edges:
                                            bit_slice_source_id = bit_slice_edge.source.id
                                            # Check if the bit_slice's source exists in merged graph (e.g., 'instr')
                                            if bit_slice_source_id in merged_graph.nodes:
                                                bit_slice_new_edge = Edge(
                                                    merged_graph.nodes[bit_slice_source_id],
                                                    copy_node,
                                                    data=bit_slice_edge.data.copy() if bit_slice_edge.data else {}
                                                )
                                                merged_graph.add_edge(bit_slice_new_edge)
                                                print(f"      Added edge from '{bit_slice_source_id}' to bit_slice '{copy_node_id}'")

                                    # For var nodes, also copy their assignment edges
                                    elif source_type == 'var':
                                        for var_edge in source_graph.nodes[unprefixed_id].incoming_edges:
                                            if var_edge.data.get('type') == 'assignment':
                                                var_source_id = var_edge.source.id
                                                # Check if the source exists in merged graph
                                                if var_source_id in merged_graph.nodes:
                                                    var_new_edge = Edge(
                                                        merged_graph.nodes[var_source_id],
                                                        copy_node,
                                                        data=var_edge.data.copy() if var_edge.data else {}
                                                    )
                                                    merged_graph.add_edge(var_new_edge)
                                                    print(f"      Added assignment edge from '{var_source_id}' to var '{copy_node_id}'")

                                    actual_source_id = copy_node_id

                        if actual_source_id in merged_graph.nodes:
                            source_target = merged_graph.nodes[actual_source_id]
                            # Check if this edge already exists
                            # Include position check for concatenation inputs
                            edge_type = edge.data.get('type') if edge.data else None
                            edge_position = edge.data.get('position') if edge.data else None
                            edge_exists = False
                            for existing_edge in merged_node.incoming_edges:
                                if (existing_edge.source.id == source_target.id and
                                    existing_edge.data.get('type') == edge_type and
                                    existing_edge.data.get('position') == edge_position):
                                    edge_exists = True
                                    break
                            if not edge_exists:
                                new_edge = Edge(source_target, merged_node, data=edge.data.copy())
                                merged_graph.add_edge(new_edge)

                    for edge in source_node.outgoing_edges:
                        target_id = edge.target.id
                        # Check if target node was remapped to a group-specific shared node
                        if target_id in node_remapping[instr_name]:
                            actual_target_id = node_remapping[instr_name][target_id]
                        # Check if target node might have been prefixed
                        elif target_id in node_instruction_count and len(node_instruction_count[target_id]) > 1:
                            actual_target_id = f"{instr_name}_{target_id}"
                        else:
                            actual_target_id = target_id

                        if actual_target_id in merged_graph.nodes:
                            target_node = merged_graph.nodes[actual_target_id]
                            # Check if this edge already exists
                            # Include position check for concatenation inputs
                            edge_type = edge.data.get('type') if edge.data else None
                            edge_position = edge.data.get('position') if edge.data else None
                            edge_exists = False
                            for existing_edge in merged_node.outgoing_edges:
                                if (existing_edge.target.id == target_node.id and
                                    existing_edge.data.get('type') == edge_type and
                                    existing_edge.data.get('position') == edge_position):
                                    edge_exists = True
                                    break
                            if not edge_exists:
                                new_edge = Edge(merged_node, target_node, data=edge.data.copy())
                                merged_graph.add_edge(new_edge)

    def _merge_instruction_nodes(self, merged_graph: ResourceGraph, instr_name: str,
                                shared_nodes: Set[str], instruction_specific_nodes: Dict[str, Set[str]]):
        """Merge instruction-specific nodes into the unified graph."""
        source_graph = self.graphs[instr_name]
        instr_nodes = instruction_specific_nodes.get(instr_name, set())

        for node_id in instr_nodes:
            if node_id in shared_nodes:
                continue  # Skip shared nodes

            source_node = source_graph.nodes[node_id]

            # Create instruction-specific version
            new_node_id = f"{instr_name}_{node_id}" if node_id not in merged_graph.nodes else f"{instr_name}_{node_id}_spec"
            new_data = source_node.data.copy() if source_node.data else {}
            new_data['instruction'] = instr_name

            new_node = Node(
                new_node_id, new_data,
                is_arch_state=source_node.is_arch_state,
                used_as_index=source_node.used_as_index,
                is_uarch_state=source_node.is_uarch_state,
                uarch_time=source_node.uarch_time
            )

            merged_graph.add_node(new_node)

            # Copy relevant edges
            self._copy_instruction_edges(merged_graph, source_graph, source_node, new_node, instr_name, shared_nodes)

    def _copy_instruction_edges(self, merged_graph: ResourceGraph, source_graph: ResourceGraph,
                               source_node: Node, new_node: Node, instr_name: str, shared_nodes: Set[str]):
        """Copy edges for instruction-specific nodes."""

        # Copy incoming edges (sorted for deterministic order)
        for edge in sorted(source_node.incoming_edges, key=lambda e: (e.source.id, e.data.get('type', ''))):
            source_id = edge.source.id

            if source_id in shared_nodes:
                # Connect from shared node
                source_target = merged_graph.nodes[source_id]
            else:
                # Connect from instruction-specific node
                instr_source_id = f"{instr_name}_{source_id}"
                if instr_source_id in merged_graph.nodes:
                    source_target = merged_graph.nodes[instr_source_id]
                else:
                    continue  # Skip if source not found

            new_edge = Edge(source_target, new_node, data=edge.data.copy())
            merged_graph.add_edge(new_edge)

        # Copy outgoing edges (sorted for deterministic order)
        for edge in sorted(source_node.outgoing_edges, key=lambda e: (e.target.id, e.data.get('type', ''))):
            target_id = edge.target.id

            if target_id in shared_nodes:
                # Connect to shared node
                target_node = merged_graph.nodes[target_id]
            else:
                # Connect to instruction-specific node
                instr_target_id = f"{instr_name}_{target_id}"
                if instr_target_id in merged_graph.nodes:
                    target_node = merged_graph.nodes[instr_target_id]
                else:
                    continue  # Skip if target not found

            new_edge = Edge(new_node, target_node, data=edge.data.copy())
            merged_graph.add_edge(new_edge)

    def _gate_instruction_operations(self, merged_graph: ResourceGraph, instruction_specific_nodes: Dict[str, Set[str]]):
        """Create multiplexers for nodes that receive assignments from multiple operations."""
        # Find all operations that assign to shared targets
        assignment_targets = {}  # target_node_id -> [(source_op_node, instr_name, enable_expr), ...]

        # Look at ALL operations and instruction-specific vars in the merged graph
        for node_id, node in sorted(merged_graph.nodes.items()):
            node_type = node.data.get('type')
            # Check for any node that can produce a value and assign it
            # Include operations, ternary ops, instruction-specific vars, and partially shared vars
            should_check = False
            if node_type in ['operation', 'ternary_op']:
                should_check = True
            elif node_type == 'var':
                # Check vars that belong to a specific instruction OR are partially shared
                if node.data.get('instruction') or any(node_id in instruction_specific_nodes[instr] for instr in instruction_specific_nodes.keys()):
                    should_check = True
                elif node_id in self.partially_shared_nodes:
                    should_check = True

            if should_check:
                # Find what this node assigns to
                for edge in node.outgoing_edges:
                    if edge.data.get('type') == 'assignment':
                        target_id = edge.target.id
                        target_node = edge.target
                        if target_id not in assignment_targets:
                            assignment_targets[target_id] = []

                        # Extract enable expression from edge (e.g., from 'when' clause)
                        enable_expr = edge.data.get('enable')

                        # Determine which instruction/group this assignment belongs to
                        # CRITICAL: When a shared data node assigns to a collision write node,
                        # use the TARGET's group_members, not the source's prefix/group
                        instr_name = node.data.get('instruction', 'shared')

                        # Check if target is a collision node (has original_id metadata)
                        # If so, the relevant instructions come from the target's group_members
                        target_group_members = target_node.data.get('group_members', [])
                        source_group_members = node.data.get('group_members', [])

                        if target_group_members and source_group_members:
                            # Both source and target have group_members
                            # Find intersection: instructions that use this source AND write to this target
                            # For shared data nodes like adc_abs_data writing to lda_abs_A_wr,
                            # we need the LDA instructions from target, not ADC from source
                            intersection = set(target_group_members) & set(source_group_members)
                            if intersection:
                                # Use all instructions from the intersection
                                for common_instr in sorted(intersection):
                                    assignment_targets[target_id].append((node, common_instr, enable_expr))
                                    print(f"Found {node_type} {node_id} ({common_instr}) assigns to {target_id} (from intersection)")
                                continue  # Skip the single append below - we added multiple

                        # CASE 2: Target is instruction-specific (no group_members) but source is a shared node
                        # Extract target's instruction from its name prefix (e.g., lda_abs_A_wr -> lda_abs)
                        if source_group_members and not target_group_members:
                            # Try to extract instruction prefix from target_id
                            # Target format: {instruction}_{register}_wr or {instruction}_{array}[{index}]_wr
                            target_instr = None
                            # Look for _wr suffix and extract prefix
                            if '_wr' in target_id:
                                # Get everything before the last part that starts with uppercase (register name)
                                parts = target_id.replace('_wr', '').split('_')
                                # Find where the register/array name starts (usually uppercase or contains brackets)
                                for i, part in enumerate(parts):
                                    if part and (part[0].isupper() or '[' in part):
                                        target_instr = '_'.join(parts[:i])
                                        break
                                if not target_instr and len(parts) > 1:
                                    # Fallback: assume last part is register name
                                    target_instr = '_'.join(parts[:-1])

                            if target_instr and target_instr in source_group_members:
                                # The target's instruction is in the source's group - use it
                                assignment_targets[target_id].append((node, target_instr, enable_expr))
                                print(f"Found {node_type} {node_id} ({target_instr}) assigns to {target_id} (target instr from source group)")
                                continue  # Skip the single append below

                        # Fall back to original logic for non-collision cases
                        if any(node_id in instruction_specific_nodes[instr] for instr in instruction_specific_nodes.keys()):
                            # Find which instruction this belongs to
                            for instr in instruction_specific_nodes.keys():
                                if node_id in instruction_specific_nodes[instr]:
                                    instr_name = instr
                                    break
                        elif node_id in self.partially_shared_nodes:
                            # Partially shared node - use first instruction from the group as representative
                            instr_name = sorted(self.partially_shared_nodes[node_id])[0]

                        assignment_targets[target_id].append((node, instr_name, enable_expr))
                        print(f"Found {node_type} {node_id} ({instr_name}) assigns to {target_id}")

        # Also check for assignments to partially shared nodes from multiple sources
        # (e.g., different concat nodes assigning to sign_ext_imm for different instruction groups)
        print(f"\nChecking for group-specific assignments to partially shared nodes...")
        nodes_to_remove_from_partially_shared = []
        for target_id in list(self.partially_shared_nodes.keys()):
            if target_id not in merged_graph.nodes:
                continue
            target_node = merged_graph.nodes[target_id]

            # Find all nodes that assign to this partially shared target
            sources_for_target = []
            for node_id, node in merged_graph.nodes.items():
                for edge in node.outgoing_edges:
                    if edge.target.id == target_id and edge.data.get('type') == 'assignment':
                        # Determine instruction group for this source
                        instr_name = node.data.get('instruction', 'shared')
                        if any(node_id in instruction_specific_nodes[instr] for instr in instruction_specific_nodes.keys()):
                            for instr in instruction_specific_nodes.keys():
                                if node_id in instruction_specific_nodes[instr]:
                                    instr_name = instr
                                    break
                        # Extract enable expression from edge (e.g., from 'when' clause)
                        enable_expr = edge.data.get('enable')
                        sources_for_target.append((node, instr_name, node_id, enable_expr))

            # If multiple sources assign to this partially shared node, we need a mux
            if len(sources_for_target) > 1:
                # Check if they're actually different nodes (not duplicates)
                unique_sources = {}
                for node, instr_name, node_id, enable_expr in sources_for_target:
                    unique_sources[node_id] = (node, instr_name, enable_expr)

                if len(unique_sources) > 1:
                    # Check if any sources are memory read nodes from 'mem' type memories
                    # If so, mark for byte/halfword selection
                    def is_mem_type_read(node_id):
                        """Check if node_id is a memory read from a 'mem' type memory."""
                        if '_rd' not in node_id:
                            return False
                        # Extract memory name from pattern like "lb_umem[addr]_rd"
                        import re
                        match = re.search(r'_(\w+)\[', node_id)
                        if match:
                            mem_name = match.group(1)
                            mem_node = merged_graph.nodes.get(mem_name)
                            if mem_node and mem_node.data.get('type') == 'isa_state mem':
                                return True
                        return False

                    has_mem_reads = any(
                        is_mem_type_read(node_id)
                        for node_id in unique_sources.keys()
                    )

                    target_width = target_node.data.get('bit_width')
                    if has_mem_reads and target_width and target_width < 32:
                        print(f"Found memory read sources for {target_id} ({target_width}-bit) - creating mux with byte/halfword selection")
                        # Create mux as normal, but mark that byte selection is needed
                        # The Verilog generator will apply byte selection to memory read inputs
                        target_node.data['needs_byte_selection'] = True
                        target_node.data['mem_read_sources'] = [
                            nid for nid in unique_sources.keys()
                            if is_mem_type_read(nid)
                        ]
                        print(f"  Marked {target_id} for byte selection from {target_node.data['mem_read_sources']}")
                        # Fall through to normal mux creation

                    print(f"Found {len(unique_sources)} sources assigning to partially shared node {target_id}:")
                    if target_id not in assignment_targets:
                        assignment_targets[target_id] = []
                    for node_id, (node, instr_name, enable_expr) in unique_sources.items():
                        print(f"  - {node_id} ({instr_name})" + (f" [enable: {enable_expr}]" if enable_expr else ""))
                        # Only add if not already in the list (check by node and instr_name)
                        already_exists = any(src[0] == node and src[1] == instr_name for src in assignment_targets[target_id])
                        if not already_exists:
                            assignment_targets[target_id].append((node, instr_name, enable_expr))

        # Remove nodes from partially_shared_nodes after iteration
        for target_id in nodes_to_remove_from_partially_shared:
            if target_id in self.partially_shared_nodes:
                del self.partially_shared_nodes[target_id]
                print(f"  Removed {target_id} from partially_shared_nodes")

        # Only remove edges that create actual conflicts (multiple operations to same target)
        # EXCEPTION: Don't remove edges for arch state targets - _create_arch_state_mux will handle them
        edges_to_remove = []
        for target_id, sources in assignment_targets.items():
            if len(sources) > 1:  # Multiple operations assign to this target
                # Skip arch state targets - they need edges preserved for _create_arch_state_mux
                if hasattr(self, '_arch_state_wr_nodes_needing_mux') and target_id in self._arch_state_wr_nodes_needing_mux:
                    print(f"Preserving edges for arch state target {target_id} - will be handled by _create_arch_state_mux")
                    continue
                # Remove direct assignment edges from ALL operations to this target
                for source_node, instr_name, enable_expr in sources:
                    for edge in list(source_node.outgoing_edges):
                        if edge.target.id == target_id and edge.data.get('type') == 'assignment':
                            edges_to_remove.append(edge)
                            print(f"Removing conflicting operation edge: {source_node.id} -> {target_id}")

        # Remove the conflicting operation edges
        for edge in edges_to_remove:
            merged_graph.remove_edge(edge.id)

        # Create multiplexers for targets with multiple instruction sources
        for target_id, sources in assignment_targets.items():
            if len(sources) > 1:  # Multiple sources need multiplexing
                # Skip if this will be handled by _create_arch_state_mux
                if hasattr(self, '_arch_state_wr_nodes_needing_mux') and target_id in self._arch_state_wr_nodes_needing_mux:
                    print(f"Skipping {target_id} mux creation - will use _create_arch_state_mux instead")
                    continue

                # Deduplicate sources: same node may appear with different instruction names
                # IMPORTANT: When multiple instructions share the same source, collect ALL instructions
                # so we can OR their enables together
                source_by_node = {}  # node_id -> (node, set of instr_names, enable_expr)
                for source_node, instr_name, enable_expr in sources:
                    node_id = source_node.id
                    if node_id not in source_by_node:
                        source_by_node[node_id] = (source_node, {instr_name}, enable_expr)
                    else:
                        # Already have this node - collect all instruction names
                        source_by_node[node_id][1].add(instr_name)
                        # Also infer instruction from node prefix (e.g., jal_jump_dest -> jal)
                        if instr_name == 'shared':
                            # Check if node_id starts with instruction prefix
                            for instr in self.graphs.keys():
                                if node_id.startswith(f'{instr}_'):
                                    source_by_node[node_id][1].add(instr)
                                    break

                # Convert to list format, keeping all instruction names for shared nodes
                deduplicated_sources = []
                for node_id, (source_node, instr_names, enable_expr) in source_by_node.items():
                    # Filter out 'shared' if there are specific instruction names
                    specific_instrs = {i for i in instr_names if i != 'shared'}
                    if specific_instrs:
                        # Use sorted to ensure deterministic ordering
                        deduplicated_sources.append((source_node, sorted(specific_instrs), enable_expr))
                    else:
                        # All are 'shared'
                        deduplicated_sources.append((source_node, ['shared'], enable_expr))
                if len(deduplicated_sources) < len(sources):
                    print(f"Deduplicated sources for {target_id}: {len(sources)} -> {len(deduplicated_sources)}")

                self._create_instruction_multiplexer(merged_graph, target_id, deduplicated_sources)

        # Handle single-source targets that don't cover all instructions.
        # These need instruction enables added to their assignment edges.
        for target_id, sources in assignment_targets.items():
            if len(sources) != 1:
                continue
            # Skip if handled by _create_arch_state_mux
            if hasattr(self, '_arch_state_wr_nodes_needing_mux') and target_id in self._arch_state_wr_nodes_needing_mux:
                continue
            # Only process _wr nodes for arch state registers (not arrays/memories)
            if not target_id.endswith('_wr'):
                continue
            target_node = merged_graph.nodes.get(target_id)
            if not target_node:
                continue
            if target_node.data.get('is_memory', False) or target_node.data.get('array_depth'):
                continue
            # Skip collision nodes (e.g., jal_pc_wr with original_id='pc_wr').
            # These will be consumed by _create_arch_state_mux which already
            # handles instruction-enable gating via _create_merged_condition.
            # Adding enables here would cause double-gating and pipeline stage
            # mismatches when the flat mux builder ANDs the edge enable with
            # the instruction enable again.
            original_id = target_node.data.get('original_id')
            if original_id:
                # Also check if the original target is in the mux set
                if hasattr(self, '_arch_state_wr_nodes_needing_mux') and original_id in self._arch_state_wr_nodes_needing_mux:
                    continue

            source_node, instr_name, enable_expr = sources[0]
            # Shared across all instructions — no enable needed
            if instr_name == 'shared':
                continue

            # Determine which instruction(s) write this target
            writing_instrs = set()
            if isinstance(instr_name, list):
                writing_instrs = set(instr_name)
            else:
                writing_instrs = {instr_name}
            # Also check instruction_specific_nodes membership
            for iname, specific_nodes in instruction_specific_nodes.items():
                if source_node.id in specific_nodes:
                    writing_instrs.add(iname)

            if writing_instrs >= set(self.graphs.keys()):
                continue  # All instructions write this — no enable needed

            # Build the instruction enable expression
            enable_signal_names = sorted(f"{iname}_enable" for iname in writing_instrs
                                          if f"{iname}_enable" in merged_graph.nodes)
            if not enable_signal_names:
                continue

            # Find the assignment edge to this target and add the enable
            for edge in target_node.incoming_edges:
                if edge.data.get('type') == 'assignment' and edge.source.id == source_node.id:
                    existing_enable = edge.data.get('enable')
                    # Build instruction enable (single or OR'd)
                    if len(enable_signal_names) == 1:
                        instr_enable = {'type': 'identifier', 'name': enable_signal_names[0]}
                    else:
                        instr_enable = {'type': 'identifier', 'name': enable_signal_names[0]}
                        for sig in enable_signal_names[1:]:
                            instr_enable = {'type': 'binary_op', 'operator': '||',
                                            'left': instr_enable, 'right': {'type': 'identifier', 'name': sig}}

                    if existing_enable:
                        # AND instruction enable with existing when-condition
                        edge.data['enable'] = {
                            'type': 'binary_op', 'operator': '&&',
                            'left': instr_enable, 'right': existing_enable
                        }
                    else:
                        edge.data['enable'] = instr_enable
                    break

        # Handle _wr nodes that were missed by assignment_targets because their
        # source is a shared constant or bit-slice (e.g., halted when (cond) = 1'b1).
        # Constants and bit-slices don't pass the should_check filter above, so they
        # never appear in assignment_targets. We need to find these _wr nodes and add
        # instruction enables to their assignment edges.
        # Note: _wr nodes may have is_arch_state=False in the merged graph even though
        # they represent ISA state, so we check node data type instead.
        for node_id, node in sorted(merged_graph.nodes.items()):
            if not node_id.endswith('_wr'):
                continue
            if node.data.get('type') != 'isa_state':
                continue
            if node.data.get('is_memory', False) or node.data.get('array_depth'):
                continue
            # Skip if already handled by assignment_targets or mux creation
            if node_id in assignment_targets:
                continue
            # Check both node_id and original_id against mux set
            # (collision nodes like builtin_pc_wr have original_id='pc_wr')
            original_id_check = node.data.get('original_id', node_id)
            if hasattr(self, '_arch_state_wr_nodes_needing_mux'):
                if node_id in self._arch_state_wr_nodes_needing_mux or original_id_check in self._arch_state_wr_nodes_needing_mux:
                    continue

            # Check for incoming assignment edges from shared/constant sources
            for edge in node.incoming_edges:
                if edge.data.get('type') != 'assignment':
                    continue
                existing_enable = edge.data.get('enable')

                # Determine which instruction(s) own this assignment
                writing_instrs = set()
                # Check instruction_specific_nodes for the target node itself
                # (collision nodes appear in multiple instructions' specific_nodes)
                original_id = node.data.get('original_id', node_id)
                for iname, specific_nodes in instruction_specific_nodes.items():
                    if node_id in specific_nodes or original_id in specific_nodes:
                        writing_instrs.add(iname)
                # Check if the node has an 'instruction' field (set for single-instruction nodes)
                if not writing_instrs and node.data.get('instruction'):
                    writing_instrs.add(node.data['instruction'])
                # Check if the enable expression references instruction-specific nodes
                if not writing_instrs and existing_enable:
                    enable_name = existing_enable.get('name', '') if existing_enable.get('type') == 'identifier' else ''
                    if enable_name:
                        for iname, specific_nodes in instruction_specific_nodes.items():
                            if enable_name in specific_nodes:
                                writing_instrs.add(iname)
                # Check if the source node itself is instruction-specific
                if not writing_instrs:
                    for iname, specific_nodes in instruction_specific_nodes.items():
                        if edge.source.id in specific_nodes:
                            writing_instrs.add(iname)

                if not writing_instrs or writing_instrs >= set(self.graphs.keys()):
                    continue  # All instructions or can't determine

                # Build instruction enable and add to edge
                enable_signal_names = sorted(f"{iname}_enable" for iname in writing_instrs
                                              if f"{iname}_enable" in merged_graph.nodes)
                if not enable_signal_names:
                    continue

                if len(enable_signal_names) == 1:
                    instr_enable = {'type': 'identifier', 'name': enable_signal_names[0]}
                else:
                    instr_enable = {'type': 'identifier', 'name': enable_signal_names[0]}
                    for sig in enable_signal_names[1:]:
                        instr_enable = {'type': 'binary_op', 'operator': '||',
                                        'left': instr_enable, 'right': {'type': 'identifier', 'name': sig}}

                if existing_enable:
                    edge.data['enable'] = {
                        'type': 'binary_op', 'operator': '&&',
                        'left': instr_enable, 'right': existing_enable
                    }
                else:
                    edge.data['enable'] = instr_enable
                print(f"  Added instruction enable {enable_signal_names} to {node_id} (source: {edge.source.id})")
                break  # Only one assignment edge per _wr node

        # CRITICAL: Handle architectural state write nodes that have group-specific replacements
        # These need muxes to merge all group-specific values back into the shared write node
        # Use flat mux approach to merge nested ternaries into single mux
        use_flat_mux = getattr(self, 'use_flat_mux_merging', True)

        if hasattr(self, '_arch_state_wr_nodes_needing_mux'):
            for arch_wr_node_id in sorted(self._arch_state_wr_nodes_needing_mux):
                if use_flat_mux:
                    self._create_arch_state_mux_flat(merged_graph, arch_wr_node_id, instruction_specific_nodes)
                else:
                    self._create_arch_state_mux(merged_graph, arch_wr_node_id, instruction_specific_nodes)

            # Cleanup absorbed ternaries if using flat mux
            if use_flat_mux:
                removed = self._cleanup_absorbed_ternaries(merged_graph)
                if removed > 0:
                    print(f"Cleaned up {removed} absorbed ternary nodes")


    def _create_instruction_multiplexer(self, merged_graph: ResourceGraph, target_id: str, sources: List):
        """Create a multiplexer to select between instruction-specific operation results.

        Args:
            merged_graph: The merged resource graph
            target_id: ID of the target node
            sources: List of (source_node, instr_names, enable_expr) where instr_names is a list of
                     instruction names and enable_expr is the optional enable condition from 'when' clause
        """
        target_node = merged_graph.nodes[target_id]
        mux_id = f"{target_id}_mux"

        # Separate sources into instruction-specific and shared (default) sources
        instruction_sources = []
        default_source = None

        for source_node, instr_names, enable_expr in sources:
            # instr_names is now a list (could be ['shared'] or list of instruction names)
            if instr_names == ['shared']:
                # This is a shared node - use as default value
                default_source = source_node
            else:
                instruction_sources.append((source_node, instr_names, enable_expr))

        # Optimization: If there's only one source used by all instructions (no default needed),
        # skip mux creation and just connect source directly to target.
        # This avoids unnecessary muxes and potential naming collisions.
        # EXCEPTION: If the single source is a ternary_op, we must NOT skip because
        # the ternary's branches need to be expanded into separate mux inputs.
        # EXCEPTION 2: If there's an enable condition, we must NOT skip because
        # the mux select needs to incorporate the enable condition.
        if len(instruction_sources) == 1 and default_source is None:
            source_node, instr_names, enable_expr = instruction_sources[0]
            # Check if this covers all instructions (i.e., used universally)
            # BUT don't skip if it's a ternary - those need expansion
            # AND don't skip if there's an enable condition - mux select needs it
            is_ternary = source_node.data.get('type') == 'ternary_op'
            has_enable = enable_expr is not None
            if len(instr_names) == len(self.graphs) and not is_ternary and not has_enable:
                print(f"  Skipping mux for {target_id}: single source '{source_node.id}' used by all {len(instr_names)} instructions")
                # Just ensure there's an assignment edge from source to target
                has_assignment = False
                for edge in target_node.incoming_edges:
                    if edge.source.id == source_node.id and edge.data.get('type') == 'assignment':
                        has_assignment = True
                        break
                if not has_assignment:
                    new_edge = Edge(source_node, target_node, data={'type': 'assignment'})
                    merged_graph.add_edge(new_edge)
                    print(f"  Created direct assignment: {source_node.id} -> {target_id}")
                return
            elif is_ternary:
                print(f"  NOT skipping mux for {target_id}: source is ternary_op that needs expansion")
            elif has_enable:
                print(f"  NOT skipping mux for {target_id}: has enable condition {enable_expr}")

        # Use PRIORITY mux with default value
        mux_type = MuxType.PRIORITY

        # Use MuxBuilder to create the multiplexer with proper bit width
        # The mux should have the same width as the target node
        target_bit_width = target_node.data.get('bit_width', 32)
        builder = MuxBuilder(merged_graph, mux_id, mux_type, bit_width=target_bit_width)
        builder.create_or_get_mux(display_name=f"{target_id} MUX")

        # Add instruction-specific inputs with their enable signals
        source_nodes = []
        input_index = 0  # Track mux input index separately since ternaries expand into 2 inputs

        for i, (source_node, instr_names, enable_expr) in enumerate(instruction_sources):
            source_nodes.append(source_node)

            # enable_expr comes from the 'when' clause in the ISA specification
            # e.g., cpsr when (cond_pass & s_bit) = new_cpsr has enable_expr = "cond_pass & s_bit"
            if enable_expr:
                print(f"  Using enable condition for {source_node.id} -> {target_id}: {enable_expr}")

            # Create OR of all instruction enables for this source
            # If there's an enable condition, AND it with each instruction enable
            enable_nodes = []
            enable_strings = []
            for instr_name in instr_names:
                enable_signal = f"{instr_name}_enable"
                enable_node = merged_graph.nodes.get(enable_signal)
                if enable_node:
                    if enable_expr:
                        # Need to AND instruction enable with enable condition from 'when' clause
                        # First get or create the condition node for enable_expr
                        condition_id = self._get_or_create_condition_node_id(merged_graph, enable_expr, instr_name)
                        condition_node = merged_graph.nodes.get(condition_id)
                        if condition_node:
                            # Create AND node: enable && condition
                            # Include condition_id to make unique when same instruction has multiple conditional writes
                            and_node_id = f"{instr_name}_{condition_id}_{target_id}_cond_select"
                            if and_node_id not in merged_graph.nodes:
                                and_node = Node(and_node_id, {
                                    'type': 'operation',
                                    'operator': '&&',
                                    'display_name': f"{instr_name}_enable && {condition_id}",
                                    'bit_width': 1
                                })
                                merged_graph.add_node(and_node)
                                e1 = Edge(enable_node, and_node, data={'type': 'operand', 'operand_index': 0, 'position': 0})
                                merged_graph.add_edge(e1)
                                e2 = Edge(condition_node, and_node, data={'type': 'operand', 'operand_index': 1, 'position': 1})
                                merged_graph.add_edge(e2)
                            enable_nodes.append(merged_graph.nodes[and_node_id])
                        else:
                            print(f"  Warning: Could not find condition node {condition_id}")
                            enable_nodes.append(enable_node)
                    else:
                        enable_nodes.append(enable_node)
                else:
                    enable_strings.append(f"{enable_signal}")

            # Get or create the enable signal (single node or OR)
            if len(enable_nodes) == 1 and not enable_strings:
                enable_select = enable_nodes[0]
            elif enable_nodes or enable_strings:
                # Multiple enables - create OR node
                or_node_id = f"{mux_id}_enable_or_{i}"
                if or_node_id not in merged_graph.nodes:
                    or_node = Node(or_node_id, {
                        'type': 'logical_or',
                        'operator': '||',
                        'display_name': ' || '.join(instr_names) + '_enable',
                        'width': 1
                    })
                    merged_graph.add_node(or_node)

                    # Connect all enable nodes to OR gate
                    for j, en in enumerate(enable_nodes):
                        edge = Edge(en, or_node, data={'type': 'operand', 'operand_index': j, 'position': j})
                        merged_graph.add_edge(edge)

                enable_select = merged_graph.nodes[or_node_id]
            else:
                # No valid enables found - use first instruction name as fallback string
                enable_select = f"{instr_names[0]}_enable == 1"

            # Check if source is a ternary that needs expansion
            if source_node.data.get('type') == 'ternary_op':
                # Analyze ternary and expand into its two branches
                # Use first instruction name for analysis (all should share the same ternary structure)
                analysis = analyze_ternary(merged_graph, source_node, instr_names[0])

                if len(analysis.cases) == 2:
                    print(f"  Expanding ternary {source_node.id} into 2 mux inputs")

                    for case in analysis.cases:
                        # Get value and condition nodes
                        value_node = merged_graph.nodes.get(case.value_node_id)
                        cond_node = merged_graph.nodes.get(case.condition_node_id)

                        if not value_node:
                            print(f"    Warning: value node {case.value_node_id} not found")
                            continue

                        source_nodes.append(value_node)

                        # Build combined condition: enable && cond (or enable && !cond for inverted)
                        if cond_node and isinstance(enable_select, Node):
                            if case.condition_inverted:
                                # False branch: enable && !cond
                                not_cond_id = f"{cond_node.id}_not_for_{mux_id}"
                                if not_cond_id not in merged_graph.nodes:
                                    not_node = Node(not_cond_id, {
                                        'type': 'operation',
                                        'operator': '!',
                                        'display_name': f"NOT {cond_node.id}",
                                        'bit_width': 1
                                    })
                                    merged_graph.add_node(not_node)
                                    e = Edge(cond_node, not_node, data={'type': 'operand', 'operand_index': 0})
                                    merged_graph.add_edge(e)
                                actual_cond = merged_graph.nodes[not_cond_id]
                            else:
                                # True branch: enable && cond
                                actual_cond = cond_node

                            # Create AND: enable && condition
                            and_node_id = f"{mux_id}_input_{input_index}_sel"
                            if and_node_id not in merged_graph.nodes:
                                and_node = Node(and_node_id, {
                                    'type': 'operation',
                                    'operator': '&&',
                                    'display_name': f"enable && {'!' if case.condition_inverted else ''}{cond_node.id}",
                                    'bit_width': 1
                                })
                                merged_graph.add_node(and_node)
                                e1 = Edge(enable_select, and_node, data={'type': 'operand', 'operand_index': 0})
                                e2 = Edge(actual_cond, and_node, data={'type': 'operand', 'operand_index': 1})
                                merged_graph.add_edge(e1)
                                merged_graph.add_edge(e2)

                            combined_select = merged_graph.nodes[and_node_id]
                        else:
                            # Fallback: just use enable
                            combined_select = enable_select

                        builder.add_input(
                            source=value_node,
                            select=combined_select,
                            input_index=input_index,
                            metadata={'source_instruction': instr_names, 'ternary_branch': 'true' if not case.condition_inverted else 'false'}
                        )
                        print(f"    Added ternary branch: {value_node.id} with select {combined_select.id if isinstance(combined_select, Node) else combined_select}")
                        input_index += 1
                else:
                    # Incomplete ternary analysis - fall back to treating as single value
                    print(f"  Warning: Ternary {source_node.id} analysis returned {len(analysis.cases)} cases, expected 2")
                    builder.add_input(
                        source=source_node,
                        select=enable_select,
                        input_index=input_index,
                        metadata={'source_instruction': instr_names[0] if len(instr_names) == 1 else instr_names}
                    )
                    input_index += 1
            else:
                # Non-ternary source - add directly with enable as select
                builder.add_input(
                    source=source_node,
                    select=enable_select,
                    input_index=input_index,
                    metadata={'source_instruction': instr_names[0] if len(instr_names) == 1 else instr_names}
                )
                input_index += 1

        # Add default source if present
        if default_source:
            builder.add_default_input(default_source)
            source_nodes.append(default_source)

        # Connect mux output to target
        builder.connect_output(target_node, 'assignment',
                              metadata={'description': f"Priority multiplexed assignment to {target_id}"})

        # Remove bypassing edges
        removed = builder.remove_bypassing_edges(source_nodes, target_node)

        print(f"Created multiplexer {mux_id} for {len(instruction_sources)} instruction sources + {'1 default' if default_source else '0 default'} to {target_id}")
        if removed > 0:
            print(f"Removed {removed} direct assignment edges")

    def _create_arch_state_mux(self, merged_graph: ResourceGraph, wr_node_id: str, instruction_specific_nodes: Dict[str, Set[str]]):
        """Create a mux to merge group-specific architectural state writes into the shared write node.
    
        For example, when pc_wr has been split into beq_pc_wr, jal_pc_wr, etc., this creates
        a mux that selects the appropriate value based on instruction enable signals and
        connects it to the shared pc_wr node.
        """
        print(f"\nCreating arch state mux for {wr_node_id}")
    
        if wr_node_id not in merged_graph.nodes:
            print(f"  ERROR: {wr_node_id} not in merged graph")
            return
    
        target_node = merged_graph.nodes[wr_node_id]
    
        # Find all group-specific versions of this write node
        # They will be named like beq_pc_wr, jal_pc_wr, etc.
        base_name = wr_node_id  # e.g., 'pc_wr'
        group_specific_sources = []
        seen_sources = set()  # Track source node IDs to avoid duplicates

        for node_id, node in sorted(merged_graph.nodes.items()):
            # Check if this is a group-specific version of our target
            if node_id.endswith(f'_{base_name}') and node_id != base_name:
                # This is a group-specific version (e.g., beq_pc_wr)
                # Get the instruction prefix
                prefix = node_id[:-len(base_name)-1]  # Extract 'beq' from 'beq_pc_wr'
    
                # Find the source that assigns to this group-specific node
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'assignment':
                        source_node = edge.source
                        if source_node.id not in seen_sources:
                            group_specific_sources.append((source_node, prefix, node_id))
                            seen_sources.add(source_node.id)
                            print(f"  Found group-specific source: {source_node.id} -> {node_id} (prefix={prefix})")
                        break
    
        # Also find instruction-prefixed nodes that directly assign to the target
        # (e.g., jalr_jump_dest -> pc_wr when jalr_pc_wr doesn't exist)
        for edge in target_node.incoming_edges:
            if edge.data.get('type') == 'assignment':
                source_node = edge.source
                source_id = source_node.id
                if source_id in seen_sources:
                    continue
                # Check if source has instruction prefix
                for instr in self.graphs.keys():
                    if source_id.startswith(f'{instr}_'):
                        group_specific_sources.append((source_node, instr, source_id))
                        seen_sources.add(source_id)
                        print(f"  Found direct assignment source: {source_id} -> {wr_node_id} (instr={instr})")
                        break
    
        if not group_specific_sources:
            print(f"  No group-specific sources found for {wr_node_id}")
            return
    
        # Find the default value - the current register value (to preserve state when not modified)
        default_source = None
        default_value_id = None

        # Check for a shared node that would be the default
        # For pc_wr, this is typically (pc + 4) from ALU/load/store instructions
        if '(pc + 4)' in merged_graph.nodes:
            default_source = merged_graph.nodes['(pc + 4)']
            default_value_id = '(pc + 4)'
            print(f"  Using {default_value_id} as default source")
        else:
            # For other registers (X_wr, S_wr, A_wr, etc.), use the _rd version
            # to preserve the current value when no instruction modifies the register
            if wr_node_id.endswith('_wr'):
                rd_node_id = wr_node_id[:-3] + '_rd'  # X_wr -> X_rd
                if rd_node_id in merged_graph.nodes:
                    default_source = merged_graph.nodes[rd_node_id]
                    default_value_id = rd_node_id
                    print(f"  Using {default_value_id} as default source (preserve current value)")
                else:
                    # Also try just the base name (e.g., 'X' for 'X_wr')
                    base_name = wr_node_id[:-3]  # X_wr -> X
                    if base_name in merged_graph.nodes:
                        default_source = merged_graph.nodes[base_name]
                        default_value_id = base_name
                        print(f"  Using {default_value_id} as default source (base register)")

        # Create the mux
        mux_id = f"{wr_node_id}_mux"
        mux_type = MuxType.PRIORITY
    
        builder = MuxBuilder(merged_graph, mux_id, mux_type)
        builder.create_or_get_mux(display_name=f"{wr_node_id} MUX")
    
        # Add group-specific inputs with their enable signals
        source_nodes = []
        for i, (source_node, prefix, group_node_id) in enumerate(group_specific_sources):
            source_nodes.append(source_node)
    
            # Get instruction enable signal - handle group prefixes
            # The prefix might be the first instruction in a group (e.g., 'beq' for branches)
            enable_signal = f"{prefix}_enable"
            enable_node = merged_graph.nodes.get(enable_signal)
    
            if enable_node:
                builder.add_input(
                    source=source_node,
                    select=enable_node,
                    input_index=i,
                    metadata={'source_instruction': prefix, 'group_node': group_node_id}
                )
                print(f"  Added mux input: {source_node.id} (select={enable_signal})")
            else:
                # Try to find enable signals for this group
                # Check if there's a group of instructions sharing this prefix
                found_enable = False
                for instr_name in sorted(self.graphs.keys()):
                    if f'{instr_name}_enable' in merged_graph.nodes:
                        # Check if this instruction uses this group-specific node
                        if instr_name == prefix or (hasattr(self, 'partially_shared_nodes') and
                                                    group_node_id in self.partially_shared_nodes and
                                                    instr_name in self.partially_shared_nodes[group_node_id]):
                            instr_enable = merged_graph.nodes[f'{instr_name}_enable']
                            builder.add_input(
                                source=source_node,
                                select=instr_enable,
                                input_index=i,
                                metadata={'source_instruction': instr_name, 'group_node': group_node_id}
                            )
                            print(f"  Added mux input: {source_node.id} (select={instr_name}_enable)")
                            found_enable = True
                            break
    
                if not found_enable:
                    # Fallback: use condition string
                    builder.add_input(
                        source=source_node,
                        select=f"{enable_signal} == 1",
                        input_index=i,
                        metadata={'source_instruction': prefix, 'group_node': group_node_id}
                    )
                    print(f"  Added mux input: {source_node.id} (select={enable_signal} == 1 [fallback])")
    
        # Add default source if present
        if default_source:
            builder.add_default_input(default_source)
            source_nodes.append(default_source)
            print(f"  Added default input: {default_source.id}")
    
        # Connect mux output to the shared write node
        builder.connect_output(target_node, 'assignment',
                              metadata={'description': f"Priority multiplexed assignment to {wr_node_id}"})
    
        # Remove bypassing edges
        removed = builder.remove_bypassing_edges(source_nodes, target_node)
    
        print(f"Created arch state multiplexer {mux_id} for {len(group_specific_sources)} group-specific sources + {'1 default' if default_source else '0 default'} to {wr_node_id}")
        if removed > 0:
            print(f"Removed {removed} direct assignment edges")
    
    def _create_arch_state_mux_flat(self, merged_graph: ResourceGraph, wr_node_id: str,
                                     instruction_specific_nodes: Dict[str, Set[str]]):
        """Create a single flat mux for ISA state writes by merging nested ternaries.
    
        This is an optimization over _create_arch_state_mux that:
        1. Analyzes ternary/mux nodes that feed into the write node
        2. Extracts their cases (value, condition pairs)
        3. Groups cases by structurally-equivalent values
        4. OR's conditions for cases with the same value
        5. Creates one flat mux instead of nested muxes
    
        Example transformation for pc_wr:
            Before: 6 branch ternaries + 2 jump destinations = 8 mux inputs
            After: branch_dest (OR'd conditions) + jal_dest + jalr_dest + (pc+4) = 4 inputs
        """
        print(f"\n=== Creating FLAT arch state mux for {wr_node_id} ===")
    
        # Step 0: Collect sources first (this works even if target node doesn't exist yet)
        sources = find_isa_state_mux_sources(merged_graph, wr_node_id)
        if not sources:
            print(f"  No sources found for {wr_node_id}")
            return
        # Sort sources for deterministic iteration order
        sources = sorted(sources, key=lambda x: (x[0].id, x[1]))
    
        # Create target node if it doesn't exist (happens when collision handling replaced it)
        if wr_node_id not in merged_graph.nodes:
            print(f"  Creating missing target node: {wr_node_id}")
            # Get metadata from a collision node
            for node_id, node in merged_graph.nodes.items():
                if node.data.get('original_id') == wr_node_id:
                    # Copy properties from collision node
                    target_data = {'type': 'var', 'name': wr_node_id, 'is_arch_state_target': True}
                    target_node = Node(
                        wr_node_id, target_data,
                        is_arch_state=True,
                        is_uarch_state=node.is_uarch_state,
                        uarch_time=node.uarch_time
                    )
                    merged_graph.add_node(target_node)
                    break
            else:
                print(f"  ERROR: Cannot create {wr_node_id} - no collision nodes found")
                return
    
        target_node = merged_graph.nodes[wr_node_id]
    
        # Step 1: Log sources (already collected)
        print(f"  Found {len(sources)} sources assigning to {wr_node_id}")
        for src, instr, enable_expr in sources:
            enable_str = f" when {enable_expr}" if enable_expr else ""
            print(f"    - {src.id} ({src.data.get('type')}) from {instr}{enable_str}")
    
        # Step 2: Build instruction enable map
        instruction_enables = {}
        for instr_name in self.graphs.keys():
            enable_id = f"{instr_name}_enable"
            if enable_id in merged_graph.nodes:
                instruction_enables[instr_name] = enable_id
    
        # Step 3: Extract all cases from sources (analyzing ternaries/muxes)
        all_cases = self._extract_all_cases_from_sources(
            merged_graph, sources, instruction_enables, target_state=wr_node_id)
    
        if not all_cases:
            print(f"  No cases extracted for {wr_node_id}")
            return

        # Sort all_cases for deterministic processing
        all_cases = sorted(all_cases, key=lambda c: (c.value_node_id or '', c.condition_node_id or '', c.source_instruction or ''))

        print(f"  Extracted {len(all_cases)} total cases")

        # Step 4: Group cases by value equivalence
        value_groups = group_cases_by_value(merged_graph, all_cases)
        print(f"  Grouped into {len(value_groups)} value groups")

        # Step 5: Create the flat mux with merged conditions
        self._build_flat_mux_from_groups(
            merged_graph, wr_node_id, target_node, value_groups, sources)
    
        # Step 6: Remove collision nodes - they're no longer needed since the mux replaces them
        # These nodes (e.g., beq_pc_wr, jal_pc_wr) were intermediate artifacts used to
        # collect instruction-specific values. Now that the mux combines them, remove them.
        collision_nodes_to_remove = []
        for node_id, node in merged_graph.nodes.items():
            if node.data.get('original_id') == wr_node_id:
                collision_nodes_to_remove.append(node_id)
    
        for node_id in collision_nodes_to_remove:
            # Remove all edges involving this node first
            node = merged_graph.nodes[node_id]
            edges_to_remove = list(node.incoming_edges) + list(node.outgoing_edges)
            for edge in edges_to_remove:
                merged_graph.remove_edge(edge.id)
            # Now remove the node
            merged_graph.remove_node(node_id)
            print(f"  Removed collision node: {node_id}")

    def _expression_to_node_id(self, expr: dict) -> str:
        """Convert an enable expression AST to a node ID (matching ISA parser format).

        Args:
            expr: Expression AST dict from 'when' clause

        Returns:
            Node ID string in ISA parser format, e.g., "(is_satp & (rs1 != 0))"
        """
        if not isinstance(expr, dict):
            return str(expr)

        expr_type = expr.get('type')

        if expr_type == 'identifier':
            return expr.get('name', 'unknown')
        elif expr_type == 'literal':
            return str(expr.get('value', 0))
        elif expr_type in ('binary_op', 'comparison'):
            left_id = self._expression_to_node_id(expr.get('left', {}))
            right_id = self._expression_to_node_id(expr.get('right', {}))
            operator = expr.get('operator', '&')
            # Match ISA parser format: (left_id operator right_id)
            return f"({left_id} {operator} {right_id})"
        elif expr_type == 'unary_op':
            operand_id = self._expression_to_node_id(expr.get('operand', {}))
            operator = expr.get('operator', '~')
            # Match ISA parser format: ~operand or !operand
            return f"{operator}{operand_id}"
        elif expr_type == 'array_access':
            array_name = expr.get('target', {}).get('name', 'unknown')
            index_id = self._expression_to_node_id(expr.get('index', {}))
            return f"{array_name}[{index_id}]_rd"
        elif expr_type == 'sized_literal':
            # Use format-aware representation: 10'h8, 5'b11001, 8'd255
            fmt = expr.get('format', 'bin')
            w = expr.get('width', 0)
            digits = expr.get('original_digits', str(expr.get('value', 0)))
            fmt_char = {'bin': 'b', 'hex': 'h', 'dec': 'd'}.get(fmt, 'b')
            return f"{w}'{fmt_char}{digits}"
        elif expr_type == 'binary_wildcard':
            bits = expr.get('bits', expr.get('pattern', ''))
            return expr.get('original', f"0b{bits}")
        elif expr_type == 'verilog_hex_literal':
            # Handle Verilog hex literals like 10'h8
            width = expr.get('width', '')
            hex_digits = expr.get('hex_digits', '0')
            return f"{width}'h{hex_digits}"
        elif expr_type == 'verilog_dec_literal':
            # Handle Verilog decimal literals like 10'd8
            width = expr.get('width', '')
            value = expr.get('value', 0)
            return f"{width}'d{value}"
        else:
            return f"expr_{hash(str(expr)) % 10000}"

    def _get_or_create_condition_node_id(self, merged_graph: ResourceGraph,
                                          enable_expr: dict, instr_name: str) -> Optional[str]:
        """Get or create a node ID for an enable condition expression.

        Handles both simple identifiers and compound expressions like (is_satp & (rs1 != 0)).

        Args:
            merged_graph: The merged resource graph
            enable_expr: Enable expression AST from 'when' clause
            instr_name: Name of the instruction (for prefixed lookups)

        Returns:
            Node ID for the condition, or None if not found/created
        """
        if not enable_expr:
            return None

        expr_type = enable_expr.get('type')

        if expr_type == 'identifier':
            # Simple identifier like 'is_satp'
            cond_name = enable_expr.get('name')

            # FIRST: Try GroupTracker to find the merged node ID
            # Condition nodes may be grouped (e.g., 'delegate_to_smode' -> 'add_delegate_to_smode')
            if hasattr(self, '_group_tracker') and self._group_tracker:
                merged_id = self._group_tracker.get_merged_id(instr_name, cond_name)
                if merged_id and merged_id in merged_graph.nodes:
                    return merged_id

            # Then try instruction-prefixed version
            prefixed_cond = f"{instr_name}_{cond_name}"
            if prefixed_cond in merged_graph.nodes:
                return prefixed_cond
            elif cond_name in merged_graph.nodes:
                return cond_name
            else:
                print(f"  WARNING: Condition {cond_name} from 'when' clause not found in graph (instr={instr_name})")
                return None

        elif expr_type == 'literal':
            # Numeric literal like 0 or 15
            value = enable_expr.get('value')
            const_id = str(value)
            if const_id not in merged_graph.nodes:
                # Create constant node
                const_node = Node(const_id, {
                    'type': 'constant',
                    'value': value,
                    'display_name': const_id
                })
                merged_graph.add_node(const_node)
            return const_id

        elif expr_type == 'sized_literal':
            # Sized literal like 10'h8, 5'b11001, 8'd255
            value = enable_expr.get('value', 0)
            fmt = enable_expr.get('format', 'bin')
            w = enable_expr.get('width', 0)
            digits = enable_expr.get('original_digits', str(value))
            fmt_char = {'bin': 'b', 'hex': 'h', 'dec': 'd'}.get(fmt, 'b')
            const_id = f"{w}'{fmt_char}{digits}"
            if const_id not in merged_graph.nodes:
                const_node = Node(const_id, {
                    'type': 'constant',
                    'value': value,
                    'display_name': const_id,
                    'bit_width': w
                })
                merged_graph.add_node(const_node)
            return const_id

        elif expr_type == 'binary_wildcard':
            # Binary wildcard like 0b1111 - use fixed_value or value
            value = enable_expr.get('fixed_value')
            if value is None:
                value = enable_expr.get('value', 0)
            bits = enable_expr.get('bits', enable_expr.get('pattern', ''))
            const_id = enable_expr.get('original', f"0b{bits}")
            if const_id not in merged_graph.nodes:
                # Create constant node
                const_node = Node(const_id, {
                    'type': 'constant',
                    'value': value,
                    'display_name': const_id,
                    'bit_width': enable_expr.get('width', 32)
                })
                merged_graph.add_node(const_node)
            return const_id

        elif expr_type == 'array_access':
            # Array access like register_list[0] - generate node ID
            array_name = enable_expr.get('target', {}).get('name', 'unknown')
            index_expr = enable_expr.get('index', {})
            if index_expr.get('type') == 'literal':
                index_str = str(index_expr.get('value'))
            else:
                index_str = self._expression_to_node_id(index_expr) if index_expr else '?'
            node_id = f"{array_name}[{index_str}]"

            # Try instruction-specific version first
            prefixed_id = f"{instr_name}_{node_id}"
            if prefixed_id in merged_graph.nodes:
                return prefixed_id
            elif node_id in merged_graph.nodes:
                return node_id
            else:
                # Try with _rd suffix (for array reads)
                rd_suffixed = f"{node_id}_rd"
                prefixed_rd = f"{instr_name}_{rd_suffixed}"
                if prefixed_rd in merged_graph.nodes:
                    return prefixed_rd
                elif rd_suffixed in merged_graph.nodes:
                    return rd_suffixed
                else:
                    print(f"  WARNING: Array access {node_id} from 'when' clause not found in graph")
                    return None

        elif expr_type in ('binary_op', 'comparison'):
            # Compound expression like (is_satp & (rs1 != 0)) or comparison like (spr == 10'h8)
            # Generate the node ID using ISA parser format
            cond_id = self._expression_to_node_id(enable_expr)

            # FIRST: Try GroupTracker to find the merged node ID
            if hasattr(self, '_group_tracker') and self._group_tracker:
                merged_id = self._group_tracker.get_merged_id(instr_name, cond_id)
                if merged_id and merged_id in merged_graph.nodes:
                    return merged_id

            # Check if any operand identifier is a collision node.
            # If so, the shared version may use a wrong operand - we need an
            # instruction-specific version connected to the correct operand.
            needs_instruction_specific = False
            if hasattr(self, '_group_tracker') and self._group_tracker:
                for sub_expr in [enable_expr.get('left'), enable_expr.get('right')]:
                    if sub_expr and sub_expr.get('type') == 'identifier':
                        sub_name = sub_expr.get('name')
                        classification = self._group_tracker.get_classification(sub_name)
                        if classification and classification.is_collision():
                            needs_instruction_specific = True
                            break

            if needs_instruction_specific:
                # Operand is a collision node - need instruction-specific version
                # to ensure we connect to the correct collision-group operand
                prefixed_cond = f"{instr_name}_{cond_id}"
                if prefixed_cond in merged_graph.nodes:
                    return prefixed_cond
                # Fall through to creation code below with instruction-specific ID
                cond_id = prefixed_cond
            else:
                # Then try instruction-prefixed version
                prefixed_cond = f"{instr_name}_{cond_id}"
                if prefixed_cond in merged_graph.nodes:
                    return prefixed_cond
                elif cond_id in merged_graph.nodes:
                    return cond_id

            # Node doesn't exist - we need to create it
            # First, recursively get/create operand nodes
            left_node_id = self._get_or_create_condition_node_id(
                merged_graph, enable_expr.get('left'), instr_name)
            right_node_id = self._get_or_create_condition_node_id(
                merged_graph, enable_expr.get('right'), instr_name)

            if left_node_id and right_node_id:
                # Create the compound condition node
                operator = enable_expr.get('operator', '&')

                # Determine result width based on operator
                if operator in ('==', '!=', '<', '>', '<=', '>=', '&', '|', '&&', '||'):
                    result_width = 1
                else:
                    result_width = 32

                cond_node = Node(
                    node_id=cond_id,
                    data={
                        'type': 'operation',
                        'operator': operator,
                        'expression': enable_expr,
                        'display_name': cond_id,
                        'bit_width': result_width,
                    }
                )
                merged_graph.add_node(cond_node)

                # Create edges from operands to the new node
                if left_node_id in merged_graph.nodes:
                    left_node = merged_graph.nodes[left_node_id]
                    left_edge = Edge(left_node, cond_node,
                        data={'type': 'operand', 'position': 'left'})
                    merged_graph.add_edge(left_edge)

                if right_node_id in merged_graph.nodes:
                    right_node = merged_graph.nodes[right_node_id]
                    right_edge = Edge(right_node, cond_node,
                        data={'type': 'operand', 'position': 'right'})
                    merged_graph.add_edge(right_edge)

                print(f"  Created compound condition node: {cond_id}")
                return cond_id
            else:
                print(f"  WARNING: Could not create compound condition - missing operands")
                print(f"    left_node_id={left_node_id}, right_node_id={right_node_id}")
                return None
        elif expr_type == 'unary_op':
            # Unary operation like ~register_list[rn] or !condition
            operator = enable_expr.get('operator', '~')
            operand_expr = enable_expr.get('operand')

            # Generate node ID for the unary expression
            cond_id = self._expression_to_node_id(enable_expr)

            # Always use instruction-specific prefix for unary nodes.
            # The operand (e.g., m68k_exc_taken) resolves to different
            # group-specific nodes per instruction, so the NOT node must
            # also be per-instruction to invert the correct signal.
            prefixed_cond = f"{instr_name}_{cond_id}"
            if prefixed_cond in merged_graph.nodes:
                return prefixed_cond

            # Recursively get/create the operand node
            operand_node_id = self._get_or_create_condition_node_id(
                merged_graph, operand_expr, instr_name)

            if operand_node_id:
                # Create the unary operation node with instruction-specific ID
                cond_node = Node(
                    node_id=prefixed_cond,
                    data={
                        'type': 'operation',
                        'operator': operator,
                        'expression': enable_expr,
                        'display_name': prefixed_cond,
                        'bit_width': 1,
                    }
                )
                merged_graph.add_node(cond_node)

                # Create edge from operand to the new node
                if operand_node_id in merged_graph.nodes:
                    operand_node = merged_graph.nodes[operand_node_id]
                    operand_edge = Edge(operand_node, cond_node,
                        data={'type': 'operand', 'position': 'operand'})
                    merged_graph.add_edge(operand_edge)

                print(f"  Created unary condition node: {prefixed_cond}")
                return prefixed_cond
            else:
                print(f"  WARNING: Could not create unary condition - missing operand")
                return None

        else:
            print(f"  WARNING: Unsupported enable expression type: {expr_type}")
            return None

    def _extract_all_cases_from_sources(self, merged_graph: ResourceGraph,
                                         sources: List[Tuple[Node, str, Optional[dict]]],
                                         instruction_enables: Dict[str, str],
                                         target_state: str = '') -> List[MuxCase]:
        """Extract all mux cases from source nodes (ternaries, muxes, or direct values).

        Args:
            merged_graph: The merged resource graph
            sources: List of (source_node, instruction_name, enable_expr) tuples
            instruction_enables: Map of instruction name -> enable node ID
            target_state: Name of the target state (e.g., 'pc', 'cr18', 'priv_level')
                         Used to disambiguate not_higher_prio nodes across different states.

        Returns:
            List of MuxCase representing all possible assignments
        """
        all_cases = []

        for source_node, instr_name, enable_expr in sources:
            node_type = source_node.data.get('type', '')
            enable_id = instruction_enables.get(instr_name)

            if node_type == 'ternary_op':
                # Analyze ternary and extract its cases
                analysis = analyze_ternary(merged_graph, source_node, instr_name)

                # Get the when-clause condition node if present
                when_condition_node_id = None
                if enable_expr:
                    when_condition_node_id = self._get_or_create_condition_node_id(
                        merged_graph, enable_expr, instr_name)

                for case in analysis.cases:
                    case.source_instruction = instr_name

                    # Resolve condition to instruction-specific version via GroupTracker
                    if case.condition_node_id and hasattr(self, '_group_tracker') and self._group_tracker:
                        remapped = self._group_tracker.get_merged_id(instr_name, case.condition_node_id)
                        if remapped and remapped != case.condition_node_id and remapped in merged_graph.nodes:
                            case.condition_node_id = remapped

                    # Combine the when-clause condition with the ternary condition
                    # so that the full guard is: when_clause && ternary_cond
                    if when_condition_node_id:
                        combined_cond_id = self._combine_conditions(
                            merged_graph, when_condition_node_id,
                            case.condition_node_id,
                            case.condition_inverted,
                            instr_name, case.value_node_id or '')
                        case.condition_node_id = combined_cond_id
                        case.condition_inverted = False  # Already handled in combined_cond
                        case.is_default = False  # Now a fully-specified conditional case

                    all_cases.append(case)

            elif node_type == 'multiplexer':
                # Analyze existing mux
                analysis = analyze_mux(merged_graph, source_node, instr_name)

                # Check if this is a gated write mux - if so, convert its default to a conditional case
                is_gated_mux = source_node.data.get('gated_write_mux', False)

                if is_gated_mux:
                    # For gated write muxes, the default represents "unconditional write when
                    # this instruction executes but no conditional overrides apply"
                    # We need to convert it to: enable && NOT(any conditional case)
                    # Sort cases for deterministic order
                    sorted_analysis_cases = sorted(analysis.cases, key=lambda c: (c.value_node_id or '', c.condition_node_id or ''))
                    conditional_cases = [c for c in sorted_analysis_cases if not c.is_default]
                    default_cases = [c for c in sorted_analysis_cases if c.is_default]

                    # Sort conditional cases by gated_mux_index (priority order: 0 = highest)
                    conditional_cases_sorted = sorted(conditional_cases,
                        key=lambda c: c.gated_mux_index if c.gated_mux_index is not None else 0)

                    # Collect original condition IDs before modifying cases
                    all_original_cond_ids = [c.condition_node_id for c in conditional_cases_sorted
                                             if c.condition_node_id]

                    # Make lower-priority conditions mutually exclusive with higher-priority ones.
                    # This converts the if-else priority cascade from the per-instruction gated mux
                    # into explicit AND-NOT conditions for the flat cross-instruction mux.
                    # E.g., for data_trap(prio 0) vs interruption(prio 1):
                    #   data_trap_taken → unchanged
                    #   exception_taken & psw_Q → (exception_taken & psw_Q) & ~data_trap_taken
                    higher_priority_cond_ids = []
                    for case in conditional_cases_sorted:
                        case.source_instruction = instr_name
                        # Resolve condition to instruction-specific version via GroupTracker
                        if case.condition_node_id and hasattr(self, '_group_tracker') and self._group_tracker:
                            remapped = self._group_tracker.get_merged_id(instr_name, case.condition_node_id)
                            if remapped and remapped != case.condition_node_id and remapped in merged_graph.nodes:
                                case.condition_node_id = remapped

                        original_cond_id = case.condition_node_id

                        if higher_priority_cond_ids and case.condition_node_id:
                            # Build NOT(OR(all higher-priority conditions))
                            if len(higher_priority_cond_ids) == 1:
                                or_higher_id = higher_priority_cond_ids[0]
                            else:
                                or_higher_id = f"{instr_name}_higher_prio_or_{case.gated_mux_index}_{target_state}"
                                if or_higher_id not in merged_graph.nodes:
                                    or_node = Node(or_higher_id, {
                                        'type': 'operation',
                                        'operator': '||',
                                        'display_name': f"Higher prio gated conds for {instr_name}[{case.gated_mux_index}] writing {target_state}",
                                        'bit_width': 1
                                    })
                                    merged_graph.add_node(or_node)
                                    for oidx, cid in enumerate(higher_priority_cond_ids):
                                        if cid in merged_graph.nodes:
                                            e = Edge(merged_graph.nodes[cid], or_node,
                                                    data={'type': 'operand', 'operand_index': oidx})
                                            merged_graph.add_edge(e)

                            not_higher_id = f"{instr_name}_not_higher_prio_{case.gated_mux_index}_{target_state}"
                            if not_higher_id not in merged_graph.nodes:
                                not_node = Node(not_higher_id, {
                                    'type': 'operation',
                                    'operator': '!',
                                    'display_name': f"No higher prio gated for {instr_name}[{case.gated_mux_index}] writing {target_state}",
                                    'bit_width': 1
                                })
                                merged_graph.add_node(not_node)
                                or_ref = merged_graph.nodes.get(or_higher_id)
                                if or_ref:
                                    e = Edge(or_ref, not_node,
                                            data={'type': 'operand', 'operand_index': 0})
                                    merged_graph.add_edge(e)

                            # Combine: case.condition AND NOT(higher priority conditions)
                            combined_id = self._combine_conditions(
                                merged_graph, case.condition_node_id, not_higher_id,
                                False, instr_name, case.value_node_id or '')
                            case.condition_node_id = combined_id
                            case.condition_inverted = False

                        if original_cond_id:
                            higher_priority_cond_ids.append(original_cond_id)

                        all_cases.append(case)

                    # For default cases, create condition: NOT(OR(all original conditionals))
                    if default_cases and conditional_cases:
                        cond_ids = all_original_cond_ids

                        if cond_ids:
                            # Create NOT(OR(all conditions)) node
                            not_any_cond_id = f"{instr_name}_no_gated_cond"

                            if not_any_cond_id not in merged_graph.nodes:
                                # Create OR of all conditional nodes (or use single condition directly)
                                if len(cond_ids) == 1:
                                    or_node_id = cond_ids[0]
                                else:
                                    or_node_id = f"{instr_name}_any_gated_cond"
                                    if or_node_id not in merged_graph.nodes:
                                        or_node = Node(or_node_id, {
                                            'type': 'operation',
                                            'operator': '||',
                                            'display_name': f"Any gated condition for {instr_name}",
                                            'bit_width': 1
                                        })
                                        merged_graph.add_node(or_node)
                                        for idx, cond_id in enumerate(cond_ids):
                                            if cond_id in merged_graph.nodes:
                                                cond_node = merged_graph.nodes[cond_id]
                                                e = Edge(cond_node, or_node,
                                                        data={'type': 'operand', 'operand_index': idx})
                                                merged_graph.add_edge(e)

                                # Create NOT node
                                not_node = Node(not_any_cond_id, {
                                    'type': 'operation',
                                    'operator': '!',
                                    'display_name': f"No gated override for {instr_name}",
                                    'bit_width': 1
                                })
                                merged_graph.add_node(not_node)
                                or_node_ref = merged_graph.nodes.get(or_node_id)
                                if or_node_ref:
                                    e = Edge(or_node_ref, not_node,
                                            data={'type': 'operand', 'operand_index': 0})
                                    merged_graph.add_edge(e)

                            # Convert default cases to conditional with NOT(conditions)
                            for dcase in default_cases:
                                # Check if the default value is itself a ternary that needs to be flattened
                                # This is critical for branch instructions where the gated mux default is:
                                # res ? branch_dest : pc+4
                                # We need to extract the ternary's cases and combine with no_gated_cond
                                default_node = merged_graph.nodes.get(dcase.value_node_id)
                                if default_node and default_node.data.get('type') == 'ternary_op':
                                    # Recursively analyze the nested ternary
                                    nested_analysis = analyze_ternary(merged_graph, default_node, instr_name)
                                    for nested_case in nested_analysis.cases:
                                        # Resolve nested condition to instruction-specific version via GroupTracker.
                                        # The ternary may reference a shared condition node (e.g., ~m68k_exc_taken)
                                        # that was split into per-group versions during merging. We need the
                                        # version specific to this instruction's group.
                                        resolved_cond_id = nested_case.condition_node_id
                                        if resolved_cond_id and hasattr(self, '_group_tracker') and self._group_tracker:
                                            remapped = self._group_tracker.get_merged_id(instr_name, resolved_cond_id)
                                            if remapped and remapped != resolved_cond_id and remapped in merged_graph.nodes:
                                                resolved_cond_id = remapped

                                        # Combine conditions: no_gated_cond && nested_condition
                                        # For true branch: no_gated_cond && ternary_cond
                                        # For false branch: no_gated_cond && !ternary_cond
                                        combined_cond_id = self._combine_conditions(
                                            merged_graph, not_any_cond_id,
                                            resolved_cond_id,
                                            nested_case.condition_inverted,
                                            instr_name, nested_case.value_node_id)

                                        combined_case = MuxCase(
                                            value_node_id=nested_case.value_node_id,
                                            condition_node_id=combined_cond_id,
                                            condition_inverted=False,  # Already handled in combined_cond
                                            source_instruction=instr_name,
                                            is_default=False,
                                            original_mux_id=nested_case.original_mux_id
                                        )
                                        all_cases.append(combined_case)
                                else:
                                    # Not a ternary - use the value directly
                                    new_case = MuxCase(
                                        value_node_id=dcase.value_node_id,
                                        condition_node_id=not_any_cond_id,
                                        condition_inverted=False,
                                        source_instruction=instr_name,
                                        is_default=False,  # Now conditional, not default
                                        original_mux_id=dcase.original_mux_id
                                    )
                                    all_cases.append(new_case)
                        else:
                            # No conditions found, keep defaults as-is
                            for dcase in default_cases:
                                dcase.source_instruction = instr_name
                                all_cases.append(dcase)
                    elif default_cases:
                        # No conditional cases, keep defaults as-is
                        for dcase in default_cases:
                            dcase.source_instruction = instr_name
                            all_cases.append(dcase)
                else:
                    # Not a gated mux - handle normally
                    for case in analysis.cases:
                        case.source_instruction = instr_name
                        # Resolve condition to instruction-specific version via GroupTracker
                        if case.condition_node_id and hasattr(self, '_group_tracker') and self._group_tracker:
                            remapped = self._group_tracker.get_merged_id(instr_name, case.condition_node_id)
                            if remapped and remapped != case.condition_node_id and remapped in merged_graph.nodes:
                                case.condition_node_id = remapped
                        all_cases.append(case)


            else:
                # Direct assignment (like jal_jump_dest -> pc_wr or satp = new_val when is_satp)
                # Check for enable condition from 'when' clause (e.g., is_satp or compound like (is_satp & (rs1 != 0)))
                condition_node_id = None
                if enable_expr:
                    # The enable_expr can be:
                    # - Simple identifier: {'type': 'identifier', 'name': 'is_satp'}
                    # - Compound expression: {'type': 'binary_op', 'operator': '&', 'left': ..., 'right': ...}
                    condition_node_id = self._get_or_create_condition_node_id(
                        merged_graph, enable_expr, instr_name)

                case = MuxCase(
                    value_node_id=source_node.id,
                    condition_node_id=condition_node_id,  # Use 'when' condition if present
                    condition_inverted=False,
                    source_instruction=instr_name,
                    is_default=False if (enable_id or condition_node_id) else True,
                    original_mux_id=None
                )
                all_cases.append(case)

        return all_cases
    
    def _build_flat_mux_from_groups(self, merged_graph: ResourceGraph,
                                     wr_node_id: str, target_node: Node,
                                     value_groups: Dict[str, ValueGroup],
                                     sources: List[Tuple[Node, str]]):
        """Build a single flat mux from grouped cases.
    
        Args:
            merged_graph: The merged resource graph
            wr_node_id: ID of the write node (e.g., 'pc_wr')
            target_node: The write node
            value_groups: Grouped cases by value equivalence
            sources: Original source nodes (for cleanup)
        """
        mux_id = f"{wr_node_id}_mux"
        builder = MuxBuilder(merged_graph, mux_id, MuxType.PRIORITY)
        builder.create_or_get_mux(display_name=f"{wr_node_id} MUX (flat)")
    
        source_nodes = []
        default_value_id = None
        input_idx = 0

        # Determine aspect ordering for this state from ISA priority declarations.
        # Extract state name from wr_node_id (e.g., cr20_wr -> cr20).
        state_name = wr_node_id[:-3] if wr_node_id.endswith('_wr') else wr_node_id
        aspect_order = getattr(self, '_aspect_order_per_state', {}).get(state_name, {})

        # Sort value groups by aspect priority. When cases from multiple aspects
        # produce the same value, keep them in one group (same result, no priority
        # conflict). Only aspect ordering between DIFFERENT values matters.
        ordered_entries = []  # list of (sort_key, value_node_id, group)
        for value_node_id, group in value_groups.items():
            if not aspect_order:
                # No explicit aspect ordering for this state - use alphabetical
                ordered_entries.append((9999, value_node_id, group))
                continue

            # Find the highest-priority (lowest rank number) aspect in this group
            min_rank = 9999
            for case in group.cases:
                aspect = case.from_aspect
                if aspect:
                    # Look up rank, trying suffix match if exact match fails
                    # (from_aspect may use absolute paths while aspect_order uses relative)
                    rank = aspect_order.get(aspect, None)
                    if rank is None:
                        for key, r in aspect_order.items():
                            if aspect.endswith('/' + key) or aspect.endswith(key):
                                rank = r
                                break
                    if rank is not None and rank < min_rank:
                        min_rank = rank
            ordered_entries.append((min_rank, value_node_id, group))

        ordered_entries.sort(key=lambda x: (x[0], x[1]))

        for rank, value_node_id, group in ordered_entries:
            if value_node_id not in merged_graph.nodes:
                print(f"  WARNING: Value node {value_node_id} not in graph")
                continue
    
            value_node = merged_graph.nodes[value_node_id]
            source_nodes.append(value_node)
    
            # Separate cases:
            # - Non-default cases are conditional (e.g., ternary true branch)
            # - Default cases with condition_inverted are also conditional (ternary false branch)
            # - Default cases WITHOUT condition_inverted are truly global defaults
            conditional_cases = [c for c in group.cases if not c.is_default]
            inverted_cases = [c for c in group.cases if c.is_default and c.condition_inverted]
            true_default_cases = [c for c in group.cases if c.is_default and not c.condition_inverted]

            # Inverted cases (ternary false branches) need explicit conditions too
            # e.g., for (imm == 0) ? 1'b1 : 1'b0, the 1'b0 branch needs: enable && !(imm == 0)
            all_conditional_cases = conditional_cases + inverted_cases

            if all_conditional_cases:
                # Create merged condition by OR'ing all conditions
                merged_condition = self._create_merged_condition(
                    merged_graph, all_conditional_cases, value_node_id, wr_node_id)
    
                if merged_condition:
                    builder.add_input(
                        source=value_node,
                        select=merged_condition,
                        input_index=input_idx,
                        metadata={
                            'merged_from': [c.source_instruction for c in all_conditional_cases],
                            'num_merged': len(all_conditional_cases)
                        }
                    )
                    print(f"  Added merged input: {value_node_id} (merged {len(all_conditional_cases)} conditions)")
                    input_idx += 1

            # Check for true default cases (not inverted ternary false branches)
            # These are cases that should actually be used as the global mux default
            if true_default_cases and default_value_id is None:
                # This value is used as default - remember for later
                default_value_id = value_node_id
                print(f"  Found default value: {value_node_id}")
    
        # Add default: For register writes (_wr nodes), ALWAYS use _rd to preserve current value
        # The ternary false branch (e.g., 1'b0) is only the "default" within that specific instruction's
        # ternary, not the global default for the mux. When no instruction modifies the register,
        # we must preserve its current value.
        if wr_node_id.endswith('_wr'):
            rd_node_id = wr_node_id[:-3] + '_rd'  # X_wr -> X_rd, flag_Z_wr -> flag_Z_rd
            if rd_node_id in merged_graph.nodes:
                default_node = merged_graph.nodes[rd_node_id]
                builder.add_default_input(default_node)
                source_nodes.append(default_node)
                print(f"  Added default input: {rd_node_id} (preserve current value)")
            else:
                # Try just the base name (e.g., 'X' for 'X_wr')
                base_name = wr_node_id[:-3]  # X_wr -> X
                if base_name in merged_graph.nodes:
                    default_node = merged_graph.nodes[base_name]
                    builder.add_default_input(default_node)
                    source_nodes.append(default_node)
                    print(f"  Added default input: {base_name} (base register)")
                elif default_value_id and default_value_id in merged_graph.nodes:
                    # Fallback to found default if no _rd version exists
                    default_node = merged_graph.nodes[default_value_id]
                    builder.add_default_input(default_node)
                    source_nodes.append(default_node)
                    print(f"  Added default input: {default_value_id}")
        elif default_value_id and default_value_id in merged_graph.nodes:
            # For non-register nodes, use the found default
            default_node = merged_graph.nodes[default_value_id]
            builder.add_default_input(default_node)
            source_nodes.append(default_node)
            print(f"  Added default input: {default_value_id}")
        elif wr_node_id.endswith('_wr'):
            # For ISA state write muxes without explicit default, use the corresponding
            # read register as default (hold behavior). This ensures the register value
            # is preserved when no instruction is actively writing to it.
            rd_node_id = wr_node_id[:-3] + '_rd'  # e.g., 'satp_wr' -> 'satp_rd'
            if rd_node_id in merged_graph.nodes:
                rd_node = merged_graph.nodes[rd_node_id]
                builder.add_default_input(rd_node)
                source_nodes.append(rd_node)
                print(f"  Added hold-value default: {rd_node_id} (for ISA state)")
            else:
                print(f"  WARNING: No default found for {wr_node_id} and read node {rd_node_id} not found")

        # Connect mux output to target
        builder.connect_output(target_node, 'assignment',
                              metadata={'description': f"Flat multiplexed assignment to {wr_node_id}"})
    
        # Remove direct edges that now go through the mux
        removed = builder.remove_bypassing_edges(source_nodes, target_node)
    
        # Also remove edges from the original ternary/mux sources
        for src_node, _, _ in sources:
            for edge in list(src_node.outgoing_edges):
                if edge.target.id == wr_node_id and edge.data.get('type') == 'assignment':
                    merged_graph.remove_edge(edge.id)
                    removed += 1

        print(f"  Created flat mux {mux_id} with {input_idx} inputs + default")
        if removed > 0:
            print(f"  Removed {removed} bypassing edges")

        # Mark original ternary nodes as absorbed (for potential cleanup)
        for src_node, _, _ in sources:
            if src_node.data.get('type') == 'ternary_op':
                src_node.data['absorbed_into_flat_mux'] = mux_id

    def _combine_conditions(self, merged_graph: ResourceGraph,
                           outer_cond_id: str, inner_cond_id: str,
                           inner_inverted: bool, instr_name: str,
                           value_hint: str = '') -> str:
        """Combine two conditions with AND, optionally inverting the inner condition.

        This is used when flattening nested ternaries inside gated muxes.
        For example, for BNE with exception handling:
        - outer_cond: no_gated_cond (!exception_taken)
        - inner_cond: bne_res (the branch condition)
        - Result: no_gated_cond && bne_res (for true branch)
        -     or: no_gated_cond && !bne_res (for false branch)

        Args:
            merged_graph: The merged resource graph
            outer_cond_id: The outer condition node ID (e.g., no_gated_cond)
            inner_cond_id: The inner condition node ID (e.g., bne_res)
            inner_inverted: Whether to invert the inner condition
            instr_name: Instruction name for node naming
            value_hint: Value being selected (for node naming)

        Returns:
            The ID of the combined condition node
        """
        if not inner_cond_id or inner_cond_id not in merged_graph.nodes:
            # No inner condition - just use outer
            return outer_cond_id

        if not outer_cond_id or outer_cond_id not in merged_graph.nodes:
            # No outer condition - use inner (with potential inversion)
            if inner_inverted:
                not_id = f"not{inner_cond_id}"
                if not_id not in merged_graph.nodes:
                    not_node = Node(not_id, {
                        'type': 'operation',
                        'operator': '!',
                        'display_name': f"NOT {inner_cond_id}",
                        'bit_width': 1
                    })
                    merged_graph.add_node(not_node)
                    cond_node = merged_graph.nodes[inner_cond_id]
                    e = Edge(cond_node, not_node, data={'type': 'operand', 'operand_index': 0})
                    merged_graph.add_edge(e)
                return not_id
            return inner_cond_id

        # Both conditions exist - create AND node
        inner_node = merged_graph.nodes[inner_cond_id]
        outer_node = merged_graph.nodes[outer_cond_id]

        # If inner is inverted, create NOT node first
        if inner_inverted:
            not_id = f"not{inner_cond_id}"
            if not_id not in merged_graph.nodes:
                not_node = Node(not_id, {
                    'type': 'operation',
                    'operator': '!',
                    'display_name': f"NOT {inner_cond_id}",
                    'bit_width': 1
                })
                merged_graph.add_node(not_node)
                e = Edge(inner_node, not_node, data={'type': 'operand', 'operand_index': 0})
                merged_graph.add_edge(e)
            inner_node = merged_graph.nodes[not_id]
            inner_cond_id = not_id

        # Create AND node
        value_short = value_hint.replace('(', '').replace(')', '').replace(' ', '_')[:15] if value_hint else ''
        and_id = f"{instr_name}_{value_short}_{outer_cond_id}_and_{inner_cond_id}_select"

        if and_id not in merged_graph.nodes:
            and_node = Node(and_id, {
                'type': 'operation',
                'operator': '&&',
                'display_name': f"{outer_cond_id} && {inner_cond_id}",
                'bit_width': 1
            })
            merged_graph.add_node(and_node)

            # Connect operands
            e1 = Edge(outer_node, and_node, data={'type': 'operand', 'operand_index': 0, 'position': 0})
            merged_graph.add_edge(e1)
            e2 = Edge(inner_node, and_node, data={'type': 'operand', 'operand_index': 1, 'position': 1})
            merged_graph.add_edge(e2)

        return and_id

    def _create_merged_condition(self, merged_graph: ResourceGraph,
                                  cases: List[MuxCase],
                                  value_node_id: str,
                                  target_wr_node_id: str = None) -> Optional[Node]:
        """Create an OR node merging multiple conditions.

        For branch instructions, this creates:
            (beq_enable && beq_res) || (bne_enable && bne_res) || ...

        Args:
            merged_graph: The merged resource graph
            cases: List of cases with conditions to OR together
            value_node_id: Value node ID (for naming the OR node)
            target_wr_node_id: Target write node ID (for unique naming, e.g., 'flag_Z_wr')

        Returns:
            The OR node, or single condition node if only one case
        """
        if not cases:
            return None
    
        if len(cases) == 1:
            # Single case - need to combine enable with condition if both exist
            # This is important for branches: we need enable && condition, not just condition
            # Otherwise the condition (like beq_res = r1 == r2) fires for ALL instructions
            case = cases[0]
            cond_id = case.condition_node_id
            enable_id = f"{case.source_instruction}_enable"

            if cond_id and cond_id in merged_graph.nodes and enable_id in merged_graph.nodes:
                # If the condition IS the instruction enable, no AND needed -
                # just use the enable directly.  Creating AND(x, x) can cause
                # pipeline stage mismatches when the two operand edges get piped
                # to different stages independently.
                if cond_id == enable_id:
                    return merged_graph.nodes[enable_id]

                # Both condition and enable exist - create AND node: enable && condition
                enable_node = merged_graph.nodes[enable_id]
                cond_node = merged_graph.nodes[cond_id]

                # If condition is inverted (false branch of ternary), create NOT node
                if case.condition_inverted:
                    not_id = f"not{cond_id}"
                    if not_id not in merged_graph.nodes:
                        not_node = Node(not_id, {
                            'type': 'operation',
                            'operator': '!',
                            'display_name': f"NOT {cond_id}",
                            'bit_width': 1
                        })
                        merged_graph.add_node(not_node)

                        # Connect condition to NOT node
                        e_not = Edge(cond_node, not_node, data={'type': 'operand', 'operand_index': 0})
                        merged_graph.add_edge(e_not)
                    else:
                        not_node = merged_graph.nodes[not_id]

                    cond_node = not_node

                # Create AND node (include condition in ID to avoid conflicts between different targets)
                # e.g., csrrw writes to both satp (when is_satp) and mtvec (when is_mtvec)
                # using the same value csrrw_new_csr_val, so we need different select nodes
                and_id = f"{case.source_instruction}_{value_node_id}_{cond_id}_select"
                if and_id not in merged_graph.nodes:
                    and_node = Node(and_id, {
                        'type': 'operation',
                        'operator': '&&',
                        'display_name': f"{case.source_instruction} selects {value_node_id} when {cond_id}"
                    })
                    merged_graph.add_node(and_node)

                    # Connect inputs - use both 'position' and 'operand_index' for Verilog generator compatibility
                    e1 = Edge(enable_node, and_node, data={'type': 'operand', 'operand_index': 0, 'position': 0})
                    merged_graph.add_edge(e1)
                    e2 = Edge(cond_node, and_node, data={'type': 'operand', 'operand_index': 1, 'position': 1})
                    merged_graph.add_edge(e2)
                else:
                    and_node = merged_graph.nodes[and_id]

                return and_node
            elif cond_id and cond_id in merged_graph.nodes:
                # Only condition exists (no enable) - use condition directly
                # Handle inverted condition case
                cond_node = merged_graph.nodes[cond_id]
                if case.condition_inverted:
                    not_id = f"not{cond_id}"
                    if not_id not in merged_graph.nodes:
                        not_node = Node(not_id, {
                            'type': 'operation',
                            'operator': '!',
                            'display_name': f"NOT {cond_id}",
                            'bit_width': 1
                        })
                        merged_graph.add_node(not_node)
                        e_not = Edge(cond_node, not_node, data={'type': 'operand', 'operand_index': 0})
                        merged_graph.add_edge(e_not)
                    else:
                        not_node = merged_graph.nodes[not_id]
                    return not_node
                return cond_node
            elif enable_id in merged_graph.nodes:
                # No explicit condition - use instruction enable directly
                return merged_graph.nodes[enable_id]
            return None
    
        # Multiple cases - check if ALL cases share the same condition node
        # If so, this is a global condition that should NOT be gated by instruction enables
        # (e.g., exception_taken from mmu.isa aspect included in all instructions)
        unique_conditions = set(c.condition_node_id for c in cases if c.condition_node_id)
        all_have_same_condition = len(unique_conditions) == 1 and all(c.condition_node_id for c in cases)

        # Check that this condition applies to all instructions
        all_instructions = set(self.graphs.keys())
        case_instructions = set(c.source_instruction for c in cases)
        is_global_condition = all_have_same_condition and case_instructions == all_instructions

        # Also detect aspect-global conditions: when all cases share the same
        # condition AND the same from_aspect, the condition applies to all
        # instructions even if deduplication reduced case_instructions to a subset.
        # This happens when an aspect writes a state uniformly for all instructions
        # (e.g., delay_slot.isa writes code_iasq for all 242 instructions) but
        # dedup collapses the group_members to just a few representatives.
        if not is_global_condition and all_have_same_condition:
            aspect_set = set(c.from_aspect for c in cases if c.from_aspect is not None)
            if len(aspect_set) == 1:
                is_global_condition = True
                print(f"    Detected aspect-global condition from {list(aspect_set)[0]}: "
                      f"{list(unique_conditions)[0]} (dedup reduced {len(all_instructions)} "
                      f"instrs to {len(case_instructions)})")

        if is_global_condition:
            # Use just the condition, no instruction enable gates needed
            # This is critical for instruction fetch exceptions where the instruction may be X
            cond_id = list(unique_conditions)[0]
            if cond_id in merged_graph.nodes:
                cond_node = merged_graph.nodes[cond_id]
                # Handle inverted conditions if any
                if cases[0].condition_inverted:
                    not_id = f"not{cond_id}"
                    if not_id not in merged_graph.nodes:
                        not_node = Node(not_id, {
                            'type': 'operation',
                            'operator': '!',
                            'display_name': f"NOT {cond_id}",
                            'bit_width': 1
                        })
                        merged_graph.add_node(not_node)
                        e_not = Edge(cond_node, not_node, data={'type': 'operand', 'operand_index': 0})
                        merged_graph.add_edge(e_not)
                    return merged_graph.nodes[not_id]
                return cond_node

        # Not a global condition - need to create AND nodes for each, then OR them
        and_nodes = []

        # Sort cases for deterministic iteration order
        sorted_cases = sorted(cases, key=lambda c: (c.source_instruction or '', c.condition_node_id or ''))
        for case in sorted_cases:
            enable_id = f"{case.source_instruction}_enable"
            cond_id = case.condition_node_id

            # For ternary true branch, condition is the ternary's condition node
            # We need: enable && condition
            # For ternary false branch, condition is inverted: enable && !condition
            if enable_id in merged_graph.nodes and cond_id and cond_id in merged_graph.nodes:
                enable_node = merged_graph.nodes[enable_id]
                cond_node = merged_graph.nodes[cond_id]

                # If condition is inverted (false branch of ternary), create NOT node
                if case.condition_inverted:
                    not_id = f"not{cond_id}"
                    if not_id not in merged_graph.nodes:
                        not_node = Node(not_id, {
                            'type': 'operation',
                            'operator': '!',
                            'display_name': f"NOT {cond_id}",
                            'bit_width': 1
                        })
                        merged_graph.add_node(not_node)

                        # Connect condition to NOT node
                        e_not = Edge(cond_node, not_node, data={'type': 'operand', 'operand_index': 0})
                        merged_graph.add_edge(e_not)
                    else:
                        not_node = merged_graph.nodes[not_id]

                    cond_node = not_node

                # Create AND node: enable && condition (or enable && !condition)
                # Include cond_id in naming to distinguish different conditions for the same value
                # e.g., add_pc_delegate_to_mmode_select vs add_pc_delegate_to_smode_select
                and_id = f"{case.source_instruction}_{value_node_id}_{cond_id}_select"
                if and_id not in merged_graph.nodes:
                    and_node = Node(and_id, {
                        'type': 'operation',
                        'operator': '&&',
                        'display_name': f"{case.source_instruction} selects {value_node_id}"
                    })
                    merged_graph.add_node(and_node)

                    # Connect inputs - use both 'position' and 'operand_index' for Verilog generator compatibility
                    e1 = Edge(enable_node, and_node, data={'type': 'operand', 'operand_index': 0, 'position': 0})
                    merged_graph.add_edge(e1)
                    e2 = Edge(cond_node, and_node, data={'type': 'operand', 'operand_index': 1, 'position': 1})
                    merged_graph.add_edge(e2)
                else:
                    and_node = merged_graph.nodes[and_id]

                and_nodes.append(and_node)
    
            elif enable_id in merged_graph.nodes:
                # No explicit condition - just use enable
                and_nodes.append(merged_graph.nodes[enable_id])
    
        if not and_nodes:
            return None
    
        if len(and_nodes) == 1:
            return and_nodes[0]
    
        # Create OR node combining all AND results
        # Use a simple naming based on the value AND the target register
        # This ensures each register gets its own select signal (flag_Z_wr's 1'b1 select != flag_C_wr's 1'b1 select)
        # Use 80 chars (not 20) to avoid truncation collisions between similar value node IDs
        # e.g., pc+10 vs pc+12 both truncated to same 20-char prefix
        value_short = value_node_id.replace('(', '').replace(')', '').replace(' ', '_')[:80]
        target_short = target_wr_node_id.replace('_wr', '') if target_wr_node_id else ''
        or_id = f"select_{value_short}_{target_short}_merged" if target_short else f"select_{value_short}_merged"

        if or_id not in merged_graph.nodes:
            or_node = Node(or_id, {
                'type': 'operation',
                'operator': '||',
                'display_name': f"Merged select for {value_node_id}",
                'merged_conditions': len(and_nodes),
                'merged_value_node_id': value_node_id
            })
            merged_graph.add_node(or_node)

            # Connect all AND nodes as inputs
            for i, and_node in enumerate(and_nodes):
                e = Edge(and_node, or_node, data={'type': 'operand', 'operand_index': i})
                merged_graph.add_edge(e)

            print(f"    Created OR node {or_id} merging {len(and_nodes)} conditions")
        else:
            or_node = merged_graph.nodes[or_id]
            # Safety check: verify we're not colliding with a different value group
            existing_value = or_node.data.get('merged_value_node_id', '')
            if existing_value and existing_value != value_node_id:
                # Truncation collision! Create a unique variant
                suffix = 1
                while or_id in merged_graph.nodes:
                    or_id = f"select_{value_short}_{target_short}_merged_{suffix}" if target_short else f"select_{value_short}_merged_{suffix}"
                    suffix += 1
                or_node = Node(or_id, {
                    'type': 'operation',
                    'operator': '||',
                    'display_name': f"Merged select for {value_node_id}",
                    'merged_conditions': len(and_nodes),
                    'merged_value_node_id': value_node_id
                })
                merged_graph.add_node(or_node)
                for i, and_node in enumerate(and_nodes):
                    e = Edge(and_node, or_node, data={'type': 'operand', 'operand_index': i})
                    merged_graph.add_edge(e)
                print(f"    WARNING: Name collision detected! Created unique OR node {or_id} merging {len(and_nodes)} conditions")
    
        return or_node
    
    def _cleanup_absorbed_ternaries(self, merged_graph: ResourceGraph):
        """Remove ternary nodes that were absorbed into flat muxes.
    
        After flat mux creation, ternary nodes that only fed into ISA state
        writes can be removed to simplify the graph.
        """
        nodes_to_remove = []
    
        for node_id, node in merged_graph.nodes.items():
            if node.data.get('absorbed_into_flat_mux'):
                # Check if this ternary has any other consumers
                has_other_consumers = False
                for edge in node.outgoing_edges:
                    if edge.data.get('type') == 'assignment':
                        target = edge.target
                        # If target is an ISA state write, it's now through the flat mux
                        if not target.data.get('is_arch_state'):
                            has_other_consumers = True
                            break

                if not has_other_consumers:
                    nodes_to_remove.append(node_id)

        # Actually remove the nodes
        for node_id in nodes_to_remove:
            merged_graph.remove_node(node_id)

        return len(nodes_to_remove)

    def _split_shared_node_for_mem_reads(self, merged_graph: ResourceGraph, target_id: str,
                                          unique_sources: Dict[str, tuple], instruction_specific_nodes: Dict[str, Set[str]]):
        """
        Split a shared target node into instruction-specific copies when sources are memory reads.

        This ensures each instruction has its own byte/halfword selection path from its memory read,
        avoiding conflicting assignments to the same wire.

        For example, if lb_byte_data is shared between LB and LBU, but they have different memory reads
        (lb_dmem[addr]_rd and lbu_dmem[addr]_rd), we need to:
        1. Remove the shared lb_byte_data node
        2. Update edges so each memory read goes directly to downstream nodes
        3. Create instruction-specific wires for byte selection in Verilog generator

        Actually, the simpler approach: remove the shared node and let each memory read
        wire directly to its downstream consumers. The Verilog generator will handle
        the byte selection logic for each memory read.
        """
        print(f"  Splitting shared node {target_id} for memory read sources")

        if target_id not in merged_graph.nodes:
            print(f"    Warning: {target_id} not in merged graph")
            return

        target_node = merged_graph.nodes[target_id]

        # Get all outgoing edges from the shared target (these are the downstream consumers)
        downstream_edges = list(target_node.outgoing_edges)

        # For each source (memory read), redirect its downstream edges
        # Instead of: mem_rd -> shared_var -> downstream
        # Make it:    mem_rd -> downstream (with byte selection in Verilog)
        for source_node_id, (source_node, instr_name) in unique_sources.items():
            # Find the assignment edge from this source to target
            source_to_target_edge = None
            for edge in source_node.outgoing_edges:
                if edge.target.id == target_id and edge.data.get('type') == 'assignment':
                    source_to_target_edge = edge
                    break

            if not source_to_target_edge:
                print(f"    Warning: No assignment edge from {source_node_id} to {target_id}")
                continue

            # Remove the edge from source to shared target
            merged_graph.remove_edge(source_to_target_edge.id)
            print(f"    Removed edge {source_node_id} -> {target_id}")

            # Connect source directly to each downstream node (if instruction matches)
            for downstream_edge in downstream_edges:
                downstream_node = downstream_edge.target
                edge_type = downstream_edge.data.get('type', 'operand')

                # Check if downstream node belongs to the same instruction
                # Only connect memory read to its instruction's downstream nodes
                downstream_instr = downstream_node.data.get('instruction', 'shared')
                if downstream_instr == 'shared':
                    # Check if this downstream node is instruction-specific via instruction_specific_nodes
                    for instr_check in instruction_specific_nodes.keys():
                        if downstream_node.id in instruction_specific_nodes[instr_check]:
                            downstream_instr = instr_check
                            break

                # Connect only if instructions match or if the downstream is shared
                if downstream_instr == instr_name or downstream_instr == 'shared':
                    # Create new edge from source to downstream
                    # This will let the Verilog generator apply byte selection from mem_rd directly
                    new_edge = Edge(
                        source_node,
                        downstream_node,
                        data=downstream_edge.data.copy() if downstream_edge.data else {'type': edge_type}
                    )
                    merged_graph.add_edge(new_edge)
                    print(f"    Connected {source_node_id} -> {downstream_node.id} ({edge_type})")
                else:
                    print(f"    Skipped {source_node_id} -> {downstream_node.id} (different instruction: {instr_name} vs {downstream_instr})")

        # Remove the shared target node (it's now replaced by direct connections)
        # First remove all downstream edges
        for edge in downstream_edges:
            merged_graph.remove_edge(edge.id)

        # Remove the node itself
        merged_graph.remove_node(target_id)
        print(f"    Removed shared node {target_id}")

    def _handle_variable_latency_operations(self, merged_graph: ResourceGraph, instruction_specific_nodes: Dict[str, Set[str]]):
        """
        Handle variable latency operations during instruction merging.

        For operations with variable latency (start/idle/complete signals):
        - If one instruction uses the operation and another doesn't
        - Wire the start signal as: instruction_enable & idle
        - This ensures the operation only starts when the instruction is active AND the operation is ready

        Args:
            merged_graph: The merged graph
            instruction_specific_nodes: Mapping of instruction names to their specific node IDs
        """

        print("\nHandling variable latency operations...")

        # Find all variable latency operations in the merged graph
        var_latency_ops = []
        for node_id, node in merged_graph.nodes.items():
            if node.variable_latency and node.data.get('has_start_input'):
                var_latency_ops.append(node)
                print(f"  Found variable latency operation: {node_id}")

        if not var_latency_ops:
            print("  No variable latency operations found")
            return

        # For each variable latency operation, determine which instructions use it
        for operation in var_latency_ops:
            self._wire_variable_latency_start_signal(merged_graph, operation, instruction_specific_nodes)

    def _wire_variable_latency_start_signal(self, merged_graph: ResourceGraph, operation: Node,
                                           instruction_specific_nodes: Dict[str, Set[str]]):
        """
        Wire up the start signal for a variable latency operation based on instruction enables.

        Creates logic: start = (instruction_A_enable & idle) | (instruction_B_enable & idle) | ...

        Args:
            merged_graph: The merged graph
            operation: The variable latency operation node
            instruction_specific_nodes: Mapping of instruction names to their specific node IDs
        """

        print(f"\n  Wiring start signal for {operation.id}...")

        # Get the start and idle signal nodes
        start_signal_id = operation.data.get('start_signal')
        idle_signal_id = operation.data.get('idle_signal')

        if not start_signal_id or not idle_signal_id:
            print(f"    WARNING: Missing start or idle signal for {operation.id}")
            return

        start_node = merged_graph.nodes.get(start_signal_id)
        idle_node = merged_graph.nodes.get(idle_signal_id)

        if not start_node or not idle_node:
            print(f"    WARNING: Start or idle signal node not found in graph")
            return

        # Determine which instructions use this operation
        # An instruction uses the operation if any of its nodes depend on it
        using_instructions = []

        for instr_name in instruction_specific_nodes.keys():
            # Check if this instruction's nodes depend on the operation
            uses_operation = False
            for instr_node_id in instruction_specific_nodes[instr_name]:
                if instr_node_id in merged_graph.nodes:
                    instr_node = merged_graph.nodes[instr_node_id]
                    # Check if this node depends on the operation (via incoming edges)
                    for edge in instr_node.incoming_edges:
                        if edge.source == operation or edge.source.id.startswith(f"{operation.id}_"):
                            uses_operation = True
                            break
                    if uses_operation:
                        break

            if uses_operation:
                using_instructions.append(instr_name)
                print(f"    Instruction '{instr_name}' uses this operation")

        if not using_instructions:
            print(f"    No instructions explicitly use this operation (may be shared)")
            return

        # Create start logic: OR of (instruction_enable & idle) for each using instruction
        # Create an OR gate to combine multiple instruction enables
        if len(using_instructions) == 1:
            # Single instruction - create: start = instruction_enable & idle
            instr_name = using_instructions[0]
            enable_signal_id = f"{instr_name}_enable"
            enable_node = merged_graph.nodes.get(enable_signal_id)

            if enable_node:
                # Create AND gate: instruction_enable & idle
                and_node = Node(
                    node_id=f"{operation.id}_start_and",
                    data={
                        'type': 'operation',
                        'operation_type': 'and',
                        'description': f"Start gate for {operation.id}: {instr_name}_enable & idle"
                    }
                )
                merged_graph.add_node(and_node)

                # Connect enable -> AND
                Edge(enable_node, and_node, data={'type': 'operand', 'operand_position': 0})
                # Connect idle -> AND
                Edge(idle_node, and_node, data={'type': 'operand', 'operand_position': 1})
                # Connect AND -> start (remove existing start edges first)
                for edge in list(start_node.incoming_edges):
                    merged_graph.remove_edge(edge.id)
                Edge(and_node, start_node, data={'type': 'assignment'})

                print(f"    Created start logic: {instr_name}_enable & idle")
        else:
            # Multiple instructions - create: start = (enable_A & idle) | (enable_B & idle) | ...
            # For simplicity, create: start = (enable_A | enable_B | ...) & idle

            # Create OR gate for instruction enables
            or_node = Node(
                node_id=f"{operation.id}_enable_or",
                data={
                    'type': 'operation',
                    'operation_type': 'or',
                    'description': f"OR of instruction enables for {operation.id}"
                }
            )
            merged_graph.add_node(or_node)

            # Connect all instruction enables to OR
            for i, instr_name in enumerate(using_instructions):
                enable_signal_id = f"{instr_name}_enable"
                enable_node = merged_graph.nodes.get(enable_signal_id)
                if enable_node:
                    Edge(enable_node, or_node, data={'type': 'operand', 'operand_position': i})

            # Create AND gate: (enable_A | enable_B | ...) & idle
            and_node = Node(
                node_id=f"{operation.id}_start_and",
                data={
                    'type': 'operation',
                    'operation_type': 'and',
                    'description': f"Start gate for {operation.id}: (enables) & idle"
                }
            )
            merged_graph.add_node(and_node)

            # Connect OR -> AND
            Edge(or_node, and_node, data={'type': 'operand', 'operand_position': 0})
            # Connect idle -> AND
            Edge(idle_node, and_node, data={'type': 'operand', 'operand_position': 1})
            # Connect AND -> start
            for edge in list(start_node.incoming_edges):
                merged_graph.remove_edge(edge.id)
            Edge(and_node, start_node, data={'type': 'assignment'})

            print(f"    Created start logic: ({' | '.join([f'{i}_enable' for i in using_instructions])}) & idle")

    def _cleanup_superseded_nodes(self, merged_graph: ResourceGraph, instruction_specific_nodes: Dict[str, Set[str]]):
        """Remove original nodes that are truly disconnected and superseded by instruction-specific versions."""

        # Collect all instruction-specific node IDs that were created
        all_instruction_specific_node_ids = set()
        for instr_name, node_ids in sorted(instruction_specific_nodes.items()):
            all_instruction_specific_node_ids.update(node_ids)

        # Only remove original nodes that are truly disconnected
        nodes_to_remove = []
        for node_id in all_instruction_specific_node_ids:
            if node_id in merged_graph.nodes:
                original_node = merged_graph.nodes[node_id]

                # Check if this node is completely disconnected (no incoming or outgoing edges)
                has_incoming = len(original_node.incoming_edges) > 0
                has_outgoing = len(original_node.outgoing_edges) > 0

                # Only remove if the node is completely disconnected
                if not has_incoming and not has_outgoing:
                    # Double-check that it has instruction-specific replacements
                    has_replacements = False
                    for instr_name in instruction_specific_nodes.keys():
                        instr_node_id = f"{instr_name}_{node_id}"
                        instr_node_id_spec = f"{instr_name}_{node_id}_spec"
                        if instr_node_id in merged_graph.nodes or instr_node_id_spec in merged_graph.nodes:
                            has_replacements = True
                            break

                    if has_replacements:
                        nodes_to_remove.append(node_id)
                        print(f"Removing truly disconnected superseded node: {node_id}")
                    else:
                        print(f"Keeping disconnected node {node_id} - no instruction-specific replacements found")
                else:
                    print(f"Keeping connected shared node: {node_id} (incoming: {has_incoming}, outgoing: {has_outgoing})")

        # Remove the truly superseded nodes
        for node_id in nodes_to_remove:
            merged_graph.remove_node(node_id)

        # Clean up orphaned instruction-specific nodes (nodes with no incoming OR outgoing edges)
        orphaned_nodes = []
        for node_id, node in merged_graph.nodes.items():
            # Check for instruction-specific nodes that have no incoming or outgoing edges
            if any(node_id.startswith(f"{instr}_") for instr in instruction_specific_nodes.keys()):
                has_incoming = len(node.incoming_edges) > 0
                has_outgoing = len(node.outgoing_edges) > 0
                # Only remove if node has neither incoming NOR outgoing edges
                # (literals like 1'b0 have no incoming edges but DO have outgoing edges to concatenations)
                if not has_incoming and not has_outgoing:
                    orphaned_nodes.append(node_id)
                    print(f"Found orphaned instruction-specific node: {node_id}")

        # Remove orphaned nodes
        for node_id in orphaned_nodes:
            merged_graph.remove_node(node_id)
            print(f"Removed orphaned node: {node_id}")

        # Clean up array_access _wr nodes that are superseded by shared write ports
        # e.g., rf[31]_wr superseded by rf_shared_wr, dmem[sw_addr]_wr superseded by dmem_shared_wr
        superseded_write_nodes = []
        for node_id, node in merged_graph.nodes.items():
            if node.data.get('type') == 'array_access' and node_id.endswith('_wr'):
                # Extract base memory name (e.g., "rf" from "rf[31]_wr", "dmem" from "dmem[sw_addr]_wr")
                if '[' in node_id:
                    base_name = node_id.split('[')[0]
                    shared_port_id = f"{base_name}_shared_wr"

                    # Check if there's a shared write port for this memory
                    if shared_port_id in merged_graph.nodes:
                        # This write is superseded by the shared port
                        superseded_write_nodes.append(node_id)
                        print(f"Found superseded array_access write: {node_id} (superseded by {shared_port_id})")

        # Remove the superseded write nodes and their assignment edges
        for node_id in superseded_write_nodes:
            merged_graph.remove_node(node_id)
            print(f"Removed superseded array_access write node: {node_id}")

        # Clean up operations that lost all their output edges (dead operations)
        dead_operations = []
        for node_id, node in merged_graph.nodes.items():
            if node.data.get('type') == 'operation' and len(node.outgoing_edges) == 0:
                dead_operations.append(node_id)
                print(f"Found dead operation (no outputs): {node_id}")

        # Remove dead operations
        for node_id in dead_operations:
            merged_graph.remove_node(node_id)
            print(f"Removed dead operation: {node_id}")

        # Clean up instruction-specific sink nodes (have incoming but no outgoing edges)
        # These are typically array accesses that only receive assignments but don't drive anything
        # BUT: Don't remove instruction_enable nodes - they are SUPPOSED to be sinks (control signals)
        # Also don't remove decode signal nodes - we need them for decode_enable edges

        # Collect all decode signal nodes to preserve
        # At this point nodes have been prefixed, so use prefixed names
        decode_signal_nodes = set()
        for instr_name, decode_info in self.decode_info.items():
            if decode_info.decode_signal_node:
                # Nodes are prefixed during _add_instruction_specific_nodes
                prefixed_node = f"{instr_name}_{decode_info.decode_signal_node}"
                decode_signal_nodes.add(prefixed_node)

        sink_nodes = []
        for node_id, node in merged_graph.nodes.items():
            if any(node_id.startswith(f"{instr}_") for instr in instruction_specific_nodes.keys()):
                # Skip instruction enable nodes - they're supposed to be sinks
                # Check both by type and by naming pattern (xxx_enable)
                if node.data.get('type') == 'instruction_enable' or node_id.endswith('_enable'):
                    continue

                # Skip byte_enable_computation nodes - they're used in memory writes
                # and need to be preserved for pipeline stages
                if node.data.get('type') == 'byte_enable_computation':
                    print(f"Preserving byte_enable_computation node: {node_id}")
                    continue

                # Skip decode signal nodes - we need them to connect to instruction_enable
                if node_id in decode_signal_nodes:
                    print(f"Preserving decode signal node: {node_id}")
                    continue

                # Skip array_access write nodes - they're side effects, not dead code
                # Check both is_write flag and access_mode field (ISA uses access_mode='write')
                is_write = (node.data.get('is_write') or
                           node.data.get('access_mode') == 'write')
                if node.data.get('type') == 'array_access' and is_write:
                    print(f"Preserving array_access write node: {node_id}")
                    continue

                # Skip architectural state nodes - they're important write targets
                # Note: instruction-specific copies (like beq_pc_wr) should have is_arch_state=False
                if node.is_arch_state:
                    print(f"Preserving architectural state node: {node_id}")
                    continue

                # Skip var nodes that are used as array indices in expressions
                # These may appear as sinks because the array_access nodes reference them
                # by unprefixed name in their expression data, not through edges
                if node.data.get('type') == 'var':
                    # Extract the unprefixed variable name properly by finding the matching
                    # instruction prefix first. This handles instruction names with underscores
                    # (e.g., "push_rm32_phys0" -> instruction="push_rm32", var="phys0")
                    unprefixed_name = None
                    instr_prefix = None
                    for instr in instruction_specific_nodes.keys():
                        prefix = f"{instr}_"
                        if node_id.startswith(prefix):
                            unprefixed_name = node_id[len(prefix):]
                            instr_prefix = instr
                            break

                    if unprefixed_name:
                        is_array_index = False

                        # Method 1: Check if any array_access node's expression uses this variable as index
                        for check_id, check_node in merged_graph.nodes.items():
                            if check_node.data.get('type') == 'array_access':
                                expr = check_node.data.get('expression', {})
                                if expr.get('type') == 'array_access':
                                    index_expr = expr.get('index', {})
                                    if index_expr.get('type') == 'identifier':
                                        index_name = index_expr.get('name', '')
                                        # Check for unprefixed name match
                                        if index_name == unprefixed_name:
                                            is_array_index = True
                                            break
                                        # Also check for prefixed name match (after merging)
                                        if index_name == node_id:
                                            is_array_index = True
                                            break

                        # Method 2: Check if this node has outgoing edges to array_access nodes
                        # The mux logic creates edges from address sources to array_access nodes
                        if not is_array_index:
                            for edge in node.outgoing_edges:
                                if edge.data.get('type') in ['array_index', 'mux_input']:
                                    is_array_index = True
                                    break

                        # Method 3: Check if this node is referenced in any address mux's mux_inputs
                        if not is_array_index:
                            for check_id, check_node in merged_graph.nodes.items():
                                if check_node.data.get('type') == 'one_hot_mux':
                                    mux_inputs = check_node.data.get('mux_inputs', [])
                                    for mux_input in mux_inputs:
                                        if mux_input.get('source_node') == node_id:
                                            is_array_index = True
                                            break
                                    if is_array_index:
                                        break

                        if is_array_index:
                            print(f"Preserving var node used as array index: {node_id}")
                            continue

                # Skip collision copies of architectural state variables
                # These are sink nodes because one instruction only writes to the state
                # (e.g., bl_lr where bl writes to lr but doesn't read it)
                # We need to preserve them to create proper _rd/_wr structure later
                original_id = node.data.get('original_id')
                if original_id:
                    # Check if original_id is an architectural state in any source graph
                    is_arch_state_copy = False
                    for instr_name, source_graph in self.graphs.items():
                        if original_id in source_graph.nodes:
                            if source_graph.nodes[original_id].is_arch_state:
                                is_arch_state_copy = True
                                break
                    if is_arch_state_copy:
                        print(f"Preserving collision copy of arch state: {node_id} (original: {original_id})")
                        continue

                has_incoming = len(node.incoming_edges) > 0
                has_outgoing = len(node.outgoing_edges) > 0
                if has_incoming and not has_outgoing:
                    sink_nodes.append(node_id)
                    print(f"Found instruction-specific sink node: {node_id}")

        # Remove sink nodes
        for node_id in sink_nodes:
            merged_graph.remove_node(node_id)
            print(f"Removed sink node: {node_id}")

        # Clean up ILA instruction nodes - these are semantic markers from ILA format
        # In ISA graphs, there are no explicit instruction nodes - the semantics are
        # encoded through decode logic, enables, and data flow. ILA instruction nodes
        # should be removed to match ISA structure.
        instruction_nodes = []
        for node_id, node in merged_graph.nodes.items():
            if node.data.get('type') == 'instruction':
                instruction_nodes.append(node_id)
                print(f"Found ILA instruction node: {node_id}")

        for node_id in instruction_nodes:
            merged_graph.remove_node(node_id)
            print(f"Removed ILA instruction node: {node_id}")

        # Connect collision copies of architectural state
        # When different instructions have different access patterns to the same arch state
        # (e.g., bclr reads lr, bl writes lr), we need to create proper _rd/_wr structure
        self._connect_arch_state_collision_copies(merged_graph, instruction_specific_nodes)

    def _connect_arch_state_collision_copies(self, merged_graph: ResourceGraph, instruction_specific_nodes: Dict):
        """
        Connect collision copies of architectural state variables.

        When different instructions have asymmetric access patterns to the same arch state:
        - Some instructions only read (e.g., bclr reads lr for branch target)
        - Some instructions only write (e.g., bl writes lr with return address)

        We need to:
        1. Identify all collision copies of each arch state
        2. Create shared {state}_rd and {state}_wr nodes if needed
        3. Connect read copies to {state}_rd
        4. Create mux for write copies to {state}_wr
        """
        print("\nConnecting architectural state collision copies...")

        # Find all collision copies of arch state, grouped by original_id
        arch_state_copies = {}  # original_id -> list of (node_id, node, is_write_only)

        for node_id, node in merged_graph.nodes.items():
            original_id = node.data.get('original_id')
            if not original_id:
                continue

            # Check if original is arch state in source graphs
            is_arch_state = False
            for instr_name, source_graph in self.graphs.items():
                if original_id in source_graph.nodes:
                    if source_graph.nodes[original_id].is_arch_state:
                        is_arch_state = True
                        break

            if not is_arch_state:
                continue

            # Determine if this is a write-only copy (sink node that was preserved)
            has_incoming = len(node.incoming_edges) > 0
            has_outgoing = len(node.outgoing_edges) > 0
            is_write_only = has_incoming and not has_outgoing

            if original_id not in arch_state_copies:
                arch_state_copies[original_id] = []
            arch_state_copies[original_id].append((node_id, node, is_write_only))

        if not arch_state_copies:
            print("  No arch state collision copies found")
            return

        for original_id, copies in arch_state_copies.items():
            print(f"  Found {len(copies)} collision copies of {original_id}:")
            for node_id, node, is_write_only in copies:
                access_type = "write-only" if is_write_only else "read"
                print(f"    - {node_id} ({access_type})")

            # Separate read and write copies
            read_copies = [(nid, n) for nid, n, wo in copies if not wo]
            write_copies = [(nid, n) for nid, n, wo in copies if wo]

            if not write_copies:
                print(f"    No write copies - skipping")
                continue

            # Check if there's already a {state}_wr node
            wr_node_id = f"{original_id}_wr"
            rd_node_id = f"{original_id}_rd"

            if wr_node_id in merged_graph.nodes:
                print(f"    {wr_node_id} already exists - will add to mux")
            else:
                print(f"    Creating {wr_node_id} node")
                # Get width from one of the copies
                sample_node = copies[0][1]
                bit_width = sample_node.data.get('bit_width', 64)

                # Create the _wr node
                from .resource_graph import Node
                wr_node = Node(
                    wr_node_id,
                    {'type': 'var', 'name': wr_node_id, 'bit_width': bit_width},
                    is_arch_state=False,  # It's a derived write port
                    is_uarch_state=False,
                    uarch_time=0
                )
                merged_graph.add_node(wr_node)

            # Track this for mux creation
            if not hasattr(self, '_arch_state_wr_nodes_needing_mux'):
                self._arch_state_wr_nodes_needing_mux = set()
            self._arch_state_wr_nodes_needing_mux.add(wr_node_id)

            # Get the _wr node (we created it or it already exists)
            wr_node = merged_graph.nodes[wr_node_id]

            # Rewire write copies to feed the _wr node
            # Connect each write source directly to _wr - the existing _create_arch_state_mux_flat
            # will handle muxing if there are multiple writers
            from .resource_graph import Edge

            for write_node_id, write_node in write_copies:
                incoming_assignment = None
                for edge in write_node.incoming_edges:
                    if edge.data.get('type') == 'assignment':
                        incoming_assignment = edge
                        break

                if incoming_assignment:
                    source_node = incoming_assignment.source
                    instr_prefix = write_node_id.split('_')[0]

                    edge_id = f"{source_node.id}_to_{wr_node_id}_from_{instr_prefix}"
                    edge_data = {
                        'type': 'assignment',
                        'instruction': instr_prefix,
                        'from_collision_copy': write_node_id
                    }
                    new_edge = Edge(source_node, wr_node, edge_id=edge_id, data=edge_data)
                    merged_graph.add_edge(new_edge)

                    print(f"    Connected {source_node.id} -> {wr_node_id} (from {write_node_id})")

                    # Remove the collision copy if it has no other uses
                    if len(write_node.outgoing_edges) == 0:
                        merged_graph.remove_node(write_node_id)
                        print(f"    Removed collision copy {write_node_id} (now redundant)")

            # For read copies, we need to:
            # 1. Create an {state}_rd node if it doesn't exist
            # 2. Rewire users of the read copies to read from {state}_rd
            # 3. Remove the read collision copies
            # Also need to create _rd even if no read copies (for sequential update)

            # Always ensure _rd node exists for sequential update
            if rd_node_id not in merged_graph.nodes:
                print(f"    Creating {rd_node_id} node")
                # Get width from one of the copies
                sample_node = copies[0][1]
                bit_width = sample_node.data.get('bit_width', 64)

                # Create the _rd node as an arch state (so it gets sequential update)
                from .resource_graph import Node
                rd_node = Node(
                    rd_node_id,
                    {'type': 'var', 'name': rd_node_id, 'bit_width': bit_width,
                     'original_arch_state': original_id},
                    is_arch_state=True,  # It's arch state for sequential update
                    is_uarch_state=False,
                    uarch_time=0
                )
                merged_graph.add_node(rd_node)
            else:
                rd_node = merged_graph.nodes[rd_node_id]

            # Add state_update edge from _wr to _rd
            # This triggers the Verilog generator to declare _rd as wire and base name as reg
            # But skip if there's already a state_update edge to _rd
            has_state_update = any(e.data.get('type') == 'state_update' for e in rd_node.incoming_edges)
            if not has_state_update:
                state_update_edge_id = f"{wr_node_id}_to_{rd_node_id}_state_update"
                state_update_edge = Edge(
                    merged_graph.nodes[wr_node_id],
                    rd_node,
                    edge_id=state_update_edge_id,
                    data={'type': 'state_update'}
                )
                merged_graph.add_edge(state_update_edge)
                print(f"    Added state_update edge: {wr_node_id} -> {rd_node_id}")

            # Now rewire users of read copies to read from rd_node
            if read_copies:
                for read_node_id, read_node in read_copies:
                    # Get all outgoing edges from this read copy
                    # and rewire them to come from rd_node instead
                    outgoing_edges = list(read_node.outgoing_edges)
                    for edge in outgoing_edges:
                        target_node = edge.target
                        # Create new edge from rd_node to target
                        edge_id = f"{rd_node_id}_to_{target_node.id}_from_{read_node_id}"
                        new_edge = Edge(rd_node, target_node, edge_id=edge_id, data=edge.data)
                        merged_graph.add_edge(new_edge)
                        # Remove old edge
                        merged_graph.remove_edge(edge.id)

                    print(f"    Rewired {len(outgoing_edges)} users of {read_node_id} to {rd_node_id}")

                    # Remove the read collision copy
                    merged_graph.remove_node(read_node_id)
                    print(f"    Removed collision copy {read_node_id}")

            # Store reference for sequential update generation
            if not hasattr(self, '_arch_state_rd_wr_pairs'):
                self._arch_state_rd_wr_pairs = {}
            self._arch_state_rd_wr_pairs[original_id] = (rd_node_id, wr_node_id)

    def _promote_mem_widths(self, merged_graph: ResourceGraph):
        """
        Promote mem node widths based on actual access patterns in the merged graph.

        For each mem node with width_inferred=True:
        1. Find all memory access nodes (array_access or split _rd/_wr nodes)
        2. Determine the maximum access width
        3. Promote the mem node's bit_width to the maximum
        """
        print("Promoting mem widths based on access patterns...")

        # Find all mem nodes
        mem_nodes = [n for n in merged_graph.nodes.values()
                     if n.data.get('type') == 'isa_state mem' and n.data.get('width_inferred')]

        for mem_node in mem_nodes:
            mem_name = mem_node.data['name']
            access_widths = []

            # Find all nodes that access this memory
            # After splitting, these will be named like "dmem[addr]_rd" or "lw_dmem[addr]_wr"
            for node in merged_graph.nodes.values():
                # Skip concatenation nodes - they combine multiple reads but are not memory accesses
                # themselves. They may contain memory node names in their IDs like
                # "{mainmem[pc_plus_1]_rd, mainmem[pc]_rd}" but this doesn't mean they're memory accesses.
                if node.data.get('type') == 'concatenation':
                    continue

                # Check if this is a split memory access node
                # Pattern: [instr_]memname[...]_rd or [instr_]memname[...]_wr
                if f'{mem_name}[' in node.id and ('_rd' in node.id or '_wr' in node.id):
                    # This is a split memory access node
                    width = node.data.get('bit_width')

                    # If width is None, try to infer from connected nodes
                    if width is None:
                        # For _rd nodes, look at outgoing edges to see what uses this data
                        # Collect ALL widths and take maximum (shared nodes may connect to multiple users)
                        # BUT: Skip concatenation targets - they combine multiple narrow reads into
                        # wider values but don't indicate the individual read width. For example,
                        # {mainmem[pc_plus_1], mainmem[pc]} is 16 bits total, but each read is 8 bits.
                        if '_rd' in node.id:
                            connected_widths = []
                            for edge in node.outgoing_edges:
                                target = edge.target
                                # Skip concatenation targets - their width is sum of parts, not individual part width
                                if target.data.get('type') == 'concatenation':
                                    continue
                                # Skip edges that go to concatenation inputs
                                if edge.data.get('type') in ['concat_input', 'concatenation_input']:
                                    continue
                                target_width = target.data.get('bit_width')
                                if target_width is not None and target_width > 0:
                                    connected_widths.append(target_width)
                            if connected_widths:
                                width = max(connected_widths)

                        # For _wr nodes, look at incoming assignment edges
                        # Collect ALL widths and take maximum (shared nodes may have multiple writers)
                        elif '_wr' in node.id:
                            connected_widths = []
                            for edge in node.incoming_edges:
                                if edge.data.get('type') == 'assignment':
                                    source = edge.source
                                    source_width = source.data.get('bit_width')
                                    if source_width is not None and source_width > 0:
                                        connected_widths.append(source_width)
                            if connected_widths:
                                width = max(connected_widths)

                    if width is not None and width > 0:
                        access_widths.append(width)
                        continue

                # Also check for regular array_access nodes (before splitting)
                if node.data.get('type') == 'array_access':
                    # Check if this access is for our memory
                    base_node = None
                    for edge in node.incoming_edges:
                        if edge.data.get('type') == 'array_base':
                            base_node = edge.source
                            break

                    if base_node and base_node.id == mem_name:
                        # Found an access to this memory
                        width = node.data.get('bit_width')
                        if width is not None and width > 0:
                            access_widths.append(width)

            # Promote to maximum width (or constrained width if specified)
            if access_widths:
                max_width = max(access_widths)

                # Apply memory constraint if specified
                if mem_name in self.memory_constraints:
                    constraint = self.memory_constraints[mem_name]
                    if constraint < max_width:
                        mem_node.data['bit_width'] = constraint
                        print(f"  Constrained {mem_name} to {constraint} bits (access widths: {set(access_widths)}, max: {max_width})")
                        print(f"    Note: Accesses wider than {constraint} bits will use multi-cycle logic")

                        # Propagate constrained width to all memory access nodes
                        self._propagate_mem_width_to_accesses(merged_graph, mem_name, constraint)
                    else:
                        mem_node.data['bit_width'] = max_width
                        print(f"  Promoted {mem_name} to {max_width} bits (constraint {constraint} not binding)")
                else:
                    mem_node.data['bit_width'] = max_width
                    print(f"  Promoted {mem_name} to {max_width} bits (access widths: {set(access_widths)})")

                # Store all access widths on the memory node for downstream use
                # This allows the port width setter to generate proper byte enable logic
                # Merge with existing access_widths (which may have been set by _create_memory_write_mux)
                existing_widths = mem_node.data.get('access_widths', [])
                all_widths = list(set(existing_widths + access_widths))

                # Normalize access widths to standard power-of-2 values (8, 16, 32, 64)
                # This handles cases like 33-bit result variables that shouldn't create sub-word stores
                def normalize_width(w):
                    if w <= 8:
                        return 8
                    elif w <= 16:
                        return 16
                    elif w <= 32:
                        return 32
                    elif w <= 64:
                        return 64
                    else:
                        return 64  # Cap at 64 bits
                all_widths = list(set(normalize_width(w) for w in all_widths))

                mem_node.data['access_widths'] = all_widths
                print(f"    Stored access_widths={all_widths} for {mem_name}")
            else:
                # No accesses found, use constraint or default to 32 bits
                if mem_name in self.memory_constraints:
                    mem_node.data['bit_width'] = self.memory_constraints[mem_name]
                    print(f"  No accesses found for {mem_name}, using constraint: {self.memory_constraints[mem_name]} bits")
                else:
                    mem_node.data['bit_width'] = 32
                    print(f"  No accesses found for {mem_name}, defaulting to 32 bits")

    def _propagate_mem_width_to_accesses(self, graph: ResourceGraph, mem_name: str, width: int):
        """
        Propagate memory width to all access nodes for this memory.

        This ensures that split nodes like `dmem[addr]_rd` have the correct
        memory width set, which is needed for the Verilog generator to detect
        when accesses are wider than the memory port.

        Args:
            graph: The ResourceGraph to update
            mem_name: Name of the memory (e.g., 'dmem')
            width: The memory width in bits
        """
        updated_count = 0

        for node in graph.nodes.values():
            # Check if this is a memory access node for this memory
            # Pattern: [instr_]memname[...]_rd or [instr_]memname[...]_wr
            if f'{mem_name}[' in node.id and ('_rd' in node.id or '_wr' in node.id):
                # This is a split memory access node - set its bit_width to memory width
                node.data['bit_width'] = width
                updated_count += 1

        if updated_count > 0:
            print(f"    Propagated {width}-bit width to {updated_count} access node(s)")

    def _multiplex_memory_write_ports(self, merged_graph: ResourceGraph, instruction_specific_nodes: Dict[str, Set[str]]):
        """
        Create multiplexers for memory write ports when multiple instructions
        write to the same base memory with different addresses.

        For example, if ADD writes to rf[rd] and LW writes to rf[rt], this creates:
        - Address mux: rf_write_addr = add_enable ? rd : rt
        - Data mux: rf_write_data = add_enable ? res : data

        IMPORTANT: When a single instruction has multiple writes to the same memory
        (e.g., JSR pushing 2 bytes to stack), we create SEPARATE write ports for each.
        Only inter-instruction writes (different instructions) are muxed together.
        """

        # Analyze original instruction graphs to find memory writes
        # Key is (base_memory, bit_range) where bit_range is None for full writes
        # or (high, low) for partial writes. This keeps byte/word/long writes separate.
        memory_writes = {}  # (base_memory, bit_range) -> list of write info dicts

        # Track write order within each (instruction, memory, bit_range) triple
        # This ensures intra-instruction writes get different write_index values
        instr_mem_write_counts = {}  # (instr_name, base_memory, bit_range) -> count

        for instr_name, instr_graph in self.graphs.items():
            # Find all array access nodes that are write targets
            for node_id, node in instr_graph.nodes.items():
                if node.data.get('type') == 'array_access':
                    # Check if this is a write (ISA-style: assignment edges, or ILA-style: is_write flag)
                    is_ila_write = node.data.get('is_write', False)

                    # Collect writes per-assignment-edge (each edge may have different enable conditions)
                    # This properly handles multiple conditional writes to the same array access
                    # e.g., rf[15] when (exc_taken) = exc_new_sp AND rf[15] when (rte_is_privileged) = rte_new_sp
                    writes_from_edges = []  # List of (source_id, enable_expr) tuples

                    # ISA-style: Check for assignment edges and their individual enable conditions
                    for edge in node.incoming_edges:
                        if edge.data.get('type') == 'assignment':
                            source_id = edge.source.id
                            # Get enable from edge data (set during parsing for 'when' clauses)
                            edge_enable = edge.data.get('enable')
                            # Fallback to node's enable if edge doesn't have one
                            if edge_enable is None:
                                edge_enable = node.data.get('enable')
                            writes_from_edges.append((source_id, edge_enable))

                    # ILA-style: Check for write_data edges
                    if is_ila_write:
                        for edge in node.incoming_edges:
                            if edge.data.get('type') == 'write_data':
                                source_id = edge.source.id
                                # ILA writes use write_enable edge, not per-edge enables
                                writes_from_edges.append((source_id, None))

                    if writes_from_edges:
                        base_memory = None
                        index_node_id = None

                        # ILA-style: Extract base memory and index from operand edges
                        if is_ila_write:
                            for edge in node.incoming_edges:
                                if edge.data.get('type') == 'operand':
                                    pos = edge.data.get('position')
                                    if pos == 0:
                                        base_memory = edge.source.data.get('name', edge.source.id)
                                    elif pos == 1:
                                        index_node_id = edge.source.id
                            # ILA enable from write_enable edge
                            ila_enable = None
                            for edge in node.incoming_edges:
                                if edge.data.get('type') == 'write_enable':
                                    ila_enable = edge.source.id
                                    break
                            # Apply ILA enable to all writes
                            writes_from_edges = [(src, ila_enable) for src, _ in writes_from_edges]

                        # ISA-style: Extract base memory and index from incoming edges
                        else:
                            for edge in node.incoming_edges:
                                edge_type = edge.data.get('type')
                                if edge_type == 'array_base':
                                    base_memory = edge.source.data.get('name', edge.source.id)
                                elif edge_type == 'array_index':
                                    index_node_id = edge.source.id

                        # Store write info if we found the base memory
                        if base_memory:
                            # Use compound key (base_memory, None) for full writes
                            write_key = (base_memory, None)
                            if write_key not in memory_writes:
                                memory_writes[write_key] = []

                            # Group writes by enable_expr - writes with same enable can share a port,
                            # writes with different enables need separate handling
                            enable_groups = {}
                            for source_id, enable_expr in writes_from_edges:
                                # Use string representation of enable_expr as key
                                enable_key = str(enable_expr) if enable_expr else 'None'
                                if enable_key not in enable_groups:
                                    enable_groups[enable_key] = {'enable': enable_expr, 'sources': []}
                                enable_groups[enable_key]['sources'].append(source_id)

                            # Create separate write entries for each enable group
                            for enable_key, group_info in sorted(enable_groups.items()):
                                # Determine write_index: which write this is within the instruction
                                key = (instr_name, base_memory)
                                write_index = instr_mem_write_counts.get(key, 0)
                                instr_mem_write_counts[key] = write_index + 1

                                memory_writes[write_key].append({
                                    'instruction': instr_name,
                                    'array_access_id': node_id,
                                    'index_id': index_node_id,
                                    'data_source_ids': group_info['sources'],
                                    'enable_expr': group_info['enable'],
                                    'write_index': write_index
                                })

                                # Debug: enable_str = f" when {group_info['enable']}" if group_info['enable'] else ""

                # Also check for bit_slice nodes that write to array elements (e.g., dregs[idx][7:0])
                # These are generated when using the 'of' keyword for sub-register views
                elif node.data.get('type') == 'bit_slice':
                    # Collect writes with their enable expressions (matching array_access pattern)
                    writes_from_edges = []
                    for edge in node.incoming_edges:
                        if edge.data.get('type') == 'assignment':
                            source_id = edge.source.id
                            edge_enable = edge.data.get('enable')
                            if edge_enable is None:
                                edge_enable = node.data.get('enable')
                            writes_from_edges.append((source_id, edge_enable))

                    if writes_from_edges:
                        # Extract base memory and index from expression.target
                        expr = node.data.get('expression', {})
                        target = expr.get('target', {})
                        bit_range = expr.get('range')

                        if target.get('type') == 'array_access':
                            base_array = target.get('target', {})
                            base_memory = base_array.get('name')
                            index_expr = target.get('index', {})

                            # Build the index node ID - needs to match what's in the graph
                            # For binary ops like (0 | dst_reg), the node ID is "(0 | dst_reg)"
                            index_node_id = None
                            if index_expr.get('type') == 'binary_op':
                                op = index_expr.get('operator')
                                left = index_expr.get('left', {})
                                right = index_expr.get('right', {})
                                left_str = str(left.get('value', left.get('name', '')))
                                right_str = right.get('name', str(right.get('value', '')))
                                index_node_id = f"({left_str} {op} {right_str})"
                            elif index_expr.get('type') == 'identifier':
                                index_node_id = index_expr.get('name')
                            elif index_expr.get('type') == 'literal':
                                index_node_id = str(index_expr.get('value'))

                            if base_memory:
                                # Use compound key (base_memory, bit_range) to keep partial writes separate
                                write_key = (base_memory, bit_range)
                                if write_key not in memory_writes:
                                    memory_writes[write_key] = []

                                # Group writes by enable_expr (matching array_access pattern)
                                enable_groups = {}
                                for source_id, enable_expr in writes_from_edges:
                                    enable_key = str(enable_expr) if enable_expr else 'None'
                                    if enable_key not in enable_groups:
                                        enable_groups[enable_key] = {'enable': enable_expr, 'sources': []}
                                    enable_groups[enable_key]['sources'].append(source_id)

                                for enable_key, group_info in sorted(enable_groups.items()):
                                    # Determine write_index
                                    key = (instr_name, base_memory, bit_range)
                                    write_index = instr_mem_write_counts.get(key, 0)
                                    instr_mem_write_counts[key] = write_index + 1

                                    memory_writes[write_key].append({
                                        'instruction': instr_name,
                                        'array_access_id': node_id,
                                        'index_id': index_node_id,
                                        'data_source_ids': group_info['sources'],
                                        'enable_expr': group_info['enable'],
                                        'write_index': write_index,
                                        'bit_range': bit_range  # track bit range for partial writes
                                    })

                                    range_str = f"[{bit_range[0]}:{bit_range[1]}]" if bit_range else ""
                                    enable_str = f" when {group_info['enable']}" if group_info['enable'] else ""
                                    print(f"Found bit_slice write: {instr_name} writes to {base_memory}[{index_node_id}]{range_str}{enable_str} from {group_info['sources']} (write_index={write_index})")

        # Build a mapping from base_memory to all bit_ranges that write to it
        # If a base_memory has multiple bit_ranges (e.g., full write AND partial writes),
        # then ALL writes to that memory need to be conditional, even single-writer cases
        memory_to_bit_ranges = {}  # base_memory -> set of bit_ranges
        for (base_memory, bit_range), writes in memory_writes.items():
            if base_memory not in memory_to_bit_ranges:
                memory_to_bit_ranges[base_memory] = set()
            memory_to_bit_ranges[base_memory].add(bit_range)

        # For each (memory, bit_range) pair, group writes by write_index and create separate ports
        # This ensures intra-instruction writes (same instruction, different write_index)
        # get separate ports, while inter-instruction writes (different instructions,
        # same write_index) share a muxed port
        for (base_memory, bit_range), writes in memory_writes.items():
            if len(writes) == 0:
                continue

            # Create a descriptive name for this write port
            if bit_range:
                range_str = f"[{bit_range[0]}:{bit_range[1]}]"
                mem_desc = f"{base_memory}{range_str}"
            else:
                range_str = ""
                mem_desc = base_memory

            # Find the maximum write_index for this memory
            max_write_index = max(w['write_index'] for w in writes)

            # Check if any instruction has multiple writes (intra-instruction multi-write)
            has_multi_write = max_write_index > 0
            if has_multi_write:
                print(f"\n{mem_desc}: Detected intra-instruction multi-write (max_write_index={max_write_index})")
                for w in writes:
                    print(f"  {w['instruction']} write_index={w['write_index']}: {mem_desc}[{w['index_id']}] <- {w['data_source_ids']}")

            # Check if this base_memory has mixed bit_ranges (e.g., full writes AND partial writes)
            # If so, all writes need to be gated to avoid conflicts
            has_mixed_bit_ranges = len(memory_to_bit_ranges.get(base_memory, set())) > 1
            if has_mixed_bit_ranges:
                print(f"\n{mem_desc}: Detected mixed bit_ranges for {base_memory}: {memory_to_bit_ranges[base_memory]}")

            # Create a separate port for each write_index
            for port_idx in range(max_write_index + 1):
                # Get all writes with this write_index
                port_writes = [w for w in writes if w['write_index'] == port_idx]

                if len(port_writes) == 0:
                    continue

                # Only create mux if multiple instructions write to this port
                # (single instruction means no muxing needed for this port)
                unique_instrs = set(w['instruction'] for w in port_writes)

                # Check if single writer has a guard (enable_expr) - needs write port for proper gating
                single_writer_has_guard = (len(port_writes) == 1 and
                                           port_writes[0].get('enable_expr') is not None)

                if len(port_writes) > 1 or has_multi_write or bit_range or has_mixed_bit_ranges or single_writer_has_guard:
                    # Multiple writes to this port OR we have multi-write OR we have partial writes (bit_range)
                    # OR we have mixed bit_ranges for this memory (full writes + partial writes)
                    # Need port even for single partial writes to ensure proper enable gating
                    port_suffix = f"_{port_idx}" if max_write_index > 0 else ""
                    print(f"\nCreating write port {mem_desc}{port_suffix} with {len(port_writes)} writer(s): {list(unique_instrs)}")
                    for w in port_writes:
                        print(f"  {w['instruction']}: {mem_desc}[{w['index_id']}] <- {w['data_source_ids']}")

                    self._create_memory_write_mux(merged_graph, base_memory, port_writes, port_index=port_idx, bit_range=bit_range)
                elif len(port_writes) == 1:
                    # Single writer to full register, no multi-write - use original behavior (no explicit port needed)
                    print(f"\n{mem_desc}: Single writer {port_writes[0]['instruction']}, no mux needed")

    @staticmethod
    def _sanitize_cond_id(cond_id: str) -> str:
        """Convert a condition expression to a valid Verilog identifier fragment."""
        s = cond_id
        s = s.replace('!=', '_ne_')
        s = s.replace('==', '_eq_')
        s = s.replace('~', 'inv')
        s = s.replace('&&', '_and_')
        s = s.replace('||', '_or_')
        s = s.replace('&', '_and_')
        s = s.replace('|', '_or_')
        s = s.replace('^', '_xor_')
        s = s.replace('!', 'not')
        s = s.replace(' ', '_')
        s = s.replace('(', '').replace(')', '')
        # Clean up multiple underscores
        while '__' in s:
            s = s.replace('__', '_')
        return s.strip('_')

    def _create_memory_write_mux(self, merged_graph: ResourceGraph, base_memory: str, writes: List[Dict], port_index: int = 0, bit_range: tuple = None):
        """
        Create multiplexers for memory write address and data.

        Args:
            base_memory: Name of the base memory (e.g., 'rf')
            writes: List of write info dicts with keys: instruction, index_id, data_source_ids
            port_index: Index of this write port (0 for first/only port, 1+ for additional ports)
            bit_range: Optional (high, low) tuple for partial writes (e.g., (7, 0) for byte writes)
        """
        from .resource_graph import Node, Edge

        # Create port suffix for multi-port memories
        port_suffix = f"_{port_index}" if port_index > 0 else ""

        # Create bit range suffix for partial writes
        if bit_range:
            bit_range_suffix = f"_{bit_range[0]}_{bit_range[1]}"
            bit_range_display = f"[{bit_range[0]}:{bit_range[1]}]"
        else:
            bit_range_suffix = ""
            bit_range_display = ""

        # Create unified write port node with clear naming
        write_port_id = f"{base_memory}_shared_wr{port_suffix}{bit_range_suffix}"
        instr_list = ', '.join([w['instruction'] for w in writes])

        # Collect writer widths for byte-lane selection generation
        writer_widths = {}
        for w in writes:
            instr_name = w['instruction']
            data_ids = w['data_source_ids']

            # Try to find the data width for this writer
            for data_id in data_ids:
                # Use GroupTracker to get correct merged ID if available
                merged_data_id = None
                if hasattr(self, '_group_tracker') and self._group_tracker:
                    merged_data_id = self._group_tracker.get_merged_id(instr_name, data_id)

                # Check in order: merged_id from GroupTracker, instruction-prefixed, then original
                if merged_data_id and merged_data_id in merged_graph.nodes:
                    data_node = merged_graph.nodes[merged_data_id]
                elif f"{instr_name}_{data_id}" in merged_graph.nodes:
                    data_node = merged_graph.nodes[f"{instr_name}_{data_id}"]
                elif data_id in merged_graph.nodes:
                    data_node = merged_graph.nodes[data_id]
                else:
                    continue

                width = data_node.data.get('bit_width')

                # If width is not explicitly set, try to infer from node type
                if width is None:
                    node_type = data_node.data.get('type')

                    # For concatenation nodes, sum widths of all inputs
                    if node_type == 'concatenation':
                        total_width = 0
                        for edge in data_node.incoming_edges:
                            src = edge.source
                            src_width = src.data.get('bit_width')
                            if src_width is None:
                                # Try to infer from repetition count
                                if src.data.get('type') == 'repetition':
                                    src_width = src.data.get('count', 1)
                                # Try to infer from binary literal (e.g., 16'b0)
                                elif src.data.get('type') == 'sized_literal':
                                    display_name = src.data.get('display_name', src.id)
                                    if "'" in display_name:
                                        width_str = display_name.split("'")[0]
                                        try:
                                            src_width = int(width_str)
                                        except ValueError:
                                            src_width = 32
                                    else:
                                        src_width = 32
                                else:
                                    src_width = 32
                            total_width += src_width
                        if total_width > 0:
                            width = total_width
                    # For repetition nodes, width = count
                    elif node_type == 'repetition':
                        width = data_node.data.get('count', 32)
                    # For bit_slice nodes, compute width from slice range
                    elif node_type == 'bit_slice':
                        expr = data_node.data.get('expression', {})
                        if expr.get('type') == 'bit_slice':
                            slice_range = expr.get('range')
                            if slice_range and len(slice_range) == 2:
                                high, low = slice_range
                                width = high - low + 1
                    else:
                        # Check if this comes from an array access (like rf)
                        for edge in data_node.incoming_edges:
                            src = edge.source
                            if src.data.get('type') == 'array_access':
                                # Extract array name from node id (e.g., "rf[rs2]_rd" -> "rf")
                                array_name = src.id.split('[')[0] if '[' in src.id else None
                                if array_name and array_name in merged_graph.nodes:
                                    array_node = merged_graph.nodes[array_name]
                                    width = array_node.data.get('bit_width')
                                    break
                            # Also check if source has explicit width
                            elif src.data.get('bit_width'):
                                width = src.data.get('bit_width')
                                break
                if width:
                    writer_widths[instr_name] = width
                    break

        write_port_node = Node(write_port_id, {
            'type': 'memory_write_port',
            'name': write_port_id,
            'display_name': f"{base_memory}{bit_range_display} Shared Write Port{port_suffix} ({instr_list})",
            'base_memory': base_memory,
            'port_index': port_index,  # Track which port this is for multi-port memories
            'bit_range': bit_range,  # Store bit range for partial writes (e.g., (7, 0) for byte)
            'num_writers': len(writes),
            'writers': [w['instruction'] for w in writes],
            'writer_widths': writer_widths  # Store widths for byte-lane selection
        })
        merged_graph.add_node(write_port_node)

        # Create write address multiplexer using MuxBuilder
        addr_mux_id = f"{base_memory}_write_addr_mux{port_suffix}{bit_range_suffix}"
        addr_builder = MuxBuilder(merged_graph, addr_mux_id, MuxType.ONE_HOT)

        # Create write data multiplexer using MuxBuilder
        data_mux_id = f"{base_memory}_write_data_mux{port_suffix}{bit_range_suffix}"
        data_builder = MuxBuilder(merged_graph, data_mux_id, MuxType.ONE_HOT)

        # First pass: collect all address and data sources to check if muxes are needed
        addr_sources = []  # List of (index_node, enable_node, instr_name)
        data_sources = []  # List of (data_source_node, enable_node, instr_name)

        # Connect address inputs, data inputs, and enable signals
        for i, write_info in enumerate(writes):
            instr_name = write_info['instruction']
            index_node_id = write_info['index_id']
            data_source_ids = write_info['data_source_ids']
            enable_expr = write_info.get('enable_expr')

            # Get instruction enable signal
            # Use the instruction_enable node (not the internal _enable_and gate)
            instr_enable_signal = f"{instr_name}_enable"
            instr_enable_node = merged_graph.nodes.get(instr_enable_signal)

            # Store the shared enable condition for later - don't create AND nodes here
            # The mux builder will handle inlining the condition
            shared_enable_cond_node = None
            if enable_expr and instr_enable_node:
                # Enable expr can be either:
                # - ISA: dict like {'type': 'binary_op', 'operator': '!=', 'left': ..., 'right': ...}
                # - ILA: string node ID like 'rf_wr_enable'

                if isinstance(enable_expr, str):
                    # ILA case: enable_expr is a node ID
                    shared_enable_cond_node = merged_graph.nodes.get(enable_expr)
                    if not shared_enable_cond_node:
                        # Try instruction-specific version
                        instr_specific_enable = f"{instr_name}_{enable_expr}"
                        shared_enable_cond_node = merged_graph.nodes.get(instr_specific_enable)

                    if shared_enable_cond_node:
                        print(f"  Using shared enable condition: {shared_enable_cond_node.id}")

                elif isinstance(enable_expr, dict):
                    # ISA case: dict expression - use _get_or_create_condition_node_id
                    # to properly handle nested expressions like ((rn_bk == 0) & ok)
                    cond_node_id = self._get_or_create_condition_node_id(
                        merged_graph, enable_expr, instr_name)
                    if cond_node_id:
                        shared_enable_cond_node = merged_graph.nodes.get(cond_node_id)
                        if shared_enable_cond_node:
                            print(f"  Using enable condition: {cond_node_id}")
                        else:
                            print(f"  WARNING: Condition node '{cond_node_id}' not found in graph")
                    else:
                        print(f"  WARNING: Could not get/create condition node for {enable_expr}")

            # Use instruction enable as the select, with shared condition stored separately
            enable_node = instr_enable_node
            enable_signal = instr_enable_signal

            # Collect index node for address mux
            if index_node_id:
                # Use GroupTracker to get correct merged ID if available
                if hasattr(self, '_group_tracker') and self._group_tracker:
                    merged_index_id = self._group_tracker.get_merged_id(instr_name, index_node_id)
                else:
                    # Fallback: try instruction-specific version (e.g., add_rd instead of rd)
                    merged_index_id = f"{instr_name}_{index_node_id}"

                if merged_index_id in merged_graph.nodes:
                    index_node = merged_graph.nodes[merged_index_id]
                    print(f"  Using index {merged_index_id} for {instr_name}")
                elif index_node_id in merged_graph.nodes:
                    index_node = merged_graph.nodes[index_node_id]
                    print(f"  Using shared index {index_node_id}")
                else:
                    print(f"  WARNING: Neither {merged_index_id} nor {index_node_id} found in merged graph")
                    index_node = None

                if index_node:
                    addr_sources.append((index_node, enable_node, instr_name))

            # Collect data sources for data mux
            for data_source_id in data_source_ids:
                # Use GroupTracker to get correct merged ID if available
                if hasattr(self, '_group_tracker') and self._group_tracker:
                    merged_data_id = self._group_tracker.get_merged_id(instr_name, data_source_id)
                else:
                    # Fallback: try instruction-specific version (e.g., add_res instead of res)
                    merged_data_id = f"{instr_name}_{data_source_id}"

                if merged_data_id in merged_graph.nodes:
                    data_source_node = merged_graph.nodes[merged_data_id]
                    print(f"  Using data source {merged_data_id} for {instr_name}")
                elif data_source_id in merged_graph.nodes:
                    data_source_node = merged_graph.nodes[data_source_id]
                    print(f"  Using shared data source {data_source_id}")
                else:
                    print(f"  WARNING: Neither {merged_data_id} nor {data_source_id} found in merged graph")
                    continue

                # Store enable_node, shared_enable_cond_node, and instr_name
                data_sources.append((data_source_node, enable_node, instr_name, shared_enable_cond_node))

        # Group instructions by their enable condition
        # Some may share one condition (e.g., rd != 0), others a different condition (e.g., rt != 0)
        cond_to_instrs = {}  # shared_cond_id -> [(enable_node, instr_name), ...]
        instrs_without_cond = []  # Instructions with no shared condition

        for _, enable_node, instr_name, shared_cond in data_sources:
            if shared_cond:
                cond_id = shared_cond.id
                if cond_id not in cond_to_instrs:
                    cond_to_instrs[cond_id] = []
                cond_to_instrs[cond_id].append((enable_node, instr_name))
            else:
                instrs_without_cond.append((enable_node, instr_name))

        # Create combined write enable
        combined_write_enable_node = None
        guarded_enable_nodes = []  # List of enable nodes to OR together

        # For each group with a shared condition, create: (instr1_enable || instr2_enable || ...) && condition
        for cond_id, instrs in cond_to_instrs.items():
            shared_cond_node = merged_graph.nodes[cond_id]
            instr_enables = [en for en, _ in instrs if en]

            if len(instr_enables) == 0:
                continue

            if len(instr_enables) > 1:
                # Create OR of instruction enables
                sanitized_cond = self._sanitize_cond_id(cond_id)
                or_node_id = f"{base_memory}{port_suffix}{bit_range_suffix}_{sanitized_cond}_enables"
                or_data = {
                    'type': 'logical_or',
                    'operation': '||',
                    'display_name': f"{base_memory}{bit_range_display}{port_suffix} writes with {cond_id}"
                }
                or_node = Node(or_node_id, or_data)
                merged_graph.add_node(or_node)

                for enable_node in instr_enables:
                    e = Edge(enable_node, or_node, data={'type': 'logic_input'})
                    merged_graph.add_edge(e)

                # Create AND: OR_result && condition
                and_node_id = f"{base_memory}{port_suffix}{bit_range_suffix}_{sanitized_cond}_guarded_enable"
                and_data = {
                    'type': 'logical_and',
                    'operation': '&&',
                    'display_name': f"{base_memory}{bit_range_display}{port_suffix} guarded enable for {cond_id}"
                }
                and_node = Node(and_node_id, and_data)
                merged_graph.add_node(and_node)

                e = Edge(or_node, and_node, data={'type': 'logic_input'})
                merged_graph.add_edge(e)
                e = Edge(shared_cond_node, and_node, data={'type': 'logic_input'})
                merged_graph.add_edge(e)

                guarded_enable_nodes.append(and_node)
                print(f"  Created guarded enable: ({' || '.join([n.id for n in instr_enables])}) && {cond_id}")
            else:
                # Single instruction with condition - just AND with condition
                sanitized_cond = self._sanitize_cond_id(cond_id)
                and_node_id = f"{base_memory}{port_suffix}{bit_range_suffix}_{sanitized_cond}_guarded_enable"
                and_data = {
                    'type': 'logical_and',
                    'operation': '&&',
                    'display_name': f"{base_memory}{bit_range_display}{port_suffix} guarded enable for {cond_id}"
                }
                and_node = Node(and_node_id, and_data)
                merged_graph.add_node(and_node)

                e = Edge(instr_enables[0], and_node, data={'type': 'logic_input'})
                merged_graph.add_edge(e)
                e = Edge(shared_cond_node, and_node, data={'type': 'logic_input'})
                merged_graph.add_edge(e)

                guarded_enable_nodes.append(and_node)
                print(f"  Created guarded enable: {instr_enables[0].id} && {cond_id}")

        # Add instructions without conditions (e.g., jal writing to r31 unconditionally)
        if instrs_without_cond:
            print(f"  WARNING: {len(instrs_without_cond)} instructions have no condition guard:")
            for enable_node, instr_name in instrs_without_cond:
                if enable_node:
                    print(f"    - {instr_name}: {enable_node.id}")
                    guarded_enable_nodes.append(enable_node)

        # Now combine all guarded enables with OR
        if len(guarded_enable_nodes) > 1:
            # Multiple groups/conditions - OR them together
            # Include bit_range_suffix to differentiate byte/word/full write enables
            final_or_id = f"{base_memory}_write_enable{port_suffix}{bit_range_suffix}"
            final_or_data = {
                'type': 'logical_or',
                'operation': '||',
                'display_name': f"{base_memory}{bit_range_display}{port_suffix} combined write enable"
            }
            final_or_node = Node(final_or_id, final_or_data)
            merged_graph.add_node(final_or_node)

            for guarded_node in guarded_enable_nodes:
                e = Edge(guarded_node, final_or_node, data={'type': 'logic_input'})
                merged_graph.add_edge(e)

            combined_write_enable_node = final_or_node
            print(f"  Combined write enable: {' || '.join([n.id for n in guarded_enable_nodes])}")
        elif len(guarded_enable_nodes) == 1:
            # Single guarded enable - use it directly
            combined_write_enable_node = guarded_enable_nodes[0]
            print(f"  Single write enable: {combined_write_enable_node.id}")

        # Store combined write enable on write port node if it exists
        if combined_write_enable_node:
            write_port_node.data['combined_write_enable'] = combined_write_enable_node.id
            print(f"  Stored combined write enable '{combined_write_enable_node.id}' on write port node")

            # Create edge from write enable to write port
            # This allows pipeline scripts to find and cut this edge for pipelining
            enable_edge = Edge(combined_write_enable_node, write_port_node, data={'type': 'write_enable'})
            merged_graph.add_edge(enable_edge)
            print(f"  Connected write enable '{combined_write_enable_node.id}' -> '{write_port_node.id}'")

        # Second pass: check if muxes are needed or if all sources are the same
        # If all address sources are the same shared node, bypass mux
        addr_needs_mux = len(addr_sources) > 1 and len(set(src[0].id for src in addr_sources)) > 1
        data_needs_mux = len(data_sources) > 1 and len(set(src[0].id for src in data_sources)) > 1

        # Connect address mux or wire directly
        if addr_needs_mux:
            print(f"  Creating address mux with {len(addr_sources)} inputs from different sources")
            addr_builder.create_or_get_mux(display_name=f"{base_memory} Write Address MUX")
            for i, (index_node, enable_node, instr_name) in enumerate(addr_sources):
                if enable_node:
                    addr_builder.add_input(
                        source=index_node,
                        select=enable_node,
                        input_index=i,
                        metadata={'source_instruction': instr_name}
                    )
                else:
                    addr_builder.add_input(
                        source=index_node,
                        select=f"{instr_name}_enable == 1",
                        input_index=i,
                        metadata={'source_instruction': instr_name}
                    )
                print(f"  Connected {index_node.id} to address mux input {i}")
        elif len(addr_sources) > 0:
            # All sources are the same - wire directly without mux
            shared_addr_node = addr_sources[0][0]
            print(f"  All {len(addr_sources)} instructions use same address source '{shared_addr_node.id}' - bypassing mux")
            # Remove the mux node that was created
            if addr_mux_id in merged_graph.nodes:
                merged_graph.remove_node(addr_mux_id)

        # Connect data mux or wire directly
        if data_needs_mux:
            print(f"  Creating data mux with {len(data_sources)} inputs from different sources")
            data_builder.create_or_get_mux(display_name=f"{base_memory} Write Data MUX")

            # Determine the maximum data width from all sources
            # This allows MuxBuilder to automatically create zero_extend nodes for narrow inputs
            max_data_width = 32  # Default
            for data_source_node, _, _, _ in data_sources:
                source_width = data_source_node.data.get('bit_width', 32)
                if source_width > max_data_width:
                    max_data_width = source_width
            data_builder.set_bit_width(max_data_width)

            for i, (data_source_node, enable_node, instr_name, shared_cond) in enumerate(data_sources):
                if enable_node:
                    select_node = enable_node
                    data_builder.add_input(
                        source=data_source_node,
                        select=select_node,
                        input_index=i,
                        metadata={'source_instruction': instr_name}
                    )
                else:
                    data_builder.add_input(
                        source=data_source_node,
                        select=f"{instr_name}_enable == 1",
                        input_index=i,
                        metadata={'source_instruction': instr_name}
                    )
        elif len(data_sources) > 0:
            # All sources are the same - wire directly without mux
            shared_data_node = data_sources[0][0]
            print(f"  All {len(data_sources)} instructions use same data source '{shared_data_node.id}' - bypassing mux")
            # Remove the mux node that was created
            if data_mux_id in merged_graph.nodes:
                merged_graph.remove_node(data_mux_id)

        # Set data_width for address and data muxes by inferring from first input
        # For address mux, infer from first index node (should be 5 bits for register file address)
        # For data mux, infer from first data source (should be 32 bits for register data)
        addr_mux_node = merged_graph.nodes.get(addr_mux_id)
        data_mux_node = merged_graph.nodes.get(data_mux_id)

        if addr_mux_node and len(writes) > 0:
            # Get the first index node to infer bit width
            first_index_id = writes[0]['index_id']
            first_instr = writes[0]['instruction']
            instr_specific_index_id = f"{first_instr}_{first_index_id}"

            if instr_specific_index_id in merged_graph.nodes:
                index_node = merged_graph.nodes[instr_specific_index_id]
            elif first_index_id in merged_graph.nodes:
                index_node = merged_graph.nodes[first_index_id]
            else:
                index_node = None

            addr_width = 32  # Default
            if index_node:
                # Try to get bit_width from node data
                if 'bit_width' in index_node.data and index_node.data['bit_width'] is not None:
                    addr_width = index_node.data['bit_width']
                # Try width field
                elif 'width' in index_node.data and index_node.data['width'] is not None:
                    addr_width = index_node.data['width']
                # If it's a bit_slice, calculate from the range
                elif index_node.data.get('type') == 'bit_slice':
                    expr = index_node.data.get('expression', {})
                    if 'range' in expr:
                        high, low = expr['range']
                        addr_width = high - low + 1
                # Otherwise, look at incoming edges to find a bit_slice source
                else:
                    for edge in index_node.incoming_edges:
                        if edge.data.get('type') in ['assignment', 'dataflow']:
                            source = edge.source
                            if source.data.get('type') == 'bit_slice':
                                source_expr = source.data.get('expression', {})
                                if 'range' in source_expr:
                                    high, low = source_expr['range']
                                    addr_width = high - low + 1
                                    break
                print(f"  Inferred address width from {index_node.id}: {addr_width} bits")

            addr_mux_node.data['data_width'] = addr_width
            addr_mux_node.data['output_width'] = addr_width
            print(f"  Set address mux data_width = {addr_width} bits")

        if data_mux_node and len(writes) > 0:
            # Get the MAXIMUM data width from ALL data sources
            # This is critical for mixed-width stores (e.g., sb+sh+sw)
            data_widths = []

            for write in writes:
                data_ids = write['data_source_ids']
                instr = write['instruction']

                for data_id in data_ids:
                    # Use GroupTracker to get correct merged ID if available
                    # This handles collision nodes like mtspr_xer_rs_val instead of rs_val
                    if hasattr(self, '_group_tracker') and self._group_tracker:
                        merged_data_id = self._group_tracker.get_merged_id(instr, data_id)
                    else:
                        # Fallback: try instruction-specific version
                        merged_data_id = f"{instr}_{data_id}"

                    if merged_data_id in merged_graph.nodes:
                        data_node = merged_graph.nodes[merged_data_id]
                    elif data_id in merged_graph.nodes:
                        data_node = merged_graph.nodes[data_id]
                    else:
                        continue

                    # Get bit_width from node data
                    width = data_node.data.get('bit_width')

                    # If width is not explicitly set, try to infer from node type
                    if width is None:
                        node_type = data_node.data.get('type')

                        # For concatenation nodes, sum widths of all inputs
                        if node_type == 'concatenation':
                            total_width = 0
                            for edge in data_node.incoming_edges:
                                src = edge.source
                                src_width = src.data.get('bit_width')
                                if src_width is None:
                                    # Try to infer from repetition count
                                    if src.data.get('type') == 'repetition':
                                        src_width = src.data.get('count', 1)
                                    # Try to infer from binary literal (e.g., 16'b0)
                                    elif src.data.get('type') == 'sized_literal':
                                        # Extract width from display_name like "16'b0"
                                        display_name = src.data.get('display_name', src.id)
                                        if "'" in display_name:
                                            width_str = display_name.split("'")[0]
                                            try:
                                                src_width = int(width_str)
                                            except ValueError:
                                                src_width = 32
                                        else:
                                            src_width = 32
                                    else:
                                        # Fallback: assume 32 bits for unknown
                                        src_width = 32
                                total_width += src_width
                            if total_width > 0:
                                width = total_width
                        # For repetition nodes, width = count * inner_width (inner usually 1 bit)
                        elif node_type == 'repetition':
                            width = data_node.data.get('count', 32)
                        # For bit_slice nodes, compute width from slice range
                        elif node_type == 'bit_slice':
                            expr = data_node.data.get('expression', {})
                            if expr.get('type') == 'bit_slice':
                                slice_range = expr.get('range')
                                if slice_range and len(slice_range) == 2:
                                    high, low = slice_range
                                    width = high - low + 1
                        else:
                            # Try to infer from source edges
                            for edge in data_node.incoming_edges:
                                src = edge.source
                                if src.data.get('type') == 'array_access':
                                    # Extract array name from node id (e.g., "rf_rd[rs2]_rd" -> "rf")
                                    array_name = src.id.split('[')[0] if '[' in src.id else None
                                    # Strip _rd/_wr suffix if present (after arch state splitting)
                                    if array_name and array_name.endswith('_rd'):
                                        array_name = array_name[:-3]
                                    elif array_name and array_name.endswith('_wr'):
                                        array_name = array_name[:-3]
                                    if array_name and array_name in merged_graph.nodes:
                                        array_node = merged_graph.nodes[array_name]
                                        width = array_node.data.get('bit_width')
                                        break
                                elif src.data.get('bit_width'):
                                    width = src.data.get('bit_width')
                                    break

                    if width is not None:
                        data_widths.append(width)
                        print(f"  Found data width from {data_node.id}: {width} bits")

            # Use maximum width to accommodate all stores
            data_width = max(data_widths) if data_widths else 32
            print(f"  Inferred data mux width from {len(data_widths)} sources: {data_width} bits (max of {set(data_widths)})")

            data_mux_node.data['data_width'] = data_width
            data_mux_node.data['output_width'] = data_width
            print(f"  Set data mux data_width = {data_width} bits")

        # Connect mux outputs (or shared nodes) to write port
        if addr_needs_mux:
            addr_builder.connect_output(write_port_node, 'write_address')
        elif len(addr_sources) > 0:
            # Wire shared address node directly to write port
            shared_addr_node = addr_sources[0][0]
            addr_edge = Edge(shared_addr_node, write_port_node, data={'type': 'write_address'})
            merged_graph.add_edge(addr_edge)
            print(f"  Wired shared address '{shared_addr_node.id}' directly to write port")

        if data_needs_mux:
            data_builder.connect_output(write_port_node, 'write_data')
        elif len(data_sources) > 0:
            # Wire shared data node directly to write port
            shared_data_node = data_sources[0][0]
            data_edge = Edge(shared_data_node, write_port_node, data={'type': 'write_data'})
            merged_graph.add_edge(data_edge)
            print(f"  Wired shared data '{shared_data_node.id}' directly to write port")

        # Connect write port to base memory
        if base_memory in merged_graph.nodes:
            base_memory_node = merged_graph.nodes[base_memory]
            port_to_mem_edge = Edge(write_port_node, base_memory_node, data={
                'type': 'memory_write'
            })
            merged_graph.add_edge(port_to_mem_edge)
        else:
            print(f"  WARNING: Could not find memory node for {base_memory}")

        print(f"\nCreated write port for {base_memory}:")
        if addr_needs_mux:
            print(f"  Address MUX: {addr_mux_id}")
        else:
            print(f"  Address: {addr_sources[0][0].id if addr_sources else 'none'} (shared, no mux needed)")
        if data_needs_mux:
            print(f"  Data MUX: {data_mux_id}")
        else:
            print(f"  Data: {data_sources[0][0].id if data_sources else 'none'} (shared, no mux needed)")
        print(f"  Write Port: {write_port_id}")

        # Create byte enable logic for narrow stores
        # Use the data mux width (which is the maximum of all writers) as the effective memory width
        # This is needed because width promotion happens later, so base memory might not be promoted yet
        if data_mux_node:
            effective_mem_width = data_mux_node.data.get('data_width')
        elif len(data_sources) > 0:
            # No mux - use width of shared data source
            shared_data_node = data_sources[0][0]
            effective_mem_width = shared_data_node.data.get('bit_width') or shared_data_node.data.get('width')
        else:
            effective_mem_width = None

        # Only create byte enables for actual mem-type memories (not register files)
        base_mem_node = merged_graph.nodes.get(base_memory)
        is_mem = base_mem_node and base_mem_node.data.get('type') == 'isa_state mem'

        if is_mem and effective_mem_width and effective_mem_width > 8:
            # Create byte enable logic for each narrow writer
            for instr_name, data_width in writer_widths.items():
                if data_width < effective_mem_width and data_width >= 8:
                    # Create byte enable computation node
                    byte_enable_id = f"{instr_name}_byte_enable"

                    # Skip if this instruction already has a byte_enable
                    # from an earlier port.  Only port 0 uses byte_enable
                    # logic; ports 1+ use case-based alignment.  Without
                    # this guard, add_node would overwrite port 0's node,
                    # wiring the byte_enable to the wrong address mux.
                    if byte_enable_id in merged_graph.nodes:
                        continue

                    # Get the enable signal for this instruction
                    enable_signal_id = f"{instr_name}_enable_and"

                    # Create byte enable node
                    byte_enable_node = Node(byte_enable_id, {
                        'type': 'byte_enable_computation',
                        'name': byte_enable_id,
                        'display_name': f"{instr_name} Byte Enable ({data_width}-bit store)",
                        'data_width': data_width,
                        'memory_width': effective_mem_width,
                        'instruction': instr_name,
                        'bit_width': effective_mem_width // 8,  # Number of byte enable bits
                    })
                    merged_graph.add_node(byte_enable_node)
                    print(f"    Created byte enable node for {instr_name} ({data_width}-bit store to {effective_mem_width}-bit memory)")

                    # Connect address source (mux or shared node) to byte enable (to compute which byte lanes)
                    if addr_mux_node:
                        addr_source = addr_mux_node
                    elif len(addr_sources) > 0:
                        addr_source = addr_sources[0][0]  # Use shared address node
                    else:
                        addr_source = None

                    if addr_source:
                        addr_to_be_edge = Edge(addr_source, byte_enable_node, data={
                            'type': 'byte_enable_address'
                        })
                        merged_graph.add_edge(addr_to_be_edge)

                    # Connect enable signal to byte enable (to gate the enable)
                    if enable_signal_id in merged_graph.nodes:
                        enable_node = merged_graph.nodes[enable_signal_id]
                        enable_to_be_edge = Edge(enable_node, byte_enable_node, data={
                            'type': 'byte_enable_gate'
                        })
                        merged_graph.add_edge(enable_to_be_edge)

                    # Connect byte enable to write port
                    be_to_port_edge = Edge(byte_enable_node, write_port_node, data={
                        'type': 'byte_enable',
                        'instruction': instr_name
                    })
                    merged_graph.add_edge(be_to_port_edge)

            # Store access_widths on the memory node for downstream transformations
            # This captures sub-word access patterns (8, 16, 32 bits) before they get merged
            if writer_widths and base_mem_node:
                existing_widths = base_mem_node.data.get('access_widths', [])
                new_widths = list(set(existing_widths + list(writer_widths.values())))
                base_mem_node.data['access_widths'] = new_widths
                print(f"    Updated {base_memory} access_widths={new_widths} from write port widths")

        # Remove the original rf[xx]_wr nodes that were superseded by the shared write port
        nodes_to_remove = []
        for write_info in writes:
            instr_name = write_info['instruction']
            # The array_access_id is like "rf_rd_wr" from the original instruction graph
            # But in the merged graph it's been prefixed to "ADD_rf_rd_wr", "ADDI_rf_rd_wr", etc.
            array_access_id = write_info['array_access_id']

            # Try to find the prefixed version in the merged graph
            prefixed_id = f"{instr_name}_{array_access_id}"
            if prefixed_id in merged_graph.nodes:
                nodes_to_remove.append(prefixed_id)
            elif array_access_id in merged_graph.nodes:
                # Fallback to unprefixed (shouldn't normally happen after our fix)
                nodes_to_remove.append(array_access_id)

        for node_id in nodes_to_remove:
            print(f"  Removing superseded write node: {node_id}")
            merged_graph.remove_node(node_id)

    def _multiplex_memory_read_ports(self, merged_graph: ResourceGraph, instruction_specific_nodes: Dict[str, Set[str]]):
        """
        Create multiplexers for memory read addresses when multiple instructions
        read from the same memory with different addresses.

        For example, if ld_a_bc reads mainmem[{B,C}] and ld_a_de reads mainmem[{D,E}], this creates:
        - Address mux: mainmem_read_addr = ld_a_bc_enable ? bc_addr : de_addr
        - Single read node uses the muxed address

        This is analogous to _multiplex_memory_write_ports but for reads.
        """
        from .resource_graph import Node, Edge

        print("\n" + "=" * 60)
        print("MULTIPLEXING MEMORY READ PORTS")
        print("=" * 60)

        # Analyze original instruction graphs to find memory reads
        memory_reads = {}  # base_memory -> list of read info dicts

        for instr_name, instr_graph in self.graphs.items():
            # Find all array access nodes that are reads (not writes)
            for node_id, node in instr_graph.nodes.items():
                if node.data.get('type') == 'array_access':
                    # Skip writes
                    is_write = node.data.get('is_write', False) or node.data.get('access_mode') == 'write'
                    if is_write:
                        continue

                    # Check for assignment edges (indicates this is a write target, not a read)
                    has_assignment_in = any(e.data.get('type') == 'assignment' for e in node.incoming_edges)
                    if has_assignment_in:
                        continue

                    # This is a memory read - get base memory and index
                    base_memory = None
                    index_node_id = None

                    for edge in node.incoming_edges:
                        edge_type = edge.data.get('type')
                        if edge_type == 'array_base':
                            base_memory = edge.source.data.get('name', edge.source.id)
                        elif edge_type == 'array_index':
                            index_node_id = edge.source.id

                    # Also check expression data if edges don't have type info
                    if not base_memory or not index_node_id:
                        expr = node.data.get('expression', {})
                        if expr.get('type') == 'array_access':
                            array_expr = expr.get('target', {})
                            if not base_memory and array_expr.get('type') == 'identifier':
                                base_memory = array_expr.get('name')
                            index_expr = expr.get('index', {})
                            if not index_node_id and index_expr.get('type') == 'identifier':
                                index_node_id = index_expr.get('name')

                    # Skip if we couldn't identify base memory or if it's not a 'mem' type
                    if not base_memory or not index_node_id:
                        continue

                    # Check if this is a 'mem' type memory (mainmem, etc.)
                    mem_node = instr_graph.nodes.get(base_memory)
                    if not mem_node:
                        continue
                    if mem_node.data.get('type') != 'isa_state mem':
                        continue

                    # Skip instruction fetch reads (reads from mainmem[pc])
                    # These are shared across all instructions and don't need muxing
                    if 'pc' in index_node_id.lower():
                        continue

                    if base_memory not in memory_reads:
                        memory_reads[base_memory] = []

                    memory_reads[base_memory].append({
                        'instruction': instr_name,
                        'array_access_id': node_id,
                        'index_id': index_node_id,
                    })

                    print(f"Found read: {instr_name} reads {base_memory}[{index_node_id}]")

        # For each memory with multiple unique read addresses, create address mux
        for base_memory, reads in memory_reads.items():
            if len(reads) <= 1:
                continue

            # Group reads by their address pattern (unprefixed index name)
            # e.g., "ld_a_bc_mem_addr" and "ld_a_de_mem_addr" are different patterns
            unique_addrs = {}  # unprefixed_index -> list of (instr_name, prefixed_index)
            for r in reads:
                instr_name = r['instruction']
                index_id = r['index_id']
                # The prefixed version in merged graph
                prefixed_index = f"{instr_name}_{index_id}" if index_id and not index_id.startswith(instr_name) else index_id

                # Check if this address exists in merged graph
                if prefixed_index not in merged_graph.nodes:
                    # Try unprefixed
                    if index_id in merged_graph.nodes:
                        prefixed_index = index_id
                    else:
                        # Skip if we can't find the address node
                        continue

                if prefixed_index not in unique_addrs:
                    unique_addrs[prefixed_index] = []
                unique_addrs[prefixed_index].append(instr_name)

            if len(unique_addrs) <= 1:
                # All instructions use the same address, no mux needed
                continue

            print(f"\n{base_memory}: Creating read address mux for {len(unique_addrs)} unique address sources")
            for addr, instrs in unique_addrs.items():
                print(f"  {addr}: used by {instrs}")

            # Create the address mux
            self._create_memory_read_address_mux(merged_graph, base_memory, unique_addrs)

    def _create_memory_read_address_mux(self, merged_graph: ResourceGraph, base_memory: str, addr_sources: Dict[str, List[str]]):
        """
        Create an address mux for memory read operations.

        Args:
            base_memory: Name of the base memory (e.g., 'mainmem')
            addr_sources: Dict mapping address node IDs to list of instructions using that address
        """
        from .resource_graph import Node, Edge

        # Find the data read node in merged graph that uses one of our address sources
        # We need to find the node that has incoming edges from our address sources,
        # NOT the instruction fetch nodes (which use PC-based addresses)
        read_node = None
        read_node_id = None
        addr_source_ids = set(addr_sources.keys())

        for node_id, node in merged_graph.nodes.items():
            if node.data.get('type') == 'array_access':
                # Skip nodes with 'pc' in the name (instruction fetches)
                if 'pc' in node_id.lower():
                    continue

                # Check if this reads from our memory
                reads_from_memory = False
                uses_our_addresses = False

                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'array_base':
                        source_name = edge.source.data.get('name', edge.source.id)
                        if source_name == base_memory or edge.source.id == base_memory:
                            reads_from_memory = True
                    elif edge.data.get('type') == 'array_index':
                        # Check if this index comes from one of our address sources
                        if edge.source.id in addr_source_ids:
                            uses_our_addresses = True

                if reads_from_memory:
                    # Check it's a read (not a write)
                    is_write = node.data.get('is_write', False) or node.data.get('access_mode') == 'write'
                    if not is_write and uses_our_addresses:
                        read_node = node
                        read_node_id = node_id
                        break

        if not read_node:
            print(f"  Warning: Could not find data read node for {base_memory} using addresses {list(addr_source_ids)[:5]}...")
            return

        print(f"  Found read node: {read_node_id}")

        # Determine bit width from address sources
        addr_width = 16  # Default for Z80
        for addr_id in addr_sources.keys():
            if addr_id in merged_graph.nodes:
                width = merged_graph.nodes[addr_id].data.get('bit_width')
                if width:
                    addr_width = width
                    break

        # Create address mux node
        mux_id = f"{base_memory}_read_addr_mux"
        mux_inputs = []

        for addr_id, instrs in addr_sources.items():
            # Create enable expression (OR of all instruction enables using this address)
            enable_ids = [f"{instr}_enable" for instr in instrs]
            mux_inputs.append({
                'source_node': addr_id,
                'enable_node': enable_ids if len(enable_ids) > 1 else enable_ids[0] if enable_ids else None,
                'instructions': instrs
            })

        mux_data = {
            'type': 'one_hot_mux',
            'name': mux_id,
            'display_name': f"{base_memory} Read Address MUX",
            'bit_width': addr_width,
            'mux_inputs': mux_inputs,
            'is_address_mux': True,
            'memory_read_node': read_node_id
        }
        mux_node = Node(mux_id, mux_data, is_uarch_state=False)
        merged_graph.add_node(mux_node)
        print(f"  Created address mux node: {mux_id}")

        # Add edges from address sources to mux
        for addr_id in addr_sources.keys():
            if addr_id in merged_graph.nodes:
                addr_node = merged_graph.nodes[addr_id]
                edge = Edge(addr_node, mux_node, data={'type': 'mux_input'})
                merged_graph.add_edge(edge)

        # Remove old index edges from read node
        old_index_edges = [e for e in list(read_node.incoming_edges)
                         if e.data.get('type') == 'array_index']
        for edge in old_index_edges:
            if edge.id in merged_graph.edges:
                del merged_graph.edges[edge.id]
                edge.source.outgoing_edges.discard(edge)
                edge.target.incoming_edges.discard(edge)
                print(f"  Removed old index edge: {edge.source.id} -> {read_node_id}")

        # Add new index edge from mux to read node
        new_index_edge = Edge(mux_node, read_node, data={
            'type': 'array_index',
            'from_address_mux': True
        })
        merged_graph.add_edge(new_index_edge)
        print(f"  Added mux -> read edge: {mux_id} -> {read_node_id}")

    def _find_ternary_condition_for_read(self, node, merged_graph):
        """
        Check if an array read node is inside a ternary conditional expression.

        If the array read has an outgoing edge of type 'ternary_true', it means
        the read is the 'true' branch of a ternary like:
            vm_enabled ? dmem[addr] : 0

        In this case, the read should only happen when the condition is true.
        Returns the condition node if found, None otherwise.
        """
        for edge in node.outgoing_edges:
            if edge.data.get('type') == 'ternary_true':
                ternary_node = edge.target
                # Find the condition input to this ternary
                for ternary_edge in ternary_node.incoming_edges:
                    if ternary_edge.data.get('type') == 'ternary_condition':
                        return ternary_edge.source
        return None

    def _create_read_enable_signals(self, merged_graph: ResourceGraph):
        """
        Create read enable signals for partially shared array read ports.

        For each array read port (e.g., rf[rs1]_rd, rf[rs2]_rd) that is only used by
        a subset of instructions, create an OR of the instruction enables:
            rf_rs1_rd_enable = add_enable || addi_enable || beq_enable || sw_enable || ...
            rf_rs2_rd_enable = add_enable || beq_enable || sw_enable || ...

        If the array read is inside a ternary conditional (e.g., vm_enabled ? dmem[addr] : 0),
        the condition is ANDed with the instruction enables:
            dmem_pte1_addr_rd_enable = vm_enabled && (lw_enable || sw_enable || ...)

        These signals can be used by hazard resolution to gate stall conditions,
        preventing false stalls when instructions like JAL/LUI/AUIPC don't actually
        use rs1/rs2 (those bit fields contain immediate values in those instructions).
        """
        from .resource_graph import Node, Edge

        print("\n" + "=" * 60)
        print("CREATING READ ENABLE SIGNALS")
        print("=" * 60)

        # Look for partially shared nodes that are array reads
        # Pattern: {array}[{index}]_rd (e.g., rf[rs1]_rd, rf[rs2]_rd)
        array_read_pattern = re.compile(r'^(\w+)\[(\w+)\]_rd$')

        read_enables_created = 0

        for node_id, using_instrs in sorted(self.partially_shared_nodes.items()):
            match = array_read_pattern.match(node_id)
            if not match:
                continue

            array_name = match.group(1)  # e.g., 'rf'
            index_name = match.group(2)  # e.g., 'rs1', 'rs2', 'pc'

            # Skip if all instructions use this (it's not really partial)
            all_instrs = set(self.graphs.keys())
            if using_instrs == all_instrs:
                print(f"  {node_id}: used by ALL instructions - skipping")
                continue

            # Create the read enable signal: OR of all instruction enables
            enable_node_id = f"{array_name}_{index_name}_rd_enable"

            # Special case: PC-indexed reads (instruction fetch) should always be enabled
            # The instruction fetch happens before decode, so it can't depend on instruction enables
            if index_name in ['pc', 'ip']:
                # Create a constant 1'b1 enable for instruction fetch
                enable_node = Node(enable_node_id, {
                    'type': 'literal',
                    'value': 1,
                    'bit_width': 1,
                    'display_name': f"{array_name}[{index_name}] read enable (always)",
                    'source_instructions': list(using_instrs)
                })
                merged_graph.add_node(enable_node)

                # Mark the read node with this enable
                read_node = merged_graph.nodes.get(node_id)
                if read_node:
                    read_node.data['read_enable'] = enable_node_id

                print(f"  Created {enable_node_id} = 1'b1 (PC-indexed instruction fetch)")
                read_enables_created += 1
                continue

            # Find instruction enable nodes
            instr_enables = []
            for instr_name in sorted(using_instrs):
                enable_id = f"{instr_name.lower()}_enable"
                if enable_id in merged_graph.nodes:
                    instr_enables.append(merged_graph.nodes[enable_id])
                else:
                    print(f"  WARNING: Enable node {enable_id} not found for {instr_name}")

            if len(instr_enables) == 0:
                print(f"  {node_id}: no enable nodes found - skipping")
                continue

            # Check if this array read is inside a ternary conditional
            read_node = merged_graph.nodes.get(node_id)
            ternary_condition = None
            if read_node:
                ternary_condition = self._find_ternary_condition_for_read(read_node, merged_graph)

            if len(instr_enables) == 1 and not ternary_condition:
                # Single instruction, no ternary - just alias the enable
                # Create a simple wire/alias node
                enable_node = Node(enable_node_id, {
                    'type': 'alias',
                    'display_name': f"{array_name}[{index_name}] read enable",
                    'source_instructions': list(using_instrs)
                })
                merged_graph.add_node(enable_node)

                edge = Edge(instr_enables[0], enable_node, data={'type': 'assignment'})
                merged_graph.add_edge(edge)

                print(f"  Created {enable_node_id} = {instr_enables[0].id}")
            elif not ternary_condition:
                # Multiple instructions, no ternary - create OR node
                or_node = Node(enable_node_id, {
                    'type': 'logical_or',
                    'operation': '||',
                    'display_name': f"{array_name}[{index_name}] read enable",
                    'source_instructions': list(using_instrs)
                })
                merged_graph.add_node(or_node)

                for enable in instr_enables:
                    edge = Edge(enable, or_node, data={'type': 'logic_input'})
                    merged_graph.add_edge(edge)

                enable_names = ' || '.join([e.id for e in instr_enables])
                print(f"  Created {enable_node_id} = {enable_names}")
            else:
                # Ternary condition found - AND with instruction enables
                # Create: enable = condition && (instr1_enable || instr2_enable || ...)
                condition_id = ternary_condition.id
                print(f"  {node_id}: found ternary condition '{condition_id}'")

                # First create the OR of instruction enables (or use single enable)
                if len(instr_enables) == 1:
                    instr_or_node = instr_enables[0]
                    enable_names = instr_enables[0].id
                else:
                    instr_or_id = f"{enable_node_id}_instr_or"
                    instr_or_node = Node(instr_or_id, {
                        'type': 'logical_or',
                        'operation': '||',
                        'display_name': f"{array_name}[{index_name}] instr enables OR",
                        'source_instructions': list(using_instrs),
                        'bit_width': 1
                    })
                    merged_graph.add_node(instr_or_node)

                    for enable in instr_enables:
                        edge = Edge(enable, instr_or_node, data={'type': 'logic_input'})
                        merged_graph.add_edge(edge)

                    enable_names = ' || '.join([e.id for e in instr_enables])

                # Now create the AND with the ternary condition
                and_node = Node(enable_node_id, {
                    'type': 'logical_and',
                    'operation': '&&',
                    'display_name': f"{array_name}[{index_name}] read enable (gated)",
                    'source_instructions': list(using_instrs),
                    'bit_width': 1
                })
                merged_graph.add_node(and_node)

                # Connect condition
                edge1 = Edge(ternary_condition, and_node, data={'type': 'logic_input', 'operand_position': 0})
                merged_graph.add_edge(edge1)

                # Connect instruction enables OR
                edge2 = Edge(instr_or_node, and_node, data={'type': 'logic_input', 'operand_position': 1})
                merged_graph.add_edge(edge2)

                print(f"  Created {enable_node_id} = {condition_id} && ({enable_names})")

            read_enables_created += 1

            # Also store this info on the read node itself for easy lookup
            if node_id in merged_graph.nodes:
                merged_graph.nodes[node_id].data['read_enable'] = enable_node_id

        print(f"\nCreated {read_enables_created} read enable signal(s) from partially_shared_nodes")

        # Second pass: Create read enables for isa_state memory reads
        # These are fully shared nodes (not in partially_shared_nodes) but only used by some instructions
        # e.g., dmem[addr]_rd is only used by load instructions (lb, lh, lw, lbu, lhu)
        print("\nChecking isa_state memory reads...")

        # Iterate over a copy of keys to avoid modifying dict during iteration
        for node_id in list(merged_graph.nodes.keys()):
            node = merged_graph.nodes[node_id]
            # Skip if already has read_enable
            if node.data.get('read_enable'):
                continue

            # Check if this is an array read node
            match = array_read_pattern.match(node_id)
            if not match:
                continue

            array_name = match.group(1)  # e.g., 'dmem'
            index_name = match.group(2)  # e.g., 'addr'

            # Check if the base array is an isa_state memory
            base_node = merged_graph.nodes.get(array_name)
            if not base_node:
                continue
            base_type = base_node.data.get('type', '')
            if 'isa_state' not in base_type:
                continue

            print(f"  Found isa_state read: {node_id} (base: {array_name}, type: {base_type})")

            # Find which instructions use this read
            # Method 1: Check which original instruction graphs contain this node
            using_instrs = set()
            for instr_name, instr_graph in self.graphs.items():
                if node_id in instr_graph.nodes:
                    using_instrs.add(instr_name)

            # Method 2 (fallback): Trace data consumers to find instruction-specific nodes
            if not using_instrs:
                def find_using_instructions(n, visited=None, depth=0):
                    """Trace output consumers to find instruction-specific nodes."""
                    if visited is None:
                        visited = set()
                    if n.id in visited or depth > 6:
                        return
                    visited.add(n.id)

                    for edge in n.outgoing_edges:
                        target = edge.target
                        target_id = target.id

                        # Check if target is instruction-specific (starts with instr_)
                        for instr_name in self.graphs.keys():
                            instr_lower = instr_name.lower()
                            if target_id.startswith(instr_lower + '_'):
                                using_instrs.add(instr_name)
                                break

                        # Recurse to find more consumers
                        find_using_instructions(target, visited, depth + 1)

                find_using_instructions(node)

            if not using_instrs:
                print(f"    No instruction-specific consumers found - skipping")
                continue

            print(f"    Used by: {sorted(using_instrs)}")

            # Create the read enable signal
            enable_node_id = f"{array_name}_{index_name}_rd_enable"

            # Special case: PC-indexed reads (instruction fetch) should always be enabled
            # The instruction fetch happens before decode, so it can't depend on instruction enables
            if index_name in ['pc', 'ip']:
                # Create a constant 1'b1 enable for instruction fetch
                enable_node = Node(enable_node_id, {
                    'type': 'literal',
                    'value': 1,
                    'bit_width': 1,
                    'display_name': f"{array_name}[{index_name}] read enable (always)",
                    'source_instructions': list(using_instrs)
                })
                merged_graph.add_node(enable_node)

                # Mark the read node with this enable
                node.data['read_enable'] = enable_node_id

                print(f"    Created {enable_node_id} = 1'b1 (PC-indexed instruction fetch)")
                read_enables_created += 1
                continue

            # Skip if already exists
            if enable_node_id in merged_graph.nodes:
                print(f"    {enable_node_id} already exists - storing on read node")
                node.data['read_enable'] = enable_node_id
                continue

            # Find instruction enable nodes
            instr_enables = []
            for instr_name in sorted(using_instrs):
                enable_id = f"{instr_name.lower()}_enable"
                if enable_id in merged_graph.nodes:
                    instr_enables.append(merged_graph.nodes[enable_id])
                else:
                    print(f"    WARNING: Enable node {enable_id} not found for {instr_name}")

            if len(instr_enables) == 0:
                print(f"    No enable nodes found - skipping")
                continue

            # Check if this array read is inside a ternary conditional
            ternary_condition = self._find_ternary_condition_for_read(node, merged_graph)

            if len(instr_enables) == 1 and not ternary_condition:
                # Single instruction, no ternary - just alias the enable
                enable_node = Node(enable_node_id, {
                    'type': 'alias',
                    'display_name': f"{array_name}[{index_name}] read enable",
                    'source_instructions': list(using_instrs),
                    'bit_width': 1
                })
                merged_graph.add_node(enable_node)

                edge = Edge(instr_enables[0], enable_node, data={'type': 'assignment'})
                merged_graph.add_edge(edge)

                print(f"    Created {enable_node_id} = {instr_enables[0].id}")
            elif not ternary_condition:
                # Multiple instructions, no ternary - create OR node
                or_node = Node(enable_node_id, {
                    'type': 'logical_or',
                    'operation': '||',
                    'display_name': f"{array_name}[{index_name}] read enable",
                    'source_instructions': list(using_instrs),
                    'bit_width': 1
                })
                merged_graph.add_node(or_node)

                for enable in instr_enables:
                    edge = Edge(enable, or_node, data={'type': 'logic_input'})
                    merged_graph.add_edge(edge)

                enable_names = ' || '.join([e.id for e in instr_enables])
                print(f"    Created {enable_node_id} = {enable_names}")
            else:
                # Ternary condition found - AND with instruction enables
                # Create: enable = condition && (instr1_enable || instr2_enable || ...)
                condition_id = ternary_condition.id
                print(f"    {node_id}: found ternary condition '{condition_id}'")

                # First create the OR of instruction enables (or use single enable)
                if len(instr_enables) == 1:
                    instr_or_node = instr_enables[0]
                    enable_names = instr_enables[0].id
                else:
                    instr_or_id = f"{enable_node_id}_instr_or"
                    instr_or_node = Node(instr_or_id, {
                        'type': 'logical_or',
                        'operation': '||',
                        'display_name': f"{array_name}[{index_name}] instr enables OR",
                        'source_instructions': list(using_instrs),
                        'bit_width': 1
                    })
                    merged_graph.add_node(instr_or_node)

                    for enable in instr_enables:
                        edge = Edge(enable, instr_or_node, data={'type': 'logic_input'})
                        merged_graph.add_edge(edge)

                    enable_names = ' || '.join([e.id for e in instr_enables])

                # Now create the AND with the ternary condition
                and_node = Node(enable_node_id, {
                    'type': 'logical_and',
                    'operation': '&&',
                    'display_name': f"{array_name}[{index_name}] read enable (gated)",
                    'source_instructions': list(using_instrs),
                    'bit_width': 1
                })
                merged_graph.add_node(and_node)

                # Connect condition
                edge1 = Edge(ternary_condition, and_node, data={'type': 'logic_input', 'operand_position': 0})
                merged_graph.add_edge(edge1)

                # Connect instruction enables OR
                edge2 = Edge(instr_or_node, and_node, data={'type': 'logic_input', 'operand_position': 1})
                merged_graph.add_edge(edge2)

                print(f"    Created {enable_node_id} = {condition_id} && ({enable_names})")

            # Store on read node for easy lookup
            node.data['read_enable'] = enable_node_id
            read_enables_created += 1

        # Third pass: Create read enables for scalar (1D) ISA state reads
        # These are nodes like cr_rd, ctr_rd, lr_rd that don't have array indexing
        # Pattern: {isa_state}_rd where isa_state is a scalar register
        print("\nChecking scalar ISA state reads...")
        scalar_read_pattern = re.compile(r'^(\w+)_rd$')

        for node_id in list(merged_graph.nodes.keys()):
            node = merged_graph.nodes[node_id]

            # Skip if already has read_enable
            if node.data.get('read_enable'):
                continue

            # Check if this is a scalar read node (e.g., cr_rd, ctr_rd, lr_rd)
            match = scalar_read_pattern.match(node_id)
            if not match:
                continue

            isa_state_name = match.group(1)  # e.g., 'cr', 'ctr', 'lr'

            # Skip if this looks like an array element read (already handled in first pass)
            # Array reads have patterns like rf[ra]_rd - they contain brackets
            if '[' in isa_state_name:
                continue

            # Skip pc_rd - instruction fetch is always enabled
            if isa_state_name == 'pc':
                continue

            # Check the read node's metadata to verify it's an isa_state read
            node_type = node.data.get('type', '')

            # Accept nodes that are marked as isa_state reads or split reads
            # The split process creates *_rd nodes from isa_state nodes
            is_isa_state_read = (
                'isa_state' in node_type or
                node.data.get('is_read_port') or
                node.data.get('split_from') or
                # Check if it has edges from an isa_state
                any('isa_state' in (e.source.data.get('type', '') or '') for e in node.incoming_edges)
            )

            if not is_isa_state_read:
                # Try looking at related nodes
                wr_node = merged_graph.nodes.get(f"{isa_state_name}_wr")
                if wr_node and 'isa_state' in wr_node.data.get('type', ''):
                    is_isa_state_read = True

            if not is_isa_state_read:
                continue

            print(f"  Found scalar ISA state read: {node_id} (type: {node_type})")

            # Find which instructions use this read by checking original graphs
            using_instrs = set()
            for instr_name, instr_graph in self.graphs.items():
                if node_id in instr_graph.nodes:
                    using_instrs.add(instr_name)

            # Fallback: trace consumers to find instruction-specific nodes
            if not using_instrs:
                def find_using_instructions_scalar(n, visited=None, depth=0):
                    """Trace output consumers to find instruction-specific nodes."""
                    if visited is None:
                        visited = set()
                    if n.id in visited or depth > 10:
                        return
                    visited.add(n.id)

                    for edge in n.outgoing_edges:
                        target = edge.target
                        target_id = target.id

                        # Check if target is instruction-specific (starts with instr_)
                        for instr_name in self.graphs.keys():
                            instr_lower = instr_name.lower()
                            if target_id.startswith(instr_lower + '_'):
                                using_instrs.add(instr_name)
                                break

                        # Recurse to find more consumers
                        find_using_instructions_scalar(target, visited, depth + 1)

                find_using_instructions_scalar(node)

            if not using_instrs:
                print(f"    No instruction-specific consumers found - skipping")
                continue

            print(f"    Used by: {sorted(using_instrs)}")

            # Create the read enable signal
            enable_node_id = f"{isa_state_name}_rd_enable"

            # Skip if already exists
            if enable_node_id in merged_graph.nodes:
                print(f"    {enable_node_id} already exists - storing on read node")
                node.data['read_enable'] = enable_node_id
                continue

            # Find instruction enable nodes
            instr_enables = []
            for instr_name in sorted(using_instrs):
                enable_id = f"{instr_name.lower()}_enable"
                if enable_id in merged_graph.nodes:
                    instr_enables.append(merged_graph.nodes[enable_id])
                else:
                    print(f"    WARNING: Enable node {enable_id} not found for {instr_name}")

            if len(instr_enables) == 0:
                print(f"    No enable nodes found - skipping")
                continue

            if len(instr_enables) == 1:
                # Single instruction - just alias the enable
                enable_node = Node(enable_node_id, {
                    'type': 'alias',
                    'display_name': f"{isa_state_name} read enable",
                    'source_instructions': list(using_instrs),
                    'bit_width': 1
                })
                merged_graph.add_node(enable_node)

                edge = Edge(instr_enables[0], enable_node, data={'type': 'assignment'})
                merged_graph.add_edge(edge)

                print(f"    Created {enable_node_id} = {instr_enables[0].id}")
            else:
                # Multiple instructions - create OR node
                or_node = Node(enable_node_id, {
                    'type': 'logical_or',
                    'operation': '||',
                    'display_name': f"{isa_state_name} read enable",
                    'source_instructions': list(using_instrs),
                    'bit_width': 1
                })
                merged_graph.add_node(or_node)

                for enable in instr_enables:
                    edge = Edge(enable, or_node, data={'type': 'logic_input'})
                    merged_graph.add_edge(edge)

                enable_names = ' || '.join([e.id for e in instr_enables])
                print(f"    Created {enable_node_id} = {enable_names}")

            # Store on read node for easy lookup
            node.data['read_enable'] = enable_node_id
            read_enables_created += 1

        print(f"\nTotal read enable signals created: {read_enables_created}")

    def _multiplex_memory_read_ports(self, merged_graph: ResourceGraph, instruction_specific_nodes: Dict[str, Set[str]]):
        """
        Create multiplexers for memory read address ports when multiple instructions
        read from the same base memory with different addresses.

        For example, if ADD reads from rf[rs1] and C.BEQZ reads from rf[c_beqz_rs1],
        and both share the same rf[rs1]_rd node, this creates:
        - Address mux: rf_rs1_rd_addr_mux = add_enable ? add_rs1 : c_beqz_enable ? c_beqz_rs1 : ...

        This is the read-side counterpart to _multiplex_memory_write_ports.
        """
        from .resource_graph import Node, Edge

        print("\n" + "=" * 60)
        print("MULTIPLEXING MEMORY READ PORTS")
        print("=" * 60)

        # Pattern for array read nodes: {array}[{index}]_rd
        # Simple pattern for basic cases like rf[rs1]_rd
        array_read_pattern = re.compile(r'^(\w+)\[(\w+)\]_rd$')
        # Extended pattern for complex computed addresses like umem[(vbr + {22'b0, exc_vector, 2'b0})]_rd
        # This matches: {array}[{any_expression}]_rd where any_expression can contain (), {}, spaces, etc.
        complex_read_pattern = re.compile(r'^(\w+)\[(.+)\]_rd$')

        reads_with_mux = 0

        # Find all array read nodes that have multiple array_index incoming edges
        for node_id, node in sorted(merged_graph.nodes.items()):
            # Try simple pattern first, then complex pattern
            match = array_read_pattern.match(node_id)
            if not match:
                match = complex_read_pattern.match(node_id)
            if not match:
                continue

            array_name = match.group(1)  # e.g., 'rf', 'dmem', 'umem'
            index_name = match.group(2)  # e.g., 'rs1', 'addr', or complex expr like '(vbr + ...)'

            # Skip instruction fetch reads (reads from mainmem[pc...])
            # These must NOT be muxed by instruction enables because the imem read
            # happens BEFORE decode — you need the address to determine which instruction.
            # The verilog generator OR-combines multiple index edges as a fallback.
            if 'pc' in index_name.lower():
                continue

            # Collect all array_index edges
            index_edges = [e for e in node.incoming_edges if e.data.get('type') == 'array_index']

            if len(index_edges) <= 1:
                # Single or no index - no mux needed
                continue

            # Check if all index sources are the same node (would be a no-op mux)
            unique_sources = set(e.source.id for e in index_edges)
            if len(unique_sources) <= 1:
                print(f"  {node_id}: {len(index_edges)} edges but all from same source '{list(unique_sources)[0]}' - skipping")
                continue

            print(f"\n  {node_id}: Found {len(index_edges)} array_index edges from {len(unique_sources)} unique sources")
            for e in index_edges:
                print(f"    - {e.source.id}")

            # Determine which instructions use each index source
            # Use GroupTracker's classification data for collision groups
            index_to_instrs = {}  # merged_source_id -> set of instruction names

            # Get unique source IDs from edges
            unique_sources = set(e.source.id for e in index_edges)

            # For each source, find which instructions were mapped to it
            for source_id in unique_sources:
                if source_id not in index_to_instrs:
                    index_to_instrs[source_id] = set()

                source_node = merged_graph.nodes.get(source_id)

                # FIRST check GroupTracker for collision groups (most authoritative)
                # source_id is the merged ID (like lb_addr), find which groups map to it
                if hasattr(self, '_group_tracker') and self._group_tracker:
                    tracker = self._group_tracker
                    # Look through all classifications to find groups that merge to source_id
                    for orig_node_id, classification in sorted(tracker.classifications.items()):
                        for group in classification.groups:
                            merged_id = classification.merged_ids.get(group.group_id)
                            if merged_id == source_id:
                                index_to_instrs[source_id].update(group.instructions)

                # If tracker found instructions, we're done with this source
                if index_to_instrs[source_id]:
                    continue

                # Fallback: check partially_shared_nodes
                if source_id in self.partially_shared_nodes:
                    index_to_instrs[source_id] = set(self.partially_shared_nodes[source_id])
                    continue

                # Fallback: check node data for group_members
                if source_node:
                    group_members = source_node.data.get('group_members', [])
                    if group_members:
                        index_to_instrs[source_id] = set(group_members)
                        continue

                    # If node has original_id, find all instructions with that node
                    original_id = source_node.data.get('original_id')
                    if original_id:
                        for instr_name, instr_graph in sorted(self.graphs.items()):
                            if original_id in instr_graph.nodes:
                                index_to_instrs[source_id].add(instr_name)
                        if index_to_instrs[source_id]:
                            continue

                    # Single instruction metadata
                    instr = source_node.data.get('instruction')
                    if instr:
                        index_to_instrs[source_id].add(instr)
                        continue

                # Last fallback: extract instruction from prefixed node name
                if not index_to_instrs[source_id]:
                    for instr_name in sorted(self.graphs.keys()):
                        prefix = f"{instr_name}_"
                        if source_id.startswith(prefix):
                            index_to_instrs[source_id].add(instr_name)
                            break

            print(f"    Index to instructions mapping:")
            for src_id, instrs in sorted(index_to_instrs.items()):
                print(f"      {src_id}: {sorted(instrs)}")

            # Create the address mux
            sanitized_node_id = node_id.replace('[', '_').replace(']', '')
            addr_mux_id = f"{sanitized_node_id}_addr_mux"

            # Build mux_inputs list (format expected by _generate_address_mux_logic)
            mux_inputs = []
            input_idx = 0
            for source_id, instrs in sorted(index_to_instrs.items()):
                source_node = merged_graph.nodes.get(source_id)
                if not source_node:
                    print(f"    WARNING: Source node {source_id} not found in merged graph")
                    continue

                # Find or create enable signal for this group of instructions
                enable_id = None
                if len(instrs) == 1:
                    instr_name = list(instrs)[0]
                    enable_id = f"{instr_name.lower()}_enable"
                    if not merged_graph.nodes.get(enable_id):
                        enable_id = None  # Node doesn't exist
                else:
                    # Multiple instructions use this source - need OR of enables
                    enable_ids = [f"{i.lower()}_enable" for i in sorted(instrs)]
                    enable_nodes = [merged_graph.nodes.get(eid) for eid in enable_ids if merged_graph.nodes.get(eid)]

                    if len(enable_nodes) == 0:
                        print(f"    WARNING: No enable nodes found for {instrs}")
                    elif len(enable_nodes) == 1:
                        enable_id = enable_nodes[0].id
                    else:
                        # Create OR node for multiple enables
                        or_id = f"{addr_mux_id}_enable_{input_idx}"
                        or_node = Node(or_id, {
                            'type': 'logical_or',
                            'operation': '||',
                            'display_name': f"Enable for {source_id}",
                            'bit_width': 1
                        })
                        merged_graph.add_node(or_node)

                        for en in enable_nodes:
                            edge = Edge(en, or_node, data={'type': 'logic_input'})
                            merged_graph.add_edge(edge)

                        enable_id = or_id

                # Add to mux_inputs list
                mux_inputs.append({
                    'source_node': source_id,
                    'enable_node': enable_id
                })

                if enable_id:
                    print(f"    Mux input {input_idx}: {source_id} (enable: {enable_id})")
                else:
                    print(f"    Mux input {input_idx}: {source_id} (no enable found)")

                input_idx += 1

            # Create mux node with mux_inputs in data
            addr_mux_node = Node(addr_mux_id, {
                'type': 'one_hot_mux',
                'name': addr_mux_id,
                'display_name': f"{array_name}[{index_name}] Read Address MUX",
                'is_address_mux': True,
                'target_read_node': node_id,
                'mux_inputs': mux_inputs
            })
            merged_graph.add_node(addr_mux_node)

            # Connect source nodes to the mux (so they get declared and assigned in Verilog)
            for i, (source_id, instrs) in enumerate(index_to_instrs.items()):
                source_node = merged_graph.nodes.get(source_id)
                if source_node:
                    mux_input_edge = Edge(source_node, addr_mux_node, data={
                        'type': 'mux_input',
                        'input_index': i
                    })
                    merged_graph.add_edge(mux_input_edge)
                    print(f"      Connected {source_id} -> {addr_mux_id}")

            # Remove old array_index edges from the read node
            for e in list(index_edges):
                if e.id in merged_graph.edges:
                    e.remove_from_nodes()
                    del merged_graph.edges[e.id]

            # Connect mux output to read node as the new single index
            new_index_edge = Edge(addr_mux_node, node, data={
                'type': 'array_index',
                'from_address_mux': True
            })
            merged_graph.add_edge(new_index_edge)

            print(f"    Created {addr_mux_id} with {input_idx} inputs")
            reads_with_mux += 1

        print(f"\nCreated address muxes for {reads_with_mux} read port(s)")

    def _multiplex_cam_lookup_keys(self, merged_graph: ResourceGraph, instruction_specific_nodes: Dict[str, Set[str]]):
        """
        Create multiplexers for CAM lookup keys when a shared CAM lookup node
        uses an instruction-specific key.

        During merging, CAM lookup nodes (e.g., utlb_vpn@[data_lookup_vpn]) may be
        shared across all instructions, but the key (data_lookup_vpn) is computed
        from instruction-specific addresses (mmu_va). The merger only connects one
        instruction's key, causing all other instructions to use the wrong key.

        This method finds such cases and creates a mux that selects the correct key
        based on which instruction is active.
        """
        from .resource_graph import Node, Edge

        print("\n" + "=" * 60)
        print("MULTIPLEXING CAM LOOKUP KEYS")
        print("=" * 60)

        cam_muxes_created = 0

        # Find all cam_lookup nodes in the merged graph
        for node_id, node in list(merged_graph.nodes.items()):
            if node.data.get('type') != 'cam_lookup':
                continue

            # Find the cam_key incoming edge
            cam_key_edges = [e for e in node.incoming_edges if e.data.get('type') == 'cam_key']
            if not cam_key_edges:
                continue

            # Get the current key source
            key_source = cam_key_edges[0].source
            key_source_id = key_source.id
            key_width = key_source.data.get('bit_width', 22)

            # Check if the key source is instruction-specific (has an instruction prefix)
            # by looking for {instr_name}_{base_name} pattern
            # Use longest matching prefix to avoid partial matches
            # (e.g., 'movb' matching 'movb_indexed_data_lookup_vpn' instead of 'movb_indexed')
            base_key_name = None
            key_instr_name = None
            for instr_name in sorted(self.graphs.keys(), key=len, reverse=True):
                prefix = f"{instr_name}_"
                if key_source_id.startswith(prefix):
                    base_key_name = key_source_id[len(prefix):]
                    key_instr_name = instr_name
                    break

            if not base_key_name:
                # Key is shared (not instruction-specific) - no mux needed
                print(f"  {node_id}: key '{key_source_id}' is shared - no mux needed")
                continue

            print(f"  {node_id}: key '{key_source_id}' is instruction-specific (base: {base_key_name})")

            # Find all instruction-specific variants of the key
            key_variants = {}  # instr_name -> node_id
            for instr_name in self.graphs.keys():
                variant_id = f"{instr_name}_{base_key_name}"
                if variant_id in merged_graph.nodes:
                    key_variants[instr_name] = variant_id

            # Recover instructions whose key node was merged into another instruction's
            # node during group-based sharing. Use the GroupTracker to find the actual
            # merged-graph node ID for each instruction's key.
            recovered_count = 0
            tracker = getattr(self, '_group_tracker', None)
            if tracker and base_key_name in tracker.classifications:
                for instr_name in self.graphs.keys():
                    if instr_name in key_variants:
                        continue
                    # Check if this instruction has the key in its per-instruction graph
                    if base_key_name not in self.graphs[instr_name].nodes:
                        continue
                    # Use GroupTracker to find the merged-graph node for this instruction's key
                    merged_id = tracker.get_merged_id(instr_name, base_key_name)
                    if merged_id in merged_graph.nodes:
                        key_variants[instr_name] = merged_id
                        recovered_count += 1

            if recovered_count > 0:
                print(f"    Recovered {recovered_count} deduplicated instruction(s) for CAM key mux (via GroupTracker)")

            if len(key_variants) <= 1:
                print(f"    Only {len(key_variants)} variant(s) found - no mux needed")
                continue

            print(f"    Found {len(key_variants)} instruction-specific key variants ({len(key_variants) - recovered_count} direct + {recovered_count} recovered)")

            # Create a mux node for the key
            cam_name = node.data.get('cam_name', 'cam')
            mux_id = f"{cam_name}_{base_key_name}_mux"

            # Build mux_inputs list
            mux_inputs = []
            input_idx = 0
            for instr_name, variant_id in sorted(key_variants.items()):
                enable_id = f"{instr_name}_enable"
                if enable_id not in merged_graph.nodes:
                    enable_id = None

                mux_inputs.append({
                    'source_node': variant_id,
                    'enable_node': enable_id
                })
                input_idx += 1

            # Create the mux node
            mux_node = Node(mux_id, {
                'type': 'one_hot_mux',
                'name': mux_id,
                'display_name': f"CAM key MUX for {cam_name}@[{base_key_name}]",
                'is_address_mux': True,
                'target_read_node': node_id,
                'mux_inputs': mux_inputs,
                'bit_width': key_width
            })
            merged_graph.add_node(mux_node)

            # Connect all key variants to the mux
            for i, (instr_name, variant_id) in enumerate(sorted(key_variants.items())):
                variant_node = merged_graph.nodes[variant_id]
                mux_input_edge = Edge(variant_node, mux_node, data={
                    'type': 'mux_input',
                    'input_index': i
                })
                merged_graph.add_edge(mux_input_edge)

            # Remove old cam_key edge(s)
            for e in list(cam_key_edges):
                if e.id in merged_graph.edges:
                    e.remove_from_nodes()
                    del merged_graph.edges[e.id]

            # Connect mux output to cam_lookup node as the new key
            new_key_edge = Edge(mux_node, node, data={
                'type': 'cam_key',
                'position': 'key',
                'from_address_mux': True
            })
            merged_graph.add_edge(new_key_edge)

            print(f"    Created {mux_id} with {len(key_variants)} inputs")
            cam_muxes_created += 1

        print(f"\nCreated CAM key muxes: {cam_muxes_created}")

    # ========================================================================
    # NEW PLAN-THEN-EXECUTE ARCHITECTURE METHODS
    # ========================================================================

    def _merge_graphs_new_architecture(self) -> ResourceGraph:
        """
        Merge all instruction graphs using the new plan-then-execute architecture.

        This uses the new group-aware classification pipeline:
        1. Classify all nodes with group tracking (GroupTracker)
        2. Propagate group structure to dependents
        3. Generate build plan from GroupTracker
        4. Execute plan in single pass
        """
        instruction_names = list(self.graphs.keys())

        # Step 1: Classify nodes using the new group-aware pipeline
        print("=== New Group-Aware Classification Pipeline ===")
        tracker = self._classify_with_groups()

        # Store tracker for later use
        self._group_tracker = tracker

        # Build instruction_specific_nodes dict for legacy mux generation
        # This bridges the new GroupTracker with existing mux code
        instruction_specific_nodes = {instr: set() for instr in instruction_names}
        for node_id, classification in tracker.classifications.items():
            if classification.tier == SharingType.INSTRUCTION_SPECIFIC:
                for group in classification.groups:
                    if len(group.instructions) == 1:
                        instr = list(group.instructions)[0]
                        instruction_specific_nodes[instr].add(node_id)
            elif classification.is_collision():
                # Collision nodes are also instruction-specific (with prefixes)
                for group in classification.groups:
                    for instr in group.instructions:
                        instruction_specific_nodes[instr].add(node_id)

        # Step 2: Generate build plan from GroupTracker
        print("\n=== Generating Build Plan ===")
        plan = self._generate_build_plan_from_tracker(tracker)

        # Step 3: Execute plan
        print("\n=== Executing Build Plan ===")
        merged_graph = self._execute_build_plan(plan)

        # Step 3b: Detect arch state _wr nodes that have collision groups
        # These need muxes to merge all instruction-specific values
        self._arch_state_wr_nodes_needing_mux = set()
        for node_id, node in merged_graph.nodes.items():
            original_id = node.data.get('original_id')
            if original_id and original_id.endswith('_wr'):
                # This is a collision node for an arch state write target
                self._arch_state_wr_nodes_needing_mux.add(original_id)

        if self._arch_state_wr_nodes_needing_mux:
            print(f"Detected arch state _wr nodes needing mux: {self._arch_state_wr_nodes_needing_mux}")

        # Step 3c: Build global aspect ordering per state from ISA priority declarations
        self._build_global_aspect_order()

        # Step 4: Add instruction decode logic and multiplexers
        # This follows the same sequence as the legacy architecture:

        # 4a: Create instruction decode enable signals
        self._create_decode_logic(merged_graph)

        # 4a2: Create muxes for collision inputs to shared orthogon nodes
        # (e.g., mux instruction-specific addr_sel into shared sel_match nodes)
        self._mux_shared_orthogon_inputs(merged_graph, tracker)

        # 4b: Create multiplexers for memory write ports
        self._multiplex_memory_write_ports(merged_graph, instruction_specific_nodes)

        # 4b2: Create multiplexers for memory read address ports
        # When multiple instructions share a read node but use different index expressions
        self._multiplex_memory_read_ports(merged_graph, instruction_specific_nodes)

        # 4b2.5: Create multiplexers for CAM lookup keys
        # When a shared CAM lookup uses an instruction-specific key
        self._multiplex_cam_lookup_keys(merged_graph, instruction_specific_nodes)

        # 4b3: Create read enable signals for array reads (e.g., rf[rs1]_rd, dmem[addr]_rd)
        # These are used by hazard resolution to gate stall conditions
        self._create_read_enable_signals(merged_graph)

        # Note: Read port sharing based on mutually exclusive enables is available via
        # memory_sharing.share_read_ports_by_enable() and should be called explicitly
        # from generator files (e.g., generate_j2_complete.py) with the desired port count

        # 4c: Create multiplexers for instruction-specific outputs to shared targets
        self._gate_instruction_operations(merged_graph, instruction_specific_nodes)

        # 4d: Handle variable latency operations
        self._handle_variable_latency_operations(merged_graph, instruction_specific_nodes)

        # 4e: Clean up superseded nodes
        self._cleanup_superseded_nodes(merged_graph, instruction_specific_nodes)

        # Step 5: Optimize the merged graph
        optimizer = GraphOptimizer(merged_graph)
        optimizer.optimize(enable_all=False, merge_nested_muxes=False, propagate_aliases=False, split_arch_state=True)

        # Step 6: Promote memory widths based on actual access patterns
        self._promote_mem_widths(merged_graph)

        # Step 7: Final cleanup
        optimizer.cleanup_bypassed_edges()
        reinfer_timing(merged_graph)

        # Step 8: Deduplicate common subexpressions in gated write muxes
        print("\nDeduplicating arch state muxes...")
        deduplicate_all_arch_state_muxes(merged_graph)

        print(f"\\nMerged graph: {merged_graph}")
        return merged_graph

    def _add_instruction_decode_logic(self, merged_graph: ResourceGraph, node_remapping: Dict) -> ResourceGraph:
        """
        Add instruction decode logic, enable signals, and multiplexers to merged graph.

        This is shared by both the legacy and new architectures.
        """
        instruction_names = list(self.graphs.keys())

        # Generate instruction decode logic
        print("\nGenerating instruction decode logic...")
        decode_builder = InstructionDecodeBuilder(merged_graph)

        for instr_name in instruction_names:
            decode_info = self.decode_info[instr_name]
            # Get the instruction node for this instruction
            instr_node_id = self.instruction_nodes[instr_name]

            # Handle ILA vs ISA decode
            if decode_info.decode_signal_node:
                # ILA: decode signal already exists, just map it
                decode_signal_id = decode_info.decode_signal_node
                # The decode signal might be remapped
                if instr_name in node_remapping and decode_signal_id in node_remapping[instr_name]:
                    decode_signal_id = node_remapping[instr_name][decode_signal_id]

                decode_builder.add_instruction_ila(
                    merged_graph,
                    instr_name,
                    decode_signal_id
                )
            else:
                # ISA: generate decode from conditions
                if instr_node_id in merged_graph.nodes:
                    decode_builder.add_instruction(
                        merged_graph,
                        instr_name,
                        merged_graph.nodes[instr_node_id],
                        decode_info.assume_conditions
                    )

        decode_builder.finalize(merged_graph)

        # Generate muxes for instruction-specific outputs
        print("\nGenerating output multiplexers...")
        self._generate_output_muxes(merged_graph, node_remapping)

        # Generate shared write ports for memories
        print("\nGenerating shared memory write ports...")
        self._generate_shared_memory_write_ports(merged_graph, node_remapping)

        return merged_graph

    def _plan_architectural_state(self, shared_nodes: Set[str]) -> List[NodeBuildPlan]:
        """Plan all architectural state nodes (tier 1)."""
        arch_plans = []

        # Get list of instruction names for consistency
        instruction_names = list(self.graphs.keys())
        if not instruction_names:
            return arch_plans

        first_instr = instruction_names[0]

        # Find all architectural state nodes
        for node_id in shared_nodes:
            node = self.graphs[first_instr].nodes.get(node_id)

            if not node or not node.is_arch_state:
                continue

            # Architectural state has NO dependencies on other nodes
            # (it's input state or self-referential)
            plan = NodeBuildPlan(
                node_id=node_id,
                original_id=node_id,
                source_instruction=first_instr,
                sharing_type=SharingType.ARCHITECTURAL_STATE,
                group_info=None,
                dependencies=set(),  # No dependencies!
                dependency_tier_levels={},
                is_collision_dependent=False,
                needs_arch_state_split=self._needs_split(node),
                metadata={'is_arch_state': True}
            )
            arch_plans.append(plan)

        return arch_plans

    def _needs_split(self, node: Node) -> bool:
        """Check if architectural state needs _rd/_wr split."""
        has_read = any(e.data.get('type') == 'data' for e in node.outgoing_edges)
        has_write = any(e.data.get('type') == 'assignment' for e in node.incoming_edges)
        return has_read and has_write

    def _get_node_dependencies(self, node: Node, instruction: str, node_remapping: Dict) -> Set[str]:
        """Extract dependencies for a node from its incoming edges."""
        deps = set()
        for edge in node.incoming_edges:
            source_id = edge.source.id
            # Map to merged graph ID (may be remapped for groups)
            merged_id = node_remapping.get(instruction, {}).get(source_id, source_id)
            deps.add(merged_id)
        return deps

    def _classify_dependency_tiers(self, deps: Set[str], plan: GraphBuildPlan) -> Dict[str, SharingType]:
        """Classify which tier each dependency belongs to."""
        dep_tiers = {}

        # Build lookup from node_id to sharing type
        node_to_tier = {}
        for node_plan in plan.get_all_nodes_ordered():
            node_to_tier[node_plan.node_id] = node_plan.sharing_type

        for dep_id in deps:
            if dep_id in node_to_tier:
                dep_tiers[dep_id] = node_to_tier[dep_id]
            # If not yet in plan, assume it will be added later (validation will catch issues)

        return dep_tiers

    def _plan_fully_shared(self, shared_nodes: Set[str], partially_shared: Dict[str, Set[str]],
                           plan: GraphBuildPlan, node_remapping: Dict,
                           instruction_specific_nodes: Dict[str, Set[str]]) -> List[NodeBuildPlan]:
        """Plan fully shared nodes (tier 2)."""
        fully_shared_plans = []
        skipped_count = 0

        instruction_names = list(self.graphs.keys())
        if not instruction_names:
            return fully_shared_plans

        first_instr = instruction_names[0]

        for node_id in shared_nodes:
            if node_id in partially_shared:
                skipped_count += 1
                continue  # It's partially shared, handle in tier 3

            # Skip if this node is instruction-specific for ANY instruction
            # (e.g., due to collision dependent marking)
            is_instruction_specific = any(
                node_id in specific_set
                for specific_set in instruction_specific_nodes.values()
            )
            if is_instruction_specific:
                skipped_count += 1
                continue  # Will be handled in tier 4

            node = self.graphs[first_instr].nodes.get(node_id)

            if not node or node.is_arch_state:
                if not node:
                    print(f"  SKIP (not in first instr): {node_id}")
                    skipped_count += 1
                continue  # Arch state handled in tier 1

            # Compute dependencies
            deps = self._get_node_dependencies(node, first_instr, node_remapping)
            dep_tiers = self._classify_dependency_tiers(deps, plan)

            # Validate: Fully shared can only depend on arch state or other fully shared
            for dep_id, dep_tier in dep_tiers.items():
                if dep_tier not in [SharingType.ARCHITECTURAL_STATE, SharingType.FULLY_SHARED]:
                    print(f"WARNING: Fully shared {node_id} depends on {dep_tier.value} node {dep_id}")

            node_plan = NodeBuildPlan(
                node_id=node_id,
                original_id=node_id,
                source_instruction=first_instr,
                sharing_type=SharingType.FULLY_SHARED,
                group_info=None,
                dependencies=deps,
                dependency_tier_levels=dep_tiers,
                is_collision_dependent=False,
                needs_arch_state_split=False,
                metadata={'is_shared': True}
            )
            fully_shared_plans.append(node_plan)

        return fully_shared_plans

    def _detect_assignment_groups(self, node_id: str, using_instrs: Set[str]) -> Dict:
        """Detect assignment groups for a variable node."""
        assignment_groups = {}

        for instr in sorted(using_instrs):
            if node_id not in self.graphs[instr].nodes:
                continue

            node = self.graphs[instr].nodes[node_id]

            # Compute deep assignment signature
            signatures = []
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'assignment':
                    sig = self._compute_deep_assignment_signature(
                        edge.source,
                        self.graphs[instr]
                    )
                    signatures.append(sig)

            # Group by signature
            sig_key = frozenset(signatures) if signatures else frozenset(['<no_assignment>'])
            if sig_key not in assignment_groups:
                assignment_groups[sig_key] = []
            assignment_groups[sig_key].append(instr)

        return assignment_groups

    def _create_group_info(self, node_id: str, group_instrs: List[str],
                          assignment_sig, multiple_groups: bool,
                          all_instructions: List[str]) -> GroupInfo:
        """Create GroupInfo for a sharing group."""
        # Only prefix if there are multiple assignment groups
        # Partially shared nodes with single group should remain unprefixed
        # (e.g., instr[19:15] used by 34/37 instructions should stay as "instr[19:15]", not "add_instr[19:15]")
        needs_prefix = multiple_groups

        if needs_prefix:
            prefix_instr = sorted(group_instrs)[0]  # First alphabetically
            group_id = f"{prefix_instr}_{node_id}"
        else:
            prefix_instr = None
            group_id = node_id

        return GroupInfo(
            group_id=group_id,
            original_id=node_id,
            member_instructions=set(group_instrs),
            assignment_signature=str(assignment_sig),
            needs_prefix=needs_prefix,
            prefix_instruction=prefix_instr
        )

    def _plan_groupwise_sharing(self, partially_shared: Dict[str, Set[str]],
                                collision_dependents: Set[str],
                                plan: GraphBuildPlan,
                                node_remapping: Dict) -> List[NodeBuildPlan]:
        """Plan groupwise shared nodes (tier 3) with assignment group detection."""
        groupwise_plans = []
        instruction_names = list(self.graphs.keys())

        for node_id, using_instrs in sorted(partially_shared.items()):
            first_instr = sorted(using_instrs)[0]
            if node_id not in self.graphs[first_instr].nodes:
                continue

            first_node = self.graphs[first_instr].nodes[node_id]

            # Detect assignment groups if this is a variable
            if first_node.data.get('type') == 'var':
                groups = self._detect_assignment_groups(node_id, using_instrs)
            else:
                # Non-variable: single group (all using instructions)
                groups = {frozenset(): list(using_instrs)}

            # Create plan for each assignment group
            for assignment_sig, group_instrs in groups.items():
                group_info = self._create_group_info(
                    node_id,
                    group_instrs,
                    assignment_sig,
                    multiple_groups=(len(groups) > 1),
                    all_instructions=instruction_names
                )

                # Determine group node ID (prefixed or unprefixed)
                if group_info.needs_prefix:
                    group_node_id = group_info.group_id  # e.g., "beq_imm"
                else:
                    group_node_id = node_id  # e.g., "r1"

                # Get dependencies from first instruction in group
                source_instr = group_instrs[0]
                source_node = self.graphs[source_instr].nodes[node_id]
                deps = self._get_node_dependencies(source_node, source_instr, node_remapping)
                dep_tiers = self._classify_dependency_tiers(deps, plan)

                # Validate: Groupwise can depend on tiers 1-3, NOT instruction-specific
                for dep_id, dep_tier in dep_tiers.items():
                    if dep_tier == SharingType.INSTRUCTION_SPECIFIC:
                        print(f"WARNING: Groupwise {group_node_id} depends on instruction-specific {dep_id}")

                node_plan = NodeBuildPlan(
                    node_id=group_node_id,
                    original_id=node_id,
                    source_instruction=source_instr,
                    sharing_type=SharingType.GROUPWISE_SHARED,
                    group_info=group_info,
                    dependencies=deps,
                    dependency_tier_levels=dep_tiers,
                    is_collision_dependent=(node_id in collision_dependents),
                    needs_arch_state_split=False,
                    metadata={'is_shared': True, 'original_id': node_id}
                )
                groupwise_plans.append(node_plan)

                # Track group for later transitive propagation
                plan.sharing_groups[group_node_id] = group_info

                # Update node_remapping for this group
                for instr in group_instrs:
                    if instr not in node_remapping:
                        node_remapping[instr] = {}
                    node_remapping[instr][node_id] = group_node_id

        return groupwise_plans

    def _propagate_groupwise_sharing(self, groupwise_plans: List[NodeBuildPlan],
                                     instruction_specific_nodes: Dict[str, Set[str]],
                                     collision_dependents: Set[str],
                                     plan: GraphBuildPlan,
                                     node_remapping: Dict) -> List[NodeBuildPlan]:
        """
        For each groupwise shared node, find instruction-specific dependents
        that are used by ALL members of the group, and make them groupwise too.
        """
        additional_plans = []
        processed = set()

        for group_plan in groupwise_plans:
            if not group_plan.group_info or not group_plan.group_info.needs_prefix:
                continue

            group_info = group_plan.group_info
            group_id = group_info.group_id
            group_members = group_info.member_instructions

            # BFS to find transitive dependents
            to_process = [group_plan.original_id]

            while to_process:
                current_id = to_process.pop(0)

                if current_id in processed:
                    continue
                processed.add(current_id)

                # Find dependents in instruction-specific sets
                potential_dependents = set()
                for instr in group_members:
                    if instr not in self.graphs or current_id not in self.graphs[instr].nodes:
                        continue

                    node = self.graphs[instr].nodes[current_id]
                    for edge in node.outgoing_edges:
                        dep_id = edge.target.id

                        # Check if this is instruction-specific
                        if dep_id in instruction_specific_nodes.get(instr, set()):
                            potential_dependents.add(dep_id)

                # For each potential dependent, check if ALL group members have it
                for dep_id in potential_dependents:
                    if dep_id in collision_dependents:
                        continue  # Collision dependents stay instruction-specific

                    # Check membership
                    instrs_with_dep = [
                        i for i in group_members
                        if i in self.graphs and dep_id in self.graphs[i].nodes
                    ]

                    if len(instrs_with_dep) == len(group_members):
                        # All group members have it - promote to groupwise!
                        group_dep_id = f"{group_info.prefix_instruction}_{dep_id}"

                        # Create plan for this grouped dependent
                        source_instr = instrs_with_dep[0]
                        source_node = self.graphs[source_instr].nodes[dep_id]
                        deps = self._get_node_dependencies(source_node, source_instr, node_remapping)

                        # Create group info for dependent
                        dep_group_info = GroupInfo(
                            group_id=group_dep_id,
                            original_id=dep_id,
                            member_instructions=set(instrs_with_dep),
                            assignment_signature="<propagated>",
                            needs_prefix=True,
                            prefix_instruction=group_info.prefix_instruction
                        )

                        node_plan = NodeBuildPlan(
                            node_id=group_dep_id,
                            original_id=dep_id,
                            source_instruction=source_instr,
                            sharing_type=SharingType.GROUPWISE_SHARED,
                            group_info=dep_group_info,
                            dependencies=deps,
                            dependency_tier_levels=self._classify_dependency_tiers(deps, plan),
                            is_collision_dependent=False,
                            needs_arch_state_split=False,
                            metadata={'is_shared': True, 'original_id': dep_id, 'propagated': True}
                        )

                        additional_plans.append(node_plan)
                        plan.sharing_groups[group_dep_id] = dep_group_info

                        # Continue propagation from this dependent
                        to_process.append(dep_id)

                        # Remove from instruction-specific for these instructions
                        for instr in instrs_with_dep:
                            if instr in instruction_specific_nodes and dep_id in instruction_specific_nodes[instr]:
                                instruction_specific_nodes[instr].remove(dep_id)

                        # Update node_remapping
                        for instr in instrs_with_dep:
                            if instr not in node_remapping:
                                node_remapping[instr] = {}
                            node_remapping[instr][dep_id] = group_dep_id

        return additional_plans

    def _plan_instruction_specific(self, instruction_specific_nodes: Dict[str, Set[str]],
                                   collision_dependents: Set[str],
                                   plan: GraphBuildPlan,
                                   node_remapping: Dict) -> List[NodeBuildPlan]:
        """Plan instruction-specific nodes (tier 4)."""
        specific_plans = []
        instruction_names = list(self.graphs.keys())

        # PASS 1: Determine merged IDs for all instruction-specific nodes
        # and populate node_remapping so dependencies can be resolved
        for instr, specific_node_ids in sorted(instruction_specific_nodes.items()):
            for node_id in sorted(specific_node_ids):
                if node_id not in self.graphs[instr].nodes:
                    continue

                # Determine if needs prefix
                appears_in_multiple = sum(
                    1 for other_instr in instruction_names
                    if node_id in instruction_specific_nodes.get(other_instr, set())
                ) > 1

                # CRITICAL: Also check if this node_id is already used in partially_shared (tier 3)
                # If so, we MUST prefix to avoid collision
                already_in_partial = node_id in self.partially_shared_nodes

                if appears_in_multiple or already_in_partial:
                    merged_id = f"{instr}_{node_id}"
                else:
                    merged_id = node_id  # Unique, no prefix needed

                # Update node_remapping
                if instr not in node_remapping:
                    node_remapping[instr] = {}
                node_remapping[instr][node_id] = merged_id

        # PASS 2: Extract dependencies and create plans
        for instr, specific_node_ids in sorted(instruction_specific_nodes.items()):
            for node_id in sorted(specific_node_ids):
                if node_id not in self.graphs[instr].nodes:
                    continue

                node = self.graphs[instr].nodes[node_id]

                # Get the merged ID we computed in pass 1
                merged_id = node_remapping[instr][node_id]

                # Get dependencies (may reference groupwise nodes!)
                deps = self._get_node_dependencies(node, instr, node_remapping)
                dep_tiers = self._classify_dependency_tiers(deps, plan)

                # Instruction-specific can depend on ANY tier (this is the bottom of the hierarchy)

                node_plan = NodeBuildPlan(
                    node_id=merged_id,
                    original_id=node_id,
                    source_instruction=instr,
                    sharing_type=SharingType.INSTRUCTION_SPECIFIC,
                    group_info=None,
                    dependencies=deps,
                    dependency_tier_levels=dep_tiers,
                    is_collision_dependent=(node_id in collision_dependents),
                    needs_arch_state_split=False,
                    metadata={'instruction': instr, 'original_id': node_id}
                )
                specific_plans.append(node_plan)

        return specific_plans

    def _topological_sort_tier(self, plans: List[NodeBuildPlan]) -> List[NodeBuildPlan]:
        """
        Sort nodes within a tier by dependencies.
        This is Kahn's algorithm with cycle detection.
        """
        # Build adjacency list
        node_map = {p.node_id: p for p in plans}
        in_degree = {p.node_id: 0 for p in plans}
        adj_list = {p.node_id: [] for p in plans}

        for plan in plans:
            for dep_id in plan.dependencies:
                if dep_id in node_map:  # Dependency within this tier
                    adj_list[dep_id].append(plan.node_id)
                    in_degree[plan.node_id] += 1

        # Kahn's algorithm
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        sorted_ids = []

        while queue:
            nid = queue.pop(0)
            sorted_ids.append(nid)

            for neighbor in adj_list[nid]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(sorted_ids) != len(plans):
            # Cycle detected!
            remaining = set(in_degree.keys()) - set(sorted_ids)
            raise ValueError(
                f"Circular dependencies in tier: {remaining}\n"
                f"This indicates a bug in classification or dependency tracking"
            )

        return [node_map[nid] for nid in sorted_ids]

    def _generate_edge_plans(self, plan: GraphBuildPlan, node_remapping: Dict) -> List[EdgeBuildPlan]:
        """Generate edge build plans based on node plans."""
        edge_plans = []

        # For each instruction, iterate through its edges
        for instr_name, graph in self.graphs.items():
            for edge in graph.edges.values():
                source_orig = edge.source.id
                target_orig = edge.target.id

                # Map to merged graph IDs
                source_merged = node_remapping.get(instr_name, {}).get(source_orig, source_orig)
                target_merged = node_remapping.get(instr_name, {}).get(target_orig, target_orig)

                # Create edge plan
                edge_data_copy = copy.deepcopy(edge.data)
                # Store source instruction on edge for proper enable matching when nodes are grouped
                edge_data_copy['source_instruction'] = instr_name
                edge_plan = EdgeBuildPlan(
                    source_id=source_merged,
                    target_id=target_merged,
                    edge_data=edge_data_copy,
                    requires_remapping=(source_merged != source_orig or target_merged != target_orig)
                )

                # Check if this edge already exists in the plan (for shared nodes)
                # Include position check for concatenation inputs (allows multiple edges
                # from same source at different positions, e.g., two 1'b1 literals)
                # IMPORTANT: Also include 'enable' field - edges with different conditions
                # must NOT be considered duplicates (e.g., rf_svc_lr when (cond_pass & is_svc)
                # vs rf_svc_lr when (cond_pass) from different instructions)
                # IMPORTANT: Also include 'input_index' and 'select_index' - mux edges
                # with the same source/target but different indices are distinct
                # (e.g., two mux_input edges from literal '1' at indices 0 and 1
                # with different select conditions must both be preserved)
                is_duplicate = any(
                    ep.source_id == edge_plan.source_id and
                    ep.target_id == edge_plan.target_id and
                    ep.edge_data.get('type') == edge_plan.edge_data.get('type') and
                    ep.edge_data.get('position') == edge_plan.edge_data.get('position') and
                    ep.edge_data.get('enable') == edge_plan.edge_data.get('enable') and
                    ep.edge_data.get('input_index') == edge_plan.edge_data.get('input_index') and
                    ep.edge_data.get('select_index') == edge_plan.edge_data.get('select_index')
                    for ep in edge_plans
                )

                if not is_duplicate:
                    edge_plans.append(edge_plan)

        return edge_plans

    def _validate_build_plan(self, plan: GraphBuildPlan) -> None:
        """Comprehensive validation of build plan correctness."""

        all_nodes = plan.get_all_nodes_ordered()
        node_ids = {n.node_id for n in all_nodes}

        # Rule 1: No duplicate node IDs
        if len(node_ids) != len(all_nodes):
            duplicates = [n.node_id for n in all_nodes if sum(1 for x in all_nodes if x.node_id == n.node_id) > 1]
            raise ValueError(f"Duplicate node IDs in plan: {set(duplicates)}")

        # Rule 2: All dependencies exist in plan
        for node_plan in all_nodes:
            for dep_id in node_plan.dependencies:
                if dep_id not in node_ids:
                    raise ValueError(
                        f"{node_plan.node_id} depends on {dep_id} which is not in plan"
                    )

        # Rule 3: Dependencies respect tier hierarchy
        tier_order = {
            SharingType.ARCHITECTURAL_STATE: 0,
            SharingType.FULLY_SHARED: 1,
            SharingType.GROUPWISE_SHARED: 2,
            SharingType.INSTRUCTION_SPECIFIC: 3
        }

        for node_plan in all_nodes:
            node_tier = tier_order[node_plan.sharing_type]

            for dep_id, dep_tier in node_plan.dependency_tier_levels.items():
                dep_tier_level = tier_order[dep_tier]

                if dep_tier_level > node_tier:
                    raise ValueError(
                        f"{node_plan.node_id} (tier {node_tier}) cannot depend on "
                        f"{dep_id} (tier {dep_tier_level}) - violates tier hierarchy"
                    )

        # Rule 4: Dependencies appear before dependents in ordered list
        added_so_far = set()
        for node_plan in all_nodes:
            for dep_id in node_plan.dependencies:
                if dep_id not in added_so_far:
                    raise ValueError(
                        f"Dependency {dep_id} not yet added when {node_plan.node_id} is added"
                    )
            added_so_far.add(node_plan.node_id)

        # Rule 5: Architectural state cannot be instruction-specific
        for node_plan in plan.architectural_nodes:
            if node_plan.sharing_type != SharingType.ARCHITECTURAL_STATE:
                raise ValueError(
                    f"Architectural node {node_plan.node_id} has wrong sharing type"
                )

        # Rule 6: All edge endpoints exist
        for edge_plan in plan.edges:
            if edge_plan.source_id not in node_ids:
                raise ValueError(f"Edge source {edge_plan.source_id} not in plan")
            if edge_plan.target_id not in node_ids:
                raise ValueError(f"Edge target {edge_plan.target_id} not in plan")

        plan.validated = True
        print("✓ Build plan validated successfully")

    def _generate_build_plan_new(self, shared_nodes: Set[str],
                                 partially_shared_nodes: Dict[str, Set[str]],
                                 instruction_specific_nodes: Dict[str, Set[str]],
                                 collision_dependents: Set[str]) -> GraphBuildPlan:
        """Generate complete build plan with all four tiers."""
        plan = GraphBuildPlan()
        node_remapping = {}  # Track how nodes are remapped

        # Tier 1: Architectural state (no dependencies)
        print("Planning Tier 1: Architectural State...")
        plan.architectural_nodes = self._plan_architectural_state(shared_nodes)

        # Tier 2: Fully shared (depends on tier 1)
        print("Planning Tier 2: Fully Shared...")
        fully_shared = self._plan_fully_shared(shared_nodes, partially_shared_nodes, plan, node_remapping, instruction_specific_nodes)
        plan.fully_shared_nodes = self._topological_sort_tier(fully_shared)

        # Tier 3: Groupwise sharing with propagation
        print("Planning Tier 3: Groupwise Sharing...")
        groupwise = self._plan_groupwise_sharing(partially_shared_nodes, collision_dependents, plan, node_remapping)
        groupwise += self._propagate_groupwise_sharing(groupwise, instruction_specific_nodes,
                                                      collision_dependents, plan, node_remapping)
        plan.groupwise_shared_nodes = self._topological_sort_tier(groupwise)

        # Tier 4: Instruction-specific (depends on tiers 1-3)
        print("Planning Tier 4: Instruction-Specific...")
        specific = self._plan_instruction_specific(instruction_specific_nodes, collision_dependents, plan, node_remapping)
        plan.instruction_specific_nodes = self._topological_sort_tier(specific)

        # Generate edge plans
        print("Planning Edges...")
        plan.edges = self._generate_edge_plans(plan, node_remapping)

        # Validate
        print("Validating Build Plan...")
        self._validate_build_plan(plan)

        return plan

    def _execute_build_plan(self, plan: GraphBuildPlan) -> ResourceGraph:
        """Execute validated build plan to construct merged graph."""

        if not plan.validated:
            raise ValueError("Cannot execute unvalidated plan")

        merged_graph = ResourceGraph()

        print("Executing Build Plan...")
        print(f"  - Architectural nodes: {len(plan.architectural_nodes)}")
        print(f"  - Fully shared nodes: {len(plan.fully_shared_nodes)}")
        print(f"  - Groupwise shared nodes: {len(plan.groupwise_shared_nodes)}")
        print(f"  - Instruction-specific nodes: {len(plan.instruction_specific_nodes)}")

        # Execute in tier order (dependencies guaranteed to exist)
        for node_plan in plan.get_all_nodes_ordered():
            # Get source node
            source_node = self.graphs[node_plan.source_instruction].nodes[node_plan.original_id]

            # Create new node with merged graph ID
            new_node = Node(
                node_plan.node_id,
                data=copy.deepcopy(source_node.data),
                is_arch_state=(node_plan.sharing_type == SharingType.ARCHITECTURAL_STATE)
            )

            # Set sharing metadata
            if node_plan.sharing_type in [SharingType.FULLY_SHARED, SharingType.GROUPWISE_SHARED]:
                new_node.is_shared = True

            # Add instruction for instruction-specific nodes
            if node_plan.sharing_type == SharingType.INSTRUCTION_SPECIFIC:
                new_node.data['instruction'] = node_plan.source_instruction

            # Add original_id if node was renamed
            if node_plan.node_id != node_plan.original_id:
                new_node.data['original_id'] = node_plan.original_id
                # Update name and display_name to match the new prefixed ID
                new_node.data['name'] = node_plan.node_id
                new_node.data['display_name'] = node_plan.node_id

            # Add group info metadata
            if node_plan.group_info:
                new_node.data['group_id'] = node_plan.group_info.group_id
                new_node.data['group_members'] = list(node_plan.group_info.member_instructions)

            # Add to graph
            merged_graph.add_node(new_node)

            # ASSERTION: All dependencies exist
            for dep_id in node_plan.dependencies:
                if dep_id not in merged_graph.nodes:
                    raise ValueError(
                        f"Dependency {dep_id} not found for {node_plan.node_id} - plan execution bug!"
                    )

        print(f"Added {len(merged_graph.nodes)} nodes to merged graph")

        # Add all edges (all endpoints guaranteed to exist)
        for edge_plan in plan.edges:
            source = merged_graph.nodes.get(edge_plan.source_id)
            target = merged_graph.nodes.get(edge_plan.target_id)

            if not source or not target:
                print(f"WARNING: Skipping edge {edge_plan.source_id} -> {edge_plan.target_id} (endpoints not found)")
                continue

            edge = Edge(source, target, data=edge_plan.edge_data)
            merged_graph.add_edge(edge)

        print(f"Added {len(merged_graph.edges)} edges to merged graph")

        # Handle architectural state splitting if needed
        for node_plan in plan.architectural_nodes:
            if node_plan.needs_arch_state_split:
                self._split_arch_state_read_write(merged_graph, node_plan.node_id)

        # Done! Graph is complete and correct
        return merged_graph


def split_arch_state_nodes(graph: ResourceGraph):
    """
    Split architectural state nodes that are both read and written into separate _rd and _wr nodes.

    This is a standalone version of ResourceGraphMerger._split_arch_state_read_write()
    that can be applied to any graph, including single instruction graphs.

    For nodes like 'pc' that have both:
    - Incoming assignment edges (writes)
    - Outgoing read edges (operand, array_index, etc.)

    We split them into:
    - 'pc_rd' - for reads (used as operands, etc.)
    - 'pc_wr' - for writes (receives assignments)
    """
    print("Splitting architectural state read/write nodes...")

    # Only split nodes that are truly ISA state (marked by ISA parser)
    # Do NOT mark nodes as is_arch_state just because they have _rd or _wr in the name
    # (e.g., imm[11]_rd is a bit slice, not ISA state)

    nodes_to_split = []

    # Edge types that represent reading from architectural state
    read_edge_types = ['operand', 'left_operand', 'right_operand', 'array_index', 'bit_access',
                       'mux_input', 'mux_default_input', 'mux_select',
                       'ternary_condition', 'ternary_true', 'ternary_false',
                       'array_base', 'concatenation_input']

    # Find nodes that need splitting: nodes with both reads and writes
    for node_id, node in list(graph.nodes.items()):
        has_write = any(e.data.get('type') == 'assignment' for e in node.incoming_edges)
        has_read = any(e.data.get('type') in read_edge_types
                      for e in node.outgoing_edges)

        # Skip if already has _rd or _wr suffix (already split)
        if node_id.endswith('_rd') or node_id.endswith('_wr'):
            continue

        # Skip if this node has already been split
        if getattr(node, 'already_split', False):
            continue

        # Skip memory arrays - they're accessed via indexing, not split into copies
        if node.data.get('array_depth') or node.data.get('is_memory'):
            continue

        # Always split scalar arch state nodes for consistency during merging
        # Some instructions may only read, others only write - merger handles this
        if node.is_arch_state:
            nodes_to_split.append(node)
            print(f"  Will split: {node_id} (has {len([e for e in node.incoming_edges if e.data.get('type')=='assignment'])} writes, {len([e for e in node.outgoing_edges if e.data.get('type') in read_edge_types])} reads)")

    if not nodes_to_split:
        print("  No nodes need splitting")
        return

    splits_made = 0

    for original_node in nodes_to_split:
        node_id = original_node.id

        # Create _rd node (for reads)
        rd_node_id = f"{node_id}_rd"
        rd_node_data = original_node.data.copy() if original_node.data else {}
        if 'name' not in rd_node_data:
            rd_node_data['name'] = node_id
        # Update display_name to show the _rd suffix
        rd_node_data['display_name'] = rd_node_id
        rd_node = Node(
            rd_node_id,
            rd_node_data,
            is_arch_state=True,
            is_uarch_state=original_node.is_uarch_state,
            uarch_time=original_node.uarch_time if original_node.uarch_time is not None else 0,
            from_isa_spec=getattr(original_node, 'from_isa_spec', False),
            already_split=True
        )
        graph.add_node(rd_node)

        # Create _wr node (for writes)
        wr_node_id = f"{node_id}_wr"
        wr_node_data = original_node.data.copy() if original_node.data else {}
        if 'name' not in wr_node_data:
            wr_node_data['name'] = node_id
        # Update display_name to show the _wr suffix
        wr_node_data['display_name'] = wr_node_id
        wr_node = Node(
            wr_node_id,
            wr_node_data,
            is_arch_state=True,
            is_uarch_state=original_node.is_uarch_state,
            uarch_time=None,
            from_isa_spec=getattr(original_node, 'from_isa_spec', False),
            already_split=True
        )
        graph.add_node(wr_node)

        # Redirect incoming assignment edges to _wr node
        max_source_time = 0
        for edge in list(original_node.incoming_edges):
            if edge.data.get('type') == 'assignment':
                new_edge = Edge(edge.source, wr_node, data=edge.data.copy())
                graph.add_edge(new_edge)
                graph.remove_edge(edge.id)
                if edge.source.uarch_time is not None:
                    max_source_time = max(max_source_time, edge.source.uarch_time)

        set_node_timing(wr_node, max_source_time)

        # Redirect outgoing read edges to come from _rd node
        for edge in list(original_node.outgoing_edges):
            edge_type = edge.data.get('type', '')
            if edge_type in read_edge_types:
                new_edge = Edge(rd_node, edge.target, data=edge.data.copy())
                graph.add_edge(new_edge)
                graph.remove_edge(edge.id)

        # Note: We don't add a forwarding edge from _wr to _rd because:
        # 1. It creates visual clutter
        # 2. The relationship is implicit - writes update state that reads access
        # 3. Unlike array accesses (rf[rs]_rd), there's no base storage node to connect through

        # Remove original node if it has no more edges
        if not original_node.incoming_edges and not original_node.outgoing_edges:
            graph.remove_node(node_id)
            print(f"    Split {node_id} -> {rd_node_id} (read, cycle={rd_node.uarch_time}) + {wr_node_id} (write, cycle={wr_node.uarch_time})")
            splits_made += 1
        else:
            original_node.already_split = True
            print(f"    WARNING: {node_id} still has edges after split attempt")

    print(f"Architectural state splitting complete: {splits_made} node(s) split")

    # Re-infer timing after splitting
    if splits_made > 0:
        print("Re-inferring uarch_time after architectural state splitting...")
        reinfer_timing(graph)


def _create_pc_increment_mux(merged_graph: ResourceGraph, instruction_lengths: Dict[str, int], pc_name: str):
    """
    Create a PC increment multiplexer for variable-length instructions using shared PC increment nodes.

    This creates:
    - Shared pc_plus_1, pc_plus_2, pc_plus_3 nodes (based on unique instruction lengths)
    - OR nodes that combine instruction enables by length group
    - One-hot mux to select between shared PC increments

    Args:
        merged_graph: The merged ResourceGraph
        instruction_lengths: Dict mapping instruction names to their lengths in bytes
        pc_name: Name of the program counter register
    """
    pc_rd_id = f"{pc_name}_rd"
    pc_wr_id = f"{pc_name}_wr"

    if pc_wr_id not in merged_graph.nodes:
        print(f"  Warning: No {pc_wr_id} node found - skipping PC increment mux")
        return

    pc_wr_node = merged_graph.nodes[pc_wr_id]
    pc_rd_node = merged_graph.nodes.get(pc_rd_id)

    if not pc_rd_node:
        print(f"  Warning: No {pc_rd_id} node found - skipping PC increment mux")
        return

    # Detect branch instructions - those with conditional PC updates (ternary operations)
    branch_instructions = set()
    pc_wr_mux_id = f"{pc_name}_wr_mux"

    for node_id, node in merged_graph.nodes.items():
        if node.data.get('type') == 'ternary_op':
            for edge in node.outgoing_edges:
                if edge.target.id == pc_wr_id or edge.target.id == pc_wr_mux_id:
                    if '_' in node_id:
                        instr_name = node_id.split('_')[0]
                        if instr_name in instruction_lengths:
                            branch_instructions.add(instr_name)
                            print(f"  Detected branch instruction: {instr_name} (has conditional PC write)")
                            break

    # Group ALL instructions by their length (including branches).
    # Branches handle their own PC update via priority mux entries, so
    # including them in select_pc_plus_N is harmless for pc_increment_mux
    # (which is only the default path). But it's essential for ibuf's
    # ibuf_instr_length, which needs the instruction length for ALL opcodes.
    instructions_by_length = {}
    for instr_name, length in instruction_lengths.items():
        if instr_name in branch_instructions:
            print(f"  Including branch {instr_name} in select_pc_plus_{length} (needed for ibuf_instr_length)")
        if length not in instructions_by_length:
            instructions_by_length[length] = []
        instructions_by_length[length].append(instr_name)

    if not instructions_by_length:
        print("  No non-branch instructions found - skipping PC increment mux")
        return

    print(f"\nCreating shared PC increment nodes for lengths: {sorted(instructions_by_length.keys())}")

    # Create literal nodes for each unique increment value
    increment_literals = {}
    for length in instructions_by_length.keys():
        literal_id = f"pc_increment_{length}"
        if literal_id not in merged_graph.nodes:
            literal_node = Node(literal_id, {
                'type': 'literal',
                'value': length,
                'display_name': str(length)
            })
            merged_graph.add_node(literal_node)
            increment_literals[length] = literal_node
            print(f"  Created increment literal: {length}")

    # Create SHARED PC + increment operation nodes (one per unique length)
    pc_plus_nodes = {}
    for length in sorted(instructions_by_length.keys()):
        increment_node = increment_literals[length]
        op_id = f"pc_plus_{length}"

        op_node = Node(op_id, {
            'type': 'operation',
            'operator': '+',
            'display_name': f"({pc_name}_rd + {length})",
            'expression': {
                'type': 'binary_op',
                'operator': '+',
                'left': {'type': 'identifier', 'name': pc_rd_id},
                'right': {'type': 'literal', 'value': length}
            }
        })
        merged_graph.add_node(op_node)

        pc_edge = Edge(pc_rd_node, op_node, data={'type': 'operand', 'position': 'left'})
        merged_graph.add_edge(pc_edge)

        inc_edge = Edge(increment_node, op_node, data={'type': 'operand', 'position': 'right'})
        merged_graph.add_edge(inc_edge)

        pc_plus_nodes[length] = op_node
        instr_names = ", ".join(instructions_by_length[length])
        print(f"  Created shared pc_plus_{length} for: {instr_names}")

    # Create OR nodes that combine instruction enables by length group
    select_signals = {}
    for length, instr_list in sorted(instructions_by_length.items()):
        if len(instr_list) == 1:
            instr_name = instr_list[0]
            enable_signal_id = f"{instr_name}_enable"
            enable_node = merged_graph.nodes.get(enable_signal_id)
            if enable_node:
                select_signals[length] = enable_node
                print(f"  Using {enable_signal_id} for pc_plus_{length} selection")
            else:
                print(f"  Warning: No enable signal found for {instr_name}")
        else:
            or_node_id = f"select_pc_plus_{length}"
            enable_nodes = []
            for instr_name in instr_list:
                enable_signal_id = f"{instr_name}_enable"
                enable_node = merged_graph.nodes.get(enable_signal_id)
                if enable_node:
                    enable_nodes.append((instr_name, enable_node))
                else:
                    print(f"  Warning: No enable signal found for {instr_name}")

            if len(enable_nodes) == 0:
                print(f"  Warning: No enable signals found for length {length}")
                continue
            elif len(enable_nodes) == 1:
                select_signals[length] = enable_nodes[0][1]
                print(f"  Using {enable_nodes[0][0]}_enable for pc_plus_{length} selection")
            else:
                or_expr = {'type': 'identifier', 'name': f"{enable_nodes[0][0]}_enable"}
                for i in range(1, len(enable_nodes)):
                    or_expr = {
                        'type': 'binary_op',
                        'operator': '|',
                        'left': or_expr,
                        'right': {'type': 'identifier', 'name': f"{enable_nodes[i][0]}_enable"}
                    }

                or_node = Node(or_node_id, {
                    'type': 'operation',
                    'operator': '|',
                    'display_name': f"select_pc_plus_{length}",
                    'expression': or_expr
                })
                merged_graph.add_node(or_node)

                for instr_name, enable_node in enable_nodes:
                    edge = Edge(enable_node, or_node, data={'type': 'operand'})
                    merged_graph.add_edge(edge)

                select_signals[length] = or_node
                instr_names_str = " | ".join([name for name, _ in enable_nodes])
                print(f"  Created OR node: {or_node_id} = {instr_names_str}")

    # Create ONE-HOT multiplexer to select correct PC increment
    mux_id = f"{pc_name}_increment_mux"
    mux_builder = MuxBuilder(merged_graph, mux_id, MuxType.ONE_HOT)
    mux_builder.create_or_get_mux(display_name=f"{pc_name} Increment One-Hot MUX")

    for i, length in enumerate(sorted(instructions_by_length.keys())):
        pc_plus_node = pc_plus_nodes[length]
        select_node = select_signals.get(length)

        if select_node:
            mux_builder.add_input(
                source=pc_plus_node,
                select=select_node,
                input_index=i,
                metadata={'instruction_length': length}
            )
            print(f"  Added mux input {i}: pc_plus_{length} (selected by {select_node.id})")
        else:
            print(f"  Warning: No select signal for length {length}")

    # Check if there's a pc_wr_mux (created by branch instructions)
    pc_wr_mux_node = merged_graph.nodes.get(pc_wr_mux_id)

    if pc_wr_mux_node:
        print(f"  Found branch mux {pc_wr_mux_id}, integrating with it...")
        # Replace the pc_wr_mux default input with pc_increment_mux
        # This way branches override the default PC increment
        mux_node = merged_graph.nodes[mux_id]

        # Find and remove old default input edge to pc_wr_mux
        old_default_edges = [e for e in list(pc_wr_mux_node.incoming_edges)
                            if e.data.get('type') == 'mux_default_input']
        for old_edge in old_default_edges:
            merged_graph.remove_edge(old_edge.id)
            print(f"    Removed old default: {old_edge.source.id}")

        # Connect pc_increment_mux as the new default input to pc_wr_mux
        default_edge = Edge(mux_node, pc_wr_mux_node,
                           data={'type': 'mux_default_input'})
        merged_graph.add_edge(default_edge)
        print(f"  Connected {mux_id} as default to {pc_wr_mux_id}")
    else:
        # No branch mux - connect increment mux directly to pc_wr
        mux_builder.connect_output(pc_wr_node, 'assignment',
                                   metadata={'description': f"Variable-length PC increment (one-hot)"})
        print(f"  Connected {mux_id} directly to pc_wr")

    print(f"  Created one-hot PC increment multiplexer with {len(pc_plus_nodes)} shared inputs")


def merge_instructions(instruction_files: Dict[str, str],
                       memory_constraints: Dict[str, int] = None,
                       pc_name: str = "pc",
                       defines: Dict[str, str] = None) -> ResourceGraph:
    """
    Merge multiple instruction ISA/ILA files into a unified ResourceGraph.

    Args:
        instruction_files: Dict mapping instruction names to ISA or ILA JSON file paths
        memory_constraints: Optional dict mapping memory names to maximum bit widths
                          (e.g., {'dmem': 16} forces dmem to 16-bit width)
                          Accesses wider than the constraint will use multi-cycle logic
        pc_name: Name of the program counter register (default "pc")
        defines: Optional dict of preprocessor defines (e.g., {'VM': '1'})

    Returns:
        Merged ResourceGraph with instruction decode logic
    """
    merger = ResourceGraphMerger(defines=defines)

    # Store memory constraints
    if memory_constraints:
        merger.memory_constraints = memory_constraints

    # Add all instructions
    for instr_name, isa_file in instruction_files.items():
        success = merger.add_instruction(instr_name, isa_file)
        if not success:
            raise ValueError(f"Failed to add instruction {instr_name}")

    # Analyze instruction lengths for variable-length ISAs
    # Only includes instructions that have pc = pc + N patterns (not computed jumps)
    print("\nAnalyzing instruction lengths...")
    instruction_lengths = {}
    for instr_name, graph in merger.graphs.items():
        length = analyze_instruction_length(graph, pc_name)
        if length is not None:
            instruction_lengths[instr_name] = length
            print(f"  {instr_name}: {length} bytes")
        else:
            print(f"  {instr_name}: computed destination (no fixed increment)")

    if instruction_lengths:
        max_length = max(instruction_lengths.values())
        print(f"  Maximum instruction length: {max_length} bytes")
    else:
        max_length = 0
        print(f"  No fixed PC increment patterns found")

    # Remove dead intermediate PC writes before merging (must happen after
    # instruction length analysis which reads the intermediate edges).
    remove_intermediate_pc_writes(merger.graphs, pc_name)

    # Merge the graphs, passing pc_name for variable-length ISA support
    merged_graph = merger.merge_graphs(pc_name=pc_name)

    # If we have variable-length instructions, create PC increment multiplexer
    # Only needed when there are multiple different increment values
    unique_lengths = set(instruction_lengths.values())
    if len(unique_lengths) > 1:
        print(f"\nCreating PC increment multiplexer for variable-length instructions...")
        _create_pc_increment_mux(merged_graph, instruction_lengths, pc_name)

    return merged_graph