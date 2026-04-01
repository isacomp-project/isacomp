#!/usr/bin/env python3
"""Regenerate 6507 Verilog (Atari 2600 CPU variant).

The MOS 6507 is the CPU used in the Atari 2600 (VCS). It is a 6502 in a
smaller 28-pin package with:

- Full BCD (decimal mode) support (identical to NMOS 6502)
- Only 13 address lines exposed (A0-A12), giving 8KB address space
- No IRQ or NMI pins (directly usable - RDY pin also missing)

IMPLEMENTATION NOTE:
The 13-bit address limitation is NOT modeled in this ISA specification because
the CPU internally still uses 16-bit addresses - only the external bus is
limited to 13 bits. This is a packaging/pinout difference, not a CPU behavior
difference.

For Atari 2600 implementation, the system integration should mask addresses
to 13 bits (addr & 0x1FFF) at the memory interface level. The generated core
is instruction-compatible with the 6507.

The Atari 2600 does have some TIA-specific behavior that affects memory
mirroring, but this is handled by the TIA chip, not the CPU.
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

# Merge all instruction graphs with BCD support enabled (6507 has BCD like standard 6502)
print("Merging instruction graphs (6507 mode - with BCD)...")
merged_graph = merge_instructions(instruction_files, defines={'CPU_6502_BCD': '1'})

# Set memory port width to 8 bits for byte-addressable memory
mainmem_node = merged_graph.nodes.get('mainmem')
if mainmem_node:
    mainmem_node.data['port_width'] = 8
    mainmem_node.data['element_width'] = 8
    print("Set mainmem port_width=8 for byte-addressable memory")

# Generate Verilog
print("\nGenerating Verilog...")
verilog_code = generate_verilog(merged_graph, module_name="cpu_6507_test")

# Write to file
output_file = project_root / "examples/verilog/6507_test/6507_test.v"
output_file.parent.mkdir(parents=True, exist_ok=True)
output_file.write_text(verilog_code)

print(f"\nGenerated Verilog: {output_file}")
print(f"Module name: cpu_6507_test")
print("\nNote: This is a MOS 6507 (Atari 2600) compatible core.")
print("Address masking to 13 bits should be implemented in system integration.")
