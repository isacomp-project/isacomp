"""
Mux deduplication for merged ResourceGraphs.

This module implements algorithms to deduplicate common subexpressions in
gated write muxes, particularly for architectural state writes like pc_wr.

For example, if we have:
  beq_enable ? (beq_res ? branch_dest : (pc + 4)) : ...
  bne_enable ? (bne_res ? branch_dest : (pc + 4)) : ...
  ...
  default: (pc + 4)

We want to identify that:
  - (pc + 4) appears in many paths
  - branch_dest appears when any branch is taken

And merge them with OR'd enables:
  - (pc + 4) when: (beq_enable && !beq_res) || (bne_enable && !bne_res) || (!any_branch && !any_jump)
  - branch_dest when: (beq_enable && beq_res) || (bne_enable && bne_res) || ...
"""

from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass, field
from core.resource_graph import ResourceGraph, Node, Edge
from core.mux_utils import MuxBuilder, MuxType


@dataclass
class PathCondition:
    """Represents a single condition in a path through the mux tree."""
    enable_node_id: str  # The enable signal (e.g., 'beq_enable')
    polarity: bool       # True = condition must be true, False = condition must be false

    def __hash__(self):
        return hash((self.enable_node_id, self.polarity))

    def __eq__(self, other):
        return self.enable_node_id == other.enable_node_id and self.polarity == other.polarity


@dataclass
class MuxPath:
    """Represents a complete path through the mux tree to a leaf value."""
    conditions: List[PathCondition]  # Ordered list of conditions forming this path
    value_node_id: str              # The leaf value reached by this path
    source_instruction: Optional[str] = None  # Which instruction this path came from
    original_input_index: Optional[int] = None  # Index in original mux (preserves priority)

    def __hash__(self):
        return hash((tuple(self.conditions), self.value_node_id))

    def to_condition_expr(self, graph: ResourceGraph) -> str:
        """Convert path conditions to a human-readable expression."""
        if not self.conditions:
            return "default"

        parts = []
        for cond in self.conditions:
            node = graph.nodes.get(cond.enable_node_id)
            name = node.data.get('display_name', cond.enable_node_id) if node else cond.enable_node_id
            if cond.polarity:
                parts.append(name)
            else:
                parts.append(f"!{name}")
        return " && ".join(parts)


@dataclass
class ValueGroup:
    """Groups multiple paths that lead to the same value."""
    value_node_id: str               # The common value
    paths: List[MuxPath]             # All paths leading to this value

    def get_merged_condition(self, graph: ResourceGraph) -> str:
        """Get the OR'd condition for all paths."""
        if not self.paths:
            return "1'b0"

        path_exprs = [f"({path.to_condition_expr(graph)})" for path in self.paths]
        return " || ".join(path_exprs)


class MuxDeduplicator:
    """Deduplicates common subexpressions in gated write muxes."""

    def __init__(self, graph: ResourceGraph):
        self.graph = graph
        self.debug = True

    def deduplicate_arch_state_muxes(self, arch_state_wr_node_id: str) -> bool:
        """
        Deduplicate common subexpressions in the multiplexer for an architectural state write node.

        Args:
            arch_state_wr_node_id: The architectural state write node (e.g., 'pc_wr')

        Returns:
            True if deduplication was performed, False otherwise
        """
        if self.debug:
            print(f"\n=== Deduplicating muxes for {arch_state_wr_node_id} ===")

        # Step 1: Find the multiplexer that writes to this arch state
        mux_node = self._find_arch_state_mux(arch_state_wr_node_id)

        if not mux_node:
            if self.debug:
                print(f"  No multiplexer found for {arch_state_wr_node_id}")
            return False

        if self.debug:
            print(f"  Found multiplexer: {mux_node.id}")

        # Step 2: Extract all mux inputs and their select conditions
        mux_inputs = self._get_mux_inputs(mux_node)

        if len(mux_inputs) <= 1:
            if self.debug:
                print(f"  Only {len(mux_inputs)} input(s) found, skipping deduplication")
            return False

        if self.debug:
            print(f"  Found {len(mux_inputs)} mux inputs")

        # Step 3: Build decision tree for each mux input
        all_paths = []
        for i, (input_node, select_node) in enumerate(mux_inputs):
            paths = self._extract_paths_from_input(input_node, select_node)
            for path in paths:
                path.original_input_index = i
            all_paths.extend(paths)

        if self.debug:
            print(f"  Extracted {len(all_paths)} total paths")

        # Step 4: Group paths by common values
        value_groups = self._group_paths_by_value(all_paths)

        if self.debug:
            print(f"  Found {len(value_groups)} unique values")
            for value_id, group in value_groups.items():
                print(f"    {value_id}: {len(group.paths)} paths")

        # Step 5: Identify which values have multiple paths (candidates for merging)
        mergeable_groups = {vid: grp for vid, grp in value_groups.items() if len(grp.paths) > 1}

        if not mergeable_groups:
            if self.debug:
                print(f"  No mergeable groups found")
            return False

        if self.debug:
            print(f"  Found {len(mergeable_groups)} mergeable value groups")

        # Step 6: Report merging opportunities
        self._report_merging_opportunities(mergeable_groups)

        # Step 7: Perform actual merging
        if self.debug:
            print(f"\n  === Performing Mux Reconstruction ===")

        self._rebuild_mux_with_merged_paths(mux_node, value_groups, mux_inputs)

        return True

    def _find_arch_state_mux(self, arch_state_wr_node_id: str) -> Optional[Node]:
        """
        Find the multiplexer node that writes to the given arch state.

        Returns:
            The mux node, or None if not found
        """
        wr_node = self.graph.nodes.get(arch_state_wr_node_id)
        if not wr_node:
            return None

        # Find the multiplexer that assigns to this arch state
        for edge in wr_node.incoming_edges:
            if edge.data.get('type') == 'assignment':
                source_node = edge.source
                # Check if it's a multiplexer
                if source_node.data.get('type') == 'multiplexer':
                    return source_node

        return None

    def _get_mux_inputs(self, mux_node: Node) -> List[Tuple[Node, Node]]:
        """
        Get all (input_node, select_node) pairs from a multiplexer.

        Returns:
            List of (input, select) tuples
        """
        inputs = []
        default_input = None

        # Collect input and select edges
        input_edges = {}  # index -> input_node
        select_edges_by_index = {}  # index -> select_node
        select_edges_no_index = []  # selects without input_index

        if self.debug:
            print(f"  DEBUG: Analyzing mux {mux_node.id} with {len(mux_node.incoming_edges)} incoming edges")

        for edge in mux_node.incoming_edges:
            edge_type = edge.data.get('type', '')

            if edge_type == 'mux_input':
                idx = edge.data.get('input_index', 0)
                input_edges[idx] = edge.source
            elif edge_type == 'mux_select':
                # MuxBuilder uses 'select_index', but older code might use 'input_index'
                # IMPORTANT: Use explicit None check, not 'or', because 0 is a valid index!
                select_idx = edge.data.get('select_index')
                idx = select_idx if select_idx is not None else edge.data.get('input_index')
                if idx is not None:
                    select_edges_by_index[idx] = edge.source
                else:
                    # No index - we'll have to match by order
                    select_edges_no_index.append(edge.source)
            elif edge_type == 'mux_default_input':
                default_input = edge.source

        # If selects don't have indices, match them by lexicographic order of source IDs
        # This is a heuristic - ideally selects should have input_index
        if select_edges_no_index and not select_edges_by_index:
            # Match selects to inputs by extracting instruction name
            for select_node in select_edges_no_index:
                # Select nodes are typically named <instr>_enable
                select_id = select_node.id
                if select_id.endswith('_enable'):
                    instr_name = select_id[:-7]  # Remove '_enable'
                    # Find the corresponding input by looking for nodes with this instruction prefix
                    for idx, input_node in input_edges.items():
                        if instr_name in input_node.id or input_node.id.startswith(instr_name):
                            select_edges_by_index[idx] = select_node
                            break

        # Pair up inputs with their selects
        for idx in sorted(input_edges.keys()):
            input_node = input_edges.get(idx)
            select_node = select_edges_by_index.get(idx)

            if input_node and select_node:
                inputs.append((input_node, select_node))
            elif input_node and not select_node:
                # Input without select - this is a bug in mux construction
                if self.debug:
                    print(f"    WARNING: Index {idx} has input but no select: {input_node.id}")
                    print(f"             This may indicate a bug in mux construction")

        # Add default input if it exists
        if default_input:
            inputs.append((default_input, None))

        if self.debug:
            print(f"  DEBUG: Found {len(input_edges)} inputs, {len(select_edges_by_index)} paired selects, default={'Yes' if default_input else 'No'}")

        return inputs

    def _extract_paths_from_input(self, input_node: Node, select_node: Optional[Node]) -> List[MuxPath]:
        """
        Extract all decision paths from a mux input.

        Args:
            input_node: The input value node
            select_node: The select condition node (None for default case)

        Returns:
            List of MuxPath objects
        """
        # Start with the select condition
        if select_node:
            base_condition = PathCondition(select_node.id, True)
            base_conditions = [base_condition]
        else:
            # Default case - no condition
            base_conditions = []

        # Recursively traverse the input node
        return self._traverse_node(input_node, base_conditions, "unknown")

    def _extract_paths_from_mux(self, mux_node_id: str, instruction: str) -> List[MuxPath]:
        """
        Recursively extract all (condition → value) paths from a mux node.

        Args:
            mux_node_id: The mux node to traverse
            instruction: The instruction this mux belongs to

        Returns:
            List of MuxPath objects representing all paths through this mux
        """
        mux_node = self.graph.nodes.get(mux_node_id)
        if not mux_node:
            return []

        # Get the instruction enable (e.g., 'beq_enable')
        enable_id = f"{instruction}_enable"

        # Start traversal with the instruction enable as the root condition
        base_condition = PathCondition(enable_id, True)

        # Find what this mux assigns (its value)
        # For gated write muxes, they typically have a single assignment source
        value_node = self._get_mux_value_source(mux_node)

        if not value_node:
            # No value source found, create a trivial path
            return [MuxPath([base_condition], mux_node_id, instruction)]

        # Recursively traverse the value node
        return self._traverse_node(value_node, [base_condition], instruction)

    def _get_mux_value_source(self, mux_node: Node) -> Optional[Node]:
        """Get the value source for a mux node (what it's assigned from)."""
        for edge in mux_node.incoming_edges:
            if edge.data.get('type') == 'assignment':
                return edge.source
        return None

    def _traverse_node(self, node: Node, path_conditions: List[PathCondition],
                      instruction: str) -> List[MuxPath]:
        """
        Recursively traverse a node to extract all paths.

        Args:
            node: Current node being traversed
            path_conditions: Accumulated conditions to reach this node
            instruction: Source instruction

        Returns:
            List of complete paths from this node
        """
        node_type = node.data.get('type', '')

        # If this is a ternary, we need to branch
        if node_type == 'ternary_op':
            return self._traverse_ternary(node, path_conditions, instruction)

        # If this is a mux_select, we need to branch based on select cases
        elif node_type == 'mux_select':
            return self._traverse_mux_select(node, path_conditions, instruction)

        # Otherwise, this is a leaf value
        else:
            return [MuxPath(path_conditions.copy(), node.id, instruction)]

    def _traverse_ternary(self, ternary_node: Node, path_conditions: List[PathCondition],
                         instruction: str) -> List[MuxPath]:
        """Traverse a ternary operator node (condition ? true_val : false_val)."""
        # Find condition, true_value, false_value
        condition_node = None
        true_node = None
        false_node = None

        for edge in ternary_node.incoming_edges:
            edge_type = edge.data.get('type', '')
            if edge_type == 'ternary_condition':
                condition_node = edge.source
            elif edge_type == 'ternary_true':
                true_node = edge.source
            elif edge_type == 'ternary_false':
                false_node = edge.source

        if self.debug and condition_node:
            cond_display = condition_node.data.get('display_name', condition_node.id)
            print(f"    DEBUG: Traversing ternary with condition: {cond_display} (id={condition_node.id})")

        paths = []

        # Traverse true branch (condition = true)
        if condition_node and true_node:
            true_conditions = path_conditions + [PathCondition(condition_node.id, True)]
            paths.extend(self._traverse_node(true_node, true_conditions, instruction))

        # Traverse false branch (condition = false)
        if condition_node and false_node:
            false_conditions = path_conditions + [PathCondition(condition_node.id, False)]
            paths.extend(self._traverse_node(false_node, false_conditions, instruction))

        return paths

    def _traverse_mux_select(self, mux_node: Node, path_conditions: List[PathCondition],
                            instruction: str) -> List[MuxPath]:
        """Traverse a mux_select node with multiple cases."""
        # TODO: Implement mux_select traversal if needed
        # For now, treat it as a leaf
        return [MuxPath(path_conditions.copy(), mux_node.id, instruction)]

    def _group_paths_by_value(self, paths: List[MuxPath]) -> Dict[str, ValueGroup]:
        """Group paths by their leaf value."""
        groups = {}

        for path in paths:
            value_id = path.value_node_id
            if value_id not in groups:
                groups[value_id] = ValueGroup(value_id, [])
            groups[value_id].paths.append(path)

        return groups

    def _rebuild_mux_with_merged_paths(self, mux_node: Node, value_groups: Dict[str, ValueGroup],
                                       original_inputs: List[Tuple[Node, Node]]):
        """
        Rebuild the multiplexer with merged common cases.

        Args:
            mux_node: The multiplexer node to rebuild
            value_groups: All value groups (including single-path ones)
            original_inputs: Original mux inputs before merging
        """
        print(f"  Rebuilding mux with {len(value_groups)} merged inputs (down from {len(original_inputs)}):")

        # Step 1: Remove all existing mux input/select/default edges
        edges_to_remove = []
        for edge in mux_node.incoming_edges:
            if edge.data.get('type') in ['mux_input', 'mux_select', 'mux_default_input']:
                edges_to_remove.append(edge)

        for edge in edges_to_remove:
            self.graph.remove_edge(edge.id)

        if self.debug:
            print(f"  Removed {len(edges_to_remove)} old mux edges")
            # Verify removal
            remaining_mux_edges = [e for e in mux_node.incoming_edges if e.data.get('type') in ['mux_input', 'mux_select', 'mux_default_input']]
            print(f"  After removal: {len(remaining_mux_edges)} mux edges remaining (should be 0)")

        # Step 2: Create MuxBuilder to properly reconstruct the mux
        # Use PRIORITY type since we're creating a priority-encoded mux
        builder = MuxBuilder(self.graph, mux_node.id, MuxType.PRIORITY)
        builder.mux_node = mux_node  # Reuse the existing node
        builder.num_inputs = 0  # Reset input count

        # Preserve original priority ordering from the flat mux builder.
        # value_groups dict insertion order matches the original mux input order
        # (first appearance of each value inherits the priority position).
        sorted_groups = list(value_groups.items())

        default_value = None

        for value_id, group in sorted_groups:
            value_node = self.graph.nodes.get(value_id)
            if not value_node:
                if self.debug:
                    print(f"    SKIPPED: {value_id} (node not found in graph)")
                continue

            display_name = value_node.data.get('display_name', value_id)

            if len(group.paths) > 1:
                # Check if any path is a default (no conditions)
                conditional_paths = [p for p in group.paths if p.conditions]
                default_paths = [p for p in group.paths if not p.conditions]

                if default_paths:
                    # This value has both conditional paths AND a default path
                    # Since the default is the "else" case, it already covers all the conditional paths
                    # We can just use the default and skip creating a separate input
                    if default_value is None:
                        default_value = value_node
                        if self.debug:
                            print(f"    [DEFAULT] {display_name} (merging {len(conditional_paths)} conditional paths into default)")
                        else:
                            print(f"    [DEFAULT] {display_name}")
                else:
                    # All paths are conditional - merge them with OR
                    condition_node = self._create_or_condition(group.paths, f"{mux_node.id}_or_{builder.num_inputs}")

                    if condition_node:
                        # Add as mux input with the OR condition as select
                        index = builder.add_input(value_node, condition_node)
                        if self.debug:
                            print(f"    [{index}] MERGED: {display_name} (id={value_id}) (from {len(group.paths)} paths)")
                        else:
                            print(f"    [{index}] MERGED: {display_name} (from {len(group.paths)} paths)")

            elif len(group.paths) == 1:
                path = group.paths[0]

                # Check if this is a default path (no conditions)
                if not path.conditions:
                    # This is the default case
                    if default_value is None:
                        default_value = value_node
                        print(f"    [DEFAULT] {display_name}")
                else:
                    # Single path - create AND condition for the path
                    condition_node = self._create_and_condition(path.conditions,
                                                               f"{mux_node.id}_and_{builder.num_inputs}")

                    if condition_node:
                        index = builder.add_input(value_node, condition_node)
                        if self.debug:
                            print(f"    [{index}] DIRECT: {display_name} (id={value_id})")
                        else:
                            print(f"    [{index}] DIRECT: {display_name}")

        # Add default if we found one
        if default_value:
            builder.add_default_input(default_value)

        print(f"  Mux rebuilt: {builder.num_inputs} inputs + {'1 default' if default_value else 'no default'}")

        # Debug: verify the mux structure
        if self.debug:
            mux_input_count = len([e for e in mux_node.incoming_edges if e.data.get('type') == 'mux_input'])
            mux_select_count = len([e for e in mux_node.incoming_edges if e.data.get('type') == 'mux_select'])
            print(f"  Verification: {mux_input_count} mux_input edges, {mux_select_count} mux_select edges")

    def _create_or_condition(self, paths: List[MuxPath], node_id: str) -> Optional[Node]:
        """Create an OR node combining all path conditions."""
        if not paths:
            return None

        # Convert each path to an AND of its conditions
        and_nodes = []
        for i, path in enumerate(paths):
            if path.conditions:
                and_node = self._create_and_condition(path.conditions, f"{node_id}_path_{i}")
                if and_node:
                    and_nodes.append(and_node)

        if not and_nodes:
            return None

        # If only one AND node, return it directly
        if len(and_nodes) == 1:
            return and_nodes[0]

        # Create single multi-input OR node for all AND nodes
        or_node = Node(node_id, {
            'type': 'logical_or',
            'operation': '||',
            'display_name': ' || '.join(n.data.get('display_name', n.id) for n in and_nodes)
        })
        self.graph.add_node(or_node)

        # Add all operands as edges
        for i, and_node in enumerate(and_nodes):
            edge = Edge(and_node, or_node, data={'type': 'operand', 'operand_index': i})
            self.graph.add_edge(edge)

        return or_node

    def _create_and_condition(self, conditions: List[PathCondition], node_id: str) -> Optional[Node]:
        """Create an AND node combining all path conditions."""
        if not conditions:
            return None

        # Get condition nodes and apply polarity (negate if needed)
        cond_nodes = []
        for cond in conditions:
            cond_node = self.graph.nodes.get(cond.enable_node_id)
            if not cond_node:
                continue

            if cond.polarity:
                # Use as-is
                cond_nodes.append(cond_node)
            else:
                # Need to negate - create NOT node
                not_id = f"!{cond.enable_node_id}"
                if not_id not in self.graph.nodes:
                    not_node = Node(not_id, {
                        'type': 'logical_not',
                        'operation': '!',
                        'display_name': f"!{cond_node.data.get('display_name', cond_node.id)}"
                    })
                    self.graph.add_node(not_node)

                    # Add operand edge
                    edge = Edge(cond_node, not_node, data={'type': 'operand', 'operand_index': 0})
                    self.graph.add_edge(edge)
                else:
                    not_node = self.graph.nodes[not_id]

                cond_nodes.append(not_node)

        if not cond_nodes:
            return None

        # If only one condition, return it directly
        if len(cond_nodes) == 1:
            return cond_nodes[0]

        # Create single multi-input AND node
        and_node = Node(node_id, {
            'type': 'logical_and',
            'operation': '&&',
            'display_name': ' && '.join(n.data.get('display_name', n.id) for n in cond_nodes)
        })
        self.graph.add_node(and_node)

        # Add all operands as edges
        for i, cond_node in enumerate(cond_nodes):
            edge = Edge(cond_node, and_node, data={'type': 'operand', 'operand_index': i})
            self.graph.add_edge(edge)

        return and_node


    def _report_merging_opportunities(self, mergeable_groups: Dict[str, ValueGroup]):
        """Report what merging opportunities were found."""
        print(f"\n  === Merging Opportunities ===")

        for value_id, group in sorted(mergeable_groups.items(),
                                     key=lambda x: len(x[1].paths),
                                     reverse=True):
            value_node = self.graph.nodes.get(value_id)
            display_name = value_node.data.get('display_name', value_id) if value_node else value_id

            print(f"\n  Value: {display_name} ({len(group.paths)} paths)")

            for i, path in enumerate(group.paths[:5]):  # Show first 5 paths
                cond_expr = path.to_condition_expr(self.graph)
                print(f"    Path {i+1}: {cond_expr}")

            if len(group.paths) > 5:
                print(f"    ... and {len(group.paths) - 5} more paths")

            # Show merged condition
            merged_cond = group.get_merged_condition(self.graph)
            if len(merged_cond) < 200:  # Only show if not too long
                print(f"  Merged condition: {merged_cond}")


def deduplicate_all_arch_state_muxes(graph: ResourceGraph) -> bool:
    """
    Deduplicate muxes for all architectural state write nodes in the graph.

    Args:
        graph: The merged ResourceGraph

    Returns:
        True if any deduplication was performed
    """
    deduplicator = MuxDeduplicator(graph)

    # Find all architectural state write nodes
    # Look for nodes ending in _wr that are likely arch state (pc_wr, rf_wr, etc.)
    arch_state_wr_nodes = []
    wr_nodes_debug = []
    for node_id, node in graph.nodes.items():
        if node_id.endswith('_wr'):
            wr_nodes_debug.append(node_id)
            # Check if it has an incoming multiplexer
            has_mux = any(
                e.source.data.get('type') == 'multiplexer'
                for e in node.incoming_edges
                if e.data.get('type') == 'assignment'
            )
            if has_mux:
                arch_state_wr_nodes.append(node_id)

    if wr_nodes_debug:
        print(f"  Found _wr nodes in graph: {wr_nodes_debug}")

    if not arch_state_wr_nodes:
        print("No architectural state write nodes with multiplexers found for deduplication")
        return False

    print(f"Found {len(arch_state_wr_nodes)} architectural state write nodes: {arch_state_wr_nodes}")

    any_deduped = False
    for wr_node_id in arch_state_wr_nodes:
        if deduplicator.deduplicate_arch_state_muxes(wr_node_id):
            any_deduped = True

    return any_deduped
