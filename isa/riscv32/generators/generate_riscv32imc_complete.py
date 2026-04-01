#!/usr/bin/env python3
"""
Generate complete RV32IMC processor (I base + M extension + C compressed extension)

This combines:
- RV32I: Base integer instructions (37 instructions)
- M: Integer multiplication and division (8 instructions)
- C: Compressed 16-bit instructions (26 instructions)

Supports Verilog, VHDL, PyRTL, and CIRCT backends via --backend argument.
"""
import sys
import os
import argparse

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core.graph_merger import merge_instructions
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec
from backends.vhdl.test_generator import generate_vhdl_test_runner_tb, generate_vhdl_test_script

# Test list for RV32I
RV32I_TESTS = [
    "add", "addi", "and", "andi", "auipc", "beq", "bge", "bgeu", "blt", "bltu",
    "bne", "jal", "jalr", "lb", "lbu", "lh", "lhu", "lui", "lw", "or", "ori",
    "sb", "sh", "sll", "slli", "slt", "slti", "sltiu", "sltu", "sra", "srai",
    "srl", "srli", "sub", "sw", "xor", "xori"
]

# RV32I base instructions (37 instructions)
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
]

# M extension instructions (8 instructions)
M_INSTRUCTIONS = [
    'mul',     # Multiply lower 32 bits
    'mulh',    # Multiply high signed×signed
    'mulhsu',  # Multiply high signed×unsigned
    'mulhu',   # Multiply high unsigned×unsigned
    'div',     # Signed division
    'divu',    # Unsigned division
    'rem',     # Signed remainder
    'remu',    # Unsigned remainder
]

# C extension instructions (26 instructions)
# These are 16-bit compressed instructions that expand to 32-bit equivalents
C_INSTRUCTIONS = [
    # Stack-pointer relative (4)
    'c.addi4spn',  # Add immediate to SP forming pointer (scaled by 4)
    'c.addi16sp',  # Add immediate to SP (scaled by 16)
    'c.lwsp',      # Load word from stack
    'c.swsp',      # Store word to stack

    # Load/Store (2)
    'c.lw',        # Load word (compressed regs)
    'c.sw',        # Store word (compressed regs)

    # Arithmetic immediate (4)
    'c.li',        # Load immediate
    'c.lui',       # Load upper immediate
    'c.addi',      # Add immediate
    'c.nop',       # No operation

    # Register arithmetic (6)
    'c.mv',        # Move/copy register
    'c.add',       # Add registers
    'c.sub',       # Subtract (compressed regs)
    'c.and',       # Bitwise AND (compressed regs)
    'c.or',        # Bitwise OR (compressed regs)
    'c.xor',       # Bitwise XOR (compressed regs)

    # Shifts and immediate logic (4)
    'c.slli',      # Shift left logical immediate
    'c.srli',      # Shift right logical immediate (compressed regs)
    'c.srai',      # Shift right arithmetic immediate (compressed regs)
    'c.andi',      # AND immediate (compressed regs)

    # Jumps (4)
    'c.j',         # Unconditional jump
    'c.jal',       # Jump and link (RV32 only)
    'c.jr',        # Jump register
    'c.jalr',      # Jump and link register

    # Branches (2)
    'c.beqz',      # Branch if equal to zero
    'c.bnez',      # Branch if not equal to zero
]


def apply_memory_transform(merged_graph):
    """Apply port width setting for word-addressed unified memory."""
    umem_node = merged_graph.nodes.get('umem')
    if umem_node:
        access_widths = umem_node.data.get('access_widths', [32])
        max_width = max(access_widths) if access_widths else 32
        print(f"  umem access widths: {access_widths}, max: {max_width}")

        # Apply set_port_width transformation to create byte selection mux nodes
        # Use alignment='unaligned' to support RV32C halfword-aligned instruction fetch
        # This creates a second memory read port for cross-word boundary access
        transform = MemoryAccessTransform(merged_graph)
        spec = MemoryAccessTransformSpec(
            memory='umem',
            strategy='set_port_width',
            current_width=max_width,
            target_width=32,  # Word-addressed memory
            direction='forward',
            alignment='unaligned'  # Support halfword-aligned 32-bit instruction fetch
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
        imem_size=4096,
        dmem_size=4096
    )

    files = generate_vhdl_with_testbench(
        merged_graph,
        entity_name=entity_name,
        output_dir=output_dir,
        testbench_config=testbench_config,
        debug_outputs=['pc_rd']  # Expose PC for debugging
    )

    # Generate test runner testbench and script
    vhdl_file = str(files['rtl'])
    test_runner_tb = generate_vhdl_test_runner_tb(
        vhdl_file, entity_name, output_dir,
        pc_width=32, is_pipelined=False
    )
    test_script = generate_vhdl_test_script(
        entity_name, output_dir,
        arch="RISC-V 32-bit IMC",
        tests=RV32I_TESTS,
        test_base_path="../riscv-tests/isa/rv32ui-isacomp-",
        data_width=32, is_pipelined=False
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


def generate_pyrtl(merged_graph, module_name, output_dir, all_instructions):
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
        imem_size=4096,
        dmem_size=4096,
        arch='riscv32'
    )

    # Generate testbench files with instructions list for test runner
    output_path = Path(output_dir)
    files = generate_pyrtl_testbench_files(
        pyrtl_block,
        module_name=module_name,
        output_dir=output_path,
        config=config,
        instructions=all_instructions,
        arch='riscv32'
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


def generate_circt(merged_graph, module_name, output_dir, all_instructions):
    """Generate CIRCT MLIR output and convert to Verilog."""
    import re as regex
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

                # Fix umem: reg [N:0][31:0] umem -> reg [31:0] umem [0:N]
                content = regex.sub(
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
                    'riscv32',
                    all_instructions
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
        description='Generate complete RV32IMC processor from ISA definitions'
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
        help='Output directory (default: <backend>/riscv32imc_complete)'
    )
    args = parser.parse_args()

    module_name = 'riscv32imc_complete'
    if args.output_dir:
        output_dir = args.output_dir
    elif args.backend == 'circt':
        output_dir = 'examples/verilog/circt_riscv32imc'
    elif args.backend == 'pyrtl':
        output_dir = 'examples/pyrtl/riscv32imc_complete'
    elif args.backend == 'verilog':
        output_dir = f'examples/verilog/riscv32imc_complete'
    else:
        output_dir = f'{args.backend}/riscv32imc_complete'

    all_instructions = RV32I_INSTRUCTIONS + M_INSTRUCTIONS + C_INSTRUCTIONS

    print("=" * 70)
    print(f"RV32IMC Processor Generator ({args.backend.upper()} backend)")
    print("=" * 70)
    print(f"\nGenerating RV32IMC processor with {len(all_instructions)} instructions...")
    print(f"  RV32I: {len(RV32I_INSTRUCTIONS)} instructions")
    print(f"  M extension: {len(M_INSTRUCTIONS)} instructions")
    print(f"  C extension: {len(C_INSTRUCTIONS)} instructions")

    # Step 1: Parse and merge ISA files
    print("\n" + "=" * 70)
    print("Step 1: Parsing and merging ISA files...")
    print("=" * 70)

    # Get project root directory
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))

    isa_files = {}

    # Add RV32I base instructions
    print("\n  Adding RV32I base instructions...")
    for instr in RV32I_INSTRUCTIONS:
        isa_files[instr] = os.path.join(project_root, f"isa/riscv32/{instr}.isa")

    # Add M extension instructions
    print("  Adding M extension instructions...")
    for instr in M_INSTRUCTIONS:
        isa_files[instr] = os.path.join(project_root, f"isa/riscv32/m/{instr}.isa")

    # Add C extension instructions (use c_instr[15:0] variable for 16-bit format)
    print("  Adding C extension instructions...")
    for instr in C_INSTRUCTIONS:
        isa_files[instr] = os.path.join(project_root, f"isa/riscv32/c/{instr}.isa")

    try:
        merged_graph = merge_instructions(isa_files)
        print(f"\n  Successfully merged {len(all_instructions)} instructions")
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
        elif args.backend == 'pyrtl':
            files = generate_pyrtl(merged_graph, module_name, output_dir, all_instructions)
        elif args.backend == 'circt':
            files = generate_circt(merged_graph, module_name, output_dir, all_instructions)

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
    print(f"  Successfully generated complete RV32IMC processor")
    print(f"  {len(all_instructions)} instructions implemented:")
    print(f"    - RV32I: {len(RV32I_INSTRUCTIONS)} base integer instructions")
    print(f"    - M: {len(M_INSTRUCTIONS)} multiply/divide instructions")
    print(f"    - C: {len(C_INSTRUCTIONS)} compressed instructions")
    print(f"  {len(merged_graph.nodes)} nodes in merged graph")
    print(f"  {len(merged_graph.edges)} edges in merged graph")
    print(f"  Backend: {args.backend.upper()}")
    print(f"  Output: {output_dir}/")

    print("\n" + "=" * 70)
    print("Done!")
    print("=" * 70)


if __name__ == "__main__":
    main()
