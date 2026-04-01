#!/usr/bin/env python3
"""
Run comprehensive 8086 test suite from SingleStepTests repository.
Tests are from: https://github.com/SingleStepTests/8086/
"""

import json
import gzip
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

@dataclass
class RegisterState:
    """8086 CPU register state"""
    ax: int = 0
    bx: int = 0
    cx: int = 0
    dx: int = 0
    cs: int = 0
    ss: int = 0
    ds: int = 0
    es: int = 0
    sp: int = 0
    bp: int = 0
    si: int = 0
    di: int = 0
    ip: int = 0
    flags: int = 0

    @classmethod
    def from_dict(cls, d: Dict[str, int]) -> 'RegisterState':
        """Create RegisterState from dictionary"""
        return cls(**{k: v for k, v in d.items() if k in cls.__annotations__})

    def to_dict(self) -> Dict[str, int]:
        """Convert to dictionary"""
        return {
            'ax': self.ax, 'bx': self.bx, 'cx': self.cx, 'dx': self.dx,
            'cs': self.cs, 'ss': self.ss, 'ds': self.ds, 'es': self.es,
            'sp': self.sp, 'bp': self.bp, 'si': self.si, 'di': self.di,
            'ip': self.ip, 'flags': self.flags
        }

    def get_flag(self, flag_name: str) -> int:
        """Extract individual flag from flags register"""
        flag_bits = {
            'CF': 0,   # Carry
            'PF': 2,   # Parity
            'AF': 4,   # Auxiliary carry
            'ZF': 6,   # Zero
            'SF': 7,   # Sign
            'TF': 8,   # Trap
            'IF': 9,   # Interrupt enable
            'DF': 10,  # Direction
            'OF': 11   # Overflow
        }
        bit = flag_bits.get(flag_name.upper())
        if bit is None:
            return 0
        return (self.flags >> bit) & 1

@dataclass
class TestCase:
    """Single 8086 instruction test case"""
    name: str
    instruction_bytes: List[int]
    initial_regs: RegisterState
    initial_ram: List[Tuple[int, int]]  # [(address, value), ...]
    initial_queue: List[int]
    final_regs: RegisterState
    final_ram: List[Tuple[int, int]]
    final_queue: List[int]
    cycles: List  # Bus cycle information (not used for now)

    @classmethod
    def from_dict(cls, d: Dict) -> 'TestCase':
        """Parse test case from JSON dictionary"""
        initial_regs = RegisterState.from_dict(d['initial']['regs'])

        # Final regs may only have changed registers
        final_regs_dict = initial_regs.to_dict()
        final_regs_dict.update(d['final']['regs'])
        final_regs = RegisterState.from_dict(final_regs_dict)

        return cls(
            name=d['name'],
            instruction_bytes=d['bytes'],
            initial_regs=initial_regs,
            initial_ram=[(addr, val) for addr, val in d['initial']['ram']],
            initial_queue=d['initial'].get('queue', []),
            final_regs=final_regs,
            final_ram=[(addr, val) for addr, val in d['final']['ram']],
            final_queue=d['final'].get('queue', []),
            cycles=d.get('cycles', [])
        )


class TestRunner:
    """Run 8086 comprehensive tests"""

    def __init__(self, test_dir: Path, verilog_dir: Path):
        self.test_dir = test_dir
        self.verilog_dir = verilog_dir
        self.sim_binary = verilog_dir / "sim_8086_comprehensive"
        self.work_dir = verilog_dir / "test_work"
        self.work_dir.mkdir(exist_ok=True)

    def load_test_file(self, filename: Path) -> List[TestCase]:
        """Load and parse a gzipped JSON test file"""
        with gzip.open(filename, 'rt') as f:
            tests_json = json.load(f)

        return [TestCase.from_dict(t) for t in tests_json]

    def build_simulator(self) -> bool:
        """Compile the comprehensive testbench"""
        print("Building simulator...")
        cmd = [
            "iverilog",
            "-o", str(self.sim_binary),
            "-g2012",
            str(self.verilog_dir / "8086_test.v"),
            str(self.verilog_dir / "cpu_8086_comprehensive_tb.sv")
        ]

        try:
            result = subprocess.run(cmd, cwd=self.verilog_dir,
                                  capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                print(f"Build failed:\n{result.stderr}")
                return False
            print("Simulator built successfully")
            return True
        except Exception as e:
            print(f"Build error: {e}")
            return False

    def write_init_file(self, test: TestCase, init_path: Path):
        """Write initial state file for testbench"""
        with open(init_path, 'w') as f:
            # Register state (hex values)
            r = test.initial_regs
            f.write(f"{r.ax:04x} {r.bx:04x} {r.cx:04x} {r.dx:04x}\n")
            f.write(f"{r.cs:04x} {r.ss:04x} {r.ds:04x} {r.es:04x}\n")
            f.write(f"{r.sp:04x} {r.bp:04x} {r.si:04x} {r.di:04x}\n")
            f.write(f"{r.ip:04x} {r.flags:04x}\n")

            # Instruction bytes
            f.write(f"{len(test.instruction_bytes)}\n")
            f.write(" ".join(f"{b:02x}" for b in test.instruction_bytes) + "\n")

            # Memory initializations
            f.write(f"{len(test.initial_ram)}\n")
            for addr, val in test.initial_ram:
                f.write(f"{addr:08x} {val:02x}\n")

    def read_result_file(self, result_path: Path) -> Optional[RegisterState]:
        """Read final state from result file"""
        try:
            with open(result_path, 'r') as f:
                lines = f.readlines()

            if len(lines) < 6:
                return None

            # Parse register values
            ax, bx, cx, dx = [int(x, 16) for x in lines[0].split()]
            cs, ss, ds, es = [int(x, 16) for x in lines[1].split()]
            sp, bp, si, di = [int(x, 16) for x in lines[2].split()]
            ip, flags = [int(x, 16) for x in lines[3].split()]

            return RegisterState(
                ax=ax, bx=bx, cx=cx, dx=dx,
                cs=cs, ss=ss, ds=ds, es=es,
                sp=sp, bp=bp, si=si, di=di,
                ip=ip, flags=flags
            )
        except Exception as e:
            print(f"Error reading result file: {e}")
            return None

    def run_test(self, test: TestCase, test_index: int = 0) -> Tuple[bool, str]:
        """
        Run a single test case.
        Returns (passed, error_message)
        """
        # Write init file
        init_file = self.work_dir / f"test_{test_index}_init.txt"
        result_file = self.work_dir / f"test_{test_index}_result.txt"

        self.write_init_file(test, init_file)

        # Run simulation
        cmd = [
            "vvp",
            str(self.sim_binary),
            f"+init_file={init_file}",
            f"+result_file={result_file}"
        ]

        try:
            result = subprocess.run(cmd, cwd=self.verilog_dir,
                                  capture_output=True, text=True, timeout=10)

            if result.returncode != 0:
                return False, f"Simulation failed (exit code {result.returncode})"

            # Read results
            final_regs = self.read_result_file(result_file)
            if final_regs is None:
                return False, "Could not read result file"

            # Compare results (only compare registers we can actually test)
            # Our DUT doesn't have DX, CS, SS, DS, ES, BP, SI, DI
            errors = []

            if final_regs.ax != test.final_regs.ax:
                errors.append(f"AX: got {final_regs.ax:04x}, expected {test.final_regs.ax:04x}")
            if final_regs.bx != test.final_regs.bx:
                errors.append(f"BX: got {final_regs.bx:04x}, expected {test.final_regs.bx:04x}")
            if final_regs.cx != test.final_regs.cx:
                errors.append(f"CX: got {final_regs.cx:04x}, expected {test.final_regs.cx:04x}")
            if final_regs.sp != test.final_regs.sp:
                errors.append(f"SP: got {final_regs.sp:04x}, expected {test.final_regs.sp:04x}")
            if final_regs.ip != test.final_regs.ip:
                errors.append(f"IP: got {final_regs.ip:04x}, expected {test.final_regs.ip:04x}")

            # Compare flags (mask to implemented flags)
            final_flags_masked = final_regs.flags & 0x08D5  # CF PF AF ZF SF OF
            expected_flags_masked = test.final_regs.flags & 0x08D5
            if final_flags_masked != expected_flags_masked:
                errors.append(f"FLAGS: got {final_regs.flags:04x}, expected {test.final_regs.flags:04x}")

            if errors:
                return False, "; ".join(errors)

            return True, ""

        except subprocess.TimeoutExpired:
            return False, "Simulation timeout"
        except Exception as e:
            return False, f"Exception: {e}"

    def run_test_file(self, filename: Path, max_tests: Optional[int] = None) -> Dict:
        """Run all tests in a file"""
        tests = self.load_test_file(filename)

        if max_tests:
            tests = tests[:max_tests]

        results = {
            'total': len(tests),
            'passed': 0,
            'failed': 0,
            'errors': []
        }

        print(f"\nRunning {len(tests)} tests from {filename.name}...")

        for i, test in enumerate(tests):
            if i % 100 == 0 and i > 0:
                print(f"  Progress: {i}/{len(tests)} tests...")

            passed, error = self.run_test(test, i)
            if passed:
                results['passed'] += 1
            else:
                results['failed'] += 1
                results['errors'].append({
                    'test_index': i,
                    'name': test.name,
                    'error': error
                })

        return results


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='Run comprehensive 8086 CPU tests')
    parser.add_argument('--max-tests', type=int, help='Maximum tests per file')
    parser.add_argument('--max-files', type=int, help='Maximum test files to run')
    parser.add_argument('--file', type=str, help='Specific test file to run (e.g., 00.json.gz)')
    args = parser.parse_args()

    project_root = Path(__file__).parent
    test_dir = project_root / "isa" / "8086" / "tests" / "v1"
    verilog_dir = project_root / "examples" / "verilog" / "8086_test"

    if not test_dir.exists():
        print(f"Error: Test directory not found: {test_dir}")
        return 1

    runner = TestRunner(test_dir, verilog_dir)

    # Build simulator
    if not runner.build_simulator():
        print("Failed to build simulator")
        return 1

    # Get test files to run
    if args.file:
        test_files = [test_dir / args.file]
    else:
        test_files = sorted(test_dir.glob("*.json.gz"))

    if args.max_files:
        test_files = test_files[:args.max_files]

    if not test_files:
        print(f"Error: No test files found in {test_dir}")
        return 1

    print(f"\n{'='*70}")
    print(f"8086 Comprehensive Test Suite")
    print(f"{'='*70}")
    print(f"Test files: {len(test_files)}")
    if args.max_tests:
        print(f"Max tests per file: {args.max_tests}")

    # Run all test files
    all_results = {
        'total': 0,
        'passed': 0,
        'failed': 0,
        'by_file': {}
    }

    for test_file in test_files:
        results = runner.run_test_file(test_file, max_tests=args.max_tests)

        all_results['total'] += results['total']
        all_results['passed'] += results['passed']
        all_results['failed'] += results['failed']
        all_results['by_file'][test_file.name] = results

        print(f"  {test_file.name}: {results['passed']}/{results['total']} passed")

        # Show first few errors
        if results['errors'] and len(results['errors']) <= 5:
            for err in results['errors'][:5]:
                print(f"    ✗ Test {err['test_index']}: {err['name']}")
                print(f"      {err['error']}")

    # Summary
    print(f"\n{'='*70}")
    print(f"SUMMARY")
    print(f"{'='*70}")
    print(f"Total tests:  {all_results['total']}")
    print(f"Passed:       {all_results['passed']} ({100*all_results['passed']//all_results['total'] if all_results['total'] > 0 else 0}%)")
    print(f"Failed:       {all_results['failed']}")
    print(f"{'='*70}")

    return 0 if all_results['failed'] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
