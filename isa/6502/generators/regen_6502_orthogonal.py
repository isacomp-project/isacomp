#!/usr/bin/env python3
"""Regenerate 6502 Verilog from orthogonal ISA specification.

This generates the standard NMOS 6502 using the orthogon-based ISA spec
in isa/6502/orthogonal/. The orthogonal spec factors out addressing modes
into shared orthogon definitions, reducing file count and duplication.

Usage:
    python regen_6502_orthogonal.py [--compare]

Options:
    --compare   Also generate from the existing spec and compare sizes
"""

import sys
import argparse
import time
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from core.graph_merger import merge_instructions
from core.orthogon_parser import is_orthogon_file
from backends.verilog import generate_verilog


def collect_instruction_files(isa_dir: Path):
    """Collect instruction files, excluding orthogon definitions."""
    isa_files = sorted(isa_dir.glob("*.isa"))
    instruction_files = {}
    orthogon_files = []

    for f in isa_files:
        if is_orthogon_file(str(f)):
            orthogon_files.append(f)
        else:
            instruction_files[f.stem] = str(f)

    return instruction_files, orthogon_files


def generate_from_spec(isa_dir: Path, label: str, defines: dict,
                       module_name: str, output_file: Path):
    """Generate Verilog from an ISA spec directory and return metrics."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")

    instruction_files, orthogon_files = collect_instruction_files(isa_dir)
    print(f"Instruction files: {len(instruction_files)}")
    if orthogon_files:
        print(f"Orthogon files: {len(orthogon_files)}")
        for f in orthogon_files:
            print(f"  - {f.name}")

    # Merge
    print(f"\nMerging instruction graphs...")
    t0 = time.time()
    merged_graph = merge_instructions(instruction_files, defines=defines)
    merge_time = time.time() - t0

    # Set memory port width
    mainmem_node = merged_graph.nodes.get('mainmem')
    if mainmem_node:
        mainmem_node.data['port_width'] = 8
        mainmem_node.data['element_width'] = 8

    # Count graph metrics
    num_nodes = len(merged_graph.nodes)
    num_edges = len(merged_graph.edges)

    print(f"Merge time: {merge_time:.2f}s")
    print(f"Graph: {num_nodes} nodes, {num_edges} edges")

    # Generate Verilog
    print(f"\nGenerating Verilog...")
    t0 = time.time()
    verilog_code = generate_verilog(merged_graph, module_name=module_name)
    gen_time = time.time() - t0

    verilog_lines = verilog_code.count('\n')
    verilog_bytes = len(verilog_code.encode('utf-8'))

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(verilog_code)

    print(f"Generation time: {gen_time:.2f}s")
    print(f"Verilog: {verilog_lines} lines, {verilog_bytes} bytes")
    print(f"Output: {output_file}")

    return {
        'num_isa_files': len(instruction_files),
        'num_orthogon_files': len(orthogon_files),
        'num_nodes': num_nodes,
        'num_edges': num_edges,
        'merge_time': merge_time,
        'gen_time': gen_time,
        'verilog_lines': verilog_lines,
        'verilog_bytes': verilog_bytes,
    }


def print_comparison(existing: dict, orthogonal: dict):
    """Print side-by-side comparison of the two specs."""
    print(f"\n{'='*60}")
    print(f"  COMPARISON: Existing vs. Orthogonal")
    print(f"{'='*60}")
    print(f"{'Metric':<25} {'Existing':>12} {'Orthogonal':>12} {'Change':>12}")
    print(f"{'-'*25} {'-'*12} {'-'*12} {'-'*12}")

    metrics = [
        ('ISA files', 'num_isa_files'),
        ('Orthogon files', 'num_orthogon_files'),
        ('Graph nodes', 'num_nodes'),
        ('Graph edges', 'num_edges'),
        ('Merge time (s)', 'merge_time'),
        ('Verilog lines', 'verilog_lines'),
        ('Verilog bytes', 'verilog_bytes'),
    ]

    for label, key in metrics:
        e = existing[key]
        o = orthogonal[key]
        if isinstance(e, float):
            e_str = f"{e:.2f}"
            o_str = f"{o:.2f}"
        else:
            e_str = str(e)
            o_str = str(o)

        if e != 0:
            pct = ((o - e) / e) * 100
            change = f"{pct:+.1f}%"
        else:
            change = "N/A"

        print(f"{label:<25} {e_str:>12} {o_str:>12} {change:>12}")


def main():
    parser = argparse.ArgumentParser(
        description='Generate 6502 Verilog from orthogonal ISA spec')
    parser.add_argument('--compare', action='store_true',
                        help='Also generate from existing spec and compare')
    args = parser.parse_args()

    defines = {'CPU_6502_BCD': '1'}

    # Generate from orthogonal spec
    orth_dir = project_root / "isa" / "6502" / "orthogonal"
    orth_out = project_root / "examples" / "verilog" / "6502_orthogonal_test" / "6502_orthogonal_test.v"
    orth_metrics = generate_from_spec(
        orth_dir, "Orthogonal Spec", defines,
        "cpu_6502_orthogonal_test", orth_out
    )

    if args.compare:
        # Generate from existing spec
        existing_dir = project_root / "isa" / "6502"
        existing_out = project_root / "examples" / "verilog" / "6502_test" / "6502_test.v"
        existing_metrics = generate_from_spec(
            existing_dir, "Existing Spec", defines,
            "cpu_6502_test", existing_out
        )

        print_comparison(existing_metrics, orth_metrics)


if __name__ == '__main__':
    main()
