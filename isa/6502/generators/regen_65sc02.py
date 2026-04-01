#!/usr/bin/env python3
"""Regenerate 65SC02 Verilog (Atari Lynx CPU variant).

The WDC 65SC02 is a variant of the 65C02:

- Full BCD (decimal mode) support
- New instructions: PHX, PHY, PLX, PLY (push/pull X and Y registers)
- New instruction: BRA (unconditional relative branch)
- New instruction: STZ (store zero) with multiple addressing modes
- TRB/TSB instructions ARE included (test and reset/set bits)
- NO Rockwell bit instructions (RMB, SMB, BBR, BBS) - not implemented anyway
- NO WAI/STP instructions - not implemented anyway

The "SC" in 65SC02 stands for "Static Core" - it has reduced power consumption
and no clock stretching. It lacks the Rockwell bit manipulation extensions
(RMB/SMB/BBR/BBS) but DOES include the standard WDC TRB/TSB instructions.

This script generates a 65SC02 core used in the Atari Lynx handheld.

NOTE: Since we haven't implemented the Rockwell extensions (BBR, BBS, RMB, SMB)
or WAI/STP, the 65SC02 is currently identical to our 65C02 implementation.
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

# Merge all instruction graphs with BCD and 65C02 extensions
# 65SC02 has TRB/TSB (unlike what I initially thought)
# It lacks Rockwell extensions (RMB/SMB/BBR/BBS) which we don't have anyway
print("Merging instruction graphs (65SC02 mode - full 65C02 without Rockwell extensions)...")
merged_graph = merge_instructions(instruction_files, defines={
    'CPU_6502_BCD': '1',   # Enable BCD support
    'CPU_65C02': '1',      # Enable 65C02-only instructions
    'CPU_65C02_BIT': '1'   # Enable TRB/TSB (65SC02 HAS these)
    # Note: Rockwell extensions (RMB/SMB/BBR/BBS) not implemented
})

# Set memory port width to 8 bits for byte-addressable memory
mainmem_node = merged_graph.nodes.get('mainmem')
if mainmem_node:
    mainmem_node.data['port_width'] = 8
    mainmem_node.data['element_width'] = 8
    print("Set mainmem port_width=8 for byte-addressable memory")

# Generate Verilog
print("\nGenerating Verilog...")
verilog_code = generate_verilog(merged_graph, module_name="cpu_65sc02_test")

# Write to file
output_file = project_root / "examples/verilog/65sc02_test/65sc02_test.v"
output_file.parent.mkdir(parents=True, exist_ok=True)
output_file.write_text(verilog_code)

print(f"\nGenerated Verilog: {output_file}")
print(f"Module name: cpu_65sc02_test")
print("\nNote: This is a WDC 65SC02 (Atari Lynx) compatible core.")
print("65C02 instructions included: PHX, PHY, PLX, PLY, BRA, STZ, TRB, TSB")
print("65C02 instructions NOT implemented: Rockwell extensions (RMB, SMB, BBR, BBS), WAI, STP")
