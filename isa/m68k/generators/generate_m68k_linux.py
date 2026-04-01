#!/usr/bin/env python3
"""
Generate MC68030 processor from ISA definitions for Linux boot.

This generates a complete MC68030-class processor including:
- Full MC68000 user-mode instruction set (260 instructions)
- Supervisor mode support (RTE, TRAP, SR access, exception handling)
- MC68020 extensions (32-bit multiply/divide, bit fields, CAS, MOVEC)
- MC68030 MMU (PMOVE, PFLUSH, PTEST, ATC translation)

The generated processor is suitable for booting Linux/m68k.

Supports Verilog, VHDL, PyRTL, and CIRCT backends via --backend argument.

MC68000 family features:
- 32-bit big-endian CISC architecture
- 8 data registers (D0-D7), 8 address registers (A0-A7)
- Dual stack pointers (USP/SSP)
- 16-bit Status Register (CCR + supervisor byte)
- 22-entry ATC (Address Translation Cache) for MMU
"""
import sys
import os
import argparse
import tempfile
import shutil
from pathlib import Path

# Add parent directories to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))
# Add generators directory to path
sys.path.insert(0, os.path.dirname(__file__))

from core.graph_merger import merge_instructions
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec
from opt.memory.memory_externalization import MemoryExternalizationSpec, apply_memory_externalization


def get_base_instructions():
    """Get base MC68000 user-mode instructions from the mmu/instructions/ directory."""
    mmu_dir = Path(__file__).parent.parent / 'mmu' / 'instructions'
    # Exclude aspect files - these are included via 'aspect' keyword, not standalone instructions
    ASPECT_FILES = {'m68k_exception', 'm68k_interrupt'}
    isa_files = list(mmu_dir.glob("*.isa"))
    return [f.stem for f in isa_files if f.stem not in ASPECT_FILES]


# Supervisor mode instructions (Phase 1)
SUPERVISOR_INSTRUCTIONS = [
    'supervisor/rte',
    'supervisor/trap',
    'supervisor/trapv',
    'supervisor/illegal',
    'supervisor/chk_w',
    'supervisor/move_to_sr',
    'supervisor/move_to_sr_an_postinc',
    'supervisor/move_from_sr',
    'supervisor/move_from_sr_predec',
    'supervisor/move_from_sr_an_disp',
    'supervisor/move_an_to_usp',
    'supervisor/move_usp_to_an',
    'supervisor/andi_to_sr',
    'supervisor/ori_to_sr',
    'supervisor/eori_to_sr',
    'supervisor/stop',
    'supervisor/reset',
    # Privilege violation traps (vector 8) - fire when supervisor-only
    # instructions are executed in user mode (sr[13]==0)
    'supervisor/move_to_sr_priv',
    'supervisor/stop_priv',
    'supervisor/reset_priv',
    'supervisor/rte_priv',
    'supervisor/move_usp_to_an_priv',
    'supervisor/move_an_to_usp_priv',
    'supervisor/andi_to_sr_priv',
    'supervisor/ori_to_sr_priv',
    'supervisor/eori_to_sr_priv',
    'supervisor/moves_l_dn_an_postinc',
    'supervisor/moves_l_an_postinc_dn',
    'supervisor/moves_w_an_postinc_dn',
    'supervisor/moves_w_dn_an_postinc',
    'supervisor/moves_b_an_postinc_dn',
    'supervisor/moves_b_dn_an_postinc',
]

# MC68020 extended instructions (Phase 2)
MC68020_INSTRUCTIONS = [
    # mc68020/muls_l  - REMOVED: conflicts with per-mode muls_l_dn_dh_dl.isa / muls_l_dn_dn.isa (same Dn enable, OR-mux corrupts result registers)
    # mc68020/mulu_l  - REMOVED: conflicts with per-mode mulu_l_dn_dh_dl.isa / mulu_l_dn_dn.isa (same Dn enable, OR-mux corrupts result registers)
    # mc68020/divsl  - REMOVED: conflicts with per-mode divs_l_dn_dn.isa / divs_l_dn_64.isa (same Dn enable, OR-mux corrupts remainder into quotient register)
    # mc68020/divul  - REMOVED: conflicts with per-mode divu_l_dn_dn.isa / divu_l_dn_64.isa (same Dn enable, OR-mux corrupts remainder into quotient register)
    'mc68020/movec',
    'mc68020/moves',
    'mc68020/cas',
    'mc68020/cas2',
    # mc68020/bfextu - REMOVED: conflicts with per-mode bfextu_dn.isa (same Dn enable)
    # mc68020/bfexts - REMOVED: conflicts with per-mode bfexts_dn.isa (same Dn enable)
    # mc68020/bfins  - REMOVED: conflicts with per-mode bfins_dn.isa (same Dn enable)
    'mc68020/bfclr',
    'mc68020/bfset',
    # mc68020/bftst  - REMOVED: conflicts with per-mode bftst_dn.isa (same Dn enable)
    'mc68020/bfchg',
    # mc68020/bfffo  - REMOVED: conflicts with per-mode bfffo_dn.isa (same Dn enable)
    'mc68020/extb',
    'mc68020/rtd',
    'mc68020/trapcc',
]

# MC68030 MMU instructions (Phase 3)
MMU_INSTRUCTIONS = [
    'mmu/pmove_to_tc',
    'mmu/pmove_to_tc_disp',
    'mmu/pmove_from_tc',
    'mmu/pmove_to_crp',
    'mmu/pmove_to_srp',
    'mmu/pmove_to_srp_disp',
    'mmu/pmove_to_tt0',
    'mmu/pmove_to_tt1',
    'mmu/pflusha',
    'mmu/pflush_fc',
    'mmu/ptestr',
    'mmu/ptestw',
    'mmu/pmove_to_crp_disp',
    'mmu/pflush_imm',
    'mmu/ptestr_fc_dn',
    'mmu/pmove_from_mmusr_disp',
]


def apply_memory_transform(merged_graph):
    """Apply port width setting for M68K memory.

    M68K has byte (8-bit), word (16-bit), and long (32-bit) memory accesses.
    This transformation creates byte selection muxes for sub-word accesses.
    M68K is big-endian.
    """
    dmem_node = merged_graph.nodes.get('dmem')
    if dmem_node:
        access_widths = dmem_node.data.get('access_widths', [32])
        max_width = max(access_widths) if access_widths else 32
        print(f"  dmem access widths: {access_widths}, max: {max_width}")

        transform = MemoryAccessTransform(merged_graph)
        spec = MemoryAccessTransformSpec(
            memory='dmem',
            strategy='set_port_width',
            current_width=max_width,
            target_width=32,
            direction='forward',
            endianness='big',
            alignment='unaligned'  # 68020+ supports misaligned memory access
        )
        result = transform.apply_transformation(spec)
        if result.get('transformed'):
            print(f"  Transformed: added {len(result.get('nodes_added', []))} byte mux nodes")
        else:
            print(f"  Skipped: {result.get('reason', 'unknown')}")
    else:
        print("  Warning: dmem node not found in graph")


def generate_verilog(merged_graph, module_name, output_dir, externalized=False):
    """Generate Verilog output."""
    from backends.verilog.verilog_generator import VerilogGenerator

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
        from backends.verilog.verilog_generator import generate_verilog_with_testbench
        testbench_config = {
            'timeout_cycles': 100000
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
        depth = 65536  # 256KB for m68k
        num_bytes = max(1, data_width // 8)
        word_addr_bits = 2 if data_width == 32 else 3

        min_latency = ports.get('min_latency', 0)

        tb.append(f"    // {mem_name} - multi-port memory model\n")
        tb.append(f"    parameter {mem_name.upper()}_MEM_LATENCY = {min_latency};\n")
        tb.append(f"    reg [{data_width-1}:0] {mem_name}_mem [0:{depth-1}];\n\n")

        for rp in ports['read_ports']:
            tb.append(f"    // {rp} read interface - combinational\n")
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
    tb.append("        for (i = 0; i < 100000; i = i + 1) begin\n")
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
        description='Generate MC68030 processor for Linux boot from ISA definitions'
    )
    parser.add_argument(
        '--backend', '-b',
        choices=['verilog', 'vhdl', 'pyrtl', 'circt'],
        default='verilog',
        help='Output backend (default: verilog)'
    )
    parser.add_argument(
        '--output-dir', '-o',
        help='Output directory (default: examples/verilog/m68k_linux)'
    )
    parser.add_argument(
        '--externalize-memory',
        action='store_true',
        help='Externalize data memory (dmem) with valid-ready handshake ports'
    )
    parser.add_argument(
        '--list-instructions',
        action='store_true',
        help='List all included instructions and exit'
    )
    args = parser.parse_args()

    # Build instruction list
    base_instructions = get_base_instructions()
    instructions = base_instructions + SUPERVISOR_INSTRUCTIONS + MC68020_INSTRUCTIONS + MMU_INSTRUCTIONS
    module_name = 'cpu_m68k_linux'
    default_output = 'examples/verilog/m68k_linux'

    output_dir = args.output_dir or default_output

    if args.list_instructions:
        print(f"MC68K Linux Generator - {len(instructions)} instructions")
        print("=" * 60)
        print(f"\nBase MC68000 ({len(base_instructions)} instructions):")
        for i, instr in enumerate(sorted(base_instructions)):
            print(f"  {instr}", end="\n" if (i + 1) % 6 == 0 else "")
        print(f"\n\nSupervisor Mode ({len(SUPERVISOR_INSTRUCTIONS)} instructions):")
        for instr in SUPERVISOR_INSTRUCTIONS:
            print(f"  {instr}")
        print(f"\nMC68020 Extensions ({len(MC68020_INSTRUCTIONS)} instructions):")
        for instr in MC68020_INSTRUCTIONS:
            print(f"  {instr}")
        print(f"\nMC68030 MMU ({len(MMU_INSTRUCTIONS)} instructions):")
        for instr in MMU_INSTRUCTIONS:
            print(f"  {instr}")
        return

    print("=" * 70)
    print(f"MC68K Linux Processor Generator ({args.backend.upper()} backend)")
    print("  Supervisor mode: enabled")
    print("  MC68020 extensions: enabled")
    print("  MMU support: enabled")
    print("=" * 70)
    print(f"\nGenerating MC68K processor with {len(instructions)} instructions...")

    # Step 1: Parse and merge ISA files
    isa_dir = Path(__file__).parent.parent
    mmu_dir = isa_dir / 'mmu' / 'instructions'
    defines = {'MMU': ''}

    print("\n" + "=" * 70)
    print("Step 1: Parsing and merging ISA files...")
    print("=" * 70)

    isa_files = {}
    missing = []

    for instr in instructions:
        # Base instructions resolve directly in mmu/instructions/
        isa_path = mmu_dir / f"{instr}.isa"
        if isa_path.exists():
            isa_files[instr] = str(isa_path)
            continue
        # Subdirectory instructions (supervisor/, mc68020/, mmu/)
        for subdir in ['supervisor', 'mc68020', 'mmu']:
            if instr.startswith(f'{subdir}/'):
                sub_name = instr[len(subdir)+1:]
                sub_path = mmu_dir / subdir / f"{sub_name}.isa"
                if sub_path.exists():
                    isa_files[instr] = str(sub_path)
                    break
        if instr not in isa_files:
            missing.append(instr)

    if missing:
        print(f"  Warning: {len(missing)} ISA files not found:")
        for m in missing[:10]:
            print(f"    - {m}.isa")
        if len(missing) > 10:
            print(f"    ... and {len(missing) - 10} more")

    print(f"  Found {len(isa_files)} ISA files")
    if defines:
        print(f"  Using defines: {defines}")

    try:
        merged_graph = merge_instructions(isa_files, defines=defines)
        print(f"  Successfully merged {len(isa_files)} instructions")
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
            memory_name='dmem',
            create_read_port=True,
            create_write_port=True,
            variable_latency=True
        )
        if apply_memory_externalization(merged_graph, spec):
            print("  Memory externalization applied successfully")
            if not args.output_dir:
                output_dir = f'examples/verilog/m68k_linux_ext' if args.backend == 'verilog' else f'{args.backend}/m68k_linux_ext'
        else:
            print("  Warning: Memory externalization failed")

    # Step 3: Generate RTL
    print("\n" + "=" * 70)
    print(f"Step 3: Generating {args.backend.upper()} RTL and testbench...")
    print("=" * 70)
    print(f"  Module name: {module_name}")
    print(f"  Output directory: {output_dir}")

    try:
        if args.backend == 'verilog':
            files = generate_verilog(merged_graph, module_name, output_dir)
        else:
            print(f"  Backend '{args.backend}' not yet implemented for m68k")
            print("  Use --backend verilog for now")
            sys.exit(1)

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
    print(f"  Successfully generated MC68K processor for Linux boot")
    print(f"  {len(isa_files)} instructions implemented")
    print(f"  {len(merged_graph.nodes)} nodes in merged graph")
    print(f"  {len(merged_graph.edges)} edges in merged graph")
    print(f"  Backend: {args.backend.upper()}")
    print(f"  Module: {module_name}")
    print(f"  Output: {output_dir}/")

    print("\n  Linux boot features:")
    print("    - Full Status Register with supervisor mode")
    print("    - Exception handling (TRAP, RTE, vectors)")
    print("    - 32-bit multiply/divide")
    print("    - Atomic operations (CAS, CAS2)")
    print("    - Control registers (VBR, SFC, DFC, CACR)")
    print("    - 22-entry ATC with CAM-based TLB")
    print("    - MMU control (PMOVE, PFLUSH, PTEST)")

    print("\n" + "=" * 70)
    print("Done!")
    print("=" * 70)


if __name__ == "__main__":
    main()
