#!/usr/bin/env python3
"""Generate testbench for HardCaml-generated pipelined Verilog.

Extracts internal signal names (which change each regeneration) from the
generated Verilog and creates a testbench with pipeline-aware pass/fail
detection: checks the Execute-stage PC gated by Execute-stage validity.
"""
import re
import sys


def extract_signals(verilog_file):
    """Extract internal signal names from HardCaml-generated Verilog."""
    with open(verilog_file) as f:
        content = f.read()

    # Module name: module XXXX (
    m = re.search(r'^module\s+(\w+)\s*\(', content, re.MULTILINE)
    module_name = m.group(1) if m else 'riscv32i_pipelined'

    # PC register: assign pc = _NNN;
    m = re.search(r'assign\s+pc\s*=\s*(\w+)\s*;', content)
    pc_reg = m.group(1) if m else None

    # Register file: reg [31:0] _NNN[0:31];
    m = re.search(r'reg\s+\[31:0\]\s+(\w+)\[0:31\]', content)
    rf_mem = m.group(1) if m else None

    # Unified memory: reg [31:0] _NNN[0:8191];
    m = re.search(r'reg\s+\[31:0\]\s+(\w+)\[0:8191\]', content)
    umem = m.group(1) if m else None

    # Execute-stage PC: look for the most-downstream pipelined pc_rd output.
    # In 5-stage: pipe_execute_pipe_decode_pc_rd_pipe_pipe
    # In 4-stage: pipe_execute_pipe_decode_pc_rd_pipe_pipe
    # In 3-stage: pipe_executememory_pc_rd_pipe (or similar)
    # In 2-stage: pipe_executememorywriteback_pc_rd_pipe
    # Strategy: find all matches, prefer the one with "execute" in the stage
    # name and pick the longest (most pipelined) version.
    exec_pc_candidates = re.findall(r'output\s+\[31:0\]\s+(pipe_\w*pc_rd\w*)', content)
    exec_pc_port = None
    if exec_pc_candidates:
        # Prefer candidates containing "execute", then longest name
        execute_cands = [c for c in exec_pc_candidates if 'execute' in c]
        if execute_cands:
            exec_pc_port = max(execute_cands, key=len)
        else:
            exec_pc_port = max(exec_pc_candidates, key=len)

    # Execute-stage validity: same strategy.
    exec_valid_candidates = re.findall(r'output\s+(pipe_\w*valid_pipe)\b', content)
    exec_valid_port = None
    if exec_valid_candidates:
        execute_cands = [c for c in exec_valid_candidates if 'execute' in c]
        if execute_cands:
            exec_valid_port = max(execute_cands, key=len)
        else:
            exec_valid_port = max(exec_valid_candidates, key=len)

    return module_name, pc_reg, rf_mem, umem, exec_pc_port, exec_valid_port


def generate_tb(module_name, pc_reg, rf_mem, umem, exec_pc_port, exec_valid_port):
    # Build pass/fail check using Execute-stage PC gated by validity
    if exec_pc_port and exec_valid_port:
        pc_check = f"dut.{exec_pc_port}"
        valid_check = f"dut.{exec_valid_port}"
        pass_fail_block = f"""
            if ({valid_check} && {pc_check} == pass_addr) begin
                $display("TEST PASSED"); $finish;
            end
            if ({valid_check} && {pc_check} == fail_addr) begin
                $display("TEST FAILED at pc=%h testnum=%d", {pc_check}, dut.{rf_mem}[28]);
                $finish;
            end"""
    else:
        # Fallback: use fetch-stage PC (less reliable for pipeline)
        pass_fail_block = f"""
            if (dut.{pc_reg} == pass_addr) begin
                $display("TEST PASSED"); $finish;
            end
            if (dut.{pc_reg} == fail_addr) begin
                $display("TEST FAILED at pc=%h testnum=%d", dut.{pc_reg}, dut.{rf_mem}[28]);
                $finish;
            end"""

    return f"""`timescale 1ns/1ps
module simple_tb;
    reg clock, clear;

    {module_name} dut (
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
        // Pipeline needs more cycles: flush + steady state
        for (i = 0; i < 50000; i = i + 1) begin
            @(posedge clock);{pass_fail_block}
        end
        $display("TIMEOUT");
        $finish;
    end
endmodule
"""


if __name__ == '__main__':
    verilog_file = sys.argv[1] if len(sys.argv) > 1 else 'riscv32i_pipelined.v'
    output_file = sys.argv[2] if len(sys.argv) > 2 else 'simple_tb.sv'

    module_name, pc_reg, rf_mem, umem, exec_pc, exec_valid = extract_signals(verilog_file)

    if not all([pc_reg, rf_mem, umem]):
        print(f"ERROR: Could not extract core signals from {verilog_file}")
        print(f"  PC={pc_reg}, RF={rf_mem}, UMEM={umem}")
        sys.exit(1)

    print(f"Extracted signals:")
    print(f"  Module={module_name}, PC={pc_reg}, RF={rf_mem}, UMEM={umem}")
    print(f"  ExecPC={exec_pc}, ExecValid={exec_valid}")

    tb = generate_tb(module_name, pc_reg, rf_mem, umem, exec_pc, exec_valid)
    with open(output_file, 'w') as f:
        f.write(tb)
    print(f"Generated {output_file}")
