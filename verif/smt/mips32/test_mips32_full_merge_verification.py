#!/usr/bin/env python3
"""
Comprehensive MIPS32 Full Merge Verification

Merges all 30 MIPS32 instructions into a single unified graph and verifies
that each instruction preserves its semantics in the merged graph.

This is the ultimate test of the SMT verification infrastructure:
- Creates a realistic merged processor with all 30 instructions
- Verifies each instruction individually against its standalone version
- Proves that instruction merging preserves semantics for the entire ISA
"""

import os
import subprocess
from core.resource_graph import ResourceGraph
from core.graph_merger import merge_instructions
from verif.smt.smt_verification import EquivalenceChecker

print("=" * 70)
print("MIPS32 FULL MERGE VERIFICATION")
print("=" * 70)
print()

# Step 1: Get all MIPS32 ISA files
print("[Step 1] Discovering MIPS32 instructions...")
print("-" * 70)

mips32_files = {}
for f in sorted(os.listdir('isa/mips32')):
    if f.endswith('.isa'):
        instr_name = f.replace('.isa', '')
        mips32_files[instr_name] = f'isa/mips32/{f}'

print(f"Found {len(mips32_files)} MIPS32 instructions:")
for i, name in enumerate(sorted(mips32_files.keys()), 1):
    print(f"  {i:2d}. {name}")

# Step 2: Merge all instructions
print(f"\n[Step 2] Merging all {len(mips32_files)} instructions...")
print("-" * 70)

try:
    merged_graph = merge_instructions(mips32_files)
    print(f"\n✓ Successfully merged all instructions!")
    print(f"  Merged graph: {len(merged_graph.nodes)} nodes, {len(merged_graph.edges)} edges")

    # Save merged graph for inspection
    merged_graph.save_to_file('mips32_full_merged.rgraph')
    print(f"  Saved to: mips32_full_merged.rgraph")

except Exception as e:
    print(f"\n✗ ERROR during merging: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

# Step 3: Load standalone graphs for comparison
print(f"\n[Step 3] Loading standalone instruction graphs...")
print("-" * 70)

standalone_graphs = {}
for instr_name, isa_file in mips32_files.items():
    try:
        standalone_graphs[instr_name] = ResourceGraph.from_isa_file(isa_file)
    except Exception as e:
        print(f"✗ Failed to load {instr_name}: {e}")

print(f"✓ Loaded {len(standalone_graphs)} standalone graphs")

# Step 4: Verify each instruction in merged graph
print(f"\n[Step 4] Verifying each instruction in merged graph...")
print("-" * 70)

passed = []
failed = []
errors = []
timeout_list = []

for instr_name in sorted(mips32_files.keys()):
    isa_file = mips32_files[instr_name]
    print(f"\n[{instr_name.upper()}]", end=" ")

    if instr_name not in standalone_graphs:
        print("✗ SKIP (standalone graph not loaded)")
        errors.append(instr_name)
        continue

    try:
        # Create equivalence checker
        standalone = standalone_graphs[instr_name]
        checker = EquivalenceChecker(standalone, merged_graph, isa_file_path=isa_file)

        # Generate SMT formula
        formula = checker.generate_equivalence_formula()

        # Save formula for debugging if needed
        smt_file = f'/tmp/mips32_full_merge_{instr_name}.smt2'
        with open(smt_file, 'w') as f:
            f.write(formula)

        # Run Z3
        result = subprocess.run(
            ['z3', '-smt2', smt_file],
            capture_output=True,
            text=True,
            timeout=30
        )

        # Check for errors
        error_lines = [l for l in result.stdout.split('\n')
                      if 'error' in l.lower() and 'model' not in l.lower()]

        if error_lines:
            print(f"✗ FAIL ({len(error_lines)} SMT errors)")
            print(f"  First error: {error_lines[0][:60]}...")
            failed.append(instr_name)
        elif 'unsat' in result.stdout.lower():
            print("✓ PASS")
            passed.append(instr_name)
        elif 'sat' in result.stdout.lower():
            print("✗ FAIL (not equivalent)")
            failed.append(instr_name)
        else:
            print("✗ ERROR (unexpected Z3 output)")
            errors.append(instr_name)

    except subprocess.TimeoutExpired:
        print("✗ TIMEOUT (>30s)")
        timeout_list.append(instr_name)
    except Exception as e:
        print(f"✗ ERROR: {str(e)[:50]}...")
        errors.append(instr_name)

# Summary
print("\n" + "=" * 70)
print("VERIFICATION SUMMARY")
print("=" * 70)

total = len(mips32_files)
print(f"\nTotal instructions: {total}")
print(f"✓ Passed:   {len(passed):2d} ({len(passed)*100//total:3d}%)")
print(f"✗ Failed:   {len(failed):2d} ({len(failed)*100//total:3d}%)")
print(f"⏱ Timeout:  {len(timeout_list):2d} ({len(timeout_list)*100//total:3d}%)")
print(f"⚠ Errors:   {len(errors):2d} ({len(errors)*100//total:3d}%)")

if passed:
    print(f"\nPassed instructions ({len(passed)}):")
    for i, name in enumerate(passed, 1):
        print(f"  {name}", end="")
        if i % 6 == 0:
            print()
    if len(passed) % 6 != 0:
        print()

if failed:
    print(f"\nFailed instructions ({len(failed)}):")
    for name in failed:
        print(f"  - {name}")

if timeout_list:
    print(f"\nTimeout instructions ({len(timeout_list)}):")
    for name in timeout_list:
        print(f"  - {name}")

if errors:
    print(f"\nError instructions ({len(errors)}):")
    for name in errors:
        print(f"  - {name}")

# Final verdict
print("\n" + "=" * 70)
if len(passed) == total:
    print("✓✓✓ SUCCESS! ALL INSTRUCTIONS VERIFIED IN MERGED GRAPH! ✓✓✓")
    print("=" * 70)
    print()
    print("This proves that:")
    print("  1. Instruction merging preserves semantics for all 30 MIPS32 instructions")
    print("  2. The SMT verification infrastructure correctly handles merged graphs")
    print("  3. The merged graph is functionally equivalent to 30 standalone processors")
    print()
    print("The merged graph represents a complete MIPS32 processor that can execute")
    print("all 30 instructions while sharing common infrastructure (RF, memory, etc.)")
    exit(0)
elif len(passed) >= total * 0.8:
    print("⚠ PARTIAL SUCCESS: Most instructions verified")
    print("=" * 70)
    print(f"\n{len(passed)}/{total} instructions verified successfully")
    print("Some instructions may need further investigation")
    exit(1)
else:
    print("✗ VERIFICATION FAILED")
    print("=" * 70)
    print(f"\nOnly {len(passed)}/{total} instructions verified")
    print("Significant issues detected - investigation needed")
    exit(1)
