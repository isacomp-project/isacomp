#!/usr/bin/env python3
"""
Generate TDMI-compatible processor from ISA definitions.

This includes A mode (32-bit) and T mode (16-bit) instructions
for TDMI core compatibility.

Supports Verilog, VHDL, PyRTL, and CIRCT backends via --backend argument.
"""
import sys
import os
import argparse

# Add parent directories to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core.graph_merger import merge_instructions
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec

# A mode instructions (32-bit)
A_INSTRUCTIONS = [
    # Data Processing - Register (no shift)
    'a/add_reg', 'a/sub_reg', 'a/and_reg', 'a/orr_reg',
    'a/eor_reg', 'a/mov_reg', 'a/mvn_reg', 'a/bic_reg',
    'a/rsb_reg', 'a/tst_reg', 'a/cmp_reg',
    'a/teq_reg', 'a/cmn_reg',
    'a/adc_reg', 'a/sbc_reg', 'a/rsc_reg',

    # Data Processing - Register (with immediate shift)
    'a/add_reg_shift', 'a/sub_reg_shift', 'a/and_reg_shift', 'a/orr_reg_shift',
    'a/eor_reg_shift', 'a/mov_reg_shift', 'a/mvn_reg_shift', 'a/bic_reg_shift',
    'a/rsb_reg_shift', 'a/tst_reg_shift', 'a/cmp_reg_shift',
    'a/teq_reg_shift', 'a/cmn_reg_shift',
    'a/adc_reg_shift', 'a/sbc_reg_shift', 'a/rsc_reg_shift',

    # Data Processing - Register (with register shift)
    'a/add_reg_regshift', 'a/sub_reg_regshift', 'a/and_reg_regshift', 'a/orr_reg_regshift',
    'a/eor_reg_regshift', 'a/mov_reg_regshift', 'a/mvn_reg_regshift', 'a/bic_reg_regshift',
    'a/rsb_reg_regshift', 'a/tst_reg_regshift', 'a/cmp_reg_regshift',
    'a/teq_reg_regshift', 'a/cmn_reg_regshift',
    'a/adc_reg_regshift', 'a/sbc_reg_regshift', 'a/rsc_reg_regshift',

    # Data Processing - Immediate
    'a/add_imm', 'a/sub_imm', 'a/mov_imm', 'a/cmp_imm',
    'a/and_imm', 'a/orr_imm', 'a/eor_imm', 'a/bic_imm',
    'a/mvn_imm', 'a/rsb_imm', 'a/tst_imm',
    'a/teq_imm', 'a/cmn_imm',
    'a/adc_imm', 'a/sbc_imm', 'a/rsc_imm',

    # Load/Store Word - Basic (pre-indexed, add, no writeback)
    'a/ldr_imm', 'a/str_imm', 'a/ldr_reg', 'a/str_reg',

    # Load/Store Word - Subtract offset
    'a/ldr_imm_sub', 'a/str_imm_sub', 'a/ldr_reg_sub', 'a/str_reg_sub',

    # Load/Store Word - Register offset with writeback/post-indexed
    'a/ldr_reg_pre_wb', 'a/str_reg_pre_wb',
    'a/ldr_reg_post', 'a/str_reg_post',

    # Load/Store Word - Scaled register offset
    'a/ldr_reg_shift', 'a/str_reg_shift',
    'a/ldr_reg_shift_sub', 'a/str_reg_shift_sub',
    'a/ldr_reg_shift_pre_wb', 'a/str_reg_shift_pre_wb',
    'a/ldr_reg_shift_pre_wb_sub', 'a/str_reg_shift_pre_wb_sub',
    'a/ldr_reg_shift_post', 'a/str_reg_shift_post',
    'a/ldr_reg_shift_post_sub', 'a/str_reg_shift_post_sub',

    # Load/Store Word - Pre-indexed with writeback
    'a/ldr_imm_pre_wb', 'a/str_imm_pre_wb',
    'a/ldr_imm_pre_wb_sub', 'a/str_imm_pre_wb_sub',

    # Load/Store Word - Post-indexed
    'a/ldr_imm_post', 'a/str_imm_post',
    'a/ldr_imm_post_sub', 'a/str_imm_post_sub',

    # Load/Store Byte - Basic and addressing modes
    'a/ldrb_imm', 'a/strb_imm', 'a/ldrb_reg', 'a/strb_reg',
    'a/ldrb_imm_sub', 'a/strb_imm_sub',
    'a/ldrb_imm_pre_wb', 'a/strb_imm_pre_wb',
    'a/ldrb_imm_pre_wb_sub', 'a/strb_imm_pre_wb_sub',
    'a/ldrb_imm_post', 'a/strb_imm_post',
    'a/ldrb_imm_post_sub', 'a/strb_imm_post_sub',

    # Load/Store Byte - Scaled register offset
    'a/ldrb_reg_shift', 'a/strb_reg_shift',
    'a/ldrb_reg_shift_pre_wb', 'a/strb_reg_shift_pre_wb',
    'a/ldrb_reg_shift_post', 'a/strb_reg_shift_post',

    # Load/Store Halfword - Basic and addressing modes
    'a/ldrh_imm', 'a/strh_imm', 'a/ldrh_reg', 'a/strh_reg',
    'a/ldrh_imm_sub', 'a/strh_imm_sub',
    'a/ldrh_imm_pre_wb', 'a/strh_imm_pre_wb',
    'a/ldrh_imm_pre_wb_sub', 'a/strh_imm_pre_wb_sub',
    'a/ldrh_imm_post', 'a/strh_imm_post',
    'a/ldrh_imm_post_sub', 'a/strh_imm_post_sub',

    # Load/Store Halfword - Register offset with writeback/post-indexed
    'a/ldrh_reg_pre_wb', 'a/strh_reg_pre_wb',
    'a/ldrh_reg_post', 'a/strh_reg_post',

    # Load Signed Byte/Halfword
    'a/ldrsb_imm', 'a/ldrsh_imm', 'a/ldrsb_reg', 'a/ldrsh_reg',

    # Branch
    'a/b', 'a/bl', 'a/bx',

    # Multiply
    'a/mul', 'a/mla',

    # Multiply Long
    'a/umull', 'a/smull', 'a/umlal', 'a/smlal',

    # Load/Store Multiple
    'a/ldm_ia', 'a/ldm_ib', 'a/ldm_da', 'a/ldm_db',
    'a/stm_ia', 'a/stm_ib', 'a/stm_da', 'a/stm_db',

    # Load/Store Multiple - User Mode (S=1)
    'a/ldm_ia_user', 'a/ldm_ib_user', 'a/ldm_da_user', 'a/ldm_db_user',
    'a/stm_ia_user', 'a/stm_ib_user', 'a/stm_da_user', 'a/stm_db_user',

    # Atomic Swap
    'a/swp', 'a/swpb',

    # Software Interrupt
    'a/swi',

    # Status Register Access
    'a/mrs_cpsr', 'a/mrs_spsr',
    'a/msr_cpsr_reg', 'a/msr_cpsr_imm',
    'a/msr_spsr_reg', 'a/msr_spsr_imm',
]

# T mode instructions (16-bit)
T_INSTRUCTIONS = [
    # Data Processing
    't/add_reg', 't/sub_reg', 't/mov_imm',
    't/cmp_imm', 't/add_imm',

    # Load/Store
    't/ldr_imm', 't/str_imm',

    # Branch
    't/b', 't/b_uncond',
]

# All instructions
ALL_INSTRUCTIONS = A_INSTRUCTIONS + T_INSTRUCTIONS

# Basic A-mode-only instructions (for testing)
BASIC_A_INSTRUCTIONS = [
    'a/add_reg', 'a/sub_reg', 'a/and_reg', 'a/orr_reg',
    'a/mov_reg', 'a/mov_imm', 'a/cmp_reg', 'a/cmp_imm',
    'a/ldr_imm', 'a/str_imm', 'a/b', 'a/bl',
]


def apply_memory_transform(merged_graph):
    """Apply port width setting for word-addressed unified memory.

    TDMI has byte (8-bit), halfword (16-bit), and word (32-bit) memory accesses.
    This transformation creates byte selection muxes for sub-word accesses.
    """
    mem_node = merged_graph.nodes.get('umem') or merged_graph.nodes.get('dmem')
    mem_name = 'umem' if merged_graph.nodes.get('umem') else 'dmem'

    if mem_node:
        access_widths = mem_node.data.get('access_widths', [32])
        max_width = max(access_widths) if access_widths else 32
        print(f"  {mem_name} access widths: {access_widths}, max: {max_width}")

        # Apply set_port_width transformation
        # TDMI is typically little-endian
        transform = MemoryAccessTransform(merged_graph)
        spec = MemoryAccessTransformSpec(
            memory=mem_name,
            strategy='set_port_width',
            current_width=max_width,
            target_width=32,  # Word-addressed memory (32-bit)
            direction='forward',
            endianness='little'  # TDMI is typically little-endian
        )
        result = transform.apply_transformation(spec)
        if result.get('transformed'):
            print(f"  Transformed: added {len(result.get('nodes_added', []))} byte mux nodes")
        else:
            print(f"  Skipped: {result.get('reason', 'unknown')}")
    else:
        print("  No memory node found (umem/dmem), skipping memory transform")


def generate_verilog(merged_graph, module_name, output_dir):
    """Generate Verilog output."""
    from backends.verilog import generate_verilog_with_testbench

    testbench_config = {
        'timeout_cycles': 10000,
        'imem_data_width': 32,  # A mode uses 32-bit instructions
        'dmem_data_width': 32,  # 32-bit data
    }

    files = generate_verilog_with_testbench(
        merged_graph,
        module_name=module_name,
        output_dir=output_dir,
        testbench_config=testbench_config
    )

    return files


def generate_vhdl(merged_graph, entity_name, output_dir, verify=True):
    """Generate VHDL output."""
    from backends.vhdl import generate_vhdl_with_testbench, VHDLTestbenchConfig
    from pathlib import Path

    testbench_config = VHDLTestbenchConfig(
        entity_name=entity_name,
        timeout_cycles=10000,
        imem_size=16384,
        dmem_size=16384
    )

    files = generate_vhdl_with_testbench(
        merged_graph,
        entity_name=entity_name,
        output_dir=output_dir,
        testbench_config=testbench_config,
        debug_outputs=['pc_rd']
    )

    if verify:
        print("\n" + "=" * 70)
        print("Verifying VHDL compilation with GHDL...")
        print("=" * 70)
        try:
            from backends.vhdl import compile_vhdl

            success, error = compile_vhdl(
                [files['rtl'], files['testbench']],
                work_dir=files['rtl'].parent,
                std='08'
            )

            if success:
                print("  VHDL compilation successful!")
            else:
                print(f"  VHDL compilation failed:")
                print(error)
        except ImportError:
            print("  GHDL not available, skipping compilation check")
        except Exception as e:
            print(f"  Error during compilation: {e}")

    return files


def main():
    parser = argparse.ArgumentParser(
        description='Generate TDMI-compatible processor from ISA definitions'
    )
    parser.add_argument(
        '--backend', '-b',
        choices=['verilog', 'vhdl'],
        default='verilog',
        help='Output backend (default: verilog)'
    )
    parser.add_argument(
        '--no-verify',
        action='store_true',
        help='Skip GHDL compilation verification for VHDL backend'
    )
    parser.add_argument(
        '--output-dir', '-o',
        help='Output directory (default: examples/verilog/tdmi_<subset>)'
    )
    parser.add_argument(
        '--subset',
        choices=['basic', 'a', 'full'],
        default='a',
        help='Instruction subset to generate (default: a)'
    )
    args = parser.parse_args()

    # Select instruction subset
    if args.subset == 'basic':
        # Basic A-mode-only set for initial testing
        instructions = BASIC_A_INSTRUCTIONS
        module_name = 'tdmi_basic'
    elif args.subset == 'a':
        # Full A mode only (no T)
        instructions = A_INSTRUCTIONS
        module_name = 'tdmi'
    else:
        # Full A + T
        instructions = ALL_INSTRUCTIONS
        module_name = 'tdmi_complete'

    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = f'examples/verilog/{module_name}'

    print("=" * 70)
    print(f"TDMI-compatible Processor Generator ({args.backend.upper()} backend)")
    print("=" * 70)
    print(f"\nGenerating TDMI processor with {len(instructions)} instructions...")
    print(f"Subset: {args.subset}")
    print(f"Instructions: {', '.join(instructions[:10])}{'...' if len(instructions) > 10 else ''}")

    # Step 1: Parse and merge ISA files
    print("\n" + "=" * 70)
    print("Step 1: Parsing and merging ISA files...")
    print("=" * 70)
    isa_files = {instr.replace('/', '_'): f"isa/tdmi/{instr}.isa" for instr in instructions}

    try:
        merged_graph = merge_instructions(isa_files)
        print(f"  Successfully merged {len(instructions)} instructions")
        print(f"  Merged graph has {len(merged_graph.nodes)} nodes and {len(merged_graph.edges)} edges")
    except Exception as e:
        print(f"  Error merging instructions: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Step 2: Apply memory transformations
    print("\n" + "=" * 70)
    print("Step 2: Applying memory port width transformation...")
    print("=" * 70)
    apply_memory_transform(merged_graph)

    # Step 3: Generate RTL
    print("\n" + "=" * 70)
    print(f"Step 3: Generating {args.backend.upper()} RTL and testbench...")
    print("=" * 70)
    print(f"  Output directory: {output_dir}")

    try:
        if args.backend == 'verilog':
            files = generate_verilog(merged_graph, module_name, output_dir)
        elif args.backend == 'vhdl':
            files = generate_vhdl(merged_graph, module_name, output_dir,
                                  verify=not args.no_verify)

        print(f"\n  Generated files:")
        for key, path in files.items():
            if hasattr(path, 'stat'):
                file_size = path.stat().st_size if path.exists() else 0
                print(f"    {key.upper()}: {path} ({file_size:,} bytes)")
            else:
                print(f"    {key.upper()}: {path}")

    except Exception as e:
        print(f"  Error generating {args.backend.upper()}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"  Successfully generated TDMI processor ({args.subset} subset)")
    print(f"  {len(instructions)} instructions implemented")
    print(f"  {len(merged_graph.nodes)} nodes in merged graph")
    print(f"  {len(merged_graph.edges)} edges in merged graph")
    print(f"  Backend: {args.backend.upper()}")
    print(f"  Output: {output_dir}/")

    print("\n" + "=" * 70)
    print("Done!")
    print("=" * 70)


if __name__ == "__main__":
    main()
