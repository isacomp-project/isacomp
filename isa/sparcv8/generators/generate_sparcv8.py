#!/usr/bin/env python3
"""
Generate SPARCv8 processor from ISA definitions.

This generates a complete SPARCv8 processor including:
- Integer arithmetic (ADD, SUB, MUL, DIV)
- Logical operations (AND, OR, XOR, XNOR)
- Shift operations (SLL, SRL, SRA)
- Load/Store operations (LD, LDUB, LDUH, LDSB, LDSH, LDD, ST, STB, STH, STD)
- Branch instructions (BA, BE, BNE, BG, BLE, BGE, BL, BGU, BLEU, BCC, BCS, BPOS, BNEG, BVC, BVS)
- Control transfer (CALL, JMPL)
- SETHI, NOP
- SAVE/RESTORE (simplified, without register windows)
- Y register access (RDY, WRY)

Supports Verilog, VHDL, PyRTL, and CIRCT backends via --backend argument.

SPARCv8 is a 32-bit big-endian RISC architecture with:
- 32 general-purpose registers (r0 always reads as 0)
- Condition codes in PSR (icc: N, Z, V, C)
- Y register for multiply/divide high result
- Optional register windows (not implemented in this simplified version)
"""
import sys
import os
import argparse

# Add parent directories to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core.graph_merger import merge_instructions
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec
from opt.memory.memory_externalization import MemoryExternalizationSpec, apply_memory_externalization

# SPARCv8 instruction set
INSTRUCTIONS = [
    # Arithmetic (12)
    'add', 'addcc', 'addx', 'addxcc',
    'sub', 'subcc', 'subx', 'subxcc',
    'smul', 'umul', 'sdiv', 'udiv',

    # Arithmetic with CC variants (4)
    'smulcc', 'umulcc', 'sdivcc', 'udivcc',

    # Tagged arithmetic (4)
    'taddcc', 'tsubcc', 'taddcctv', 'tsubcctv',

    # Multiply step (1)
    'mulscc',

    # Logical (12)
    'and', 'andcc', 'andn', 'andncc',
    'or', 'orcc', 'orn', 'orncc',
    'xor', 'xorcc', 'xnor', 'xnorcc',

    # Shifts (3)
    'sll', 'srl', 'sra',

    # Loads (6)
    'ld', 'ldub', 'lduh', 'ldsb', 'ldsh', 'ldd',

    # Stores (4)
    'st', 'stb', 'sth', 'std',

    # Atomic operations (2)
    'swap', 'ldstub',

    # Branches (16)
    'ba', 'bn', 'be', 'bne', 'bg', 'ble', 'bge', 'bl',
    'bgu', 'bleu', 'bcc', 'bcs', 'bpos', 'bneg', 'bvc', 'bvs',

    # Control transfer (2)
    'call', 'jmpl',

    # SETHI/NOP (2)
    'sethi', 'nop',

    # Window operations (2)
    'save', 'restore',

    # Y register (2)
    'rdy', 'wry',

    # Conditional traps - Ticc (16)
    'ta', 'tn', 'tne', 'te', 'tg', 'tle', 'tge', 'tl',
    'tgu', 'tleu', 'tcc', 'tcs', 'tpos', 'tneg', 'tvc', 'tvs',

    # Privileged instructions (6)
    'rdpsr', 'wrpsr', 'rdwim', 'wrwim', 'rdtbr', 'wrtbr',

    # Return from trap (1)
    'rett',

    # Memory barrier and flush (2)
    'stbar', 'flush',

    # FP instructions (requires cvfpu submodules)
    'fp/ldf', 'fp/stf', 'fp/lddf', 'fp/stdf', 'fp/ldfsr', 'fp/stfsr',
    'fp/fadds', 'fp/fsubs', 'fp/fmuls', 'fp/fdivs', 'fp/fsqrts',
    'fp/faddd', 'fp/fsubd', 'fp/fmuld', 'fp/fdivd', 'fp/fsqrtd',
    # 'fp/fsmuld',  # requires fp_smul_d intrinsic (not yet implemented)
    'fp/fmovs', 'fp/fnegs', 'fp/fabss',
    'fp/fitos', 'fp/fstoi', 'fp/fitod', 'fp/fdtoi', 'fp/fstod', 'fp/fdtos',
    # 'fp/fcmps', 'fp/fcmpd', 'fp/fcmpes', 'fp/fcmped',  # require fp_unordered intrinsic
    'fp/fba', 'fp/fbn', 'fp/fbe', 'fp/fbne', 'fp/fbl', 'fp/fbg',
    'fp/fble', 'fp/fbge', 'fp/fbu', 'fp/fblg', 'fp/fbue', 'fp/fbug',
    'fp/fbul', 'fp/fbuge', 'fp/fbule', 'fp/fbo',

    # Alternate space load (6)
    'lda', 'ldda', 'ldsba', 'ldsha', 'lduba', 'lduha',

    # Alternate space store (4)
    'sta', 'stda', 'stba', 'stha',

    # Alternate space atomic (2)
    'swapa', 'ldstuba',
]

# MMU instructions (optional, enabled with --mmu flag)
MMU_INSTRUCTIONS = [
    'mmu/sta_mmu_flush',      # TLB flush (ASI 0x03)
    'mmu/lda_mmu_probe',      # TLB probe (ASI 0x04)
    'mmu/sta_mmu_ctrl',       # MMU control register write (ASI 0x04)
    'mmu/lda_mmu_ctrl',       # MMU control register read (ASI 0x04)
    'mmu/sta_mmu_tlb_write',  # Direct TLB entry write (ASI 0x05)
    'mmu/ld_mmu',             # Load with MMU translation
    'mmu/st_mmu',             # Store with MMU translation
]


def apply_memory_transform(merged_graph):
    """Apply port width setting for word-addressed unified memory."""
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

    for mem_name, ports in memory_ports.items():
        data_width = ports['data_width']
        addr_width = ports['addr_width']
        depth = 16384
        num_bytes = max(1, data_width // 8)
        word_addr_bits = 2 if data_width == 32 else 3

        min_latency = ports.get('min_latency', 0)

        tb.append(f"    // {mem_name} - multi-port memory model\n")
        tb.append(f"    parameter {mem_name.upper()}_MEM_LATENCY = {min_latency};\n")
        tb.append(f"    reg [{data_width-1}:0] {mem_name}_mem [0:{depth-1}];\n\n")

        mem_latency_param = f"{mem_name.upper()}_MEM_LATENCY"
        for rp in ports['read_ports']:
            tb.append(f"    // {rp} read interface - combinational for single-cycle\n")
            tb.append(f"    assign {rp}_read_resp_data = {mem_name}_mem[{rp}_read_req_addr[{addr_width-1}:{word_addr_bits}]];\n")
            if ports['use_valid_ready']:
                tb.append(f"    assign {rp}_read_resp_ready = {rp}_read_req_valid;\n")
            tb.append("\n")

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
    tb.append("            if (dut.pc_rd == fail_addr) begin $display(\"TEST FAILED at pc=%h\", dut.pc_rd); $finish; end\n")
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
        debug_outputs=['pc_rd']
    )

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

    pyrtl_block = gen_pyrtl(merged_graph, module_name)

    config = PyRTLTestbenchConfig(
        module_name=module_name,
        timeout_cycles=10000,
        imem_size=4096,
        dmem_size=4096,
        arch='sparcv8'
    )

    output_path = Path(output_dir)
    files = generate_pyrtl_testbench_files(
        pyrtl_block,
        module_name=module_name,
        output_dir=output_path,
        config=config,
        instructions=INSTRUCTIONS,
        arch='sparcv8'
    )

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

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    mlir_output = gen_circt_mlir(merged_graph, module_name)

    mlir_file = output_path / f'{module_name}.mlir'
    with open(mlir_file, 'w') as f:
        f.write(mlir_output)

    files = {'mlir': str(mlir_file)}
    print(f"  Generated MLIR: {mlir_file} ({len(mlir_output)} bytes)")

    firtool_path = shutil.which('firtool')
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

                tb_files = generate_circt_testbench(
                    str(sv_file),
                    module_name,
                    'sparcv8',
                    INSTRUCTIONS
                )
                files.update(tb_files)
                print(f"  Generated testbench: {tb_files.get('testbench')}")
            else:
                print(f"  firtool conversion failed:")
                print(f"    {result.stderr[:500]}")
        except FileNotFoundError:
            print("  firtool not found in PATH, skipping Verilog conversion")
        except subprocess.TimeoutExpired:
            print("  firtool timed out")
        except Exception as e:
            print(f"  Error running firtool: {e}")
    else:
        print("  firtool not found in PATH, skipping Verilog conversion")

    return files


def main():
    parser = argparse.ArgumentParser(
        description='Generate SPARCv8 processor from ISA definitions'
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
        help='Output directory (default: examples/verilog/sparcv8)'
    )
    parser.add_argument(
        '--externalize-memory',
        action='store_true',
        help='Externalize unified memory (umem) with valid-ready handshake ports'
    )
    parser.add_argument(
        '--mmu',
        action='store_true',
        help='Include MMU/TLB instructions for virtual memory support'
    )
    args = parser.parse_args()

    module_name = 'sparcv8'
    if args.output_dir:
        output_dir = args.output_dir
    elif args.backend == 'circt':
        output_dir = 'examples/verilog/circt_sparcv8'
    elif args.backend == 'pyrtl':
        output_dir = 'examples/pyrtl/sparcv8'
    elif args.backend == 'verilog':
        output_dir = f'examples/verilog/sparcv8'
    else:
        output_dir = f'{args.backend}/sparcv8'

    # Build instruction list
    instructions = INSTRUCTIONS.copy()
    if args.mmu:
        # Replace base load/store with MMU versions (they handle both MMU enabled/disabled)
        instructions = [i for i in instructions if i not in ('ld', 'st')]
        instructions.extend(MMU_INSTRUCTIONS)
        if not args.output_dir:
            output_dir = f'examples/verilog/sparcv8_mmu' if args.backend == 'verilog' else f'{args.backend}/sparcv8_mmu'
        module_name = 'sparcv8_mmu'

    print("=" * 70)
    print(f"SPARCv8 Processor Generator ({args.backend.upper()} backend)")
    if args.mmu:
        print("  MMU/TLB support enabled")
    print("=" * 70)
    print(f"\nGenerating SPARCv8 processor with {len(instructions)} instructions...")
    print(f"Instructions: {', '.join(instructions)}")

    # Step 1: Parse and merge ISA files
    print("\n" + "=" * 70)
    print("Step 1: Parsing and merging ISA files...")
    print("=" * 70)
    isa_files = {instr: f"isa/sparcv8/{instr}.isa" for instr in instructions}

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

    # Step 2b: Mark FP div/sqrt as multi-cycle (for CVFPU handshake-based stalling)
    print("\n" + "=" * 70)
    print("Step 2b: Marking FP div/sqrt as multi-cycle (10 cycles, handshake-based)")
    print("=" * 70)
    # The node IDs depend on how the intrinsics are called in the .isa files
    # SPARCv8 uses: fp_div(f1, f2, {1'b0, rm}) and fp_sqrt(f2, {1'b0, rm})
    fp_div_candidates = ['fp_div(f1, f2, concat_1_b0_rm)', 'fp_div(f1, f2)', 'fp_div_f1_f2']
    fp_sqrt_candidates = ['fp_sqrt(f2, concat_1_b0_rm)', 'fp_sqrt(f2)', 'fp_sqrt_f2']
    fp_div_d_candidates = ['fp_div_d(f1, f2, concat_1_b0_rm)', 'fp_div_d(f1, f2)', 'fp_div_d_f1_f2']
    fp_sqrt_d_candidates = ['fp_sqrt_d(f2, concat_1_b0_rm)', 'fp_sqrt_d(f2)', 'fp_sqrt_d_f2']

    marked_count = 0
    for candidates in [fp_div_candidates, fp_sqrt_candidates, fp_div_d_candidates, fp_sqrt_d_candidates]:
        for op_id in candidates:
            if op_id in merged_graph.nodes:
                node = merged_graph.nodes[op_id]
                node.data['multi_cycle'] = True
                node.data['latency_cycles'] = 10
                print(f"  Marked {op_id} as multi-cycle (10 cycles)")
                marked_count += 1
                break

    if marked_count == 0:
        print("  No FP div/sqrt operations found (FP instructions may not be enabled)")
    else:
        print(f"  Marked {marked_count} FP div/sqrt operation(s) as multi-cycle")

    # Step 2c: Apply memory externalization if requested
    if args.externalize_memory:
        print("\n" + "=" * 70)
        print("Step 2c: Applying memory externalization...")
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
                output_dir = f'examples/verilog/sparcv8_ext' if args.backend == 'verilog' else f'{args.backend}/sparcv8_ext'
        else:
            print("  Warning: Memory externalization failed")

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
    print(f"  Successfully generated SPARCv8 processor")
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
