#!/usr/bin/env python3
"""
Generate OpenPOWER LCS (Linux Compliance Subset) processor for Linux boot.

This generates a processor suitable for Verilator simulation and Linux boot:
- Externalized memory for large address space
- Valid-ready handshake protocol for memory access
- Timer/Decrementer interface for Linux tick
- 64-bit mode support (SF=1)

Based on the complete LCS instruction set (280 instructions).
"""
import sys
import os
import argparse
from pathlib import Path

# Add parent directories to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core.graph_merger import merge_instructions
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec
from opt.memory.memory_externalization import apply_memory_externalization, MemoryExternalizationSpec
from opt.temporal.multi_cycle_operations import apply_multi_cycle_operations, OperationLatencySpec
from backends.verilog import VerilogGenerator

# Import the instruction lists from the complete generator
from isa.openpower.generators.generate_oplcs_complete import (
    SFS_CORE_INSTRUCTIONS,
    EXTENDED_ARITHMETIC_INSTRUCTIONS,
    EXTENDED_LOGICAL_INSTRUCTIONS,
    BIT_MANIPULATION_INSTRUCTIONS,
    BYTE_REVERSE_INSTRUCTIONS,
    ATOMIC_INSTRUCTIONS,
    MULTIPLE_INSTRUCTIONS,
    SYSTEM_INSTRUCTIONS,
    CACHE_BARRIER_INSTRUCTIONS,
    FP_SP_INSTRUCTIONS,
    FP_DP_INSTRUCTIONS,
)

# Integer instructions only for initial Linux boot (no FP)
INTEGER_INSTRUCTIONS = (
    SFS_CORE_INSTRUCTIONS +
    EXTENDED_ARITHMETIC_INSTRUCTIONS +
    EXTENDED_LOGICAL_INSTRUCTIONS +
    BIT_MANIPULATION_INSTRUCTIONS +
    BYTE_REVERSE_INSTRUCTIONS +
    ATOMIC_INSTRUCTIONS +
    MULTIPLE_INSTRUCTIONS +
    SYSTEM_INSTRUCTIONS +
    CACHE_BARRIER_INSTRUCTIONS
)

# Optional: Include FP instructions
FP_INSTRUCTIONS = FP_SP_INSTRUCTIONS + FP_DP_INSTRUCTIONS


def apply_memory_transform(merged_graph):
    """Apply port width setting for 64-bit word-addressed unified memory."""
    mem_node = merged_graph.nodes.get('umem')
    if mem_node:
        access_widths = mem_node.data.get('access_widths', [64])
        max_width = max(access_widths) if access_widths else 64
        print(f"  umem access widths: {access_widths}, max: {max_width}")

        # Apply set_port_width transformation
        # OpenPOWER is big-endian
        transform = MemoryAccessTransform(merged_graph)
        spec = MemoryAccessTransformSpec(
            memory='umem',
            strategy='set_port_width',
            current_width=max_width,
            target_width=64,  # 64-bit word-addressed memory
            direction='forward',
            endianness='big',  # PowerPC is big-endian
            alignment='unaligned'  # Enable cross-DW boundary handling
        )
        result = transform.apply_transformation(spec)
        if result.get('transformed'):
            print(f"  Transformed: added {len(result.get('nodes_added', []))} byte mux nodes")
        else:
            print(f"  Skipped: {result.get('reason', 'unknown')}")
    else:
        print("  No umem node found, skipping memory transform")


def apply_fp_latency(merged_graph):
    """Apply multi-cycle latency for FP div/sqrt operations."""
    fp_div_sqrt_ops = []
    for node_id, node in merged_graph.nodes.items():
        fp_intrinsic = node.data.get('fp_intrinsic', '')
        if fp_intrinsic in ['fp_div', 'fp_sqrt']:
            fp_div_sqrt_ops.append(OperationLatencySpec(
                operation_id=node_id,
                latency_cycles=10
            ))
        elif fp_intrinsic in ['fp_div_d', 'fp_sqrt_d']:
            fp_div_sqrt_ops.append(OperationLatencySpec(
                operation_id=node_id,
                latency_cycles=20
            ))

    if fp_div_sqrt_ops:
        apply_multi_cycle_operations(merged_graph, fp_div_sqrt_ops)
        print(f"  Applied {len(fp_div_sqrt_ops)} multi-cycle FP operation(s)")


def generate_linux_processor(output_dir, include_fp=False, externalized=True):
    """Generate OpenPOWER LCS processor for Linux boot."""

    module_name = 'openpower_lcs_extmem' if externalized else 'openpower_lcs'
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Build instruction list
    instructions = list(INTEGER_INSTRUCTIONS)
    if include_fp:
        instructions.extend(FP_INSTRUCTIONS)

    print("=" * 70)
    print("OPENPOWER LCS LINUX BOOT GENERATOR")
    print("=" * 70)
    print(f"\nGenerating processor with {len(instructions)} instructions...")
    print(f"  Integer: {len(INTEGER_INSTRUCTIONS)}")
    if include_fp:
        print(f"  Floating-Point: {len(FP_INSTRUCTIONS)}")
    print(f"  Externalized memory: {externalized}")

    # Build ISA file paths
    isa_files = {}
    for instr in INTEGER_INSTRUCTIONS:
        isa_files[instr] = f"isa/openpower/{instr}.isa"
    if include_fp:
        for instr in FP_INSTRUCTIONS:
            isa_files[instr] = f"isa/openpower/f/{instr}.isa"

    print("\n" + "=" * 70)
    print("PARSING AND MERGING ISA FILES")
    print("=" * 70)

    merged_graph = merge_instructions(isa_files, defines={'VM': ''})
    print(f"  Merged graph has {len(merged_graph.nodes)} nodes and {len(merged_graph.edges)} edges")
    print("  VM enabled: Radix MMU virtual memory translation active")

    # Apply memory transform
    print("\nApplying memory port width transformation...")
    apply_memory_transform(merged_graph)

    # Apply FP latency if included
    if include_fp:
        print("\nApplying FP operation latencies...")
        apply_fp_latency(merged_graph)

    # Apply memory externalization for Linux boot
    if externalized:
        print("\nApplying memory externalization for Linux boot...")
        ext_spec = MemoryExternalizationSpec(
            memory_name='umem',
            create_read_port=True,
            create_write_port=True,
            variable_latency=True  # Use valid-ready handshake
        )
        apply_memory_externalization(merged_graph, ext_spec)

    print("\n" + "=" * 70)
    print("GENERATING VERILOG")
    print("=" * 70)

    # Generate RTL
    generator = VerilogGenerator(merged_graph, module_name)
    verilog_code = generator.generate()

    rtl_file = output_path / f"{module_name}.v"
    rtl_file.write_text(verilog_code)
    print(f"  Generated: {rtl_file}")

    files = {'rtl': rtl_file}

    # Generate memory wrapper if externalized
    if externalized and generator.externalized_memories:
        for mem_name in generator.externalized_memories:
            wrapper_code = generator.generate_memory_wrapper(mem_name)
            if wrapper_code:
                wrapper_file = output_path / f"{mem_name}_memory.v"
                wrapper_file.write_text(wrapper_code)
                files[f'{mem_name}_wrapper'] = wrapper_file
                print(f"  Generated: {wrapper_file}")

    # Copy platform files to output
    import shutil
    # SV platform files are in examples/verilog/openpower_linux/
    verilog_platform_dir = Path(__file__).parent.parent.parent.parent / 'examples' / 'verilog' / 'openpower_linux'
    if verilog_platform_dir.exists():
        for sv_file in verilog_platform_dir.glob('*.sv'):
            dst = output_path / sv_file.name
            if output_path.resolve() != verilog_platform_dir.resolve():
                shutil.copy(sv_file, dst)
                print(f"  Copied: {dst}")

    # Copy DTS and other platform config files
    platform_dir = Path(__file__).parent.parent / 'platform'
    if platform_dir.exists():
        for f in platform_dir.glob('*.dts'):
            dst = output_path / f.name
            shutil.copy(f, dst)
            print(f"  Copied: {dst}")

    print("\n" + "=" * 70)
    print("GENERATION COMPLETE")
    print("=" * 70)
    print(f"\nOpenPOWER LCS processor generated for Linux boot!")
    print(f"\nOutput files in: {output_path}")
    print("\nTo build and run:")
    print(f"  cd {output_path}")
    print("  verilator -Wall -Wno-fatal --cc --exe --build linux_boot_tb.sv \\")
    print(f"            {module_name}.v uart16550.sv power_timer.sv -o Vlinux_boot_tb")
    print("  ./obj_dir/Vlinux_boot_tb +kernel=vmlinux.bin")

    return files


def main():
    parser = argparse.ArgumentParser(
        description='Generate OpenPOWER LCS processor for Linux boot'
    )
    parser.add_argument(
        '--output-dir', '-o',
        default='examples/verilog/openpower_linux',
        help='Output directory (default: examples/verilog/openpower_linux)'
    )
    parser.add_argument(
        '--with-fp',
        action='store_true',
        help='Include floating-point instructions'
    )
    parser.add_argument(
        '--no-externalize',
        action='store_true',
        help='Do not externalize memory (for small simulations)'
    )
    args = parser.parse_args()

    generate_linux_processor(
        output_dir=args.output_dir,
        include_fp=args.with_fp,
        externalized=not args.no_externalize
    )


if __name__ == "__main__":
    main()
