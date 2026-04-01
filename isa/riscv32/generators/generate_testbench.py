#!/usr/bin/env python3
"""
Generate a testbench for a RISC-V pipelined processor.

This script parses the Verilog module and generates a testbench that correctly
connects all reset ports to appropriate default values.
"""

import re
import sys
import os

# Add project root to path for imports
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def parse_module_ports(verilog_file, target_module=None):
    """
    Parse a Verilog file to extract module name and ports.

    Finds the main (top-level) module by deriving the expected name from the
    file/directory name, then extracts only that module's port declarations.

    Returns:
        dict with 'module_name' and 'ports' (list of dicts with name, direction, width)
    """
    with open(verilog_file, 'r') as f:
        content = f.read()

    # Derive expected main module name from file name (e.g. riscv32i_pipelined_5stage.v)
    expected_name = target_module or os.path.splitext(os.path.basename(verilog_file))[0]

    # Find the main module - prefer one matching the file name, fall back to first
    module_pattern = re.compile(r'module\s+(\w+)\s*(?:#\s*\([^)]*\)\s*)?\(', re.DOTALL)
    main_module_match = None
    for m in module_pattern.finditer(content):
        if m.group(1) == expected_name:
            main_module_match = m
            break
    if not main_module_match:
        # Fall back to first module
        main_module_match = module_pattern.search(content)
    if not main_module_match:
        raise ValueError(f"Could not find module in {verilog_file}")
    module_name = main_module_match.group(1)

    # Extract only the port declaration section of this module (up to closing ");")
    module_start = main_module_match.start()
    closing = content.find(');', module_start)
    if closing == -1:
        port_section = content[module_start:]
    else:
        port_section = content[module_start:closing]

    # Find all port declarations within the main module's header
    ports = []

    # Look for input/output declarations
    # Pattern: input [31:0] name,  or input name,
    port_pattern = re.compile(r'(input|output)\s+(wire\s+|reg\s+)?(\[(\d+):(\d+)\]\s+)?(\w+)')

    for match in port_pattern.finditer(port_section):
        direction = match.group(1)
        msb = int(match.group(4)) if match.group(4) else 0
        lsb = int(match.group(5)) if match.group(5) else 0
        name = match.group(6)
        width = msb - lsb + 1 if msb >= lsb else lsb - msb + 1

        ports.append({
            'name': name,
            'direction': direction,
            'width': width
        })

    return {
        'module_name': module_name,
        'ports': ports
    }


def generate_testbench(verilog_file, output_file=None):
    """
    Generate a testbench for the given Verilog file.
    """
    module_info = parse_module_ports(verilog_file)
    module_name = module_info['module_name']
    ports = module_info['ports']

    # Find reset ports and their widths
    reset_ports = []
    clk_port = None
    reset_port = None
    other_inputs = []

    for port in ports:
        name = port['name']
        if name == 'clk':
            clk_port = port
        elif name == 'reset':
            reset_port = port
        elif port['direction'] == 'input' and name.startswith('reset_'):
            reset_ports.append(port)
        elif port['direction'] == 'input':
            other_inputs.append(port)

    # Generate testbench
    tb_lines = []
    tb_lines.append('`timescale 1ns/1ps')
    tb_lines.append('module simple_tb;')
    tb_lines.append('    reg clk, reset;')
    tb_lines.append('    wire [31:0] zero32 = 32\'d0;')
    tb_lines.append('    wire zero1 = 1\'b0;')
    tb_lines.append('')

    # DUT instantiation
    tb_lines.append(f'    {module_name} dut (')
    tb_lines.append('        .clk(clk),')
    tb_lines.append('        .reset(reset),')

    # Connect reset ports
    port_connections = []
    for port in reset_ports:
        if port['width'] == 1:
            port_connections.append(f"        .{port['name']}(zero1)")
        else:
            port_connections.append(f"        .{port['name']}(zero32)")

    # Also connect other input ports (like irq_*, external interrupts, etc.)
    for port in other_inputs:
        if port['width'] == 1:
            port_connections.append(f"        .{port['name']}(zero1)")
        else:
            port_connections.append(f"        .{port['name']}(zero32)")

    if port_connections:
        tb_lines.append(',\n'.join(port_connections))

    tb_lines.append('    );')
    tb_lines.append('')

    # Find the PC tracking signal - look for patterns like PIPE_*_pc_rd_PIPE_PIPE
    # This is the PC value in the Execute stage (or whichever stage commits)
    exec_pc_signal = None
    exec_valid_signal = None

    # Read the verilog file to find internal signals
    with open(verilog_file, 'r') as f:
        verilog_content = f.read()

    # Find PC pipeline register (for tracking execution)
    # We need the DEEPEST PC pipeline register - the one with most _PIPE suffixes
    # This corresponds to the commit time (where RF writes happen)
    # Pattern: reg [...] [p0_]PIPE_*pc_rd*PIPE (matches any pipelined pc_rd signal,
    # including dual-issue prefixed versions like p0_PIPE_...)
    pc_pattern = re.compile(r'reg\s+\[\d+:\d+\]\s+((?:p0_)?PIPE_\w*pc_rd\w*_PIPE\w*)')
    all_pc_signals = pc_pattern.findall(verilog_content)

    if all_pc_signals:
        # Find the deepest PC signal (most _PIPE suffixes = latest pipeline stage)
        # Count _PIPE occurrences and pick the one with the most
        def count_pipe_depth(signal):
            return signal.count('_PIPE')

        # Sort by depth (most _PIPE suffixes first)
        all_pc_signals.sort(key=count_pipe_depth, reverse=True)
        exec_pc_signal = all_pc_signals[0]
        print(f"  Found {len(all_pc_signals)} PC signals, using deepest: {exec_pc_signal} (depth={count_pipe_depth(exec_pc_signal)})")

    # For dual-issue 2-stage pipelines (no pipelined PC), use p0_fetch_pc
    if not exec_pc_signal:
        if re.search(r'reg\s+\[\d+:\d+\]\s+p0_fetch_pc\b', verilog_content):
            exec_pc_signal = 'p0_fetch_pc'
            print(f"  Using dual-issue 2-stage PC signal: {exec_pc_signal}")

    # Find validity signal that matches the PC signal's pipeline stage.
    # The valid signal should be from the same stage as the exec_pc signal.
    # Extract the stage name from the PC signal if possible.
    if exec_pc_signal:
        # For dual-issue: p0_PIPE_Execute_PIPE_Decode_pc_rd_PIPE_PIPE -> stage is Execute
        # For single-issue: PIPE_Execute_pc_rd_PIPE -> stage is Execute
        # The stage name is the first PIPE_<StageName> in the signal
        stage_match = re.search(r'(?:p0_)?PIPE_(\w+?)_', exec_pc_signal)
        if stage_match:
            pc_stage = stage_match.group(1)
            # Try to find valid signal for this specific stage
            prefix = 'p0_' if exec_pc_signal.startswith('p0_') else ''
            stage_valid = f'{prefix}PIPE_{pc_stage}_valid_PIPE'
            if re.search(r'reg\s+' + re.escape(stage_valid), verilog_content):
                exec_valid_signal = stage_valid
                print(f"  Valid signal: {exec_valid_signal} (matched PC stage: {pc_stage})")

    if not exec_valid_signal:
        valid_patterns = [
            r'reg\s+(PIPE_Execute_valid_PIPE)',
            r'reg\s+(PIPE_ExecuteMemoryWriteback_valid_PIPE)',
            r'reg\s+(PIPE_MemoryWriteback_valid_PIPE)',
            r'reg\s+(PIPE_\w+_valid_PIPE)',
            # Dual-issue: P0's valid pipeline register
            r'reg\s+(p0_PIPE_Execute_valid_PIPE)',
            r'reg\s+(p0_PIPE_ExecuteMemoryWriteback_valid_PIPE)',
            r'reg\s+(p0_PIPE_\w+_valid_PIPE)',
        ]

        for pattern in valid_patterns:
            match = re.search(pattern, verilog_content)
            if match:
                exec_valid_signal = match.group(1)
                break

    # Test logic
    tb_lines.append('    reg [31:0] pass_addr, fail_addr;')
    tb_lines.append('    integer i;')
    tb_lines.append('    always #5 clk = ~clk;')
    tb_lines.append('')

    if exec_pc_signal:
        tb_lines.append(f'    wire [31:0] exec_pc = dut.{exec_pc_signal};')
    else:
        tb_lines.append('    wire [31:0] exec_pc = dut.pc_rd;  // Fallback')

    if exec_valid_signal:
        tb_lines.append(f'    wire exec_valid = dut.{exec_valid_signal};')
    else:
        tb_lines.append('    wire exec_valid = 1\'b1;  // Fallback')

    # Check if control_hazard_flush exists (may be prefixed with p0_ in dual-issue)
    if re.search(r'\bp0_control_hazard_flush\b', verilog_content):
        tb_lines.append('    wire flush = dut.p0_control_hazard_flush;')
    elif re.search(r'\bcontrol_hazard_flush\b', verilog_content):
        tb_lines.append('    wire flush = dut.control_hazard_flush;')
    else:
        tb_lines.append('    wire flush = 1\'b0;')

    # For pass/fail detection: instruction at pass_addr may itself cause a flush (branch)
    # So check exec_valid && pc match, without requiring !flush
    tb_lines.append('    wire exec_at_pass = exec_valid && (exec_pc == pass_addr);')
    tb_lines.append('    wire exec_at_fail = exec_valid && (exec_pc == fail_addr);')
    tb_lines.append('')

    tb_lines.append('    integer max_cycles;')
    tb_lines.append('')
    tb_lines.append('    initial begin')
    tb_lines.append('        clk = 0; reset = 1;')
    tb_lines.append('        if (!$value$plusargs("pass_addr=%h", pass_addr)) pass_addr = 32\'hFFFFFFFF;')
    tb_lines.append('        if (!$value$plusargs("fail_addr=%h", fail_addr)) fail_addr = 32\'hFFFFFFFE;')
    tb_lines.append('        if (!$value$plusargs("max_cycles=%d", max_cycles)) max_cycles = 10000;')
    tb_lines.append('        $readmemh("umem.hex", dut.umem);')
    tb_lines.append('        repeat(3) @(posedge clk);')
    tb_lines.append('        reset = 0;')
    tb_lines.append('        for (i = 0; i < max_cycles; i = i + 1) begin')
    tb_lines.append('            @(posedge clk);')
    tb_lines.append('            if (exec_at_pass) begin $display("TEST PASSED in %0d cycles", i); $finish; end')
    tb_lines.append('            if (exec_at_fail) begin $display("TEST FAILED at test %0d", dut.rf[3]); $finish; end')
    tb_lines.append('        end')
    tb_lines.append('        $display("TIMEOUT after %0d cycles", max_cycles);')
    tb_lines.append('        $finish;')
    tb_lines.append('    end')
    tb_lines.append('endmodule')

    testbench = '\n'.join(tb_lines) + '\n'

    if output_file:
        with open(output_file, 'w') as f:
            f.write(testbench)
        print(f"Generated testbench: {output_file}")
        print(f"  Module: {module_name}")
        print(f"  Reset ports: {len(reset_ports)}")
        if exec_pc_signal:
            print(f"  PC tracking: {exec_pc_signal}")
        if exec_valid_signal:
            print(f"  Valid signal: {exec_valid_signal}")
    else:
        print(testbench)

    return testbench


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python generate_testbench.py <verilog_file> [output_file]")
        sys.exit(1)

    verilog_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    generate_testbench(verilog_file, output_file)
