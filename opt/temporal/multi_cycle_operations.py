"""
Multi-cycle operation support for ResourceGraphs.

This module implements algorithms to handle operations with different latencies,
creating proper pipeline stall logic and completion detection.
"""

import re
from typing import Dict, List, Set, Tuple, Optional
from core.resource_graph import ResourceGraph, Node, Edge
from opt.isa_state_gating import ISAStateGatingHelper
from core.array_access_utils import ArrayAccessAnalyzer


def sanitize_identifier(identifier: str) -> str:
    """Convert an identifier to a valid Verilog/VHDL identifier.

    Replaces special characters with underscores or descriptive names.
    """
    sanitized = identifier
    sanitized = sanitized.replace('(', '_').replace(')', '_')
    sanitized = sanitized.replace('[', '_').replace(']', '_')
    sanitized = sanitized.replace(',', '_').replace(' ', '_')
    sanitized = sanitized.replace('.', '_').replace("'", '_')
    sanitized = sanitized.replace('{', '_').replace('}', '_')
    # Remove consecutive underscores and trailing underscores
    sanitized = re.sub(r'_+', '_', sanitized)
    sanitized = sanitized.rstrip('_')
    return sanitized


class OperationLatencySpec:
    """Specification for operation latency."""

    def __init__(self, operation_id: str, latency_cycles: int, operation_type: str = ""):
        self.operation_id = operation_id
        self.latency_cycles = latency_cycles
        self.operation_type = operation_type  # e.g., "multiply", "divide", "memory_load"

        if latency_cycles < 0:
            raise ValueError(f"Latency must be at least 0 (combinational), got {latency_cycles}")

    def __str__(self):
        type_str = f" ({self.operation_type})" if self.operation_type else ""
        return f"{self.operation_id}{type_str}: {self.latency_cycles} cycles"


class MultiCycleOperationTransform:
    """Transforms operations to support multiple cycle latencies."""

    def __init__(self, graph: ResourceGraph):
        self.graph = graph

    def apply_multi_cycle_latency(self, spec: OperationLatencySpec) -> bool:
        """Apply multi-cycle latency to a specific operation.

        Sets the latency attribute on the node and creates necessary gating logic.
        The operation node itself has complete and cycle outputs for gating.

        Args:
            spec: Operation latency specification

        Returns:
            True if successful, False otherwise
        """

        print(f"\\nApplying multi-cycle latency: {spec}")

        # Find the target operation
        target_operation = self.graph.nodes.get(spec.operation_id)
        if not target_operation:
            print(f"  Error: Operation {spec.operation_id} not found")
            return False

        if target_operation.data.get('type') not in ['operation', 'alu_module', 'fp_operation']:
            print(f"  Error: Node {spec.operation_id} is not an operation, ALU module, or FP operation")
            return False

        # Analyze operation dependencies
        operation_analysis = self._analyze_operation_dependencies(target_operation)

        print(f"  Operation type: {target_operation.data.get('type')}")
        print(f"  Input dependencies: {len(operation_analysis['inputs'])}")
        print(f"  Output dependencies: {len(operation_analysis['outputs'])}")

        # Apply latency to the node
        self._apply_latency_to_node(target_operation, spec, operation_analysis)

        return True

    def _analyze_operation_dependencies(self, operation: Node) -> Dict:
        """Analyze operation dependencies for pipeline integration."""

        inputs = []
        outputs = []

        # Find input dependencies
        for edge in operation.incoming_edges:
            if edge.data.get('type') in ['operand', 'alu_operand', 'opcode_control']:
                inputs.append({
                    'source': edge.source,
                    'edge_type': edge.data.get('type'),
                    'signal_name': edge.data.get('signal_name', ''),
                    'operand_position': edge.data.get('operand_position')
                })

        # Find output dependencies
        for edge in operation.outgoing_edges:
            if edge.data.get('type') in ['assignment', 'alu_result']:
                outputs.append({
                    'target': edge.target,
                    'edge_type': edge.data.get('type'),
                    'enable_signal': edge.data.get('enable_signal', ''),
                    'gated_by': edge.data.get('gated_by', '')
                })

        return {
            'inputs': inputs,
            'outputs': outputs,
            'operation_type': operation.data.get('type'),
            'operation_name': operation.data.get('name', operation.id)
        }

    def _create_latency_cycle_counter(self, operation_id: str, latency_cycles: int) -> Node:
        """Create a cycle counter for tracking multi-cycle operation progress.

        Creates a counter node similar to serialization_counter, which tracks
        the current cycle of execution for a multi-cycle operation.

        Args:
            operation_id: ID of the operation
            latency_cycles: Number of cycles the operation takes

        Returns:
            The created counter node
        """
        import math

        safe_id = sanitize_identifier(operation_id)
        counter_name = f"{safe_id}_cycle_counter"
        counter_width = math.ceil(math.log2(latency_cycles + 1))

        counter_data = {
            'type': 'uarch_counter',
            'name': counter_name,
            'display_name': f"{operation_id} cycle counter",
            'bit_width': counter_width,
            'max_count': latency_cycles - 1,
            'operation_id': operation_id
        }

        counter_node = Node(counter_name, counter_data, is_uarch_state=True)
        counter_node.uarch_time = 0  # Counter starts at cycle 0
        self.graph.add_node(counter_node)

        return counter_node

    def _create_control_signal_nodes(self, operation: Node) -> Tuple[Node, Node, Node]:
        """Create start/idle/complete control signal nodes for a multi-cycle operation.

        These signals enable proper pipeline integration:
        - start: Input signal to initiate the operation
        - idle: Output signal indicating ready for new request
        - complete: Output signal indicating operation finished

        Args:
            operation: The operation node

        Returns:
            Tuple of (start_node, idle_node, complete_node)
        """
        safe_id = sanitize_identifier(operation.id)

        # Create start signal node (input to operation)
        start_node = Node(
            node_id=f"{safe_id}_start",
            data={
                'type': 'control_signal',
                'signal_type': 'start',
                'operation': operation.id,
                'direction': 'input',
                'description': f"Start signal for {operation.id}",
                'bit_width': 1
            }
        )
        self.graph.add_node(start_node)

        # Create edge from start signal to operation
        start_edge = Edge(
            source=start_node,
            target=operation,
            data={
                'type': 'control',
                'signal_type': 'start',
                'description': f"Start signal to {operation.id}"
            }
        )
        self.graph.add_edge(start_edge)

        # Create idle signal node (output from operation)
        idle_node = Node(
            node_id=f"{safe_id}_idle",
            data={
                'type': 'control_signal',
                'signal_type': 'idle',
                'operation': operation.id,
                'direction': 'output',
                'description': f"Idle signal for {operation.id} (ready for new request)",
                'bit_width': 1
            }
        )
        self.graph.add_node(idle_node)

        # Create edge from operation to idle signal
        idle_edge = Edge(
            source=operation,
            target=idle_node,
            data={
                'type': 'control',
                'signal_type': 'idle',
                'description': f"Idle signal from {operation.id}"
            }
        )
        self.graph.add_edge(idle_edge)

        # Create complete signal node (output from operation)
        complete_node = Node(
            node_id=f"{safe_id}_complete",
            data={
                'type': 'control_signal',
                'signal_type': 'complete',
                'operation': operation.id,
                'direction': 'output',
                'description': f"Completion signal for {operation.id}",
                'bit_width': 1
            }
        )
        self.graph.add_node(complete_node)

        # Create edge from operation to complete signal
        complete_edge = Edge(
            source=operation,
            target=complete_node,
            data={
                'type': 'control',
                'signal_type': 'complete',
                'description': f"Completion signal from {operation.id}"
            }
        )
        self.graph.add_edge(complete_edge)

        return start_node, idle_node, complete_node

    def _apply_latency_to_node(self, operation: Node, spec: OperationLatencySpec,
                               analysis: Dict):
        """Apply multi-cycle latency to a node.

        Creates a cycle counter, control signal nodes (start/idle/complete),
        and uses ISAStateGatingHelper to properly gate ISA writes.
        """

        print(f"  Setting latency on node: {operation.id}")

        # Set the latency attribute
        operation.latency = spec.latency_cycles

        # Update node metadata
        operation.data['multi_cycle'] = True
        operation.data['latency_cycles'] = spec.latency_cycles
        operation.data['operation_type'] = spec.operation_type

        # Create cycle counter for tracking operation progress
        counter_node = self._create_latency_cycle_counter(operation.id, spec.latency_cycles)
        operation.data['cycle_counter'] = counter_node.id

        # Create control signal nodes (start, idle, complete)
        start_node, idle_node, complete_node = self._create_control_signal_nodes(operation)

        # Store signal references in operation metadata
        operation.data['start_signal'] = start_node.id
        operation.data['idle_signal'] = idle_node.id
        operation.data['complete_signal'] = complete_node.id
        operation.data['has_start_input'] = True
        operation.data['has_idle_output'] = True
        operation.data['has_complete_output'] = True
        operation.data['has_cycle_output'] = True

        # Gate ISA state writes based on operation completion using proper SMT-compatible format
        self._gate_isa_writes_on_completion(operation, spec, analysis, counter_node)

        print(f"  Multi-cycle latency applied:")
        print(f"    - Latency: {spec.latency_cycles} cycles")
        print(f"    - Created cycle counter: {counter_node.id}")
        print(f"    - Created control signals: {start_node.id}, {idle_node.id}, {complete_node.id}")
        print(f"    - ISA writes gated with SMT-compatible enable expression")

        # Clear timing for downstream nodes that need to be re-inferred
        self._clear_downstream_timing(analysis['outputs'])

    def _gate_isa_writes_on_completion(self, operation: Node, spec: OperationLatencySpec,
                                      analysis: Dict, counter_node: Node):
        """Gate ALL ISA state writes to only occur when the operation completes.

        Uses ISAStateGatingHelper to create proper SMT-compatible enable expressions
        based on the cycle counter reaching the final cycle value.

        Args:
            operation: The operation node being made multi-cycle
            spec: Operation latency specification
            analysis: Operation dependency analysis
            counter_node: The cycle counter node tracking operation progress
        """
        final_cycle = spec.latency_cycles

        print(f"    - Gating {len(self.graph.nodes)} total nodes checked for ISA writes")

        # Use ISAStateGatingHelper to create proper enable comparator and gate ISA writes
        gating_helper = ISAStateGatingHelper(self.graph)

        # This creates:
        # 1. Enable comparator node with expression: (counter == final_cycle)
        # 2. Proper enable metadata on ISA writes
        # 3. write_enable edges from enable node to ISA writes
        enable_node = gating_helper.gate_all_isa_writes_for_operation(
            operation_id=operation.id,
            counter_node=counter_node,
            final_cycle=final_cycle - 1,  # Counter counts from 0, so final is latency-1
            enable_type='multi_cycle_enable',
            gate_condition_fmt=f"{counter_node.id} == {final_cycle - 1}"
        )

        print(f"    - Created enable comparator: {enable_node.id}")
        print(f"    - Enable expression: ({counter_node.id} == {final_cycle - 1})")

    def _clear_downstream_timing(self, output_deps: List[Dict]):
        """Clear timing for nodes downstream of multi-cycle operations to allow re-inference."""

        visited = set()
        nodes_to_clear = []

        for output_dep in output_deps:
            target = output_dep['target']
            self._collect_downstream_nodes(target, visited, nodes_to_clear)

        for node in nodes_to_clear:
            # Don't clear timing for architectural state or uarch state nodes
            if not node.is_arch_state and not node.is_uarch_state:
                node.uarch_time = None

        if nodes_to_clear:
            print(f"    - Cleared timing for {len(nodes_to_clear)} downstream nodes")

    def _collect_downstream_nodes(self, node: Node, visited: Set[Node], nodes_to_clear: List[Node]):
        """Recursively collect nodes downstream of the given node."""

        if node in visited:
            return

        visited.add(node)
        nodes_to_clear.append(node)

        # Follow outgoing edges to collect downstream nodes
        for edge in node.outgoing_edges:
            target = edge.target
            # Don't follow edges to architectural state or control nodes
            if not target.is_arch_state and not target.is_uarch_state:
                node_type = target.data.get('type', '')
                if node_type not in ['uarch_counter', 'hazard_detection_unit', 'stall_controller']:
                    self._collect_downstream_nodes(target, visited, nodes_to_clear)

    def update_graph_timing(self):
        """Update overall graph timing to account for multi-cycle operations."""

        print("\\nUpdating graph timing for multi-cycle operations...")

        # Find all multi-cycle operations
        multi_cycle_ops = []
        for node in self.graph.nodes.values():
            if node.data.get('multi_cycle'):
                latency = node.data.get('latency_cycles', 1)
                multi_cycle_ops.append((node, latency))

        if not multi_cycle_ops:
            print("  No multi-cycle operations found")
            return

        print(f"  Found {len(multi_cycle_ops)} multi-cycle operations:")
        for op, latency in multi_cycle_ops:
            print(f"    {op.id}: {latency} cycles")

        # Re-infer timing considering pipeline stages
        # Use force_reinfer=False to preserve multi-cycle operation timing
        self.graph.infer_uarch_time(force_reinfer=False)

        max_time = self.graph.get_max_uarch_time()
        print(f"  Updated pipeline depth: {max_time + 1} cycles")


def apply_multi_cycle_operations(graph: ResourceGraph, latency_specs: List[OperationLatencySpec]) -> bool:
    """
    Apply multi-cycle latency specifications to operations in a ResourceGraph.

    Sets the latency attribute on nodes and creates necessary gating logic.
    The operation nodes themselves have implicit complete and cycle outputs.

    Args:
        graph: ResourceGraph to transform
        latency_specs: List of operation latency specifications

    Returns:
        True if any operations were made multi-cycle, False otherwise
    """
    transform = MultiCycleOperationTransform(graph)

    applied_any = False
    for spec in latency_specs:
        if transform.apply_multi_cycle_latency(spec):
            applied_any = True

    if applied_any:
        # Re-infer uarch_time to propagate timing changes throughout the graph
        print("\nRe-inferring uarch_time after multi-cycle operations...")
        graph.infer_uarch_time(force_reinfer=True)
        print("Uarch_time inference complete")

    return applied_any


def change_operation_latency(graph: ResourceGraph, operation_id: str,
                            target_latency: int) -> bool:
    """
    Change the latency of an operation, validating and adjusting gating logic as needed.

    This function:
    1. Validates that the latency change is legal
    2. Cleans up old multi-cycle logic if reducing latency
    3. Inserts new multi-cycle logic if increasing latency
    4. Handles combinational (latency=0) operations

    Args:
        graph: ResourceGraph to modify
        operation_id: ID of the operation node
        target_latency: Target latency in cycles (0 = combinational, no multi-cycle logic)

    Returns:
        True if successful, False if the change is illegal or fails
    """

    print(f"\n=== Changing Operation Latency ===")
    print(f"Operation: {operation_id}")
    print(f"Target latency: {target_latency} cycle(s)")

    # Find the operation
    operation = graph.nodes.get(operation_id)

    if not operation:
        print(f"ERROR: Operation {operation_id} not found in graph")
        return False

    current_latency = operation.latency
    print(f"Current latency: {current_latency} cycle(s)")

    # Check if operation type is valid
    if operation.data.get('type') not in ['operation', 'alu_module', 'fp_operation']:
        print(f"ERROR: Node {operation_id} is not an operation, ALU module, or FP operation")
        return False

    # Validate target latency
    if target_latency < 0:
        print(f"ERROR: Latency must be at least 0 (combinational), got {target_latency}")
        return False

    # Check if already at target latency
    if current_latency == target_latency:
        print(f"Operation already has latency of {target_latency} cycle(s), no change needed")
        return True

    # Validate that the change is legal
    if not _validate_latency_change(graph, operation, target_latency):
        print(f"ERROR: Latency change to {target_latency} cycles is not legal for this operation")
        return False

    print(f"✓ Latency change validated as legal")

    # Clean up old multi-cycle logic if it exists
    if current_latency > 0:
        print(f"\nCleaning up old multi-cycle logic (latency={current_latency})...")
        _cleanup_multi_cycle_logic(graph, operation_id)

    # Apply new latency
    if target_latency == 0:
        # Combinational operation (no latency)
        print(f"\nSetting to combinational operation (latency=0)")
        operation.latency = 0
        operation.data['multi_cycle'] = False
        operation.data['latency_cycles'] = 0
        operation.data['has_complete_output'] = False
        operation.data['has_cycle_output'] = False
        print(f"✓ Operation is now combinational")

    else:
        # Multi-cycle operation, apply the transformation
        print(f"\nApplying multi-cycle transformation (latency={target_latency})...")
        spec = OperationLatencySpec(operation_id, target_latency, operation.data.get('operation_type', 'operation'))

        # Use the existing multi-cycle operations logic
        success = apply_multi_cycle_operations(graph, [spec])

        if not success:
            print(f"ERROR: Failed to apply multi-cycle transformation")
            return False

    # Re-infer timing - force complete re-inference to ensure proper propagation
    print(f"\nRe-inferring timing...")
    graph.infer_uarch_time(force_reinfer=True)

    print(f"\n✓ Latency successfully changed from {current_latency} to {target_latency} cycle(s)")
    return True


def _validate_latency_change(graph: ResourceGraph, operation: Node, target_latency: int) -> bool:
    """
    Validate that a latency change is legal and safe.

    Checks for:
    1. The operation is a valid operation node
    2. Latency reduction doesn't break existing hazard resolution
    3. No stall/bypass logic depends on the current latency

    Args:
        graph: ResourceGraph
        operation: Operation node
        target_latency: Target latency

    Returns:
        True if the change is safe, False otherwise with warnings
    """

    current_latency = operation.latency

    # If increasing latency or setting for the first time, always safe
    if target_latency >= current_latency:
        return True

    # Reducing latency - need to check for safety issues
    print(f"\n  ⚠️  Reducing latency from {current_latency} to {target_latency}")
    print(f"  Checking for safety issues...")

    warnings = []

    # Check 1: Look for stall logic that might depend on this operation
    stall_controllers = [n for n in graph.nodes.values()
                        if n.data.get('type') == 'stall_controller']

    if stall_controllers:
        warnings.append(f"Found {len(stall_controllers)} stall controller(s) in graph")
        print(f"    - {len(stall_controllers)} stall controller(s) exist")

    # Check 2: Look for bypass/forwarding logic
    bypass_nodes = [n for n in graph.nodes.values()
                   if 'bypass' in n.id.lower() or 'forward' in n.id.lower()]

    if bypass_nodes:
        warnings.append(f"Found {len(bypass_nodes)} bypass/forwarding node(s)")
        print(f"    - {len(bypass_nodes)} bypass/forwarding node(s) exist")

    # Check 3: Look for pipeline registers that might be affected
    pipe_regs = [n for n in graph.nodes.values()
                if n.data.get('type') == 'pipeline_register']

    if pipe_regs:
        # Check if any are gated by this operation
        gated_by_this = [r for r in pipe_regs
                        if r.data.get('gated_by_operation') == operation.id]

        if gated_by_this:
            warnings.append(f"{len(gated_by_this)} pipeline register(s) gated by this operation")
            print(f"    - {len(gated_by_this)} pipeline register(s) gated by this operation")
            print(f"      (will be automatically ungated)")

    # Check 4: Look for explicit timing dependencies
    timing_deps = []
    if hasattr(operation, 'outgoing_edges'):
        for edge in operation.outgoing_edges:
            if edge.data.get('type') in ['timing_constraint', 'dependency']:
                timing_deps.append(edge)

    if timing_deps:
        warnings.append(f"Found {len(timing_deps)} timing/dependency edge(s)")
        print(f"    - {len(timing_deps)} timing/dependency edge(s)")

    # Check 5: Check if this operation is part of hazard resolution
    # Look for metadata indicating hazard resolution was applied
    has_hazard_metadata = (
        operation.data.get('resolves_hazard') or
        operation.data.get('hazard_resolution_target') or
        operation.data.get('part_of_stall_logic')
    )

    if has_hazard_metadata:
        warnings.append("Operation is part of hazard resolution logic")
        print(f"    - Operation is part of hazard resolution logic")

    # Display summary
    if warnings:
        print(f"\n  ⚠️  SAFETY WARNINGS ({len(warnings)} issue(s)):")
        for w in warnings:
            print(f"    • {w}")

        print(f"\n  Latency reduction may require:")
        print(f"    - Re-running hazard analysis")
        print(f"    - Updating stall/bypass logic")
        print(f"    - Verifying pipeline timing")

        # For now, we allow it but warn
        # In the future, could make this configurable or block unsafe changes
        print(f"\n  ⚠️  Proceeding with latency change (warnings noted)")
        return True
    else:
        print(f"  ✓ No safety issues detected")
        return True


def _cleanup_multi_cycle_logic(graph: ResourceGraph, operation_id: str):
    """
    Clean up multi-cycle logic for an operation.

    Removes:
    - Cycle counter node
    - Enable comparator node
    - Enable metadata from ISA writes
    - write_enable edges

    Args:
        graph: ResourceGraph
        operation_id: Operation ID
    """

    operation = graph.nodes.get(operation_id)
    if not operation:
        print(f"  Warning: Operation {operation_id} not found")
        return

    # Find and remove the cycle counter node
    counter_id = operation.data.get('cycle_counter')
    if counter_id and counter_id in graph.nodes:
        counter_node = graph.nodes[counter_id]

        # Remove all edges connected to counter
        edges_to_remove = list(counter_node.incoming_edges) + list(counter_node.outgoing_edges)
        for edge in edges_to_remove:
            edge.remove_from_nodes()
            if edge.id in graph.edges:
                del graph.edges[edge.id]

        # Remove counter node
        del graph.nodes[counter_id]
        print(f"  Removed cycle counter: {counter_id}")

    # Find and remove the enable comparator node
    safe_op_id = sanitize_identifier(operation_id)
    enable_id = f"{safe_op_id}_enable"
    if enable_id in graph.nodes:
        enable_node = graph.nodes[enable_id]

        # Remove all edges connected to enable node
        edges_to_remove = list(enable_node.incoming_edges) + list(enable_node.outgoing_edges)
        for edge in edges_to_remove:
            edge.remove_from_nodes()
            if edge.id in graph.edges:
                del graph.edges[edge.id]

        # Remove enable node
        del graph.nodes[enable_id]
        print(f"  Removed enable comparator: {enable_id}")

    # Ungate ISA state writes
    isa_writes = [n for n in graph.nodes.values()
                 if n.is_arch_state and n.data.get('enable')]

    ungated_count = 0
    for write_node in isa_writes:
        # Check if this enable references our operation
        enable_expr = write_node.data.get('enable', {})
        if isinstance(enable_expr, dict):
            # Check for both old format (type: 'complete') and new format (binary_op)
            if (enable_expr.get('operation') == operation_id or
                enable_expr.get('left', {}).get('name', '').startswith(operation_id)):

                # Remove the enable condition
                del write_node.data['enable']
                if 'gate_condition' in write_node.data:
                    del write_node.data['gate_condition']

                # Reset timing to None so it gets re-inferred
                write_node.uarch_time = None

                print(f"  Ungated ISA write: {write_node.id}")
                ungated_count += 1

    print(f"  Cleanup complete: ungated {ungated_count} ISA writes")


def set_operation_variable_latency(graph: ResourceGraph, operation_id: str,
                                   enable: bool = True) -> bool:
    """
    Set an operation to have variable (unknown) latency.

    This is used for operations like memory loads/stores with caching, where the
    latency can vary depending on cache hit/miss. The operation will complete at
    some unknown future time.

    Args:
        graph: ResourceGraph to modify
        operation_id: ID of the operation node
        enable: If True, enable variable latency. If False, disable it.

    Returns:
        True if successful, False otherwise
    """

    print(f"\n=== Setting Variable Latency ===")
    print(f"Operation: {operation_id}")
    print(f"Enable variable latency: {enable}")

    # Find the operation
    operation = graph.nodes.get(operation_id)

    if not operation:
        print(f"ERROR: Operation {operation_id} not found in graph")
        return False

    # Check if operation type is valid
    if operation.data.get('type') not in ['operation', 'alu_module', 'fp_operation']:
        print(f"ERROR: Node {operation_id} is not an operation, ALU module, or FP operation")
        return False

    if enable:
        # Enable variable latency
        print(f"\nEnabling variable latency...")

        # Check if already variable latency (no-op)
        if operation.variable_latency:
            print(f"  Operation already has variable latency (no change needed)")
            return True

        # Clean up any existing fixed-latency logic
        if operation.latency > 0:
            print(f"  Cleaning up existing fixed latency logic (latency={operation.latency})...")
            _cleanup_multi_cycle_logic(graph, operation_id)

        # Set variable latency attributes
        operation.variable_latency = True
        operation.latency = 0  # No fixed latency
        operation.data['variable_latency'] = True
        operation.data['multi_cycle'] = True  # Similar semantics to multi-cycle
        operation.data['has_complete_output'] = True  # Has dynamic completion signal
        operation.data['has_cycle_output'] = False  # No specific cycle count

        # Create control signal nodes for start, idle, and complete
        print(f"\nCreating control signal nodes...")
        _create_variable_latency_signals(graph, operation)

        # Gate all ISA state writes on completion
        print(f"\nGating ISA state writes on variable completion...")
        _gate_isa_writes_on_variable_completion(graph, operation)

        # Also gate any existing pipeline registers
        print(f"\nGating existing pipeline registers...")
        _gate_pipeline_registers_on_variable_completion(graph, operation)

        print(f"✓ Variable latency enabled")

    else:
        # Disable variable latency
        print(f"\nDisabling variable latency...")

        # Check if already not variable latency (no-op)
        if not operation.variable_latency:
            print(f"  Operation already has fixed/combinational latency (no change needed)")
            return True

        # Ungate pipeline registers BEFORE removing control signals
        # (we need the complete signal ID to find which registers to ungate)
        _ungate_pipeline_registers_on_variable_removal(graph, operation)

        # Clean up gating logic
        _cleanup_multi_cycle_logic(graph, operation_id)

        # Remove control signal nodes
        _remove_variable_latency_signals(graph, operation)

        # Clear variable latency attributes
        operation.variable_latency = False
        operation.latency = 0
        operation.data['variable_latency'] = False
        operation.data['multi_cycle'] = False
        operation.data['has_complete_output'] = False
        operation.data['has_start_input'] = False
        operation.data['has_idle_output'] = False

        print(f"✓ Variable latency disabled")

    # Re-infer timing
    print(f"\nRe-inferring timing...")
    graph.infer_uarch_time(force_reinfer=True)

    print(f"\n✓ Variable latency configuration complete")
    return True


def set_memory_variable_latency(graph: ResourceGraph, memory_name: str,
                                enable: bool = True,
                                min_latency: int = 2,
                                max_latency: int = 15) -> bool:
    """
    Set a memory to have variable (unknown) latency.

    This is used for memories like dmem where access latency can vary
    (e.g., due to caching, external memory controllers, etc.).

    When enabled, creates:
    - start signal: Input indicating a new memory access has started
    - complete signal: Output indicating the access has completed
    - idle signal: Output indicating memory is ready for new request

    Args:
        graph: ResourceGraph to modify
        memory_name: Name of the memory node (e.g., 'dmem')
        enable: If True, enable variable latency. If False, disable it.
        min_latency: Minimum latency cycles (default 2, must be >= 1)
        max_latency: Maximum latency cycles (default 15)

    Returns:
        True if successful, False otherwise
    """

    print(f"\n=== Setting Memory Variable Latency ===")
    print(f"Memory: {memory_name}")
    print(f"Enable variable latency: {enable}")

    # Find the memory node
    memory = graph.nodes.get(memory_name)

    if not memory:
        print(f"ERROR: Memory {memory_name} not found in graph")
        return False

    # Check if this is a memory node
    is_memory = memory.data.get('is_memory', False) or 'mem' in memory.data.get('type', '')
    if not is_memory:
        print(f"ERROR: Node {memory_name} is not a memory (type={memory.data.get('type')})")
        return False

    if enable:
        # Enable variable latency
        print(f"\nEnabling variable latency for memory...")

        # Check if already variable latency (no-op)
        if memory.variable_latency:
            print(f"  Memory already has variable latency (no change needed)")
            return True

        # Set variable latency attributes
        memory.variable_latency = True
        memory.latency = 0  # No fixed latency
        memory.data['variable_latency'] = True
        memory.data['has_complete_output'] = True
        memory.data['min_latency'] = min_latency
        memory.data['max_latency'] = max_latency
        print(f"  Latency range: {min_latency}-{max_latency} cycles")

        # Create control signal nodes for start, idle, and complete
        print(f"\nCreating control signal nodes for memory...")
        _create_memory_latency_signals(graph, memory)

        print(f"✓ Variable latency enabled for memory {memory_name}")

    else:
        # Disable variable latency
        print(f"\nDisabling variable latency for memory...")

        # Check if already not variable latency (no-op)
        if not memory.variable_latency:
            print(f"  Memory already has fixed/combinational latency (no change needed)")
            return True

        # Remove control signal nodes
        _remove_memory_latency_signals(graph, memory)

        # Clear variable latency attributes
        memory.variable_latency = False
        memory.latency = 0
        memory.data['variable_latency'] = False
        memory.data['has_complete_output'] = False

        print(f"✓ Variable latency disabled for memory {memory_name}")

    print(f"\n✓ Memory variable latency configuration complete")
    return True


def _create_memory_latency_signals(graph: ResourceGraph, memory: Node):
    """
    Create control signal nodes for a variable-latency memory.

    Creates three signal nodes:
    - start: Input signal indicating a new memory access has begun
    - idle: Output signal indicating memory is ready for new request
    - complete: Output signal indicating memory access has finished

    Args:
        graph: ResourceGraph
        memory: Memory node with variable latency
    """

    # Create start signal node (input to memory - indicates new access)
    start_node = Node(
        node_id=f"{memory.id}_start",
        data={
            'type': 'control_signal',
            'signal_type': 'start',
            'memory': memory.id,
            'direction': 'input',
            'description': f"Start signal for {memory.id} (new access begun)",
            'bit_width': 1
        }
    )
    graph.add_node(start_node)

    # Create edge from start signal to memory
    start_edge = Edge(
        source=start_node,
        target=memory,
        data={
            'type': 'control',
            'signal_type': 'start',
            'description': f"Start signal for {memory.id}"
        }
    )
    graph.add_edge(start_edge)

    # Create idle signal node (output from memory)
    idle_node = Node(
        node_id=f"{memory.id}_idle",
        data={
            'type': 'control_signal',
            'signal_type': 'idle',
            'memory': memory.id,
            'direction': 'output',
            'description': f"Idle signal for {memory.id} (ready for new request)",
            'bit_width': 1
        }
    )
    graph.add_node(idle_node)

    # Create edge from memory to idle signal
    idle_edge = Edge(
        source=memory,
        target=idle_node,
        data={
            'type': 'control',
            'signal_type': 'idle',
            'description': f"Idle signal from {memory.id}"
        }
    )
    graph.add_edge(idle_edge)

    # Create complete signal node (output from memory)
    complete_node = Node(
        node_id=f"{memory.id}_complete",
        data={
            'type': 'control_signal',
            'signal_type': 'complete',
            'memory': memory.id,
            'direction': 'output',
            'description': f"Completion signal for {memory.id}",
            'bit_width': 1
        }
    )
    graph.add_node(complete_node)

    # Create edge from memory to complete signal
    complete_edge = Edge(
        source=memory,
        target=complete_node,
        data={
            'type': 'control',
            'signal_type': 'complete',
            'description': f"Completion signal from {memory.id}"
        }
    )
    graph.add_edge(complete_edge)

    # Update memory metadata to track these signals
    memory.data['start_signal'] = start_node.id
    memory.data['idle_signal'] = idle_node.id
    memory.data['complete_signal'] = complete_node.id
    memory.data['has_start_input'] = True
    memory.data['has_idle_output'] = True

    print(f"  Created control signals for memory:")
    print(f"    • {start_node.id} (input)")
    print(f"    • {idle_node.id} (output)")
    print(f"    • {complete_node.id} (output)")


def _remove_memory_latency_signals(graph: ResourceGraph, memory: Node):
    """
    Remove control signal nodes for a variable-latency memory.

    Args:
        graph: ResourceGraph
        memory: Memory node
    """

    # Get signal node IDs from memory metadata
    signal_ids = [
        memory.data.get('start_signal'),
        memory.data.get('idle_signal'),
        memory.data.get('complete_signal')
    ]

    for signal_id in signal_ids:
        if signal_id and signal_id in graph.nodes:
            signal_node = graph.nodes[signal_id]

            # Remove all edges connected to this signal
            edges_to_remove = list(signal_node.incoming_edges) + list(signal_node.outgoing_edges)
            for edge in edges_to_remove:
                graph.remove_edge(edge)

            # Remove the signal node
            graph.remove_node(signal_node)
            print(f"  Removed signal node: {signal_id}")

    # Clear metadata
    memory.data.pop('start_signal', None)
    memory.data.pop('idle_signal', None)
    memory.data.pop('complete_signal', None)
    memory.data.pop('has_start_input', None)
    memory.data.pop('has_idle_output', None)


def wire_memory_start_signal(graph: ResourceGraph, memory_name: str) -> bool:
    """
    Wire the start signal for a variable latency memory using graph structure.

    The start signal should be: idle && memory_access_enable
    where memory_access_enable indicates ANY memory operation (load OR store).

    This function finds memory accesses by using ArrayAccessAnalyzer to identify
    all reads and writes to the memory, then finds the enable signals that gate
    those accesses.

    Args:
        graph: ResourceGraph with the memory
        memory_name: Name of the variable latency memory

    Returns:
        True if successfully wired, False otherwise
    """
    memory = graph.nodes.get(memory_name)
    if not memory:
        print(f"ERROR: Memory {memory_name} not found")
        return False

    if not memory.variable_latency:
        print(f"ERROR: Memory {memory_name} is not variable latency")
        return False

    # Get signal nodes
    start_signal_id = memory.data.get('start_signal')
    idle_signal_id = memory.data.get('idle_signal')

    if not start_signal_id or not idle_signal_id:
        print(f"ERROR: Memory {memory_name} missing start or idle signal")
        return False

    start_signal = graph.nodes.get(start_signal_id)
    idle_signal = graph.nodes.get(idle_signal_id)

    if not start_signal or not idle_signal:
        print(f"ERROR: Could not find start or idle signal nodes")
        return False

    # Use ArrayAccessAnalyzer to find all reads and writes to this memory
    analyzer = ArrayAccessAnalyzer(graph)
    read_accesses, write_accesses = analyzer.get_reads_and_writes(memory_name)

    print(f"  Found {len(read_accesses)} read accesses, {len(write_accesses)} write accesses")

    # Find write enable (stores) - look for validity-gated version first
    write_enable_node = None
    for node in graph.nodes.values():
        if (f'{memory_name}_write_enable' in node.id and
            'valid_gated' in node.id):
            write_enable_node = node
            break

    if not write_enable_node:
        for node in graph.nodes.values():
            if node.id == f'{memory_name}_write_enable':
                write_enable_node = node
                break

    # For reads, find the read_enable signals from the graph structure
    # The graph_merger stores 'read_enable' on the read node's data dict
    read_enable_nodes = []

    for read_access in read_accesses:
        read_node = read_access.node
        print(f"  Checking read node: {read_node.id}")
        print(f"    Node data keys: {list(read_node.data.keys())}")

        # First check: read_enable stored on the node itself by graph_merger
        read_enable_id = read_node.data.get('read_enable')
        if read_enable_id and read_enable_id in graph.nodes:
            read_enable_nodes.append(graph.nodes[read_enable_id])
            print(f"    Found read_enable from node data: {read_enable_id}")
            continue

        # Second check: explicit rd_enable pattern
        rd_enable_id = f"{memory_name}_{read_access.index}_rd_enable"
        if rd_enable_id in graph.nodes:
            read_enable_nodes.append(graph.nodes[rd_enable_id])
            print(f"    Found read_enable pattern: {rd_enable_id}")
            continue

        # Third check: look for instruction enables connected to this read
        # These are enable signals that control when the read is active
        for edge in read_node.incoming_edges:
            source = edge.source
            # Look for instruction enables that gate this read
            if ('enable' in source.id.lower() and
                source.data.get('bit_width', 32) == 1 and
                source not in read_enable_nodes):
                read_enable_nodes.append(source)
                print(f"    Found enable from incoming edge: {source.id}")

    if write_enable_node:
        print(f"  Found write enable: {write_enable_node.id}")
    if read_enable_nodes:
        print(f"  Found {len(read_enable_nodes)} read enable signals")
        for node in read_enable_nodes[:5]:  # Print first 5
            print(f"    - {node.id}")

    if not write_enable_node and not read_enable_nodes:
        print(f"  Warning: Could not find any memory access enables for {memory_name}")
        return False

    # Gate read enables with Memory stage validity (like write enables are)
    # This ensures invalid instructions don't trigger memory stalls
    memory_valid_node = None
    for node in graph.nodes.values():
        if 'PIPE_Memory_valid_PIPE' in node.id or node.id == 'PIPE_Memory_valid_PIPE':
            memory_valid_node = node
            break

    gated_read_enable_nodes = []
    if memory_valid_node and read_enable_nodes:
        for read_enable in read_enable_nodes:
            # Create gated version: read_enable && Memory_valid
            gated_id = f"{read_enable.id}_valid_gated"
            if gated_id not in graph.nodes:
                gated_node = Node(
                    node_id=gated_id,
                    data={
                        'type': 'logical_and',
                        'description': f'Memory read enable gated with validity',
                        'pipeline_component': True,
                        'bit_width': 1
                    }
                )
                # Copy pipe_time from source node so memory latency stall logic can find Memory stage
                if hasattr(read_enable, 'pipe_time'):
                    gated_node.pipe_time = read_enable.pipe_time
                if hasattr(read_enable, 'uarch_time'):
                    gated_node.uarch_time = read_enable.uarch_time
                graph.add_node(gated_node)
                graph.add_edge(Edge(read_enable, gated_node, data={'type': 'logic_input', 'operand_position': 0}))
                graph.add_edge(Edge(memory_valid_node, gated_node, data={'type': 'logic_input', 'operand_position': 1}))
                print(f"  Gated read enable {read_enable.id} with Memory validity")
                gated_read_enable_nodes.append(gated_node)
            else:
                gated_read_enable_nodes.append(graph.nodes[gated_id])
    else:
        gated_read_enable_nodes = read_enable_nodes

    # Create memory_access_enable = write_enable || read_enables
    # ALWAYS create the OR gate node so that cache refill and write-through
    # connections can add their signals to it later via connect_cache_refill_to_memory
    # and connect_rwcache_write_through.
    all_enables = []

    # Check if there's a data cache (RW cache) on this memory
    # If so, skip adding write_enable because stores go through the cache's
    # write-through path which adds dcache_write_through_req to access_enable
    has_rw_cache = any(
        node.data.get('type') == 'read_write_cache' and
        node.data.get('memory_name') == memory_name
        for node in graph.nodes.values()
    )

    if write_enable_node and not has_rw_cache:
        all_enables.append(write_enable_node)
    elif write_enable_node and has_rw_cache:
        print(f"  Skipping {write_enable_node.id} (stores go through RW cache write-through)")

    # When there's a data cache (RW cache), skip adding read enables to
    # umem_access_enable. Data reads go through the dcache (which issues
    # refill_req when needed), and instruction fetch is a combinational read
    # that doesn't need the FSM. The FSM's umem_complete drives
    # dcache_refill_valid, so it must only fire for actual cache operations.
    if not has_rw_cache:
        all_enables.extend(gated_read_enable_nodes)
    else:
        print(f"  Skipping read enables (reads go through RW cache or are combinational)")

    # Always create OR gate for memory access enables (even with 0 or 1 inputs)
    # This allows cache connections to add more inputs later
    or_gate_id = f"{memory_name}_access_enable"
    or_gate = Node(
        node_id=or_gate_id,
        data={
            'type': 'logical_or',
            'description': f'Memory access enable for {memory_name}: any read or write',
            'pipeline_component': True,
            'bit_width': 1
        }
    )
    # Copy pipe_time from input nodes so stall logic knows this is Memory stage
    for enable_node in all_enables:
        if hasattr(enable_node, 'pipe_time') and enable_node.pipe_time is not None:
            or_gate.pipe_time = enable_node.pipe_time
            break
        if hasattr(enable_node, 'uarch_time') and enable_node.uarch_time is not None:
            or_gate.uarch_time = enable_node.uarch_time
            break
    graph.add_node(or_gate)

    for i, enable_node in enumerate(all_enables):
        graph.add_edge(Edge(enable_node, or_gate, data={
            'type': 'logic_input', 'operand_position': i
        }))

    access_enable_node = or_gate
    print(f"  Created {or_gate_id} OR with {len(all_enables)} initial input(s)")

    # For instruction memory (imem), we always fetch when idle - no access enable needed
    # This is because instruction fetch happens every cycle, unlike dmem which is conditional
    is_instruction_memory = memory_name == 'imem'

    if is_instruction_memory:
        # For imem: start = idle (always fetch when ready)
        # Connect idle -> start signal directly
        graph.add_edge(Edge(idle_signal, start_signal, data={
            'type': 'operand',
            'description': f'Start condition for {memory_name}: always fetch when idle'
        }))
        print(f"  Wired {start_signal_id} = {idle_signal_id} (instruction memory always fetches)")
    else:
        # For data memory (dmem): start = idle && access_enable
        and_gate_id = f"{memory_name}_start_condition"
        and_gate = Node(
            node_id=and_gate_id,
            data={
                'type': 'logical_and',
                'description': f'Start condition for {memory_name}: idle && access_enable',
                'pipeline_component': True,
                'bit_width': 1
            }
        )
        graph.add_node(and_gate)

        # Connect idle -> AND gate
        graph.add_edge(Edge(idle_signal, and_gate, data={
            'type': 'logic_input', 'operand_position': 0
        }))

        # Connect access_enable -> AND gate
        graph.add_edge(Edge(access_enable_node, and_gate, data={
            'type': 'logic_input', 'operand_position': 1
        }))

        # Connect AND gate -> start signal
        graph.add_edge(Edge(and_gate, start_signal, data={
            'type': 'operand',
            'description': f'Start condition for {memory_name}'
        }))

        print(f"  Wired {start_signal_id} = {idle_signal_id} && {access_enable_node.id}")

    # Store access_enable node for use by stall logic
    memory.data['access_enable_signal'] = access_enable_node.id

    return True


def wire_memory_complete_to_stall(graph: ResourceGraph, memory_name: str,
                                   stall_controller_id: str = None) -> bool:
    """
    DEPRECATED: Use HazardResolver.add_memory_latency_stalls() instead.

    This function is kept for backward compatibility but stall logic should
    be handled by the HazardResolver which has the proper infrastructure for
    stage detection, bubble injection, and register gating.

    Args:
        graph: ResourceGraph with the memory
        memory_name: Name of the variable latency memory
        stall_controller_id: Unused (for compatibility)

    Returns:
        True (no-op for backward compatibility)
    """
    print(f"  Note: wire_memory_complete_to_stall is deprecated.")
    print(f"  Use HazardResolver.add_memory_latency_stalls('{memory_name}') instead.")
    return True


def _create_variable_latency_signals(graph: ResourceGraph, operation: Node):
    """
    Create control signal nodes for a variable-latency operation.

    Creates three signal nodes:
    - start: Input signal to begin the operation
    - idle: Output signal indicating operation is ready for new request
    - complete: Output signal indicating operation has finished

    Args:
        graph: ResourceGraph
        operation: Operation node with variable latency
    """

    # Create start signal node (input to operation)
    start_node = Node(
        node_id=f"{operation.id}_start",
        data={
            'type': 'control_signal',
            'signal_type': 'start',
            'operation': operation.id,
            'direction': 'input',
            'description': f"Start signal for {operation.id}",
            'bit_width': 1
        }
    )
    graph.add_node(start_node)

    # Create edge from start signal to operation
    start_edge = Edge(
        source=start_node,
        target=operation,
        data={
            'type': 'control',
            'signal_type': 'start',
            'description': f"Start signal for {operation.id}"
        }
    )
    graph.add_edge(start_edge)

    # Create idle signal node (output from operation)
    idle_node = Node(
        node_id=f"{operation.id}_idle",
        data={
            'type': 'control_signal',
            'signal_type': 'idle',
            'operation': operation.id,
            'direction': 'output',
            'description': f"Idle signal for {operation.id} (ready for new request)",
            'bit_width': 1
        }
    )
    graph.add_node(idle_node)

    # Create edge from operation to idle signal
    idle_edge = Edge(
        source=operation,
        target=idle_node,
        data={
            'type': 'control',
            'signal_type': 'idle',
            'description': f"Idle signal from {operation.id}"
        }
    )
    graph.add_edge(idle_edge)

    # Create complete signal node (output from operation)
    complete_node = Node(
        node_id=f"{operation.id}_complete",
        data={
            'type': 'control_signal',
            'signal_type': 'complete',
            'operation': operation.id,
            'direction': 'output',
            'description': f"Completion signal for {operation.id}",
            'bit_width': 1
        }
    )
    graph.add_node(complete_node)

    # Create edge from operation to complete signal
    complete_edge = Edge(
        source=operation,
        target=complete_node,
        data={
            'type': 'control',
            'signal_type': 'complete',
            'description': f"Completion signal from {operation.id}"
        }
    )
    graph.add_edge(complete_edge)

    # Update operation metadata to track these signals
    operation.data['start_signal'] = start_node.id
    operation.data['idle_signal'] = idle_node.id
    operation.data['complete_signal'] = complete_node.id
    operation.data['has_start_input'] = True
    operation.data['has_idle_output'] = True

    print(f"  Created control signals:")
    print(f"    • {start_node.id} (input)")
    print(f"    • {idle_node.id} (output)")
    print(f"    • {complete_node.id} (output)")


def _remove_variable_latency_signals(graph: ResourceGraph, operation: Node):
    """
    Remove control signal nodes for a variable-latency operation.

    Args:
        graph: ResourceGraph
        operation: Operation node
    """

    # Get signal node IDs from operation metadata
    signal_ids = [
        operation.data.get('start_signal'),
        operation.data.get('idle_signal'),
        operation.data.get('complete_signal')
    ]

    removed_count = 0

    # Remove signal nodes and their edges
    for signal_id in signal_ids:
        if signal_id and signal_id in graph.nodes:
            signal_node = graph.nodes[signal_id]

            # Remove all edges connected to this signal node
            edges_to_remove = list(signal_node.incoming_edges) + list(signal_node.outgoing_edges)
            for edge in edges_to_remove:
                edge.remove_from_nodes()
                if edge.id in graph.edges:
                    del graph.edges[edge.id]

            # Remove the signal node itself
            del graph.nodes[signal_id]
            removed_count += 1

            print(f"  Removed signal node: {signal_id}")

    # Clear metadata
    operation.data.pop('start_signal', None)
    operation.data.pop('idle_signal', None)
    operation.data.pop('complete_signal', None)

    if removed_count > 0:
        print(f"  Removed {removed_count} control signal nodes")


def _gate_isa_writes_on_variable_completion(graph: ResourceGraph, operation: Node):
    """
    Gate all ISA state writes to occur only when a variable-latency operation completes.

    Similar to fixed multi-cycle gating, but uses a variable completion signal
    instead of a specific cycle number. Creates enable edges from the complete
    signal node to all ISA writes.

    Args:
        graph: ResourceGraph
        operation: Operation node with variable latency
    """

    # Get the complete signal node
    complete_signal_id = operation.data.get('complete_signal')
    if not complete_signal_id or complete_signal_id not in graph.nodes:
        print(f"  WARNING: No complete signal found for {operation.id}")
        return

    complete_signal = graph.nodes[complete_signal_id]

    # Find ALL ISA state writes in the graph
    isa_writes = [n for n in graph.nodes.values()
                 if n.is_arch_state and
                 any(e.data.get('type') == 'assignment' for e in n.incoming_edges)]

    # Create enable expression for variable completion
    enable_expr = {
        'type': 'variable_complete',
        'operation': operation.id,
        'complete_signal': complete_signal_id,
        'description': f"{operation.id} completion (variable latency)"
    }

    gated_count = 0

    # Gate the ISA writes
    for write_node in isa_writes:
        # Set the enable condition
        write_node.data['enable'] = enable_expr

        # Create visible enable edge from complete signal to ISA write
        edge = Edge(
            source=complete_signal,
            target=write_node,
            data={
                'type': 'enable',
                'signal_type': 'variable_complete',
                'description': f"{operation.id} completion gates {write_node.id}"
            }
        )
        graph.add_edge(edge)

        print(f"  Gated ISA write: {write_node.id}")
        gated_count += 1

    print(f"  Gated {gated_count} ISA writes on variable completion")


def _ungate_pipeline_registers_on_variable_removal(graph: ResourceGraph, operation: Node):
    """
    Ungate pipeline registers when disabling variable latency.

    This function is called when disabling variable latency on an operation.
    It removes the gating from any pipeline registers that were gated by this
    operation's complete signal.

    Args:
        graph: ResourceGraph
        operation: Operation node with variable latency being disabled
    """

    # Get the complete signal node (if it still exists)
    complete_signal_id = operation.data.get('complete_signal')
    if not complete_signal_id or complete_signal_id not in graph.nodes:
        print(f"  No complete signal to clean up")
        return

    complete_signal = graph.nodes[complete_signal_id]

    # Find all pipeline registers that were gated by this operation
    gated_registers = []
    for node in graph.nodes.values():
        if (node.data.get('type') == 'pipeline_register' and
            node.data.get('gated_by_operation') == operation.id):
            gated_registers.append(node)

    if not gated_registers:
        print(f"  No pipeline registers to ungate")
        return

    ungated_count = 0

    # Ungate each register
    for pipe_reg in gated_registers:
        # Find and remove enable edges from complete signal to this register
        edges_to_remove = []
        if hasattr(complete_signal, 'outgoing_edges'):
            for edge in complete_signal.outgoing_edges:
                if (edge.target == pipe_reg and
                    edge.data.get('type') == 'pipeline_control' and
                    edge.data.get('control_type') == 'enable'):
                    edges_to_remove.append(edge)

        # Remove the edges
        for edge in edges_to_remove:
            graph.remove_edge(edge)

        # Clear gating metadata
        if 'variable_latency_gated' in pipe_reg.data:
            del pipe_reg.data['variable_latency_gated']
        if 'gated_by_operation' in pipe_reg.data:
            del pipe_reg.data['gated_by_operation']
        if 'gated_by_signal' in pipe_reg.data:
            del pipe_reg.data['gated_by_signal']

        print(f"  Ungated pipeline register: {pipe_reg.id}")
        ungated_count += 1

    print(f"  Ungated {ungated_count} pipeline register(s)")


def _gate_pipeline_registers_on_variable_completion(graph: ResourceGraph, operation: Node):
    """
    Gate existing pipeline registers that depend on a variable-latency operation.

    This function is called when setting an operation to variable latency AFTER
    pipelining has already been applied. It retroactively gates any pipeline
    registers that are in the data flow path from the variable latency operation.

    Args:
        graph: ResourceGraph
        operation: Operation node with variable latency
    """

    # Get the complete signal node
    complete_signal_id = operation.data.get('complete_signal')
    if not complete_signal_id or complete_signal_id not in graph.nodes:
        print(f"  WARNING: No complete signal found for {operation.id}")
        return

    complete_signal = graph.nodes[complete_signal_id]

    # Find all pipeline registers that are downstream from this operation
    # We need to traverse the graph to find pipeline registers that depend on this operation
    pipeline_registers = []
    visited = set()
    to_visit = [operation]

    while to_visit:
        current = to_visit.pop(0)
        if current.id in visited:
            continue
        visited.add(current.id)

        # Check all outgoing edges
        if hasattr(current, 'outgoing_edges'):
            for edge in current.outgoing_edges:
                target = edge.target

                # If target is a pipeline register and it's not already gated
                if (target.data.get('type') == 'pipeline_register' and
                    not target.data.get('variable_latency_gated')):
                    pipeline_registers.append(target)

                # Continue traversal for non-control signals
                if edge.data.get('type') != 'control_signal':
                    to_visit.append(target)

    gated_count = 0

    # Gate each pipeline register
    for pipe_reg in pipeline_registers:
        # Check if it's not already gated by this operation
        if pipe_reg.data.get('gated_by_operation') == operation.id:
            continue

        # Add enable edge from complete signal to pipeline register
        enable_edge = Edge(
            source=complete_signal,
            target=pipe_reg,
            data={
                'type': 'pipeline_control',
                'control_type': 'enable',
                'signal_type': 'variable_complete',
                'description': f'Variable latency completion gates {pipe_reg.id}'
            }
        )
        graph.add_edge(enable_edge)

        # Mark the register as gated
        pipe_reg.data['variable_latency_gated'] = True
        pipe_reg.data['gated_by_operation'] = operation.id
        pipe_reg.data['gated_by_signal'] = complete_signal_id

        print(f"  Gated pipeline register: {pipe_reg.id}")
        gated_count += 1

    if gated_count > 0:
        print(f"  Retroactively gated {gated_count} existing pipeline register(s)")
    else:
        print(f"  No existing pipeline registers to gate")


def create_example_latency_specs() -> List[OperationLatencySpec]:
    """Create example latency specifications for common operations."""

    return [
        OperationLatencySpec("multiply_op", 3, "multiply"),    # 3-cycle multiply
        OperationLatencySpec("divide_op", 8, "divide"),       # 8-cycle divide
        OperationLatencySpec("memory_load", 2, "memory"),     # 2-cycle memory load
        OperationLatencySpec("floating_add", 4, "float"),     # 4-cycle floating point add
    ]


def add_simple_memory_stalls(graph: ResourceGraph, memory_name: str) -> bool:
    """
    Add simple stall logic for memory latency in non-pipelined designs.

    For single-cycle designs (like the MMU), this creates:
    1. A stall signal: mem_stall = mem_access_enable && !mem_complete
    2. Gates the PC write so PC only updates when !stall

    Args:
        graph: ResourceGraph with memory and PC
        memory_name: Name of the memory (e.g., 'dmem')

    Returns:
        True if stall logic was added successfully
    """
    print(f"\nAdding simple memory stall logic for {memory_name}...")

    # Find memory node
    mem_node = graph.nodes.get(memory_name)
    if not mem_node:
        print(f"  ERROR: Memory {memory_name} not found")
        return False

    # Check for variable latency
    if not mem_node.data.get('variable_latency'):
        print(f"  Memory {memory_name} doesn't have variable latency, skipping")
        return True

    # Get complete and access_enable signals
    complete_signal_id = mem_node.data.get('complete_signal')
    access_enable_id = mem_node.data.get('access_enable_signal')

    if not complete_signal_id:
        print(f"  ERROR: Memory {memory_name} missing complete_signal")
        return False

    complete_signal = graph.nodes.get(complete_signal_id)
    if not complete_signal:
        print(f"  ERROR: Complete signal {complete_signal_id} not found")
        return False

    # Create NOT complete signal
    not_complete_id = f"{memory_name}_not_complete"
    if not_complete_id not in graph.nodes:
        not_complete = Node(
            node_id=not_complete_id,
            data={
                'type': 'operation',
                'operator': '!',
                'name': not_complete_id,
                'description': f'NOT {memory_name}_complete',
                'bit_width': 1
            }
        )
        graph.add_node(not_complete)
        graph.add_edge(Edge(complete_signal, not_complete, data={
            'type': 'operand',
            'operand_position': 0
        }))
        print(f"  Created {not_complete_id}")
    else:
        not_complete = graph.nodes[not_complete_id]

    # Create stall signal: !complete && access_enable (if access_enable exists)
    # OR just !complete && !idle (memory is busy)
    idle_signal_id = f"{memory_name}_idle"
    idle_signal = graph.nodes.get(idle_signal_id)

    if idle_signal:
        # Create NOT idle
        not_idle_id = f"{memory_name}_not_idle"
        if not_idle_id not in graph.nodes:
            not_idle = Node(
                node_id=not_idle_id,
                data={
                    'type': 'operation',
                    'operator': '!',
                    'name': not_idle_id,
                    'description': f'NOT {memory_name}_idle',
                    'bit_width': 1
                }
            )
            graph.add_node(not_idle)
            graph.add_edge(Edge(idle_signal, not_idle, data={
                'type': 'operand',
                'operand_position': 0
            }))
        else:
            not_idle = graph.nodes[not_idle_id]

        # Stall = !idle && !complete (memory is busy and not done)
        stall_id = f"{memory_name}_stall"
        if stall_id not in graph.nodes:
            stall_signal = Node(
                node_id=stall_id,
                data={
                    'type': 'operation',
                    'operator': '&&',
                    'name': stall_id,
                    'description': f'{memory_name} stall: busy and not complete',
                    'bit_width': 1
                }
            )
            graph.add_node(stall_signal)
            graph.add_edge(Edge(not_idle, stall_signal, data={'type': 'operand', 'operand_index': 0}))
            graph.add_edge(Edge(not_complete, stall_signal, data={'type': 'operand', 'operand_index': 1}))
            print(f"  Created {stall_id} = !idle && !complete")
        else:
            stall_signal = graph.nodes[stall_id]
    else:
        # Fall back to just not_complete as stall
        stall_signal = not_complete
        print(f"  Using {not_complete_id} as stall signal (no idle signal)")

    # Find PC node and gate its write
    pc_node = None
    for name in ['pc', 'pc_rd', 'ip', 'ip_rd']:
        if name in graph.nodes:
            pc_node = graph.nodes[name]
            break

    if not pc_node:
        print(f"  WARNING: No PC node found, cannot add stall gating")
        return False

    # Add stall signal as write gate for PC
    # The verilog generator should pick this up and gate PC updates
    if 'write_stall_signals' not in pc_node.data:
        pc_node.data['write_stall_signals'] = []
    if stall_signal.id not in pc_node.data['write_stall_signals']:
        pc_node.data['write_stall_signals'].append(stall_signal.id)
        print(f"  Added {stall_signal.id} as write stall for {pc_node.id}")

    # Also mark any architectural state that should be stalled
    # Look for nodes with is_arch_state=True
    arch_state_count = 0
    for node in graph.nodes.values():
        if node.is_arch_state and node.id != pc_node.id:
            if 'write_stall_signals' not in node.data:
                node.data['write_stall_signals'] = []
            if stall_signal.id not in node.data['write_stall_signals']:
                node.data['write_stall_signals'].append(stall_signal.id)
                arch_state_count += 1

    print(f"  Added stall gating to {arch_state_count} additional architectural state nodes")
    return True


def add_memory_access_arbiter(graph: ResourceGraph, memory_name: str,
                                cache_names: List[str] = None) -> bool:
    """
    Add arbitration logic for memory access when multiple caches share a memory.

    When multiple caches (e.g., icache and dcache) share a single backing memory,
    we need to track which source was granted access and only signal completion
    to that source. This prevents multiple caches from seeing completion
    simultaneously when only one was actually served.

    The arbiter:
    1. Detects which request sources are connected to the memory's access_enable
    2. Creates grant signals based on priority (writes > dcache > icache)
    3. Registers which source was granted when memory_start occurs
    4. Rewires completion signals to be gated with the registered grant

    Args:
        graph: ResourceGraph with memory and caches
        memory_name: Name of the shared memory (e.g., 'umem')
        cache_names: Optional list of cache names to arbitrate (auto-detected if None)

    Returns:
        True if successfully added, False otherwise
    """
    print(f"\n=== Adding memory access arbiter for {memory_name} ===")

    memory = graph.nodes.get(memory_name)
    if not memory:
        print(f"  ERROR: Memory {memory_name} not found")
        return False

    # Get memory control signals
    complete_signal_id = memory.data.get('complete_signal')
    start_signal_id = memory.data.get('start_signal')
    idle_signal_id = memory.data.get('idle_signal')

    if not complete_signal_id:
        print(f"  ERROR: Memory {memory_name} missing complete signal")
        return False

    complete_signal = graph.nodes.get(complete_signal_id)
    start_signal = graph.nodes.get(start_signal_id) if start_signal_id else None
    idle_signal = graph.nodes.get(idle_signal_id) if idle_signal_id else None

    if not complete_signal:
        print(f"  ERROR: Complete signal {complete_signal_id} not found")
        return False

    # Find the access_enable node to discover connected request sources
    access_enable_id = f"{memory_name}_access_enable"
    access_enable = graph.nodes.get(access_enable_id)
    if not access_enable:
        print(f"  WARNING: {access_enable_id} not found - no arbitration needed")
        return True

    # Discover request sources from the access_enable OR gate inputs
    request_sources = []
    for edge in access_enable.incoming_edges:
        if edge.data.get('type') == 'logic_input':
            source = edge.source
            # Look for cache refill and write-through request signals
            if '_refill_req' in source.id or '_write_through_req' in source.id:
                request_sources.append(source)
                print(f"  Found request source: {source.id}")

    if len(request_sources) <= 1:
        print(f"  Only {len(request_sources)} cache request source(s) - no arbitration needed")
        return True

    print(f"  Found {len(request_sources)} request sources requiring arbitration")

    # Define priority order (higher index = higher priority)
    # Priority: dcache_write_through > dcache_refill > icache_refill
    def get_priority(source_id: str) -> int:
        if 'write_through' in source_id:
            return 3  # Highest priority - complete writes ASAP
        elif 'dcache' in source_id and 'refill' in source_id:
            return 2  # Data cache refill
        elif 'icache' in source_id or 'refill' in source_id:
            return 1  # Instruction cache refill
        return 0  # Unknown

    # Sort by priority (ascending - we'll process in this order)
    request_sources.sort(key=lambda s: get_priority(s.id))
    print(f"  Priority order (low to high): {[s.id for s in request_sources]}")

    # Create grant signals for each source
    # Grant[i] = req[i] && !req[i+1] && !req[i+2] && ... (higher priority blocks lower)
    grant_signals = []

    for i, source in enumerate(request_sources):
        source_name = source.id.replace('_req', '')
        grant_id = f"{source_name}_grant"

        # Higher priority sources block this one
        higher_priority = request_sources[i + 1:]

        if not higher_priority:
            # Highest priority - grant when requesting
            grant_node = Node(
                node_id=grant_id,
                data={
                    'type': 'var',
                    'name': grant_id,
                    'bit_width': 1,
                    'description': f'Grant for {source.id} (highest priority)',
                    'is_grant_signal': True,
                    'source_req': source.id,
                }
            )
            graph.add_node(grant_node)
            # grant = req
            graph.add_edge(Edge(source, grant_node, data={'type': 'assignment'}))
        else:
            # Create negated higher priority signals and AND them together
            # grant = req && !higher1 && !higher2 ...
            not_higher_nodes = []

            for hp_source in higher_priority:
                not_hp_id = f"not_{hp_source.id}"
                if not_hp_id not in graph.nodes:
                    not_hp = Node(
                        node_id=not_hp_id,
                        data={
                            'type': 'operation',
                            'operator': '!',
                            'name': not_hp_id,
                            'bit_width': 1
                        }
                    )
                    graph.add_node(not_hp)
                    graph.add_edge(Edge(hp_source, not_hp, data={
                        'type': 'operand', 'operand_position': 0
                    }))
                else:
                    not_hp = graph.nodes[not_hp_id]
                not_higher_nodes.append(not_hp)

            # Create AND gate: req && !higher1 && !higher2 ...
            grant_node = Node(
                node_id=grant_id,
                data={
                    'type': 'logical_and',
                    'name': grant_id,
                    'bit_width': 1,
                    'description': f'Grant for {source.id}',
                    'is_grant_signal': True,
                    'source_req': source.id,
                }
            )
            graph.add_node(grant_node)

            # Connect all inputs to the AND gate
            all_inputs = [source] + not_higher_nodes
            for j, inp in enumerate(all_inputs):
                graph.add_edge(Edge(inp, grant_node, data={
                    'type': 'logic_input', 'operand_position': j
                }))

        grant_signals.append(grant_node)
        print(f"  Created {grant_id}")

    # Create registered grant signals that latch when memory starts
    # These persist during the memory operation to track who was served
    registered_grants = []

    for grant in grant_signals:
        reg_grant_id = f"{grant.id}_reg"
        reg_grant = Node(
            node_id=reg_grant_id,
            data={
                'type': 'register',
                'name': reg_grant_id,
                'bit_width': 1,
                'description': f'Registered grant for {grant.id}',
                'is_registered_grant': True,
                'grant_signal': grant.id,
                'latch_condition': start_signal_id if start_signal else None,
                'clear_condition': complete_signal_id,
            }
        )
        graph.add_node(reg_grant)
        # The register takes the grant value and latches it
        graph.add_edge(Edge(grant, reg_grant, data={
            'type': 'register_input',
            'latch_on': start_signal_id,
            'clear_on': complete_signal_id,
        }))
        if start_signal:
            graph.add_edge(Edge(start_signal, reg_grant, data={
                'type': 'latch_enable'
            }))
        registered_grants.append(reg_grant)
        print(f"  Created registered grant: {reg_grant_id}")

    # Rewire completion signals to be gated with registered grants
    # For each cache completion signal (refill_valid, write_through_complete),
    # change it from "= memory_complete" to "= memory_complete && grant_reg"

    for grant, reg_grant in zip(grant_signals, registered_grants):
        source_req_id = grant.data.get('source_req')
        if not source_req_id:
            continue

        # Determine which completion signal this grant controls
        if 'write_through' in source_req_id:
            # dcache_write_through_req -> dcache_write_through_complete
            completion_id = source_req_id.replace('_req', '_complete')
        else:
            # icache_refill_req -> icache_refill_valid
            # dcache_refill_req -> dcache_refill_valid
            completion_id = source_req_id.replace('_req', '_valid')

        completion_node = graph.nodes.get(completion_id)
        if not completion_node:
            print(f"  WARNING: Completion signal {completion_id} not found")
            continue

        # Find the current edge from memory_complete to completion signal
        old_edge = None
        for edge in completion_node.incoming_edges:
            if edge.source.id == complete_signal_id and edge.data.get('type') == 'assignment':
                old_edge = edge
                break

        if old_edge:
            # Remove old direct connection
            graph.remove_edge(old_edge)
            print(f"  Removed direct {complete_signal_id} -> {completion_id}")

        # Create gated completion: completion_source && grant_reg
        # Use direct resp_ready signals instead of global umem_complete
        # This is because umem_complete depends on ALL stalls, which can oscillate
        # and prevent completion from being seen. Each port should use its own resp_ready.
        if 'write_through' in source_req_id:
            # For writes, use the external write response ready signal
            resp_ready_id = f"{memory_name}_write_resp_ready"
            resp_ready = graph.nodes.get(resp_ready_id)
            if not resp_ready:
                # Create the node for the external write response input
                resp_ready = Node(
                    node_id=resp_ready_id,
                    data={
                        'type': 'external_input',
                        'name': resp_ready_id,
                        'bit_width': 1,
                        'description': 'External memory write response ready',
                        'is_external_port': True,
                    }
                )
                graph.add_node(resp_ready)
                print(f"  Created external input node: {resp_ready_id}")
            completion_source = resp_ready
            completion_source_id = resp_ready_id
        elif 'refill' in source_req_id:
            # For cache refills, determine which port's resp_ready to use
            # Pattern: dcache_refill_req or icache_refill_req
            # Corresponding port: umem_dcache_refill_addr or umem_icache_refill_addr
            cache_prefix = source_req_id.replace('_refill_req', '')  # dcache or icache
            resp_ready_id = f"{memory_name}_{cache_prefix}_refill_addr_read_resp_ready"
            resp_ready = graph.nodes.get(resp_ready_id)
            if not resp_ready:
                # Create the node for the external read response input
                resp_ready = Node(
                    node_id=resp_ready_id,
                    data={
                        'type': 'external_input',
                        'name': resp_ready_id,
                        'bit_width': 1,
                        'description': f'External memory read response ready for {cache_prefix} refill',
                        'is_external_port': True,
                    }
                )
                graph.add_node(resp_ready)
                print(f"  Created external input node: {resp_ready_id}")
            completion_source = resp_ready
            completion_source_id = resp_ready_id
        else:
            completion_source = complete_signal
            completion_source_id = complete_signal_id

        gated_complete_id = f"{completion_id}_gated"
        gated_complete = Node(
            node_id=gated_complete_id,
            data={
                'type': 'logical_and',
                'name': gated_complete_id,
                'bit_width': 1,
                'description': f'Gated completion for {completion_id}',
            }
        )
        graph.add_node(gated_complete)
        graph.add_edge(Edge(completion_source, gated_complete, data={
            'type': 'logic_input', 'operand_position': 0
        }))
        graph.add_edge(Edge(reg_grant, gated_complete, data={
            'type': 'logic_input', 'operand_position': 1
        }))

        # Connect gated completion to the completion signal
        graph.add_edge(Edge(gated_complete, completion_node, data={
            'type': 'assignment'
        }))
        print(f"  Rewired {completion_id} = {completion_source_id} && {reg_grant.id}")

    # Store grant register IDs in memory node for use by idle signal generation
    grant_reg_ids = [rg.id for rg in registered_grants]
    memory_node = graph.nodes.get(memory_name)
    if memory_node:
        memory_node.data['arbiter_grant_regs'] = grant_reg_ids
        print(f"    Generated arbiter registers: {grant_reg_ids}")

    print(f"  Memory arbiter configured successfully")
    return True