#!/usr/bin/env python3
"""
Generate Verilog from the AES ILA resource graph.

This script generates synthesizable Verilog for the AES-128 accelerator
from the optimized LUT-based resource graph.
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from frontends.ila.ila_parser_real import RealILAParser
from frontends.ila.accelerator_verilog_generator import ILAVerilogGenerator


def generate_aes_verilog(json_file: str, output_file: str):
    """
    Generate Verilog from AES JSON.

    Args:
        json_file: Path to aes128_function_lut.json or aes_full_lut.json
        output_file: Path to output .v file
    """
    print(f"=== Generating Verilog for AES ===")
    print(f"Input: {json_file}")
    print(f"Output: {output_file}")

    # Parse the JSON
    print("\n1. Parsing AES JSON...")
    parser = RealILAParser()
    with open(json_file, 'r') as f:
        data = json.load(f)

    graph = parser.parse_json(data)
    print(f"   Parsed: {len(graph.nodes)} nodes, {len(graph.edges)} edges")

    # Determine module name from JSON
    ila_name = data.get('t', {}).get('n', 'aes_module')
    print(f"   ILA name: {ila_name}")

    # Generate Verilog
    print("\n2. Generating Verilog...")
    generator = ILAVerilogGenerator(graph, module_name=ila_name.lower())

    try:
        verilog_code = generator.generate()
        print(f"   Generated: {len(verilog_code)} characters")
        print(f"   Lines: {verilog_code.count(chr(10))}")

        # Write to file
        with open(output_file, 'w') as f:
            f.write(verilog_code)

        print(f"\n✓ Verilog written to: {output_file}")

        # Show sample
        print("\n3. Verilog Preview (first 1000 chars):")
        print("=" * 70)
        print(verilog_code[:1000])
        print("=" * 70)

        return verilog_code

    except Exception as e:
        print(f"\n✗ Error generating Verilog: {e}")
        import traceback
        traceback.print_exc()
        return None


def analyze_aes_graph_for_verilog(json_file: str):
    """
    Analyze the AES graph to understand what needs to be generated.
    """
    print(f"\n=== Analyzing AES Graph for Verilog Generation ===")

    parser = RealILAParser()
    with open(json_file, 'r') as f:
        data = json.load(f)

    graph = parser.parse_json(data)

    # Analyze node types
    print("\nNode Type Distribution:")
    node_types = {}
    for node in graph.nodes.values():
        if isinstance(node.data, dict):
            node_type = node.data.get('type', 'unknown')
            node_types[node_type] = node_types.get(node_type, 0) + 1

    for node_type, count in sorted(node_types.items(), key=lambda x: -x[1]):
        print(f"  {node_type:30s}: {count:5d}")

    # Find ISA states
    print("\nISA States (registers):")
    states = [n for n in graph.nodes.values()
              if isinstance(n.data, dict) and n.data.get('type') == 'isa_state']

    for state in states:
        name = state.data.get('name', state.id)
        sort = state.data.get('sort', {})
        width = sort.get('w', '?')
        print(f"  {name:20s}: {width}-bit")

    # Find instructions
    print("\nInstructions (FSM states):")
    instructions = [n for n in graph.nodes.values()
                    if isinstance(n.data, dict) and n.data.get('type') == 'instruction']

    for instr in instructions:
        name = instr.data.get('name', instr.id)
        print(f"  {name}")

    # Find operations
    print("\nOperation Types:")
    ops = {}
    for node in graph.nodes.values():
        if isinstance(node.data, dict) and node.data.get('type') == 'operation':
            op = node.data.get('operation', 'unknown')
            ops[op] = ops.get(op, 0) + 1

    for op, count in sorted(ops.items(), key=lambda x: -x[1])[:15]:
        print(f"  {op:30s}: {count:5d}")

    print(f"\n✓ Analysis complete")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Generate Verilog from AES ILA resource graph'
    )

    parser.add_argument(
        'input',
        help='Input JSON file (aes128_function_lut.json or aes_full_lut.json)',
        default='test_data/aes128_function_lut.json',
        nargs='?'
    )

    parser.add_argument(
        'output',
        help='Output Verilog file',
        default='aes_generated.v',
        nargs='?'
    )

    parser.add_argument(
        '--analyze-only',
        action='store_true',
        help='Only analyze the graph, don\'t generate Verilog'
    )

    args = parser.parse_args()

    # Check if file exists
    if not Path(args.input).exists():
        print(f"✗ Error: Input file not found: {args.input}")
        print("\nAvailable AES JSON files:")
        for f in Path('test_data').glob('aes*.json'):
            print(f"  {f}")
        return 1

    if args.analyze_only:
        analyze_aes_graph_for_verilog(args.input)
        return 0

    # Generate Verilog
    verilog = generate_aes_verilog(args.input, args.output)

    if verilog:
        print("\n✓ SUCCESS: Verilog generation complete")
        print(f"\nNext steps:")
        print(f"  1. Syntax check: verilator --lint-only {args.output}")
        print(f"  2. Simulate: iverilog {args.output}")
        print(f"  3. Synthesize: yosys -p 'read_verilog {args.output}; synth'")
        return 0
    else:
        print("\n✗ FAILED: Could not generate Verilog")
        return 1


if __name__ == '__main__':
    exit(main())
