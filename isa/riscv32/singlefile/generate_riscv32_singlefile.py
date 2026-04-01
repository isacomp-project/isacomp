#!/usr/bin/env python3
"""
Generate complete RV32I processor from single-file specification.
This uses the riscv32i_singlefile.isa file which contains all 37 RV32I instructions
in a single file using one-hot enable encoding with OR-based result multiplexing.
"""
import sys
import os
# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from core.isa_parser import ISAParser
from backends.verilog import generate_verilog_with_testbench

print("Generating RV32I processor from single-file specification...")
print("Source: riscv32/singlefile/riscv32i_singlefile.isa")

print("\nParsing single-file ISA specification...")
parser = ISAParser()
graph = parser.parse_file('riscv32/singlefile/riscv32i_singlefile.isa', preprocess=False)
print(f"Parsed graph has {len(graph.nodes)} nodes and {len(graph.edges)} edges")

print("\nApplying graph optimizations...")
from core.graph_optimizer import GraphOptimizer
from core.timing_utils import reinfer_timing
from core.graph_merger import split_arch_state_nodes

# Split architectural state nodes first (like pc -> pc_rd + pc_wr)
# This must be done before other optimizations
split_arch_state_nodes(graph)

optimizer = GraphOptimizer(graph)
# Use same settings as multi-file merger - disable alias propagation and nested mux merging
# Note: split_arch_state=False because we already called split_arch_state_nodes() above
optimizer.optimize(enable_all=False, merge_nested_muxes=False, propagate_aliases=False, split_arch_state=False)
print(f"After optimization: {len(graph.nodes)} nodes and {len(graph.edges)} edges")

# Cleanup bypassed edges
print("\nCleaning up bypassed edges...")
optimizer.cleanup_bypassed_edges()

# Reinfer timing
print("Reinferring timing...")
reinfer_timing(graph)

print(f"Final graph: {len(graph.nodes)} nodes and {len(graph.edges)} edges")

print("\nSetting memory port widths...")
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec
transform = MemoryAccessTransform(graph)
for mem_name in ['dmem', 'imem']:
    if mem_name in graph.nodes:
        mem_node = graph.nodes[mem_name]
        bit_width = mem_node.data.get('bit_width', 32)

        spec = MemoryAccessTransformSpec(
            memory=mem_name,
            strategy='set_port_width',
            current_width=bit_width,
            target_width=bit_width,
            direction='forward'
        )
        transform.apply_transformation(spec)

print(f"\nGenerating Verilog to examples/verilog/riscv32i_singlefile/...")
testbench_config = {
    'timeout_cycles': 10000,
    'dmem_name': 'dmem',  # Enable loading into both imem and dmem for unified memory space
    'use_hex_loading': True  # Use $readmemh instead of $elf_load_file for iverilog compatibility
}

files = generate_verilog_with_testbench(
    graph,
    module_name='riscv32i_singlefile',
    output_dir=f'examples/verilog/riscv32i_singlefile',
    testbench_config=testbench_config
)

print("\nGenerated files:")
for key, path in files.items():
    print(f"  {key.upper()}: {path}")

print(f"\nDone! Generated RV32I processor from single-file specification")
print("This processor contains all 37 RV32I instructions with decode logic")
