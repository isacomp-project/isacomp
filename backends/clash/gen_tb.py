#!/usr/bin/env python3
"""Generate testbench for Clash-generated Verilog.

Clash compiles Haskell to Verilog with a single flat state register
containing all state (PC, register file, memory) as one bitvector.
This script parses the generated Verilog to extract the state register
layout and generates a testbench that can initialize memory and monitor
execution.

For pipelined designs, pass/fail detection uses the Execute-stage PC
and validity signal extracted from the state register, matching the
approach used by the verilog and hardcaml backends.
"""
import re
import sys


def extract_signals(verilog_file):
    """Extract state register info from Clash-generated Verilog."""
    with open(verilog_file) as f:
        content = f.read()

    # Find the state register: reg [N:0] identifier = ...
    m = re.search(r'reg \[(\d+):0\] ([\w$]+)\s*=', content)
    if not m:
        return None
    state_width = int(m.group(1)) + 1
    state_reg = m.group(2)

    # Find memory extraction: assign umem = state_reg[H:L];
    umem_match = re.search(
        rf'assign umem = {re.escape(state_reg)}\[(\d+):(\d+)\];', content)
    if umem_match:
        mem_hi = int(umem_match.group(1))
        mem_lo = int(umem_match.group(2))
    else:
        mem_hi = None
        mem_lo = None

    # Find RF extraction: assign rf = state_reg[H:L];
    rf_match = re.search(
        rf'assign rf = {re.escape(state_reg)}\[(\d+):(\d+)\];', content)
    if rf_match:
        rf_hi = int(rf_match.group(1))
        rf_lo = int(rf_match.group(2))
    else:
        rf_hi = None
        rf_lo = None

    # PC is at the top of the state register, above RF
    # Try to find explicit PC extraction: assign pc* = state_reg[H:L];
    pc_match = re.search(
        rf'assign (pc\w*) = {re.escape(state_reg)}\[(\d+):(\d+)\];', content)
    if pc_match:
        pc_hi = int(pc_match.group(2))
        pc_lo = int(pc_match.group(3))
    elif rf_hi is not None:
        # PC is above RF in the state register
        pc_hi = state_width - 1
        pc_lo = rf_hi + 1
    else:
        pc_hi = state_width - 1
        pc_lo = state_width - 32

    # Module name
    m = re.search(r'module (\w+)', content)
    module_name = m.group(1) if m else 'Riscv32i_complete'

    # Check if 'en' port exists
    has_en = bool(re.search(r'input\s+wire\s+en\b', content))

    # Detect pipelined design: if memory doesn't start at bit 0,
    # there are pipeline registers below it
    is_pipelined = (mem_lo is not None and mem_lo > 0)

    # For pipelined designs, find execute-stage PC and validity signals
    # from the state register. Clash names follow the pattern:
    #   pIPE_Execute_PIPE_Decode_pc_rd_PIPE_PIPE = state_reg[H:L]
    #   pIPE_Execute_valid_PIPE = state_reg[H:H]
    # Stage names vary by pipeline depth:
    #   2-stage: pIPE_ExecuteMemoryWriteback_pc_rd_PIPE
    #   3-stage: pIPE_ExecuteMemoryWriteback_PIPE_Decode_pc_rd_PIPE_PIPE
    #   4-stage: pIPE_Execute_PIPE_Decode_pc_rd_PIPE_PIPE
    #   5-stage: pIPE_Execute_PIPE_Decode_pc_rd_PIPE_PIPE
    exec_pc_hi = None
    exec_pc_lo = None
    exec_valid_bit = None

    if is_pipelined:
        # Find execute-stage PC: pIPE_Execute*pc_rd* = state_reg[H:L]
        exec_pc_matches = re.findall(
            rf'assign\s+(pIPE_Execute\w*pc_rd\w*)\s*=\s*{re.escape(state_reg)}\[(\d+):(\d+)\];',
            content)
        if exec_pc_matches:
            # Pick the longest name (most pipelined)
            best = max(exec_pc_matches, key=lambda m: len(m[0]))
            exec_pc_hi = int(best[1])
            exec_pc_lo = int(best[2])

        # Find execute-stage validity: pIPE_Execute*valid* = state_reg[H:H]
        exec_valid_matches = re.findall(
            rf'assign\s+(pIPE_Execute\w*valid\w*)\s*=\s*{re.escape(state_reg)}\[(\d+):(\d+)\];',
            content)
        if exec_valid_matches:
            best = max(exec_valid_matches, key=lambda m: len(m[0]))
            exec_valid_bit = int(best[1])

    return {
        'state_reg': state_reg,
        'state_width': state_width,
        'module_name': module_name,
        'has_en': has_en,
        'is_pipelined': is_pipelined,
        'pc_hi': pc_hi,
        'pc_lo': pc_lo,
        'rf_hi': rf_hi,
        'rf_lo': rf_lo,
        'mem_hi': mem_hi,
        'mem_lo': mem_lo,
        'exec_pc_hi': exec_pc_hi,
        'exec_pc_lo': exec_pc_lo,
        'exec_valid_bit': exec_valid_bit,
    }


def generate_tb(info, num_rf_regs=32, reg_width=32):
    """Generate testbench for Clash design."""
    state_reg = info['state_reg']
    module_name = info['module_name']
    has_en = info['has_en']
    is_pipelined = info['is_pipelined']

    # Use extracted bit ranges or compute them
    if info['mem_hi'] is not None:
        mem_hi = info['mem_hi']
        mem_lo = info['mem_lo']
    else:
        pc_bits = info['pc_hi'] - info['pc_lo'] + 1
        rf_bits = num_rf_regs * reg_width
        mem_hi = info['state_width'] - pc_bits - rf_bits - 1
        mem_lo = 0

    if info['rf_hi'] is not None:
        rf_hi = info['rf_hi']
    else:
        pc_bits = info['pc_hi'] - info['pc_lo'] + 1
        rf_hi = info['state_width'] - pc_bits - 1

    mem_bits = mem_hi - mem_lo + 1
    mem_words = mem_bits // reg_width

    # GP register (x3) bit positions - used for riscv-tests pass/fail
    gp_hi = rf_hi - 3 * reg_width

    # Escaped identifier for hierarchical reference (handles $ in name)
    if '$' in state_reg:
        esc_reg = f'\\{state_reg} '
    else:
        esc_reg = state_reg

    # Module instantiation ports
    en_port = '\n        .en(en),' if has_en else ''
    en_decl = '\n    reg en;' if has_en else ''
    en_init = ' en = 1;' if has_en else ''

    # Generate pass/fail detection logic based on pipeline type
    if is_pipelined and info['exec_pc_hi'] is not None and info['exec_valid_bit'] is not None:
        # Pipelined design with execute-stage PC: use direct PC comparison
        # gated by execute-stage validity, matching examples/verilog/hardcaml approach
        exec_pc_hi = info['exec_pc_hi']
        exec_valid_bit = info['exec_valid_bit']

        passfail_decls = f"""
    wire [31:0] exec_pc;
    wire exec_valid;

    // Execute-stage PC and validity from state register
    assign exec_pc = dut.{esc_reg}[{exec_pc_hi} -: 32];
    assign exec_valid = dut.{esc_reg}[{exec_valid_bit}];"""

        passfail_init = ""

        passfail_check = f"""
            if (exec_valid && exec_pc == pass_addr) begin
                $display("TEST PASSED"); $finish;
            end
            if (exec_valid && exec_pc == fail_addr) begin
                $display("TEST FAILED at pc=%h testnum=%0d", exec_pc, dut.{esc_reg}[{gp_hi} -: 32] >> 1);
                $finish;
            end"""
        max_cycles = 20000
    elif is_pipelined:
        # Pipelined design without execute-stage signals: fallback to
        # gp register + infinite loop detection
        passfail_decls = f"""
    wire [31:0] gp_val;
    reg [31:0] prev_pc;
    integer same_pc_count;

    // Read gp register (x3) from register file in state register
    assign gp_val = dut.{esc_reg}[{gp_hi} -: 32];"""

        passfail_init = """
        prev_pc = 32'hFFFFFFFF;
        same_pc_count = 0;"""

        passfail_check = """
            // Pipelined pass/fail detection using gp register
            // riscv-tests set gp=1 on pass, gp=(test_num<<1|1) on fail
            if (gp_val == 32'h1) begin
                $display("TEST PASSED");
                $finish;
            end
            // Detect infinite loop (j . instruction) for fail detection
            if (pc == prev_pc) begin
                same_pc_count = same_pc_count + 1;
            end else begin
                same_pc_count = 0;
                prev_pc = pc;
            end
            if (same_pc_count >= 10) begin
                if (gp_val == 32'h1) begin
                    $display("TEST PASSED");
                end else begin
                    $display("TEST FAILED testnum=%0d", gp_val >> 1);
                end
                $finish;
            end"""
        max_cycles = 20000
    else:
        # Non-pipelined design: check fetch PC directly
        passfail_decls = ""
        passfail_init = ""
        passfail_check = f"""
            if (pc == pass_addr) begin $display("TEST PASSED"); $finish; end
            if (pc == fail_addr) begin
                $display("TEST FAILED at pc=%h testnum=%0d", pc, dut.{esc_reg}[{gp_hi} -: 32] >> 1);
                $finish;
            end"""
        max_cycles = 10000

    # Build state-register zeroing code that handles widths not divisible by 32
    remainder = info['state_width'] % reg_width
    if remainder:
        partial_clear = (
            f"// Clear upper {remainder} bits that don't fill a full 32-bit word\n"
            f"        dut.{esc_reg}[{info['state_width'] - 1} -: {remainder}] = {remainder}'h0;\n"
            f"        "
        )
        loop_top_bit = info['state_width'] - 1 - remainder
    else:
        partial_clear = ""
        loop_top_bit = info['state_width'] - 1

    return f"""`timescale 1ns/1ps
module simple_tb;
    reg clk, rst;{en_decl}
    wire [31:0] pc;

    {module_name} dut (
        .clk(clk),
        .rst(rst),{en_port}
        .pc(pc)
    );

    reg [31:0] pass_addr, fail_addr;
    reg [31:0] mem_init [0:{mem_words - 1}];
    integer i;{passfail_decls}
    always #5 clk = ~clk;

    initial begin
        clk = 0; rst = 0;{en_init}
        if (!$value$plusargs("pass_addr=%h", pass_addr)) pass_addr = 32'hFFFFFFFF;
        if (!$value$plusargs("fail_addr=%h", fail_addr)) fail_addr = 32'hFFFFFFFE;{passfail_init}

        // Wait for DUT's reg initializers to settle before modifying state
        #1;

        // Zero the entire state register (clears pipeline regs, PC, RF, memory)
        {partial_clear}for (i = 0; i < {info['state_width'] // reg_width}; i = i + 1) begin
            dut.{esc_reg}[{loop_top_bit} - i*32 -: 32] = 32'h0;
        end

        // Initialize memory array to zero
        for (i = 0; i < {mem_words}; i = i + 1) mem_init[i] = 32'h0;

        // Load hex file into temporary array
        $readmemh("umem.hex", mem_init);

        // Copy memory data into flat state register
        // Clash packs all state into one bitvector: (PC, RF, Memory)
        // Memory region: bits [{mem_hi}:{mem_lo}] of {state_reg}
        for (i = 0; i < {mem_words}; i = i + 1) begin
            dut.{esc_reg}[{mem_hi} - i*32 -: 32] = mem_init[i];
        end

        // Start clocking - #1 ensures state is set before first posedge
        #1;
        for (i = 0; i < {max_cycles}; i = i + 1) begin
            @(posedge clk);{passfail_check}
        end
        $display("TIMEOUT");
        $finish;
    end
endmodule
"""


if __name__ == '__main__':
    verilog_file = sys.argv[1] if len(sys.argv) > 1 else 'Riscv32i_complete.v'
    output_file = sys.argv[2] if len(sys.argv) > 2 else 'simple_tb.sv'

    info = extract_signals(verilog_file)
    if not info:
        print(f"ERROR: Could not extract state register from {verilog_file}")
        sys.exit(1)

    mem_bits = (info['mem_hi'] or 0) - (info['mem_lo'] or 0) + 1
    mem_words = mem_bits // 32

    print(f"Module: {info['module_name']}")
    print(f"State register: {info['state_reg']} [{info['state_width']-1}:0]")
    print(f"PC at [{info['pc_hi']}:{info['pc_lo']}]")
    print(f"RF at [{info['rf_hi']}:{info['rf_lo']}]")
    print(f"Memory at [{info['mem_hi']}:{info['mem_lo']}] ({mem_words} words)")
    print(f"Enable port: {'yes' if info['has_en'] else 'no'}")
    print(f"Pipelined: {'yes' if info['is_pipelined'] else 'no'}")
    if info['is_pipelined']:
        if info['exec_pc_hi'] is not None:
            print(f"Execute PC at [{info['exec_pc_hi']}:{info['exec_pc_lo']}]")
        else:
            print(f"Execute PC: not found (using gp fallback)")
        if info['exec_valid_bit'] is not None:
            print(f"Execute valid at [{info['exec_valid_bit']}]")
        else:
            print(f"Execute valid: not found (using gp fallback)")

    tb = generate_tb(info)
    with open(output_file, 'w') as f:
        f.write(tb)
    print(f"Generated {output_file}")
