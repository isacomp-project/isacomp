#!/usr/bin/env python3
"""
Dual-Issue Superscalar Pipeline Merger.

This module merges two independently-pipelined graphs into a dual-issue processor.
The key innovation is the dual_issue_time concept which provides unified ordering
for hazard detection across both pipelines.

P1 only executes instructions in its supported subset. When P1's instruction is
ineligible, P1 idles and PC advances by one instruction.

See DUAL_ISSUE_PLAN.md for detailed design documentation.
"""

from typing import Dict, List, Optional, Set, Tuple
from core.resource_graph import ResourceGraph, Node, Edge
from core.array_access_utils import ArrayAccessAnalyzer


class DualIssuePipelineMerger:
    """
    Merges two independently-pipelined graphs into a dual-issue processor.

    Input:
    - p0_graph: Pipelined graph for p0's instruction set (primary pipeline)
    - p1_graph: Pipelined graph for p1's instruction set (secondary pipeline)

    Both graphs must be pipelined with the same stage structure but NOT
    yet hazard-resolved.

    Output:
    - Merged graph with:
      - All nodes prefixed (p0_, p1_)
      - pipe_id set on each node (0 for p0, 1 for p1, None for shared)
      - Shared state (RF, PC, memories) connected
      - p1's PC source replaced with p0_pc + 4
      - Eligibility detection added
      - dual_issue_time inferred
      - Ready for hazard resolution
    """

    def __init__(self, p0_graph: ResourceGraph, p1_graph: ResourceGraph):
        """
        Initialize the merger.

        Args:
            p0_graph: Pipelined graph for p0 (primary pipeline, full instruction set)
            p1_graph: Pipelined graph for p1 (secondary pipeline, subset of instructions)
        """
        self.p0_graph = p0_graph
        self.p1_graph = p1_graph
        self.shared_memories: Set[str] = set()  # Memory names that are shared

    def merge(self, p0_pc_name: str = 'pc_rd', p1_pc_name: str = 'pc_rd',
              shared_state_names: Optional[List[str]] = None) -> ResourceGraph:
        """
        Merge the two pipelined graphs into a dual-issue processor.

        Args:
            p0_pc_name: Name of PC read signal in p0 (e.g., 'pc_rd')
            p1_pc_name: Name of PC read signal in p1 (e.g., 'pc_rd')
            shared_state_names: List of shared state node names (e.g., ['rf', 'pc', 'imem', 'dmem'])
                               If None, auto-detects ISA state and memories.

        Returns:
            Merged ResourceGraph ready for hazard resolution
        """
        print("=" * 70)
        print("DUAL-ISSUE PIPELINE MERGER")
        print("=" * 70)

        merged = ResourceGraph()

        # Step 1: Copy p0 nodes with prefix and pipe_id=0
        print("\nStep 1: Copying p0 graph with prefix 'p0_'...")
        node_mapping_p0 = self._copy_with_prefix(self.p0_graph, merged, "p0_", pipe_id=0)
        print(f"  Copied {len(node_mapping_p0)} nodes from p0")

        # Step 2: Copy p1 nodes with prefix and pipe_id=1
        print("\nStep 2: Copying p1 graph with prefix 'p1_'...")
        node_mapping_p1 = self._copy_with_prefix(self.p1_graph, merged, "p1_", pipe_id=1)
        print(f"  Copied {len(node_mapping_p1)} nodes from p1")

        # Step 3: Identify and create shared state
        print("\nStep 3: Creating shared state...")
        if shared_state_names is None:
            shared_state_names = self._auto_detect_shared_state()
        shared_nodes = self._create_shared_state(merged, shared_state_names)
        print(f"  Created {len(shared_nodes)} shared state nodes")

        # Step 4: Connect p0's state accesses to shared state
        print("\nStep 4: Connecting p0 to shared state...")
        p0_connections = self._connect_to_shared_state(merged, "p0_", shared_state_names)
        print(f"  Connected {p0_connections} p0 access points to shared state")

        # Step 5: Connect p1's state accesses to shared state
        print("\nStep 5: Connecting p1 to shared state...")
        p1_connections = self._connect_to_shared_state(merged, "p1_", shared_state_names)
        print(f"  Connected {p1_connections} p1 access points to shared state")

        # Step 6: Replace p1's PC source with p0_pc + 4
        print("\nStep 6: Replacing p1 PC source with p0_pc + 4...")
        self._replace_p1_pc_source(merged, p0_pc_name, p1_pc_name)

        # Step 7: Add eligibility detection for p1
        print("\nStep 7: Adding p1 eligibility detection...")
        self._add_eligibility_detection(merged)

        # Step 8: Add PC advancement logic (0/4/8)
        # Note: This is called AFTER hazard resolution adds stall controllers
        # For now, we just create placeholder signals that will be connected later
        print("\nStep 8: Creating PC advancement infrastructure...")
        self._add_pc_advancement_infrastructure(merged)

        # Step 9: Infer timing
        print("\nStep 9: Inferring timing...")
        merged.infer_pipe_time(force_reinfer=False)  # Preserve existing values
        merged.infer_dual_issue_time(force_reinfer=True)

        print("\n" + "=" * 70)
        print("DUAL-ISSUE MERGER COMPLETE")
        print(f"  Total nodes: {len(merged.nodes)}")
        print(f"  Total edges: {len(merged.edges)}")
        print("=" * 70)

        return merged

    def _copy_with_prefix(self, source_graph: ResourceGraph, target_graph: ResourceGraph,
                          prefix: str, pipe_id: int) -> Dict[str, str]:
        """
        Copy all nodes and edges from source to target with a prefix.

        Args:
            source_graph: Source graph to copy from
            target_graph: Target graph to copy to
            prefix: Prefix to add to all node IDs (e.g., 'p0_', 'p1_')
            pipe_id: Pipeline ID to set on all copied nodes

        Returns:
            Mapping from old node IDs to new (prefixed) node IDs
        """
        node_mapping = {}  # old_id -> new_id

        # Copy nodes with prefix
        for old_id, old_node in source_graph.nodes.items():
            new_id = f"{prefix}{old_id}"
            node_mapping[old_id] = new_id

            # Copy node data and prefix relevant fields
            new_data = old_node.data.copy() if old_node.data else {}
            if 'name' in new_data:
                new_data['name'] = f"{prefix}{new_data['name']}"
            # Prefix combined_write_enable for memory write ports
            if 'combined_write_enable' in new_data:
                new_data['combined_write_enable'] = f"{prefix}{new_data['combined_write_enable']}"

            # Create new node with same data but new ID
            new_node = Node(
                node_id=new_id,
                data=new_data,
                is_arch_state=old_node.is_arch_state,
                used_as_index=old_node.used_as_index,
                indexed_by=old_node.indexed_by,  # Temporary, will fix in second pass
                is_uarch_state=old_node.is_uarch_state,
                uarch_time=old_node.uarch_time,
                pipe_time=old_node.pipe_time,
                from_isa_spec=old_node.from_isa_spec,
                already_split=old_node.already_split,
                latency=old_node.latency,
                variable_latency=old_node.variable_latency,
                is_shared=old_node.is_shared,
                pipe_id=pipe_id,
                dual_issue_time=None  # Will be inferred later
            )
            target_graph.add_node(new_node)

        # Fix indexed_by relationships to point to prefixed nodes
        for old_id, new_id in node_mapping.items():
            if new_id not in target_graph.nodes:
                continue
            new_node = target_graph.nodes[new_id]
            if new_node.indexed_by:
                old_index_id = new_node.indexed_by.id
                if old_index_id in node_mapping:
                    new_index_id = node_mapping[old_index_id]
                    if new_index_id in target_graph.nodes:
                        new_node.indexed_by = target_graph.nodes[new_index_id]
                    else:
                        new_node.indexed_by = None
                else:
                    new_node.indexed_by = None

        # Copy edges with updated node references
        for old_edge in source_graph.edges.values():
            new_source_id = node_mapping.get(old_edge.source.id)
            new_target_id = node_mapping.get(old_edge.target.id)

            if new_source_id and new_target_id:
                new_source = target_graph.nodes[new_source_id]
                new_target = target_graph.nodes[new_target_id]

                new_edge = Edge(
                    source=new_source,
                    target=new_target,
                    edge_id=None,
                    data=old_edge.data.copy() if old_edge.data else {}
                )
                target_graph.add_edge(new_edge)

        return node_mapping

    def _auto_detect_shared_state(self) -> List[str]:
        """
        Auto-detect which state should be shared between pipelines.

        Returns:
            List of shared state names (base names without prefixes)
        """
        shared = []

        # Look for ISA state in p0
        for node_id, node in self.p0_graph.nodes.items():
            node_type = node.data.get('type') if node.data else None

            # Register files
            if node_type == 'register_file':
                base_name = node_id
                shared.append(base_name)
                print(f"    Auto-detected shared register file: {base_name}")

            # Memories
            elif node_type in ('memory', 'instruction_memory', 'data_memory'):
                base_name = node_id
                shared.append(base_name)
                self.shared_memories.add(base_name)
                print(f"    Auto-detected shared memory: {base_name}")

            # ISA state elements
            elif node_type == 'isa_state':
                base_name = node_id
                shared.append(base_name)
                print(f"    Auto-detected shared ISA state: {base_name}")

        return shared

    def _create_shared_state(self, graph: ResourceGraph,
                             shared_state_names: List[str]) -> Dict[str, Node]:
        """
        Create shared state nodes (without prefix, pipe_id=None).

        Args:
            graph: Target graph to add shared nodes to
            shared_state_names: List of base state names to make shared

        Returns:
            Mapping of base name to shared node
        """
        shared_nodes = {}

        for base_name in shared_state_names:
            # Check if p0 has this node (preferred source of metadata)
            p0_node = self.p0_graph.nodes.get(base_name)

            if p0_node:
                # Create shared node based on p0's definition
                shared_node = Node(
                    node_id=base_name,
                    data=p0_node.data.copy() if p0_node.data else {},
                    is_arch_state=p0_node.is_arch_state,
                    used_as_index=p0_node.used_as_index,
                    is_uarch_state=p0_node.is_uarch_state,
                    uarch_time=p0_node.uarch_time,
                    pipe_time=p0_node.pipe_time,
                    from_isa_spec=p0_node.from_isa_spec,
                    latency=p0_node.latency,
                    variable_latency=p0_node.variable_latency,
                    is_shared=True,
                    pipe_id=None,  # Shared state has no pipe_id
                    dual_issue_time=None
                )
                graph.add_node(shared_node)
                shared_nodes[base_name] = shared_node
                print(f"    Created shared node: {base_name}")

        return shared_nodes

    def _connect_to_shared_state(self, graph: ResourceGraph, prefix: str,
                                 shared_state_names: List[str]) -> int:
        """
        Connect a pipeline's state accesses to shared state nodes.

        This finds nodes like p0_rf[rs1]_rd and connects them to the shared 'rf' node.

        Args:
            graph: Merged graph
            prefix: Pipeline prefix ('p0_' or 'p1_')
            shared_state_names: List of shared state base names

        Returns:
            Number of connections made
        """
        connections = 0

        for base_name in shared_state_names:
            shared_node = graph.nodes.get(base_name)
            if not shared_node:
                continue

            # Find all prefixed access nodes for this shared state
            prefixed_name = f"{prefix}{base_name}"

            for node_id, node in list(graph.nodes.items()):
                if not node_id.startswith(prefix):
                    continue

                # Check if this node accesses the shared state
                node_type = node.data.get('type') if node.data else None

                # Array access nodes (e.g., p0_rf[rs1]_rd)
                if node_type == 'array_access':
                    # Find the array_base edge and check if it points to a prefixed copy
                    for edge in list(node.incoming_edges):
                        if edge.data.get('type') == 'array_base':
                            source_id = edge.source.id
                            # Check if the source is a prefixed version of the shared state
                            if source_id == prefixed_name:
                                # Update expression if present
                                if 'expression' in node.data:
                                    expr = node.data['expression']
                                    if expr.get('type') == 'array_access' and 'array' in expr:
                                        if expr['array'].get('name') == base_name:
                                            pass  # Expression already references shared name

                                # Redirect edge to shared node
                                edge.remove_from_nodes()
                                if edge.id in graph.edges:
                                    del graph.edges[edge.id]
                                # Create new edge from shared node
                                new_edge = Edge(shared_node, node, None, {'type': 'array_base'})
                                graph.add_edge(new_edge)
                                connections += 1
                                break

                # ISA state read/write nodes
                elif node_type in ('isa_state_read', 'isa_state_write', 'isa_state'):
                    state_name = node.data.get('state_name')
                    if state_name == base_name or state_name == prefixed_name:
                        node.data['state_name'] = base_name
                        node.data['shared_state'] = True

            # Delete the prefixed copy of the shared state node (e.g., p0_rf, p1_rf)
            # since we now use the unprefixed shared version
            prefixed_node = graph.nodes.get(prefixed_name)
            if prefixed_node:
                # Redirect incoming memory_write edges to the shared node
                for edge in list(prefixed_node.incoming_edges):
                    if edge.data.get('type') == 'memory_write':
                        # Redirect to shared node
                        source = edge.source
                        edge.remove_from_nodes()
                        if edge.id in graph.edges:
                            del graph.edges[edge.id]
                        # Create new edge to shared node
                        new_edge = Edge(source, shared_node, None, {'type': 'memory_write'})
                        graph.add_edge(new_edge)
                        print(f"    Redirected memory_write edge from {source.id} to {base_name}")
                    else:
                        # Remove non-memory_write edges
                        edge.remove_from_nodes()
                        if edge.id in graph.edges:
                            del graph.edges[edge.id]

                # Redirect outgoing edges that are memory_write (from write ports to memory)
                # Also redirect array_base edges for array access reads
                for edge in list(prefixed_node.outgoing_edges):
                    edge_type = edge.data.get('type')
                    if edge_type == 'memory_write':
                        # This is a write from this (prefixed) memory - shouldn't happen
                        # since memory nodes don't have outgoing memory_write edges
                        pass
                    elif edge_type == 'array_base':
                        # Array read from this memory - redirect to shared
                        target = edge.target
                        edge.remove_from_nodes()
                        if edge.id in graph.edges:
                            del graph.edges[edge.id]
                        new_edge = Edge(shared_node, target, None, {'type': 'array_base'})
                        graph.add_edge(new_edge)
                    else:
                        edge.remove_from_nodes()
                        if edge.id in graph.edges:
                            del graph.edges[edge.id]

                # Remove the node
                del graph.nodes[prefixed_name]
                print(f"    Removed prefixed node: {prefixed_name} (using shared {base_name})")

        return connections

    def _replace_p1_pc_source(self, graph: ResourceGraph,
                              p0_pc_name: str, p1_pc_name: str) -> None:
        """
        Replace p1's PC read with p0's PC + 4.

        This connects p1's fetch to read from PC+4 while p0 reads from PC.

        Args:
            graph: Merged graph
            p0_pc_name: PC read signal name in p0 (e.g., 'pc_rd')
            p1_pc_name: PC read signal name in p1 (e.g., 'pc_rd')
        """
        p0_pc_rd_id = f"p0_{p0_pc_name}"
        p1_pc_rd_id = f"p1_{p1_pc_name}"

        p0_pc_rd = graph.nodes.get(p0_pc_rd_id)
        p1_pc_rd = graph.nodes.get(p1_pc_rd_id)

        if not p0_pc_rd:
            print(f"    Warning: Could not find p0 PC read: {p0_pc_rd_id}")
            return
        if not p1_pc_rd:
            print(f"    Warning: Could not find p1 PC read: {p1_pc_rd_id}")
            return

        # Determine bit width from p0's PC
        pc_width = p0_pc_rd.data.get('bit_width', 32)

        # Derive instruction size from graph metadata
        instr_size = _get_instruction_byte_size(graph)

        # Create PC + instr_size adder (P1 fetches the next instruction after P0)
        pc_plus_4_id = 'p1_pc_plus_4'
        pc_plus_4 = Node(pc_plus_4_id, data={
            'type': 'operation',
            'operator': '+',
            'bit_width': pc_width,
            'name': pc_plus_4_id,
            'display_name': f'p1_pc = p0_pc + {instr_size}'
        })
        pc_plus_4.pipe_id = 1
        pc_plus_4.pipe_time = 0  # Fetch stage
        graph.add_node(pc_plus_4)

        # Create constant for instruction size
        const_4_id = 'fetch_offset_4'
        if const_4_id not in graph.nodes:
            const_4 = Node(const_4_id, data={
                'type': 'constant',
                'value': instr_size,
                'bit_width': pc_width,
                'name': const_4_id
            })
            graph.add_node(const_4)
        else:
            const_4 = graph.nodes[const_4_id]

        # Connect: p0_pc_rd -> pc_plus_4 (left operand)
        edge_pc = Edge(p0_pc_rd, pc_plus_4, None, {
            'type': 'left_operand',
            'position': 'left'
        })
        graph.add_edge(edge_pc)

        # Connect: const_4 -> pc_plus_4 (right operand)
        edge_const = Edge(const_4, pc_plus_4, None, {
            'type': 'right_operand',
            'position': 'right'
        })
        graph.add_edge(edge_const)

        # Find all outgoing edges from p1_pc_rd and redirect them to pc_plus_4
        edges_to_redirect = list(p1_pc_rd.outgoing_edges)
        for edge in edges_to_redirect:
            # Create new edge from pc_plus_4 to the same target
            new_edge = Edge(pc_plus_4, edge.target, None, edge.data.copy() if edge.data else {})
            graph.add_edge(new_edge)

            # Remove old edge
            edge.remove_from_nodes()
            if edge.id in graph.edges:
                del graph.edges[edge.id]

        print(f"    Created {pc_plus_4_id} = {p0_pc_rd_id} + {instr_size}")
        print(f"    Redirected {len(edges_to_redirect)} edges from p1_pc_rd to pc_plus_4")

    def _add_eligibility_detection(self, graph: ResourceGraph) -> None:
        """
        Create p1_eligible signal from p1's instruction enable signals.

        p1_eligible = OR(p1_instr1_enable, p1_instr2_enable, ...)

        This uses the existing instruction_enables from the merged graph.
        """
        # Find all p1 instruction enables (created during graph merging)
        p1_enables = []
        for node_id, node in sorted(graph.nodes.items()):
            if node_id.startswith('p1_') and '_enable' in node_id:
                node_type = node.data.get('type') if node.data else None
                # Only include actual enable signals, not other nodes with 'enable' in name
                if node_type in ('instruction_enable', 'enable_signal', 'operation', None):
                    # Check that it's likely an instruction enable (has bit_width=1 or no other indicators)
                    bit_width = node.data.get('bit_width', 1) if node.data else 1
                    if bit_width == 1:
                        p1_enables.append(node)

        if not p1_enables:
            print("    Warning: No p1 instruction enables found, skipping eligibility detection")
            return

        print(f"    Found {len(p1_enables)} p1 instruction enable signals")

        # Create OR tree for eligibility
        if len(p1_enables) == 1:
            # Single enable - just alias it
            p1_eligible_id = 'p1_eligible'
            p1_eligible = Node(p1_eligible_id, data={
                'type': 'alias',
                'bit_width': 1,
                'name': p1_eligible_id,
                'display_name': 'P1 Eligible'
            })
            p1_eligible.pipe_id = 1
            p1_eligible.pipe_time = 1  # Decode stage (after instruction decode)
            graph.add_node(p1_eligible)

            edge = Edge(p1_enables[0], p1_eligible, None, {'type': 'assignment'})
            graph.add_edge(edge)
        else:
            # Multiple enables - create OR tree
            p1_eligible = self._create_or_tree(graph, p1_enables, 'p1_eligible')
            p1_eligible.pipe_id = 1
            p1_eligible.pipe_time = 1  # Decode stage

        print(f"    Created p1_eligible signal")

    def _create_or_tree(self, graph: ResourceGraph, inputs: List[Node],
                        result_name: str) -> Node:
        """
        Create an OR tree combining multiple inputs.

        Args:
            graph: Target graph
            inputs: List of input nodes to OR together
            result_name: Name for the result node

        Returns:
            The root OR node
        """
        if len(inputs) == 1:
            return inputs[0]

        if len(inputs) == 2:
            or_node = Node(result_name, data={
                'type': 'operation',
                'operator': '||',
                'bit_width': 1,
                'name': result_name
            })
            graph.add_node(or_node)

            edge1 = Edge(inputs[0], or_node, None, {'type': 'operand', 'operand_index': 0})
            graph.add_edge(edge1)
            edge2 = Edge(inputs[1], or_node, None, {'type': 'operand', 'operand_index': 1})
            graph.add_edge(edge2)

            return or_node

        # More than 2 inputs - build balanced tree
        mid = len(inputs) // 2
        left_inputs = inputs[:mid]
        right_inputs = inputs[mid:]

        left_node = self._create_or_tree(graph, left_inputs, f"{result_name}_left")
        right_node = self._create_or_tree(graph, right_inputs, f"{result_name}_right")

        or_node = Node(result_name, data={
            'type': 'operation',
            'operator': '||',
            'bit_width': 1,
            'name': result_name
        })
        graph.add_node(or_node)

        edge1 = Edge(left_node, or_node, None, {'type': 'operand', 'operand_index': 0})
        graph.add_edge(edge1)
        edge2 = Edge(right_node, or_node, None, {'type': 'operand', 'operand_index': 1})
        graph.add_edge(edge2)

        return or_node

    def _add_pc_advancement_infrastructure(self, graph: ResourceGraph) -> None:
        """
        Add infrastructure for dual-issue PC advancement.

        PC advances by:
        - 0 if p0 is stalled (neither pipe advances)
        - 4 if p1 is stalled or ineligible (only p0 advances)
        - 8 if both pipes advance

        This creates placeholder signals that will be connected after hazard resolution.
        """
        # Create p0_any_stall placeholder (will be connected to stall controllers later)
        p0_any_stall_id = 'p0_any_stall'
        if p0_any_stall_id not in graph.nodes:
            p0_any_stall = Node(p0_any_stall_id, data={
                'type': 'control_signal',
                'bit_width': 1,
                'name': p0_any_stall_id,
                'display_name': 'P0 Any Stall',
                'description': 'OR of all p0 stall signals'
            })
            p0_any_stall.pipe_id = 0
            p0_any_stall.pipe_time = 0
            graph.add_node(p0_any_stall)
            print(f"    Created {p0_any_stall_id} placeholder")

        # Create p1_any_stall placeholder
        p1_any_stall_id = 'p1_any_stall'
        if p1_any_stall_id not in graph.nodes:
            p1_any_stall = Node(p1_any_stall_id, data={
                'type': 'control_signal',
                'bit_width': 1,
                'name': p1_any_stall_id,
                'display_name': 'P1 Any Stall',
                'description': 'OR of all p1 stall signals'
            })
            p1_any_stall.pipe_id = 1
            p1_any_stall.pipe_time = 0
            graph.add_node(p1_any_stall)
            print(f"    Created {p1_any_stall_id} placeholder")

        # Check if p1_eligible exists
        p1_eligible = graph.nodes.get('p1_eligible')

        # Create p1_blocked = p1_any_stall OR NOT p1_eligible
        p1_blocked_id = 'p1_blocked'
        if p1_blocked_id not in graph.nodes:
            p1_blocked = Node(p1_blocked_id, data={
                'type': 'control_signal',
                'bit_width': 1,
                'name': p1_blocked_id,
                'display_name': 'P1 Blocked',
                'description': 'P1 is stalled or instruction is not eligible for P1'
            })
            p1_blocked.pipe_id = 1
            p1_blocked.pipe_time = 0
            graph.add_node(p1_blocked)
            print(f"    Created {p1_blocked_id} placeholder")

        print("    PC advancement infrastructure created (will be finalized after hazard resolution)")

def _create_fetch_stage_eligibility(graph: ResourceGraph, p1_instr_node) -> Node:
    """
    Create a fetch-stage eligibility signal for P1 using the raw instruction from memory.

    This discovers P1's supported instruction types structurally by examining P1's
    existing decode comparators. Only primary opcode-level comparisons (bit_slice
    fields starting at bit 0) are used for eligibility, since sub-field checks
    (funct3, funct7, etc.) are not sufficient alone to identify instruction types
    and would match unrelated instructions.

    The discovery is ISA-agnostic: it finds all P1 comparison nodes that check the
    primary instruction type field (starting at bit 0), which works for any ISA
    encoding scheme (RISC-V opcode[6:0], ARM cond[31:28], MIPS op[31:26], etc.).

    Returns the p1_fetch_eligible node.
    """
    if not p1_instr_node:
        return None

    # Structurally discover P1's supported instruction types from its decode comparisons.
    # Only collect comparisons that check the primary instruction type field (bit_slice
    # starting at bit 0). Sub-field checks (funct3, funct7, etc.) are excluded because
    # they match many unrelated instructions and would make P1 eligible for instructions
    # it cannot execute.
    #
    # Deduplicate by the expression's right-hand value to avoid creating duplicate
    # fetch-time checks for the same opcode.
    seen_opcodes = {}  # right_value_str -> comparison_node

    for node_id, node in graph.nodes.items():
        if not node_id.startswith('p1_'):
            continue
        if node.data.get('type') != 'comparison':
            continue

        expr = node.data.get('expression', {})
        if expr.get('type') != 'binary_op' or expr.get('operation') != '==':
            continue

        left = expr.get('left', {})
        right = expr.get('right', {})

        # Must have a literal value on the right side (the instruction encoding pattern)
        right_val = right.get('value')
        if right_val is None:
            continue

        # Must have a bit_slice on the left side (extracting a field from the instruction)
        if left.get('type') != 'bit_slice':
            continue

        # Only include primary opcode checks (fields starting at bit 0).
        # This filters out sub-field checks like funct3[14:12] or funct7[31:25].
        low = _get_bit_slice_low(left)
        if low != 0:
            continue

        opcode_key = str(right_val)
        if opcode_key not in seen_opcodes:
            seen_opcodes[opcode_key] = node
            print(f"    Discovered P1 opcode: {node.data.get('display_name', node_id)} (from {node_id})")

    if not seen_opcodes:
        print("    Warning: No P1 opcode comparisons found, cannot create eligibility")
        return None

    # Create fetch-stage copies of each opcode comparison, connected to p1_instr
    comparator_nodes = []
    for idx, (_, ref_node) in enumerate(sorted(seen_opcodes.items())):
        # Clone the expression from the reference node, preserving the exact format
        ref_expr = ref_node.data.get('expression', {})
        cmp_id = f'p1_fetch_opcode_check_{idx}'
        cmp_node = Node(cmp_id, data={
            'type': 'comparison',
            'name': cmp_id,
            'display_name': ref_node.data.get('display_name', cmp_id),
            'operation': '==',
            'bit_width': 1,
            'expression': {
                'type': ref_expr.get('type', 'binary_op'),
                'operation': ref_expr.get('operation', '=='),
                'left': ref_expr.get('left', {}).copy() if isinstance(ref_expr.get('left'), dict) else ref_expr.get('left'),
                'right': ref_expr.get('right', {}).copy() if isinstance(ref_expr.get('right'), dict) else ref_expr.get('right'),
            }
        })
        cmp_node.pipe_time = 0
        graph.add_node(cmp_node)

        # Connect p1_instr as the operand (same edge type as existing comparators)
        edge_op = Edge(p1_instr_node, cmp_node, None, {'type': 'operand'})
        graph.add_edge(edge_op)

        comparator_nodes.append(cmp_node)

    # OR all comparators together to form p1_fetch_eligible
    eligible_id = 'p1_fetch_eligible'
    if len(comparator_nodes) == 1:
        eligible = comparator_nodes[0]
        eligible.data['name'] = eligible_id
    else:
        eligible = _create_or_tree_static(graph, comparator_nodes, 'p1_fetch_eligible_or')
        eligible.data['name'] = eligible_id

    eligible.pipe_time = 0
    print(f"    Created fetch-stage eligibility: {eligible_id} (discovered {len(seen_opcodes)} instruction types)")
    return eligible


def finalize_pc_advancement(graph: ResourceGraph, pc_wr_name: str = 'pc_wr',
                            lockstep: bool = False) -> None:
    """
    Finalize PC advancement logic after hazard resolution.

    This should be called AFTER HazardResolver has created stall controllers.
    It connects the stall signals to the PC advancement logic.

    PC advances by:
    - 0 if p0 is stalled (neither pipe advances)
    - 4 if p1 is stalled or ineligible (only p0 advances)
    - 8 if both pipes advance

    Args:
        graph: The merged dual-issue graph after hazard resolution
        pc_wr_name: Name of the PC write node
    """
    print("\n" + "=" * 70)
    print("FINALIZING PC ADVANCEMENT LOGIC")
    print("=" * 70)

    # Step 1: Collect all p0 stall controllers and OR them together
    print("\nStep 1: Collecting p0 stall controllers...")
    p0_stall_nodes = []
    for node_id, node in sorted(graph.nodes.items()):
        if node_id.startswith('p0_') and node_id.endswith('_stall_ctrl'):
            p0_stall_nodes.append(node)
            print(f"    Found: {node_id}")

    # Step 2: Collect all p1 stall controllers and OR them together
    print("\nStep 2: Collecting p1 stall controllers...")
    p1_stall_nodes = []
    for node_id, node in sorted(graph.nodes.items()):
        if node_id.startswith('p1_') and node_id.endswith('_stall_ctrl'):
            p1_stall_nodes.append(node)
            print(f"    Found: {node_id}")

    # Step 2b: Cross-couple stall conditions between pipes.
    if lockstep:
        print("\nStep 2b: Cross-coupling stall conditions (LOCKSTEP: both directions)...")
    else:
        print("\nStep 2b: Cross-coupling stall conditions (P0 -> P1 only)...")

    # Collect all original conditions from each controller BEFORE modification
    p0_ctrl_conditions = {}  # ctrl_id -> list of condition source nodes
    p1_ctrl_conditions = {}
    for ctrl in p0_stall_nodes:
        p0_ctrl_conditions[ctrl.id] = [e.source for e in ctrl.incoming_edges
                                        if e.data.get('type') == 'control']
    for ctrl in p1_stall_nodes:
        p1_ctrl_conditions[ctrl.id] = [e.source for e in ctrl.incoming_edges
                                        if e.data.get('type') == 'control']

    # Add P0's conditions to corresponding P1 controllers
    for p0_ctrl in p0_stall_nodes:
        p1_counterpart_id = 'p1_' + p0_ctrl.id[3:]
        for p1_ctrl in p1_stall_nodes:
            if p1_ctrl.id == p1_counterpart_id:
                existing_sources = {e.source.id for e in p1_ctrl.incoming_edges}
                for cond in p0_ctrl_conditions.get(p0_ctrl.id, []):
                    if cond.id not in existing_sources:
                        edge = Edge(cond, p1_ctrl, None, {'type': 'control'})
                        graph.add_edge(edge)
                        print(f"    Added {cond.id} -> {p1_ctrl.id}")
                break

    # In lockstep mode, also add P1's conditions to P0 controllers
    if lockstep:
        for p1_ctrl in p1_stall_nodes:
            p0_counterpart_id = 'p0_' + p1_ctrl.id[3:]
            for p0_ctrl in p0_stall_nodes:
                if p0_ctrl.id == p0_counterpart_id:
                    existing_sources = {e.source.id for e in p0_ctrl.incoming_edges}
                    for cond in p1_ctrl_conditions.get(p1_ctrl.id, []):
                        if cond.id not in existing_sources:
                            edge = Edge(cond, p0_ctrl, None, {'type': 'control'})
                            graph.add_edge(edge)
                            print(f"    Added {cond.id} -> {p0_ctrl.id}")
                    break

    # Step 3: Create OR tree for p0 stalls
    print("\nStep 3: Creating p0_any_stall signal...")
    p0_any_stall = graph.nodes.get('p0_any_stall')
    if p0_stall_nodes and p0_any_stall:
        if len(p0_stall_nodes) == 1:
            # Single stall - create direct connection
            edge = Edge(p0_stall_nodes[0], p0_any_stall, None, {'type': 'assignment'})
            graph.add_edge(edge)
        else:
            # Multiple stalls - create OR tree
            or_result = _create_or_tree_static(graph, p0_stall_nodes, 'p0_stall_or')
            edge = Edge(or_result, p0_any_stall, None, {'type': 'assignment'})
            graph.add_edge(edge)
        print(f"    Connected {len(p0_stall_nodes)} p0 stall signals")
    elif not p0_stall_nodes:
        # No stalls - create constant 0
        const_0 = _get_or_create_constant(graph, 0, 1, 'const_0')
        edge = Edge(const_0, p0_any_stall, None, {'type': 'assignment'})
        graph.add_edge(edge)
        print("    No p0 stall signals found, using constant 0")

    # Step 4: Create OR tree for p1 stalls
    print("\nStep 4: Creating p1_any_stall signal...")
    p1_any_stall = graph.nodes.get('p1_any_stall')
    if p1_stall_nodes and p1_any_stall:
        if len(p1_stall_nodes) == 1:
            edge = Edge(p1_stall_nodes[0], p1_any_stall, None, {'type': 'assignment'})
            graph.add_edge(edge)
        else:
            or_result = _create_or_tree_static(graph, p1_stall_nodes, 'p1_stall_or')
            edge = Edge(or_result, p1_any_stall, None, {'type': 'assignment'})
            graph.add_edge(edge)
        print(f"    Connected {len(p1_stall_nodes)} p1 stall signals")
    elif not p1_stall_nodes:
        const_0 = _get_or_create_constant(graph, 0, 1, 'const_0')
        edge = Edge(const_0, p1_any_stall, None, {'type': 'assignment'})
        graph.add_edge(edge)
        print("    No p1 stall signals found, using constant 0")

    # Step 5: Create p1_blocked = p1_any_stall OR NOT p1_fetch_eligible
    # IMPORTANT: The eligibility check must use the FETCH-stage instruction (p1_instr),
    # not the execute-stage pipelined instruction. The PC increment decision must be
    # made at fetch time, before the instruction enters the pipeline.
    print("\nStep 5: Creating p1_blocked signal with fetch-stage eligibility...")
    p1_blocked = graph.nodes.get('p1_blocked')
    p1_any_stall = graph.nodes.get('p1_any_stall')
    p1_instr = graph.nodes.get('p1_instr')

    if p1_blocked and p1_any_stall:
        fetch_eligible = _create_fetch_stage_eligibility(graph, p1_instr)
        if fetch_eligible:
            # NOT p1_fetch_eligible
            not_eligible_id = 'p1_not_eligible'
            not_eligible = Node(not_eligible_id, data={
                'type': 'operation',
                'operator': '!',
                'bit_width': 1,
                'name': not_eligible_id
            })
            graph.add_node(not_eligible)
            edge_not = Edge(fetch_eligible, not_eligible, None, {'type': 'operand'})
            graph.add_edge(edge_not)

            # p1_blocked = p1_any_stall OR NOT p1_fetch_eligible
            p1_blocked.data['type'] = 'operation'
            p1_blocked.data['operator'] = '||'
            edge1 = Edge(p1_any_stall, p1_blocked, None, {'type': 'operand', 'operand_index': 0})
            graph.add_edge(edge1)
            edge2 = Edge(not_eligible, p1_blocked, None, {'type': 'operand', 'operand_index': 1})
            graph.add_edge(edge2)
            print("    p1_blocked = p1_any_stall || !p1_fetch_eligible")
        else:
            # No fetch instruction available - fall back to always blocked
            const_1 = _get_or_create_constant(graph, 1, 1, 'const_1')
            edge = Edge(const_1, p1_blocked, None, {'type': 'assignment'})
            graph.add_edge(edge)
            print("    p1_blocked = 1 (no fetch-stage instruction available)")

    # Step 5.5: Add within-pair RAW hazard detection
    # When P0 and P1 issue in the same cycle, if P0 writes a register that P1 reads,
    # P1 must be blocked (it would read the stale value from the register file).
    # This is different from the cross-cycle hazards handled by stall controllers.
    print("\nStep 5.5: Adding within-pair RAW hazard detection...")
    _add_within_pair_raw_hazard(graph, p1_blocked)

    # Step 5.6: Block P1 when P0 is a control-flow instruction (branch/jump)
    # When P0 has a branch/jal/jalr, P1 must not issue because:
    # - If the branch is taken, P1's instruction (at PC+4) is on the wrong path
    # - P1 would execute and corrupt state before the flush takes effect
    print("\nStep 5.6: Adding P0 control-flow blocking for P1...")
    _add_p0_control_flow_blocking(graph, p1_blocked)

    # Step 5.7: Gate P1's Decode valid with fetch-time validity
    # When P1 is blocked for non-stall reasons (ineligible instruction, within-pair
    # RAW hazard, or P0 control-flow), P1's pipeline valid must be 0 (bubble).
    # Otherwise the instruction at PC+4 executes in P1's pipeline even though
    # it will be re-fetched by P0 (since PC only incremented by 4).
    print("\nStep 5.7: Gating P1 Decode valid with fetch validity...")
    _gate_p1_decode_valid_with_blocked(graph)

    # Step 5.8: Gate P0's Decode valid when PC is frozen due to P1 stall
    # (non-lockstep only — in lockstep, P0 stalls with P1 so no bubble needed)
    if not lockstep:
        print("\nStep 5.8: Gating P0 Decode valid when P1 stalls (bubble injection)...")
        _gate_p0_decode_valid_on_p1_stall(graph)
    else:
        print("\nStep 5.8: Skipped (lockstep mode)")

    # Step 6: Create PC increment mux
    print("\nStep 6: Creating PC increment logic...")
    _create_pc_increment_mux(graph, pc_wr_name, lockstep=lockstep)

    print("\n" + "=" * 70)
    print("PC ADVANCEMENT FINALIZATION COMPLETE")
    print("=" * 70)


def _add_within_pair_raw_hazard(graph: ResourceGraph, p1_blocked_node) -> None:
    """
    Add within-pair RAW (Read-After-Write) hazard detection.

    When P0 and P1 issue simultaneously, P0's result won't be available for P1 to read
    until after writeback. If P0 writes rd and P1 reads rs1 or rs2 matching that rd,
    P1 must be blocked (deferred to the next cycle as a single-issue).

    Discovers register indices and write enables structurally:
    - P0 write index and P1 read indices via ArrayAccessAnalyzer on the shared RF
    - P0 write enable via the RF write port's combined_write_enable
    - P0 rd != 0 via the write index bit width

    Adds the hazard signal as an additional OR input to p1_blocked.
    """
    if not p1_blocked_node:
        print("    Warning: Missing p1_blocked node, skipping within-pair hazard")
        return

    p0_instr = graph.nodes.get('p0_instr')
    p1_instr = graph.nodes.get('p1_instr')
    if not p0_instr or not p1_instr:
        print("    Warning: Missing p0_instr or p1_instr, skipping within-pair hazard")
        return

    # Step 1: Structurally discover P0 write index and P1 read indices from the RF.
    #
    # In the merged graph, RF reads use array_access nodes (found by ArrayAccessAnalyzer)
    # but RF writes use memory_write_port nodes connected to the shared RF via memory_write
    # edges. The write address (index) is connected via write_address edges.
    rf_node = graph.nodes.get('rf')
    if not rf_node:
        print("    Warning: No shared 'rf' node found, skipping within-pair hazard")
        return

    # Find P0 write indices from write port nodes (write_address edges).
    # In multi-stage pipelines, the write_address may point to a pipelined version
    # (e.g., p0_PIPE_ExecuteMemoryWriteback_rd_PIPE). Trace backward through
    # pipeline_input edges to find the original decode-time node (e.g., p0_rd).
    def _trace_to_original(node, max_depth=10):
        """Trace backward through pipeline registers to find original node."""
        current = node
        for _ in range(max_depth):
            if current.data.get('type') != 'pipeline_register':
                return current
            # Follow pipeline_input edge backward
            found = False
            for e in current.incoming_edges:
                if e.data.get('type') == 'pipeline_input':
                    current = e.source
                    found = True
                    break
            if not found:
                return current
        return current

    p0_write_indices = []
    for edge in rf_node.incoming_edges:
        if edge.data.get('type') == 'memory_write':
            write_port = edge.source
            if write_port.id.startswith('p0_'):
                for wp_edge in write_port.incoming_edges:
                    if wp_edge.data.get('type') == 'write_address':
                        original = _trace_to_original(wp_edge.source)
                        if original.id not in [n.id for n in p0_write_indices]:
                            p0_write_indices.append(original)

    # Find P1 read indices from array_access nodes (array_index edges)
    analyzer = ArrayAccessAnalyzer(graph)
    reads, _ = analyzer.get_reads_and_writes('rf')
    p1_read_indices = []
    for r in reads:
        if r.node.id.startswith('p1_') and r.index_node:
            if r.index_node.id not in [n.id for n in p1_read_indices]:
                p1_read_indices.append(r.index_node)

    if not p0_write_indices:
        print("    Warning: No P0 RF write indices found, skipping within-pair hazard")
        return
    if not p1_read_indices:
        print("    Warning: No P1 RF read indices found, skipping within-pair hazard")
        return

    # Use the first P0 write index (typically p0_rd)
    p0_wr_idx = p0_write_indices[0]
    print(f"    Discovered P0 write index: {p0_wr_idx.id}")
    print(f"    Discovered P1 read indices: {[n.id for n in p1_read_indices]}")

    # Step 2: Create fetch-time clones of the index nodes.
    # The decode-time index nodes (p0_rd, p1_rs1, etc.) are var nodes assigned from
    # bit_slice nodes (like p0_instr[11:7]). We find the source bit_slice to get the
    # bit range, then create a new bit_slice node connected to the raw fetch-time
    # instruction word (p0_instr / p1_instr) instead of the pipelined instruction.
    def _clone_index_for_fetch(index_node, instr_node, prefix):
        """Create a fetch-time bit_slice node extracting the same field as index_node."""
        fetch_id = f'{prefix}_fetch_{index_node.id.split("_", 1)[1] if "_" in index_node.id else index_node.id}'
        bit_width = index_node.data.get('bit_width', 5)

        # Find the source bit_slice node that feeds this var via assignment edge
        source_bit_slice = None
        for e in index_node.incoming_edges:
            if e.data.get('type') == 'assignment' and e.source.data.get('type') == 'bit_slice':
                source_bit_slice = e.source
                break

        if source_bit_slice and source_bit_slice.data.get('expression'):
            # Copy the bit range from the source bit_slice's expression
            src_expr = source_bit_slice.data['expression']
            bit_range = src_expr.get('range')
            if bit_range:
                expr = {
                    'type': 'bit_slice',
                    'range': list(bit_range) if isinstance(bit_range, tuple) else bit_range,
                    'operand': {'type': 'identifier', 'name': instr_node.id}
                }
                display_name = f'{instr_node.id}[{bit_range[0]}:{bit_range[1]}]'
            else:
                # Fallback: copy the expression and update the operand
                expr = src_expr.copy() if isinstance(src_expr, dict) else src_expr
                display_name = source_bit_slice.data.get('display_name', fetch_id)
        else:
            print(f"      Warning: No bit_slice source found for {index_node.id}")
            expr = {}
            display_name = fetch_id

        fetch_node = Node(fetch_id, data={
            'type': 'bit_slice',
            'name': fetch_id,
            'display_name': display_name,
            'bit_width': bit_width,
            'expression': expr,
        })
        fetch_node.pipe_time = 0
        fetch_node.pipe_id = 0 if prefix == 'p0' else 1
        graph.add_node(fetch_node)
        graph.add_edge(Edge(instr_node, fetch_node, None, {'type': 'bit_access'}))
        return fetch_node

    p0_fetch_rd = _clone_index_for_fetch(p0_wr_idx, p0_instr, 'p0')
    p1_fetch_reads = [_clone_index_for_fetch(idx, p1_instr, 'p1') for idx in p1_read_indices]

    print(f"    Created fetch-time bit slices: {p0_fetch_rd.id}, {[n.id for n in p1_fetch_reads]}")

    # Step 3: Create comparisons — p0_fetch_rd == each p1_fetch_rsN
    match_nodes = []
    for i, p1_fetch_idx in enumerate(p1_fetch_reads):
        match_id = f'within_pair_rs{i}_match'
        match_node = Node(match_id, data={
            'type': 'operation',
            'operator': '==',
            'bit_width': 1,
            'name': match_id,
            'display_name': f'{p0_fetch_rd.id} == {p1_fetch_idx.id}'
        })
        match_node.pipe_time = 0
        graph.add_node(match_node)
        graph.add_edge(Edge(p0_fetch_rd, match_node, None, {'type': 'left_operand', 'position': 'left'}))
        graph.add_edge(Edge(p1_fetch_idx, match_node, None, {'type': 'right_operand', 'position': 'right'}))
        match_nodes.append(match_node)

    # OR all comparisons: any_rs_match
    if len(match_nodes) == 1:
        any_match = match_nodes[0]
    else:
        any_match = _create_or_tree_static(graph, match_nodes, 'within_pair_any_rs_match')
    any_match.pipe_time = 0

    print(f"    Created {len(match_nodes)} register match comparisons")

    # Step 4: Create p0_fetch_rd != 0 check (writing to x0/r0 is always safe)
    rd_bit_width = p0_wr_idx.data.get('bit_width', 5)
    const_0 = _get_or_create_constant(graph, 0, rd_bit_width, f'const_0_{rd_bit_width}bit')
    rd_ne_0_id = 'within_pair_rd_ne_0'
    rd_ne_0 = Node(rd_ne_0_id, data={
        'type': 'operation',
        'operator': '!=',
        'bit_width': 1,
        'name': rd_ne_0_id,
        'display_name': f'{p0_fetch_rd.id} != 0'
    })
    rd_ne_0.pipe_time = 0
    graph.add_node(rd_ne_0)
    graph.add_edge(Edge(p0_fetch_rd, rd_ne_0, None, {'type': 'left_operand', 'position': 'left'}))
    graph.add_edge(Edge(const_0, rd_ne_0, None, {'type': 'right_operand', 'position': 'right'}))

    # Step 5: Discover P0's RF write enable structurally.
    # The shared RF node has memory_write edges from write port nodes; each
    # write port's combined_write_enable gives the signal that gates whether
    # the instruction actually writes to RF (already includes rd != 0 guard,
    # store/branch exclusion, etc.). We replicate the instruction enables at
    # fetch time by cloning P0's decode comparators against p0_instr.
    p0_writes_rf = _discover_p0_writes_rf_at_fetch(graph, p0_instr)

    if not p0_writes_rf:
        print("    Warning: Could not discover P0 writes-RF signal, skipping within-pair hazard")
        return

    print(f"    Created P0 writes-RF check: {p0_writes_rf.id}")

    # Step 6: Combine: p1_within_pair_hazard = any_rs_match && rd_ne_0 && p0_writes_rf
    hazard_id = 'p1_within_pair_hazard'
    hazard = Node(hazard_id, data={
        'type': 'operation',
        'operator': '&&',
        'bit_width': 1,
        'name': hazard_id,
        'display_name': 'P1 Within-Pair RAW Hazard'
    })
    hazard.pipe_time = 0
    graph.add_node(hazard)
    graph.add_edge(Edge(any_match, hazard, None, {'type': 'operand', 'operand_index': 0}))
    graph.add_edge(Edge(rd_ne_0, hazard, None, {'type': 'operand', 'operand_index': 1}))
    graph.add_edge(Edge(p0_writes_rf, hazard, None, {'type': 'operand', 'operand_index': 2}))

    print(f"    Created {hazard_id}")

    # Step 7: Add hazard to p1_blocked (OR it in)
    graph.add_edge(Edge(hazard, p1_blocked_node, None, {'type': 'operand', 'operand_index': 2}))
    print(f"    Added {hazard_id} to p1_blocked")


def _discover_p0_writes_rf_at_fetch(graph: ResourceGraph, p0_instr: Node) -> Optional[Node]:
    """
    Discover whether P0 writes to RF at fetch time, ISA-agnostically.

    Strategy: find all P0 instruction enables that feed (directly or via mux)
    into the RF write port's combined_write_enable. Clone their decode comparisons
    against p0_instr (raw fetch instruction). OR them together to form
    p0_fetch_writes_rf.

    If no enables are found, falls back to checking which P0 instruction enables
    do NOT produce an RF write (inferred from the graph structure).
    """
    rf_node = graph.nodes.get('rf')
    if not rf_node:
        return None

    # Find P0's instruction enables that contribute to RF writes.
    # Trace: rf <- memory_write <- write_port.combined_write_enable <- OR of enables
    p0_write_enables = []
    for edge in rf_node.incoming_edges:
        if edge.data.get('type') == 'memory_write':
            write_port = edge.source
            cwe_id = write_port.data.get('combined_write_enable')
            if cwe_id and cwe_id.startswith('p0_'):
                cwe_node = graph.nodes.get(cwe_id)
                if cwe_node:
                    p0_write_enables.append(cwe_node)

    if not p0_write_enables:
        return None

    # Trace through the combined_write_enable to find the opcode-level comparators.
    # We only collect comparators that check the primary instruction type field
    # (bit_slice starting at bit 0), avoiding sub-field checks (funct3, funct7, etc.)
    # that would create redundant fine-grained checks at fetch time.
    enable_comparators = set()

    def _find_opcode_comparators(node, visited=None, depth=0):
        """Trace backward from a write enable to find opcode-level comparators."""
        if visited is None:
            visited = set()
        if node.id in visited or depth > 8:
            return
        visited.add(node.id)

        ntype = node.data.get('type', '')
        if ntype == 'comparison' and node.data.get('expression'):
            expr = node.data.get('expression', {})
            left = expr.get('left', {})
            if left.get('type') == 'bit_slice':
                low = _get_bit_slice_low(left)
                if low == 0:
                    enable_comparators.add(node.id)
            return  # Don't trace past comparisons

        # Trace through operations (OR, AND, NOT) and other combinational logic
        for e in node.incoming_edges:
            _find_opcode_comparators(e.source, visited, depth + 1)

    for we in p0_write_enables:
        _find_opcode_comparators(we)

    if not enable_comparators:
        return None

    # Create fetch-time clones of these comparators, connected to p0_instr
    fetch_comparator_nodes = []
    for idx, comp_id in enumerate(sorted(enable_comparators)):
        comp_node = graph.nodes[comp_id]
        ref_expr = comp_node.data.get('expression', {})
        fetch_cmp_id = f'p0_fetch_rf_wr_check_{idx}'
        fetch_cmp = Node(fetch_cmp_id, data={
            'type': 'comparison',
            'name': fetch_cmp_id,
            'display_name': comp_node.data.get('display_name', fetch_cmp_id),
            'operation': '==',
            'bit_width': 1,
            'expression': {
                'type': ref_expr.get('type', 'binary_op'),
                'operation': ref_expr.get('operation', '=='),
                'left': ref_expr.get('left', {}).copy() if isinstance(ref_expr.get('left'), dict) else ref_expr.get('left'),
                'right': ref_expr.get('right', {}).copy() if isinstance(ref_expr.get('right'), dict) else ref_expr.get('right'),
            }
        })
        fetch_cmp.pipe_time = 0
        graph.add_node(fetch_cmp)
        graph.add_edge(Edge(p0_instr, fetch_cmp, None, {'type': 'operand'}))
        fetch_comparator_nodes.append(fetch_cmp)
        print(f"      Cloned RF write enable comparator: {comp_id} -> {fetch_cmp_id}")

    if not fetch_comparator_nodes:
        return None

    # OR all fetch comparators: p0_fetch_writes_rf
    if len(fetch_comparator_nodes) == 1:
        result = fetch_comparator_nodes[0]
        result.data['name'] = 'p0_fetch_writes_rf'
    else:
        result = _create_or_tree_static(graph, fetch_comparator_nodes, 'p0_fetch_writes_rf')
    result.pipe_time = 0
    return result


def _add_p0_control_flow_blocking(graph: ResourceGraph, p1_blocked_node) -> None:
    """
    Block P1 when P0's instruction is a control-flow instruction.

    When P0 fetches a branch or jump, P1 must not co-issue because:
    - If the control-flow instruction redirects PC, P1's instruction (at PC+4)
      is on the wrong path and would corrupt architectural state
    - The flush mechanism only takes effect on the next cycle, but P1's writes
      happen in the same cycle as P0's branch execution

    Discovers control-flow instructions structurally from the PC write mux:
    each non-default mux_select edge represents a control transfer (branch/jump).
    The corresponding decode comparators are traced backward from those selectors,
    then cloned as fetch-time checks against p0_instr.

    Adds the combined signal as an additional OR input to p1_blocked.
    """
    p0_instr = graph.nodes.get('p0_instr')
    if not p0_instr or not p1_blocked_node:
        print("    Warning: Missing p0_instr or p1_blocked, skipping control-flow blocking")
        return

    # Structurally discover control-flow selectors from the PC write mux.
    # This is the same discovery pattern used by add_dual_issue_control_hazard_flush().
    pc_mux = graph.nodes.get('p0_pc_wr_mux')
    if not pc_mux:
        print("    Warning: p0_pc_wr_mux not found, skipping control-flow blocking")
        return

    # Find the default input source (fallthrough/normal-flow PC)
    default_source_id = None
    for edge in pc_mux.incoming_edges:
        if edge.data.get('type') == 'mux_default_input':
            default_source_id = edge.source.id
            break

    # Collect mux_select and mux_input edges
    select_edges = []
    input_edges_by_index = {}
    for edge in pc_mux.incoming_edges:
        if edge.data.get('type') == 'mux_select':
            select_edges.append(edge)
        elif edge.data.get('type') == 'mux_input':
            idx = edge.data.get('input_index')
            if idx is not None:
                input_edges_by_index[idx] = edge

    # Find selectors that redirect PC (non-default targets = control transfers).
    # A mux input is "normal flow" (sequential advancement) if it is directly
    # derived from the default source (e.g., default=pc, normal-flow=pc+4).
    # Control-flow inputs (branch/jump targets) are NOT derived from the default.
    def _is_sequential_flow(input_source):
        """Check if input is derived from default source (e.g., pc+4 from pc)."""
        if not default_source_id:
            return False
        for e in input_source.incoming_edges:
            if e.source.id == default_source_id:
                return True
        return False

    cf_selectors = []
    for sel_edge in select_edges:
        sel_idx = sel_edge.data.get('select_index')
        paired_input = input_edges_by_index.get(sel_idx)
        if not paired_input:
            continue
        if paired_input.source.id == default_source_id:
            continue  # Same as default, not a redirect
        if _is_sequential_flow(paired_input.source):
            print(f"    Sequential-flow selector (skipped): {sel_edge.source.id}")
            continue  # Normal sequential flow (e.g., pc+4 derived from pc)
        cf_selectors.append(sel_edge.source)

    if not cf_selectors:
        print("    No control-flow selectors found in PC mux, skipping")
        return

    # Find the opcode-level comparators that identify control-flow instructions.
    # We trace from each PC mux selector backward through combinational logic
    # (OR/AND/enable nodes) to find comparison nodes that check the primary
    # instruction type field (the opcode, starting at bit 0). We stop at the
    # first comparison level and skip sub-field checks (funct3, funct7, etc.)
    # to avoid over-decomposing instruction enables into many fine-grained checks.
    #
    # We restrict the trace to only follow enable/gate logic (instruction_enable,
    # logical_and, logical_or, operation with logical operators) and stop at
    # data-path nodes (var, array_access, isa_state, etc.) to avoid wandering
    # through the datapath into unrelated comparators.
    cf_comparators = set()

    # Node types that represent enable/gate logic (safe to trace through).
    # Include pipeline_register so we can trace through pipelined enables in
    # multi-stage pipelines (e.g., 3-stage where enables are pipelined before
    # reaching the PC mux selectors at the execution stage).
    _ENABLE_TYPES = {'instruction_enable', 'logical_and', 'logical_or', 'operation', 'pipeline_register'}

    def _find_opcode_comparators(node, visited=None, depth=0):
        if visited is None:
            visited = set()
        if node.id in visited or depth > 8:
            return
        visited.add(node.id)
        ntype = node.data.get('type', '')
        if ntype == 'comparison' and node.data.get('expression'):
            expr = node.data.get('expression', {})
            left = expr.get('left', {})
            if left.get('type') == 'bit_slice':
                low = _get_bit_slice_low(left)
                # Only include primary opcode checks (fields starting at bit 0).
                # This filters out sub-field checks like funct3[14:12] or funct7[31:25].
                if low == 0:
                    cf_comparators.add(node.id)
            return  # Don't trace past comparisons
        # Only trace through enable/gate logic, not data-path nodes
        if ntype not in _ENABLE_TYPES:
            return
        for e in node.incoming_edges:
            _find_opcode_comparators(e.source, visited, depth + 1)

    for sel_node in cf_selectors:
        _find_opcode_comparators(sel_node)

    if not cf_comparators:
        print("    Warning: Could not trace control-flow selectors to decode comparators")
        return

    # Create fetch-time clones of the control-flow decode comparators
    fetch_cf_nodes = []
    for idx, comp_id in enumerate(sorted(cf_comparators)):
        comp_node = graph.nodes[comp_id]
        ref_expr = comp_node.data.get('expression', {})
        fetch_cmp_id = f'p0_fetch_cf_check_{idx}'
        fetch_cmp = Node(fetch_cmp_id, data={
            'type': 'comparison',
            'name': fetch_cmp_id,
            'display_name': comp_node.data.get('display_name', fetch_cmp_id),
            'operation': '==',
            'bit_width': 1,
            'expression': {
                'type': ref_expr.get('type', 'binary_op'),
                'operation': ref_expr.get('operation', '=='),
                'left': ref_expr.get('left', {}).copy() if isinstance(ref_expr.get('left'), dict) else ref_expr.get('left'),
                'right': ref_expr.get('right', {}).copy() if isinstance(ref_expr.get('right'), dict) else ref_expr.get('right'),
            }
        })
        fetch_cmp.pipe_time = 0
        graph.add_node(fetch_cmp)
        graph.add_edge(Edge(p0_instr, fetch_cmp, None, {'type': 'operand'}))
        fetch_cf_nodes.append(fetch_cmp)
        print(f"      Discovered control-flow comparator: {comp_id} -> {fetch_cmp_id}")

    # OR all control-flow checks together
    if len(fetch_cf_nodes) == 1:
        p0_cf = fetch_cf_nodes[0]
        p0_cf.data['name'] = 'p0_fetch_is_control_flow'
        p0_cf.data['display_name'] = 'P0 is control-flow'
    else:
        p0_cf = _create_or_tree_static(graph, fetch_cf_nodes, 'p0_fetch_is_control_flow')
        p0_cf.data['display_name'] = 'P0 is control-flow'
    p0_cf.pipe_time = 0

    # Add to p1_blocked as operand_index 3
    graph.add_edge(Edge(p0_cf, p1_blocked_node, None, {'type': 'operand', 'operand_index': 3}))
    print(f"    Added {p0_cf.id} to p1_blocked ({len(cf_comparators)} control-flow types)")


def _gate_p1_decode_valid_with_blocked(graph: ResourceGraph) -> None:
    """
    Replace P1's Decode valid source from constant 1 with a fetch-validity signal.

    Without this fix, P1's pipeline always has valid=1, so instructions fetched
    by P1 always execute even when P1 is blocked (non-eligible, within-pair hazard,
    or P0 control-flow). This causes double-execution because the same instruction
    will also be fetched by P0 in the next cycle (since PC only incremented by 4).

    Creates:
      p1_blocked_non_stall = p1_not_eligible || p1_within_pair_hazard || p0_is_control_flow
      p1_fetch_valid = !p1_blocked_non_stall

    Finds the first P1 valid pipeline register structurally (the one with the
    lowest pipe_time among p1_PIPE_*_valid_PIPE nodes) and replaces its
    pipeline_input source with p1_fetch_valid.
    """
    # Structurally find the first P1 valid pipeline register by searching for
    # p1_PIPE_*_valid_PIPE nodes and selecting the one with lowest pipe_time.
    import re as _re
    p1_decode_valid = None
    best_pipe_time = float('inf')
    for node_id, node in graph.nodes.items():
        if _re.match(r'p1_PIPE_\w+_valid_PIPE$', node_id):
            pt = getattr(node, 'pipe_time', None)
            if pt is not None and pt < best_pipe_time:
                best_pipe_time = pt
                p1_decode_valid = node
    if not p1_decode_valid:
        print("    Warning: No P1 valid pipeline register found, skipping")
        return
    print(f"    Found P1 valid pipeline register: {p1_decode_valid.id}")

    # Collect the non-stall blocking condition nodes
    p1_not_eligible = graph.nodes.get('p1_not_eligible')
    p1_within_pair_hazard = graph.nodes.get('p1_within_pair_hazard')
    p0_control_flow = graph.nodes.get('p0_fetch_is_control_flow')

    blocking_conditions = []
    if p1_not_eligible:
        blocking_conditions.append(p1_not_eligible)
    if p1_within_pair_hazard:
        blocking_conditions.append(p1_within_pair_hazard)
    if p0_control_flow:
        blocking_conditions.append(p0_control_flow)

    if not blocking_conditions:
        print("    Warning: No blocking conditions found, skipping")
        return

    # Create OR tree for non-stall blocking
    if len(blocking_conditions) == 1:
        blocked_signal = blocking_conditions[0]
    else:
        blocked_id = 'p1_blocked_non_stall'
        blocked = Node(blocked_id, data={
            'type': 'operation',
            'operator': '||',
            'bit_width': 1,
            'name': blocked_id,
            'display_name': 'P1 blocked (non-stall)'
        })
        blocked.pipe_time = 0
        graph.add_node(blocked)
        for i, cond in enumerate(blocking_conditions):
            graph.add_edge(Edge(cond, blocked, None, {'type': 'operand', 'operand_index': i}))
        blocked_signal = blocked

    # Create p1_fetch_valid = NOT blocked
    fetch_valid_id = 'p1_fetch_valid'
    fetch_valid = Node(fetch_valid_id, data={
        'type': 'operation',
        'operator': '!',
        'bit_width': 1,
        'name': fetch_valid_id,
        'display_name': 'P1 fetch valid'
    })
    fetch_valid.pipe_time = 0
    graph.add_node(fetch_valid)
    graph.add_edge(Edge(blocked_signal, fetch_valid, None, {'type': 'operand'}))

    # Find and replace the pipeline_input source edge to the P1 valid register
    old_source_edge = None
    for edge in list(p1_decode_valid.incoming_edges):
        if edge.data.get('type') == 'pipeline_input':
            old_source_edge = edge
            break

    if old_source_edge:
        # Remove old edge and add new one with p1_fetch_valid as source
        graph.remove_edge(old_source_edge.id)
        graph.add_edge(Edge(fetch_valid, p1_decode_valid, None, {'type': 'pipeline_input'}))
        print(f"    Replaced {p1_decode_valid.id} source with {fetch_valid_id}")
    else:
        print(f"    Warning: No pipeline_input edge found for {p1_decode_valid.id}")


def _gate_p0_decode_valid_on_p1_stall(graph: ResourceGraph) -> None:
    """
    Inject a bubble into P0's decode valid when P1 has a real stall.

    When P1 stalls but P0 doesn't, P0's pipeline drains forward (the current
    P0 instruction advances from Decode to Execute). The PC is frozen (no new
    pair fetched), so P0's fetch stage re-reads the same instruction from memory.
    Without this fix, that re-fetched instruction would enter P0's decode with
    valid=1 and execute again (double-execution).

    This gates P0's decode valid with !p1_any_stall. When P1 stalls, P0's
    decode gets a bubble even though P0 itself is not stalled.
    """
    import re as _re

    p1_any_stall = graph.nodes.get('p1_any_stall')
    if not p1_any_stall:
        print("    No p1_any_stall signal, skipping (no stall hazards)")
        return

    # Find P0's first valid pipeline register (lowest pipe_time p0_PIPE_*_valid_PIPE)
    p0_decode_valid = None
    best_pipe_time = float('inf')
    for node_id, node in graph.nodes.items():
        if _re.match(r'p0_PIPE_\w+_valid_PIPE$', node_id):
            pt = getattr(node, 'pipe_time', None)
            if pt is not None and pt < best_pipe_time:
                best_pipe_time = pt
                p0_decode_valid = node
    if not p0_decode_valid:
        print("    Warning: No P0 valid pipeline register found, skipping")
        return
    print(f"    Found P0 valid pipeline register: {p0_decode_valid.id}")

    # Find the current pipeline_input source for the P0 valid register
    old_source_edge = None
    old_source = None
    for edge in list(p0_decode_valid.incoming_edges):
        if edge.data.get('type') == 'pipeline_input':
            old_source_edge = edge
            old_source = edge.source
            break

    if not old_source:
        print("    Warning: No pipeline_input source found for P0 valid register, skipping")
        return

    # Create: p0_fetch_valid_no_p1_stall = old_source AND !p1_any_stall
    # This injects a bubble (valid=0) when P1 stalls, preventing double-execution
    # of the re-fetched instruction at the frozen PC.
    not_p1_stall_id = 'p0_not_p1_any_stall'
    not_p1_stall = Node(not_p1_stall_id, data={
        'type': 'operation',
        'operator': '!',
        'bit_width': 1,
        'name': not_p1_stall_id,
        'display_name': 'NOT P1 any stall'
    })
    not_p1_stall.pipe_time = 0
    graph.add_node(not_p1_stall)
    graph.add_edge(Edge(p1_any_stall, not_p1_stall, None, {'type': 'operand'}))

    gated_id = 'p0_fetch_valid_gated'
    gated = Node(gated_id, data={
        'type': 'operation',
        'operator': '&&',
        'bit_width': 1,
        'name': gated_id,
        'display_name': 'P0 fetch valid (gated by P1 stall)'
    })
    gated.pipe_time = 0
    graph.add_node(gated)
    graph.add_edge(Edge(old_source, gated, None, {'type': 'operand', 'operand_index': 0}))
    graph.add_edge(Edge(not_p1_stall, gated, None, {'type': 'operand', 'operand_index': 1}))

    # Replace the pipeline_input source
    graph.remove_edge(old_source_edge.id)
    graph.add_edge(Edge(gated, p0_decode_valid, None, {'type': 'pipeline_input'}))
    print(f"    Gated {p0_decode_valid.id} with !p1_any_stall -> {gated_id}")


def _add_waw_hazard_detection(graph: ResourceGraph) -> None:
    """
    Add Write-After-Write hazard detection for register file writes.

    When both P0 and P1 try to write to the same destination register,
    P1's write should be blocked (P0 has priority).

    This creates:
    - rf_waw_hazard = (p0_rd == p1_rd) && p0_rf_wr_en
    - Gates P1's RF write enable with !rf_waw_hazard

    RF write enable nodes are discovered structurally by finding the shared
    register file node and tracing its combined_write_enable references.
    """
    # Structurally discover RF write enable signals.
    # Find the shared register file node and look for combined_write_enable in
    # RF write port nodes (array_access nodes connected to rf via memory_write edges).
    p0_rf_wr_en = None
    p1_rf_wr_en = None
    p0_rd = graph.nodes.get('p0_rd')
    p1_rd = graph.nodes.get('p1_rd')

    rf_node = graph.nodes.get('rf')
    if rf_node:
        # Find write port nodes that write to RF
        for edge in rf_node.incoming_edges:
            if edge.data.get('type') == 'memory_write':
                write_port = edge.source
                # The write port's combined_write_enable points to the enable signal
                cwe_id = write_port.data.get('combined_write_enable')
                if cwe_id:
                    cwe_node = graph.nodes.get(cwe_id)
                    if cwe_node:
                        if cwe_id.startswith('p0_') and not p0_rf_wr_en:
                            p0_rf_wr_en = cwe_node
                            print(f"    Discovered P0 RF write enable: {cwe_id}")
                        elif cwe_id.startswith('p1_') and not p1_rf_wr_en:
                            p1_rf_wr_en = cwe_node
                            print(f"    Discovered P1 RF write enable: {cwe_id}")

    if not all([p0_rf_wr_en, p1_rf_wr_en, p0_rd, p1_rd]):
        print("    Warning: Missing RF write signals, skipping WAW hazard detection")
        missing = []
        if not p0_rf_wr_en:
            missing.append('p0 RF write enable (not found)')
        if not p1_rf_wr_en:
            missing.append('p1 RF write enable (not found)')
        if not p0_rd:
            missing.append('p0_rd')
        if not p1_rd:
            missing.append('p1_rd')
        print(f"      Missing: {missing}")
        return

    # Create comparator: p0_rd == p1_rd
    rd_eq_id = 'rf_waw_rd_eq'
    rd_eq = Node(rd_eq_id, data={
        'type': 'operation',
        'operator': '==',
        'bit_width': 1,
        'name': rd_eq_id,
        'display_name': 'P0.rd == P1.rd'
    })
    graph.add_node(rd_eq)
    edge_p0_rd = Edge(p0_rd, rd_eq, None, {'type': 'left_operand', 'position': 'left'})
    graph.add_edge(edge_p0_rd)
    edge_p1_rd = Edge(p1_rd, rd_eq, None, {'type': 'right_operand', 'position': 'right'})
    graph.add_edge(edge_p1_rd)

    # Create WAW hazard signal: rf_waw_hazard = rd_eq && p0_rf_wr_en
    waw_hazard_id = 'rf_waw_hazard'
    waw_hazard = Node(waw_hazard_id, data={
        'type': 'operation',
        'operator': '&&',
        'bit_width': 1,
        'name': waw_hazard_id,
        'display_name': 'RF WAW Hazard'
    })
    graph.add_node(waw_hazard)
    edge_rd_eq = Edge(rd_eq, waw_hazard, None, {'type': 'operand', 'operand_index': 0})
    graph.add_edge(edge_rd_eq)
    edge_p0_wr = Edge(p0_rf_wr_en, waw_hazard, None, {'type': 'operand', 'operand_index': 1})
    graph.add_edge(edge_p0_wr)

    # Create NOT waw_hazard
    not_waw_id = 'rf_waw_no_hazard'
    not_waw = Node(not_waw_id, data={
        'type': 'operation',
        'operator': '!',
        'bit_width': 1,
        'name': not_waw_id
    })
    graph.add_node(not_waw)
    edge_waw = Edge(waw_hazard, not_waw, None, {'type': 'operand'})
    graph.add_edge(edge_waw)

    # Gate P1's RF write enable: p1_rf_wr_en_gated = p1_rf_wr_en && !waw_hazard
    gated_wr_id = 'p1_rf_rd_ne_0_guarded_enable_valid_waw_gated'
    gated_wr = Node(gated_wr_id, data={
        'type': 'operation',
        'operator': '&&',
        'bit_width': 1,
        'name': gated_wr_id,
        'display_name': 'P1 RF Write Enable (WAW gated)'
    })
    graph.add_node(gated_wr)
    edge_orig = Edge(p1_rf_wr_en, gated_wr, None, {'type': 'operand', 'operand_index': 0})
    graph.add_edge(edge_orig)
    edge_no_waw = Edge(not_waw, gated_wr, None, {'type': 'operand', 'operand_index': 1})
    graph.add_edge(edge_no_waw)

    # Now redirect consumers of p1_rf_wr_en to use the gated version
    # Find edges from p1_rf_wr_en to RF write port
    redirected = 0
    for edge in list(p1_rf_wr_en.outgoing_edges):
        # Check if this is a write enable edge to the RF
        target_id = edge.target.id
        if 'rf' in target_id.lower() and ('wr' in target_id.lower() or 'write' in target_id.lower()):
            # Redirect to gated version
            new_edge = Edge(gated_wr, edge.target, None, edge.data.copy())
            graph.add_edge(new_edge)
            graph.remove_edge(edge.id)
            redirected += 1

            # Also update the combined_write_enable field in the target node's data
            target_node = edge.target
            if 'combined_write_enable' in target_node.data:
                target_node.data['combined_write_enable'] = gated_wr_id
                print(f"      Updated {target_id}.combined_write_enable to {gated_wr_id}")

    print(f"    Created RF WAW hazard detection (redirected {redirected} write enable edges)")


def add_dual_issue_control_hazard_flush(graph: ResourceGraph,
                                        branch_conditions: Optional[Dict[str, str]] = None,
                                        jump_types: Optional[List[str]] = None) -> None:
    """
    Add control hazard flush logic for dual-issue pipeline.

    When P0 executes a taken branch or jump, both P0 and P1 pipeline registers
    must be invalidated in the next cycle (the speculatively fetched instructions
    are from the wrong path).

    This discovers flush components structurally from the PC write mux:
    - Non-default mux_select edges whose source nodes are NOT the "normal flow"
      select (i.e., they select alternative PC destinations) indicate branch/jump paths.
    - These selectors ARE the flush conditions (each represents a taken control transfer).

    The branch_conditions and jump_types parameters are deprecated and ignored.
    All discovery is done from the graph structure.

    Args:
        graph: The merged dual-issue graph (after hazard resolution)
        branch_conditions: DEPRECATED - ignored, kept for API compatibility
        jump_types: DEPRECATED - ignored, kept for API compatibility
    """
    print("\n" + "=" * 70)
    print("ADDING DUAL-ISSUE CONTROL HAZARD FLUSH")
    print("=" * 70)

    import re as _re_flush

    # Structurally discover flush components from the PC write mux.
    # The PC mux has mux_select edges; each non-default input selects an alternative
    # PC destination (branch target, jump target). The "normal flow" select also exists
    # but isn't a flush condition. We identify flush selectors as those whose mux_input
    # sibling differs from the mux default input (i.e., they redirect the PC elsewhere).
    pc_mux = graph.nodes.get('p0_pc_wr_mux')
    if not pc_mux:
        print("  WARNING: p0_pc_wr_mux not found, skipping flush")
        return

    # Find the default input source (the fallthrough/normal-flow PC value)
    default_source_id = None
    for edge in pc_mux.incoming_edges:
        if edge.data.get('type') == 'mux_default_input':
            default_source_id = edge.source.id
            break

    # Collect all mux_select edges and find paired mux_input edges by select_index
    select_edges = []
    input_edges_by_index = {}
    for edge in pc_mux.incoming_edges:
        if edge.data.get('type') == 'mux_select':
            select_edges.append(edge)
        elif edge.data.get('type') == 'mux_input':
            idx = edge.data.get('input_index')
            if idx is not None:
                input_edges_by_index[idx] = edge

    # Flush components: selectors whose mux_input source differs from default
    # (i.e., they redirect the PC to a branch/jump target, not normal flow)
    flush_components = []
    for sel_edge in select_edges:
        sel_idx = sel_edge.data.get('select_index')
        sel_node = sel_edge.source

        # Check if the paired mux_input points to a different destination than default
        paired_input = input_edges_by_index.get(sel_idx)
        if paired_input and paired_input.source.id != default_source_id:
            # This selector redirects PC to a non-default target → control transfer
            flush_components.append(sel_node)
            print(f"  Flush component (from PC mux): {sel_node.id}")
        else:
            print(f"  Normal-flow selector (skipped): {sel_node.id}")

    if not flush_components:
        print("  No flush components found, skipping control hazard flush")
        return

    # Find the P0 valid signal that matches the flush components' pipe_time.
    # The flush components (branch/jump enables) are at the pipeline stage where
    # control-flow decisions happen. The valid signal must be at the SAME stage
    # so that:
    # - The flush fires only when the branch instruction is actually valid
    # - PC mux selectors are correctly gated with the branch instruction's valid
    # - The branch instruction flows through subsequent stages to complete
    #
    # Determine the target pipe_time from the flush components themselves.
    flush_pipe_times = []
    for fc in flush_components:
        pt = getattr(fc, 'pipe_time', None)
        if pt is not None:
            flush_pipe_times.append(pt)
    target_pipe_time = max(flush_pipe_times) if flush_pipe_times else None

    # Build a map of pipe_time -> valid signal
    valid_by_pipe_time = {}
    for node_id, node in graph.nodes.items():
        if _re_flush.match(r'p0_PIPE_\w+_valid_PIPE$', node_id):
            pt = getattr(node, 'pipe_time', None)
            if pt is not None:
                valid_by_pipe_time[pt] = node

    # Select the valid signal matching the flush components' pipe_time.
    # Fall back to the highest pipe_time if no exact match.
    p0_valid = None
    if target_pipe_time is not None and target_pipe_time in valid_by_pipe_time:
        p0_valid = valid_by_pipe_time[target_pipe_time]
    elif valid_by_pipe_time:
        max_pt = max(valid_by_pipe_time.keys())
        p0_valid = valid_by_pipe_time[max_pt]

    if not p0_valid:
        print("  WARNING: No P0 valid signal found, skipping")
        return
    selected_pt = getattr(p0_valid, 'pipe_time', '?')
    print(f"  Found P0 valid signal: {p0_valid.id} (pipe_time={selected_pt}, flush components pipe_time={target_pipe_time})")

    # OR all flush components together
    if len(flush_components) == 1:
        flush_or = flush_components[0]
    else:
        flush_or = _create_or_tree_static(graph, flush_components, 'p0_flush_or')

    # Gate with P0 valid: flush = flush_or && p0_valid
    flush_id = 'p0_control_hazard_flush'
    flush_node = Node(flush_id, data={
        'type': 'operation',
        'operator': '&&',
        'bit_width': 1,
        'name': flush_id,
        'display_name': 'Pipeline flush on control hazard',
    })
    graph.add_node(flush_node)

    edge_or = Edge(flush_or, flush_node, None, {'type': 'left_operand', 'position': 'left'})
    graph.add_edge(edge_or)
    edge_valid = Edge(p0_valid, flush_node, None, {'type': 'right_operand', 'position': 'right'})
    graph.add_edge(edge_valid)

    # Connect flush signal to all valid_PIPE nodes (structurally discovered)
    # These are pipeline validity registers that need flushing on control hazards.
    #
    # IMPORTANT: For pipelines with stages after the flush stage (Execute), we must
    # preserve valid bits for in-flight instructions that should complete:
    #
    # P0 (the flushing pipeline): The instruction at Execute (e.g., JAL) must flow
    # through ALL subsequent stages to complete (e.g., write ret_addr at Writeback).
    # Additionally, instructions from previous pairs that are already in later stages
    # must also complete. So P0's valid bits for ALL stages after Execute are preserved.
    #
    # P1 (the paired pipeline): The instruction at P1 Execute was paired with the
    # flushing P0 instruction and must be cancelled. Flushing P1's immediate successor
    # (e.g., Memory) prevents it from proceeding. However, P1 instructions from previous
    # pairs that are 2+ stages past Execute must complete (they were correctly fetched).
    # So P1 stages 2+ past Execute are preserved.
    #
    # Examples:
    #   4-stage (F/D/X/MW): P0 skip={MW}, P1 skip={}
    #   5-stage (F/D/X/M/W): P0 skip={M,W}, P1 skip={W}
    import re as _re
    flush_stage_match = _re.match(r'p0_PIPE_(\w+)_valid_PIPE', p0_valid.id)
    flush_stage_name = flush_stage_match.group(1) if flush_stage_match else None

    # Build the full successor chain from the flush stage.
    # Find successor stages by looking at pipeline registers: if a node like
    # p0_PIPE_Memory_PIPE_Execute_*_PIPE_PIPE exists, then Memory follows Execute.
    # Then find Memory's successor by looking for p0_PIPE_Writeback_PIPE_Memory_*_PIPE_PIPE, etc.
    successor_chain = []  # ordered list of stage names after the flush stage
    if flush_stage_name:
        current_stage = flush_stage_name
        while True:
            found_next = None
            for node_id in graph.nodes:
                match = _re.match(r'p0_PIPE_(\w+)_PIPE_' + _re.escape(current_stage) + r'_\w+_PIPE_PIPE$', node_id)
                if match:
                    found_next = match.group(1)
                    break
            if found_next and found_next not in successor_chain:
                successor_chain.append(found_next)
                current_stage = found_next
            else:
                break
        if successor_chain:
            print(f"  Flush at {flush_stage_name}, successor chain: {' -> '.join(successor_chain)}")

    # P0: skip ALL successor stages (the flushing instruction and older instructions
    # must complete through these stages)
    p0_skip_valids = set()
    for stage in successor_chain:
        p0_skip_valids.add(f'p0_PIPE_{stage}_valid_PIPE')

    # P1: skip successor stages 2+ past the flush stage. The immediate successor
    # (index 0) is the stage where the paired P1 instruction is — it must be flushed
    # to cancel the P1 instruction that was co-issued with the flushing P0 instruction.
    # Stages 2+ past the flush stage contain older P1 instructions from previous
    # pairs that were correctly fetched and must complete.
    p1_skip_valids = set()
    for stage in successor_chain[1:]:  # skip first successor (flush it), preserve rest
        p1_skip_valids.add(f'p1_PIPE_{stage}_valid_PIPE')

    skip_valids = p0_skip_valids | p1_skip_valids

    flush_count = 0
    for node_id, node in graph.nodes.items():
        if node.data.get('type') == 'validity_bit' or (
            '_PIPE_' in node_id and node_id.endswith('_valid_PIPE')
        ):
            if node_id in skip_valids:
                reason = "P0 flush instruction completes here" if node_id in p0_skip_valids else "P1 previous pair completes here"
                print(f"  SKIP flush -> {node_id} ({reason})")
                continue
            flush_edge = Edge(flush_node, node, None, {'type': 'flush'})
            graph.add_edge(flush_edge)
            flush_count += 1
            print(f"  Connected flush -> {node_id}")

    print(f"  Created {flush_id} signal with {len(flush_components)} components, {flush_count} flush targets")

    # Gate branch/jump PC mux selectors with validity
    # When the instruction is invalidated (flushed), the branch/jump enables
    # still decode from the instruction bits. The PC write mux must ignore
    # these when valid=0, otherwise an invalidated branch will redirect the PC.
    _gate_pc_mux_with_validity(graph, p0_valid)


def _gate_pc_mux_with_validity(graph: ResourceGraph, valid_node: Node) -> None:
    """
    Gate ALL PC mux selectors with the validity signal.

    When an instruction is invalidated by a pipeline flush, its branch/jump enable
    signals still decode from the instruction bits in the pipeline register. Without
    gating, an invalidated branch instruction would incorrectly redirect the PC.

    This discovers all mux_select edges on the PC write mux structurally (no hardcoded
    names) and inserts AND gates between each selector and the mux.
    """
    pc_mux = graph.nodes.get('p0_pc_wr_mux')
    if not pc_mux:
        print("  WARNING: p0_pc_wr_mux not found, skipping validity gating")
        return

    # Discover ALL mux_select edges structurally from the PC mux
    select_edges = [
        edge for edge in list(pc_mux.incoming_edges)
        if edge.data.get('type') == 'mux_select'
    ]

    if not select_edges:
        print("  No mux_select edges found on p0_pc_wr_mux, skipping validity gating")
        return

    for select_edge in select_edges:
        sel_node = select_edge.source
        sel_id = sel_node.id

        # Create gated selector: sel_gated = sel && valid
        gated_id = f'{sel_id}_valid_gated'
        gated_node = Node(gated_id, data={
            'type': 'operation',
            'operator': '&&',
            'bit_width': 1,
            'name': gated_id,
        })
        graph.add_node(gated_node)

        edge_sel = Edge(sel_node, gated_node, None, {'type': 'left_operand', 'position': 'left'})
        graph.add_edge(edge_sel)
        edge_valid = Edge(valid_node, gated_node, None, {'type': 'right_operand', 'position': 'right'})
        graph.add_edge(edge_valid)

        # Replace the mux_select edge: remove old, add new from gated
        graph.remove_edge(select_edge.id)
        new_edge = Edge(gated_node, pc_mux, None, select_edge.data.copy())
        graph.add_edge(new_edge)

        print(f"  Gated PC mux selector {sel_id} with valid")


def _get_bit_slice_low(bit_slice_expr: dict) -> int:
    """Extract the low bit index from a bit_slice expression.

    Handles both formats:
    - {'range': [high, low]} where values may be ints or {'value': int} dicts
    - {'high': ..., 'low': ...} where values may be ints or {'type': 'literal', 'value': int} dicts
    """
    # Format 1: 'range' list
    bit_range = bit_slice_expr.get('range')
    if bit_range:
        low_val = bit_range[1]
        if isinstance(low_val, int):
            return low_val
        if isinstance(low_val, dict):
            return low_val.get('value', -1)
        return -1

    # Format 2: 'low' key
    low_val = bit_slice_expr.get('low')
    if low_val is None:
        return -1
    if isinstance(low_val, int):
        return low_val
    if isinstance(low_val, dict):
        return low_val.get('value', -1)
    return -1


def _create_or_tree_static(graph: ResourceGraph, inputs: List[Node], base_name: str) -> Node:
    """Create an OR tree combining multiple inputs (static function)."""
    if len(inputs) == 1:
        return inputs[0]

    if len(inputs) == 2:
        or_node = Node(base_name, data={
            'type': 'operation',
            'operator': '||',
            'bit_width': 1,
            'name': base_name
        })
        graph.add_node(or_node)
        edge1 = Edge(inputs[0], or_node, None, {'type': 'operand', 'operand_index': 0})
        graph.add_edge(edge1)
        edge2 = Edge(inputs[1], or_node, None, {'type': 'operand', 'operand_index': 1})
        graph.add_edge(edge2)
        return or_node

    # More than 2 - build balanced tree
    mid = len(inputs) // 2
    left = _create_or_tree_static(graph, inputs[:mid], f"{base_name}_l")
    right = _create_or_tree_static(graph, inputs[mid:], f"{base_name}_r")

    or_node = Node(base_name, data={
        'type': 'operation',
        'operator': '||',
        'bit_width': 1,
        'name': base_name
    })
    graph.add_node(or_node)
    edge1 = Edge(left, or_node, None, {'type': 'operand', 'operand_index': 0})
    graph.add_edge(edge1)
    edge2 = Edge(right, or_node, None, {'type': 'operand', 'operand_index': 1})
    graph.add_edge(edge2)
    return or_node


def _get_or_create_constant(graph: ResourceGraph, value: int, width: int, name: str) -> Node:
    """Get or create a constant node."""
    if name in graph.nodes:
        return graph.nodes[name]

    const = Node(name, data={
        'type': 'constant',
        'value': value,
        'bit_width': width,
        'name': name
    })
    graph.add_node(const)
    return const


def _get_instruction_byte_size(graph: ResourceGraph) -> int:
    """
    Derive instruction size in bytes from the graph's instruction variable width.

    Uses the 'instr' node's bit_width (which reflects the ISA's instruction word
    size) rather than the memory word width (which may be wider for data accesses).
    Falls back to 4 if no metadata is available.
    """
    # Primary: use the instruction variable's bit width
    for node_id in ('instr', 'p0_instr', 'p1_instr'):
        node = graph.nodes.get(node_id)
        if node and node.data:
            bw = node.data.get('bit_width')
            if bw and bw > 0:
                return bw // 8
    return 4  # Default: 32-bit instructions = 4 bytes


def _create_pc_increment_mux(graph: ResourceGraph, pc_wr_name: str, lockstep: bool = False) -> None:
    """
    Create the PC increment multiplexer.

    pc_next = pc + pc_increment
    where pc_increment =
        0              if p0_any_stall
        instr_size     if p1_blocked (but not p0_stalled) -- single issue
        instr_size * 2 otherwise                          -- dual issue

    Instruction size is derived from the graph's memory width metadata.
    This is implemented as a nested ternary:
    pc_increment = p0_any_stall ? 0 : (p1_blocked ? instr_size : instr_size*2)
    """
    p0_any_stall = graph.nodes.get('p0_any_stall')
    p1_any_stall = graph.nodes.get('p1_any_stall')
    p1_blocked = graph.nodes.get('p1_blocked')

    if not p0_any_stall or not p1_blocked:
        print("    Warning: Missing stall signals, skipping PC increment mux")
        return

    # Get PC width from existing PC node
    pc_width = 32  # Default
    for node_id, node in graph.nodes.items():
        if 'pc' in node_id.lower() and node.data.get('bit_width'):
            pc_width = node.data['bit_width']
            break

    # Derive instruction byte size from graph metadata
    instr_size = _get_instruction_byte_size(graph)
    dual_instr_size = instr_size * 2
    print(f"    Instruction size: {instr_size} bytes (derived from memory metadata)")

    # Create constants
    const_0 = _get_or_create_constant(graph, 0, pc_width, 'pc_inc_0')
    const_single = _get_or_create_constant(graph, instr_size, pc_width, f'pc_inc_{instr_size}')
    const_dual = _get_or_create_constant(graph, dual_instr_size, pc_width, f'pc_inc_{dual_instr_size}')

    # Create any_pipe_stall = p0_any_stall || p1_any_stall
    # In non-lockstep mode, PC must freeze when EITHER pipeline stalls.
    # In lockstep mode, P0 already includes P1's stalls via cross-coupling.
    if not lockstep and p1_any_stall:
        any_stall_id = 'any_pipe_stall'
        any_pipe_stall = Node(any_stall_id, data={
            'type': 'operation',
            'operator': '||',
            'bit_width': 1,
            'name': any_stall_id,
            'display_name': 'Any Pipeline Stall'
        })
        any_pipe_stall.pipe_time = 0
        graph.add_node(any_pipe_stall)
        graph.add_edge(Edge(p0_any_stall, any_pipe_stall, None, {'type': 'operand', 'operand_index': 0}))
        graph.add_edge(Edge(p1_any_stall, any_pipe_stall, None, {'type': 'operand', 'operand_index': 1}))
        pc_stall_signal = any_pipe_stall
        print(f"    Created {any_stall_id} = p0_any_stall || p1_any_stall")
    else:
        pc_stall_signal = p0_any_stall

    # Inner mux: p1_blocked ? instr_size : dual_instr_size
    inner_mux_id = 'pc_inc_inner_mux'
    inner_mux = Node(inner_mux_id, data={
        'type': 'multiplexer',
        'bit_width': pc_width,
        'name': inner_mux_id,
        'display_name': f'PC Inc (p1_blocked ? {instr_size} : {dual_instr_size})',
        'mux_style': 'ternary'
    })
    graph.add_node(inner_mux)

    # Connect inner mux inputs
    edge_sel_inner = Edge(p1_blocked, inner_mux, None, {'type': 'mux_select', 'select_index': 0})
    graph.add_edge(edge_sel_inner)
    edge_true_inner = Edge(const_single, inner_mux, None, {'type': 'mux_input', 'input_index': 1})
    graph.add_edge(edge_true_inner)
    edge_false_inner = Edge(const_dual, inner_mux, None, {'type': 'mux_default_input'})
    graph.add_edge(edge_false_inner)

    # Outer mux: any_pipe_stall ? 0 : inner_mux
    outer_mux_id = 'pc_increment_mux'
    outer_mux = Node(outer_mux_id, data={
        'type': 'multiplexer',
        'bit_width': pc_width,
        'name': outer_mux_id,
        'display_name': f'PC Increment (0/{instr_size}/{dual_instr_size})',
        'mux_style': 'ternary'
    })
    graph.add_node(outer_mux)

    edge_sel_outer = Edge(pc_stall_signal, outer_mux, None, {'type': 'mux_select', 'select_index': 0})
    graph.add_edge(edge_sel_outer)
    edge_true_outer = Edge(const_0, outer_mux, None, {'type': 'mux_input', 'input_index': 1})
    graph.add_edge(edge_true_outer)
    edge_false_outer = Edge(inner_mux, outer_mux, None, {'type': 'mux_default_input'})
    graph.add_edge(edge_false_outer)

    print(f"    Created {outer_mux_id}: any_pipe_stall ? 0 : (p1_blocked ? {instr_size} : {dual_instr_size})")

    # Step 7: Create p0_pc_add_increment = p0_pc_rd + pc_increment_mux
    # This replaces p0_pc_add_4 for dual-issue PC advancement
    print("\nStep 7: Connecting PC increment to PC advancement...")

    p0_pc_rd = graph.nodes.get('p0_pc_rd')
    p0_pc_add_4 = graph.nodes.get('p0_pc_add_4')

    if not p0_pc_add_4:
        # Try alternative name
        p0_pc_add_4 = graph.nodes.get('p0_(pc + 4)')
        if p0_pc_add_4:
            print("    Found p0_(pc + 4) instead of p0_pc_add_4")

    if p0_pc_rd and outer_mux:
        # Create the adder: p0_pc_add_increment = p0_pc_rd + pc_increment_mux
        add_inc_id = 'p0_pc_add_increment'
        add_inc = Node(add_inc_id, data={
            'type': 'operation',
            'operator': '+',
            'bit_width': pc_width,
            'name': add_inc_id,
            'display_name': 'PC + Increment'
        })
        graph.add_node(add_inc)

        # Connect inputs
        edge_pc = Edge(p0_pc_rd, add_inc, None, {'type': 'left_operand', 'position': 'left'})
        graph.add_edge(edge_pc)
        edge_inc = Edge(outer_mux, add_inc, None, {'type': 'right_operand', 'position': 'right'})
        graph.add_edge(edge_inc)

        print(f"    Created {add_inc_id} = p0_pc_rd + pc_increment_mux")

        # Now redirect all consumers of p0_pc_add_4 to use p0_pc_add_increment instead
        # This handles the normal instruction advancement case
        if p0_pc_add_4:
            # Find all outgoing edges from p0_pc_add_4
            edges_to_redirect = list(p0_pc_add_4.outgoing_edges)
            redirected_count = 0
            for edge in edges_to_redirect:
                target = edge.target
                # Skip pipeline registers - they should capture the original (pc + 4)
                # value at fetch time, not the variable pc_add_increment
                if target.data.get('type') == 'pipeline_register':
                    print(f"    Skipped pipeline register {target.id} (preserving original pc+4)")
                    continue
                # Create new edge from add_inc to the target
                new_edge = Edge(add_inc, target, None, edge.data.copy())
                graph.add_edge(new_edge)
                # Remove old edge - note: remove_edge takes edge_id (string)
                graph.remove_edge(edge.id)
                redirected_count += 1
            print(f"    Redirected {redirected_count} edges from p0_pc_add_4 to p0_pc_add_increment")

        # Also check the PC mux default case - if it uses p0_pc_rd, change to p0_pc_add_increment
        # Find p0_pc_wr_mux and update its default input
        pc_mux_node = graph.nodes.get('p0_pc_wr_mux')
        if pc_mux_node:
            # Find edges from p0_pc_rd to pc_mux that are mux_default_input
            for edge in list(p0_pc_rd.outgoing_edges):
                if (edge.target.id == 'p0_pc_wr_mux' and
                    edge.data.get('type') == 'mux_default_input'):
                    # Redirect to p0_pc_add_increment
                    # Note: remove_edge takes edge_id (string), not edge object
                    new_edge = Edge(add_inc, edge.target, None, edge.data.copy())
                    graph.add_edge(new_edge)
                    graph.remove_edge(edge.id)
                    print(f"    Updated PC mux default input to p0_pc_add_increment")

    # Step 8: Fix branch/jump PC calculations for pipeline
    # In a 2-stage pipeline, when executing a branch/jump, pc has already advanced
    # by 4 for the next fetch. Branch/jump targets should use the instruction's PC,
    # not the next fetch PC.
    print("\nStep 8: Fixing branch/jump PC calculations for pipeline delay...")
    _fix_branch_jump_pc(graph)


def _fix_branch_jump_pc(graph: ResourceGraph) -> None:
    """
    Fix PC-dependent calculations for the pipeline delay in dual-issue.

    In a dual-issue 2-stage pipeline, the PC advances by a variable amount
    (4 or 8) during fetch. When computing branch/jump targets, auipc results,
    and jal/jalr return addresses, we need the instruction's actual PC, not the
    current (already-advanced) fetch PC.

    Solution: Create pipeline registers p0_fetch_pc and p1_fetch_pc that capture
    the fetch-time PC values. These are updated alongside the instruction pipeline
    registers (with the same stall gating).

    - p0_fetch_pc: saves p0_pc_rd, updated each cycle (unless stalled)
    - p1_fetch_pc: p0_fetch_pc + 4 (P1's instruction is always at P0's PC + 4)
    - p0_exec_pc: alias for p0_fetch_pc (used by branch/jump target calculations)
    """
    p0_pc_rd = graph.nodes.get('p0_pc_rd')
    if not p0_pc_rd:
        print("    Warning: p0_pc_rd not found, skipping branch/jump PC fix")
        return

    pc_width = p0_pc_rd.data.get('bit_width', 32)

    # Create p0_fetch_pc pipeline register (saves p0_pc_rd at fetch time)
    fetch_pc_id = 'p0_fetch_pc'
    fetch_pc = Node(fetch_pc_id, data={
        'type': 'pipeline_register',
        'bit_width': pc_width,
        'name': fetch_pc_id,
        'display_name': 'P0 fetch-time PC',
    })
    fetch_pc.pipe_time = 1  # Execute stage
    graph.add_node(fetch_pc)

    # Connect p0_pc_rd -> p0_fetch_pc (pipeline input)
    edge_in = Edge(p0_pc_rd, fetch_pc, None, {'type': 'pipeline_input', 'pipeline_component': True})
    graph.add_edge(edge_in)

    # Connect stall signal to p0_fetch_pc (same stall as instruction pipeline register).
    # Find the P0 stall controller structurally: search for p0_PIPE_*_stall_ctrl nodes
    # and use the one with the lowest pipe_time (earliest execution stage).
    import re as _re_stall
    p0_stall = None
    best_stall_time = float('inf')
    for nid, nd in graph.nodes.items():
        if _re_stall.match(r'p0_PIPE_\w+_stall_ctrl$', nid):
            pt = getattr(nd, 'pipe_time', None)
            if pt is not None and pt < best_stall_time:
                best_stall_time = pt
                p0_stall = nd
    if p0_stall:
        stall_edge = Edge(p0_stall, fetch_pc, None, {'type': 'stall'})
        graph.add_edge(stall_edge)
        print(f"    Connected stall to {fetch_pc_id} (from {p0_stall.id})")

    print(f"    Created {fetch_pc_id} (pipeline register for P0 fetch PC)")

    # Use p0_fetch_pc directly as the execute-stage PC
    # (no alias node needed - avoids Verilog generation issues with unhandled operator types)
    exec_pc = fetch_pc  # redirect target for all PC-dependent execute-stage nodes

    # Create p1_fetch_pc = p0_fetch_pc + instr_size
    instr_size = _get_instruction_byte_size(graph)
    const_instr_size = _get_or_create_constant(graph, instr_size, pc_width, 'pc_pipeline_delay')
    p1_fetch_pc_id = 'p1_fetch_pc'
    p1_fetch_pc = Node(p1_fetch_pc_id, data={
        'type': 'operation',
        'operator': '+',
        'bit_width': pc_width,
        'name': p1_fetch_pc_id,
        'display_name': 'P1 fetch-time PC',
    })
    graph.add_node(p1_fetch_pc)
    e1 = Edge(fetch_pc, p1_fetch_pc, None, {'type': 'left_operand', 'position': 'left'})
    graph.add_edge(e1)
    e2 = Edge(const_instr_size, p1_fetch_pc, None, {'type': 'right_operand', 'position': 'right'})
    graph.add_edge(e2)
    print(f"    Created {p1_fetch_pc_id} = {fetch_pc_id} + {instr_size}")

    # Structurally redirect P0 nodes that read from p0_pc_rd to use p0_fetch_pc.
    # We traverse outgoing edges from p0_pc_rd and redirect all except:
    # - PC infrastructure (fetch_pc register, PC increment adder, P1 PC offset)
    # - Nodes in the fetch path (memory address calculation → instruction memory read)
    #
    # The fetch path is identified by finding nodes that transitively feed into
    # an instruction memory read (array_access of type memory/instruction_memory).
    redirected = 0
    pc_infra_ids = {
        fetch_pc_id,           # p0_fetch_pc - the pipeline register we're creating
        'p0_pc_add_increment', # PC increment adder (needs current pc_rd)
        'p1_pc_plus_4',        # P1's fetch PC offset (needs current pc_rd)
    }

    # In 3+ stage pipelines, (pc + 4) is cut across the F/D pipeline boundary,
    # creating a pipeline register that preserves the fetch-time value. In that
    # case it should NOT be redirected to fetch_pc (it already has the correct value).
    # In 2-stage pipelines, (pc + 4) is NOT pipelined, so it must be redirected
    # to use fetch_pc (since pc_rd has already advanced by execution time).
    pc_add_4_node = graph.nodes.get('p0_(pc + 4)')
    if pc_add_4_node:
        has_pipe_reg = any(
            e.target.data.get('type') == 'pipeline_register'
            for e in pc_add_4_node.outgoing_edges
        )
        if has_pipe_reg:
            pc_infra_ids.add('p0_(pc + 4)')
            pc_infra_ids.add('p0_pc_add_4')
            print(f"    Excluding p0_(pc + 4) from redirect (has pipeline registers)")
        else:
            print(f"    Will redirect p0_(pc + 4) to fetch_pc (no pipeline registers)")

    # Identify fetch-path nodes: those that directly feed into instruction memory reads.
    # The fetch path is short: pc_rd → addr_adj → umem[addr] → instr (2-3 hops).
    # We check if the target node leads to an instruction memory array read within
    # a limited depth (max 3 hops), to avoid traversing the entire graph through
    # shared register file paths.
    imem_names = {'umem', 'imem', 'p0_umem', 'p0_imem', 'p1_umem', 'p1_imem'}

    def _is_fetch_path_node(node, depth=0, max_depth=3):
        """Check if a node is on the instruction fetch path (max 3 hops to imem)."""
        if depth > max_depth:
            return False
        # Is this an instruction memory read from umem/imem?
        ntype = node.data.get('type', '')
        if ntype == 'array_access':
            for e in node.incoming_edges:
                if e.data.get('type') == 'array_base' and e.source.id in imem_names:
                    return True
        # Check immediate downstream (limited depth)
        for edge in node.outgoing_edges:
            if _is_fetch_path_node(edge.target, depth + 1, max_depth):
                return True
        return False

    for edge in list(p0_pc_rd.outgoing_edges):
        target = edge.target
        target_id = target.id

        # Skip PC infrastructure nodes (they need the current fetch PC)
        if target_id in pc_infra_ids:
            continue

        # Skip nodes that aren't in p0's pipeline (shared/p1 nodes)
        if not target_id.startswith('p0_'):
            continue

        # Skip pipeline registers - in 3+ stage pipelines, the pipeline cuts
        # already create pipeline registers for pc_rd that correctly preserve
        # the fetch-time PC through all stages
        if target.data.get('type') == 'pipeline_register':
            print(f"    Skipped pipeline register {target_id} (already pipelined)")
            continue

        # Skip fetch-path nodes (memory address → instruction memory read)
        if _is_fetch_path_node(target):
            print(f"    Skipped fetch-path node {target_id}")
            continue

        # This node reads from p0_pc_rd and is a non-fetch computation.
        # Redirect it to use the pipelined fetch PC instead.
        graph.remove_edge(edge.id)
        new_edge = Edge(exec_pc, target, None, edge.data.copy())
        graph.add_edge(new_edge)
        redirected += 1
        print(f"    Redirected {target_id} to use p0_fetch_pc")

    # Fix return address nodes: should use exec_pc + 4, not pc_add_increment.
    # finalize_pc_advancement() connected ret_addr to pc_add_increment
    # (which is pc_rd + variable_increment), but the return address for jal/jalr
    # should be the instruction's own PC + 4.
    # Discover structurally: find any P0 node with 'ret_addr' in its name.
    ret_addr = None
    for nid in sorted(graph.nodes):
        if nid.startswith('p0_') and 'ret_addr' in nid:
            ret_addr = graph.nodes[nid]
            break
    # Find the (pc + 4) node structurally: a P0 node computing PC + constant
    pc_add_4 = graph.nodes.get('p0_(pc + 4)')
    if not pc_add_4:
        pc_add_4 = graph.nodes.get('p0_pc_add_4')
    if ret_addr and pc_add_4:
        for edge in list(ret_addr.incoming_edges):
            # Redirect from pc_add_increment (variable-width advance) to the
            # fixed pc + instr_size node
            if 'pc_add_increment' in edge.source.id:
                graph.remove_edge(edge.id)
                new_edge = Edge(pc_add_4, ret_addr, None, edge.data.copy())
                graph.add_edge(new_edge)
                redirected += 1
                print(f"    Redirected {ret_addr.id} from {edge.source.id} to {pc_add_4.id}")

    # Redirect P1's PC-dependent execute-stage nodes to use p1_fetch_pc.
    # Structurally: traverse outgoing edges from p1_pc_plus_4 and redirect
    # pipelined (execute-stage) nodes, excluding fetch infrastructure.
    p1_pc_plus_4 = graph.nodes.get('p1_pc_plus_4')
    if p1_pc_plus_4:
        p1_infra_ids = {p1_fetch_pc_id}  # p1_fetch_pc reads from p0_fetch_pc, not p1_pc_plus_4
        for edge in list(p1_pc_plus_4.outgoing_edges):
            target = edge.target
            target_id = target.id

            if target_id in p1_infra_ids:
                continue

            # Skip pipeline registers - already correctly pipelining the PC
            if target.data.get('type') == 'pipeline_register':
                print(f"    Skipped pipeline register {target_id} (already pipelined)")
                continue

            # Skip fetch-path nodes (memory address → instruction memory read)
            if _is_fetch_path_node(target):
                print(f"    Skipped fetch-path node {target_id}")
                continue

            # Redirect to p1_fetch_pc
            graph.remove_edge(edge.id)
            new_edge = Edge(p1_fetch_pc, target, None, edge.data.copy())
            graph.add_edge(new_edge)
            redirected += 1
            print(f"    Redirected {target_id} to use p1_fetch_pc")

    print(f"    Total redirected: {redirected} PC-dependent calculations")
