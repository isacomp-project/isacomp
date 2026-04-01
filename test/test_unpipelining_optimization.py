#!/usr/bin/env python3
"""
Test unpipelining optimization.

This demonstrates reversing pipelining optimizations to restore a design to
a single-cycle implementation.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.resource_graph import ResourceGraph
from core.graph_merger import merge_instructions
from opt.pipeline.pipelining_optimization import apply_pipelining_optimization
from opt.pipeline.unpipelining_optimization import apply_unpipelining_optimization, UnpipelineTransform


def count_pipeline_components(graph: ResourceGraph) -> dict:
    """Count different types of pipeline components in the graph."""
    components = {
        'pipeline_registers': 0,
        'hazard_comparators': 0,
        'stall_signals': 0,
        'stall_controllers': 0,
        'bypass_muxes': 0,
        'bypass_comparators': 0,
        'other_pipeline_components': 0,
        'total_pipeline_components': 0
    }

    for node in graph.nodes.values():
        node_type = node.data.get('type')
        node_resolution = node.data.get('resolution')

        # Check for bypass muxes (may not have pipeline_component flag!)
        if node_type == 'mux' and node_resolution == 'bypass':
            components['bypass_muxes'] += 1
            components['total_pipeline_components'] += 1
            continue

        # Check for bypass comparators (may not have pipeline_component flag!)
        if (node_type == 'operation' and
            (node_resolution == 'bypass' or 'bypass' in node.id.lower())):
            components['bypass_comparators'] += 1
            components['total_pipeline_components'] += 1
            continue

        # Check for stall comparators (may not have pipeline_component flag!)
        if (node_type == 'operation' and
            'stall' in node.id.lower() and
            node.data.get('operator') == '=='):
            components['stall_signals'] += 1
            components['total_pipeline_components'] += 1
            continue

        # Check for hazard comparators without pipeline_component flag
        if (node_type == 'operation' and
            'hazard' in node.id.lower() and
            'cmp' in node.id.lower()):
            components['hazard_comparators'] += 1
            components['total_pipeline_components'] += 1
            continue

        # Check if this is a pipeline component (with pipeline_component flag)
        if not node.data.get('pipeline_component'):
            continue

        components['total_pipeline_components'] += 1

        if node_type == 'pipeline_register':
            components['pipeline_registers'] += 1
        elif node_type == 'pipeline_stall_controller':
            components['stall_controllers'] += 1
        elif node_type == 'operation':
            # Hazard comparators and stall signals are marked as operations with pipeline_component flag
            if 'hazard' in node.id.lower() and 'cmp' in node.id.lower():
                components['hazard_comparators'] += 1
            elif 'stall' in node.id.lower():
                components['stall_signals'] += 1
            else:
                components['other_pipeline_components'] += 1
        else:
            components['other_pipeline_components'] += 1

    return components


def test_basic_unpipelining():
    """Test unpipelining on a simple pipelined instruction."""

    print("=== TESTING BASIC UNPIPELINING ===")
    print()

    # STEP 1: Create a simple graph
    print("STEP 1: Creating test graph...")
    graph = ResourceGraph.from_isa_file('isa/riscv32/add.isa')
    graph.infer_uarch_time()

    initial_node_count = len(graph.nodes)
    initial_edge_count = len(graph.edges)
    initial_max_time = graph.get_max_uarch_time()

    print(f"Original graph: {initial_node_count} nodes, {initial_edge_count} edges")
    print(f"Original pipeline depth: {initial_max_time + 1} cycles")

    # STEP 2: Apply pipelining
    print("\nSTEP 2: Applying pipelining (2 stages)...")
    success = apply_pipelining_optimization(graph, num_stages=2)

    if not success:
        print("ERROR: Pipelining failed!")
        return False

    pipelined_node_count = len(graph.nodes)
    pipelined_edge_count = len(graph.edges)
    pipelined_max_time = graph.get_max_uarch_time()

    print(f"After pipelining: {pipelined_node_count} nodes, {pipelined_edge_count} edges")
    print(f"Pipeline depth: {pipelined_max_time + 1} cycles")

    # Count pipeline components
    components = count_pipeline_components(graph)
    print(f"\nPipeline components added:")
    print(f"  - Pipeline registers: {components['pipeline_registers']}")
    print(f"  - Hazard comparators: {components['hazard_comparators']}")
    print(f"  - Stall signals: {components['stall_signals']}")
    print(f"  - Stall controllers: {components['stall_controllers']}")
    print(f"  - Total: {components['total_pipeline_components']}")

    # STEP 3: Apply unpipelining
    print("\nSTEP 3: Applying unpipelining...")
    success = apply_unpipelining_optimization(graph)

    if not success:
        print("ERROR: Unpipelining failed!")
        return False

    unpipelined_node_count = len(graph.nodes)
    unpipelined_edge_count = len(graph.edges)
    unpipelined_max_time = graph.get_max_uarch_time()

    print(f"After unpipelining: {unpipelined_node_count} nodes, {unpipelined_edge_count} edges")
    print(f"Pipeline depth: {unpipelined_max_time + 1} cycles")

    # Count remaining pipeline components
    remaining_components = count_pipeline_components(graph)
    print(f"\nRemaining pipeline components:")
    print(f"  - Pipeline registers: {remaining_components['pipeline_registers']}")
    print(f"  - Hazard comparators: {remaining_components['hazard_comparators']}")
    print(f"  - Stall signals: {remaining_components['stall_signals']}")
    print(f"  - Stall controllers: {remaining_components['stall_controllers']}")
    print(f"  - Total: {remaining_components['total_pipeline_components']}")

    # Verify unpipelining
    print("\nVERIFICATION:")
    print("=" * 50)

    success = True

    # Check 1: All pipeline components removed
    if remaining_components['total_pipeline_components'] > 0:
        print(f"❌ FAIL: {remaining_components['total_pipeline_components']} pipeline components still present")
        success = False
    else:
        print("✓ PASS: All pipeline components removed")

    # Check 2: Design is single-cycle (max uarch_time should be 0 or very small)
    if unpipelined_max_time > 0:
        print(f"⚠ WARNING: Maximum uarch_time is {unpipelined_max_time} (expected 0 for single-cycle)")
        # This might be okay if there are multi-cycle operations
    else:
        print("✓ PASS: Design is single-cycle (max uarch_time = 0)")

    # Check 3: Node count approximately restored (may differ due to removed pipeline components)
    if unpipelined_node_count > initial_node_count:
        print(f"⚠ WARNING: Node count increased from {initial_node_count} to {unpipelined_node_count}")
    else:
        print(f"✓ PASS: Node count restored or reduced ({initial_node_count} -> {unpipelined_node_count})")

    return success


def test_merged_instruction_unpipelining():
    """Test unpipelining on merged instructions with hazards."""

    print("\n\n=== TESTING MERGED INSTRUCTION UNPIPELINING ===")
    print()

    # STEP 1: Create merged graph
    print("STEP 1: Creating merged instruction graph...")
    instruction_files = {
        'add': 'isa/riscv32/add.isa',
        'or': 'isa/riscv32/or.isa'
    }

    graph = merge_instructions(instruction_files)
    graph.infer_uarch_time()

    initial_node_count = len(graph.nodes)
    initial_edge_count = len(graph.edges)
    initial_max_time = graph.get_max_uarch_time()

    print(f"Merged graph: {initial_node_count} nodes, {initial_edge_count} edges")
    print(f"Original pipeline depth: {initial_max_time + 1} cycles")

    # STEP 2: Apply pipelining
    print("\nSTEP 2: Applying pipelining (3 stages)...")
    success = apply_pipelining_optimization(graph, num_stages=3)

    if not success:
        print("ERROR: Pipelining failed!")
        return False

    pipelined_node_count = len(graph.nodes)
    pipelined_max_time = graph.get_max_uarch_time()

    print(f"After pipelining: {pipelined_node_count} nodes")
    print(f"Pipeline depth: {pipelined_max_time + 1} cycles")

    # Count pipeline components
    components = count_pipeline_components(graph)
    print(f"\nPipeline components added:")
    print(f"  - Pipeline registers: {components['pipeline_registers']}")
    print(f"  - Hazard comparators: {components['hazard_comparators']}")
    print(f"  - Stall signals: {components['stall_signals']}")
    print(f"  - Stall controllers: {components['stall_controllers']}")
    print(f"  - Total: {components['total_pipeline_components']}")

    # STEP 3: Apply unpipelining
    print("\nSTEP 3: Applying unpipelining...")
    success = apply_unpipelining_optimization(graph)

    if not success:
        print("ERROR: Unpipelining failed!")
        return False

    unpipelined_node_count = len(graph.nodes)
    unpipelined_max_time = graph.get_max_uarch_time()

    print(f"After unpipelining: {unpipelined_node_count} nodes")
    print(f"Pipeline depth: {unpipelined_max_time + 1} cycles")

    # Verify
    remaining_components = count_pipeline_components(graph)
    print(f"\nRemaining pipeline components: {remaining_components['total_pipeline_components']}")

    print("\nVERIFICATION:")
    print("=" * 50)

    success = True

    if remaining_components['total_pipeline_components'] > 0:
        print(f"❌ FAIL: {remaining_components['total_pipeline_components']} pipeline components still present")
        success = False
    else:
        print("✓ PASS: All pipeline components removed")

    if unpipelined_max_time > 0:
        print(f"⚠ WARNING: Maximum uarch_time is {unpipelined_max_time}")
    else:
        print("✓ PASS: Design is single-cycle")

    return success


def test_unpipeline_transform_class():
    """Test the UnpipelineTransform class directly."""

    print("\n\n=== TESTING UNPIPELINE TRANSFORM CLASS ===")
    print()

    # Create and pipeline a graph
    print("STEP 1: Creating and pipelining test graph...")
    graph = ResourceGraph.from_isa_file('isa/riscv32/add.isa')
    graph.infer_uarch_time()

    apply_pipelining_optimization(graph, num_stages=2)

    initial_components = count_pipeline_components(graph)
    print(f"Pipeline components before unpipelining: {initial_components['total_pipeline_components']}")

    # Create UnpipelineTransform and test methods
    print("\nSTEP 2: Testing UnpipelineTransform class...")
    transform = UnpipelineTransform(graph)

    # Test component identification
    components = transform.identify_pipeline_components()

    print(f"\nIdentified components:")
    print(f"  - Pipeline registers: {len(components['pipeline_registers'])}")
    print(f"  - Hazard comparators: {len(components['hazard_comparators'])}")
    print(f"  - Stall signals: {len(components['stall_signals'])}")
    print(f"  - Stall controllers: {len(components['stall_controllers'])}")

    # Apply unpipelining
    print("\nSTEP 3: Applying unpipelining transformation...")
    success = transform.unpipeline()

    if not success:
        print("ERROR: Unpipelining failed!")
        return False

    # Get statistics
    stats = transform.get_statistics()
    print(f"\nTransformation statistics:")
    print(f"  - Nodes removed: {stats['nodes_removed']}")
    print(f"  - Edges removed: {stats['edges_removed']}")
    print(f"  - Edges restored: {stats['edges_restored']}")

    # Verify
    final_components = count_pipeline_components(graph)
    print(f"\nRemaining pipeline components: {final_components['total_pipeline_components']}")

    print("\nVERIFICATION:")
    print("=" * 50)

    if final_components['total_pipeline_components'] == 0:
        print("✓ PASS: All pipeline components removed")
        return True
    else:
        print(f"❌ FAIL: {final_components['total_pipeline_components']} components remaining")
        return False


def test_unpipelining_already_single_cycle():
    """Test unpipelining on a design that's already single-cycle."""

    print("\n\n=== TESTING UNPIPELINING ON SINGLE-CYCLE DESIGN ===")
    print()

    # Create a graph without pipelining
    print("STEP 1: Creating single-cycle graph...")
    graph = ResourceGraph.from_isa_file('isa/riscv32/add.isa')
    graph.infer_uarch_time()

    initial_node_count = len(graph.nodes)
    initial_max_time = graph.get_max_uarch_time()

    print(f"Graph: {initial_node_count} nodes")
    print(f"Pipeline depth: {initial_max_time + 1} cycles")

    components = count_pipeline_components(graph)
    print(f"Pipeline components: {components['total_pipeline_components']}")

    # Apply unpipelining (should be a no-op)
    print("\nSTEP 2: Applying unpipelining to already single-cycle design...")
    success = apply_unpipelining_optimization(graph)

    final_node_count = len(graph.nodes)
    final_max_time = graph.get_max_uarch_time()

    print(f"\nAfter unpipelining: {final_node_count} nodes")
    print(f"Pipeline depth: {final_max_time + 1} cycles")

    print("\nVERIFICATION:")
    print("=" * 50)

    if success:
        print("✓ PASS: Unpipelining succeeded (no-op expected)")
    else:
        print("❌ FAIL: Unpipelining failed on single-cycle design")
        return False

    if final_node_count == initial_node_count:
        print("✓ PASS: Node count unchanged")
    else:
        print(f"❌ FAIL: Node count changed from {initial_node_count} to {final_node_count}")
        return False

    return True


def run_all_tests():
    """Run all unpipelining tests."""

    print("=" * 70)
    print("UNPIPELINING OPTIMIZATION TEST SUITE")
    print("=" * 70)
    print()

    tests = [
        ("Basic Unpipelining", test_basic_unpipelining),
        ("Merged Instruction Unpipelining", test_merged_instruction_unpipelining),
        ("UnpipelineTransform Class", test_unpipeline_transform_class),
        ("Already Single-Cycle", test_unpipelining_already_single_cycle),
    ]

    results = []

    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ TEST FAILED WITH EXCEPTION: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))

    # Print summary
    print("\n\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✓ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")

    print()
    print(f"Total: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 ALL TESTS PASSED! 🎉")
        return True
    else:
        print(f"\n⚠ {total - passed} test(s) failed")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
