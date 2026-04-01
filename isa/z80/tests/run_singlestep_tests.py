#!/usr/bin/env python3
"""
Run SingleStepTests against the generated Z80 Verilog.

This script:
1. Reads JSON test files from the SingleStepTests/z80 repository
2. Generates Verilator test harnesses for each instruction
3. Runs simulations and compares results with expected values
"""

import json
import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Map from opcode to instruction name (for instructions we've implemented)
IMPLEMENTED_OPCODES = {
    0x00: 'nop',
    0x01: 'ld_bc_nn',
    0x03: 'inc_bc',
    0x04: 'inc_b',
    0x05: 'dec_b',
    0x06: 'ld_b_imm',
    0x07: 'rlca',
    0x09: 'add_hl_bc',
    0x0B: 'dec_bc',
    0x0C: 'inc_c',
    0x0D: 'dec_c',
    0x0E: 'ld_c_imm',
    0x0F: 'rrca',
    0x10: 'djnz_e',
    0x11: 'ld_de_nn',
    0x13: 'inc_de',
    0x16: 'ld_d_imm',
    0x17: 'rla',
    0x18: 'jr_e',
    0x19: 'add_hl_de',
    0x1B: 'dec_de',
    0x1E: 'ld_e_imm',
    0x1F: 'rra',
    0x20: 'jr_nz_e',
    0x21: 'ld_hl_nn',
    0x23: 'inc_hl',
    0x26: 'ld_h_imm',
    0x28: 'jr_z_e',
    0x29: 'add_hl_hl',
    0x2B: 'dec_hl',
    0x2E: 'ld_l_imm',
    0x2F: 'cpl',
    0x30: 'jr_nc_e',
    0x31: 'ld_sp_nn',
    0x32: 'ld_nn_a',
    0x33: 'inc_sp',
    0x37: 'scf',
    0x38: 'jr_c_e',
    0x39: 'add_hl_sp',
    0x3A: 'ld_a_nn',
    0x3B: 'dec_sp',
    0x3C: 'inc_a',
    0x3D: 'dec_a',
    0x3E: 'ld_a_imm',
    0x3F: 'ccf',
    0x47: 'ld_b_a',
    0x4F: 'ld_c_a',
    0x57: 'ld_d_a',
    0x5F: 'ld_e_a',
    0x67: 'ld_h_a',
    0x6F: 'ld_l_a',
    0x76: 'halt',
    0x77: 'ld_hl_a',
    0x78: 'ld_a_b',
    0x79: 'ld_a_c',
    0x7A: 'ld_a_d',
    0x7B: 'ld_a_e',
    0x7C: 'ld_a_h',
    0x7D: 'ld_a_l',
    0x7E: 'ld_a_hl',
    0x80: 'add_a_b',
    0x81: 'add_a_c',
    0x86: 'add_a_hl',
    0x88: 'adc_a_b',
    0x90: 'sub_a_b',
    0x98: 'sbc_a_b',
    0xA0: 'and_a_b',
    0xA8: 'xor_a_b',
    0xAF: 'xor_a_a',
    0xB0: 'or_a_b',
    0xB8: 'cp_a_b',
    0xC0: 'ret_nz',
    0xC1: 'pop_bc',
    0xC2: 'jp_nz_nn',
    0xC3: 'jp_nn',
    0xC4: 'call_nz_nn',
    0xC5: 'push_bc',
    0xC6: 'add_a_imm',
    0xC8: 'ret_z',
    0xC9: 'ret',
    0xCA: 'jp_z_nn',
    0xCC: 'call_z_nn',
    0xCD: 'call_nn',
    0xCE: 'adc_a_imm',
    0xD1: 'pop_de',
    0xD2: 'jp_nc_nn',
    0xD5: 'push_de',
    0xD6: 'sub_a_imm',
    0xDA: 'jp_c_nn',
    0xDE: 'sbc_a_imm',
    0xE1: 'pop_hl',
    0xE5: 'push_hl',
    0xE6: 'and_a_imm',
    0xE9: 'jp_hl',
    0xEB: 'ex_de_hl',
    0xEE: 'xor_a_imm',
    0xF1: 'pop_af',
    0xF5: 'push_af',
    0xF6: 'or_a_imm',
    0xFE: 'cp_a_imm',
}


@dataclass
class TestResult:
    """Result of a single test."""
    name: str
    passed: bool
    expected: Dict
    actual: Dict
    error: Optional[str] = None


def generate_testbench_verilog(test: Dict, output_dir: Path) -> Path:
    """Generate a Verilog testbench for a single test."""

    initial = test['initial']
    final = test['final']
    name = test['name'].replace(' ', '_')

    # Extract initial RAM
    ram_init = {addr: val for addr, val in initial.get('ram', [])}

    # Generate mainmem.hex file for $readmemh initialization
    # Format: @address value (hex format)
    hex_lines = []
    for addr, val in sorted(ram_init.items()):
        hex_lines.append(f"@{addr:04x} {val:02x}")
    hex_content = '\n'.join(hex_lines) if hex_lines else ''
    (output_dir / 'mainmem.hex').write_text(hex_content)

    # Generate memory init statements (backup for direct assignment)
    mem_init_lines = []
    for addr, val in sorted(ram_init.items()):
        mem_init_lines.append(f"        cpu.mainmem[{addr}] = 8'h{val:02x};")
    mem_init = '\n'.join(mem_init_lines) if mem_init_lines else "        // No memory init"

    # Flag decoding from F register
    f_reg = initial['f']
    flag_c = f_reg & 1
    flag_n = (f_reg >> 1) & 1
    flag_pv = (f_reg >> 2) & 1
    flag_h = (f_reg >> 4) & 1
    flag_z = (f_reg >> 6) & 1
    flag_s = (f_reg >> 7) & 1

    # Expected flag values
    f_final = final['f']
    exp_flag_c = f_final & 1
    exp_flag_z = (f_final >> 6) & 1

    tb_code = f'''`timescale 1ns/1ps

module tb_test_{name};
    reg clk;
    reg reset;

    // Initial values
    reg [7:0] init_A = 8'h{initial['a']:02x};
    reg [7:0] init_B = 8'h{initial['b']:02x};
    reg [7:0] init_C = 8'h{initial['c']:02x};
    reg [7:0] init_D = 8'h{initial['d']:02x};
    reg [7:0] init_E = 8'h{initial['e']:02x};
    reg [7:0] init_H = 8'h{initial['h']:02x};
    reg [7:0] init_L = 8'h{initial['l']:02x};
    reg [15:0] init_PC = 16'h{initial['pc']:04x};
    reg [15:0] init_SP = 16'h{initial['sp']:04x};
    reg init_flag_C = 1'b{flag_c};
    reg init_flag_Z = 1'b{flag_z};
    reg init_flag_S = 1'b{flag_s};
    reg init_flag_H = 1'b{flag_h};
    reg init_flag_N = 1'b{flag_n};
    reg init_flag_PV = 1'b{flag_pv};

    // Expected values
    reg [7:0] exp_A = 8'h{final['a']:02x};
    reg [7:0] exp_B = 8'h{final['b']:02x};
    reg [7:0] exp_C = 8'h{final['c']:02x};
    reg [7:0] exp_D = 8'h{final['d']:02x};
    reg [7:0] exp_E = 8'h{final['e']:02x};
    reg [7:0] exp_H = 8'h{final['h']:02x};
    reg [7:0] exp_L = 8'h{final['l']:02x};
    reg [15:0] exp_PC = 16'h{final['pc']:04x};
    reg [15:0] exp_SP = 16'h{final['sp']:04x};
    reg exp_flag_C = 1'b{exp_flag_c};
    reg exp_flag_Z = 1'b{exp_flag_z};

    // Instantiate CPU
    processor cpu(
        .clk(clk),
        .reset(reset),
        .reset_A(init_A),
        .reset_A_prime(8'h00),
        .reset_B(init_B),
        .reset_B_prime(8'h00),
        .reset_C(init_C),
        .reset_C_prime(8'h00),
        .reset_D(init_D),
        .reset_D_prime(8'h00),
        .reset_E(init_E),
        .reset_E_prime(8'h00),
        .reset_H(init_H),
        .reset_H_prime(8'h00),
        .reset_L(init_L),
        .reset_L_prime(8'h00),
        .reset_I(8'h00),
        .reset_R(8'h00),
        .reset_IXH(8'h00),
        .reset_IXL(8'h00),
        .reset_IYH(8'h00),
        .reset_IYL(8'h00),
        .reset_IM(2'b00),
        .reset_IFF2(1'b0),
        .reset_pc_rd(init_PC),
        .reset_sp_rd(init_SP),
        .reset_flag_C(init_flag_C),
        .reset_flag_C_prime(1'b0),
        .reset_flag_Z(init_flag_Z),
        .reset_flag_Z_prime(1'b0),
        .reset_flag_S(init_flag_S),
        .reset_flag_S_prime(1'b0),
        .reset_flag_H(init_flag_H),
        .reset_flag_H_prime(1'b0),
        .reset_flag_N(init_flag_N),
        .reset_flag_N_prime(1'b0),
        .reset_flag_PV(init_flag_PV),
        .reset_flag_PV_prime(1'b0),
        .reset_halted_rd(1'b0),
        .reset_int_ff1_rd(1'b0),
        .reset_int_ff2(1'b0)
    );

    // Clock generation
    initial clk = 0;
    always #5 clk = ~clk;

    // Test sequence
    integer errors;
    initial begin
        errors = 0;

        // Initialize memory
{mem_init}

        // Reset
        reset = 1;
        @(posedge clk);
        @(posedge clk);
        reset = 0;

        // Run exactly one instruction cycle
        @(posedge clk);  // Execute instruction

        // Check results
        if (cpu.A !== exp_A) begin
            $display("FAIL: A expected %02x got %02x", exp_A, cpu.A);
            errors = errors + 1;
        end
        if (cpu.B !== exp_B) begin
            $display("FAIL: B expected %02x got %02x", exp_B, cpu.B);
            errors = errors + 1;
        end
        if (cpu.C !== exp_C) begin
            $display("FAIL: C expected %02x got %02x", exp_C, cpu.C);
            errors = errors + 1;
        end
        if (cpu.D !== exp_D) begin
            $display("FAIL: D expected %02x got %02x", exp_D, cpu.D);
            errors = errors + 1;
        end
        if (cpu.E !== exp_E) begin
            $display("FAIL: E expected %02x got %02x", exp_E, cpu.E);
            errors = errors + 1;
        end
        if (cpu.H !== exp_H) begin
            $display("FAIL: H expected %02x got %02x", exp_H, cpu.H);
            errors = errors + 1;
        end
        if (cpu.L !== exp_L) begin
            $display("FAIL: L expected %02x got %02x", exp_L, cpu.L);
            errors = errors + 1;
        end
        if (cpu.pc_rd !== exp_PC) begin
            $display("FAIL: PC expected %04x got %04x", exp_PC, cpu.pc_rd);
            errors = errors + 1;
        end
        if (cpu.sp_rd !== exp_SP) begin
            $display("FAIL: SP expected %04x got %04x", exp_SP, cpu.sp_rd);
            errors = errors + 1;
        end

        if (errors == 0) begin
            $display("PASS: {name}");
        end else begin
            $display("FAIL: {name} (%0d errors)", errors);
        end

        $finish;
    end

endmodule
'''

    tb_path = output_dir / f"tb_test_{name}.v"
    tb_path.write_text(tb_code)
    return tb_path


def run_verilator_lint(verilog_path: Path) -> Tuple[bool, str]:
    """Run Verilator lint check on generated Verilog."""
    try:
        result = subprocess.run(
            ['verilator', '--lint-only', '-Wall', '-Wno-fatal',
             '-Wno-WIDTHTRUNC', '-Wno-WIDTHEXPAND', '-Wno-UNUSEDSIGNAL',
             '-Wno-UNDRIVEN', '-Wno-UNUSEDPARAM', '-Wno-DECLFILENAME',
             '-Wno-SELRANGE', '-Wno-CMPCONST', '-Wno-UNSIGNED',
             str(verilog_path)],
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode == 0:
            return True, "Lint passed"
        else:
            return False, result.stderr
    except Exception as e:
        return False, str(e)


def run_verilator_sim(verilog_path: Path, tb_path: Path, output_dir: Path) -> Tuple[bool, str]:
    """Compile and run simulation with Verilator 5 --timing."""
    try:
        obj_dir = output_dir / 'obj_dir'

        # Compile with Verilator using --timing and --binary
        result = subprocess.run(
            ['verilator', '--binary', '--timing',
             '-Wno-fatal', '-Wno-WIDTHTRUNC', '-Wno-WIDTHEXPAND',
             '-Wno-UNUSEDSIGNAL', '-Wno-UNDRIVEN', '-Wno-LATCH',
             '-Wno-TIMESCALEMOD', '-Wno-DECLFILENAME', '-Wno-UNUSEDPARAM',
             '-Wno-WIDTHCONCAT', '-Wno-UNSIGNED',
             '--top-module', tb_path.stem,
             '-o', 'sim_test',
             '--Mdir', str(obj_dir),
             str(verilog_path), str(tb_path)],
            cwd=str(output_dir),
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode != 0:
            return False, f"Compile failed:\n{result.stderr}"

        # Run simulation from output_dir so it finds mainmem.hex
        sim_result = subprocess.run(
            [str(obj_dir / 'sim_test')],
            cwd=str(output_dir),
            capture_output=True,
            text=True,
            timeout=30
        )

        output = sim_result.stdout + sim_result.stderr
        passed = 'PASS:' in output
        return passed, output

    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except Exception as e:
        return False, str(e)


def run_icarus_sim(verilog_path: Path, tb_path: Path, output_dir: Path) -> Tuple[bool, str]:
    """Compile and run simulation with Icarus Verilog (fallback)."""
    try:
        # Compile with iverilog
        sim_exe = output_dir / 'sim_test.vvp'

        result = subprocess.run(
            ['iverilog', '-g2012', '-o', str(sim_exe),
             str(verilog_path), str(tb_path)],
            cwd=str(output_dir),
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode != 0:
            return False, f"Compile failed:\n{result.stderr}"

        # Run simulation with vvp from output_dir so it finds mainmem.hex
        sim_result = subprocess.run(
            ['vvp', str(sim_exe)],
            cwd=str(output_dir),
            capture_output=True,
            text=True,
            timeout=30
        )

        output = sim_result.stdout + sim_result.stderr
        passed = 'PASS:' in output
        return passed, output

    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except Exception as e:
        return False, str(e)


def run_single_test(test: Dict, verilog_path: Path, output_dir: Path) -> TestResult:
    """Run a single test case."""
    name = test['name']

    try:
        # Generate testbench
        tb_path = generate_testbench_verilog(test, output_dir)

        # Run simulation with Verilator (faster) or fall back to Icarus
        passed, output = run_verilator_sim(verilog_path, tb_path, output_dir)

        return TestResult(
            name=name,
            passed=passed,
            expected=test['final'],
            actual={'output': output},
            error=None if passed else output
        )

    except Exception as e:
        return TestResult(
            name=name,
            passed=False,
            expected=test['final'],
            actual={},
            error=str(e)
        )


def run_tests_for_opcode(opcode: int, tests_dir: Path, verilog_path: Path,
                         max_tests: int = 5, verbose: bool = False) -> List[TestResult]:
    """Run tests for a single opcode."""
    results = []

    test_file = tests_dir / f"{opcode:02x}.json"
    if not test_file.exists():
        return results

    with open(test_file) as f:
        tests = json.load(f)

    # Create temp directory
    with tempfile.TemporaryDirectory(prefix='z80_test_') as tmpdir:
        output_dir = Path(tmpdir)

        for i, test in enumerate(tests[:max_tests]):
            if verbose:
                print(f"    Test {i+1}/{min(len(tests), max_tests)}: {test['name']}", end=' ')

            result = run_single_test(test, verilog_path, output_dir)
            results.append(result)

            if verbose:
                print("PASS" if result.passed else "FAIL")

    return results


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Run Z80 SingleStep tests')
    parser.add_argument('--tests-dir', type=Path,
                        default=project_root / 'isa' / 'z80' / 'singlestep-tests' / 'v1',
                        help='Path to SingleStepTests v1 directory')
    parser.add_argument('--verilog', type=Path,
                        default=project_root / 'examples' / 'verilog' / 'z80' / 'z80.v',
                        help='Path to generated Z80 Verilog')
    parser.add_argument('--opcode', type=str, default=None,
                        help='Test specific opcode (hex, e.g., "00" for NOP)')
    parser.add_argument('--max-tests', type=int, default=3,
                        help='Max tests per opcode file')
    parser.add_argument('--list-implemented', action='store_true',
                        help='List implemented opcodes and exit')
    parser.add_argument('--lint-only', action='store_true',
                        help='Only run Verilator lint check')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output')

    args = parser.parse_args()

    if args.list_implemented:
        print("Implemented opcodes:")
        for opcode, name in sorted(IMPLEMENTED_OPCODES.items()):
            print(f"  0x{opcode:02X}: {name}")
        print(f"\nTotal: {len(IMPLEMENTED_OPCODES)} instructions")
        return

    # Check Verilog exists
    if not args.verilog.exists():
        print(f"Error: Verilog file not found: {args.verilog}")
        print("Generate it with: python3 isa/z80/generators/regen_z80.py")
        sys.exit(1)

    # Lint check
    print(f"Checking Verilog: {args.verilog}")
    lint_ok, lint_msg = run_verilator_lint(args.verilog)
    if not lint_ok:
        print(f"Verilator lint failed:\n{lint_msg}")
        sys.exit(1)
    print("  Verilator lint: PASS")

    if args.lint_only:
        return

    # Determine which opcodes to test
    if args.opcode:
        opcodes = [int(args.opcode, 16)]
    else:
        opcodes = sorted(IMPLEMENTED_OPCODES.keys())

    total_passed = 0
    total_failed = 0
    total_skipped = 0

    for opcode in opcodes:
        instr_name = IMPLEMENTED_OPCODES.get(opcode, 'unknown')
        test_file = args.tests_dir / f"{opcode:02x}.json"

        if not test_file.exists():
            if args.verbose:
                print(f"\nSkipping opcode 0x{opcode:02X} ({instr_name}): no test file")
            total_skipped += 1
            continue

        print(f"\nTesting opcode 0x{opcode:02X} ({instr_name})...")

        results = run_tests_for_opcode(
            opcode, args.tests_dir, args.verilog,
            max_tests=args.max_tests, verbose=args.verbose
        )

        passed = sum(1 for r in results if r.passed)
        failed = len(results) - passed
        total_passed += passed
        total_failed += failed

        print(f"  Results: {passed}/{len(results)} passed")

        # Show first failed test details
        for r in results:
            if not r.passed and args.verbose:
                print(f"    FAIL: {r.name}")
                if r.error:
                    # Truncate long error messages
                    error_lines = r.error.split('\n')[:10]
                    for line in error_lines:
                        print(f"      {line}")

    print(f"\n{'='*60}")
    print(f"Summary:")
    print(f"  Passed: {total_passed}")
    print(f"  Failed: {total_failed}")
    print(f"  Skipped: {total_skipped} (no test files)")

    sys.exit(0 if total_failed == 0 else 1)


if __name__ == '__main__':
    main()
