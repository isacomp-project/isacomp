#!/usr/bin/env python3
"""
Run multiple i486/80386 tests against the merged design.
Uses the SingleStepTests submodule for test data.
Supports Verilator (preferred) or Icarus Verilog.
"""

import subprocess
import sys
import csv
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# Get project root and script directory
script_dir = Path(__file__).parent
project_root = script_dir.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(script_dir))

# Import from our test runner
from run_i486_merged_test import (
    load_tests, run_test_verilator, run_test_iverilog,
    MERGED_VERILOG, TEST_DIR, BUILD_DIR
)

# Check for Verilator
HAS_VERILATOR = shutil.which('verilator') is not None


def get_instructions_in_merged_design():
    """Extract list of instructions available in the merged design."""
    instructions = set()

    if not MERGED_VERILOG.exists():
        return instructions

    with open(MERGED_VERILOG) as f:
        for line in f:
            if '_enable' in line and 'wire' in line:
                parts = line.strip().split()
                for part in parts:
                    if '_enable' in part:
                        name = part.rstrip(';').rstrip(',')
                        if name.endswith('_enable'):
                            instr = name[:-7]
                            if instr and not instr.startswith('('):
                                instructions.add(instr)
                        break

    return instructions


def find_test_file(opcode_hex):
    """Find test file for a given opcode hex string."""
    # Try exact match
    test_file = TEST_DIR / f"{opcode_hex}.MOO.gz"
    if test_file.exists():
        return test_file

    # Try uppercase
    test_file = TEST_DIR / f"{opcode_hex.upper()}.MOO.gz"
    if test_file.exists():
        return test_file

    return None


def run_single_test(test, merged_verilog, build_dir, use_iverilog=False, verbose=False):
    """Run a single test."""
    if use_iverilog or not HAS_VERILATOR:
        return run_test_iverilog(test, merged_verilog, build_dir, verbose)
    else:
        return run_test_verilator(test, merged_verilog, build_dir, verbose)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Run multiple tests on merged i486 design')
    parser.add_argument('--opcodes', '-o', nargs='+',
                        help='Specific opcode hex values to test (e.g., 01 09 0B)')
    parser.add_argument('--all', '-a', action='store_true',
                        help='Test all available opcodes')
    parser.add_argument('--max-tests', '-n', type=int, default=5,
                        help='Max tests per opcode (default: 5)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show detailed output')
    parser.add_argument('--use-iverilog', action='store_true',
                        help='Force use of Icarus Verilog instead of Verilator')
    parser.add_argument('--parallel', '-p', type=int, default=1,
                        help='Number of parallel tests (default: 1)')
    parser.add_argument('--output', help='Output CSV file for results')
    parser.add_argument('--list', action='store_true',
                        help='List available test files')

    args = parser.parse_args()

    # List available tests
    if args.list:
        print(f"Test files in {TEST_DIR}:")
        for f in sorted(TEST_DIR.glob("*.MOO.gz")):
            print(f"  {f.stem}")
        return 0

    # Check merged design exists
    if not MERGED_VERILOG.exists():
        print(f"Error: Merged Verilog not found: {MERGED_VERILOG}")
        print("Run: python3 i486/generators/regen_i486_targeted.py")
        sys.exit(1)

    # Get opcodes to test
    if args.all:
        test_files = sorted(TEST_DIR.glob("*.MOO.gz"))
        opcodes = [f.stem for f in test_files]
    elif args.opcodes:
        opcodes = args.opcodes
    else:
        # Default: test a few common opcodes
        opcodes = ['01', '09', '0B', '31', '39']

    use_iverilog = args.use_iverilog or not HAS_VERILATOR

    if not HAS_VERILATOR and not args.use_iverilog:
        print("Note: Verilator not found, using Icarus Verilog")

    results = []
    passed = 0
    failed = 0
    skipped = 0

    print(f"\nTesting {len(opcodes)} opcode(s) against merged design")
    print(f"Max {args.max_tests} tests per opcode")
    print(f"Using: {'Icarus Verilog' if use_iverilog else 'Verilator'}")
    print("-" * 60)

    for opcode in opcodes:
        test_file = find_test_file(opcode)

        if test_file is None:
            if args.verbose:
                print(f"[SKIP] {opcode}: No test file found")
            skipped += 1
            results.append({'opcode': opcode, 'status': 'SKIP', 'reason': 'No test file'})
            continue

        # Load tests
        try:
            tests = load_tests(str(test_file))
        except Exception as e:
            print(f"[ERROR] {opcode}: Failed to load tests: {e}")
            failed += 1
            results.append({'opcode': opcode, 'status': 'ERROR', 'reason': str(e)})
            continue

        # Run limited number of tests
        num_tests = min(args.max_tests, len(tests))
        opcode_passed = 0
        opcode_failed = 0

        for test_idx in range(num_tests):
            test = tests[test_idx]
            build_dir = BUILD_DIR / f"test_{opcode}_{test_idx}"

            success, output = run_single_test(
                test, MERGED_VERILOG, build_dir,
                use_iverilog=use_iverilog, verbose=args.verbose
            )

            if success:
                opcode_passed += 1
                passed += 1
            else:
                opcode_failed += 1
                failed += 1
                if args.verbose:
                    print(f"  Test {test_idx}: FAIL")
                    print(f"    {output[:200]}...")

        status = "PASS" if opcode_failed == 0 else f"FAIL ({opcode_failed}/{num_tests})"
        print(f"[{status}] {opcode}: {opcode_passed}/{num_tests} tests passed")

        results.append({
            'opcode': opcode,
            'status': 'PASS' if opcode_failed == 0 else 'FAIL',
            'passed': opcode_passed,
            'failed': opcode_failed,
            'total': num_tests
        })

    print("-" * 60)
    print(f"\nResults: {passed} passed, {failed} failed, {skipped} skipped")
    total = passed + failed + skipped
    print(f"Total: {total}")

    # Write CSV if requested
    if args.output:
        with open(args.output, 'w', newline='') as f:
            fieldnames = ['opcode', 'status', 'passed', 'failed', 'total', 'reason']
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(results)
        print(f"\nResults written to: {args.output}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == '__main__':
    main()
