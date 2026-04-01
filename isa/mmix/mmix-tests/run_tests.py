#!/usr/bin/env python3
"""
MMIX Test Runner

Runs MMIX ISA tests against the generated processor using iverilog.
"""

import sys
import os
import subprocess
import shutil
from pathlib import Path

# Add parent directories to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

# List of tests to run
TESTS = [
    'add', 'sub', 'and', 'or', 'xor', 'sli', 'srui', 'setl', 'bz', 'bnz'
]


def convert_hex_to_memfile(hex_file, mem_file, data_width=64):
    """Convert a .hex file with 32-bit instructions to a memory hex file.

    For 64-bit memory, we pack two 32-bit instructions per line.
    """
    with open(hex_file, 'r') as f:
        lines = f.readlines()

    # Extract hex values (skip comments)
    hex_values = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith('//'):
            # Handle both raw hex and potentially commented lines
            parts = line.split()
            if parts:
                hex_val = parts[0]
                if all(c in '0123456789ABCDEFabcdef' for c in hex_val):
                    hex_values.append(hex_val.upper())

    # Write memory file
    with open(mem_file, 'w') as f:
        if data_width == 64:
            # Pack two 32-bit instructions per 64-bit word
            for i in range(0, len(hex_values), 2):
                if i + 1 < len(hex_values):
                    # Big-endian: first instruction in high word
                    word = hex_values[i] + hex_values[i + 1]
                else:
                    word = hex_values[i] + '00000000'
                f.write(f"{word}\n")
        else:
            # 32-bit memory
            for hex_val in hex_values:
                f.write(f"{hex_val}\n")


def run_test(test_name, processor_dir, test_dir, verbose=False):
    """Run a single test."""
    test_hex = Path(test_dir) / f"{test_name}.hex"
    if not test_hex.exists():
        print(f"  SKIP: {test_name} (no test file)")
        return None

    # Create working directory
    work_dir = Path(processor_dir) / "work"
    work_dir.mkdir(exist_ok=True)

    # Convert test hex to memory file
    mem_file = work_dir / "umem.hex"
    convert_hex_to_memfile(test_hex, mem_file, data_width=64)

    # Copy Verilog files to work directory
    rtl_file = Path(processor_dir) / "mmix_complete.v"
    tb_file = Path(processor_dir) / "mmix_complete_tb.sv"

    if not rtl_file.exists():
        print(f"  FAIL: {test_name} (no RTL file)")
        return False

    shutil.copy(rtl_file, work_dir)
    if tb_file.exists():
        shutil.copy(tb_file, work_dir)

    # Compile with iverilog
    compile_cmd = [
        'iverilog', '-g2012', '-o', 'sim.vvp',
        'mmix_complete.v', 'mmix_complete_tb.sv'
    ]

    try:
        result = subprocess.run(
            compile_cmd,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode != 0:
            if verbose:
                print(f"  Compile error: {result.stderr}")
            print(f"  FAIL: {test_name} (compile error)")
            return False
    except subprocess.TimeoutExpired:
        print(f"  FAIL: {test_name} (compile timeout)")
        return False
    except FileNotFoundError:
        print(f"  FAIL: {test_name} (iverilog not found)")
        return False

    # Run simulation
    # Pass addresses: 0x20 for most tests (the pass: label)
    # Fail addresses: 0x24 for most tests
    sim_cmd = [
        'vvp', 'sim.vvp',
        '+pass_addr=0000000000000020',
        '+fail_addr=0000000000000024'
    ]

    try:
        result = subprocess.run(
            sim_cmd,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=30
        )

        output = result.stdout + result.stderr

        if 'TEST PASSED' in output:
            print(f"  PASS: {test_name}")
            return True
        elif 'TEST FAILED' in output:
            if verbose:
                print(f"  Output: {output}")
            print(f"  FAIL: {test_name} (test failed)")
            return False
        elif 'TIMEOUT' in output:
            if verbose:
                print(f"  Output: {output}")
            print(f"  FAIL: {test_name} (simulation timeout)")
            return False
        else:
            if verbose:
                print(f"  Output: {output}")
            print(f"  UNKNOWN: {test_name}")
            return None
    except subprocess.TimeoutExpired:
        print(f"  FAIL: {test_name} (vvp timeout)")
        return False
    except Exception as e:
        print(f"  FAIL: {test_name} ({e})")
        return False


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Run MMIX ISA tests')
    parser.add_argument('--processor-dir', '-p',
                        default='examples/verilog/mmix_complete',
                        help='Directory containing generated processor')
    parser.add_argument('--test-dir', '-t',
                        default='isa/mmix/mmix-tests/isa',
                        help='Directory containing test hex files')
    parser.add_argument('--tests', '-T', nargs='+',
                        default=TESTS,
                        help='Tests to run')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output')
    args = parser.parse_args()

    print("=" * 60)
    print("MMIX ISA Test Runner")
    print("=" * 60)
    print(f"Processor: {args.processor_dir}")
    print(f"Tests: {args.test_dir}")
    print()

    passed = 0
    failed = 0
    skipped = 0

    for test in args.tests:
        result = run_test(test, args.processor_dir, args.test_dir, args.verbose)
        if result is True:
            passed += 1
        elif result is False:
            failed += 1
        else:
            skipped += 1

    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
