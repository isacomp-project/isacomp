#!/usr/bin/env python3
"""
Run all MicroVAX tests on the generated processor.
Assembles test files and runs iverilog simulation.
"""

import subprocess
import sys
import os
from pathlib import Path

GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
RESET = '\033[0m'

TESTS = [
    # Longword arithmetic - 3 operand
    'addl3', 'subl3', 'mull3', 'divl3',

    # Longword arithmetic - 2 operand
    'addl2', 'subl2', 'mull2', 'divl2',

    # Longword arithmetic - immediate
    'addli', 'subli',

    # Longword arithmetic - 1 operand
    'movl', 'incl', 'decl', 'clrl', 'mnegl', 'mcoml',

    # Logical - 3 operand
    'andl3', 'bisl3', 'xorl3', 'bicl3',

    # Logical - 2 operand
    'andl2', 'bisl2', 'xorl2', 'bicl2',

    # Shifts
    'ashl', 'ashli', 'shrli', 'shrai', 'rotl',

    # Signed branches
    'beql', 'bneq', 'blss', 'bgeq', 'bgtr', 'bleq',

    # Unsigned branches
    'bgtru', 'blequ',

    # Unconditional branches
    'brw', 'jmp',

    # Bit test branches
    'bbs', 'bbc',

    # Bit test and modify
    'bbss', 'bbcc',

    # Loop control
    'sobgtr', 'sobgeq', 'aobleq', 'acbl',

    # Subroutine
    'jsb_rsb',

    # Memory
    'ldl_stl', 'pushl_popl',

    # Move address
    'moval',

    # Byte arithmetic
    'addb2', 'addb3', 'subb3', 'incb', 'decb',

    # Byte data movement
    'movb', 'clrb', 'mnegb', 'movzbl', 'cvtbl',

    # Word arithmetic
    'addw2', 'addw3', 'subw3', 'incw', 'decw',

    # Word data movement
    'movw', 'clrw', 'mnegw', 'movzwl', 'cvtwl',

    # Bit field
    'ffs', 'ffc',

    # Misc
    'nop',
]

SCRIPT_DIR = Path(__file__).parent.resolve()
TEST_DIR = SCRIPT_DIR / '../../../isa/microvax/microvax-tests/isa'
ASM_SCRIPT = SCRIPT_DIR / '../../../isa/microvax/microvax-tests/mvax_asm.py'

def compile_processor():
    """Compile the processor with iverilog."""
    verilog_file = SCRIPT_DIR / 'microvax_complete.v'
    testbench_file = SCRIPT_DIR / 'simple_tb.sv'
    fpu_stub = SCRIPT_DIR / 'cvfpu_stub.v'  # Use stub FPU for iverilog
    sim_file = SCRIPT_DIR / 'sim'

    if not verilog_file.exists():
        print(f"{RED}ERROR: microvax_complete.v not found{RESET}")
        return False

    # Check all source files for recompilation
    source_files = [verilog_file, testbench_file]
    if fpu_stub.exists():
        source_files.append(fpu_stub)

    if sim_file.exists():
        sim_mtime = sim_file.stat().st_mtime
        needs_recompile = any(f.stat().st_mtime > sim_mtime for f in source_files if f.exists())
        if not needs_recompile:
            return True

    print("Compiling processor...")
    try:
        # Build compile command - include FPU stub for iverilog
        compile_files = [str(verilog_file), str(testbench_file)]
        if fpu_stub.exists():
            compile_files.append(str(fpu_stub))

        result = subprocess.run(
            ['iverilog', '-g2012', '-o', str(sim_file)] + compile_files,
            capture_output=True,
            text=True,
            cwd=SCRIPT_DIR
        )
        if result.returncode != 0:
            print(f"{RED}Compilation failed:{RESET}")
            print(result.stderr)
            return False
        print("Compilation successful")
        return True
    except FileNotFoundError:
        print(f"{RED}ERROR: iverilog not found{RESET}")
        return False

def assemble_test(test_name):
    """Assemble a test file and return pass/fail addresses."""
    test_file = TEST_DIR / f'{test_name}.S'
    hex_file = SCRIPT_DIR / 'umem.hex'

    if not test_file.exists():
        return None, None, None

    try:
        result = subprocess.run(
            ['python3', str(ASM_SCRIPT), str(test_file), '-o', str(hex_file), '-v'],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            return None, None, result.stderr

        # Parse output to get pass/fail addresses
        pass_addr = None
        fail_addr = None
        for line in result.stdout.split('\n'):
            if 'Labels:' in line:
                import ast
                labels_str = line.split('Labels:')[1].strip()
                labels = ast.literal_eval(labels_str)
                pass_addr = labels.get('pass')
                fail_addr = labels.get('fail')
                break

        return pass_addr, fail_addr, None
    except Exception as e:
        return None, None, str(e)

def run_test(test_name):
    """Run a single test."""
    # Create empty rf.hex
    rf_hex = SCRIPT_DIR / 'rf.hex'
    with open(rf_hex, 'w') as f:
        for i in range(16):
            f.write('00000000\n')

    # Assemble test
    pass_addr, fail_addr, error = assemble_test(test_name)
    if error:
        return 'ERROR', f'Assembly failed: {error}'
    if pass_addr is None or fail_addr is None:
        return 'SKIP', 'No pass/fail labels'

    # Run simulation
    try:
        result = subprocess.run(
            ['timeout', '5', 'vvp', str(SCRIPT_DIR / 'sim'),
             f'+pass_addr={pass_addr:08x}',
             f'+fail_addr={fail_addr:08x}'],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=SCRIPT_DIR
        )

        output = result.stdout + result.stderr

        if 'TEST PASSED' in output:
            return 'PASS', ''
        elif 'TEST FAILED' in output:
            return 'FAIL', 'Test assertion failed'
        elif 'TIMEOUT' in output or result.returncode == 124:
            return 'TIMEOUT', 'Simulation timeout'
        else:
            return 'ERROR', f'Unknown: {output[:100]}'

    except subprocess.TimeoutExpired:
        return 'TIMEOUT', 'Simulation timeout'
    except Exception as e:
        return 'ERROR', str(e)

def main():
    print("=" * 70)
    print("MICROVAX PROCESSOR TEST SUITE")
    print("=" * 70)
    print()

    if not compile_processor():
        return 1

    print()
    results = {}
    pass_count = 0
    fail_count = 0
    skip_count = 0

    for test in TESTS:
        status, msg = run_test(test)
        results[test] = (status, msg)

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

    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    total = len(TESTS)
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
