#!/usr/bin/env python3
"""
Generate OpenRISC OR1K processor with MMU support.
Includes all Orbis32 + ORFPX32 instructions with ITLB/DTLB translation aspects
for running Linux with virtual memory.

The OR1K MMU uses software-managed TLBs:
  - ITLB: 128 entries, indexed by VPN[6:0]
  - DTLB: 128 entries, indexed by VPN[6:0]
  - TLB miss -> hardware exception -> OS handler fills TLB
  - Separate execute/read/write permission bits per supervisor/user mode

Exception vectors:
  0x300 - Data Page Fault (permission violation)
  0x400 - Instruction Page Fault (permission violation)
  0x500 - Tick Timer
  0x800 - External Interrupt
  0x900 - DTLB Miss
  0xA00 - ITLB Miss
  0xC00 - System Call
  0xD00 - Floating Point
  0xE00 - Trap

Supports Verilog backend with optional memory externalization for
Linux boot simulation with peripherals (UART, PIC, Tick Timer).
"""
import sys
import os
import argparse

# Add ISAComp root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core.graph_merger import ResourceGraphMerger
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec
from opt.memory.memory_externalization import MemoryExternalizationSpec, apply_memory_externalization
from backends.verilog import VerilogGenerator, generate_verilog_with_testbench

# Complete OR1K instruction set - MMU-aware versions
# These use aspect files for instruction fetch and data translation
INSTRUCTIONS = [
    # Arithmetic (8)
    'l.add', 'l.addi', 'l.sub', 'l.mul', 'l.mulu', 'l.div', 'l.divu',
    'l.muli',

    # Logical (6)
    'l.and', 'l.andi', 'l.or', 'l.ori', 'l.xor', 'l.xori',

    # Shifts (8)
    'l.sll', 'l.srl', 'l.sra', 'l.slli', 'l.srli', 'l.srai',
    'l.ror', 'l.rori',

    # Data transfer (2)
    'l.movhi', 'l.cmov',

    # Sign/zero extension (6)
    'l.extbs', 'l.extbz', 'l.exths', 'l.exthz', 'l.extws', 'l.extwz',

    # Bit manipulation (2)
    'l.ff1', 'l.fl1',

    # Compare register (10)
    'l.sfeq', 'l.sfne', 'l.sfgtu', 'l.sfgeu', 'l.sfltu', 'l.sfleu',
    'l.sfgts', 'l.sfges', 'l.sflts', 'l.sfles',

    # Compare immediate (10)
    'l.sfeqi', 'l.sfnei', 'l.sfgtui', 'l.sfgeui', 'l.sfltui', 'l.sfleui',
    'l.sfgtsi', 'l.sfgesi', 'l.sfltsi', 'l.sflesi',

    # Branch (6)
    'l.j', 'l.jal', 'l.jalr', 'l.jr', 'l.bf', 'l.bnf',

    # Load (5) - use DTLB translation aspect
    'l.lw', 'l.lbz', 'l.lbs', 'l.lhz', 'l.lhs',

    # Store (3) - use DTLB translation aspect
    'l.sw', 'l.sb', 'l.sh',

    # Atomic (2) - use DTLB translation aspects
    'l.lwa', 'l.swa',

    # System (8)
    'l.mtspr', 'l.mfspr', 'l.sys', 'l.trap', 'l.rfe',
    'l.msync', 'l.psync', 'l.csync',

    # NOP (1)
    'l.nop',
]

# ORFPX32 single-precision floating-point instructions
FP_INSTRUCTIONS = [
    # FP Arithmetic (8)
    'lf.add.s', 'lf.sub.s', 'lf.mul.s', 'lf.div.s',
    'lf.itof.s', 'lf.ftoi.s', 'lf.rem.s', 'lf.madd.s',

    # FP Compare (6)
    'lf.sfeq.s', 'lf.sfne.s', 'lf.sfgt.s', 'lf.sfge.s',
    'lf.sflt.s', 'lf.sfle.s',
]


def apply_memory_transform(merged_graph):
    """Apply port width setting for word-addressed unified memory."""
    umem_node = merged_graph.nodes.get('umem')
    if umem_node:
        access_widths = umem_node.data.get('access_widths', [32])
        max_width = max(access_widths) if access_widths else 32
        print(f"  umem access widths: {access_widths}, max: {max_width}")

        transform = MemoryAccessTransform(merged_graph)
        spec = MemoryAccessTransformSpec(
            memory='umem',
            strategy='set_port_width',
            current_width=max_width,
            target_width=32,
            direction='forward',
            endianness='big'
        )
        result = transform.apply_transformation(spec)
        if result.get('transformed'):
            print(f"  Transformed: added {len(result.get('nodes_added', []))} byte mux nodes")
        else:
            print(f"  Skipped: {result.get('reason', 'unknown')}")


def generate_externalized_memory_testbench(generator, module_name, output_path):
    """Generate a testbench for a processor with externalized memory.

    This testbench:
    1. Instantiates the processor module
    2. Creates external memory (64MB for OR1K)
    3. Connects the external memory ports
    4. Loads test programs via $readmemh into external memory
    """
    from pathlib import Path

    ext_memories = list(generator.externalized_memories)
    if not ext_memories:
        return ""

    memory_ports = {}
    for mem_name in ext_memories:
        memory_ports[mem_name] = {
            'read_ports': [],
            'write_ports': [],
            'data_width': 32,
            'addr_width': 32,
        }

        mem_info = generator.memory_declarations.get(mem_name, {})
        memory_ports[mem_name]['data_width'] = mem_info.get('bit_width', 32)
        memory_ports[mem_name]['addr_width'] = mem_info.get('externalized_addr_width', 32)
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

    # Memory models
    for mem_name, ports in memory_ports.items():
        data_width = ports['data_width']
        addr_width = ports['addr_width']
        depth = 16 * 1024 * 1024 // 4  # 16M words = 64MB
        num_bytes = max(1, data_width // 8)
        word_addr_bits = 2 if data_width == 32 else 3

        min_latency = ports.get('min_latency', 0)

        tb.append(f"    // {mem_name} - multi-port memory model (64MB)\n")
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
    tb.append("        for (i = 0; i < 50000; i = i + 1) begin\n")
    tb.append("            @(posedge clk);\n")
    tb.append("            if (dut.pc_rd == pass_addr) begin $display(\"TEST PASSED\"); $finish; end\n")
    tb.append("            if (dut.pc_rd == fail_addr) begin $display(\"TEST FAILED at pc=%h\", dut.pc_rd); $finish; end\n")
    tb.append("        end\n")
    tb.append("        $display(\"TIMEOUT\");\n")
    tb.append("        $finish;\n")
    tb.append("    end\n")
    tb.append("endmodule\n")

    return "".join(tb)


def generate_verilog(merged_graph, module_name, output_dir, externalized=False):
    """Generate Verilog output with optional memory externalization."""
    from pathlib import Path

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    generator = VerilogGenerator(merged_graph, module_name)
    verilog_code = generator.generate()

    rtl_file = output_path / f"{module_name}.v"
    rtl_file.write_text(verilog_code)

    files = {'rtl': rtl_file}

    has_externalized = bool(generator.externalized_memories)

    if has_externalized:
        for mem_name in generator.externalized_memories:
            wrapper_code = generator.generate_memory_wrapper(mem_name)
            if wrapper_code:
                wrapper_file = output_path / f"{mem_name}_memory.v"
                wrapper_file.write_text(wrapper_code)
                files[f'{mem_name}_wrapper'] = wrapper_file
                print(f"  Generated memory wrapper: {wrapper_file}")

        testbench_code = generate_externalized_memory_testbench(
            generator, module_name, output_path
        )
        tb_file = output_path / f"simple_tb.sv"
        tb_file.write_text(testbench_code)
        files['testbench'] = tb_file
        print(f"  Generated externalized memory testbench: {tb_file}")
    else:
        testbench_config = {
            'timeout_cycles': 50000
        }
        tb_files = generate_verilog_with_testbench(
            merged_graph,
            module_name=module_name,
            output_dir=output_dir,
            testbench_config=testbench_config
        )
        files.update(tb_files)

    return files


def main():
    parser = argparse.ArgumentParser(
        description='Generate OpenRISC OR1K MMU processor from ISA definitions'
    )
    parser.add_argument(
        '--backend', '-b',
        choices=['verilog'],
        default='verilog',
        help='Output backend (default: verilog)'
    )
    parser.add_argument(
        '--output-dir', '-o',
        help='Output directory (default: examples/verilog/or1k_mmu)'
    )
    parser.add_argument(
        '--externalize-memory',
        action='store_true',
        help='Externalize unified memory (umem) with valid-ready handshake ports'
    )
    parser.add_argument(
        '--no-fp',
        action='store_true',
        help='Exclude floating-point instructions (ORFPX32)'
    )
    args = parser.parse_args()

    module_name = 'or1k_mmu'

    # Build instruction list
    all_instructions = list(INSTRUCTIONS)
    if not args.no_fp:
        all_instructions.extend(FP_INSTRUCTIONS)

    print("=" * 70)
    print("OpenRISC OR1K MMU PROCESSOR GENERATOR")
    print("=" * 70)
    print(f"Total instructions: {len(all_instructions)}")
    features = "ITLB, DTLB, Tick Timer, External Interrupts, Atomics"
    if not args.no_fp:
        features += ", ORFPX32 FP"
    print(f"Features: {features}")
    if args.externalize_memory:
        print("Memory: Externalized with valid-ready handshake")
    print("=" * 70)

    mmu_dir = os.path.join(os.path.dirname(__file__), '..', 'mmu')

    # Step 1: Parse and merge ISA files
    print("\n" + "=" * 70)
    print("Step 1: Parsing and merging ISA files...")
    print("=" * 70)

    merger = ResourceGraphMerger()
    skipped = []

    for instr_name in all_instructions:
        isa_file = os.path.join(mmu_dir, f"{instr_name}.isa")
        if not os.path.exists(isa_file):
            print(f"  WARNING: MMU file not found for {instr_name}, skipping")
            skipped.append(instr_name)
            continue
        success = merger.add_instruction(instr_name, isa_file)
        if not success:
            print(f"  WARNING: Failed to add instruction {instr_name}")
            skipped.append(instr_name)
            continue

    if skipped:
        print(f"\n  Skipped {len(skipped)} instructions: {', '.join(skipped)}")

    merged_graph = merger.merge_graphs()
    print(f"\n  Successfully merged {len(all_instructions) - len(skipped)} instructions")
    print(f"  Merged graph has {len(merged_graph.nodes)} nodes and {len(merged_graph.edges)} edges")

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
        else:
            print("  Warning: Memory externalization failed")

    # Step 3: Generate output
    if args.output_dir:
        output_dir = args.output_dir
    elif args.externalize_memory:
        output_dir = os.path.join(os.path.dirname(__file__), '../../../examples/verilog/or1k_mmu_ext')
    else:
        output_dir = os.path.join(os.path.dirname(__file__), '../../../examples/verilog/or1k_mmu')

    print("\n" + "=" * 70)
    print(f"Step 3: Generating Verilog RTL and testbench...")
    print("=" * 70)
    print(f"  Output directory: {output_dir}")

    try:
        files = generate_verilog(merged_graph, module_name, output_dir,
                                 externalized=args.externalize_memory)

        print(f"\n  Generated files:")
        for key, path in files.items():
            if hasattr(path, 'stat'):
                file_size = path.stat().st_size if path.exists() else 0
                print(f"    {key.upper()}: {path} ({file_size:,} bytes)")
            else:
                print(f"    {key.upper()}: {path}")

    except Exception as e:
        print(f"  Error generating Verilog: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"  Successfully generated OR1K MMU processor")
    print(f"  {len(all_instructions) - len(skipped)} instructions implemented")
    print(f"  {len(merged_graph.nodes)} nodes in merged graph")
    print(f"  {len(merged_graph.edges)} edges in merged graph")
    print(f"  Software-managed TLB: ITLB 128 entries, DTLB 128 entries")
    if not args.no_fp:
        print(f"  FP: ORFPX32 single-precision ({len(FP_INSTRUCTIONS)} instructions)")
    if args.externalize_memory:
        print(f"  Memory: Externalized with valid-ready handshake")
    print(f"  Output: {output_dir}/")

    print("\n" + "=" * 70)
    print("Done!")
    print("=" * 70)

    return merged_graph


if __name__ == '__main__':
    main()
