#!/usr/bin/env python3
"""
Generate RV32I processor with MMU (Sv32 virtual memory) support.
Includes all RV32I instructions plus Zicsr extensions and MMU aspects.

Optional TLB support using read-only cache optimization for PTW ports.
"""
import sys
import os
import argparse
# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from core.graph_merger import ResourceGraphMerger
from backends.verilog import generate_verilog_with_testbench
from core.isa_parser import ISAParser
from opt.memory.cache_optimization import ReadOnlyCacheSpec, apply_read_only_cache
from opt.temporal.multi_cycle_operations import set_memory_variable_latency, wire_memory_start_signal, add_simple_memory_stalls

# Complete RV32IMA instruction set
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

    # Loads (5)
    'lw', 'lh', 'lhu', 'lb', 'lbu',

    # Stores (3)
    'sw', 'sh', 'sb',

    # M Extension - Multiply/Divide (8)
    'mul', 'mulh', 'mulhu', 'mulhsu',
    'div', 'divu', 'rem', 'remu',

    # Atomics - full A extension (11)
    'amoadd_w', 'amoswap_w', 'amoxor_w', 'amoand_w', 'amoor_w',
    'amomin_w', 'amomax_w', 'amominu_w', 'amomaxu_w',
    'lr_w', 'sc_w',

    # Fence instructions (2) - memory/instruction fence, NOP for single-core no-cache
    'fence', 'fence_i',
]

# Zicsr extensions (6 CSR instructions + privileged instructions)
ZICSR_INSTRUCTIONS = [
    'csrrw', 'csrrs', 'csrrc', 'csrrwi', 'csrrsi', 'csrrci',
    'mret', 'sret', 'wfi', 'ecall', 'sfence_vma', 'ebreak',
]


def _wire_tlb_to_dmem_latency(graph):
    """Wire TLB refill to dmem latency mechanism and add TLB stall.

    When TLB has a miss, it needs to:
    1. Trigger dmem latency counter (TLB refill goes through dmem)
    2. Stall the processor while waiting for refill

    This function:
    1. Adds tlb_refill_req to dmem's access_enable (OR gate)
    2. Adds tlb_refill_req to processor's write_stall_signals
    """
    from core.resource_graph import Node, Edge

    print("  Wiring TLB to dmem latency mechanism...")

    # Find tlb_refill_req node
    tlb_refill_req = graph.nodes.get('tlb_refill_req')
    if not tlb_refill_req:
        print("    WARNING: tlb_refill_req not found")
        return

    # Find dmem_access_enable node and add tlb_refill_req as input
    dmem_access_enable = graph.nodes.get('dmem_access_enable')
    if dmem_access_enable:
        # Add tlb_refill_req as another input to the OR gate
        existing_inputs = len([e for e in dmem_access_enable.incoming_edges
                               if e.data.get('type') == 'logic_input'])
        graph.add_edge(Edge(
            tlb_refill_req, dmem_access_enable,
            data={'type': 'logic_input', 'operand_position': existing_inputs}
        ))
        print(f"    Added tlb_refill_req to dmem_access_enable (input {existing_inputs})")
    else:
        print("    WARNING: dmem_access_enable not found")

    # Add tlb_refill_req to write_stall_signals for all arch state
    # This stalls the processor while TLB is refilling
    stall_count = 0
    for node in graph.nodes.values():
        if node.is_arch_state:
            if 'write_stall_signals' not in node.data:
                node.data['write_stall_signals'] = []
            if 'tlb_refill_req' not in node.data['write_stall_signals']:
                node.data['write_stall_signals'].append('tlb_refill_req')
                stall_count += 1

    print(f"    Added tlb_refill_req stall to {stall_count} architectural state nodes")


def main(enable_tlb: bool = False, tlb_entries: int = 16, tlb_assoc: int = 4,
         dmem_min_latency: int = 1, dmem_max_latency: int = 1):
    """
    Generate RV32I+Zicsr+MMU processor.

    Args:
        enable_tlb: Enable TLB (Translation Lookaside Buffer) for PTW caching
        tlb_entries: Number of TLB entries (default 16)
        tlb_assoc: TLB associativity (default 4-way)
        dmem_min_latency: Minimum data memory latency in cycles (default 1)
        dmem_max_latency: Maximum data memory latency in cycles (default 1)
    """
    print("=" * 70)
    print("RV32I+Zicsr+MMU PROCESSOR GENERATOR")
    print("=" * 70)
    print(f"Instructions: {len(INSTRUCTIONS)} RV32I + {len(ZICSR_INSTRUCTIONS)} Zicsr")
    if enable_tlb:
        print(f"TLB: {tlb_entries} entries, {tlb_assoc}-way associative")
    else:
        print("TLB: Disabled")
    if dmem_max_latency > 1:
        print(f"Data memory latency: {dmem_min_latency}-{dmem_max_latency} cycles")
    print("=" * 70)

    print(f"\nRV32I: {', '.join(INSTRUCTIONS)}")
    print(f"Zicsr: {', '.join(ZICSR_INSTRUCTIONS)}")

    print("\nParsing and merging ISA files from riscv32/mmu/...")
    isa_files = {}
    # Add RV32I instructions from mmu directory
    for instr in INSTRUCTIONS:
        isa_files[instr] = f"riscv32/mmu/{instr}.isa"

    # Add Zicsr instructions from mmu/zicsr directory
    for instr in ZICSR_INSTRUCTIONS:
        isa_files[instr] = f"riscv32/mmu/zicsr/{instr}.isa"

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
    print("VM enabled: Virtual memory translation active")

    # Apply dmem latency if configured
    if dmem_min_latency > 1 or dmem_max_latency > 1:
        print(f"\nApplying data memory latency: {dmem_min_latency}-{dmem_max_latency} cycles")
        set_memory_variable_latency(merged_graph, 'dmem', dmem_min_latency, dmem_max_latency)
        if wire_memory_start_signal(merged_graph, 'dmem'):
            print("  dmem start signal wired")
        # Add stall logic to gate PC and state updates during memory access
        add_simple_memory_stalls(merged_graph, 'dmem')

    # Apply TLB if enabled
    if enable_tlb:
        print("\n" + "=" * 70)
        print("APPLYING TLB (Translation Lookaside Buffer)")
        print("=" * 70)

        # TLB caches only PTW (Page Table Walk) ports of dmem
        # PTW address nodes are: pte1_addr, pte0_addr, addr_pte1_addr, addr_pte0_addr
        # Pattern 'pte' matches all of these
        tlb_spec = ReadOnlyCacheSpec(
            memory_name='dmem',
            cache_name='tlb',
            block_size=4,               # Single PTE (4 bytes for Sv32)
            num_rows=tlb_entries,
            associativity=tlb_assoc,
            address_width=32,
            data_width=32,
            replacement_policy='lru',
            cached_ports=['pte']        # Only cache PTW ports (pte1_addr, pte0_addr, etc.)
        )

        print(f"  TLB specification: {tlb_spec}")
        success = apply_read_only_cache(merged_graph, tlb_spec)
        if success:
            print(f"  TLB applied successfully")

            # If dmem has variable latency, wire TLB refill to trigger dmem latency
            # and add TLB stall to processor stall signals
            if dmem_max_latency > 1:
                _wire_tlb_to_dmem_latency(merged_graph)
        else:
            print(f"  WARNING: Failed to apply TLB")

    print(f"\nGenerating Verilog to examples/verilog/riscv32_mmu/...")
    testbench_config = {
        'timeout_cycles': 10000
    }

    files = generate_verilog_with_testbench(
        merged_graph,
        module_name='riscv32_mmu',
        output_dir=f'examples/verilog/riscv32_mmu',
        testbench_config=testbench_config
    )

    print("\nGenerated files:")
    for key, path in files.items():
        print(f"  {key.upper()}: {path}")

    print(f"\nDone! Generated RV32I+Zicsr+MMU processor")
    if enable_tlb:
        print(f"TLB enabled: {tlb_entries} entries, {tlb_assoc}-way, caching PTW ports only")

    return merged_graph


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Generate RV32I+Zicsr+MMU processor with optional TLB',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python generate_riscv32i_mmu.py                    # Without TLB
  python generate_riscv32i_mmu.py --tlb              # With default TLB (16 entries, 4-way)
  python generate_riscv32i_mmu.py --tlb --tlb-entries 32 --tlb-assoc 8
  python generate_riscv32i_mmu.py --dmem-latency 3   # dmem latency 3 cycles
  python generate_riscv32i_mmu.py --tlb --dmem-latency 5  # TLB with 5-cycle dmem latency
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

    # Parse dmem latency (can be single value or min/max pair)
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
