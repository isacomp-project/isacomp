#!/usr/bin/env python3
"""
Generate complete RV32I processor (excluding system/CSR instructions)
This includes all arithmetic, logical, shift, compare, branch, jump, load, and store instructions.

Supports Verilog, VHDL, PyRTL, and CIRCT backends via --backend argument.
Supports --engine python (default) or --engine rust to use the Rust isacomp_core backend.
"""
import sys
import os
import argparse

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

# Engine selection — set by main() before use.
# When engine='rust', these point to isacomp_core equivalents.
_engine = 'python'

def _init_engine(engine):
    """Initialize the engine-specific imports."""
    global _engine, merge_instructions, MemoryAccessTransform, MemoryAccessTransformSpec
    global MemoryExternalizationSpec, apply_memory_externalization
    _engine = engine

    if engine == 'rust':
        try:
            import isacomp_core as _rc
        except ImportError:
            print("Error: isacomp_core not found. Build it with:")
            print("  cd rust_core && maturin develop")
            sys.exit(1)

        merge_instructions = _rc.merge_instructions

        # Wrap the Rust MemoryAccessTransform to match Python's in-place API.
        # The Rust binding takes ownership of the graph, so we need an adapter
        # that mutates the graph object after the transform.
        class _RustMemoryAccessTransformSpec:
            """Thin wrapper matching Python MemoryAccessTransformSpec kwargs API."""
            def __init__(self, memory, strategy, current_width, target_width, direction='forward', **kwargs):
                self._inner = _rc.MemoryAccessTransformSpec(
                    memory, strategy, current_width, target_width, direction
                )
                self.memory = memory
                self.strategy = strategy
                self.current_width = current_width
                self.target_width = target_width
                self.direction = direction
                self.endianness = kwargs.get('endianness', 'little')
                self.alignment = kwargs.get('alignment', 'port_width')

        class _RustMemoryAccessTransform:
            """Adapter that applies Rust transform and updates the graph in-place."""
            def __init__(self, graph):
                self._graph = graph

            def apply_transformation(self, spec, dry_run=False):
                inner_spec = spec._inner if hasattr(spec, '_inner') else spec
                transform = _rc.MemoryAccessTransform(self._graph)
                result = transform.apply_transformation(inner_spec, dry_run)
                # Replace the graph contents with the transformed version
                updated = transform.get_graph()
                # Swap internals — the caller's reference to self._graph
                # won't see changes, but we return the updated graph in result
                # for the caller to use.
                result['graph'] = updated
                return result

        MemoryAccessTransformSpec = _RustMemoryAccessTransformSpec
        MemoryAccessTransform = _RustMemoryAccessTransform
        apply_memory_externalization = _rc.apply_memory_externalization

        # Wrap VerilogGenerator for use by generate_verilog()
        _rc._VerilogGenerator = _rc.VerilogGenerator

        print(f"  Using Rust engine (isacomp_core)")
    else:
        from core.graph_merger import merge_instructions as _mi
        from opt.memory.memory_access_transform import MemoryAccessTransform as _mat, MemoryAccessTransformSpec as _mats
        from opt.memory.memory_externalization import MemoryExternalizationSpec as _mes, apply_memory_externalization as _ame

        merge_instructions = _mi
        MemoryAccessTransform = _mat
        MemoryAccessTransformSpec = _mats
        MemoryExternalizationSpec = _mes
        apply_memory_externalization = _ame

        print(f"  Using Python engine")

from backends.vhdl.test_generator import generate_vhdl_test_runner_tb, generate_vhdl_test_script

# Test list for RV32I
RV32I_TESTS = [
    "add", "addi", "and", "andi", "auipc", "beq", "bge", "bgeu", "blt", "bltu",
    "bne", "jal", "jalr", "lb", "lbu", "lh", "lhu", "lui", "lw", "or", "ori",
    "sb", "sh", "sll", "slli", "slt", "slti", "sltiu", "sltu", "sra", "srai",
    "srl", "srli", "sub", "sw", "xor", "xori"
]

# Complete RV32I instruction set (37 instructions total, excluding system/CSR)
INSTRUCTIONS = [
    # Arithmetic (5)
    'add', 'addi', 'sub', 'lui', 'auipc',

    # Logical (6)
    'and', 'andi', 'or', 'ori', 'xor', 'xori',

    # Shifts (6)
    'sll', 'slli', 'srl', 'srli', 'sra', 'srai',

    # Compare (4)
    'slt', 'slti', 'sltu', 'sltiu',

    # Branches (6)
    'beq', 'bne', 'blt', 'bltu', 'bge', 'bgeu',

    # Jumps (2)
    'jal', 'jalr',

    # Loads (5)
    'lw', 'lh', 'lhu', 'lb', 'lbu',

    # Stores (3)
    'sw', 'sh', 'sb',
]


def apply_memory_transform(merged_graph):
    """Apply port width setting for word-addressed unified memory.

    Returns the (possibly new) graph object — needed for Rust engine which
    returns a new graph rather than mutating in place.
    """
    # Support both legacy 'dmem' and unified 'umem' naming
    nodes = merged_graph.nodes
    umem_node = nodes.get('umem')
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

        # Rust engine returns the graph in the result since it can't mutate in place
        if 'graph' in result:
            return result['graph']

    return merged_graph


def generate_verilog(merged_graph, module_name, output_dir, externalized=False):
    """Generate Verilog output."""
    from pathlib import Path

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Generate RTL — use Rust or Python VerilogGenerator based on engine
    if _engine == 'rust':
        import isacomp_core
        generator = isacomp_core.VerilogGenerator(merged_graph, module_name)
        verilog_code = generator.generate()

        rtl_file = output_path / f"{module_name}.v"
        rtl_file.write_text(verilog_code)
        files = {'rtl': rtl_file}

        # Rust engine doesn't support memory externalization yet — skip
        # testbench generation that depends on Python backends.
        print(f"  Generated RTL: {rtl_file} ({len(verilog_code)} bytes, {verilog_code.count(chr(10))} lines)")
        return files

    from backends.verilog import VerilogGenerator
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
    2. Instantiates external memory modules
    3. Connects the external memory ports
    4. Loads test programs via $readmemh into external memory
    """
    from pathlib import Path

    # Collect information about externalized memory ports
    ext_memories = list(generator.externalized_memories)
    if not ext_memories:
        return ""

    # For RV32I, we expect 'umem' with potentially multiple read ports (pc, ea)
    # The generator tracks these in memory_read_ports and memory_write_ports

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

    # Load memory - use the first externalized memory name
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
        arch="RISC-V 32-bit",
        tests=RV32I_TESTS,
        test_base_path="../riscv-tests/isa/rv32ui-isacomp-",
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
        arch='riscv32'
    )

    # Generate testbench files with instructions list for test runner
    output_path = Path(output_dir)
    files = generate_pyrtl_testbench_files(
        pyrtl_block,
        module_name=module_name,
        output_dir=output_path,
        config=config,
        instructions=INSTRUCTIONS,
        arch='riscv32'
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


def generate_hardcaml(merged_graph, module_name, output_dir):
    """Generate HardCaml (OCaml) output with dune build files."""
    from pathlib import Path
    from backends.hardcaml import generate_hardcaml as gen_hardcaml

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Generate OCaml source
    ocaml_code = gen_hardcaml(merged_graph, module_name)
    ml_file = output_path / f"{module_name}.ml"
    ml_file.write_text(ocaml_code)

    files = {'ocaml': ml_file}
    print(f"  Generated OCaml: {ml_file} ({len(ocaml_code):,} bytes)")

    # Generate dune build file
    dune_file = output_path / "dune"
    dune_content = f"""(executable
 (name {module_name})
 (libraries hardcaml))
"""
    dune_file.write_text(dune_content)
    files['dune'] = dune_file

    # Generate dune-project file
    dune_project = output_path / "dune-project"
    dune_project.write_text("(lang dune 3.0)\n")
    files['dune_project'] = dune_project

    print(f"  Generated dune build files")

    # Try to compile and produce Verilog
    import subprocess
    import shutil

    ocaml_switch = os.environ.get('OCAML_SWITCH', '4.14.1')
    opam_env = {}
    try:
        env_result = subprocess.run(
            ["opam", "env", f"--switch={ocaml_switch}", "--set-switch"],
            capture_output=True, text=True, timeout=10
        )
        if env_result.returncode == 0:
            for line in env_result.stdout.strip().split('\n'):
                # Parse: VAR=value; export VAR;
                if '=' in line and 'export' in line:
                    var_part = line.split(';')[0]
                    key, val = var_part.split('=', 1)
                    opam_env[key.strip()] = val.strip().strip("'\"")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # opam not installed or not responding; fall back to default environment
        pass

    build_env = os.environ.copy()
    build_env.update(opam_env)

    # Build with dune
    try:
        result = subprocess.run(
            ["dune", "build"],
            capture_output=True, text=True, timeout=120,
            cwd=str(output_path), env=build_env
        )
        if result.returncode == 0:
            print("  OCaml compilation successful!")

            # Run to produce Verilog
            exe_path = output_path / f"_build/default/{module_name}.exe"
            if not exe_path.exists():
                # Try alternate location
                exe_path = output_path / f"./_build/default/{module_name}.exe"

            run_result = subprocess.run(
                ["dune", "exec", f"./{module_name}.exe"],
                capture_output=True, text=True, timeout=60,
                cwd=str(output_path), env=build_env
            )
            if run_result.returncode == 0:
                v_file = output_path / f"{module_name}.v"
                v_file.write_text(run_result.stdout)
                files['verilog'] = v_file
                print(f"  Generated Verilog via HardCaml: {v_file} ({len(run_result.stdout):,} bytes)")
            else:
                print(f"  HardCaml execution failed:")
                print(f"    {run_result.stderr[:1000]}")
        else:
            print(f"  OCaml compilation failed:")
            print(f"    {result.stderr[:1000]}")
    except FileNotFoundError:
        print("  dune not found in PATH, skipping compilation")
    except subprocess.TimeoutExpired:
        print("  Build timed out")
    except Exception as e:
        print(f"  Error during build: {e}")

    return files


def generate_chisel_output(merged_graph, module_name, output_dir):
    """Generate Chisel (Scala) output, compile to Verilog, and create testbench."""
    from pathlib import Path
    from backends.chisel import generate_chisel as gen_chisel
    from backends.chisel.toolchain import (
        find_jars, download_jars, compile_scala, emit_firrtl, firrtl_to_verilog,
    )

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Create src/main/scala directory structure for sbt
    scala_dir = output_path / "src" / "main" / "scala"
    scala_dir.mkdir(parents=True, exist_ok=True)

    # Generate Chisel Scala source
    scala_code = gen_chisel(merged_graph, module_name)
    class_name = ''.join(p.capitalize() for p in module_name.replace('-', '_').split('_'))
    scala_file = scala_dir / f"{class_name}.scala"
    scala_file.write_text(scala_code)

    files = {'scala': scala_file}
    print(f"  Generated Scala: {scala_file} ({len(scala_code):,} bytes)")

    # Generate build.sbt (for users who prefer sbt)
    build_sbt = output_path / "build.sbt"
    build_sbt_content = f"""// Build configuration for ISAComp Chisel backend
ThisBuild / scalaVersion := "2.13.14"

lazy val root = (project in file("."))
  .settings(
    name := "{module_name}",
    libraryDependencies ++= Seq(
      "org.chipsalliance" %% "chisel" % "6.6.0",
    ),
    scalacOptions ++= Seq(
      "-language:reflectiveCalls",
      "-deprecation",
      "-feature",
      "-Xcheckinit",
    ),
    addCompilerPlugin("org.chipsalliance" % "chisel-plugin" % "6.6.0" cross CrossVersion.full),
  )
"""
    build_sbt.write_text(build_sbt_content)
    files['build_sbt'] = build_sbt

    project_dir = output_path / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    build_props = project_dir / "build.properties"
    build_props.write_text("sbt.version=1.10.7\n")
    files['build_properties'] = build_props

    print(f"  Generated sbt build files")

    # --- Compile pipeline: Scala -> FIRRTL -> Verilog ---
    import shutil

    # Step 1: Find or download Chisel dependency JARs
    jar_dir = find_jars()
    if not jar_dir:
        print("  Chisel JARs not found, downloading from Maven Central...")
        jar_dir = download_jars(Path.home() / '.cache' / 'isacomp' / 'chisel_deps')

    if not list(jar_dir.glob('*.jar')):
        print("  ERROR: No Chisel JARs available, cannot compile")
        return files

    # Step 2: Compile Scala with scalac + Chisel plugin
    classes_dir = output_path / "classes"
    try:
        print("  Compiling Scala with scalac...")
        compile_scala(scala_file, class_name, jar_dir, classes_dir)
        print("  Scala compilation successful")
    except Exception as e:
        print(f"  ERROR: Scala compilation failed: {e}")
        return files

    # Step 3: Emit FIRRTL
    firrtl_dir = output_path / "generated"
    try:
        emit_firrtl(class_name, jar_dir, classes_dir, firrtl_dir)
        firrtl_file = firrtl_dir / f"{class_name}.fir"
        files['firrtl'] = firrtl_file
    except Exception as e:
        print(f"  ERROR: FIRRTL emission failed: {e}")
        return files

    # Step 4: Convert FIRRTL to Verilog via firtool
    verilog_file = output_path / f"{module_name}.v"
    try:
        print("  Converting FIRRTL to Verilog via firtool...")
        firrtl_to_verilog(firrtl_file, verilog_file)
        files['verilog'] = verilog_file
        v_size = verilog_file.stat().st_size
        print(f"  Generated Verilog: {verilog_file} ({v_size:,} bytes)")
    except Exception as e:
        print(f"  ERROR: firtool conversion failed: {e}")
        return files

    # Step 5: Generate testbench
    tb_file = output_path / "simple_tb.sv"
    _generate_chisel_testbench(tb_file, module_name, class_name)
    files['testbench'] = tb_file
    print(f"  Generated testbench: {tb_file}")

    # Step 6: Generate test runner script
    runner_file = output_path / "run_all_tests.sh"
    _generate_chisel_test_runner(runner_file, module_name)
    files['test_runner'] = runner_file
    print(f"  Generated test runner: {runner_file}")

    return files


def generate_rtlil(merged_graph, module_name, output_dir):
    """Generate RTLIL output, convert to CXXRTL C++, and generate testbench."""
    import shutil
    from pathlib import Path
    from backends.rtlil import (
        RTLILGenerator, rtlil_to_cxxrtl, rtlil_to_verilog,
        CXXRTLTestbenchConfig, generate_cxxrtl_testbench,
    )

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Generate RTLIL
    generator = RTLILGenerator(merged_graph, module_name)
    rtlil_code = generator.generate()

    il_file = output_path / f"{module_name}.il"
    il_file.write_text(rtlil_code)

    files = {'rtlil': il_file}
    print(f"  Generated RTLIL: {il_file} ({len(rtlil_code):,} bytes)")

    # Try to convert to CXXRTL C++ via Yosys
    yosys_path = shutil.which('yosys')
    if yosys_path:
        cc_file = output_path / f"{module_name}.cc"
        try:
            rtlil_to_cxxrtl(str(il_file), str(cc_file))
            files['cxxrtl'] = cc_file
            print(f"  Generated CXXRTL C++: {cc_file}")
        except Exception as e:
            print(f"  CXXRTL conversion failed: {e}")

        # Also generate Verilog via Yosys for inspection
        v_file = output_path / f"{module_name}_from_rtlil.v"
        try:
            rtlil_to_verilog(str(il_file), str(v_file))
            files['verilog'] = v_file
            print(f"  Generated Verilog (via Yosys): {v_file}")
        except Exception as e:
            print(f"  Verilog conversion failed: {e}")
    else:
        print("  Yosys not found in PATH, skipping CXXRTL/Verilog conversion")

    # Generate CXXRTL testbench (graph-dependent)
    tb_config = CXXRTLTestbenchConfig(module_name=module_name)
    tb_files = generate_cxxrtl_testbench(merged_graph, tb_config, output_dir)
    files.update(tb_files)
    print(f"  Generated testbench: {tb_files['testbench']}")

    # Test scripts (run_all_tests.sh, compile_*.sh) are canonical templates
    # already present in the backends/rtlil/riscv32i_complete/ directory.

    return files


def _generate_chisel_testbench(tb_file, module_name, class_name, pipelined=False,
                               num_stages=5, verilog_path=None):
    """Generate a SystemVerilog testbench for the Chisel-generated Verilog.

    firtool generates separate memory modules (e.g., umem_8192x32) instantiated
    as umem_ext in the main module. The memory array is at dut.umem_ext.Memory.
    The register file is at dut.rf_ext.Memory.

    For pipelined designs, pass/fail is detected using the Execute-stage PC
    with valid gating (to avoid false triggers from speculative fetches).

    The signal names vary by pipeline configuration:
      5-stage: pIPE_Execute_PIPE_Decode_pc_rd_PIPE_PIPE / pIPE_Execute_valid_PIPE
      4-stage: same as 5-stage (Execute stage exists)
      3-stage: pIPE_ExecuteMemoryWriteback_PIPE_Decode_pc_rd_PIPE_PIPE / ...valid_PIPE
      2-stage: pIPE_ExecuteMemoryWriteback_PIPE_FetchDecode_pc_rd_PIPE_PIPE / ...valid_PIPE

    If verilog_path is provided, signal names are auto-detected from the generated Verilog.
    """
    from pathlib import Path

    if pipelined:
        # Try auto-detecting signal names from generated Verilog
        exec_pc_sig = None
        exec_valid_sig = None

        if verilog_path and Path(verilog_path).exists():
            import re
            verilog_text = Path(verilog_path).read_text()
            # Find the deepest pc_rd pipeline register (most _PIPE suffixes)
            pc_matches = re.findall(r'\b(pIPE_\w*pc_rd\w*PIPE\w*)\b', verilog_text)
            if pc_matches:
                best = max(set(pc_matches), key=lambda s: s.count('_PIPE'))
                exec_pc_sig = best
            # Find the valid signal for the execute-equivalent stage
            valid_matches = re.findall(r'\b(pIPE_\w+_valid_PIPE)\b', verilog_text)
            if valid_matches:
                # Prefer Execute, then ExecuteMemoryWriteback
                for candidate in sorted(set(valid_matches)):
                    if 'Execute' in candidate:
                        exec_valid_sig = candidate
                        break
                if not exec_valid_sig and valid_matches:
                    exec_valid_sig = sorted(set(valid_matches))[0]

        # Fall back to construction from num_stages
        if not exec_pc_sig or not exec_valid_sig:
            # The execute-equivalent stage (where branches resolve)
            if num_stages >= 4:
                exec_stage = "Execute"
                decode_stage = "Decode"
            elif num_stages == 3:
                exec_stage = "ExecuteMemoryWriteback"
                decode_stage = "Decode"
            else:  # 2-stage
                exec_stage = "ExecuteMemoryWriteback"
                decode_stage = "FetchDecode"

            if not exec_pc_sig:
                exec_pc_sig = f"pIPE_{exec_stage}_PIPE_{decode_stage}_pc_rd_PIPE_PIPE"
            if not exec_valid_sig:
                exec_valid_sig = f"pIPE_{exec_stage}_valid_PIPE"

        pass_fail_check = f"""\
    wire [31:0] exec_pc = dut.{exec_pc_sig};
    wire exec_valid = dut.{exec_valid_sig};
    wire exec_at_pass = exec_valid && (exec_pc == pass_addr);
    wire exec_at_fail = exec_valid && (exec_pc == fail_addr);"""
        pass_cond = "exec_at_pass"
        fail_cond = "exec_at_fail"
    else:
        # Single-cycle: check fetch PC directly
        pass_fail_check = ""
        pass_cond = "dut.pc == pass_addr"
        fail_cond = "dut.pc == fail_addr"

    tb = f"""`timescale 1ns/1ps
module simple_tb;
    reg clk, reset_s;

    {class_name} dut (
        .clock(clk),
        .reset(reset_s),
        .io_pc_out()
    );

    reg [31:0] pass_addr, fail_addr;
    integer i;
    always #5 clk = ~clk;
{pass_fail_check}

    initial begin
        clk = 0; reset_s = 1;
        if (!$value$plusargs("pass_addr=%h", pass_addr)) pass_addr = 32'hFFFFFFFF;
        if (!$value$plusargs("fail_addr=%h", fail_addr)) fail_addr = 32'hFFFFFFFE;
        // firtool generates memory as a separate module instantiated as umem_ext
        $readmemh("umem.hex", dut.umem_ext.Memory);
        // Initialize register file (firtool extracts Mem to separate module)
        for (i = 0; i < 32; i = i + 1) dut.rf_ext.Memory[i] = 32'h0;
        repeat(3) @(posedge clk);
        reset_s = 0;
        for (i = 0; i < 10000; i = i + 1) begin
            @(posedge clk);
            if ({pass_cond}) begin $display("TEST PASSED"); $finish; end
            if ({fail_cond}) begin
                $display("TEST FAILED at pc=%h testnum=%d", dut.pc, dut.rf_ext.Memory[3]);
                $finish;
            end
        end
        $display("TIMEOUT");
        $finish;
    end
endmodule
"""
    tb_file.write_text(tb)


def _generate_chisel_test_runner(runner_file, module_name):
    """Generate a test runner script for riscv-tests."""
    script = f"""#!/bin/bash
# Test all RV32I instructions using Chisel-generated Verilog
# Usage: ./run_all_tests.sh

SIMULATOR=${{SIMULATOR:-iverilog}}

echo "Compiling Chisel-generated Verilog testbench with $SIMULATOR..."

if [ "$SIMULATOR" = "verilator" ]; then
    if [ ! -f "test_simple" ] || [ "{module_name}.v" -nt "test_simple" ] || [ "simple_tb.sv" -nt "test_simple" ]; then
        verilator --timing --exe --binary \\
            -Wno-fatal -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-TIMESCALEMOD \\
            -o test_simple {module_name}.v simple_tb.sv
        if [ $? -ne 0 ]; then echo "ERROR: Verilator compilation failed!"; exit 1; fi
        # Move binary from obj_dir and ensure it exists
        if ! mv obj_dir/test_simple . 2>/dev/null; then
            echo "ERROR: Failed to move Verilator sim binary from obj_dir/test_simple"
            exit 1
        fi
        if [ ! -x "./test_simple" ]; then
            echo "ERROR: Verilator sim binary './test_simple' not found or not executable"
            exit 1
        fi
    fi
    TEST_CMD="./test_simple"
else
    if [ ! -f "test_simple" ] || [ "{module_name}.v" -nt "test_simple" ] || [ "simple_tb.sv" -nt "test_simple" ]; then
        iverilog -g2012 -DSYNTHESIS -o test_simple {module_name}.v simple_tb.sv
        if [ $? -ne 0 ]; then echo "ERROR: Icarus Verilog compilation failed!"; exit 1; fi
    fi
    TEST_CMD="vvp test_simple"
fi

TESTS="add addi sub lui auipc and andi or ori xor xori sll slli srl srli sra srai slt slti sltu sltiu beq bne blt bltu bge bgeu jal jalr lw lh lhu lb lbu sw sh sb"

PASS=0
FAIL=0
SKIP=0

for test in $TESTS; do
    echo -n "Testing $test... "

    TEST_BASE="../riscv-tests/isa/rv32ui-isacomp-$test"

    if [ ! -f "$TEST_BASE.hex" ]; then
        echo "SKIP (no hex file)"
        SKIP=$((SKIP + 1))
        continue
    fi

    if [ ! -f "$TEST_BASE.addrs" ]; then
        echo "SKIP (no addrs file)"
        SKIP=$((SKIP + 1))
        continue
    fi

    read PASS_ADDR FAIL_ADDR < "$TEST_BASE.addrs"

    python3 -c "
import sys
data = {{}}
with open('$TEST_BASE.hex', 'r') as f:
    for line in f:
        line = line.strip()
        if not line.startswith(':'):
            continue
        byte_count = int(line[1:3], 16)
        address = int(line[3:7], 16)
        record_type = int(line[7:9], 16)
        if record_type == 0:
            for i in range(byte_count):
                byte_val = int(line[9+i*2:11+i*2], 16)
                data[address + i] = byte_val
        elif record_type == 1:
            break
if not data:
    sys.exit(1)
max_addr = max(data.keys())
max_word = (max_addr // 4) + 1
with open('umem.hex', 'w') as f:
    for word_idx in range(max(1024, max_word)):
        word = 0
        for byte_offset in range(4):
            addr = word_idx * 4 + byte_offset
            if addr in data:
                word |= data[addr] << (byte_offset * 8)
        f.write(f'{{word:08x}}\\n')
"

    RESULT=$(timeout 5 $TEST_CMD +pass_addr=$PASS_ADDR +fail_addr=$FAIL_ADDR 2>&1)
    EXIT_CODE=$?

    if echo "$RESULT" | grep -q "TEST PASSED"; then
        echo "PASS"
        PASS=$((PASS + 1))
    elif echo "$RESULT" | grep -q "TEST FAILED"; then
        echo "FAIL"
        FAIL=$((FAIL + 1))
    elif [ $EXIT_CODE -eq 124 ]; then
        echo "TIMEOUT"
        FAIL=$((FAIL + 1))
    else
        echo "ERROR"
        FAIL=$((FAIL + 1))
    fi
done

echo ""
echo "================================"
echo "Results: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
echo "================================"

if [ $FAIL -gt 0 ]; then
    echo "FAILED: $FAIL test(s) failed"
    exit 1
fi

if [ $PASS -eq 0 ]; then
    echo "FAILED: No tests passed (all skipped)"
    exit 1
fi

echo "SUCCESS: All $PASS tests passed"
exit 0
"""
    runner_file.write_text(script)
    runner_file.chmod(0o755)


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

                # Fix imem: reg [N:0][31:0] imem -> reg [31:0] imem [0:N]
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
                    'riscv32',
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


def generate_clash(merged_graph, module_name, output_dir):
    """Generate Clash HDL output with testbench files."""
    from pathlib import Path
    from backends.clash import generate_clash_pipeline as gen_clash_code, generate_clash_testbench

    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Generate Clash code using graph-traversing generator
    clash_code = gen_clash_code(merged_graph, module_name)

    # Write Clash file
    clash_file = output_path / f'{module_name.capitalize()}.hs'
    with open(clash_file, 'w') as f:
        f.write(clash_code)

    files = {'clash': str(clash_file)}
    print(f"  Generated Clash: {clash_file} ({len(clash_code)} bytes)")

    # Generate testbench files
    tb_files = generate_clash_testbench(
        str(clash_file),
        module_name.capitalize(),
        'riscv32',
        INSTRUCTIONS,
        str(output_path)
    )
    files.update(tb_files)
    for name, path in tb_files.items():
        print(f"  Copied {name} -> {path}")

    return files


def main():
    parser = argparse.ArgumentParser(
        description='Generate complete RV32I processor from ISA definitions'
    )
    parser.add_argument(
        '--backend', '-b',
        choices=['verilog', 'vhdl', 'pyrtl', 'circt', 'clash', 'hardcaml', 'chisel', 'rtlil'],
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
        help='Output directory (default: <backend>/riscv32i_complete)'
    )
    parser.add_argument(
        '--externalize-memory',
        action='store_true',
        help='Externalize unified memory (umem) with valid-ready handshake ports'
    )
    parser.add_argument(
        '--engine', '-e',
        choices=['python', 'rust'],
        default='python',
        help='Backend engine: python (default) or rust (uses isacomp_core)'
    )
    parser.add_argument(
        '--alu-spec',
        metavar='FILE',
        help='ALU specification file (.spec) to apply ALU integration'
    )
    args = parser.parse_args()

    # Initialize engine-specific imports
    _init_engine(args.engine)

    module_name = 'riscv32i_complete'
    if args.output_dir:
        output_dir = args.output_dir
    elif args.backend == 'circt':
        output_dir = 'examples/verilog/circt_riscv32i'
    elif args.backend == 'pyrtl':
        output_dir = 'examples/pyrtl/riscv32i_complete'
    elif args.backend == 'clash':
        output_dir = 'examples/clash/riscv32i_complete'
    elif args.backend == 'hardcaml':
        output_dir = 'examples/hardcaml/riscv32i_complete'
    elif args.backend == 'chisel':
        output_dir = 'examples/chisel/riscv32i_complete'
    elif args.backend == 'rtlil':
        output_dir = 'examples/rtlil/riscv32i_complete'
    elif args.backend == 'verilog':
        output_dir = f'examples/verilog/riscv32i_complete'
    else:
        output_dir = f'{args.backend}/riscv32i_complete'

    print("=" * 70)
    print(f"RV32I Processor Generator ({args.backend.upper()} backend, {args.engine} engine)")
    print("=" * 70)
    print(f"\nGenerating RV32I processor with {len(INSTRUCTIONS)} instructions...")
    print(f"Instructions: {', '.join(INSTRUCTIONS)}")

    # Step 1: Parse and merge ISA files
    print("\n" + "=" * 70)
    print("Step 1: Parsing and merging ISA files...")
    print("=" * 70)
    isa_files = {instr: f"isa/riscv32/{instr}.isa" for instr in INSTRUCTIONS}

    try:
        merged_graph = merge_instructions(isa_files)
        print(f"  Successfully merged {len(INSTRUCTIONS)} instructions")
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
    merged_graph = apply_memory_transform(merged_graph)

    # Step 2b: Apply memory externalization if requested
    if args.externalize_memory:
        print("\n" + "=" * 70)
        print("Step 2b: Applying memory externalization...")
        print("=" * 70)

        # NOTE: For externalized memory, variable latency is handled externally
        # via valid-ready handshake. The Verilog generator creates mem_ext_stall
        # based on the handshake signals. We do NOT use set_memory_variable_latency
        # here because that creates internal latency counters, which conflicts
        # with the external handshake approach.

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
                output_dir = f'examples/verilog/riscv32i_complete_ext' if args.backend == 'verilog' else f'{args.backend}/riscv32i_complete_ext'

            # Note: ISA state gating for single-cycle machines is handled by the
            # Verilog generator via mem_ext_stall signal. The generator creates
            # pending trackers and gates all state updates with !mem_ext_stall.
            # No additional graph-level gating is needed.
        else:
            print("  Warning: Memory externalization failed")

    # Step 2c: Apply ALU integration if requested
    if args.alu_spec:
        print("\n" + "=" * 70)
        print("Step 2c: Applying ALU integration...")
        print("=" * 70)

        from core.alu_spec_parser import parse_alu_spec_file
        from opt.alu_integration import apply_alu_integration

        alu_specs = parse_alu_spec_file(args.alu_spec)
        if not alu_specs:
            print(f"  Error: no alu_module declarations found in '{args.alu_spec}'")
            sys.exit(1)
        alu_spec = alu_specs[0]
        print(f"  Loaded ALU spec: {alu_spec.name} ({len(alu_spec.operations)} operations)")

        # RV32I nodes to integrate: register-register and register-immediate
        # operations, comparison-ternaries, branch comparisons, and address
        # calculations.  Use --list-operations to see all available nodes.
        ALU_NODES = [
            # Register-register arithmetic/logic
            '(r1 + r2)',
            '(r1 - r2)',
            '(r1 & r2)',
            '(r1 | r2)',
            '(r1 ^ r2)',
            # Register-immediate arithmetic/logic
            '(r1 & sign_ext_imm)',
            '(r1 | sign_ext_imm)',
            '(r1 ^ sign_ext_imm)',
            # Shifts
            '(r1 << r2[4:0])',
            '(r1 << shamt)',
            '(r1 >> r2[4:0])',
            '(r1 >> shamt)',
            '(r1 >>> r2[4:0])',
            '(r1 >>> shamt)',
            # Branch comparisons
            '(r1 == r2)',
            '(r1 != r2)',
            '(r1 >=s r2)',
            '(r1 >= r2)',
            # Set-less-than (comparison ? 1 : 0 ternaries)
            '(r1 <s r2) ? 1 : 0',
            '(r1 < r2) ? 1 : 0',
            '(r1 <s sign_ext_imm) ? 1 : 0',
            '(r1 < sign_ext_imm) ? 1 : 0',
            # Address calculations (shared across addi/loads/stores)
            'addi_(r1 + sign_ext_imm)',
            'sb_(r1 + sign_ext_imm)',
        ]

        # Filter to nodes that actually exist in this graph (some may be
        # absent if the instruction set is a subset of full RV32I).
        node_ids = [nid for nid in ALU_NODES if nid in merged_graph.nodes]
        print(f"  Nodes to integrate: {len(node_ids)}")

        if apply_alu_integration(merged_graph, alu_spec, node_ids):
            alu_nodes = [n for n in merged_graph.nodes.values()
                         if n.data.get('type') == 'alu_module']
            print(f"  ALU integration applied: {len(alu_nodes)} ALU module(s) created")
            print(f"  Graph now has {len(merged_graph.nodes)} nodes and {len(merged_graph.edges)} edges")
        else:
            print("  Warning: No operations could be integrated into the ALU")

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
        elif args.backend == 'clash':
            files = generate_clash(merged_graph, module_name, output_dir)
        elif args.backend == 'hardcaml':
            files = generate_hardcaml(merged_graph, module_name, output_dir)
        elif args.backend == 'chisel':
            files = generate_chisel_output(merged_graph, module_name, output_dir)
        elif args.backend == 'rtlil':
            files = generate_rtlil(merged_graph, module_name, output_dir)

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
    print(f"  Successfully generated complete RV32I processor")
    print(f"  {len(INSTRUCTIONS)} instructions implemented")
    print(f"  {len(merged_graph.nodes)} nodes in merged graph")
    print(f"  {len(merged_graph.edges)} edges in merged graph")
    print(f"  Backend: {args.backend.upper()}")
    print(f"  Output: {output_dir}/")

    print("\n" + "=" * 70)
    print("Done!")
    print("=" * 70)


if __name__ == "__main__":
    main()
