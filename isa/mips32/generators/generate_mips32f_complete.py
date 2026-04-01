#!/usr/bin/env python3
"""
Generate complete MIPS32 + FPU processor (MIPS32 Release 2 + Coprocessor 1)
This includes all base MIPS32 instructions plus single-precision floating-point
instructions from the MIPS32 FPU specification.

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

# Complete MIPS32 integer instruction set (39 instructions total)
MIPS32_INSTRUCTIONS = [
    # R-type arithmetic (7)
    'add', 'addu', 'sub', 'subu', 'slt', 'sltu', 'nor',

    # R-type logical (3)
    'and', 'or', 'xor',

    # R-type shifts - immediate (3)
    'sll', 'srl', 'sra',

    # R-type shifts - variable (3)
    'sllv', 'srlv', 'srav',

    # I-type arithmetic/logical (8)
    'addi', 'addiu', 'andi', 'ori', 'xori', 'slti', 'sltiu', 'lui',

    # Loads - word and subword (5)
    'lw', 'lh', 'lhu', 'lb', 'lbu',

    # Stores - word and subword (3)
    'sw', 'sh', 'sb',

    # Branches (2)
    'beq', 'bne',

    # Jumps (4)
    'j', 'jal', 'jr', 'jalr',
]

# MIPS32 FPU single-precision instructions (20 instructions)
MIPS32F_INSTRUCTIONS = [
    # Arithmetic (5)
    'add_s', 'sub_s', 'mul_s', 'div_s', 'sqrt_s',

    # Fused multiply-add (4)
    'madd_s', 'msub_s', 'nmadd_s', 'nmsub_s',

    # Min/Max (2)
    'min_s', 'max_s',

    # Comparisons (3)
    'c_eq_s', 'c_lt_s', 'c_le_s',

    # Conversions (2)
    'cvt_s_w', 'cvt_w_s',

    # Move/Sign operations (3)
    'mov_s', 'neg_s', 'abs_s',

    # Move between integer and FP registers (2)
    'mfc1', 'mtc1',

    # Load/Store (2)
    'lwc1', 'swc1',
]

# Combined instruction set
INSTRUCTIONS = MIPS32_INSTRUCTIONS + MIPS32F_INSTRUCTIONS

# Test list for MIPS32
MIPS32_TESTS = [
    "add", "addi", "addiu", "addu", "and", "andi", "beq", "bne",
    "j", "jal", "jalr", "jr", "lb", "lbu", "lh", "lhu", "lui", "lw",
    "nor", "or", "ori", "sb", "sh", "sll", "sllv", "slt", "slti",
    "sltiu", "sltu", "sra", "srav", "srl", "srlv", "sub", "subu",
    "sw", "xor", "xori"
]


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
        description='Generate complete MIPS32 + FPU processor from ISA definitions'
    )
    parser.add_argument(
        '--backend', '-b',
        choices=['verilog', 'vhdl', 'pyrtl', 'circt'],
        default='verilog',
        help='Output backend (default: verilog)'
    )
    parser.add_argument(
        '--output-dir', '-o',
        help='Output directory (default: examples/verilog/mips32f_complete)'
    )
    args = parser.parse_args()

    module_name = 'mips32f_complete'
    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = 'examples/verilog/mips32f_complete'

    print("=" * 70)
    print(f"MIPS32 + FPU COMPLETE PROCESSOR GENERATOR ({args.backend.upper()} backend)")
    print("=" * 70)
    print(f"\nGenerating MIPS32 + FPU processor with {len(INSTRUCTIONS)} instructions...")
    print(f"  Base MIPS32: {len(MIPS32_INSTRUCTIONS)} instructions")
    print(f"  FPU (single-precision): {len(MIPS32F_INSTRUCTIONS)} instructions")

    print("\n" + "=" * 70)
    print("PARSING AND MERGING ISA FILES")
    print("=" * 70)

    # Build instruction paths
    isa_files = {}
    for instr in MIPS32_INSTRUCTIONS:
        isa_files[instr] = f"isa/mips32/{instr}.isa"
    for instr in MIPS32F_INSTRUCTIONS:
        isa_files[instr] = f"isa/mips32/f/{instr}.isa"

    print(f"\nMerging {len(INSTRUCTIONS)} ISA specifications...")
    merged_graph = merge_instructions(isa_files)
    print(f"  Merged graph has {len(merged_graph.nodes)} nodes and {len(merged_graph.edges)} edges")

    # Apply port width setting for word-addressed unified memory
    print("\nApplying memory port width transformation for umem...")
    umem_node = merged_graph.nodes.get('umem')
    if umem_node:
        access_widths = umem_node.data.get('access_widths', [32])
        max_width = max(access_widths) if access_widths else 32
        print(f"  umem access widths: {access_widths}, max: {max_width}")

        transform = MemoryAccessTransform(merged_graph)
        spec = MemoryAccessTransformSpec(
            memory='umem',
            strategy='set_port_width',
            current_width=max_width,
            target_width=32,
            direction='forward'
        )
        result = transform.apply_transformation(spec)
        if result.get('transformed'):
            print(f"  Transformed: added {len(result.get('nodes_added', []))} byte mux nodes")
        else:
            print(f"  Skipped: {result.get('reason', 'unknown')}")

    # Apply multi-cycle latency for FP div/sqrt
    print("\nApplying multi-cycle latency for FP operations...")
    fp_div_sqrt_ops = []
    for node_id, node in merged_graph.nodes.items():
        fp_intrinsic = node.data.get('fp_intrinsic', '')
        if fp_intrinsic in ['fp_div', 'fp_sqrt']:
            fp_div_sqrt_ops.append(OperationLatencySpec(
                operation_id=node_id,
                latency_cycles=10
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
            print(f"  Backend '{args.backend}' not yet implemented for MIPS32F")
            print("  Using Verilog backend instead")
            files = generate_verilog(merged_graph, module_name, output_dir)

        print("\n" + "=" * 70)
        print("GENERATION COMPLETE")
        print("=" * 70)
        print(f"\nMIPS32 + FPU processor generated successfully!")
        print(f"  Total instructions: {len(INSTRUCTIONS)}")
        print(f"    - Base MIPS32: {len(MIPS32_INSTRUCTIONS)}")
        print(f"    - FPU (single-precision): {len(MIPS32F_INSTRUCTIONS)}")
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

    print(f"\n  Successfully generated MIPS32 + FPU processor!")


if __name__ == "__main__":
    main()
