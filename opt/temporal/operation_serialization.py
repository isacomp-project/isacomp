"""
Operation serialization optimization for ResourceGraphs.

This module implements algorithms to serialize wide operations into narrower
operations over multiple cycles, trading latency for area.
"""

from typing import Dict, List, Set, Tuple, Optional
from core.resource_graph import ResourceGraph, Node, Edge
from opt.isa_state_gating import ISAStateGatingHelper
import math


class SerializationSpec:
    """Specification for operation serialization."""

    def __init__(self, operation_id: str, granularity_bits: int):
        self.operation_id = operation_id  # ID of operation to serialize
        self.granularity_bits = granularity_bits  # Width of serialized operation (power of 2)

        # Validate granularity is power of 2
        if granularity_bits & (granularity_bits - 1) != 0:
            raise ValueError(f"Granularity must be power of 2, got {granularity_bits}")

    def __str__(self):
        return f"Serialize {self.operation_id} to {self.granularity_bits}-bit granularity"


class OperationSerializationTransform:
    """Transforms operations to use serialized implementations."""

    def __init__(self, graph: ResourceGraph):
        self.graph = graph

    def apply_serialization(self, spec: SerializationSpec) -> bool:
        """Apply serialization to a specific operation."""

        print(f"\\nApplying serialization: {spec}")

        # Find the operation to serialize
        target_operation = self.graph.nodes.get(spec.operation_id)
        if not target_operation:
            print(f"  Error: Operation {spec.operation_id} not found")
            return False

        # Accept both 'operation' and 'wide_operation' types
        op_type = target_operation.data.get('type')
        if op_type not in ['operation', 'wide_operation']:
            print(f"  Error: Node {spec.operation_id} is not an operation (type={op_type})")
            return False

        # Analyze the operation
        operation_analysis = self._analyze_operation(target_operation)
        if not operation_analysis['can_serialize']:
            print(f"  Error: Cannot serialize operation: {operation_analysis.get('reason', 'unknown')}")
            return False

        print(f"  Operation analysis: {operation_analysis['operator']} on {operation_analysis['data_width']}-bit data")

        # Calculate serialization parameters
        data_width = operation_analysis['data_width']
        num_cycles = math.ceil(data_width / spec.granularity_bits)

        print(f"  Serializing {data_width}-bit operation into {num_cycles} cycles of {spec.granularity_bits}-bit operations")

        # Create serialized implementation
        self._create_serialized_operation(target_operation, spec, operation_analysis, num_cycles)

        return True

    def _analyze_operation(self, operation: Node) -> Dict:
        """Analyze operation to determine if it can be serialized."""

        expr = operation.data.get('expression', {})
        if expr.get('type') != 'binary_op':
            return {'can_serialize': False, 'reason': 'not a binary operation'}

        operator = expr.get('operator')
        if operator not in ['+', '-', '|', '&', '^']:  # Serializable operations
            return {'can_serialize': False, 'reason': f'operator {operator} not serializable'}

        # Determine data width from operands
        operands = []
        for edge in operation.incoming_edges:
            if edge.data.get('type') == 'operand':
                operands.append(edge.source)

        if len(operands) != 2:
            return {'can_serialize': False, 'reason': f'expected 2 operands, got {len(operands)}'}

        # Assume 32-bit operations for now (could be inferred from operand types)
        data_width = 32

        return {
            'can_serialize': True,
            'operator': operator,
            'operands': operands,
            'data_width': data_width,
            'result_destinations': self._get_result_destinations(operation)
        }

    def _get_result_destinations(self, operation: Node) -> List[Node]:
        """Get nodes that receive the operation result."""
        destinations = []
        for edge in operation.outgoing_edges:
            if edge.data.get('type') == 'assignment':
                destinations.append(edge.target)
        return destinations

    def _create_serialized_operation(self, original_op: Node, spec: SerializationSpec,
                                   analysis: Dict, num_cycles: int):
        """Create serialized implementation of the operation."""

        operator = analysis['operator']
        operands = analysis['operands']
        data_width = analysis['data_width']

        # The serialized operation completes at cycle num_cycles - 1
        final_cycle = num_cycles - 1

        # Create serialization counter
        counter_node = self._create_serialization_counter(spec.operation_id, num_cycles)

        # Create narrow operation unit
        narrow_op_node = self._create_narrow_operation_unit(spec, operator)

        # Create temporary storage for partial results
        partial_result_node = self._create_partial_result_storage(spec, data_width, final_cycle)

        # Create bit slice extraction logic
        slice_nodes = self._create_bit_slice_logic(spec, operands, data_width)

        # Create mux logic to select which slice to process
        self._create_slice_selection_muxes(spec, slice_nodes, narrow_op_node, counter_node, num_cycles)

        # Create result accumulation logic
        completion_node = self._create_result_accumulation(spec, narrow_op_node, partial_result_node,
                                       counter_node, analysis['result_destinations'], num_cycles)

        # Create control logic and enable gating
        self._create_serialization_control(spec, counter_node, num_cycles, completion_node,
                                          analysis['result_destinations'])

        # Update destination nodes to have correct uarch_time (only for ISA state)
        # Intermediate variables can stay at their original timing
        for dest in analysis['result_destinations']:
            if dest.is_arch_state:
                dest.uarch_time = final_cycle
                print(f"    - Updated {dest.id} uarch_time to {final_cycle}")

        # Remove original operation
        self._remove_original_operation(original_op)

        print(f"  Created serialized implementation:")
        print(f"    - Serialization counter: {counter_node.id}")
        print(f"    - Narrow {operator} unit: {narrow_op_node.id} ({spec.granularity_bits}-bit)")
        print(f"    - Partial result storage: {partial_result_node.id}")
        print(f"    - Control logic for {num_cycles} cycles")
        print(f"    - Enable/gating logic: {completion_node.id}")

    def _create_serialization_counter(self, operation_id: str, num_cycles: int) -> Node:
        """Create counter for serialization cycles."""

        counter_name = f"{operation_id}_serial_counter"
        counter_width = math.ceil(math.log2(num_cycles + 1))

        counter_data = {
            'type': 'serialization_counter',
            'name': counter_name,
            'display_name': f"{operation_id} serialization counter",
            'bit_width': counter_width,
            'max_count': num_cycles - 1,
            'operation_id': operation_id
        }

        counter_node = Node(counter_name, counter_data, is_uarch_state=True)
        counter_node.uarch_time = 0  # Counter starts at cycle 0
        self.graph.add_node(counter_node)

        return counter_node

    def _create_narrow_operation_unit(self, spec: SerializationSpec, operator: str) -> Node:
        """Create narrow operation unit."""

        unit_name = f"{spec.operation_id}_narrow_{operator}"

        unit_data = {
            'type': 'narrow_operation_unit',
            'name': unit_name,
            'display_name': f"{spec.granularity_bits}-bit {operator} unit",
            'operation': operator,
            'bit_width': spec.granularity_bits,
            'original_operation': spec.operation_id
        }

        unit_node = Node(unit_name, unit_data, is_uarch_state=True)
        unit_node.uarch_time = 0  # Combinational logic, operates every cycle
        self.graph.add_node(unit_node)

        return unit_node

    def _create_partial_result_storage(self, spec: SerializationSpec, data_width: int, final_cycle: int) -> Node:
        """Create storage for partial results during serialization."""

        storage_name = f"{spec.operation_id}_partial_result"

        storage_data = {
            'type': 'partial_result_storage',
            'name': storage_name,
            'display_name': f"{spec.operation_id} partial result",
            'bit_width': data_width,
            'operation_id': spec.operation_id
        }

        storage_node = Node(storage_name, storage_data, is_uarch_state=True)
        storage_node.uarch_time = final_cycle  # Result ready at final cycle
        self.graph.add_node(storage_node)

        return storage_node

    def _create_bit_slice_logic(self, spec: SerializationSpec, operands: List[Node],
                               data_width: int) -> Dict[str, List[Node]]:
        """Create bit slice extraction logic for operands."""

        slice_nodes = {'operand_a': [], 'operand_b': []}

        num_slices = math.ceil(data_width / spec.granularity_bits)

        for i in range(num_slices):
            low_bit = i * spec.granularity_bits
            high_bit = min((i + 1) * spec.granularity_bits - 1, data_width - 1)

            # Create slice extractors for both operands
            for j, (operand, operand_name) in enumerate(zip(operands, ['operand_a', 'operand_b'])):
                slice_name = f"{spec.operation_id}_{operand_name}_slice_{i}"

                slice_data = {
                    'type': 'bit_slice_extractor',
                    'name': slice_name,
                    'display_name': f"{operand.id}[{high_bit}:{low_bit}]",
                    'source_operand': operand.id,
                    'slice_index': i,
                    'high_bit': high_bit,
                    'low_bit': low_bit,
                    'slice_width': high_bit - low_bit + 1,
                    'operation_id': spec.operation_id
                }

                slice_node = Node(slice_name, slice_data, is_uarch_state=True)
                self.graph.add_node(slice_node)

                # Connect operand to slice extractor
                slice_edge = Edge(operand, slice_node, data={
                    'type': 'bit_slice',
                    'slice_index': i
                })
                self.graph.add_edge(slice_edge)

                slice_nodes[operand_name].append(slice_node)

        print(f"    - Created {num_slices} bit slice extractors for each operand")
        return slice_nodes

    def _create_slice_selection_muxes(self, spec: SerializationSpec, slice_nodes: Dict,
                                     narrow_op: Node, counter: Node, num_cycles: int):
        """Create mux logic to select which bit slice to process based on counter value."""

        # Create muxes for both operands to select the appropriate slice
        for operand_name in ['operand_a', 'operand_b']:
            mux_name = f"{spec.operation_id}_{operand_name}_mux"

            mux_data = {
                'type': 'mux',
                'name': mux_name,
                'display_name': f"{operand_name} slice selector",
                'selector': counter.id,
                'num_inputs': num_cycles,
                'operation_id': spec.operation_id
            }

            mux_node = Node(mux_name, mux_data, is_uarch_state=True)
            self.graph.add_node(mux_node)

            # Connect all slices to the mux
            for i, slice_node in enumerate(slice_nodes[operand_name]):
                slice_edge = Edge(slice_node, mux_node, data={
                    'type': 'mux_input',
                    'input_index': i
                })
                self.graph.add_edge(slice_edge)

            # Connect counter to mux as selector
            selector_edge = Edge(counter, mux_node, data={'type': 'mux_selector'})
            self.graph.add_edge(selector_edge)

            # Connect mux output to narrow operation
            position = 'left' if operand_name == 'operand_a' else 'right'
            mux_to_op_edge = Edge(mux_node, narrow_op, data={
                'type': 'operand',
                'position': position
            })
            self.graph.add_edge(mux_to_op_edge)

        print(f"    - Created slice selection muxes")

    def _create_result_accumulation(self, spec: SerializationSpec, narrow_op: Node,
                                  partial_storage: Node, counter: Node, destinations: List[Node],
                                  num_cycles: int) -> Node:
        """Create result accumulation and final assignment logic. Returns completion node."""

        # Create result accumulator
        accumulator_name = f"{spec.operation_id}_result_accumulator"

        accumulator_data = {
            'type': 'result_accumulator',
            'name': accumulator_name,
            'display_name': f"{spec.operation_id} result accumulator",
            'operation_id': spec.operation_id
        }

        accumulator_node = Node(accumulator_name, accumulator_data, is_uarch_state=True)
        accumulator_node.uarch_time = 0  # Accumulates results every cycle
        self.graph.add_node(accumulator_node)

        # Connect narrow operation to accumulator
        narrow_edge = Edge(narrow_op, accumulator_node, data={
            'type': 'partial_result',
            'operation_id': spec.operation_id
        })
        self.graph.add_edge(narrow_edge)

        # Connect accumulator to partial storage
        storage_edge = Edge(accumulator_node, partial_storage, data={
            'type': 'accumulation',
            'operation_id': spec.operation_id
        })
        self.graph.add_edge(storage_edge)

        # Create completion signal node
        completion_name = f"{counter.id}_complete"
        completion_data = {
            'type': 'serialization_completion',
            'name': completion_name,
            'display_name': f"{spec.operation_id} serialization complete",
            'counter_id': counter.id,
            'max_count': num_cycles - 1,
            'operation_id': spec.operation_id
        }

        completion_node = Node(completion_name, completion_data, is_uarch_state=True)
        completion_node.uarch_time = num_cycles - 1  # Fires at final cycle
        self.graph.add_node(completion_node)

        # Connect counter to completion signal
        completion_edge = Edge(counter, completion_node, data={
            'type': 'completion_check',
            'condition': f"{counter.id} == {num_cycles - 1}"
        })
        self.graph.add_edge(completion_edge)

        # Connect partial storage to final destinations (NO longer inline gating - will add proper enable edges)
        for dest in destinations:
            final_edge = Edge(partial_storage, dest, data={
                'type': 'serialized_result',
                'operation_id': spec.operation_id
            })
            self.graph.add_edge(final_edge)

        print(f"    - Created result accumulation logic")
        return completion_node

    def _create_serialization_control(self, spec: SerializationSpec, counter: Node, num_cycles: int,
                                     completion_node: Node, destinations: List[Node]):
        """Create control logic for serialization with proper enable/gating nodes."""

        final_cycle = num_cycles - 1

        # Use shared ISA gating helper
        gating_helper = ISAStateGatingHelper(self.graph)

        # Create enable comparator and gate all ISA writes
        enable_node = gating_helper.gate_all_isa_writes_for_operation(
            operation_id=spec.operation_id,
            counter_node=counter,
            final_cycle=final_cycle,
            enable_type='serialization_enable'
        )

        print(f"    - Created enable condition: {enable_node.id}")
        print(f"    - Created enable/gating control (fires when counter == {final_cycle})")

    def _remove_original_operation(self, operation: Node):
        """Remove the original wide operation."""

        print(f"    - Removing original operation: {operation.id}")

        # Remove all edges
        edges_to_remove = list(operation.incoming_edges) + list(operation.outgoing_edges)
        for edge in edges_to_remove:
            edge.remove_from_nodes()
            if edge.id in self.graph.edges:
                del self.graph.edges[edge.id]

        # Remove node
        if operation.id in self.graph.nodes:
            del self.graph.nodes[operation.id]


def apply_operation_serialization(graph: ResourceGraph, serialization_specs: List[SerializationSpec]) -> bool:
    """
    Apply operation serialization to a ResourceGraph.

    Args:
        graph: ResourceGraph to transform
        serialization_specs: List of serialization specifications

    Returns:
        True if any operations were serialized, False otherwise
    """
    transform = OperationSerializationTransform(graph)

    serialized_any = False
    for spec in serialization_specs:
        if transform.apply_serialization(spec):
            serialized_any = True

    # Re-infer uarch_time to propagate timing changes throughout the graph
    if serialized_any:
        print("\nRe-inferring uarch_time after serialization...")
        graph.infer_uarch_time()
        print("Uarch_time inference complete")

    return serialized_any


def create_example_serialization_specs() -> List[SerializationSpec]:
    """Create example serialization specifications."""

    return [
        SerializationSpec("(r1 + r2)", 8),      # Serialize 32-bit add to 8-bit granularity
        SerializationSpec("(r1 | r2)", 4),     # Serialize 32-bit OR to 4-bit granularity
    ]