"""
Shared ISA state gating logic for resource optimizations.

This module provides common functionality for gating ISA state writes to ensure
atomicity of multi-cycle operations (serialization, multi-cycle latency, resource sharing).
"""

import re
from typing import Dict, List, Optional
from core.resource_graph import ResourceGraph, Node, Edge


def sanitize_identifier(identifier: str) -> str:
    """Convert an identifier to a valid Verilog/VHDL identifier."""
    sanitized = identifier
    sanitized = sanitized.replace('(', '_').replace(')', '_')
    sanitized = sanitized.replace('[', '_').replace(']', '_')
    sanitized = sanitized.replace(',', '_').replace(' ', '_')
    sanitized = sanitized.replace('.', '_').replace("'", '_')
    sanitized = sanitized.replace('{', '_').replace('}', '_')
    sanitized = re.sub(r'_+', '_', sanitized)
    sanitized = sanitized.rstrip('_')
    return sanitized


class ISAStateGatingHelper:
    """Helper class for creating ISA state write gating logic."""

    def __init__(self, graph: ResourceGraph):
        self.graph = graph

    def create_enable_comparator(self,
                                 operation_id: str,
                                 counter_node: Node,
                                 final_value: int,
                                 enable_type: str = 'generic') -> Node:
        """
        Create an enable comparator that checks if counter == final_value.

        Args:
            operation_id: ID of the operation being gated
            counter_node: Counter/cycle tracker node to compare
            final_value: Value to compare against (when to enable)
            enable_type: Type label for the enable (e.g., 'serialization_enable', 'multi_cycle_enable')

        Returns:
            The created enable comparator node
        """
        safe_id = sanitize_identifier(operation_id)
        enable_node_id = f"{safe_id}_enable"

        # Create or reuse literal node for final value
        literal_id = str(final_value)
        if literal_id not in self.graph.nodes:
            literal_data = {
                'type': 'literal',
                'value': final_value,
                'display_name': literal_id
            }
            literal_node = Node(literal_id, literal_data)
            self.graph.add_node(literal_node)
        else:
            literal_node = self.graph.nodes[literal_id]

        # Create enable condition comparator (counter == final_value)
        enable_expr = {
            'type': 'binary_op',
            'operator': '==',
            'left': {'type': 'identifier', 'name': counter_node.id},
            'right': {'type': 'literal', 'value': final_value}
        }

        enable_data = {
            'type': 'operation',
            'operator': '==',
            'display_name': f"{counter_node.id} == {final_value}",
            'expression': enable_expr,
            'enable_condition': True,
            enable_type: True  # e.g., 'serialization_enable': True
        }

        enable_node = Node(enable_node_id, enable_data)
        enable_node.uarch_time = final_value  # Enable fires at final cycle
        self.graph.add_node(enable_node)

        # Connect counter and literal to enable node
        counter_edge = Edge(counter_node, enable_node, data={'type': 'operand', 'position': 'left'})
        literal_edge = Edge(literal_node, enable_node, data={'type': 'operand', 'position': 'right'})
        self.graph.add_edge(counter_edge)
        self.graph.add_edge(literal_edge)

        return enable_node

    def find_all_isa_writes(self) -> List[Node]:
        """
        Find all ISA state write nodes in the graph.

        An ISA write is defined as an architectural state node with incoming assignment edges.

        Returns:
            List of ISA state write nodes
        """
        isa_writes = []
        for node_id, node in self.graph.nodes.items():
            if node.is_arch_state:
                # Check if this node has incoming assignment edges (indicating a write)
                has_write = any(e.data.get('type') == 'assignment' for e in node.incoming_edges)
                if has_write:
                    isa_writes.append(node)
        return isa_writes

    def gate_isa_writes(self,
                       isa_writes: List[Node],
                       enable_node: Node,
                       enable_expr: Dict,
                       gate_condition_str: str,
                       final_cycle: int):
        """
        Gate ISA state writes with enable condition.

        Args:
            isa_writes: List of ISA state write nodes to gate
            enable_node: Enable comparator node
            enable_expr: Enable expression dictionary
            gate_condition_str: String description of gate condition (for metadata)
            final_cycle: Cycle when writes should occur
        """
        for write_node in isa_writes:
            # Update uarch_time to final cycle
            write_node.uarch_time = final_cycle

            # Add enable expression to the write node's data
            if write_node.data:
                write_node.data['enable'] = enable_expr
                write_node.data['gate_condition'] = gate_condition_str

            # Find and mark assignment edges as gated
            for edge in write_node.incoming_edges:
                if edge.data.get('type') == 'assignment':
                    edge.data['gated'] = True
                    edge.data['gate_condition'] = gate_condition_str
                    edge.data['enable'] = enable_expr

            # Create write_enable edge from enable node to ISA write node
            enable_edge = Edge(enable_node, write_node, data={'type': 'write_enable'})
            self.graph.add_edge(enable_edge)

    def gate_all_isa_writes_for_operation(self,
                                         operation_id: str,
                                         counter_node: Node,
                                         final_cycle: int,
                                         enable_type: str = 'generic',
                                         gate_condition_fmt: Optional[str] = None) -> Node:
        """
        Complete workflow to create enable comparator and gate all ISA writes.

        This is the main entry point that combines all the steps.

        Args:
            operation_id: ID of the operation
            counter_node: Counter/cycle tracker node
            final_cycle: Final cycle value
            enable_type: Type of enable (for metadata)
            gate_condition_fmt: Format string for gate condition (default: "{counter_id} == {final_cycle}")

        Returns:
            The created enable comparator node
        """
        # Create enable comparator
        enable_node = self.create_enable_comparator(
            operation_id, counter_node, final_cycle, enable_type
        )

        # Find all ISA writes
        isa_writes = self.find_all_isa_writes()

        if not isa_writes:
            print(f"    - No ISA state writes to gate")
            return enable_node

        print(f"    - Gating all {len(isa_writes)} ISA state writes for atomicity:")

        # Create gate condition string
        if gate_condition_fmt is None:
            gate_condition_str = f"{counter_node.id} == {final_cycle}"
        else:
            gate_condition_str = gate_condition_fmt.format(
                counter_id=counter_node.id,
                final_cycle=final_cycle
            )

        # Create enable expression
        enable_expr = {
            'type': 'binary_op',
            'operator': '==',
            'left': {'type': 'identifier', 'name': counter_node.id},
            'right': {'type': 'literal', 'value': final_cycle}
        }

        # Gate all ISA writes
        self.gate_isa_writes(isa_writes, enable_node, enable_expr, gate_condition_str, final_cycle)

        for write_node in isa_writes:
            print(f"      - Gated ISA write: {write_node.id} (cycle {final_cycle})")

        return enable_node
