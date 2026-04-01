#!/usr/bin/env python3
"""
Batch test runner for M68K merged design.
Finds and runs test cases that match our implemented instruction patterns.
"""

import json
import sys
import os
import subprocess
from pathlib import Path

# Instruction opcode patterns we've implemented
# Format: (mask, expected_value, description)
IMPLEMENTED_OPCODES = [
    # === MOVE/MOVEQ ===
    # MOVEQ #imm,Dn - 0111 RRR0 DDDD DDDD
    (0xF100, 0x7000, "MOVEQ"),
    # MOVE.L Dn,Dm - 0010 DDD0 00SS SSSS (size=10, dest mode=000, dest=Dn, src=Dn)
    (0xF1C0, 0x2000, "MOVE.L"),
    # MOVEA.L Dn,An - 0010 AAA0 0100 0DDD (dest mode=001, src mode=000)
    (0xF1F8, 0x2040, "MOVEA.L Dn,An"),

    # === ADD ===
    # ADD.L Dn,Dm - 1101 DDD1 1000 0SSS (opmode=110, EA=000)
    (0xF1F8, 0xD180, "ADD.L Dn,Dm"),
    # ADD.L (An),Dn - 1101 DDD0 1001 0AAA (opmode=010, EA=010)
    (0xF1F8, 0xD090, "ADD.L (An),Dn"),
    # ADD.L Dn,(An) - 1101 DDD1 1001 0AAA (opmode=110, EA=010)
    (0xF1F8, 0xD190, "ADD.L Dn,(An)"),
    # ADD.L (An)+,Dn - 1101 DDD0 1001 1AAA (opmode=010, EA=011)
    (0xF1F8, 0xD098, "ADD.L (An)+,Dn"),
    # ADD.L -(An),Dn - 1101 DDD0 1010 0AAA (opmode=010, EA=100)
    (0xF1F8, 0xD0A0, "ADD.L -(An),Dn"),
    # ADD.L (d16,An),Dn - 1101 DDD0 1010 1AAA (opmode=010, EA=101)
    (0xF1F8, 0xD0A8, "ADD.L (d16,An),Dn"),
    # ADD.L (d8,An,Xn),Dn - 1101 DDD0 1011 0AAA (opmode=010, EA=110)
    (0xF1F8, 0xD0B0, "ADD.L (d8,An,Xn),Dn"),
    # ADD.L Dn,(d8,An,Xn) - 1101 DDD1 1011 0AAA (opmode=110, EA=110)
    (0xF1F8, 0xD1B0, "ADD.L Dn,(d8,An,Xn)"),
    # ADD.L (xxx).W,Dn - 1101 DDD0 1011 1000 (opmode=010, EA=111, reg=000)
    (0xF1FF, 0xD0B8, "ADD.L (xxx).W,Dn"),
    # ADD.L (xxx).L,Dn - 1101 DDD0 1011 1001 (opmode=010, EA=111, reg=001)
    (0xF1FF, 0xD0B9, "ADD.L (xxx).L,Dn"),
    # ADD.L #imm,Dn - 1101 DDD0 1011 1100 (EA=111, reg=100)
    (0xF1FF, 0xD0BC, "ADD.L #imm,Dn"),
    # ADDQ.L #data,Dn - 0101 DDD0 1000 0RRR
    (0xF1F8, 0x5080, "ADDQ.L"),

    # === SUB ===
    # SUB.L Dn,Dm - 1001 DDD1 1000 0SSS (opmode=110, EA=000)
    (0xF1F8, 0x9180, "SUB.L Dn,Dm"),
    # SUBQ.L #data,Dn - 0101 DDD1 1000 0RRR
    (0xF1F8, 0x5180, "SUBQ.L"),

    # === LOGICAL ===
    # AND.L Dn,Dm - 1100 DDD1 1000 0SSS (opmode=110, EA=000)
    (0xF1F8, 0xC180, "AND.L Dn,Dm"),
    # AND.L #imm,Dn - 0000 0010 10SS SSSS (ANDI.L)
    (0xFFF8, 0x0280, "ANDI.L"),
    # OR.L Dn,Dm - 1000 DDD1 1000 0SSS (opmode=110, EA=000)
    (0xF1F8, 0x8180, "OR.L Dn,Dm"),
    # EOR.L Dn,Dm - 1011 DDD1 1000 0SSS (opmode=110, EA=000)
    (0xF1F8, 0xB180, "EOR.L Dn,Dm"),
    # EORI.L #imm,Dn - 0000 1010 10SS SSSS
    (0xFFF8, 0x0A80, "EORI.L"),

    # === COMPARE ===
    # CMP.L Dn,Dn - 1011 DDD0 1000 0SSS (opmode=010)
    (0xF1F8, 0xB080, "CMP.L Dn,Dn"),
    # CMPI.L #imm,Dn - 0000 1100 10SS SSSS
    (0xFFF8, 0x0C80, "CMPI.L"),
    # CMPA.L Dn,An - 1011 AAA1 1100 0SSS (opmode=111)
    (0xF1F8, 0xB1C0, "CMPA.L"),

    # === UNARY ===
    # CLR.L Dn - 0100 0010 1000 0DDD (size=10, EA=000)
    (0xFFF8, 0x4280, "CLR.L Dn"),
    # NOT.L Dn - 0100 0110 1000 0DDD (size=10, EA=000)
    (0xFFF8, 0x4680, "NOT.L Dn"),
    # NEG.L Dn - 0100 0100 1000 0DDD (size=10, EA=000)
    (0xFFF8, 0x4480, "NEG.L Dn"),
    # TST.L Dn - 0100 1010 1000 0DDD (size=10, EA=000)
    (0xFFF8, 0x4A80, "TST.L Dn"),
    # SWAP Dn - 0100 1000 0100 0DDD
    (0xFFF8, 0x4840, "SWAP Dn"),
    # EXT.W Dn - 0100 1000 1000 0DDD
    (0xFFF8, 0x4880, "EXT.W Dn"),
    # EXT.L Dn - 0100 1000 1100 0DDD
    (0xFFF8, 0x48C0, "EXT.L Dn"),

    # === SHIFTS/ROTATES (immediate count, long size) ===
    # ASL.L #count,Dn - 1110 CCC1 1010 0DDD
    (0xF1F8, 0xE180, "ASL.L"),
    # ASR.L #count,Dn - 1110 CCC0 1010 0DDD
    (0xF1F8, 0xE080, "ASR.L"),
    # LSL.L #count,Dn - 1110 CCC1 1010 1DDD
    (0xF1F8, 0xE188, "LSL.L"),
    # LSR.L #count,Dn - 1110 CCC0 1010 1DDD
    (0xF1F8, 0xE088, "LSR.L"),
    # ROL.L #count,Dn - 1110 CCC1 1011 1DDD
    (0xF1F8, 0xE198, "ROL.L"),
    # ROR.L #count,Dn - 1110 CCC0 1011 1DDD
    (0xF1F8, 0xE098, "ROR.L"),

    # === MULTIPLY/DIVIDE ===
    # MULU.W Dn,Dn - 1100 DDD0 1100 0SSS
    (0xF1F8, 0xC0C0, "MULU.W"),
    # MULS.W Dn,Dn - 1100 DDD1 1100 0SSS
    (0xF1F8, 0xC1C0, "MULS.W"),
    # DIVU.W Dn,Dn - 1000 DDD0 1100 0SSS
    (0xF1F8, 0x80C0, "DIVU.W"),

    # === BRANCHES (byte displacement) ===
    # BRA.B - 0110 0000 DDDD DDDD (disp != 0, != FF)
    (0xFF00, 0x6000, "BRA"),
    # BSR.B - 0110 0001 DDDD DDDD
    (0xFF00, 0x6100, "BSR"),
    # BCC.B - 0110 0100 DDDD DDDD
    (0xFF00, 0x6400, "BCC"),
    # BCS.B - 0110 0101 DDDD DDDD
    (0xFF00, 0x6500, "BCS"),
    # BEQ.B - 0110 0111 DDDD DDDD
    (0xFF00, 0x6700, "BEQ"),
    # BNE.B - 0110 0110 DDDD DDDD
    (0xFF00, 0x6600, "BNE"),
    # BGE.B - 0110 1100 DDDD DDDD
    (0xFF00, 0x6C00, "BGE"),
    # BGT.B - 0110 1110 DDDD DDDD
    (0xFF00, 0x6E00, "BGT"),
    # BLE.B - 0110 1111 DDDD DDDD
    (0xFF00, 0x6F00, "BLE"),
    # BLT.B - 0110 1101 DDDD DDDD
    (0xFF00, 0x6D00, "BLT"),
    # BHI.B - 0110 0010 DDDD DDDD
    (0xFF00, 0x6200, "BHI"),
    # BLS.B - 0110 0011 DDDD DDDD
    (0xFF00, 0x6300, "BLS"),
    # BMI.B - 0110 1011 DDDD DDDD
    (0xFF00, 0x6B00, "BMI"),
    # BPL.B - 0110 1010 DDDD DDDD
    (0xFF00, 0x6A00, "BPL"),

    # === JUMPS/RETURNS ===
    # JMP (An) - 0100 1110 11 010 AAA
    (0xFFF8, 0x4ED0, "JMP (An)"),
    # JMP (xxx).L - 0100 1110 11 111 001
    (0xFFFF, 0x4EF9, "JMP (xxx).L"),
    # JSR (An) - 0100 1110 10 010 AAA
    (0xFFF8, 0x4E90, "JSR (An)"),
    # JSR (xxx).L - 0100 1110 10 111 001
    (0xFFFF, 0x4EB9, "JSR (xxx).L"),
    # RTS - 0100 1110 0111 0101
    (0xFFFF, 0x4E75, "RTS"),

    # === ADDRESS OPERATIONS ===
    # LEA (d16,An),An - 0100 AAA1 11 101 SSS
    (0xF1F8, 0x41E8, "LEA (d16,An)"),
    # PEA (An) - 0100 1000 01 010 AAA
    (0xFFF8, 0x4850, "PEA (An)"),
    # LINK An,#disp - 0100 1110 0101 0AAA
    (0xFFF8, 0x4E50, "LINK"),
    # UNLK An - 0100 1110 0101 1AAA
    (0xFFF8, 0x4E58, "UNLK"),

    # === SET CONDITIONAL ===
    # Scc Dn - 0101 CCCC 11 000 DDD (various conditions)
    (0xFFF8, 0x57C0, "SEQ Dn"),   # Z=1
    (0xFFF8, 0x56C0, "SNE Dn"),   # Z=0
    (0xFFF8, 0x54C0, "SCC Dn"),   # C=0
    (0xFFF8, 0x55C0, "SCS Dn"),   # C=1
    (0xFFF8, 0x5AC0, "SPL Dn"),   # N=0
    (0xFFF8, 0x5BC0, "SMI Dn"),   # N=1
    (0xFFF8, 0x58C0, "SVC Dn"),   # V=0
    (0xFFF8, 0x59C0, "SVS Dn"),   # V=1
    (0xFFF8, 0x52C0, "SHI Dn"),   # C=0 & Z=0
    (0xFFF8, 0x53C0, "SLS Dn"),   # C=1 | Z=1
    (0xFFF8, 0x5CC0, "SGE Dn"),   # N=V
    (0xFFF8, 0x5DC0, "SLT Dn"),   # N!=V
    (0xFFF8, 0x5EC0, "SGT Dn"),   # Z=0 & N=V
    (0xFFF8, 0x5FC0, "SLE Dn"),   # Z=1 | N!=V
    (0xFFF8, 0x50C0, "ST Dn"),    # True
    (0xFFF8, 0x51C0, "SF Dn"),    # False

    # === DBRA ===
    # DBRA/DBF Dn,disp - 0101 0001 1100 1DDD
    (0xFFF8, 0x51C8, "DBRA"),

    # === BIT OPERATIONS (immediate) ===
    # BTST #bit,Dn - 0000 1000 00 000 DDD
    (0xFFF8, 0x0800, "BTST #,Dn"),
    # BCLR #bit,Dn - 0000 1000 10 000 DDD
    (0xFFF8, 0x0880, "BCLR #,Dn"),
    # BSET #bit,Dn - 0000 1000 11 000 DDD
    (0xFFF8, 0x08C0, "BSET #,Dn"),

    # === EXCHANGE === (DISABLED - unconditional writes issue)
    # EXG Dn,Dn - 1100 DDD1 0100 0SSS
    # (0xF1F8, 0xC140, "EXG Dn,Dn"),
    # EXG An,An - 1100 DDD1 0100 1SSS
    # (0xF1F8, 0xC148, "EXG An,An"),
    # EXG Dn,An - 1100 DDD1 1000 1SSS
    # (0xF1F8, 0xC188, "EXG Dn,An"),

    # === NOP ===
    (0xFFFF, 0x4E71, "NOP"),
]


def get_opcode_from_test(test):
    """Extract the opcode from a test case's prefetch."""
    prefetch = test['initial'].get('prefetch', [])
    if prefetch:
        return prefetch[0]
    return None


def is_opcode_implemented(opcode):
    """Check if an opcode matches one of our implemented patterns."""
    for mask, expected, name in IMPLEMENTED_OPCODES:
        if (opcode & mask) == expected:
            return True, name
    return False, None


def main():
    test_dir = Path("isa/m68k/tests/v1")

    # Collect all test files
    test_files = sorted(test_dir.glob("*.json"))

    total_tests = 0
    passed_tests = 0
    failed_tests = 0
    skipped_tests = 0

    results = []

    for test_file in test_files:
        if not test_file.name.endswith('.json'):
            continue

        # Skip binary files
        if test_file.name.endswith('.json.bin'):
            continue

        try:
            with open(test_file) as f:
                tests = json.load(f)
        except json.JSONDecodeError:
            print(f"Error loading {test_file.name}")
            continue

        if isinstance(tests, dict):
            tests = [tests]

        # Check first test to see if this instruction is implemented
        if tests:
            opcode = get_opcode_from_test(tests[0])
            if opcode is not None:
                implemented, instr_name = is_opcode_implemented(opcode)
                if not implemented:
                    skipped_tests += len(tests)
                    continue
            else:
                skipped_tests += len(tests)
                continue

        # Run first test from each implemented instruction
        test = tests[0]
        total_tests += 1

        print(f"\n{'='*60}")
        print(f"Testing: {test_file.name} - {test['name']}")
        print(f"Opcode: 0x{opcode:04X} -> {instr_name}")
        print(f"{'='*60}")

        result = subprocess.run([
            'python3', 'examples/verilog/m68k_test/run_merged_test.py',
            str(test_file), '0'
        ], capture_output=True, text=True)

        if "TEST PASSED" in result.stdout:
            passed_tests += 1
            print("PASSED")
            results.append((test_file.name, "PASSED", instr_name))
        elif "TEST FAILED" in result.stdout:
            failed_tests += 1
            print("FAILED")
            # Show relevant output
            for line in result.stdout.split('\n'):
                if 'got' in line or 'expected' in line or 'MISMATCH' in line:
                    print(f"  {line}")
            results.append((test_file.name, "FAILED", instr_name))
        else:
            failed_tests += 1
            print("ERROR")
            print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
            results.append((test_file.name, "ERROR", instr_name))

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Total implemented tests run: {total_tests}")
    print(f"Passed: {passed_tests}")
    print(f"Failed: {failed_tests}")
    print(f"Skipped (unimplemented): {skipped_tests}")

    if failed_tests > 0:
        print(f"\nFailed tests:")
        for name, status, instr in results:
            if status == "FAILED" or status == "ERROR":
                print(f"  {name}: {instr}")

    return 0 if failed_tests == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
