#!/usr/bin/env python3
"""
Generate RV32I processor from ILA merged resourcegraph (proper merge version).
This uses the properly merged graph from ILA models with decode logic.
"""
import sys
import os
# Add parent directory to path to import root modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from core.resource_graph import ResourceGraph
from backends.verilog import generate_verilog_with_testbench

# Get the directory where this script is located
script_dir = os.path.dirname(os.path.abspath(__file__))

print("Loading ILA properly merged resourcegraph...")
ila_merged_graph = ResourceGraph.load_from_file(os.path.join(script_dir, 'test_data/riscv/riscv32_ila_merged_proper.rgraph'))
print(f"  Loaded: {len(ila_merged_graph.nodes)} nodes, {len(ila_merged_graph.edges)} edges")

# Count instructions
instruction_nodes = [n for n in ila_merged_graph.nodes.values() if n.data.get('type') == 'instruction']
print(f"  Instructions: {len(instruction_nodes)}")

print("\nGenerating Verilog to examples/verilog/riscv32i_ila/...")
testbench_config = {
    'timeout_cycles': 10000
}

# Output directory relative to repo root
verilog_output_dir = os.path.join(script_dir, '../../examples/verilog/riscv32i_ila')

files = generate_verilog_with_testbench(
    ila_merged_graph,
    module_name='riscv32i_ila',
    output_dir=verilog_output_dir,
    testbench_config=testbench_config
)

print("\nGenerated files:")
for key, path in files.items():
    print(f"  {key.upper()}: {path}")

print("\nDone! Generated RV32I processor from ILA properly merged graph")
print(f"Source: ILA models from Princeton IMDb")
print(f"Instructions: All RV32I instructions")
