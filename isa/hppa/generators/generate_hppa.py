#!/usr/bin/env python3
"""
Generate HPPA (PA-RISC) processor from ISA definitions.

This generates a single-cycle implementation of the HP Precision Architecture (PA-RISC)
ISA. The HPPA architecture features:
- 32 general-purpose 32-bit registers (GR0 always reads as 0)
- Fixed 32-bit instruction length
- Load/store architecture
- 14-bit displacement for memory operations
- Compare-and-branch instructions

Supports Verilog backend.
"""
import sys
import os
import argparse

# Add parent directories to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core.graph_merger import merge_instructions
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec

# HPPA instruction set - comprehensive implementation
# Note: Double-precision FP instructions require 64-bit memory access which has a generator bug
# Those are listed separately for documentation but excluded from generation

# Instructions that work with 32-bit memory (testable)
INSTRUCTIONS = [
    # Arithmetic (6)
    'add', 'sub', 'addi', 'addc', 'subb', 'addil',

    # Arithmetic - logical (no carry update)
    'addl', 'subl',

    # Overflow-trapping arithmetic (6)
    'addo', 'subo', 'sh1addo', 'sh2addo', 'sh3addo', 'addco',

    # Trap-on-condition arithmetic
    'addit', 'subit', 'addito', 'subito', 'subbo',

    # Logical (5)
    'and', 'or', 'xor', 'andcm', 'copy',

    # Shift-and-add (6)
    'sh1add', 'sh2add', 'sh3add',
    'sh1addl', 'sh2addl', 'sh3addl',

    # Immediates (6)
    'ldo', 'ldi', 'subi', 'depwi', 'ldil', 'addi_tc',

    # Shifts/Extract/Deposit (10 + 3 fixed-pos DEPW variants)
    'extru', 'extrs', 'shd', 'vshd', 'zvdep',
    'dep', 'vdep', 'vextrs', 'vextru', 'zvdepi',
    'zdepw', 'depw', 'zdepwi',

    # Control registers (1)
    'mtsar',

    # Loads (7 - long displacement 14-bit forms)
    'ldw', 'ldh', 'ldb', 'ldwx', 'ldcw',
    'ldbx', 'ldhx',

    # Loads (1 - long displacement 14-bit with modify, opcode 0x13)
    'ldw_mb',

    # Loads (3 - short displacement IM5 forms, opcode 0x03)
    'ldw_short', 'ldh_short', 'ldb_short',

    # Loads (8 - short displacement IM5 with modify, opcode 0x03)
    'ldw_short_ma', 'ldw_short_mb',
    'ldh_short_ma', 'ldh_short_mb',
    'ldb_short_ma', 'ldb_short_mb',

    # Stores (6 - long displacement 14-bit forms)
    'stw', 'sth', 'stb', 'stwx',
    'stbx', 'sthx',

    # Stores (1 - long displacement 14-bit with modify, opcode 0x1B)
    'stw_ma',

    # Stores (3 - short displacement IM5 forms, opcode 0x03)
    'stw_short', 'sth_short', 'stb_short',

    # Stores (short displacement IM5 with modify, opcode 0x03)
    'stw_short_ma', 'stw_short_mb',
    'stb_short_ma',
    'sth_short_ma',

    # Branches - unconditional (4)
    'b', 'bl', 'bv', 'blr',

    # Branches - external (3)
    'be', 'ble', 'gate',

    # Branches - COMBT signed (true conditions: =, <, <=)
    'cmpb_eq', 'cmpb_lt', 'cmpb_le',

    # Branches - COMBT unsigned/special (<<, <<=, OD)
    'cmpb_ltu', 'cmpb_leu', 'cmpb_od',

    # Branches - COMBF signed (false conditions: <>, >=, >)
    'cmpb_ne', 'cmpb_ge', 'cmpb_gt',

    # Branches - COMBF unsigned/special (>>=, >>, EV)
    'cmpb_geu', 'cmpb_gtu', 'cmpb_ev',

    # COMBF duplicates (opcode 0x22) - same conditions as cmpb_ne/ge/geu/gtu above
    # Kept with identical logic to maintain graph structure stability
    'combf_eq', 'combf_lt', 'combf_ltu',
    'combf_ne', 'combf_ge', 'combf_geu',

    # COMB aliases removed - they conflict with cmpb_* encodings (same opcode 0x20)

    # Compare Immediate and Branch - COMIBT true (opcode 0x21)
    'cmpib_eq', 'cmpib_lt', 'cmpib_le',
    'cmpib_ltu', 'cmpib_leu', 'cmpib_od',

    # Compare Immediate and Branch - COMIBF false (opcode 0x23)
    # NE=COMIBF-EQ, GE=COMIBF-LT, GT=COMIBF-LE, GEU=COMIBF-LTU, GTU=COMIBF-LEU, EV=COMIBF-OD
    'cmpibf_eq', 'cmpibf_lt', 'cmpibf_le',
    'cmpibf_ltu', 'cmpibf_leu', 'cmpibf_ne', 'cmpib_ev',

    # COMCLR - compare and clear (10)
    'comclr_eq', 'comclr_ne', 'comclr_lt', 'comclr_le',
    'comclr_gt', 'comclr_ge', 'comclr_ltu', 'comclr_leu',
    'comclr_geu', 'comclr_gtu',

    # COMICLR - compare immediate and clear (10+1)
    'comiclr_tr', 'comiclr_eq', 'comiclr_ne',
    'comiclr_lt', 'comiclr_ge', 'comiclr_le', 'comiclr_gt',
    'comiclr_ltu', 'comiclr_geu', 'comiclr_leu', 'comiclr_gtu',

    # Add and Branch (10)
    'addb_eq', 'addb_ne', 'addb_tr',
    'addib_eq', 'addib_ne', 'addib_gt', 'addib_ge', 'addib_lt', 'addib_le', 'addib_tr', 'addib_uv',

    # Move and Branch (10)
    'movb_eq', 'movb_ne', 'movb_lt', 'movb_ge', 'movb_tr',
    'movib_eq', 'movib_ne', 'movib_tr',

    # Branch on Bit - fixed position (2) + SAR-based position (2)
    'bb_set', 'bb_clear',
    'bb_sar_set', 'bb_sar_clear',

    # Floating-point arithmetic - single precision (4)
    'fadd_sgl', 'fsub_sgl', 'fmpy_sgl', 'fdiv_sgl',

    # Floating-point load/store - single precision (4)
    'fldw', 'fldwr', 'fstw', 'fstwr',

    # Floating-point compare - single precision (1)
    'fcmp_sgl',

    # Floating-point convert - single precision (4)
    'fcnvxf_w_sgl', 'fcnvfx_sgl_w', 'fcnvfxt_sgl_w',

    # Floating-point utility - single precision (5)
    'fcpy_sgl', 'fabs_sgl', 'fneg_sgl', 'fsqrt_sgl', 'frnd_sgl',

    # Floating-point arithmetic - double precision (4)
    'fadd_dbl', 'fsub_dbl', 'fmpy_dbl', 'fdiv_dbl',

    # Floating-point compare - double precision (1)
    'fcmp_dbl',

    # Floating-point convert - double precision (4)
    'fcnvff_sgl_dbl', 'fcnvff_dbl_sgl',
    'fcnvxf_w_dbl', 'fcnvfx_dbl_w',

    # Floating-point utility - double precision (5)
    'fcpy_dbl', 'fabs_dbl', 'fneg_dbl', 'fsqrt_dbl', 'frnd_dbl',

    # Floating-point load/store - double precision (2)
    'fldd', 'fstd',

    # Floating-point test (1)
    'ftest',

    # Fixed-point multiply (uses FP regs) (1)
    'xmpyu',

    # System instructions (12)
    'break', 'rfi', 'rfir', 'mfctl', 'mtctl', 'ssm', 'rsm', 'mtsm',
    'mfsp', 'mtsp', 'lpa', 'prober', 'probew',

    # Synchronization (2)
    'sync', 'syncdma',

    # Division support (2)
    'ds', 'uaddcm',

    # Decimal correction (2)
    'dcor', 'idcor',

    # Cache operations (10)
    'fdc', 'fic', 'pdc',
    'fice', 'fice_m', 'fdce', 'fdce_m',
    'fdc_m', 'fic_m',

    # TLB operations (8)
    'idtlba', 'idtlbp', 'iitlba', 'iitlbp', 'pdtlb', 'pitlb',
    'pdtlbe', 'pitlbe',

    # Special/Coprocessor operations (5)
    'copr', 'spop0', 'spop1', 'spop2', 'spop3',

    # Diagnostic (3)
    'diag', 'diag_btlb_insert', 'diag_btlb_purge_all',

    # Move from instruction address (1)
    'mfia',

    # Misc (1)
    'nop',
]

# Test list for HPPA
HPPA_TESTS = [
    "add", "sub", "and", "or", "xor",
    "sh1add", "sh2add", "sh3add",
    "ldo", "addi",
    "ldw", "stw",
    "b", "bl", "cmpb_eq", "cmpb_ne",
]


def apply_memory_transform(merged_graph):
    """Apply port width setting for 64-bit word-addressed unified memory (for double-precision FP)."""
    umem_node = merged_graph.nodes.get('umem')
    if umem_node:
        access_widths = umem_node.data.get('access_widths', [64])
        max_width = max(access_widths) if access_widths else 64
        print(f"  umem access widths: {access_widths}, max: {max_width}")

        # Apply set_port_width transformation to create byte selection mux nodes
        transform = MemoryAccessTransform(merged_graph)
        spec = MemoryAccessTransformSpec(
            memory='umem',
            strategy='set_port_width',
            current_width=max_width,
            target_width=64,  # 64-bit memory for double-precision FP
            direction='forward',
            endianness='big'
        )
        result = transform.apply_transformation(spec)
        if result.get('transformed'):
            print(f"  Transformed: added {len(result.get('nodes_added', []))} byte mux nodes")
        else:
            print(f"  Skipped: {result.get('reason', 'unknown')}")


def generate_verilog(merged_graph, module_name, output_dir):
    """Generate Verilog output."""
    from backends.verilog import generate_verilog_with_testbench
    from pathlib import Path

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    testbench_config = {
        'timeout_cycles': 10000,
    }

    files = generate_verilog_with_testbench(
        merged_graph,
        module_name=module_name,
        output_dir=output_dir,
        testbench_config=testbench_config
    )

    return files


def main():
    parser = argparse.ArgumentParser(
        description='Generate HPPA (PA-RISC) processor from ISA definitions'
    )
    parser.add_argument(
        '--output-dir', '-o',
        default='examples/verilog/hppa',
        help='Output directory (default: examples/verilog/hppa)'
    )
    parser.add_argument(
        '--module-name', '-m',
        default='hppa',
        help='Module name (default: hppa)'
    )
    args = parser.parse_args()

    module_name = args.module_name
    output_dir = args.output_dir

    print("=" * 70)
    print("HPPA (PA-RISC) Processor Generator")
    print("=" * 70)
    print(f"\nGenerating HPPA processor with {len(INSTRUCTIONS)} instructions...")
    print(f"Instructions: {', '.join(INSTRUCTIONS)}")

    # Step 1: Parse and merge ISA files
    print("\n" + "=" * 70)
    print("Step 1: Parsing and merging ISA files...")
    print("=" * 70)

    # Build paths to ISA files
    isa_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    isa_files = {instr: os.path.join(isa_dir, f"{instr}.isa") for instr in INSTRUCTIONS}

    try:
        merged_graph = merge_instructions(isa_files)
        print(f"  Successfully merged {len(INSTRUCTIONS)} instructions")
        print(f"  Merged graph has {len(merged_graph.nodes)} nodes and {len(merged_graph.edges)} edges")
    except Exception as e:
        print(f"  Error merging instructions: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Step 2: Apply memory transformations
    print("\n" + "=" * 70)
    print("Step 2: Applying memory port width transformation...")
    print("=" * 70)
    apply_memory_transform(merged_graph)

    # Step 3: Generate RTL
    print("\n" + "=" * 70)
    print("Step 3: Generating Verilog RTL and testbench...")
    print("=" * 70)
    print(f"  Output directory: {output_dir}")

    try:
        files = generate_verilog(merged_graph, module_name, output_dir)

        print(f"\n  Generated files:")
        for key, path in files.items():
            if hasattr(path, 'stat'):
                file_size = path.stat().st_size if path.exists() else 0
                print(f"    {key.upper()}: {path} ({file_size:,} bytes)")
            else:
                print(f"    {key.upper()}: {path}")

    except Exception as e:
        print(f"  Error generating Verilog: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"  Successfully generated HPPA processor")
    print(f"  {len(INSTRUCTIONS)} instructions implemented")
    print(f"  {len(merged_graph.nodes)} nodes in merged graph")
    print(f"  {len(merged_graph.edges)} edges in merged graph")
    print(f"  Output: {output_dir}/")

    print("\n" + "=" * 70)
    print("Done!")
    print("=" * 70)


if __name__ == "__main__":
    main()
