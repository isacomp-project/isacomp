#!/usr/bin/env python3
"""
Generate complete OpenRISC OR1K processor (without MMU).
Includes all Orbis32 + ORFPX32 instructions needed for NOMMU Linux.
"""
import sys
import os
import argparse
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core.graph_merger import ResourceGraphMerger
from backends.verilog import generate_verilog_with_testbench

# Complete OR1K Orbis32 instruction set
INSTRUCTIONS = [
    # Arithmetic (8)
    'l.add', 'l.addi', 'l.sub', 'l.mul', 'l.mulu', 'l.div', 'l.divu',
    'l.muli',

    # Logical (6)
    'l.and', 'l.andi', 'l.or', 'l.ori', 'l.xor', 'l.xori',

    # Shifts (8)
    'l.sll', 'l.srl', 'l.sra', 'l.slli', 'l.srli', 'l.srai',
    'l.ror', 'l.rori',

    # Data transfer (2)
    'l.movhi', 'l.cmov',

    # Sign/zero extension (6)
    'l.extbs', 'l.extbz', 'l.exths', 'l.exthz', 'l.extws', 'l.extwz',

    # Bit manipulation (2)
    'l.ff1', 'l.fl1',

    # Compare register (10)
    'l.sfeq', 'l.sfne', 'l.sfgtu', 'l.sfgeu', 'l.sfltu', 'l.sfleu',
    'l.sfgts', 'l.sfges', 'l.sflts', 'l.sfles',

    # Compare immediate (10)
    'l.sfeqi', 'l.sfnei', 'l.sfgtui', 'l.sfgeui', 'l.sfltui', 'l.sfleui',
    'l.sfgtsi', 'l.sfgesi', 'l.sfltsi', 'l.sflesi',

    # Branch (6)
    'l.j', 'l.jal', 'l.jalr', 'l.jr', 'l.bf', 'l.bnf',

    # Load (5)
    'l.lw', 'l.lbz', 'l.lbs', 'l.lhz', 'l.lhs',

    # Store (3)
    'l.sw', 'l.sb', 'l.sh',

    # Atomic (2)
    'l.lwa', 'l.swa',

    # System (8)
    'l.mtspr', 'l.mfspr', 'l.sys', 'l.trap', 'l.rfe',
    'l.msync', 'l.psync', 'l.csync',

    # NOP (1)
    'l.nop',
]

# ORFPX32 single-precision floating-point instructions
FP_INSTRUCTIONS = [
    # FP Arithmetic (8)
    'lf.add.s', 'lf.sub.s', 'lf.mul.s', 'lf.div.s',
    'lf.itof.s', 'lf.ftoi.s', 'lf.rem.s', 'lf.madd.s',

    # FP Compare (6)
    'lf.sfeq.s', 'lf.sfne.s', 'lf.sfgt.s', 'lf.sfge.s',
    'lf.sflt.s', 'lf.sfle.s',
]


def main():
    parser = argparse.ArgumentParser(
        description='Generate OpenRISC OR1K NOMMU processor from ISA definitions'
    )
    parser.add_argument(
        '--no-fp', action='store_true',
        help='Exclude floating-point instructions (ORFPX32)'
    )
    args = parser.parse_args()

    all_instructions = list(INSTRUCTIONS)
    if not args.no_fp:
        all_instructions.extend(FP_INSTRUCTIONS)

    print("=" * 70)
    print("OpenRISC OR1K COMPLETE PROCESSOR GENERATOR")
    print("=" * 70)
    print(f"Total instructions: {len(all_instructions)}")
    if not args.no_fp:
        print(f"  Including ORFPX32 FP: {len(FP_INSTRUCTIONS)} instructions")
    print("=" * 70)

    isa_dir = os.path.join(os.path.dirname(__file__), '..')

    print("\nParsing and merging ISA files...")
    merger = ResourceGraphMerger()

    for instr_name in all_instructions:
        isa_file = os.path.join(isa_dir, f"{instr_name}.isa")
        if not os.path.exists(isa_file):
            print(f"  WARNING: File not found for {instr_name}, skipping")
            continue
        success = merger.add_instruction(instr_name, isa_file)
        if not success:
            print(f"  WARNING: Failed to add instruction {instr_name}")
            continue

    merged_graph = merger.merge_graphs()
    print(f"\nMerged graph has {len(merged_graph.nodes)} nodes and {len(merged_graph.edges)} edges")

    output_dir = os.path.join(os.path.dirname(__file__), '../../../examples/verilog/or1k_complete')
    print(f"\nGenerating Verilog to {output_dir}/...")
    testbench_config = {
        'timeout_cycles': 10000
    }

    files = generate_verilog_with_testbench(
        merged_graph,
        module_name='or1k_complete',
        output_dir=output_dir,
        testbench_config=testbench_config
    )

    print("\nGenerated files:")
    for key, path in files.items():
        print(f"  {key.upper()}: {path}")

    print(f"\nDone! Generated OR1K complete processor ({len(all_instructions)} instructions)")
    return merged_graph


if __name__ == '__main__':
    main()
