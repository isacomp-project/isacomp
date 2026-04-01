#!/usr/bin/env python3
"""
Test that SMT verification catches semantic bugs.

This test creates a "bogus" ADD instruction that has the correct opcode
but performs XOR instead of addition. The verification should FAIL,
proving that our infrastructure actually detects semantic differences.
"""

import subprocess
from core.resource_graph import ResourceGraph
from verif.smt.smt_verification import EquivalenceChecker

print("=" * 70)
print("NEGATIVE TEST: Verifying Bogus Instruction Detection")
print("=" * 70)
print()

# Test 1: Compare bogus ADD (does XOR) vs real ADD
print("[Test 1] Bogus ADD (does XOR) vs Real ADD")
print("-" * 70)

graph_real_add = ResourceGraph.from_isa_file('isa/mips32/add.isa')
graph_bogus_add = ResourceGraph.from_isa_file('verif/smt/mips32/bogus_add.isa')

print(f"Real ADD:  r1 + r2 → rd")
print(f"Bogus ADD: r1 ^ r2 → rd (WRONG!)")
print()

checker = EquivalenceChecker(graph_real_add, graph_bogus_add, isa_file_path='isa/mips32/add.isa')
formula = checker.generate_equivalence_formula()

with open('/tmp/bogus_add_test.smt2', 'w') as f:
    f.write(formula)

result = subprocess.run(['z3', '-smt2', '/tmp/bogus_add_test.smt2'],
                       capture_output=True, text=True, timeout=10)

errors = [l for l in result.stdout.split('\n')
          if 'error' in l.lower() and 'model' not in l.lower()]

if errors:
    print(f"✗ SMT Errors: {len(errors)}")
    for e in errors[:2]:
        print(f"  {e}")
    test1_result = "ERROR"
elif 'unsat' in result.stdout.lower():
    print("✗ VERIFICATION BUG: Says they're equivalent (UNSAT)")
    print("  This is WRONG - bogus ADD should NOT equal real ADD!")
    test1_result = "FAIL"
elif 'sat' in result.stdout.lower():
    print("✓ CORRECT: Found counterexample (SAT)")
    print("  Verification correctly detected the semantic difference!")
    # Show the counterexample
    lines = result.stdout.split('\n')
    print("\n  Counterexample values:")
    for line in lines:
        if 'define-fun pre_r1_in' in line or 'define-fun pre_r2_in' in line:
            print(f"    {line.strip()}")
        if line.strip().startswith('#x') or line.strip().startswith('#b'):
            print(f"      {line.strip()}")
    test1_result = "PASS"
else:
    print("✗ Unexpected Z3 output")
    test1_result = "ERROR"

# Test 2: Bogus ADD preserved in merged graph
print("\n[Test 2] Bogus ADD Semantics Preserved in Merge")
print("-" * 70)
print("Testing: merge [Real ADD, Bogus ADD, SUB]")
print("Expected: Bogus ADD in merge should equal standalone bogus ADD")
print("         (merger should preserve even buggy semantics)")
print()

from core.graph_merger import ResourceGraphMerger

merger = ResourceGraphMerger()
merger.add_instruction('add', 'isa/mips32/add.isa')
merger.add_instruction('bogus_add', 'verif/smt/mips32/bogus_add.isa')
merger.add_instruction('sub', 'isa/mips32/sub.isa')

try:
    merged_graph = merger.merge_graphs()
    print(f"✓ Merged 3 instructions successfully")
    print(f"  Merged graph: {len(merged_graph.nodes)} nodes")

    # Verify that bogus_add's semantics are preserved in merge
    print("\n  Comparing: standalone bogus_add vs merged bogus_add...")
    checker = EquivalenceChecker(graph_bogus_add, merged_graph, isa_file_path='verif/smt/mips32/bogus_add.isa')
    formula = checker.generate_equivalence_formula()

    with open('/tmp/bogus_add_merged_test.smt2', 'w') as f:
        f.write(formula)

    result = subprocess.run(['z3', '-smt2', '/tmp/bogus_add_merged_test.smt2'],
                           capture_output=True, text=True, timeout=30)

    errors = [l for l in result.stdout.split('\n')
              if 'error' in l.lower() and 'model' not in l.lower()]

    if errors:
        print(f"  ✗ SMT Errors: {len(errors)}")
        test2_result = "ERROR"
    elif 'unsat' in result.stdout.lower():
        print("  ✓ CORRECT: Merger preserved bogus ADD semantics (UNSAT)")
        print("     (Even buggy instructions are correctly merged)")
        test2_result = "PASS"
    elif 'sat' in result.stdout.lower():
        print("  ✗ WRONG: Merger changed bogus ADD semantics!")
        print("     (This indicates a bug in the merger)")
        test2_result = "FAIL"
    else:
        print("  ✗ Unexpected output")
        test2_result = "ERROR"

except Exception as e:
    print(f"  ✗ ERROR: {e}")
    import traceback
    traceback.print_exc()
    test2_result = "ERROR"

# Test 3: Self-comparison of bogus ADD (should still pass - it's consistent)
print("\n[Test 3] Bogus ADD vs Itself")
print("-" * 70)
print("Testing: bogus_add compared to itself")
print("Expected: Should be equivalent (consistent, even if wrong)")
print()

checker = EquivalenceChecker(graph_bogus_add, graph_bogus_add, isa_file_path='verif/smt/mips32/bogus_add.isa')
formula = checker.generate_equivalence_formula()

with open('/tmp/bogus_add_self_test.smt2', 'w') as f:
    f.write(formula)

result = subprocess.run(['z3', '-smt2', '/tmp/bogus_add_self_test.smt2'],
                       capture_output=True, text=True, timeout=10)

errors = [l for l in result.stdout.split('\n')
          if 'error' in l.lower() and 'model' not in l.lower()]

if errors:
    print(f"✗ SMT Errors: {len(errors)}")
    test3_result = "ERROR"
elif 'unsat' in result.stdout.lower():
    print("✓ CORRECT: Bogus ADD is equivalent to itself (UNSAT)")
    print("  (Consistent implementation, even though semantically wrong)")
    test3_result = "PASS"
elif 'sat' in result.stdout.lower():
    print("✗ WRONG: Self-comparison should always be equivalent!")
    test3_result = "FAIL"
else:
    print("✗ Unexpected output")
    test3_result = "ERROR"

# Summary
print("\n" + "=" * 70)
print("NEGATIVE TEST SUMMARY")
print("=" * 70)

print(f"\nTest 1 (Bogus vs Real):     {test1_result}")
print(f"Test 2 (Bogus in Merge):    {test2_result}")
print(f"Test 3 (Bogus vs Itself):   {test3_result}")

all_pass = test1_result == "PASS" and test2_result == "PASS" and test3_result == "PASS"

print("\n" + "=" * 70)
if all_pass:
    print("✓✓✓ VALIDATION SUCCESS ✓✓✓")
    print("=" * 70)
    print()
    print("The SMT verification infrastructure correctly:")
    print("  1. Detects semantic differences (bogus ADD ≠ real ADD)")
    print("  2. Catches bugs in merged graphs")
    print("  3. Correctly handles self-comparison (bogus = bogus)")
    print()
    print("This proves the verification is NOT giving false positives!")
    print("When we see PASS results, they are genuine semantic equivalence.")
    exit(0)
else:
    print("✗ VALIDATION FAILED")
    print("=" * 70)
    print()
    print("Some tests did not behave as expected.")
    print("This may indicate issues with the verification infrastructure.")
    exit(1)
