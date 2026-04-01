#!/usr/bin/env python3
"""
Generate RV32IM processor with M extension.
Combines RV32I base integer instructions with integer multiplication and division.
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

# M extension instructions (8 instructions)
m_instructions = [
    'mul',     # Multiply lower 32 bits
    'mulh',    # Multiply high signed×signed
    'mulhsu',  # Multiply high signed×unsigned
    'mulhu',   # Multiply high unsigned×unsigned
    'div',     # Signed division
    'divu',    # Unsigned division
    'rem',     # Signed remainder
    'remu',    # Unsigned remainder
]

all_instructions = rv32i_instructions + m_instructions

print(f"Generating RV32IM processor with {len(all_instructions)} instructions...")
print(f"  RV32I: {len(rv32i_instructions)} instructions")
print(f"  M extension: {len(m_instructions)} instructions")

print("\nParsing and merging ISA files...")
# Get the project root directory (two levels up from this script)
project_root = os.path.join(os.path.dirname(__file__), '../..')

# Build instruction file paths
isa_files = {}
for instr in rv32i_instructions:
    isa_files[instr] = os.path.join(project_root, f"riscv32/{instr}.isa")
for instr in m_instructions:
    isa_files[instr] = os.path.join(project_root, f"riscv32/m/{instr}.isa")

# Merge all instructions
merged_graph = merge_instructions(isa_files)
print(f"Merged graph has {len(merged_graph.nodes)} nodes and {len(merged_graph.edges)} edges")

print(f"\nGenerating Verilog to examples/verilog/riscv32im/...")
testbench_config = {
    'timeout_cycles': 10000,
    'dmem_name': 'dmem'
}

files = generate_verilog_with_testbench(
    merged_graph,
    module_name='riscv32im',
    output_dir=os.path.join(project_root, 'examples/verilog/riscv32im'),
    testbench_config=testbench_config
)

print("\nGenerated files:")
for key, path in files.items():
    print(f"  {key.upper()}: {path}")

print(f"\nDone! Generated RV32IM processor with {len(all_instructions)} instructions")
print("\nM extension provides hardware multiply and divide:")
print("  - MUL/MULH/MULHSU/MULHU: 32-bit and 64-bit multiplication")
print("  - DIV/DIVU: Signed and unsigned division")
print("  - REM/REMU: Signed and unsigned remainder")
