#!/usr/bin/env python3
"""
Generate complete RV64IF processor (I + F + Zicsr extensions)
This includes all RV64I instructions plus single-precision floating-point instructions
and CSR access instructions needed for fcsr support.

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

# Test list for RV64I
RV64I_TESTS = [
    "add", "addi", "and", "andi", "auipc", "beq", "bge", "bgeu", "blt", "bltu",
    "bne", "jal", "jalr", "lb", "lbu", "lh", "lhu", "lui", "lw", "lwu", "ld",
    "or", "ori", "sb", "sh", "sll", "slli", "slt", "slti", "sltiu", "sltu",
    "sra", "srai", "srl", "srli", "sub", "sw", "sd", "xor", "xori",
    "addw", "addiw", "subw", "sllw", "slliw", "srlw", "srliw", "sraw", "sraiw"
]

# Test list for RV64F (single-precision floating-point)
RV64F_TESTS = [
    "fadd", "fclass", "fcmp", "fcvt", "fcvt_w", "fdiv", "fmadd", "fmin",
    "fmv", "fsgnj", "fsqrt", "fsub", "ldst", "recoding"
]

# Complete RV64I instruction set (49 instructions, excluding system/CSR)
RV64I_INSTRUCTIONS = [
    # Base Arithmetic (5)
    'add', 'addi', 'sub', 'lui', 'auipc',

    # Logical (6)
    'and', 'andi', 'or', 'ori', 'xor', 'xori',

    # Shifts - 64-bit (6)
    'sll', 'slli', 'srl', 'srli', 'sra', 'srai',

    # Compare (4)
    'slt', 'slti', 'sltu', 'sltiu',

    # Branches (6)
    'beq', 'bne', 'blt', 'bltu', 'bge', 'bgeu',

    # Jumps (2)
    'jal', 'jalr',

    # Loads - Base (5)
    'lw', 'lh', 'lhu', 'lb', 'lbu',

    # Stores - Base (3)
    'sw', 'sh', 'sb',

    # RV64I-specific Memory Operations (3)
    'ld', 'lwu', 'sd',

    # RV64I-specific Word Operations - Immediate (4)
    'addiw', 'slliw', 'srliw', 'sraiw',

    # RV64I-specific Word Operations - Register (5)
    'addw', 'subw', 'sllw', 'srlw', 'sraw',

    # Fences (2) - NOP for single-cycle, single-core
    'fence', 'fence_i',
]

# RV64F single-precision floating-point instructions (30 instructions)
# Includes all RV32F instructions adapted for 64-bit plus RV64F-specific
RV64F_INSTRUCTIONS = [
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

    # Conversions (float <-> 32-bit int)
    'fcvt_w_s', 'fcvt_wu_s', 'fcvt_s_w', 'fcvt_s_wu',

    # RV64F-specific: Conversions (float <-> 64-bit int)
    'fcvt_l_s', 'fcvt_lu_s', 'fcvt_s_l', 'fcvt_s_lu',

    # Move (between int and FP registers)
    'fmv_x_w', 'fmv_w_x',

    # Load/Store
    'flw', 'fsw',
]

# Zicsr CSR access instructions (6 instructions) - needed for fcsr access
ZICSR_INSTRUCTIONS = [
    'csrrw', 'csrrs', 'csrrc',      # Register operand versions
    'csrrwi', 'csrrsi', 'csrrci',   # Immediate operand versions
]

# Combined instruction set
INSTRUCTIONS = RV64I_INSTRUCTIONS + RV64F_INSTRUCTIONS + ZICSR_INSTRUCTIONS


def apply_memory_transform(merged_graph):
    """Apply port width setting for 64-bit word-addressed unified memory."""
    umem_node = merged_graph.nodes.get('umem')
    if umem_node:
        access_widths = umem_node.data.get('access_widths', [64])
        max_width = max(access_widths) if access_widths else 64
        print(f"  umem access widths: {access_widths}, max: {max_width}")

        # Apply set_port_width transformation
        transform = MemoryAccessTransform(merged_graph)
        spec = MemoryAccessTransformSpec(
            memory='umem',
            strategy='set_port_width',
            current_width=max_width,
            target_width=64,  # 64-bit memory for RV64
            direction='forward'
        )
        result = transform.apply_transformation(spec)
        if result.get('transformed'):
            print(f"  Transformed: added {len(result.get('nodes_added', []))} byte mux nodes")
        else:
            print(f"  Skipped: {result.get('reason', 'unknown')}")


def apply_fp_multicycle_latency(merged_graph):
    """Apply fixed multi-cycle latency to FP div and sqrt operations.

    The PULP div/sqrt unit has fixed latency for FP32:
    - 8 iteration cycles (with 3 iteration units, the default)
    - +2 cycles for setup/output
    - Total: 10 cycles fixed
    """
    fp_div_id = 'fp_div(f1, f2)'
    fp_sqrt_id = 'fp_sqrt(f1)'

    latency_specs = []

    if fp_div_id in merged_graph.nodes:
        latency_specs.append(OperationLatencySpec(fp_div_id, 10, 'fp_division'))
        print(f"  Found {fp_div_id}, will apply 10-cycle latency")
    else:
        print(f"  {fp_div_id} not found in graph")

    if fp_sqrt_id in merged_graph.nodes:
        latency_specs.append(OperationLatencySpec(fp_sqrt_id, 10, 'fp_sqrt'))
        print(f"  Found {fp_sqrt_id}, will apply 10-cycle latency")
    else:
        print(f"  {fp_sqrt_id} not found in graph")

    if latency_specs:
        result = apply_multi_cycle_operations(merged_graph, latency_specs)
        if result:
            print(f"  Successfully applied multi-cycle latency to {len(latency_specs)} FP operation(s)")
        else:
            print(f"  Failed to apply multi-cycle latency")
        return result
    else:
        print(f"  No FP div/sqrt operations found to apply latency")
        return False


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
        pc_width=64, is_pipelined=False
    )
    test_script = generate_vhdl_test_script(
        entity_name, output_dir,
        arch="RISC-V 64-bit IF",
        tests=RV64I_TESTS + RV64F_TESTS,
        test_base_path="../../isa/riscv64/riscv-tests/isa/rv64ui-isacomp-",
        data_width=64, is_pipelined=False
    )
    files['test_runner_tb'] = Path(test_runner_tb)
    files['test_script'] = Path(test_script)
    print(f"  Generated: {test_runner_tb}")
    print(f"  Generated: {test_script}")

    # Optionally verify compilation with GHDL
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


def generate_pyrtl(merged_graph, module_name, output_dir):
    """Generate PyRTL output with testbench files."""
    import pyrtl
    from backends.pyrtl import generate_pyrtl as gen_pyrtl, generate_pyrtl_testbench_files, PyRTLTestbenchConfig
    from pathlib import Path

    # Generate PyRTL design
    pyrtl_block = gen_pyrtl(merged_graph, module_name)

    # Create testbench configuration
    config = PyRTLTestbenchConfig(
        module_name=module_name,
        timeout_cycles=10000,
        imem_size=16384,
        dmem_size=16384,
        arch='riscv64'
    )

    # Generate testbench files with instructions list for test runner
    output_path = Path(output_dir)
    files = generate_pyrtl_testbench_files(
        pyrtl_block,
        module_name=module_name,
        output_dir=output_path,
        config=config,
        instructions=INSTRUCTIONS,
        arch='riscv64'
    )

    # Also output the PyRTL block as Verilog for inspection
    verilog_file = output_path / f"{module_name}.v"
    with open(verilog_file, 'w') as f:
        pyrtl.output_to_verilog(f, block=pyrtl_block)
    files['verilog'] = verilog_file

    print(f"  PyRTL block contains:")
    print(f"    {len(list(pyrtl_block.logic))} logic operations")
    print(f"    {len(list(pyrtl_block.wirevector_set))} wires")

    return files


def generate_circt(merged_graph, module_name, output_dir):
    """Generate CIRCT MLIR output and convert to Verilog."""
    import re
    import shutil
    from pathlib import Path
    from backends.circt.circt_generator import generate_circt as gen_circt_mlir
    from backends.circt.circt_testbench import generate_circt_testbench

    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Generate CIRCT MLIR
    mlir_output = gen_circt_mlir(merged_graph, module_name)

    # Write MLIR file
    mlir_file = output_path / f'{module_name}.mlir'
    with open(mlir_file, 'w') as f:
        f.write(mlir_output)

    files = {'mlir': str(mlir_file)}
    print(f"  Generated MLIR: {mlir_file} ({len(mlir_output)} bytes)")

    # Find firtool in PATH
    firtool_path = shutil.which('firtool')
    if firtool_path is None:
        raise RuntimeError("firtool not found in PATH. Please install CIRCT and ensure firtool is available.")

    # Convert to Verilog using firtool
    if firtool_path:
        import subprocess
        sv_file = output_path / f'{module_name}.sv'
        try:
            result = subprocess.run(
                [firtool_path, str(mlir_file), '-o', str(sv_file)],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode == 0:
                files['systemverilog'] = str(sv_file)
                print(f"  Generated SystemVerilog: {sv_file}")

                # Post-process for Verilator compatibility:
                # Convert packed arrays to unpacked arrays for $readmemh support
                with open(sv_file, 'r') as f:
                    content = f.read()

                # Fix umem: reg [N:0][63:0] umem -> reg [63:0] umem [0:N]
                content = re.sub(
                    r'reg\s+\[(\d+):0\]\[(\d+):0\]\s+umem;',
                    r'reg [\2:0] umem [0:\1];',
                    content
                )

                with open(sv_file, 'w') as f:
                    f.write(content)
                print("  Post-processed for Verilator compatibility")

                # Generate testbench and test runner
                tb_files = generate_circt_testbench(
                    str(sv_file),
                    module_name,
                    'riscv64',
                    INSTRUCTIONS
                )
                files.update(tb_files)
                print(f"  Generated testbench: {tb_files.get('testbench')}")
                print(f"  Generated test runner: {tb_files.get('test_runner')}")
            else:
                print(f"  firtool conversion failed:")
                print(f"    {result.stderr[:500]}")
        except FileNotFoundError:
            print("  firtool not found in PATH, skipping Verilog conversion")
        except subprocess.TimeoutExpired:
            print("  firtool timed out")
        except Exception as e:
            print(f"  Error running firtool: {e}")

    return files


def main():
    parser = argparse.ArgumentParser(
        description='Generate complete RV64IF processor from ISA definitions'
    )
    parser.add_argument(
        '--backend', '-b',
        choices=['verilog', 'vhdl', 'pyrtl', 'circt'],
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
        help='Output directory (default: <backend>/riscv64if_complete)'
    )
    args = parser.parse_args()

    module_name = 'riscv64if_complete'
    if args.output_dir:
        output_dir = args.output_dir
    elif args.backend == 'circt':
        output_dir = 'examples/verilog/circt_riscv64if'
    elif args.backend == 'pyrtl':
        output_dir = 'examples/pyrtl/riscv64if_complete'
    elif args.backend == 'verilog':
        output_dir = f'examples/verilog/riscv64if_complete'
    else:
        output_dir = f'{args.backend}/riscv64if_complete'

    print("=" * 70)
    print(f"RV64IF Processor Generator ({args.backend.upper()} backend)")
    print("=" * 70)
    print(f"\nGenerating RV64IF processor with {len(INSTRUCTIONS)} instructions...")
    print(f"  RV64I:  {len(RV64I_INSTRUCTIONS)} instructions")
    print(f"  RV64F:  {len(RV64F_INSTRUCTIONS)} instructions")
    print(f"  Zicsr:  {len(ZICSR_INSTRUCTIONS)} instructions")

    # Step 1: Parse and merge ISA files
    print("\n" + "=" * 70)
    print("Step 1: Parsing and merging ISA files...")
    print("=" * 70)

    # Map instruction names to file paths
    # I instructions are in isa/riscv64/, F instructions are in isa/riscv64/f/, CSR in isa/riscv64/csr/
    isa_files = {}
    for instr in RV64I_INSTRUCTIONS:
        isa_files[instr] = f"isa/riscv64/{instr}.isa"
    for instr in RV64F_INSTRUCTIONS:
        isa_files[instr] = f"isa/riscv64/f/{instr}.isa"
    for instr in ZICSR_INSTRUCTIONS:
        isa_files[instr] = f"isa/riscv64/csr/{instr}.isa"

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
    fp_div_id = 'fp_div(f1, f2)'
    fp_sqrt_id = 'fp_sqrt(f1)'
    for op_id in [fp_div_id, fp_sqrt_id]:
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
        elif args.backend == 'pyrtl':
            files = generate_pyrtl(merged_graph, module_name, output_dir)
        elif args.backend == 'circt':
            files = generate_circt(merged_graph, module_name, output_dir)

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
    print(f"  Successfully generated complete RV64IF processor")
    print(f"  {len(RV64I_INSTRUCTIONS)} RV64I instructions implemented")
    print(f"  {len(RV64F_INSTRUCTIONS)} RV64F instructions implemented")
    print(f"  {len(ZICSR_INSTRUCTIONS)} Zicsr instructions implemented")
    print(f"  {len(merged_graph.nodes)} nodes in merged graph")
    print(f"  {len(merged_graph.edges)} edges in merged graph")
    print(f"  Backend: {args.backend.upper()}")
    print(f"  Output: {output_dir}/")

    print("\nKey features:")
    print("  - 64-bit register file (x0-x31)")
    print("  - 64-bit program counter")
    print("  - 32-bit FP register file (f0-f31, single precision)")
    print("  - All RV64I instructions")
    print("  - 30 RV64F instructions (including L/LU conversions)")
    print("  - Multi-cycle FP divide and square root (10 cycles)")

    print("\n" + "=" * 70)
    print("Done!")
    print("=" * 70)


if __name__ == "__main__":
    main()
