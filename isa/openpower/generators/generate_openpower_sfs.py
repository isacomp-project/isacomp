#!/usr/bin/env python3
"""
Generate OpenPOWER Scalar Fixed-point Subset (SFS) processor.
This includes fixed-point arithmetic, logical, shift, compare, branch, load, and store instructions
from the Power ISA v3.0B specification.

Supports Verilog, VHDL, PyRTL, and CIRCT backends via --backend argument.
Supports --engine python (default) or --engine rust to use the Rust isacomp_core backend.
"""
import sys
import os
import argparse

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

# Engine selection — set by main() before use.
_engine = 'python'

def _init_engine(engine):
    """Initialize the engine-specific imports."""
    global _engine, merge_instructions, MemoryAccessTransform, MemoryAccessTransformSpec
    _engine = engine

    if engine == 'rust':
        try:
            import isacomp_core as _rc
        except ImportError:
            print("Error: isacomp_core not found. Build it with:")
            print("  cd rust_core && maturin develop")
            sys.exit(1)

        merge_instructions = _rc.merge_instructions

        class _RustMemoryAccessTransformSpec:
            def __init__(self, memory, strategy, current_width, target_width, direction='forward', **kwargs):
                self._inner = _rc.MemoryAccessTransformSpec(
                    memory, strategy, current_width, target_width, direction
                )
                self.memory = memory
                self.strategy = strategy
                self.current_width = current_width
                self.target_width = target_width
                self.direction = direction

        class _RustMemoryAccessTransform:
            def __init__(self, graph):
                self._graph = graph

            def apply_transformation(self, spec, dry_run=False):
                inner_spec = spec._inner if hasattr(spec, '_inner') else spec
                transform = _rc.MemoryAccessTransform(self._graph)
                result = transform.apply_transformation(inner_spec, dry_run)
                updated = transform.get_graph()
                result['graph'] = updated
                return result

        MemoryAccessTransformSpec = _RustMemoryAccessTransformSpec
        MemoryAccessTransform = _RustMemoryAccessTransform

        print(f"  Using Rust engine (isacomp_core)")
    else:
        from core.graph_merger import merge_instructions as _mi
        from opt.memory.memory_access_transform import MemoryAccessTransform as _mat, MemoryAccessTransformSpec as _mats

        merge_instructions = _mi
        MemoryAccessTransform = _mat
        MemoryAccessTransformSpec = _mats

        print(f"  Using Python engine")

from backends.verilog import generate_verilog_with_testbench

# OpenPOWER Scalar Fixed-point Subset (SFS) - 85 instructions total
# Based on libre-soc documentation and Power ISA v3.0B

INSTRUCTIONS = [
    # Fixed-point Arithmetic - Register (7)
    'add', 'subf', 'neg', 'mullw', 'mulld', 'divw', 'divwu',
    'divd', 'divdu',

    # Fixed-point Arithmetic - Immediate (4)
    'addi', 'addis', 'subfic', 'mulli',

    # Fixed-point Logical - Register (8)
    'and', 'or', 'xor', 'nand', 'nor', 'eqv', 'andc', 'orc',

    # Fixed-point Logical - Immediate (6)
    'andi', 'andis', 'ori', 'oris', 'xori', 'xoris',

    # Sign Extension (3)
    'extsb', 'extsh', 'extsw',

    # Shift - Word (4)
    'slw', 'srw', 'sraw', 'srawi',

    # Shift - Doubleword (4)
    'sld', 'srd', 'srad', 'sradi',

    # Rotate Doubleword - MD-form (2) - includes sldi/srdi extended mnemonics
    'rldicl', 'rldicr',

    # Rotate Word - M-form (1) - includes clrrwi, clrlwi, extlwi, etc.
    'rlwinm',

    # Load - Byte (2)
    'lbz', 'lbzx',

    # Load - Halfword (3)
    'lhz', 'lhzx', 'lha',

    # Load - Word (3)
    'lwz', 'lwzx', 'lwa',

    # Load - Doubleword (2)
    'ld', 'ldx',

    # Store - Byte (2)
    'stb', 'stbx',

    # Store - Halfword (2)
    'sth', 'sthx',

    # Store - Word (2)
    'stw', 'stwx',

    # Store - Doubleword (2)
    'std', 'stdx',

    # Branch - Unconditional (4)
    'b', 'ba', 'bl', 'bla',

    # Branch - Conditional (6)
    'bc', 'bcl', 'bclr', 'bclrl', 'bcctr', 'bcctrl',

    # Compare - Word (4)
    'cmpw', 'cmplw', 'cmpwi', 'cmplwi',

    # Compare - Doubleword (4)
    'cmpd', 'cmpld', 'cmpdi', 'cmpldi',

    # Condition Register Operations (6)
    'crand', 'cror', 'crxor', 'crnand', 'crnor', 'mcrf',

    # CR Move (2)
    'mfcr', 'mtcrf',

    # SPR Move - LR/CTR (2)
    'mfspr', 'mtspr',

    # SPR Move - XER (2) - needed for carry/overflow from sraw, srawi, subfic, etc.
    'mfspr_xer', 'mtspr_xer',
]

# Test list for OpenPOWER SFS
OPENPOWER_TESTS = [
    # Basic arithmetic
    "add", "addi", "addis", "subf", "subfic", "neg",
    # Multiply/divide
    "mulli", "mullw", "mulld", "divw", "divwu", "divd", "divdu",
    # Logical
    "and", "andi", "andis", "or", "ori", "oris", "xor", "xori", "xoris",
    "nand", "nor", "eqv", "andc", "orc",
    # Sign extension
    "extsb", "extsh", "extsw",
    # Shifts
    "slw", "srw", "sraw", "srawi", "sld", "srd", "srad", "sradi",
    # Rotate/Shift Doubleword (for sldi/srdi)
    "rldicl", "rldicr",
    # Rotate Word (for clrrwi, clrlwi, etc.)
    "rlwinm",
    # Loads
    "lbz", "lbzx", "lhz", "lhzx", "lha", "lwz", "lwzx", "lwa", "ld", "ldx",
    # Stores
    "stb", "stbx", "sth", "sthx", "stw", "stwx", "std", "stdx",
    # Branches
    "b", "ba", "bl", "bla", "bc", "bcl", "bclr", "bclrl", "bcctr", "bcctrl",
    # Compares
    "cmpw", "cmplw", "cmpwi", "cmplwi", "cmpd", "cmpld", "cmpdi", "cmpldi",
    # CR operations
    "crand", "cror", "crxor", "crnand", "crnor", "mcrf",
    # SPR operations
    "mfcr", "mtcrf", "mfspr", "mtspr",
    # XER operations (separate instructions for pipeline support)
    "mfspr_xer", "mtspr_xer",
]


def generate_verilog(merged_graph, module_name, output_dir):
    """Generate Verilog output."""
    from pathlib import Path

    if _engine == 'rust':
        import isacomp_core
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        generator = isacomp_core.VerilogGenerator(merged_graph, module_name)
        verilog_code = generator.generate()

        rtl_file = output_path / f"{module_name}.v"
        rtl_file.write_text(verilog_code)
        files = {'rtl': rtl_file}

        print(f"  Generated RTL: {rtl_file} ({len(verilog_code)} bytes, {verilog_code.count(chr(10))} lines)")
        return files

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
    from backends.vhdl.test_generator import generate_vhdl_test_runner_tb, generate_vhdl_test_script
    from pathlib import Path

    testbench_config = VHDLTestbenchConfig(
        entity_name=entity_name,
        timeout_cycles=10000,
        imem_size=16384,
        dmem_size=16384
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
        arch="OpenPOWER",
        tests=OPENPOWER_TESTS,
        test_base_path="../../isa/openpower/power-tests/isa/power-isacomp-",
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
        arch='openpower'
    )

    # Generate testbench files with instructions list for test runner
    output_path = Path(output_dir)
    files = generate_pyrtl_testbench_files(
        pyrtl_block,
        module_name=module_name,
        output_dir=output_path,
        config=config,
        instructions=INSTRUCTIONS,
        arch='openpower'
    )

    # Also output the PyRTL block as Verilog for debugging and synthesis compatibility
    verilog_file = output_path / f"{module_name}.v"
    with open(verilog_file, 'w') as f:
        pyrtl.output_to_verilog(f, block=pyrtl_block)
    files['verilog'] = verilog_file

    print(f"  PyRTL block contains:")
    print(f"    {len(list(pyrtl_block.logic))} logic operations")
    print(f"    {len(list(pyrtl_block.wirevector_set))} wires")
    print(f"    {len(pyrtl_block.memblock_by_name)} memories")

    return files


def generate_circt(merged_graph, module_name, output_dir):
    """Generate CIRCT MLIR output and convert to SystemVerilog."""
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

    # Convert to SystemVerilog using firtool
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
                    'openpower',
                    INSTRUCTIONS
                )
                files.update(tb_files)
                print(f"  Generated testbench: {tb_files.get('testbench')}")
                print(f"  Generated test runner: {tb_files.get('test_runner')}")
            else:
                print(f"  firtool failed: {result.stderr[:200]}")
        except subprocess.TimeoutExpired:
            print("  firtool timed out")
        except Exception as e:
            print(f"  firtool error: {e}")

    return files


def main():
    parser = argparse.ArgumentParser(
        description='Generate OpenPOWER Scalar Fixed-point Subset (SFS) processor from ISA definitions'
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
        help='Output directory (default: <backend>/openpower_sfs)'
    )
    parser.add_argument(
        '--engine',
        choices=['python', 'rust'],
        default='python',
        help='Computation engine (default: python)'
    )
    args = parser.parse_args()

    _init_engine(args.engine)

    module_name = 'openpower_sfs'
    if args.output_dir:
        output_dir = args.output_dir
    elif args.backend == 'circt':
        output_dir = 'examples/verilog/circt_openpower'
    elif args.backend == 'vhdl':
        output_dir = 'examples/vhdl/openpower_sfs'
    elif args.backend == 'pyrtl':
        output_dir = 'examples/pyrtl/openpower_sfs'
    else:
        output_dir = 'examples/verilog/openpower_sfs'

    print("=" * 70)
    print(f"OPENPOWER SFS PROCESSOR GENERATOR ({args.backend.upper()} backend)")
    print("=" * 70)
    print(f"\nGenerating OpenPOWER SFS processor with {len(INSTRUCTIONS)} instructions...")
    print(f"\nInstruction breakdown:")
    print(f"  Fixed-point Arithmetic:  13 instructions")
    print(f"  Fixed-point Logical:     17 instructions")
    print(f"  Shift/Rotate:            8 instructions")
    print(f"  Load/Store:              17 instructions")
    print(f"  Branch:                  10 instructions")
    print(f"  Compare:                 8 instructions")
    print(f"  CR/SPR Operations:       10 instructions")
    print(f"  Total:                   {len(INSTRUCTIONS)} instructions")
    print(f"\nInstructions: {', '.join(INSTRUCTIONS)}")

    print("\n" + "=" * 70)
    print("PARSING AND MERGING ISA FILES")
    print("=" * 70)
    isa_files = {instr: f"isa/openpower/{instr}.isa" for instr in INSTRUCTIONS}

    print(f"\nMerging {len(INSTRUCTIONS)} ISA specifications...")
    try:
        merged_graph = merge_instructions(isa_files)
        print(f"✓ Merged graph has {len(merged_graph.nodes)} nodes and {len(merged_graph.edges)} edges")
    except Exception as e:
        print(f"✗ Error merging instructions: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Apply port width setting for 64-bit word-addressed unified memory
    # This creates byte selection mux nodes for sub-word accesses
    print("\nApplying memory port width transformation for umem...")
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
            target_width=64,  # 64-bit word-addressed memory for OpenPOWER
            direction='forward'
            # Note: Using little-endian (default) because tests are compiled with powerpc64le toolchain
        )
        result = transform.apply_transformation(spec)
        if result.get('transformed'):
            print(f"  Transformed: added {len(result.get('nodes_added', []))} byte mux nodes")
        else:
            print(f"  Skipped: {result.get('reason', 'unknown')}")

        # Rust engine returns the graph in the result since it can't mutate in place
        if 'graph' in result:
            merged_graph = result['graph']

    print("\n" + "=" * 70)
    print(f"GENERATING {args.backend.upper()}")
    print("=" * 70)
    print(f"\nOutput directory: {output_dir}/")

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

    except Exception as e:
        print(f"  Error generating {args.backend.upper()}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print(f"\n✓ Successfully generated OpenPOWER SFS processor with {len(INSTRUCTIONS)} instructions!")
    print(f"  Backend: {args.backend.upper()}")
    print("\nKey features:")
    print("  - 64-bit register file (r0-r31)")
    print("  - 64-bit program counter")
    print("  - 32-bit Condition Register (CR)")
    print("  - Link Register (LR) and Count Register (CTR)")
    print("  - Full fixed-point arithmetic, logical, shift operations")
    print("  - Byte, halfword, word, and doubleword memory access")
    print("  - Conditional and unconditional branching")
    print("\nNote: This is a non-pipelined (single-cycle) implementation.")


if __name__ == "__main__":
    main()
