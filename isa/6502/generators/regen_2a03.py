#!/usr/bin/env python3
"""Regenerate 2A03/2A07 Verilog (NES CPU variant).

The Ricoh 2A03 (NTSC) and 2A07 (PAL) are 6502 variants used in the Nintendo
Entertainment System (NES/Famicom). These CPUs are nearly identical to the
NMOS 6502 except:

- No decimal mode (BCD): The D flag exists but ADC/SBC always use binary mode
- Built-in audio processing unit (APU) - not modeled here
- Built-in controller I/O - not modeled here

This script generates a 6502 core without BCD support, matching 2A03/2A07 behavior.
For the standard 6502 with BCD, use regen_6502.py instead.
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

# Merge all instruction graphs WITHOUT BCD support (2A03 mode)
# By not defining CPU_6502_BCD, the #else branches are taken in ADC/SBC
print("Merging instruction graphs (2A03 mode - no BCD)...")
merged_graph = merge_instructions(instruction_files)

# Set memory port width to 8 bits for byte-addressable memory
mainmem_node = merged_graph.nodes.get('mainmem')
if mainmem_node:
    mainmem_node.data['port_width'] = 8
    mainmem_node.data['element_width'] = 8
    print("Set mainmem port_width=8 for byte-addressable memory")

# Generate Verilog
print("\nGenerating Verilog...")
verilog_code = generate_verilog(merged_graph, module_name="cpu_2a03_test")

# Write to file
output_file = project_root / "examples/verilog/2a03_test/2a03_test.v"
output_file.parent.mkdir(parents=True, exist_ok=True)
output_file.write_text(verilog_code)

print(f"\nGenerated Verilog: {output_file}")
print(f"Module name: cpu_2a03_test")
print("\nNote: This is a 2A03/2A07 (NES) compatible core without decimal mode.")
