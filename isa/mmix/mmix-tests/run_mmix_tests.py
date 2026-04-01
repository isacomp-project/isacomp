#!/usr/bin/env python3
"""
MMIX ISA Test Runner

Runs MMIX ISA tests against the generated processor using iverilog.
"""

import sys
import subprocess
from pathlib import Path

# MMIX opcodes for test generation
OPCODES = {
    # Set instructions
    'SETL': 0xE3,
    'SETH': 0xE0,
    'SETMH': 0xE1,
    'SETML': 0xE2,

    # Arithmetic - signed
    'ADD': 0x20,
    'ADDI': 0x21,
    'SUB': 0x24,
    'SUBI': 0x25,
    'MUL': 0x18,
    'MULI': 0x19,
    'DIV': 0x1C,
    'DIVI': 0x1D,
    'NEG': 0x34,
    'NEGI': 0x35,

    # Arithmetic - unsigned
    'ADDU': 0x22,
    'ADDUI': 0x23,
    'SUBU': 0x26,
    'SUBUI': 0x27,
    'MULU': 0x1A,
    'MULUI': 0x1B,
    'DIVU': 0x1E,
    'DIVUI': 0x1F,
    'NEGU': 0x36,
    'NEGUI': 0x37,

    # Scaled address
    '2ADDU': 0x28,
    '2ADDUI': 0x29,
    '4ADDU': 0x2A,
    '4ADDUI': 0x2B,
    '8ADDU': 0x2C,
    '8ADDUI': 0x2D,
    '16ADDU': 0x2E,
    '16ADDUI': 0x2F,

    # Compare
    'CMP': 0x30,
    'CMPI': 0x31,
    'CMPU': 0x32,
    'CMPUI': 0x33,

    # Logical
    'AND': 0xC8,
    'ANDI': 0xC9,
    'OR': 0xC0,
    'ORI': 0xC1,
    'XOR': 0xC6,
    'XORI': 0xC7,
    'NOR': 0xC4,
    'NORI': 0xC5,
    'NAND': 0xCC,
    'NANDI': 0xCD,
    'NXOR': 0xCE,
    'NXORI': 0xCF,
    'ANDN': 0xCA,
    'ANDNI': 0xCB,
    'ORN': 0xC2,
    'ORNI': 0xC3,

    # Shifts
    'SL': 0x38,
    'SLI': 0x39,
    'SLU': 0x3A,
    'SLUI': 0x3B,
    'SR': 0x3C,
    'SRI': 0x3D,
    'SRU': 0x3E,
    'SRUI': 0x3F,

    # Branch
    'BN': 0x40,
    'BNB': 0x41,
    'BZ': 0x42,
    'BZB': 0x43,
    'BP': 0x44,
    'BPB': 0x45,
    'BOD': 0x46,
    'BODB': 0x47,
    'BNN': 0x48,
    'BNNB': 0x49,
    'BNZ': 0x4A,
    'BNZB': 0x4B,
    'BNP': 0x4C,
    'BNPB': 0x4D,
    'BEV': 0x4E,
    'BEVB': 0x4F,

    # Conditional set
    'CSN': 0x60,
    'CSNI': 0x61,
    'CSZ': 0x62,
    'CSZI': 0x63,
    'CSP': 0x64,
    'CSPI': 0x65,
    'CSOD': 0x66,
    'CSODI': 0x67,
    'CSNN': 0x68,
    'CSNNI': 0x69,
    'CSNZ': 0x6A,
    'CSNZI': 0x6B,
    'CSNP': 0x6C,
    'CSNPI': 0x6D,
    'CSEV': 0x6E,
    'CSEVI': 0x6F,

    # Zero-or set
    'ZSN': 0x70,
    'ZSNI': 0x71,
    'ZSZ': 0x72,
    'ZSZI': 0x73,
    'ZSP': 0x74,
    'ZSPI': 0x75,
    'ZSOD': 0x76,
    'ZSODI': 0x77,
    'ZSNN': 0x78,
    'ZSNNI': 0x79,
    'ZSNZ': 0x7A,
    'ZSNZI': 0x7B,
    'ZSNP': 0x7C,
    'ZSNPI': 0x7D,
    'ZSEV': 0x7E,
    'ZSEVI': 0x7F,

    # Load
    'LDB': 0x80,
    'LDBI': 0x81,
    'LDBU': 0x82,
    'LDBUI': 0x83,
    'LDO': 0x8C,
    'LDOI': 0x8D,

    # Store
    'STB': 0xA0,
    'STBI': 0xA1,
    'STO': 0xAC,
    'STOI': 0xAD,

    # Jump
    'JMP': 0xF0,
    'JMPB': 0xF1,
    'GO': 0x9E,
    'GOI': 0x9F,

    # Wyde operations
    'INCH': 0xE4,
    'INCMH': 0xE5,
    'INCML': 0xE6,
    'INCL': 0xE7,
    'ORH': 0xE8,
    'ORMH': 0xE9,
    'ORML': 0xEA,
    'ORL': 0xEB,

    # Floating-point arithmetic (opcodes from .isa files)
    'FADD': 0x04,
    'FSUB': 0x06,
    'FMUL': 0x08,
    'FDIV': 0x0A,
    'FSQRT': 0x0E,

    # Floating-point compare
    'FCMP': 0x01,
    'FEQL': 0x02,
    'FUN': 0x03,

    # Floating-point conversion
    'FIX': 0x05,
    'FIXU': 0x07,
    'FLOT': 0x09,
    'FLOTI': 0x0B,
    'FLOTU': 0x0D,
    'FLOTUI': 0x0F,
}


def mmix_instr(op, x, y, z):
    """Create a 32-bit MMIX instruction."""
    return (op << 24) | (x << 16) | (y << 8) | z


def mmix_instr_yz(op, x, yz):
    """Create a 32-bit MMIX instruction with 16-bit immediate."""
    return (op << 24) | (x << 16) | (yz & 0xFFFF)


def create_test_program(instructions):
    """Convert a list of 32-bit instructions to 64-bit memory words.

    Instructions are packed as: umem[i] = {instr@(i*8+4), instr@(i*8)}
    """
    words = []
    for i in range(0, len(instructions), 2):
        low = instructions[i]
        high = instructions[i+1] if i+1 < len(instructions) else 0xF0000000
        word = (high << 32) | low
        words.append(f"{word:016X}")
    return words


def run_test(test_name, test_instrs, pass_addr, fail_addr, work_dir, verbose=False, simulator=None):
    """Run a single test."""
    # Create memory file
    mem_words = create_test_program(test_instrs)
    mem_file = work_dir / "umem.hex"
    rf_file = work_dir / "rf.hex"

    with open(mem_file, 'w') as f:
        for word in mem_words:
            f.write(word + '\n')

    # Create empty rf.hex
    rf_file.touch()

    # Run simulation (use relative path since we're running from work_dir)
    if simulator:
        # Use specified simulator (Verilator)
        sim_path = Path(simulator)
        if sim_path.is_absolute():
            sim_cmd = [str(sim_path)]
        else:
            sim_cmd = [str(sim_path)]
        sim_cmd.extend([
            f'+pass_addr={pass_addr:016X}',
            f'+fail_addr={fail_addr:016X}'
        ])
        run_cwd = work_dir
    else:
        # Default to iverilog (vvp)
        sim_cmd = [
            'vvp', 'sim.vvp',
            f'+pass_addr={pass_addr:016X}',
            f'+fail_addr={fail_addr:016X}'
        ]
        run_cwd = work_dir

    try:
        result = subprocess.run(
            sim_cmd,
            cwd=run_cwd,
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
            print(f"  FAIL: {test_name}")
            return False
        elif 'TIMEOUT' in output:
            if verbose:
                print(f"  Output: {output}")
            print(f"  FAIL: {test_name} (timeout)")
            return False
        else:
            if verbose:
                print(f"  Output: {output}")
            print(f"  UNKNOWN: {test_name}")
            return None
    except subprocess.TimeoutExpired:
        print(f"  FAIL: {test_name} (simulation timeout)")
        return False
    except Exception as e:
        print(f"  FAIL: {test_name} ({e})")
        return False


def define_tests():
    """Define test cases."""
    tests = []

    # Test 1: ADD
    # SETL $1, 5; SETL $2, 3; ADD $3, $1, $2; SETL $4, 8; SUB $5, $3, $4; BZ $5, pass; JMP fail
    tests.append(('add', [
        mmix_instr_yz(OPCODES['SETL'], 1, 5),      # 0x00
        mmix_instr_yz(OPCODES['SETL'], 2, 3),      # 0x04
        mmix_instr(OPCODES['ADD'], 3, 1, 2),       # 0x08
        mmix_instr_yz(OPCODES['SETL'], 4, 8),      # 0x0C
        mmix_instr(OPCODES['SUB'], 5, 3, 4),       # 0x10
        mmix_instr_yz(OPCODES['BZ'], 5, 2),        # 0x14: BZ $5, +2 -> 0x1C
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x18: JMP +2 -> fail @ 0x20
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x1C: pass loop
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x20: fail loop
    ], 0x1C, 0x20))

    # Test 2: SUB
    tests.append(('sub', [
        mmix_instr_yz(OPCODES['SETL'], 1, 10),     # 0x00
        mmix_instr_yz(OPCODES['SETL'], 2, 3),      # 0x04
        mmix_instr(OPCODES['SUB'], 3, 1, 2),       # 0x08
        mmix_instr_yz(OPCODES['SETL'], 4, 7),      # 0x0C
        mmix_instr(OPCODES['SUB'], 5, 3, 4),       # 0x10
        mmix_instr_yz(OPCODES['BZ'], 5, 2),        # 0x14
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x18
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x1C
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x20
    ], 0x1C, 0x20))

    # Test 3: AND
    tests.append(('and', [
        mmix_instr_yz(OPCODES['SETL'], 1, 0xFF),   # 0x00
        mmix_instr_yz(OPCODES['SETL'], 2, 0x0F),   # 0x04
        mmix_instr(OPCODES['AND'], 3, 1, 2),       # 0x08
        mmix_instr_yz(OPCODES['SETL'], 4, 0x0F),   # 0x0C
        mmix_instr(OPCODES['SUB'], 5, 3, 4),       # 0x10
        mmix_instr_yz(OPCODES['BZ'], 5, 2),        # 0x14
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x18
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x1C
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x20
    ], 0x1C, 0x20))

    # Test 4: OR
    tests.append(('or', [
        mmix_instr_yz(OPCODES['SETL'], 1, 0xF0),   # 0x00
        mmix_instr_yz(OPCODES['SETL'], 2, 0x0F),   # 0x04
        mmix_instr(OPCODES['OR'], 3, 1, 2),        # 0x08
        mmix_instr_yz(OPCODES['SETL'], 4, 0xFF),   # 0x0C
        mmix_instr(OPCODES['SUB'], 5, 3, 4),       # 0x10
        mmix_instr_yz(OPCODES['BZ'], 5, 2),        # 0x14
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x18
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x1C
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x20
    ], 0x1C, 0x20))

    # Test 5: XOR
    tests.append(('xor', [
        mmix_instr_yz(OPCODES['SETL'], 1, 0xFF),   # 0x00
        mmix_instr_yz(OPCODES['SETL'], 2, 0x0F),   # 0x04
        mmix_instr(OPCODES['XOR'], 3, 1, 2),       # 0x08
        mmix_instr_yz(OPCODES['SETL'], 4, 0xF0),   # 0x0C
        mmix_instr(OPCODES['SUB'], 5, 3, 4),       # 0x10
        mmix_instr_yz(OPCODES['BZ'], 5, 2),        # 0x14
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x18
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x1C
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x20
    ], 0x1C, 0x20))

    # Test 6: SLI (shift left immediate)
    tests.append(('sli', [
        mmix_instr_yz(OPCODES['SETL'], 1, 3),      # 0x00
        mmix_instr(OPCODES['SLI'], 2, 1, 2),       # 0x04: $2 = $1 << 2 = 12
        mmix_instr_yz(OPCODES['SETL'], 3, 12),     # 0x08
        mmix_instr(OPCODES['SUB'], 4, 2, 3),       # 0x0C
        mmix_instr_yz(OPCODES['BZ'], 4, 2),        # 0x10
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x14
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x18
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x1C
    ], 0x18, 0x1C))

    # Test 7: SRUI (shift right unsigned immediate)
    tests.append(('srui', [
        mmix_instr_yz(OPCODES['SETL'], 1, 12),     # 0x00
        mmix_instr(OPCODES['SRUI'], 2, 1, 2),      # 0x04: $2 = $1 >> 2 = 3
        mmix_instr_yz(OPCODES['SETL'], 3, 3),      # 0x08
        mmix_instr(OPCODES['SUB'], 4, 2, 3),       # 0x0C
        mmix_instr_yz(OPCODES['BZ'], 4, 2),        # 0x10
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x14
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x18
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x1C
    ], 0x18, 0x1C))

    # Test 8: BZ (branch if zero)
    tests.append(('bz', [
        mmix_instr_yz(OPCODES['SETL'], 1, 0),      # 0x00: $1 = 0
        mmix_instr_yz(OPCODES['BZ'], 1, 2),        # 0x04: BZ $1, +2 -> 0x0C (should branch)
        mmix_instr_yz(OPCODES['JMP'], 0, 3),       # 0x08: JMP to fail
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x0C: pass
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x10: fail
    ], 0x0C, 0x10))

    # Test 9: BNZ (branch if non-zero)
    tests.append(('bnz', [
        mmix_instr_yz(OPCODES['SETL'], 1, 5),      # 0x00: $1 = 5
        mmix_instr_yz(OPCODES['BNZ'], 1, 2),       # 0x04: BNZ $1, +2 -> 0x0C (should branch)
        mmix_instr_yz(OPCODES['JMP'], 0, 3),       # 0x08: JMP to fail
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x0C: pass
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x10: fail
    ], 0x0C, 0x10))

    # Test 10: ADDI (add immediate)
    tests.append(('addi', [
        mmix_instr_yz(OPCODES['SETL'], 1, 5),      # 0x00
        mmix_instr(OPCODES['ADDI'], 2, 1, 3),      # 0x04: $2 = $1 + 3 = 8
        mmix_instr_yz(OPCODES['SETL'], 3, 8),      # 0x08
        mmix_instr(OPCODES['SUB'], 4, 2, 3),       # 0x0C
        mmix_instr_yz(OPCODES['BZ'], 4, 2),        # 0x10
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x14
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x18
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x1C
    ], 0x18, 0x1C))

    # Test 11: SETL
    tests.append(('setl', [
        mmix_instr_yz(OPCODES['SETL'], 1, 0x1234), # 0x00
        mmix_instr_yz(OPCODES['SETL'], 2, 0x1234), # 0x04
        mmix_instr(OPCODES['SUB'], 3, 1, 2),       # 0x08
        mmix_instr_yz(OPCODES['BZ'], 3, 2),        # 0x0C
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x10
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x14
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x18
    ], 0x14, 0x18))

    # Test 12: MUL
    tests.append(('mul', [
        mmix_instr_yz(OPCODES['SETL'], 1, 6),      # 0x00
        mmix_instr_yz(OPCODES['SETL'], 2, 7),      # 0x04
        mmix_instr(OPCODES['MUL'], 3, 1, 2),       # 0x08: $3 = 6 * 7 = 42
        mmix_instr_yz(OPCODES['SETL'], 4, 42),     # 0x0C
        mmix_instr(OPCODES['SUB'], 5, 3, 4),       # 0x10
        mmix_instr_yz(OPCODES['BZ'], 5, 2),        # 0x14
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x18
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x1C
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x20
    ], 0x1C, 0x20))

    # Test 13: DIV
    tests.append(('div', [
        mmix_instr_yz(OPCODES['SETL'], 1, 42),     # 0x00
        mmix_instr_yz(OPCODES['SETL'], 2, 6),      # 0x04
        mmix_instr(OPCODES['DIV'], 3, 1, 2),       # 0x08: $3 = 42 / 6 = 7
        mmix_instr_yz(OPCODES['SETL'], 4, 7),      # 0x0C
        mmix_instr(OPCODES['SUB'], 5, 3, 4),       # 0x10
        mmix_instr_yz(OPCODES['BZ'], 5, 2),        # 0x14
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x18
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x1C
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x20
    ], 0x1C, 0x20))

    # Test 14: ADDU (unsigned add)
    tests.append(('addu', [
        mmix_instr_yz(OPCODES['SETL'], 1, 100),    # 0x00
        mmix_instr_yz(OPCODES['SETL'], 2, 50),     # 0x04
        mmix_instr(OPCODES['ADDU'], 3, 1, 2),      # 0x08: $3 = 100 + 50 = 150
        mmix_instr_yz(OPCODES['SETL'], 4, 150),    # 0x0C
        mmix_instr(OPCODES['SUB'], 5, 3, 4),       # 0x10
        mmix_instr_yz(OPCODES['BZ'], 5, 2),        # 0x14
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x18
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x1C
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x20
    ], 0x1C, 0x20))

    # Test 15: 2ADDU (scaled address: $Y*2 + $Z)
    tests.append(('2addu', [
        mmix_instr_yz(OPCODES['SETL'], 1, 5),      # 0x00
        mmix_instr_yz(OPCODES['SETL'], 2, 3),      # 0x04
        mmix_instr(OPCODES['2ADDU'], 3, 1, 2),     # 0x08: $3 = 5*2 + 3 = 13
        mmix_instr_yz(OPCODES['SETL'], 4, 13),     # 0x0C
        mmix_instr(OPCODES['SUB'], 5, 3, 4),       # 0x10
        mmix_instr_yz(OPCODES['BZ'], 5, 2),        # 0x14
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x18
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x1C
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x20
    ], 0x1C, 0x20))

    # Test 16: 4ADDU (scaled address: $Y*4 + $Z)
    tests.append(('4addu', [
        mmix_instr_yz(OPCODES['SETL'], 1, 5),      # 0x00
        mmix_instr_yz(OPCODES['SETL'], 2, 3),      # 0x04
        mmix_instr(OPCODES['4ADDU'], 3, 1, 2),     # 0x08: $3 = 5*4 + 3 = 23
        mmix_instr_yz(OPCODES['SETL'], 4, 23),     # 0x0C
        mmix_instr(OPCODES['SUB'], 5, 3, 4),       # 0x10
        mmix_instr_yz(OPCODES['BZ'], 5, 2),        # 0x14
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x18
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x1C
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x20
    ], 0x1C, 0x20))

    # Test 17: 8ADDU (scaled address: $Y*8 + $Z)
    tests.append(('8addu', [
        mmix_instr_yz(OPCODES['SETL'], 1, 5),      # 0x00
        mmix_instr_yz(OPCODES['SETL'], 2, 3),      # 0x04
        mmix_instr(OPCODES['8ADDU'], 3, 1, 2),     # 0x08: $3 = 5*8 + 3 = 43
        mmix_instr_yz(OPCODES['SETL'], 4, 43),     # 0x0C
        mmix_instr(OPCODES['SUB'], 5, 3, 4),       # 0x10
        mmix_instr_yz(OPCODES['BZ'], 5, 2),        # 0x14
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x18
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x1C
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x20
    ], 0x1C, 0x20))

    # Test 18: 16ADDU (scaled address: $Y*16 + $Z)
    tests.append(('16addu', [
        mmix_instr_yz(OPCODES['SETL'], 1, 5),      # 0x00
        mmix_instr_yz(OPCODES['SETL'], 2, 3),      # 0x04
        mmix_instr(OPCODES['16ADDU'], 3, 1, 2),    # 0x08: $3 = 5*16 + 3 = 83
        mmix_instr_yz(OPCODES['SETL'], 4, 83),     # 0x0C
        mmix_instr(OPCODES['SUB'], 5, 3, 4),       # 0x10
        mmix_instr_yz(OPCODES['BZ'], 5, 2),        # 0x14
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x18
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x1C
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x20
    ], 0x1C, 0x20))

    # Test 19: NXOR (logical equivalence)
    tests.append(('nxor', [
        mmix_instr_yz(OPCODES['SETL'], 1, 0xFF),   # 0x00
        mmix_instr_yz(OPCODES['SETL'], 2, 0xFF),   # 0x04
        mmix_instr(OPCODES['NXOR'], 3, 1, 2),      # 0x08: $3 = ~(0xFF ^ 0xFF) = ~0 = all 1s
        # Low 16 bits should be 0xFFFF
        mmix_instr_yz(OPCODES['SETL'], 4, 0xFFFF), # 0x0C
        mmix_instr(OPCODES['AND'], 5, 3, 4),       # 0x10: mask to 16 bits
        mmix_instr(OPCODES['SUB'], 6, 5, 4),       # 0x14
        mmix_instr_yz(OPCODES['BZ'], 6, 2),        # 0x18
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x1C
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x20
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x24
    ], 0x20, 0x24))

    # Test 20: CMP (compare - equal)
    tests.append(('cmp_eq', [
        mmix_instr_yz(OPCODES['SETL'], 1, 42),     # 0x00
        mmix_instr_yz(OPCODES['SETL'], 2, 42),     # 0x04
        mmix_instr(OPCODES['CMP'], 3, 1, 2),       # 0x08: $3 = 0 (equal)
        mmix_instr_yz(OPCODES['BZ'], 3, 2),        # 0x0C
        mmix_instr_yz(OPCODES['JMP'], 0, 3),       # 0x10
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x14: pass
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x18: fail
    ], 0x14, 0x18))

    # Test 21: CMP (compare - greater)
    tests.append(('cmp_gt', [
        mmix_instr_yz(OPCODES['SETL'], 1, 50),     # 0x00
        mmix_instr_yz(OPCODES['SETL'], 2, 42),     # 0x04
        mmix_instr(OPCODES['CMP'], 3, 1, 2),       # 0x08: $3 = 1 (greater)
        mmix_instr_yz(OPCODES['SETL'], 4, 1),      # 0x0C
        mmix_instr(OPCODES['SUB'], 5, 3, 4),       # 0x10
        mmix_instr_yz(OPCODES['BZ'], 5, 2),        # 0x14
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x18
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x1C
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x20
    ], 0x1C, 0x20))

    # Test 22: CSZ (conditional set if zero)
    tests.append(('csz', [
        mmix_instr_yz(OPCODES['SETL'], 1, 0),      # 0x00: $1 = 0 (condition true)
        mmix_instr_yz(OPCODES['SETL'], 2, 99),     # 0x04: $2 = 99 (value to set)
        mmix_instr_yz(OPCODES['SETL'], 3, 0),      # 0x08: $3 = 0 (initial)
        mmix_instr(OPCODES['CSZ'], 3, 1, 2),       # 0x0C: if $1==0, $3 = $2
        mmix_instr_yz(OPCODES['SETL'], 4, 99),     # 0x10
        mmix_instr(OPCODES['SUB'], 5, 3, 4),       # 0x14
        mmix_instr_yz(OPCODES['BZ'], 5, 2),        # 0x18
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x1C
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x20
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x24
    ], 0x20, 0x24))

    # Test 23: CSZ (condition false - should not set)
    tests.append(('csz_false', [
        mmix_instr_yz(OPCODES['SETL'], 1, 5),      # 0x00: $1 = 5 (condition false)
        mmix_instr_yz(OPCODES['SETL'], 2, 99),     # 0x04: $2 = 99
        mmix_instr_yz(OPCODES['SETL'], 3, 42),     # 0x08: $3 = 42 (initial)
        mmix_instr(OPCODES['CSZ'], 3, 1, 2),       # 0x0C: if $1==0, $3 = $2 (won't happen)
        mmix_instr_yz(OPCODES['SETL'], 4, 42),     # 0x10: $3 should still be 42
        mmix_instr(OPCODES['SUB'], 5, 3, 4),       # 0x14
        mmix_instr_yz(OPCODES['BZ'], 5, 2),        # 0x18
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x1C
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x20
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x24
    ], 0x20, 0x24))

    # Test 24: ZSZ (zero or set if zero)
    tests.append(('zsz', [
        mmix_instr_yz(OPCODES['SETL'], 1, 0),      # 0x00: $1 = 0 (condition true)
        mmix_instr_yz(OPCODES['SETL'], 2, 77),     # 0x04: $2 = 77
        mmix_instr(OPCODES['ZSZ'], 3, 1, 2),       # 0x08: $3 = ($1==0) ? $2 : 0 = 77
        mmix_instr_yz(OPCODES['SETL'], 4, 77),     # 0x0C
        mmix_instr(OPCODES['SUB'], 5, 3, 4),       # 0x10
        mmix_instr_yz(OPCODES['BZ'], 5, 2),        # 0x14
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x18
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x1C
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x20
    ], 0x1C, 0x20))

    # Test 25: ZSZ (condition false - should be zero)
    tests.append(('zsz_false', [
        mmix_instr_yz(OPCODES['SETL'], 1, 5),      # 0x00: $1 = 5 (condition false)
        mmix_instr_yz(OPCODES['SETL'], 2, 77),     # 0x04: $2 = 77
        mmix_instr(OPCODES['ZSZ'], 3, 1, 2),       # 0x08: $3 = ($1==0) ? $2 : 0 = 0
        mmix_instr_yz(OPCODES['BZ'], 3, 2),        # 0x0C: $3 should be 0
        mmix_instr_yz(OPCODES['JMP'], 0, 3),       # 0x10
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x14: pass
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x18: fail
    ], 0x14, 0x18))

    # Test 26: NOR
    tests.append(('nor', [
        mmix_instr_yz(OPCODES['SETL'], 1, 0x00),   # 0x00
        mmix_instr_yz(OPCODES['SETL'], 2, 0x00),   # 0x04
        mmix_instr(OPCODES['NOR'], 3, 1, 2),       # 0x08: $3 = ~(0 | 0) = all 1s
        mmix_instr_yz(OPCODES['SETL'], 4, 0xFFFF), # 0x0C
        mmix_instr(OPCODES['AND'], 5, 3, 4),       # 0x10: mask to 16 bits
        mmix_instr(OPCODES['SUB'], 6, 5, 4),       # 0x14
        mmix_instr_yz(OPCODES['BZ'], 6, 2),        # 0x18
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x1C
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x20
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x24
    ], 0x20, 0x24))

    # Test 27: NAND
    tests.append(('nand', [
        mmix_instr_yz(OPCODES['SETL'], 1, 0xFFFF), # 0x00
        mmix_instr_yz(OPCODES['SETL'], 2, 0xFFFF), # 0x04
        mmix_instr(OPCODES['NAND'], 3, 1, 2),      # 0x08: $3 = ~(0xFFFF & 0xFFFF) = ~0xFFFF
        mmix_instr_yz(OPCODES['SETL'], 4, 0xFFFF), # 0x0C
        mmix_instr(OPCODES['AND'], 5, 3, 4),       # 0x10: mask to 16 bits - should be 0
        mmix_instr_yz(OPCODES['BZ'], 5, 2),        # 0x14
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x18
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x1C
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x20
    ], 0x1C, 0x20))

    # Test 28: NEG (negate)
    tests.append(('neg', [
        mmix_instr_yz(OPCODES['SETL'], 1, 5),      # 0x00: $1 = 5
        mmix_instr(OPCODES['NEG'], 2, 0, 1),       # 0x04: $2 = 0 - $1 = -5
        mmix_instr(OPCODES['ADD'], 3, 1, 2),       # 0x08: $3 = 5 + (-5) = 0
        mmix_instr_yz(OPCODES['BZ'], 3, 2),        # 0x0C
        mmix_instr_yz(OPCODES['JMP'], 0, 3),       # 0x10
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x14: pass
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x18: fail
    ], 0x14, 0x18))

    # Test 29: BN (branch if negative)
    tests.append(('bn', [
        mmix_instr_yz(OPCODES['SETL'], 1, 5),      # 0x00
        mmix_instr(OPCODES['NEG'], 1, 0, 1),       # 0x04: $1 = -5
        mmix_instr_yz(OPCODES['BN'], 1, 2),        # 0x08: BN should branch
        mmix_instr_yz(OPCODES['JMP'], 0, 3),       # 0x0C: to fail
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x10: pass
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x14: fail
    ], 0x10, 0x14))

    # Test 30: BP (branch if positive)
    tests.append(('bp', [
        mmix_instr_yz(OPCODES['SETL'], 1, 5),      # 0x00: $1 = 5 (positive)
        mmix_instr_yz(OPCODES['BP'], 1, 2),        # 0x04: BP should branch
        mmix_instr_yz(OPCODES['JMP'], 0, 3),       # 0x08: to fail
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x0C: pass
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x10: fail
    ], 0x0C, 0x10))

    # Test 31: INCH (increment high wyde)
    tests.append(('inch', [
        mmix_instr_yz(OPCODES['SETL'], 1, 0),      # 0x00: $1 = 0
        mmix_instr_yz(OPCODES['INCH'], 1, 1),      # 0x04: $1 += 1 << 48
        # The result should have bit 48 set
        mmix_instr(OPCODES['SRUI'], 2, 1, 48),     # 0x08: $2 = $1 >> 48
        mmix_instr_yz(OPCODES['SETL'], 3, 1),      # 0x0C
        mmix_instr(OPCODES['SUB'], 4, 2, 3),       # 0x10
        mmix_instr_yz(OPCODES['BZ'], 4, 2),        # 0x14
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x18
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x1C
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x20
    ], 0x1C, 0x20))

    # Test 32: SL (shift left - register)
    tests.append(('sl', [
        mmix_instr_yz(OPCODES['SETL'], 1, 1),      # 0x00: $1 = 1
        mmix_instr_yz(OPCODES['SETL'], 2, 4),      # 0x04: $2 = 4
        mmix_instr(OPCODES['SL'], 3, 1, 2),        # 0x08: $3 = 1 << 4 = 16
        mmix_instr_yz(OPCODES['SETL'], 4, 16),     # 0x0C
        mmix_instr(OPCODES['SUB'], 5, 3, 4),       # 0x10
        mmix_instr_yz(OPCODES['BZ'], 5, 2),        # 0x14
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x18
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x1C
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x20
    ], 0x1C, 0x20))

    # Test 33: SR (shift right - register, signed)
    tests.append(('sr', [
        mmix_instr_yz(OPCODES['SETL'], 1, 64),     # 0x00: $1 = 64
        mmix_instr_yz(OPCODES['SETL'], 2, 3),      # 0x04: $2 = 3
        mmix_instr(OPCODES['SR'], 3, 1, 2),        # 0x08: $3 = 64 >> 3 = 8
        mmix_instr_yz(OPCODES['SETL'], 4, 8),      # 0x0C
        mmix_instr(OPCODES['SUB'], 5, 3, 4),       # 0x10
        mmix_instr_yz(OPCODES['BZ'], 5, 2),        # 0x14
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x18
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x1C
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x20
    ], 0x1C, 0x20))

    # Test 34: MULU (unsigned multiply)
    tests.append(('mulu', [
        mmix_instr_yz(OPCODES['SETL'], 1, 1000),   # 0x00
        mmix_instr_yz(OPCODES['SETL'], 2, 1000),   # 0x04
        mmix_instr(OPCODES['MULU'], 3, 1, 2),      # 0x08: $3 = 1000 * 1000 = 1000000
        # Check lower bits: 1000000 & 0xFFFF = 0x4240
        mmix_instr_yz(OPCODES['SETL'], 4, 0x4240), # 0x0C: 1000000 = 0xF4240, low 16 = 0x4240
        mmix_instr_yz(OPCODES['SETL'], 5, 0xFFFF), # 0x10
        mmix_instr(OPCODES['AND'], 6, 3, 5),       # 0x14: mask to 16 bits
        mmix_instr(OPCODES['SUB'], 7, 6, 4),       # 0x18
        mmix_instr_yz(OPCODES['BZ'], 7, 2),        # 0x1C
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x20
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x24
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x28
    ], 0x24, 0x28))

    # Test 35: DIVU (unsigned divide)
    tests.append(('divu', [
        mmix_instr_yz(OPCODES['SETL'], 1, 100),    # 0x00
        mmix_instr_yz(OPCODES['SETL'], 2, 7),      # 0x04
        mmix_instr(OPCODES['DIVU'], 3, 1, 2),      # 0x08: $3 = 100 / 7 = 14
        mmix_instr_yz(OPCODES['SETL'], 4, 14),     # 0x0C
        mmix_instr(OPCODES['SUB'], 5, 3, 4),       # 0x10
        mmix_instr_yz(OPCODES['BZ'], 5, 2),        # 0x14
        mmix_instr_yz(OPCODES['JMP'], 0, 2),       # 0x18
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x1C
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # 0x20
    ], 0x1C, 0x20))

    # =========================================================================
    # Floating-Point Tests (require --with-fp flag when generating processor)
    # =========================================================================
    # FP64 bit patterns:
    #   1.0 = 0x3FF0_0000_0000_0000
    #   2.0 = 0x4000_0000_0000_0000
    #   3.0 = 0x4008_0000_0000_0000
    #   4.0 = 0x4010_0000_0000_0000
    #   0.5 = 0x3FE0_0000_0000_0000
    #  -1.0 = 0xBFF0_0000_0000_0000
    #   NaN = 0x7FF8_0000_0000_0000 (quiet NaN)
    # =========================================================================

    # Test 36: FADD (1.0 + 2.0 = 3.0)
    # Build 1.0 = 0x3FF0_0000_0000_0000, 2.0 = 0x4000_0000_0000_0000
    # Expected: 3.0 = 0x4008_0000_0000_0000
    tests.append(('fadd', [
        mmix_instr_yz(OPCODES['SETH'], 1, 0x3FF0), # $1 = 1.0
        mmix_instr_yz(OPCODES['SETH'], 2, 0x4000), # $2 = 2.0
        mmix_instr(OPCODES['FADD'], 3, 1, 2),      # $3 = 1.0 + 2.0 = 3.0
        mmix_instr_yz(OPCODES['SETH'], 4, 0x4008), # $4 = 3.0 (expected)
        mmix_instr(OPCODES['SUB'], 5, 3, 4),       # Compare bit patterns
        mmix_instr_yz(OPCODES['BZ'], 5, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # pass
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # fail
    ], 0x1C, 0x20))

    # Test 37: FSUB (3.0 - 1.0 = 2.0)
    tests.append(('fsub', [
        mmix_instr_yz(OPCODES['SETH'], 1, 0x4008), # $1 = 3.0
        mmix_instr_yz(OPCODES['SETH'], 2, 0x3FF0), # $2 = 1.0
        mmix_instr(OPCODES['FSUB'], 3, 1, 2),      # $3 = 3.0 - 1.0 = 2.0
        mmix_instr_yz(OPCODES['SETH'], 4, 0x4000), # $4 = 2.0 (expected)
        mmix_instr(OPCODES['SUB'], 5, 3, 4),       # Compare bit patterns
        mmix_instr_yz(OPCODES['BZ'], 5, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # pass
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # fail
    ], 0x1C, 0x20))

    # Test 38: FMUL (2.0 * 2.0 = 4.0)
    tests.append(('fmul', [
        mmix_instr_yz(OPCODES['SETH'], 1, 0x4000), # $1 = 2.0
        mmix_instr_yz(OPCODES['SETH'], 2, 0x4000), # $2 = 2.0
        mmix_instr(OPCODES['FMUL'], 3, 1, 2),      # $3 = 2.0 * 2.0 = 4.0
        mmix_instr_yz(OPCODES['SETH'], 4, 0x4010), # $4 = 4.0 (expected)
        mmix_instr(OPCODES['SUB'], 5, 3, 4),       # Compare bit patterns
        mmix_instr_yz(OPCODES['BZ'], 5, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # pass
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # fail
    ], 0x1C, 0x20))

    # Test 39: FDIV (4.0 / 2.0 = 2.0)
    tests.append(('fdiv', [
        mmix_instr_yz(OPCODES['SETH'], 1, 0x4010), # $1 = 4.0
        mmix_instr_yz(OPCODES['SETH'], 2, 0x4000), # $2 = 2.0
        mmix_instr(OPCODES['FDIV'], 3, 1, 2),      # $3 = 4.0 / 2.0 = 2.0
        mmix_instr_yz(OPCODES['SETH'], 4, 0x4000), # $4 = 2.0 (expected)
        mmix_instr(OPCODES['SUB'], 5, 3, 4),       # Compare bit patterns
        mmix_instr_yz(OPCODES['BZ'], 5, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # pass
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # fail
    ], 0x1C, 0x20))

    # Test 40: FSQRT (sqrt(4.0) = 2.0)
    tests.append(('fsqrt', [
        mmix_instr_yz(OPCODES['SETH'], 1, 0x4010), # $1 = 4.0
        mmix_instr(OPCODES['FSQRT'], 2, 0, 1),     # $2 = sqrt(4.0) = 2.0
        mmix_instr_yz(OPCODES['SETH'], 3, 0x4000), # $3 = 2.0 (expected)
        mmix_instr(OPCODES['SUB'], 4, 2, 3),       # Compare bit patterns
        mmix_instr_yz(OPCODES['BZ'], 4, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # pass
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # fail
    ], 0x18, 0x1C))

    # Test 41: FCMP (1.0 < 2.0, should return -1 = 0xFFFFFFFFFFFFFFFF)
    tests.append(('fcmp_lt', [
        mmix_instr_yz(OPCODES['SETH'], 1, 0x3FF0), # $1 = 1.0
        mmix_instr_yz(OPCODES['SETH'], 2, 0x4000), # $2 = 2.0
        mmix_instr(OPCODES['FCMP'], 3, 1, 2),      # $3 = fcmp(1.0, 2.0) = -1
        # Check if $3 is negative (high bit set)
        mmix_instr_yz(OPCODES['BN'], 3, 2),        # Branch if negative
        mmix_instr_yz(OPCODES['JMP'], 0, 3),       # fail
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # pass
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # fail
    ], 0x14, 0x18))

    # Test 42: FCMP (2.0 > 1.0, should return 1)
    tests.append(('fcmp_gt', [
        mmix_instr_yz(OPCODES['SETH'], 1, 0x4000), # $1 = 2.0
        mmix_instr_yz(OPCODES['SETH'], 2, 0x3FF0), # $2 = 1.0
        mmix_instr(OPCODES['FCMP'], 3, 1, 2),      # $3 = fcmp(2.0, 1.0) = 1
        mmix_instr_yz(OPCODES['SETL'], 4, 1),      # $4 = 1
        mmix_instr(OPCODES['SUB'], 5, 3, 4),
        mmix_instr_yz(OPCODES['BZ'], 5, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # pass
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # fail
    ], 0x1C, 0x20))

    # Test 43: FCMP (2.0 == 2.0, should return 0)
    tests.append(('fcmp_eq', [
        mmix_instr_yz(OPCODES['SETH'], 1, 0x4000), # $1 = 2.0
        mmix_instr_yz(OPCODES['SETH'], 2, 0x4000), # $2 = 2.0
        mmix_instr(OPCODES['FCMP'], 3, 1, 2),      # $3 = fcmp(2.0, 2.0) = 0
        mmix_instr_yz(OPCODES['BZ'], 3, 2),        # Branch if zero
        mmix_instr_yz(OPCODES['JMP'], 0, 3),       # fail
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # pass
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # fail
    ], 0x14, 0x18))

    # Test 44: FEQL (2.0 == 2.0, should return 1)
    tests.append(('feql', [
        mmix_instr_yz(OPCODES['SETH'], 1, 0x4000), # $1 = 2.0
        mmix_instr_yz(OPCODES['SETH'], 2, 0x4000), # $2 = 2.0
        mmix_instr(OPCODES['FEQL'], 3, 1, 2),      # $3 = feql(2.0, 2.0) = 1
        mmix_instr_yz(OPCODES['SETL'], 4, 1),
        mmix_instr(OPCODES['SUB'], 5, 3, 4),
        mmix_instr_yz(OPCODES['BZ'], 5, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # pass
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # fail
    ], 0x1C, 0x20))

    # Test 45: FEQL (1.0 != 2.0, should return 0)
    tests.append(('feql_ne', [
        mmix_instr_yz(OPCODES['SETH'], 1, 0x3FF0), # $1 = 1.0
        mmix_instr_yz(OPCODES['SETH'], 2, 0x4000), # $2 = 2.0
        mmix_instr(OPCODES['FEQL'], 3, 1, 2),      # $3 = feql(1.0, 2.0) = 0
        mmix_instr_yz(OPCODES['BZ'], 3, 2),        # Branch if zero
        mmix_instr_yz(OPCODES['JMP'], 0, 3),       # fail
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # pass
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # fail
    ], 0x14, 0x18))

    # Test 46: FUN (neither is NaN, should return 0)
    tests.append(('fun_ordered', [
        mmix_instr_yz(OPCODES['SETH'], 1, 0x3FF0), # $1 = 1.0
        mmix_instr_yz(OPCODES['SETH'], 2, 0x4000), # $2 = 2.0
        mmix_instr(OPCODES['FUN'], 3, 1, 2),       # $3 = fun(1.0, 2.0) = 0
        mmix_instr_yz(OPCODES['BZ'], 3, 2),        # Branch if zero
        mmix_instr_yz(OPCODES['JMP'], 0, 3),       # fail
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # pass
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # fail
    ], 0x14, 0x18))

    # Test 47: FUN (one is NaN, should return 1)
    # NaN = 0x7FF8_0000_0000_0000
    tests.append(('fun_nan', [
        mmix_instr_yz(OPCODES['SETH'], 1, 0x7FF8), # $1 = quiet NaN
        mmix_instr_yz(OPCODES['SETH'], 2, 0x4000), # $2 = 2.0
        mmix_instr(OPCODES['FUN'], 3, 1, 2),       # $3 = fun(NaN, 2.0) = 1
        mmix_instr_yz(OPCODES['SETL'], 4, 1),
        mmix_instr(OPCODES['SUB'], 5, 3, 4),
        mmix_instr_yz(OPCODES['BZ'], 5, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # pass
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # fail
    ], 0x1C, 0x20))

    # Test 48: FLOT (convert int 2 to FP = 2.0)
    tests.append(('flot', [
        mmix_instr_yz(OPCODES['SETL'], 1, 2),      # $1 = 2 (integer)
        mmix_instr(OPCODES['FLOT'], 2, 0, 1),      # $2 = (float)2 = 2.0
        mmix_instr_yz(OPCODES['SETH'], 3, 0x4000), # $3 = 2.0 (expected)
        mmix_instr(OPCODES['SUB'], 4, 2, 3),
        mmix_instr_yz(OPCODES['BZ'], 4, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # pass
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # fail
    ], 0x18, 0x1C))

    # Test 49: FLOTI (convert immediate 3 to FP = 3.0)
    tests.append(('floti', [
        mmix_instr(OPCODES['FLOTI'], 1, 0, 3),     # $1 = (float)3 = 3.0
        mmix_instr_yz(OPCODES['SETH'], 2, 0x4008), # $2 = 3.0 (expected)
        mmix_instr(OPCODES['SUB'], 3, 1, 2),
        mmix_instr_yz(OPCODES['BZ'], 3, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # pass
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # fail
    ], 0x14, 0x18))

    # Test 50: FIX (convert 2.0 to int = 2)
    tests.append(('fix', [
        mmix_instr_yz(OPCODES['SETH'], 1, 0x4000), # $1 = 2.0
        mmix_instr(OPCODES['FIX'], 2, 0, 1),       # $2 = (int)2.0 = 2
        mmix_instr_yz(OPCODES['SETL'], 3, 2),      # $3 = 2 (expected)
        mmix_instr(OPCODES['SUB'], 4, 2, 3),
        mmix_instr_yz(OPCODES['BZ'], 4, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # pass
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # fail
    ], 0x18, 0x1C))

    # Test 51: FIXU (convert 3.0 to unsigned int = 3)
    tests.append(('fixu', [
        mmix_instr_yz(OPCODES['SETH'], 1, 0x4008), # $1 = 3.0
        mmix_instr(OPCODES['FIXU'], 2, 0, 1),      # $2 = (unsigned)3.0 = 3
        mmix_instr_yz(OPCODES['SETL'], 3, 3),      # $3 = 3 (expected)
        mmix_instr(OPCODES['SUB'], 4, 2, 3),
        mmix_instr_yz(OPCODES['BZ'], 4, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # pass
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # fail
    ], 0x18, 0x1C))

    # Test 52: FLOTU (convert unsigned 4 to FP = 4.0)
    tests.append(('flotu', [
        mmix_instr_yz(OPCODES['SETL'], 1, 4),      # $1 = 4 (unsigned)
        mmix_instr(OPCODES['FLOTU'], 2, 0, 1),     # $2 = (float)4 = 4.0
        mmix_instr_yz(OPCODES['SETH'], 3, 0x4010), # $3 = 4.0 (expected)
        mmix_instr(OPCODES['SUB'], 4, 2, 3),
        mmix_instr_yz(OPCODES['BZ'], 4, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 2),
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # pass
        mmix_instr_yz(OPCODES['JMP'], 0, 0),       # fail
    ], 0x18, 0x1C))

    return tests


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Run MMIX ISA tests')
    parser.add_argument('--processor-dir', '-p',
                        default='examples/verilog/mmix_complete',
                        help='Directory containing generated processor')
    parser.add_argument('--simulator', '-s',
                        help='Path to simulator executable (Verilator binary). If not specified, uses iverilog.')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output')
    args = parser.parse_args()

    # Change to processor directory
    processor_dir = Path(args.processor_dir)
    if not processor_dir.exists():
        print(f"Error: Processor directory not found: {processor_dir}")
        return 1

    # Check for compiled simulator
    if args.simulator:
        sim_path = Path(args.simulator)
        if not sim_path.exists():
            print(f"Error: Simulator not found: {sim_path}")
            return 1
        print(f"Using simulator: {sim_path}")
    else:
        sim_vvp = processor_dir / 'sim.vvp'
        if not sim_vvp.exists():
            print("Compiling simulator with iverilog...")
            result = subprocess.run(
                ['iverilog', '-g2012', '-o', 'sim.vvp',
                 'mmix_complete.v', 'mmix_complete_tb.sv'],
                cwd=processor_dir,
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                print(f"Compilation failed: {result.stderr}")
                return 1

    print("=" * 60)
    print("MMIX ISA Test Suite")
    print("=" * 60)
    print(f"Processor: {processor_dir}")
    if args.simulator:
        print(f"Simulator: {args.simulator}")
    print()

    tests = define_tests()
    passed = 0
    failed = 0

    for test_name, instrs, pass_addr, fail_addr in tests:
        result = run_test(test_name, instrs, pass_addr, fail_addr,
                          processor_dir, args.verbose, args.simulator)
        if result:
            passed += 1
        else:
            failed += 1

    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
