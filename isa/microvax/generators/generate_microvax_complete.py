#!/usr/bin/env python3
"""
Generate complete MicroVAX processor from ISA definitions.

This includes:
- Arithmetic: ADDL2/3, SUBL2/3, MULL2/3, INCL, DECL, MNEGL
- Logical: ANDL2/3, BISL2/3, BICL2/3, XORL2/3, MCOML
- Shifts: ASHL, ASHLI, SHRLI, SHRAI, ROTL
- Data movement: MOVL, MOVLI, CLRL, TSTL, CMPL
- Load/Store: LDL, STL
- Branches: BRB, BEQL, BNEQ, BLSS, BGEQ, BGTR, BLEQ, BLSSU, BGEQU
- Subroutine: JSB, RSB
- Control: NOP
"""
import sys
import os
import argparse

# Add parent directories to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from core.graph_merger import merge_instructions
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec

# Complete MicroVAX instruction set (139 instructions)
INSTRUCTIONS = [
    # Byte arithmetic (6)
    'addb2', 'addb3', 'subb2', 'subb3', 'incb', 'decb',

    # Word arithmetic (6)
    'addw2', 'addw3', 'subw2', 'subw3', 'incw', 'decw',

    # Longword arithmetic (13)
    'addl2', 'addl3', 'addli',
    'subl2', 'subl3', 'subli',
    'mull2', 'mull3',
    'divl2', 'divl3',
    'incl', 'decl', 'mnegl',

    # Logical (9)
    'andl2', 'andl3',
    'bisl2', 'bisl3',
    'bicl2', 'bicl3',
    'xorl2', 'xorl3',
    'mcoml',

    # Shifts (5)
    'ashl', 'ashli',
    'shrli', 'shrai',
    'rotl',

    # Data movement - byte/word (8)
    'movb', 'movw',
    'clrb', 'clrw',
    'tstb', 'tstw',
    'mnegb', 'mnegw',

    # Data movement - longword (5)
    'movl', 'movli',
    'clrl', 'tstl', 'cmpl',

    # Comparison - byte/word (2)
    'cmpb', 'cmpw',

    # Zero/sign extend (7)
    'movzbl', 'movzwl', 'movzbw',
    'cvtbl', 'cvtbw', 'cvtlb', 'cvtwl',

    # Load/Store (2)
    'ldl', 'stl',

    # Stack operations (2)
    'pushl', 'popl',

    # Branches - basic (3)
    'brb', 'brw', 'jmp',

    # Branches - signed comparison (6)
    'beql', 'bneq',
    'blss', 'bgeq', 'bgtr', 'bleq',

    # Branches - unsigned comparison (4)
    'blssu', 'bgequ', 'bgtru', 'blequ',

    # Branches - condition code (2)
    'bvs', 'bvc',

    # Branches - bit test (2)
    'bbs', 'bbc',

    # Branches - bit test and modify (4)
    'bbss', 'bbcs', 'bbsc', 'bbcc',

    # Loop control - SOB/AOB (4)
    'sobgtr', 'sobgeq',
    'aobleq', 'aoblss',

    # Loop control - ACB (3)
    'acbb', 'acbw', 'acbl',

    # Subroutine/procedure (4)
    'jsb', 'rsb',
    'calls', 'ret',

    # Move address (3)
    'movab', 'movaw', 'moval',

    # Push address (3)
    'pushab', 'pushaw', 'pushal',

    # Bit field (5)
    'extv', 'extzv', 'insv',
    'ffs', 'ffc',

    # Extended arithmetic (2)
    'emul', 'ediv',

    # Arithmetic with carry (2)
    'adwc', 'sbwc',

    # Case instructions (3)
    'caseb', 'casew', 'casel',

    # Processor status (3)
    'movpsl', 'bispsw', 'bicpsw',

    # F_floating arithmetic (8)
    'addf2', 'addf3',
    'subf2', 'subf3',
    'mulf2', 'mulf3',
    'divf2', 'divf3',

    # F_floating data movement (5)
    'movf', 'clrf', 'tstf', 'cmpf', 'mnegf',

    # F_floating conversion (2)
    'cvtlf', 'cvtfl',

    # Privileged/misc (5)
    'rei', 'bpt',
    'index', 'nop', 'halt', 'illegal',
]


def apply_memory_transform(merged_graph):
    """Apply port width setting for word-addressed unified memory."""
    umem_node = merged_graph.nodes.get('umem')
    if umem_node:
        access_widths = umem_node.data.get('access_widths', [32])
        max_width = max(access_widths) if access_widths else 32
        print(f"  umem access widths: {access_widths}, max: {max_width}")

        # Apply set_port_width transformation
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


def generate_verilog(merged_graph, module_name, output_dir):
    """Generate Verilog output."""
    from backends.verilog import VerilogGenerator, generate_verilog_with_testbench
    from pathlib import Path

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Generate RTL with testbench
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


def main():
    parser = argparse.ArgumentParser(
        description='Generate complete MicroVAX processor from ISA definitions'
    )
    parser.add_argument(
        '--output-dir', '-o',
        default='examples/verilog/microvax_complete',
        help='Output directory (default: examples/verilog/microvax_complete)'
    )
    args = parser.parse_args()

    module_name = 'microvax_complete'
    output_dir = args.output_dir

    print("=" * 70)
    print("MicroVAX Processor Generator")
    print("=" * 70)
    print(f"\nGenerating MicroVAX processor with {len(INSTRUCTIONS)} instructions...")
    print(f"Instructions: {', '.join(INSTRUCTIONS)}")

    # Step 1: Parse and merge ISA files
    print("\n" + "=" * 70)
    print("Step 1: Parsing and merging ISA files...")
    print("=" * 70)
    isa_files = {instr: f"isa/microvax/{instr}.isa" for instr in INSTRUCTIONS}

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

    # Step 3: Generate RTL
    print("\n" + "=" * 70)
    print("Step 3: Generating Verilog RTL and testbench...")
    print("=" * 70)
    print(f"  Output directory: {output_dir}")

    try:
        files = generate_verilog(merged_graph, module_name, output_dir)
        print(f"\n  Generated files:")
        for key, path in files.items():
            if hasattr(path, 'stat'):
                file_size = path.stat().st_size if path.exists() else 0
                print(f"    {key.upper()}: {path} ({file_size:,} bytes)")
            else:
                print(f"    {key.upper()}: {path}")

    except Exception as e:
        print(f"  Error generating Verilog: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"  Successfully generated complete MicroVAX processor")
    print(f"  {len(INSTRUCTIONS)} instructions implemented")
    print(f"  {len(merged_graph.nodes)} nodes in merged graph")
    print(f"  {len(merged_graph.edges)} edges in merged graph")
    print(f"  Output: {output_dir}/")

    print("\n" + "=" * 70)
    print("Done!")
    print("=" * 70)


if __name__ == "__main__":
    main()
