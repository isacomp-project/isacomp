#!/usr/bin/env python3
"""Regenerate 6502 Verilog with fixed merger and variable-length instruction support.

This generates the standard NMOS 6502 with full BCD (decimal mode) support.
For the 2A03/2A07 (NES) variant without BCD, use regen_2a03.py instead.

Optional flags:
    --ibuf              Enable instruction buffer optimization
    --ibuf-fetch-width  Fetch width in bits (default: 32)
    --ibuf-size         Buffer FIFO depth in entries (default: 4)
"""

import sys
import argparse
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from core.graph_merger import merge_instructions
from backends.verilog import generate_verilog

# Parse arguments
parser = argparse.ArgumentParser(
    description='Generate 6502 Verilog with optional instruction buffer')
parser.add_argument('--ibuf', action='store_true',
                    help='Enable instruction buffer optimization')
parser.add_argument('--ibuf-fetch-width', type=int, default=32,
                    help='Instruction buffer fetch width in bits (default: 32)')
parser.add_argument('--ibuf-size', type=int, default=4,
                    help='Instruction buffer FIFO depth in entries (default: 4)')
args = parser.parse_args()

# Get all 6502 ISA files
isa_dir = project_root / "6502"
isa_files = sorted(isa_dir.glob("*.isa"))

print(f"Found {len(isa_files)} ISA files")

# Create instruction files dict
instruction_files = {f.stem: str(f) for f in isa_files}

# Merge all instruction graphs with BCD support enabled
print("Merging instruction graphs (with BCD support)...")
merged_graph = merge_instructions(instruction_files, defines={'CPU_6502_BCD': '1'})

# Set memory port width to 8 bits for 6502's byte-addressable memory
# This tells the generator not to use word-aligned addressing
mainmem_node = merged_graph.nodes.get('mainmem')
if mainmem_node:
    mainmem_node.data['port_width'] = 8
    mainmem_node.data['element_width'] = 8
    print("Set mainmem port_width=8 for byte-addressable memory")

# Apply instruction buffer optimization if requested
if args.ibuf:
    from opt.fetch.instruction_buffer_optimization import (
        InstructionBufferSpec,
        apply_instruction_buffer,
        create_instr_length_node,
        create_pc_redirect_signal,
    )

    print("\n=== Applying instruction buffer optimization ===")

    # Create an instruction length node from the merged graph's
    # select_pc_plus_N decode signals
    instr_len_id = create_instr_length_node(merged_graph)
    if instr_len_id is None:
        print("Error: Could not create instruction length node.")
        print("The merged graph may not have variable-length instruction support.")
        sys.exit(1)

    # Create a flush signal that fires on any non-sequential PC change
    # (JMP, BNE taken, JSR, RTS, BRK, RTI, etc.)
    flush_id = create_pc_redirect_signal(merged_graph)

    spec = InstructionBufferSpec(
        imem_node='mainmem',
        pc_node='pc',
        instr_width_node=instr_len_id,
        fetch_width=args.ibuf_fetch_width,
        buffer_size=args.ibuf_size,
        address_width=16,   # 6502 has 16-bit address bus
        data_width=8,        # 6502 fetches bytes
        flush_node=flush_id,          # flush ibuf on branch/jump
        redirect_node='pc_wr' if flush_id else None,  # redirect to new PC
    )

    success = apply_instruction_buffer(merged_graph, spec)
    if success:
        print(f"Instruction buffer applied: fetch_width={args.ibuf_fetch_width}b, "
              f"buffer_size={args.ibuf_size}")
    else:
        print("Warning: Instruction buffer optimization failed, continuing without it.")

# Generate Verilog
print("\nGenerating Verilog...")
verilog_code = generate_verilog(merged_graph, module_name="cpu_6502_test")

# Write to file
output_file = project_root / "examples/verilog/6502_test/6502_test.v"
output_file.parent.mkdir(parents=True, exist_ok=True)
output_file.write_text(verilog_code)

print(f"\nGenerated Verilog: {output_file}")
print(f"Module name: cpu_6502_test")
