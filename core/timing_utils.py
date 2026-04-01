"""
Timing management utilities for ResourceGraph optimizations.

This module provides common timing-related operations used across multiple
optimization modules for managing and updating uarch_time values.
"""

from typing import List, Set, Optional
from .resource_graph import ResourceGraph, Node


class TimingManager:
    """Manages timing information for ResourceGraph nodes."""

    def __init__(self, graph: ResourceGraph):
        self.graph = graph

    def set_node_timing(self, node: Node, time: int):
        """
        Set uarch_time for a node.

        Args:
            node: The node to set timing for
            time: The timing value to set
        """
        node.uarch_time = time

    def set_nodes_timing(self, nodes: List[Node], time: int):
        """
        Set uarch_time for multiple nodes.

        Args:
            nodes: List of nodes to set timing for
            time: The timing value to set for all nodes
        """
        for node in nodes:
            node.uarch_time = time

    def clear_downstream_timing(self, from_nodes: List[Node]):
        """
        Clear uarch_time for all nodes reachable from the given nodes.

        This is useful when modifying a graph and needing to force
        timing re-inference for affected nodes.

        Args:
            from_nodes: Starting nodes to clear timing from
        """
        visited = set()

        def clear_recursive(node: Node):
            if node.id in visited:
                return
            visited.add(node.id)

            # Clear the timing
            node.uarch_time = None

            # Recursively clear downstream nodes
            for edge in node.outgoing_edges:
                clear_recursive(edge.target)

        for node in from_nodes:
            clear_recursive(node)

    def reinfer_after_transform(self, force: bool = False):
        """
        Re-infer timing after a graph transformation.

        Args:
            force: If True, force re-inference even if timing exists
        """
        self.graph.infer_uarch_time(force_reinfer=force)

    def get_critical_path(self) -> List[Node]:
        """
        Find the critical path (longest path) through the graph.

        Returns:
            List of nodes on the critical path, ordered from start to end
        """
        # First ensure timing is inferred
        if not self._has_timing():
            self.graph.infer_uarch_time()

        # Find the node(s) with maximum uarch_time
        max_time = self.graph.get_max_uarch_time()
        end_nodes = [n for n in self.graph.nodes.values() if n.uarch_time == max_time]

        if not end_nodes:
            return []

        # Trace backwards from the end node to find the critical path
        # Pick the first end node (if multiple exist, they all represent critical paths)
        critical_path = []
        current = end_nodes[0]
        visited = set()

        while current and current.id not in visited:
            visited.add(current.id)
            critical_path.append(current)

            # Find the predecessor with the highest timing
            best_pred = None
            best_time = -1

            for edge in current.incoming_edges:
                pred = edge.source
                if pred.uarch_time is not None and pred.uarch_time > best_time:
                    best_time = pred.uarch_time
                    best_pred = pred

            current = best_pred

        # Reverse to get path from start to end
        critical_path.reverse()
        return critical_path

    def get_max_time(self) -> int:
        """
        Get the maximum uarch_time in the graph.

        Returns:
            Maximum uarch_time value, or 0 if no timing exists
        """
        return self.graph.get_max_uarch_time()

    def get_nodes_at_time(self, time: int) -> List[Node]:
        """
        Get all nodes at a specific uarch_time.

        Args:
            time: The uarch_time to query

        Returns:
            List of nodes with the specified uarch_time
        """
        return self.graph.get_nodes_at_time(time)

    def _has_timing(self) -> bool:
        """Check if the graph has timing information."""
        for node in self.graph.nodes.values():
            if node.uarch_time is not None:
                return True
        return False

    def compute_slack(self, node: Node, target_time: int) -> int:
        """
        Compute timing slack for a node relative to a target time.

        Args:
            node: The node to compute slack for
            target_time: The target/deadline time

        Returns:
            Slack value (positive means ahead of schedule, negative means late)
        """
        if node.uarch_time is None:
            return 0
        return target_time - node.uarch_time

    def find_nodes_on_critical_path(self) -> Set[Node]:
        """
        Find all nodes that lie on any critical path.

        Returns:
            Set of nodes on critical paths
        """
        critical_path = self.get_critical_path()
        return set(critical_path)

    def propagate_timing_forward(self, from_node: Node, delay: int = 1):
        """
        Propagate timing forward from a node through its successors.

        Args:
            from_node: Starting node
            delay: Delay to add for each edge traversal (default: 1 cycle)
        """
        if from_node.uarch_time is None:
            return

        visited = set()
        queue = [(from_node, from_node.uarch_time)]

        while queue:
            current, current_time = queue.pop(0)

            if current.id in visited:
                continue
            visited.add(current.id)

            for edge in current.outgoing_edges:
                target = edge.target
                new_time = current_time + delay

                # Update if target has no time or if this path is longer
                if target.uarch_time is None or new_time > target.uarch_time:
                    target.uarch_time = new_time
                    queue.append((target, new_time))


# Convenience functions

def set_node_timing(node: Node, time: int):
    """
    Convenience function to set timing on a single node.

    Args:
        node: The node to set timing for
        time: The timing value to set
    """
    node.uarch_time = time


def reinfer_timing(graph: ResourceGraph, force: bool = False):
    """
    Convenience function to re-infer graph timing.

    Args:
        graph: The graph to infer timing for
        force: If True, force re-inference even if timing exists
    """
    graph.infer_uarch_time(force_reinfer=force)


def get_critical_path(graph: ResourceGraph) -> List[Node]:
    """
    Convenience function to get the critical path.

    Args:
        graph: The graph to analyze

    Returns:
        List of nodes on the critical path
    """
    manager = TimingManager(graph)
    return manager.get_critical_path()


def clear_timing(graph: ResourceGraph):
    """
    Clear all timing information from a graph.

    Args:
        graph: The graph to clear timing from
    """
    for node in graph.nodes.values():
        node.uarch_time = None
