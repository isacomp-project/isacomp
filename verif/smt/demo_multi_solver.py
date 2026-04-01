#!/usr/bin/env python3
"""
Demonstration of multi-solver SMT verification.

Shows how the multi-solver approach:
- Detects available solvers
- Tries them in order
- Falls back on timeout/failure
- Reports which solver succeeded
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from core.resource_graph import ResourceGraph
from verif.smt.smt_verification import EquivalenceChecker
from smt_multi_solver import MultiSolverVerifier


def main():
    print("\n" + "="*70)
    print("  MULTI-SOLVER SMT VERIFICATION DEMO")
    print("="*70)

    # Initialize multi-solver
    verifier = MultiSolverVerifier(timeout_per_solver=30)

    print(f"\nAvailable solvers: {', '.join(verifier.available_solvers)}")
    if not verifier.available_solvers:
        print("\n⚠ No solvers available!")
        print("Please install z3: pip3 install z3-solver")
        return 1

    print("\n" + "-"*70)
    print("Test 1: Simple self-equivalence check (should be UNSAT)")
    print("-"*70)

    # Load a simple MIPS32 instruction
    print("\nLoading MIPS32 ADD instruction...")
    graph_add = ResourceGraph.from_isa_file('isa/mips32/add.isa')

    print("Generating SMT formula (comparing graph to itself)...")
    checker = EquivalenceChecker(graph_add, graph_add, isa_file_path='isa/mips32/add.isa')
    formula = checker.generate_equivalence_formula()

    print(f"Formula size: {len(formula)} bytes")
    print("\nVerifying with multi-solver approach:")

    # Verify using multi-solver
    is_equiv, details, solver_used = verifier.verify(formula)

    print("\n" + "="*70)
    print("  RESULT")
    print("="*70)

    if is_equiv:
        print(f"\n✓ PASS: Graphs are equivalent (no counterexample found)")
        print(f"  Solver: {solver_used}")
    else:
        print(f"\n✗ FAIL: Graphs are NOT equivalent")
        print(f"  Solver: {solver_used}")
        print(f"\nDetails:\n{details[:500]}")  # First 500 chars

    # Performance stats
    print(verifier.get_stats_summary())

    print("\n" + "="*70)
    print("Test 2: Verify different instruction (ADDI)")
    print("="*70)

    print("\nLoading MIPS32 ADDI instruction...")
    graph_addi = ResourceGraph.from_isa_file('isa/mips32/addi.isa')

    print("Generating SMT formula (comparing ADDI to itself)...")
    checker2 = EquivalenceChecker(graph_addi, graph_addi, isa_file_path='isa/mips32/addi.isa')
    formula2 = checker2.generate_equivalence_formula()

    print(f"Formula size: {len(formula2)} bytes")
    print("\nVerifying:")

    is_equiv2, details2, solver_used2 = verifier.verify(formula2)

    print("\n" + "="*70)
    print("  RESULT")
    print("="*70)

    if is_equiv2:
        print(f"\n✓ PASS: Graphs are equivalent")
        print(f"  Solver: {solver_used2}")
    else:
        print(f"\n✗ FAIL: Graphs are NOT equivalent")
        print(f"  Solver: {solver_used2}")

    # Final stats
    print(verifier.get_stats_summary())

    print("\n" + "="*70)
    print("Demo complete!")
    print("="*70)
    print("\nKey features demonstrated:")
    print("  ✓ Automatic solver detection")
    print("  ✓ Fallback on failure/timeout")
    print("  ✓ Performance tracking")
    print("  ✓ Solver reporting")
    print()

    return 0


if __name__ == '__main__':
    sys.exit(main())
