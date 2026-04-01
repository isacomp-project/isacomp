#!/usr/bin/env python3
"""
Generate Z80 processor with proper memory access transform.

This generator:
1. Collects all Z80 ISA files
2. Merges them into a single processor
3. Applies memory access transform for correct address muxing
4. Generates Verilog output
"""
import sys
import os
import argparse
from pathlib import Path

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.graph_merger import merge_instructions
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec
from backends.verilog import VerilogGenerator


def get_isa_files(isa_dir: Path, skip_patterns: list = None) -> dict:
    """Collect all .isa files from the directory."""
    skip_patterns = skip_patterns or []
    isa_files = {}

    for isa_file in sorted(isa_dir.glob('*.isa')):
        # Skip files matching skip patterns
        if any(pat in isa_file.name for pat in skip_patterns):
            continue

        # Extract instruction name from filename
        instr_name = isa_file.stem
        isa_files[instr_name] = str(isa_file)

    return isa_files


def apply_memory_transform(merged_graph):
    """Apply memory access transform for Z80's 8-bit memory."""
    mainmem_node = merged_graph.nodes.get('mainmem')
    if not mainmem_node:
        print("  Warning: mainmem node not found")
        return

    mem_type = mainmem_node.data.get('type', '')
    if 'mem' not in mem_type:
        print(f"  Warning: mainmem is not a mem type ({mem_type})")
        print("  Memory access transform requires 'mem' type memory declaration")
        return

    access_widths = mainmem_node.data.get('access_widths', [8])
    max_width = max(access_widths) if access_widths else 8
    print(f"  mainmem access widths: {access_widths}, max: {max_width}")

    # Apply set_port_width transformation
    # Z80 has 8-bit data bus, so port width is 8
    transform = MemoryAccessTransform(merged_graph)
    spec = MemoryAccessTransformSpec(
        memory='mainmem',
        strategy='set_port_width',
        current_width=max_width,
        target_width=8,  # Z80's 8-bit data bus
        direction='forward'
    )
    result = transform.apply_transformation(spec)

    if result.get('transformed'):
        print(f"  Transformed: added {len(result.get('nodes_added', []))} nodes")
    else:
        print(f"  Skipped: {result.get('reason', 'unknown')}")


def main():
    parser = argparse.ArgumentParser(description='Generate Z80 processor')
    parser.add_argument('--isa-dir', type=Path,
                        default=Path(__file__).parent.parent,
                        help='Directory containing .isa files')
    parser.add_argument('--output', '-o', type=Path,
                        default=Path(__file__).parent.parent.parent.parent / 'examples' / 'verilog' / 'z80' / 'z80.v',
                        help='Output Verilog file')
    parser.add_argument('--module-name', '-m', type=str, default='processor',
                        help='Module name')
    parser.add_argument('--skip', type=str, nargs='*', default=[],
                        help='Patterns to skip (e.g., "disabled" to skip *.disabled.isa)')
    args = parser.parse_args()

    print(f"Z80 Processor Generator")
    print(f"ISA directory: {args.isa_dir}")

    # Collect ISA files
    isa_files = get_isa_files(args.isa_dir, args.skip)
    print(f"Found {len(isa_files)} ISA files")

    if not isa_files:
        print("Error: No ISA files found")
        sys.exit(1)

    # Merge instructions
    print("\nMerging instructions...")
    merged_graph = merge_instructions(isa_files)
    print(f"Merged graph: {merged_graph}")

    # Apply memory transform
    print("\nApplying memory access transform...")
    apply_memory_transform(merged_graph)

    # Generate Verilog
    print("\nGenerating Verilog...")
    gen = VerilogGenerator(merged_graph, module_name=args.module_name)
    verilog = gen.generate()

    # Write output
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, 'w') as f:
        f.write(verilog)
    print(f"Written to {args.output}")

    # Count instructions
    instr_count = sum(1 for nid in merged_graph.nodes if nid.endswith('_enable'))
    print(f"\nGenerated processor with {instr_count} instructions")


if __name__ == '__main__':
    main()
