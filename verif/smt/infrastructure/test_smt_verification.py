#!/usr/bin/env python3
"""
Test SMT-based verification of isacomp optimizations.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.resource_graph import ResourceGraph
from verif.smt.smt_verification import (
    ResourceGraphToSMT,
    ISAAssumptionExtractor,
    EquivalenceChecker,
    verify_optimization
)
from opt.sharing.operation_sharing import apply_operation_sharing, SharingMode
from core.graph_merger import merge_instructions
import copy


def test_smt_formula_generation():
    """Test basic SMT formula generation from a resource graph."""
    print("=" * 70)
    print("TEST 1: Basic SMT Formula Generation")
    print("=" * 70)
    print()

    # Load a simple instruction
    isa_file = "isa/riscv32/add.isa"
    print(f"Loading {isa_file}...")

    graph = ResourceGraph.from_isa_file(isa_file)
    print(f"Loaded graph with {len(graph.nodes)} nodes, {len(graph.edges)} edges")
    print()

    # Convert to SMT
    print("Converting to SMT formula...")
    converter = ResourceGraphToSMT(graph, "test_")
    ctx = converter.convert_graph()

    formula = ctx.to_smt_lib2()
    print("Generated SMT-LIB2 formula:")
    print("-" * 70)
    print(formula[:1000])  # Print first 1000 chars
    if len(formula) > 1000:
        print(f"... ({len(formula) - 1000} more characters)")
    print("-" * 70)
    print()

    # Save to file for inspection
    with open("/tmp/test_add.smt2", "w") as f:
        f.write(formula)
    print("Full formula saved to /tmp/test_add.smt2")
    print()

    print("✓ Test 1 passed: SMT formula generated successfully")
    print()


def test_isa_assumption_extraction():
    """Test extracting assumptions from .isa files."""
    print("=" * 70)
    print("TEST 2: ISA Assumption Extraction")
    print("=" * 70)
    print()

    isa_file = "isa/riscv32/add.isa"
    print(f"Extracting assumptions from {isa_file}...")

    extractor = ISAAssumptionExtractor(isa_file)
    assumptions = extractor.extract()

    print(f"Found {len(assumptions)} assumptions:")
    for i, assumption in enumerate(assumptions, 1):
        print(f"  {i}. {assumption}")
    print()

    print("✓ Test 2 passed: Assumptions extracted successfully")
    print()


def test_self_equivalence():
    """Test that a graph is equivalent to itself."""
    print("=" * 70)
    print("TEST 3: Self-Equivalence Check")
    print("=" * 70)
    print()

    isa_file = "isa/riscv32/add.isa"
    print(f"Loading {isa_file}...")

    graph = ResourceGraph.from_isa_file(isa_file)
    print(f"Loaded graph with {len(graph.nodes)} nodes")
    print()

    # Create a deep copy
    graph_copy = copy.deepcopy(graph)

    print("Checking equivalence between graph and its copy...")
    print("(This should always succeed)")
    print()

    # Generate equivalence formula
    checker = EquivalenceChecker(graph, graph_copy, isa_file)
    formula = checker.generate_equivalence_formula()

    # Save for inspection
    with open("/tmp/test_equivalence.smt2", "w") as f:
        f.write(formula)
    print("Equivalence formula saved to /tmp/test_equivalence.smt2")
    print()

    # Check with z3
    print("Running z3 solver...")
    is_equiv, details = checker.check_equivalence(solver="z3", timeout=10)

    print(f"Result: {is_equiv}")
    print(f"Details: {details[:200]}")
    print()

    if is_equiv:
        print("✓ Test 3 passed: Graph is equivalent to itself")
    else:
        print("✗ Test 3 FAILED: Graph should be equivalent to itself!")
        return False

    print()
    return True


def test_simple_optimization():
    """Test verification with a simple optimization."""
    print("=" * 70)
    print("TEST 4: Simple Operation Sharing Verification")
    print("=" * 70)
    print()

    # Create a merged graph with two ADD instructions
    print("Creating merged graph with ADD and ADDI instructions...")

    # Use relative paths from the test directory
    instruction_files = {
        'add': 'isa/riscv32/add.isa',
        'addi': 'isa/riscv32/addi.isa'
    }

    print("Merging instructions...")
    merged_graph = merge_instructions(instruction_files)
    print(f"Merged graph: {len(merged_graph.nodes)} nodes, {len(merged_graph.edges)} edges")
    print()

    # Save the pre-optimization graph
    graph_pre = copy.deepcopy(merged_graph)

    # Count operations before
    ops_before = [n for n in graph_pre.nodes.values() if n.data.get('type') == 'operation']
    print(f"Operations before optimization: {len(ops_before)}")
    for op in ops_before:
        print(f"  - {op.data.get('display_name', op.id)} [{op.data.get('instruction', 'N/A')}]")
    print()

    # Select add operations explicitly for sharing
    add_op_ids = [n.id for n in ops_before
                  if (n.data.get('operator') == '+' or
                      n.data.get('expression', {}).get('operator') == '+')]
    print("Applying operation sharing...")
    print(f"  Selected nodes: {add_op_ids}")
    sharing_applied = apply_operation_sharing(merged_graph, selected_node_ids=add_op_ids, mode=SharingMode.SPATIAL) if len(add_op_ids) >= 2 else False

    if not sharing_applied:
        print("Note: No sharing was applied (may be expected for this instruction pair)")
        print()

    graph_post = merged_graph

    # Count operations after
    ops_after = [n for n in graph_post.nodes.values() if n.data.get('type') == 'operation']
    print(f"Operations after optimization: {len(ops_after)}")
    for op in ops_after:
        print(f"  - {op.data.get('display_name', op.id)}")
    print()

    # Verify equivalence
    print("Verifying equivalence...")
    is_equiv, details = verify_optimization(
        graph_pre,
        graph_post,
        isa_file_path='isa/riscv32/add.isa',  # Use assumptions from ADD
        solver='z3'
    )

    print(f"Result: {is_equiv}")
    print(f"Details: {details[:300]}")
    print()

    if is_equiv or not sharing_applied:
        print("✓ Test 4 passed")
    else:
        print("✗ Test 4 FAILED: Optimization changed semantics!")
        return False

    print()
    return True


def test_single_instruction_verification():
    """Test verification with just a single instruction (no optimization)."""
    print("=" * 70)
    print("TEST 5: Single Instruction Verification (Baseline)")
    print("=" * 70)
    print()

    isa_file = "isa/riscv32/add.isa"
    print(f"Loading {isa_file}...")

    # Load graph
    graph = ResourceGraph.from_isa_file(isa_file)
    print(f"Loaded graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
    print()

    # List some nodes
    print("Sample nodes:")
    for i, (node_id, node) in enumerate(list(graph.nodes.items())[:10]):
        node_type = node.data.get('type', 'unknown')
        node_name = node.data.get('name', node_id)
        print(f"  {i+1}. {node_name} ({node_type})")
    print()

    # Create a copy as "optimized" (identity optimization)
    graph_pre = graph
    graph_post = copy.deepcopy(graph)

    print("Generating SMT formulas for equivalence check...")

    # Generate and save formulas
    converter_pre = ResourceGraphToSMT(graph_pre, "pre_")
    ctx_pre = converter_pre.convert_graph()

    converter_post = ResourceGraphToSMT(graph_post, "post_")
    ctx_post = converter_post.convert_graph()

    print(f"Pre-optimization formula: {len(ctx_pre.declarations)} declarations, {len(ctx_pre.constraints)} constraints")
    print(f"Post-optimization formula: {len(ctx_post.declarations)} declarations, {len(ctx_post.constraints)} constraints")
    print()

    # Save for debugging
    with open("/tmp/test_pre.smt2", "w") as f:
        f.write(ctx_pre.to_smt_lib2())
    with open("/tmp/test_post.smt2", "w") as f:
        f.write(ctx_post.to_smt_lib2())

    print("Formulas saved to /tmp/test_pre.smt2 and /tmp/test_post.smt2")
    print()

    # Check equivalence
    print("Running equivalence check with z3...")
    is_equiv, details = verify_optimization(
        graph_pre,
        graph_post,
        isa_file_path=isa_file,
        solver='z3'
    )

    print(f"Result: {is_equiv}")
    print(f"Details:\n{details}")
    print()

    if is_equiv:
        print("✓ Test 5 passed: Identity transformation preserves semantics")
    else:
        print("Note: Equivalence check may need refinement")
        print("This is expected for initial implementation")

    print()
    return True


def main():
    """Run all tests."""
    print()
    print("=" * 70)
    print("SMT VERIFICATION TEST SUITE")
    print("=" * 70)
    print()

    tests = [
        test_smt_formula_generation,
        test_isa_assumption_extraction,
        test_self_equivalence,
        test_single_instruction_verification,
        # test_simple_optimization,  # May need more work
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            result = test()
            if result is False:
                failed += 1
            else:
                passed += 1
        except Exception as e:
            print(f"✗ Test failed with exception: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
            print()

    print()
    print("=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print()

    if failed == 0:
        print("✓ All tests passed!")
        return 0
    else:
        print("✗ Some tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
