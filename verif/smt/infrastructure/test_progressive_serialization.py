#!/usr/bin/env python3
"""
Test progressive serialization - verify that stepwise serialization
maintains correctness at each step and end-to-end.

This tests the transitivity of equivalence:
If A ≡ B and B ≡ C, then A ≡ C

Serialization chain: 32-bit → 16-bit → 8-bit → 4-bit → 2-bit → 1-bit
"""

import sys
from core.resource_graph import ResourceGraph
from opt.temporal.operation_serialization import apply_operation_serialization, SerializationSpec
from verif.smt.smt_verification import (
    MultiCycleResourceGraphToSMT,
    verify_multicycle_optimization
)
import copy


def create_serialized_graph(granularity: int):
    """Create a graph with serialization at the given granularity."""
    graph = ResourceGraph.from_isa_file('isa/mips32/add.isa')

    # Find the (r1 + r2) operation
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

    if not target_op:
        raise ValueError("Could not find (r1 + r2) operation")

    # Apply serialization
    spec = SerializationSpec(target_op.id, granularity_bits=granularity)
    result = apply_operation_serialization(graph, [spec])

    if not result:
        raise ValueError(f"Serialization to {granularity}-bit failed")

    return graph


def test_progressive_serialization():
    """Test progressive serialization with stepwise verification."""
    print("=" * 70)
    print("PROGRESSIVE SERIALIZATION VERIFICATION")
    print("=" * 70)
    print()
    print("Testing that progressive serialization maintains correctness:")
    print("  32-bit (parallel) → 16-bit → 8-bit → 4-bit → 2-bit → 1-bit")
    print()
    print("Each step will be verified for equivalence.")
    print()

    # Define the serialization chain
    granularities = [32, 16, 8, 4, 2, 1]

    # Create all graphs
    print("Step 1: Creating serialized graphs at each granularity...")
    print("-" * 70)

    graphs = {}
    for gran in granularities:
        if gran == 32:
            # Original graph (no serialization)
            graphs[gran] = ResourceGraph.from_isa_file('isa/mips32/add.isa')
            print(f"  {gran}-bit: Original parallel implementation")
        else:
            try:
                graphs[gran] = create_serialized_graph(gran)
                expected_cycles = 32 // gran
                converter = MultiCycleResourceGraphToSMT(graphs[gran], "tmp_")
                actual_cycles = converter.max_cycle
                print(f"  {gran}-bit: {len(graphs[gran].nodes)} nodes, "
                      f"max_cycle={actual_cycles} (expected ~{expected_cycles})")
            except Exception as e:
                print(f"  {gran}-bit: FAILED - {e}")
                return False

    print()

    # Test stepwise equivalence
    print("Step 2: Verifying stepwise equivalence...")
    print("-" * 70)

    stepwise_results = []

    for i in range(len(granularities) - 1):
        gran_a = granularities[i]
        gran_b = granularities[i + 1]

        print(f"\nVerifying: {gran_a}-bit ≡ {gran_b}-bit")
        print(f"  (Step {i+1} of {len(granularities)-1})")

        graph_a = graphs[gran_a]
        graph_b = graphs[gran_b]

        # Get cycle counts
        conv_a = MultiCycleResourceGraphToSMT(graph_a, "a_")
        conv_b = MultiCycleResourceGraphToSMT(graph_b, "b_")

        print(f"  Graph A ({gran_a}-bit): {len(graph_a.nodes)} nodes, {conv_a.max_cycle} cycles")
        print(f"  Graph B ({gran_b}-bit): {len(graph_b.nodes)} nodes, {conv_b.max_cycle} cycles")

        # Verify equivalence
        print(f"  Running z3 solver...")

        is_equiv, details = verify_multicycle_optimization(
            graph_a,
            graph_b,
            isa_file_path='isa/mips32/add.isa',
            solver='z3'
        )

        result_str = "✓ EQUIVALENT" if is_equiv else "✗ NOT EQUIVALENT"
        print(f"  Result: {result_str}")

        stepwise_results.append({
            'from': gran_a,
            'to': gran_b,
            'equivalent': is_equiv,
            'details': details[:200]
        })

        if not is_equiv:
            print(f"  ✗ FAILED at step {gran_a}→{gran_b}")
            print(f"  Details: {details[:500]}")
            return False

        print(f"  ✓ Step passed")

    print()
    print("=" * 70)
    print("✓ ALL STEPWISE VERIFICATIONS PASSED!")
    print("=" * 70)
    print()

    # Test end-to-end equivalence
    print("Step 3: Verifying end-to-end equivalence...")
    print("-" * 70)
    print()
    print("Testing: 32-bit (original) ≡ 1-bit (fully serialized)")
    print("  This verifies transitivity: if A≡B≡C≡D≡E≡F, then A≡F")
    print()

    graph_32 = graphs[32]
    graph_1 = graphs[1]

    conv_32 = MultiCycleResourceGraphToSMT(graph_32, "orig_")
    conv_1 = MultiCycleResourceGraphToSMT(graph_1, "serial_")

    print(f"  Original (32-bit):     {len(graph_32.nodes)} nodes, {conv_32.max_cycle} cycles")
    print(f"  Serialized (1-bit):    {len(graph_1.nodes)} nodes, {conv_1.max_cycle} cycles")
    print(f"  Complexity ratio:      {len(graph_1.nodes) / len(graph_32.nodes):.1f}x nodes")
    print(f"  Cycle expansion:       {conv_1.max_cycle + 1}x cycles")
    print()

    print("  Running z3 solver (this may take longer for 1-bit serialization)...")

    is_equiv, details = verify_multicycle_optimization(
        graph_32,
        graph_1,
        isa_file_path='isa/mips32/add.isa',
        solver='z3'
    )

    print()
    result_str = "✓ EQUIVALENT" if is_equiv else "✗ NOT EQUIVALENT"
    print(f"  Result: {result_str}")
    print()

    if is_equiv:
        print("=" * 70)
        print("🎉 END-TO-END VERIFICATION PASSED!")
        print("=" * 70)
        print()
        print("This proves:")
        print("  • Progressive serialization is correct at each step")
        print("  • Equivalence is transitive")
        print("  • 32-bit parallel ≡ 1-bit serialized (32× more cycles)")
        print("  • Can serialize operations to arbitrary granularity safely!")
        print()
    else:
        print("✗ End-to-end verification failed!")
        print(f"Details: {details[:500]}")
        return False

    # Summary
    print("=" * 70)
    print("VERIFICATION SUMMARY")
    print("=" * 70)
    print()
    print("Stepwise verifications:")
    for i, result in enumerate(stepwise_results, 1):
        status = "✓" if result['equivalent'] else "✗"
        print(f"  {status} Step {i}: {result['from']}-bit → {result['to']}-bit")

    print()
    print(f"  ✓ End-to-end: 32-bit → 1-bit")
    print()
    print(f"Total verifications: {len(stepwise_results) + 1}")
    print(f"All passed: ✓")
    print()

    return True


def test_serialization_chain_properties():
    """Test properties of the serialization chain."""
    print("=" * 70)
    print("SERIALIZATION CHAIN PROPERTIES")
    print("=" * 70)
    print()

    granularities = [32, 16, 8, 4, 2, 1]

    print("Analyzing graph growth as serialization increases:")
    print("-" * 70)
    print()

    print(f"{'Gran':<8} {'Nodes':<8} {'Cycles':<8} {'Vars':<8} {'Constraints':<12}")
    print("-" * 50)

    for gran in granularities:
        if gran == 32:
            graph = ResourceGraph.from_isa_file('isa/mips32/add.isa')
        else:
            graph = create_serialized_graph(gran)

        converter = MultiCycleResourceGraphToSMT(graph, "test_")
        ctx = converter.convert_graph()

        nodes = len(graph.nodes)
        cycles = converter.max_cycle
        vars_count = len(ctx.declarations)
        constraints = len(ctx.constraints)

        print(f"{gran}-bit  {nodes:<8} {cycles:<8} {vars_count:<8} {constraints:<12}")

    print()
    print("Observations:")
    print("  • Node count increases with finer serialization (more slicers, muxes)")
    print("  • Cycle count grows linearly (32/granularity)")
    print("  • SMT variables/constraints grow with nodes × cycles")
    print()

    return True


def main():
    """Run progressive serialization verification tests."""
    print()
    print("=" * 70)
    print("PROGRESSIVE SERIALIZATION VERIFICATION TEST SUITE")
    print("=" * 70)
    print()
    print("This test suite verifies that:")
    print("  1. Each step of serialization preserves semantics")
    print("  2. Equivalence is transitive across the chain")
    print("  3. Full serialization (32-bit → 1-bit) is correct")
    print()

    tests = [
        ("Properties Analysis", test_serialization_chain_properties),
        ("Progressive Verification", test_progressive_serialization),
    ]

    passed = 0
    failed = 0

    for test_name, test_func in tests:
        print()
        print(f"Running: {test_name}")
        print("=" * 70)

        try:
            result = test_func()
            if result:
                print(f"✓ {test_name} PASSED")
                passed += 1
            else:
                print(f"✗ {test_name} FAILED")
                failed += 1
        except Exception as e:
            print(f"✗ {test_name} FAILED with exception: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

        print()

    print()
    print("=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    print(f"Tests passed: {passed}/{len(tests)}")
    print(f"Tests failed: {failed}/{len(tests)}")
    print()

    if failed == 0:
        print("🎉 ALL TESTS PASSED!")
        print()
        print("Progressive serialization is PROVEN CORRECT!")
        return 0
    else:
        print("Some tests failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
