#!/usr/bin/env python3
"""
Externalized Memory State Gating for Single-Cycle Machines

This module gates ISA state updates for single-cycle machines with externalized
variable-latency memory. Unlike pipelined processors which use stall controllers,
single-cycle machines must:

1. Track pending memory operations (read/write)
2. Latch loaded values when they arrive (for multi-port memories)
3. Only update ISA state when ALL operations complete

This mirrors the pattern used by multi_cycle_operations.py but uses memory
completion signals instead of cycle counters.
"""

from typing import List
from core.resource_graph import ResourceGraph, Node, Edge


class ExternalizedMemoryGating:
    """
    Gate ISA state updates for single-cycle machines with externalized memory.

    Creates:
    - Pending operation trackers ({mem}_read_pending, {mem}_write_pending)
    - Load value latches ({mem}_{port}_latched_data, {mem}_{port}_latched_valid)
    - Combined completion signal (all_ext_mem_complete)
    - Write enable edges to all ISA state nodes
    """

    def __init__(self, graph: ResourceGraph):
        self.graph = graph
        self.externalized_memories: List[str] = []
        self.pending_trackers: List[Node] = []
        self.load_latches: List[Node] = []
        self.completion_signals: List[Node] = []

    def apply(self) -> bool:
        """
        Apply externalized memory gating to the graph.

        Returns:
            True if gating was applied, False if no externalized memories found
        """
        # Find all externalized memories with variable latency
        self.externalized_memories = self._find_externalized_memories()

        if not self.externalized_memories:
            print("  No externalized variable-latency memories found, skipping gating")
            return False

        print(f"Applying externalized memory gating for single-cycle machine:")
        print(f"  Externalized memories: {self.externalized_memories}")

        # Create pending operation trackers for each memory
        for mem_name in self.externalized_memories:
            self._create_pending_trackers(mem_name)

        # Create load value latches for multi-port memories
        for mem_name in self.externalized_memories:
            self._create_load_latches(mem_name)

        # Create per-memory completion signals
        for mem_name in self.externalized_memories:
            self._create_completion_signal(mem_name)

        # Create combined completion signal
        combined_complete = self._create_combined_completion_signal()

        # Gate all ISA state writes with completion signal
        self._gate_all_isa_writes(combined_complete)

        return True

    def _find_externalized_memories(self) -> List[str]:
        """Find all externalized memories that use variable latency."""
        memories = []
        for node in self.graph.nodes.values():
            if node.data.get('is_memory') and node.data.get('externalized'):
                # Only gate for variable latency memories
                if node.data.get('use_valid_ready') or node.data.get('memory_variable_latency'):
                    mem_name = node.data.get('name', node.id)
                    memories.append(mem_name)
        return sorted(memories)

    def _create_pending_trackers(self, mem_name: str):
        """
        Create pending operation tracker nodes for a memory.

        Creates:
        - {mem}_read_pending: Set when read starts, cleared when response arrives
        - {mem}_write_pending: Set when write starts, cleared when response arrives
        """
        # Find the memory node to check read/write port config
        mem_node = None
        for node in self.graph.nodes.values():
            if node.data.get('name') == mem_name and node.data.get('is_memory'):
                mem_node = node
                break

        if not mem_node:
            return

        # Create read pending tracker if read port exists
        if mem_node.data.get('externalize_read', True):
            read_pending_id = f"{mem_name}_read_pending"
            read_pending = Node(read_pending_id, {
                'type': 'ext_mem_pending_tracker',
                'name': read_pending_id,
                'bit_width': 1,
                'memory_name': mem_name,
                'port_type': 'read',
                'is_uarch_state': True,
                'description': f"Tracks pending read operation for {mem_name}"
            })
            read_pending.is_uarch_state = True
            self.graph.add_node(read_pending)
            self.pending_trackers.append(read_pending)
            print(f"    Created read pending tracker: {read_pending_id}")

        # Create write pending tracker if write port exists
        if mem_node.data.get('externalize_write', True):
            write_pending_id = f"{mem_name}_write_pending"
            write_pending = Node(write_pending_id, {
                'type': 'ext_mem_pending_tracker',
                'name': write_pending_id,
                'bit_width': 1,
                'memory_name': mem_name,
                'port_type': 'write',
                'is_uarch_state': True,
                'description': f"Tracks pending write operation for {mem_name}"
            })
            write_pending.is_uarch_state = True
            self.graph.add_node(write_pending)
            self.pending_trackers.append(write_pending)
            print(f"    Created write pending tracker: {write_pending_id}")

    def _create_load_latches(self, mem_name: str):
        """
        Create load value latch nodes for a memory's read ports.

        For memories with multiple read ports, we need to latch data as it
        arrives so it remains valid until all operations complete.

        Creates:
        - {mem}_{port}_latched_data: Latched read data
        - {mem}_{port}_latched_valid: Indicates latch contains valid data
        """
        # Find read port nodes for this memory
        mem_node = None
        for node in self.graph.nodes.values():
            if node.data.get('name') == mem_name and node.data.get('is_memory'):
                mem_node = node
                break

        if not mem_node or not mem_node.data.get('externalize_read', True):
            return

        # Get data width from memory node
        data_width = mem_node.data.get('bit_width', 32)

        # Find tracked read ports from memory declarations
        read_ports = mem_node.data.get('tracked_read_ports', [])

        # If no tracked ports but memory has reads, create a default latch
        if not read_ports:
            # Check if there are any read accesses to this memory
            has_reads = any(
                edge.data.get('type') == 'memory_read'
                for edge in mem_node.outgoing_edges
            )
            if has_reads:
                read_ports = [{'port_name': 'data'}]  # Default port name

        for port_info in read_ports:
            if isinstance(port_info, dict):
                port_name = port_info.get('port_name', 'data')
            else:
                port_name = str(port_info)

            # Create latched data register
            latch_data_id = f"{mem_name}_{port_name}_latched_data"
            latch_data = Node(latch_data_id, {
                'type': 'ext_mem_load_latch',
                'name': latch_data_id,
                'bit_width': data_width,
                'memory_name': mem_name,
                'port_name': port_name,
                'is_uarch_state': True,
                'latch_type': 'data',
                'description': f"Latched read data for {mem_name}.{port_name}"
            })
            latch_data.is_uarch_state = True
            self.graph.add_node(latch_data)
            self.load_latches.append(latch_data)

            # Create latched valid flag
            latch_valid_id = f"{mem_name}_{port_name}_latched_valid"
            latch_valid = Node(latch_valid_id, {
                'type': 'ext_mem_load_latch',
                'name': latch_valid_id,
                'bit_width': 1,
                'memory_name': mem_name,
                'port_name': port_name,
                'is_uarch_state': True,
                'latch_type': 'valid',
                'description': f"Valid flag for latched data from {mem_name}.{port_name}"
            })
            latch_valid.is_uarch_state = True
            self.graph.add_node(latch_valid)
            self.load_latches.append(latch_valid)

            print(f"    Created load latch for {mem_name}.{port_name}: {latch_data_id}")

    def _create_completion_signal(self, mem_name: str):
        """
        Create completion signal for a single memory.

        Complete when:
        - No pending operations (!read_pending && !write_pending)
        - All current requests have responses
        """
        complete_id = f"{mem_name}_ext_complete"
        complete_node = Node(complete_id, {
            'type': 'ext_mem_complete',
            'name': complete_id,
            'bit_width': 1,
            'memory_name': mem_name,
            'description': f"Completion signal for externalized memory {mem_name}"
        })
        self.graph.add_node(complete_node)
        self.completion_signals.append(complete_node)
        print(f"    Created completion signal: {complete_id}")

    def _create_combined_completion_signal(self) -> Node:
        """
        Create combined completion signal that ANDs all memory completions.

        This is the signal used to gate ISA state updates.
        """
        combined_id = "all_ext_mem_complete"
        combined_node = Node(combined_id, {
            'type': 'ext_mem_combined_complete',
            'name': combined_id,
            'bit_width': 1,
            'memory_names': self.externalized_memories,
            'completion_signals': [n.id for n in self.completion_signals],
            'description': "Combined completion signal for all externalized memories"
        })
        self.graph.add_node(combined_node)

        # Connect individual completion signals to combined
        for complete_node in self.completion_signals:
            edge = Edge(complete_node, combined_node, data={'type': 'operand'})
            self.graph.add_edge(edge)

        print(f"    Created combined completion signal: {combined_id}")
        return combined_node

    def _gate_all_isa_writes(self, complete_node: Node):
        """
        Gate all ISA state writes with the completion signal.

        This includes:
        - Scalar arch state (1D): pc, flags, etc.
        - Array arch state (2D): rf[32], frf[32], etc.
        - Memory nodes: dmem, imem (if not externalized)
        """
        isa_writes = self._find_all_isa_state_writes()

        if not isa_writes:
            print("    No ISA state writes to gate")
            return

        print(f"    Gating {len(isa_writes)} ISA state writes with {complete_node.id}:")

        # Create enable expression for the completion signal
        enable_expr = {
            'type': 'identifier',
            'name': complete_node.id
        }

        for write_node in isa_writes:
            # Add write_enable edge from completion signal
            enable_edge = Edge(complete_node, write_node, data={'type': 'write_enable'})
            self.graph.add_edge(enable_edge)

            # Mark the node with the gate condition
            if write_node.data is None:
                write_node.data = {}
            write_node.data['ext_mem_gated'] = True
            write_node.data['ext_mem_gate_signal'] = complete_node.id

            # Mark all incoming assignment edges as gated
            for edge in write_node.incoming_edges:
                if edge.data.get('type') == 'assignment':
                    edge.data['gated'] = True
                    edge.data['ext_mem_gated'] = True
                    edge.data['enable'] = enable_expr
                    edge.data['gate_condition'] = complete_node.id

            node_type = "memory" if write_node.data.get('is_memory') else "arch_state"
            has_array = write_node.data.get('array_depth') is not None
            dim = "2D" if has_array else "1D"
            print(f"      - {write_node.id} ({node_type}, {dim})")

    def _find_all_isa_state_writes(self) -> List[Node]:
        """
        Find ALL ISA state write nodes including:
        - Scalar arch state (1D): pc, flags, etc.
        - Array arch state (2D): rf[32], frf[32], etc.
        - Memory nodes: dmem, imem (if not externalized)

        An ISA write is any architectural state node with incoming assignment edges.
        """
        isa_writes = []
        for node in self.graph.nodes.values():
            # Include arch state (both scalar and array)
            is_isa_state = node.is_arch_state

            # Include non-externalized memory nodes
            is_internal_memory = (node.data.get('is_memory', False) and
                                  not node.data.get('externalized', False))

            if is_isa_state or is_internal_memory:
                # Check for incoming assignment edges (indicating a write)
                has_write = any(e.data.get('type') == 'assignment'
                               for e in node.incoming_edges)
                if has_write:
                    isa_writes.append(node)

        return isa_writes


def apply_externalized_memory_gating(graph: ResourceGraph) -> bool:
    """
    Apply externalized memory gating to a single-cycle machine.

    This should be called after memory externalization but before Verilog generation.

    Args:
        graph: Resource graph with externalized memories

    Returns:
        True if gating was applied, False otherwise
    """
    gating = ExternalizedMemoryGating(graph)
    return gating.apply()
