#!/usr/bin/env python3
"""Test SMT verification on merged MIPS32 instruction graphs."""

from core.resource_graph import ResourceGraph
from core.graph_merger import ResourceGraphMerger
from verif.smt.smt_verification import EquivalenceChecker
import subprocess

print("=" * 70)
print("Testing SMT Verification on Merged MIPS32 Graphs")
print("=" * 70)

# Test 1: Merge ADD and SUB instructions
print("\n[Test 1] Merge ADD and SUB")
print("-" * 70)

try:
    # Load individual graphs
    graph_add = ResourceGraph.from_isa_file('isa/mips32/add.isa')
    graph_sub = ResourceGraph.from_isa_file('isa/mips32/sub.isa')

    # Merge them
    merger = ResourceGraphMerger()
    merger.add_instruction('add', 'isa/mips32/add.isa')
    merger.add_instruction('sub', 'isa/mips32/sub.isa')
    merged_graph = merger.merge_graphs()

    print(f"Individual graphs: {len(graph_add.nodes)} + {len(graph_sub.nodes)} nodes")
    print(f"Merged graph: {len(merged_graph.nodes)} nodes")

    # Verify ADD instruction in merged graph is equivalent to standalone ADD
    print("\nVerifying ADD in merged graph vs standalone ADD...")
    checker = EquivalenceChecker(graph_add, merged_graph, isa_file_path='isa/mips32/add.isa')
    formula = checker.generate_equivalence_formula()

    with open('/tmp/mips32_merged_add.smt2', 'w') as f:
        f.write(formula)

    result = subprocess.run(['z3', '-smt2', '/tmp/mips32_merged_add.smt2'],
                          capture_output=True, text=True, timeout=30)

    errors = [l for l in result.stdout.split('\n')
              if 'error' in l.lower() and 'model' not in l.lower()]

    if errors:
        print(f"  ✗ FAIL: {len(errors)} SMT errors")
        for e in errors[:3]:
            print(f"    {e}")
        test1_pass = False
    elif 'unsat' in result.stdout.lower():
        print("  ✓ PASS: ADD preserved in merged graph")
        test1_pass = True
    elif 'sat' in result.stdout.lower():
        print("  ✗ FAIL: ADD not equivalent in merged graph")
        test1_pass = False
    else:
        print("  ✗ ERROR: Unexpected Z3 output")
        test1_pass = False

    # Verify SUB instruction in merged graph
    print("\nVerifying SUB in merged graph vs standalone SUB...")
    checker = EquivalenceChecker(graph_sub, merged_graph, isa_file_path='isa/mips32/sub.isa')
    formula = checker.generate_equivalence_formula()

    with open('/tmp/mips32_merged_sub.smt2', 'w') as f:
        f.write(formula)

    result = subprocess.run(['z3', '-smt2', '/tmp/mips32_merged_sub.smt2'],
                          capture_output=True, text=True, timeout=30)

    errors = [l for l in result.stdout.split('\n')
              if 'error' in l.lower() and 'model' not in l.lower()]

    if errors:
        print(f"  ✗ FAIL: {len(errors)} SMT errors")
        for e in errors[:3]:
            print(f"    {e}")
        test1_sub_pass = False
    elif 'unsat' in result.stdout.lower():
        print("  ✓ PASS: SUB preserved in merged graph")
        test1_sub_pass = True
    elif 'sat' in result.stdout.lower():
        print("  ✗ FAIL: SUB not equivalent in merged graph")
        test1_sub_pass = False
    else:
        print("  ✗ ERROR: Unexpected Z3 output")
        test1_sub_pass = False

    test1_final = test1_pass and test1_sub_pass

except subprocess.TimeoutExpired:
    print("  ✗ TIMEOUT: Z3 took > 30s")
    test1_final = False
except Exception as e:
    print(f"  ✗ ERROR: {str(e)[:80]}...")
    import traceback
    traceback.print_exc()
    test1_final = False

# Summary
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

if test1_final:
    print("✓ Merged graph verification successful!")
    print("  - ADD instruction semantics preserved")
    print("  - SUB instruction semantics preserved")
else:
    print("✗ Merged graph verification failed")
    print("  This may indicate issues with:")
    print("  - Instruction merging logic")
    print("  - SMT handling of merged graphs")
    print("  - ISA assumptions in merged context")
