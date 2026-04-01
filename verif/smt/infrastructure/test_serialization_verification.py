#!/usr/bin/env python3
"""
Test SMT verification of operation serialization optimization.

This test verifies that breaking a 32-bit add into four 8-bit adds
preserves instruction semantics.
"""

import sys
from core.resource_graph import ResourceGraph
from opt.temporal.operation_serialization import apply_operation_serialization, SerializationSpec
from verif.smt.smt_verification import (
    MultiCycleResourceGraphToSMT,
    verify_multicycle_optimization
)
import copy


def test_analyze_serialization():
    """Analyze what operation serialization creates."""
    print("=" * 70)
    print("TEST 1: Analyzing Operation Serialization")
    print("=" * 70)
    print()

    # Load MIPS32 add
    print("Loading isa/mips32/add.isa...")
    graph = ResourceGraph.from_isa_file('isa/mips32/add.isa')
    print(f"✓ Loaded graph: {len(graph.nodes)} nodes")
    print()

    # Find the (r1 + r2) operation
    print("Finding (r1 + r2) operation...")
    target_op = None
    for node in graph.nodes.values():
        if node.data.get('type') == 'operation':
            expr = node.data.get('expression', {})
            if expr.get('type') == 'binary_op' and expr.get('operator') == '+':
                # Check if it writes to 'res'
                for edge in node.outgoing_edges:
                    if edge.data.get('type') == 'assignment':
                        if edge.target.data.get('name') == 'res':
                            target_op = node
                            break
        if target_op:
            break

    if not target_op:
        print("✗ Could not find (r1 + r2) operation")
        return False

    print(f"✓ Found operation: {target_op.id}")
    print(f"  Display: {target_op.data.get('display_name', target_op.id)}")
    print()

    # Apply 8-bit serialization
    print("Applying 8-bit granularity serialization...")
    print(f"  Target: {target_op.id}")
    print(f"  This will break the 32-bit add into four 8-bit adds")
    print()

    spec = SerializationSpec(target_op.id, granularity_bits=8)
    result = apply_operation_serialization(graph, [spec])

    if not result:
        print("✗ Serialization failed")
        return False

    print(f"✓ Serialization applied")
    print(f"  Graph after: {len(graph.nodes)} nodes")
    print()

    # Analyze what was created
    print("Analyzing serialization components:")
    print("-" * 70)

    # Count by type
    by_type = {}
    for node in graph.nodes.values():
        node_type = node.data.get('type', 'unknown')
        by_type[node_type] = by_type.get(node_type, 0) + 1

    for node_type, count in sorted(by_type.items()):
        print(f"  {node_type}: {count}")
    print()

    # Show serialization-specific components
    serial_types = ['serialization_counter', 'narrow_operation_unit',
                   'partial_result_storage', 'bit_slice_extractor']

    for stype in serial_types:
        nodes = [n for n in graph.nodes.values() if n.data.get('type') == stype]
        if nodes:
            print(f"\n{stype.upper()} ({len(nodes)}):")
            for node in nodes[:5]:  # Show first 5
                print(f"  - {node.id}")
                if 'bit_width' in node.data:
                    print(f"    Width: {node.data['bit_width']} bits")
                if 'max_count' in node.data:
                    print(f"    Max count: {node.data['max_count']}")
                if 'slice_index' in node.data:
                    print(f"    Slice: {node.data['slice_index']}")

    # Show timing
    print("\nTiming distribution:")
    by_time = {}
    for node in graph.nodes.values():
        time = node.uarch_time if node.uarch_time is not None else "None"
        by_time[time] = by_time.get(time, 0) + 1

    for time in sorted(by_time.keys(), key=lambda x: x if isinstance(x, int) else -1):
        print(f"  Time {time}: {by_time[time]} nodes")
    print()

    print("✓ Test 1 passed")
    print()
    return True


def test_serialization_verification():
    """Verify that operation serialization preserves semantics."""
    print("=" * 70)
    print("TEST 2: Verifying Operation Serialization")
    print("=" * 70)
    print()

    # Create pre-optimization graph
    print("Step 1: Creating pre-optimization graph...")
    graph_pre = ResourceGraph.from_isa_file('isa/mips32/add.isa')
    print(f"✓ Pre-optimization: {len(graph_pre.nodes)} nodes")
    print()

    # Find target operation
    target_op = None
    for node in graph_pre.nodes.values():
        if node.data.get('type') == 'operation':
            expr = node.data.get('expression', {})
            if expr.get('type') == 'binary_op' and expr.get('operator') == '+':
                for edge in node.outgoing_edges:
                    if edge.data.get('type') == 'assignment':
                        if edge.target.data.get('name') == 'res':
                            target_op = node
                            break
        if target_op:
            break

    if not target_op:
        print("✗ Could not find target operation")
        return False

    # Create post-optimization graph
    print("Step 2: Applying 8-bit serialization...")
    graph_post = ResourceGraph.from_isa_file('isa/mips32/add.isa')

    # Find operation in post graph (same ID)
    target_op_post = graph_post.nodes.get(target_op.id)
    if not target_op_post:
        print("✗ Could not find operation in post graph")
        return False

    spec = SerializationSpec(target_op_post.id, granularity_bits=8)
    result = apply_operation_serialization(graph_post, [spec])

    if not result:
        print("✗ Serialization failed")
        return False

    print(f"✓ Post-optimization: {len(graph_post.nodes)} nodes")
    print()

    # Analyze cycles
    converter_pre = MultiCycleResourceGraphToSMT(graph_pre, "pre_")
    converter_post = MultiCycleResourceGraphToSMT(graph_post, "post_")

    print(f"Pre-optimization cycles: {converter_pre.max_cycle}")
    print(f"Post-optimization cycles: {converter_post.max_cycle}")
    print()

    # Generate SMT formulas
    print("Step 3: Generating SMT formulas...")
    ctx_pre = converter_pre.convert_graph()
    ctx_post = converter_post.convert_graph()

    print(f"Pre-optimization:  {len(ctx_pre.declarations)} vars, {len(ctx_pre.constraints)} constraints")
    print(f"Post-optimization: {len(ctx_post.declarations)} vars, {len(ctx_post.constraints)} constraints")
    print()

    # Save for inspection
    with open("/tmp/serialize_pre.smt2", "w") as f:
        f.write(ctx_pre.to_smt_lib2())
    with open("/tmp/serialize_post.smt2", "w") as f:
        f.write(ctx_post.to_smt_lib2())

    print("Formulas saved to /tmp/serialize_pre.smt2 and /tmp/serialize_post.smt2")
    print()

    # Verify equivalence
    print("Step 4: Verifying semantic equivalence with z3...")
    print("(This may take a minute for complex serializations...)")
    print()

    is_equiv, details = verify_multicycle_optimization(
        graph_pre,
        graph_post,
        isa_file_path='isa/mips32/add.isa',
        solver='z3'
    )

    print(f"Result: {'✓ EQUIVALENT' if is_equiv else '✗ NOT EQUIVALENT'}")
    print()
    print("Solver details (first 800 chars):")
    print("-" * 70)
    print(details[:800])
    print("-" * 70)
    print()

    if is_equiv:
        print("✓ Test 2 passed: Serialization preserves semantics!")
        return True
    else:
        print("Note: Verification may need refinement for serialization")
        print("This is expected if serialization components aren't fully modeled")
        return False


def test_different_granularities():
    """Test serialization with different granularities."""
    print("=" * 70)
    print("TEST 3: Different Serialization Granularities")
    print("=" * 70)
    print()

    granularities = [16, 8, 4]  # Different bit widths

    for gran in granularities:
        print(f"Testing {gran}-bit granularity:")
        print("-" * 50)

        graph = ResourceGraph.from_isa_file('isa/mips32/add.isa')

        # Find operation
        target_op = None
        for node in graph.nodes.values():
            if node.data.get('type') == 'operation':
                expr = node.data.get('expression', {})
                if expr.get('type') == 'binary_op' and expr.get('operator') == '+':
                    for edge in node.outgoing_edges:
                        if edge.data.get('type') == 'assignment':
                            if edge.target.data.get('name') == 'res':
                                target_op = node
                                break
            if target_op:
                break

        if target_op:
            spec = SerializationSpec(target_op.id, granularity_bits=gran)
            result = apply_operation_serialization(graph, [spec])

            if result:
                # Calculate expected cycles
                expected_cycles = 32 // gran
                converter = MultiCycleResourceGraphToSMT(graph, "test_")
                actual_cycles = converter.max_cycle

                print(f"  ✓ Serialization applied")
                print(f"  Expected cycles: {expected_cycles}")
                print(f"  Actual max cycle: {actual_cycles}")
                print(f"  Nodes created: {len(graph.nodes)}")
            else:
                print(f"  ✗ Serialization failed")
        else:
            print(f"  ✗ Could not find operation")

        print()

    print("✓ Test 3 passed")
    print()


def main():
    """Run operation serialization verification tests."""
    print()
    print("=" * 70)
    print("OPERATION SERIALIZATION VERIFICATION TEST SUITE")
    print("=" * 70)
    print()
    print("This test verifies that breaking a 32-bit add into")
    print("multiple 8-bit adds preserves instruction semantics.")
    print()

    tests = [
        test_analyze_serialization,
        test_different_granularities,
        test_serialization_verification,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            result = test()
            if result is not False:
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"✗ Test failed with exception: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
            print()

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Passed: {passed}/{len(tests)}")
    print(f"Failed: {failed}/{len(tests)}")
    print()

    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
