#!/usr/bin/env python3
"""
Generate basic J4 (SuperH-4) processor with minimal instruction set.
This subset avoids the complex memory write multiplexing issues.
"""
import sys
import os
import argparse

# Add parent directories to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core.graph_merger import merge_instructions
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec

# Basic J4 instruction set - avoiding complex memory writes
INSTRUCTIONS = [
    # Arithmetic
    'add', 'addi', 'sub', 'neg',

    # Logical
    'and', 'andi', 'or', 'ori', 'xor', 'xori', 'not',

    # Shift & Rotate
    'shll', 'shlr', 'rotl', 'rotr',

    # Data Movement - Basic only (no memory stores)
    'mov', 'movi', 'movt',

    # Comparison
    'cmpeq', 'cmpge', 'cmpgt', 'cmphi', 'cmphs', 'cmppl', 'cmppz', 'cmpimm',

    # Branch & Control
    'bt', 'bf', 'bra',

    # System Control - Basic
    'clrt', 'sett', 'nop',
]


def main():
    parser = argparse.ArgumentParser(description="Generate basic J4 processor")
    parser.add_argument('--output-dir', default='isa/j4/j4-tests/sim',
                        help='Output directory for generated files')
    parser.add_argument('--module-name', default='j4_basic',
                        help='Name of the generated module')
    args = parser.parse_args()

    output_dir = args.output_dir
    module_name = args.module_name

    print("=" * 70)
    print("J4 (SuperH-4) Basic Processor Generator")
    print("=" * 70)
    print(f"\nGenerating J4 processor with {len(INSTRUCTIONS)} instructions...")
    print(f"Instructions: {', '.join(INSTRUCTIONS[:10])}...")

    # Build dictionary of ISA files
    isa_files = {instr: f"isa/j4/{instr}.isa" for instr in INSTRUCTIONS}

    print("\n" + "=" * 70)
    print("Step 1: Parsing and merging ISA files...")
    print("=" * 70)

    try:
        merged_graph = merge_instructions(isa_files)
    except Exception as e:
        print(f"  Error merging instructions: {e}")
        raise

    print("\n" + "=" * 70)
    print("Step 2: Applying memory access transform...")
    print("=" * 70)

    # Apply memory transform if umem exists
    mem_node = merged_graph.nodes.get('umem')
    if mem_node:
        access_widths = mem_node.data.get('access_widths', [32])
        max_width = max(access_widths) if access_widths else 32
        print(f"  umem access widths: {access_widths}, max: {max_width}")

        if max_width > 16:
            transform_spec = MemoryAccessTransformSpec(
                memory_name='umem',
                word_bits=32,
                byte_addressed=False,
                big_endian=True
            )
            transform = MemoryAccessTransform()
            transform.apply(merged_graph, transform_spec)
            print("  Applied memory access transform (32-bit words)")

    print("\n" + "=" * 70)
    print("Step 3: Generating Verilog output...")
    print("=" * 70)

    from backends.verilog import generate_verilog_with_testbench
    from pathlib import Path

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    files = generate_verilog_with_testbench(
        merged_graph,
        module_name=module_name,
        output_dir=str(output_path)
    )

    verilog_file = files['rtl']
    file_size = Path(verilog_file).stat().st_size
    print(f"  Generated: {verilog_file} ({file_size} bytes)")

    print("\n" + "=" * 70)
    print("Generation complete!")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
