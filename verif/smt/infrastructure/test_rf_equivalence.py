#!/usr/bin/env python3
"""Test that verification checks ALL architectural state (pc and rf)."""

from core.resource_graph import ResourceGraph
from verif.smt.smt_verification import EquivalenceChecker
import copy

print("=" * 70)
print("TEST: Verify that register file writes are checked")
print("=" * 70)

# Create original graph
print("\n1. Creating original graph (r1 + r2)...")
graph1 = ResourceGraph.from_isa_file('isa/riscv32/add.isa')

# Create modified graph - change addition to subtraction
print("2. Creating modified graph (r1 - r2 instead of r1 + r2)...")
graph2 = copy.deepcopy(graph1)

# Find the (r1 + r2) operation and change + to -
modified = False
for node_id, node in graph2.nodes.items():
    if node.data.get('type') == 'operation':
        expr = node.data.get('expression', {})
        if expr.get('operator') == '+' and '(r1 + r2)' in node_id:
            print(f"   Found addition in node: {node_id}")
            print(f"   Changing operator from + to -")
            expr['operator'] = '-'
            modified = True
            break

if not modified:
    print("   ERROR: Could not find (r1 + r2) operation!")
    exit(1)

print("\n3. Comparing graphs (no ISA assumptions)...")
checker = EquivalenceChecker(graph1, graph2, isa_file_path=None)
is_equiv, details = checker.check_equivalence()

print("\n" + "=" * 70)
print("RESULT")
print("=" * 70)
print(f"Graphs equivalent: {is_equiv}")

# Check what was compared
if "rf" in details and "pc" in details:
    print("\n✓ Both RF and PC were checked in equivalence")
else:
    print("\n✗ WARNING: Not all state was checked")

# Check the result
if "sat" in details.lower() and "unsat" not in details.lower():
    print("\n✓ CORRECT: Z3 returned SAT (found counterexample)")
    print("  Graph1: rf[rd] = r1 + r2")
    print("  Graph2: rf[rd] = r1 - r2")
    print("  These produce different register file outputs")
elif "unsat" in details.lower():
    print("\n✗ WRONG: Z3 returned UNSAT")
    print("  We changed + to -, outputs SHOULD differ!")

print("\n" + "=" * 70)
print(f"EXPECTED: is_equiv = False (addition ≠ subtraction)")
print(f"ACTUAL:   is_equiv = {is_equiv}")

if not is_equiv:
    print("\n✓ TEST PASSED: Register file writes are checked!")
else:
    print("\n✗ TEST FAILED: Should detect different RF outputs!")
print("=" * 70)
