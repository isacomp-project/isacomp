"""
Test suite for operation parallelization optimization.

Tests the ability to detect repeated operations (from serialization) and
parallelize them back into parallel wide operations.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.resource_graph import ResourceGraph, Node, Edge
from opt.temporal.operation_serialization import SerializationSpec, apply_operation_serialization
from opt.temporal.operation_parallelization import (
    OperationParallelizationTransform,
    ParallelizationSpec,
    parallelize_serialized_operations
)


def create_simple_add_operation() -> ResourceGraph:
    """
    Create a simple ResourceGraph with a 32-bit add operation.

    This represents: result = operand_a + operand_b
    """
    graph = ResourceGraph()

    # Create operand nodes (architectural state)
    operand_a = Node('operand_a', {
        'type': 'arch_state',
        'name': 'operand_a',
        'display_name': 'Operand A',
        'bit_width': 32
    }, is_arch_state=True)
    operand_a.uarch_time = 0
    graph.add_node(operand_a)

    operand_b = Node('operand_b', {
        'type': 'arch_state',
        'name': 'operand_b',
        'display_name': 'Operand B',
        'bit_width': 32
    }, is_arch_state=True)
    operand_b.uarch_time = 0
    graph.add_node(operand_b)

    # Create add operation
    add_op = Node('(operand_a + operand_b)', {
        'type': 'operation',
        'name': 'add_operation',
        'display_name': '32-bit Add',
        'expression': {
            'type': 'binary_op',
            'operator': '+',
            'left': 'operand_a',
            'right': 'operand_b'
        }
    }, is_uarch_state=False)
    add_op.uarch_time = 0
    graph.add_node(add_op)

    # Create result storage
    result = Node('result', {
        'type': 'arch_state',
        'name': 'result',
        'display_name': 'Result',
        'bit_width': 32
    }, is_arch_state=True)
    result.uarch_time = 0
    graph.add_node(result)

    # Connect operands to operation
    edge_a = Edge(operand_a, add_op, data={
        'type': 'operand',
        'position': 'left'
    })
    graph.add_edge(edge_a)

    edge_b = Edge(operand_b, add_op, data={
        'type': 'operand',
        'position': 'right'
    })
    graph.add_edge(edge_b)

    # Connect operation to result
    result_edge = Edge(add_op, result, data={
        'type': 'assignment'
    })
    graph.add_edge(result_edge)

    return graph


def test_detect_serialized_operations():
    """Test detection of serialized operations."""
    print("\n" + "="*70)
    print("TEST: Detect Serialized Operations")
    print("="*70)

    # Create a simple add operation
    graph = create_simple_add_operation()

    # Serialize it to 8-bit granularity (4 cycles for 32-bit)
    print("\nStep 1: Serializing 32-bit add to 8-bit granularity...")
    spec = SerializationSpec("(operand_a + operand_b)", 8)
    success = apply_operation_serialization(graph, [spec])

    assert success, "Serialization should succeed"
    print("✓ Serialization successful")

    # Detect serialized operations
    print("\nStep 2: Detecting serialized operations...")
    parallelizeer = OperationParallelizationTransform(graph)
    parallelize_specs = parallelizeer.detect_serialized_operations()

    # Verify detection
    assert len(parallelize_specs) > 0, "Should detect at least one serialized operation"
    assert any(s.can_parallelize for s in parallelize_specs), "At least one operation should be parallelizeable"

    parallelizeable = [s for s in parallelize_specs if s.can_parallelize]
    print(f"\n✓ Detected {len(parallelizeable)} parallelizeable operation(s)")

    for spec in parallelizeable:
        print(f"  - {spec}")
        assert spec.num_cycles == 4, "Should be 4 cycles (32-bit / 8-bit)"
        assert spec.narrow_width == 8, "Should be 8-bit narrow operations"
        assert spec.wide_width == 32, "Should parallelize to 32-bit wide operation"

    print("\n✓ TEST PASSED: Detection works correctly")
    return graph, parallelize_specs


def test_parallelize_serialized_operation():
    """Test parallelization a serialized operation back to wide parallel operation."""
    print("\n" + "="*70)
    print("TEST: Unroll Serialized Operation")
    print("="*70)

    # Create and serialize an operation
    graph = create_simple_add_operation()

    print("\nStep 1: Serializing operation...")
    spec = SerializationSpec("(operand_a + operand_b)", 8)
    apply_operation_serialization(graph, [spec])

    initial_depth = graph.get_max_uarch_time() + 1
    print(f"  Pipeline depth after serialization: {initial_depth} cycles")
    assert initial_depth >= 4, "Should take at least 4 cycles after serialization"

    # Unroll it back
    print("\nStep 2: Parallelization operation...")
    parallelizeer = OperationParallelizationTransform(graph)
    parallelize_specs = parallelizeer.detect_serialized_operations()
    parallelize_plan = parallelizeer.plan_parallelization(parallelize_specs)

    assert len(parallelize_plan) > 0, "Should have operations to parallelize"

    # Apply parallelization
    parallelizeed_any = False
    for parallelize_spec in parallelize_plan:
        if parallelizeer.apply_parallelization(parallelize_spec):
            parallelizeed_any = True

    assert parallelizeed_any, "Should successfully parallelize at least one operation"

    # Update timing
    parallelizeer.update_timing(parallelize_plan)

    final_depth = graph.get_max_uarch_time() + 1
    print(f"  Pipeline depth after parallelization: {final_depth} cycles")

    # Verify parallelization reduced latency
    assert final_depth < initial_depth, "Parallelization should reduce pipeline depth"
    print(f"  ✓ Latency reduced by {initial_depth - final_depth} cycle(s)")

    # Verify wide operation was created
    wide_ops = [n for n in graph.nodes.values() if n.data.get('type') == 'wide_operation']
    assert len(wide_ops) > 0, "Should have created a wide operation"
    print(f"  ✓ Created {len(wide_ops)} wide operation(s)")

    # Verify serialization infrastructure was removed
    counters = [n for n in graph.nodes.values() if n.data.get('type') == 'serialization_counter']
    narrow_ops = [n for n in graph.nodes.values() if n.data.get('type') == 'narrow_operation_unit']
    assert len(counters) == 0, "Serialization counter should be removed"
    assert len(narrow_ops) == 0, "Narrow operation should be removed"
    print(f"  ✓ Serialization infrastructure removed")

    print("\n✓ TEST PASSED: Parallelization works correctly")
    return graph


def test_end_to_end_workflow():
    """Test complete workflow: serialize then parallelize."""
    print("\n" + "="*70)
    print("TEST: End-to-End Workflow")
    print("="*70)

    # Create original graph
    graph = create_simple_add_operation()
    original_depth = graph.get_max_uarch_time() + 1
    print(f"\nOriginal pipeline depth: {original_depth} cycle(s)")

    # Serialize
    print("\nSerializing to 8-bit granularity...")
    spec = SerializationSpec("(operand_a + operand_b)", 8)
    apply_operation_serialization(graph, [spec])

    serialized_depth = graph.get_max_uarch_time() + 1
    print(f"Pipeline depth after serialization: {serialized_depth} cycle(s)")
    assert serialized_depth > original_depth, "Serialization should increase depth"

    # Unroll (using high-level API)
    print("\nParallelization back to parallel...")
    parallelizeed = parallelize_serialized_operations(graph)
    assert parallelizeed, "Should successfully parallelize"

    final_depth = graph.get_max_uarch_time() + 1
    print(f"Pipeline depth after parallelization: {final_depth} cycle(s)")

    # Should be back to original or close
    print(f"\nDepth comparison:")
    print(f"  Original:      {original_depth} cycle(s)")
    print(f"  Serialized:    {serialized_depth} cycle(s) (+{serialized_depth - original_depth})")
    print(f"  After parallelize:  {final_depth} cycle(s) ({final_depth - original_depth:+d})")

    assert final_depth <= serialized_depth, "Parallelization should not increase depth"

    print("\n✓ TEST PASSED: End-to-end workflow successful")


def test_multiple_operations():
    """Test parallelization multiple serialized operations."""
    print("\n" + "="*70)
    print("TEST: Multiple Operations")
    print("="*70)

    graph = ResourceGraph()

    # Create two operations
    ops = []
    for i in range(2):
        # Operands
        op_a = Node(f'op{i}_a', {
            'type': 'arch_state',
            'name': f'op{i}_a',
            'bit_width': 32
        }, is_arch_state=True)
        op_a.uarch_time = 0
        graph.add_node(op_a)

        op_b = Node(f'op{i}_b', {
            'type': 'arch_state',
            'name': f'op{i}_b',
            'bit_width': 32
        }, is_arch_state=True)
        op_b.uarch_time = 0
        graph.add_node(op_b)

        # Operation
        operation = Node(f'(op{i}_a + op{i}_b)', {
            'type': 'operation',
            'name': f'add_op_{i}',
            'expression': {
                'type': 'binary_op',
                'operator': '+',
                'left': f'op{i}_a',
                'right': f'op{i}_b'
            }
        }, is_uarch_state=False)
        operation.uarch_time = 0
        graph.add_node(operation)

        # Result
        result = Node(f'result{i}', {
            'type': 'arch_state',
            'name': f'result{i}',
            'bit_width': 32
        }, is_arch_state=True)
        result.uarch_time = 0
        graph.add_node(result)

        # Edges
        graph.add_edge(Edge(op_a, operation, data={'type': 'operand', 'position': 'left'}))
        graph.add_edge(Edge(op_b, operation, data={'type': 'operand', 'position': 'right'}))
        graph.add_edge(Edge(operation, result, data={'type': 'assignment'}))

        ops.append(operation.id)

    # Serialize both operations
    print(f"\nSerializing {len(ops)} operations...")
    serialization_specs = [
        SerializationSpec(ops[0], 8),
        SerializationSpec(ops[1], 16)  # Different granularity
    ]
    apply_operation_serialization(graph, serialization_specs)

    # Unroll all
    print(f"\nParallelization all serialized operations...")
    parallelizeed = parallelize_serialized_operations(graph)
    assert parallelizeed, "Should parallelize operations"

    # Verify both were parallelizeed
    wide_ops = [n for n in graph.nodes.values() if n.data.get('type') == 'wide_operation']
    print(f"\n✓ Created {len(wide_ops)} wide operation(s)")
    assert len(wide_ops) == 2, "Should create 2 wide operations"

    print("\n✓ TEST PASSED: Multiple operations handled correctly")


def run_all_tests():
    """Run all test cases."""
    print("\n" + "="*70)
    print("OPERATION PARALLELER TEST SUITE")
    print("="*70)

    tests = [
        ("Detection", test_detect_serialized_operations),
        ("Serialization Parallelization", test_parallelize_serialized_operation),
        
        ("End-to-End", test_end_to_end_workflow),
        ("Multiple Operations", test_multiple_operations)
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            test_func()
            passed += 1
            print(f"\n{'='*70}")
            print(f"✓ {name} test PASSED")
            print(f"{'='*70}")
        except AssertionError as e:
            failed += 1
            print(f"\n{'='*70}")
            print(f"✗ {name} test FAILED")
            print(f"Error: {e}")
            print(f"{'='*70}")
        except Exception as e:
            failed += 1
            print(f"\n{'='*70}")
            print(f"✗ {name} test FAILED with exception")
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            print(f"{'='*70}")

    # Summary
    print("\n" + "="*70)
    print("TEST SUITE SUMMARY")
    print("="*70)
    print(f"Total tests: {passed + failed}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    if failed == 0:
        print("\n🎉 ALL TESTS PASSED!")
    else:
        print(f"\n⚠ {failed} test(s) failed")

    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
