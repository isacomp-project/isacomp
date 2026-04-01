#!/usr/bin/env python3
"""
Generate complete Zarf (H-Machine) processor from ISA definitions.

The Zarf machine is a lazy functional processor with:
- 5 core instructions (apply, return, case, pattern_literal, pattern_cons)
- 18 built-in primitives (arithmetic, comparison, bitwise, I/O)
- Continuation-based execution model
- Heap-allocated thunks and constructors

Supports Verilog backend via --backend argument.
"""
import sys
import os
import argparse

# Add parent directories to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core.graph_merger import merge_instructions
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec

# Core instructions (6 opcodes)
INSTRUCTIONS = [
    'apply',           # Opcode 0x1 - Create thunk or apply function
    'return',          # Opcode 0x2 - Return value from function
    'case',            # Opcode 0x3 - Begin pattern matching
    'pattern_literal', # Opcode 0x4 - Match integer literal
    'pattern_cons',    # Opcode 0x5 - Match constructor
    'builtin',         # Opcode 0x6 - Execute built-in primitive
]

# Built-in primitives (function indices 0x00-0xFF)
BUILTINS = [
    'error',    # 0x00 - Runtime error
    'add',      # 0x01 - Addition
    'sub',      # 0x02 - Subtraction
    'mult',     # 0x03 - Multiplication
    'div',      # 0x04 - Division
    'eq',       # 0x05 - Equality
    'leq',      # 0x06 - Less than or equal
    'and',      # 0x07 - Bitwise AND
    'or',       # 0x08 - Bitwise OR
    'nand',     # 0x09 - Bitwise NAND
    'nor',      # 0x0A - Bitwise NOR
    'xor',      # 0x0B - Bitwise XOR
    'sll',      # 0x0C - Shift left logical
    'srl',      # 0x0D - Shift right logical
    'sra',      # 0x0E - Shift right arithmetic
    'lt',       # 0x0F - Less than
    'neg',      # 0x12 - Negation
    'getint',   # 0x80 - Read integer from input
    'putint',   # 0x81 - Write integer to output
]


MEMORIES = ['imem', 'heap', 'cstack', 'lstack']


def apply_memory_transform(merged_graph):
    """Apply port width setting for word-addressed memories."""
    transform = MemoryAccessTransform(merged_graph)
    for mem_name in MEMORIES:
        mem_node = merged_graph.nodes.get(mem_name)
        if not mem_node:
            continue
        access_widths = mem_node.data.get('access_widths', [32])
        max_width = max(access_widths) if access_widths else 32
        print(f"  {mem_name} access widths: {access_widths}, max: {max_width}")

        spec = MemoryAccessTransformSpec(
            memory=mem_name,
            strategy='set_port_width',
            current_width=max_width,
            target_width=32,
            direction='forward'
        )
        result = transform.apply_transformation(spec)
        if result.get('transformed'):
            print(f"  Transformed {mem_name}: added {len(result.get('nodes_added', []))} nodes")
        else:
            print(f"  {mem_name}: {result.get('reason', 'skipped')}")


def generate_verilog(merged_graph, module_name, output_dir):
    """Generate Verilog output."""
    from backends.verilog.verilog_generator import VerilogGenerator
    from pathlib import Path

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Generate RTL
    generator = VerilogGenerator(merged_graph, module_name)
    verilog_code = generator.generate()

    rtl_file = output_path / f"{module_name}.v"
    rtl_file.write_text(verilog_code)

    files = {'rtl': rtl_file}

    # Generate a simple testbench (only if one doesn't already exist)
    tb_file = output_path / f"{module_name}_tb.sv"
    if not tb_file.exists():
        tb_code = generate_zarf_testbench(module_name)
        tb_file.write_text(tb_code)
    files['testbench'] = tb_file

    return files


def generate_zarf_testbench(module_name):
    """Generate a simple testbench for the Zarf processor."""
    tb = []
    tb.append("`timescale 1ns/1ps\n\n")
    tb.append(f"module {module_name}_tb;\n\n")
    tb.append("    // Clock and reset\n")
    tb.append("    reg clk;\n")
    tb.append("    reg reset;\n\n")

    tb.append("    // External I/O\n")
    tb.append("    reg [31:0] io_in;\n")
    tb.append("    reg io_in_ready;\n")
    tb.append("    wire [31:0] io_out;\n")
    tb.append("    wire io_out_valid;\n\n")

    tb.append("    // Halt detection\n")
    tb.append("    wire halted;\n")
    tb.append("    wire [7:0] error_code;\n\n")

    tb.append("    // DUT instantiation\n")
    tb.append(f"    {module_name} dut (\n")
    tb.append("        .clk(clk),\n")
    tb.append("        .reset(reset)\n")
    tb.append("        // TODO: Connect I/O and halt signals based on generated ports\n")
    tb.append("    );\n\n")

    tb.append("    // Clock generation\n")
    tb.append("    always #5 clk = ~clk;\n\n")

    tb.append("    // Test sequence\n")
    tb.append("    integer cycle_count;\n\n")

    tb.append("    initial begin\n")
    tb.append("        $dumpfile(\"zarf_tb.vcd\");\n")
    tb.append("        $dumpvars(0, dut);\n\n")

    tb.append("        clk = 0;\n")
    tb.append("        reset = 1;\n")
    tb.append("        io_in = 32'd0;\n")
    tb.append("        io_in_ready = 0;\n")
    tb.append("        cycle_count = 0;\n\n")

    tb.append("        // Load program into instruction memory\n")
    tb.append("        // $readmemh(\"program.hex\", dut.imem);\n\n")

    tb.append("        // Release reset\n")
    tb.append("        repeat(3) @(posedge clk);\n")
    tb.append("        reset = 0;\n\n")

    tb.append("        // Run for up to 10000 cycles\n")
    tb.append("        for (cycle_count = 0; cycle_count < 10000; cycle_count = cycle_count + 1) begin\n")
    tb.append("            @(posedge clk);\n")
    tb.append("            // Check for halt condition\n")
    tb.append("            // if (dut.halted) begin\n")
    tb.append("            //     if (dut.error_code == 0)\n")
    tb.append("            //         $display(\"Program completed successfully at cycle %d\", cycle_count);\n")
    tb.append("            //     else\n")
    tb.append("            //         $display(\"Program halted with error %d at cycle %d\", dut.error_code, cycle_count);\n")
    tb.append("            //     $finish;\n")
    tb.append("            // end\n")
    tb.append("        end\n\n")

    tb.append("        $display(\"TIMEOUT after %d cycles\", cycle_count);\n")
    tb.append("        $finish;\n")
    tb.append("    end\n\n")

    tb.append("endmodule\n")

    return "".join(tb)


def main():
    parser = argparse.ArgumentParser(
        description='Generate complete Zarf (H-Machine) processor from ISA definitions'
    )
    parser.add_argument(
        '--backend', '-b',
        choices=['verilog'],
        default='verilog',
        help='Output backend (default: verilog)'
    )
    parser.add_argument(
        '--output-dir', '-o',
        help='Output directory (default: examples/verilog/zarf_complete)'
    )
    parser.add_argument(
        '--instructions-only',
        action='store_true',
        help='Only merge core instructions, skip builtins'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose output'
    )
    args = parser.parse_args()

    module_name = 'zarf_complete'
    output_dir = args.output_dir or f'examples/verilog/{module_name}'

    print("=" * 70)
    print("Zarf (H-Machine) Processor Generator")
    print("=" * 70)

    # Determine which files to merge
    if args.instructions_only:
        files_to_merge = INSTRUCTIONS
        file_type = "instructions"
    else:
        files_to_merge = INSTRUCTIONS  # Start with just instructions
        # Note: Builtins are separate entry points, not merged with main instruction decode
        file_type = "instructions"

    print(f"\nMerging {len(files_to_merge)} {file_type}:")
    print(f"  {', '.join(files_to_merge)}")

    # Step 1: Parse and merge ISA files
    print("\n" + "=" * 70)
    print("Step 1: Parsing and merging ISA files...")
    print("=" * 70)

    # Build file paths
    isa_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    isa_files = {}

    for instr in INSTRUCTIONS:
        isa_files[instr] = os.path.join(isa_base, 'instructions', f'{instr}.isa')

    # Verify files exist
    missing = []
    for name, path in isa_files.items():
        if not os.path.exists(path):
            missing.append(f"  {name}: {path}")

    if missing:
        print("ERROR: Missing ISA files:")
        for m in missing:
            print(m)
        sys.exit(1)

    if args.verbose:
        print("ISA files to merge:")
        for name, path in isa_files.items():
            print(f"  {name}: {path}")

    try:
        merged_graph = merge_instructions(isa_files)
        print(f"  Successfully merged {len(files_to_merge)} {file_type}")
        print(f"  Merged graph has {len(merged_graph.nodes)} nodes and {len(merged_graph.edges)} edges")

        if args.verbose:
            # Print some details about the merged graph
            print("\n  State nodes:")
            for node_name, node in merged_graph.nodes.items():
                if node.data and node.data.get('type') == 'isa_state':
                    print(f"    {node_name}: {node.data}")

            print("\n  Memory nodes:")
            for node_name, node in merged_graph.nodes.items():
                if node.data and node.data.get('type') == 'isa_state mem':
                    print(f"    {node_name}: {node.data}")

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

    # Step 3: Generate RTL
    print("\n" + "=" * 70)
    print(f"Step 3: Generating {args.backend.upper()} RTL...")
    print("=" * 70)
    print(f"  Output directory: {output_dir}")

    try:
        if args.backend == 'verilog':
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
    print(f"  Successfully generated Zarf processor")
    print(f"  {len(files_to_merge)} {file_type} merged")
    print(f"  {len(merged_graph.nodes)} nodes in merged graph")
    print(f"  {len(merged_graph.edges)} edges in merged graph")
    print(f"  Backend: {args.backend.upper()}")
    print(f"  Output: {output_dir}/")

    # Print memory configuration
    print("\n  Memory blocks:")
    print("    imem   - Instruction memory (32K words)")
    print("    heap   - Heap/name table (1M words)")
    print("    cstack - Continuation stack (1M words)")
    print("    lstack - Local stack (1M words)")

    print("\n" + "=" * 70)
    print("Done!")
    print("=" * 70)


if __name__ == "__main__":
    main()
