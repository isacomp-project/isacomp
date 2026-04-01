#!/usr/bin/env python3
"""
Generate complete J2 (SuperH-2) processor with all instructions.

This includes all arithmetic, logical, shift, compare, branch, jump, load, and store instructions
for full j2 core compatibility (j-core.org), plus J2-specific extensions.

Supports Verilog, VHDL, PyRTL, and CIRCT backends via --backend argument.
"""
import sys
import os
import argparse

# Add parent directories to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core.graph_merger import merge_instructions
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec
from opt.memory.memory_externalization import apply_memory_externalization, MemoryExternalizationSpec
from backends.vhdl.test_generator import generate_vhdl_test_runner_tb, generate_vhdl_test_script

# Test list for J2 (tests that have assembly test files)
J2_TESTS = [
    "add", "sub", "and", "or", "xor", "mov", "nop"
]

# Complete J2/SH-2 instruction set (133 instructions total)
INSTRUCTIONS = [
    # Arithmetic (18)
    'add', 'addc', 'addi', 'addv', 'sub', 'subc', 'subv', 'neg', 'negc',
    'mull', 'mulsw', 'muluw', 'dmulsl', 'dmulul', 'dt',
    'extsb', 'extsw', 'extub', 'extuw',

    # Logical (9)
    'and', 'andi', 'or', 'ori', 'xor', 'xori', 'not', 'tst', 'tsti',

    # Shift & Rotate (16) - includes J2 barrel shifts
    'shal', 'shar',
    'shll', 'shll2', 'shll8', 'shll16',
    'shlr', 'shlr2', 'shlr8', 'shlr16',
    'rotl', 'rotr', 'rotcl', 'rotcr',
    'shad', 'shld',

    # Data Movement - Basic (19)
    'mov', 'movi', 'mova', 'movt',
    'movl', 'movl_store', 'movl_postinc', 'movl_predec',
    'movl_indexed', 'movl_indexed_store', 'movl_pcrel',
    'movw', 'movw_store', 'movw_pcrel',
    'movb', 'movb_store',
    'swapb', 'swapw', 'xtrct',

    # Data Movement - Byte/Word Extended (8)
    'movb_postinc', 'movw_postinc',  # @Rm+,Rn
    'movb_predec', 'movw_predec',    # Rm,@-Rn
    'movb_indexed', 'movw_indexed',  # @(R0,Rm),Rn
    'movb_indexed_store', 'movw_indexed_store',  # Rm,@(R0,Rn)

    # Data Movement - Displacement (6)
    'movb_disp_load', 'movw_disp_load', 'movl_disp_load',    # @(disp,Rm),R0 or Rn
    'movb_disp_store', 'movw_disp_store', 'movl_disp_store',  # R0,@(disp,Rn) or Rm

    # Data Movement - GBR-relative (6)
    'movb_gbr_load', 'movw_gbr_load', 'movl_gbr_load',    # @(disp,GBR),R0
    'movb_gbr_store', 'movw_gbr_store', 'movl_gbr_store', # R0,@(disp,GBR)

    # GBR Memory Modify (4)
    'andb_gbr', 'orb_gbr', 'tstb_gbr', 'xorb_gbr',

    # Comparison (9)
    'cmpeq', 'cmpge', 'cmpgt', 'cmphi', 'cmphs',
    'cmppl', 'cmppz', 'cmpimm', 'cmpstr',

    # Branch & Control (11)
    'bt', 'bf', 'bts', 'bfs',
    'bra', 'braf', 'bsr', 'bsrf',
    'jmp', 'jsr', 'rts',

    # System Control - Basic (21)
    'clrt', 'sett',
    'lds_pr', 'sts_pr',
    'ldsl_pr', 'stsl_pr',  # LDS.L @Rn+,PR and STS.L PR,@-Rn
    'lds_macl', 'sts_macl', 'lds_mach', 'sts_mach',
    'ldsl_macl', 'stsl_macl', 'ldsl_mach', 'stsl_mach',  # LDS.L/STS.L for MAC registers
    'lds_gbr', 'sts_gbr',
    'ldcl_gbr', 'stcl_gbr',  # LDC.L/STC.L for GBR
    'ldcl_sr', 'stcl_sr',    # LDC.L/STC.L for SR (context switch)

    # System Control - Privileged (6)
    'ldc_sr', 'stc_sr',      # SR access (LDC privileged)
    'ldc_vbr', 'stc_vbr',    # VBR access (LDC privileged)
    'rte',                    # Return from exception
    'sleep',                  # Sleep until interrupt

    # MAC Instructions (3)
    'clrmac', 'macl', 'macw',

    # Division (3)
    'div0s', 'div0u', 'div1',

    # Special (4) - includes J2 CAS
    'nop', 'tasb', 'trapa', 'casl',  # casl is J2-specific
]


def apply_memory_transform(merged_graph):
    """Apply port width setting for word-addressed unified memory.

    J2 has byte (8-bit), word (16-bit), and long (32-bit) memory accesses.
    This transformation creates byte selection muxes for sub-word accesses.
    """
    # Check for unified memory (umem) first, then dmem
    mem_node = merged_graph.nodes.get('umem') or merged_graph.nodes.get('dmem')
    mem_name = 'umem' if merged_graph.nodes.get('umem') else 'dmem'

    if mem_node:
        access_widths = mem_node.data.get('access_widths', [32])
        max_width = max(access_widths) if access_widths else 32
        print(f"  {mem_name} access widths: {access_widths}, max: {max_width}")

        # Apply set_port_width transformation to create byte selection mux nodes
        # J2/SH2 is a big-endian architecture
        transform = MemoryAccessTransform(merged_graph)
        spec = MemoryAccessTransformSpec(
            memory=mem_name,
            strategy='set_port_width',
            current_width=max_width,
            target_width=32,  # Word-addressed memory (32-bit)
            direction='forward',
            endianness='big'  # J2/SH2 is big-endian
        )
        result = transform.apply_transformation(spec)
        if result.get('transformed'):
            print(f"  Transformed: added {len(result.get('nodes_added', []))} byte mux nodes")
        else:
            print(f"  Skipped: {result.get('reason', 'unknown')}")
    else:
        print("  No memory node found (umem/dmem), skipping memory transform")


def generate_verilog(merged_graph, module_name, output_dir, externalized=False):
    """Generate Verilog output."""
    from backends.verilog import VerilogGenerator
    from pathlib import Path

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Generate RTL
    generator = VerilogGenerator(merged_graph, module_name)
    verilog_code = generator.generate()

    rtl_file = output_path / f"{module_name}.v"
    rtl_file.write_text(verilog_code)

    files = {'rtl': rtl_file}

    # Check if any memories are externalized
    has_externalized = bool(generator.externalized_memories)

    if has_externalized:
        # Generate memory wrappers for each externalized memory
        for mem_name in generator.externalized_memories:
            wrapper_code = generator.generate_memory_wrapper(mem_name)
            if wrapper_code:
                wrapper_file = output_path / f"{mem_name}_memory.v"
                wrapper_file.write_text(wrapper_code)
                files[f'{mem_name}_wrapper'] = wrapper_file
                print(f"  Generated memory wrapper: {wrapper_file}")

        # Generate testbench for externalized memory
        testbench_code = generate_externalized_memory_testbench(
            generator, module_name, output_path
        )
        tb_file = output_path / f"simple_tb.sv"
        tb_file.write_text(testbench_code)
        files['testbench'] = tb_file
        print(f"  Generated externalized memory testbench: {tb_file}")
    else:
        # Use standard testbench generation
        from backends.verilog import generate_verilog_with_testbench
        testbench_config = {
            'timeout_cycles': 10000,
            'imem_data_width': 16,  # J2 has 16-bit instructions
            'dmem_data_width': 32,  # J2 has 32-bit data
        }
        tb_files = generate_verilog_with_testbench(
            merged_graph,
            module_name=module_name,
            output_dir=output_dir,
            testbench_config=testbench_config
        )
        files.update(tb_files)

    return files


def generate_externalized_memory_testbench(generator, module_name, output_path):
    """Generate a testbench for a J2 processor with externalized memory.

    This testbench:
    1. Instantiates the processor module
    2. Creates multi-port memory model with valid-ready handshake
    3. Connects the external memory ports
    4. Loads test programs via $readmemh into external memory
    """
    from pathlib import Path

    # Collect information about externalized memory ports
    ext_memories = list(generator.externalized_memories)
    if not ext_memories:
        return ""

    # Build port lists for each externalized memory
    memory_ports = {}
    for mem_name in ext_memories:
        memory_ports[mem_name] = {
            'read_ports': [],
            'write_ports': [],
            'data_width': 32,
            'addr_width': 32,
        }

        # Get info from generator
        mem_info = generator.memory_declarations.get(mem_name, {})
        memory_ports[mem_name]['data_width'] = mem_info.get('bit_width', 32)
        # For externalized memory ports, use full 32-bit addresses
        memory_ports[mem_name]['addr_width'] = mem_info.get('externalized_addr_width', 32)
        memory_ports[mem_name]['use_valid_ready'] = mem_info.get('use_valid_ready', True)
        # Get latency specification from memory node
        memory_ports[mem_name]['min_latency'] = mem_info.get('min_latency', 0)
        memory_ports[mem_name]['max_latency'] = mem_info.get('max_latency', 0)

        # Find read ports for this memory
        tracked_read = set()
        for rp in generator.memory_read_ports:
            if rp['mem'] == mem_name:
                ext_port = rp.get('ext_port_name', mem_name)
                if ext_port not in tracked_read:
                    tracked_read.add(ext_port)
                    memory_ports[mem_name]['read_ports'].append(ext_port)

        # Find write ports for this memory
        tracked_write = set()
        for wp in generator.memory_write_ports:
            if wp['mem'] == mem_name:
                ext_port = wp.get('ext_port_name', mem_name)
                if ext_port not in tracked_write:
                    tracked_write.add(ext_port)
                    memory_ports[mem_name]['write_ports'].append(ext_port)

    # Generate testbench
    tb = []
    tb.append("`timescale 1ns/1ps\n")
    tb.append(f"module simple_tb;\n")
    tb.append("    reg clk, reset;\n")
    tb.append("    wire [31:0] zero32 = 32'd0;\n\n")

    # Declare wires for external memory connections
    tb.append("    // External memory interface signals\n")
    for mem_name, ports in memory_ports.items():
        data_width = ports['data_width']
        addr_width = ports['addr_width']

        for rp in ports['read_ports']:
            tb.append(f"    wire [{addr_width-1}:0] {rp}_read_req_addr;\n")
            tb.append(f"    wire {rp}_read_req_valid;\n")
            tb.append(f"    wire [{data_width-1}:0] {rp}_read_resp_data;\n")
            if ports['use_valid_ready']:
                tb.append(f"    wire {rp}_read_resp_ready;\n")

        for wp in ports['write_ports']:
            num_bytes = max(1, data_width // 8)
            tb.append(f"    wire [{addr_width-1}:0] {wp}_write_req_addr;\n")
            tb.append(f"    wire [{data_width-1}:0] {wp}_write_req_data;\n")
            tb.append(f"    wire [{num_bytes-1}:0] {wp}_write_req_we;\n")
            tb.append(f"    wire {wp}_write_req_valid;\n")
            if ports['use_valid_ready']:
                tb.append(f"    wire {wp}_write_resp_ready;\n")
    tb.append("\n")

    # Instantiate the processor
    tb.append(f"    // Device Under Test - J2 processor core\n")
    tb.append(f"    {module_name} dut (\n")
    tb.append("        .clk(clk),\n")
    tb.append("        .reset(reset),\n")
    tb.append("        .reset_pc(zero32),\n")
    tb.append("        .reset_pr(zero32),\n")
    tb.append("        .reset_t_rd(1'b0),\n")
    tb.append("        .reset_delay_slot(1'b0),\n")
    tb.append("        .reset_branch_target_rd(zero32),\n")
    tb.append("        .reset_macl(zero32),\n")
    tb.append("        .reset_mach(zero32),\n")
    tb.append("        .reset_gbr(zero32),\n")
    tb.append("        .reset_sr(32'h40000000),  // MD=1 privileged mode\n")
    tb.append("        .reset_vbr(zero32),\n")
    tb.append("        .irq_i_rd(1'b0),\n")
    tb.append("        .irq_i_wr(1'b0),\n")
    tb.append("        .irq_priority_rd(4'd0),\n")
    tb.append("        .irq_priority_wr(4'd0),\n")
    tb.append("        .irq_vector_rd(8'd0),\n")
    tb.append("        .irq_vector_wr(8'd0)")

    # Connect external memory ports
    for mem_name, ports in memory_ports.items():
        for rp in ports['read_ports']:
            tb.append(f",\n        .{rp}_read_req_addr({rp}_read_req_addr)")
            tb.append(f",\n        .{rp}_read_req_valid({rp}_read_req_valid)")
            tb.append(f",\n        .{rp}_read_resp_data({rp}_read_resp_data)")
            if ports['use_valid_ready']:
                tb.append(f",\n        .{rp}_read_resp_ready({rp}_read_resp_ready)")

        for wp in ports['write_ports']:
            tb.append(f",\n        .{wp}_write_req_addr({wp}_write_req_addr)")
            tb.append(f",\n        .{wp}_write_req_data({wp}_write_req_data)")
            tb.append(f",\n        .{wp}_write_req_we({wp}_write_req_we)")
            tb.append(f",\n        .{wp}_write_req_valid({wp}_write_req_valid)")
            if ports['use_valid_ready']:
                tb.append(f",\n        .{wp}_write_resp_ready({wp}_write_resp_ready)")

    tb.append("\n    );\n\n")

    # For each externalized memory, create a multi-port memory model
    for mem_name, ports in memory_ports.items():
        data_width = ports['data_width']
        addr_width = ports['addr_width']
        depth = 16777216  # 64MB for 32-bit words (J2 has 24-bit word address = 16M words)
        num_bytes = max(1, data_width // 8)
        word_addr_bits = 2 if data_width == 32 else 3

        min_latency = ports.get('min_latency', 0)
        max_latency = ports.get('max_latency', 0)

        tb.append(f"    // {mem_name} - multi-port memory model (J2 unified memory)\n")
        tb.append(f"    // Latency specification: min={min_latency}, max={max_latency}\n")
        tb.append(f"    parameter {mem_name.upper()}_MEM_LATENCY = {min_latency};  // 0 = combinational\n")
        tb.append(f"    reg [{data_width-1}:0] {mem_name}_mem [0:{depth-1}];\n\n")

        mem_latency_param = f"{mem_name.upper()}_MEM_LATENCY"
        for rp in ports['read_ports']:
            tb.append(f"    // {rp} read interface\n")
            tb.append(f"    generate\n")
            tb.append(f"        if ({mem_latency_param} == 0) begin : {rp}_comb\n")
            tb.append(f"            // Combinational read (single-cycle processor)\n")
            tb.append(f"            assign {rp}_read_resp_data = {mem_name}_mem[{rp}_read_req_addr[{addr_width-1}:{word_addr_bits}]];\n")
            if ports['use_valid_ready']:
                tb.append(f"            assign {rp}_read_resp_ready = {rp}_read_req_valid;\n")
            tb.append(f"        end else if ({mem_latency_param} == 1) begin : {rp}_lat1\n")
            tb.append(f"            // Single-cycle latency\n")
            tb.append(f"            reg resp_ready_reg;\n")
            tb.append(f"            reg [{data_width-1}:0] resp_data_reg;\n")
            tb.append(f"            always @(posedge clk) begin\n")
            tb.append(f"                if (reset) resp_ready_reg <= 0;\n")
            tb.append(f"                else begin\n")
            tb.append(f"                    resp_ready_reg <= {rp}_read_req_valid;\n")
            tb.append(f"                    if ({rp}_read_req_valid)\n")
            tb.append(f"                        resp_data_reg <= {mem_name}_mem[{rp}_read_req_addr[{addr_width-1}:{word_addr_bits}]];\n")
            tb.append(f"                end\n")
            tb.append(f"            end\n")
            tb.append(f"            assign {rp}_read_resp_data = resp_data_reg;\n")
            if ports['use_valid_ready']:
                tb.append(f"            assign {rp}_read_resp_ready = resp_ready_reg;\n")
            tb.append(f"        end else begin : {rp}_pipe\n")
            tb.append(f"            // Pipelined read with configurable latency\n")
            tb.append(f"            reg [{mem_latency_param}-1:0] pending;\n")
            tb.append(f"            reg [{data_width-1}:0] data_pipe [0:{mem_latency_param}-1];\n")
            tb.append(f"            reg [{addr_width-1}:0] addr_pipe [0:{mem_latency_param}-1];\n")
            tb.append(f"            reg resp_ready_reg;\n")
            tb.append(f"            reg [{data_width-1}:0] resp_data_reg;\n")
            tb.append(f"            always @(posedge clk) begin\n")
            tb.append(f"                if (reset) begin pending <= 0; resp_ready_reg <= 0; end\n")
            tb.append(f"                else begin\n")
            tb.append(f"                    pending <= {{pending[{mem_latency_param}-2:0], {rp}_read_req_valid}};\n")
            tb.append(f"                    if ({rp}_read_req_valid) begin\n")
            tb.append(f"                        data_pipe[0] <= {mem_name}_mem[{rp}_read_req_addr[{addr_width-1}:{word_addr_bits}]];\n")
            tb.append(f"                        addr_pipe[0] <= {rp}_read_req_addr;\n")
            tb.append(f"                    end\n")
            tb.append(f"                    for (integer j = 1; j < {mem_latency_param}; j = j + 1) begin\n")
            tb.append(f"                        data_pipe[j] <= data_pipe[j-1];\n")
            tb.append(f"                        addr_pipe[j] <= addr_pipe[j-1];\n")
            tb.append(f"                    end\n")
            tb.append(f"                    resp_ready_reg <= pending[{mem_latency_param}-1] && (addr_pipe[{mem_latency_param}-1] == {rp}_read_req_addr);\n")
            tb.append(f"                    resp_data_reg <= data_pipe[{mem_latency_param}-1];\n")
            tb.append(f"                end\n")
            tb.append(f"            end\n")
            tb.append(f"            assign {rp}_read_resp_data = resp_data_reg;\n")
            if ports['use_valid_ready']:
                tb.append(f"            assign {rp}_read_resp_ready = resp_ready_reg;\n")
            tb.append(f"        end\n")
            tb.append(f"    endgenerate\n\n")

        # Write ports with byte enables
        for wp in ports['write_ports']:
            tb.append(f"    // {wp} write interface\n")
            tb.append(f"    always @(posedge clk) begin\n")
            tb.append(f"        if (!reset && {wp}_write_req_valid) begin\n")
            for b in range(num_bytes):
                tb.append(f"            if ({wp}_write_req_we[{b}]) {mem_name}_mem[{wp}_write_req_addr[{addr_width-1}:{word_addr_bits}]][{b*8} +: 8] <= {wp}_write_req_data[{b*8} +: 8];\n")
            tb.append(f"        end\n")
            tb.append(f"    end\n")
            if ports['use_valid_ready']:
                tb.append(f"    assign {wp}_write_resp_ready = {wp}_write_req_valid;\n")
            tb.append("\n")

    # Test logic
    tb.append("    reg [31:0] pass_addr, fail_addr;\n")
    tb.append("    integer i;\n")
    tb.append("    always #10 clk = ~clk;  // 50MHz\n\n")

    tb.append("    initial begin\n")
    tb.append("        clk = 0; reset = 1;\n")
    tb.append("        if (!$value$plusargs(\"pass_addr=%h\", pass_addr)) pass_addr = 32'hFFFFFFFF;\n")
    tb.append("        if (!$value$plusargs(\"fail_addr=%h\", fail_addr)) fail_addr = 32'hFFFFFFFE;\n")

    if ext_memories:
        mem_name = ext_memories[0]
        tb.append(f"        $readmemh(\"{mem_name}.hex\", {mem_name}_mem);\n")

    tb.append("        repeat(10) @(posedge clk);\n")
    tb.append("        reset = 0;\n")
    tb.append("        for (i = 0; i < 100000; i = i + 1) begin\n")
    tb.append("            @(posedge clk);\n")
    tb.append("            if (dut.pc == pass_addr) begin $display(\"TEST PASSED\"); $finish; end\n")
    tb.append("            if (dut.pc == fail_addr) begin $display(\"TEST FAILED at pc=%h\", dut.pc); $finish; end\n")
    tb.append("        end\n")
    tb.append("        $display(\"TIMEOUT\");\n")
    tb.append("        $finish;\n")
    tb.append("    end\n")
    tb.append("endmodule\n")

    return "".join(tb)


def generate_vhdl(merged_graph, entity_name, output_dir, verify=True):
    """Generate VHDL output."""
    from backends.vhdl import generate_vhdl_with_testbench, VHDLTestbenchConfig
    from pathlib import Path

    testbench_config = VHDLTestbenchConfig(
        entity_name=entity_name,
        timeout_cycles=10000,
        imem_size=4096,
        dmem_size=4096
    )

    files = generate_vhdl_with_testbench(
        merged_graph,
        entity_name=entity_name,
        output_dir=output_dir,
        testbench_config=testbench_config,
        debug_outputs=['pc_rd']  # Expose PC for debugging
    )

    # Generate test runner testbench and script
    vhdl_file = str(files['rtl'])
    test_runner_tb = generate_vhdl_test_runner_tb(
        vhdl_file, entity_name, output_dir,
        pc_width=32, is_pipelined=False
    )
    test_script = generate_vhdl_test_script(
        entity_name, output_dir,
        arch="J2 (SuperH-2)",
        tests=J2_TESTS,
        test_base_path="../j2-tests/isa/j2-isacomp-",
        data_width=32, is_pipelined=False
    )
    files['test_runner_tb'] = Path(test_runner_tb)
    files['test_script'] = Path(test_script)
    print(f"  Generated: {test_runner_tb}")
    print(f"  Generated: {test_script}")

    # Optionally verify compilation with GHDL
    if verify:
        print("\n" + "=" * 70)
        print("Verifying VHDL compilation with GHDL...")
        print("=" * 70)
        try:
            from backends.vhdl import compile_vhdl

            success, error = compile_vhdl(
                [files['rtl'], files['testbench']],
                work_dir=files['rtl'].parent,
                std='08'
            )

            if success:
                print("  VHDL compilation successful!")
            else:
                print(f"  VHDL compilation failed:")
                print(error)
        except ImportError:
            print("  GHDL not available, skipping compilation check")
        except Exception as e:
            print(f"  Error during compilation: {e}")

    return files


def generate_pyrtl(merged_graph, module_name, output_dir):
    """Generate PyRTL output with testbench files."""
    import pyrtl
    from backends.pyrtl import generate_pyrtl as gen_pyrtl, generate_pyrtl_testbench_files, PyRTLTestbenchConfig
    from pathlib import Path

    # Generate PyRTL design
    pyrtl_block = gen_pyrtl(merged_graph, module_name)

    # Create testbench configuration
    config = PyRTLTestbenchConfig(
        module_name=module_name,
        timeout_cycles=10000,
        imem_size=4096,
        dmem_size=4096,
        arch='j2'
    )

    # Generate testbench files with instructions list for test runner
    output_path = Path(output_dir)
    files = generate_pyrtl_testbench_files(
        pyrtl_block,
        module_name=module_name,
        output_dir=output_path,
        config=config,
        instructions=INSTRUCTIONS,
        arch='j2'
    )

    # Also output the PyRTL block as Verilog for inspection
    verilog_file = output_path / f"{module_name}.v"
    with open(verilog_file, 'w') as f:
        pyrtl.output_to_verilog(f, block=pyrtl_block)
    files['verilog'] = verilog_file

    print(f"  PyRTL block contains:")
    print(f"    {len(list(pyrtl_block.logic))} logic operations")
    print(f"    {len(list(pyrtl_block.wirevector_set))} wires")

    return files


def generate_circt(merged_graph, module_name, output_dir):
    """Generate CIRCT MLIR output and convert to Verilog."""
    import re
    import shutil
    from pathlib import Path
    from backends.circt.circt_generator import generate_circt as gen_circt_mlir
    from backends.circt.circt_testbench import generate_circt_testbench

    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Generate CIRCT MLIR
    mlir_output = gen_circt_mlir(merged_graph, module_name)

    # Write MLIR file
    mlir_file = output_path / f'{module_name}.mlir'
    with open(mlir_file, 'w') as f:
        f.write(mlir_output)

    files = {'mlir': str(mlir_file)}
    print(f"  Generated MLIR: {mlir_file} ({len(mlir_output)} bytes)")

    # Find firtool in PATH
    firtool_path = shutil.which('firtool')
    if firtool_path is None:
        raise RuntimeError("firtool not found in PATH. Please install CIRCT and ensure firtool is available.")

    # Convert to Verilog using firtool
    if firtool_path:
        import subprocess
        sv_file = output_path / f'{module_name}.sv'
        try:
            result = subprocess.run(
                [firtool_path, str(mlir_file), '-o', str(sv_file)],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode == 0:
                files['systemverilog'] = str(sv_file)
                print(f"  Generated SystemVerilog: {sv_file}")

                # Post-process for Verilator compatibility:
                # Convert packed arrays to unpacked arrays for $readmemh support
                with open(sv_file, 'r') as f:
                    content = f.read()

                # Fix imem: reg [N:0][15:0] imem -> reg [15:0] imem [0:N]
                content = re.sub(
                    r'reg\s+\[(\d+):0\]\[(\d+):0\]\s+imem;',
                    r'reg [\2:0] imem [0:\1];',
                    content
                )

                # Fix dmem: reg [N:0][31:0] dmem -> reg [31:0] dmem [0:N]
                content = re.sub(
                    r'reg\s+\[(\d+):0\]\[(\d+):0\]\s+dmem;',
                    r'reg [\2:0] dmem [0:\1];',
                    content
                )

                with open(sv_file, 'w') as f:
                    f.write(content)
                print("  Post-processed for Verilator compatibility")

                # Generate testbench and test runner
                tb_files = generate_circt_testbench(
                    str(sv_file),
                    module_name,
                    'j2',
                    INSTRUCTIONS
                )
                files.update(tb_files)
                print(f"  Generated testbench: {tb_files.get('testbench')}")
                print(f"  Generated test runner: {tb_files.get('test_runner')}")
            else:
                print(f"  firtool conversion failed:")
                print(f"    {result.stderr[:500]}")
        except FileNotFoundError:
            print("  firtool not found in PATH, skipping Verilog conversion")
        except subprocess.TimeoutExpired:
            print("  firtool timed out")
        except Exception as e:
            print(f"  Error running firtool: {e}")

    return files


def main():
    parser = argparse.ArgumentParser(
        description='Generate complete J2 (SuperH-2) processor from ISA definitions'
    )
    parser.add_argument(
        '--backend', '-b',
        choices=['verilog', 'vhdl', 'pyrtl', 'circt'],
        default='verilog',
        help='Output backend (default: verilog)'
    )
    parser.add_argument(
        '--no-verify',
        action='store_true',
        help='Skip GHDL compilation verification for VHDL backend'
    )
    parser.add_argument(
        '--output-dir', '-o',
        help='Output directory (default: <backend>/j2_complete)'
    )
    parser.add_argument(
        '--subset',
        choices=['minimal', 'basic', 'full'],
        default='full',
        help='Instruction subset to generate (default: full)'
    )
    parser.add_argument(
        '--externalize-memory',
        action='store_true',
        help='Externalize unified memory (umem) for external memory/peripheral bus'
    )
    args = parser.parse_args()

    # Select instruction subset
    if args.subset == 'minimal':
        # Minimal set for basic testing
        instructions = [
            'add', 'sub', 'and', 'or', 'xor', 'not',
            'mov', 'movi', 'movl', 'movl_store',
            'cmpeq', 'bt', 'bf', 'bra', 'nop'
        ]
        module_name = 'j2_minimal'
    elif args.subset == 'basic':
        # Basic set without advanced features
        instructions = [
            'add', 'addi', 'sub', 'neg',
            'and', 'andi', 'or', 'ori', 'xor', 'xori', 'not',
            'shll', 'shlr', 'rotl', 'rotr',
            'mov', 'movi', 'movl', 'movl_store', 'movw', 'movw_store', 'movb', 'movb_store',
            'cmpeq', 'cmpgt', 'cmpge', 'cmphi', 'cmphs',
            'bt', 'bf', 'bra', 'jmp', 'jsr', 'rts',
            'clrt', 'sett', 'nop'
        ]
        module_name = 'j2_basic'
    else:
        instructions = INSTRUCTIONS
        module_name = 'j2_complete'

    if args.output_dir:
        output_dir = args.output_dir
    elif args.backend == 'circt':
        output_dir = f'examples/verilog/circt_{module_name}'
    elif args.backend == 'pyrtl':
        output_dir = f'examples/pyrtl/{module_name}'
    elif args.backend == 'verilog':
        output_dir = f'examples/verilog/{module_name}'
    else:
        output_dir = f'{args.backend}/{module_name}'

    print("=" * 70)
    print(f"J2 (SuperH-2) Processor Generator ({args.backend.upper()} backend)")
    print("=" * 70)
    print(f"\nGenerating J2 processor with {len(instructions)} instructions...")
    print(f"Subset: {args.subset}")
    print(f"Instructions: {', '.join(instructions[:10])}{'...' if len(instructions) > 10 else ''}")

    # Step 1: Parse and merge ISA files
    print("\n" + "=" * 70)
    print("Step 1: Parsing and merging ISA files...")
    print("=" * 70)
    isa_files = {instr: f"isa/j2/{instr}.isa" for instr in instructions}

    try:
        merged_graph = merge_instructions(isa_files)
        print(f"  Successfully merged {len(instructions)} instructions")
        print(f"  Merged graph has {len(merged_graph.nodes)} nodes and {len(merged_graph.edges)} edges")
    except Exception as e:
        print(f"  Error merging instructions: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Step 2: Apply memory transformations
    print("\n" + "=" * 70)
    print("Step 2: Applying memory port width transformation...")
    print("=" * 70)
    apply_memory_transform(merged_graph)

    # Step 2b: Apply read port sharing optimization (optional)
    # This reduces physical read ports by muxing addresses when read enables
    # are mutually exclusive (e.g., instruction enables are one-hot decoded)
    print("\n" + "=" * 70)
    print("Step 2b: Applying read port sharing optimization...")
    print("=" * 70)
    from opt.memory.memory_sharing import share_read_ports_by_enable

    # Share rf_bank read ports - use auto-detect (None) for minimum ports
    # J2 has many rf_bank reads (one per instruction) that are mutually exclusive
    rf_bank_result = share_read_ports_by_enable(merged_graph, 'rf_bank', target_read_ports=None)
    if rf_bank_result['success']:
        print(f"  rf_bank: {rf_bank_result['ports_before']} → {rf_bank_result['ports_after']} ports")

    # Share umem read ports - use auto-detect for minimum
    umem_result = share_read_ports_by_enable(merged_graph, 'umem', target_read_ports=None)
    if umem_result['success']:
        print(f"  umem: {umem_result['ports_before']} → {umem_result['ports_after']} ports")

    # Share rf read ports if available
    rf_result = share_read_ports_by_enable(merged_graph, 'rf', target_read_ports=None)
    if rf_result['success']:
        print(f"  rf: {rf_result['ports_before']} → {rf_result['ports_after']} ports")

    # Step 2.5: Externalize memory if requested
    if args.externalize_memory:
        print("\n" + "=" * 70)
        print("Step 2.5: Externalizing unified memory (umem) with valid-ready handshake...")
        print("=" * 70)

        # NOTE: For externalized memory, variable latency is handled externally
        # via valid-ready handshake. The Verilog generator creates mem_ext_stall
        # based on the handshake signals. We use variable_latency=True to enable
        # the valid-ready protocol for proper SoC integration.
        spec = MemoryExternalizationSpec(
            memory_name='umem',
            create_read_port=True,
            create_write_port=True,
            variable_latency=True  # Use valid-ready handshake protocol
        )
        if apply_memory_externalization(merged_graph, spec):
            print("  Memory externalization successful")
            module_name = module_name + '_extmem'
            # Update output dir to avoid overwriting non-externalized version
            if not args.output_dir:
                output_dir = f'examples/verilog/{module_name}' if args.backend == 'verilog' else f'{args.backend}/{module_name}'
        else:
            print("  Warning: Memory externalization failed, continuing with internal memory")

    # Step 3: Generate RTL
    print("\n" + "=" * 70)
    print(f"Step 3: Generating {args.backend.upper()} RTL and testbench...")
    print("=" * 70)
    print(f"  Output directory: {output_dir}")

    try:
        if args.backend == 'verilog':
            files = generate_verilog(merged_graph, module_name, output_dir)
        elif args.backend == 'vhdl':
            files = generate_vhdl(merged_graph, module_name, output_dir,
                                  verify=not args.no_verify)
        elif args.backend == 'pyrtl':
            files = generate_pyrtl(merged_graph, module_name, output_dir)
        elif args.backend == 'circt':
            files = generate_circt(merged_graph, module_name, output_dir)

        print(f"\n  Generated files:")
        for key, path in files.items():
            if hasattr(path, 'stat'):
                file_size = path.stat().st_size if path.exists() else 0
                print(f"    {key.upper()}: {path} ({file_size:,} bytes)")
            else:
                print(f"    {key.upper()}: {path}")

    except Exception as e:
        print(f"  Error generating {args.backend.upper()}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"  Successfully generated J2 processor ({args.subset} subset)")
    print(f"  {len(instructions)} instructions implemented")
    print(f"  {len(merged_graph.nodes)} nodes in merged graph")
    print(f"  {len(merged_graph.edges)} edges in merged graph")
    print(f"  Backend: {args.backend.upper()}")
    print(f"  Output: {output_dir}/")

    print("\n" + "=" * 70)
    print("Done!")
    print("=" * 70)


if __name__ == "__main__":
    main()
