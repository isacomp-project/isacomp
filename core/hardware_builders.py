"""
Hardware builder utilities for ResourceGraph optimizations.

This module provides common hardware building blocks used across multiple
optimizations (pipelining, hazard resolution, parallel merging).
"""

from typing import Optional, Dict, Any
from .resource_graph import ResourceGraph, Node, Edge
import re


class ComparatorBuilder:
    """Builder for creating comparator hardware (equality checks, etc.)."""

    def __init__(self, graph: ResourceGraph):
        self.graph = graph

    def create_index_comparator(
        self,
        comp_id: str,
        left_node: Node,
        right_node: Node,
        operator: str = '==',
        display_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Node:
        """
        Create a comparator node that compares two index nodes.

        Args:
            comp_id: ID for the comparator node
            left_node: Left operand node
            right_node: Right operand node
            operator: Comparison operator (default '==')
            display_name: Display name for the comparator
            metadata: Additional metadata to include in node data

        Returns:
            Created comparator node
        """
        if display_name is None:
            display_name = f"{left_node.id} {operator} {right_node.id}"

        comp_data = {
            'type': 'operation',
            'operator': operator,
            'operation': f'{left_node.id} {operator} {right_node.id}',
            'display_name': display_name
        }

        # Add any additional metadata
        if metadata:
            comp_data.update(metadata)

        comp_node = Node(comp_id, comp_data, is_uarch_state=False)
        self.graph.add_node(comp_node)

        # Connect operands to comparator
        left_edge = Edge(left_node, comp_node, data={
            'type': 'operand',
            'position': 'left'
        })
        self.graph.add_edge(left_edge)

        right_edge = Edge(right_node, comp_node, data={
            'type': 'operand',
            'position': 'right'
        })
        self.graph.add_edge(right_edge)

        return comp_node

    def create_comparator_from_condition(
        self,
        comp_id: str,
        condition: str,
        display_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Node]:
        """
        Create a comparator by parsing a condition string (e.g., "rd == rs").

        Args:
            comp_id: ID for the comparator node
            condition: Condition string to parse
            display_name: Display name for the comparator
            metadata: Additional metadata

        Returns:
            Created comparator node, or None if parsing failed
        """
        # Parse the condition (e.g., "rs == rt" or "rd == rs")
        match = re.match(r'(\w+)\s*(==|!=|<|>|<=|>=)\s*(\w+)', condition)
        if not match:
            return None

        left_name, operator, right_name = match.groups()

        # Find the nodes by name (may need to search with prefixes/suffixes)
        left_node = self._find_node_by_name(left_name)
        right_node = self._find_node_by_name(right_name)

        if not left_node or not right_node:
            return None

        return self.create_index_comparator(
            comp_id, left_node, right_node, operator, display_name, metadata
        )

    def _find_node_by_name(self, name: str) -> Optional[Node]:
        """Find a node by name, searching with common prefixes/suffixes."""
        # Try exact match first
        if name in self.graph.nodes:
            return self.graph.nodes[name]

        # Try with common suffixes
        for suffix in ['', '_rd', '_wr', '_reg']:
            candidate = f"{name}{suffix}"
            if candidate in self.graph.nodes:
                return self.graph.nodes[candidate]

        # Search by partial match - sorted for determinism
        for node_id, node in sorted(self.graph.nodes.items()):
            if node_id == name or node_id.endswith(f"_{name}"):
                return node

        return None


class LiteralBuilder:
    """Builder for creating and reusing literal/constant nodes."""

    def __init__(self, graph: ResourceGraph):
        self.graph = graph

    def create_or_get_literal(
        self,
        value: int,
        reuse: bool = True,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Node:
        """
        Create a literal node or reuse an existing one with the same value.

        Args:
            value: The literal value
            reuse: If True, reuse existing literal nodes with same value
            metadata: Additional metadata for the node

        Returns:
            Literal node (either existing or newly created)
        """
        literal_id = str(value)

        # Try to reuse existing literal if requested
        if reuse and literal_id in self.graph.nodes:
            return self.graph.nodes[literal_id]

        # Create new literal node
        literal_data = {
            'type': 'literal',
            'value': value,
            'display_name': str(value)
        }

        if metadata:
            literal_data.update(metadata)

        literal_node = Node(literal_id, literal_data)
        self.graph.add_node(literal_node)

        return literal_node

    def create_or_get_constant(
        self,
        const_id: str,
        value: int,
        display_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Node:
        """
        Create a constant node (similar to literal but with custom ID).

        Args:
            const_id: ID for the constant node
            value: The constant value
            display_name: Display name for the constant
            metadata: Additional metadata

        Returns:
            Constant node
        """
        if display_name is None:
            display_name = str(value)

        const_data = {
            'type': 'constant',
            'value': value,
            'display_name': display_name
        }

        if metadata:
            const_data.update(metadata)

        const_node = Node(const_id, const_data)
        self.graph.add_node(const_node)

        return const_node


class StallLogicBuilder:
    """Builder for creating stall-related hardware."""

    def __init__(self, graph: ResourceGraph):
        self.graph = graph

    def create_stall_signal(
        self,
        stall_id: str,
        hazard_node: Node,
        hazard_type: str,
        display_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Node:
        """
        Create a stall signal node based on hazard detection.

        NOTE: For typical hazard resolution, this intermediate node is unnecessary.
        Instead, include stall metadata directly in the comparator and connect it
        directly to the stall controller. This method is kept for backwards
        compatibility and special cases.

        Args:
            stall_id: ID for the stall signal node
            hazard_node: Hazard detector node (comparator or constant)
            hazard_type: Type of hazard (RAW, WAR, WAW)
            display_name: Display name for the stall signal
            metadata: Additional metadata

        Returns:
            Created stall signal node
        """
        if display_name is None:
            display_name = f"Stall Signal ({hazard_type})"

        stall_data = {
            'type': 'operation',
            'operation': f'Stall Signal ({hazard_type})',
            'display_name': display_name,
            'hazard_type': hazard_type
        }

        if metadata:
            stall_data.update(metadata)

        stall_node = Node(stall_id, stall_data, is_uarch_state=False)
        self.graph.add_node(stall_node)

        # Connect hazard detector to stall signal
        edge = Edge(hazard_node, stall_node, data={'type': 'control'})
        self.graph.add_edge(edge)

        return stall_node

    def create_or_get_stall_controller(
        self,
        controller_id: str,
        stage_name: str,
        pipeline_prefix: str = 'PIPE',
        metadata: Optional[Dict[str, Any]] = None
    ) -> Node:
        """
        Create a stall controller or reuse existing one for the stage.

        Args:
            controller_id: ID for the stall controller
            stage_name: Name of the pipeline stage
            pipeline_prefix: Prefix for pipeline components
            metadata: Additional metadata

        Returns:
            Stall controller node (existing or newly created)
        """
        # Check if controller already exists
        if controller_id in self.graph.nodes:
            return self.graph.nodes[controller_id]

        # Create new stall controller
        controller_data = {
            'type': 'pipeline_stall_controller',
            'name': controller_id,
            'display_name': f'Stall controller for {stage_name}',
            'stage_name': stage_name,
            'stall_type': 'hazard_detection',
            'pipeline_component': True,
            'pipeline_prefix': pipeline_prefix
        }

        if metadata:
            controller_data.update(metadata)

        controller_node = Node(controller_id, controller_data, is_uarch_state=False)
        self.graph.add_node(controller_node)

        return controller_node

    def connect_stall_to_controller(
        self,
        stall_node: Node,
        controller_node: Node,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Connect a stall signal to a stall controller.

        Args:
            stall_node: Stall signal node
            controller_node: Stall controller node
            metadata: Additional edge metadata
        """
        edge_data = {'type': 'control'}
        if metadata:
            edge_data.update(metadata)

        edge = Edge(stall_node, controller_node, data=edge_data)
        self.graph.add_edge(edge)

    def connect_controller_to_register(
        self,
        controller_node: Node,
        pipeline_register: Node,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Connect a stall controller to a pipeline register.

        Args:
            controller_node: Stall controller node
            pipeline_register: Pipeline register node
            metadata: Additional edge metadata
        """
        # BUGFIX: Deduplicate pipeline_input edges before adding stall logic
        # Find all pipeline_input edges to this register - sorted for determinism
        pipeline_input_edges = [e for e in sorted(pipeline_register.incoming_edges, key=lambda e: (e.source.id, e.target.id))
                               if e.data.get('type') == 'pipeline_input']

        # If there are duplicate pipeline_input edges, remove all but one
        if len(pipeline_input_edges) > 1:
            print(f"  [DEDUP] Found {len(pipeline_input_edges)} pipeline_input edges for {pipeline_register.id}, removing {len(pipeline_input_edges)-1} duplicates")
            # Keep the first edge (by sorted order), remove the rest
            for edge_to_remove in pipeline_input_edges[1:]:
                edge_to_remove.remove_from_nodes()
                if edge_to_remove.id in self.graph.edges:
                    del self.graph.edges[edge_to_remove.id]
            print(f"  [DEDUP] After cleanup: {len([e for e in pipeline_register.incoming_edges if e.data.get('type') == 'pipeline_input'])} pipeline_input edges remain")

        edge_data = {'type': 'stall'}
        if metadata:
            edge_data.update(metadata)

        edge = Edge(controller_node, pipeline_register, data=edge_data)
        self.graph.add_edge(edge)


class HardwareBuilderFactory:
    """
    Factory that provides access to all hardware builders for a graph.

    Usage:
        factory = HardwareBuilderFactory(graph)
        comparator = factory.comparators.create_index_comparator(...)
        literal = factory.literals.create_or_get_literal(1)
        stall_signal = factory.stall_logic.create_stall_signal(...)
    """

    def __init__(self, graph: ResourceGraph):
        self.graph = graph
        self.comparators = ComparatorBuilder(graph)
        self.literals = LiteralBuilder(graph)
        self.stall_logic = StallLogicBuilder(graph)


def create_index_comparator(
    graph: ResourceGraph,
    comp_id: str,
    left_node: Node,
    right_node: Node,
    operator: str = '==',
    **kwargs
) -> Node:
    """
    Convenience function to create an index comparator.

    See ComparatorBuilder.create_index_comparator for full documentation.
    """
    builder = ComparatorBuilder(graph)
    return builder.create_index_comparator(comp_id, left_node, right_node, operator, **kwargs)


def create_or_get_literal(graph: ResourceGraph, value: int, reuse: bool = True) -> Node:
    """
    Convenience function to create or reuse a literal node.

    See LiteralBuilder.create_or_get_literal for full documentation.
    """
    builder = LiteralBuilder(graph)
    return builder.create_or_get_literal(value, reuse)


def create_stall_controller(
    graph: ResourceGraph,
    controller_id: str,
    stage_name: str,
    **kwargs
) -> Node:
    """
    Convenience function to create a stall controller.

    See StallLogicBuilder.create_or_get_stall_controller for full documentation.
    """
    builder = StallLogicBuilder(graph)
    return builder.create_or_get_stall_controller(controller_id, stage_name, **kwargs)
