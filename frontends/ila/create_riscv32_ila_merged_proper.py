#!/usr/bin/env python3
"""
Properly merge all RV32I ILA instruction graphs using ResourceGraphMerger.

This creates a merged graph with decode logic and multiplexers,
just like the ISA merged graph.
"""

import os
import sys
# Add parent directory to path to import root modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from core.graph_merger import ResourceGraphMerger

def main():
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Directory containing individual ILA JSON files
    # These are extracted from the full pico_full.json model
    ila_dir = os.path.join(script_dir, "test_data/riscv/pico")

    if not os.path.exists(ila_dir):
        print(f"Error: Directory {ila_dir} not found")
        return 1

    # Get all ILA JSON files
    json_files = sorted([f for f in os.listdir(ila_dir) if f.endswith('.json')])

    print(f"Found {len(json_files)} ILA instruction files")
    print()

    # Create merger
    merger = ResourceGraphMerger()

    # Add each instruction
    for json_file in json_files:
        file_path = os.path.join(ila_dir, json_file)
        # Extract instruction name: riscv_add.json -> ADD
        instr_name = json_file.replace('riscv_', '').replace('.json', '').upper()

        print(f"Adding {instr_name} from {file_path}")
        success = merger.add_instruction(instr_name, file_path)

        if not success:
            print(f"  ✗ Failed to add {instr_name}")
            return 1
        print(f"  ✓ Added {instr_name}")

    print()
    print("Merging all instruction graphs...")

    # Merge all graphs
    try:
        merged_graph = merger.merge_graphs()
        print(f"  ✓ Merged successfully")
    except Exception as e:
        print(f"  ✗ Merge failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Save merged graph
    output_file = os.path.join(script_dir, "test_data/riscv/riscv32_ila_merged_proper.rgraph")
    merged_graph.save_to_file(output_file)

    print()
    print("=" * 60)
    print("MERGED ILA GRAPH STATISTICS (PROPER MERGE)")
    print("=" * 60)
    print(f"Output file: {output_file}")
    print(f"Total nodes: {len(merged_graph.nodes)}")
    print(f"Total edges: {len(merged_graph.edges)}")
    print()

    # Count node types
    from collections import Counter
    node_types = Counter()
    for node in merged_graph.nodes.values():
        node_type = node.data.get('type', 'unknown')
        node_types[node_type] += 1

    print("Node type distribution:")
    for node_type, count in sorted(node_types.items()):
        print(f"  {node_type:30s}: {count:4d}")

    print()
    print("This merged graph should now have:")
    print("  • Shared state nodes (rf, pc, dmem)")
    print("  • Decode logic for instruction selection")
    print("  • Multiplexers for result selection")
    print("  • Instruction enable signals")
    print("  • No explicit 'instruction' nodes")
    print("=" * 60)

    return 0


if __name__ == '__main__':
    sys.exit(main())
