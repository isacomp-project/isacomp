#!/usr/bin/env python3
"""
Generate J4 (SuperH-4) processor with MMU support.

This generator creates a J4 processor with software-managed TLB
using CAM-based address translation, similar to the MIPS32 MMU generator.

Usage:
  python generate_j4_mmu.py                    # Generate with MMU
  python generate_j4_mmu.py --output-dir path  # Custom output directory
"""
import sys
import os
import re
import argparse

# Add parent directories to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core.graph_merger import ResourceGraphMerger
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec
from backends.verilog import generate_verilog_with_testbench

# Import instruction list from complete generator
from isa.j4.generators.generate_j4_complete import INSTRUCTIONS


def fix_utlb_lookup_vpn_mux(verilog_path):
    """
    Post-process generated Verilog to fix UTLB lookup VPN muxing.

    The Verilog generator creates separate lookup_vpn variables for load (movl)
    and store (movl_store) instructions, but only uses one of them for the
    CAM comparisons. This fix:

    1. Adds a muxed data_lookup_vpn that selects store VPN when store is active
    2. Updates all UTLB CAM comparisons to use the muxed VPN

    This ensures both load and store instructions use their correct VPN for TLB lookup.
    """
    print("\n  Post-processing: Fixing UTLB lookup VPN mux for data accesses...")

    with open(verilog_path, 'r') as f:
        content = f.read()

    # Check if fix is needed
    if 'movl_store_lookup_vpn' not in content:
        print("    No movl_store_lookup_vpn found, skipping fix")
        return False

    if 'data_lookup_vpn' in content:
        print("    data_lookup_vpn already exists, skipping fix")
        return False

    # Find the wire declaration section (after movl_lookup_vpn declaration)
    # Add the muxed VPN wire declaration
    decl_pattern = r'(    wire \[21:0\] movl_lookup_vpn;)'
    decl_replacement = r'''\1
    wire [21:0] data_lookup_vpn;  // Muxed VPN for load/store UTLB lookup'''

    content, decl_count = re.subn(decl_pattern, decl_replacement, content)
    if decl_count == 0:
        print("    WARNING: Could not find movl_lookup_vpn declaration")
        return False

    # Find the assignment section and add the mux assignment
    # Add after movl_lookup_vpn assignment
    assign_pattern = r'(    assign movl_lookup_vpn = movl_addr_31_10;)'
    assign_replacement = r'''\1
    // Mux VPN for load vs store: use store address when store is active
    assign data_lookup_vpn = movl_store_enable ? movl_store_lookup_vpn : movl_lookup_vpn;'''

    content, assign_count = re.subn(assign_pattern, assign_replacement, content)
    if assign_count == 0:
        print("    WARNING: Could not find movl_lookup_vpn assignment")
        return False

    # Replace all UTLB CAM comparisons to use data_lookup_vpn
    # The generator may use either movl_lookup_vpn or movl_store_lookup_vpn
    # We need to handle both cases
    cam_count = 0

    # Pattern 1: (utlb_vpn[N] == movl_lookup_vpn)
    cam_pattern1 = r'\(utlb_vpn\[(\d+)\] == movl_lookup_vpn\)'
    cam_replacement = r'(utlb_vpn[\1] == data_lookup_vpn)'
    content, count1 = re.subn(cam_pattern1, cam_replacement, content)
    cam_count += count1

    # Pattern 2: (utlb_vpn[N] == movl_store_lookup_vpn)
    cam_pattern2 = r'\(utlb_vpn\[(\d+)\] == movl_store_lookup_vpn\)'
    content, count2 = re.subn(cam_pattern2, cam_replacement, content)
    cam_count += count2

    # Write back
    with open(verilog_path, 'w') as f:
        f.write(content)

    print(f"    Fixed: Added data_lookup_vpn mux, updated {cam_count} CAM comparisons")
    return True


def main():
    parser = argparse.ArgumentParser(description='Generate J4 processor with MMU support')
    parser.add_argument(
        '--output-dir', '-o',
        default='examples/verilog/j4_mmu',
        help='Output directory (default: examples/verilog/j4_mmu)'
    )
    parser.add_argument(
        '--output',
        help='Output Verilog file path (alternative to --output-dir)'
    )

    args = parser.parse_args()

    # Handle output path
    if args.output:
        # If --output is specified, use its directory
        output_dir = os.path.dirname(args.output) or '.'
    else:
        output_dir = args.output_dir

    module_name = 'j4_complete'

    print("=" * 70)
    print("J4 (SuperH-4) + MMU PROCESSOR GENERATOR")
    print("=" * 70)
    print(f"Instructions: {len(INSTRUCTIONS)}")
    print("MMU: Enabled (CAM-based TLB)")
    print("=" * 70)

    print(f"\nInstructions: {', '.join(INSTRUCTIONS[:10])}...")

    # Build ISA file paths from j4/mmu/ directory
    print("\nParsing and merging ISA files...")
    isa_files = {}

    for instr in INSTRUCTIONS:
        isa_files[instr] = f"isa/j4/mmu/{instr}.isa"

    # Create merger with MMU preprocessing enabled
    defines = {'MMU': ''}
    merger = ResourceGraphMerger(defines=defines)

    # Add all instructions
    for instr_name, isa_file in isa_files.items():
        if not os.path.exists(isa_file):
            print(f"  WARNING: {isa_file} not found, skipping {instr_name}")
            continue
        success = merger.add_instruction(instr_name, isa_file)
        if not success:
            raise ValueError(f"Failed to add instruction {instr_name} from {isa_file}")
        print(f"  Added: {instr_name}")

    # Merge all instructions
    merged_graph = merger.merge_graphs()
    print(f"\nMerged graph has {len(merged_graph.nodes)} nodes and {len(merged_graph.edges)} edges")
    print("MMU enabled: CAM-based TLB with 64 UTLB entries, 4 ITLB entries")

    # Apply memory port width transformation for sub-word accesses
    print("\nApplying memory transformations...")
    umem_node = merged_graph.nodes.get('umem')
    if umem_node:
        access_widths = umem_node.data.get('access_widths', [32])
        max_width = max(access_widths) if access_widths else 32
        print(f"  umem access widths: {access_widths}, max: {max_width}")

        if max_width != 32 or len(access_widths) > 1:
            transform = MemoryAccessTransform(merged_graph)
            spec = MemoryAccessTransformSpec(
                memory='umem',
                strategy='set_port_width',
                current_width=max_width,
                target_width=32,
                direction='forward',
                endianness='big'  # J4/SH4 is big-endian
            )
            result = transform.apply_transformation(spec)
            if result.get('transformed'):
                print(f"  Transformed: added {len(result.get('nodes_added', []))} byte mux nodes")

    # Generate Verilog
    print("\n" + "=" * 70)
    print("Generating Verilog...")
    print("=" * 70)

    try:
        files = generate_verilog_with_testbench(
            merged_graph,
            module_name=module_name,
            output_dir=output_dir
        )

        print(f"\n  Generated files:")
        for key, path in files.items():
            if hasattr(path, 'stat'):
                file_size = path.stat().st_size if path.exists() else 0
                print(f"    {key.upper()}: {path} ({file_size:,} bytes)")
            else:
                print(f"    {key.upper()}: {path}")

        # Post-process Verilog to fix UTLB lookup VPN muxing for stores
        verilog_file = files.get('rtl')
        if verilog_file:
            fix_utlb_lookup_vpn_mux(str(verilog_file))

    except Exception as e:
        print(f"  Error generating Verilog: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"  Successfully generated J4+MMU processor")
    print(f"  {len(INSTRUCTIONS)} instructions implemented")
    print(f"  {len(merged_graph.nodes)} nodes in merged graph")
    print(f"  {len(merged_graph.edges)} edges in merged graph")
    print(f"  Output: {output_dir}/")

    print("\n" + "=" * 70)
    print("Done!")
    print("=" * 70)


if __name__ == "__main__":
    main()
