#!/usr/bin/env python3
"""
Comprehensive test of all 36 RISC-V RV32I instructions for ILA vs ISA equivalence.
"""

import sys
import os
from pathlib import Path

_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_root))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from riscv_smt_equivalence import check_riscv_equivalence

# All 36 RISC-V RV32I instructions
INSTRUCTIONS = [
    # Arithmetic
    'add', 'addi', 'sub',
    # Logical
    'and', 'andi', 'or', 'ori', 'xor', 'xori',
    # Shift
    'sll', 'slli', 'srl', 'srli', 'sra', 'srai',
    # Comparison
    'slt', 'slti', 'sltu', 'sltiu',
    # Branch
    'beq', 'bne', 'blt', 'bltu', 'bge', 'bgeu',
    # Jump
    'jal', 'jalr',
    # Load
    'lb', 'lbu', 'lh', 'lhu', 'lw',
    # Store
    'sb', 'sh', 'sw',
    # Upper immediate
    'lui', 'auipc',
]

def test_all_instructions():
    """Test all 36 RISC-V instructions."""
    results = []

    for instr in sorted(INSTRUCTIONS):
        ila_file = f'frontends/ila/test_data/riscv/individual/riscv_{instr}.json'
        isa_file = f'isa/riscv32/{instr}.isa'

        # Check if files exist
        if not os.path.exists(ila_file):
            results.append((instr.upper(), 'SKIP', f'ILA file not found: {ila_file}'))
            continue

        if not os.path.exists(isa_file):
            results.append((instr.upper(), 'SKIP', f'ISA file not found: {isa_file}'))
            continue

        print(f"\n{'='*70}")
        print(f"Testing {instr.upper()}...")
        print(f"{'='*70}")

        try:
            result, message = check_riscv_equivalence(ila_file, isa_file)

            # Categorize the result
            if result:
                status = 'PASS'
                summary = 'PROVEN EQUIVALENT (UNSAT)'
            elif 'timeout' in message.lower():
                status = 'TIMEOUT'
                summary = 'Solver timeout (>60s)'
            elif 'error' in message.lower() and ('sort' in message.lower() or 'incompatible' in message.lower()):
                status = 'SMT_ERROR'
                summary = 'SMT generation error (width mismatch)'
            elif 'counterexample' in message.lower():
                status = 'COUNTEREX'
                summary = 'Counterexample found (SAT)'
            else:
                status = 'FAIL'
                summary = message.split('\n')[0] if '\n' in message else message[:60]

            results.append((instr.upper(), status, summary))
            print(f"Result: {status} - {summary}")

        except Exception as e:
            status = 'ERROR'
            summary = str(e)[:100]
            results.append((instr.upper(), status, summary))
            print(f"ERROR: {summary}")

    # Print summary
    print("\n" + "="*80)
    print("COMPREHENSIVE TEST RESULTS - ALL 36 RISC-V RV32I INSTRUCTIONS")
    print("="*80)

    # Group by status
    by_status = {}
    for instr, status, summary in results:
        if status not in by_status:
            by_status[status] = []
        by_status[status].append((instr, summary))

    # Print by category
    for status in ['PASS', 'TIMEOUT', 'SMT_ERROR', 'COUNTEREX', 'FAIL', 'ERROR', 'SKIP']:
        if status in by_status:
            print(f"\n{status} ({len(by_status[status])}):")
            for instr, summary in sorted(by_status[status]):
                print(f"  {instr:8} - {summary[:60]}")

    # Print counts
    print("\n" + "="*80)
    print("SUMMARY COUNTS:")
    print("="*80)
    pass_count = len(by_status.get('PASS', []))
    timeout_count = len(by_status.get('TIMEOUT', []))
    smt_error_count = len(by_status.get('SMT_ERROR', []))
    counterex_count = len(by_status.get('COUNTEREX', []))
    fail_count = len(by_status.get('FAIL', []))
    error_count = len(by_status.get('ERROR', []))
    skip_count = len(by_status.get('SKIP', []))
    total = len(results)

    print(f"  ✓ PASS (proven equivalent):     {pass_count:2d}/{total} ({100*pass_count/total:.1f}%)")
    print(f"  ⏱ TIMEOUT (solver >60s):        {timeout_count:2d}/{total} ({100*timeout_count/total:.1f}%)")
    print(f"  ⚠ SMT_ERROR (width mismatch):   {smt_error_count:2d}/{total} ({100*smt_error_count/total:.1f}%)")
    print(f"  ✗ COUNTEREX (not equivalent):   {counterex_count:2d}/{total} ({100*counterex_count/total:.1f}%)")
    print(f"  ✗ FAIL (other):                 {fail_count:2d}/{total} ({100*fail_count/total:.1f}%)")
    print(f"  ⚠ ERROR (exception):            {error_count:2d}/{total} ({100*error_count/total:.1f}%)")
    print(f"  ⊘ SKIP (missing files):         {skip_count:2d}/{total} ({100*skip_count/total:.1f}%)")
    print("="*80)

    # Determine overall status
    if pass_count == total:
        print("\n🎉 ALL TESTS PASSED! All instructions are proven equivalent!")
        return 0
    else:
        print(f"\n⚠️  {total - pass_count} instructions still need fixing")
        return 1

if __name__ == '__main__':
    sys.exit(test_all_instructions())
