#!/usr/bin/env python3
"""
Create a dual-issue superscalar RISC-V 32-bit processor.

This script creates a dual-issue in-order pipeline where:
- P0 (primary): Full RV32I instruction set
- P1 (secondary): ALU-only subset (R-type and I-type ALU instructions)

Both pipelines share:
- Register file (4 read ports, 2 write ports)
- Instruction memory
- Data memory
- PC (single, advances by 0/4/8)

Usage:
    python create_rv32i_dual_issue.py [--stages N]

Arguments:
    --stages N    Number of pipeline stages (2, 3, 4, or 5). Default: 2
"""

import os
import sys
import argparse

# Add project root to path for imports
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from core.resource_graph import ResourceGraph, Node, Edge
from core.graph_merger import ResourceGraphMerger
from opt.pipeline.pipelining_optimization import PipelineTransform
from opt.pipeline.hazard_resolution import HazardAnalyzer, HazardResolver, HazardResolutionStrategy
from backends.verilog import VerilogGenerator
from core.pipeline_config import get_pipeline_config, PipelineConfig
from opt.pipeline.dual_issue_pipeline import DualIssuePipelineMerger, finalize_pc_advancement, add_dual_issue_control_hazard_flush
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec

# P0 (full RV32I) instruction list
P0_INSTRUCTIONS = [
    # R-type
    'add', 'sub', 'and', 'or', 'xor', 'sll', 'srl', 'sra', 'slt', 'sltu',
    # I-type ALU
    'addi', 'andi', 'ori', 'xori', 'slli', 'srli', 'srai', 'slti', 'sltiu',
    # Load
    'lb', 'lh', 'lw', 'lbu', 'lhu',
    # Store
    'sb', 'sh', 'sw',
    # Branch
    'beq', 'bne', 'blt', 'bge', 'bltu', 'bgeu',
    # Jump
    'jal', 'jalr',
    # Upper immediate
    'lui', 'auipc',
]

# P1 (ALU-only subset) instruction list
P1_INSTRUCTIONS = [
    # R-type ALU
    'add', 'sub', 'and', 'or', 'xor', 'sll', 'srl', 'sra', 'slt', 'sltu',
    # I-type ALU
    'addi', 'andi', 'ori', 'xori', 'slli', 'srli', 'srai', 'slti', 'sltiu',
    # Upper immediate (these are also safe for P1)
    'lui', 'auipc',
]


def get_instruction_files(instruction_list):
    """Get ISA files for instructions."""
    rv32i_dir = os.path.join(_project_root, "riscv32")
    files = {}
    for instr in instruction_list:
        isa_file = os.path.join(rv32i_dir, f"{instr}.isa")
        if os.path.exists(isa_file):
            files[instr] = isa_file
    return files


def build_merged_graph(instruction_list, name):
    """Build merged graph for an instruction set."""
    print(f"\nBuilding merged graph for {name}...")

    instructions = get_instruction_files(instruction_list)
    print(f"  Found {len(instructions)} instructions")

    merger = ResourceGraphMerger()
    for instr_name, path in instructions.items():
        merger.add_instruction(instr_name, path)

    merged = merger.merge_graphs()
    merged.infer_uarch_time()

    print(f"  Nodes: {len(merged.nodes)}")
    print(f"  Edges: {len(merged.edges)}")

    return merged


def select_2stage_cuts(graph):
    """Select pipeline cut edges for 2-stage pipeline."""
    cuts = {'ExecuteMemoryWriteback': []}

    def find_edge(src_id, tgt_id):
        for edge_id, edge in graph.edges.items():
            if edge.source.id == src_id and edge.target.id == tgt_id:
                return edge_id
        return None

    def find_edges_from(src_id):
        edges = []
        for edge_id, edge in graph.edges.items():
            if edge.source.id == src_id:
                edges.append((edge_id, edge.target.id))
        return edges

    # Cut after Fetch: instruction fetch -> decode/execute
    print("\n2-STAGE PIPELINE CUTS")
    print("-" * 50)

    # PC to instruction memory
    eid = find_edge('pc_rd', 'imem')
    if eid:
        cuts['ExecuteMemoryWriteback'].append(eid)
        print(f"  pc_rd -> imem")

    # Cut ALL edges from instruction - includes both field extractions and comparisons
    # This ensures all consumers of the instruction see the pipelined version
    for eid, tgt in find_edges_from('instr'):
        cuts['ExecuteMemoryWriteback'].append(eid)
        print(f"  instr -> {tgt}")

    return cuts


def select_3stage_cuts(graph):
    """
    Select pipeline cut edges for 3-stage pipeline.

    3-stage pipeline: Fetch -> Decode -> ExecuteMemoryWriteback

    Cut 1 (F/D): Instruction fetch boundary
    Cut 2 (D/XMW): Decode boundary - register reads, immediates, enables
    """
    cuts = {'Decode': [], 'ExecuteMemoryWriteback': []}

    def find_edge(src_id, tgt_id):
        for edge_id, edge in graph.edges.items():
            if edge.source.id == src_id and edge.target.id == tgt_id:
                return edge_id
        return None

    def find_edges_from(src_id):
        edges = []
        for edge_id, edge in graph.edges.items():
            if edge.source.id == src_id:
                edges.append((edge_id, edge.target.id))
        return edges

    def find_edges_to(tgt_id):
        edges = []
        for edge_id, edge in graph.edges.items():
            if edge.target.id == tgt_id:
                edges.append((edge_id, edge.source.id))
        return edges

    def find_edges_to_suffix(src_id, suffix):
        edges = []
        for edge_id, edge in graph.edges.items():
            if edge.source.id == src_id and (edge.target.id == suffix or edge.target.id.endswith('_' + suffix)):
                edges.append((edge_id, edge.target.id))
        return edges

    # ========================================
    # CUT 1: F/D - Fetch / Decode
    # ========================================
    print("\n3-STAGE PIPELINE CUTS")
    print("-" * 50)
    print("\nCUT 1: Fetch -> Decode")
    print("-" * 50)

    # Instruction word from memory
    eid = find_edge('pc_rd', 'imem')
    if eid:
        cuts['Decode'].append(eid)
        print(f"  [F/D] pc_rd -> imem")

    # All edges from instruction word
    for eid, tgt in find_edges_from('instr'):
        cuts['Decode'].append(eid)
        print(f"  [F/D] instr -> {tgt}")

    # PC value alongside instruction (for branch/jump target calculations)
    for eid, tgt in find_edges_from('pc_rd'):
        if '(pc +' in tgt and tgt != '(pc + 4)':
            cuts['Decode'].append(eid)
            print(f"  [F/D] pc_rd -> {tgt} (PC value for instruction)")

    # JAL/JALR return address
    eid = find_edge('(pc + 4)', 'ret_addr')
    if eid:
        cuts['Decode'].append(eid)
        print(f"  [F/D] (pc + 4) -> ret_addr (JAL/JALR return address)")

    # ========================================
    # CUT 2: D/XMW - Decode / ExecuteMemoryWriteback
    # ========================================
    print(f"\nCUT 2: Decode -> ExecuteMemoryWriteback")
    print("-" * 50)

    # Register file read values (r1/r2 may be instruction-prefixed like add_r1, sw_r2)
    for eid, tgt in find_edges_to_suffix('rf[rs1]_rd', 'r1'):
        cuts['ExecuteMemoryWriteback'].append(eid)
        print(f"  [D/XMW] rf[rs1]_rd -> {tgt} (source reg 1 value)")

    for eid, tgt in find_edges_to_suffix('rf[rs2]_rd', 'r2'):
        cuts['ExecuteMemoryWriteback'].append(eid)
        print(f"  [D/XMW] rf[rs2]_rd -> {tgt} (source reg 2 value)")

    # Destination register index
    for eid, tgt in find_edges_from('rd'):
        if tgt != '(rd != 0)':
            cuts['ExecuteMemoryWriteback'].append(eid)
            print(f"  [D/XMW] rd -> {tgt} (dest reg index)")

    # PC for branch/jump calculations
    for eid, tgt in find_edges_from('pc_rd'):
        if '(pc +' in tgt and tgt != '(pc + 4)':
            cuts['ExecuteMemoryWriteback'].append(eid)
            print(f"  [D/XMW] pc_rd -> {tgt} (PC for target calc)")

    # Sign-extended immediates
    immediate_types = ['addi_sign_ext_imm', 'sb_sign_ext_imm', 'beq_sign_ext_imm',
                       'jal_sign_ext_imm', 'sign_ext_imm', 'auipc_imm']
    for imm_type in immediate_types:
        if imm_type in graph.nodes:
            for eid, src in find_edges_to(imm_type):
                cuts['ExecuteMemoryWriteback'].append(eid)
                print(f"  [D/XMW] {src} -> {imm_type}")

    # JAL/JALR return address
    eid = find_edge('(pc + 4)', 'ret_addr')
    if eid:
        cuts['ExecuteMemoryWriteback'].append(eid)
        print(f"  [D/XMW] (pc + 4) -> ret_addr")

    # Instruction enable signals
    for node_id in graph.nodes:
        if node_id.endswith('_enable') and not node_id.startswith('rf_rd_ne_0') and node_id != 'umem_write_enable':
            # Skip byte enables - computed at ExecuteMemoryWriteback from address
            if node_id in ['sh_byte_enable', 'sb_byte_enable']:
                print(f"  [D/XMW] SKIP {node_id} (byte enable computed from address)")
                continue
            for eid, tgt in find_edges_from(node_id):
                if '_rd_enable' in tgt:
                    continue
                if tgt == 'rf_rd_ne_0_enables':
                    print(f"  [D/XMW] SKIP {node_id} -> {tgt} (stays at Decode)")
                    continue
                if tgt == 'umem_write_enable':
                    print(f"  [D/XMW] SKIP {node_id} -> {tgt} (stays at Decode)")
                    continue
                cuts['ExecuteMemoryWriteback'].append(eid)
                print(f"  [D/XMW] {node_id} -> {tgt} (control)")

    # Shamt for shift instructions
    eid = find_edge('instr[24:20]', 'shamt')
    if eid:
        cuts['ExecuteMemoryWriteback'].append(eid)
        print(f"  [D/XMW] instr[24:20] -> shamt")

    # Combined write enable - pipeline from Decode to Execute
    for eid, tgt in find_edges_from('rf_rd_ne_0_guarded_enable'):
        cuts['ExecuteMemoryWriteback'].append(eid)
        print(f"  [D/XMW] rf_rd_ne_0_guarded_enable -> {tgt}")

    # Memory write enable - pipeline from Decode to Execute
    for eid, tgt in find_edges_from('umem_write_enable'):
        cuts['ExecuteMemoryWriteback'].append(eid)
        print(f"  [D/XMW] umem_write_enable -> {tgt}")

    # Summary
    print(f"\n  Decode: {len(cuts['Decode'])} edges")
    print(f"  ExecuteMemoryWriteback: {len(cuts['ExecuteMemoryWriteback'])} edges")

    return cuts


def select_4stage_cuts(graph):
    """
    Select pipeline cut edges for 4-stage pipeline.

    4-stage pipeline: Fetch -> Decode -> Execute -> MemoryWriteback

    Cut 1 (F/D): Instruction fetch boundary
    Cut 2 (D/X): Decode boundary - register reads, immediates, enables
    Cut 3 (X/MW): Execute boundary - ALU results, memory addresses, store data
    """
    cuts = {'Decode': [], 'Execute': [], 'MemoryWriteback': []}

    def find_edge(src_id, tgt_id):
        for edge_id, edge in graph.edges.items():
            if edge.source.id == src_id and edge.target.id == tgt_id:
                return edge_id
        return None

    def find_edges_from(src_id):
        edges = []
        for edge_id, edge in graph.edges.items():
            if edge.source.id == src_id:
                edges.append((edge_id, edge.target.id))
        return edges

    def find_edges_to(tgt_id):
        edges = []
        for edge_id, edge in graph.edges.items():
            if edge.target.id == tgt_id:
                edges.append((edge_id, edge.source.id))
        return edges

    def find_edges_to_suffix(src_id, suffix):
        edges = []
        for edge_id, edge in graph.edges.items():
            if edge.source.id == src_id and (edge.target.id == suffix or edge.target.id.endswith('_' + suffix)):
                edges.append((edge_id, edge.target.id))
        return edges

    def find_edges_from_suffix(suffix, tgt_id):
        edges = []
        for edge_id, edge in graph.edges.items():
            if edge.target.id == tgt_id and (edge.source.id == suffix or edge.source.id.endswith('_' + suffix)):
                edges.append((edge_id, edge.source.id))
        return edges

    # ========================================
    # CUT 1: F/D - Fetch / Decode
    # ========================================
    print("\n4-STAGE PIPELINE CUTS")
    print("-" * 50)
    print("\nCUT 1: Fetch -> Decode")
    print("-" * 50)

    # Instruction word from memory
    eid = find_edge('pc_rd', 'imem')
    if eid:
        cuts['Decode'].append(eid)
        print(f"  [F/D] pc_rd -> imem")

    # All edges from instruction word
    for eid, tgt in find_edges_from('instr'):
        cuts['Decode'].append(eid)
        print(f"  [F/D] instr -> {tgt}")

    # PC value alongside instruction (for branch/jump target calculations)
    for eid, tgt in find_edges_from('pc_rd'):
        if '(pc +' in tgt and tgt != '(pc + 4)':
            cuts['Decode'].append(eid)
            print(f"  [F/D] pc_rd -> {tgt} (PC value for instruction)")

    # JAL/JALR return address
    eid = find_edge('(pc + 4)', 'ret_addr')
    if eid:
        cuts['Decode'].append(eid)
        print(f"  [F/D] (pc + 4) -> ret_addr (JAL/JALR return address)")

    # ========================================
    # CUT 2: D/X - Decode / Execute
    # ========================================
    print(f"\nCUT 2: Decode -> Execute")
    print("-" * 50)

    # Register file read values
    for eid, tgt in find_edges_to_suffix('rf[rs1]_rd', 'r1'):
        cuts['Execute'].append(eid)
        print(f"  [D/X] rf[rs1]_rd -> {tgt} (source reg 1 value)")

    for eid, tgt in find_edges_to_suffix('rf[rs2]_rd', 'r2'):
        cuts['Execute'].append(eid)
        print(f"  [D/X] rf[rs2]_rd -> {tgt} (source reg 2 value)")

    # Destination register index
    for eid, tgt in find_edges_from('rd'):
        if tgt != '(rd != 0)':
            cuts['Execute'].append(eid)
            print(f"  [D/X] rd -> {tgt} (dest reg index)")

    # PC for branch/jump calculations
    for eid, tgt in find_edges_from('pc_rd'):
        if '(pc +' in tgt and tgt != '(pc + 4)':
            cuts['Execute'].append(eid)
            print(f"  [D/X] pc_rd -> {tgt} (PC for target calc)")

    # Sign-extended immediates
    immediate_types = ['addi_sign_ext_imm', 'sb_sign_ext_imm', 'beq_sign_ext_imm',
                       'jal_sign_ext_imm', 'sign_ext_imm', 'auipc_imm']
    for imm_type in immediate_types:
        if imm_type in graph.nodes:
            for eid, src in find_edges_to(imm_type):
                cuts['Execute'].append(eid)
                print(f"  [D/X] {src} -> {imm_type}")

    # JAL/JALR return address
    eid = find_edge('(pc + 4)', 'ret_addr')
    if eid:
        cuts['Execute'].append(eid)
        print(f"  [D/X] (pc + 4) -> ret_addr")

    # Instruction enable signals
    for node_id in graph.nodes:
        if node_id.endswith('_enable') and not node_id.startswith('rf_rd_ne_0') and node_id != 'umem_write_enable':
            # Skip byte enables - computed at MemoryWriteback from address
            if node_id in ['sh_byte_enable', 'sb_byte_enable']:
                print(f"  [D/X] SKIP {node_id} (byte enable computed from address)")
                continue
            # Skip umem_write_enable - computed in MemoryWriteback from store enables
            for eid, tgt in find_edges_from(node_id):
                if '_rd_enable' in tgt:
                    continue
                if tgt == 'rf_rd_ne_0_enables':
                    print(f"  [D/X] SKIP {node_id} -> {tgt} (stays at Decode)")
                    continue
                if tgt == 'umem_write_enable':
                    # Store enables must be pipelined D/X and X/MW for umem_write_enable
                    cuts['Execute'].append(eid)
                    print(f"  [D/X] {node_id} -> {tgt} (pipeline store enable to Execute)")
                    continue
                cuts['Execute'].append(eid)
                print(f"  [D/X] {node_id} -> {tgt} (control)")

    # Shamt for shift instructions
    eid = find_edge('instr[24:20]', 'shamt')
    if eid:
        cuts['Execute'].append(eid)
        print(f"  [D/X] instr[24:20] -> shamt")

    # Combined write enable - pipeline from Decode to Execute
    for eid, tgt in find_edges_from('rf_rd_ne_0_guarded_enable'):
        cuts['Execute'].append(eid)
        print(f"  [D/X] rf_rd_ne_0_guarded_enable -> {tgt} (pipeline combined write enable)")

    # For 4-stage: umem_write_enable is computed in MemoryWriteback from pipelined store enables
    # Do NOT pipeline umem_write_enable from Decode

    # ========================================
    # CUT 3: X/MW - Execute / MemoryWriteback
    # ========================================
    print(f"\nCUT 3: Execute -> MemoryWriteback (Memory+Writeback combined)")
    print("-" * 50)

    # Memory addresses
    for addr_node in ['lb_addr', 'sb_addr']:
        for eid, tgt in find_edges_from(addr_node):
            if 'umem' in tgt:
                cuts['MemoryWriteback'].append(eid)
                print(f"  [X/MW] {addr_node} -> {tgt} (memory address)")

    # Byte offset nodes - dynamically find nodes that handle byte/halfword selection
    for node_id in list(graph.nodes.keys()):
        is_byte_offset = node_id.endswith('_byte_offset')
        is_halfword_select = node_id.endswith('_halfword_select')
        is_word_select = node_id.endswith('_word_select')

        if is_byte_offset or is_halfword_select or is_word_select:
            for eid, tgt in find_edges_from(node_id):
                cuts['MemoryWriteback'].append(eid)
                print(f"  [X/MW] {node_id} -> {tgt} (byte selection offset)")

    # ALU results and return address going to writeback mux
    alu_results = [
        'add_res', 'sub_res', 'and_res', 'or_res', 'xor_res',
        'sll_res', 'srl_res', 'sra_res', 'slt_res', 'sltu_res',
        'addi_res', 'andi_res', 'ori_res', 'xori_res',
        'slli_res', 'srli_res', 'srai_res', 'slti_res', 'sltiu_res',
        'lui_res', 'auipc_res',
        'ret_addr',  # JAL/JALR return address (pc+4) must be pipelined to MW
    ]
    for res in alu_results:
        for eid, tgt in find_edges_from(res):
            if tgt == 'rf_write_data_mux':
                cuts['MemoryWriteback'].append(eid)
                print(f"  [X/MW] {res} -> rf_write_data_mux")

    # Store data (r2 may be instruction-prefixed like sw_r2)
    for eid, src in find_edges_from_suffix('r2', 'umem_write_data_mux'):
        cuts['MemoryWriteback'].append(eid)
        print(f"  [X/MW] {src} -> umem_write_data_mux (store data)")

    # Store enables - cut to umem_write_data_mux and umem_write_enable
    for store_enable in ['sb_enable', 'sh_enable', 'sw_enable']:
        for eid, tgt in find_edges_from(store_enable):
            if tgt == 'umem_write_data_mux':
                cuts['MemoryWriteback'].append(eid)
                print(f"  [X/MW] {store_enable} -> {tgt} (store enable)")
            elif tgt == 'umem_write_enable':
                cuts['MemoryWriteback'].append(eid)
                print(f"  [X/MW] {store_enable} -> {tgt} (store enable to write)")

    # Store byte/halfword data
    for store_data in ['sb_byte_data', 'sh_halfword_data']:
        for eid, tgt in find_edges_from(store_data):
            if tgt == 'umem_write_data_mux' or 'zext' in tgt or 'positioned' in tgt:
                cuts['MemoryWriteback'].append(eid)
                print(f"  [X/MW] {store_data} -> {tgt}")

    # Store address to byte_enable nodes
    for eid, tgt in find_edges_from('sb_addr'):
        if 'byte_enable' in tgt or 'positioned' in tgt or 'shift' in tgt:
            cuts['MemoryWriteback'].append(eid)
            print(f"  [X/MW] sb_addr -> {tgt} (store address to byte enable)")

    # Propagate rd to MemoryWriteback
    for eid, tgt in find_edges_from('rd'):
        if tgt in ['rf[rd]_wr', 'rf_shared_wr']:
            cuts['MemoryWriteback'].append(eid)
            print(f"  [X/MW] rd -> {tgt} (propagate rd to MW)")

    # Propagate enable signals to rf_write_data_mux
    for node_id in graph.nodes:
        if node_id.endswith('_enable') and not node_id.startswith('rf_rd_ne_0') and node_id != 'umem_write_enable':
            for eid, tgt in find_edges_from(node_id):
                if tgt == 'rf_write_data_mux':
                    cuts['MemoryWriteback'].append(eid)
                    print(f"  [X/MW] {node_id} -> {tgt} (propagate control)")

    # Combined write enable - continue pipeline from Execute to MemoryWriteback
    for eid, tgt in find_edges_from('rf_rd_ne_0_guarded_enable'):
        cuts['MemoryWriteback'].append(eid)
        print(f"  [X/MW] rf_rd_ne_0_guarded_enable -> {tgt} (pipeline combined write enable)")

    # For 4-stage: umem_write_enable is computed and used in MemoryWriteback
    # Do NOT cut edges FROM umem_write_enable (no further pipelining needed)

    # Load enables - pipeline to MemoryWriteback for memory stall detection
    for load_enable in ['lb_enable', 'lh_enable', 'lw_enable', 'lbu_enable', 'lhu_enable']:
        for eid, tgt in find_edges_from(load_enable):
            if tgt == 'umem_addr_rd_enable':
                cuts['MemoryWriteback'].append(eid)
                print(f"  [X/MW] {load_enable} -> {tgt} (load enable)")

    # Summary
    print(f"\n  Decode: {len(cuts['Decode'])} edges")
    print(f"  Execute: {len(cuts['Execute'])} edges")
    print(f"  MemoryWriteback: {len(cuts['MemoryWriteback'])} edges")

    return cuts


def select_5stage_cuts(graph):
    """
    Select pipeline cut edges for 5-stage pipeline.

    5-stage pipeline: Fetch -> Decode -> Execute -> Memory -> Writeback

    Cut 1 (F/D): Instruction fetch boundary
    Cut 2 (D/X): Decode boundary - register reads, immediates, enables
    Cut 3 (X/M): Execute boundary - ALU results, memory addresses, store data
    Cut 4 (M/W): Memory boundary - memory read results, ALU results propagated
    """
    cuts = {'Decode': [], 'Execute': [], 'Memory': [], 'Writeback': []}

    def find_edge(src_id, tgt_id):
        for edge_id, edge in graph.edges.items():
            if edge.source.id == src_id and edge.target.id == tgt_id:
                return edge_id
        return None

    def find_edges_from(src_id):
        edges = []
        for edge_id, edge in graph.edges.items():
            if edge.source.id == src_id:
                edges.append((edge_id, edge.target.id))
        return edges

    def find_edges_to(tgt_id):
        edges = []
        for edge_id, edge in graph.edges.items():
            if edge.target.id == tgt_id:
                edges.append((edge_id, edge.source.id))
        return edges

    def find_edges_to_suffix(src_id, suffix):
        edges = []
        for edge_id, edge in graph.edges.items():
            if edge.source.id == src_id and (edge.target.id == suffix or edge.target.id.endswith('_' + suffix)):
                edges.append((edge_id, edge.target.id))
        return edges

    def find_edges_from_suffix(suffix, tgt_id):
        edges = []
        for edge_id, edge in graph.edges.items():
            if edge.target.id == tgt_id and (edge.source.id == suffix or edge.source.id.endswith('_' + suffix)):
                edges.append((edge_id, edge.source.id))
        return edges

    # ========================================
    # CUT 1: F/D - Fetch / Decode
    # ========================================
    print("\n5-STAGE PIPELINE CUTS")
    print("-" * 50)
    print("\nCUT 1: Fetch -> Decode")
    print("-" * 50)

    # Instruction word from memory
    eid = find_edge('pc_rd', 'imem')
    if eid:
        cuts['Decode'].append(eid)
        print(f"  [F/D] pc_rd -> imem")

    # All edges from instruction word
    for eid, tgt in find_edges_from('instr'):
        cuts['Decode'].append(eid)
        print(f"  [F/D] instr -> {tgt}")

    # PC value alongside instruction (for branch/jump target calculations)
    for eid, tgt in find_edges_from('pc_rd'):
        if '(pc +' in tgt and tgt != '(pc + 4)':
            cuts['Decode'].append(eid)
            print(f"  [F/D] pc_rd -> {tgt} (PC value for instruction)")

    # JAL/JALR return address
    eid = find_edge('(pc + 4)', 'ret_addr')
    if eid:
        cuts['Decode'].append(eid)
        print(f"  [F/D] (pc + 4) -> ret_addr (JAL/JALR return address)")

    # ========================================
    # CUT 2: D/X - Decode / Execute
    # ========================================
    print(f"\nCUT 2: Decode -> Execute")
    print("-" * 50)

    # Register file read values
    for eid, tgt in find_edges_to_suffix('rf[rs1]_rd', 'r1'):
        cuts['Execute'].append(eid)
        print(f"  [D/X] rf[rs1]_rd -> {tgt} (source reg 1 value)")

    for eid, tgt in find_edges_to_suffix('rf[rs2]_rd', 'r2'):
        cuts['Execute'].append(eid)
        print(f"  [D/X] rf[rs2]_rd -> {tgt} (source reg 2 value)")

    # Destination register index
    for eid, tgt in find_edges_from('rd'):
        if tgt != '(rd != 0)':
            cuts['Execute'].append(eid)
            print(f"  [D/X] rd -> {tgt} (dest reg index)")

    # PC for branch/jump calculations
    for eid, tgt in find_edges_from('pc_rd'):
        if '(pc +' in tgt and tgt != '(pc + 4)':
            cuts['Execute'].append(eid)
            print(f"  [D/X] pc_rd -> {tgt} (PC for target calc)")

    # Sign-extended immediates
    immediate_types = ['addi_sign_ext_imm', 'sb_sign_ext_imm', 'beq_sign_ext_imm',
                       'jal_sign_ext_imm', 'sign_ext_imm', 'auipc_imm']
    for imm_type in immediate_types:
        if imm_type in graph.nodes:
            for eid, src in find_edges_to(imm_type):
                cuts['Execute'].append(eid)
                print(f"  [D/X] {src} -> {imm_type}")

    # JAL/JALR return address - pipeline chain through Execute, Memory, and Writeback
    eid = find_edge('(pc + 4)', 'ret_addr')
    if eid:
        cuts['Execute'].append(eid)
        cuts['Memory'].append(eid)
        cuts['Writeback'].append(eid)
        print(f"  [D/X+] (pc + 4) -> ret_addr (return address pipeline chain)")

    # Instruction enable signals
    for node_id in graph.nodes:
        if node_id.endswith('_enable') and not node_id.startswith('rf_rd_ne_0') and node_id != 'umem_write_enable':
            # Skip byte enables - computed from address in Memory stage
            if node_id in ['sh_byte_enable', 'sb_byte_enable']:
                print(f"  [D/X] SKIP {node_id} (byte enable computed from address)")
                continue
            for eid, tgt in find_edges_from(node_id):
                if '_rd_enable' in tgt:
                    continue
                if tgt == 'rf_rd_ne_0_enables':
                    print(f"  [D/X] SKIP {node_id} -> {tgt} (stays at Decode)")
                    continue
                if tgt == 'umem_write_enable':
                    # Store enables must be pipelined D/X and X/M for umem_write_enable
                    cuts['Execute'].append(eid)
                    print(f"  [D/X] {node_id} -> {tgt} (pipeline store enable to Execute)")
                    continue
                cuts['Execute'].append(eid)
                print(f"  [D/X] {node_id} -> {tgt} (control)")

    # Shamt for shift instructions
    eid = find_edge('instr[24:20]', 'shamt')
    if eid:
        cuts['Execute'].append(eid)
        print(f"  [D/X] instr[24:20] -> shamt")

    # Combined write enable - pipeline from Decode to Execute
    for eid, tgt in find_edges_from('rf_rd_ne_0_guarded_enable'):
        cuts['Execute'].append(eid)
        print(f"  [D/X] rf_rd_ne_0_guarded_enable -> {tgt} (pipeline combined write enable)")

    # For 5-stage: umem_write_enable is computed in Memory from pipelined store enables
    # Do NOT pipeline umem_write_enable from Decode

    # ========================================
    # CUT 3: X/M - Execute / Memory
    # ========================================
    print(f"\nCUT 3: Execute -> Memory")
    print("-" * 50)

    # Memory addresses
    for addr_node in ['lb_addr', 'sb_addr']:
        for eid, tgt in find_edges_from(addr_node):
            if 'umem' in tgt:
                cuts['Memory'].append(eid)
                print(f"  [X/M] {addr_node} -> {tgt} (memory address)")

    # Byte offset nodes - dynamically find nodes that handle byte/halfword selection
    for node_id in list(graph.nodes.keys()):
        is_byte_offset = node_id.endswith('_byte_offset')
        is_halfword_select = node_id.endswith('_halfword_select')
        is_word_select = node_id.endswith('_word_select')

        if is_byte_offset or is_halfword_select or is_word_select:
            for eid, tgt in find_edges_from(node_id):
                cuts['Memory'].append(eid)
                print(f"  [X/M] {node_id} -> {tgt} (byte selection offset)")

    # ALU results going to writeback mux (will be propagated through to Writeback in CUT 4)
    alu_results = [
        'add_res', 'sub_res', 'and_res', 'or_res', 'xor_res',
        'sll_res', 'srl_res', 'sra_res', 'slt_res', 'sltu_res',
        'addi_res', 'andi_res', 'ori_res', 'xori_res',
        'slli_res', 'srli_res', 'srai_res', 'slti_res', 'sltiu_res',
        'lui_res', 'auipc_res',
    ]
    for res in alu_results:
        for eid, tgt in find_edges_from(res):
            if tgt == 'rf_write_data_mux':
                cuts['Memory'].append(eid)
                print(f"  [X/M] {res} -> rf_write_data_mux")

    # Store data (r2 may be instruction-prefixed like sw_r2)
    for eid, src in find_edges_from_suffix('r2', 'umem_write_data_mux'):
        cuts['Memory'].append(eid)
        print(f"  [X/M] {src} -> umem_write_data_mux (store data)")

    # Store enables - cut to umem_write_data_mux and umem_write_enable
    for store_enable in ['sb_enable', 'sh_enable', 'sw_enable']:
        for eid, tgt in find_edges_from(store_enable):
            if tgt == 'umem_write_data_mux':
                cuts['Memory'].append(eid)
                print(f"  [X/M] {store_enable} -> {tgt} (store enable)")
            elif tgt == 'umem_write_enable':
                cuts['Memory'].append(eid)
                print(f"  [X/M] {store_enable} -> {tgt} (store enable to write)")

    # Store byte/halfword data
    for store_data in ['sb_byte_data', 'sh_halfword_data']:
        for eid, tgt in find_edges_from(store_data):
            if tgt == 'umem_write_data_mux' or 'zext' in tgt or 'positioned' in tgt:
                cuts['Memory'].append(eid)
                print(f"  [X/M] {store_data} -> {tgt}")

    # Store address to byte_enable nodes
    for eid, tgt in find_edges_from('sb_addr'):
        if 'byte_enable' in tgt or 'positioned' in tgt or 'shift' in tgt:
            cuts['Memory'].append(eid)
            print(f"  [X/M] sb_addr -> {tgt} (store address to byte enable)")

    # Load enables - pipeline to Memory for memory read
    for load_enable in ['lb_enable', 'lh_enable', 'lw_enable', 'lbu_enable', 'lhu_enable']:
        for eid, tgt in find_edges_from(load_enable):
            if tgt == 'umem_addr_rd_enable':
                cuts['Memory'].append(eid)
                print(f"  [X/M] {load_enable} -> {tgt} (load enable)")

    # Propagate rd to Memory
    for eid, tgt in find_edges_from('rd'):
        if tgt in ['rf[rd]_wr', 'rf_shared_wr']:
            cuts['Memory'].append(eid)
            print(f"  [X/M] rd -> {tgt} (propagate rd to Memory)")

    # Propagate enable signals to rf_write_data_mux
    for node_id in graph.nodes:
        if node_id.endswith('_enable') and not node_id.startswith('rf_rd_ne_0') and node_id != 'umem_write_enable':
            for eid, tgt in find_edges_from(node_id):
                if tgt == 'rf_write_data_mux':
                    cuts['Memory'].append(eid)
                    print(f"  [X/M] {node_id} -> {tgt} (propagate control)")

    # Combined write enable - continue pipeline from Execute to Memory
    for eid, tgt in find_edges_from('rf_rd_ne_0_guarded_enable'):
        cuts['Memory'].append(eid)
        print(f"  [X/M] rf_rd_ne_0_guarded_enable -> {tgt} (pipeline combined write enable)")

    # For 5-stage: umem_write_enable is computed and used in Memory stage
    # Do NOT cut edges FROM umem_write_enable (no further pipelining to Writeback needed)

    # ========================================
    # CUT 4: M/W - Memory / Writeback
    # ========================================
    print(f"\nCUT 4: Memory -> Writeback")
    print("-" * 50)

    # Memory read results -> rf_write_data_mux
    memory_results = [
        '{{24{byte_data[7]_rd}}, byte_data}',
        '{{16{halfword_data[15]_rd}}, halfword_data}',
        '{24\'b0, byte_data}',
        '{16\'b0, halfword_data}',
        'data',
    ]
    for res in memory_results:
        for eid, tgt in find_edges_from(res):
            if tgt == 'rf_write_data_mux':
                cuts['Writeback'].append(eid)
                print(f"  [M/W] {res} -> rf_write_data_mux")

    # ALU results propagated to Writeback (they were pipelined to Memory in CUT 3,
    # now continue to Writeback for the register write mux)
    for res in alu_results:
        for eid, tgt in find_edges_from(res):
            if tgt == 'rf_write_data_mux':
                cuts['Writeback'].append(eid)
                print(f"  [M/W] {res} -> rf_write_data_mux (propagate to WB)")

    # Propagate rd to Writeback
    for eid, tgt in find_edges_from('rd'):
        if tgt in ['rf[rd]_wr', 'rf_shared_wr']:
            cuts['Writeback'].append(eid)
            print(f"  [M/W] rd -> {tgt} (propagate rd to WB)")

    # Propagate enable signals to rf_write_data_mux for Writeback
    for node_id in graph.nodes:
        if node_id.endswith('_enable') and not node_id.startswith('rf_rd_ne_0') and node_id != 'umem_write_enable':
            for eid, tgt in find_edges_from(node_id):
                if tgt == 'rf_write_data_mux':
                    cuts['Writeback'].append(eid)
                    print(f"  [M/W] {node_id} -> {tgt} (propagate control to WB)")

    # Combined write enable - continue pipeline from Memory to Writeback
    for eid, tgt in find_edges_from('rf_rd_ne_0_guarded_enable'):
        cuts['Writeback'].append(eid)
        print(f"  [M/W] rf_rd_ne_0_guarded_enable -> {tgt} (pipeline combined write enable)")

    # For 5-stage: umem_write_enable is computed and used in Memory stage (not Writeback)
    # Do NOT cut edges FROM umem_write_enable to Writeback

    # Summary
    print(f"\n  Decode: {len(cuts['Decode'])} edges")
    print(f"  Execute: {len(cuts['Execute'])} edges")
    print(f"  Memory: {len(cuts['Memory'])} edges")
    print(f"  Writeback: {len(cuts['Writeback'])} edges")

    return cuts


def apply_pipeline_transform(graph, cuts, num_stages=2):
    """Apply pipeline transformation.

    Args:
        graph: The resource graph to transform
        cuts: Dictionary of stage_name -> list of edge IDs to cut
        num_stages: Number of pipeline stages (2, 3, 4, or 5)
    """
    print("\nApplying pipeline transformation...")

    transform = PipelineTransform(graph)

    # Set explicit stage order for validity signal creation
    if num_stages == 5:
        # For 5-stage: Fetch (0) -> Decode (1) -> Execute (2) -> Memory (3) -> Writeback (4)
        stage_order = ['Decode', 'Execute', 'Memory', 'Writeback']
        stage_indices = {'Decode': 1, 'Execute': 2, 'Memory': 3, 'Writeback': 4}
    elif num_stages == 4:
        # For 4-stage: Fetch (0) -> Decode (1) -> Execute (2) -> MemoryWriteback (3)
        stage_order = ['Decode', 'Execute', 'MemoryWriteback']
        stage_indices = {'Decode': 1, 'Execute': 2, 'MemoryWriteback': 3}
    elif num_stages == 3:
        # For 3-stage: Fetch (0) -> Decode (1) -> ExecuteMemoryWriteback (2)
        stage_order = ['Decode', 'ExecuteMemoryWriteback']
        stage_indices = {'Decode': 1, 'ExecuteMemoryWriteback': 2}
    else:
        # For 2-stage: Fetch (0) -> ExecuteMemoryWriteback (1)
        stage_order = ['ExecuteMemoryWriteback']
        stage_indices = {'ExecuteMemoryWriteback': 1}

    transform.set_stage_order(stage_order, stage_indices)
    print(f"  Stage order: {stage_order}")

    # Build cut specifications
    cut_specs = []
    for stage_name in stage_order:
        edge_ids = cuts.get(stage_name, [])
        if edge_ids:
            cut_specs.append({
                'edges': edge_ids,
                'after_stage': stage_name,
                'stage_index': stage_indices[stage_name]
            })
            print(f"  Stage {stage_name}: {len(edge_ids)} edges to cut (pipe_time={stage_indices[stage_name]})")

    # Apply all pipeline stages
    print("\nInserting pipeline registers...")
    success = transform.add_multiple_pipeline_stages(cut_specs)

    if success:
        summary = transform.get_pipeline_summary()
        print(f"\nPipeline transformation successful!")
        print(f"  Total stages: {summary['total_stages']}")
        print(f"  Max uarch_time: {summary['max_uarch_time']}")
    else:
        print("Pipeline transformation FAILED!")

    # Get the transformed graph
    pipelined = graph  # The transform modifies in place
    pipelined.infer_pipe_time()

    print(f"  Pipelined nodes: {len(pipelined.nodes)}")
    print(f"  Pipelined edges: {len(pipelined.edges)}")

    return pipelined


def main():
    parser = argparse.ArgumentParser(description="Create dual-issue RV32I pipeline")
    parser.add_argument('--stages', type=int, default=2, choices=[2, 3, 4, 5],
                        help='Number of pipeline stages (2, 3, 4, or 5)')
    parser.add_argument('--no-verify', action='store_true',
                        help='Skip verification step')
    parser.add_argument('--lockstep', action='store_true',
                        help='Use lockstep stall coupling (P1 stall also stalls P0)')
    args = parser.parse_args()

    num_stages = args.stages
    lockstep_mode = args.lockstep

    spec_label = ""
    if lockstep_mode:
        spec_label = " (LOCKSTEP)"
    print("=" * 70)
    print(f"DUAL-ISSUE RV32I {num_stages}-STAGE PIPELINE GENERATOR{spec_label}")
    print("=" * 70)

    # Step 1: Build merged graphs for P0 and P1
    print("\n" + "=" * 70)
    print("STEP 1: BUILD INSTRUCTION GRAPHS")
    print("=" * 70)

    p0_graph = build_merged_graph(P0_INSTRUCTIONS, "P0 (full RV32I)")
    p1_graph = build_merged_graph(P1_INSTRUCTIONS, "P1 (ALU subset)")

    # Step 2: Apply pipelining to both graphs
    print("\n" + "=" * 70)
    print(f"STEP 2: APPLY {num_stages}-STAGE PIPELINING")
    print("=" * 70)

    # Select cuts based on pipeline depth
    if num_stages == 5:
        select_cuts = select_5stage_cuts
    elif num_stages == 4:
        select_cuts = select_4stage_cuts
    elif num_stages == 3:
        select_cuts = select_3stage_cuts
    else:
        select_cuts = select_2stage_cuts

    # Apply to P0
    print("\nPipelining P0...")
    p0_cuts = select_cuts(p0_graph)
    p0_pipelined = apply_pipeline_transform(p0_graph, p0_cuts, num_stages)

    # Apply to P1 (same cut strategy)
    print("\nPipelining P1...")
    p1_cuts = select_cuts(p1_graph)
    p1_pipelined = apply_pipeline_transform(p1_graph, p1_cuts, num_stages)

    # Step 3: Merge the two pipelines
    print("\n" + "=" * 70)
    print("STEP 3: MERGE PIPELINES")
    print("=" * 70)

    merger = DualIssuePipelineMerger(p0_pipelined, p1_pipelined)
    merged = merger.merge(
        p0_pc_name='pc_rd',
        p1_pc_name='pc_rd',
        shared_state_names=['rf', 'pc', 'imem', 'umem']
    )

    # Step 3b: Transform byte_enable_computation nodes for sub-word stores
    print("\n" + "=" * 70)
    print("STEP 3b: TRANSFORM BYTE ENABLE NODES")
    print("=" * 70)

    mem_transform = MemoryAccessTransform(merged)
    umem_spec = MemoryAccessTransformSpec(
        memory='umem',
        strategy='set_port_width',
        current_width=8,
        target_width=32,
        direction='forward'
    )
    result = mem_transform.apply_transformation(umem_spec)
    if result.get('transformed'):
        print(f"  Memory transformation successful: {result.get('num_accesses_transformed', 0)} accesses transformed")
    else:
        print(f"  Memory transformation skipped: {result.get('reason', 'unknown')}")

    # Step 4: Hazard Analysis
    print("\n" + "=" * 70)
    print("STEP 4: HAZARD ANALYSIS")
    print("=" * 70)

    # Use dual_issue_time for hazard detection
    # analyze_hazards() discovers both indexed (RF) and non-indexed (individual) hazards
    analyzer = HazardAnalyzer(merged, 'pc_rd', time_field='dual_issue_time')
    all_hazards = analyzer.analyze_hazards()

    indexed_hazards = [h for h in all_hazards if h.is_indexed]
    individual_hazards = [h for h in all_hazards if not h.is_indexed]
    print(f"  Detected {len(indexed_hazards)} RF hazards")
    print(f"  Detected {len(individual_hazards)} individual ISA state hazards")

    # Step 5: Hazard Resolution
    print("\n" + "=" * 70)
    print("STEP 5: HAZARD RESOLUTION")
    print("=" * 70)

    resolver = HazardResolver(merged, isa_states_to_gate=['pc_rd'])

    # Mark all RF hazards for stalling
    for hazard in indexed_hazards:
        hazard.resolution = HazardResolutionStrategy.STALL

    resolver.resolve_all_hazards(indexed_hazards)

    # Skip individual ISA state hazards (PC) - branch/jump destinations
    # are computed in Execute stage and written back at end of cycle
    print(f"  Skipping {len(individual_hazards)} individual ISA state hazards (PC) for {num_stages}-stage pipeline")

    # Step 6: Finalize PC advancement
    print("\n" + "=" * 70)
    print("STEP 6: FINALIZE PC ADVANCEMENT")
    print("=" * 70)

    finalize_pc_advancement(merged, 'pc_wr', lockstep=lockstep_mode)

    # Step 6b: Add control hazard flush logic
    print("\n" + "=" * 70)
    print("STEP 6b: CONTROL HAZARD FLUSH")
    print("=" * 70)

    # Flush components are now discovered structurally from the PC write mux
    add_dual_issue_control_hazard_flush(merged)

    # Step 7: Re-infer timing
    print("\n" + "=" * 70)
    print("STEP 7: RE-INFER TIMING")
    print("=" * 70)

    merged.infer_pipe_time(force_reinfer=True)
    merged.infer_dual_issue_time(force_reinfer=True)

    # Step 8: Generate Verilog
    print("\n" + "=" * 70)
    print("STEP 8: GENERATE VERILOG")
    print("=" * 70)

    if num_stages == 2:
        dir_name = "riscv32i_dual_issue"
        module_name = "riscv32i_dual_issue"
    else:
        dir_name = f"riscv32i_dual_issue_{num_stages}stage"
        module_name = f"riscv32i_dual_issue_{num_stages}stage"

    output_dir = os.path.join(_project_root, "examples", "verilog", dir_name)
    os.makedirs(output_dir, exist_ok=True)

    generator = VerilogGenerator(merged, module_name=module_name)
    verilog_code = generator.generate()

    verilog_path = os.path.join(output_dir, f"{module_name}.v")
    with open(verilog_path, 'w') as f:
        f.write(verilog_code)
    print(f"  Generated: {verilog_path}")

    # Save graph
    graph_path = os.path.join(output_dir, f"{module_name}.rgraph")
    merged.save_to_file(graph_path)
    print(f"  Saved graph: {graph_path}")

    # Generate testbench
    from isa.riscv32.generators.generate_testbench import generate_testbench
    tb_path = os.path.join(output_dir, "simple_tb.sv")
    generate_testbench(verilog_path, tb_path)

    # Copy test script if not already present
    dst_script = os.path.join(output_dir, "run_riscv_tests.sh")
    if not os.path.exists(dst_script):
        # Search for an existing dual-issue test script to use as template
        import shutil
        candidates = [
            os.path.join(_project_root, "examples/verilog/riscv32i_dual_issue/run_riscv_tests.sh"),
            os.path.join(_project_root, "examples/verilog/riscv32i_pipelined/run_riscv_tests.sh"),
            os.path.join(_project_root, "../examples/verilog/riscv32i_dual_issue/run_riscv_tests.sh"),
        ]
        for src_script in candidates:
            if os.path.exists(src_script):
                shutil.copy2(src_script, dst_script)
                os.chmod(dst_script, 0o755)
                print(f"  Copied test script: {dst_script}")
                break

    print("\n" + "=" * 70)
    print("DUAL-ISSUE PIPELINE GENERATION COMPLETE")
    print("=" * 70)
    print(f"\nGenerated files:")
    print(f"  - {verilog_path}")
    print(f"  - {graph_path}")
    print(f"  - {tb_path}")


if __name__ == '__main__':
    main()
