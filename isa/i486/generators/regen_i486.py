#!/usr/bin/env python3
"""Regenerate i486 Verilog with all implemented instructions."""

import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from core.graph_merger import merge_instructions
from backends.verilog import generate_verilog

# Get all i486 ISA files
isa_dir = project_root / "isa/i486"
isa_files = sorted(isa_dir.glob("*.isa"))

print(f"Found {len(isa_files)} ISA files in i486/")

# Create instruction files dict
instruction_files = {f.stem: str(f) for f in isa_files}

# Merge all instruction graphs
print("Merging instruction graphs...")
merged_graph = merge_instructions(instruction_files)

# Generate Verilog
print("Generating Verilog...")
verilog_code = generate_verilog(merged_graph, module_name="cpu_i486_targeted")

# Write to output file
output_file = project_root / "examples/verilog/i486_test/i486_targeted_merged.v"
output_file.parent.mkdir(parents=True, exist_ok=True)
output_file.write_text(verilog_code)

print(f"Generated Verilog written to: {output_file}")
print(f"Module name: cpu_i486_targeted")
print(f"File size: {len(verilog_code):,} bytes")
