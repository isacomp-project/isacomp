#!/usr/bin/env python3
"""Regenerate 65C02 Verilog (CMOS 6502 variant).

The WDC 65C02 is the CMOS version of the 6502 with several enhancements:

- Full BCD (decimal mode) support with correct flags (improved over NMOS)
- New instructions: PHX, PHY, PLX, PLY (push/pull X and Y registers)
- New instruction: BRA (unconditional relative branch)
- New instruction: STZ (store zero) with multiple addressing modes
- New instructions: TRB/TSB (test and reset/set bits)
- Rockwell/WDC extensions: RMB/SMB (reset/set memory bit), BBR/BBS (branch on bit)
- Additional addressing modes for some existing instructions
- Fixed RMW behavior and other bug fixes from NMOS version

This script generates a WDC W65C02 compatible core with all extensions.
Used in Apple IIc, Apple IIe Enhanced, BBC Master, and other systems.
"""

import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from core.graph_merger import merge_instructions
from backends.verilog import generate_verilog

# Get all 6502 ISA files
isa_dir = project_root / "6502"
isa_files = sorted(isa_dir.glob("*.isa"))

print(f"Found {len(isa_files)} ISA files")

# Create instruction files dict
instruction_files = {f.stem: str(f) for f in isa_files}

# Merge all instruction graphs with BCD and 65C02 extensions enabled
print("Merging instruction graphs (WDC W65C02 mode - with all extensions)...")
merged_graph = merge_instructions(instruction_files, defines={
    'CPU_6502_BCD': '1',       # Enable BCD support
    'CPU_65C02': '1',          # Enable 65C02-only instructions
    'CPU_65C02_BIT': '1',      # Enable TRB/TSB bit manipulation instructions
    'CPU_65C02_ROCKWELL': '1'  # Enable Rockwell/WDC extensions (RMB/SMB/BBR/BBS)
})

# Set memory port width to 8 bits for byte-addressable memory
mainmem_node = merged_graph.nodes.get('mainmem')
if mainmem_node:
    mainmem_node.data['port_width'] = 8
    mainmem_node.data['element_width'] = 8
    print("Set mainmem port_width=8 for byte-addressable memory")

# Generate Verilog
print("\nGenerating Verilog...")
verilog_code = generate_verilog(merged_graph, module_name="cpu_65c02_test")

# Write to file
output_file = project_root / "examples/verilog/65c02_test/65c02_test.v"
output_file.parent.mkdir(parents=True, exist_ok=True)
output_file.write_text(verilog_code)

print(f"\nGenerated Verilog: {output_file}")
print(f"Module name: cpu_65c02_test")
print("\nNote: This is a WDC W65C02 compatible core with all extensions.")
print("Includes: PHX, PHY, PLX, PLY, BRA, STZ, TRB, TSB, INC A, DEC A")
print("Rockwell extensions: RMB0-7, SMB0-7, BBR0-7, BBS0-7")
