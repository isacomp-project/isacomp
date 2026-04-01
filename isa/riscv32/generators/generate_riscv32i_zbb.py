#!/usr/bin/env python3
"""
Generate RV32I processor with Zbb extension.
Combines RV32I base integer instructions with basic bit manipulation.
"""
import sys
import os

# Add parent directory to path so we can import from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from core.graph_merger import merge_instructions
from backends.verilog import generate_verilog_with_testbench

# RV32I base instructions (30 instructions)
rv32i_instructions = [
    # Arithmetic (5)
    'add', 'addi', 'sub', 'lui', 'auipc',

    # Logical (6)
    'and', 'andi', 'or', 'ori', 'xor', 'xori',

    # Shifts (5)
    'sll', 'slli', 'srl', 'srli', 'srai',

    # Compare (4)
    'slt', 'slti', 'sltu', 'sltiu',

    # Branches (6)
    'beq', 'bne', 'blt', 'bltu', 'bge', 'bgeu',

    # Jumps (2)
    'jal', 'jalr',

    # Loads/Stores (2)
    'lw', 'sw',
]

# Zbb extension instructions (15 instructions - partial implementation)
zbb_instructions = [
    # Bitwise with inversion (3)
    'andn', 'orn', 'xnor',
    # Min/Max (4)
    'max', 'maxu', 'min', 'minu',
    # Sign/Zero extend (3)
    'sext.b', 'sext.h', 'zext.h',
    # Rotate (3)
    'rol', 'ror', 'rori',
    # Byte operations (2)
    'orc.b', 'rev8',
]

all_instructions = rv32i_instructions + zbb_instructions

print(f"Generating RV32I+Zbb processor with {len(all_instructions)} instructions...")
print(f"  RV32I: {len(rv32i_instructions)} instructions")
print(f"  Zbb: {len(zbb_instructions)} instructions (15/18 - count instructions not implemented)")

print("\nParsing and merging ISA files...")
# Get the project root directory (two levels up from this script)
project_root = os.path.join(os.path.dirname(__file__), '../..')

# Build instruction file paths
isa_files = {}
for instr in rv32i_instructions:
    isa_files[instr] = os.path.join(project_root, f"riscv32/{instr}.isa")
for instr in zbb_instructions:
    isa_files[instr] = os.path.join(project_root, f"riscv32/zbb/{instr}.isa")

# Merge all instructions
merged_graph = merge_instructions(isa_files)
print(f"Merged graph has {len(merged_graph.nodes)} nodes and {len(merged_graph.edges)} edges")

print(f"\nGenerating Verilog to examples/verilog/riscv32i_zbb/...")
testbench_config = {
    'timeout_cycles': 10000,
    'dmem_name': 'dmem'
}

files = generate_verilog_with_testbench(
    merged_graph,
    module_name='riscv32i_zbb',
    output_dir=os.path.join(project_root, 'examples/verilog/riscv32i_zbb'),
    testbench_config=testbench_config
)

print("\nGenerated files:")
for key, path in files.items():
    print(f"  {key.upper()}: {path}")

print(f"\nDone! Generated RV32I+Zbb processor with {len(all_instructions)} instructions")
print("\nZbb provides basic bit manipulation:")
print("  - Bitwise ops with inversion (andn, orn, xnor)")
print("  - Min/Max operations (max, maxu, min, minu)")
print("  - Sign/Zero extension (sext.b, sext.h, zext.h)")
print("  - Rotate operations (rol, ror, rori)")
print("  - Byte operations (orc.b, rev8)")
print("\nNote: Count instructions (clz, ctz, cpop) require parser enhancements")
