#!/usr/bin/env python3
"""Generate RV32IF processor from SAIL-extracted instruction patterns."""

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

# RV32I patterns (16 patterns, 37 instructions)
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

# RV32F patterns (split by extractor into per-operation instruction types)
RV32F_PATTERNS = [
    # F_BIN_RM_TYPE_S split by funct7 into per-operation types:
    'F_BIN_RM_TYPE_S_FADD',    # fadd.s
    'F_BIN_RM_TYPE_S_FSUB',    # fsub.s
    'F_BIN_RM_TYPE_S_FMUL',    # fmul.s
    'F_BIN_RM_TYPE_S_FDIV',    # fdiv.s
    # F_BIN_TYPE_F_S split by funct7+funct3:
    'F_BIN_TYPE_F_S_SGNJ',    # fsgnj.s
    'F_BIN_TYPE_F_S_SGNJN',   # fsgnjn.s
    'F_BIN_TYPE_F_S_SGNJX',   # fsgnjx.s
    'F_BIN_TYPE_F_S_MIN',     # fmin.s
    'F_BIN_TYPE_F_S_MAX',     # fmax.s
    # F_BIN_TYPE_X_S split by funct3:
    'F_BIN_TYPE_X_S_EQ',      # feq.s
    'F_BIN_TYPE_X_S_LT',      # flt.s
    'F_BIN_TYPE_X_S_LE',      # fle.s
    'F_UN_TYPE_F_S',           # fmv.w.x
    # F_UN_TYPE_X_S split by funct3:
    'F_UN_TYPE_X_S_FMV_X_W',  # fmv.x.w
    'F_UN_TYPE_X_S_FCLASS',   # fclass.s
    'F_UN_RM_FF_TYPE_S',      # fsqrt.s
    # F_UN_RM_FX_TYPE_S split by rs2 field:
    'F_UN_RM_FX_TYPE_S_W',    # fcvt.w.s
    'F_UN_RM_FX_TYPE_S_WU',   # fcvt.wu.s
    # F_UN_RM_XF_TYPE_S split by rs2 field:
    'F_UN_RM_XF_TYPE_S_W',    # fcvt.s.w
    'F_UN_RM_XF_TYPE_S_WU',   # fcvt.s.wu
    'F_MADD_TYPE_S',           # fmadd.s, fmsub.s, fnmadd.s, fnmsub.s (internal mux)
    # Per-width FP load/store (split from LOAD_FP/STORE_FP by extractor)
    'LOAD_FP_WORD',            # flw
    'STORE_FP_WORD',           # fsw
]

# System patterns (needed for F extension tests to enable FPU via mstatus)
# CSRReg/CSRImm split into per-operation types by extractor, named to produce
# csrrw_enable, csrrs_enable, etc. (matching verilog generator's fflags detection)
SYSTEM_PATTERNS = [
    'csrrw',
    'csrrs',
    'csrrc',
    'csrrwi',
    'csrrsi',
    'csrrci',
]

SAIL_PATTERNS = RV32I_PATTERNS + RV32F_PATTERNS + SYSTEM_PATTERNS


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
    print(f"  RV32F: {len(RV32F_PATTERNS)} patterns")
    print(f"  System: {len(SYSTEM_PATTERNS)} patterns")
    merger = ResourceGraphMerger()

    for name, graph in instruction_graphs.items():
        reinfer_timing(graph)
        decode_info = InstructionDecodeInfo(name)
        for assume_expr in getattr(graph, 'assume_expressions', []):
            if assume_expr.get('type') == 'binary_op' and assume_expr.get('operator') in ('==', '!='):
                left_str = ResourceGraphMerger._assume_expr_to_string(assume_expr.get('left', {}))
                right_str = ResourceGraphMerger._assume_expr_to_string(assume_expr.get('right', {}))
                decode_info.add_assume_condition(left_str, assume_expr['operator'], right_str)

        merger.graphs[name] = graph
        merger.decode_info[name] = decode_info
        merger.instruction_nodes[name] = 'instr'
        print(f"  Added {name}: {decode_info}")

    merged_graph = merger.merge_graphs(pc_name='pc_rd')
    print(f"\nMerged graph: {len(merged_graph.nodes)} nodes, {len(merged_graph.edges)} edges")

    # Now that FDIV is split into its own instruction type, mark fp_div
    # and fp_sqrt as multi-cycle operations (matching reference generator)
    for node_id, node in merged_graph.nodes.items():
        op = node.data.get('operator', '')
        if op in ('fp_div', 'fp_sqrt') and node.data.get('type') == 'fp_operation':
            node.data['multi_cycle'] = True
            node.data['latency_cycles'] = 10
            print(f"  Marked {node_id} ({op}) as multi_cycle (latency=10)")

    return merged_graph


def main():
    parser = argparse.ArgumentParser(description='Generate RV32IF processor from SAIL')
    parser.add_argument('--cache', default=os.path.join(REPO_ROOT, 'frontends/sail/riscv_instructions.json'),
                        help='Path to SAIL extractor JSON cache')
    parser.add_argument('-o', '--output-dir', default='.',
                        help='Output directory')
    args = parser.parse_args()

    merged_graph = load_and_merge(args.cache)

    print("\nGenerating Verilog...")
    generator = VerilogGenerator(merged_graph, 'processor')
    verilog_code = generator.generate()

    output_file = os.path.join(args.output_dir, 'sail_rv32if.v')
    with open(output_file, 'w') as f:
        f.write(verilog_code)
    print(f"Written to {output_file}")
    print(f"  {len(verilog_code.splitlines())} lines of Verilog")

    return output_file


if __name__ == '__main__':
    main()
