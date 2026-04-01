#!/usr/bin/env python3
"""
Alpha ISA Test Runner

Runs the Alpha test suite against the generated Verilator model.
Each test stores its result at address 0xF00:
  - 1 = all tests passed
  - test_num << 1 = test failed at test_num
"""

import subprocess
import sys
import shutil
import re
from pathlib import Path

# Configuration
TESTS_DIR = Path(__file__).parent
BIN_DIR = TESTS_DIR / "bin"
VERILOG_DIR = TESTS_DIR.parent.parent.parent / "examples" / "verilog" / "alpha64"

# Processor configurations
PROCESSORS = {
    "integer": {
        "simulator": VERILOG_DIR / "obj_dir" / "Valpha64_integer_tb",
        "rtl": VERILOG_DIR / "alpha64_integer.v",
        "tb": VERILOG_DIR / "alpha64_integer_tb.sv",
        "top_module": "alpha64_integer_tb",
    },
    "complete": {
        "simulator": VERILOG_DIR / "obj_dir" / "Valpha64_complete_tb",
        "rtl": VERILOG_DIR / "alpha64_complete.v",
        "tb": VERILOG_DIR / "alpha64_integer_tb.sv",  # Reuse the testbench
        "top_module": "alpha64_integer_tb",  # Will be patched for complete
    },
}

# gem5 pseudo-instructions (not real Alpha instructions)
GEM5_PSEUDO_OPS = {
    "initparam", "m5a_getid", "m5a_old", "m5readfile", "m5panic",
    "quiesce", "quiesceTime", "rpcc", "rpns", "rduniq", "wruniq", "rc", "rs",
}

# FP instructions (only available in complete processor)
FP_INSTRUCTIONS = {
    "adds", "subs", "muls", "divs", "addt", "subt", "mult", "divt",
    "sqrts", "sqrtt", "cmpteq", "cmptlt", "cmptle",
    "cvtts", "cvttq", "cvtqs", "cvtqt",
    "cpys", "cpysn", "cpyse",
    "lds", "ldt", "sts", "stt",
    "mf_fpcr", "mt_fpcr", "ftoit", "itoft",
}


def build_simulator(proc_type="integer", force=False):
    """Build the Verilator simulator if needed."""
    config = PROCESSORS[proc_type]
    simulator = config["simulator"]
    rtl_file = config["rtl"]
    tb_file = config["tb"]

    if simulator.exists() and not force:
        # Check if source files are newer
        if rtl_file.exists() and tb_file.exists():
            src_mtime = max(rtl_file.stat().st_mtime, tb_file.stat().st_mtime)
            sim_mtime = simulator.stat().st_mtime
            if sim_mtime > src_mtime:
                return True  # Simulator is up to date

    print(f"Building {proc_type} simulator...")

    if not rtl_file.exists():
        print(f"Error: RTL file not found: {rtl_file}")
        if proc_type == "integer":
            print("Generate it with: python3 core/generate_processor.py isa/alpha64/*.isa --merge -o examples/verilog/alpha64/alpha64_integer.v -m alpha64_integer")
        else:
            print("Generate it with: python3 isa/alpha64/generators/generate_alpha64_complete.py")
        return False

    if not tb_file.exists():
        print(f"Error: Testbench not found: {tb_file}")
        return False

    # For complete processor, create a proper testbench with FP support
    if proc_type == "complete":
        complete_tb = VERILOG_DIR / "alpha64_complete_tb_test.sv"
        # Create a custom testbench for the complete processor
        tb_content = """`timescale 1ns/1ps
// Testbench for alpha64_complete processor - loads test programs from hex files
module alpha64_complete_tb;
    reg clk, reset;
    wire [63:0] zero64 = 64'd0;

    alpha64_complete dut (
        .clk(clk),
        .reset(reset),
        .reset_fpcr(zero64),
        .reset_pc_rd(zero64)
    );

    reg [63:0] pass_addr, fail_addr;
    integer cycles;
    integer max_cycles;
    always #5 clk = ~clk;

    initial begin
        clk = 0; reset = 1;
        cycles = 0;
        // Get max cycles from plusargs, default 50000
        if (!$value$plusargs("cycles=%d", max_cycles)) max_cycles = 50000;
        // Get pass/fail addresses from test dump file
        if (!$value$plusargs("pass_addr=%h", pass_addr)) pass_addr = 64'hFFFFFFFFFFFFFFFF;
        if (!$value$plusargs("fail_addr=%h", fail_addr)) fail_addr = 64'hFFFFFFFFFFFFFFFE;

        // Load memory from hex files
        $readmemh("imem.hex", dut.imem);
        $readmemh("rf.hex", dut.rf);
        $readmemh("dmem.hex", dut.dmem);
        // Load FP register file
        $readmemh("frf.hex", dut.frf);

        repeat(3) @(posedge clk);
        reset = 0;

        forever begin
            @(posedge clk);
            cycles = cycles + 1;

            // Debug: show PC and instruction each cycle
            $display("cycle=%d pc=%h instr=%h ldt_en=%b frf_wr_en=%b f1=%h f2=%h f3=%h f5=%h f6=%h",
                cycles, dut.pc_rd, dut.instr, dut.ldt_enable, dut.frf_write_enable,
                dut.frf[1], dut.frf[2], dut.frf[3], dut.frf[5], dut.frf[6]);

            // Check for pass condition (PC reaches pass label)
            if (dut.pc_rd == pass_addr) begin
                $display("TEST PASSED");
                $finish;
            end

            // Check for fail condition (PC reaches fail label)
            if (dut.pc_rd == fail_addr) begin
                $display("TEST FAILED at pc=%h testnum=%d", dut.pc_rd, dut.rf[4]);
                $finish;
            end

            // Also check memory location 0xF00 for result (as per test_macros.h)
            // dmem is 64-bit, address 0xF00 is word 0x1E0 (0xF00/8)
            if (dut.dmem[64'h1E0][31:0] == 32'h00000001) begin
                $display("TEST PASSED (via result memory)");
                $finish;
            end
            if (dut.dmem[64'h1E0][31:0] != 32'h0 && dut.dmem[64'h1E0][0] == 1'b0) begin
                $display("TEST FAILED: result=%h testnum=%d", dut.dmem[64'h1E0], dut.dmem[64'h1E0] >> 1);
                $finish;
            end

            // Timeout
            if (cycles >= max_cycles) begin
                $display("TIMEOUT after %d cycles at pc=%h", cycles, dut.pc_rd);
                $finish;
            end
        end
    end
endmodule
"""
        with open(complete_tb, 'w') as f:
            f.write(tb_content)
        tb_file = complete_tb

    # Build with Verilator --binary mode (no C++ testbench needed)
    sim_name = f"Valpha64_{proc_type}_tb"
    top_module = f"alpha64_{proc_type}_tb" if proc_type == "complete" else config["top_module"]

    # FPU sources for complete processor
    vendor_dir = VERILOG_DIR.parent.parent / "vendor"
    fpu_wrapper = vendor_dir / "cvfpu_wrapper.sv"

    cmd = [
        "verilator",
        "--binary",
        "--timing",
        "-Wno-fatal",
        "-Wno-WIDTHEXPAND",
        "-Wno-WIDTHTRUNC",
        "-Wno-WIDTHCONCAT",
        "-Wno-INITIALDLY",
        "-Wno-UNUSEDSIGNAL",
        "-Wno-UNOPTFLAT",
        "-Wno-CASEINCOMPLETE",
        "-Wno-CASEX",
        "-Wno-LATCH",
        "-Wno-COMBDLY",
        "-Wno-MULTIDRIVEN",
        "-Wno-BLKANDNBLK",
        "-Wno-SELRANGE",
        "-Wno-UNSIGNED",
        "-Wno-ASCRANGE",
        "-Wno-TIMESCALEMOD",
        "--top-module", top_module,
        "-o", sim_name,
        str(rtl_file),
        str(tb_file),
    ]

    # Add FPU sources for complete processor
    if proc_type == "complete" and fpu_wrapper.exists():
        # Add include paths and source files for fpnew FPU
        cmd.insert(-2, f"+incdir+{vendor_dir}/common_cells/include")
        cmd.insert(-2, f"+incdir+{vendor_dir}/fpu_div_sqrt_mvp/hdl")
        cmd.insert(-2, f"+incdir+{vendor_dir}/cvfpu/src")
        # Add source files in dependency order
        fpu_sources = [
            # Common cells
            "common_cells/src/cf_math_pkg.sv",
            "common_cells/src/lzc.sv",
            "common_cells/src/rr_arb_tree.sv",
            # FPU div/sqrt MVP (PULP)
            "fpu_div_sqrt_mvp/hdl/defs_div_sqrt_mvp.sv",
            "fpu_div_sqrt_mvp/hdl/preprocess_mvp.sv",
            "fpu_div_sqrt_mvp/hdl/nrbd_nrsc_mvp.sv",
            "fpu_div_sqrt_mvp/hdl/control_mvp.sv",
            "fpu_div_sqrt_mvp/hdl/iteration_div_sqrt_mvp.sv",
            "fpu_div_sqrt_mvp/hdl/norm_div_sqrt_mvp.sv",
            "fpu_div_sqrt_mvp/hdl/div_sqrt_top_mvp.sv",
            "fpu_div_sqrt_mvp/hdl/div_sqrt_mvp_wrapper.sv",
            # T-Head E906 div/sqrt (used by fpnew_divsqrt_th_32.sv)
            "cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/clk/rtl/gated_clk_cell.v",
            "cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_ctrl.v",
            "cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_ff1.v",
            "cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_pack_single.v",
            "cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_prepare.v",
            "cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_round_single.v",
            "cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_special.v",
            "cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_srt_single.v",
            "cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_top.v",
            "cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fpu/rtl/pa_fpu_dp.v",
            "cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fpu/rtl/pa_fpu_frbus.v",
            "cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fpu/rtl/pa_fpu_src_type.v",
            # CVFPU core
            "cvfpu/src/fpnew_pkg.sv",
            "cvfpu/src/fpnew_classifier.sv",
            "cvfpu/src/fpnew_rounding.sv",
            "cvfpu/src/fpnew_fma.sv",
            "cvfpu/src/fpnew_fma_multi.sv",
            "cvfpu/src/fpnew_cast_multi.sv",
            "cvfpu/src/fpnew_noncomp.sv",
            "cvfpu/src/fpnew_divsqrt_multi.sv",
            "cvfpu/src/fpnew_opgroup_fmt_slice.sv",
            "cvfpu/src/fpnew_opgroup_multifmt_slice.sv",
            "cvfpu/src/fpnew_opgroup_block.sv",
            "cvfpu/src/fpnew_top.sv",
            # isacomp wrapper
            "cvfpu_wrapper.sv",
        ]
        for src in fpu_sources:
            src_path = vendor_dir / src
            if src_path.exists():
                cmd.insert(-2, str(src_path))

    try:
        result = subprocess.run(
            cmd,
            cwd=str(VERILOG_DIR),
            capture_output=True,
            text=True,
            timeout=600
        )
        if result.returncode != 0:
            print(f"Verilator compilation failed:")
            print(result.stderr)
            return False
        print(f"Simulator built successfully: {sim_name}")
        return True
    except subprocess.TimeoutExpired:
        print("Error: Verilator compilation timed out")
        return False
    except FileNotFoundError:
        print("Error: verilator not found. Please install Verilator 5+")
        return False


def find_tests(proc_type="integer"):
    """Find all test hex files, excluding tests for unimplemented instructions."""
    all_tests = sorted(BIN_DIR.glob("*.hex"))

    # Always exclude gem5 pseudo-ops
    excluded = GEM5_PSEUDO_OPS.copy()

    # Exclude FP instructions if using integer-only processor
    if proc_type == "integer":
        excluded.update(FP_INSTRUCTIONS)

    return [t for t in all_tests if t.stem not in excluded]


def extract_pass_fail_addrs(test_name):
    """Extract pass/fail addresses from the dump file."""
    dump_file = BIN_DIR / f"{test_name}.dump"
    pass_addr = None
    fail_addr = None

    if dump_file.exists():
        with open(dump_file, 'r') as f:
            for line in f:
                # Match lines like "00000000000000a8 <pass>:"
                match = re.match(r'^([0-9a-f]+)\s+<(pass|fail)>:', line)
                if match:
                    addr = int(match.group(1), 16)
                    label = match.group(2)
                    if label == 'pass':
                        pass_addr = addr
                    elif label == 'fail':
                        fail_addr = addr

    return pass_addr, fail_addr


def prepare_test_files(test_hex, proc_type="integer"):
    """Prepare imem.hex, rf.hex, dmem.hex files for the test."""
    # Copy test hex to imem.hex
    imem_hex = VERILOG_DIR / "imem.hex"
    shutil.copy(test_hex, imem_hex)

    # Create empty rf.hex (32 registers, all zeros)
    rf_hex = VERILOG_DIR / "rf.hex"
    with open(rf_hex, 'w') as f:
        for _ in range(32):
            f.write("0000000000000000\n")

    # Create empty dmem.hex (16K words, all zeros)
    dmem_hex = VERILOG_DIR / "dmem.hex"
    with open(dmem_hex, 'w') as f:
        for _ in range(16384):
            f.write("0000000000000000\n")

    # For complete processor, also create empty FP register file
    if proc_type == "complete":
        frf_hex = VERILOG_DIR / "frf.hex"
        with open(frf_hex, 'w') as f:
            for _ in range(32):
                f.write("0000000000000000\n")


def run_test(test_hex, proc_type="integer", max_cycles=500, verbose=False):
    """
    Run a single test and return (status, message).

    Returns:
        status: 'PASS', 'FAIL', 'TIMEOUT', or 'ERROR'
        message: Additional info (e.g., which test failed)
    """
    test_name = test_hex.stem
    config = PROCESSORS[proc_type]
    simulator = config["simulator"]

    # Extract pass/fail addresses from dump file
    pass_addr, fail_addr = extract_pass_fail_addrs(test_name)

    if pass_addr is None or fail_addr is None:
        return "ERROR", f"Could not extract pass/fail addresses from {test_name}.dump"

    # Prepare memory files
    prepare_test_files(test_hex, proc_type)

    # Build command with plusargs
    cmd = [
        str(simulator),
        f"+pass_addr={pass_addr:x}",
        f"+fail_addr={fail_addr:x}",
        f"+cycles={max_cycles}",
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(VERILOG_DIR),
            capture_output=True,
            text=True,
            timeout=30
        )

        output = result.stdout.strip()

        if verbose:
            print(f"    Output: {output}")

        if "PASS" in output:
            return "PASS", ""
        elif "FAIL" in output:
            return "FAIL", output
        elif "TIMEOUT" in output:
            return "TIMEOUT", output
        else:
            return "ERROR", f"Exit code {result.returncode}: {output}"

    except subprocess.TimeoutExpired:
        return "TIMEOUT", "Process killed after 30s"
    except Exception as e:
        return "ERROR", str(e)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Alpha ISA Test Runner")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--test", "-t", type=str, help="Run specific test")
    parser.add_argument("--cycles", "-c", type=int, default=500, help="Max cycles per test")
    parser.add_argument("--rebuild", "-r", action="store_true", help="Force rebuild simulator")
    parser.add_argument("--fp", action="store_true", help="Use complete processor with FP support")
    args = parser.parse_args()

    proc_type = "complete" if args.fp else "integer"

    print("=" * 60)
    print(f"Alpha ISA Test Suite ({proc_type} processor)")
    print("=" * 60)

    # Build simulator if needed
    config = PROCESSORS[proc_type]
    if args.rebuild and config["simulator"].exists():
        config["simulator"].unlink()

    if not build_simulator(proc_type, force=args.rebuild):
        sys.exit(1)

    # Find tests
    tests = find_tests(proc_type)
    if not tests:
        print(f"Error: No test files found in {BIN_DIR}")
        print("Run 'make' in the alpha-tests directory first")
        sys.exit(1)

    # Filter to specific test if requested
    if args.test:
        tests = [t for t in tests if t.stem == args.test]
        if not tests:
            print(f"Error: Test '{args.test}' not found")
            sys.exit(1)

    print(f"Running {len(tests)} test(s)...\n")

    # Run tests
    passed = 0
    failed = 0
    errors = 0

    for test in tests:
        test_name = test.stem
        status, message = run_test(test, proc_type, max_cycles=args.cycles, verbose=args.verbose)

        if status == "PASS":
            print(f"  {test_name}: \033[32mPASS\033[0m")
            passed += 1
        elif status == "FAIL":
            print(f"  {test_name}: \033[31mFAIL\033[0m - {message}")
            failed += 1
        elif status == "TIMEOUT":
            print(f"  {test_name}: \033[33mTIMEOUT\033[0m")
            errors += 1
        else:
            print(f"  {test_name}: \033[33mERROR\033[0m - {message}")
            errors += 1

    # Summary
    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed, {errors} errors")
    print("=" * 60)

    if failed > 0 or errors > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
