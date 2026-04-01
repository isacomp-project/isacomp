#!/usr/bin/env python3
"""
Generate MIPS32 processor with Linux-compatible instruction set.

This includes:
- Base MIPS32 instructions (38)
- Extended MIPS32R2 instructions for Linux (branches, multiply/divide, bit ops, etc.)
- Unaligned load/store instructions (lwl/lwr/swl/swr)
- Kernel/privileged instructions (syscall, eret, CP0 access, TLB ops)
- Single-precision floating-point instructions (optional)

Supports Verilog, VHDL, PyRTL, and CIRCT backends via --backend argument.
"""
import sys
import os
import argparse

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core.graph_merger import merge_instructions, ResourceGraphMerger
from backends.verilog import generate_verilog_with_testbench
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec
from opt.temporal.multi_cycle_operations import apply_multi_cycle_operations, OperationLatencySpec

# =============================================================================
# MIPS32 Base Integer Instructions (38)
# =============================================================================
MIPS32_BASE = [
    # R-type arithmetic
    'add', 'addu', 'sub', 'subu', 'slt', 'sltu', 'nor',
    # R-type logical
    'and', 'or', 'xor',
    # R-type shifts - immediate
    'sll', 'srl', 'sra',
    # R-type shifts - variable
    'sllv', 'srlv', 'srav',
    # I-type arithmetic/logical
    'addi', 'addiu', 'andi', 'ori', 'xori', 'slti', 'sltiu', 'lui',
    # Loads
    'lw', 'lh', 'lhu', 'lb', 'lbu',
    # Stores
    'sw', 'sh', 'sb',
    # Branches
    'beq', 'bne',
    # Jumps
    'j', 'jal', 'jr', 'jalr',
]

# =============================================================================
# Extended MIPS32R2 Instructions for Linux (from mips32/mmu/ without MMU)
# =============================================================================
MIPS32R2_EXTENDED = [
    # Additional branches (6)
    'bgez', 'bgtz', 'blez', 'bltz',
    'bgezal', 'bltzal',

    # Multiply/divide with HI/LO (10)
    'mul',                    # rd = rs * rt (low 32 bits)
    'mult', 'multu',          # HI:LO = rs * rt
    'div', 'divu',            # LO = quotient, HI = remainder
    'madd', 'maddu',          # HI:LO += rs * rt
    'msub', 'msubu',          # HI:LO -= rs * rt
    'mfhi', 'mflo',           # Move from HI/LO
    'mthi', 'mtlo',           # Move to HI/LO

    # Bit manipulation (9)
    'clz', 'clo',             # Count leading zeros/ones
    'ext', 'ins',             # Extract/Insert bit field
    'seb', 'seh',             # Sign extend byte/halfword
    'wsbh',                   # Word swap bytes within halfwords
    'rotr', 'rotrv',          # Rotate right

    # Conditional moves (2)
    'movz', 'movn',           # Move if zero/not-zero

    # Atomic operations (2)
    'll', 'sc',               # Load-linked / Store-conditional

    # Hints (1)
    'pref',                   # Prefetch (can be nop)
]

# =============================================================================
# Unaligned Load/Store Instructions (4)
# =============================================================================
MIPS32_UNALIGNED = [
    'lwl', 'lwr',             # Load word left/right
    'swl', 'swr',             # Store word left/right
]

# =============================================================================
# Kernel/Privileged Instructions for Linux (from mips32/mmu/cp0/)
# =============================================================================
MIPS32_KERNEL = [
    # System calls and exceptions (2)
    'syscall',                # System call exception
    'break',                  # Breakpoint exception

    # Memory barriers (1)
    'sync',                   # Memory synchronization barrier

    # CP0 register access (2)
    'mfc0', 'mtc0',           # Move from/to Coprocessor 0

    # Exception handling (1)
    'eret',                   # Exception return

    # TLB management (4)
    'tlbr',                   # TLB Read
    'tlbwi',                  # TLB Write Indexed
    'tlbwr',                  # TLB Write Random
    'tlbp',                   # TLB Probe

    # Cache operations (1)
    'cache',                  # Cache operation

    # Wait for interrupt (1)
    'wait',                   # Wait for interrupt

    # Interrupt enable/disable - MIPS32R2 (2)
    'ei', 'di',               # Enable/Disable interrupts

    # Hardware register access (1)
    'rdhwr',                  # Read hardware register

    # Trap instructions (14)
    'teq', 'teqi',            # Trap if equal
    'tge', 'tgei', 'tgeiu', 'tgeu',  # Trap if greater/equal
    'tlt', 'tlti', 'tltiu', 'tltu',  # Trap if less than
    'tne', 'tnei',            # Trap if not equal
]

# =============================================================================
# Single-Precision Floating-Point Instructions
# =============================================================================
MIPS32_FPU_SINGLE = [
    # Arithmetic (5)
    'add_s', 'sub_s', 'mul_s', 'div_s', 'sqrt_s',

    # Fused multiply-add (4)
    'madd_s', 'msub_s', 'nmadd_s', 'nmsub_s',

    # Min/Max (2)
    'min_s', 'max_s',

    # Comparisons (4)
    'c_eq_s', 'c_lt_s', 'c_le_s', 'c_un_s',

    # Conversions (6)
    'cvt_s_w', 'cvt_w_s',
    'ceil_w_s', 'floor_w_s', 'round_w_s', 'trunc_w_s',

    # Move/Sign operations (3)
    'mov_s', 'neg_s', 'abs_s',

    # Conditional moves (4)
    'movz_s', 'movn_s', 'movf_s', 'movt_s',

    # Move between integer and FP registers (4)
    'mfc1', 'mtc1', 'cfc1', 'ctc1',

    # FP branches (2)
    'bc1f', 'bc1t',

    # Load/Store (2)
    'lwc1', 'swc1',
]

# =============================================================================
# Test lists for verification
# =============================================================================
MIPS32_TESTS = [
    # Base tests
    "add", "addi", "addiu", "addu", "and", "andi", "beq", "bne",
    "j", "jal", "jalr", "jr", "lb", "lbu", "lh", "lhu", "lui", "lw",
    "nor", "or", "ori", "sb", "sh", "sll", "sllv", "slt", "slti",
    "sltiu", "sltu", "sra", "srav", "srl", "srlv", "sub", "subu",
    "sw", "xor", "xori",
    # Extended tests
    "bgez", "bgtz", "blez", "bltz", "bgezal", "bltzal",
    "mul", "mult", "multu", "div", "divu", "madd", "maddu", "msub", "msubu",
    "clz", "clo", "ext", "ins", "seb", "seh", "wsbh", "rotr", "rotrv",
    "movz", "movn", "ll", "sc",
]


def generate_verilog(merged_graph, module_name, output_dir):
    """Generate Verilog output."""
    testbench_config = {
        'timeout_cycles': 20000
    }

    files = generate_verilog_with_testbench(
        merged_graph,
        module_name=module_name,
        output_dir=output_dir,
        testbench_config=testbench_config
    )
    return files


def main():
    parser = argparse.ArgumentParser(
        description='Generate MIPS32 Linux-compatible processor from ISA definitions'
    )
    parser.add_argument(
        '--backend', '-b',
        choices=['verilog', 'vhdl', 'pyrtl', 'circt'],
        default='verilog',
        help='Output backend (default: verilog)'
    )
    parser.add_argument(
        '--output-dir', '-o',
        help='Output directory (default: examples/verilog/mips32_linux)'
    )
    parser.add_argument(
        '--no-fpu',
        action='store_true',
        help='Generate integer-only processor (no FPU)'
    )
    parser.add_argument(
        '--kernel',
        action='store_true',
        help='Include kernel/privileged instructions (requires MMU support, WIP)'
    )
    args = parser.parse_args()

    module_name = 'mips32_linux'
    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = 'examples/verilog/mips32_linux'

    # Build instruction list
    instructions = MIPS32_BASE + MIPS32R2_EXTENDED + MIPS32_UNALIGNED
    if args.kernel:
        instructions = instructions + MIPS32_KERNEL
    if not args.no_fpu:
        instructions = instructions + MIPS32_FPU_SINGLE

    print("=" * 70)
    print(f"MIPS32 LINUX PROCESSOR GENERATOR ({args.backend.upper()} backend)")
    print("=" * 70)
    print(f"\nGenerating MIPS32 Linux processor with {len(instructions)} instructions...")
    print(f"  Base MIPS32: {len(MIPS32_BASE)} instructions")
    print(f"  Extended MIPS32R2: {len(MIPS32R2_EXTENDED)} instructions")
    print(f"  Unaligned load/store: {len(MIPS32_UNALIGNED)} instructions")
    if args.kernel:
        print(f"  Kernel/privileged: {len(MIPS32_KERNEL)} instructions")
    if not args.no_fpu:
        print(f"  FPU (single-precision): {len(MIPS32_FPU_SINGLE)} instructions")

    print("\n" + "=" * 70)
    print("PARSING AND MERGING ISA FILES")
    print("=" * 70)

    # Build instruction paths
    isa_files = {}

    # When kernel mode is enabled, use mips32/mmu/ instructions (with TLB support)
    # Otherwise use base mips32/ instructions without MMU
    if args.kernel:
        # All base instructions from mips32/mmu/ (with TLB aspect support)
        for instr in MIPS32_BASE:
            isa_files[instr] = f"isa/mips32/mmu/{instr}.isa"
    else:
        # Base MIPS32 instructions without MMU
        for instr in MIPS32_BASE:
            isa_files[instr] = f"isa/mips32/{instr}.isa"

    # Extended instructions from isa/mips32/mmu/ (they work with/without MMU define)
    for instr in MIPS32R2_EXTENDED:
        isa_files[instr] = f"isa/mips32/mmu/{instr}.isa"

    # Unaligned load/store instructions from isa/mips32/mmu/
    for instr in MIPS32_UNALIGNED:
        isa_files[instr] = f"isa/mips32/mmu/{instr}.isa"

    # Kernel/privileged instructions from isa/mips32/mmu/cp0/
    if args.kernel:
        for instr in MIPS32_KERNEL:
            isa_files[instr] = f"isa/mips32/mmu/cp0/{instr}.isa"

    # FPU instructions (located in isa/mips32/mmu/f/)
    if not args.no_fpu:
        for instr in MIPS32_FPU_SINGLE:
            isa_files[instr] = f"isa/mips32/mmu/f/{instr}.isa"

    # Verify all files exist
    print("\nVerifying ISA files...")
    missing = []
    for instr, path in isa_files.items():
        full_path = os.path.join(os.path.dirname(__file__), '../../..', path)
        if not os.path.exists(full_path):
            missing.append(f"  {instr}: {path}")

    if missing:
        print("ERROR: Missing ISA files:")
        for m in missing:
            print(m)
        sys.exit(1)
    print(f"  All {len(isa_files)} ISA files found")

    print(f"\nMerging {len(instructions)} ISA specifications...")

    # Use ResourceGraphMerger with MMU define for kernel mode
    if args.kernel:
        print("  MMU enabled: Using TLB translation for all instructions")
        defines = {'MMU': ''}
        merger = ResourceGraphMerger(defines=defines)
        for instr_name, isa_file in isa_files.items():
            success = merger.add_instruction(instr_name, isa_file)
            if not success:
                raise ValueError(f"Failed to add instruction {instr_name} from {isa_file}")
        merged_graph = merger.merge_graphs()
    else:
        # Without kernel mode, use simple merge
        merged_graph = merge_instructions(isa_files)

    print(f"  Merged graph has {len(merged_graph.nodes)} nodes and {len(merged_graph.edges)} edges")

    # Apply port width setting for word-addressed unified memory
    print("\nApplying memory port width transformation for umem...")
    umem_node = merged_graph.nodes.get('umem')
    if umem_node:
        access_widths = umem_node.data.get('access_widths', [32])
        max_width = max(access_widths) if access_widths else 32
        print(f"  umem access widths: {access_widths}, max: {max_width}")

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

    # Apply multi-cycle latency for FP div/sqrt
    if not args.no_fpu:
        print("\nApplying multi-cycle latency for FP operations...")
        fp_div_sqrt_ops = []
        for node_id, node in merged_graph.nodes.items():
            fp_intrinsic = node.data.get('fp_intrinsic', '')
            if fp_intrinsic in ['fp_div', 'fp_sqrt']:
                fp_div_sqrt_ops.append(OperationLatencySpec(
                    operation_id=node_id,
                    latency_cycles=10
                ))

        if fp_div_sqrt_ops:
            apply_multi_cycle_operations(merged_graph, fp_div_sqrt_ops)
            print(f"  Applied {len(fp_div_sqrt_ops)} multi-cycle operation(s)")

    print("\n" + "=" * 70)
    print(f"GENERATING {args.backend.upper()}")
    print("=" * 70)
    print(f"\nOutput directory: {output_dir}/")

    try:
        if args.backend == 'verilog':
            files = generate_verilog(merged_graph, module_name, output_dir)
        else:
            print(f"  Backend '{args.backend}' not yet implemented")
            print("  Using Verilog backend instead")
            files = generate_verilog(merged_graph, module_name, output_dir)

        print("\n" + "=" * 70)
        print("GENERATION COMPLETE")
        print("=" * 70)
        print(f"\nMIPS32 Linux processor generated successfully!")
        print(f"  Total instructions: {len(instructions)}")
        print(f"    - Base MIPS32: {len(MIPS32_BASE)}")
        print(f"    - Extended MIPS32R2: {len(MIPS32R2_EXTENDED)}")
        print(f"    - Unaligned load/store: {len(MIPS32_UNALIGNED)}")
        if args.kernel:
            print(f"    - Kernel/privileged: {len(MIPS32_KERNEL)}")
        if not args.no_fpu:
            print(f"    - FPU (single-precision): {len(MIPS32_FPU_SINGLE)}")
        print(f"\nGenerated files:")
        for key, path in files.items():
            if hasattr(path, 'stat'):
                file_size = path.stat().st_size if path.exists() else 0
                print(f"  {key.upper()}: {path} ({file_size:,} bytes)")
            else:
                print(f"  {key.upper()}: {path}")

        print(f"\nTest command:")
        print(f"  cd {output_dir} && bash run_mips_tests.sh")

    except Exception as e:
        print(f"  Error generating: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print(f"\n  Successfully generated MIPS32 Linux processor!")


if __name__ == "__main__":
    main()
