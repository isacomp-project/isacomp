"""
Unified operation sharing optimization for ResourceGraphs.

Supports two modes:
- SPATIAL: Mux-based sharing within a single cycle (operand muxes + gated results)
- TEMPORAL: Time-multiplexed sharing across cycles (counter + pipeline registers + ISA gating)
"""

from enum import Enum
from typing import Dict, List, Optional
from core.resource_graph import ResourceGraph, Node, Edge
from core.mux_utils import MuxBuilder, MuxType
from opt.isa_state_gating import ISAStateGatingHelper


class SharingMode(Enum):
    SPATIAL = "spatial"
    TEMPORAL = "temporal"


class OperationSharingTransform:
    """Unified operation sharing: spatial (mux-based) or temporal (counter-based)."""

    def __init__(self, graph: ResourceGraph, mode: SharingMode = SharingMode.SPATIAL):
        self.graph = graph
        self.mode = mode
        self.shared_resources: Dict[str, List[Node]] = {}
        self.uarch_counter: Optional[Node] = None

    # ------------------------------------------------------------------ #
    #  Validate designer-selected nodes for sharing
    # ------------------------------------------------------------------ #

    def select_nodes_for_sharing(
        self,
        selected_node_ids: List[str],
    ) -> Dict[str, List[Node]]:
        """Validate designer-selected nodes for sharing.

        The designer explicitly specifies which nodes to share — isacomp does
        not automatically discover sharing opportunities.

        Args:
            selected_node_ids: Node IDs the designer wants to share.

        Returns:
            Dict mapping a resource key to the validated list of nodes.
        """
        return self._validate_selection(selected_node_ids)

    def _validate_selection(self, selected_node_ids: List[str]) -> Dict[str, List[Node]]:
        if len(selected_node_ids) < 2:
            print(f"Need at least 2 nodes for sharing (got {len(selected_node_ids)})")
            return {}

        selected_nodes = []
        node_type = None
        operator = None

        for node_id in selected_node_ids:
            if node_id not in self.graph.nodes:
                print(f"Node {node_id} not found in graph")
                return {}
            node = self.graph.nodes[node_id]
            selected_nodes.append(node)

            current_type = node.data.get('type')
            if node_type is None:
                node_type = current_type
                if current_type == 'operation':
                    operator = node.data.get('operator') or node.data.get('expression', {}).get('operator')
            else:
                if current_type != node_type:
                    print(f"Selected nodes must be of the same type (got {node_type} and {current_type})")
                    return {}
                if current_type == 'operation':
                    current_op = node.data.get('operator') or node.data.get('expression', {}).get('operator')
                    if current_op != operator:
                        print(f"Selected operations must have the same operator (got {operator} and {current_op})")
                        return {}

        # For spatial sharing, verify mutual exclusivity via instruction enables.
        # Operations from different instructions are mutually exclusive because
        # instructions are 1-hot decoded — only one fires per cycle.
        if self.mode == SharingMode.SPATIAL:
            if not self._check_mutual_exclusivity(selected_nodes):
                return {}

        key = f"{node_type}_{operator}" if operator else node_type
        self.shared_resources = {key: selected_nodes}
        return self.shared_resources

    def _get_instruction_set(self, node: Node) -> set:
        """Get the set of instructions that can activate a node.

        For single-instruction nodes, returns {instruction_name}.
        For shared nodes (active across multiple instructions), returns the
        set of all instructions that use the node.
        """
        instruction = node.data.get('instruction')
        if instruction and instruction != 'shared':
            return {instruction}

        # For shared/unlabelled nodes, look at the enable signal to find
        # which instructions gate this node.
        enable_signal_str = self._get_instruction_enable(node)
        enable_node = self.graph.nodes.get(enable_signal_str)
        if enable_node:
            enable_type = enable_node.data.get('type', '')
            if enable_type == 'logical_or':
                # OR of multiple instruction enables
                source_instrs = enable_node.data.get('source_instructions', [])
                if source_instrs:
                    return set(source_instrs)
                instrs = set()
                for edge in enable_node.incoming_edges:
                    if edge.source.id.endswith('_enable'):
                        instrs.add(edge.source.id[:-7])
                if instrs:
                    return instrs

        # If we can't determine the instruction set, the node could
        # potentially be active in any cycle — not safe to assume exclusive.
        return set()

    def _check_mutual_exclusivity(self, operations: List[Node]) -> bool:
        """Verify that operations are mutually exclusive for spatial sharing.

        Operations are mutually exclusive when their instruction enable sets
        don't overlap.  Since instructions are 1-hot decoded, operations from
        different instructions can never fire simultaneously.

        Returns True if all operations are pairwise mutually exclusive.
        """
        instruction_sets = []
        for op in operations:
            instr_set = self._get_instruction_set(op)
            if not instr_set:
                instr = op.data.get('instruction', 'shared')
                print(f"Cannot determine instruction set for {op.id} "
                      f"(instruction={instr}) — cannot verify mutual exclusivity")
                return False
            instruction_sets.append((op, instr_set))

        # Pairwise overlap check.
        for i, (op_a, set_a) in enumerate(instruction_sets):
            for j, (op_b, set_b) in enumerate(instruction_sets):
                if j <= i:
                    continue
                overlap = set_a & set_b
                if overlap:
                    print(f"Operations {op_a.id} and {op_b.id} are NOT mutually exclusive "
                          f"— both active for instruction(s): {overlap}")
                    return False

        return True

    # ------------------------------------------------------------------ #
    #  Apply (dispatches to spatial or temporal)
    # ------------------------------------------------------------------ #

    def apply(self, resource_key: Optional[str] = None) -> bool:
        """Apply sharing to validated operations.

        Args:
            resource_key: Specific key from select_nodes_for_sharing().
                          If None, applies to all validated groups.

        Returns:
            True if any sharing was applied.
        """
        if not self.shared_resources:
            return False

        keys = [resource_key] if resource_key else list(self.shared_resources.keys())
        shared_any = False

        for key in keys:
            if key not in self.shared_resources:
                continue
            operations = self.shared_resources[key]
            if len(operations) < 2:
                continue

            # Infer operator from key or operations
            operator = self._infer_operator(operations, key)

            print(f"\nSharing {len(operations)} '{operator}' operations ({self.mode.value} mode):")
            for op in operations:
                instruction = op.data.get('instruction', 'shared')
                print(f"  {op.data.get('display_name', op.id)} [{instruction}]")

            if self.mode == SharingMode.SPATIAL:
                if self._apply_spatial_sharing(operations, operator):
                    shared_any = True
            else:
                if self._apply_temporal_sharing(key, operations):
                    shared_any = True

        return shared_any

    def _infer_operator(self, operations: List[Node], key: str) -> str:
        """Infer the operator from operations or resource key."""
        for op in operations:
            operator = op.data.get('operator')
            if operator:
                return operator
            expr = op.data.get('expression', {})
            if expr.get('type') == 'binary_op':
                return expr.get('operator', '?')
        # Fallback: parse from key like "operation_+"
        if key.startswith("operation_"):
            return key[len("operation_"):].split("_to_")[0]
        return '?'

    # ------------------------------------------------------------------ #
    #  Shared utilities
    # ------------------------------------------------------------------ #

    def _analyze_operands(self, operations: List[Node]) -> Dict:
        """Analyze operand patterns to determine shared vs muxed positions."""
        operand_sets = []
        for op in operations:
            operands = [e.source for e in op.incoming_edges if e.data.get('type') == 'operand']
            operand_sets.append(operands)

        if not operand_sets:
            return {'can_share': False}

        operand_counts = [len(ops) for ops in operand_sets]
        if len(set(operand_counts)) > 1:
            return {'can_share': False, 'reason': 'different operand counts'}

        num_operands = operand_counts[0]
        shared_operands = []
        muxed_operands = []

        for pos in range(num_operands):
            operands_at_pos = [op_set[pos] for op_set in operand_sets]
            if all(op.id == operands_at_pos[0].id for op in operands_at_pos):
                shared_operands.append((pos, operands_at_pos[0]))
            else:
                muxed_operands.append((pos, operands_at_pos))

        return {
            'can_share': True,
            'num_operands': num_operands,
            'shared_operands': shared_operands,
            'muxed_operands': muxed_operands,
            'operations': operations,
        }

    def _get_instruction_enable(self, operation: Node) -> str:
        """Get the instruction enable signal for an operation."""
        instruction = operation.data.get('instruction', 'shared')
        if instruction == 'shared':
            return 'default_enable'
        return f"{instruction}_enable"

    def _get_node_width(self, node: Node) -> int:
        """Get the bit width of a node, with fallback to 32."""
        if 'bit_width' in node.data and node.data['bit_width'] is not None:
            return node.data['bit_width']
        if 'width' in node.data and node.data['width'] is not None:
            return node.data['width']
        if node.data.get('type') == 'bit_slice':
            expr = node.data.get('expression', {})
            if 'range' in expr:
                high, low = expr['range']
                return high - low + 1
        if 'dimensions' in node.data:
            dims = node.data['dimensions']
            if dims and len(dims) > 0:
                high, low = dims[0]
                return high - low + 1
        return 32

    def _remove_operation_node(self, operation: Node):
        """Remove an original operation node and its edges."""
        print(f"    Removing original operation: {operation.id}")
        edges_to_remove = list(operation.incoming_edges) + list(operation.outgoing_edges)
        for edge in edges_to_remove:
            edge.remove_from_nodes()
            if edge.id in self.graph.edges:
                del self.graph.edges[edge.id]
        if operation.id in self.graph.nodes:
            del self.graph.nodes[operation.id]

    # ================================================================== #
    #  SPATIAL SHARING (mux-based, single cycle)
    # ================================================================== #

    def _apply_spatial_sharing(self, operations: List[Node], operator: str) -> bool:
        """Create a shared op with MuxBuilder operand muxes and gated result routing."""
        analysis = self._analyze_operands(operations)
        if not analysis['can_share']:
            print(f"  Cannot share '{operator}' operations - {analysis.get('reason', 'incompatible operand patterns')}")
            return False

        # Create shared operation node
        shared_op_name = f"shared_{operator}_op"
        shared_op_data = {
            'type': 'operation',
            'name': shared_op_name,
            'display_name': f"shared {operator}",
            'operation': operator,
            'expression': {
                'type': 'binary_op',
                'operator': operator,
                'left': {'type': 'identifier', 'name': 'operand1'},
                'right': {'type': 'identifier', 'name': 'operand2'},
            },
        }
        shared_op_node = Node(shared_op_name, shared_op_data)
        self.graph.add_node(shared_op_node)
        print(f"  Created shared operation: {shared_op_name}")

        # Wire operands
        self._create_operand_connections(shared_op_node, analysis, operations)

        # Route results
        self._route_shared_results(shared_op_node, operations)

        # Remove originals
        for op in operations:
            self._remove_operation_node(op)

        return True

    def _create_operand_connections(self, shared_op: Node, analysis: Dict, operations: List[Node]):
        """Create operand connections for shared operation."""
        for pos, operand_node in analysis['shared_operands']:
            operand_name = f"operand{pos + 1}"
            edge = Edge(operand_node, shared_op, data={
                'type': 'operand',
                'operand_position': pos,
                'operand_name': operand_name,
            })
            self.graph.add_edge(edge)
            print(f"    Shared operand {pos + 1}: {operand_node.id}")

        for pos, operand_list in analysis['muxed_operands']:
            mux_name = f"operand{pos + 1}_mux"
            self._create_operand_mux(mux_name, operand_list, operations, shared_op, pos)

    def _create_operand_mux(self, mux_name: str, operand_list: List[Node],
                            operations: List[Node], shared_op: Node, pos: int):
        """Create operand multiplexer using MuxBuilder."""
        builder = MuxBuilder(self.graph, mux_name, MuxType.ONE_HOT)
        mux_node = builder.create_or_get_mux(display_name=mux_name)
        mux_node.data['operand_position'] = pos
        mux_node.is_uarch_state = True
        print(f"    Created operand mux: {mux_name}")

        for i, (operand_node, operation) in enumerate(zip(operand_list, operations)):
            enable_signal_str = self._get_instruction_enable(operation)
            enable_node = self.graph.nodes.get(enable_signal_str)

            if enable_node:
                builder.add_input(
                    source=operand_node,
                    select=enable_node,
                    input_index=i,
                    metadata={'enable_signal': enable_signal_str},
                )
            else:
                builder.add_input(
                    source=operand_node,
                    select=f"{enable_signal_str} == 1",
                    input_index=i,
                    metadata={'enable_signal': enable_signal_str},
                )
            print(f"      Input {i}: {operand_node.id} (when {enable_signal_str})")

        builder.connect_output(shared_op, 'operand',
                               metadata={'operand_position': pos, 'operand_name': f"operand{pos + 1}"})

    def _route_shared_results(self, shared_op: Node, operations: List[Node]):
        """Route shared operation result to all original destinations."""
        result_destinations = []
        for operation in operations:
            for edge in operation.outgoing_edges:
                if edge.data.get('type') == 'assignment':
                    result_destinations.append((edge.target, operation))

        print(f"    Routing shared result to {len(result_destinations)} destinations:")

        for dest_node, orig_operation in result_destinations:
            enable_signal = self._get_instruction_enable(orig_operation)
            result_edge = Edge(shared_op, dest_node, data={
                'type': 'assignment',
                'gated_by': enable_signal,
                'original_operation': orig_operation.id,
            })
            self.graph.add_edge(result_edge)
            dest_instruction = dest_node.data.get('instruction', 'shared')
            print(f"      -> {dest_node.id} [{dest_instruction}] (when {enable_signal})")

    # ================================================================== #
    #  TEMPORAL SHARING (counter-based, multi-cycle)
    # ================================================================== #

    def _apply_temporal_sharing(self, resource_key: str, operations: List[Node]) -> bool:
        """Insert counter, pipeline registers, ISA state gating."""
        num_sharers = len(operations)

        # Step 1: Create uarch counter
        self._create_uarch_counter(num_sharers)

        # Step 2: Insert timing cuts before each resource usage
        for i, node in enumerate(operations):
            self._insert_timing_cut_before(node, i)

        # Step 3: Insert timing cuts after each resource usage (except the last)
        for i, node in enumerate(operations):
            if i < num_sharers - 1:
                self._insert_timing_cut_after(node, i)

        # Step 4: Add control edges from counter to shared operations
        self._add_counter_control_edges(operations)

        # Step 5: Gate ISA state updates
        self._gate_isa_state_updates(num_sharers)

        # Step 6: Re-infer timing
        self.graph.infer_uarch_time()

        # Step 7: Set proper timing for shared resources
        self._set_shared_resource_timing(operations, num_sharers)

        return True

    def _create_uarch_counter(self, max_count: int):
        """Create a uarch counter that counts from 0 to max_count-1."""
        counter_data = {
            'type': 'uarch_counter',
            'name': 'uarch_cycle_counter',
            'display_name': 'uarch_cycle_counter',
            'bit_width': (max_count - 1).bit_length() + 1,
            'max_value': max_count - 1,
        }
        self.uarch_counter = Node('uarch_cycle_counter', counter_data, is_uarch_state=True)
        self.graph.add_node(self.uarch_counter)

        counter_increment = Node('counter_increment', {
            'type': 'operation',
            'operator': '+',
            'display_name': 'Counter Increment',
            'bit_width': counter_data['bit_width'],
        })
        self.graph.add_node(counter_increment)

        one_literal = Node('counter_one', {
            'type': 'literal',
            'value': 1,
            'display_name': '1',
            'bit_width': counter_data['bit_width'],
        })
        self.graph.add_node(one_literal)

        self.graph.add_edge(Edge(self.uarch_counter, counter_increment, data={'type': 'operand'}))
        self.graph.add_edge(Edge(one_literal, counter_increment, data={'type': 'operand'}))
        self.graph.add_edge(Edge(counter_increment, self.uarch_counter, data={'type': 'assignment'}))

        print(f"Created uarch counter: {self.uarch_counter.id} (0 to {max_count - 1})")

    def _add_counter_control_edges(self, resource_nodes: List[Node]):
        """Add control edges from counter to shared operations."""
        if not self.uarch_counter:
            return

        for i, resource_node in enumerate(resource_nodes):
            if resource_node.data:
                resource_node.data['shared_resource'] = True
                resource_node.data['time_slot'] = i
                resource_node.data['display_name'] = f"Shared {resource_node.data.get('display_name', resource_node.id)} [slot {i}]"

            control_edge = Edge(self.uarch_counter, resource_node, data={
                'type': 'resource_control',
                'time_slot': i,
                'condition': f"counter == {i}",
            })
            self.graph.add_edge(control_edge)

    def _insert_timing_cut_before(self, resource_node: Node, time_slot: int):
        """Insert uarch_state registers before a resource node."""
        input_edges = list(resource_node.incoming_edges)

        for edge in input_edges:
            source_node = edge.source
            edge_data = edge.data.copy()

            source_width = self._get_node_width(source_node)
            reg_name = f"{source_node.id}_t{time_slot}_reg"
            reg_data = {
                'type': 'uarch_state',
                'name': reg_name,
                'display_name': reg_name,
                'bit_width': source_width,
                'time_slot': time_slot,
            }

            pipeline_reg = Node(reg_name, reg_data, is_uarch_state=True)
            self.graph.add_node(pipeline_reg)

            self.graph.remove_edge(edge.id)

            self.graph.add_edge(Edge(source_node, pipeline_reg, data={'type': 'pipeline_stage'}))
            self.graph.add_edge(Edge(pipeline_reg, resource_node, data=edge_data))

            print(f"  Inserted pipeline register {reg_name} before {resource_node.id}")

    def _insert_timing_cut_after(self, resource_node: Node, time_slot: int):
        """Insert uarch_state registers after a resource node to hold results."""
        output_edges = list(resource_node.outgoing_edges)

        for edge in output_edges:
            target_node = edge.target
            edge_data = edge.data.copy()

            reg_name = f"{resource_node.id}_result_t{time_slot}_reg"
            reg_data = {
                'type': 'uarch_state',
                'name': reg_name,
                'display_name': reg_name,
                'bit_width': self._get_node_width(resource_node),
                'time_slot': time_slot,
            }

            result_reg = Node(reg_name, reg_data, is_uarch_state=True)
            self.graph.add_node(result_reg)

            self.graph.remove_edge(edge.id)

            self.graph.add_edge(Edge(resource_node, result_reg, data={'type': 'result_capture'}))
            self.graph.add_edge(Edge(result_reg, target_node, data=edge_data))

            print(f"  Inserted result register {reg_name} after {resource_node.id}")

    def _gate_isa_state_updates(self, num_sharers: int):
        """Gate ISA state updates to only occur when counter reaches max."""
        if not self.uarch_counter:
            return

        final_cycle = num_sharers - 1
        gating_helper = ISAStateGatingHelper(self.graph)

        enable_node = gating_helper.gate_all_isa_writes_for_operation(
            operation_id='resource_sharing',
            counter_node=self.uarch_counter,
            final_cycle=final_cycle,
            enable_type='resource_sharing_enable',
        )

        print(f"  Created enable condition: {enable_node.id}")

    def _set_shared_resource_timing(self, resource_nodes: List[Node], num_sharers: int):
        """Set appropriate timing for shared resources and related nodes."""
        if self.uarch_counter:
            self.uarch_counter.uarch_time = 0

        for i, resource_node in enumerate(resource_nodes):
            resource_node.uarch_time = i
            print(f"  Set {resource_node.id} timing to {i} (time slot)")

        # Set timing for pipeline registers
        for node in self.graph.nodes.values():
            if node.data.get('type') == 'uarch_state' and '_t' in node.id:
                try:
                    if '_t' in node.id and '_reg' in node.id and 'result' not in node.id:
                        slot_part = node.id.split('_t')[1].split('_')[0]
                        time_slot = int(slot_part)
                        node.uarch_time = time_slot
                        print(f"  Set {node.id} timing to {time_slot} (input register)")
                    elif 'result_t' in node.id and '_reg' in node.id:
                        slot_part = node.id.split('_t')[1].split('_')[0]
                        time_slot = int(slot_part)
                        node.uarch_time = time_slot + 1
                        print(f"  Set {node.id} timing to {time_slot + 1} (result register)")
                except (ValueError, IndexError):
                    node.uarch_time = 0

        # Counter increment logic at time 0
        for node in self.graph.nodes.values():
            if (node.data.get('type') == 'operation' and
                    node.data.get('display_name') == 'Counter Increment'):
                node.uarch_time = 0
            elif node.data.get('type') == 'literal' and node.id == 'counter_one':
                node.uarch_time = 0

        # ISA state updates: set to latest incoming time
        for node in self.graph.nodes.values():
            source_node = None
            max_incoming_time = None

            for edge in node.incoming_edges:
                if edge.data.get('type') != 'assignment':
                    continue
                if 'result' in edge.source.id and 'reg' in edge.source.id:
                    result_reg = edge.source
                    operation_node = None
                    for result_edge in result_reg.incoming_edges:
                        if result_edge.source.data.get('type') == 'operation':
                            operation_node = result_edge.source
                            break
                    if operation_node:
                        source_node = operation_node
                        if max_incoming_time is None or operation_node.uarch_time > max_incoming_time:
                            max_incoming_time = operation_node.uarch_time
                    else:
                        print(f"  WARNING: Could not find operation for result register {result_reg.id}")
                        source_node = result_reg
                        if max_incoming_time is None or result_reg.uarch_time > max_incoming_time:
                            max_incoming_time = result_reg.uarch_time
                elif edge.source.data.get('type') == 'operation':
                    source_node = edge.source
                    if max_incoming_time is None or edge.source.uarch_time > max_incoming_time:
                        max_incoming_time = edge.source.uarch_time
                elif edge.source.data.get('type') == 'bit_slice' and edge.source.uarch_time is not None:
                    if max_incoming_time is None or edge.source.uarch_time > max_incoming_time:
                        max_incoming_time = edge.source.uarch_time
                        source_node = edge.source
                elif edge.source.uarch_time is not None:
                    if max_incoming_time is None or edge.source.uarch_time > max_incoming_time:
                        max_incoming_time = edge.source.uarch_time
                        source_node = edge.source

            if max_incoming_time is not None:
                if node.uarch_time is None or node.uarch_time < max_incoming_time:
                    node.uarch_time = max_incoming_time
                    source_type = "result register" if source_node and 'reg' in source_node.id else \
                                 "bit slice" if source_node and source_node.data.get('type') == 'bit_slice' else \
                                 "aggregate" if source_node and any(e.data.get('type') == 'bit_access' for e in source_node.outgoing_edges) else \
                                 "operation"
                    source_id = source_node.id if source_node else "multiple sources"
                    print(f"  Set {node.id} timing to {max_incoming_time} (ISA state update, same as {source_type} {source_id})")

        # Aggregate variables with bit_access edges
        for node in self.graph.nodes.values():
            if node.uarch_time is None or node.uarch_time == 0:
                bit_slice_targets = [e.target for e in node.outgoing_edges if e.data.get('type') == 'bit_access']
                if bit_slice_targets:
                    max_slice_time = max((t.uarch_time for t in bit_slice_targets if t.uarch_time is not None), default=None)
                    if max_slice_time is not None and max_slice_time > 0:
                        node.uarch_time = max_slice_time
                        print(f"  Set {node.id} timing to {max_slice_time} (aggregate of bit slices)")

        # Propagate timing to unset nodes
        for node in self.graph.nodes.values():
            if node.uarch_time is None:
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'assignment' and edge.source.uarch_time is not None:
                        node.uarch_time = edge.source.uarch_time
                        print(f"  Set {node.id} timing to {edge.source.uarch_time} (updated from {edge.source.id})")
                        break

        # Final pass: nodes at 0 depending on aggregates
        for node in self.graph.nodes.values():
            if node.uarch_time == 0:
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'assignment' and edge.source.uarch_time is not None and edge.source.uarch_time > 0:
                        is_aggregate = any(e.data.get('type') == 'bit_access' for e in edge.source.outgoing_edges)
                        if is_aggregate:
                            node.uarch_time = edge.source.uarch_time
                            print(f"  Set {node.id} timing to {edge.source.uarch_time} (updated from aggregate {edge.source.id})")
                            break

        final_time = max((n.uarch_time for n in self.graph.nodes.values() if n.uarch_time is not None), default=0)
        print(f"  Resource sharing sequence: 0 to {final_time} cycles")

    # ------------------------------------------------------------------ #
    #  Summary
    # ------------------------------------------------------------------ #

    def get_transformation_summary(self) -> str:
        """Generate a summary of the sharing transformation."""
        summary = f"Operation Sharing Summary ({self.mode.value} mode):\n"
        summary += "=" * 50 + "\n\n"

        if not self.shared_resources:
            summary += "No shareable resources identified.\n"
            return summary

        for resource_key, nodes in self.shared_resources.items():
            summary += f"Resource: {resource_key}\n"
            summary += f"  Shared across {len(nodes)} instances:\n"
            for node in nodes:
                summary += f"    - {node.id}\n"
            summary += "\n"

        if self.uarch_counter:
            max_val = self.uarch_counter.data.get('max_value', 0)
            summary += f"Uarch Counter: {self.uarch_counter.id} (0 to {max_val})\n"
            summary += f"ISA updates gated to occur only when counter = {max_val}\n\n"

        max_time = self.graph.get_max_uarch_time()
        summary += f"Pipeline depth after sharing: {max_time} cycles\n"

        for time in range(max_time + 1):
            nodes_at_time = self.graph.get_nodes_at_time(time)
            summary += f"  Time {time}: {len(nodes_at_time)} nodes\n"

        return summary


# ====================================================================== #
#  Module-level entry points (single unified API)
# ====================================================================== #

def apply_operation_sharing(graph: ResourceGraph,
                            selected_node_ids: List[str],
                            mode: SharingMode = SharingMode.SPATIAL) -> bool:
    """Apply operation sharing to designer-selected nodes.

    The designer explicitly specifies which nodes to share — isacomp
    validates the selection and applies sharing, but does not automatically
    discover sharing opportunities.

    Args:
        graph: ResourceGraph to optimise.
        selected_node_ids: Node IDs the designer wants to share.
        mode: SPATIAL (mux-based, single cycle) or TEMPORAL (counter-based, multi-cycle).

    Returns:
        True if sharing was applied.
    """
    transform = OperationSharingTransform(graph, mode)
    resources = transform.select_nodes_for_sharing(selected_node_ids)
    if not resources:
        return False

    success = transform.apply()

    if success and mode == SharingMode.TEMPORAL:
        print("\nTransformation Summary:")
        print(transform.get_transformation_summary())

    return success
