#!/usr/bin/env python3
"""
Comprehensive SMT Verification: ILA vs ISA for All RV32I Instructions

This script verifies that all 36 extracted ILA instructions from real RISC-V
cores (Pico/Piccolo/Rocket) are semantically equivalent to the ISAComp ISA
specifications using Z3 SMT solver.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.resource_graph import ResourceGraph
from verif.smt.smt_verification import verify_optimization
import time
from pathlib import Path


# All 36 RV32I instructions (SRA missing from ISA files)
ALL_INSTRUCTIONS = [
    # Arithmetic
    ('ADD', 'add'),
    ('ADDI', 'addi'),
    ('SUB', 'sub'),

    # Logical
    ('AND', 'and'),
    ('ANDI', 'andi'),
    ('OR', 'or'),
    ('ORI', 'ori'),
    ('XOR', 'xor'),
    ('XORI', 'xori'),

    # Shift
    ('SLL', 'sll'),
    ('SLLI', 'slli'),
    ('SRL', 'srl'),
    ('SRLI', 'srli'),
    ('SRAI', 'srai'),
    # ('SRA', 'sra'),  # No ISA file

    # Compare
    ('SLT', 'slt'),
    ('SLTI', 'slti'),
    ('SLTU', 'sltu'),
    ('SLTIU', 'sltiu'),

    # Branch
    ('BEQ', 'beq'),
    ('BNE', 'bne'),
    ('BLT', 'blt'),
    ('BLTU', 'bltu'),
    ('BGE', 'bge'),
    ('BGEU', 'bgeu'),

    # Jump
    ('JAL', 'jal'),
    ('JALR', 'jalr'),

    # Load
    ('LW', 'lw'),
    ('LH', 'lh'),
    ('LB', 'lb'),
    ('LHU', 'lhu'),
    ('LBU', 'lbu'),

    # Store
    ('SW', 'sw'),
    ('SH', 'sh'),
    ('SB', 'sb'),

    # Upper Immediate
    ('LUI', 'lui'),
    ('AUIPC', 'auipc'),
]


def test_instruction(instr_name: str, isa_basename: str, verbose: bool = False) -> dict:
    """
    Verify a single instruction using SMT.

    Args:
        instr_name: Display name (e.g., "ADD")
        isa_basename: ISA file basename (e.g., "add")
        verbose: Print detailed output

    Returns:
        Dict with 'status', 'duration', 'error', 'isa_nodes', 'ila_nodes'
    """
    isa_file = f'isa/riscv32/{isa_basename}.isa'
    ila_file = f'ila/test_data/riscv/individual/riscv_{isa_basename}.json'

    result = {
        'status': 'unknown',
        'duration': 0.0,
        'error': None,
        'isa_nodes': 0,
        'ila_nodes': 0,
    }

    if verbose:
        print(f"\n  Testing {instr_name}:")
        print(f"    ISA: {isa_file}")
        print(f"    ILA: {ila_file}")
    else:
        print(f"  {instr_name:6s} ", end='', flush=True)

    try:
        # Check files exist
        if not Path(isa_file).exists():
            result['status'] = 'skip'
            result['error'] = f'ISA file not found'
            if verbose:
                print(f"    ⚠ SKIP: {result['error']}")
            else:
                print(f"⚠ SKIP (no ISA)")
            return result

        if not Path(ila_file).exists():
            result['status'] = 'skip'
            result['error'] = f'ILA file not found'
            if verbose:
                print(f"    ⚠ SKIP: {result['error']}")
            else:
                print(f"⚠ SKIP (no ILA)")
            return result

        # Load ISA specification
        isa_graph = ResourceGraph.from_isa_file(isa_file)
        result['isa_nodes'] = isa_graph.get_node_count()
        if verbose:
            print(f"    ISA graph: {result['isa_nodes']} nodes")
        else:
            print(f"ISA:{result['isa_nodes']:4d} ", end='', flush=True)

        # Load ILA JSON
        ila_graph = ResourceGraph.from_ila_json_file(ila_file)
        result['ila_nodes'] = ila_graph.get_node_count()
        if verbose:
            print(f"    ILA graph: {result['ila_nodes']} nodes")
        else:
            print(f"ILA:{result['ila_nodes']:4d} ", end='', flush=True)

        # Run SMT verification
        start = time.time()
        is_equiv, details = verify_optimization(
            isa_graph, ila_graph,
            isa_file_path=isa_file,
            solver='z3'
        )
        result['duration'] = time.time() - start

        if is_equiv:
            result['status'] = 'pass'
            if verbose:
                print(f"    ✓ EQUIVALENT ({result['duration']:.2f}s)")
            else:
                print(f"✓ ({result['duration']:5.2f}s)")
        else:
            result['status'] = 'fail'
            result['error'] = details[:200] if details else "Not equivalent"
            if verbose:
                print(f"    ✗ NOT EQUIVALENT ({result['duration']:.2f}s)")
                print(f"      Reason: {result['error']}")
            else:
                print(f"✗ FAIL ({result['duration']:5.2f}s)")

    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)[:200]
        if verbose:
            print(f"    ✗ ERROR: {result['error']}")
        else:
            print(f"✗ ERROR: {str(e)[:40]}")

    return result


def print_category_header(category: str):
    """Print a category header."""
    print(f"\n{'─' * 80}")
    print(f"  {category}")
    print(f"{'─' * 80}")


def main():
    """Run comprehensive SMT verification for all RV32I instructions."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Comprehensive SMT verification of ILA vs ISA for all RV32I instructions'
    )
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Verbose output with detailed information')
    parser.add_argument('--category', '-c',
                       choices=['arithmetic', 'logical', 'shift', 'compare', 'branch', 'jump', 'load', 'store', 'upper'],
                       help='Test only specific category')
    parser.add_argument('--instruction', '-i',
                       help='Test only specific instruction (e.g., ADD)')

    args = parser.parse_args()

    print("=" * 80)
    print("COMPREHENSIVE SMT VERIFICATION: ILA vs ISA")
    print("Testing all extracted RISC-V RV32I instructions from real cores")
    print("=" * 80)
    print()
    print("Source:")
    print("  ISA Specs: riscv32/*.isa (ISAComp specifications)")
    print("  ILA Models: ila/test_data/riscv/individual/*.json (from Pico/Piccolo/Rocket)")
    print()
    print("Method: Z3 SMT Solver proving semantic equivalence")
    print("=" * 80)

    # Categorize instructions
    categories = {
        'arithmetic': [('ADD', 'add'), ('ADDI', 'addi'), ('SUB', 'sub')],
        'logical': [('AND', 'and'), ('ANDI', 'andi'), ('OR', 'or'), ('ORI', 'ori'), ('XOR', 'xor'), ('XORI', 'xori')],
        'shift': [('SLL', 'sll'), ('SLLI', 'slli'), ('SRL', 'srl'), ('SRLI', 'srli'), ('SRAI', 'srai')],
        'compare': [('SLT', 'slt'), ('SLTI', 'slti'), ('SLTU', 'sltu'), ('SLTIU', 'sltiu')],
        'branch': [('BEQ', 'beq'), ('BNE', 'bne'), ('BLT', 'blt'), ('BLTU', 'bltu'), ('BGE', 'bge'), ('BGEU', 'bgeu')],
        'jump': [('JAL', 'jal'), ('JALR', 'jalr')],
        'load': [('LW', 'lw'), ('LH', 'lh'), ('LB', 'lb'), ('LHU', 'lhu'), ('LBU', 'lbu')],
        'store': [('SW', 'sw'), ('SH', 'sh'), ('SB', 'sb')],
        'upper': [('LUI', 'lui'), ('AUIPC', 'auipc')],
    }

    # Filter by arguments
    if args.instruction:
        # Test single instruction
        found = False
        for name, basename in ALL_INSTRUCTIONS:
            if name.lower() == args.instruction.lower():
                print_category_header(f"Single Instruction: {name}")
                result = test_instruction(name, basename, verbose=True)
                found = True
                break
        if not found:
            print(f"Instruction '{args.instruction}' not found")
            return 1
        return 0 if result['status'] == 'pass' else 1

    if args.category:
        # Test single category
        if args.category in categories:
            print_category_header(f"Category: {args.category.capitalize()}")
            results = []
            for name, basename in categories[args.category]:
                result = test_instruction(name, basename, verbose=args.verbose)
                results.append((name, result))
        else:
            print(f"Category '{args.category}' not found")
            return 1
    else:
        # Test all instructions by category
        results = []
        for cat_name, instrs in categories.items():
            print_category_header(f"{cat_name.capitalize()} Instructions")
            for name, basename in instrs:
                result = test_instruction(name, basename, verbose=args.verbose)
                results.append((name, result))

    # Print summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()

    # Count by status
    passed = sum(1 for _, r in results if r['status'] == 'pass')
    failed = sum(1 for _, r in results if r['status'] == 'fail')
    errors = sum(1 for _, r in results if r['status'] == 'error')
    skipped = sum(1 for _, r in results if r['status'] == 'skip')

    total_tested = passed + failed + errors
    total_time = sum(r['duration'] for _, r in results)

    print(f"  Total Instructions: {len(results)}")
    print(f"  ✓ Passed:  {passed:2d} ({100*passed/len(results) if results else 0:.1f}%)")
    print(f"  ✗ Failed:  {failed:2d} ({100*failed/len(results) if results else 0:.1f}%)")
    print(f"  ✗ Errors:  {errors:2d} ({100*errors/len(results) if results else 0:.1f}%)")
    print(f"  ⚠ Skipped: {skipped:2d} ({100*skipped/len(results) if results else 0:.1f}%)")
    print()
    print(f"  Total verification time: {total_time:.1f}s")
    print(f"  Average time per instruction: {total_time/total_tested if total_tested > 0 else 0:.2f}s")

    # List failures and errors
    if failed > 0 or errors > 0:
        print()
        print("Failed/Error Instructions:")
        for name, result in results:
            if result['status'] in ['fail', 'error']:
                print(f"  {name:6s}: {result['status'].upper()} - {result['error'][:60] if result['error'] else 'Unknown'}")

    print()

    if passed == len(results):
        print("🎉 PERFECT! All instructions verified equivalent!")
        print()
        print("This proves that:")
        print("  • ILA extraction from real cores is semantically correct")
        print("  • Individual instruction extraction preserves semantics")
        print("  • ISAComp ISA specs match real RISC-V implementations")
        return 0
    elif passed > 0 and failed == 0 and errors == 0:
        print(f"✓ SUCCESS! {passed} instructions verified equivalent (some skipped)")
        return 0
    elif passed > 0:
        print(f"⚠ PARTIAL: {passed}/{total_tested} instructions verified")
        print("Some instructions failed or had errors - review above for details")
        return 1
    else:
        print("✗ FAILED: No instructions verified successfully")
        return 1


if __name__ == "__main__":
    sys.exit(main())
