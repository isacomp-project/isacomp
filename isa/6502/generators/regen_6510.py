#!/usr/bin/env python3
"""Regenerate 6510 Verilog (Commodore 64 CPU variant).

The MOS 6510 is the CPU used in the Commodore 64. It is essentially a 6502 with:

- Full BCD (decimal mode) support (identical to NMOS 6502)
- Built-in bidirectional I/O port at addresses $00 (DDR) and $01 (Port)
- Used for memory banking and cassette/keyboard control in C64

IMPLEMENTATION NOTE:
The I/O port at $00-$01 is NOT modeled in this ISA specification because it is
a peripheral feature rather than a core CPU instruction behavior. The I/O port
should be implemented in the system integration/testbench by intercepting
memory accesses to addresses $0000 and $0001.

The generated core is instruction-compatible with the 6510 for all other
memory addresses.
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

# Merge all instruction graphs with BCD support enabled (6510 has BCD like standard 6502)
print("Merging instruction graphs (6510 mode - with BCD)...")
merged_graph = merge_instructions(instruction_files, defines={'CPU_6502_BCD': '1'})

# Set memory port width to 8 bits for byte-addressable memory
mainmem_node = merged_graph.nodes.get('mainmem')
if mainmem_node:
    mainmem_node.data['port_width'] = 8
    mainmem_node.data['element_width'] = 8
    print("Set mainmem port_width=8 for byte-addressable memory")

# Generate Verilog
print("\nGenerating Verilog...")
verilog_code = generate_verilog(merged_graph, module_name="cpu_6510_test")

# Write to file
output_file = project_root / "examples/verilog/6510_test/6510_test.v"
output_file.parent.mkdir(parents=True, exist_ok=True)
output_file.write_text(verilog_code)

print(f"\nGenerated Verilog: {output_file}")
print(f"Module name: cpu_6510_test")
print("\nNote: This is a MOS 6510 (C64) compatible core.")
print("The I/O port at $00-$01 should be implemented in system integration.")
