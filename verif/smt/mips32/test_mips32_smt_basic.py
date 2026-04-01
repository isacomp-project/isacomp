#!/usr/bin/env python3
"""Test SMT verification on basic MIPS32 instructions."""

from core.resource_graph import ResourceGraph
from verif.smt.smt_verification import EquivalenceChecker
import subprocess

print("=" * 70)
print("Testing SMT verification on MIPS32 instructions")
print("=" * 70)

# Test 1: MIPS32 ADD self-comparison
print("\n[Test 1] MIPS32 ADD: Comparing graph to itself")
print("-" * 70)

graph_add = ResourceGraph.from_isa_file('isa/mips32/add.isa')
checker = EquivalenceChecker(graph_add, graph_add, isa_file_path='isa/mips32/add.isa')
formula = checker.generate_equivalence_formula()

with open('/tmp/mips32_add_self.smt2', 'w') as f:
    f.write(formula)

result = subprocess.run(
    ["z3", "-smt2", "/tmp/mips32_add_self.smt2"],
    capture_output=True,
    text=True,
    timeout=10
)

error_lines = [l for l in result.stdout.split('\n') if 'error' in l.lower() and 'model is not available' not in l]
print(f"Z3 errors: {len(error_lines)}")
if error_lines:
    print("First 3 errors:")
    for err in error_lines[:3]:
        print(f"  {err}")

if "unsat" in result.stdout.lower():
    print("✓ PASS: ADD graph is equivalent to itself")
    test1_pass = True
elif "sat" in result.stdout.lower():
    print("✗ FAIL: ADD graph not equivalent to itself!")
    test1_pass = False
else:
    print("✗ FAIL: Z3 error or timeout")
    test1_pass = False

# Test 2: MIPS32 LW self-comparison
print("\n[Test 2] MIPS32 LW: Comparing graph to itself")
print("-" * 70)

graph_lw = ResourceGraph.from_isa_file('isa/mips32/lw.isa')
checker = EquivalenceChecker(graph_lw, graph_lw, isa_file_path='isa/mips32/lw.isa')
formula = checker.generate_equivalence_formula()

with open('/tmp/mips32_lw_self.smt2', 'w') as f:
    f.write(formula)

result = subprocess.run(
    ["z3", "-smt2", "/tmp/mips32_lw_self.smt2"],
    capture_output=True,
    text=True,
    timeout=10
)

error_lines = [l for l in result.stdout.split('\n') if 'error' in l.lower() and 'model is not available' not in l]
print(f"Z3 errors: {len(error_lines)}")
if error_lines:
    print("First 3 errors:")
    for err in error_lines[:3]:
        print(f"  {err}")

if "unsat" in result.stdout.lower():
    print("✓ PASS: LW graph is equivalent to itself")
    test2_pass = True
elif "sat" in result.stdout.lower():
    print("✗ FAIL: LW graph not equivalent to itself!")
    test2_pass = False
else:
    print("✗ FAIL: Z3 error or timeout")
    test2_pass = False

# Test 3: MIPS32 SUB self-comparison
print("\n[Test 3] MIPS32 SUB: Comparing graph to itself")
print("-" * 70)

graph_sub = ResourceGraph.from_isa_file('isa/mips32/sub.isa')
checker = EquivalenceChecker(graph_sub, graph_sub, isa_file_path='isa/mips32/sub.isa')
formula = checker.generate_equivalence_formula()

with open('/tmp/mips32_sub_self.smt2', 'w') as f:
    f.write(formula)

result = subprocess.run(
    ["z3", "-smt2", "/tmp/mips32_sub_self.smt2"],
    capture_output=True,
    text=True,
    timeout=10
)

error_lines = [l for l in result.stdout.split('\n') if 'error' in l.lower() and 'model is not available' not in l]
print(f"Z3 errors: {len(error_lines)}")
if error_lines:
    print("First 3 errors:")
    for err in error_lines[:3]:
        print(f"  {err}")

if "unsat" in result.stdout.lower():
    print("✓ PASS: SUB graph is equivalent to itself")
    test3_pass = True
elif "sat" in result.stdout.lower():
    print("✗ FAIL: SUB graph not equivalent to itself!")
    test3_pass = False
else:
    print("✗ FAIL: Z3 error or timeout")
    test3_pass = False

# Summary
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
total_passed = sum([test1_pass, test2_pass, test3_pass])
print(f"Passed: {total_passed}/3")

if total_passed == 3:
    print("\n✓ All MIPS32 basic tests passed!")
else:
    print(f"\n✗ {3 - total_passed} test(s) failed")
