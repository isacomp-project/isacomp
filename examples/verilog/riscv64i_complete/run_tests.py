#!/usr/bin/env python3
"""
Run all RV64I tests on the generated processor.
Converts ELF files to hex and uses a simple testbench.
"""

import subprocess
import sys
import os
import re
from pathlib import Path

# Color codes for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
RESET = '\033[0m'

# All 49 RV64I instructions
TESTS_BASE = ['add', 'addi', 'sub', 'lui', 'auipc', 'and', 'andi', 'or', 'ori',
              'xor', 'xori', 'sll', 'slli', 'srl', 'srli', 'sra', 'srai',
              'slt', 'slti', 'sltu', 'sltiu', 'beq', 'bne', 'blt', 'bltu',
              'bge', 'bgeu', 'jal', 'jalr']

TESTS_MEM = ['lw', 'lh', 'lhu', 'lb', 'lbu', 'sw', 'sh', 'sb']

TESTS_RV64 = ['ld', 'lwu', 'sd', 'addiw', 'slliw', 'srliw', 'sraiw',
              'addw', 'subw', 'sllw', 'srlw', 'sraw']

ALL_TESTS = TESTS_BASE + TESTS_MEM + TESTS_RV64

def compile_processor():
    """Compile the processor if needed."""
    if not Path('riscv64i_complete.v').exists():
        print(f"{RED}ERROR: riscv64i_complete.v not found{RESET}")
        print("Generate it first with: python3 ../../../isa/riscv64/generators/generate_riscv64i_complete.py")
        return False

    # Check if we need to recompile
    if (Path('sim').exists() and
        Path('sim').stat().st_mtime > Path('riscv64i_complete.v').stat().st_mtime and
        Path('sim').stat().st_mtime > Path('test_runner_tb.sv').stat().st_mtime):
        return True

    print("Compiling processor...")
    try:
        result = subprocess.run(
            ['iverilog', '-g2012', '-o', 'sim', 'riscv64i_complete.v', 'test_runner_tb.sv'],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            # Only show errors
            errors = [line for line in result.stderr.split('\n') if 'error' in line.lower()]
            if errors:
                print(f"{RED}Compilation errors:{RESET}")
                for err in errors:
                    print(err)
            return False
        print()
        return True
    except FileNotFoundError:
        print(f"{RED}ERROR: iverilog not found. Install with: apt-get install iverilog{RESET}")
        return False

def get_pass_fail_addrs(elf_file):
    """Extract pass/fail addresses from .addrs file or ELF file."""
    # Try .addrs file first (faster and doesn't need nm)
    addrs_file = elf_file + '.addrs'
    if Path(addrs_file).exists():
        try:
            with open(addrs_file, 'r') as f:
                line = f.read().strip()
                parts = line.split()
                if len(parts) >= 2:
                    return parts[0], parts[1]  # pass_addr, fail_addr
        except:
            pass

    # Fall back to using nm on ELF file
    try:
        result = subprocess.run(
            ['riscv64-unknown-elf-nm', elf_file],
            capture_output=True,
            text=True
        )

        pass_addr = None
        fail_addr = None

        for line in result.stdout.split('\n'):
            if ' pass' in line and line.strip().endswith('pass'):
                pass_addr = line.split()[0]
            elif ' fail' in line and line.strip().endswith('fail'):
                fail_addr = line.split()[0]

        return pass_addr, fail_addr
    except:
        return None, None

def elf_to_hex(elf_file, hex_file):
    """Convert ELF to hex file."""
    # Try different objcopy tools to get verilog format (byte-addressed)
    objcopy_tools = ['objcopy', 'llvm-objcopy', 'riscv64-unknown-elf-objcopy']

    temp_hex = hex_file + '.temp'
    for tool in objcopy_tools:
        try:
            subprocess.run(
                [tool, '-O', 'verilog', elf_file, temp_hex],
                check=True,
                capture_output=True
            )
            # Convert byte-addressed to word-addressed hex
            result = subprocess.run(
                ['python3', 'parse_verilog_hex.py', temp_hex, hex_file],
                check=True,
                capture_output=True
            )
            subprocess.run(['rm', '-f', temp_hex], capture_output=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue

    return False

def run_test(test_name):
    """Run a single test."""
    test_path = f'../../../isa/riscv64/riscv-tests/isa/rv64ui-isacomp-{test_name}'

    if not Path(test_path).exists():
        return 'SKIP', 'Test file not found'

    # Get pass/fail addresses
    pass_addr, fail_addr = get_pass_fail_addrs(test_path)
    if not pass_addr or not fail_addr:
        return 'SKIP', 'No pass/fail symbols'

    # Convert to hex
    hex_file = f'test.hex'
    if not elf_to_hex(test_path, hex_file):
        return 'ERROR', 'Failed to convert ELF'

    # Run simulation
    try:
        result = subprocess.run(
            ['timeout', '5', 'vvp', 'sim',
             f'+hexfile={hex_file}',
             f'+pass_addr={pass_addr}',
             f'+fail_addr={fail_addr}'],
            capture_output=True,
            text=True,
            timeout=10
        )

        output = result.stdout + result.stderr

        if 'TEST PASSED' in output:
            return 'PASS', ''
        elif 'TEST FAILED' in output:
            return 'FAIL', 'Test assertion failed'
        elif 'Timeout' in output or result.returncode == 124:
            return 'TIMEOUT', 'Simulation timeout'
        else:
            return 'ERROR', 'Unknown error'

    except subprocess.TimeoutExpired:
        return 'TIMEOUT', 'Simulation timeout'
    except Exception as e:
        return 'ERROR', str(e)

def main():
    print("=" * 70)
    print("RV64I PROCESSOR TEST SUITE")
    print("=" * 70)
    print()

    # Compile processor
    if not compile_processor():
        return 1

    # Run tests
    results = {}
    pass_count = 0
    fail_count = 0
    skip_count = 0

    for test in ALL_TESTS:
        status, msg = run_test(test)
        results[test] = (status, msg)

        # Print result
        status_str = {
            'PASS': f'{GREEN}✓ PASS{RESET}',
            'FAIL': f'{RED}✗ FAIL{RESET}',
            'SKIP': f'{YELLOW}⊘ SKIP{RESET}',
            'TIMEOUT': f'{RED}✗ TIMEOUT{RESET}',
            'ERROR': f'{RED}✗ ERROR{RESET}',
        }[status]

        print(f"{test:12s} ... {status_str}", end='')
        if msg:
            print(f" ({msg})", end='')
        print()

        if status == 'PASS':
            pass_count += 1
        elif status in ['FAIL', 'TIMEOUT', 'ERROR']:
            fail_count += 1
        else:
            skip_count += 1

    # Print summary
    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    total = len(ALL_TESTS)
    print(f"PASS:  {pass_count:2d} / {total}")
    print(f"FAIL:  {fail_count:2d} / {total}")
    print(f"SKIP:  {skip_count:2d} / {total}")
    print()

    if fail_count == 0 and pass_count > 0:
        print(f"{GREEN}✓ ALL TESTS PASSED!{RESET}")
        return 0
    else:
        print(f"{RED}✗ SOME TESTS FAILED{RESET}")
        return 1

if __name__ == '__main__':
    sys.exit(main())
