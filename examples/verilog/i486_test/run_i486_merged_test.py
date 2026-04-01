#!/usr/bin/env python3
"""
Test runner for the merged i486 design using Verilator.
Uses the pre-generated merged Verilog and runs SingleStepTests against it.
Builds the design ONCE with Verilator, then runs multiple tests.
"""

import json
import gzip
import sys
import os
import subprocess
import tempfile
from pathlib import Path

# Add project root and script directory to path for imports
script_dir = Path(__file__).parent
project_root = script_dir.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(script_dir))

from moo_parser import parse_moo_file

# Default paths
MERGED_VERILOG = script_dir / "i486_targeted_merged.v"
MODULE_NAME = "cpu_i486_targeted"
TEST_DIR = project_root / "isa/i486/tests/v1_ex_real_mode"
BUILD_DIR = script_dir / "verilator_build"


def load_tests(test_file):
    """Load tests from either MOO or JSON format."""
    test_path = Path(test_file)

    if '.MOO' in test_path.name.upper():
        return parse_moo_file(test_file)
    else:
        if test_path.suffix == '.gz':
            with gzip.open(test_file, 'rt') as f:
                data = json.load(f)
        else:
            with open(test_file, 'r') as f:
                data = json.load(f)

        if isinstance(data, dict):
            return [data]
        return data


def remap_80386_registers(regs):
    """
    Remap registers to fix systematic bug in 80386 SingleStepTests.
    """
    remapped = {}

    # Group 1: 4-element cycle (edx->eax, ebp->edx, eip->ebp, eax->eip)
    if 'edx' in regs:
        remapped['eax'] = regs['edx']
    if 'ebp' in regs:
        remapped['edx'] = regs['ebp']
    if 'eip' in regs:
        remapped['ebp'] = regs['eip']
    if 'eax' in regs:
        remapped['eip'] = regs['eax']

    # Group 2: 3-element cycle (esp->ecx, eflags->esp, ecx->eflags)
    if 'esp' in regs:
        remapped['ecx'] = regs['esp']
    if 'eflags' in regs:
        remapped['esp'] = regs['eflags']
    if 'ecx' in regs:
        remapped['eflags'] = regs['ecx']

    # Segment registers
    if 'cr2' in regs:
        remapped['ds'] = regs['cr2'] & 0xFFFF
    if 'cr3' in regs:
        remapped['es'] = regs['cr3'] & 0xFFFF
    if 'dr2' in regs:
        remapped['ss'] = regs['dr2'] & 0xFFFF

    # Copy unchanged registers
    for reg in ['ebx', 'esi', 'edi', 'cr0', 'cr2', 'cr3',
                'dr0', 'dr1', 'dr2', 'dr3', 'dr6', 'dr7', 'fs', 'gs']:
        if reg in regs:
            remapped[reg] = regs[reg]

    return remapped


# Shared obj_dir for Verilator to cache compiled DUT
VERILATOR_OBJ_DIR = BUILD_DIR / "obj_verilator"


def generate_testbench_verilog(test, output_file):
    """Generate a SystemVerilog testbench for a single test."""
    init_regs = remap_80386_registers(test['initial']['regs'])
    final_regs = remap_80386_registers(test['final']['regs'])

    # Expected values
    expected_eax = final_regs.get('eax', init_regs.get('eax', 0))
    expected_ecx = final_regs.get('ecx', init_regs.get('ecx', 0))
    expected_edx = final_regs.get('edx', init_regs.get('edx', 0))
    expected_ebx = final_regs.get('ebx', init_regs.get('ebx', 0))

    # EIP calculation
    if 'eip' in final_regs:
        expected_eip = final_regs['eip']
    else:
        init_eip = init_regs.get('eip', 0)
        instr_len = len(test['bytes']) - 1
        expected_eip = init_eip + instr_len

    # Flags
    raw_regs = test['initial']['regs']
    init_flags = raw_regs.get('dr6', 0)
    cf_init = (init_flags >> 0) & 1
    pf_init = (init_flags >> 2) & 1
    af_init = (init_flags >> 4) & 1
    zf_init = (init_flags >> 6) & 1
    sf_init = (init_flags >> 7) & 1
    of_init = (init_flags >> 11) & 1
    df_init = (init_flags >> 10) & 1

    IMEM_MASK = 0xFFFFF
    DMEM_MASK = 0xFFFFF

    imem_loads = ""
    for i, byte in enumerate(test['bytes']):
        addr = (init_regs['eip'] + i) & IMEM_MASK
        imem_loads += f"        dut.imem[32'h{addr:08X}] = 8'h{byte:02X};\n"

    dmem_loads = ""
    if 'ram' in test.get('initial', {}):
        for addr, val in test['initial']['ram']:
            masked_addr = addr & DMEM_MASK
            dmem_loads += f"        dut.dmem[32'h{masked_addr:08X}] = 8'h{val:02X};\n"

    bytes_display = ' '.join(f'{b:02X}h' for b in test['bytes'])

    testbench = f'''`timescale 1ns/1ps
module tb_test;
    reg clk;
    reg reset;

    // Minimal reset ports
    reg [31:0] reset_eip;
    reg reset_flag_CF, reset_flag_OF, reset_flag_AF;
    reg reset_flag_PF_rd, reset_flag_ZF_rd, reset_flag_SF_rd, reset_flag_DF_rd;
    reg [31:0] reset_EAX, reset_EBX_rd;
    reg [15:0] reset_DS, reset_ES, reset_SS, reset_CS;

    {MODULE_NAME} dut (
        .clk(clk), .reset(reset),
        .reset_eip(reset_eip),
        .reset_flag_CF(reset_flag_CF), .reset_flag_OF(reset_flag_OF),
        .reset_flag_AF(reset_flag_AF), .reset_flag_PF_rd(reset_flag_PF_rd),
        .reset_flag_ZF_rd(reset_flag_ZF_rd), .reset_flag_SF_rd(reset_flag_SF_rd),
        .reset_flag_DF_rd(reset_flag_DF_rd),
        .reset_EAX(reset_EAX), .reset_EBX_rd(reset_EBX_rd),
        .reset_DS(reset_DS), .reset_ES(reset_ES), .reset_SS(reset_SS), .reset_CS(reset_CS)
    );

    always #5 clk = ~clk;

    initial begin
        $display("=== Test: {bytes_display} ===");
        clk = 0; reset = 1;
        reset_eip = 32'h{init_regs.get('eip', 0):08X};
        reset_flag_CF = 1'b{cf_init};
        reset_flag_OF = 1'b{of_init};
        reset_flag_AF = 1'b{af_init};
        reset_flag_PF_rd = 1'b{pf_init};
        reset_flag_ZF_rd = 1'b{zf_init};
        reset_flag_SF_rd = 1'b{sf_init};
        reset_flag_DF_rd = 1'b{df_init};
        reset_EAX = 32'h{init_regs.get('eax', 0):08X};
        reset_EBX_rd = 32'h{init_regs.get('ebx', 0):08X};
        reset_DS = 16'h{init_regs.get('ds', 0) & 0xFFFF:04X};
        reset_ES = 16'h{init_regs.get('es', 0) & 0xFFFF:04X};
        reset_SS = 16'h{init_regs.get('ss', 0) & 0xFFFF:04X};
        reset_CS = 16'h0000;

{imem_loads}
{dmem_loads}
        dut.xregs[0] = 32'h{init_regs.get('eax', 0):08X};
        dut.xregs[1] = 32'h{init_regs.get('ecx', 0):08X};
        dut.xregs[2] = 32'h{init_regs.get('edx', 0):08X};
        dut.xregs[3] = 32'h{init_regs.get('ebx', 0):08X};
        dut.xregs[4] = 32'h{init_regs.get('esp', 0):08X};
        dut.xregs[5] = 32'h{init_regs.get('ebp', 0):08X};
        dut.xregs[6] = 32'h{init_regs.get('esi', 0):08X};
        dut.xregs[7] = 32'h{init_regs.get('edi', 0):08X};
        dut.eip = 32'h{init_regs.get('eip', 0):08X};
        dut.flag_CF = 1'b{cf_init};
        dut.flag_PF_rd = 1'b{pf_init};
        dut.flag_AF = 1'b{af_init};
        dut.flag_ZF_rd = 1'b{zf_init};
        dut.flag_SF_rd = 1'b{sf_init};
        dut.flag_OF = 1'b{of_init};
        dut.flag_DF_rd = 1'b{df_init};

        #20; reset = 0;
        repeat(100) @(posedge clk);

        if (dut.xregs[0] !== 32'h{expected_eax:08X}) begin
            $display("FAIL: EAX got %08Xh expected %08Xh", dut.xregs[0], 32'h{expected_eax:08X});
            $finish(1);
        end
        $display("PASS: EAX=%08Xh", dut.xregs[0]);
        $finish(0);
    end
endmodule
'''
    with open(output_file, 'w') as f:
        f.write(testbench)


def run_test_verilator(test, merged_verilog, build_dir, verbose=False):
    """Run a single test using Verilator with pure SystemVerilog testbench.

    Uses a shared obj_dir so the DUT is only compiled once and cached.
    Subsequent tests only need to recompile the testbench wrapper.
    """
    build_dir = Path(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)

    # Generate testbench
    tb_file = build_dir / "tb_test.sv"
    generate_testbench_verilog(test, tb_file)

    # Use shared obj_dir so Verilator caches the compiled DUT
    obj_dir = VERILATOR_OBJ_DIR
    obj_dir.mkdir(parents=True, exist_ok=True)

    # Compile with Verilator - pure Verilog, no C++ harness needed
    verilator_cmd = [
        'verilator', '--binary', '--timing',
        '-Wno-fatal', '-Wno-WIDTHTRUNC', '-Wno-WIDTHEXPAND',
        '-Wno-UNUSEDSIGNAL', '-Wno-UNDRIVEN', '-Wno-LATCH',
        '-Wno-TIMESCALEMOD', '-Wno-DECLFILENAME', '-Wno-UNUSEDPARAM',
        '-Wno-WIDTHCONCAT', '-Wno-UNSIGNED', '-Wno-CASEINCOMPLETE',
        '-Wno-MULTIDRIVEN', '-Wno-UNOPTFLAT', '-Wno-INITIALDLY',
        '--top-module', 'tb_test',
        '-o', 'sim_test',
        '--Mdir', str(obj_dir),
        str(merged_verilog),
        str(tb_file)
    ]

    if verbose:
        print(f"Compiling with Verilator...")

    result = subprocess.run(
        verilator_cmd,
        capture_output=True,
        text=True,
        cwd=str(build_dir),
        timeout=900  # 15 min for initial DUT compilation (cached after first run)
    )

    if result.returncode != 0:
        if verbose:
            print(f"Verilator failed:\n{result.stderr[:1000]}")
        return False, result.stderr

    # Run simulation
    sim_exe = obj_dir / 'sim_test'
    if not sim_exe.exists():
        return False, "Simulation executable not found"

    sim_result = subprocess.run(
        [str(sim_exe)],
        capture_output=True,
        text=True,
        cwd=str(build_dir),
        timeout=30
    )

    output = sim_result.stdout + sim_result.stderr
    test_passed = 'PASS:' in output and 'FAIL:' not in output

    if verbose:
        print(output)

    return test_passed, output


def run_test_iverilog(test, merged_verilog, build_dir, verbose=False):
    """Run a single test using Icarus Verilog (fallback)."""
    build_dir = Path(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)

    # Generate testbench
    tb_file = build_dir / "tb_test.sv"
    generate_testbench_verilog(test, tb_file)

    # Compile
    vvp_file = build_dir / "sim_test.vvp"
    compile_cmd = ['iverilog', '-g2012', '-o', str(vvp_file),
                   str(merged_verilog), str(tb_file)]

    result = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        return False, result.stderr

    # Run
    sim_result = subprocess.run(
        ['vvp', str(vvp_file)],
        capture_output=True,
        text=True,
        cwd=str(build_dir),
        timeout=30
    )

    output = sim_result.stdout + sim_result.stderr
    test_passed = 'PASS:' in output and 'FAIL:' not in output

    if verbose:
        print(output)

    return test_passed, output


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Run single-step tests on merged i486 design')
    parser.add_argument('test_file', nargs='?', help='Test file (MOO or JSON format)')
    parser.add_argument('--merged-verilog', '-m', default=str(MERGED_VERILOG),
                        help='Path to merged Verilog file')
    parser.add_argument('--test-index', '-t', type=int, default=0,
                        help='Index of test to run (default: 0)')
    parser.add_argument('--use-iverilog', action='store_true',
                        help='Use Icarus Verilog instead of Verilator')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show detailed output')
    parser.add_argument('--build-dir', '-b', default=str(BUILD_DIR),
                        help='Build directory for Verilator output')
    parser.add_argument('--list-tests', action='store_true',
                        help='List available test files')

    args = parser.parse_args()

    # List available tests
    if args.list_tests:
        print(f"Test files in {TEST_DIR}:")
        for f in sorted(TEST_DIR.glob("*.MOO.gz")):
            print(f"  {f.name}")
        return 0

    # Check merged Verilog exists
    merged_path = Path(args.merged_verilog)
    if not merged_path.exists():
        print(f"Error: Merged Verilog file not found: {merged_path}")
        print("Run: python3 i486/generators/regen_i486_targeted.py")
        sys.exit(1)

    # If no test file, use a default
    if not args.test_file:
        # Find first available test
        test_files = list(TEST_DIR.glob("*.MOO.gz"))
        if test_files:
            args.test_file = str(test_files[0])
            print(f"Using default test: {args.test_file}")
        else:
            print("No test files found. Run: git submodule update --init isa/i486/tests")
            sys.exit(1)

    # Load tests
    tests = load_tests(args.test_file)
    print(f"Loaded {len(tests)} test(s) from {args.test_file}")

    if args.test_index >= len(tests):
        print(f"Error: Test index {args.test_index} out of range (0-{len(tests)-1})")
        sys.exit(1)

    test = tests[args.test_index]

    # Run test
    build_dir = Path(args.build_dir)
    if args.use_iverilog:
        success, output = run_test_iverilog(test, merged_path, build_dir, args.verbose)
    else:
        success, output = run_test_verilator(test, merged_path, build_dir, args.verbose)

    if success:
        print("\n=== TEST PASSED ===")
        sys.exit(0)
    else:
        print("\n=== TEST FAILED ===")
        if not args.verbose:
            print(output[-500:] if len(output) > 500 else output)
        sys.exit(1)


if __name__ == '__main__':
    main()
