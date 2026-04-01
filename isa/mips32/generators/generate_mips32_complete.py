#!/usr/bin/env python3
"""
Generate complete MIPS32 processor (excluding atomic ll/sc and mult/div instructions)
This includes all arithmetic, logical, shift, compare, branch, jump, load, and store instructions
from the MIPS Green Sheet Core Instruction Set plus useful extensions.

Supports Verilog, VHDL, PyRTL, and CIRCT backends via --backend argument.
"""
import sys
import os
import argparse

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core.graph_merger import merge_instructions
from backends.verilog import generate_verilog_with_testbench
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec
from opt.memory.memory_externalization import MemoryExternalizationSpec, apply_memory_externalization

# Complete MIPS32 instruction set (39 instructions total)
# Covers MIPS Green Sheet Core Instruction Set (excluding ll/sc)
# Plus: xor, xori, sra, sllv, srlv, srav, jalr, lb, lh
INSTRUCTIONS = [
    # R-type arithmetic (7)
    'add', 'addu', 'sub', 'subu', 'slt', 'sltu', 'nor',

    # R-type logical (3)
    'and', 'or', 'xor',

    # R-type shifts - immediate (3)
    'sll', 'srl', 'sra',

    # R-type shifts - variable (3)
    'sllv', 'srlv', 'srav',

    # I-type arithmetic/logical (8)
    'addi', 'addiu', 'andi', 'ori', 'xori', 'slti', 'sltiu', 'lui',

    # Loads - word and subword (5)
    'lw', 'lh', 'lhu', 'lb', 'lbu',

    # Stores - word and subword (3)
    'sw', 'sh', 'sb',

    # Branches (2)
    'beq', 'bne',

    # Jumps (4)
    'j', 'jal', 'jr', 'jalr',
]

# Test list for MIPS32
MIPS32_TESTS = [
    "add", "addi", "addiu", "addu", "and", "andi", "beq", "bne",
    "j", "jal", "jalr", "jr", "lb", "lbu", "lh", "lhu", "lui", "lw",
    "nor", "or", "ori", "sb", "sh", "sll", "sllv", "slt", "slti",
    "sltiu", "sltu", "sra", "srav", "srl", "srlv", "sub", "subu",
    "sw", "xor", "xori"
]


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
        testbench_config = {
            'timeout_cycles': 10000
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
    """Generate a testbench for a processor with externalized memory.

    This testbench:
    1. Instantiates the processor module
    2. Creates multi-port memory model
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
        # For externalized memory ports, use full 32-bit addresses (not ISA-limited addr_width)
        memory_ports[mem_name]['addr_width'] = mem_info.get('externalized_addr_width', 32)
        memory_ports[mem_name]['use_valid_ready'] = mem_info.get('use_valid_ready', True)
        # Get latency specification from memory node (set by set_memory_variable_latency)
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
    tb.append(f"    // Device Under Test\n")
    tb.append(f"    {module_name} dut (\n")
    tb.append("        .clk(clk),\n")
    tb.append("        .reset(reset),\n")
    tb.append("        .reset_pc_rd(zero32)")

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
    # Note: Single-cycle processors use combinational (same-cycle) response
    # For pipelined processors with stall support, modify MEM_LATENCY > 0
    for mem_name, ports in memory_ports.items():
        data_width = ports['data_width']
        addr_width = ports['addr_width']
        depth = 16384  # 64KB for 32-bit words
        num_bytes = max(1, data_width // 8)
        word_addr_bits = 2 if data_width == 32 else 3  # log2(bytes per word)

        # Get latency from memory specification (set by set_memory_variable_latency)
        min_latency = ports.get('min_latency', 0)
        max_latency = ports.get('max_latency', 0)

        tb.append(f"    // {mem_name} - multi-port memory model\n")
        tb.append(f"    // Latency specification from memory node: min={min_latency}, max={max_latency}\n")
        tb.append(f"    parameter {mem_name.upper()}_MEM_LATENCY = {min_latency};  // 0 = combinational, >0 = N-cycle latency\n")
        tb.append(f"    reg [{data_width-1}:0] {mem_name}_mem [0:{depth-1}];\n\n")

        # Read ports - generate both combinational and pipelined versions
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
            tb.append(f"            // Single-cycle latency (1 clock delay)\n")
            tb.append(f"            reg resp_ready_reg;\n")
            tb.append(f"            reg [{data_width-1}:0] resp_data_reg;\n")
            tb.append(f"            always @(posedge clk) begin\n")
            tb.append(f"                if (reset) begin\n")
            tb.append(f"                    resp_ready_reg <= 0;\n")
            tb.append(f"                end else begin\n")
            tb.append(f"                    resp_ready_reg <= {rp}_read_req_valid;\n")
            tb.append(f"                    if ({rp}_read_req_valid)\n")
            tb.append(f"                        resp_data_reg <= {mem_name}_mem[{rp}_read_req_addr[{addr_width-1}:{word_addr_bits}]];\n")
            tb.append(f"                end\n")
            tb.append(f"            end\n")
            tb.append(f"            assign {rp}_read_resp_data = resp_data_reg;\n")
            if ports['use_valid_ready']:
                tb.append(f"            assign {rp}_read_resp_ready = resp_ready_reg;\n")
            tb.append(f"        end else begin : {rp}_pipe\n")
            tb.append(f"            // Pipelined read with configurable latency (>1 cycle)\n")
            tb.append(f"            // Track addresses through the pipeline to handle address changes correctly\n")
            tb.append(f"            reg [{mem_latency_param}-1:0] pending;\n")
            tb.append(f"            reg [{data_width-1}:0] data_pipe [0:{mem_latency_param}-1];\n")
            tb.append(f"            reg [{addr_width-1}:0] addr_pipe [0:{mem_latency_param}-1];\n")
            tb.append(f"            reg resp_ready_reg;\n")
            tb.append(f"            reg [{data_width-1}:0] resp_data_reg;\n")
            tb.append(f"            always @(posedge clk) begin\n")
            tb.append(f"                if (reset) begin\n")
            tb.append(f"                    pending <= 0;\n")
            tb.append(f"                    resp_ready_reg <= 0;\n")
            tb.append(f"                end else begin\n")
            tb.append(f"                    pending <= {{pending[{mem_latency_param}-2:0], {rp}_read_req_valid}};\n")
            tb.append(f"                    if ({rp}_read_req_valid) begin\n")
            tb.append(f"                        data_pipe[0] <= {mem_name}_mem[{rp}_read_req_addr[{addr_width-1}:{word_addr_bits}]];\n")
            tb.append(f"                        addr_pipe[0] <= {rp}_read_req_addr;\n")
            tb.append(f"                    end\n")
            tb.append(f"                    for (integer j = 1; j < {mem_latency_param}; j = j + 1) begin\n")
            tb.append(f"                        data_pipe[j] <= data_pipe[j-1];\n")
            tb.append(f"                        addr_pipe[j] <= addr_pipe[j-1];\n")
            tb.append(f"                    end\n")
            tb.append(f"                    // Only signal ready when the address matches (for correct multi-cycle stalling)\n")
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
    tb.append("    always #5 clk = ~clk;\n\n")

    tb.append("    initial begin\n")
    tb.append("        clk = 0; reset = 1;\n")
    tb.append("        if (!$value$plusargs(\"pass_addr=%h\", pass_addr)) pass_addr = 32'hFFFFFFFF;\n")
    tb.append("        if (!$value$plusargs(\"fail_addr=%h\", fail_addr)) fail_addr = 32'hFFFFFFFE;\n")

    if ext_memories:
        mem_name = ext_memories[0]
        tb.append(f"        $readmemh(\"{mem_name}.hex\", {mem_name}_mem);\n")

    tb.append("        repeat(3) @(posedge clk);\n")
    tb.append("        reset = 0;\n")
    tb.append("        for (i = 0; i < 10000; i = i + 1) begin\n")
    tb.append("            @(posedge clk);\n")
    tb.append("            if (dut.pc_rd == pass_addr) begin $display(\"TEST PASSED\"); $finish; end\n")
    tb.append("            if (dut.pc_rd == fail_addr) begin $display(\"TEST FAILED at pc=%h testnum=%d\", dut.pc_rd, dut.rf[28]); $finish; end\n")
    tb.append("        end\n")
    tb.append("        $display(\"TIMEOUT\");\n")
    tb.append("        $finish;\n")
    tb.append("    end\n")
    tb.append("endmodule\n")

    return "".join(tb)


def generate_vhdl(merged_graph, entity_name, output_dir, verify=True):
    """Generate VHDL output."""
    from backends.vhdl import generate_vhdl_with_testbench, VHDLTestbenchConfig
    from backends.vhdl.test_generator import generate_vhdl_test_runner_tb, generate_vhdl_test_script
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
        debug_outputs=['pc_rd']
    )

    # Generate test runner testbench and script
    vhdl_file = str(files['rtl'])
    test_runner_tb = generate_vhdl_test_runner_tb(
        vhdl_file, entity_name, output_dir,
        pc_width=32, is_pipelined=False
    )
    test_script = generate_vhdl_test_script(
        entity_name, output_dir,
        arch="MIPS32",
        tests=MIPS32_TESTS,
        test_base_path="../../isa/mips32/mips-tests/isa/mips32-isacomp-",
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
        arch='mips32'
    )

    # Generate testbench files with instructions list for test runner
    output_path = Path(output_dir)
    files = generate_pyrtl_testbench_files(
        pyrtl_block,
        module_name=module_name,
        output_dir=output_path,
        config=config,
        instructions=INSTRUCTIONS,
        arch='mips32'
    )

    # Also output the PyRTL block as Verilog for debugging and synthesis compatibility
    verilog_file = output_path / f"{module_name}.v"
    with open(verilog_file, 'w') as f:
        pyrtl.output_to_verilog(f, block=pyrtl_block)
    files['verilog'] = verilog_file

    print(f"  PyRTL block contains:")
    print(f"    {len(list(pyrtl_block.logic))} logic operations")
    print(f"    {len(list(pyrtl_block.wirevector_set))} wires")
    print(f"    {len(pyrtl_block.memblock_by_name)} memories")

    return files


def generate_circt(merged_graph, module_name, output_dir):
    """Generate CIRCT MLIR output and convert to SystemVerilog."""
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

    # Convert to SystemVerilog using firtool
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

                # Fix umem: reg [N:0][31:0] umem -> reg [31:0] umem [0:N]
                content = re.sub(
                    r'reg\s+\[(\d+):0\]\[(\d+):0\]\s+umem;',
                    r'reg [\2:0] umem [0:\1];',
                    content
                )

                with open(sv_file, 'w') as f:
                    f.write(content)
                print("  Post-processed for Verilator compatibility")

                # Generate testbench and test runner
                tb_files = generate_circt_testbench(
                    str(sv_file),
                    module_name,
                    'mips32',
                    INSTRUCTIONS
                )
                files.update(tb_files)
                print(f"  Generated testbench: {tb_files.get('testbench')}")
                print(f"  Generated test runner: {tb_files.get('test_runner')}")
            else:
                print(f"  firtool failed: {result.stderr[:200]}")
        except subprocess.TimeoutExpired:
            print("  firtool timed out")
        except Exception as e:
            print(f"  firtool error: {e}")

    return files


def main():
    parser = argparse.ArgumentParser(
        description='Generate complete MIPS32 processor from ISA definitions'
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
        help='Output directory (default: <backend>/mips32_complete)'
    )
    parser.add_argument(
        '--externalize-memory',
        action='store_true',
        help='Externalize unified memory (umem) with valid-ready handshake ports'
    )
    parser.add_argument(
        '--delay-slot',
        action='store_true',
        help='Enable branch delay slot support (defines DELAY_SLOT preprocessor macro)'
    )
    args = parser.parse_args()

    module_name = 'mips32_complete'
    if args.output_dir:
        output_dir = args.output_dir
    elif args.backend == 'circt':
        output_dir = 'examples/verilog/circt_mips32'
    elif args.backend == 'vhdl':
        output_dir = 'examples/vhdl/mips32_complete'
    elif args.backend == 'pyrtl':
        output_dir = 'examples/pyrtl/mips32_complete'
    else:
        output_dir = 'examples/verilog/mips32_complete'

    print("=" * 70)
    print(f"MIPS32 COMPLETE PROCESSOR GENERATOR ({args.backend.upper()} backend)")
    print("=" * 70)
    print(f"\nGenerating MIPS32 processor with {len(INSTRUCTIONS)} instructions...")
    print(f"Instructions: {', '.join(INSTRUCTIONS)}")

    print("\n" + "=" * 70)
    print("PARSING AND MERGING ISA FILES")
    print("=" * 70)
    isa_files = {instr: f"isa/mips32/{instr}.isa" for instr in INSTRUCTIONS}

    # Set up preprocessor defines
    defines = {}
    if args.delay_slot:
        defines['DELAY_SLOT'] = '1'
        print(f"Delay slot support: ENABLED")
    else:
        print(f"Delay slot support: disabled")

    print(f"\nMerging {len(INSTRUCTIONS)} ISA specifications...")
    merged_graph = merge_instructions(isa_files, defines=defines if defines else None)
    print(f"✓ Merged graph has {len(merged_graph.nodes)} nodes and {len(merged_graph.edges)} edges")

    # Apply port width setting for word-addressed unified memory
    # This creates byte selection mux nodes for sub-word accesses (lb, lbu, lh, lhu, sb, sh)
    print("\nApplying memory port width transformation for umem...")
    umem_node = merged_graph.nodes.get('umem')
    if umem_node:
        access_widths = umem_node.data.get('access_widths', [32])
        max_width = max(access_widths) if access_widths else 32
        print(f"  umem access widths: {access_widths}, max: {max_width}")

        # Apply set_port_width transformation to create byte selection mux nodes
        transform = MemoryAccessTransform(merged_graph)
        spec = MemoryAccessTransformSpec(
            memory='umem',
            strategy='set_port_width',
            current_width=max_width,
            target_width=32,  # Word-addressed memory
            direction='forward'
        )
        result = transform.apply_transformation(spec)
        if result.get('transformed'):
            print(f"  Transformed: added {len(result.get('nodes_added', []))} byte mux nodes")
        else:
            print(f"  Skipped: {result.get('reason', 'unknown')}")

    # Apply memory externalization if requested
    if args.externalize_memory:
        print("\n" + "=" * 70)
        print("Applying memory externalization...")
        print("=" * 70)

        # NOTE: For externalized memory, variable latency is handled externally
        # via valid-ready handshake. The Verilog generator creates mem_ext_stall
        # based on the handshake signals. We do NOT use set_memory_variable_latency
        # here because that creates internal latency counters, which conflicts
        # with the external handshake approach.
        #
        # The pipeline approach (create_rv32i_pipeline.py) uses set_memory_variable_latency
        # for INTERNAL memories with simulated variable latency (like cache miss modeling).
        # For EXTERNALIZED memory, the SoC/testbench handles the latency externally.

        spec = MemoryExternalizationSpec(
            memory_name='umem',
            create_read_port=True,
            create_write_port=True,
            variable_latency=True  # Use valid-ready handshake protocol
        )
        if apply_memory_externalization(merged_graph, spec):
            print("  Memory externalization applied successfully")
            # Update output dir to avoid overwriting non-externalized version
            if not args.output_dir:
                output_dir = f'examples/verilog/mips32_complete_ext' if args.backend == 'verilog' else f'{args.backend}/mips32_complete_ext'

            # Note: ISA state gating for single-cycle machines is handled by the
            # Verilog generator via mem_ext_stall signal. The generator creates
            # pending trackers and gates all state updates with !mem_ext_stall.
            # No additional graph-level gating is needed.
        else:
            print("  Warning: Memory externalization failed")

    print("\n" + "=" * 70)
    print(f"GENERATING {args.backend.upper()}")
    print("=" * 70)
    print(f"\nOutput directory: {output_dir}/")

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

        print("\n" + "=" * 70)
        print("GENERATION COMPLETE")
        print("=" * 70)
        print("\nGenerated files:")
        for key, path in files.items():
            if hasattr(path, 'stat'):
                file_size = path.stat().st_size if path.exists() else 0
                print(f"  {key.upper()}: {path} ({file_size:,} bytes)")
            else:
                print(f"  {key.upper()}: {path}")

    except Exception as e:
        print(f"  Error generating {args.backend.upper()}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print(f"\n✓ Successfully generated MIPS32 processor with {len(INSTRUCTIONS)} instructions!")
    print(f"  Backend: {args.backend.upper()}")
    print("\nNote: This is a non-pipelined (single-cycle) implementation.")
    print("For pipelined versions, use create_mips32_pipeline.py")


if __name__ == "__main__":
    main()
