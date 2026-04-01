#!/usr/bin/env python3
"""Generate testbench for HardCaml-generated Verilog.

HardCaml uses internal numbered names for memories and registers.
This script extracts those names from the generated Verilog and
creates a testbench that references them correctly.
"""
import re
import sys

def extract_signals(verilog_file):
    """Extract PC register, register file, and memory names from Verilog."""
    with open(verilog_file) as f:
        content = f.read()

    # PC register: assign pc = _NNN;
    m = re.search(r'assign pc = (\w+);', content)
    pc_reg = m.group(1) if m else None

    # Register file: reg [31:0] _NNN[0:31];
    m = re.search(r'reg \[31:0\] (\w+)\[0:31\]', content)
    rf_mem = m.group(1) if m else None

    # Unified memory: reg [31:0] _NNN[0:8191];
    m = re.search(r'reg \[31:0\] (\w+)\[0:8191\]', content)
    umem = m.group(1) if m else None

    return pc_reg, rf_mem, umem

def generate_tb(pc_reg, rf_mem, umem):
    return f"""`timescale 1ns/1ps
module simple_tb;
    reg clock, clear;

    riscv32i_complete dut (
        .clock(clock),
        .clear(clear)
    );

    reg [31:0] pass_addr, fail_addr;
    integer i, j;
    always #5 clock = ~clock;

    initial begin
        clock = 0; clear = 1;
        if (!$value$plusargs("pass_addr=%h", pass_addr)) pass_addr = 32'hFFFFFFFF;
        if (!$value$plusargs("fail_addr=%h", fail_addr)) fail_addr = 32'hFFFFFFFE;
        $readmemh("umem.hex", dut.{umem});
        // Initialize register file to 0 (HardCaml multiport_memory has no reset)
        for (j = 0; j < 32; j = j + 1)
            dut.{rf_mem}[j] = 32'h0;
        repeat(3) @(posedge clock);
        clear = 0;
        for (i = 0; i < 10000; i = i + 1) begin
            @(posedge clock);
            if (dut.{pc_reg} == pass_addr) begin $display("TEST PASSED"); $finish; end
            if (dut.{pc_reg} == fail_addr) begin $display("TEST FAILED at pc=%h testnum=%d", dut.{pc_reg}, dut.{rf_mem}[28]); $finish; end
        end
        $display("TIMEOUT");
        $finish;
    end
endmodule
"""

if __name__ == '__main__':
    verilog_file = sys.argv[1] if len(sys.argv) > 1 else 'riscv32i_complete.v'
    output_file = sys.argv[2] if len(sys.argv) > 2 else 'simple_tb.sv'

    pc_reg, rf_mem, umem = extract_signals(verilog_file)
    if not all([pc_reg, rf_mem, umem]):
        print(f"ERROR: Could not extract signals from {verilog_file}")
        print(f"  PC={pc_reg}, RF={rf_mem}, UMEM={umem}")
        sys.exit(1)

    print(f"Extracted signals: PC={pc_reg}, RF={rf_mem}, UMEM={umem}")
    tb = generate_tb(pc_reg, rf_mem, umem)
    with open(output_file, 'w') as f:
        f.write(tb)
    print(f"Generated {output_file}")
