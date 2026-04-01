#!/usr/bin/env python3
"""
Batch test runner for ILA-ISA verification with CVC5.

NOTE: Before running this test, you need to generate ILA JSON files:
    cd frontends/ila
    ./generate_ila_models.sh
    ./extract_all_individual_instructions.sh

This will create the required JSON files in frontends/ila/test_data/riscv/nibbler/
"""
import sys
import os
from pathlib import Path
_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_root))
os.chdir(str(_root))

from core.resource_graph import ResourceGraph
from verif.smt.smt_verification import verify_optimization
import time

# Get batch number and instructions from command line
batch_num = int(sys.argv[1])

batches = [
    ['add', 'addi', 'and', 'andi', 'auipc', 'beq', 'bge', 'bgeu'],
    ['blt', 'bltu', 'bne', 'jal', 'jalr', 'lb', 'lbu', 'lh'],
    ['lhu', 'lui', 'lw', 'or', 'ori', 'sb', 'sh', 'sll'],
    ['slli', 'slt', 'slti', 'sltiu', 'sltu', 'sra', 'srai', 'srl'],
    ['srli', 'sub', 'sw', 'xor', 'xori'],
    # Quick final run of just the stores that were failing
    ['sb', 'sh', 'sw']
]

instructions = batches[batch_num - 1]

print(f'Testing Batch {batch_num} ({len(instructions)} instructions) with CVC5:')
print('=' * 70)

pass_count = 0
fail_count = 0

for instr in instructions:
    print(f'{instr:6s}: ', end='', flush=True)
    start = time.time()
    try:
        isa_graph = ResourceGraph.from_isa_file(f'isa/riscv32/{instr}.isa')
        ila_graph = ResourceGraph.from_ila_json_file(f'frontends/ila/test_data/riscv/nibbler/riscv_{instr}.json')
        is_equiv, details = verify_optimization(isa_graph, ila_graph, isa_file_path=f'isa/riscv32/{instr}.isa', solver='cvc5')
        elapsed = time.time() - start

        if is_equiv:
            print(f'PASS ✓ ({elapsed:.1f}s)')
            pass_count += 1
        else:
            print(f'FAIL ✗ ({elapsed:.1f}s)')
            fail_count += 1
    except Exception as e:
        elapsed = time.time() - start
        print(f'ERROR ✗ ({elapsed:.1f}s): {str(e)[:50]}')
        fail_count += 1

print('=' * 70)
print(f'Batch {batch_num} Result: {pass_count}/{len(instructions)} passing')
