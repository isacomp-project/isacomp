#!/usr/bin/env python3
"""
Test runner for merged M68000 design against SingleStepTests.
"""

import json
import sys
import os
import subprocess
from pathlib import Path

def extract_ccr_flags(sr):
    """Extract CCR flags from status register."""
    return {
        'C': (sr >> 0) & 1,
        'V': (sr >> 1) & 1,
        'Z': (sr >> 2) & 1,
        'N': (sr >> 3) & 1,
        'X': (sr >> 4) & 1,
    }

def generate_testbench(test, verilog_file, output_file):
    """Generate a testbench for the merged M68000 design."""

    init_state = test['initial']
    final_state = test['final']

    init_sr = init_state.get('sr', 0)
    init_ccr = extract_ccr_flags(init_sr)

    final_sr = final_state.get('sr', 0)
    final_ccr = extract_ccr_flags(final_sr)

    # M68000 prefetch handling:
    # The test's PC points ahead of the instruction to execute.
    # prefetch[0] contains the instruction that should be executed.
    # We need to find where that instruction is in RAM (usually PC-4 or PC-2).
    prefetch = init_state.get('prefetch', [])
    documented_pc = init_state['pc']

    # Find the actual instruction location in RAM
    # M68000 prefetch means instruction is at PC-4 (2 words ahead)
    actual_instr_pc = documented_pc - 4

    # Build memory initialization from RAM
    mem_init = ""
    if 'ram' in init_state:
        ram_bytes = {addr: val for addr, val in init_state['ram']}

        # Load into both imem and dmem (16-bit words at word-aligned addresses)
        # Use 23-bit word addressing to support M68K's full 24-bit byte address space
        processed_addrs = set()
        for addr, val in init_state['ram']:
            # Round down to even address for word alignment
            even_addr = addr & ~1
            if even_addr not in processed_addrs:
                processed_addrs.add(even_addr)
                hi_byte = ram_bytes.get(even_addr, 0)
                lo_byte = ram_bytes.get(even_addr + 1, 0)
                word = (hi_byte << 8) | lo_byte
                word_addr = even_addr >> 1  # Convert byte address to word address
                # Load into both imem and dmem
                mem_init += f"        dut.imem[23'h{word_addr:06X}] = 16'h{word:04X};\n"
                mem_init += f"        dut.dmem[23'h{word_addr:06X}] = 16'h{word:04X};\n"

    # Also ensure prefetch[0] instruction is at the actual_instr_pc location
    if prefetch:
        instr_word = prefetch[0]
        instr_word_addr = actual_instr_pc >> 1
        mem_init += f"        // Prefetch instruction at actual PC\n"
        mem_init += f"        dut.imem[23'h{instr_word_addr:06X}] = 16'h{instr_word:04X};\n"

    # Data register initialization
    dreg_init = ""
    for i in range(8):
        val = init_state.get(f'd{i}', 0)
        dreg_init += f"        dut.dregs[{i}] = 32'h{val:08X};\n"

    # Address register initialization
    areg_init = ""
    for i in range(7):
        val = init_state.get(f'a{i}', 0)
        areg_init += f"        dut.aregs[{i}] = 32'h{val:08X};\n"
    # A7 = SSP (supervisor stack pointer)
    ssp = init_state.get('ssp', 0)
    areg_init += f"        dut.aregs[7] = 32'h{ssp:08X};  // A7/SSP\n"

    # Expected values - adjust for prefetch offset
    # Since we start at actual_instr_pc (4 bytes before documented PC),
    # the expected final PC is also 4 bytes earlier
    expected_pc = final_state.get('pc', 0) - 4

    # Build register checks
    dreg_checks = ""
    for i in range(8):
        expected = final_state.get(f'd{i}', init_state.get(f'd{i}', 0))
        dreg_checks += f'''
        if (dut.dregs[{i}] !== 32'h{expected:08X}) begin
            $display("  D{i}: got %08X, expected %08X - FAIL", dut.dregs[{i}], 32'h{expected:08X});
            errors = errors + 1;
        end else begin
            $display("  D{i}: %08X - OK", dut.dregs[{i}]);
        end'''

    # Escape test name for Verilog string
    test_name = test['name'].replace('"', '\\"').replace('\\', '\\\\')

    testbench = f'''`timescale 1ns/1ps
module m68k_merged_tb;
    reg clk;
    reg reset;
    reg [31:0] reset_pc_rd;
    reg reset_flag_X_rd;
    reg reset_flag_N;
    reg reset_flag_Z;
    reg reset_flag_V_rd;
    reg reset_flag_C;

    cpu_m68k_test dut (
        .clk(clk),
        .reset(reset),
        .reset_pc_rd(reset_pc_rd),
        .reset_flag_X_rd(reset_flag_X_rd),
        .reset_flag_N(reset_flag_N),
        .reset_flag_Z(reset_flag_Z),
        .reset_flag_V_rd(reset_flag_V_rd),
        .reset_flag_C(reset_flag_C)
    );

    initial clk = 0;
    always #5 clk = ~clk;

    initial begin
        integer errors;
        integer cycle;
        reg [31:0] prev_pc;

        errors = 0;

        $display("========================================");
        $display("Test: {test_name}");
        $display("========================================");

        #1;

        // Initialize state - use actual instruction PC (accounting for prefetch)
        reset_pc_rd = 32'h{actual_instr_pc:08X};
        reset_flag_X_rd = 1'b{init_ccr['X']};
        reset_flag_N = 1'b{init_ccr['N']};
        reset_flag_Z = 1'b{init_ccr['Z']};
        reset_flag_V_rd = 1'b{init_ccr['V']};
        reset_flag_C = 1'b{init_ccr['C']};

        // Load memory
{mem_init}
        // Initialize data registers
{dreg_init}
        // Initialize address registers
{areg_init}

        $display("Initial PC: %08X", reset_pc_rd);

        // Apply reset
        reset = 1;
        @(posedge clk);
        @(posedge clk);
        #1;

        reset = 0;
        prev_pc = dut.pc_rd;

        // Execute (wait for PC to change or timeout)
        for (cycle = 0; cycle < 20; cycle = cycle + 1) begin
            @(posedge clk);
            #1;
            if (dut.pc_rd !== prev_pc) begin
                $display("Instruction completed in %0d cycles", cycle + 1);
                cycle = 100;
            end
        end

        $display("");
        $display("Final PC: %08X (expected %08X)", dut.pc_rd, 32'h{expected_pc:08X});

        if (dut.pc_rd !== 32'h{expected_pc:08X}) begin
            $display("  PC MISMATCH!");
            errors = errors + 1;
        end

        $display("");
        $display("Data Registers:");
{dreg_checks}

        $display("");
        if (errors == 0) begin
            $display("=== TEST PASSED ===");
            $finish(0);
        end else begin
            $display("=== TEST FAILED (%0d errors) ===", errors);
            $finish(1);
        end
    end

    initial begin
        #5000;
        $display("TIMEOUT!");
        $finish(1);
    end
endmodule
'''

    with open(output_file, 'w') as f:
        f.write(testbench)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 run_merged_test.py <test_file.json> [test_index]")
        print("Example: python3 run_merged_test.py isa/m68k/tests/v1/MOVE.q.json 0")
        sys.exit(1)

    test_file = sys.argv[1]
    test_index = int(sys.argv[2]) if len(sys.argv) >= 3 else 0

    # Load tests
    with open(test_file, 'r') as f:
        tests = json.load(f)

    if isinstance(tests, dict):
        tests = [tests]

    test = tests[test_index]
    print(f"Running test: {test['name']} (#{test_index})")

    verilog_file = "examples/verilog/m68k_test/m68k_test.v"
    tb_file = "examples/verilog/m68k_test/m68k_merged_tb.sv"
    sim_file = "examples/verilog/m68k_test/sim_merged"

    # Generate testbench
    generate_testbench(test, verilog_file, tb_file)

    # Compile
    result = subprocess.run([
        'iverilog', '-g2012', '-o', sim_file,
        verilog_file, tb_file
    ], capture_output=True, text=True)

    if result.returncode != 0:
        print("Compilation failed:")
        print(result.stderr)
        sys.exit(1)

    # Run simulation
    result = subprocess.run([sim_file], capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print(result.stderr)

    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
