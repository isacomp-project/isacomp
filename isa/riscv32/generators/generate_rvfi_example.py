#!/usr/bin/env python3
"""
Example: Generating RISC-V processor with RVFI for formal verification

This example demonstrates how to:
1. Merge RISC-V instructions
2. Generate processor RTL
3. Generate RVFI wrapper for formal verification
4. Create testbenches and verification configuration

Usage:
    python3 examples/generate_rvfi_example.py
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.graph_merger import merge_instructions
from backends.verilog.rvfi.verilog_rvfi_integration import generate_verilog_with_rvfi
from backends.verilog.rvfi.rvfi_generator import RVFIConfig


def main():
    print("="*70)
    print("ISAComp RVFI Generation Example")
    print("="*70)

    # Step 1: Define which instructions to include
    print("\n[Step 1] Selecting RISC-V instructions to verify...")

    instruction_files = {
        'add': 'isa/riscv32/add.isa',
        'addi': 'isa/riscv32/addi.isa',
        'sub': 'isa/riscv32/sub.isa',
        'and': 'isa/riscv32/and.isa',
        'andi': 'isa/riscv32/andi.isa',
        'or': 'isa/riscv32/or.isa',
        'ori': 'isa/riscv32/ori.isa',
    }

    print(f"  Selected {len(instruction_files)} instructions:")
    for name in instruction_files.keys():
        print(f"    - {name.upper()}")

    # Step 2: Merge instructions into a single processor
    print("\n[Step 2] Merging instructions into processor...")

    merged_graph = merge_instructions(instruction_files)

    print(f"  ✓ Merged {len(instruction_files)} instructions")
    print(f"  Graph has {len(merged_graph.nodes)} nodes, {len(merged_graph.edges)} edges")

    # Step 3: Optimize the merged graph
    print("\n[Step 3] Optimizing processor design...")

    merged_graph.optimize()

    print(f"  ✓ Optimization complete")
    print(f"  Optimized graph: {len(merged_graph.nodes)} nodes, {len(merged_graph.edges)} edges")

    # Step 4: Configure RVFI
    print("\n[Step 4] Configuring RVFI (RISC-V Formal Interface)...")

    rvfi_config = RVFIConfig(
        xlen=32,              # RV32 - 32-bit registers
        nret=1,               # Single instruction retirement per cycle
        ilen=32,              # 32-bit instructions
        enable_mem=True,      # Track memory accesses
        enable_csr=False      # No CSR tracking (yet)
    )

    print(f"  XLEN: {rvfi_config.xlen} bits")
    print(f"  Instructions per cycle: {rvfi_config.nret}")
    print(f"  Memory tracking: {'enabled' if rvfi_config.enable_mem else 'disabled'}")

    # Step 5: Specify which formal checks to generate
    print("\n[Step 5] Configuring formal verification checks...")

    rvfi_checks = [
        'insn_add',
        'insn_addi',
        'insn_sub',
        'insn_and',
        'insn_andi',
        'insn_or',
        'insn_ori',
    ]

    print(f"  Will generate {len(rvfi_checks)} formal verification checks")

    # Step 6: Generate processor with RVFI
    print("\n[Step 6] Generating processor RTL and RVFI wrapper...")

    module_name = "riscv32_alu_rvfi_example"
    output_dir = f"examples/verilog/{module_name}"

    try:
        files = generate_verilog_with_rvfi(
            graph=merged_graph,
            module_name=module_name,
            output_dir=output_dir,
            rvfi_config=rvfi_config,
            rvfi_checks=rvfi_checks
        )

        print(f"\n  ✓ Generation successful!")
        print(f"\n  Generated files in {output_dir}/:")
        print(f"    1. {files['processor'].name} - Base processor RTL")
        print(f"    2. {files['rvfi_wrapper'].name} - RVFI wrapper")
        print(f"    3. {files['rvfi_testbench'].name} - Formal testbench")
        print(f"    4. {files['sby_config'].name} - SymbiYosys config")
        print(f"    5. {files['readme'].name} - Usage instructions")

    except Exception as e:
        print(f"\n  ✗ Generation failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Step 7: Print next steps
    print("\n" + "="*70)
    print("Next Steps for Formal Verification")
    print("="*70)

    print(f"\n1. Install SymbiYosys (if not already installed):")
    print(f"   # Ubuntu/Debian:")
    print(f"   sudo apt-get install yosys z3")
    print(f"   pip3 install symbiyosys")

    print(f"\n2. Clone riscv-formal framework:")
    print(f"   cd {output_dir}")
    print(f"   git clone https://github.com/SymbioticEDA/riscv-formal.git")

    print(f"\n3. Run formal verification:")
    print(f"   cd {output_dir}")
    print(f"   sby -f {module_name}.sby")

    print(f"\n4. View results:")
    print(f"   cat {module_name}/status")
    print(f"   # Should show 'PASS' for each check")

    print(f"\n5. Debug failures (if any):")
    print(f"   gtkwave {module_name}/engine_0/trace.vcd")

    print("\n" + "="*70)
    print("Additional Resources")
    print("="*70)

    print(f"\n- RVFI Documentation: RVFI_GUIDE.md")
    print(f"- riscv-formal: https://github.com/SymbioticEDA/riscv-formal")
    print(f"- SymbiYosys: https://symbiyosys.readthedocs.io/")

    print("\n" + "="*70)
    print("Example completed successfully!")
    print("="*70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
