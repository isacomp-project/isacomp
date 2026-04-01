"""
Instruction decode utilities for ResourceGraph merging.

This module provides common utilities for creating instruction decode logic,
including enable signals, comparisons, and conditional gates.
"""

from typing import Dict, List, Optional, Any
from .resource_graph import ResourceGraph, Node, Edge


class InstructionDecodeBuilder:
    """Builder for creating instruction decode logic."""

    def __init__(self, graph: ResourceGraph):
        self.graph = graph

    def create_instruction_enable_node(
        self,
        instruction_name: str,
        decode_conditions: Optional[List] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Node:
        """
        Create an instruction enable signal node.

        Args:
            instruction_name: Name of the instruction (e.g., 'add', 'lw')
            decode_conditions: List of decode conditions for metadata
            metadata: Additional metadata to include

        Returns:
            Created enable signal node
        """
        enable_signal_name = f"{instruction_name}_enable"

        enable_data = {
            'type': 'instruction_enable',
            'name': enable_signal_name,
            'display_name': enable_signal_name,
            'instruction': instruction_name,
            'bit_width': 1  # Enable signals are always 1-bit
        }

        if decode_conditions:
            enable_data['decode_conditions'] = decode_conditions

        if metadata:
            enable_data.update(metadata)

        enable_node = Node(enable_signal_name, enable_data)
        self.graph.add_node(enable_node)

        return enable_node

    def get_or_create_bitslice(
        self,
        source_node: Node,
        high: int,
        low: int
    ) -> Node:
        """
        Get or create a bit_slice node for the given range.
        Reuses existing bit_slice nodes to enable sharing across instructions.

        Args:
            source_node: Source node to slice from (e.g., 'instr')
            high: High bit index
            low: Low bit index

        Returns:
            Bit slice node (reused if already exists)
        """
        # Create consistent node ID based on source and range
        slice_id = f"{source_node.id}[{high}:{low}]"

        # Check if this bit slice already exists
        if slice_id in self.graph.nodes:
            slice_node = self.graph.nodes[slice_id]
            # Ensure edge exists from source to slice (might be missing if node was created elsewhere)
            has_edge = any(
                e.source.id == source_node.id and e.target.id == slice_id
                for e in slice_node.incoming_edges
            )
            if not has_edge:
                edge = Edge(source_node, slice_node, data={'type': 'bit_slice'})
                self.graph.add_edge(edge)
            return slice_node

        # Create new bit_slice node
        slice_data = {
            'type': 'bit_slice',
            'name': slice_id,
            'display_name': slice_id,
            'bitslice': (high, low),
            'high': high,
            'low': low,
            'data_width': high - low + 1
        }

        slice_node = Node(slice_id, slice_data)
        self.graph.add_node(slice_node)

        # Connect source to slice
        edge = Edge(source_node, slice_node, data={'type': 'bit_slice'})
        self.graph.add_edge(edge)

        return slice_node

    def get_or_create_comparison(
        self,
        field_expr: str,
        operator: str,
        value: str,
        field_ast: Optional[Dict] = None,
        source_node: Optional[Node] = None
    ) -> Node:
        """
        Get or create a shared comparison node for the given expression.
        Reuses existing comparison nodes to enable sharing across instructions.

        Args:
            field_expr: Field expression (e.g., 'instr[31:26]')
            operator: Comparison operator (e.g., '==', '!=')
            value: Value to compare against
            field_ast: Optional AST representation of field expression
            source_node: Optional source node for bit slicing

        Returns:
            Comparison node (reused if already exists)
        """
        # Create consistent node ID based on expression and value
        # Sanitize field expression for use in node ID
        sanitized_field = field_expr.replace('[', '_').replace(':', '_').replace(']', '')
        sanitized_value = str(value).replace("'", "").replace("0b", "b").replace("0x", "h")

        # Create a shared comparison ID (not instruction-specific)
        # Use appropriate suffix based on operator
        op_suffix = 'ne' if operator == '!=' else 'eq'
        shared_comp_id = f"{sanitized_field}_{op_suffix}_{sanitized_value}"

        # Check if this comparison already exists
        if shared_comp_id in self.graph.nodes:
            return self.graph.nodes[shared_comp_id]

        comp_data = {
            'type': 'comparison',
            'name': shared_comp_id,
            'display_name': f"{field_expr} {operator} {value}",
            'operation': operator,
            'expression': {
                'type': 'binary_op',
                'operation': operator,
                'left': field_ast if field_ast else {'type': 'identifier', 'name': field_expr},
                'right': {'type': 'literal', 'value': value}
            }
        }

        comp_node = Node(shared_comp_id, comp_data)
        self.graph.add_node(comp_node)

        # Connect source node directly to comparison (SMT verifier reads bit slice from expression)
        if source_node:
            edge = Edge(source_node, comp_node, data={'type': 'operand'})
            self.graph.add_edge(edge)

        return comp_node

    def create_decode_comparison(
        self,
        enable_node_id: str,
        field_expr: str,
        operator: str,
        value: str,
        field_ast: Optional[Dict] = None,
        source_node: Optional[Node] = None
    ) -> Node:
        """
        Create a comparison node for instruction decode.
        If field_ast represents a bit_slice, creates a shared bit_slice node.
        Reuses existing comparison nodes when possible.

        Args:
            enable_node_id: ID of the enable node this comparison feeds
            field_expr: Field expression (e.g., 'instr[31:26]')
            operator: Comparison operator (e.g., '==', '!=')
            value: Value to compare against
            field_ast: Optional AST representation of field expression
            source_node: Optional source node for bit slicing

        Returns:
            Created (or reused) comparison node
        """
        # Use shared comparison node
        return self.get_or_create_comparison(field_expr, operator, value, field_ast, source_node)

    def create_and_gate(
        self,
        gate_id: str,
        display_name: Optional[str] = None
    ) -> Node:
        """
        Create a logical AND gate node.

        Args:
            gate_id: ID for the AND gate
            display_name: Optional display name

        Returns:
            Created AND gate node
        """
        if display_name is None:
            display_name = gate_id

        and_data = {
            'type': 'logical_and',
            'name': gate_id,
            'display_name': display_name,
            'operation': '&&'
        }

        and_node = Node(gate_id, and_data)
        self.graph.add_node(and_node)

        return and_node

    def wire_decode_logic(
        self,
        comparison_nodes: List[Node],
        enable_node: Node
    ):
        """
        Wire up decode logic: comparisons -> enable signal.

        The enable_node becomes an AND gate combining all comparisons.
        If there's a single comparison, it connects directly to the enable.
        If there are multiple comparisons, the enable node IS the AND gate.

        Args:
            comparison_nodes: List of comparison nodes
            enable_node: Enable signal node that will receive comparison inputs
        """
        if len(comparison_nodes) == 0:
            return
        elif len(comparison_nodes) == 1:
            # Single condition - connect directly to enable node
            edge = Edge(comparison_nodes[0], enable_node, data={'type': 'decode_enable'})
            self.graph.add_edge(edge)
        else:
            # Multiple conditions - convert enable node to an AND gate
            # Update the enable node to be an AND gate
            enable_node.data['type'] = 'logical_and'
            enable_node.data['operation'] = '&&'

            # Connect comparisons directly to enable node
            for comp_node in comparison_nodes:
                edge = Edge(comp_node, enable_node, data={'type': 'logic_input'})
                self.graph.add_edge(edge)

    def connect_field_to_comparison(
        self,
        field_node: Node,
        comparison_node: Node,
        edge_type: str = 'decode_input'
    ):
        """
        Connect a field node to a comparison node.

        Args:
            field_node: Source field node (e.g., instruction register)
            comparison_node: Target comparison node
            edge_type: Type of edge to create
        """
        edge = Edge(field_node, comparison_node, data={'type': edge_type})
        self.graph.add_edge(edge)

    def create_combined_enable(
        self,
        instruction_name: str,
        base_name: str,
        instruction_enable_node: Node,
        condition_expr: Dict,
        condition_operand_node: Optional[Node] = None
    ) -> Node:
        """
        Create a combined enable signal: instruction_enable && condition.

        This is used for conditional writes like: write when (add_enable && rd != 0)

        Args:
            instruction_name: Name of the instruction
            base_name: Base name for the combined enable (e.g., 'rf_write')
            instruction_enable_node: The instruction's enable signal
            condition_expr: AST of the condition (e.g., {'operator': '!=', 'left': ..., 'right': ...})
            condition_operand_node: Optional node for the condition's operand

        Returns:
            Combined enable node (AND gate output)
        """
        operator = condition_expr.get('operator', '!=')
        left_expr = condition_expr.get('left', {})
        right_expr = condition_expr.get('right', {})

        # Create descriptive names
        left_name = left_expr.get('name', 'operand') if left_expr.get('type') == 'identifier' else str(left_expr.get('value', '?'))
        right_val = right_expr.get('value', '?')

        # Check if a shared comparison node already exists for this condition
        # Look for nodes with display_name matching the comparison pattern
        enable_cond_node = None
        shared_comp_display = f"({left_name} {operator} {right_val})"

        for node_id, node in self.graph.nodes.items():
            if (node.data.get('type') in ['comparison', 'operation'] and
                node.data.get('display_name') == shared_comp_display and
                node.data.get('operation') == operator):
                # Found a shared comparison node - reuse it
                enable_cond_node = node
                print(f"  Reusing shared comparison node: {node_id}")
                break

        # Create new comparison node only if shared one doesn't exist
        if not enable_cond_node:
            enable_cond_id = f"{instruction_name}_{left_name}_{operator.replace('!=', 'ne').replace('==', 'eq')}_{right_val}"
            enable_cond_data = {
                'type': 'comparison',
                'name': enable_cond_id,
                'display_name': shared_comp_display,
                'operation': operator,
                'expression': condition_expr
            }
            enable_cond_node = Node(enable_cond_id, enable_cond_data)
            self.graph.add_node(enable_cond_node)

            # Connect operand to comparison if provided
            if condition_operand_node:
                left_edge = Edge(condition_operand_node, enable_cond_node,
                               data={'type': 'operand', 'position': 'left'})
                self.graph.add_edge(left_edge)

        # Create AND gate: instruction_enable && condition
        combined_enable_id = f"{instruction_name}_{base_name}_enable"
        combined_enable_data = {
            'type': 'logical_and',
            'name': combined_enable_id,
            'display_name': f"{instruction_name} {base_name} enable",
            'operation': '&&'
        }
        combined_enable_node = Node(combined_enable_id, combined_enable_data)
        self.graph.add_node(combined_enable_node)

        # Wire: instruction_enable -> AND gate
        instr_to_combined_edge = Edge(instruction_enable_node, combined_enable_node,
                                      data={'type': 'logic_input'})
        self.graph.add_edge(instr_to_combined_edge)

        # Wire: condition -> AND gate
        cond_to_combined_edge = Edge(enable_cond_node, combined_enable_node,
                                     data={'type': 'logic_input'})
        self.graph.add_edge(cond_to_combined_edge)

        return combined_enable_node


# Convenience functions

def create_instruction_enable(
    graph: ResourceGraph,
    instruction_name: str,
    decode_conditions: Optional[List] = None,
    **kwargs
) -> Node:
    """
    Convenience function to create an instruction enable signal.

    See InstructionDecodeBuilder.create_instruction_enable_node for full documentation.
    """
    builder = InstructionDecodeBuilder(graph)
    return builder.create_instruction_enable_node(instruction_name, decode_conditions, **kwargs)


def create_decode_comparison(
    graph: ResourceGraph,
    enable_node_id: str,
    field_expr: str,
    operator: str,
    value: str,
    **kwargs
) -> Node:
    """
    Convenience function to create a decode comparison.

    See InstructionDecodeBuilder.create_decode_comparison for full documentation.
    """
    builder = InstructionDecodeBuilder(graph)
    return builder.create_decode_comparison(enable_node_id, field_expr, operator, value, **kwargs)


def wire_decode_logic(
    graph: ResourceGraph,
    comparison_nodes: List[Node],
    enable_node: Node
):
    """
    Convenience function to wire decode logic.

    See InstructionDecodeBuilder.wire_decode_logic for full documentation.
    """
    builder = InstructionDecodeBuilder(graph)
    builder.wire_decode_logic(comparison_nodes, enable_node)


def create_combined_enable(
    graph: ResourceGraph,
    instruction_name: str,
    base_name: str,
    instruction_enable_node: Node,
    condition_expr: Dict,
    condition_operand_node: Optional[Node] = None
) -> Node:
    """
    Convenience function to create a combined enable signal.

    See InstructionDecodeBuilder.create_combined_enable for full documentation.
    """
    builder = InstructionDecodeBuilder(graph)
    return builder.create_combined_enable(
        instruction_name, base_name, instruction_enable_node,
        condition_expr, condition_operand_node
    )
