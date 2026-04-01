#!/usr/bin/env python3
"""
Generate complete PDP-11/70 processor from ISA definitions.
This includes the Extended Instruction Set (EIS) for MUL, DIV, ASH, ASHC.

The PDP-11/70 was the highest performance PDP-11 variant with:
- Full 16-bit word size, byte-addressable memory
- 8 general purpose registers (R0-R7, R7=PC, R6=SP)
- EIS (Extended Instruction Set) as standard
- 8 addressing modes
- Processor Status Word with N, Z, V, C condition codes

Supports Verilog backend via --backend argument.
"""
import sys
import os
import argparse

# Add parent directories to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core.graph_merger import merge_instructions
from backends.verilog import generate_verilog_with_testbench, VerilogGenerator

# PDP-11/70 complete instruction set
# Auto-discover all .isa files from the pdp11 ISA directory
def _discover_instructions():
    """Discover all instruction .isa files in the pdp11 ISA directory."""
    import glob as g
    isa_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    isa_files = g.glob(os.path.join(isa_dir, '*.isa'))
    return sorted(os.path.splitext(os.path.basename(f))[0] for f in isa_files)

INSTRUCTIONS = _discover_instructions()


def generate_verilog(merged_graph, module_name, output_dir):
    """Generate Verilog output."""
    from pathlib import Path

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Generate RTL
    generator = VerilogGenerator(merged_graph, module_name)
    verilog_code = generator.generate()

    rtl_file = output_path / f"{module_name}.v"
    rtl_file.write_text(verilog_code)

    files = {'rtl': rtl_file}

    # Generate testbench
    testbench_config = {
        'timeout_cycles': 10000
    }
    tb_files = generate_verilog_with_testbench(
        merged_graph,
        module_name=module_name,
        output_dir=output_dir,
        testbench_config=testbench_config
    )
    files.update(tb_files)

    # Generate FuseSoC core file
    core_content = f"""CAPI=2:
name: ::pdp11_complete:1.0.0
description: PDP-11/70 complete processor

filesets:
  rtl:
    files:
      - {module_name}.v
    file_type: verilogSource

  tb:
    files:
      - {module_name}_tb.sv
    file_type: systemVerilogSource

targets:
  default:
    filesets:
      - rtl

  sim:
    default_tool: icarus
    filesets:
      - rtl
      - tb
    toplevel: {module_name}_tb
    tools:
      icarus:
        iverilog_options:
          - -g2012
"""
    core_file = output_path / f"{module_name}.core"
    core_file.write_text(core_content)
    files['core'] = core_file

    return files


def main():
    parser = argparse.ArgumentParser(description='Generate PDP-11/70 processor')
    parser.add_argument('--output-dir', '-o', default='examples/verilog/pdp11_complete',
                        help='Output directory for generated files')
    parser.add_argument('--backend', '-b', default='verilog',
                        choices=['verilog'],
                        help='Backend to use for code generation')
    args = parser.parse_args()

    # Build dict of ISA files (instruction name -> file path)
    isa_dir = os.path.join(os.path.dirname(__file__), '..')
    isa_files = {name: os.path.join(isa_dir, f"{name}.isa") for name in INSTRUCTIONS}

    # Merge all instructions
    print(f"Merging {len(INSTRUCTIONS)} instructions...")
    merged_graph = merge_instructions(isa_files)

    # Generate output
    module_name = 'pdp11_complete'
    files = generate_verilog(merged_graph, module_name, args.output_dir)

    print("\n" + "=" * 70)
    print("GENERATION COMPLETE")
    print("=" * 70)
    print(f"\nGenerated files:")
    for file_type, file_path in files.items():
        print(f"  {file_type.upper()}: {file_path} ({file_path.stat().st_size:,} bytes)")

    print(f"\n  Successfully generated PDP-11/70 processor with {len(INSTRUCTIONS)} instructions!")
    print(f"  Backend: {args.backend.upper()}")
    print("\nNote: This is a non-pipelined (single-cycle) implementation.")


if __name__ == '__main__':
    main()
