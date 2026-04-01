#!/usr/bin/env python3
"""
Generate complete J4 (SuperH-4) processor with all instructions.

This includes all arithmetic, logical, shift, compare, branch, jump, load, and store instructions
for full SH-4 core compatibility, plus FPU instructions for single-precision floating-point.

Supports Verilog, VHDL, PyRTL, and CIRCT backends via --backend argument.
"""
import sys
import os
import argparse

# Add parent directories to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core.graph_merger import merge_instructions
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec
from backends.vhdl.test_generator import generate_vhdl_test_runner_tb, generate_vhdl_test_script

# Test list for J4 (tests that have assembly test files)
J4_TESTS = [
    "add", "sub", "and", "or", "xor", "mov", "nop"
]

# Complete J4/SH-4 instruction set (202 instructions total)
# Includes all J2/SH-2 integer instructions plus SH-4 specific features, FPU, and MMU
INSTRUCTIONS = [
    # Arithmetic (19)
    'add', 'addc', 'addi', 'addv', 'sub', 'subc', 'subv', 'neg', 'negc',
    'mull', 'mulsw', 'muluw', 'dmulsl', 'dmulul', 'dt',
    'extsb', 'extsw', 'extub', 'extuw',

    # Logical (9)
    'and', 'andi', 'or', 'ori', 'xor', 'xori', 'not', 'tst', 'tsti',

    # Shift & Rotate (16)
    'shal', 'shar',
    'shll', 'shll2', 'shll8', 'shll16',
    'shlr', 'shlr2', 'shlr8', 'shlr16',
    'rotl', 'rotr', 'rotcl', 'rotcr',
    'shad', 'shld',

    # Data Movement - Basic (20)
    'mov', 'movi', 'mova', 'movt',
    'movl', 'movl_store', 'movl_postinc', 'movl_predec',
    'movl_indexed', 'movl_indexed_store', 'movl_pcrel',
    'movw', 'movw_store', 'movw_pcrel',
    'movb', 'movb_store',
    'swapb', 'swapw', 'xtrct',

    # Data Movement - Byte/Word Extended (8)
    'movb_postinc', 'movw_postinc',
    'movb_predec', 'movw_predec',
    'movb_indexed', 'movw_indexed',
    'movb_indexed_store', 'movw_indexed_store',

    # Data Movement - Displacement (6)
    'movb_disp_load', 'movw_disp_load', 'movl_disp_load',
    'movb_disp_store', 'movw_disp_store', 'movl_disp_store',

    # Data Movement - GBR-relative (6)
    'movb_gbr_load', 'movw_gbr_load', 'movl_gbr_load',
    'movb_gbr_store', 'movw_gbr_store', 'movl_gbr_store',

    # GBR Memory Modify (4)
    'andb_gbr', 'orb_gbr', 'tstb_gbr', 'xorb_gbr',

    # Comparison (9)
    'cmpeq', 'cmpge', 'cmpgt', 'cmphi', 'cmphs',
    'cmppl', 'cmppz', 'cmpimm', 'cmpstr',

    # Branch & Control (11)
    'bt', 'bf', 'bts', 'bfs',
    'bra', 'braf', 'bsr', 'bsrf',
    'jmp', 'jsr', 'rts',

    # System Control - Basic (11)
    'clrt', 'sett',
    'lds_pr', 'sts_pr',
    'lds_macl', 'sts_macl', 'lds_mach', 'sts_mach',
    'lds_gbr', 'sts_gbr',

    # System Control - Privileged (6)
    'ldc_sr', 'stc_sr',
    'ldc_vbr', 'stc_vbr',
    'rte', 'sleep',

    # SH-4 Specific Control Registers (8)
    'stc_sgr', 'ldc_sgr',  # Saved GBR
    'stc_dbr', 'ldc_dbr',  # Debug Base Register
    'stc_ssr', 'ldc_ssr',  # Saved Status Register
    'stc_spc', 'ldc_spc',  # Saved Program Counter

    # SH-4 Bank Register Instructions (4)
    'ldc_rn_bank',         # LDC Rm,Rn_BANK - Load banked register
    'stc_rn_bank',         # STC Rm_BANK,Rn - Store banked register
    'ldcl_rn_bank',        # LDC.L @Rm+,Rn_BANK - Load banked register from memory
    'stcl_rn_bank',        # STC.L Rm_BANK,@-Rn - Store banked register to memory

    # SH-4 GBR via Control Register Interface (3)
    # Note: GBR can be accessed via both STS/LDS (0x4n12/0x4n16) and STC/LDC (0x0n12/0x4n13/0x4n17)
    'stc_gbr',             # STC GBR,Rn (0x0n12) - Store GBR to register
    'stcl_gbr',            # STC.L GBR,@-Rn (0x4n13) - Store GBR to stack
    'ldcl_gbr',            # LDC.L @Rn+,GBR (0x4n17) - Load GBR from stack

    # Stack Push/Pop - System Registers (24)
    'stsl_pr', 'ldsl_pr',               # STS.L/LDS.L PR,@-Rn / @Rn+,PR
    'stcl_sr', 'ldcl_sr',               # STC.L/LDC.L SR,@-Rn / @Rn+,SR
    'stcl_vbr', 'ldcl_vbr',             # STC.L/LDC.L VBR,@-Rn / @Rn+,VBR
    'stsl_gbr', 'ldsl_gbr',             # STS.L/LDS.L GBR,@-Rn / @Rn+,GBR
    'stsl_mach', 'ldsl_mach',           # STS.L/LDS.L MACH,@-Rn / @Rn+,MACH
    'stsl_macl', 'ldsl_macl',           # STS.L/LDS.L MACL,@-Rn / @Rn+,MACL
    'stsl_fpscr', 'ldsl_fpscr',         # STS.L/LDS.L FPSCR,@-Rn / @Rn+,FPSCR
    'stsl_fpul', 'ldsl_fpul',           # STS.L/LDS.L FPUL,@-Rn / @Rn+,FPUL
    'stcl_ssr', 'ldcl_ssr',             # STC.L/LDC.L SSR,@-Rn / @Rn+,SSR
    'stcl_spc', 'ldcl_spc',             # STC.L/LDC.L SPC,@-Rn / @Rn+,SPC
    'stcl_sgr',                         # STC.L SGR,@-Rn (read-only register)
    'stcl_dbr', 'ldcl_dbr',             # STC.L/LDC.L DBR,@-Rn / @Rn+,DBR

    # MAC Instructions (3)
    'clrmac', 'macl', 'macw',

    # Division (3)
    'div0s', 'div0u', 'div1',

    # Special (4)
    'nop', 'tasb', 'trapa', 'casl',

    # FPU Instructions - Single Precision (20)
    'fadd', 'fsub', 'fmul', 'fdiv',
    'fcmpeq', 'fcmpgt',
    'fneg', 'fabs', 'fsqrt',
    'fmov', 'fmov_load', 'fmov_store',
    'flds', 'fsts',
    'float', 'ftrc',
    'lds_fpscr', 'sts_fpscr',
    'lds_fpul', 'sts_fpul',

    # FPU Instructions - Double Precision (13)
    'fadd_d', 'fsub_d', 'fmul_d', 'fdiv_d', 'fsqrt_d',
    'fabs_d', 'fneg_d',
    'fcmpeq_d', 'fcmpgt_d',
    'float_d', 'ftrc_d',
    'fcnvds', 'fcnvsd',                 # Double<->Single conversion

    # MMU Instructions (SH-4 specific) - software-managed TLB
    # NOTE: Custom STC/LDC instructions for PTEH/PTEL/TTB/TEA were REMOVED because
    # their encodings conflicted with standard SH4 instructions:
    #   stc_pteh (0x0n05) = MOV.W R0,@(R0,Rn), ldc_pteh (0x4n05) = ROTR Rn
    #   stc_ptel (0x0n15) = MOV.W R1,@(R0,Rn), ldc_ptel (0x4n15) = CMP/PL Rn
    #   stc_ttb  (0x0n25) = MOV.W R2,@(R0,Rn), ldc_ttb  (0x4n25) = ROTCR Rn
    #   stc_tea  (0x0n35) = MOV.W R3,@(R0,Rn)
    #   stc_mmucr(0x0n34) = MOV.B R3,@(R0,Rn)
    # Kernel accesses PTEH/PTEL/TTB/TEA/MMUCR via P4 memory-mapped I/O instead.
    # LDTLB reads PTEH/PTEL/MMUCR from umem at P4-mapped addresses.
    'ldtlb',                            # Load UTLB entry from PTEH/PTEL (reads from umem)
    'ldc_mmucr',                        # MMU Control Register (0x4n35, no conflict)

    # Cache Instructions (6) - NOPs for cache-less implementation
    'ocbi',                             # Operand Cache Block Invalidate
    'ocbp',                             # Operand Cache Block Purge
    'ocbwb',                            # Operand Cache Block Write-back
    'pref',                             # Prefetch to Cache
    'icbi',                             # Instruction Cache Block Invalidate
    'movca',                            # Move with Cache Block Allocation (acts as store)
]


def apply_memory_transform(merged_graph):
    """Apply port width setting for word-addressed unified memory.

    J4 has byte (8-bit), word (16-bit), and long (32-bit) memory accesses.
    This transformation creates byte selection muxes for sub-word accesses.
    """
    # Check for unified memory (umem) first, then dmem
    mem_node = merged_graph.nodes.get('umem') or merged_graph.nodes.get('dmem')
    mem_name = 'umem' if merged_graph.nodes.get('umem') else 'dmem'

    if mem_node:
        access_widths = mem_node.data.get('access_widths', [32])
        max_width = max(access_widths) if access_widths else 32
        print(f"  {mem_name} access widths: {access_widths}, max: {max_width}")

        # Apply set_port_width transformation to create byte selection mux nodes
        # J4/SH4 is a big-endian architecture
        transform = MemoryAccessTransform(merged_graph)
        spec = MemoryAccessTransformSpec(
            memory=mem_name,
            strategy='set_port_width',
            current_width=max_width,
            target_width=32,  # Word-addressed memory (32-bit)
            direction='forward',
            endianness='big'  # J4/SH4 is big-endian
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
        'imem_data_width': 16,  # J4 has 16-bit instructions
        'dmem_data_width': 32,  # J4 has 32-bit data
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
        arch="J4 (SuperH-4)",
        tests=J4_TESTS,
        test_base_path="../../isa/j4/j4-tests/isa/j4-isacomp-",
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
        imem_size=4096,
        dmem_size=4096,
        arch='j4'
    )

    # Generate testbench files with instructions list for test runner
    output_path = Path(output_dir)
    files = generate_pyrtl_testbench_files(
        pyrtl_block,
        module_name=module_name,
        output_dir=output_path,
        config=config,
        instructions=INSTRUCTIONS,
        arch='j4'
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

                # Fix imem: reg [N:0][15:0] imem -> reg [15:0] imem [0:N]
                content = re.sub(
                    r'reg\s+\[(\d+):0\]\[(\d+):0\]\s+imem;',
                    r'reg [\2:0] imem [0:\1];',
                    content
                )

                # Fix dmem: reg [N:0][31:0] dmem -> reg [31:0] dmem [0:N]
                content = re.sub(
                    r'reg\s+\[(\d+):0\]\[(\d+):0\]\s+dmem;',
                    r'reg [\2:0] dmem [0:\1];',
                    content
                )

                with open(sv_file, 'w') as f:
                    f.write(content)
                print("  Post-processed for Verilator compatibility")

                # Generate testbench and test runner
                tb_files = generate_circt_testbench(
                    str(sv_file),
                    module_name,
                    'j4',
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
        description='Generate complete J4 (SuperH-4) processor from ISA definitions'
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
        help='Output directory (default: <backend>/j4_complete)'
    )
    parser.add_argument(
        '--subset',
        choices=['minimal', 'basic', 'full'],
        default='full',
        help='Instruction subset to generate (default: full)'
    )
    args = parser.parse_args()

    # Select instruction subset
    if args.subset == 'minimal':
        # Minimal set for basic testing (no FPU)
        instructions = [
            'add', 'sub', 'and', 'or', 'xor', 'not',
            'mov', 'movi', 'movl', 'movl_store',
            'cmpeq', 'bt', 'bf', 'bra', 'nop'
        ]
        module_name = 'j4_minimal'
    elif args.subset == 'basic':
        # Basic set for running ISA tests (includes PC-relative loads for test macros)
        instructions = [
            'add', 'addi', 'sub', 'neg',
            'and', 'andi', 'or', 'ori', 'xor', 'xori', 'not',
            'shll', 'shlr', 'rotl', 'rotr',
            'mov', 'movi', 'mova', 'movl', 'movl_store', 'movl_pcrel',
            'movw', 'movw_store', 'movw_pcrel', 'movb', 'movb_store',
            'cmpeq', 'cmpgt', 'cmpge', 'cmphi', 'cmphs', 'cmpimm',
            'bt', 'bf', 'bra', 'jmp', 'jsr', 'rts',
            'clrt', 'sett', 'nop'
        ]
        module_name = 'j4_basic'
    else:
        instructions = INSTRUCTIONS
        module_name = 'j4_complete'

    if args.output_dir:
        output_dir = args.output_dir
    elif args.backend == 'circt':
        output_dir = f'examples/verilog/circt_{module_name}'
    elif args.backend == 'pyrtl':
        output_dir = f'examples/pyrtl/{module_name}'
    elif args.backend == 'verilog':
        output_dir = f'examples/verilog/{module_name}'
    else:
        output_dir = f'{args.backend}/{module_name}'

    print("=" * 70)
    print(f"J4 (SuperH-4) Processor Generator ({args.backend.upper()} backend)")
    print("=" * 70)
    print(f"\nGenerating J4 processor with {len(instructions)} instructions...")
    print(f"Subset: {args.subset}")
    print(f"Instructions: {', '.join(instructions[:10])}{'...' if len(instructions) > 10 else ''}")

    # Step 1: Parse and merge ISA files
    print("\n" + "=" * 70)
    print("Step 1: Parsing and merging ISA files...")
    print("=" * 70)
    # Use j4/mmu/ directory for MMU-enabled ISA files (with interrupt handling,
    # data/instruction TLB translation, and P4 memory-mapped register access)
    isa_files = {instr: f"isa/j4/mmu/{instr}.isa" for instr in instructions}

    try:
        merged_graph = merge_instructions(isa_files, defines={'MMU': ''})
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
    print(f"  Successfully generated J4 processor ({args.subset} subset)")
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
