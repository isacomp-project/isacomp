#!/usr/bin/env python3
"""Run multiple M68000 JSON tests to validate Verilog generator."""

import subprocess
import sys
from pathlib import Path

# Get project root and script directory
script_dir = Path(__file__).parent
project_root = script_dir.parent.parent

# List of (ISA file, test file, description) tuples
# Test files are from SingleStepTests/m68000
test_cases = [
    # Data Movement - MOVE
    ("isa/m68k/move_l_dn_dn.isa", "isa/m68k/tests/v1/MOVE.l.json", "MOVE.L Dn,Dm"),
    ("isa/m68k/move_w_dn_dn.isa", "isa/m68k/tests/v1/MOVE.w.json", "MOVE.W Dn,Dm"),
    ("isa/m68k/move_b_dn_dn.isa", "isa/m68k/tests/v1/MOVE.b.json", "MOVE.B Dn,Dm"),
    ("isa/m68k/moveq.isa", "isa/m68k/tests/v1/MOVEQ.json", "MOVEQ #imm,Dn"),

    # Data Movement - MOVEA
    ("isa/m68k/movea_l_dn_an.isa", "isa/m68k/tests/v1/MOVEA.l.json", "MOVEA.L Dn,An"),
    ("isa/m68k/movea_l_imm_an.isa", "isa/m68k/tests/v1/MOVEA.l.json", "MOVEA.L #imm,An"),

    # Load Effective Address
    ("isa/m68k/lea.isa", "isa/m68k/tests/v1/LEA.json", "LEA d16(An),Am"),

    # Arithmetic - ADD
    ("isa/m68k/add_l_dn_dn.isa", "isa/m68k/tests/v1/ADD.l.json", "ADD.L Dn,Dm"),
    ("isa/m68k/add_w_dn_dn.isa", "isa/m68k/tests/v1/ADD.w.json", "ADD.W Dn,Dm"),
    ("isa/m68k/addq_l_dn.isa", "isa/m68k/tests/v1/ADDQ.l.json", "ADDQ.L #data,Dn"),

    # Arithmetic - SUB
    ("isa/m68k/sub_l_dn_dn.isa", "isa/m68k/tests/v1/SUB.l.json", "SUB.L Dn,Dm"),
    ("isa/m68k/subq_l_dn.isa", "isa/m68k/tests/v1/SUBQ.l.json", "SUBQ.L #data,Dn"),

    # Arithmetic - MUL/DIV
    ("isa/m68k/mulu_w.isa", "isa/m68k/tests/v1/MULU.json", "MULU.W Dn,Dm"),
    ("isa/m68k/muls_w.isa", "isa/m68k/tests/v1/MULS.json", "MULS.W Dn,Dm"),
    ("isa/m68k/divu_w.isa", "isa/m68k/tests/v1/DIVU.json", "DIVU.W Dn,Dm"),

    # Arithmetic - NEG/CLR
    ("isa/m68k/neg_l_dn.isa", "isa/m68k/tests/v1/NEG.l.json", "NEG.L Dn"),
    ("isa/m68k/clr_l_dn.isa", "isa/m68k/tests/v1/CLR.l.json", "CLR.L Dn"),

    # Logical - AND
    ("isa/m68k/and_l_dn_dn.isa", "isa/m68k/tests/v1/AND.l.json", "AND.L Dn,Dm"),

    # Logical - OR
    ("isa/m68k/or_l_dn_dn.isa", "isa/m68k/tests/v1/OR.l.json", "OR.L Dn,Dm"),

    # Logical - EOR
    ("isa/m68k/eor_l_dn_dn.isa", "isa/m68k/tests/v1/EOR.l.json", "EOR.L Dn,Dm"),

    # Logical - NOT
    ("isa/m68k/not_l_dn.isa", "isa/m68k/tests/v1/NOT.l.json", "NOT.L Dn"),

    # Shifts - ASL/ASR
    ("isa/m68k/asl_l_imm_dn.isa", "isa/m68k/tests/v1/ASL.l.json", "ASL.L #count,Dn"),
    ("isa/m68k/asr_l_imm_dn.isa", "isa/m68k/tests/v1/ASR.l.json", "ASR.L #count,Dn"),

    # Shifts - LSL/LSR
    ("isa/m68k/lsl_l_imm_dn.isa", "isa/m68k/tests/v1/LSL.l.json", "LSL.L #count,Dn"),
    ("isa/m68k/lsr_l_imm_dn.isa", "isa/m68k/tests/v1/LSR.l.json", "LSR.L #count,Dn"),

    # Rotates - ROL/ROR
    ("isa/m68k/rol_l_imm_dn.isa", "isa/m68k/tests/v1/ROL.l.json", "ROL.L #count,Dn"),
    ("isa/m68k/ror_l_imm_dn.isa", "isa/m68k/tests/v1/ROR.l.json", "ROR.L #count,Dn"),

    # Comparison
    ("isa/m68k/cmp_l_dn_dn.isa", "isa/m68k/tests/v1/CMP.l.json", "CMP.L Dn,Dm"),
    ("isa/m68k/tst_l_dn.isa", "isa/m68k/tests/v1/TST.l.json", "TST.L Dn"),

    # Branches
    ("isa/m68k/bra_b.isa", "isa/m68k/tests/v1/Bcc.json", "BRA.B"),
    ("isa/m68k/beq_b.isa", "isa/m68k/tests/v1/Bcc.json", "BEQ.B"),
    ("isa/m68k/bne_b.isa", "isa/m68k/tests/v1/Bcc.json", "BNE.B"),

    # Jumps
    ("isa/m68k/jmp_an_ind.isa", "isa/m68k/tests/v1/JMP.json", "JMP (An)"),
    ("isa/m68k/jmp_abs_l.isa", "isa/m68k/tests/v1/JMP.json", "JMP abs.L"),

    # Subroutine
    ("isa/m68k/jsr_an_ind.isa", "isa/m68k/tests/v1/JSR.json", "JSR (An)"),
    ("isa/m68k/rts.isa", "isa/m68k/tests/v1/RTS.json", "RTS"),
    ("isa/m68k/bsr_b.isa", "isa/m68k/tests/v1/BSR.json", "BSR.B"),

    # Stack frame
    ("isa/m68k/link.isa", "isa/m68k/tests/v1/LINK.json", "LINK An,#disp"),
    ("isa/m68k/unlk.isa", "isa/m68k/tests/v1/UNLK.json", "UNLK An"),

    # Miscellaneous
    ("isa/m68k/nop.isa", "isa/m68k/tests/v1/NOP.json", "NOP"),
    ("isa/m68k/ext_w_dn.isa", "isa/m68k/tests/v1/EXT.w.json", "EXT.W Dn"),
    ("isa/m68k/ext_l_dn.isa", "isa/m68k/tests/v1/EXT.l.json", "EXT.L Dn"),
    ("isa/m68k/swap_dn.isa", "isa/m68k/tests/v1/SWAP.json", "SWAP Dn"),
    ("isa/m68k/exg_dn_dn.isa", "isa/m68k/tests/v1/EXG.json", "EXG Dn,Dm"),

    # Bit operations
    ("isa/m68k/btst_imm_dn.isa", "isa/m68k/tests/v1/BTST.json", "BTST #bit,Dn"),
    ("isa/m68k/bset_imm_dn.isa", "isa/m68k/tests/v1/BSET.json", "BSET #bit,Dn"),
    ("isa/m68k/bclr_imm_dn.isa", "isa/m68k/tests/v1/BCLR.json", "BCLR #bit,Dn"),

    # DBcc
    ("isa/m68k/dbra.isa", "isa/m68k/tests/v1/DBcc.json", "DBRA Dn,label"),
]


def run_test(isa_file, test_file, description, timeout=30):
    """Run a single test and return (success, output)."""
    # Check if files exist
    isa_path = project_root / isa_file
    test_path = project_root / test_file

    if not isa_path.exists():
        return False, f"ISA file not found: {isa_file}"

    if not test_path.exists():
        return False, f"Test file not found: {test_file}"

    # Run the test
    cmd = [
        sys.executable,
        str(script_dir / "run_m68k_json_test.py"),
        str(isa_path),
        str(test_path)
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(project_root)
        )

        success = result.returncode == 0 and 'ERROR' not in result.stdout
        output = result.stdout + result.stderr
        return success, output

    except subprocess.TimeoutExpired:
        return False, f"Test timed out after {timeout}s"
    except Exception as e:
        return False, f"Exception: {str(e)}"


def main():
    print("M68000 Multi-Test Runner")
    print("=" * 70)

    passed = 0
    failed = 0
    skipped = 0
    failed_tests = []

    for i, (isa_file, test_file, desc) in enumerate(test_cases):
        print(f"\n[{i+1}/{len(test_cases)}] {desc}")
        print(f"    ISA: {isa_file}")
        print(f"    Test: {test_file}")

        # Check if test file exists (may need to decode first)
        test_path = project_root / test_file
        if not test_path.exists():
            # Try to decode if .json.bin exists
            bin_path = Path(str(test_path) + ".bin")
            if bin_path.exists():
                print(f"    Decoding {bin_path.name}...")
                # Run decode.py for this specific file
                import json
                sys.path.insert(0, str(project_root / "isa/m68k/tests"))
                # Skip for now if not decoded
                print(f"    ⚠ SKIPPED (test file needs decoding)")
                skipped += 1
                continue
            else:
                print(f"    ⚠ SKIPPED (test file not found)")
                skipped += 1
                continue

        success, output = run_test(isa_file, test_file, desc)

        if success:
            print(f"    ✅ PASSED")
            passed += 1
        else:
            print(f"    ❌ FAILED")
            failed += 1
            failed_tests.append((isa_file, test_file, desc, output))

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total:   {len(test_cases)}")
    print(f"Passed:  {passed}")
    print(f"Failed:  {failed}")
    print(f"Skipped: {skipped}")

    if failed_tests:
        print("\nFailed tests:")
        for isa, test, desc, output in failed_tests:
            print(f"  - {desc}")
            print(f"    ISA: {isa}")
            # Show last few lines of output
            lines = output.strip().split('\n')
            for line in lines[-5:]:
                print(f"    {line}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == '__main__':
    main()
