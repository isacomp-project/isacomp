#!/usr/bin/env python3
"""Run bulk Z80 tests with Verilator - compile once, run many tests."""

import json
import re
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent

def get_implemented_opcodes(isa_dir: Path) -> tuple:
    """Scan .isa files to find all implemented opcodes.

    Returns:
        (single_byte_opcodes: set, prefixed_opcodes: dict, ddcb_opcodes: set, fdcb_opcodes: set)
        prefixed_opcodes maps prefix -> set of second bytes
    """
    single_byte = set()
    prefixed = {'CB': set(), 'DD': set(), 'ED': set(), 'FD': set()}
    ddcb_opcodes = set()
    fdcb_opcodes = set()

    for isa_file in isa_dir.glob('*.isa'):
        with open(isa_file) as f:
            content = f.read()

        # Check for DDCB instruction (ddcb_prefix == 16'hCBDD and op_byte == 8'hXX)
        ddcb_match = re.search(r"assume ddcb_prefix == 16'hCBDD", content)
        if ddcb_match:
            opcode_match = re.search(r"assume op_byte == 8'h([0-9a-fA-F]{2})", content)
            if opcode_match:
                ddcb_opcodes.add(int(opcode_match.group(1), 16))
            continue

        # Check for FDCB instruction (fdcb_prefix == 16'hCBFD and op_byte == 8'hXX)
        fdcb_match = re.search(r"assume fdcb_prefix == 16'hCBFD", content)
        if fdcb_match:
            opcode_match = re.search(r"assume op_byte == 8'h([0-9a-fA-F]{2})", content)
            if opcode_match:
                fdcb_opcodes.add(int(opcode_match.group(1), 16))
            continue

        # Check for CB-style instruction (cb_instr == 0xXXCB)
        cb_match = re.search(r'assume cb_instr == 0x([0-9a-fA-F]+)CB', content)
        if cb_match:
            second_byte = int(cb_match.group(1), 16)
            prefixed['CB'].add(second_byte)
            continue

        # Check for DD/FD/ED prefix using xx_instr == 16'hXXYY or 0xXXYY format
        dd_match = re.search(r"assume dd_instr == (?:16'h|0x)([0-9a-fA-F]{2})DD", content)
        if dd_match:
            second_byte = int(dd_match.group(1), 16)
            prefixed['DD'].add(second_byte)
            continue

        fd_match = re.search(r"assume fd_instr == (?:16'h|0x)([0-9a-fA-F]{2})FD", content)
        if fd_match:
            second_byte = int(fd_match.group(1), 16)
            prefixed['FD'].add(second_byte)
            continue

        ed_match = re.search(r"assume ed_instr == (?:16'h|0x)([0-9a-fA-F]{2})ED", content)
        if ed_match:
            second_byte = int(ed_match.group(1), 16)
            prefixed['ED'].add(second_byte)
            continue

        # Check for other prefix-style instructions (instr == 0xDD/ED/FD and opcode == 0xXX)
        prefix_match = re.search(r'assume instr == 0x(DD|ED|FD)', content)
        opcode_match = re.search(r'assume opcode == 0x([0-9a-fA-F]+)', content)

        if prefix_match and opcode_match:
            prefix = prefix_match.group(1)
            second_byte = int(opcode_match.group(1), 16)
            prefixed[prefix].add(second_byte)
        else:
            # Single-byte opcode
            instr_match = re.search(r'assume instr == 0x([0-9a-fA-F]+)', content)
            if instr_match:
                single_byte.add(int(instr_match.group(1), 16))

    return single_byte, prefixed, ddcb_opcodes, fdcb_opcodes

# Skip these single-byte opcodes
SKIP_OPCODES = {
    0x76,  # HALT - stops simulation
    0xCB,  # CB prefix byte (not standalone)
    0xDD,  # DD prefix byte (not standalone)
    0xED,  # ED prefix byte (not standalone)
    0xFD,  # FD prefix byte (not standalone)
}

# Skip these prefixed opcodes
SKIP_CB_OPCODES = set()  # All CB opcodes now supported

# Skip DD/FD opcodes that are memory operations or not implemented
SKIP_DD_OPCODES = set()
SKIP_FD_OPCODES = set()
SKIP_ED_OPCODES = set()


def generate_test_file(tests_dir: Path, single_opcodes: list, prefixed_opcodes: dict,
                       max_per_opcode: int, output_file: Path,
                       ddcb_opcodes: set = None, fdcb_opcodes: set = None):
    """Generate tests.txt file for bulk testing."""
    all_tests = []

    # Single-byte opcodes
    for opcode in single_opcodes:
        test_file = tests_dir / f"{opcode:02x}.json"
        if not test_file.exists():
            continue
        all_tests.extend(load_tests(test_file, max_per_opcode))

    # Prefixed opcodes
    for prefix, second_bytes in prefixed_opcodes.items():
        for second_byte in second_bytes:
            # Test files have names like "cb 00.json"
            test_file = tests_dir / f"{prefix.lower()} {second_byte:02x}.json"
            if not test_file.exists():
                continue
            all_tests.extend(load_tests(test_file, max_per_opcode))

    # DDCB opcodes - test files named "dd cb __ XX.json"
    if ddcb_opcodes:
        for opcode in ddcb_opcodes:
            test_file = tests_dir / f"dd cb __ {opcode:02x}.json"
            if not test_file.exists():
                continue
            all_tests.extend(load_tests(test_file, max_per_opcode))

    # FDCB opcodes - test files named "fd cb __ XX.json"
    if fdcb_opcodes:
        for opcode in fdcb_opcodes:
            test_file = tests_dir / f"fd cb __ {opcode:02x}.json"
            if not test_file.exists():
                continue
            all_tests.extend(load_tests(test_file, max_per_opcode))

    with open(output_file, 'w') as f:
        f.write(f"{len(all_tests)}\n")
        for t in all_tests:
            f.write(f"{t['name']}\n")
            f.write(' '.join(str(x) for x in t['init']) + '\n')
            f.write(' '.join(str(x) for x in t['final']) + '\n')
            f.write(' '.join(str(x) for x in t['init_prime']) + '\n')
            f.write(' '.join(str(x) for x in t['final_prime']) + '\n')
            f.write(' '.join(str(x) for x in t['init_index']) + '\n')
            f.write(' '.join(str(x) for x in t['final_index']) + '\n')
            f.write(f"{len(t['ram'])}\n")
            for addr, val in t['ram']:
                f.write(f"{addr} {val}\n")
            # Write port I/O data
            f.write(f"{len(t['ports'])}\n")
            for addr, val in t['ports']:
                f.write(f"{addr} {val}\n")

    return len(all_tests)


def load_tests(test_file: Path, max_per_opcode: int) -> list:
    """Load tests from a JSON test file."""
    with open(test_file) as f:
        tests = json.load(f)

    result = []
    for test in tests[:max_per_opcode]:
        init = test['initial']
        final = test['final']
        ram = init.get('ram', [])

        # Extract prime registers from combined 16-bit values
        init_af_ = init.get('af_', 0)
        init_bc_ = init.get('bc_', 0)
        init_de_ = init.get('de_', 0)
        init_hl_ = init.get('hl_', 0)

        final_af_ = final.get('af_', 0)
        final_bc_ = final.get('bc_', 0)
        final_de_ = final.get('de_', 0)
        final_hl_ = final.get('hl_', 0)

        # Extract IX/IY and I/R registers
        init_ix = init.get('ix', 0)
        init_iy = init.get('iy', 0)
        init_i = init.get('i', 0)
        init_r = init.get('r', 0)
        init_iff2 = init.get('iff2', 0)

        final_ix = final.get('ix', 0)
        final_iy = final.get('iy', 0)
        final_i = final.get('i', 0)
        final_r = final.get('r', 0)
        final_iff2 = final.get('iff2', 0)

        result.append({
            'name': test['name'].replace(' ', '_'),
            'init': [init['a'], init['b'], init['c'], init['d'], init['e'],
                     init['h'], init['l'], init['f'], init['pc'], init['sp']],
            'final': [final['a'], final['b'], final['c'], final['d'], final['e'],
                      final['h'], final['l'], final['f'], final['pc'], final['sp']],
            'init_prime': [init_af_ >> 8, init_af_ & 0xFF,
                           init_bc_ >> 8, init_bc_ & 0xFF,
                           init_de_ >> 8, init_de_ & 0xFF,
                           init_hl_ >> 8, init_hl_ & 0xFF],
            'final_prime': [final_af_ >> 8, final_af_ & 0xFF,
                            final_bc_ >> 8, final_bc_ & 0xFF,
                            final_de_ >> 8, final_de_ & 0xFF,
                            final_hl_ >> 8, final_hl_ & 0xFF],
            'init_index': [init_ix >> 8, init_ix & 0xFF,
                           init_iy >> 8, init_iy & 0xFF,
                           init_i, init_r, init_iff2],
            'final_index': [final_ix >> 8, final_ix & 0xFF,
                            final_iy >> 8, final_iy & 0xFF,
                            final_i, final_r, final_iff2],
            'ram': ram,
            'ports': extract_ports(test.get('ports', []))
        })
    return result


def extract_ports(ports):
    """Extract port read values from ports list.

    Ports format: [[addr, value, 'r'/'w'], ...]
    For reads ('r'), we set up the port with the value before execution.
    We use the lower 8 bits of the address as the port index.
    """
    result = []
    for entry in ports:
        addr, value, rw = entry
        if rw == 'r':  # Read operations - need to pre-set port value
            # Use lower 8 bits of 16-bit port address
            result.append((addr & 0xFF, value))
    return result


def compile_bulk_test(verilog_path: Path, tb_path: Path, output_dir: Path):
    """Compile bulk testbench with Verilator."""
    obj_dir = output_dir / 'obj_dir'

    result = subprocess.run(
        ['verilator', '--binary', '--timing',
         '-Wno-fatal', '-Wno-WIDTHTRUNC', '-Wno-WIDTHEXPAND',
         '-Wno-UNUSEDSIGNAL', '-Wno-UNDRIVEN', '-Wno-LATCH',
         '-Wno-TIMESCALEMOD', '-Wno-DECLFILENAME', '-Wno-UNUSEDPARAM',
         '-Wno-WIDTHCONCAT', '-Wno-UNSIGNED', '-Wno-BLKSEQ',
         '--top-module', 'bulk_test',
         '-o', 'bulk_sim',
         '--Mdir', str(obj_dir),
         str(verilog_path), str(tb_path)],
        cwd=str(output_dir),
        capture_output=True,
        text=True,
        timeout=180
    )

    if result.returncode != 0:
        print(f"Compile failed:\n{result.stderr}")
        return None

    return obj_dir / 'bulk_sim'


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Run Z80 bulk tests with Verilator')
    parser.add_argument('--tests-dir', type=Path,
                        default=project_root / 'isa' / 'z80' / 'singlestep-tests' / 'v1')
    parser.add_argument('--verilog', type=Path,
                        default=project_root / 'examples' / 'verilog' / 'z80' / 'z80.v')
    parser.add_argument('--opcode', type=str, default=None,
                        help='Test specific opcode (hex), e.g., "08" or "cb 00"')
    parser.add_argument('--max-tests', type=int, default=100,
                        help='Max tests per opcode')
    args = parser.parse_args()

    tb_path = Path(__file__).parent / 'bulk_testbench.v'
    isa_dir = project_root / 'isa' / 'z80'

    # Determine opcodes to test
    if args.opcode:
        # Handle both single-byte and prefixed opcodes
        if ' ' in args.opcode:
            # Prefixed like "cb 00"
            parts = args.opcode.split()
            prefix = parts[0].upper()
            second = int(parts[1], 16)
            single_opcodes = []
            prefixed_opcodes = {prefix: {second}}
        else:
            single_opcodes = [int(args.opcode, 16)]
            prefixed_opcodes = {}
        ddcb_opcodes = set()
        fdcb_opcodes = set()
    else:
        # Dynamically scan implemented opcodes from .isa files
        single_impl, prefixed_impl, ddcb_opcodes, fdcb_opcodes = get_implemented_opcodes(isa_dir)
        single_opcodes = sorted(single_impl - SKIP_OPCODES)
        prefixed_opcodes = {
            'CB': prefixed_impl['CB'] - SKIP_CB_OPCODES,
            'DD': prefixed_impl['DD'] - SKIP_DD_OPCODES,
            'ED': prefixed_impl['ED'] - SKIP_ED_OPCODES,
            'FD': prefixed_impl['FD'] - SKIP_FD_OPCODES,
        }

    # Count total opcodes
    total_opcodes = len(single_opcodes) + len(ddcb_opcodes) + len(fdcb_opcodes)
    for prefix, seconds in prefixed_opcodes.items():
        total_opcodes += len(seconds)

    with tempfile.TemporaryDirectory(prefix='z80_bulk_') as tmpdir:
        output_dir = Path(tmpdir)

        print(f"Generating test data for {total_opcodes} opcodes, {args.max_tests} tests each...")
        tests_file = output_dir / 'tests.txt'
        num_tests = generate_test_file(args.tests_dir, single_opcodes, prefixed_opcodes,
                                       args.max_tests, tests_file, ddcb_opcodes, fdcb_opcodes)
        print(f"Generated {num_tests} test cases")

        print("Compiling with Verilator...")
        sim_exe = compile_bulk_test(args.verilog, tb_path, output_dir)
        if not sim_exe:
            sys.exit(1)
        print("Compilation successful")

        print("Running tests...")
        result = subprocess.run(
            [str(sim_exe)],
            cwd=str(output_dir),
            capture_output=True,
            text=True,
            timeout=600
        )

        print(result.stdout)
        if result.stderr:
            print(result.stderr)


if __name__ == '__main__':
    main()
