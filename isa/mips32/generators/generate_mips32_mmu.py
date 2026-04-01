#!/usr/bin/env python3
"""
Generate MIPS32 processor with MMU (software-managed TLB) support for Linux.
Includes all MIPS32 instructions plus CP0 coprocessor for system control.

Features:
- 32-entry fully-associative TLB with ASID
- CP0 registers: Status, Cause, EPC, BadVAddr, EntryHi, EntryLo0/1, Index, etc.
- TLB instructions: TLBR, TLBWI, TLBWR, TLBP
- Exception handling: SYSCALL, BREAK, ERET
- Atomic operations: LL/SC
- Multiply/divide with HI/LO registers
"""
import sys
import os
import argparse

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core.graph_merger import ResourceGraphMerger
from backends.verilog import generate_verilog_with_testbench
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec

# Complete MIPS32 instruction set with MMU support
INSTRUCTIONS = [
    # R-type arithmetic (11)
    'add', 'addu', 'sub', 'subu', 'slt', 'sltu', 'nor',
    'and', 'or', 'xor',
    'lui',

    # R-type shifts - immediate (3)
    'sll', 'srl', 'sra',

    # R-type shifts - variable (3)
    'sllv', 'srlv', 'srav',

    # I-type arithmetic/logical (8)
    'addi', 'addiu', 'andi', 'ori', 'xori', 'slti', 'sltiu',

    # Loads (6)
    'lw', 'lh', 'lhu', 'lb', 'lbu',
    'll',  # Load Linked (atomic)

    # Stores (4)
    'sw', 'sh', 'sb',
    'sc',  # Store Conditional (atomic)

    # Branches (6)
    'beq', 'bne', 'bgez', 'bltz', 'bgtz', 'blez',

    # Jumps (4)
    'j', 'jal', 'jr', 'jalr',

    # Multiply/Divide (8)
    'mult', 'multu', 'div', 'divu',
    'mfhi', 'mflo', 'mthi', 'mtlo',
]

# CP0 coprocessor instructions (9)
CP0_INSTRUCTIONS = [
    'mfc0', 'mtc0',           # CP0 register access
    'tlbr', 'tlbwi', 'tlbwr', 'tlbp',  # TLB operations
    'eret',                   # Exception return
    'syscall', 'break',       # Exceptions
]

# Tests for MIPS32 MMU
MIPS32_MMU_TESTS = [
    "add", "addi", "addiu", "addu", "and", "andi", "beq", "bne",
    "bgez", "bltz", "bgtz", "blez",
    "div", "divu", "mult", "multu", "mfhi", "mflo",
    "j", "jal", "jalr", "jr", "lb", "lbu", "lh", "lhu", "lui", "lw",
    "ll", "sc",
    "nor", "or", "ori", "sb", "sh", "sll", "sllv", "slt", "slti",
    "sltiu", "sltu", "sra", "srav", "srl", "srlv", "sub", "subu",
    "sw", "xor", "xori",
    "mfc0", "mtc0", "tlbwi", "tlbr", "tlbp", "eret", "syscall",
]


def main():
    parser = argparse.ArgumentParser(
        description='Generate MIPS32+MMU processor for Linux boot',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python generate_mips32_mmu.py                    # Generate with MMU
  python generate_mips32_mmu.py --no-mmu           # Generate without MMU (bare metal)
  python generate_mips32_mmu.py -o examples/verilog/custom  # Custom output directory
        '''
    )

    parser.add_argument(
        '--no-mmu',
        action='store_true',
        default=False,
        help='Disable MMU (generate bare-metal processor)'
    )
    parser.add_argument(
        '--output-dir', '-o',
        default='examples/verilog/mips32_mmu',
        help='Output directory (default: examples/verilog/mips32_mmu)'
    )
    parser.add_argument(
        '--backend', '-b',
        choices=['verilog'],
        default='verilog',
        help='Output backend (default: verilog)'
    )

    args = parser.parse_args()

    module_name = 'mips32_mmu'
    output_dir = args.output_dir
    enable_mmu = not args.no_mmu

    print("=" * 70)
    print("MIPS32 + MMU PROCESSOR GENERATOR")
    print("=" * 70)
    print(f"Instructions: {len(INSTRUCTIONS)} base + {len(CP0_INSTRUCTIONS)} CP0")
    print(f"MMU: {'Enabled (software-managed TLB)' if enable_mmu else 'Disabled'}")
    print("=" * 70)

    print(f"\nBase: {', '.join(INSTRUCTIONS)}")
    print(f"CP0:  {', '.join(CP0_INSTRUCTIONS)}")

    # Build ISA file paths
    print("\nParsing and merging ISA files...")
    isa_files = {}

    # Add base instructions from mmu directory
    for instr in INSTRUCTIONS:
        isa_files[instr] = f"isa/mips32/mmu/{instr}.isa"

    # Add CP0 instructions from mmu/cp0 directory
    for instr in CP0_INSTRUCTIONS:
        isa_files[instr] = f"isa/mips32/mmu/cp0/{instr}.isa"

    # Create merger with MMU preprocessing enabled
    defines = {'MMU': ''} if enable_mmu else {}
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
    if enable_mmu:
        print("MMU enabled: Software-managed TLB with 32 entries")

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
                direction='forward'
            )
            result = transform.apply_transformation(spec)
            if result.get('transformed'):
                print(f"  Transformed: added {len(result.get('nodes_added', []))} byte mux nodes")
            else:
                print(f"  Skipped: {result.get('reason', 'unknown')}")

    # Generate Verilog
    print(f"\nGenerating Verilog to {output_dir}/...")
    testbench_config = {
        'timeout_cycles': 50000  # Longer timeout for Linux boot
    }

    files = generate_verilog_with_testbench(
        merged_graph,
        module_name=module_name,
        output_dir=output_dir,
        testbench_config=testbench_config
    )

    print("\n" + "=" * 70)
    print("GENERATION COMPLETE")
    print("=" * 70)
    print("\nGenerated files:")
    for key, path in files.items():
        if hasattr(path, 'stat'):
            file_size = path.stat().st_size if path.exists() else 0
            print(f"  {key.upper()}: {path} ({file_size:,} bytes)")
        else:
            print(f"  {key.upper()}: {path}")

    print(f"\n{'=' * 70}")
    print("NEXT STEPS FOR LINUX BOOT")
    print("=" * 70)
    print("""
1. Compile tests:
   cd mips32/mips-tests && make

2. Run simulation:
   cd examples/verilog/mips32_mmu
   iverilog -o sim mips32_mmu.v mips32_mmu_tb.sv
   vvp sim

3. For Linux boot:
   - Cross-compile kernel with mips-linux-gnu-gcc
   - Load kernel image into memory
   - Entry point: 0x80000000 (kseg0)
""")

    return merged_graph


if __name__ == '__main__':
    main()
