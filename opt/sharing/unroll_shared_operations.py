#!/usr/bin/env python3
"""
Unroll Shared Operations Transform

This module reverses resource sharing optimizations by expanding shared operations
back into separate parallel operations. This is useful when:
- Area overhead is acceptable but latency needs improvement
- Specific instruction sequences never co-execute
- Power budget allows dedicated resources

The transform detects operations that have been shared (marked with 'shared_resource'
in node data) and unrolls them by:
1. Creating separate operation nodes for each time slot
2. Removing pipeline registers (timing cuts)
3. Removing the uarch counter
4. Removing gating logic on ISA state updates
5. Reconnecting data flow paths

Author: Claude
Date: 2025-10-20
"""

from typing import Dict, List, Set, Optional, Tuple
from core.resource_graph import ResourceGraph, Node, Edge
import re


class UnrollSharedOperationsTransform:
    """Transform to unroll shared operations back into parallel operations."""

    def __init__(self, graph: ResourceGraph):
        """
        Initialize the transform.

        Args:
            graph: The resource graph to transform
        """
        self.graph = graph
        self.shared_operations: List[Node] = []
        self.pipeline_registers: Set[Node] = set()
        self.counter_nodes: Set[Node] = set()
        self.nodes_to_remove: Set[Node] = set()
        self.edges_to_remove: Set[Edge] = set()

    def unroll_all_shared_resources(self) -> bool:
        """
        Main entry point: unroll all shared resources in the graph.

        Returns:
            True if any shared resources were unrolled, False otherwise
        """
        # Step 1: Identify shared resources
        self._identify_shared_resources()

        if not self.shared_operations:
            return False

        # Step 2: Unroll each shared resource
        for shared_op in self.shared_operations:
            self._unroll_shared_operation(shared_op)

        # Step 3: Remove counter nodes
        self._remove_counter_nodes()

        # Step 4: Clean up pipeline registers
        self._cleanup_pipeline_registers()

        # Step 5: Remove enable signals
        self._remove_enable_signals()

        # Step 6: Remove gating on ISA state updates
        self._remove_isa_state_gating()

        # Step 7: Actually remove nodes and edges
        self._apply_removals()

        # Step 8: Reset timing for affected nodes
        self._reset_timing()

        return True

    def _identify_shared_resources(self):
        """Identify all shared resource nodes and related infrastructure."""
        for node_id, node in self.graph.nodes.items():
            # Find shared operations
            if node.data.get('shared_resource', False):
                self.shared_operations.append(node)

            # Find pipeline registers (timing cuts)
            if node.is_uarch_state and ('_reg' in node_id or node.data.get('type') == 'pipeline_register'):
                # Check if it's part of resource sharing pattern
                if self._is_resource_sharing_register(node):
                    self.pipeline_registers.add(node)

            # Find counter nodes
            if 'counter' in node_id.lower() and node.is_uarch_state:
                if self._is_resource_sharing_counter(node):
                    self.counter_nodes.add(node)

    def _is_resource_sharing_register(self, node: Node) -> bool:
        """
        Check if a register is part of resource sharing infrastructure.

        Looks for patterns like:
        - xxx_t0_reg, xxx_t1_reg (time slot registers)
        - xxx_result_t0_reg (result registers)
        """
        # Pattern: ends with _t{digit}_reg or _t{digit}
        pattern = r'_t\d+(_reg)?$'
        return bool(re.search(pattern, node.id))

    def _is_resource_sharing_counter(self, node: Node) -> bool:
        """
        Check if a node is a resource sharing counter.

        Looks for:
        - uarch_counter or uarch_cycle_counter
        - Has outgoing edges with 'resource_control' type
        """
        if 'uarch' in node.id and 'counter' in node.id:
            # Verify it controls shared resources
            for edge in node.outgoing_edges:
                if edge.data.get('type') == 'resource_control':
                    return True
        return False

    def _unroll_shared_operation(self, shared_op: Node):
        """
        Unroll a single shared operation into separate parallel operations.

        Args:
            shared_op: The shared operation node to unroll
        """
        # Gather all time slots for this operation
        time_slots = self._gather_time_slots(shared_op)

        if not time_slots:
            # No time slot information, simple case
            self._unroll_simple(shared_op)
            return

        # For each time slot, create a dedicated operation
        for slot_idx, slot_info in time_slots.items():
            self._create_dedicated_operation(shared_op, slot_idx, slot_info)

        # Mark shared operation for removal
        self.nodes_to_remove.add(shared_op)

    def _gather_time_slots(self, shared_op: Node) -> Dict[int, Dict]:
        """
        Gather information about all time slots for a shared operation.

        Returns:
            Dict mapping time_slot -> {
                'input_regs': [(register_node, original_source), ...],
                'result_regs': [register_node, ...],
                'destinations': [(dest_node, edge_data), ...]
            }
        """
        time_slots: Dict[int, Dict] = {}

        # Find input pipeline registers feeding this operation
        for edge in shared_op.incoming_edges:
            source = edge.source
            if source in self.pipeline_registers:
                slot = self._extract_time_slot(source.id)
                if slot is not None:
                    if slot not in time_slots:
                        time_slots[slot] = {
                            'input_regs': [],
                            'result_regs': [],
                            'destinations': []
                        }

                    # Find the original source before the pipeline register
                    original_source = self._find_original_source(source)
                    time_slots[slot]['input_regs'].append((source, original_source, edge.data))

        # Find result registers from this operation
        for edge in shared_op.outgoing_edges:
            target = edge.target
            if target in self.pipeline_registers:
                slot = self._extract_time_slot(target.id)
                if slot is not None:
                    if slot not in time_slots:
                        time_slots[slot] = {
                            'input_regs': [],
                            'result_regs': [],
                            'destinations': []
                        }
                    time_slots[slot]['result_regs'].append(target)

                    # Find destinations of the result register
                    for dest_edge in target.outgoing_edges:
                        time_slots[slot]['destinations'].append((dest_edge.target, dest_edge.data))

        # Also check for direct edges if no result registers
        if not any(slot_info['result_regs'] for slot_info in time_slots.values()):
            # Shared operation may have direct outputs
            # Use the operation's own time_slot from node data
            op_time_slot = shared_op.data.get('time_slot')
            if op_time_slot is not None:
                if op_time_slot not in time_slots:
                    time_slots[op_time_slot] = {
                        'input_regs': [],
                        'result_regs': [],
                        'destinations': []
                    }
                # Add all direct outputs to this operation's time slot
                for edge in shared_op.outgoing_edges:
                    if edge.target not in self.pipeline_registers:
                        time_slots[op_time_slot]['destinations'].append((edge.target, edge.data))

        return time_slots

    def _extract_time_slot(self, node_id: str) -> Optional[int]:
        """Extract time slot number from node ID like 'xxx_t0_reg' -> 0."""
        match = re.search(r'_t(\d+)', node_id)
        if match:
            return int(match.group(1))
        return None

    def _find_original_source(self, pipeline_reg: Node) -> Optional[Tuple[Node, Dict]]:
        """
        Find the original source node before a pipeline register.

        Returns:
            (source_node, edge_data) or None
        """
        for edge in pipeline_reg.incoming_edges:
            if edge.data.get('type') == 'pipeline_stage' or edge.source not in self.pipeline_registers:
                return (edge.source, edge.data)
        return None

    def _create_dedicated_operation(self, shared_op: Node, slot_idx: int, slot_info: Dict):
        """
        Create a dedicated operation for a specific time slot.

        Args:
            shared_op: The original shared operation
            slot_idx: Time slot index
            slot_info: Information about this time slot's connections
        """
        # Create new operation node
        new_op_id = f"{shared_op.id}_unrolled_t{slot_idx}"
        new_op = Node(
            node_id=new_op_id,
            data={
                **shared_op.data,
                'shared_resource': False,  # No longer shared
                'unrolled_from': shared_op.id,
                'original_time_slot': slot_idx,
                'display_name': shared_op.data.get('display_name', '').replace('Shared ', '').replace(f' [slot {slot_idx}]', '')
            },
            is_arch_state=shared_op.is_arch_state,
            is_uarch_state=shared_op.is_uarch_state
        )

        # Clean up display name
        if 'Shared' in new_op.data.get('display_name', ''):
            new_op.data['display_name'] = re.sub(r'Shared\s+', '', new_op.data.get('display_name', ''))
        if '[slot' in new_op.data.get('display_name', ''):
            new_op.data['display_name'] = re.sub(r'\s*\[slot \d+\]', '', new_op.data.get('display_name', ''))

        self.graph.add_node(new_op)

        # Connect inputs: bypass pipeline registers
        for input_reg, original_source_info, edge_data in slot_info['input_regs']:
            if original_source_info:
                original_source, orig_edge_data = original_source_info
                # Create edge from original source to new operation
                new_edge_data = {**edge_data}
                # Preserve operand information
                if 'operand' in orig_edge_data:
                    new_edge_data['operand'] = orig_edge_data['operand']

                new_edge = Edge(original_source, new_op, data=new_edge_data)
                self.graph.add_edge(new_edge)

            # Mark input register for removal
            self.pipeline_registers.add(input_reg)

        # Connect outputs: bypass result registers
        for dest_node, edge_data in slot_info['destinations']:
            # Remove gating information
            new_edge_data = {**edge_data}
            if 'gated_by' in new_edge_data:
                del new_edge_data['gated_by']
            if 'condition' in new_edge_data:
                del new_edge_data['condition']

            new_edge = Edge(new_op, dest_node, data=new_edge_data)
            self.graph.add_edge(new_edge)

        # Mark result registers for removal
        for result_reg in slot_info['result_regs']:
            self.pipeline_registers.add(result_reg)

    def _unroll_simple(self, shared_op: Node):
        """
        Unroll a shared operation without time slot information.

        This handles cases where sharing was simple without explicit time slots.
        """
        # Just mark it as no longer shared
        if shared_op.data is None:
            shared_op.data = {}
        shared_op.data['shared_resource'] = False
        if 'display_name' in shared_op.data:
            shared_op.data['display_name'] = shared_op.data['display_name'].replace('Shared ', '')
            shared_op.data['display_name'] = re.sub(r'\s*\[slot \d+\]', '', shared_op.data['display_name'])

    def _remove_counter_nodes(self):
        """Remove uarch counter nodes and their increment logic."""
        increment_nodes = set()

        for counter in self.counter_nodes:
            # Find and remove increment operations and related nodes
            for edge in list(counter.outgoing_edges) + list(counter.incoming_edges):
                if edge.data.get('type') == 'resource_control':
                    self.edges_to_remove.add(edge)

                # Check for counter increment nodes
                if 'increment' in edge.source.id:
                    increment_nodes.add(edge.source)
                if 'increment' in edge.target.id:
                    increment_nodes.add(edge.target)

                # Check for constant "1" nodes feeding the counter
                if edge.source.data and edge.source.data.get('type') == 'literal' and edge.source.data.get('value') == 1:
                    # This might be used elsewhere, check
                    if all('counter' in out_edge.target.id for out_edge in edge.source.outgoing_edges):
                        self.nodes_to_remove.add(edge.source)

            self.nodes_to_remove.add(counter)

        # Remove increment nodes and their inputs
        for inc_node in increment_nodes:
            self.nodes_to_remove.add(inc_node)
            # Also check inputs to the increment node
            for edge in inc_node.incoming_edges:
                source = edge.source
                # If it's a literal constant only used by counter logic, remove it
                if source.data and source.data.get('type') == 'literal':
                    if all('counter' in out_edge.target.id or out_edge.target in increment_nodes
                           for out_edge in source.outgoing_edges):
                        self.nodes_to_remove.add(source)

    def _cleanup_pipeline_registers(self):
        """Remove pipeline registers and their edges."""
        for reg in self.pipeline_registers:
            self.nodes_to_remove.add(reg)

            # Mark all edges to/from this register for removal
            for edge in reg.incoming_edges:
                self.edges_to_remove.add(edge)
            for edge in reg.outgoing_edges:
                self.edges_to_remove.add(edge)

    def _remove_enable_signals(self):
        """
        Remove enable signal nodes created by resource sharing.

        These are typically named 'resource_sharing_enable' or similar,
        and are used to gate ISA state updates.
        """
        enable_nodes = []

        for node_id, node in self.graph.nodes.items():
            # Check for explicit resource_sharing_enable marker in data
            if node.data and node.data.get('resource_sharing_enable'):
                enable_nodes.append(node)
                continue

            # Find enable signal nodes related to resource sharing
            if 'enable' in node_id.lower():
                # Direct match: contains 'sharing' in the name
                if 'sharing' in node_id.lower():
                    enable_nodes.append(node)
                    continue

                # Check if it's connected to counter nodes
                is_sharing_enable = False
                for edge in node.incoming_edges:
                    if edge.source in self.counter_nodes or 'counter' in edge.source.id.lower():
                        is_sharing_enable = True
                        break

                # Check if it's connected to nodes we're removing
                if not is_sharing_enable:
                    for edge in list(node.incoming_edges) + list(node.outgoing_edges):
                        if edge.source in self.nodes_to_remove or edge.target in self.nodes_to_remove:
                            is_sharing_enable = True
                            break

                if is_sharing_enable:
                    enable_nodes.append(node)

        # Mark enable nodes for removal
        for node in enable_nodes:
            self.nodes_to_remove.add(node)

    def _remove_isa_state_gating(self):
        """
        Remove gating conditions from ISA state updates.

        After unrolling, ISA state can be updated unconditionally.
        """
        for node in self.graph.nodes.values():
            if node.is_arch_state:
                # Find incoming assignment edges
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'assignment':
                        # Remove gating conditions
                        if 'gated_by' in edge.data:
                            del edge.data['gated_by']
                        if 'condition' in edge.data:
                            del edge.data['condition']

    def _apply_removals(self):
        """Actually remove nodes and edges marked for removal."""
        # Remove edges first
        for edge in self.edges_to_remove:
            try:
                self.graph.remove_edge(edge.id)
            except (ValueError, KeyError):
                pass  # Edge might already be removed

        # Remove nodes
        for node in self.nodes_to_remove:
            try:
                self.graph.remove_node(node.id)
            except (ValueError, KeyError):
                pass  # Node might already be removed

    def _reset_timing(self):
        """
        Reset uarch_time for nodes that were affected by resource sharing.

        After unrolling, operations that were previously serialized should
        return to their original timing (typically cycle 0).
        """
        # Find all nodes that still exist and may have been affected
        for node_id, node in self.graph.nodes.items():
            # Skip nodes that are uarch infrastructure (they're being removed anyway)
            if node.is_uarch_state:
                continue

            # Reset timing for any node at time > 0
            if node.uarch_time and node.uarch_time > 0:
                # Check if this node has any remaining gating
                has_gating = False
                for edge in node.incoming_edges:
                    if edge.data.get('gated_by') or edge.data.get('condition'):
                        has_gating = True
                        break

                # If no gating remains, reset to cycle 0
                if not has_gating:
                    node.uarch_time = 0


def unroll_shared_operations(graph: ResourceGraph) -> bool:
    """
    Convenience function to unroll all shared operations in a graph.

    Args:
        graph: The resource graph to transform

    Returns:
        True if any shared resources were unrolled, False otherwise

    Example:
        >>> graph = ResourceGraph()
        >>> # ... build graph with shared operations ...
        >>> unrolled = unroll_shared_operations(graph)
        >>> if unrolled:
        ...     print("Shared operations were unrolled")
    """
    transform = UnrollSharedOperationsTransform(graph)
    return transform.unroll_all_shared_resources()


if __name__ == '__main__':
    print("UnrollSharedOperationsTransform module")
    print("This module provides functionality to reverse resource sharing optimizations.")
