#!/usr/bin/env python3
"""
Roundtrip test for ISA -> RG -> Verilog -> RG -> Verilog -> RG -> Verilog

This tests the complete roundtrip:
1. ISA files -> RG (done by generate_riscv32i_complete.py)
2. RG -> Verilog (original generated file: riscv32i_complete.v)
3. Verilog -> RG (parse the generated Verilog)
4. RG -> Verilog (regenerate Verilog from parsed RG)
5. Verilog -> RG (parse the regenerated Verilog)
6. RG -> Verilog (regenerate Verilog from second parsed RG)
7. Compare outputs at each stage
"""
import sys
import os
from frontends.verilog import parse_verilog_file
from backends.verilog import generate_verilog

def save_verilog(verilog_code, filename):
    """Save Verilog code to file"""
    with open(filename, 'w') as f:
        f.write(verilog_code)
    print(f"  Saved to: {filename}")

def test_roundtrip():
    """Test the complete roundtrip"""

    print("=" * 80)
    print("ROUNDTRIP TEST: ISA -> RG -> Verilog -> RG -> Verilog -> RG -> Verilog")
    print("=" * 80)

    # Step 1: Start with the ISA-generated Verilog
    original_verilog = "examples/verilog/riscv32i_complete/riscv32i_complete.v"
    if not os.path.exists(original_verilog):
        print(f"\nERROR: {original_verilog} not found!")
        print("Please run: python3 isa/riscv32/generators/generate_riscv32i_complete.py")
        return False

    print(f"\nStep 1: Starting with ISA-generated Verilog: {original_verilog}")

    # Step 2: Parse original Verilog to RG
    print("\nStep 2: Parsing Verilog -> RG (first parse)")
    try:
        graph1 = parse_verilog_file(original_verilog, top_module='riscv32i_complete')
        print(f"  Successfully parsed! Graph has {len(graph1.nodes)} nodes, {len(graph1.edges)} edges")
    except Exception as e:
        print(f"  ERROR during first parse: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Step 3: Generate Verilog from first RG
    print("\nStep 3: Generating Verilog from first RG")
    try:
        verilog1 = generate_verilog(graph1, module_name='riscv32i_complete_rt1')
        save_verilog(verilog1, 'riscv32i_complete_rt1.v')
        print(f"  Generated {len(verilog1)} characters of Verilog")
    except Exception as e:
        print(f"  ERROR during first generation: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Step 4: Verify first regenerated Verilog compiles with Verilator
    print("\nStep 4: Verifying first regenerated Verilog compiles with Verilator")
    import subprocess
    result = subprocess.run(
        ['verilator', '--lint-only', '-Wall', 'riscv32i_complete_rt1.v'],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print(f"  WARNING: Verilator found issues:")
        print(result.stderr)
    else:
        print(f"  SUCCESS: First regenerated Verilog compiles cleanly!")

    # Step 5: Parse regenerated Verilog to RG
    print("\nStep 5: Parsing regenerated Verilog -> RG (second parse)")
    try:
        graph2 = parse_verilog_file('riscv32i_complete_rt1.v', top_module='riscv32i_complete_rt1')
        print(f"  Successfully parsed! Graph has {len(graph2.nodes)} nodes, {len(graph2.edges)} edges")
    except Exception as e:
        print(f"  ERROR during second parse: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Step 6: Generate Verilog from second RG
    print("\nStep 6: Generating Verilog from second RG")
    try:
        verilog2 = generate_verilog(graph2, module_name='riscv32i_complete_rt2')
        save_verilog(verilog2, 'riscv32i_complete_rt2.v')
        print(f"  Generated {len(verilog2)} characters of Verilog")
    except Exception as e:
        print(f"  ERROR during second generation: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Step 7: Verify second regenerated Verilog compiles with Verilator
    print("\nStep 7: Verifying second regenerated Verilog compiles with Verilator")
    result = subprocess.run(
        ['verilator', '--lint-only', '-Wall', 'riscv32i_complete_rt2.v'],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print(f"  WARNING: Verilator found issues:")
        print(result.stderr)
    else:
        print(f"  SUCCESS: Second regenerated Verilog compiles cleanly!")

    # Step 8: Compare graph sizes
    print("\n" + "=" * 80)
    print("COMPARISON")
    print("=" * 80)
    print(f"\nGraph 1 (from ISA-generated Verilog): {len(graph1.nodes)} nodes, {len(graph1.edges)} edges")
    print(f"Graph 2 (from regenerated Verilog):   {len(graph2.nodes)} nodes, {len(graph2.edges)} edges")
    print(f"\nVerilog 1 size: {len(verilog1)} characters")
    print(f"Verilog 2 size: {len(verilog2)} characters")

    # Step 9: Check for stability (convergence)
    print("\n" + "=" * 80)
    print("STABILITY CHECK")
    print("=" * 80)

    if len(verilog1) == len(verilog2) and verilog1 == verilog2:
        print("\n✓ SUCCESS: Roundtrip has CONVERGED!")
        print("  The regenerated Verilog is identical after one iteration.")
        return True
    else:
        print("\n✗ WARNING: Roundtrip has NOT converged")
        print("  The Verilog output is still changing between iterations.")
        print("  This may indicate:")
        print("    - Information loss in the parser")
        print("    - Non-determinism in the generator")
        print("    - Semantic-preserving transformations")

        # Check if at least the graphs are similar
        if len(graph1.nodes) == len(graph2.nodes) and len(graph1.edges) == len(graph2.edges):
            print("\n  However, the RG sizes are the same, which is a good sign!")
            print("  The differences may be cosmetic (naming, ordering, etc.)")

        return False

if __name__ == '__main__':
    success = test_roundtrip()
    sys.exit(0 if success else 1)
