#!/usr/bin/env python3
"""
Generate complete OpenPOWER + FPU processor (Power ISA v3.0B + IEEE 754 FPU)
This includes all base OpenPOWER SFS instructions plus single-precision and
double-precision floating-point instructions from the Power ISA specification.

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

# OpenPOWER Scalar Fixed-point Subset (SFS) - 85 instructions total
OPENPOWER_INSTRUCTIONS = [
    # Fixed-point Arithmetic - Register (9)
    'add', 'subf', 'neg', 'mullw', 'mulld', 'divw', 'divwu',
    'divd', 'divdu',

    # Fixed-point Arithmetic - Immediate (4)
    'addi', 'addis', 'subfic', 'mulli',

    # Fixed-point Logical - Register (8)
    'and', 'or', 'xor', 'nand', 'nor', 'eqv', 'andc', 'orc',

    # Fixed-point Logical - Immediate (6)
    'andi', 'andis', 'ori', 'oris', 'xori', 'xoris',

    # Sign Extension (3)
    'extsb', 'extsh', 'extsw',

    # Shift - Word (4)
    'slw', 'srw', 'sraw', 'srawi',

    # Shift - Doubleword (4)
    'sld', 'srd', 'srad', 'sradi',

    # Rotate Doubleword - MD-form (2) - includes sldi/srdi extended mnemonics
    'rldicl', 'rldicr',

    # Rotate Word - M-form (1) - includes clrrwi, clrlwi, extlwi, etc.
    'rlwinm',

    # Load - Byte (2)
    'lbz', 'lbzx',

    # Load - Halfword (3)
    'lhz', 'lhzx', 'lha',

    # Load - Word (3)
    'lwz', 'lwzx', 'lwa',

    # Load - Doubleword (2)
    'ld', 'ldx',

    # Store - Byte (2)
    'stb', 'stbx',

    # Store - Halfword (2)
    'sth', 'sthx',

    # Store - Word (2)
    'stw', 'stwx',

    # Store - Doubleword (2)
    'std', 'stdx',

    # Branch - Unconditional (4)
    'b', 'ba', 'bl', 'bla',

    # Branch - Conditional (6)
    'bc', 'bcl', 'bclr', 'bclrl', 'bcctr', 'bcctrl',

    # Compare - Word (4)
    'cmpw', 'cmplw', 'cmpwi', 'cmplwi',

    # Compare - Doubleword (4)
    'cmpd', 'cmpld', 'cmpdi', 'cmpldi',

    # Condition Register Operations (6)
    'crand', 'cror', 'crxor', 'crnand', 'crnor', 'mcrf',

    # CR/SPR Move (4)
    'mfcr', 'mtcrf', 'mfspr', 'mtspr',
]

# OpenPOWER FPU single-precision instructions (30 instructions)
OPENPOWERF_SP_INSTRUCTIONS = [
    # Arithmetic (5)
    'fadds', 'fsubs', 'fmuls', 'fdivs', 'fsqrts',

    # Fused multiply-add (4)
    'fmadds', 'fmsubs', 'fnmadds', 'fnmsubs',

    # Comparison (2)
    'fcmpu', 'fcmpo',

    # Move/Sign operations (6)
    'fmr', 'fneg', 'fabs', 'fnabs', 'fcpsgn', 'fsel',

    # Conversions (6)
    'frsp', 'fctiwz', 'fcfids', 'fcfidus', 'fctiw', 'fctiwu', 'fctiwuz',

    # Load/Store (4)
    'lfs', 'stfs', 'lfsx', 'stfsx',

    # Load/Store with Update (4)
    'lfsu', 'lfsux', 'stfsu', 'stfsux',
]

# OpenPOWER FPU double-precision instructions (31 instructions)
OPENPOWERF_DP_INSTRUCTIONS = [
    # Arithmetic (5)
    'fadd', 'fsub', 'fmul', 'fdiv', 'fsqrt',

    # Fused multiply-add (4)
    'fmadd', 'fmsub', 'fnmadd', 'fnmsub',

    # Conversions (7)
    'fcfid', 'fctid', 'fctidz', 'fcfidu', 'fctidu', 'fctiduz',

    # Round to integer (4)
    'frin', 'friz', 'frip', 'frim',

    # Load/Store (4)
    'lfd', 'stfd', 'lfdx', 'stfdx',

    # Load/Store with Update (4)
    'lfdu', 'lfdux', 'stfdu', 'stfdux',

    # Load/Store Integer via FP (3)
    'lfiwax', 'lfiwzx', 'stfiwx',

    # Merge operations (2)
    'fmrgew', 'fmrgow',

    # Test operations (2)
    'ftdiv', 'ftsqrt',

    # FPSCR access (6)
    'mffs', 'mtfsb0', 'mtfsb1', 'mtfsf', 'mtfsfi', 'mcrfs',
]

# Combined FPU instruction set
OPENPOWERF_INSTRUCTIONS = OPENPOWERF_SP_INSTRUCTIONS + OPENPOWERF_DP_INSTRUCTIONS

# Combined instruction set
INSTRUCTIONS = OPENPOWER_INSTRUCTIONS + OPENPOWERF_INSTRUCTIONS


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
        description='Generate complete OpenPOWER + FPU processor from ISA definitions'
    )
    parser.add_argument(
        '--backend', '-b',
        choices=['verilog', 'vhdl', 'pyrtl', 'circt'],
        default='verilog',
        help='Output backend (default: verilog)'
    )
    parser.add_argument(
        '--output-dir', '-o',
        help='Output directory (default: examples/verilog/openpowerf_complete)'
    )
    args = parser.parse_args()

    module_name = 'openpowerf_complete'
    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = 'examples/verilog/openpowerf_complete'

    print("=" * 70)
    print(f"OPENPOWER + FPU COMPLETE PROCESSOR GENERATOR ({args.backend.upper()} backend)")
    print("=" * 70)
    print(f"\nGenerating OpenPOWER + FPU processor with {len(INSTRUCTIONS)} instructions...")
    print(f"  Base OpenPOWER SFS: {len(OPENPOWER_INSTRUCTIONS)} instructions")
    print(f"  FPU Single-Precision: {len(OPENPOWERF_SP_INSTRUCTIONS)} instructions")
    print(f"  FPU Double-Precision: {len(OPENPOWERF_DP_INSTRUCTIONS)} instructions")

    print("\n" + "=" * 70)
    print("PARSING AND MERGING ISA FILES")
    print("=" * 70)

    # Build instruction paths
    isa_files = {}
    for instr in OPENPOWER_INSTRUCTIONS:
        isa_files[instr] = f"isa/openpower/{instr}.isa"
    for instr in OPENPOWERF_INSTRUCTIONS:
        isa_files[instr] = f"isa/openpower/f/{instr}.isa"

    print(f"\nMerging {len(INSTRUCTIONS)} ISA specifications...")
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
            print(f"  Backend '{args.backend}' not yet implemented for OpenPOWERF")
            print("  Using Verilog backend instead")
            files = generate_verilog(merged_graph, module_name, output_dir)

        print("\n" + "=" * 70)
        print("GENERATION COMPLETE")
        print("=" * 70)
        print(f"\nOpenPOWER + FPU processor generated successfully!")
        print(f"  Total instructions: {len(INSTRUCTIONS)}")
        print(f"    - Base OpenPOWER SFS: {len(OPENPOWER_INSTRUCTIONS)}")
        print(f"    - FPU Single-Precision: {len(OPENPOWERF_SP_INSTRUCTIONS)}")
        print(f"    - FPU Double-Precision: {len(OPENPOWERF_DP_INSTRUCTIONS)}")
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

    print(f"\n  Successfully generated OpenPOWER + FPU processor!")
    print("\nKey features:")
    print("  - 64-bit integer register file (r0-r31)")
    print("  - 64-bit floating-point register file (fpr0-fpr31)")
    print("  - 64-bit program counter")
    print("  - 32-bit Condition Register (CR)")
    print("  - 32-bit Floating-Point Status and Control Register (FPSCR)")
    print("  - IEEE 754 single-precision floating-point arithmetic")
    print("  - IEEE 754 double-precision floating-point arithmetic")
    print("  - Fused multiply-add operations (fmadd/s, fmsub/s, etc.)")
    print("  - Integer <-> FP conversions (fcfid, fctid, fctidz)")


if __name__ == "__main__":
    main()
