#!/usr/bin/env python3
"""
Generate RV64I processor with MMU (Sv39 virtual memory) support.
Includes all RV64IMA instructions plus Zicsr extensions and MMU aspects.

Optional TLB support using read-only cache optimization for PTW ports.
"""
import sys
import os
import argparse
# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core.graph_merger import ResourceGraphMerger
from backends.verilog import generate_verilog_with_testbench
from opt.memory.cache_optimization import ReadOnlyCacheSpec, apply_read_only_cache
from opt.temporal.multi_cycle_operations import set_memory_variable_latency, wire_memory_start_signal, add_simple_memory_stalls
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec

# Complete RV64IMA instruction set
INSTRUCTIONS = [
    # Arithmetic (5)
    'add', 'addi', 'sub', 'lui', 'auipc',

    # Logical (6)
    'and', 'andi', 'or', 'ori', 'xor', 'xori',

    # Shifts (6)
    'sll', 'slli', 'srl', 'srli', 'sra', 'srai',

    # Compare (4)
    'slt', 'slti', 'sltu', 'sltiu',

    # Branches (6)
    'beq', 'bne', 'blt', 'bltu', 'bge', 'bgeu',

    # Jumps (2)
    'jal', 'jalr',

    # Loads (7)
    'ld', 'lw', 'lwu', 'lh', 'lhu', 'lb', 'lbu',

    # Stores (4)
    'sd', 'sw', 'sh', 'sb',

    # RV64I-specific word operations (9)
    'addw', 'addiw', 'subw',
    'sllw', 'slliw', 'srlw', 'srliw', 'sraw', 'sraiw',

    # M Extension - Multiply/Divide (8 + 5 word variants)
    'mul', 'mulh', 'mulhu', 'mulhsu',
    'div', 'divu', 'rem', 'remu',
    'mulw', 'divw', 'divuw', 'remw', 'remuw',

    # Atomics - full A extension, word (11)
    'amoadd_w', 'amoswap_w', 'amoxor_w', 'amoand_w', 'amoor_w',
    'amomin_w', 'amomax_w', 'amominu_w', 'amomaxu_w',
    'lr_w', 'sc_w',

    # Atomics - full A extension, doubleword (11)
    'amoadd_d', 'amoswap_d', 'amoxor_d', 'amoand_d', 'amoor_d',
    'amomin_d', 'amomax_d', 'amominu_d', 'amomaxu_d',
    'lr_d', 'sc_d',

    # Fence instructions (2)
    'fence', 'fence_i',
]

# Zicsr extensions (6 CSR instructions + privileged instructions)
ZICSR_INSTRUCTIONS = [
    'csrrw', 'csrrs', 'csrrc', 'csrrwi', 'csrrsi', 'csrrci',
    'mret', 'sret', 'wfi', 'ecall', 'sfence_vma', 'ebreak',
]


def main(enable_tlb: bool = False, tlb_entries: int = 16, tlb_assoc: int = 4,
         dmem_min_latency: int = 1, dmem_max_latency: int = 1):
    """
    Generate RV64I+Zicsr+MMU processor.

    Args:
        enable_tlb: Enable TLB (Translation Lookaside Buffer) for PTW caching
        tlb_entries: Number of TLB entries (default 16)
        tlb_assoc: TLB associativity (default 4-way)
        dmem_min_latency: Minimum data memory latency in cycles (default 1)
        dmem_max_latency: Maximum data memory latency in cycles (default 1)
    """
    print("=" * 70)
    print("RV64I+Zicsr+MMU PROCESSOR GENERATOR (Sv39)")
    print("=" * 70)
    print(f"Instructions: {len(INSTRUCTIONS)} RV64IMA + {len(ZICSR_INSTRUCTIONS)} Zicsr")
    if enable_tlb:
        print(f"TLB: {tlb_entries} entries, {tlb_assoc}-way associative")
    else:
        print("TLB: Disabled")
    if dmem_max_latency > 1:
        print(f"Data memory latency: {dmem_min_latency}-{dmem_max_latency} cycles")
    print("=" * 70)

    print(f"\nRV64IMA: {', '.join(INSTRUCTIONS)}")
    print(f"Zicsr: {', '.join(ZICSR_INSTRUCTIONS)}")

    print("\nParsing and merging ISA files from isa/riscv64/mmu/...")
    isa_files = {}
    # Add RV64IMA instructions from mmu directory
    for instr in INSTRUCTIONS:
        isa_files[instr] = f"isa/riscv64/mmu/{instr}.isa"

    # Add Zicsr instructions from mmu/zicsr directory
    for instr in ZICSR_INSTRUCTIONS:
        isa_files[instr] = f"isa/riscv64/mmu/zicsr/{instr}.isa"

    # Create merger with VM preprocessing enabled
    merger = ResourceGraphMerger(defines={'VM': ''})

    # Add all instructions
    for instr_name, isa_file in isa_files.items():
        success = merger.add_instruction(instr_name, isa_file)
        if not success:
            raise ValueError(f"Failed to add instruction {instr_name}")

    # Merge all instructions
    merged_graph = merger.merge_graphs()
    print(f"\nMerged graph has {len(merged_graph.nodes)} nodes and {len(merged_graph.edges)} edges")
    print("VM enabled: Sv39 virtual memory translation active")

    # Apply memory access transform for 64-bit word-addressed memory
    # This sets port_width=64 on umem so the Verilog generator produces correct
    # byte-lane selection for narrow stores (sb/sh/sw) and narrow reads (lb/lh/lw)
    umem_node = merged_graph.nodes.get('umem')
    if umem_node:
        access_widths = umem_node.data.get('access_widths', [64])
        max_width = max(access_widths) if access_widths else 64
        print(f"\n  umem access widths: {access_widths}, max: {max_width}")

        transform = MemoryAccessTransform(merged_graph)
        spec = MemoryAccessTransformSpec(
            memory='umem',
            strategy='set_port_width',
            current_width=max_width,
            target_width=64,  # 64-bit memory elements for RV64
            direction='forward',
            alignment='unaligned'  # Support sub-word accesses within 64-bit words
        )
        result = transform.apply_transformation(spec)
        if result.get('transformed'):
            print(f"  Transformed: added {len(result.get('nodes_added', []))} byte mux nodes")
        else:
            print(f"  Skipped: {result.get('reason', 'unknown')}")

    # Apply dmem latency if configured
    if dmem_min_latency > 1 or dmem_max_latency > 1:
        print(f"\nApplying data memory latency: {dmem_min_latency}-{dmem_max_latency} cycles")
        set_memory_variable_latency(merged_graph, 'dmem', dmem_min_latency, dmem_max_latency)
        if wire_memory_start_signal(merged_graph, 'dmem'):
            print("  dmem start signal wired")
        add_simple_memory_stalls(merged_graph, 'dmem')

    # Apply TLB if enabled
    if enable_tlb:
        print("\n" + "=" * 70)
        print("APPLYING TLB (Translation Lookaside Buffer)")
        print("=" * 70)

        # TLB caches only PTW (Page Table Walk) ports of dmem
        # Sv39 has 3 levels of PTW, pattern 'pte' matches all PTW address nodes
        tlb_spec = ReadOnlyCacheSpec(
            memory_name='dmem',
            cache_name='tlb',
            block_size=8,               # Single PTE (8 bytes for Sv39)
            num_rows=tlb_entries,
            associativity=tlb_assoc,
            address_width=64,
            data_width=64,
            replacement_policy='lru',
            cached_ports=['pte']        # Only cache PTW ports
        )

        print(f"  TLB specification: {tlb_spec}")
        success = apply_read_only_cache(merged_graph, tlb_spec)
        if success:
            print(f"  TLB applied successfully")
        else:
            print(f"  WARNING: Failed to apply TLB")

    print(f"\nGenerating Verilog to examples/verilog/riscv64_mmu/...")
    testbench_config = {
        'timeout_cycles': 10000
    }

    files = generate_verilog_with_testbench(
        merged_graph,
        module_name='riscv64_mmu',
        output_dir=f'examples/verilog/riscv64_mmu',
        testbench_config=testbench_config
    )

    print("\nGenerated files:")
    for key, path in files.items():
        print(f"  {key.upper()}: {path}")

    print(f"\nDone! Generated RV64I+Zicsr+MMU processor ({len(INSTRUCTIONS) + len(ZICSR_INSTRUCTIONS)} instructions)")
    if enable_tlb:
        print(f"TLB enabled: {tlb_entries} entries, {tlb_assoc}-way, caching PTW ports only")

    return merged_graph


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Generate RV64I+Zicsr+MMU processor with optional TLB',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python generate_riscv64i_mmu.py                    # Without TLB
  python generate_riscv64i_mmu.py --tlb              # With default TLB (16 entries, 4-way)
  python generate_riscv64i_mmu.py --tlb --tlb-entries 32 --tlb-assoc 8
  python generate_riscv64i_mmu.py --dmem-latency 3   # dmem latency 3 cycles
        '''
    )

    parser.add_argument(
        '--tlb',
        action='store_true',
        default=False,
        help='Enable TLB (Translation Lookaside Buffer) for PTW port caching'
    )
    parser.add_argument(
        '--tlb-entries',
        type=int,
        default=16,
        help='Number of TLB entries (default: 16)'
    )
    parser.add_argument(
        '--tlb-assoc',
        type=int,
        default=4,
        choices=[1, 2, 4, 8],
        help='TLB associativity: 1=direct-mapped, 2/4/8=set-associative (default: 4)'
    )
    parser.add_argument(
        '--dmem-latency', '-dl',
        type=int,
        nargs='+',
        default=[1],
        metavar='CYCLES',
        help='Data memory latency (1 value for fixed, 2 for min/max range)'
    )

    args = parser.parse_args()

    # Parse dmem latency
    if len(args.dmem_latency) == 1:
        dmem_min = dmem_max = args.dmem_latency[0]
    else:
        dmem_min, dmem_max = args.dmem_latency[0], args.dmem_latency[1]

    main(
        enable_tlb=args.tlb,
        tlb_entries=args.tlb_entries,
        tlb_assoc=args.tlb_assoc,
        dmem_min_latency=dmem_min,
        dmem_max_latency=dmem_max
    )
