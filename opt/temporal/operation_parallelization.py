"""
Operation parallelization optimization for ResourceGraphs.

This module implements algorithms to detect serialized operations (from
operation_serialization.py) and parallelize them back into wide operations,
trading area for reduced latency.

This is the inverse of operation_serialization.py - it detects serialized
narrow operations and combines them into wide parallel operations, enabling
flexible design space exploration of area vs. latency trade-offs.
"""

from typing import Dict, List, Set, Tuple, Optional
from core.resource_graph import ResourceGraph, Node, Edge
import math


class ParallelizationSpec:
    """Specification for operation parallelization."""

    def __init__(self, operation_id: str):
        self.operation_id = operation_id  # The original operation ID

        # Analysis results
        self.num_cycles = None  # Will be determined during analysis
        self.can_parallelize = False
        self.reason = ""

        # Serialization pattern fields
        self.serialization_counter_id = None
        self.narrow_width = None
        self.wide_width = None
        self.narrow_operation_node = None

    def __str__(self):
        if self.can_parallelize:
            return f"Parallelize {self.operation_id}: {self.num_cycles}x{self.narrow_width}-bit → {self.wide_width}-bit"
        else:
            return f"Cannot parallelize {self.operation_id}: {self.reason}"


class OperationParallelizationTransform:
    """Transforms serialized operations back into wide parallel operations."""

    def __init__(self, graph: ResourceGraph):
        self.graph = graph

    # =========================================================================
    # PHASE 1: ANALYSIS
    # =========================================================================

    def detect_serialized_operations(self) -> List[ParallelizationSpec]:
        """
        Detect serialized operations in the graph.

        Returns list of ParallelizationSpec objects for each detected serialization pattern.
        """
        print("\n=== Phase 1: ANALYSIS - Detecting serialized operations ===")

        parallelization_specs = []

        # Find all serialization counters
        serialization_counters = self._find_serialization_counters()

        print(f"Found {len(serialization_counters)} serialization counter(s)")

        for counter in serialization_counters:
            print(f"\nAnalyzing serialization: {counter.id}")

            # Create spec for this serialization
            operation_id = counter.data.get('operation_id', '')
            spec = ParallelizationSpec(operation_id)
            spec.serialization_counter_id = counter.id

            # Analyze the serialization structure
            analysis = self._analyze_serialization_structure(counter, spec)

            if analysis['can_parallelize']:
                spec.can_parallelize = True
                spec.num_cycles = analysis['num_cycles']
                spec.narrow_width = analysis['narrow_width']
                spec.wide_width = analysis['wide_width']
                spec.narrow_operation_node = analysis['narrow_operation_node']
                print(f"  ✓ Can parallelize: {spec}")
            else:
                spec.can_parallelize = False
                spec.reason = analysis.get('reason', 'Unknown')
                print(f"  ✗ Cannot parallelize: {spec.reason}")

            parallelization_specs.append(spec)

        parallelizable_count = sum(1 for spec in parallelization_specs if spec.can_parallelize)
        print(f"\nAnalysis complete: {parallelizable_count}/{len(parallelization_specs)} operations can be parallelized")

        return parallelization_specs

    def _find_serialization_counters(self) -> List[Node]:
        """Find all serialization counter nodes in the graph."""
        counters = []
        for node in self.graph.nodes.values():
            if node.data.get('type') == 'serialization_counter':
                counters.append(node)
        return counters

    def _analyze_serialization_structure(self, counter: Node, spec: ParallelizationSpec) -> Dict:
        """
        Analyze the serialization structure to determine if it can be parallelized.

        Returns a dict with analysis results.
        """
        analysis = {
            'can_parallelize': False,
            'reason': ''
        }

        # Extract serialization parameters
        num_cycles = counter.data.get('max_count', 0) + 1
        operation_id = counter.data.get('operation_id', '')

        # Find the narrow operation unit
        narrow_op = self._find_narrow_operation_unit(operation_id)
        if not narrow_op:
            analysis['reason'] = 'Narrow operation unit not found'
            return analysis

        narrow_width = narrow_op.data.get('bit_width', 0)
        if narrow_width == 0:
            analysis['reason'] = 'Cannot determine narrow operation width'
            return analysis

        wide_width = narrow_width * num_cycles
        operator = narrow_op.data.get('operation', '')

        # Find bit slice extractors
        slices = self._find_bit_slice_extractors(operation_id)
        if not slices:
            analysis['reason'] = 'Bit slice extractors not found'
            return analysis

        # Verify slices match expected pattern
        expected_slices = num_cycles * 2  # Two operands
        if len(slices) != expected_slices:
            analysis['reason'] = f'Expected {expected_slices} slices, found {len(slices)}'
            return analysis

        # Check for cross-iteration dependencies (would prevent unrolling)
        if self._has_cross_iteration_dependencies(counter, narrow_op):
            analysis['reason'] = 'Cross-iteration dependencies detected'
            return analysis

        # All checks passed
        analysis['can_parallelize'] = True
        analysis['num_cycles'] = num_cycles
        analysis['narrow_width'] = narrow_width
        analysis['wide_width'] = wide_width
        analysis['operator'] = operator
        analysis['narrow_operation_node'] = narrow_op
        analysis['bit_slices'] = slices

        print(f"    Operator: {operator}, {num_cycles}x{narrow_width}-bit → {wide_width}-bit")

        return analysis

    def _find_narrow_operation_unit(self, operation_id: str) -> Optional[Node]:
        """Find the narrow operation unit for a serialized operation."""
        for node in self.graph.nodes.values():
            if node.data.get('type') == 'narrow_operation_unit':
                if node.data.get('original_operation') == operation_id:
                    return node
        return None

    def _find_bit_slice_extractors(self, operation_id: str) -> List[Node]:
        """Find all bit slice extractors for an operation."""
        slices = []
        for node in self.graph.nodes.values():
            if node.data.get('type') == 'bit_slice_extractor':
                if node.data.get('operation_id') == operation_id:
                    slices.append(node)
        return slices

    def _has_cross_iteration_dependencies(self, counter: Node, narrow_op: Node) -> bool:
        """
        Check if there are dependencies between iterations that would prevent unrolling.

        For now, we assume serialized operations don't have cross-iteration dependencies.
        A more sophisticated analysis could check for feedback loops.
        """
        # TODO: Implement more sophisticated dependency analysis
        # For now, assume no cross-iteration dependencies for standard serialized ops
        return False

    def plan_parallelization(self, specs: List[ParallelizationSpec]) -> List[ParallelizationSpec]:
        """
        Filter and prioritize unrolling specifications.

        Returns list of specs that should actually be unrolled.
        """
        print("\n=== Phase 2: PLANNING - Creating unroll plan ===")

        # Filter to only unrollable specs
        unrollable_specs = [spec for spec in specs if spec.can_parallelize]

        if not unrollable_specs:
            print("No operations to unroll")
            return []

        print(f"Planning to unroll {len(unrollable_specs)} operation(s):")
        for spec in unrollable_specs:
            print(f"  - {spec}")

        return unrollable_specs

    # =========================================================================
    # PHASE 3: STRUCTURE CREATION
    # =========================================================================

    def create_wide_operation_structure(self, spec: ParallelizationSpec) -> Dict[str, Node]:
        """
        Create the structure for a wide parallel operation.

        Returns dict with created nodes.
        """
        print(f"\n=== Phase 3: STRUCTURE - Creating wide parallel operation for {spec.operation_id} ===")

        structure = {}

        # Get operator from narrow operation
        narrow_op = spec.narrow_operation_node
        operator = narrow_op.data.get('operation', '')
        bit_width = spec.wide_width

        # Create wide operation node
        op_id = f"{spec.operation_id}_wide"

        # Build expression from original operand sources
        operand_sources = self._find_original_operand_sources(spec.operation_id)
        expression = {
            'type': 'binary_op',
            'operator': operator,
        }
        # Set left and right operands based on sources
        if len(operand_sources) >= 2:
            expression['left'] = operand_sources[0][1].id   # First operand's source node ID
            expression['right'] = operand_sources[1][1].id  # Second operand's source node ID
        elif len(operand_sources) == 1:
            # Fallback for single operand operations (shouldn't happen for binary ops)
            expression['left'] = operand_sources[0][1].id
            expression['right'] = operand_sources[0][1].id

        op_data = {
            'type': 'wide_operation',  # Keep as 'wide_operation' for test compatibility
            'name': op_id,
            'display_name': f"{bit_width}-bit {operator}",
            'operation': operator,
            'bit_width': bit_width,
            'original_operation': spec.operation_id,
            'parallelized_from': 'serialization',
            'expression': expression  # Reconstruct expression from operand sources
        }

        print(f"  Created wide operation: {op_id} ({bit_width}-bit {operator})")

        op_node = Node(op_id, op_data, is_uarch_state=False)
        op_node.uarch_time = 0  # Completes in single cycle
        self.graph.add_node(op_node)
        structure['operation'] = op_node

        return structure

    # =========================================================================
    # PHASE 4: HARDWARE GENERATION
    # =========================================================================

    def generate_wide_operation_hardware(self, spec: ParallelizationSpec, structure: Dict[str, Node]) -> Dict[str, Node]:
        """
        Generate hardware components for the wide operation.

        In this case, the wide operation itself is the hardware - no additional
        components needed since we're just widening the datapath.
        """
        print(f"\n=== Phase 4: HARDWARE - Wide operation hardware ===")
        print(f"  Wide operation hardware already created in structure phase")

        # No additional hardware needed - the wide operation is the hardware
        return structure

    # =========================================================================
    # PHASE 5: CONNECTION/WIRING
    # =========================================================================

    def wire_wide_operation(self, spec: ParallelizationSpec, structure: Dict[str, Node]):
        """
        Connect the wide parallel operation to its inputs and outputs.
        """
        print(f"\n=== Phase 5: CONNECTION - Wiring wide operation ===")

        op = structure['operation']

        # Find original operand sources (before bit slicing)
        operand_sources = self._find_original_operand_sources(spec.operation_id)

        if len(operand_sources) != 2:
            print(f"  Warning: Expected 2 operand sources, found {len(operand_sources)}")

        # Connect operands directly to wide operation
        for i, (operand_name, source_node) in enumerate(operand_sources):
            position = 'left' if i == 0 else 'right'
            edge = Edge(source_node, op, data={
                'type': 'operand',
                'position': position,
                'operand_name': operand_name
            })
            self.graph.add_edge(edge)
            print(f"  Connected {source_node.id} → {op.id} ({position})")

        # Find result destinations (where the partial result went)
        result_destinations = self._find_result_destinations(spec.operation_id)

        # Connect wide operation to destinations
        for dest in result_destinations:
            edge = Edge(op, dest, data={
                'type': 'assignment',
                'unrolled_result': True
            })
            self.graph.add_edge(edge)
            print(f"  Connected {op.id} → {dest.id}")

        print(f"  Wired {len(operand_sources)} inputs and {len(result_destinations)} outputs")

    def _find_original_operand_sources(self, operation_id: str) -> List[Tuple[str, Node]]:
        """
        Find the original operand sources (before bit slicing).

        Returns list of (operand_name, source_node) tuples.
        """
        sources = []

        # Find bit slice extractors
        slices = self._find_bit_slice_extractors(operation_id)

        # Group slices by operand
        operand_slices = {}
        for slice_node in slices:
            source_operand = slice_node.data.get('source_operand', '')
            if source_operand not in operand_slices:
                operand_slices[source_operand] = []
            operand_slices[source_operand].append(slice_node)

        # For each operand, trace back to the original source
        for operand_name, slice_nodes in operand_slices.items():
            # Take first slice and trace back to its source
            if slice_nodes:
                slice_node = slice_nodes[0]
                # Find the source of the slice (should be the original operand)
                for edge in slice_node.incoming_edges:
                    if edge.data.get('type') == 'bit_slice':
                        sources.append((operand_name, edge.source))
                        break

        return sources

    def _find_result_destinations(self, operation_id: str) -> List[Node]:
        """Find where the serialized result goes."""
        destinations = []

        # Find partial result storage
        for node in self.graph.nodes.values():
            if node.data.get('type') == 'partial_result_storage':
                if node.data.get('operation_id') == operation_id:
                    # Find what the partial result connects to
                    for edge in node.outgoing_edges:
                        destinations.append(edge.target)
                    break

        return destinations

    # =========================================================================
    # PHASE 6: CLEANUP
    # =========================================================================

    def cleanup_infrastructure(self, spec: ParallelizationSpec):
        """
        Remove all the serialization infrastructure that's no longer needed.
        """
        print(f"\n=== Phase 6: CLEANUP - Removing serialization infrastructure ===")

        nodes_to_remove = []

        # Find and mark all serialization-related nodes for removal
        for node in list(self.graph.nodes.values()):
            node_type = node.data.get('type', '')
            node_op_id = node.data.get('operation_id', '')
            # Narrow operation units use 'original_operation' field
            node_orig_op = node.data.get('original_operation', '')

            if node_op_id == spec.operation_id or node_orig_op == spec.operation_id:
                if node_type in [
                    'serialization_counter',
                    'narrow_operation_unit',
                    'bit_slice_extractor',
                    'mux',  # Slice selection muxes
                    'partial_result_storage',
                    'result_accumulator',
                    'serialization_completion'
                ]:
                    nodes_to_remove.append(node)

        print(f"  Removing {len(nodes_to_remove)} serialization infrastructure nodes:")

        # Remove nodes
        for node in nodes_to_remove:
            print(f"    - {node.id} ({node.data.get('type', 'unknown')})")
            self._remove_node(node)

        # Also remove any enable/gating nodes
        self._cleanup_enable_gating_nodes(spec)

    def _remove_node(self, node: Node):
        """Helper to remove a node and all its edges."""
        # Remove all edges
        edges_to_remove = list(node.incoming_edges) + list(node.outgoing_edges)
        for edge in edges_to_remove:
            edge.remove_from_nodes()
            if edge.id in self.graph.edges:
                del self.graph.edges[edge.id]

        # Remove node
        if node.id in self.graph.nodes:
            del self.graph.nodes[node.id]

    def _cleanup_enable_gating_nodes(self, spec: ParallelizationSpec):
        """Remove enable/gating nodes associated with the serialization."""
        nodes_to_remove = []

        for node in list(self.graph.nodes.values()):
            # Look for enable nodes that reference the serialization counter
            if 'enable' in node.id.lower() or 'gating' in node.id.lower():
                if spec.operation_id in node.id or spec.serialization_counter_id in node.id:
                    nodes_to_remove.append(node)

        for node in nodes_to_remove:
            print(f"    - {node.id} (enable/gating)")

            edges_to_remove = list(node.incoming_edges) + list(node.outgoing_edges)
            for edge in edges_to_remove:
                edge.remove_from_nodes()
                if edge.id in self.graph.edges:
                    del self.graph.edges[edge.id]

            if node.id in self.graph.nodes:
                del self.graph.nodes[node.id]

    # =========================================================================
    # PHASE 7: TIMING UPDATE
    # =========================================================================

    def update_timing(self, specs: List[ParallelizationSpec]):
        """
        Update timing information after unrolling.

        Unrolling should reduce latency since operations complete in 1 cycle
        instead of N cycles.
        """
        print(f"\n=== Phase 7: TIMING - Updating graph timing ===")

        max_time_before = self.graph.get_max_uarch_time()
        print(f"  Pipeline depth before timing update: {max_time_before + 1} cycles")

        # Re-infer timing for the entire graph
        self.graph.infer_uarch_time(force_reinfer=True)

        max_time_after = self.graph.get_max_uarch_time()
        print(f"  Pipeline depth after timing update: {max_time_after + 1} cycles")

        if max_time_after < max_time_before:
            print(f"  ✓ Latency reduced by {max_time_before - max_time_after} cycle(s)")

        print(f"  Timing update complete")

    # =========================================================================
    # HIGH-LEVEL API
    # =========================================================================

    def apply_parallelization(self, spec: ParallelizationSpec) -> bool:
        """
        Apply unrolling for a single ParallelizationSpec.

        Returns True if unrolling was successful.
        """
        if not spec.can_parallelize:
            print(f"\nSkipping {spec.operation_id}: {spec.reason}")
            return False

        print(f"\n{'='*70}")
        print(f"UNROLLING: {spec.operation_id}")
        print(f"{'='*70}")

        try:
            # Phase 3: Structure
            structure = self.create_wide_operation_structure(spec)

            # Phase 4: Hardware (minimal for wide operations)
            hardware = self.generate_wide_operation_hardware(spec, structure)

            # Phase 5: Connection
            self.wire_wide_operation(spec, structure)

            # Phase 6: Cleanup
            self.cleanup_infrastructure(spec)

            print(f"\n✓ Successfully unrolled {spec.operation_id}")
            return True

        except Exception as e:
            print(f"\n✗ Error unrolling {spec.operation_id}: {e}")
            import traceback
            traceback.print_exc()
            return False


def parallelize_serialized_operations(graph: ResourceGraph, operation_id: str = None, target_granularity: int = None) -> bool:
    """
    Detect and parallelize serialized operations in a ResourceGraph.

    This detects operations that have been serialized (from operation_serialization.py)
    and converts them back into wide parallel operations, trading area for reduced latency.

    Supports partial parallelization to intermediate granularities for fine-grained control.

    This is a high-level convenience function that performs all phases:
    1. Detection (Analysis) - Detects serialization patterns
    2. Planning
    3. Parallelization (Structure, Hardware, Connection, Cleanup)
    4. Timing update
    5. Optional re-serialization to target granularity

    Args:
        graph: ResourceGraph to optimize
        operation_id: Optional specific operation ID to parallelize. If None, parallelizes all.
        target_granularity: Optional target bit width. If specified and less than original width,
                           will re-serialize to this granularity after full parallelization.
                           E.g., 8→32→16 to go from 8-bit (4 cycles) to 16-bit (2 cycles).

    Returns:
        True if any operations were parallelized, False otherwise
    """
    from .operation_serialization import apply_operation_serialization, SerializationSpec

    print("\n" + "="*70)
    print("OPERATION PARALLELIZATION OPTIMIZATION")
    print("="*70)

    parallelizer = OperationParallelizationTransform(graph)

    # Phase 1: Analysis - Detect serialized operations
    specs = parallelizer.detect_serialized_operations()

    if not specs:
        print("\nNo serialized operations detected")
        return False

    # Filter to specific operation if requested
    if operation_id:
        specs = [s for s in specs if s.operation_id == operation_id]
        if not specs:
            print(f"\nOperation '{operation_id}' not found or not serialized")
            return False
        print(f"\nTargeting specific operation: {operation_id}")

    # Check if we need partial parallelization
    original_width = None
    current_granularity = None
    if target_granularity and specs:
        spec = specs[0]
        original_width = spec.wide_width
        current_granularity = spec.narrow_width

        if target_granularity < current_granularity:
            print(f"\nError: Target granularity ({target_granularity}-bit) is smaller than current ({current_granularity}-bit)")
            print(f"Cannot serialize further via parallelization. Use serialization mode instead.")
            return False

        if target_granularity >= original_width:
            print(f"\nTarget granularity ({target_granularity}-bit) >= original width ({original_width}-bit)")
            print(f"Will fully parallelize to {original_width}-bit")
            target_granularity = None  # Full parallelization
        elif target_granularity > current_granularity:
            print(f"\nPartial parallelization: {current_granularity}-bit → {original_width}-bit → {target_granularity}-bit")

    # Phase 2: Planning
    parallel_plan = parallelizer.plan_parallelization(specs)

    if not parallel_plan:
        print("\nNo operations selected for parallelization")
        return False

    # Phases 3-6: Apply parallelization to each operation
    parallelized_any = False
    parallelized_operation_ids = []
    for spec in parallel_plan:
        if parallelizer.apply_parallelization(spec):
            parallelized_any = True
            parallelized_operation_ids.append(spec.operation_id)

    # Phase 7: Timing (done once for all parallelized operations)
    if parallelized_any:
        parallelizer.update_timing(parallel_plan)

    # Phase 8: Optional re-serialization to target granularity
    if parallelized_any and target_granularity and target_granularity < original_width:
        print(f"\n--- Re-serializing to target granularity: {target_granularity}-bit ---")

        # Re-serialize each parallelized operation to target granularity
        for op_id in parallelized_operation_ids:
            # The operation is now called "op_id_wide" after parallelization
            wide_op_id = f"{op_id}_wide"
            if wide_op_id in graph.nodes:
                print(f"Re-serializing {wide_op_id} to {target_granularity}-bit")
                reserial_spec = SerializationSpec(wide_op_id, target_granularity)
                apply_operation_serialization(graph, [reserial_spec])

    print("\n" + "="*70)
    if parallelized_any:
        if target_granularity and target_granularity < original_width:
            print(f"PARTIAL PARALLELIZATION COMPLETE ({target_granularity}-bit)")
        else:
            print("OPERATION PARALLELIZATION COMPLETE")
    else:
        print("NO OPERATIONS PARALLELIZED")
    print("="*70 + "\n")

    return parallelized_any


def create_example_parallelization_workflow():
    """
    Example showing how to use operation parallelization:
    1. Serialize an operation (for demonstration)
    2. Parallelize it back to wide operation
    """
    print("""
Example workflow:

from .operation_serialization import apply_operation_serialization, SerializationSpec
from .operation_parallelization import parallelize_serialized_operations

# Step 1: Serialize a 32-bit add to 8-bit granularity (creates repeated ops)
serialization_specs = [
    SerializationSpec("my_add_operation", 8)  # 4 cycles
]
apply_operation_serialization(graph, serialization_specs)

# Step 2: Parallelize back (automatically detects serialized ops)
parallelize_serialized_operations(graph)

# Result: Back to single-cycle 32-bit wide operation
""")
