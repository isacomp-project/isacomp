#!/usr/bin/env python3
"""
Generate complete RV32IFD processor (I + F + D + Zicsr extensions)
This includes all RV32I instructions plus single and double-precision
floating-point instructions and CSR access instructions needed for fcsr support.

Supports Verilog, VHDL, PyRTL, and CIRCT backends via --backend argument.
"""
import sys
import os
import argparse

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core.graph_merger import merge_instructions
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec
from opt.temporal.multi_cycle_operations import apply_multi_cycle_operations, OperationLatencySpec
from backends.vhdl.test_generator import generate_vhdl_test_runner_tb, generate_vhdl_test_script

# Test list for RV32I
RV32I_TESTS = [
    "add", "addi", "and", "andi", "auipc", "beq", "bge", "bgeu", "blt", "bltu",
    "bne", "jal", "jalr", "lb", "lbu", "lh", "lhu", "lui", "lw", "or", "ori",
    "sb", "sh", "sll", "slli", "slt", "slti", "sltiu", "sltu", "sra", "srai",
    "srl", "srli", "sub", "sw", "xor", "xori"
]

# Test list for RV32F (single-precision floating-point)
RV32F_TESTS = [
    "fadd", "fclass", "fcmp", "fcvt", "fcvt_w", "fdiv", "fmadd", "fmin",
    "fmv", "fsgnj", "fsqrt", "fsub", "ldst", "recoding"
]

# Test list for RV32D (double-precision floating-point)
RV32D_TESTS = [
    "fadd", "fclass", "fcmp", "fcvt", "fcvt_w", "fdiv", "fmadd", "fmin",
    "ldst", "move", "recoding"
]

# Complete RV32I instruction set (37 instructions, excluding system/CSR)
RV32I_INSTRUCTIONS = [
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

    # Fences (2) - NOP for single-cycle, single-core
    'fence', 'fence_i',
]

# RV32F single-precision floating-point instructions (26 instructions)
RV32F_INSTRUCTIONS = [
    # Arithmetic
    'fadd_s', 'fsub_s', 'fmul_s', 'fdiv_s', 'fsqrt_s',

    # Fused multiply-add
    'fmadd_s', 'fmsub_s', 'fnmadd_s', 'fnmsub_s',

    # Sign injection
    'fsgnj_s', 'fsgnjn_s', 'fsgnjx_s',

    # Min/Max
    'fmin_s', 'fmax_s',

    # Compare
    'feq_s', 'flt_s', 'fle_s',

    # Classification
    'fclass_s',

    # Conversions (float <-> int)
    'fcvt_w_s', 'fcvt_wu_s', 'fcvt_s_w', 'fcvt_s_wu',

    # Move (between int and FP registers)
    'fmv_x_w', 'fmv_w_x',

    # Load/Store
    'flw', 'fsw',
]

# RV32D double-precision floating-point instructions (26 instructions)
RV32D_INSTRUCTIONS = [
    # Arithmetic
    'fadd_d', 'fsub_d', 'fmul_d', 'fdiv_d', 'fsqrt_d',

    # Fused multiply-add
    'fmadd_d', 'fmsub_d', 'fnmadd_d', 'fnmsub_d',

    # Sign injection
    'fsgnj_d', 'fsgnjn_d', 'fsgnjx_d',

    # Min/Max
    'fmin_d', 'fmax_d',

    # Compare
    'feq_d', 'flt_d', 'fle_d',

    # Classification
    'fclass_d',

    # Conversions (double <-> int32)
    'fcvt_w_d', 'fcvt_wu_d', 'fcvt_d_w', 'fcvt_d_wu',

    # Conversions (double <-> single)
    'fcvt_s_d', 'fcvt_d_s',

    # Load/Store
    'fld', 'fsd',
]

# Zicsr CSR access instructions (6 instructions) - needed for fcsr access
ZICSR_INSTRUCTIONS = [
    'csrrw', 'csrrs', 'csrrc',      # Register operand versions
    'csrrwi', 'csrrsi', 'csrrci',   # Immediate operand versions
]

# Combined instruction set
INSTRUCTIONS = RV32I_INSTRUCTIONS + RV32F_INSTRUCTIONS + RV32D_INSTRUCTIONS + ZICSR_INSTRUCTIONS


def apply_memory_transform(merged_graph):
    """Apply port width setting for 64-bit word-addressed unified memory (for D extension)."""
    umem_node = merged_graph.nodes.get('umem')
    if umem_node:
        access_widths = umem_node.data.get('access_widths', [64])
        max_width = max(access_widths) if access_widths else 64
        print(f"  umem access widths: {access_widths}, max: {max_width}")

        # Apply set_port_width transformation to create byte selection mux nodes
        transform = MemoryAccessTransform(merged_graph)
        spec = MemoryAccessTransformSpec(
            memory='umem',
            strategy='set_port_width',
            current_width=max_width,
            target_width=64,  # 64-bit memory for D extension
            direction='forward'
        )
        result = transform.apply_transformation(spec)
        if result.get('transformed'):
            print(f"  Transformed: added {len(result.get('nodes_added', []))} byte mux nodes")
        else:
            print(f"  Skipped: {result.get('reason', 'unknown')}")


def generate_verilog(merged_graph, module_name, output_dir):
    """Generate Verilog output."""
    from backends.verilog import generate_verilog_with_testbench

    testbench_config = {
        'timeout_cycles': 10000
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
        imem_size=8192,
        dmem_size=8192
    )

    files = generate_vhdl_with_testbench(
        merged_graph,
        entity_name=entity_name,
        output_dir=output_dir,
        testbench_config=testbench_config,
        debug_outputs=['pc_rd']
    )

    # Generate test runner testbench and script
    vhdl_file = str(files['rtl'])
    test_runner_tb = generate_vhdl_test_runner_tb(
        vhdl_file, entity_name, output_dir,
        pc_width=32, is_pipelined=False
    )
    test_script = generate_vhdl_test_script(
        entity_name, output_dir,
        arch="RISC-V 32-bit IFD",
        tests=RV32I_TESTS + RV32F_TESTS + RV32D_TESTS,
        test_base_path="../riscv-tests/isa/rv32ui-isacomp-",
        data_width=64, is_pipelined=False
    )
    files['test_runner_tb'] = Path(test_runner_tb)
    files['test_script'] = Path(test_script)
    print(f"  Generated: {test_runner_tb}")
    print(f"  Generated: {test_script}")

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
        description='Generate complete RV32IFD processor from ISA definitions'
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
        help='Output directory (default: <backend>/riscv32ifd_complete)'
    )
    args = parser.parse_args()

    module_name = 'riscv32ifd_complete'
    if args.output_dir:
        output_dir = args.output_dir
    elif args.backend == 'verilog':
        output_dir = f'examples/verilog/riscv32ifd_complete'
    else:
        output_dir = f'{args.backend}/riscv32ifd_complete'

    print("=" * 70)
    print(f"RV32IFD Processor Generator ({args.backend.upper()} backend)")
    print("=" * 70)
    print(f"\nGenerating RV32IFD processor with {len(INSTRUCTIONS)} instructions...")
    print(f"  RV32I:  {len(RV32I_INSTRUCTIONS)} instructions")
    print(f"  RV32F:  {len(RV32F_INSTRUCTIONS)} instructions")
    print(f"  RV32D:  {len(RV32D_INSTRUCTIONS)} instructions")
    print(f"  Zicsr:  {len(ZICSR_INSTRUCTIONS)} instructions")

    # Step 1: Parse and merge ISA files
    print("\n" + "=" * 70)
    print("Step 1: Parsing and merging ISA files...")
    print("=" * 70)

    # Map instruction names to file paths
    isa_files = {}
    for instr in RV32I_INSTRUCTIONS:
        isa_files[instr] = f"isa/riscv32/{instr}.isa"
    for instr in RV32F_INSTRUCTIONS:
        isa_files[instr] = f"isa/riscv32/f/{instr}.isa"
    for instr in RV32D_INSTRUCTIONS:
        isa_files[instr] = f"isa/riscv32/d/{instr}.isa"
    for instr in ZICSR_INSTRUCTIONS:
        isa_files[instr] = f"isa/riscv32/csr/{instr}.isa"

    try:
        merged_graph = merge_instructions(isa_files)
        print(f"  Successfully merged {len(INSTRUCTIONS)} instructions")
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

    # Step 3: Mark FP div/sqrt as multi-cycle (for CVFPU handshake-based stalling)
    print("\n" + "=" * 70)
    print("Step 3: Marking FP div/sqrt as multi-cycle (10 cycles, handshake-based)")
    print("=" * 70)
    # Both F and D extension div/sqrt operations
    fp_ops = [
        'fp_div(f1, f2)', 'fp_sqrt(f1)',           # F extension
        'fp_div_d(f1, f2)', 'fp_sqrt_d(f1)',       # D extension
    ]
    for op_id in fp_ops:
        if op_id in merged_graph.nodes:
            node = merged_graph.nodes[op_id]
            node.data['multi_cycle'] = True
            node.data['latency_cycles'] = 10
            print(f"  Marked {op_id} as multi-cycle (10 cycles)")
        else:
            print(f"  {op_id} not found in graph")

    # Step 4: Generate RTL
    print("\n" + "=" * 70)
    print(f"Step 4: Generating {args.backend.upper()} RTL and testbench...")
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
    print(f"  Successfully generated complete RV32IFD processor")
    print(f"  {len(RV32I_INSTRUCTIONS)} RV32I instructions implemented")
    print(f"  {len(RV32F_INSTRUCTIONS)} RV32F instructions implemented")
    print(f"  {len(RV32D_INSTRUCTIONS)} RV32D instructions implemented")
    print(f"  {len(ZICSR_INSTRUCTIONS)} Zicsr instructions implemented")
    print(f"  {len(merged_graph.nodes)} nodes in merged graph")
    print(f"  {len(merged_graph.edges)} edges in merged graph")
    print(f"  Backend: {args.backend.upper()}")
    print(f"  Output: {output_dir}/")

    print("\nKey features:")
    print("  - 32-bit integer register file (x0-x31)")
    print("  - 32-bit program counter")
    print("  - 64-bit FP register file (f0-f31, single and double precision)")
    print("  - All RV32I instructions")
    print("  - 26 RV32F instructions (single precision)")
    print("  - 26 RV32D instructions (double precision)")
    print("  - Multi-cycle FP divide and square root (10 cycles)")

    print("\n" + "=" * 70)
    print("Done!")
    print("=" * 70)


if __name__ == "__main__":
    main()
