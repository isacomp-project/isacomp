#!/usr/bin/env python3
"""Regenerate M68000 Verilog with all implemented instructions."""

import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from core.graph_merger import merge_instructions
from backends.verilog import generate_verilog
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec


def apply_memory_transform(merged_graph):
    """Apply port width setting for M68K memory.

    M68K has byte (8-bit), word (16-bit), and long (32-bit) memory accesses.
    This transformation creates byte selection muxes for sub-word accesses.
    M68K is big-endian, like J2/SH2.
    """
    dmem_node = merged_graph.nodes.get('dmem')
    if dmem_node:
        access_widths = dmem_node.data.get('access_widths', [32])
        max_width = max(access_widths) if access_widths else 32
        print(f"  dmem access widths: {access_widths}, max: {max_width}")

        # Apply set_port_width transformation to create byte selection mux nodes
        transform = MemoryAccessTransform(merged_graph)
        spec = MemoryAccessTransformSpec(
            memory='dmem',
            strategy='set_port_width',
            current_width=max_width,
            target_width=32,  # 32-bit port with byte selection
            direction='forward',
            endianness='big'  # M68K is big-endian
        )
        result = transform.apply_transformation(spec)
        if result.get('transformed'):
            print(f"  Transformed: added {len(result.get('nodes_added', []))} byte mux nodes")
        else:
            print(f"  Skipped: {result.get('reason', 'unknown')}")
    else:
        print("  Warning: dmem node not found in graph")


def main():
    # Get all m68k ISA files
    isa_dir = project_root / "isa" / "m68k"
    isa_files = sorted(isa_dir.glob("*.isa"))

    print(f"Found {len(isa_files)} ISA files in isa/m68k/")

    # Create instruction files dict
    instruction_files = {f.stem: str(f) for f in isa_files}

    # Merge all instruction graphs
    print("Merging instruction graphs...")
    merged_graph = merge_instructions(instruction_files)

    # Apply memory port width transformation
    print("Applying memory access transform...")
    apply_memory_transform(merged_graph)

    # Generate Verilog
    print("Generating Verilog...")
    verilog_code = generate_verilog(merged_graph, module_name="cpu_m68k_test")

    # Write to output file
    output_file = project_root / "examples/verilog/m68k_test/m68k_test.v"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(verilog_code)

    # Also update m68k_full.v for tests
    full_output = project_root / "examples/verilog/m68k_full.v"
    full_output.write_text(verilog_code)

    print(f"Generated Verilog written to: {output_file}")
    print(f"Also copied to: {full_output}")
    print(f"Module name: cpu_m68k_test")
    print(f"PC name: pc (program counter)")


if __name__ == "__main__":
    main()
