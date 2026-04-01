#!/usr/bin/env python3
"""
Run 6502 ISAComp tests using Icarus Verilog.

This script:
1. Builds tests if needed
2. Compiles the processor with testbench
3. Runs each test and checks for pass/fail
4. Reports results
"""

import os
import sys
import subprocess
import argparse
import shutil
from pathlib import Path


# Configuration
SCRIPT_DIR = Path(__file__).parent.resolve()
VERILOG_DIR_PIPELINED = SCRIPT_DIR.parent.parent.parent / "examples" / "verilog" / "6502_pipelined_3stage"
VERILOG_DIR_SINGLECYCLE = SCRIPT_DIR.parent.parent.parent / "examples" / "verilog" / "6502_test"
TEST_DIR = SCRIPT_DIR / "bin"
DEFAULT_TIMEOUT = 30  # seconds


def run_command(cmd, cwd=None, timeout=None):
    """Run a command and return (success, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "TIMEOUT"
    except Exception as e:
        return False, "", str(e)


def build_tests():
    """Build all tests."""
    print("Building tests...")
    success, stdout, stderr = run_command(["./build_tests.sh"], cwd=str(SCRIPT_DIR))
    if not success:
        print(f"Build failed: {stderr}")
        return False
    print(stdout)
    return True


def get_test_list():
    """Get list of available tests."""
    if not TEST_DIR.exists():
        return []

    tests = []
    for hex_file in sorted(TEST_DIR.glob("*.hex")):
        test_name = hex_file.stem
        addrs_file = TEST_DIR / f"{test_name}.addrs"
        if addrs_file.exists():
            tests.append(test_name)

    return tests


def get_test_addresses(test_name):
    """Get pass/fail addresses for a test."""
    addrs_file = TEST_DIR / f"{test_name}.addrs"
    if not addrs_file.exists():
        return "FF00", "FF10"  # Defaults

    with open(addrs_file, 'r') as f:
        parts = f.read().strip().split()
        if len(parts) >= 2:
            return parts[0], parts[1]
    return "FF00", "FF10"


def compile_pipelined(verilog_dir):
    """Compile the pipelined processor testbench."""
    proc_file = verilog_dir / "cpu_6502_pipelined_3stage.v"
    tb_file = verilog_dir / "simple_tb.sv"
    sim_file = verilog_dir / "sim_test"

    if not proc_file.exists():
        print(f"ERROR: Processor not found: {proc_file}")
        return None

    cmd = ["iverilog", "-g2012", "-o", str(sim_file), str(proc_file), str(tb_file)]
    success, stdout, stderr = run_command(cmd)
    if not success:
        print(f"Compilation failed: {stderr}")
        return None

    return sim_file


def run_test_pipelined(verilog_dir, sim_file, test_name, hex_file, pass_addr, fail_addr, timeout):
    """Run a single test on the pipelined processor."""
    # Copy hex file to imem.hex (what simple_tb.sv expects)
    imem_hex = verilog_dir / "imem.hex"
    shutil.copy(hex_file, imem_hex)

    cmd = [
        "vvp", str(sim_file),
        f"+pass_addr={pass_addr}",
        f"+fail_addr={fail_addr}"
    ]

    success, stdout, stderr = run_command(cmd, cwd=str(verilog_dir), timeout=timeout)

    # Parse result
    output = stdout + stderr
    if "TEST PASSED" in output:
        return "PASS", output
    elif "TEST FAILED" in output:
        return "FAIL", output
    elif "PC STALLED" in output:
        return "STALL", output
    elif "TIMEOUT" in output or not success:
        return "TIMEOUT", output
    else:
        return "UNKNOWN", output


def main():
    parser = argparse.ArgumentParser(description='Run 6502 ISAComp tests')
    parser.add_argument('--build', action='store_true', help='Build tests before running')
    parser.add_argument('--test', type=str, help='Run specific test only')
    parser.add_argument('--timeout', type=int, default=DEFAULT_TIMEOUT, help='Timeout per test')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--processor', type=str, default='pipelined',
                        choices=['pipelined', 'singlecycle', 'both'],
                        help='Which processor to test')
    args = parser.parse_args()

    os.chdir(SCRIPT_DIR)

    # Build tests if needed
    if args.build or not TEST_DIR.exists():
        if not build_tests():
            sys.exit(1)

    # Get test list
    tests = get_test_list()
    if not tests:
        print("ERROR: No tests found. Run with --build to build tests.")
        sys.exit(1)

    if args.test:
        if args.test not in tests:
            print(f"ERROR: Test '{args.test}' not found. Available: {', '.join(tests)}")
            sys.exit(1)
        tests = [args.test]

    print(f"\nFound {len(tests)} tests")

    # Test on pipelined processor
    if args.processor in ['pipelined', 'both']:
        print("\n" + "=" * 60)
        print("Testing PIPELINED 6502")
        print("=" * 60)

        verilog_dir = VERILOG_DIR_PIPELINED

        # Compile testbench
        print(f"Verilog directory: {verilog_dir}")
        print("Compiling testbench...")
        sim_file = compile_pipelined(verilog_dir)
        if not sim_file:
            print("Compilation failed!")
            sys.exit(1)
        print(f"Compiled: {sim_file}")

        # Run tests
        print("\n" + "-" * 60)
        print("Running Tests")
        print("-" * 60)

        results = {"PASS": 0, "FAIL": 0, "TIMEOUT": 0, "STALL": 0, "UNKNOWN": 0}
        failed_tests = []

        for test_name in tests:
            hex_file = TEST_DIR / f"{test_name}.hex"
            pass_addr, fail_addr = get_test_addresses(test_name)

            result, output = run_test_pipelined(
                verilog_dir, sim_file, test_name, hex_file, pass_addr, fail_addr, args.timeout
            )

            results[result] = results.get(result, 0) + 1

            status_char = {"PASS": ".", "FAIL": "F", "TIMEOUT": "T", "STALL": "S", "UNKNOWN": "?"}
            print(f"  {test_name:15s} [{status_char.get(result, '?')}] {result}")

            if result != "PASS":
                failed_tests.append((test_name, result))
                if args.verbose:
                    # Show last few lines of output
                    lines = output.strip().split('\n')
                    for line in lines[-5:]:
                        print(f"    {line}")

        # Summary
        print("\n" + "-" * 60)
        print("Pipelined Results Summary")
        print("-" * 60)
        print(f"  PASS:    {results['PASS']}")
        print(f"  FAIL:    {results['FAIL']}")
        print(f"  TIMEOUT: {results['TIMEOUT']}")
        print(f"  STALL:   {results['STALL']}")
        print(f"  UNKNOWN: {results['UNKNOWN']}")
        print(f"  TOTAL:   {len(tests)}")

        if failed_tests:
            print("\nFailed tests:")
            for name, result in failed_tests:
                print(f"  - {name} ({result})")

    # TODO: Add single-cycle processor testing

    if args.processor == 'singlecycle':
        print("\nSingle-cycle processor testing not yet implemented")
        sys.exit(1)

    # Final status
    if results['PASS'] == len(tests):
        print("\nAll tests passed!")
        sys.exit(0)
    else:
        print(f"\n{len(tests) - results['PASS']} test(s) failed")
        sys.exit(1)


if __name__ == '__main__':
    main()
