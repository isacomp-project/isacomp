"""
Graph optimization passes for ResourceGraphs.

This module contains optimization transformations that can be applied
to both single ResourceGraphs and merged graphs.
"""

from typing import Dict, List, Set, Optional
from core.resource_graph import ResourceGraph, Node, Edge


class GraphOptimizer:
    """Applies optimization transformations to ResourceGraphs."""

    def __init__(self, graph: ResourceGraph):
        self.graph = graph

    def optimize(self, enable_all: bool = True,
                 propagate_aliases: bool = True,
                 merge_nested_muxes: bool = True,
                 split_arch_state: bool = True) -> None:
        """
        Apply optimization passes to the graph.

        Args:
            enable_all: If True, enables all optimizations
            propagate_aliases: Propagate wire aliases to simplify graph
            merge_nested_muxes: Flatten nested muxes/ternary operators
            split_arch_state: Split arch state nodes into read/write
        """
        if enable_all or propagate_aliases:
            self.propagate_wire_aliases()

        if enable_all or merge_nested_muxes:
            self.merge_nested_muxes()

        if enable_all or split_arch_state:
            self.split_arch_state_read_write()

        # Re-infer timing after optimizations
        self.graph.infer_uarch_time()

    def propagate_wire_aliases(self) -> None:
        """
        Propagate wire aliases to simplify the graph.

        If a variable node (wire) has a single incoming assignment from an operation
        and no other writes, then all reads from that wire can be replaced with direct
        reads from the source operation. This eliminates redundant intermediate wires.

        Example: If we have:
            pc_plus_4 = (pc + 4)
            result = res ? branch_dest : pc_plus_4

        And pc_plus_4 is only used in that one place, we can replace it with:
            result = res ? branch_dest : (pc + 4)
        """
        print("Propagating wire aliases...")

        # Find wire aliases: var nodes with single assignment from operation/ternary/bit_slice
        wire_aliases = {}  # wire_node_id -> source_node

        for node_id, node in self.graph.nodes.items():
            node_type = node.data.get('type', '')

            # Only consider variable nodes (wires)
            if node_type != 'var':
                continue

            # Must have exactly one incoming assignment
            incoming_assigns = [e for e in node.incoming_edges
                               if e.data.get('type') == 'assignment']

            if len(incoming_assigns) != 1:
                continue

            source_node = incoming_assigns[0].source
            source_type = source_node.data.get('type', '')

            # Don't propagate if the source is arch state (preserves read/write distinction)
            if source_node.is_arch_state:
                continue

            # Only propagate wires that are transparent aliases to already-shared operations
            # This preserves user-defined names that have semantic meaning
            # Check if source is an operation that's already shared (used >1 time)
            source_uses = len([e for e in source_node.outgoing_edges])

            is_shared_operation = (
                source_type in ['operation', 'ternary_op', 'bit_slice', 'concatenation', 'repetition'] and
                source_uses > 1  # Source is used by multiple things (shared across instructions)
            )

            # ONLY propagate if it's a transparent alias to a shared operation
            # This preserves user-defined names that have semantic meaning
            if is_shared_operation:
                wire_aliases[node_id] = source_node
                print(f"  Found wire alias: {node_id} = {source_node.id} (transparent alias to shared operation)")

        if not wire_aliases:
            print("  No wire aliases found")
            return

        # Replace all uses of wire aliases with direct connections to source
        replacements_made = 0

        for wire_id, source_node in wire_aliases.items():
            wire_node = self.graph.nodes[wire_id]

            # Find all non-assignment edges from the wire (these are reads)
            outgoing_edges = list(wire_node.outgoing_edges)

            for edge in outgoing_edges:
                edge_type = edge.data.get('type', '')

                # Skip assignment edges (we'll remove these later)
                if edge_type == 'assignment':
                    continue

                # Create new edge directly from source to target
                target_node = edge.target
                new_edge_data = edge.data.copy()
                new_edge = Edge(source_node, target_node, data=new_edge_data)
                self.graph.add_edge(new_edge)

                # Remove old edge from wire to target
                self.graph.remove_edge(edge.id)

                replacements_made += 1
                print(f"    Replaced: {wire_id} -> {target_node.id} with {source_node.id} -> {target_node.id}")

        # Remove the wire alias nodes if they're now unused
        for wire_id in wire_aliases:
            wire_node = self.graph.nodes[wire_id]

            # Check if wire still has any non-assignment outgoing edges
            non_assign_edges = [e for e in wire_node.outgoing_edges
                               if e.data.get('type') != 'assignment']

            if not non_assign_edges:
                # Wire is no longer used, remove it and its incoming assignment
                for edge in list(wire_node.incoming_edges):
                    self.graph.remove_edge(edge.id)
                self.graph.remove_node(wire_id)
                print(f"    Removed unused wire: {wire_id}")

        print(f"Wire alias propagation complete: {replacements_made} replacements made")

    def eliminate_passthrough_variables(self) -> None:
        """
        Eliminate pass-through variables by renaming the source expression node.

        If a variable node has a single incoming assignment from an expression node,
        and is only used as an intermediate value (not as architectural state),
        we rename the expression node to use the variable's name and eliminate the variable.

        Example:
            concatenation {{19{imm[12]_rd}}, imm} -> var sign_ext_imm -> var branch_offset
        Becomes:
            concatenation sign_ext_imm ({{19{imm[12]_rd}}, imm}) -> var branch_offset
        """
        print("Eliminating pass-through variables...")

        eliminated = 0

        for node_id, node in list(self.graph.nodes.items()):
            node_type = node.data.get('type', '')

            # Only consider variable nodes
            if node_type != 'var':
                continue

            # Skip architectural state
            if node.is_arch_state:
                continue

            # Must have exactly one incoming assignment
            incoming_assigns = [e for e in node.incoming_edges
                               if e.data.get('type') == 'assignment']

            if len(incoming_assigns) != 1:
                continue

            source_node = incoming_assigns[0].source
            source_type = source_node.data.get('type', '')

            # Source must be an expression (operation, concatenation, etc.)
            if source_type not in ['operation', 'concatenation', 'repetition',
                                  'sign_extend', 'zero_extend', 'ternary_op', 'bit_slice']:
                continue

            # Source should only be used by this variable (single assignment)
            source_outgoing = list(source_node.outgoing_edges)
            if len(source_outgoing) != 1:
                continue

            # Rename the source expression node to use the variable's name
            var_name = node.data.get('name', node_id)
            source_display = source_node.data.get('display_name', source_node.id)
            print(f"  Renaming {source_display} to {var_name}, eliminating var {node_id}")
            print(f"    Source has {len(source_node.outgoing_edges)} outgoing, var has {len([e for e in node.outgoing_edges if e.data.get('type') != 'assignment'])} non-assign outgoing")

            # First, remove the variable node and the assignment edge
            # This must be done BEFORE renaming to avoid name conflicts
            self.graph.remove_edge(incoming_assigns[0].id)

            # Redirect all outgoing edges from the var to come from the source
            for edge in list(node.outgoing_edges):
                if edge.data.get('type') == 'assignment':
                    continue  # Skip if var assigns to something else

                # Create new edge from source to target
                target_node = edge.target
                new_edge_data = edge.data.copy()
                new_edge = Edge(source_node, target_node, data=new_edge_data)
                self.graph.add_edge(new_edge)

                # Remove old edge
                self.graph.remove_edge(edge.id)

            # Now remove the variable node
            self.graph.remove_node(node_id)

            # Now it's safe to rename the source node
            old_source_id = source_node.id
            del self.graph.nodes[old_source_id]
            source_node.id = var_name
            source_node.data['name'] = var_name
            self.graph.nodes[var_name] = source_node

            # Update all edge IDs that reference the renamed node
            for edge in list(source_node.incoming_edges) + list(source_node.outgoing_edges):
                # Edge IDs use format "source_id->target_id"
                old_edge_id = edge.id
                # Rebuild edge ID
                new_edge_id = f"{edge.source.id}->{edge.target.id}"
                if old_edge_id in self.graph.edges:
                    del self.graph.edges[old_edge_id]
                edge.id = new_edge_id
                self.graph.edges[new_edge_id] = edge

            eliminated += 1

        print(f"Eliminated {eliminated} pass-through variables")

    def merge_nested_muxes(self) -> None:
        """
        Merge nested muxes to eliminate redundancy.

        Pattern: If a mux has an input that is a ternary operator or another mux,
        and that nested selection shares common values with other inputs, we can
        flatten the structure.

        Example:
            pc_mux selects between:
                Input 0 [shared]: (pc + 4)
                Input 1 [beq]: (res ? branch_dest : (pc + 4))

            This can be flattened to:
            pc_mux selects between:
                Input 0 [add_enable || (beq_enable && !res)]: (pc + 4)
                Input 1 [beq_enable && res]: branch_dest
        """
        print("Checking for nested mux patterns to merge...")

        # Find all multiplexer nodes
        mux_nodes = [node for node in self.graph.nodes.values()
                    if node.data.get('type') == 'multiplexer']

        merges_made = 0

        for mux_node in mux_nodes:
            # Get mux inputs
            mux_inputs = []
            for edge in mux_node.incoming_edges:
                if edge.data.get('type') == 'mux_input':
                    mux_inputs.append({
                        'edge': edge,
                        'source': edge.source,
                        'instruction': edge.data.get('source_instruction', 'unknown'),
                        'index': edge.data.get('input_index', 0)
                    })

            # Sort by index to maintain order
            mux_inputs.sort(key=lambda x: x['index'])

            # Check each input to see if it's a ternary operator
            for mux_input in mux_inputs:
                source = mux_input['source']

                if source.data.get('type') != 'ternary_op':
                    continue

                # Found a ternary input! Check if we can merge it
                # Get the ternary's inputs
                ternary_condition = None
                ternary_true = None
                ternary_false = None

                for edge in source.incoming_edges:
                    edge_type = edge.data.get('type', '')
                    if edge_type == 'ternary_condition':
                        ternary_condition = edge.source
                    elif edge_type == 'ternary_true':
                        ternary_true = edge.source
                    elif edge_type == 'ternary_false':
                        ternary_false = edge.source

                if not all([ternary_condition, ternary_true, ternary_false]):
                    continue

                # Check if the ternary's false value matches another mux input
                # (This is the common case: shared value for "default" behavior)
                shared_value = None
                shared_input = None

                for other_input in mux_inputs:
                    if other_input['source'].id == ternary_false.id:
                        shared_value = ternary_false
                        shared_input = other_input
                        break

                if shared_value and shared_input:
                    # We can merge! The ternary's true branch becomes a direct mux input
                    print(f"  Merging nested ternary in {mux_node.id}:")
                    print(f"    Ternary false branch ({ternary_false.id}) matches other input")
                    print(f"    Promoting ternary true branch ({ternary_true.id}) to direct mux input")

                    # Replace the ternary input with the true branch
                    # Remove old edge from ternary to mux
                    self.graph.remove_edge(mux_input['edge'].id)

                    # Add new edge from ternary_true to mux
                    # Use the condition from the ternary as part of the select logic
                    instruction = mux_input['instruction']
                    new_edge_data = {
                        'type': 'mux_input',
                        'input_index': mux_input['index'],
                        'source_instruction': instruction,
                        'condition': ternary_condition.id,
                        'metadata': 'merged_from_ternary'
                    }
                    new_edge = Edge(ternary_true, mux_node, data=new_edge_data)
                    self.graph.add_edge(new_edge)

                    # The ternary node might now be unused - check and remove if so
                    if not source.outgoing_edges:
                        # Remove edges to the ternary
                        for edge in list(source.incoming_edges):
                            self.graph.remove_edge(edge.id)
                        self.graph.remove_node(source.id)
                        print(f"    Removed unused ternary node: {source.id}")

                    merges_made += 1

        if merges_made > 0:
            print(f"Nested mux merging complete: {merges_made} merge(s) performed")
        else:
            print("  No nested mux patterns found to merge")

    def split_arch_state_read_write(self) -> None:
        """
        Split architectural state nodes that are both read and written into separate nodes.

        For nodes like 'pc' that have both:
        - Incoming assignment edges (writes)
        - Outgoing read edges (operand, array_index, etc.)

        We split them into:
        - 'pc_rd' - for reads (used as operands, etc.)
        - 'pc_wr' - for writes (receives assignments)

        This is essential for proper timing in pipelined graphs, where the write happens
        in a later cycle than the read.
        """
        print("Splitting architectural state read/write nodes...")

        # Only split nodes that are truly ISA state (marked by ISA parser)
        # Do NOT mark nodes as is_arch_state just because they have _rd or _wr in the name
        # (e.g., imm[11]_rd is a bit slice, not ISA state; add_rf_write_enable is a signal, not ISA state)

        nodes_to_split = []

        # Find nodes that need splitting: nodes with both reads and writes
        for node_id, node in list(self.graph.nodes.items()):
            # Look for nodes that are architectural state or behave like it
            # (e.g., 'pc' which is an implicit arch state even if not marked)

            has_write = any(e.data.get('type') == 'assignment' for e in node.incoming_edges)

            # A "read" is when the node is used as:
            # 1. An operand in an operation
            # 2. An array index
            # 3. A bit access
            # 4. A source in a blocking assignment (combinational read, e.g., npc = pc + 4)
            # 5. A ternary operand (condition, true branch, or false branch)
            # 6. A mux input or select
            read_edge_types = ['operand', 'left_operand', 'right_operand', 'array_index', 'bit_access',
                               'mux_input', 'mux_default_input', 'mux_select',
                               'ternary_condition', 'ternary_true', 'ternary_false']
            has_read = any(e.data.get('type') in read_edge_types or
                          (e.data.get('type') == 'assignment' and e.data.get('assign_type') == 'blocking')
                          for e in node.outgoing_edges)

            # Skip if already has _rd or _wr suffix (already split)
            if '_rd' in node_id or '_wr' in node_id:
                continue

            # Skip memory arrays - they're accessed via indexing, not split into copies
            if node.data.get('array_depth') or node.data.get('is_memory'):
                continue

            # Always split scalar arch state nodes for consistency during merging
            # Some instructions may only read, others only write - merger handles this
            if node.is_arch_state or node_id == 'pc' or node_id in ['imem', 'dmem', 'rf']:
                nodes_to_split.append(node)
                print(f"  Will split: {node_id} (has {len([e for e in node.incoming_edges if e.data.get('type')=='assignment'])} writes, {len([e for e in node.outgoing_edges if e.data.get('type') in ['operand','array_index','bit_access','assignment']])} reads)")

        if not nodes_to_split:
            print("  No nodes need splitting")
            return

        splits_made = 0

        for original_node in nodes_to_split:
            node_id = original_node.id

            # Create _rd node (for reads)
            # Mark as architectural state since it's reading from arch state
            rd_node_id = f"{node_id}_rd"
            rd_node_data = original_node.data.copy() if original_node.data else {}
            # Keep the original name in the data for display purposes
            if 'name' not in rd_node_data:
                rd_node_data['name'] = node_id
            rd_node = Node(
                rd_node_id,
                rd_node_data,
                is_arch_state=True,  # Always mark as arch state
                is_uarch_state=original_node.is_uarch_state,
                uarch_time=original_node.uarch_time if original_node.uarch_time is not None else 0
            )
            self.graph.add_node(rd_node)

            # Create _wr node (for writes)
            # Mark as architectural state since it's writing to arch state
            # uarch_time will be computed from incoming assignment edges
            wr_node_id = f"{node_id}_wr"
            wr_node_data = original_node.data.copy() if original_node.data else {}
            # Keep the original name in the data for display purposes
            if 'name' not in wr_node_data:
                wr_node_data['name'] = node_id
            wr_node = Node(
                wr_node_id,
                wr_node_data,
                is_arch_state=True,  # Always mark as arch state
                is_uarch_state=original_node.is_uarch_state,
                uarch_time=None  # Will be computed from incoming edges
            )
            self.graph.add_node(wr_node)

            # Redirect incoming assignment edges to _wr node
            # Track the maximum uarch_time from source nodes
            max_source_time = 0
            for edge in list(original_node.incoming_edges):
                if edge.data.get('type') == 'assignment':
                    new_edge = Edge(edge.source, wr_node, data=edge.data.copy())
                    self.graph.add_edge(new_edge)
                    self.graph.remove_edge(edge.id)
                    # Track timing
                    if edge.source.uarch_time is not None:
                        max_source_time = max(max_source_time, edge.source.uarch_time)

            # Set write node's uarch_time based on its sources
            # The write happens after all sources have computed their values
            wr_node.uarch_time = max_source_time

            # Redirect outgoing read edges to come from _rd node
            # This includes:
            # 1. Operands, array indices, bit accesses (explicit reads)
            # 2. Blocking assignments (combinational reads, like npc = pc + 4)
            # 3. Mux inputs (conditional expressions using the state)
            # 4. Ternary operator inputs (condition, true, false branches)
            # 5. Regular assignments where this node is the RHS (ret_addr = pc)
            for edge in list(original_node.outgoing_edges):
                edge_type = edge.data.get('type', '')
                assign_type = edge.data.get('assign_type', '')
                if (edge_type in ['operand', 'left_operand', 'right_operand', 'array_index', 'bit_access',
                                  'mux_input', 'mux_default_input', 'mux_select',
                                  'ternary_condition', 'ternary_true', 'ternary_false',
                                  'assignment'] or
                    (edge_type == 'assignment' and assign_type == 'blocking')):
                    new_edge = Edge(rd_node, edge.target, data=edge.data.copy())
                    self.graph.add_edge(new_edge)
                    self.graph.remove_edge(edge.id)

            # Add forwarding edge: _wr -> _rd (write value becomes next read value)
            # This edge represents the architectural state update
            forward_edge = Edge(wr_node, rd_node, data={
                'type': 'state_update',
                'description': f'{node_id} write forwarding to next read'
            })
            self.graph.add_edge(forward_edge)

            # Keep array base nodes (like regfile), but remove scalar nodes (like pc)
            # Check if this is an array by looking at the data type
            is_array = (original_node.data.get('type') == 'memory' or
                       'array' in str(original_node.data.get('type', '')).lower() or
                       node_id in ['regfile', 'rf', 'mem', 'imem', 'dmem'])

            if is_array:
                # Keep the base array node and add edges to _rd and _wr
                base_to_rd = Edge(original_node, rd_node, data={
                    'type': 'state_read',
                    'description': f'Read port from {node_id}'
                })
                self.graph.add_edge(base_to_rd)

                base_to_wr = Edge(original_node, wr_node, data={
                    'type': 'state_write',
                    'description': f'Write port to {node_id}'
                })
                self.graph.add_edge(base_to_wr)
                print(f"    Split array {node_id} -> {rd_node_id} + {wr_node_id} (keeping base)")
            else:
                # Remove scalar base node if it has no more edges
                if not original_node.incoming_edges and not original_node.outgoing_edges:
                    self.graph.remove_node(node_id)
                    print(f"    Split {node_id} -> {rd_node_id} (read, cycle={rd_node.uarch_time}) + {wr_node_id} (write, cycle={wr_node.uarch_time})")
                else:
                    print(f"    WARNING: {node_id} still has edges after split attempt")

            splits_made += 1

        print(f"Architectural state splitting complete: {splits_made} node(s) split")

        # Also split array accesses for ISA state arrays (like regfile[index])
        array_splits = self._split_array_accesses()
        print(f"Array access splitting complete: {array_splits} node(s) split")

        # Re-run uarch_time inference to ensure proper timing for all nodes
        if splits_made > 0 or array_splits > 0:
            print("Re-inferring uarch_time after architectural state splitting...")
            self.graph.infer_uarch_time()

    def _split_array_accesses(self) -> int:
        """
        Split array access nodes for ISA state arrays into _rd and _wr versions.

        For array accesses like regfile[index]:
        - regfile[index] with reads becomes regfile[index]_rd
        - regfile[index] with writes becomes regfile[index]_wr
        - Both get an edge from the base array node
        """
        splits_made = 0

        # Find all array access nodes for ISA state arrays
        array_accesses = []
        for node_id, node in list(self.graph.nodes.items()):
            # Look for array access patterns: base[index]
            if '[' in node_id and ']' in node_id:
                # Extract base name
                base_name = node_id.split('[')[0]

                # Check if base is ISA state
                if base_name in self.graph.nodes:
                    base_node = self.graph.nodes[base_name]
                    if base_node.is_arch_state or base_node.data.get('type') == 'isa_state':
                        array_accesses.append((node, base_name))

        for access_node, base_name in array_accesses:
            node_id = access_node.id

            # Skip if already split or if it's a mux node (ends with _mux)
            if node_id.endswith('_rd') or node_id.endswith('_wr') or node_id.endswith('_mux'):
                continue

            # Skip zero-extend nodes - they're derived signals, not array accesses
            # (e.g., rf[rm]_rd_zext is a zero-extend of rf[rm]_rd, not an array access)
            if '_zext' in node_id:
                continue

            # Determine if this is a read or write
            has_write = any(e.data.get('type') == 'assignment' for e in access_node.incoming_edges)
            has_read = any(e.data.get('type') in ['operand', 'assignment', 'mux_input'] for e in access_node.outgoing_edges)

            if has_write:
                # Create _wr version
                wr_node_id = f"{node_id}_wr"
                wr_data = access_node.data.copy() if access_node.data else {}
                wr_node = Node(wr_node_id, wr_data, is_arch_state=True)
                self.graph.add_node(wr_node)

                # Copy over array_index and array_base edges from original node
                for edge in list(access_node.incoming_edges):
                    if edge.data.get('type') in ['array_index', 'array_base']:
                        new_edge = Edge(edge.source, wr_node, data=edge.data.copy())
                        self.graph.add_edge(new_edge)

                # Redirect incoming assignment edges
                for edge in list(access_node.incoming_edges):
                    if edge.data.get('type') == 'assignment':
                        new_edge = Edge(edge.source, wr_node, data=edge.data.copy())
                        self.graph.add_edge(new_edge)
                        self.graph.remove_edge(edge.id)

                splits_made += 1
                print(f"    Split array write: {node_id} -> {wr_node_id}")

            if has_read:
                # Create _rd version
                rd_node_id = f"{node_id}_rd"
                rd_data = access_node.data.copy() if access_node.data else {}
                rd_node = Node(rd_node_id, rd_data, is_arch_state=True)
                self.graph.add_node(rd_node)

                # Copy over array_index, array_base, and bit_access edges from original node
                # (bit_access is needed for bit_slice nodes like S[7:7])
                for edge in list(access_node.incoming_edges):
                    if edge.data.get('type') in ['array_index', 'array_base', 'bit_access']:
                        new_edge = Edge(edge.source, rd_node, data=edge.data.copy())
                        self.graph.add_edge(new_edge)

                # Redirect outgoing edges
                for edge in list(access_node.outgoing_edges):
                    new_edge = Edge(rd_node, edge.target, data=edge.data.copy())
                    self.graph.add_edge(new_edge)
                    self.graph.remove_edge(edge.id)

                splits_made += 1
                print(f"    Split array read: {node_id} -> {rd_node_id}")

            # Remove original access node if it has no more edges
            if not access_node.incoming_edges and not access_node.outgoing_edges:
                self.graph.remove_node(node_id)

        return splits_made

    def cleanup_bypassed_edges(self) -> None:
        """Cleanup to remove any direct assignment edges that bypass multiplexers."""

        # Find all multiplexer nodes
        mux_nodes = [node for node in self.graph.nodes.values()
                    if node.data.get('type') == 'multiplexer']

        if not mux_nodes:
            return

        print(f"Cleanup: checking {len(mux_nodes)} multiplexers for bypassed edges")

        for mux_node in mux_nodes:
            # Find what this multiplexer outputs to
            mux_targets = [edge.target for edge in mux_node.outgoing_edges
                          if edge.data.get('type') == 'assignment']

            # Find what feeds into this multiplexer
            mux_sources = [edge.source for edge in mux_node.incoming_edges
                          if edge.data.get('type') == 'mux_input']

            # Remove any direct edges from mux sources to mux targets
            edges_to_remove = []
            for source in mux_sources:
                for target in mux_targets:
                    for edge in source.outgoing_edges:
                        if (edge.target == target and
                            edge.data.get('type') == 'assignment'):
                            edges_to_remove.append(edge)

            for edge in edges_to_remove:
                print(f"Cleanup: removing bypassed edge {edge.source.id} -> {edge.target.id}")
                self.graph.remove_edge(edge.id)
