#!/usr/bin/env python3
"""
Generate processor RTL from ISA specifications.

Supports multiple backend formats:
- Verilog (default)
- CIRCT MLIR
"""

import argparse
import sys
from pathlib import Path
from core.isa_parser import ISAParser, parse_isa_file
from core.resource_graph import ResourceGraph
from core.graph_merger import merge_instructions


def main():
    parser = argparse.ArgumentParser(
        description="Generate processor RTL from ISA specifications"
    )
    parser.add_argument(
        "isa_files",
        nargs="+",
        help="ISA specification files (.isa)"
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        help="Output file (default: stdout)"
    )
    parser.add_argument(
        "-f", "--format",
        choices=["verilog", "circt", "mlir"],
        default="verilog",
        help="Output format (default: verilog)"
    )
    parser.add_argument(
        "-m", "--module-name",
        default="processor",
        help="Module name (default: processor)"
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Merge multiple ISA files into single processor"
    )
    parser.add_argument(
        "-D", "--define",
        action="append",
        default=[],
        metavar="NAME[=VALUE]",
        help="Preprocessor define (can be repeated)"
    )
    parser.add_argument(
        "--mem-transform",
        metavar="MEM:ENDIAN",
        action="append",
        default=[],
        help="Apply memory port-width transform (e.g., --mem-transform dmem:big)"
    )

    args = parser.parse_args()

    # Parse defines into dictionary
    defines = {}
    for d in args.define:
        if '=' in d:
            key, value = d.split('=', 1)
            defines[key] = value
        else:
            defines[d] = '1'

    # Parse ISA files
    if len(args.isa_files) == 1 and not args.merge:
        # Single file, parse directly
        print(f"Parsing {args.isa_files[0]}...")
        graph = parse_isa_file(args.isa_files[0], defines=defines)
    else:
        # Multiple files, merge them
        print(f"Parsing and merging {len(args.isa_files)} ISA files...")
        if defines:
            print(f"  with defines: {defines}")
        isa_dict = {Path(f).stem: f for f in args.isa_files}
        graph = merge_instructions(isa_dict, defines=defines)

    print(f"Graph has {len(graph.nodes)} nodes and {len(graph.edges)} edges")

    # Apply memory endianness settings
    for mem_spec in args.mem_transform:
        parts = mem_spec.split(':')
        mem_name = parts[0]
        endianness = parts[1] if len(parts) > 1 else 'little'
        mem_node = graph.nodes.get(mem_name)
        if not mem_node:
            print(f"  Warning: memory '{mem_name}' not found in graph, skipping")
            continue
        mem_node.data['endianness'] = endianness
        access_widths = mem_node.data.get('access_widths', [])
        print(f"  {mem_name}: endianness={endianness}, access_widths={access_widths}")

    # Generate output based on format
    if args.format in ["circt", "mlir"]:
        print(f"\nGenerating CIRCT MLIR...")
        output = graph.generate_circt(args.module_name)
    else:  # verilog
        print(f"\nGenerating Verilog...")
        output = graph.generate_verilog(args.module_name)

    # Write or print output
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output)
        print(f"✓ Written to {args.output}")
    else:
        print("\n" + "="*80)
        print(output)
        print("="*80)

    return 0


if __name__ == "__main__":
    sys.exit(main())
