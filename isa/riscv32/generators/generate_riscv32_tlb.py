#!/usr/bin/env python3
"""
Generate RV32I processor with MMU and TLB support.

This generator extends the base MMU processor with a proper TLB (Translation
Lookaside Buffer) that caches page table entries at multiple depths.

Features:
- Multi-level tag matching (depth-aware TLB entries)
- Fill entries at all levels during page table walk
- Superpage support via depth field
- sfence.vma flush support
"""
import sys
import os
import argparse
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from core.graph_merger import ResourceGraphMerger
from backends.verilog import generate_verilog_with_testbench
from opt.memory.tlb_optimization import TLBSpec, apply_tlb_optimization
from opt.temporal.multi_cycle_operations import set_memory_variable_latency, wire_memory_start_signal, add_simple_memory_stalls

# Complete RV32I instruction set (37 instructions)
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

    # Fence instructions (2)
    'fence', 'fence_i',
]

# Zicsr extensions (6 CSR instructions + mret + sret + ecall + sfence_vma)
ZICSR_INSTRUCTIONS = [
    'csrrw', 'csrrs', 'csrrc', 'csrrwi', 'csrrsi', 'csrrci', 'mret', 'sret', 'ecall', 'sfence_vma',
]


def find_ptw_reads(graph, patterns):
    """
    Find PTW read nodes matching the given patterns.

    Args:
        graph: ResourceGraph to search
        patterns: List of patterns to match in address node IDs

    Returns:
        List of (read_node_id, address_node_id) tuples in root-to-leaf order
    """
    from core.resource_graph import Node

    matches = []

    for node_id, node in graph.nodes.items():
        if not node.data or node.data.get('type') != 'array_access':
            continue
        if node.data.get('access_mode') != 'read':
            continue

        # Find address node
        addr_node_id = None
        for edge in node.incoming_edges:
            if edge.data and edge.data.get('type') == 'array_index':
                addr_node_id = edge.source.id
                break

        if not addr_node_id:
            continue

        # Check if address matches any pattern
        for pattern in patterns:
            if pattern in addr_node_id:
                matches.append((node_id, addr_node_id))
                break

    # Sort by VPN level (pte1 before pte0 = root to leaf)
    # Higher level number = closer to root
    def level_key(item):
        addr = item[1]
        # Extract level number (pte1 -> 1, pte0 -> 0)
        for i in range(10, -1, -1):
            if f'pte{i}' in addr:
                return -i  # Negative for descending order
        return 0

    matches.sort(key=level_key)
    return matches


def main(enable_itlb: bool = True, enable_dtlb: bool = True,
         tlb_entries: int = 64, tlb_assoc: int = 4,
         dmem_min_latency: int = 1, dmem_max_latency: int = 1):
    """
    Generate RV32I+Zicsr+MMU+TLB processor.

    Args:
        enable_itlb: Enable instruction TLB
        enable_dtlb: Enable data TLB
        tlb_entries: Number of TLB entries per TLB
        tlb_assoc: TLB associativity
        dmem_min_latency: Minimum data memory latency
        dmem_max_latency: Maximum data memory latency
    """
    print("=" * 70)
    print("RV32I+Zicsr+MMU+TLB PROCESSOR GENERATOR")
    print("=" * 70)
    print(f"Instructions: {len(INSTRUCTIONS)} RV32I + {len(ZICSR_INSTRUCTIONS)} Zicsr")
    if enable_itlb:
        print(f"ITLB: {tlb_entries} entries, {tlb_assoc}-way")
    if enable_dtlb:
        print(f"DTLB: {tlb_entries} entries, {tlb_assoc}-way")
    if dmem_max_latency > 1:
        print(f"Data memory latency: {dmem_min_latency}-{dmem_max_latency} cycles")
    print("=" * 70)

    print(f"\nRV32I: {', '.join(INSTRUCTIONS)}")
    print(f"Zicsr: {', '.join(ZICSR_INSTRUCTIONS)}")

    print("\nParsing and merging ISA files from riscv32/mmu/...")
    isa_files = {}
    for instr in INSTRUCTIONS:
        isa_files[instr] = f"riscv32/mmu/{instr}.isa"
    for instr in ZICSR_INSTRUCTIONS:
        isa_files[instr] = f"riscv32/mmu/zicsr/{instr}.isa"

    # Create merger with VM preprocessing enabled
    merger = ResourceGraphMerger(defines={'VM': ''})

    for instr_name, isa_file in isa_files.items():
        success = merger.add_instruction(instr_name, isa_file)
        if not success:
            raise ValueError(f"Failed to add instruction {instr_name}")

    merged_graph = merger.merge_graphs()
    print(f"\nMerged graph has {len(merged_graph.nodes)} nodes and {len(merged_graph.edges)} edges")

    # Debug: print all array_access nodes to find PTW reads
    print("\nLooking for PTW read nodes...")
    for node_id, node in merged_graph.nodes.items():
        if node.data and node.data.get('type') == 'array_access':
            addr = None
            for edge in node.incoming_edges:
                if edge.data and edge.data.get('type') == 'array_index':
                    addr = edge.source.id
                    break
            if addr and 'pte' in addr:
                print(f"  Found: {node_id} (addr: {addr})")

    # Apply dmem latency if configured
    if dmem_min_latency > 1 or dmem_max_latency > 1:
        print(f"\nApplying data memory latency: {dmem_min_latency}-{dmem_max_latency} cycles")
        set_memory_variable_latency(merged_graph, 'dmem', dmem_min_latency, dmem_max_latency)
        if wire_memory_start_signal(merged_graph, 'dmem'):
            print("  dmem start signal wired")
        add_simple_memory_stalls(merged_graph, 'dmem')

    # Apply ITLB if enabled
    if enable_itlb:
        print("\n" + "=" * 70)
        print("APPLYING ITLB (Instruction TLB)")
        print("=" * 70)

        # Find ITLB PTW reads (pc translation uses pte1_addr, pte0_addr)
        itlb_reads = find_ptw_reads(merged_graph, ['pte1_addr', 'pte0_addr'])
        # Filter out data TLB reads (addr_pte*) and exception detection reads (exc_pte*)
        itlb_reads = [(r, a) for r, a in itlb_reads if 'addr_pte' not in a and 'exc_pte' not in a]

        if itlb_reads:
            print(f"Found ITLB PTW reads: {itlb_reads}")

            # Build leaf indicators in same order as ptw_reads
            # For Sv32: pte1 can be a superpage (is_leaf_pte1), pte0 is always leaf (None)
            itlb_leaf_indicators = []
            for read_id, addr_id in itlb_reads:
                # Extract level number from address (pte1_addr -> 1, pte0_addr -> 0)
                level = None
                for i in range(10, -1, -1):
                    if f'pte{i}' in addr_id and 'addr_pte' not in addr_id:
                        level = i
                        break
                # Root level (pte1 for Sv32) has leaf indicator, leaf level (pte0) is always leaf
                if level is not None and level > 0:
                    itlb_leaf_indicators.append(f'is_leaf_pte{level}')
                else:
                    itlb_leaf_indicators.append(None)

            print(f"ITLB leaf indicators: {itlb_leaf_indicators}")

            itlb_spec = TLBSpec(
                ptw_reads=[r for r, a in itlb_reads],
                leaf_indicators=itlb_leaf_indicators,
                num_entries=tlb_entries,
                associativity=tlb_assoc,
                tlb_name='itlb',
            )

            success = apply_tlb_optimization(merged_graph, itlb_spec)
            if success:
                print("ITLB applied successfully")
            else:
                raise RuntimeError("Failed to apply ITLB - TLB optimization failed")
        else:
            raise RuntimeError("Failed to apply ITLB - no PTW reads found matching patterns ['pte1_addr', 'pte0_addr']")

    # Apply DTLB if enabled
    if enable_dtlb:
        print("\n" + "=" * 70)
        print("APPLYING DTLB (Data TLB)")
        print("=" * 70)

        # Find DTLB PTW reads (data translation uses addr_pte1_addr, addr_pte0_addr)
        dtlb_reads = find_ptw_reads(merged_graph, ['addr_pte1_addr', 'addr_pte0_addr'])

        if dtlb_reads:
            print(f"Found DTLB PTW reads: {dtlb_reads}")

            # Build leaf indicators in same order as ptw_reads
            # For Sv32: addr_pte1 can be a superpage (addr_is_leaf_pte1), addr_pte0 is always leaf (None)
            dtlb_leaf_indicators = []
            for read_id, addr_id in dtlb_reads:
                # Extract level number from address (addr_pte1_addr -> 1, addr_pte0_addr -> 0)
                level = None
                for i in range(10, -1, -1):
                    if f'addr_pte{i}' in addr_id:
                        level = i
                        break
                # Root level (addr_pte1 for Sv32) has leaf indicator, leaf level (addr_pte0) is always leaf
                if level is not None and level > 0:
                    dtlb_leaf_indicators.append(f'addr_is_leaf_pte{level}')
                else:
                    dtlb_leaf_indicators.append(None)

            print(f"DTLB leaf indicators: {dtlb_leaf_indicators}")

            dtlb_spec = TLBSpec(
                ptw_reads=[r for r, a in dtlb_reads],
                leaf_indicators=dtlb_leaf_indicators,
                num_entries=tlb_entries,
                associativity=tlb_assoc,
                tlb_name='dtlb',
            )

            success = apply_tlb_optimization(merged_graph, dtlb_spec)
            if success:
                print("DTLB applied successfully")
            else:
                raise RuntimeError("Failed to apply DTLB - TLB optimization failed")
        else:
            raise RuntimeError("Failed to apply DTLB - no PTW reads found matching patterns ['addr_pte1_addr', 'addr_pte0_addr']")

    print(f"\nGenerating Verilog to examples/verilog/riscv32_tlb/...")
    testbench_config = {
        'timeout_cycles': 10000
    }

    files = generate_verilog_with_testbench(
        merged_graph,
        module_name='riscv32_tlb',
        output_dir='examples/verilog/riscv32_tlb',
        testbench_config=testbench_config
    )

    print("\nGenerated files:")
    for key, path in files.items():
        print(f"  {key.upper()}: {path}")

    print(f"\nDone! Generated RV32I+Zicsr+MMU+TLB processor")

    return merged_graph


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Generate RV32I+Zicsr+MMU+TLB processor',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python generate_riscv32_tlb.py                     # ITLB + DTLB with defaults
  python generate_riscv32_tlb.py --no-itlb           # DTLB only
  python generate_riscv32_tlb.py --no-dtlb           # ITLB only
  python generate_riscv32_tlb.py --tlb-entries 128   # Larger TLBs
  python generate_riscv32_tlb.py --dmem-latency 3    # Variable dmem latency
        '''
    )

    parser.add_argument(
        '--no-itlb',
        action='store_true',
        default=False,
        help='Disable instruction TLB'
    )
    parser.add_argument(
        '--no-dtlb',
        action='store_true',
        default=False,
        help='Disable data TLB'
    )
    parser.add_argument(
        '--tlb-entries',
        type=int,
        default=64,
        help='Number of TLB entries per TLB (default: 64)'
    )
    parser.add_argument(
        '--tlb-assoc',
        type=int,
        default=4,
        choices=[1, 2, 4, 8],
        help='TLB associativity (default: 4)'
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

    if len(args.dmem_latency) == 1:
        dmem_min = dmem_max = args.dmem_latency[0]
    else:
        dmem_min, dmem_max = args.dmem_latency[0], args.dmem_latency[1]

    main(
        enable_itlb=not args.no_itlb,
        enable_dtlb=not args.no_dtlb,
        tlb_entries=args.tlb_entries,
        tlb_assoc=args.tlb_assoc,
        dmem_min_latency=dmem_min,
        dmem_max_latency=dmem_max,
    )
