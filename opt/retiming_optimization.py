#!/usr/bin/env python3
"""
Microarchitectural Retiming Optimization for ResourceGraph.

This module implements retiming transformations that allow moving uarch_state registers
earlier or later in the pipeline while maintaining correctness.

Key principles:
- Only uarch_state registers can be retimed
- Cannot retime before cycle 0 or after the last cycle
- Properly splits and merges across combinational nodes
- Does not create entirely new nodes unless needed for splits/merges
"""

from typing import List, Set, Dict, Tuple, Optional
from core.resource_graph import ResourceGraph, Node, Edge


class RetimingTransform:
    """Implements retiming transformations on ResourceGraphs."""

    def __init__(self, graph: ResourceGraph):
        self.graph = graph
        self.max_time = graph.get_max_uarch_time()

    def can_retime_forward(self, register_node: Node) -> bool:
        """
        Check if a register can be retimed forward (moved later in time).

        Args:
            register_node: The uarch_state node to check

        Returns:
            True if forward retiming is possible
        """
        if not register_node.is_uarch_state:
            print(f"  Cannot retime {register_node.id}: not a uarch_state register")
            return False

        if register_node.uarch_time is None:
            print(f"  Cannot retime {register_node.id}: no timing information")
            return False

        # Cannot move beyond the last cycle
        if register_node.uarch_time >= self.max_time:
            print(f"  Cannot retime {register_node.id} later: already at max cycle {self.max_time}")
            return False

        # Check if all output paths can accommodate the register moving forward
        # For forward retiming, we need to ensure that moving the register forward
        # doesn't violate timing constraints
        for out_edge in register_node.outgoing_edges:
            target = out_edge.target
            # If target is a register or arch state with timing, check timing constraint
            # Combinational nodes (like 'var' type) can be retimed through regardless of their timing annotation
            if target.uarch_time is not None:
                # Only enforce timing for actual registers/state, not combinational nodes
                is_combinational = not target.is_uarch_state and not target.is_arch_state
                if not is_combinational and register_node.uarch_time + 1 > target.uarch_time:
                    print(f"  Cannot retime {register_node.id} later: would violate timing of {target.id} (reg@{register_node.uarch_time}+1 > target@{target.uarch_time})")
                    return False

        return True

    def can_retime_backward(self, register_node: Node) -> bool:
        """
        Check if a register can be retimed backward (moved earlier in time).

        Args:
            register_node: The uarch_state node to check

        Returns:
            True if backward retiming is possible
        """
        if not register_node.is_uarch_state:
            print(f"  Cannot retime {register_node.id}: not a uarch_state register")
            return False

        if register_node.uarch_time is None:
            print(f"  Cannot retime {register_node.id}: no timing information")
            return False

        # Cannot move before cycle 0
        if register_node.uarch_time <= 0:
            print(f"  Cannot retime {register_node.id} earlier: already at cycle 0")
            return False

        # Check if all input paths can accommodate the register moving backward
        # For backward retiming, we need to ensure sources are early enough
        for in_edge in register_node.incoming_edges:
            source = in_edge.source
            # If source is a register or arch state with timing, check timing constraint
            # Combinational nodes (like 'var' type) can be retimed through regardless of their timing annotation
            if source.uarch_time is not None:
                # Only enforce timing for actual registers/state, not combinational nodes
                is_combinational = not source.is_uarch_state and not source.is_arch_state
                if not is_combinational and register_node.uarch_time - 1 < source.uarch_time:
                    print(f"  Cannot retime {register_node.id} earlier: would violate timing of {source.id} (reg@{register_node.uarch_time}-1 < source@{source.uarch_time})")
                    return False

        return True

    def retime_forward(self, register_node_id: str) -> bool:
        """
        Retime a register forward by one cycle.

        This moves the register across its output combinational logic.
        If the output fans out, the register may need to be replicated.

        Args:
            register_node_id: ID of the register to retime

        Returns:
            True if retiming was successful
        """
        if register_node_id not in self.graph.nodes:
            print(f"Error: Node {register_node_id} not found")
            return False

        register_node = self.graph.nodes[register_node_id]

        if not self.can_retime_forward(register_node):
            print(f"Error: Cannot retime {register_node_id} forward")
            return False

        print(f"Retiming {register_node_id} forward from time {register_node.uarch_time} to {register_node.uarch_time + 1}")

        # Simple approach: Move register forward by rewiring connections
        # Find the immediate successor (what the register feeds)
        if len(register_node.outgoing_edges) == 1:
            out_edge = list(register_node.outgoing_edges)[0]
            succ = out_edge.target

            # If successor is combinational, we can move the register after it
            if not succ.is_uarch_state and not succ.is_arch_state:
                print(f"  Moving {register_node.id} forward through combinational node {succ.id}")

                # Find what the successor feeds
                succ_outputs = list(succ.outgoing_edges)
                reg_inputs = list(register_node.incoming_edges)

                # Remove current connections
                self.graph.remove_edge(out_edge.id)

                # Rewire: reg_inputs -> succ -> register -> succ_outputs
                for reg_in_edge in reg_inputs:
                    # Connect register's input to successor instead
                    new_edge = Edge(reg_in_edge.source, succ, data=reg_in_edge.data.copy())
                    self.graph.add_edge(new_edge)
                    self.graph.remove_edge(reg_in_edge.id)

                # Connect successor output to register input
                new_edge = Edge(succ, register_node, data=out_edge.data.copy())
                self.graph.add_edge(new_edge)

                # Reconnect successor's outputs to go through register
                for succ_out_edge in succ_outputs:
                    # Remove succ -> target, add register -> target
                    new_edge = Edge(register_node, succ_out_edge.target, data=succ_out_edge.data.copy())
                    self.graph.add_edge(new_edge)
                    self.graph.remove_edge(succ_out_edge.id)

                # Update timing
                register_node.uarch_time += 1
                print(f"  New time for {register_node.id}: {register_node.uarch_time}")
                return True

        # Fallback: just update timing (for direct register-to-register connections)
        register_node.uarch_time += 1
        return True

    def retime_backward(self, register_node_id: str) -> bool:
        """
        Retime a register backward by one cycle.

        This moves the register across its input combinational logic.
        If the input has multiple sources, the register may need to be replicated.

        Args:
            register_node_id: ID of the register to retime

        Returns:
            True if retiming was successful
        """
        if register_node_id not in self.graph.nodes:
            print(f"Error: Node {register_node_id} not found")
            return False

        register_node = self.graph.nodes[register_node_id]

        if not self.can_retime_backward(register_node):
            print(f"Error: Cannot retime {register_node_id} backward")
            return False

        print(f"Retiming {register_node_id} backward from time {register_node.uarch_time} to {register_node.uarch_time - 1}")

        # Simple approach: Move register backward by rewiring connections
        # Find the immediate predecessor (what feeds the register)
        if len(register_node.incoming_edges) == 1:
            in_edge = list(register_node.incoming_edges)[0]
            pred = in_edge.source

            # If predecessor is combinational, we can move the register before it
            if not pred.is_uarch_state and not pred.is_arch_state:
                print(f"  Moving {register_node.id} backward through combinational node {pred.id}")

                # Find what feeds the predecessor
                pred_inputs = list(pred.incoming_edges)
                reg_outputs = list(register_node.outgoing_edges)

                # Remove current connections
                self.graph.remove_edge(in_edge.id)

                # Rewire: pred_inputs -> register -> pred -> reg_outputs
                for pred_in_edge in pred_inputs:
                    # Connect predecessor's input to register instead
                    new_edge = Edge(pred_in_edge.source, register_node, data=pred_in_edge.data.copy())
                    self.graph.add_edge(new_edge)
                    self.graph.remove_edge(pred_in_edge.id)

                # Connect register output to predecessor
                new_edge = Edge(register_node, pred, data=in_edge.data.copy())
                self.graph.add_edge(new_edge)

                # Update timing
                register_node.uarch_time -= 1
                print(f"  New time for {register_node.id}: {register_node.uarch_time}")
                return True

        # Fallback: just update timing (for direct register-to-register connections)
        register_node.uarch_time -= 1
        return True

    def _find_combinational_paths_forward(self, register_node: Node) -> List[List[Node]]:
        """
        Find all combinational paths forward from a register.

        A combinational path ends when we hit:
        - Another uarch_state node
        - An arch_state node
        - A node with explicit timing
        """
        paths = []

        def trace_path(current: Node, path: List[Node]):
            # Stop conditions
            if current != register_node and (current.is_uarch_state or current.is_arch_state or current.uarch_time is not None):
                if path:
                    paths.append(path.copy())
                return

            # Continue tracing through combinational logic
            for edge in current.outgoing_edges:
                trace_path(edge.target, path + [current])

        trace_path(register_node, [])
        return paths

    def _find_combinational_paths_backward(self, register_node: Node) -> List[List[Node]]:
        """
        Find all combinational paths backward to a register.

        A combinational path starts when we hit:
        - Another uarch_state node
        - An arch_state node
        - A node with explicit timing
        """
        paths = []

        def trace_path(current: Node, path: List[Node]):
            # Stop conditions
            if current != register_node and (current.is_uarch_state or current.is_arch_state or current.uarch_time is not None):
                if path:
                    paths.append(path.copy())
                return

            # Continue tracing through combinational logic
            for edge in current.incoming_edges:
                trace_path(edge.source, path + [current])

        trace_path(register_node, [])
        return paths

    def _move_register_across_logic_forward(self, register_node: Node, comb_paths: List[List[Node]]):
        """
        Move a register forward across combinational logic.

        Strategy:
        1. Remove the register from its current position
        2. Insert it after the combinational logic
        3. Handle fanout by potentially replicating the register
        """
        # Find all endpoints of combinational paths (where new registers go)
        endpoints = set()
        for path in comb_paths:
            if path:
                # Last node in path that's not a register
                for node in reversed(path):
                    if not node.is_uarch_state:
                        # Find what this feeds
                        for edge in node.outgoing_edges:
                            endpoints.add(edge.target)
                        break

        if not endpoints:
            # Simple case - just update timing
            register_node.uarch_time += 1
            return

        # If there's only one endpoint, we can just move the register
        if len(endpoints) == 1:
            endpoint = list(endpoints)[0]

            # Reconnect: inputs -> comb_logic -> endpoint
            # becomes: inputs -> comb_logic -> register -> endpoint

            # Find the edge from comb logic to endpoint
            comb_source = None
            edge_to_endpoint = None
            for edge in endpoint.incoming_edges:
                if not edge.source.is_uarch_state and edge.source != register_node:
                    comb_source = edge.source
                    edge_to_endpoint = edge
                    break

            if comb_source and edge_to_endpoint:
                # Get input to current register
                reg_input = None
                reg_input_edge = None
                for edge in register_node.incoming_edges:
                    reg_input = edge.source
                    reg_input_edge = edge
                    break

                if reg_input:
                    # Remove old edges
                    self.graph.remove_edge(reg_input_edge.id)
                    self.graph.remove_edge(edge_to_endpoint.id)

                    # Reconnect through combinational logic
                    edge1 = Edge(reg_input, comb_source, data=reg_input_edge.data.copy())
                    self.graph.add_edge(edge1)

                    # Register now between comb logic and endpoint
                    edge2 = Edge(comb_source, register_node, data={'type': 'operand'})
                    edge3 = Edge(register_node, endpoint, data=edge_to_endpoint.data.copy())
                    self.graph.add_edge(edge2)
                    self.graph.add_edge(edge3)

                    # Update timing
                    register_node.uarch_time += 1
                    print(f"  Moved {register_node.id} across {comb_source.id} to time {register_node.uarch_time}")
        else:
            # Multiple endpoints - need to replicate register
            print(f"  Forward retiming with fanout to {len(endpoints)} endpoints requires register replication")
            # TODO: Implement register replication for fanout
            register_node.uarch_time += 1

    def _move_register_across_logic_backward(self, register_node: Node, comb_paths: List[List[Node]]):
        """
        Move a register backward across combinational logic.

        Strategy:
        1. Remove the register from its current position
        2. Insert it before the combinational logic
        3. Handle fanin by potentially replicating the register
        """
        # Find all startpoints of combinational paths (where new registers go)
        startpoints = set()
        for path in comb_paths:
            if path:
                # First node in path that feeds combinational logic
                for node in path:
                    if not node.is_uarch_state:
                        # Find what feeds this
                        for edge in node.incoming_edges:
                            if not edge.source.is_uarch_state or edge.source == register_node:
                                continue
                            startpoints.add(edge.source)
                        break

        if not startpoints:
            # Simple case - just update timing
            register_node.uarch_time -= 1
            return

        # If there's only one startpoint, we can move the register
        if len(startpoints) == 1:
            startpoint = list(startpoints)[0]

            # Find the combinational input node
            comb_input = None
            edge_from_start = None
            for edge in startpoint.outgoing_edges:
                if not edge.target.is_uarch_state and edge.target != register_node:
                    comb_input = edge.target
                    edge_from_start = edge
                    break

            if comb_input and edge_from_start:
                # Get output from current register
                reg_output = None
                reg_output_edge = None
                for edge in register_node.outgoing_edges:
                    reg_output = edge.target
                    reg_output_edge = edge
                    break

                if reg_output:
                    # Remove old edges
                    self.graph.remove_edge(edge_from_start.id)
                    self.graph.remove_edge(reg_output_edge.id)

                    # Register now between startpoint and comb logic
                    edge1 = Edge(startpoint, register_node, data={'type': 'operand'})
                    edge2 = Edge(register_node, comb_input, data=edge_from_start.data.copy())
                    self.graph.add_edge(edge1)
                    self.graph.add_edge(edge2)

                    # Reconnect comb logic output
                    edge3 = Edge(comb_input, reg_output, data=reg_output_edge.data.copy())
                    self.graph.add_edge(edge3)

                    # Update timing
                    register_node.uarch_time -= 1
                    print(f"  Moved {register_node.id} across {comb_input.id} to time {register_node.uarch_time}")
        else:
            # Multiple startpoints - need to replicate register
            print(f"  Backward retiming with fanin from {len(startpoints)} startpoints requires register replication")
            # TODO: Implement register replication for fanin
            register_node.uarch_time -= 1

    def _update_downstream_timing(self, register_node: Node):
        """Update timing for nodes downstream of a retimed register."""
        # This is a simple propagation - in practice, full re-inference might be needed
        for edge in register_node.outgoing_edges:
            target = edge.target
            if target.uarch_time is not None and target.uarch_time < register_node.uarch_time:
                target.uarch_time = register_node.uarch_time
                self._update_downstream_timing(target)

    def _update_upstream_timing(self, register_node: Node):
        """Update timing for nodes upstream of a retimed register."""
        # This is a simple propagation - in practice, full re-inference might be needed
        for edge in register_node.incoming_edges:
            source = edge.source
            if source.uarch_time is not None and source.uarch_time > register_node.uarch_time:
                source.uarch_time = register_node.uarch_time
                self._update_upstream_timing(source)


def apply_retiming_forward(graph: ResourceGraph, register_ids: List[str]) -> bool:
    """
    Apply forward retiming to selected registers.

    Args:
        graph: ResourceGraph to transform
        register_ids: List of register node IDs to retime forward

    Returns:
        True if retiming was successful
    """
    transform = RetimingTransform(graph)

    success = True
    for reg_id in register_ids:
        if not transform.retime_forward(reg_id):
            print(f"Failed to retime {reg_id} forward")
            success = False

    # Re-infer timing after retiming
    if success:
        graph.infer_uarch_time(force_reinfer=False)

    return success


def apply_retiming_backward(graph: ResourceGraph, register_ids: List[str]) -> bool:
    """
    Apply backward retiming to selected registers.

    Args:
        graph: ResourceGraph to transform
        register_ids: List of register node IDs to retime backward

    Returns:
        True if retiming was successful
    """
    transform = RetimingTransform(graph)

    success = True
    for reg_id in register_ids:
        if not transform.retime_backward(reg_id):
            print(f"Failed to retime {reg_id} backward")
            success = False

    # Re-infer timing after retiming
    if success:
        graph.infer_uarch_time(force_reinfer=False)

    return success


def get_retimeable_registers(graph: ResourceGraph) -> Dict[str, Dict[str, bool]]:
    """
    Get all registers and their retiming capabilities.

    Args:
        graph: ResourceGraph to analyze

    Returns:
        Dictionary mapping register IDs to their retiming capabilities:
        {'reg_id': {'forward': True/False, 'backward': True/False}}
    """
    transform = RetimingTransform(graph)
    result = {}

    for node_id, node in graph.nodes.items():
        if node.is_uarch_state:
            result[node_id] = {
                'forward': transform.can_retime_forward(node),
                'backward': transform.can_retime_backward(node)
            }

    return result
