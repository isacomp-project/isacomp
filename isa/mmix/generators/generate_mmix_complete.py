#!/usr/bin/env python3
"""
Generate complete MMIX processor from ISA definitions.

MMIX is a 64-bit RISC architecture designed by Donald Knuth.
This generator supports Verilog backend.
"""
import sys
import os
import argparse

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core.graph_merger import merge_instructions
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec
from opt.memory.memory_externalization import MemoryExternalizationSpec, apply_memory_externalization

# Complete MMIX instruction set (256 instructions total, ~220 enabled)
INSTRUCTIONS = [
    # Arithmetic - signed (10)
    'add', 'addi', 'sub', 'subi', 'mul', 'muli', 'div', 'divi', 'neg', 'negi',

    # Arithmetic - unsigned (8)
    'addu', 'addui', 'subu', 'subui', 'mulu', 'mului', 'divu', 'divui',
    'negu', 'negui',

    # Scaled address (8)
    '2addu', '2addui', '4addu', '4addui', '8addu', '8addui', '16addu', '16addui',

    # Logical (16)
    'and', 'andi', 'or', 'ori', 'xor', 'xori', 'nor', 'nori', 'nand', 'nandi',
    'andn', 'andni', 'orn', 'orni', 'nxor', 'nxori',

    # Shifts (8)
    'sl', 'sli', 'slu', 'slui', 'sr', 'sri', 'sru', 'srui',

    # Compare (4)
    'cmp', 'cmpi', 'cmpu', 'cmpui',

    # Load - standard (16)
    'ldb', 'ldbi', 'ldbu', 'ldbui', 'ldw', 'ldwi', 'ldwu', 'ldwui',
    'ldt', 'ldti', 'ldtu', 'ldtui', 'ldo', 'ldoi', 'ldou', 'ldoui',

    # Load - special (10)
    'ldsf', 'ldsfi', 'ldht', 'ldhti', 'ldunc', 'ldunci', 'ldvts', 'ldvtsi',

    # Store - standard (16)
    'stb', 'stbi', 'stbu', 'stbui', 'stw', 'stwi', 'stwu', 'stwui',
    'stt', 'stti', 'sttu', 'sttui', 'sto', 'stoi', 'stou', 'stoui',

    # Store - special (10)
    'stsf', 'stsfi', 'stht', 'sthti', 'stco', 'stcoi', 'stunc', 'stunci',

    # Branch (16)
    'bn', 'bnb', 'bz', 'bzb', 'bp', 'bpb', 'bod', 'bodb',
    'bnn', 'bnnb', 'bnz', 'bnzb', 'bnp', 'bnpb', 'bev', 'bevb',

    # Probable branches (16)
    'pbn', 'pbnb', 'pbz', 'pbzb', 'pbp', 'pbpb', 'pbod', 'pbodb',
    'pbnn', 'pbnnb', 'pbnz', 'pbnzb', 'pbnp', 'pbnpb', 'pbev', 'pbevb',

    # Jump (4)
    'jmp', 'jmpb', 'go', 'goi',

    # Address (2)
    'geta', 'getab',

    # Set (4)
    'seth', 'setmh', 'setml', 'setl',

    # Conditional set (16)
    'csn', 'csni', 'csz', 'cszi', 'csp', 'cspi', 'csod', 'csodi',
    'csnn', 'csnni', 'csnz', 'csnzi', 'csnp', 'csnpi', 'csev', 'csevi',

    # Zero-or set (16)
    'zsn', 'zsni', 'zsz', 'zszi', 'zsp', 'zspi', 'zsod', 'zsodi',
    'zsnn', 'zsnni', 'zsnz', 'zsnzi', 'zsnp', 'zsnpi', 'zsev', 'zsevi',

    # Immediate wyde operations (12)
    'inch', 'incmh', 'incml', 'incl',
    'orh', 'ormh', 'orml', 'orl',
    'andnh', 'andnmh', 'andnml', 'andnl',

    # Byte/wyde/tetra/octa difference (8)
    'bdif', 'bdifi', 'wdif', 'wdifi', 'tdif', 'tdifi', 'odif', 'odifi',

    # Bitwise operations - mux only (sadd/mor/mxor need unsupported intrinsics)
    'mux', 'muxi',

    # Cache/sync hints (12)
    'preld', 'preldi', 'prego', 'pregoi', 'prest', 'presti',
    'syncd', 'syncdi', 'syncid', 'syncidi', 'sync', 'swym',

    # Atomic operations (2)
    'cswap', 'cswapi',

    # Subroutine call/return (7)
    'pushj', 'pushjb', 'pushgo', 'pushgoi', 'pop', 'save', 'unsave',

    # Special registers (4)
    'get', 'put', 'puti',

    # System/trap (4)
    'trap', 'trip', 'resume',

    # Note: Instructions requiring unsupported intrinsics (popcount, bmatrix):
    # 'sadd', 'saddi', 'mor', 'mori', 'mxor', 'mxori',
]

# Floating-point instructions (require cvfpu module and --with-fp flag)
FP_INSTRUCTIONS = [
    # FP arithmetic (5)
    'fadd', 'fsub', 'fmul', 'fdiv', 'fsqrt',

    # FP compare (6)
    'fcmp', 'feql', 'fun', 'fcmpe', 'feqle', 'fune',

    # FP conversion - float to int (2)
    'fix', 'fixu',

    # FP conversion - int to float (4)
    'flot', 'floti', 'flotu', 'flotui',

    # Note: Excluded FP instructions (need unsupported intrinsics):
    # 'frem' - needs fp_rem_d (not in cvfpu)
    # 'fint' - needs fp_round_d (not in cvfpu)
    # 'sflot', 'sfloti', 'sflotu', 'sflotui' - need int_to_fp_s_extend_d
]

# Test list for MMIX
MMIX_TESTS = [
    'add', 'addi', 'sub', 'and', 'or', 'xor', 'sl', 'sr', 'sru',
    'cmp', 'cmpu', 'ldo', 'sto', 'bz', 'bnz', 'jmp', 'go', 'setl',
]


def apply_memory_transform(merged_graph):
    """Apply port width setting for word-addressed unified memory."""
    umem_node = merged_graph.nodes.get('umem')
    if umem_node:
        access_widths = umem_node.data.get('access_widths', [64])
        max_width = max(access_widths) if access_widths else 64
        print(f"  umem access widths: {access_widths}, max: {max_width}")

        # Apply set_port_width transformation for 64-bit memory
        transform = MemoryAccessTransform(merged_graph)
        spec = MemoryAccessTransformSpec(
            memory='umem',
            strategy='set_port_width',
            current_width=max_width,
            target_width=64,  # 64-bit word-addressed memory for MMIX
            direction='forward'
        )
        result = transform.apply_transformation(spec)
        if result.get('transformed'):
            print(f"  Transformed: added {len(result.get('nodes_added', []))} byte mux nodes")
        else:
            print(f"  Skipped: {result.get('reason', 'unknown')}")


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
        # Generate simple testbench
        testbench_code = generate_simple_testbench(module_name)
        tb_file = output_path / f"{module_name}_tb.sv"
        tb_file.write_text(testbench_code)
        files['testbench'] = tb_file

    return files


def generate_simple_testbench(module_name):
    """Generate a simple testbench for MMIX processor."""
    return f"""`timescale 1ns/1ps

module {module_name}_tb;
    reg clk, reset;
    wire [63:0] zero64 = 64'd0;

    // Device Under Test
    {module_name} dut (
        .clk(clk),
        .reset(reset),
        .reset_pc_rd(zero64)
    );

    reg [63:0] pass_addr, fail_addr;
    integer i;

    always #5 clk = ~clk;

    initial begin
        clk = 0;
        reset = 1;
        if (!$value$plusargs("pass_addr=%h", pass_addr)) pass_addr = 64'hFFFFFFFFFFFFFFFF;
        if (!$value$plusargs("fail_addr=%h", fail_addr)) fail_addr = 64'hFFFFFFFFFFFFFFFE;

        // Load memory
        $readmemh("umem.hex", dut.umem);

        repeat(3) @(posedge clk);
        reset = 0;

        for (i = 0; i < 10000; i = i + 1) begin
            @(posedge clk);
            if (dut.pc_rd == pass_addr) begin
                $display("TEST PASSED");
                $finish;
            end
            if (dut.pc_rd == fail_addr) begin
                $display("TEST FAILED at pc=%h", dut.pc_rd);
                $finish;
            end
        end
        $display("TIMEOUT");
        $finish;
    end
endmodule
"""


def generate_externalized_memory_testbench(generator, module_name, output_path):
    """Generate a testbench for a processor with externalized memory."""
    from pathlib import Path

    ext_memories = list(generator.externalized_memories)
    if not ext_memories:
        return ""

    memory_ports = {}
    for mem_name in ext_memories:
        memory_ports[mem_name] = {
            'read_ports': [],
            'write_ports': [],
            'data_width': 64,
            'addr_width': 64,
        }

        mem_info = generator.memory_declarations.get(mem_name, {})
        memory_ports[mem_name]['data_width'] = mem_info.get('bit_width', 64)
        memory_ports[mem_name]['addr_width'] = mem_info.get('externalized_addr_width', 64)
        memory_ports[mem_name]['use_valid_ready'] = mem_info.get('use_valid_ready', True)
        memory_ports[mem_name]['min_latency'] = mem_info.get('min_latency', 0)
        memory_ports[mem_name]['max_latency'] = mem_info.get('max_latency', 0)

        tracked_read = set()
        for rp in generator.memory_read_ports:
            if rp['mem'] == mem_name:
                ext_port = rp.get('ext_port_name', mem_name)
                if ext_port not in tracked_read:
                    tracked_read.add(ext_port)
                    memory_ports[mem_name]['read_ports'].append(ext_port)

        tracked_write = set()
        for wp in generator.memory_write_ports:
            if wp['mem'] == mem_name:
                ext_port = wp.get('ext_port_name', mem_name)
                if ext_port not in tracked_write:
                    tracked_write.add(ext_port)
                    memory_ports[mem_name]['write_ports'].append(ext_port)

    tb = []
    tb.append("`timescale 1ns/1ps\n")
    tb.append(f"module simple_tb;\n")
    tb.append("    reg clk, reset;\n")
    tb.append("    wire [63:0] zero64 = 64'd0;\n\n")

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

    tb.append(f"    // Device Under Test\n")
    tb.append(f"    {module_name} dut (\n")
    tb.append("        .clk(clk),\n")
    tb.append("        .reset(reset),\n")
    tb.append("        .reset_pc_rd(zero64)")

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

    for mem_name, ports in memory_ports.items():
        data_width = ports['data_width']
        addr_width = ports['addr_width']
        depth = 16384
        num_bytes = max(1, data_width // 8)
        word_addr_bits = 3  # log2(8) for 64-bit words

        min_latency = ports.get('min_latency', 0)

        tb.append(f"    // {mem_name} - multi-port memory model\n")
        tb.append(f"    parameter {mem_name.upper()}_MEM_LATENCY = {min_latency};\n")
        tb.append(f"    reg [{data_width-1}:0] {mem_name}_mem [0:{depth-1}];\n\n")

        mem_latency_param = f"{mem_name.upper()}_MEM_LATENCY"
        for rp in ports['read_ports']:
            tb.append(f"    // {rp} read interface\n")
            tb.append(f"    generate\n")
            tb.append(f"        if ({mem_latency_param} == 0) begin : {rp}_comb\n")
            tb.append(f"            assign {rp}_read_resp_data = {mem_name}_mem[{rp}_read_req_addr[{addr_width-1}:{word_addr_bits}]];\n")
            if ports['use_valid_ready']:
                tb.append(f"            assign {rp}_read_resp_ready = {rp}_read_req_valid;\n")
            tb.append(f"        end else begin : {rp}_lat1\n")
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
            tb.append(f"        end\n")
            tb.append(f"    endgenerate\n\n")

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

    tb.append("    reg [63:0] pass_addr, fail_addr;\n")
    tb.append("    integer i;\n")
    tb.append("    always #5 clk = ~clk;\n\n")

    tb.append("    initial begin\n")
    tb.append("        clk = 0; reset = 1;\n")
    tb.append("        if (!$value$plusargs(\"pass_addr=%h\", pass_addr)) pass_addr = 64'hFFFFFFFFFFFFFFFF;\n")
    tb.append("        if (!$value$plusargs(\"fail_addr=%h\", fail_addr)) fail_addr = 64'hFFFFFFFFFFFFFFFE;\n")

    if ext_memories:
        mem_name = ext_memories[0]
        tb.append(f"        $readmemh(\"{mem_name}.hex\", {mem_name}_mem);\n")

    tb.append("        repeat(3) @(posedge clk);\n")
    tb.append("        reset = 0;\n")
    tb.append("        for (i = 0; i < 10000; i = i + 1) begin\n")
    tb.append("            @(posedge clk);\n")
    tb.append("            if (dut.pc_rd == pass_addr) begin $display(\"TEST PASSED\"); $finish; end\n")
    tb.append("            if (dut.pc_rd == fail_addr) begin $display(\"TEST FAILED at pc=%h\", dut.pc_rd); $finish; end\n")
    tb.append("        end\n")
    tb.append("        $display(\"TIMEOUT\");\n")
    tb.append("        $finish;\n")
    tb.append("    end\n")
    tb.append("endmodule\n")

    return "".join(tb)


def main():
    parser = argparse.ArgumentParser(
        description='Generate complete MMIX processor from ISA definitions'
    )
    parser.add_argument(
        '--backend', '-b',
        choices=['verilog'],
        default='verilog',
        help='Output backend (default: verilog)'
    )
    parser.add_argument(
        '--output-dir', '-o',
        help='Output directory (default: examples/verilog/mmix_complete)'
    )
    parser.add_argument(
        '--externalize-memory',
        action='store_true',
        help='Externalize unified memory (umem) with valid-ready handshake ports'
    )
    parser.add_argument(
        '--with-fp',
        action='store_true',
        help='Include floating-point instructions (requires cvfpu module)'
    )
    args = parser.parse_args()

    # Build instruction list
    instructions = list(INSTRUCTIONS)
    if args.with_fp:
        instructions.extend(FP_INSTRUCTIONS)

    module_name = 'mmix_complete'
    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = 'examples/verilog/mmix_complete'

    print("=" * 70)
    print(f"MMIX Processor Generator ({args.backend.upper()} backend)")
    print("=" * 70)
    if args.with_fp:
        print(f"\nGenerating MMIX processor with {len(instructions)} instructions (including FP)...")
    else:
        print(f"\nGenerating MMIX processor with {len(instructions)} instructions...")
    print(f"Instructions: {', '.join(instructions[:10])}...")

    # Step 1: Parse and merge ISA files
    print("\n" + "=" * 70)
    print("Step 1: Parsing and merging ISA files...")
    print("=" * 70)
    isa_files = {instr: f"isa/mmix/{instr}.isa" for instr in instructions}

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

    # Step 2b: Apply memory externalization if requested
    if args.externalize_memory:
        print("\n" + "=" * 70)
        print("Step 2b: Applying memory externalization...")
        print("=" * 70)

        spec = MemoryExternalizationSpec(
            memory_name='umem',
            create_read_port=True,
            create_write_port=True,
            variable_latency=True
        )
        if apply_memory_externalization(merged_graph, spec):
            print("  Memory externalization applied successfully")
            if not args.output_dir:
                output_dir = 'examples/verilog/mmix_complete_ext'
        else:
            print("  Warning: Memory externalization failed")

    # Step 3: Mark FP div/sqrt as multi-cycle (for CVFPU handshake-based stalling)
    if args.with_fp:
        print("\n" + "=" * 70)
        print("Step 3: Marking FP div/sqrt as multi-cycle (10 cycles, handshake-based)")
        print("=" * 70)
        # MMIX double-precision div/sqrt operations
        fp_ops = [
            'fp_div_d(y_val, z_val)', 'fp_sqrt_d(z_val)',
        ]
        for op_id in fp_ops:
            if op_id in merged_graph.nodes:
                node = merged_graph.nodes[op_id]
                node.data['multi_cycle'] = True
                node.data['latency_cycles'] = 10
                print(f"  Marked {op_id} as multi-cycle (10 cycles)")
            else:
                # Try to find similar nodes
                found = False
                for node_id in merged_graph.nodes:
                    if op_id.split('(')[0] in node_id:
                        node = merged_graph.nodes[node_id]
                        node.data['multi_cycle'] = True
                        node.data['latency_cycles'] = 10
                        print(f"  Marked {node_id} as multi-cycle (10 cycles)")
                        found = True
                        break
                if not found:
                    print(f"  {op_id} not found in graph")

    # Step 4: Generate RTL
    print("\n" + "=" * 70)
    print(f"Step 4: Generating {args.backend.upper()} RTL and testbench...")
    print("=" * 70)
    print(f"  Output directory: {output_dir}")

    try:
        files = generate_verilog(merged_graph, module_name, output_dir)

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
    print(f"  Successfully generated complete MMIX processor")
    print(f"  {len(instructions)} instructions implemented")
    if args.with_fp:
        print(f"  (includes {len(FP_INSTRUCTIONS)} FP instructions)")
    print(f"  {len(merged_graph.nodes)} nodes in merged graph")
    print(f"  {len(merged_graph.edges)} edges in merged graph")
    print(f"  Backend: {args.backend.upper()}")
    print(f"  Output: {output_dir}/")

    print("\n" + "=" * 70)
    print("Done!")
    print("=" * 70)


if __name__ == "__main__":
    main()
