#!/usr/bin/env python3
"""
PDP-11 Test Suite Runner

Assembles test sources, compiles the processor, and runs tests.
Reports pass/fail status for each test.

Usage: python3 run_tests.py [test_name ...]
       python3 run_tests.py --all
"""

import os
import sys
import subprocess
import tempfile
import argparse
import re
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
SRC_DIR = SCRIPT_DIR / "isa_src"
HEX_DIR = SCRIPT_DIR / "isa"
VERILOG_DIR = SCRIPT_DIR.parent.parent.parent / "examples" / "verilog" / "pdp11_complete"
TB_FILE = SCRIPT_DIR / "simple_tb.sv"

# Test configurations: test_name -> (pass_pc, fail_pc)
# These are determined by examining the assembled code
# Pass PC is the address of 'pass: br pass' loop
# Fail PC is the address of 'fail: br fail' loop


def assemble_test(src_file: Path, hex_file: Path) -> bool:
    """Assemble a test source file to hex"""
    asm_script = SCRIPT_DIR / "pdp11_asm.py"
    try:
        result = subprocess.run(
            ["python3", str(asm_script), str(src_file), str(hex_file)],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            print(f"  Assembly error: {result.stderr}")
            return False
        return True
    except Exception as e:
        print(f"  Assembly exception: {e}")
        return False


def find_pass_fail_addrs(hex_file: Path) -> tuple:
    """
    Find the pass and fail addresses by scanning the hex file.
    We look for the BR loop pattern: instruction where
    the branch offset points to itself (-1 word = -2 bytes).

    BR opcode is 0x01xx where xx is the signed 8-bit offset.
    A self-loop has offset 0xFF (-1 word).
    So we look for 0x01FF.
    """
    with open(hex_file, 'r') as f:
        bytes_list = [int(line.strip(), 16) for line in f if line.strip()]

    # Find addresses of self-looping branches
    # BR opcode is 0x01xx where xx is offset (in words, 2's complement)
    # A self-loop has offset 0xFF (-1 word = -2 bytes), so look for 0x01FF
    pass_addr = None
    fail_addr = None

    for i in range(0, len(bytes_list) - 1, 2):
        lo = bytes_list[i]
        hi = bytes_list[i + 1]
        word = (hi << 8) | lo

        # Check for BR with offset -1 (0x01FF)
        if word == 0x01FF:
            if pass_addr is None:
                pass_addr = i
            else:
                fail_addr = i
                break

    if pass_addr is None or fail_addr is None:
        # Fallback: assume pass is at end-4, fail is at end-2
        pass_addr = len(bytes_list) - 4
        fail_addr = len(bytes_list) - 2

    return (pass_addr, fail_addr)


def run_test(test_name: str, work_dir: Path) -> bool:
    """Run a single test and return True if passed"""
    src_file = SRC_DIR / f"{test_name}.s"
    hex_file = HEX_DIR / f"{test_name}.hex"

    if not src_file.exists():
        print(f"  Source not found: {src_file}")
        return False

    # Assemble
    if not assemble_test(src_file, hex_file):
        return False

    # Find pass/fail addresses
    pass_addr, fail_addr = find_pass_fail_addrs(hex_file)

    # Copy hex to work dir as umem.hex
    umem_hex = work_dir / "umem.hex"
    subprocess.run(["cp", str(hex_file), str(umem_hex)], check=True)

    # Run simulation
    vvp_file = work_dir / "test.vvp"
    result = subprocess.run(
        ["vvp", str(vvp_file), f"+pass_addr={pass_addr:x}", f"+fail_addr={fail_addr:x}"],
        capture_output=True,
        text=True,
        cwd=work_dir
    )

    output = result.stdout + result.stderr

    # Check result
    if "PASSED" in output:
        return True
    elif "FAILED" in output:
        return False
    elif "TIMEOUT" in output:
        return False
    else:
        return False


def compile_processor(work_dir: Path) -> bool:
    """Compile the processor and testbench"""
    proc_file = SCRIPT_DIR / "pdp11_complete.v"
    tb_file = SCRIPT_DIR / "simple_tb.sv"
    vvp_file = work_dir / "test.vvp"

    result = subprocess.run(
        ["iverilog", "-g2012", "-o", str(vvp_file), str(tb_file), str(proc_file)],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        print(f"Compilation error: {result.stderr}")
        return False

    return True


def main():
    parser = argparse.ArgumentParser(description="Run PDP-11 tests")
    parser.add_argument("tests", nargs="*", help="Test names to run")
    parser.add_argument("--all", action="store_true", help="Run all tests")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    # Get list of tests
    if args.all:
        tests = sorted([f.stem for f in SRC_DIR.glob("*.s")])
    elif args.tests:
        tests = args.tests
    else:
        print("Usage: python3 run_tests.py [test_name ...] | --all")
        sys.exit(1)

    # Create work directory
    work_dir = Path(tempfile.mkdtemp(prefix="pdp11_tests_"))

    # Compile processor
    print("=== Compiling PDP-11 processor ===")
    if not compile_processor(work_dir):
        print("Failed to compile processor")
        sys.exit(1)
    print("Compilation successful")

    # Run tests
    print("\n=== Running PDP-11 Test Suite ===\n")
    passed = []
    failed = []

    for test in tests:
        print(f"{test}... ", end="", flush=True)
        if run_test(test, work_dir):
            print("PASS")
            passed.append(test)
        else:
            print("FAIL")
            failed.append(test)

    # Summary
    print(f"\n=== Test Summary ===")
    print(f"Passed: {len(passed)}")
    print(f"Failed: {len(failed)}")
    print(f"Total:  {len(tests)}")

    if failed:
        print(f"\nFailed tests: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
