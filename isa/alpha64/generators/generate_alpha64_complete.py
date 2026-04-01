#!/usr/bin/env python3
"""
Generate complete Alpha64 processor with IEEE floating-point support.

This includes all Alpha integer instructions plus single/double precision
floating-point instructions.

Supports Verilog backend.
"""
import sys
import os
import argparse

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core.graph_merger import merge_instructions
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec

# Alpha integer instructions
ALPHA_INTEGER_INSTRUCTIONS = [
    # Arithmetic (16)
    'addl', 'addq', 'subl', 'subq', 'mull', 'mulq', 'umulh',
    's4addl', 's4addq', 's4subl', 's4subq',
    's8addl', 's8addq', 's8subl', 's8subq',

    # Logical (7)
    'and', 'bis', 'xor', 'bic', 'ornot', 'eqv',
    'amask',

    # Shifts (3)
    'sll', 'srl', 'sra',

    # Sign extension (2)
    'sextb', 'sextw',

    # Comparisons (6)
    'cmpeq', 'cmplt', 'cmple', 'cmpult', 'cmpule', 'cmpbge',

    # Conditional moves (8)
    'cmoveq', 'cmovne', 'cmovlt', 'cmovle', 'cmovgt', 'cmovge',
    'cmovlbs', 'cmovlbc',

    # Branches (8)
    'beq', 'bne', 'blt', 'ble', 'bgt', 'bge', 'blbs', 'blbc',

    # Jumps (4)
    'br', 'bsr', 'jmp', 'jsr', 'jsr_coroutine', 'ret',

    # Loads (7)
    'lda', 'ldah', 'ldl', 'ldq', 'ldq_u', 'ldbu', 'ldwu', 'ldl_l', 'ldq_l',

    # Stores (6)
    'stl', 'stq', 'stb', 'stw', 'stl_c', 'stq_c',

    # Byte manipulation - extract (7)
    'extbl', 'extwl', 'extll', 'extql', 'extwh', 'extlh', 'extqh',

    # Byte manipulation - insert (7)
    'insbl', 'inswl', 'insll', 'insql', 'inswh', 'inslh', 'insqh',

    # Byte manipulation - other (4)
    'unpkbl', 'unpkbw', 'pklb', 'pkwb',

    # Count/population (2)
    'ctpop', 'ctlz',

    # Min/Max (8)
    'minsb8', 'minsw4', 'minub8', 'minuw4',
    'maxsb8', 'maxsw4', 'maxub8', 'maxuw4',

    # Permute (1)
    'perr',

    # Memory barriers (4)
    'mb', 'wmb', 'trapb', 'excb',

    # Privileged/HW (3)
    'hw_ld', 'hw_st', 'implver',
]

# Alpha IEEE floating-point instructions
ALPHA_FP_INSTRUCTIONS = [
    # Single precision arithmetic (4)
    'adds', 'subs', 'muls', 'divs',

    # Double precision arithmetic (4)
    'addt', 'subt', 'mult', 'divt',

    # Square root (2)
    'sqrts', 'sqrtt',

    # Comparisons (3)
    'cmpteq', 'cmptlt', 'cmptle',

    # Conversions (4)
    'cvtts', 'cvttq', 'cvtqs', 'cvtqt',

    # Sign operations (3)
    'cpys', 'cpysn', 'cpyse',

    # Load/Store (4)
    'lds', 'ldt', 'sts', 'stt',

    # FPCR access (2)
    'mf_fpcr', 'mt_fpcr',

    # Integer-FP moves (2)
    'ftoit', 'itoft',
]

# Pseudo-instructions to exclude (gem5-specific, not real Alpha)
EXCLUDED_INSTRUCTIONS = {
    'initparam', 'm5a_getid', 'm5a_old', 'm5readfile', 'm5panic',
    'quiesce', 'quiesceTime', 'rpcc', 'rpns', 'rduniq', 'wruniq', 'rc', 'rs',
}


def apply_memory_transform(merged_graph):
    """Apply port width setting for 64-bit word-addressed memory."""
    # Alpha uses separate instruction and data memory
    for mem_name in ['imem', 'dmem']:
        mem_node = merged_graph.nodes.get(mem_name)
        if mem_node:
            access_widths = mem_node.data.get('access_widths', [64])
            max_width = max(access_widths) if access_widths else 64
            print(f"  {mem_name} access widths: {access_widths}, max: {max_width}")


def generate_verilog(merged_graph, module_name, output_dir):
    """Generate Verilog output."""
    from backends.verilog import generate_verilog_with_testbench

    testbench_config = {
        'timeout_cycles': 50000
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
        description='Generate complete Alpha64 processor from ISA definitions'
    )
    parser.add_argument(
        '--output-dir', '-o',
        default='examples/verilog/alpha64',
        help='Output directory (default: examples/verilog/alpha64)'
    )
    parser.add_argument(
        '--module-name', '-m',
        default='alpha64_complete',
        help='Module name (default: alpha64_complete)'
    )
    args = parser.parse_args()

    module_name = args.module_name
    output_dir = args.output_dir

    # Filter out excluded instructions
    int_instructions = [i for i in ALPHA_INTEGER_INSTRUCTIONS if i not in EXCLUDED_INSTRUCTIONS]
    fp_instructions = [i for i in ALPHA_FP_INSTRUCTIONS if i not in EXCLUDED_INSTRUCTIONS]

    print("=" * 70)
    print("Alpha64 Complete Processor Generator")
    print("=" * 70)
    print(f"\nGenerating Alpha64 processor with {len(int_instructions) + len(fp_instructions)} instructions...")
    print(f"  Integer:  {len(int_instructions)} instructions")
    print(f"  FP:       {len(fp_instructions)} instructions")

    # Step 1: Parse and merge ISA files
    print("\n" + "=" * 70)
    print("Step 1: Parsing and merging ISA files...")
    print("=" * 70)

    # Map instruction names to file paths
    isa_files = {}
    missing = []

    for instr in int_instructions:
        path = f"isa/alpha64/{instr}.isa"
        if os.path.exists(path):
            isa_files[instr] = path
        else:
            missing.append(instr)

    for instr in fp_instructions:
        path = f"isa/alpha64/f/{instr}.isa"
        if os.path.exists(path):
            isa_files[instr] = path
        else:
            missing.append(instr)

    if missing:
        print(f"  Warning: Missing ISA files for: {missing}")

    print(f"  Found {len(isa_files)} ISA files")

    try:
        merged_graph = merge_instructions(isa_files)
        print(f"  Successfully merged {len(isa_files)} instructions")
        print(f"  Merged graph has {len(merged_graph.nodes)} nodes and {len(merged_graph.edges)} edges")
    except Exception as e:
        print(f"  Error merging instructions: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Step 2: Apply memory transformations
    print("\n" + "=" * 70)
    print("Step 2: Checking memory access widths...")
    print("=" * 70)
    apply_memory_transform(merged_graph)

    # Step 3: Mark FP div/sqrt as multi-cycle
    print("\n" + "=" * 70)
    print("Step 3: Marking FP div/sqrt as multi-cycle...")
    print("=" * 70)
    for op_id in ['fp_div(f1, f2)', 'fp_div_d(f1, f2)', 'fp_sqrt(f1)', 'fp_sqrt_d(f1)']:
        if op_id in merged_graph.nodes:
            node = merged_graph.nodes[op_id]
            node.data['multi_cycle'] = True
            node.data['latency_cycles'] = 10
            print(f"  Marked {op_id} as multi-cycle (10 cycles)")

    # Step 4: Generate RTL
    print("\n" + "=" * 70)
    print("Step 4: Generating Verilog RTL and testbench...")
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
    print(f"  Successfully generated complete Alpha64 processor")
    print(f"  {len(int_instructions)} integer instructions implemented")
    print(f"  {len(fp_instructions)} FP instructions implemented")
    print(f"  {len(merged_graph.nodes)} nodes in merged graph")
    print(f"  {len(merged_graph.edges)} edges in merged graph")
    print(f"  Output: {output_dir}/")

    print("\nKey features:")
    print("  - 64-bit register file (r0-r31, r31=zero)")
    print("  - 64-bit program counter")
    print("  - 64-bit FP register file (f0-f31)")
    print("  - IEEE 754 single and double precision FP")
    print("  - All integer, logical, shift, compare operations")
    print("  - Branch, jump, and subroutine call support")
    print("  - Byte manipulation (extract, insert, pack, unpack)")
    print("  - Load-linked/store-conditional atomics")
    print("  - Memory barriers (MB, WMB, TRAPB, EXCB)")

    print("\n" + "=" * 70)
    print("Done!")
    print("=" * 70)


if __name__ == "__main__":
    main()
