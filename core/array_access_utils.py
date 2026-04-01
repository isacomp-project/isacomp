"""
Array access analysis utilities for ResourceGraph optimizations.

This module provides common array access analysis functionality used across multiple
optimizations (pipelining, hazard resolution, dependency analysis).
"""

from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from .resource_graph import ResourceGraph, Node


@dataclass
class ArrayAccessInfo:
    """Information about an array access (read or write)."""
    node: Node  # The array access node (e.g., rf[rs]_rd)
    base_resource: str  # Base resource name (e.g., "rf")
    index: str  # Index name (e.g., "rs", "rd")
    index_node: Optional[Node]  # The node that provides the index value
    access_type: str  # 'READ', 'WRITE', or 'READ_WRITE'
    access_key: str  # Full access key (e.g., "rf[rs]")
    uarch_time: int  # Timing information


class ArrayAccessAnalyzer:
    """Analyzes array access patterns in ResourceGraphs."""

    def __init__(self, graph: ResourceGraph):
        self.graph = graph

    def parse_array_access_name(self, node_name: str) -> Optional[Tuple[str, str]]:
        """
        Parse an array access node name to extract base resource and index.

        Args:
            node_name: Node name like "rf[rs]" or "add_imm_rf[rt]_spec"

        Returns:
            Tuple of (base_resource, index_name) or None if parsing failed

        Examples:
            "rf[rs]" -> ("rf", "rs")
            "rf[rd]_wr" -> ("rf", "rd")
            "add_imm_rf[rt]_spec" -> ("rf", "rt")
            "p0_rf[rs]_rd" -> ("rf", "rs")  # dual-issue prefixed
            "p1_rf[rd]_wr" -> ("rf", "rd")  # dual-issue prefixed
        """
        if '[' not in node_name or ']' not in node_name:
            return None

        # Strip dual-issue prefix if present (p0_, p1_)
        working_name = node_name
        if working_name.startswith('p0_') or working_name.startswith('p1_'):
            working_name = working_name[3:]

        # Handle instruction-specific names like "add_imm_rf[rt]_spec" -> "rf[rt]"
        if '_' in working_name and working_name.endswith('_spec'):
            # Extract the core resource part
            parts = working_name.split('_')
            for i, part in enumerate(parts):
                if '[' in part:
                    # Found the resource[index] part
                    resource_part = '_'.join(parts[i:]).replace('_spec', '')
                    base_resource = resource_part.split('[')[0]
                    index_part = resource_part.split('[')[1].split(']')[0]
                    return (base_resource, index_part)
            # Fallback to original parsing
            base_resource = working_name.split('[')[0]
            index_part = working_name.split('[')[1].split(']')[0]
            return (base_resource, index_part)
        else:
            # Normal case: strip suffixes like _rd, _wr
            clean_name = working_name.replace('_rd', '').replace('_wr', '')
            if '[' in clean_name and ']' in clean_name:
                base_resource = clean_name.split('[')[0]
                index_part = clean_name.split('[')[1].split(']')[0]
                return (base_resource, index_part)

        return None

    def classify_access_type(self, node: Node) -> str:
        """
        Classify an array access node as READ, WRITE, or READ_WRITE.

        Based on edge patterns:
        - WRITE: has assignment edge incoming, no assignment outgoing
        - READ: has assignment edge outgoing, no assignment incoming
        - READ_WRITE: has both assignment incoming and outgoing

        Also handles pipelined graphs where assignment edges become pipeline_input edges:
        - READ: has pipeline_input edge outgoing (indicates read that feeds pipeline register)

        Args:
            node: Array access node to classify

        Returns:
            'READ', 'WRITE', 'READ_WRITE', or 'UNKNOWN'
        """
        incoming_types = [e.data.get('type') for e in node.incoming_edges]
        outgoing_types = [e.data.get('type') for e in node.outgoing_edges]

        has_incoming_assignment = 'assignment' in incoming_types
        has_outgoing_assignment = 'assignment' in outgoing_types
        # After pipelining, assignment edges become pipeline_input edges
        has_outgoing_pipeline = 'pipeline_input' in outgoing_types

        if has_incoming_assignment and not has_outgoing_assignment and not has_outgoing_pipeline:
            return 'WRITE'
        elif (has_outgoing_assignment or has_outgoing_pipeline) and not has_incoming_assignment:
            return 'READ'
        elif has_incoming_assignment and (has_outgoing_assignment or has_outgoing_pipeline):
            return 'READ_WRITE'
        else:
            return 'UNKNOWN'

    def find_index_node(self, array_access_node: Node) -> Optional[Node]:
        """
        Find the node that provides the index for an array access.

        Follows array_index edges to find the actual index node,
        skipping the edge from the array base itself.

        Args:
            array_access_node: The array access node (e.g., rf[rs]_rd)

        Returns:
            The index node (e.g., rs) or None if not found
        """
        # Extract base resource name from the array access node
        node_name = array_access_node.data.get('name', array_access_node.id)
        parsed = self.parse_array_access_name(node_name)
        if not parsed:
            return None

        base_resource, _ = parsed

        # Find the index node by following array_index edges
        # Skip the edge from the array base itself (e.g., rf -> rf[rd])
        for edge in array_access_node.incoming_edges:
            if edge.data.get('type') == 'array_index' and edge.source.id != base_resource:
                return edge.source

        return None

    def get_all_array_accesses(self, resource_name: Optional[str] = None) -> List[ArrayAccessInfo]:
        """
        Get all array accesses in the graph, optionally filtered by resource name.

        Args:
            resource_name: Optional resource name to filter by (e.g., "rf")

        Returns:
            List of ArrayAccessInfo objects
        """
        accesses = []

        for node in self.graph.nodes.values():
            if node.data.get('type') != 'array_access':
                continue

            node_name = node.data.get('name', node.id)
            parsed = self.parse_array_access_name(node_name)
            if not parsed:
                continue

            base_resource, index = parsed

            # Filter by resource name if specified
            if resource_name and base_resource != resource_name:
                continue

            # Classify access type
            access_type = self.classify_access_type(node)

            # Find index node
            index_node = self.find_index_node(node)

            # Determine uarch_time
            uarch_time = node.uarch_time if hasattr(node, 'uarch_time') and node.uarch_time is not None else 0

            # Create access key
            access_key = f"{base_resource}[{index}]"

            access_info = ArrayAccessInfo(
                node=node,
                base_resource=base_resource,
                index=index,
                index_node=index_node,
                access_type=access_type,
                access_key=access_key,
                uarch_time=uarch_time
            )
            accesses.append(access_info)

        return accesses

    def get_reads_and_writes(self, resource_name: Optional[str] = None) -> Tuple[List[ArrayAccessInfo], List[ArrayAccessInfo]]:
        """
        Get separate lists of read and write accesses.

        Args:
            resource_name: Optional resource name to filter by

        Returns:
            Tuple of (reads, writes) lists
        """
        all_accesses = self.get_all_array_accesses(resource_name)

        reads = [a for a in all_accesses if a.access_type in ['READ', 'READ_WRITE']]
        writes = [a for a in all_accesses if a.access_type in ['WRITE', 'READ_WRITE']]

        return reads, writes


def parse_array_access_name(node_name: str) -> Optional[Tuple[str, str]]:
    """
    Convenience function to parse an array access node name.

    See ArrayAccessAnalyzer.parse_array_access_name for full documentation.
    """
    # Create a dummy analyzer just for parsing (doesn't need a graph)
    class DummyGraph:
        pass
    analyzer = ArrayAccessAnalyzer(DummyGraph())  # type: ignore
    return analyzer.parse_array_access_name(node_name)


def classify_access_type(node: Node) -> str:
    """
    Convenience function to classify an array access node.

    See ArrayAccessAnalyzer.classify_access_type for full documentation.
    """
    class DummyGraph:
        pass
    analyzer = ArrayAccessAnalyzer(DummyGraph())  # type: ignore
    return analyzer.classify_access_type(node)
