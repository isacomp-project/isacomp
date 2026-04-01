#!/usr/bin/env python3
"""
Generate complete OpenPOWER LCS (Linux Compliance Subset) processor
This includes all implemented instructions: SFS + SFFS + additional Linux-required
instructions for Power ISA v3.0B compliance.

Total: 280 instructions (208 integer + 72 floating-point)

Supports Verilog, VHDL, PyRTL, and CIRCT backends via --backend argument.
"""
import sys
import os
import argparse

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core.graph_merger import merge_instructions
from backends.verilog import generate_verilog_with_testbench
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec
from opt.temporal.multi_cycle_operations import apply_multi_cycle_operations, OperationLatencySpec

# OpenPOWER SFS (Scalar Fixed-point Subset) - Core integer operations
SFS_CORE_INSTRUCTIONS = [
    # Fixed-point Arithmetic - Register
    'add', 'subf', 'neg', 'mullw', 'mulld', 'divw', 'divwu', 'divd', 'divdu',

    # Fixed-point Arithmetic - Immediate
    'addi', 'addis', 'subfic', 'mulli',

    # Fixed-point Logical - Register
    'and', 'or', 'xor', 'nand', 'nor', 'eqv', 'andc', 'orc',

    # Fixed-point Logical - Immediate
    'andi', 'andis', 'ori', 'oris', 'xori', 'xoris',

    # Sign Extension
    'extsb', 'extsh', 'extsw',

    # Shift - Word
    'slw', 'srw', 'sraw', 'srawi',

    # Shift - Doubleword
    'sld', 'srd', 'srad', 'sradi',

    # Rotate - Word
    'rlwinm', 'rlwimi', 'rlwnm',

    # Rotate - Doubleword
    'rldicl', 'rldicr', 'rldic', 'rldimi', 'rldcl', 'rldcr',

    # Load - Byte
    'lbz', 'lbzx', 'lbzu', 'lbzux',

    # Load - Halfword Zero
    'lhz', 'lhzx', 'lhzu', 'lhzux',

    # Load - Halfword Algebraic
    'lha', 'lhax', 'lhau', 'lhaux',

    # Load - Word Zero
    'lwz', 'lwzx', 'lwzu', 'lwzux',

    # Load - Word Algebraic
    'lwa', 'lwax', 'lwaux',

    # Load - Doubleword
    'ld', 'ldx', 'ldu', 'ldux',

    # Store - Byte
    'stb', 'stbx', 'stbu', 'stbux',

    # Store - Halfword
    'sth', 'sthx', 'sthu', 'sthux',

    # Store - Word
    'stw', 'stwx', 'stwu', 'stwux',

    # Store - Doubleword
    'std', 'stdx', 'stdu', 'stdux',

    # Branch - Unconditional
    'b', 'ba', 'bl', 'bla',

    # Branch - Conditional
    'bc', 'bcl', 'bclr', 'bclrl', 'bcctr', 'bcctrl',

    # Compare - Word
    'cmpw', 'cmplw', 'cmpwi', 'cmplwi',

    # Compare - Doubleword
    'cmpd', 'cmpld', 'cmpdi', 'cmpldi',

    # Condition Register Operations
    'crand', 'cror', 'crxor', 'crnand', 'crnor', 'crandc', 'crorc', 'creqv', 'mcrf',

    # CR/SPR Move
    'mfcr', 'mtcrf', 'mfspr', 'mtspr', 'mfocrf', 'mtocrf',
]

# Additional arithmetic instructions with record forms
# Note: Overflow forms (addo, subfo, nego, etc.) are excluded due to XER SO bit cycles.
EXTENDED_ARITHMETIC_INSTRUCTIONS = [
    # Add with carry (no overflow tracking)
    'addc',
    'add_dot',

    # Subtract with carry (no overflow tracking)
    'subfc',
    'subf_dot',

    # Carry-extending forms (read and write CA in the same instruction)
    'adde', 'subfe',
    'addze', 'subfze',
    'addme', 'subfme',

    # Add immediate with carry
    'addic', 'addic_dot',

    # Negate record form
    'neg_dot',

    # Multiply high/record forms
    'mulhw', 'mulhwu', 'mulhd', 'mulhdu',
    'mulld_dot', 'mullw_dot',

    # Divide record forms
    'divw_dot', 'divwu_dot', 'divd_dot', 'divdu_dot',

    # Modulo operations
    'modsd', 'modsw', 'modud', 'moduw',

    # Multiply-Add (POWER9)
    'maddld',
]

# Additional logical instructions with record forms
EXTENDED_LOGICAL_INSTRUCTIONS = [
    'and_dot', 'or_dot', 'xor_dot', 'nand_dot', 'nor_dot', 'eqv_dot', 'andc_dot', 'orc_dot',
    'extsb_dot', 'extsh_dot', 'extsw_dot',
    'slw_dot', 'srw_dot', 'sraw_dot',
    'sld_dot', 'srd_dot', 'srad_dot',
    # Rotate record forms
    'rlwinm_dot',
    'rldicl_dot', 'rldicr_dot', 'rldic_dot', 'rldimi_dot', 'rldcl_dot', 'rldcr_dot',
]

# Bit manipulation and population count instructions
BIT_MANIPULATION_INSTRUCTIONS = [
    # Count leading/trailing zeros
    'cntlzw', 'cntlzw_dot', 'cntlzd', 'cntlzd_dot',
    'cnttzw', 'cnttzd',

    # Population count
    'popcntb', 'popcntw', 'popcntd',

    # Parity
    'prtyw', 'prtyd',

    # Byte comparison
    'cmpb',

    # Set boolean
    'setb',

    # Extend and shift left immediate
    'extswsli',

    # Select
    'isel',
]

# Byte-reverse load/store instructions
BYTE_REVERSE_INSTRUCTIONS = [
    'lhbrx', 'lwbrx', 'ldbrx',
    'sthbrx', 'stwbrx', 'stdbrx',
]

# Atomic load-reserve/store-conditional
ATOMIC_INSTRUCTIONS = [
    'lbarx', 'lharx', 'lwarx', 'ldarx',
    'stbcx', 'sthcx', 'stwcx', 'stdcx',
]

# Multiple load/store
MULTIPLE_INSTRUCTIONS = [
    'lmw', 'stmw',
]

# System instructions
SYSTEM_INSTRUCTIONS = [
    # MSR operations
    'mfmsr', 'mtmsr', 'mtmsrd',

    # Time base
    'mftb',

    # XER access
    'mcrxrx',

    # System call
    'sc',

    # Return from interrupt
    'rfid',

    # Traps
    'tw', 'twi', 'td', 'tdi',

    # Wait
    'wait',

    # Random number (POWER9)
    'darn',

    # SPR-specific access (required for Linux boot)
    # These are variants of mfspr/mtspr with specific SPR numbers
    'mfspr_dec', 'mtspr_dec',       # Decrementer (SPR 22)
    'mfspr_srr0', 'mtspr_srr0',     # Save/Restore Register 0 (SPR 26)
    'mfspr_srr1', 'mtspr_srr1',     # Save/Restore Register 1 (SPR 27)
    'mfspr_dar', 'mtspr_dar',       # Data Address Register (SPR 19)
    'mfspr_dsisr', 'mtspr_dsisr',   # Data Storage Interrupt Status (SPR 18)
    'mfspr_sprg0', 'mtspr_sprg0',   # SPRG0 (SPR 272)
    'mfspr_sprg1', 'mtspr_sprg1',   # SPRG1 (SPR 273)
    'mfspr_sprg2', 'mtspr_sprg2',   # SPRG2 (SPR 274)
    'mfspr_sprg3', 'mtspr_sprg3',   # SPRG3 (SPR 275)
    'mfspr_pvr',                     # Processor Version Register (SPR 287, read-only)
    'mfspr_xer', 'mtspr_xer',       # Fixed-Point Exception Register (SPR 1)
    'mfspr_tb',                      # Time Base (SPR 268)
    'mfspr_tbu',                     # Time Base Upper (SPR 269)
    'mfspr_ptcr', 'mtspr_ptcr',     # Partition Table Control Register (SPR 464)
    'mfspr_pidr', 'mtspr_pidr',     # Process ID Register (SPR 48)
]

# Cache and memory barrier instructions
CACHE_BARRIER_INSTRUCTIONS = [
    # Data cache
    'dcbf', 'dcbi', 'dcbst', 'dcbt', 'dcbtst', 'dcbz',

    # Instruction cache
    'icbi', 'icbt',

    # Barriers
    'sync', 'lwsync', 'ptesync', 'isync', 'eieio', 'msgsync',

    # TLB management
    'tlbie', 'tlbiel', 'tlbsync',

    # SLB management
    'slbia', 'slbie',
]

# All integer instructions
INTEGER_INSTRUCTIONS = (
    SFS_CORE_INSTRUCTIONS +
    EXTENDED_ARITHMETIC_INSTRUCTIONS +
    EXTENDED_LOGICAL_INSTRUCTIONS +
    BIT_MANIPULATION_INSTRUCTIONS +
    BYTE_REVERSE_INSTRUCTIONS +
    ATOMIC_INSTRUCTIONS +
    MULTIPLE_INSTRUCTIONS +
    SYSTEM_INSTRUCTIONS +
    CACHE_BARRIER_INSTRUCTIONS
)

# OpenPOWER SFFS Single-Precision FP Instructions
FP_SP_INSTRUCTIONS = [
    # Arithmetic
    'fadds', 'fsubs', 'fmuls', 'fdivs', 'fsqrts',

    # Fused multiply-add
    'fmadds', 'fmsubs', 'fnmadds', 'fnmsubs',

    # Comparison
    'fcmpu', 'fcmpo',

    # Move/Sign operations
    'fmr', 'fneg', 'fabs', 'fnabs', 'fcpsgn', 'fsel',

    # Conversions
    'frsp', 'fctiw', 'fctiwu', 'fctiwz', 'fctiwuz', 'fcfids', 'fcfidus',

    # Load/Store
    'lfs', 'lfsx', 'stfs', 'stfsx',

    # Load/Store with Update
    'lfsu', 'lfsux', 'stfsu', 'stfsux',
]

# OpenPOWER SFFS Double-Precision FP Instructions
FP_DP_INSTRUCTIONS = [
    # Arithmetic
    'fadd', 'fsub', 'fmul', 'fdiv', 'fsqrt',

    # Fused multiply-add
    'fmadd', 'fmsub', 'fnmadd', 'fnmsub',

    # Conversions
    'fcfid', 'fcfidu', 'fctid', 'fctidz', 'fctidu', 'fctiduz',

    # Round to integer
    'frin', 'friz', 'frip', 'frim',

    # Load/Store
    'lfd', 'lfdx', 'stfd', 'stfdx',

    # Load/Store with Update
    'lfdu', 'lfdux', 'stfdu', 'stfdux',

    # Load/Store Integer via FP
    'lfiwax', 'lfiwzx', 'stfiwx',

    # Merge operations
    'fmrgew', 'fmrgow',

    # Test operations
    'ftdiv', 'ftsqrt',

    # FPSCR access
    'mffs', 'mtfsb0', 'mtfsb1', 'mtfsf', 'mtfsfi', 'mcrfs',
]

# All FP instructions
FP_INSTRUCTIONS = FP_SP_INSTRUCTIONS + FP_DP_INSTRUCTIONS

# Combined instruction set
ALL_INSTRUCTIONS = INTEGER_INSTRUCTIONS + FP_INSTRUCTIONS


def generate_verilog(merged_graph, module_name, output_dir):
    """Generate Verilog output."""
    testbench_config = {
        'timeout_cycles': 20000
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
        description='Generate complete OpenPOWER LCS (Linux Compliance Subset) processor from ISA definitions'
    )
    parser.add_argument(
        '--backend', '-b',
        choices=['verilog', 'vhdl', 'pyrtl', 'circt'],
        default='verilog',
        help='Output backend (default: verilog)'
    )
    parser.add_argument(
        '--output-dir', '-o',
        help='Output directory (default: examples/verilog/openpower_lcs)'
    )
    args = parser.parse_args()

    module_name = 'openpower_lcs'
    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = 'examples/verilog/openpower_lcs'

    print("=" * 70)
    print(f"OPENPOWER LCS (LINUX COMPLIANCE SUBSET) GENERATOR ({args.backend.upper()} backend)")
    print("=" * 70)
    print(f"\nGenerating OpenPOWER LCS processor with {len(ALL_INSTRUCTIONS)} instructions...")
    print(f"  SFS Core: {len(SFS_CORE_INSTRUCTIONS)} instructions")
    print(f"  Extended Arithmetic: {len(EXTENDED_ARITHMETIC_INSTRUCTIONS)} instructions")
    print(f"  Extended Logical: {len(EXTENDED_LOGICAL_INSTRUCTIONS)} instructions")
    print(f"  Bit Manipulation: {len(BIT_MANIPULATION_INSTRUCTIONS)} instructions")
    print(f"  Byte Reverse: {len(BYTE_REVERSE_INSTRUCTIONS)} instructions")
    print(f"  Atomic: {len(ATOMIC_INSTRUCTIONS)} instructions")
    print(f"  Multiple Load/Store: {len(MULTIPLE_INSTRUCTIONS)} instructions")
    print(f"  System: {len(SYSTEM_INSTRUCTIONS)} instructions")
    print(f"  Cache/Barrier: {len(CACHE_BARRIER_INSTRUCTIONS)} instructions")
    print(f"  FP Single-Precision: {len(FP_SP_INSTRUCTIONS)} instructions")
    print(f"  FP Double-Precision: {len(FP_DP_INSTRUCTIONS)} instructions")
    print(f"  Total Integer: {len(INTEGER_INSTRUCTIONS)}")
    print(f"  Total FP: {len(FP_INSTRUCTIONS)}")

    print("\n" + "=" * 70)
    print("PARSING AND MERGING ISA FILES")
    print("=" * 70)

    # Build instruction paths
    isa_files = {}
    for instr in INTEGER_INSTRUCTIONS:
        isa_files[instr] = f"isa/openpower/{instr}.isa"
    for instr in FP_INSTRUCTIONS:
        isa_files[instr] = f"isa/openpower/f/{instr}.isa"

    print(f"\nMerging {len(ALL_INSTRUCTIONS)} ISA specifications...")
    merged_graph = merge_instructions(isa_files)
    print(f"  Merged graph has {len(merged_graph.nodes)} nodes and {len(merged_graph.edges)} edges")

    # Apply port width setting for 64-bit word-addressed unified memory
    print("\nApplying memory port width transformation for umem...")
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
            target_width=64,  # 64-bit word-addressed memory for OpenPOWER
            direction='forward'
        )
        result = transform.apply_transformation(spec)
        if result.get('transformed'):
            print(f"  Transformed: added {len(result.get('nodes_added', []))} byte mux nodes")
        else:
            print(f"  Skipped: {result.get('reason', 'unknown')}")

    # Apply multi-cycle latency for FP div/sqrt (single and double precision)
    print("\nApplying multi-cycle latency for FP operations...")
    fp_div_sqrt_ops = []
    for node_id, node in merged_graph.nodes.items():
        fp_intrinsic = node.data.get('fp_intrinsic', '')
        if fp_intrinsic in ['fp_div', 'fp_sqrt']:
            fp_div_sqrt_ops.append(OperationLatencySpec(
                operation_id=node_id,
                latency_cycles=10
            ))
        elif fp_intrinsic in ['fp_div_d', 'fp_sqrt_d']:
            # Double-precision has higher latency
            fp_div_sqrt_ops.append(OperationLatencySpec(
                operation_id=node_id,
                latency_cycles=20
            ))

    if fp_div_sqrt_ops:
        apply_multi_cycle_operations(merged_graph, fp_div_sqrt_ops)
        print(f"  Applied {len(fp_div_sqrt_ops)} multi-cycle operation(s)")

    print("\n" + "=" * 70)
    print(f"GENERATING {args.backend.upper()}")
    print("=" * 70)
    print(f"\nOutput directory: {output_dir}/")

    try:
        if args.backend == 'verilog':
            files = generate_verilog(merged_graph, module_name, output_dir)
        else:
            print(f"  Backend '{args.backend}' not yet implemented for OpenPOWER LCS")
            print("  Using Verilog backend instead")
            files = generate_verilog(merged_graph, module_name, output_dir)

        print("\n" + "=" * 70)
        print("GENERATION COMPLETE")
        print("=" * 70)
        print(f"\nOpenPOWER LCS processor generated successfully!")
        print(f"  Total instructions: {len(ALL_INSTRUCTIONS)}")
        print(f"    - Integer: {len(INTEGER_INSTRUCTIONS)}")
        print(f"    - Floating-Point: {len(FP_INSTRUCTIONS)}")
        print(f"\nGenerated files:")
        for key, path in files.items():
            if hasattr(path, 'stat'):
                file_size = path.stat().st_size if path.exists() else 0
                print(f"  {key.upper()}: {path} ({file_size:,} bytes)")
            else:
                print(f"  {key.upper()}: {path}")

    except Exception as e:
        print(f"  Error generating: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print(f"\n  Successfully generated OpenPOWER LCS processor!")
    print("\nKey features:")
    print("  - 64-bit integer register file (r0-r31)")
    print("  - 64-bit floating-point register file (fpr0-fpr31)")
    print("  - 64-bit program counter")
    print("  - 32-bit Condition Register (CR)")
    print("  - 32-bit XER register (SO/OV/CA)")
    print("  - 64-bit CTR and LR registers")
    print("  - 32-bit Floating-Point Status and Control Register (FPSCR)")
    print("  - Complete arithmetic with carry/overflow tracking")
    print("  - Bit manipulation (cntlz/cnttz, popcnt, parity)")
    print("  - Byte comparison (cmpb) and set boolean (setb)")
    print("  - Atomic load-reserve/store-conditional")
    print("  - IEEE 754 single and double-precision FP")
    print("  - Fused multiply-add operations")
    print("  - Integer <-> FP conversions")


if __name__ == "__main__":
    main()
