#!/usr/bin/env python3
"""Generate RV32IM processor from SAIL-extracted instruction patterns."""

import sys
import os
import argparse

# Add isacomp root to path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, REPO_ROOT)

from frontends.sail.ocaml_sail_extractor.sail_loader import SAILInstructionLoader
from core.graph_merger import ResourceGraphMerger, InstructionDecodeInfo
from core.timing_utils import reinfer_timing
from backends.verilog import VerilogGenerator

# RV32I patterns (17 patterns, 37 instructions)
RV32I_PATTERNS = [
    'RTYPE',     # add, sub, and, or, xor, slt, sltu, sll, srl, sra
    'ITYPE',     # addi, andi, ori, xori, slti, sltiu
    'SHIFTIOP',  # slli, srli, srai
    'BTYPE',     # beq, bne, blt, bltu, bge, bgeu
    'JAL',       # jal
    'JALR',      # jalr
    'LUI',       # lui  (split from UTYPE by extractor)
    'AUIPC',     # auipc (split from UTYPE by extractor)
    # Per-width load variants (split from LOAD by extractor)
    'LOAD_BYTE',           # lb
    'LOAD_BYTE_UNSIGNED',  # lbu
    'LOAD_HALF',           # lh
    'LOAD_HALF_UNSIGNED',  # lhu
    'LOAD_WORD',           # lw
    # Per-width store variants (split from STORE by extractor)
    'STORE_BYTE',  # sb
    'STORE_HALF',  # sh
    'STORE_WORD',  # sw
    'FENCE',       # fence (NOP for in-order)
]

# RV32M patterns (8 patterns, 8 instructions - split per variant by extractor)
RV32M_PATTERNS = [
    'MUL',     # mul (lower 32 bits of product)
    'MULH',    # mulh (upper 32 bits, signed*signed)
    'MULHSU',  # mulhsu (upper 32 bits, signed*unsigned)
    'MULHU',   # mulhu (upper 32 bits, unsigned*unsigned)
    'DIV',     # div (signed division)
    'DIVU',    # divu (unsigned division)
    'REM',     # rem (signed remainder)
    'REMU',    # remu (unsigned remainder)
]

SAIL_PATTERNS = RV32I_PATTERNS + RV32M_PATTERNS


def load_and_merge(cache_path):
    """Load SAIL patterns and merge into a single graph."""
    loader = SAILInstructionLoader(require_extractor=False)
    instruction_graphs = {}

    for pattern in SAIL_PATTERNS:
        print(f"Loading {pattern}...")
        graph = loader.load_instruction_pattern(pattern, cache_path=cache_path)
        instruction_graphs[pattern] = graph
        print(f"  {len(graph.nodes)} nodes, {len(graph.edges)} edges, "
              f"{len(graph.assume_expressions)} decode constraints")

    print(f"\nMerging {len(instruction_graphs)} instruction patterns...")
    print(f"  RV32I: {len(RV32I_PATTERNS)} patterns")
    print(f"  RV32M: {len(RV32M_PATTERNS)} patterns")
    merger = ResourceGraphMerger()

    for name, graph in instruction_graphs.items():
        reinfer_timing(graph)
        decode_info = InstructionDecodeInfo(name)
        for assume_expr in getattr(graph, 'assume_expressions', []):
            if assume_expr.get('type') == 'binary_op' and assume_expr.get('operator') in ('==', '!='):
                left_str = ResourceGraphMerger._assume_expr_to_string(assume_expr.get('left', {}))
                right_str = ResourceGraphMerger._assume_expr_to_string(assume_expr.get('right', {}))
                decode_info.add_assume_condition(left_str, assume_expr['operator'], right_str)

        # RTYPE and M-extension (MUL/DIV/REM) share opcode 0110011.
        # The extractor computes RTYPE's common decode constraints across all
        # variants, losing the per-variant funct7 specificity.  Add mutual
        # exclusion so RTYPE doesn't fire on M-extension encodings.
        if name == 'RTYPE':
            decode_info.add_assume_condition('instr[31:25]', '!=', "7'b0000001")

        merger.graphs[name] = graph
        merger.decode_info[name] = decode_info
        merger.instruction_nodes[name] = 'instr'
        print(f"  Added {name}: {decode_info}")

    merged_graph = merger.merge_graphs(pc_name='pc_rd')
    print(f"\nMerged graph: {len(merged_graph.nodes)} nodes, {len(merged_graph.edges)} edges")
    return merged_graph


def main():
    parser = argparse.ArgumentParser(description='Generate RV32IM processor from SAIL')
    parser.add_argument('--cache', default=os.path.join(REPO_ROOT, 'frontends/sail/riscv_instructions.json'),
                        help='Path to SAIL extractor JSON cache')
    parser.add_argument('-o', '--output-dir', default='.',
                        help='Output directory')
    args = parser.parse_args()

    merged_graph = load_and_merge(args.cache)

    print("\nGenerating Verilog...")
    generator = VerilogGenerator(merged_graph, 'processor')
    verilog_code = generator.generate()

    output_file = os.path.join(args.output_dir, 'sail_rv32im.v')
    with open(output_file, 'w') as f:
        f.write(verilog_code)
    print(f"Written to {output_file}")
    print(f"  {len(verilog_code.splitlines())} lines of Verilog")

    return output_file


if __name__ == '__main__':
    main()
