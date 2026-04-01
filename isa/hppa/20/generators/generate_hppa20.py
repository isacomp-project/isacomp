#!/usr/bin/env python3
"""
Generate HPPA PA-RISC 2.0 (64-bit) processor from ISA definitions.

This generates a single-cycle implementation of the HP Precision Architecture
PA-RISC 2.0 ISA. PA-RISC 2.0 extends PA-RISC 1.1 with:
- 64-bit general-purpose registers (GR0 always reads as 0)
- 64-bit virtual addressing (with PSW.W wide mode)
- 64-bit control registers and PSW
- New 64-bit extract/deposit/shift instructions (EXTRD, DEPD, SHRPD)
- New 64-bit load/store (LDD, STD)
- MAX-2 multimedia SIMD instructions (HADD, HSUB, HAVG, PERMH, MIXW, MIXH)
- Fused multiply-add floating-point (FMPYFADD, FMPYNFADD)
- Branch prediction hints (POPBTS)
- 6-bit SAR for 64-bit shift operations
- Fixed 32-bit instruction length (unchanged from 1.1)
- Load/store architecture with delay slots (unchanged)

Supports Verilog backend.
"""
import sys
import os
import argparse

# Add parent directories to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../..')))

from core.graph_merger import merge_instructions
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec

# PA-RISC 2.0 instruction set - comprehensive 64-bit implementation
# All instructions operate on 64-bit registers in wide mode (PSW.W=1)

INSTRUCTIONS = [
    # =====================================================================
    # Arithmetic (64-bit) - carry/overflow on full 64-bit values
    # =====================================================================
    'add', 'sub', 'addi', 'addc', 'subb', 'addil',

    # Arithmetic - logical (no carry update)
    'addl',

    # Overflow-trapping arithmetic
    'addo', 'subo', 'sh1addo', 'sh2addo', 'sh3addo', 'addco',

    # Trap-on-condition arithmetic
    'subit', 'subito', 'subbo',

    # =====================================================================
    # Logical (64-bit)
    # =====================================================================
    'and', 'or', 'xor', 'andcm', 'copy',

    # =====================================================================
    # Shift-and-add (64-bit)
    # =====================================================================
    'sh1add', 'sh2add', 'sh3add',
    'sh1addl', 'sh2addl', 'sh3addl',

    # =====================================================================
    # Immediates (64-bit sign-extended)
    # =====================================================================
    'ldo', 'ldi', 'subi', 'depwi', 'ldil', 'addi_tc',

    # =====================================================================
    # Shifts/Extract/Deposit - 32-bit field ops (PA-RISC 1.1 compat)
    # =====================================================================
    'extru', 'extrs', 'shd', 'vshd', 'zvdep',
    'dep', 'vdep', 'vextrs', 'vextru', 'zvdepi',
    'zdepw', 'depw', 'zdepwi',

    # =====================================================================
    # NEW PA-RISC 2.0: 64-bit Extract/Deposit/Shift
    # =====================================================================
    'extrd_u', 'extrd_s',       # Extract Doubleword Unsigned/Signed
    'depd', 'depdi',            # Deposit Doubleword / Immediate
    'depd_z', 'depdi_z',        # Deposit Doubleword Zero-fill
    'zvdepd', 'zvdepdi',        # Zero Variable Deposit Doubleword (SAR-based)
    'vdepd', 'vdepdi',          # Variable Deposit Doubleword (SAR-based)
    'shrpd', 'shrpd_v',         # Shift Right Pair Doubleword (fixed/variable)

    # =====================================================================
    # Control registers (6-bit SAR in PA2.0)
    # =====================================================================
    'mtsar', 'mtsarcm',

    # =====================================================================
    # Loads - long displacement 14-bit forms
    # =====================================================================
    'ldw', 'ldh', 'ldb', 'ldwx', 'ldcw', 'ldcd',
    'ldbx', 'ldhx',

    # Load with modify (long displacement)
    'ldw_mb',

    # Loads - short displacement IM5 forms
    'ldw_short', 'ldh_short', 'ldb_short',

    # Loads - short displacement with modify
    'ldw_short_ma', 'ldw_short_mb',
    'ldh_short_ma', 'ldh_short_mb',
    'ldb_short_ma', 'ldb_short_mb',

    # =====================================================================
    # NEW PA-RISC 2.0: 64-bit Load Doubleword
    # =====================================================================
    'ldd', 'ldd_ma', 'ldd_mb',
    'ldd_short', 'ldd_short_ma', 'ldd_short_mb',
    'lddx',

    # =====================================================================
    # Stores - long displacement 14-bit forms
    # =====================================================================
    'stw', 'sth', 'stb', 'stwx',
    'stbx', 'sthx',

    # Store with modify
    'stw_ma',

    # Stores - short displacement IM5 forms
    'stw_short', 'sth_short', 'stb_short',

    # Stores - short displacement with modify
    'stw_short_ma', 'stw_short_mb',
    'stb_short_ma',
    'sth_short_ma',

    # =====================================================================
    # NEW PA-RISC 2.0: 64-bit Store Doubleword
    # =====================================================================
    'std', 'std_ma', 'std_mb',
    'std_short', 'std_short_ma', 'std_short_mb',
    'stdx',

    # Store bytes (unaligned access)
    'stby', 'stdby',

    # =====================================================================
    # Absolute addressing (physical address, bypass TLB)
    # =====================================================================
    'ldwa', 'stwa', 'ldda', 'stda',

    # =====================================================================
    # Branches - unconditional
    # =====================================================================
    'b', 'bl', 'bv', 'blr',

    # NEW PA-RISC 2.0: 64-bit branch instructions
    'bve', 'bve_l', 'bl_l',

    # Branches - external
    'be', 'ble', 'gate',

    # =====================================================================
    # COMB - Compare and Branch True (opcode 0x20, merged narrow+wide)
    # =====================================================================
    'comb_never', 'comb_eq', 'comb_lt', 'comb_le',
    'comb_ltu', 'comb_leu', 'comb_sv', 'comb_od',

    # =====================================================================
    # COMIBT - Compare Immediate and Branch True (opcode 0x21, merged)
    # =====================================================================
    'comibt_never', 'comibt_eq', 'comibt_lt', 'comibt_le',
    'comibt_ltu', 'comibt_leu', 'comibt_sv', 'comibt_od',

    # =====================================================================
    # COMBF - Compare and Branch False (opcode 0x22, merged narrow+wide)
    # =====================================================================
    'combf_tr', 'combf_ne', 'combf_ge', 'combf_gt',
    'combf_geu', 'combf_gtu', 'combf_nsv', 'combf_ev',

    # =====================================================================
    # CMPIBF - Compare Immediate and Branch False (opcode 0x23, merged)
    # =====================================================================
    'cmpibf_tr', 'cmpibf_ne', 'cmpibf_ge', 'cmpibf_ev',
    'cmpibf_never', 'cmpibf_eq', 'cmpibf_lt', 'cmpibf_od',

    # =====================================================================
    # NEW PA-RISC 2.0: CMPB,* - Wide Compare and Branch True (opcode 0x27)
    # Always 64-bit comparison, wide displacement format
    # =====================================================================
    'cmpb_true_never', 'cmpb_true_eq', 'cmpb_true_lt', 'cmpb_true_le',
    'cmpb_true_ltu', 'cmpb_true_leu', 'cmpb_true_sv', 'cmpb_true_od',

    # =====================================================================
    # NEW PA-RISC 2.0: CMPBF,* - Wide Compare and Branch False (opcode 0x2F)
    # =====================================================================
    'cmpb_false_tr', 'cmpb_false_ne', 'cmpb_false_ge', 'cmpb_false_gt',
    'cmpb_false_geu', 'cmpb_false_gtu', 'cmpb_false_nsv', 'cmpb_false_ev',

    # =====================================================================
    # NEW PA-RISC 2.0: CMPIB,* - Wide Compare Immediate and Branch True (opcode 0x33)
    # Always 64-bit comparison, narrow displacement format
    # PA-RISC 2.0 remapped condition encoding: c[2]=complement, c[1:0]=LTU/EQ/LT/LE
    # =====================================================================
    'cmpib_true_geu', 'cmpib_true_ne', 'cmpib_true_ge', 'cmpib_true_gt',
    'cmpib_true_ltu', 'cmpib_true_eq', 'cmpib_true_lt', 'cmpib_true_le',

    # =====================================================================
    # NEW PA-RISC 2.0: CMPIBF,* - Wide Compare Immediate and Branch False (opcode 0x3B)
    # PA-RISC 2.0 remapped condition encoding: c[2]=complement, c[1:0]=LTU/EQ/LT/LE
    # =====================================================================
    'cmpib_false_ltu', 'cmpib_false_eq', 'cmpib_false_lt', 'cmpib_false_le',
    'cmpib_false_geu', 'cmpib_false_ne', 'cmpib_false_ge', 'cmpib_false_gt',

    # PA-RISC 1.1 COMIB removed: opcode 0x24 is exclusively COMICLR
    # 'comib_eq', 'comib_lt', 'comib_le', 'comib_ne',  # DELETED - no COMIB at opcode 0x24

    # =====================================================================
    # COMCLR - compare and clear (64-bit comparisons)
    # =====================================================================
    'comclr_eq', 'comclr_ne', 'comclr_lt', 'comclr_le',
    'comclr_gt', 'comclr_ge', 'comclr_ltu', 'comclr_leu',
    'comclr_geu', 'comclr_gtu',

    # COMICLR - compare immediate and clear
    'comiclr_tr', 'comiclr_eq', 'comiclr_ne',
    'comiclr_lt', 'comiclr_ge', 'comiclr_le', 'comiclr_gt',
    'comiclr_ltu', 'comiclr_geu', 'comiclr_leu', 'comiclr_gtu',

    # =====================================================================
    # Add and Branch (64-bit)
    # =====================================================================
    'addb_eq', 'addb_ne', 'addb_tr',
    'addib_eq', 'addib_ne', 'addib_gt', 'addib_ge',
    'addib_lt', 'addib_le', 'addib_tr', 'addib_uv', 'addib_nuv',

    # Move and Branch (64-bit)
    'movb_eq', 'movb_ne', 'movb_lt', 'movb_ge', 'movb_tr', 'movb_od',
    'movib_eq', 'movib_ne', 'movib_lt', 'movib_tr',

    # Branch on Bit (64-bit registers)
    'bb_set', 'bb_clear',
    'bb_sar_set', 'bb_sar_clear',

    # =====================================================================
    # Floating-point arithmetic - single precision
    # =====================================================================
    'fadd_sgl', 'fsub_sgl', 'fmpy_sgl', 'fdiv_sgl',

    # Floating-point load/store - single precision
    'fldw', 'fldwr', 'fstw', 'fstwr',

    # Floating-point compare - single precision
    'fcmp_sgl',

    # Floating-point convert - single precision
    'fcnvxf_w_sgl', 'fcnvfx_sgl_w', 'fcnvfxt_sgl_w',

    # Floating-point utility - single precision
    'fcpy_sgl', 'fabs_sgl', 'fneg_sgl', 'fsqrt_sgl', 'frnd_sgl',

    # Floating-point arithmetic - double precision
    'fadd_dbl', 'fsub_dbl', 'fmpy_dbl', 'fdiv_dbl',

    # Floating-point compare - double precision
    'fcmp_dbl',

    # Floating-point convert - double precision
    'fcnvff_sgl_dbl', 'fcnvff_dbl_sgl',
    'fcnvxf_w_dbl', 'fcnvfx_dbl_w', 'fcnvfxt_dbl_w',

    # Floating-point utility - double precision
    'fcpy_dbl', 'fabs_dbl', 'fneg_dbl', 'fsqrt_dbl', 'frnd_dbl',

    # Floating-point load/store - double precision
    'fldd', 'fstd',
    'flddx', 'fstdx',               # FP double indexed
    'fldds', 'fstds',               # FP double short displacement
    'fldd_mb',                       # FP double load modify-before
    'fstd_ma',                       # FP double store modify-after
    'fldd_long', 'fstd_long',       # FP double long displacement (opcode 0x14/0x1C)

    # Floating-point load/store - word short displacement
    'fldws', 'fstws',

    # Floating-point test
    'ftest',

    # Fixed-point multiply (uses FP regs)
    'xmpyu',

    # PA-RISC 1.1 dual-result FP multiply-add/subtract (retained in 2.0)
    'fmpyadd_sgl', 'fmpyadd_dbl',
    'fmpysub_sgl', 'fmpysub_dbl',

    # =====================================================================
    # NEW PA-RISC 2.0: Fused Multiply-Add
    # =====================================================================
    'fmpyfadd_sgl', 'fmpyfadd_dbl',
    'fmpynfadd_sgl', 'fmpynfadd_dbl',

    # =====================================================================
    # NEW PA-RISC 2.0: MAX-2 Multimedia SIMD Instructions
    # =====================================================================
    # Halfword parallel arithmetic (4x16-bit SIMD)
    'hadd_ss', 'hadd_us',       # Halfword Add (signed/unsigned saturating)
    'hsub_ss', 'hsub_us',       # Halfword Subtract
    'havg',                      # Halfword Average

    # Halfword shift-and-add
    'hshladd', 'hshradd',       # Halfword Shift Left/Right and Add

    # Halfword shifts
    'hshl', 'hshr',             # Halfword Shift Left/Right

    # Halfword permute and interleave
    'permh',                     # Halfword Permute
    'mixw_l', 'mixw_r',         # Word Interleave Left/Right
    'mixh_l', 'mixh_r',         # Halfword Interleave Left/Right

    # =====================================================================
    # System instructions (64-bit CRs and PSW)
    # =====================================================================
    'break', 'rfi', 'rfir', 'mfctl', 'mtctl', 'ssm', 'rsm', 'mtsm',
    'mfsp', 'mtsp', 'lpa', 'ldsid', 'prober', 'probew',

    # =====================================================================
    # Synchronization
    # =====================================================================
    'sync', 'syncdma',

    # =====================================================================
    # Division support (64-bit)
    # =====================================================================
    'ds', 'uaddcm',

    # Decimal correction
    'dcor', 'idcor',

    # =====================================================================
    # Cache operations
    # =====================================================================
    'fdc', 'fic', 'pdc', 'pdc_m', 'lci',
    'fice', 'fice_m', 'fdce', 'fdce_m',
    'fdc_m', 'fic_m',

    # =====================================================================
    # TLB operations
    # =====================================================================
    'idtlba', 'idtlbp', 'iitlba', 'iitlbp', 'pdtlb', 'pitlb',
    'pdtlbe', 'pitlbe',
    # NEW PA-RISC 2.0: Combined TLB insert (wide-mode)
    'idtlbt', 'iitlbt',

    # =====================================================================
    # Special/Coprocessor operations
    # =====================================================================
    'copr', 'spop0', 'spop1', 'spop2', 'spop3',

    # Diagnostic
    'diag', 'diag_btlb_insert', 'diag_btlb_purge_all',

    # Move from instruction address (64-bit)
    'mfia',

    # =====================================================================
    # NEW PA-RISC 2.0: Branch prediction
    # =====================================================================
    'popbts',

    # Misc
    'nop',
]

# Test list for HPPA PA-RISC 2.0
HPPA20_TESTS = [
    "add", "sub", "and", "or", "xor",
    "sh1add", "sh2add", "sh3add",
    "ldo", "addi",
    "ldw", "stw", "ldd", "std",
    "b", "bl", "comb_eq", "combf_ne",
    "extrd_u", "depd",
    "hadd_ss", "havg", "permh",
    "mixw_l", "mixh_l",
]


def apply_narrow_mode_fix(verilog_path):
    """No-op: narrow mode handling is now in the ISA files themselves.

    Each arithmetic/comparison ISA file checks psw[27] (PSW.W) and
    sign-extends register sources and results from 32 bits when in
    narrow mode (PSW.W=0). This ensures correct condition evaluation,
    carry/overflow detection, and comparison semantics for both 32-bit
    and 64-bit modes without post-processing the generated Verilog.
    """
    print("  Skipped: narrow mode handling is now in ISA files (no Verilog patching needed)")


def apply_memory_transform(merged_graph):
    """Apply port width setting for 64-bit word-addressed unified memory."""
    umem_node = merged_graph.nodes.get('umem')
    if umem_node:
        access_widths = umem_node.data.get('access_widths', [64])
        max_width = max(access_widths) if access_widths else 64
        print(f"  umem access widths: {access_widths}, max: {max_width}")

        transform = MemoryAccessTransform(merged_graph)
        spec = MemoryAccessTransformSpec(
            memory='umem',
            strategy='set_port_width',
            current_width=max_width,
            target_width=64,
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
        description='Generate HPPA PA-RISC 2.0 (64-bit) processor from ISA definitions'
    )
    parser.add_argument(
        '--output-dir', '-o',
        default='examples/verilog/hppa20',
        help='Output directory (default: examples/verilog/hppa20)'
    )
    parser.add_argument(
        '--module-name', '-m',
        default='hppa20',
        help='Module name (default: hppa20)'
    )
    args = parser.parse_args()

    module_name = args.module_name
    output_dir = args.output_dir

    print("=" * 70)
    print("HPPA PA-RISC 2.0 (64-bit) Processor Generator")
    print("=" * 70)
    print(f"\nGenerating PA-RISC 2.0 processor with {len(INSTRUCTIONS)} instructions...")
    print(f"Instructions: {', '.join(INSTRUCTIONS)}")

    # Step 1: Parse and merge ISA files
    print("\n" + "=" * 70)
    print("Step 1: Parsing and merging ISA files...")
    print("=" * 70)

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

    # Step 4: Apply narrow mode fix (PSW.W=0 zero-extends 32-bit results)
    print("\n" + "=" * 70)
    print("Step 4: Applying narrow mode register write masking...")
    print("=" * 70)
    apply_narrow_mode_fix(os.path.join(output_dir, f"{module_name}.v"))

    # Summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"  Successfully generated PA-RISC 2.0 processor")
    print(f"  {len(INSTRUCTIONS)} instructions implemented")
    print(f"  {len(merged_graph.nodes)} nodes in merged graph")
    print(f"  {len(merged_graph.edges)} edges in merged graph")
    print(f"  Output: {output_dir}/")

    print("\n" + "=" * 70)
    print("Done!")
    print("=" * 70)


if __name__ == "__main__":
    main()
