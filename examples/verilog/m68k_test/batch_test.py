#!/usr/bin/env python3
"""Run batch of SingleStepTests and report pass/fail status."""
import json
import subprocess
import sys
from pathlib import Path

def main():
    verilog_file = Path(__file__).parent.parent / "m68k_full.v"
    test_dir = Path(__file__).parent.parent.parent.parent / "isa/m68k/tests/v1"
    
    # Test files to check - expanded to cover new addressing modes
    test_files = [
        # Arithmetic
        "ADD.l.json",
        "SUB.l.json",
        "ADDA.l.json",
        "SUBA.l.json",
        "ADDX.l.json",
        "SUBX.l.json",
        # Logic
        "AND.l.json",
        "OR.l.json",
        "EOR.l.json",
        # Compare
        "CMP.l.json",
        "CMPA.l.json",
        # Move
        "MOVE.l.json",
        "MOVEA.l.json",
        # Unary
        "NEG.l.json",
        "NOT.l.json",
        "CLR.l.json",
        "TST.l.json",
        # Quick
        "ADDQ.json",
        "SUBQ.json",
        # Shifts/Rotates
        "ASL.l.json",
        "ASR.l.json",
        "LSL.l.json",
        "LSR.l.json",
        "ROL.l.json",
        "ROR.l.json",
        "ROXL.l.json",
        "ROXR.l.json",
        # Multiply/Divide
        "MULU.json",
        "MULS.json",
        "DIVU.json",
        "DIVS.json",
        # Bit operations
        "BTST.json",
        "BSET.json",
        "BCLR.json",
        "BCHG.json",
        # Branches
        "Bcc.json",
        "DBcc.json",
        "BSR.json",
        # Return
        "RTR.json",
        # Set conditional
        "Scc.json",
        # BCD
        "ABCD.json",
        "SBCD.json",
        "NBCD.json",
        # Exchange
        "EXG.json",
        # Extend
        "EXT.l.json",
        # Swap
        "SWAP.json",
        # TAS
        "TAS.json",
    ]
    
    passed = 0
    failed = 0
    skipped = 0
    
    for test_file in test_files:
        test_path = test_dir / test_file
        if not test_path.exists():
            print(f"SKIP {test_file}: file not found")
            skipped += 1
            continue
            
        tests = json.load(open(test_path))
        num_tests = min(20, len(tests))  # Test first 20
        
        print(f"\n=== {test_file} ({num_tests} tests) ===")
        
        for i in range(num_tests):
            test = tests[i]
            # Skip exception tests
            init_pc = test['initial']['pc']
            final_pc = test['final']['pc']
            if abs(final_pc - init_pc) > 1000:
                skipped += 1
                continue
                
            result = subprocess.run(
                ["python3", "run_merged_m68k_test.py", str(verilog_file), str(test_path), str(i)],
                capture_output=True, text=True,
                cwd=Path(__file__).parent
            )
            
            if "TEST PASSED" in result.stdout:
                print(f"✓ {test['name']}")
                passed += 1
            else:
                print(f"✗ {test['name']}")
                failed += 1
    
    print(f"\n{'='*50}")
    print(f"RESULTS: {passed} passed, {failed} failed, {skipped} skipped")
    
if __name__ == "__main__":
    main()
