#!/usr/bin/env python3
"""Comprehensive SMT verification test for MIPS32 instructions."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from core.resource_graph import ResourceGraph
from verif.smt.smt_verification import EquivalenceChecker
import subprocess

print("=" * 70)
print("Comprehensive MIPS32 SMT Verification Test")
print("=" * 70)

# Find all MIPS32 ISA files
mips32_files = []
for f in os.listdir('isa/mips32'):
    if f.endswith('.isa'):
        mips32_files.append(f'isa/mips32/{f}')

mips32_files.sort()
print(f"\nFound {len(mips32_files)} MIPS32 ISA files")

passed = []
failed = []
errors = []

for isa_file in mips32_files:
    instr_name = os.path.basename(isa_file).replace('.isa', '')
    print(f"\n[{instr_name.upper()}] Testing self-equivalence...")

    try:
        # Load graph
        graph = ResourceGraph.from_isa_file(isa_file)

        # Create checker
        checker = EquivalenceChecker(graph, graph, isa_file_path=isa_file)
        formula = checker.generate_equivalence_formula()

        # Run Z3
        smt_file = f'/tmp/mips32_{instr_name}_self.smt2'
        with open(smt_file, 'w') as f:
            f.write(formula)

        result = subprocess.run(
            ["z3", "-smt2", smt_file],
            capture_output=True,
            text=True,
            timeout=15
        )

        # Check for errors (excluding "model is not available")
        error_lines = [l for l in result.stdout.split('\n')
                      if 'error' in l.lower() and 'model is not available' not in l]

        if error_lines:
            print(f"  ✗ FAIL: {len(error_lines)} SMT errors")
            print(f"    First error: {error_lines[0][:60]}...")
            failed.append(instr_name)
        elif "unsat" in result.stdout.lower():
            print(f"  ✓ PASS: Self-equivalence verified")
            passed.append(instr_name)
        elif "sat" in result.stdout.lower():
            print(f"  ✗ FAIL: Not equivalent to itself!")
            failed.append(instr_name)
        else:
            print(f"  ✗ ERROR: Unexpected Z3 output")
            errors.append(instr_name)

    except subprocess.TimeoutExpired:
        print(f"  ✗ TIMEOUT: Z3 took > 15s")
        errors.append(instr_name)
    except Exception as e:
        print(f"  ✗ ERROR: {str(e)[:50]}...")
        errors.append(instr_name)

# Summary
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"Total instructions: {len(mips32_files)}")
print(f"✓ Passed: {len(passed)}")
print(f"✗ Failed: {len(failed)}")
print(f"⚠ Errors: {len(errors)}")

if failed:
    print(f"\nFailed instructions: {', '.join(failed)}")
if errors:
    print(f"Error instructions: {', '.join(errors)}")

if len(passed) == len(mips32_files):
    print("\n✓ All MIPS32 instructions verified successfully!")
else:
    print(f"\n✗ {len(failed) + len(errors)} instruction(s) had issues")
