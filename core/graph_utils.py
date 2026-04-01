"""
Graph utility functions for ResourceGraph operations.

This module provides common graph manipulation utilities used across multiple
optimization modules.
"""

from typing import List, Set, Optional, Callable
from .resource_graph import ResourceGraph, Node, Edge


def deep_copy_graph(graph: ResourceGraph) -> ResourceGraph:
    """
    Create a deep copy of a ResourceGraph.

    This creates a complete independent copy with all nodes, edges, and metadata.

    Args:
        graph: The ResourceGraph to copy

    Returns:
        A new ResourceGraph that is a deep copy of the input
    """
    new_graph = ResourceGraph()

    # Copy all nodes
    for node_id, node in graph.nodes.items():
        new_data = node.data.copy() if node.data else {}
        new_node = Node(
            node_id, new_data,
            is_arch_state=node.is_arch_state,
            used_as_index=node.used_as_index,
            is_uarch_state=node.is_uarch_state,
            uarch_time=node.uarch_time,
            from_isa_spec=getattr(node, 'from_isa_spec', False),
            already_split=getattr(node, 'already_split', False)
        )
        new_graph.add_node(new_node)

    # Copy all edges
    for edge_id, edge in graph.edges.items():
        source = new_graph.nodes[edge.source.id]
        target = new_graph.nodes[edge.target.id]
        new_data = edge.data.copy() if edge.data else {}
        new_edge = Edge(source, target, edge_id, new_data)
        new_graph.add_edge(new_edge)

    return new_graph


def find_nodes_by_type(graph: ResourceGraph, node_type: str) -> List[Node]:
    """
    Find all nodes in a graph with a specific type.

    Args:
        graph: The ResourceGraph to search
        node_type: The node type to search for (e.g., 'operation', 'literal')

    Returns:
        List of nodes matching the specified type
    """
    matching_nodes = []
    for node in graph.nodes.values():
        if node.data.get('type') == node_type:
            matching_nodes.append(node)
    return matching_nodes


def find_nodes_by_pattern(graph: ResourceGraph, pattern: str) -> List[Node]:
    """
    Find all nodes whose IDs match a pattern (substring search).

    Args:
        graph: The ResourceGraph to search
        pattern: Pattern to search for in node IDs

    Returns:
        List of nodes with IDs containing the pattern
    """
    matching_nodes = []
    for node_id, node in graph.nodes.items():
        if pattern in node_id:
            matching_nodes.append(node)
    return matching_nodes


def find_nodes_by_predicate(graph: ResourceGraph, predicate: Callable[[Node], bool]) -> List[Node]:
    """
    Find all nodes that match a custom predicate function.

    Args:
        graph: The ResourceGraph to search
        predicate: Function that takes a Node and returns True if it matches

    Returns:
        List of nodes for which predicate returns True
    """
    matching_nodes = []
    for node in graph.nodes.values():
        if predicate(node):
            matching_nodes.append(node)
    return matching_nodes


def trace_path_forward(
    start_node: Node,
    predicate: Callable[[Node], bool],
    max_depth: int = 100
) -> List[List[Node]]:
    """
    Find all forward paths from a starting node until a predicate is met.

    Args:
        start_node: Node to start tracing from
        predicate: Function that returns True when the target node is found
        max_depth: Maximum depth to search (prevents infinite loops)

    Returns:
        List of paths, where each path is a list of nodes from start to target
    """
    paths = []
    visited = set()

    def dfs(node: Node, current_path: List[Node], depth: int):
        if depth > max_depth:
            return

        if node.id in visited:
            return

        current_path = current_path + [node]

        if predicate(node):
            paths.append(current_path)
            return

        visited.add(node.id)

        for edge in node.outgoing_edges:
            dfs(edge.target, current_path, depth + 1)

        visited.remove(node.id)

    dfs(start_node, [], 0)
    return paths


def trace_path_backward(
    start_node: Node,
    predicate: Callable[[Node], bool],
    max_depth: int = 100
) -> List[List[Node]]:
    """
    Find all backward paths from a starting node until a predicate is met.

    Args:
        start_node: Node to start tracing from
        predicate: Function that returns True when the target node is found
        max_depth: Maximum depth to search (prevents infinite loops)

    Returns:
        List of paths, where each path is a list of nodes from start to target
    """
    paths = []
    visited = set()

    def dfs(node: Node, current_path: List[Node], depth: int):
        if depth > max_depth:
            return

        if node.id in visited:
            return

        current_path = current_path + [node]

        if predicate(node):
            paths.append(current_path)
            return

        visited.add(node.id)

        for edge in node.incoming_edges:
            dfs(edge.source, current_path, depth + 1)

        visited.remove(node.id)

    dfs(start_node, [], 0)
    return paths


def get_reachable_nodes(start_node: Node, direction: str = 'forward') -> Set[Node]:
    """
    Get all nodes reachable from a starting node.

    Args:
        start_node: Node to start from
        direction: Either 'forward' (follow outgoing edges) or 'backward' (follow incoming edges)

    Returns:
        Set of all reachable nodes including the start node
    """
    reachable = set()
    visited = set()

    def dfs(node: Node):
        if node.id in visited:
            return
        visited.add(node.id)
        reachable.add(node)

        if direction == 'forward':
            for edge in node.outgoing_edges:
                dfs(edge.target)
        else:  # backward
            for edge in node.incoming_edges:
                dfs(edge.source)

    dfs(start_node)
    return reachable


def find_shortest_path(
    start_node: Node,
    end_node: Node,
    direction: str = 'forward'
) -> Optional[List[Node]]:
    """
    Find the shortest path between two nodes using BFS.

    Args:
        start_node: Starting node
        end_node: Target node
        direction: Either 'forward' (follow outgoing edges) or 'backward' (follow incoming edges)

    Returns:
        List of nodes representing the shortest path, or None if no path exists
    """
    from collections import deque

    if start_node.id == end_node.id:
        return [start_node]

    queue = deque([(start_node, [start_node])])
    visited = {start_node.id}

    while queue:
        current_node, path = queue.popleft()

        edges = current_node.outgoing_edges if direction == 'forward' else current_node.incoming_edges

        for edge in edges:
            next_node = edge.target if direction == 'forward' else edge.source

            if next_node.id == end_node.id:
                return path + [next_node]

            if next_node.id not in visited:
                visited.add(next_node.id)
                queue.append((next_node, path + [next_node]))

    return None


def is_reachable(start_node: Node, end_node: Node, direction: str = 'forward') -> bool:
    """
    Check if one node is reachable from another.

    Args:
        start_node: Starting node
        end_node: Target node
        direction: Either 'forward' or 'backward'

    Returns:
        True if end_node is reachable from start_node
    """
    return end_node in get_reachable_nodes(start_node, direction)


def get_nodes_at_time(graph: ResourceGraph, uarch_time: int) -> List[Node]:
    """
    Get all nodes at a specific uarch_time.

    Args:
        graph: The ResourceGraph to search
        uarch_time: The uarch_time to match

    Returns:
        List of nodes with the specified uarch_time
    """
    matching_nodes = []
    for node in graph.nodes.values():
        if node.uarch_time == uarch_time:
            matching_nodes.append(node)
    return matching_nodes


def get_nodes_in_time_range(
    graph: ResourceGraph,
    min_time: int,
    max_time: int
) -> List[Node]:
    """
    Get all nodes within a uarch_time range (inclusive).

    Args:
        graph: The ResourceGraph to search
        min_time: Minimum uarch_time (inclusive)
        max_time: Maximum uarch_time (inclusive)

    Returns:
        List of nodes within the time range
    """
    matching_nodes = []
    for node in graph.nodes.values():
        if node.uarch_time is not None and min_time <= node.uarch_time <= max_time:
            matching_nodes.append(node)
    return matching_nodes
