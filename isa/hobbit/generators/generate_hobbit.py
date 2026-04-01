#!/usr/bin/env python3
"""
Generate AT&T Hobbit (ATT92010) processor from ISA specifications.

The Hobbit is a 32-bit stack-cache based processor derived from the CRISP
architecture. It has no general-purpose registers; instead, a 64-entry
hardware-managed stack cache maps the top of the program stack into fast
on-chip storage. Instructions use stack-offset addressing to reference
operands relative to the stack pointer.

This generates a single-cycle implementation from the .isa specifications.
Supports Verilog, VHDL, PyRTL, and CIRCT backends via --backend argument.

Usage:
    python3 isa/hobbit/generators/generate_hobbit.py
    python3 isa/hobbit/generators/generate_hobbit.py --backend vhdl
    python3 isa/hobbit/generators/generate_hobbit.py -o examples/verilog/hobbit_custom
"""
import sys
import os
import argparse

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core.graph_merger import merge_instructions
from backends.verilog import generate_verilog_with_testbench

# ============================================================================
# Hobbit instruction set
# ============================================================================

# Arithmetic instructions
ARITHMETIC = [
    'add_ss',       # ADD stack,stack (one-parcel)
    'add_cs',       # ADD imm,stack (one-parcel)
    'add_gen',      # ADD gen,gen (three-parcel)
    'add_imm',      # ADD imm16,stack (three-parcel, immediate source)
    'add_5p',       # ADD gen,gen (five-parcel, full 32-bit operands)
    'add3_ss',      # ADD3 stack,stack -> acc (one-parcel)
    'add3_cs',      # ADD3 imm,stack -> acc (one-parcel)
    'add3_ws',      # ADD3 word-aligned-imm,stack -> acc (one-parcel)
    'add3_gen',     # ADD3 gen,gen -> acc (three-parcel)
    'sub_gen',      # SUB gen,gen (three-parcel)
    'sub_imm',      # SUB imm16,stack (three-parcel, immediate source)
    'sub_5p',       # SUB gen,gen (five-parcel, full 32-bit operands)
    'sub3_gen',     # SUB3 gen,gen -> acc (three-parcel)
    'mul_gen',      # MUL gen,gen (three-parcel, with 64-bit overflow)
    'mul3_gen',     # MUL3 gen,gen -> acc (three-parcel, with 64-bit overflow)
    'div_gen',      # DIV gen,gen signed (three-parcel)
    'div3_gen',     # DIV3 gen,gen -> acc signed (three-parcel)
    'rem_gen',      # REM gen,gen signed (three-parcel)
    'rem3_gen',     # REM3 gen,gen -> acc signed (three-parcel)
    'udiv_gen',     # UDIV gen,gen unsigned (three-parcel)
    'urem_gen',     # UREM gen,gen unsigned (three-parcel)
]

# Logical instructions
LOGICAL = [
    'and_ss',       # AND stack,stack (one-parcel)
    'and_gen',      # AND gen,gen (three-parcel)
    'and_imm',      # AND imm16,stack (three-parcel, immediate source)
    'and3_cs',      # AND3 imm,stack -> acc (one-parcel)
    'and3_gen',     # AND3 gen,gen -> acc (three-parcel)
    'or_gen',       # OR gen,gen (three-parcel)
    'or_imm',       # OR imm16,stack (three-parcel, immediate source)
    'or3_gen',      # OR3 gen,gen -> acc (three-parcel)
    'xor_gen',      # XOR gen,gen (three-parcel)
    'xor3_gen',     # XOR3 gen,gen -> acc (three-parcel)
]

# Interlocked (atomic) instructions (3 files)
INTERLOCKED = [
    'addi_gen',     # ADDI gen,gen atomic add (three-parcel)
    'andi_gen',     # ANDI gen,gen atomic AND (three-parcel)
    'ori_gen',      # ORI gen,gen atomic OR (three-parcel)
]

# Shift instructions (8 files)
SHIFT = [
    'shl_gen',      # SHL gen,gen (three-parcel)
    'shl3_cs',      # SHL3 imm,stack -> acc (one-parcel)
    'shl3_gen',     # SHL3 gen,gen -> acc (three-parcel)
    'shr_gen',      # SHR arithmetic right (three-parcel)
    'shr3_cs',      # SHR3 imm,stack -> acc (one-parcel)
    'shr3_gen',     # SHR3 gen,gen -> acc (three-parcel)
    'ushr_gen',     # USHR logical right (three-parcel)
    'ushr3_gen',    # USHR3 gen,gen -> acc (three-parcel)
]

# Compare instructions
COMPARE = [
    'cmpeq_ss',     # CMPEQ imm,stack (one-parcel, opcode 0x10)
    'cmpeq_ss2',    # CMPEQ stack,stack (one-parcel, opcode 0x13)
    'cmpeq_gen',    # CMPEQ gen,gen (three-parcel)
    'cmpeq_imm',    # CMPEQ imm16,stack (three-parcel, immediate source)
    'cmpgt_ss',     # CMPGT stack,stack signed (one-parcel, opcode 0x11)
    'cmpgt_cs',     # CMPGT imm,stack signed (one-parcel, opcode 0x12)
    'cmpgt_gen',    # CMPGT gen,gen signed (three-parcel)
    'cmphi_gen',    # CMPHI gen,gen unsigned (three-parcel)
]

# Move instructions
MOVE = [
    'mov_ss',       # MOV stack,stack (one-parcel)
    'mov_cs',       # MOV imm,stack (one-parcel)
    'mov_ws',       # MOV word-aligned-imm,stack (one-parcel)
    'mov_is',       # MOV indirect-stack,stack (one-parcel, opcode 0x19)
    'mov_si',       # MOV stack,indirect-stack (one-parcel, opcode 0x1A)
    'mov_ii',       # MOV indirect-stack,indirect-stack (one-parcel, opcode 0x1B)
    'mov_gen',      # MOV gen,gen (three-parcel)
    'mov_imm',      # MOV imm16,stack (three-parcel, immediate source)
    'mov_5p',       # MOV gen,gen (five-parcel, full 32-bit operands)
    'mov_5p_imm',   # MOV imm32,stack (five-parcel, 32-bit immediate)
    'mova_ss',      # MOVA stack,stack (one-parcel)
    'mova_gen',     # MOVA gen,gen (three-parcel)
    'ldraa_gen',    # LDRAA load relative address -> acc (three-parcel)
]

# Program control instructions
CONTROL = [
    'jmp_pcrel',    # JMP PC-relative (one-parcel)
    'jmp_gen',      # JMP PC-relative (three-parcel, far jump)
    'jmpfn_pcrel',  # JMPFN flag=0, predict not taken (one-parcel)
    'jmpfy_pcrel',  # JMPFY flag=0, predict taken (one-parcel)
    'jmpfy_gen',    # JMPFY flag=0, predict taken (three-parcel)
    'jmptn_pcrel',  # JMPTN flag=1, predict not taken (one-parcel)
    'jmpty_pcrel',  # JMPTY flag=1, predict taken (one-parcel)
    'jmpty_gen',    # JMPTY flag=1, predict taken (three-parcel)
    'call_pcrel',   # CALL PC-relative (one-parcel)
    'call_gen',     # CALL PC-relative (three-parcel, far call)
    'call_abs',     # CALL absolute (three-parcel)
    'return_stk',   # RETURN stack offset (one-parcel)
    'return_gen',   # RETURN stack offset (three-parcel, large frame)
    'enter_stk',    # ENTER stack offset (one-parcel)
    'enter_gen',    # ENTER stack offset (three-parcel, large frame)
    'catch_stk',    # CATCH stack offset (one-parcel)
    'catch_gen',    # CATCH stack offset (three-parcel)
    'popn_stk',     # POPN stack offset (one-parcel)
    'popn_gen',     # POPN stack offset (three-parcel)
]

# Kernel instructions (3 files)
KERNEL = [
    'kcall_imm',    # KCALL immediate (one-parcel)
    'kret',         # KRET (one-parcel)
    'cret',         # CRET context return (one-parcel)
]

# Tagged arithmetic (2 files)
TAGGED = [
    'tadd_gen',     # TADD gen,gen tagged add (three-parcel)
    'tsub_gen',     # TSUB gen,gen tagged sub (three-parcel)
]

# CPU prefix (register access) instructions
CPU_PREFIX = [
    'cpu_mov_reg_to_stk',  # CPU; MOV %reg, dst (read control register)
    'cpu_mov_stk_to_reg',  # CPU; MOV src, %reg (write control register)
]

# Other instructions
OTHER = [
    'nop',              # NOP (one-parcel)
    'testc',            # TESTC copy carry to flag (one-parcel)
    'testv',            # TESTV copy overflow to flag (one-parcel)
    'clre',             # CLRE clear enter guard (one-parcel)
    'flushi',           # FLUSHI flush instruction cache (one-parcel)
    'flushp',           # FLUSHP flush prefetch buffer (one-parcel)
    'flushd',           # FLUSHD flush data cache (one-parcel, triggers exception)
    'flushpte_gen',     # FLUSHPTE flush page TLB entry (three-parcel)
    'flushpbe_gen',     # FLUSHPBE flush prefetch buffer entry (three-parcel)
    'flushdce_gen',     # FLUSHDCE flush data cache entry (three-parcel)
    'dqm_gen',          # DQM double/quad-word move (three-parcel)
]

# All instructions combined
ALL_INSTRUCTIONS = (
    ARITHMETIC + LOGICAL + INTERLOCKED + SHIFT +
    COMPARE + MOVE + CONTROL + KERNEL + TAGGED + CPU_PREFIX + OTHER
)

# Core subset: useful for initial testing / simulation
CORE_INSTRUCTIONS = (
    ARITHMETIC[:9] +    # ADD variants (incl. imm, 5p, ws), SUB
    LOGICAL[:5] +       # AND variants incl. imm
    SHIFT[:3] +         # SHL, SHL3
    COMPARE[:5] +       # CMPEQ (all), CMPGT (all)
    MOVE[:7] +          # MOV variants incl. indirect
    CONTROL[:12] +      # JMP (short+far), CALL (short+far+abs), RETURN, ENTER
    [
        'nop',
        'testc',
        'testv',
    ]
)


def main():
    parser = argparse.ArgumentParser(
        description='Generate AT&T Hobbit (ATT92010) processor')
    parser.add_argument(
        '--backend', choices=['verilog', 'vhdl', 'pyrtl', 'circt'],
        default='verilog',
        help='Output backend (default: verilog)')
    parser.add_argument(
        '-o', '--output-dir',
        help='Output directory (default: <backend>/hobbit)')
    parser.add_argument(
        '--core-only', action='store_true',
        help='Generate only core instruction subset (27 instructions)')
    parser.add_argument(
        '--no-kernel', action='store_true',
        help='Exclude kernel-mode instructions (KCALL, KRET, CRET)')
    parser.add_argument(
        '--no-tagged', action='store_true',
        help='Exclude tagged arithmetic (TADD, TSUB)')
    parser.add_argument(
        '--module-name', default='hobbit',
        help='Verilog module name (default: hobbit)')
    args = parser.parse_args()

    # Select instruction set
    if args.core_only:
        instructions = list(CORE_INSTRUCTIONS)
        variant = 'core'
    else:
        instructions = list(ALL_INSTRUCTIONS)
        variant = 'complete'

    if args.no_kernel:
        instructions = [i for i in instructions if i not in KERNEL]
    if args.no_tagged:
        instructions = [i for i in instructions if i not in TAGGED]

    output_dir = args.output_dir or f'examples/verilog/hobbit_{variant}' if args.backend == 'verilog' else f'{args.backend}/hobbit_{variant}'
    module_name = args.module_name

    print("=" * 70)
    print("AT&T Hobbit (ATT92010) Processor Generator")
    print("=" * 70)
    print(f"\nVariant: {variant}")
    print(f"Instructions: {len(instructions)}")
    print(f"Backend: {args.backend}")
    print(f"Output: {output_dir}/")

    # Print instruction breakdown
    categories = [
        ('Arithmetic', ARITHMETIC),
        ('Logical', LOGICAL),
        ('Interlocked', INTERLOCKED),
        ('Shift', SHIFT),
        ('Compare', COMPARE),
        ('Move', MOVE),
        ('Control', CONTROL),
        ('Kernel', KERNEL),
        ('Tagged', TAGGED),
        ('Other', OTHER),
    ]

    print("\nInstruction breakdown:")
    for name, cat in categories:
        included = [i for i in cat if i in instructions]
        if included:
            print(f"  {name}: {len(included)}/{len(cat)}")

    # Build ISA file paths
    print("\n" + "=" * 70)
    print("PARSING AND MERGING ISA FILES")
    print("=" * 70)

    isa_files = {instr: f"isa/hobbit/{instr}.isa" for instr in instructions}

    print(f"\nMerging {len(instructions)} ISA specifications...")
    merged_graph = merge_instructions(isa_files)
    print(f"Merged graph has {len(merged_graph.nodes)} nodes and {len(merged_graph.edges)} edges")

    # Configure memory: the Hobbit uses a unified memory space
    # The stack cache is modeled as part of this memory
    umem_node = merged_graph.nodes.get('umem')
    if umem_node:
        print(f"\nMemory node 'umem' found")
        access_widths = umem_node.data.get('access_widths', [32])
        print(f"  Access widths: {access_widths}")

    # Generate output
    print("\n" + "=" * 70)
    print(f"GENERATING {args.backend.upper()}")
    print("=" * 70)
    print(f"\nOutput directory: {output_dir}/")

    try:
        if args.backend == 'verilog':
            testbench_config = {
                'timeout_cycles': 10000,
            }
            files = generate_verilog_with_testbench(
                merged_graph,
                module_name=module_name,
                output_dir=output_dir,
                testbench_config=testbench_config,
            )
        elif args.backend == 'vhdl':
            from backends.vhdl import generate_vhdl_with_testbench
            files = generate_vhdl_with_testbench(
                merged_graph,
                entity_name=module_name,
                output_dir=output_dir,
            )
        elif args.backend == 'pyrtl':
            from backends.pyrtl import generate_pyrtl
            files = generate_pyrtl(
                merged_graph,
                module_name=module_name,
                output_dir=output_dir,
            )
        elif args.backend == 'circt':
            from backends.circt import generate_circt
            files = generate_circt(
                merged_graph,
                module_name=module_name,
                output_dir=output_dir,
            )

        print("\n" + "=" * 70)
        print("GENERATION COMPLETE")
        print("=" * 70)
        print("\nGenerated files:")
        for key, path in files.items():
            if hasattr(path, 'stat'):
                file_size = path.stat().st_size if path.exists() else 0
                print(f"  {key}: {path} ({file_size:,} bytes)")
            else:
                print(f"  {key}: {path}")

    except Exception as e:
        print(f"\n  Error generating {args.backend.upper()}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print(f"\nSuccessfully generated Hobbit processor with {len(instructions)} instructions!")
    print(f"  Backend: {args.backend.upper()}")
    print(f"  Module: {module_name}")
    print("\nNote: This is a single-cycle implementation.")
    print("The Hobbit's stack cache is modeled as unified memory accessed")
    print("via SP-relative addressing. The hardware stack cache management")
    print("(ENTER flush, CATCH refill) is architecturally modeled.")

    if args.backend == 'verilog':
        print(f"\nTo simulate with Icarus Verilog:")
        print(f"  cd {output_dir}")
        print(f"  iverilog -o {module_name}_sim {module_name}.v {module_name}_tb.v")
        print(f"  vvp {module_name}_sim")


if __name__ == "__main__":
    main()
