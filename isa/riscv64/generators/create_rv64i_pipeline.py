#!/usr/bin/env python3
from __future__ import annotations
"""
Create a pipelined RISC-V 64-bit processor with configurable stages.

This script applies pipeline transformations to create 2, 3, 4, or 5-stage pipelines
for RV64I. Pipeline cut decisions are made here by the architect.

Supports --engine python (default) or --engine rust for the Rust isacomp_core backend.
Supports Verilog, VHDL, PyRTL, and CIRCT backends via --backend argument.

Usage:
    python create_rv64i_pipeline.py [--engine ENGINE] [--stages N]

Arguments:
    --engine ENGINE             Engine: 'python' or 'rust'. Default: python
    --stages N                  Number of pipeline stages (2, 3, 4, or 5). Default: 5
    --hazard-resolution STRATEGY  Hazard resolution strategy: 'stall' or 'bypass'. Default: stall
    --backend BACKEND           Output backend: 'verilog', 'vhdl', 'pyrtl', or 'circt'. Default: verilog
"""

import os
import sys
import argparse
import re
import shutil

# Add project root to path for imports
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Engine selection — set by _init_engine() before use.
_engine = 'python'

# These will be set by _init_engine() for both engines.
ResourceGraphMerger = None
PipelineTransform = None
HazardAnalyzer = None
HazardResolver = None
HazardResolutionStrategy = None
VerilogGenerator = None
MemoryAccessTransform = None
MemoryAccessTransformSpec = None
get_pipeline_config = None
PipelineStageMapper = None
set_memory_variable_latency = None
wire_memory_start_signal = None
apply_branch_prediction_not_taken = None
RASSpec = None
CallSpec = None
ReturnSpec = None
apply_return_address_stack = None
Node = None
Edge = None


def _init_engine(engine):
    """Initialize engine-specific imports."""
    global _engine
    global ResourceGraphMerger, PipelineTransform
    global HazardAnalyzer, HazardResolver, HazardResolutionStrategy
    global VerilogGenerator, MemoryAccessTransform, MemoryAccessTransformSpec
    global get_pipeline_config, PipelineStageMapper
    global set_memory_variable_latency, wire_memory_start_signal
    global apply_branch_prediction_not_taken
    global RASSpec, CallSpec, ReturnSpec, apply_return_address_stack
    global Node, Edge

    _engine = engine

    if engine == 'rust':
        # Add rust_core to path for isacomp_core
        _rust_core = os.path.join(_project_root, 'rust_core')
        if _rust_core not in sys.path:
            sys.path.insert(0, _rust_core)
        try:
            import isacomp_core as _rc
        except ImportError:
            print("Error: isacomp_core not found. Build it with:")
            print("  cd rust_core && maturin build --release")
            sys.exit(1)

        # Graph operations
        ResourceGraphMerger = None  # Not needed — merge_instructions() used directly
        PipelineTransform = _rc.PipelineTransform
        HazardAnalyzer = _rc.HazardAnalyzer
        HazardResolver = _rc.HazardResolver
        HazardResolutionStrategy = _rc.HazardResolutionStrategy
        VerilogGenerator = _rc.VerilogGenerator
        MemoryAccessTransform = _rc.MemoryAccessTransform
        MemoryAccessTransformSpec = _rc.MemoryAccessTransformSpec
        get_pipeline_config = _rc.get_pipeline_config
        set_memory_variable_latency = _rc.set_memory_variable_latency
        wire_memory_start_signal = _rc.wire_memory_start_signal
        apply_branch_prediction_not_taken = _rc.apply_branch_prediction_not_taken

        # PipelineStageMapper is pure Python — same for both engines
        from core.pipeline_config import PipelineStageMapper as _PSM
        PipelineStageMapper = _PSM

        # Advanced features — Rust function-based API with Python-compatible wrappers
        Node = _rc.Node
        Edge = _rc.Edge

        class CallSpec:
            def __init__(self, enable_node_id, dest_reg_node_id=None, return_addr_node_id=None):
                self.enable_node_id = enable_node_id
                self.dest_reg_node_id = dest_reg_node_id
                self.return_addr_node_id = return_addr_node_id
        class ReturnSpec:
            def __init__(self, enable_node_id, src_reg_node_id=None, dest_reg_node_id=None):
                self.enable_node_id = enable_node_id
                self.src_reg_node_id = src_reg_node_id
                self.dest_reg_node_id = dest_reg_node_id
        class RASSpec:
            def __init__(self, call_specs, return_specs, link_registers, ras_depth, ras_width,
                         predicted_pc_node_id, default_prediction_node_id,
                         control_hazard_flush_node_id, jalr_target_node_id,
                         jalr_execute_enable_node_id=None, return_branch_taken_node_id=None,
                         use_combinational_validity=False):
                self.call_specs = call_specs
                self.return_specs = return_specs
                self.link_registers = link_registers
                self.ras_depth = ras_depth
                self.ras_width = ras_width
                self.predicted_pc_node_id = predicted_pc_node_id
                self.default_prediction_node_id = default_prediction_node_id
                self.control_hazard_flush_node_id = control_hazard_flush_node_id
                self.jalr_target_node_id = jalr_target_node_id
                self.jalr_execute_enable_node_id = jalr_execute_enable_node_id
                self.return_branch_taken_node_id = return_branch_taken_node_id
                self.use_combinational_validity = use_combinational_validity
        def _apply_return_address_stack(graph, spec):
            return _rc.apply_return_address_stack(
                graph,
                call_enables=[c.enable_node_id for c in spec.call_specs],
                call_dest_regs=[c.dest_reg_node_id for c in spec.call_specs],
                call_return_addrs=[c.return_addr_node_id for c in spec.call_specs],
                return_enables=[r.enable_node_id for r in spec.return_specs],
                return_src_regs=[r.src_reg_node_id for r in spec.return_specs],
                return_dest_regs=[r.dest_reg_node_id for r in spec.return_specs],
                predicted_pc_node_id=spec.predicted_pc_node_id,
                default_prediction_node_id=spec.default_prediction_node_id,
                control_hazard_flush_node_id=spec.control_hazard_flush_node_id,
                jalr_target_node_id=spec.jalr_target_node_id,
                link_registers=spec.link_registers,
                ras_depth=spec.ras_depth,
                ras_width=spec.ras_width,
                jalr_execute_enable_node_id=spec.jalr_execute_enable_node_id,
                return_branch_taken_node_id=spec.return_branch_taken_node_id,
                use_combinational_validity=spec.use_combinational_validity,
            )
        apply_return_address_stack = _apply_return_address_stack

        # Store module reference for build_merged_graph
        _init_engine._rc = _rc

        print(f"  Using Rust engine (isacomp_core)")
    else:
        from core.resource_graph import ResourceGraph as _RG, Node as _Node, Edge as _Edge
        from core.graph_merger import ResourceGraphMerger as _RGM
        from opt.pipeline.pipelining_optimization import PipelineTransform as _PT
        from opt.fetch.branch_prediction_not_taken import apply_branch_prediction_not_taken as _abpnt
        from opt.fetch.return_address_stack import RASSpec as _RASS, CallSpec as _CS, ReturnSpec as _RS, apply_return_address_stack as _aras
        from opt.pipeline.hazard_resolution import HazardAnalyzer as _HA, HazardResolver as _HR, HazardResolutionStrategy as _HRS
        from backends.verilog import VerilogGenerator as _VG
        from opt.memory.memory_access_transform import MemoryAccessTransform as _MAT, MemoryAccessTransformSpec as _MATS
        from core.pipeline_config import get_pipeline_config as _gpc, PipelineStageMapper as _PSM
        from opt.temporal.multi_cycle_operations import (
            set_memory_variable_latency as _smvl,
            wire_memory_start_signal as _wmss,
        )

        ResourceGraphMerger = _RGM
        PipelineTransform = _PT
        HazardAnalyzer = _HA
        HazardResolver = _HR
        HazardResolutionStrategy = _HRS
        VerilogGenerator = _VG
        MemoryAccessTransform = _MAT
        MemoryAccessTransformSpec = _MATS
        get_pipeline_config = _gpc
        PipelineStageMapper = _PSM
        set_memory_variable_latency = _smvl
        wire_memory_start_signal = _wmss
        apply_branch_prediction_not_taken = _abpnt
        RASSpec = _RASS
        CallSpec = _CS
        ReturnSpec = _RS
        apply_return_address_stack = _aras
        Node = _Node
        Edge = _Edge

        print(f"  Using Python engine")

# RV64I instruction list for testbench generation
RV64I_INSTRUCTIONS = [
    # R-type arithmetic
    'add', 'sub', 'and', 'or', 'xor', 'sll', 'srl', 'sra', 'slt', 'sltu',
    # I-type immediate
    'addi', 'andi', 'ori', 'xori', 'slli', 'srli', 'srai', 'slti', 'sltiu',
    # Load (base)
    'lb', 'lh', 'lw', 'lbu', 'lhu',
    # Load (RV64I-specific)
    'ld', 'lwu',
    # Store (base)
    'sb', 'sh', 'sw',
    # Store (RV64I-specific)
    'sd',
    # Branch
    'beq', 'bne', 'blt', 'bge', 'bltu', 'bgeu',
    # Jump
    'jal', 'jalr',
    # Upper immediate
    'lui', 'auipc',
    # RV64I-specific word operations
    'addw', 'subw', 'sllw', 'srlw', 'sraw',
    'addiw', 'slliw', 'srliw', 'sraiw',
]


def get_rv64i_instructions():
    """Get all RV64I base instructions."""
    rv64i_dir = os.path.join(_project_root, "isa/riscv64")
    instructions = {}

    # Complete RV64I instruction set (49 instructions)
    base_instrs = [
        # R-type arithmetic
        'add', 'sub', 'and', 'or', 'xor', 'sll', 'srl', 'sra', 'slt', 'sltu',
        # I-type immediate
        'addi', 'andi', 'ori', 'xori', 'slli', 'srli', 'srai', 'slti', 'sltiu',
        # Load (base)
        'lb', 'lh', 'lw', 'lbu', 'lhu',
        # Load (RV64I-specific)
        'ld', 'lwu',
        # Store (base)
        'sb', 'sh', 'sw',
        # Store (RV64I-specific)
        'sd',
        # Branch
        'beq', 'bne', 'blt', 'bge', 'bltu', 'bgeu',
        # Jump
        'jal', 'jalr',
        # Upper immediate
        'lui', 'auipc',
        # RV64I-specific word operations
        'addiw', 'slliw', 'srliw', 'sraiw',
        'addw', 'subw', 'sllw', 'srlw', 'sraw',
    ]

    for instr in base_instrs:
        isa_file = os.path.join(rv64i_dir, f"{instr}.isa")
        if os.path.exists(isa_file):
            instructions[instr] = isa_file

    return instructions


def build_merged_graph():
    """Build merged graph of all RV64I instructions."""
    print(f"Building merged RV64I graph ({_engine} engine)...")

    instructions = get_rv64i_instructions()
    print(f"  Found {len(instructions)} instructions")

    if _engine == 'rust':
        _rc = _init_engine._rc
        merged = _rc.merge_instructions(instructions, pc_name="pc")
    else:
        merger = ResourceGraphMerger()
        for name, path in instructions.items():
            merger.add_instruction(name, path)
        merged = merger.merge_graphs()

    merged.infer_uarch_time()

    print(f"  Nodes: {len(merged.nodes)}")
    print(f"  Edges: {len(merged.edges)}")

    return merged


def select_pipeline_cut_edges_generic(graph: ResourceGraph, config: PipelineConfig):
    """
    Select edges for each pipeline cut based on the pipeline configuration.

    This is a generic version that works with 2, 3, 4, or 5-stage pipelines.
    The cuts are selected based on which stages are present in the configuration.
    """

    print("\n" + "=" * 70)
    print(f"PIPELINE CUT EDGE SELECTION ({config.num_stages}-stage)")
    print(f"Stages: {' -> '.join(config.stage_names)}")
    print("=" * 70)

    cuts = {}
    for cut in config.cuts:
        cuts[cut.name] = []

    # Edge lookup helpers — use native Rust methods when available (O(degree)
    # per node), fall back to full iteration for Python engine.
    _has_native = hasattr(graph, 'find_edges_from')

    def find_edge(src_id, tgt_id):
        if _has_native:
            return graph.find_edge(src_id, tgt_id)
        for edge_id, edge in graph.edges.items():
            if edge.source.id == src_id and edge.target.id == tgt_id:
                return edge_id
        return None

    def find_edges_to_suffix(src_id, suffix):
        if _has_native:
            return graph.find_edges_to_suffix(src_id, suffix)
        edges = []
        for edge_id, edge in graph.edges.items():
            if edge.source.id == src_id and (edge.target.id == suffix or edge.target.id.endswith('_' + suffix)):
                edges.append((edge_id, edge.target.id))
        return edges

    def find_edges_from_suffix(suffix, tgt_id):
        if _has_native:
            return graph.find_edges_from_suffix(suffix, tgt_id)
        edges = []
        for edge_id, edge in graph.edges.items():
            if edge.target.id == tgt_id and (edge.source.id == suffix or edge.source.id.endswith('_' + suffix)):
                edges.append((edge_id, edge.source.id))
        return edges

    def find_edges_from(src_id):
        if _has_native:
            return graph.find_edges_from(src_id)
        edges = []
        for edge_id, edge in graph.edges.items():
            if edge.source.id == src_id:
                edges.append((edge_id, edge.target.id))
        return edges

    def find_edges_to(tgt_id):
        if _has_native:
            return graph.find_edges_to(tgt_id)
        edges = []
        for edge_id, edge in graph.edges.items():
            if edge.target.id == tgt_id:
                edges.append((edge_id, edge.source.id))
        return edges

    # Stage mapper for translating between canonical and actual stage names
    mapper = PipelineStageMapper(config)

    # Get actual stage names for each canonical stage
    decode_stage = mapper.canonical_to_actual("Decode")
    execute_stage = mapper.canonical_to_actual("Execute")
    memory_stage = mapper.canonical_to_actual("Memory")
    writeback_stage = mapper.canonical_to_actual("Writeback")

    # ========================================
    # CUT 1: F/D - Instruction Fetch / Decode
    # ========================================
    # This cut is always present (in all configurations)
    if decode_stage in cuts:
        print(f"\nCUT 1: Fetch -> {decode_stage}")
        print("-" * 50)

        # Instruction word from umem (unified memory)
        # For 64-bit memory with 32-bit instructions, there's a byte mux in between
        eid = find_edge('umem[pc]_rd', 'instr')
        if eid:
            cuts[decode_stage].append(eid)
            print(f"  [F/{decode_stage[0]}] umem[pc]_rd -> instr")
        else:
            # Check for byte mux (64-bit memory with 32-bit instruction fetch)
            eid = find_edge('instr_byte_mux', 'instr')
            if eid:
                cuts[decode_stage].append(eid)
                print(f"  [F/{decode_stage[0]}] instr_byte_mux -> instr (via byte mux)")

        # PC value needs to be pipelined alongside the instruction it fetched
        for eid, tgt in find_edges_from('pc_rd'):
            if '(pc +' in tgt and tgt != '(pc + 4)':
                cuts[decode_stage].append(eid)
                print(f"  [F/{decode_stage[0]}] pc_rd -> {tgt} (PC value for instruction)")

        # JAL/JALR return address
        eid = find_edge('(pc + 4)', 'ret_addr')
        if eid:
            cuts[decode_stage].append(eid)
            print(f"  [F/{decode_stage[0]}] (pc + 4) -> ret_addr (JAL/JALR return address)")

    # ========================================
    # CUT 2: D/X - Decode / Execute
    # ========================================
    # This cut is present in 4 and 5-stage pipelines (NOT 3-stage)
    # For 3-stage, the combined ExecuteMemoryWriteback stage is handled separately below
    if config.num_stages >= 4 and execute_stage in cuts and execute_stage != decode_stage:
        print(f"\nCUT 2: {decode_stage} -> {execute_stage}")
        print("-" * 50)

        # Register file read values - handles both merged (r1/r2) and split (add_r1/sd_r2) naming
        for eid, tgt in find_edges_to_suffix('rf[rs1]_rd', 'r1'):
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] rf[rs1]_rd -> {tgt} (source reg 1 value)")

        for eid, tgt in find_edges_to_suffix('rf[rs2]_rd', 'r2'):
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] rf[rs2]_rd -> {tgt} (source reg 2 value)")

        # Destination register index - flows through subsequent stages
        for eid, tgt in find_edges_from('rd'):
            if tgt != '(rd != 0)':  # Comparison stays in Decode
                cuts[execute_stage].append(eid)
                print(f"  [{decode_stage[0]}/{execute_stage[0]}] rd -> {tgt} (dest reg index)")

        # PC for branch/jump calculations
        for eid, tgt in find_edges_from('pc_rd'):
            if '(pc +' in tgt and tgt != '(pc + 4)':
                cuts[execute_stage].append(eid)
                print(f"  [{decode_stage[0]}/{execute_stage[0]}] pc_rd -> {tgt} (PC for target calc)")

        # Sign-extended immediates — discover dynamically to support both
        # Python merger (shared nodes like 'sign_ext_imm') and Rust merger
        # (per-instruction nodes like 'bne_sign_ext_imm')
        immediate_types = set()
        for node_id in graph.nodes:
            if node_id.endswith('_sign_ext_imm') or node_id == 'sign_ext_imm':
                immediate_types.add(node_id)
            elif node_id.endswith('_imm') and node_id in ('auipc_imm',):
                immediate_types.add(node_id)
        for imm_type in sorted(immediate_types):
            if imm_type in graph.nodes:
                for eid, src in find_edges_to(imm_type):
                    cuts[execute_stage].append(eid)
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] {src} -> {imm_type}")

        # JAL/JALR return address pipeline chain
        eid = find_edge('(pc + 4)', 'ret_addr')
        if eid:
            cuts[execute_stage].append(eid)
            # Also add to subsequent stages if they exist
            if memory_stage in cuts and memory_stage != execute_stage:
                cuts[memory_stage].append(eid)
            if writeback_stage in cuts and writeback_stage != memory_stage:
                cuts[writeback_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}+] (pc + 4) -> ret_addr (return address pipeline chain)")

        # All instruction enable signals
        for node_id in graph.nodes:
            if node_id.endswith('_enable') and not node_id.startswith('rf_rd_ne_0'):
                # Skip umem_write_enable for 4/5-stage - it's computed in Memory stage from Memory-stage enables
                # For 5-stage: Memory stage exists separately, umem_write_enable computed there
                # For 4-stage: MemoryWriteback combined, umem_write_enable computed there
                if node_id == 'umem_write_enable' and memory_stage != execute_stage:
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} (computed at {memory_stage} from store enables)")
                    continue
                # Skip byte enables - computed in Memory stage from address, not Decode
                # In RV64I: sb/sh/sw are all subword stores (sd is full-width)
                if node_id in ['sh_byte_enable', 'sb_byte_enable', 'sw_byte_enable', 'sd_byte_enable']:
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} (byte enable computed at {memory_stage} from address)")
                    continue
                for eid, tgt in find_edges_from(node_id):
                    # Exception: umem_addr_rd_enable needs to reach Memory for stall detection
                    if '_rd_enable' in tgt and tgt != 'umem_addr_rd_enable':
                        print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} -> {tgt} (read enable stays at Decode)")
                        continue
                    # Skip edges to rf_rd_ne_0_enables - it's computed at Decode from D-stage enables
                    if tgt == 'rf_rd_ne_0_enables':
                        print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} -> {tgt} (rf_rd_ne_0_enables stays at Decode)")
                        continue
                    # For 4/5-stage: Cut edges to umem_write_enable at D/E so they get double-pipelined (D->E->M)
                    # The edge will be cut again at E/M to complete the pipeline chain
                    cuts[execute_stage].append(eid)
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] {node_id} -> {tgt} (control)")

        # Shamt for shift instructions (6 bits in RV64I)
        # After merge, shamt becomes instruction-specific: slli_shamt, slliw_shamt, etc.
        shamt_targets = [
            'shamt',  # Original name
            'slli_shamt', 'srli_shamt', 'srai_shamt',  # RV64I immediate shifts
            'slliw_shamt',  # RV64I word immediate shifts
            'sllw_shamt', 'srlw_shamt', 'sraw_shamt',  # RV64I word register shifts
        ]
        for shamt_src in ['instr[25:20]', 'instr[24:20]']:
            for shamt_tgt in shamt_targets:
                eid = find_edge(shamt_src, shamt_tgt)
                if eid:
                    cuts[execute_stage].append(eid)
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] {shamt_src} -> {shamt_tgt}")

        # DON'T cut edges TO rf_rd_ne_0_guarded_enable - it stays at Decode
        # rf_rd_ne_0_guarded_enable = rf_rd_ne_0_enables && (rd != 0), computed at Decode
        # Instead, cut edges FROM rf_rd_ne_0_guarded_enable to pipeline the combined signal
        for eid, tgt in find_edges_from('rf_rd_ne_0_guarded_enable'):
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] rf_rd_ne_0_guarded_enable -> {tgt} (pipeline combined write enable)")

        # Note: Store data (sb_byte_data, sh_halfword_data, sd_data) are computed IN Execute stage from pipelined r2
        # They should NOT be pipelined at D/E - only at E/M (handled later in the code)

        # For 4/5-stage: umem_write_enable is computed in Memory stage from store enables, not pipelined from Decode
        # For 3-stage and below: umem_write_enable is computed at Decode and pipelined forward
        # So only pipeline umem_write_enable if Memory stage == Execute stage (i.e., 3-stage or less)
        if memory_stage == execute_stage:
            # DON'T cut edges TO umem_write_enable - it stays at Decode
            # umem_write_enable is computed at Decode from D-stage store enables
            # Instead, cut edges FROM umem_write_enable to pipeline the combined signal
            for eid, tgt in find_edges_from('umem_write_enable'):
                cuts[execute_stage].append(eid)
                print(f"  [{decode_stage[0]}/{execute_stage[0]}] umem_write_enable -> {tgt} (pipeline combined write enable)")

    # For 3-stage pipeline where Execute/Memory/Writeback is combined
    elif config.num_stages == 3:
        print(f"\nCUT 2 (combined X/M/W): {decode_stage} -> {execute_stage}")
        print("-" * 50)

        # Register file read values - handles both merged (r1/r2) and split (add_r1/sd_r2) naming
        for eid, tgt in find_edges_to_suffix('rf[rs1]_rd', 'r1'):
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] rf[rs1]_rd -> {tgt} (source reg 1 value)")

        for eid, tgt in find_edges_to_suffix('rf[rs2]_rd', 'r2'):
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] rf[rs2]_rd -> {tgt} (source reg 2 value)")

        # Destination register index
        for eid, tgt in find_edges_from('rd'):
            if tgt != '(rd != 0)':
                cuts[execute_stage].append(eid)
                print(f"  [{decode_stage[0]}/{execute_stage[0]}] rd -> {tgt} (dest reg index)")

        # PC for branch/jump calculations
        for eid, tgt in find_edges_from('pc_rd'):
            if '(pc +' in tgt and tgt != '(pc + 4)':
                cuts[execute_stage].append(eid)
                print(f"  [{decode_stage[0]}/{execute_stage[0]}] pc_rd -> {tgt} (PC for target calc)")

        # Sign-extended immediates — discover dynamically
        immediate_types = set()
        for node_id in graph.nodes:
            if node_id.endswith('_sign_ext_imm') or node_id == 'sign_ext_imm':
                immediate_types.add(node_id)
            elif node_id.endswith('_imm') and node_id in ('auipc_imm',):
                immediate_types.add(node_id)
        for imm_type in sorted(immediate_types):
            if imm_type in graph.nodes:
                for eid, src in find_edges_to(imm_type):
                    cuts[execute_stage].append(eid)
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] {src} -> {imm_type}")

        # JAL/JALR return address
        eid = find_edge('(pc + 4)', 'ret_addr')
        if eid:
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] (pc + 4) -> ret_addr")

        # Instruction enable signals
        for node_id in graph.nodes:
            if node_id.endswith('_enable') and not node_id.startswith('rf_rd_ne_0') and node_id != 'umem_write_enable':
                # Skip byte enables - computed at ExecuteMemoryWriteback stage from address, not Decode
                # In RV64I: sb/sh/sw are all subword stores (sd is full-width)
                if node_id in ['sh_byte_enable', 'sb_byte_enable', 'sw_byte_enable', 'sd_byte_enable']:
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} (byte enable computed at {execute_stage[0]} from address)")
                    continue
                for eid, tgt in find_edges_from(node_id):
                    if '_rd_enable' in tgt or tgt == 'rf_rd_ne_0_enables' or tgt == 'umem_write_enable':
                        continue
                    cuts[execute_stage].append(eid)
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] {node_id} -> {tgt} (control)")

        # Shamt for shift instructions (6 bits in RV64I)
        shamt_targets = ['shamt', 'slli_shamt', 'srli_shamt', 'srai_shamt',
                        'slliw_shamt', 'sllw_shamt', 'srlw_shamt', 'sraw_shamt']
        for shamt_src in ['instr[25:20]', 'instr[24:20]']:
            for shamt_tgt in shamt_targets:
                eid = find_edge(shamt_src, shamt_tgt)
                if eid:
                    cuts[execute_stage].append(eid)
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] {shamt_src} -> {shamt_tgt}")

        # Combined enables
        for eid, tgt in find_edges_from('rf_rd_ne_0_guarded_enable'):
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] rf_rd_ne_0_guarded_enable -> {tgt}")

        for eid, tgt in find_edges_from('umem_write_enable'):
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] umem_write_enable -> {tgt}")

    # For 2-stage or other combined pipelines
    elif execute_stage == decode_stage:
        # Execute is combined with Decode or later - skip separate cut
        pass

    # ========================================
    # CUT 3: X/M - Execute / Memory
    # ========================================
    # This cut is present in 5-stage pipelines ONLY (where Memory and Writeback are separate)
    # For 4-stage, memory_stage == writeback_stage, so this condition is false
    if memory_stage in cuts and memory_stage != execute_stage and memory_stage != writeback_stage:
        print(f"\nCUT 3: {execute_stage} -> {memory_stage}")
        print("-" * 50)

        # Memory addresses — discover dynamically to support both Python merger
        # (shared 'lb_addr'/'sb_addr') and Rust merger (per-instruction addresses)
        mem_addr_nodes = set()
        for node_id in graph.nodes:
            if node_id.endswith('_addr'):
                for eid, tgt in find_edges_from(node_id):
                    if 'umem' in tgt:
                        mem_addr_nodes.add(node_id)
        for addr_node in sorted(mem_addr_nodes):
            for eid, tgt in find_edges_from(addr_node):
                if 'umem' in tgt and not tgt.endswith('_byte_offset') and not tgt.endswith('_halfword_select') and not tgt.endswith('_word_select'):
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {addr_node} -> {tgt} (memory address)")

        # Byte offset nodes - dynamically find nodes that handle byte/halfword/word selection
        # These are created by memory_access_transform and have specific suffixes
        # Skip instruction fetch related nodes (umem_pc_rd_*) - they operate in Fetch stage
        for node_id, node in graph.nodes.items():
            # Skip instruction fetch byte selection (operates in Fetch, not Memory)
            if 'umem_pc_rd' in node_id:
                continue

            # Match nodes by suffix pattern (structural approach)
            is_byte_offset = node_id.endswith('_byte_offset')
            is_halfword_select = node_id.endswith('_halfword_select')
            is_word_select = node_id.endswith('_word_select')

            if is_byte_offset or is_halfword_select or is_word_select:
                for eid, tgt in find_edges_from(node_id):
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {node_id} -> {tgt} (byte selection offset)")

        # ALU results going to writeback mux (includes RV64I *w operations)
        alu_results = [
            'add_res', 'sub_res', 'and_res', 'or_res', 'xor_res',
            'sll_res', 'srl_res', 'sra_res', 'slt_res', 'sltu_res',
            'addi_res', 'andi_res', 'ori_res', 'xori_res',
            'slli_res', 'srli_res', 'srai_res', 'slti_res', 'sltiu_res',
            'lui_res', 'auipc_res',
            # RV64I-specific word operations
            'addw_res', 'subw_res', 'addiw_res',
            'sllw_res', 'srlw_res', 'sraw_res',
            'slliw_res', 'srliw_res', 'sraiw_res',
        ]
        for res in alu_results:
            for eid, tgt in find_edges_from(res):
                if tgt == 'rf_write_data_mux':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {res} -> rf_write_data_mux")

        # Store data - handles both merged (r2) and split (add_r2/sd_r2) naming
        for eid, src in find_edges_from_suffix('r2', 'umem_write_data_mux'):
            cuts[memory_stage].append(eid)
            print(f"  [{execute_stage[0]}/{memory_stage[0]}] {src} -> umem_write_data_mux (store data)")

        # Store enables (includes RV64I sd) - cut to both umem_write_data_mux and umem_write_enable
        for store_enable in ['sb_enable', 'sh_enable', 'sw_enable', 'sd_enable']:
            for eid, tgt in find_edges_from(store_enable):
                if tgt == 'umem_write_data_mux':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_enable} -> {tgt} (store enable)")
                elif tgt == 'umem_write_enable':
                    # Also cut edges to umem guarded address enables
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_enable} -> {tgt} (store enable to guarded addr)")

        # Load enables - pipeline to Memory stage for memory stall detection
        # RV64I has additional load instructions: ld (doubleword), lwu (word unsigned)
        for load_enable in ['lb_enable', 'lh_enable', 'lw_enable', 'lbu_enable', 'lhu_enable', 'ld_enable', 'lwu_enable']:
            for eid, tgt in find_edges_from(load_enable):
                if tgt == 'umem_addr_rd_enable':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {load_enable} -> {tgt} (load enable)")

        # Store byte/halfword/word/doubleword data — discover dynamically
        # Rust merger may use r2[31:0] instead of sw_word_data for sw stores
        store_data_nodes = ['sb_byte_data', 'sh_halfword_data', 'sw_word_data', 'sd_doubleword_data', 'r2[31:0]']
        for store_data in store_data_nodes:
            for eid, tgt in find_edges_from(store_data):
                if tgt == 'umem_write_data_mux':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_data} -> {tgt} (store data)")

        # Store address to byte_enable/positioned_data nodes
        # In RV64I, sb/sh/sw are all subword stores (8/16/32 bits in 64-bit word)
        # Discover store address nodes dynamically
        for addr_node in sorted(mem_addr_nodes):
            for eid, tgt in find_edges_from(addr_node):
                if 'byte_enable' in tgt or 'positioned' in tgt or 'shift' in tgt:
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {addr_node} -> {tgt} (store address to byte enable)")

        # Store data to positioned_data nodes
        for store_data in store_data_nodes:
            for eid, tgt in find_edges_from(store_data):
                if 'zext' in tgt or 'positioned' in tgt:
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_data} -> {tgt} (store data to positioned_data)")

        # Propagate rd through Memory stage
        for eid, tgt in find_edges_from('rd'):
            if tgt in ['rf[rd]_wr', 'rf_shared_wr']:
                cuts[memory_stage].append(eid)
                print(f"  [{execute_stage[0]}/{memory_stage[0]}] rd -> {tgt} (propagate rd to Mem)")

        # Propagate enable signals to rf_write_data_mux
        for node_id in graph.nodes:
            if node_id.endswith('_enable') and not node_id.startswith('rf_rd_ne_0') and node_id != 'umem_write_enable':
                for eid, tgt in find_edges_from(node_id):
                    if tgt == 'rf_write_data_mux':
                        cuts[memory_stage].append(eid)
                        print(f"  [{execute_stage[0]}/{memory_stage[0]}] {node_id} -> {tgt} (propagate control)")

        # DON'T cut edges TO rf_rd_ne_0_guarded_enable - it's already been pipelined from Decode
        # Cut edges FROM rf_rd_ne_0_guarded_enable to continue pipelining the combined signal
        for eid, tgt in find_edges_from('rf_rd_ne_0_guarded_enable'):
            cuts[memory_stage].append(eid)
            print(f"  [{execute_stage[0]}/{memory_stage[0]}] rf_rd_ne_0_guarded_enable -> {tgt} (pipeline combined write enable)")

        # For 5-stage: umem_write_enable is computed IN Memory stage from pipelined store enables
        # It's used in Memory stage to write to umem, and doesn't need to be pipelined to Writeback
        # So DON'T cut edges FROM umem_write_enable here

        print(f"  NOTE: pc_wr_mux inputs stay in {execute_stage} stage")
        print(f"  NOTE: Branch conditions stay in {execute_stage} - branches resolve in {execute_stage} stage")

    # ========================================
    # CUT 4: M/W - Memory / Writeback
    # ========================================
    # This cut is present in 5-stage pipelines
    if writeback_stage in cuts and writeback_stage != memory_stage:
        print(f"\nCUT 4: {memory_stage} -> {writeback_stage}")
        print("-" * 50)

        # Memory read results (including 64-bit extension patterns for RV64I)
        # Note: After memory_access_transform, node names include instruction prefix (lb_, lw_, etc.)
        memory_results = [
            '{{24{byte_data[7]_rd}}, byte_data}',
            '{{16{halfword_data[15]_rd}}, halfword_data}',
            '{24\'b0, byte_data}',
            '{16\'b0, halfword_data}',
            'data',
            # RV64I-specific patterns (with instruction prefixes from merged graph)
            '{{56{byte_data[7]_rd}}, byte_data}',
            '{{48{halfword_data[15]_rd}}, halfword_data}',
            '{{32{lw_word_data[31]_rd}}, lw_word_data}',  # lw sign-extended
            '{56\'b0, byte_data}',
            '{48\'b0, halfword_data}',
            '{32\'b0, lwu_word_data}',  # lwu zero-extended
            'doubleword_data',
            # Also include the intermediate word data nodes themselves
            'lw_word_data',
            'lwu_word_data',
        ]
        for res in memory_results:
            for eid, tgt in find_edges_from(res):
                if tgt == 'rf_write_data_mux':
                    cuts[writeback_stage].append(eid)
                    print(f"  [{memory_stage[0]}/{writeback_stage[0]}] {res} -> rf_write_data_mux")

        # ALU results propagated to Writeback (includes RV64I *w operations)
        alu_results_for_wb = [
            'add_res', 'sub_res', 'and_res', 'or_res', 'xor_res',
            'sll_res', 'srl_res', 'sra_res', 'slt_res', 'sltu_res',
            'addi_res', 'andi_res', 'ori_res', 'xori_res',
            'slli_res', 'srli_res', 'srai_res', 'slti_res', 'sltiu_res',
            'lui_res', 'auipc_res',
            # RV64I-specific
            'addw_res', 'subw_res', 'addiw_res',
            'sllw_res', 'srlw_res', 'sraw_res',
            'slliw_res', 'srliw_res', 'sraiw_res',
        ]
        for res in alu_results_for_wb:
            for eid, tgt in find_edges_from(res):
                if tgt == 'rf_write_data_mux':
                    cuts[writeback_stage].append(eid)
                    print(f"  [{memory_stage[0]}/{writeback_stage[0]}] {res} -> rf_write_data_mux (propagate to WB)")

        # Propagate rd through Writeback
        for eid, tgt in find_edges_from('rd'):
            if tgt in ['rf[rd]_wr', 'rf_shared_wr']:
                cuts[writeback_stage].append(eid)
                print(f"  [{memory_stage[0]}/{writeback_stage[0]}] rd -> {tgt} (propagate rd to WB)")

        # Propagate enable signals to Writeback
        for node_id in graph.nodes:
            if node_id.endswith('_enable') and not node_id.startswith('rf_rd_ne_0') and node_id != 'umem_write_enable':
                for eid, tgt in find_edges_from(node_id):
                    if tgt == 'rf_write_data_mux':
                        cuts[writeback_stage].append(eid)
                        print(f"  [{memory_stage[0]}/{writeback_stage[0]}] {node_id} -> {tgt} (propagate control to WB)")

        # DON'T cut edges TO rf_rd_ne_0_guarded_enable - it's already been pipelined from Decode
        # Cut edges FROM rf_rd_ne_0_guarded_enable to continue pipelining the combined signal
        for eid, tgt in find_edges_from('rf_rd_ne_0_guarded_enable'):
            cuts[writeback_stage].append(eid)
            print(f"  [{memory_stage[0]}/{writeback_stage[0]}] rf_rd_ne_0_guarded_enable -> {tgt} (pipeline combined write enable)")

        # For 5-stage: umem_write_enable is computed and used in Memory stage (not Writeback)
        # So DON'T cut edges FROM umem_write_enable to Writeback

    # For 4-stage pipeline, Memory/Writeback is combined
    elif writeback_stage == memory_stage and memory_stage in cuts and memory_stage != execute_stage:
        # Memory/Writeback combined - handle in memory stage
        print(f"\nCUT 3: {execute_stage} -> {memory_stage} (Memory+Writeback combined)")
        print("-" * 50)

        # Memory addresses — discover dynamically
        mem_addr_nodes = set()
        for node_id in graph.nodes:
            if node_id.endswith('_addr'):
                for eid, tgt in find_edges_from(node_id):
                    if 'umem' in tgt:
                        mem_addr_nodes.add(node_id)
        for addr_node in sorted(mem_addr_nodes):
            for eid, tgt in find_edges_from(addr_node):
                if 'umem' in tgt and not tgt.endswith('_byte_offset') and not tgt.endswith('_halfword_select') and not tgt.endswith('_word_select'):
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {addr_node} -> {tgt}")

        # Byte offset nodes - dynamically find nodes that handle byte/halfword/word selection
        # Skip instruction fetch related nodes (umem_pc_rd_*) - they operate in Fetch stage
        for node_id, node in graph.nodes.items():
            # Skip instruction fetch byte selection (operates in Fetch, not Memory)
            if 'umem_pc_rd' in node_id:
                continue

            is_byte_offset = node_id.endswith('_byte_offset')
            is_halfword_select = node_id.endswith('_halfword_select')
            is_word_select = node_id.endswith('_word_select')

            if is_byte_offset or is_halfword_select or is_word_select:
                for eid, tgt in find_edges_from(node_id):
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {node_id} -> {tgt}")

        # ALL results going to writeback mux (ALU + memory reads will be computed in this stage)
        all_results = [
            'add_res', 'sub_res', 'and_res', 'or_res', 'xor_res',
            'sll_res', 'srl_res', 'sra_res', 'slt_res', 'sltu_res',
            'addi_res', 'andi_res', 'ori_res', 'xori_res',
            'slli_res', 'srli_res', 'srai_res', 'slti_res', 'sltiu_res',
            'lui_res', 'auipc_res',
            # RV64I-specific
            'addw_res', 'subw_res', 'addiw_res',
            'sllw_res', 'srlw_res', 'sraw_res',
            'slliw_res', 'srliw_res', 'sraiw_res',
        ]
        for res in all_results:
            for eid, tgt in find_edges_from(res):
                if tgt == 'rf_write_data_mux':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {res} -> rf_write_data_mux")

        # Store data and control - handles both merged (r2) and split (add_r2/sd_r2) naming
        for eid, src in find_edges_from_suffix('r2', 'umem_write_data_mux'):
            cuts[memory_stage].append(eid)
            print(f"  [{execute_stage[0]}/{memory_stage[0]}] {src} -> umem_write_data_mux")

        # Store enables - cut to both umem_write_data_mux and umem_write_enable
        for store_enable in ['sb_enable', 'sh_enable', 'sw_enable', 'sd_enable']:
            for eid, tgt in find_edges_from(store_enable):
                if tgt == 'umem_write_data_mux':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_enable} -> {tgt} (store enable)")
                elif tgt == 'umem_write_enable':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_enable} -> {tgt} (store enable to guarded addr)")

        # Note: sw uses shared node 'r2[31:0]' instead of instruction-specific 'sw_word_data'
        for store_data in ['sb_byte_data', 'sh_halfword_data', 'sw_word_data', 'sd_doubleword_data', 'r2[31:0]']:
            for eid, tgt in find_edges_from(store_data):
                if tgt == 'umem_write_data_mux' or 'zext' in tgt or 'positioned' in tgt:
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_data} -> {tgt}")

        # Store address to byte_enable/positioned_data nodes
        # Discover store address nodes dynamically
        for addr_node in sorted(mem_addr_nodes):
            for eid, tgt in find_edges_from(addr_node):
                if 'byte_enable' in tgt or 'positioned' in tgt or 'shift' in tgt:
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {addr_node} -> {tgt}")

        # Propagate rd to Writeback (combined)
        for eid, tgt in find_edges_from('rd'):
            if tgt in ['rf[rd]_wr', 'rf_shared_wr']:
                cuts[memory_stage].append(eid)
                print(f"  [{execute_stage[0]}/{memory_stage[0]}] rd -> {tgt}")

        # Propagate enable signals
        for node_id in graph.nodes:
            if node_id.endswith('_enable') and not node_id.startswith('rf_rd_ne_0') and node_id != 'umem_write_enable':
                for eid, tgt in find_edges_from(node_id):
                    if tgt == 'rf_write_data_mux':
                        cuts[memory_stage].append(eid)
                        print(f"  [{execute_stage[0]}/{memory_stage[0]}] {node_id} -> {tgt}")

        # DON'T cut edges TO rf_rd_ne_0_guarded_enable - it's already been pipelined from Decode
        # Cut edges FROM rf_rd_ne_0_guarded_enable to continue pipelining the combined signal
        for eid, tgt in find_edges_from('rf_rd_ne_0_guarded_enable'):
            cuts[memory_stage].append(eid)
            print(f"  [{execute_stage[0]}/{memory_stage[0]}] rf_rd_ne_0_guarded_enable -> {tgt} (pipeline combined write enable)")

        # For 4-stage: umem_write_enable is computed and used in MemoryWriteback stage
        # So DON'T cut edges FROM umem_write_enable (no further pipelining needed)

    # For 2-stage pipeline, Fetch+Decode is combined and Execute+Memory+Writeback is combined
    # Only ONE cut: FetchDecode -> ExecuteMemoryWriteback
    if config.num_stages == 2:
        combined_stage = execute_stage  # This will be ExecuteMemoryWriteback
        print(f"\nCUT 1: FetchDecode -> {combined_stage} (single cut, 2-stage pipeline)")
        print("-" * 50)

        # Register file read values - pipeline them at FD/XMW boundary
        # Handles both merged (r1/r2) and split (add_r1/sd_r2) naming
        for eid, tgt in find_edges_to_suffix('rf[rs1]_rd', 'r1'):
            cuts[combined_stage].append(eid)
            print(f"  [FD/{combined_stage[0]}] rf[rs1]_rd -> {tgt}")

        for eid, tgt in find_edges_to_suffix('rf[rs2]_rd', 'r2'):
            cuts[combined_stage].append(eid)
            print(f"  [FD/{combined_stage[0]}] rf[rs2]_rd -> {tgt}")

        # Destination register index
        for eid, tgt in find_edges_from('rd'):
            if tgt != '(rd != 0)':
                cuts[combined_stage].append(eid)
                print(f"  [FD/{combined_stage[0]}] rd -> {tgt}")

        # PC for branch/jump calculations - needs to flow to XMW for branch target computation
        for eid, tgt in find_edges_from('pc_rd'):
            if '(pc +' in tgt and tgt != '(pc + 4)':
                cuts[combined_stage].append(eid)
                print(f"  [FD/{combined_stage[0]}] pc_rd -> {tgt}")

        # Sign-extended immediates — discover dynamically
        immediate_types = set()
        for node_id in graph.nodes:
            if node_id.endswith('_sign_ext_imm') or node_id == 'sign_ext_imm':
                immediate_types.add(node_id)
            elif node_id.endswith('_imm') and node_id in ('auipc_imm',):
                immediate_types.add(node_id)
        for imm_type in sorted(immediate_types):
            if imm_type in graph.nodes:
                for eid, src in find_edges_to(imm_type):
                    cuts[combined_stage].append(eid)
                    print(f"  [FD/{combined_stage[0]}] {src} -> {imm_type}")

        # JAL/JALR return address
        eid = find_edge('(pc + 4)', 'ret_addr')
        if eid:
            cuts[combined_stage].append(eid)
            print(f"  [FD/{combined_stage[0]}] (pc + 4) -> ret_addr")

        # All instruction enable signals
        for node_id in graph.nodes:
            if node_id.endswith('_enable') and not node_id.startswith('rf_rd_ne_0') and node_id != 'umem_write_enable':
                # Skip byte enables - computed at ExecuteMemoryWriteback stage from address, not FetchDecode
                # In RV64I: sb/sh/sw are all subword stores (sd is full-width)
                if node_id in ['sh_byte_enable', 'sb_byte_enable', 'sw_byte_enable', 'sd_byte_enable']:
                    print(f"  [FD/{combined_stage[0]}] SKIP {node_id} (byte enable computed at {combined_stage[0]} from address)")
                    continue
                for eid, tgt in find_edges_from(node_id):
                    if '_rd_enable' in tgt:
                        continue
                    # Skip edges to rf_rd_ne_0_enables - it's computed at Decode
                    if tgt == 'rf_rd_ne_0_enables':
                        print(f"  [FD/{combined_stage[0]}] SKIP {node_id} -> {tgt} (rf_rd_ne_0_enables stays at Decode)")
                        continue
                    # Skip edges to umem_write_enable - it's computed at Decode from D-stage enables
                    if tgt == 'umem_write_enable':
                        print(f"  [FD/{combined_stage[0]}] SKIP {node_id} -> {tgt} (umem_write_enable stays at Decode)")
                        continue
                    cuts[combined_stage].append(eid)
                    print(f"  [FD/{combined_stage[0]}] {node_id} -> {tgt}")

        # Shamt for shift instructions (6 bits in RV64I)
        # After merge, shamt becomes instruction-specific: slli_shamt, slliw_shamt, etc.
        shamt_targets = [
            'shamt',  # Original name
            'slli_shamt', 'srli_shamt', 'srai_shamt',  # RV64I immediate shifts
            'slliw_shamt',  # RV64I word immediate shifts
            'sllw_shamt', 'srlw_shamt', 'sraw_shamt',  # RV64I word register shifts
        ]
        for shamt_src in ['instr[25:20]', 'instr[24:20]']:
            for shamt_tgt in shamt_targets:
                eid = find_edge(shamt_src, shamt_tgt)
                if eid:
                    cuts[combined_stage].append(eid)
                    print(f"  [FD/{combined_stage[0]}] {shamt_src} -> {shamt_tgt}")

        # DON'T cut edges TO rf_rd_ne_0_guarded_enable - it stays at Decode
        # Cut edges FROM rf_rd_ne_0_guarded_enable to pipeline the combined signal
        for eid, tgt in find_edges_from('rf_rd_ne_0_guarded_enable'):
            cuts[combined_stage].append(eid)
            print(f"  [FD/{combined_stage[0]}] rf_rd_ne_0_guarded_enable -> {tgt} (pipeline combined write enable)")

        # Cut edges FROM umem_write_enable to pipeline the combined signal
        for eid, tgt in find_edges_from('umem_write_enable'):
            cuts[combined_stage].append(eid)
            print(f"  [FD/{combined_stage[0]}] umem_write_enable -> {tgt} (pipeline combined write enable)")

    # Summary
    print("\n" + "=" * 70)
    print("EDGE SELECTION SUMMARY")
    print("=" * 70)
    total = 0
    for stage, edges in cuts.items():
        print(f"{stage}: {len(edges)} edges")
        total += len(edges)
    print(f"Total: {total} edges")

    return cuts


def apply_pipeline_transforms(graph: ResourceGraph, cuts: dict, config: PipelineConfig):
    """Apply pipeline transformations to the graph.

    Returns (success, graph) — graph may be a new object (Rust engine) or the
    same object mutated in place (Python engine).
    """
    print("\n" + "=" * 70)
    print("APPLYING PIPELINE TRANSFORMATIONS")
    print("=" * 70)

    transform = PipelineTransform(graph)

    # Set explicit stage order for validity signal creation
    # This ensures correct pipeline ordering and validity signal pipe_time assignment
    stage_order = [cut.name for cut in config.cuts]
    stage_indices = {cut.name: cut.stage_index for cut in config.cuts}
    transform.set_stage_order(stage_order, stage_indices)
    print(f"  Using explicit stage order: {stage_order}")
    print(f"  Stage indices: {stage_indices}")

    # Build cut specifications using the actual stage order from config
    cut_specs = []
    for cut in config.cuts:
        stage_name = cut.name
        if stage_name in cuts and cuts[stage_name]:
            cut_specs.append({
                'edges': cuts[stage_name],
                'after_stage': stage_name,
                'stage_index': cut.stage_index  # Use stage_index as pipe_time
            })
            print(f"  Stage {stage_name}: {len(cuts[stage_name])} edges to cut (pipe_time={cut.stage_index})")

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

    # Rust engine: get updated graph back from transform
    if _engine == 'rust':
        graph = transform.get_graph()

    return success, graph


def apply_branch_prediction(graph: ResourceGraph, config: PipelineConfig):
    """
    Apply not-taken branch prediction optimization.

    Architectural design:
    - Fetch stage computes pc_add_4 = pc_rd + 4 speculatively
    - Branch resolution stage computes branch targets AND resolves branch conditions
    - Branch prediction: default to PC+4, flush on taken branches
    """
    print("\n" + "=" * 70)
    print("APPLYING BRANCH PREDICTION (NOT-TAKEN)")
    print("=" * 70)

    pc_node_id = 'pc_wr'
    pc_mux_id = 'pc_wr_mux'
    not_taken_input_id = 'pc_add_4'
    taken_input_id = 'jal_jump_dest'

    print(f"  Architectural specification:")
    print(f"    PC register: {pc_node_id}")
    print(f"    PC mux: {pc_mux_id}")
    print(f"    Not-taken path (speculative): {not_taken_input_id}")
    print(f"    Taken path (representative): {taken_input_id}")
    print(f"    Branch resolution stage: {config.branch_resolution_stage}")

    success = apply_branch_prediction_not_taken(
        graph,
        pc_node_id=pc_node_id,
        pc_mux_id=pc_mux_id,
        not_taken_input_id=not_taken_input_id,
        taken_input_id=taken_input_id
    )

    if success:
        print("\n Branch prediction applied successfully!")
    else:
        print("\n Branch prediction not applicable")

    return success


def apply_hazard_resolution(graph: ResourceGraph, config: PipelineConfig, strategy: str = 'stall'):
    """
    Analyze and resolve data hazards.

    Args:
        graph: The resource graph to resolve hazards in
        config: Pipeline configuration
        strategy: 'stall' for stalling or 'bypass' for forwarding/bypassing

    Returns:
        Tuple of (success, resolver) where resolver can be used for control hazards
    """
    print("\n" + "=" * 70)
    print("ANALYZING AND RESOLVING DATA HAZARDS")
    print("=" * 70)

    analyzer = HazardAnalyzer(graph, pc_name='pc')
    analyzer.identify_pipeline_stages()
    hazards = analyzer.analyze_hazards()

    if hazards:
        print(f"\nDetected {len(hazards)} data hazard(s):")
        if _engine == 'rust':
            # Rust returns dicts from analyze_hazards
            for i, hazard in enumerate(hazards):
                print(f"  {i+1}. {hazard['write_access_node_id']} -> {hazard['read_access_node_id']}")
                print(f"     Write at stage {hazard['write_stage']} ({hazard['write_stage_name']})")
                print(f"     Read at stage {hazard['read_stage']} ({hazard['read_stage_name']})")
                print(f"     Hazard distance: {hazard['forwarding_distance']}")
        else:
            for i, hazard in enumerate(hazards):
                print(f"  {i+1}. {hazard.write_access_node.id} -> {hazard.read_access_node.id}")
                print(f"     Write at stage {hazard.write_stage} ({hazard.write_stage_name})")
                print(f"     Read at stage {hazard.read_stage} ({hazard.read_stage_name})")
                print(f"     Hazard distance: {hazard.get_forwarding_distance()}")

        # Designer specifies which ISA state elements to gate when stalling
        # PC is the main element that needs to be held during stalls
        resolver = HazardResolver(graph, isa_states_to_gate=['pc_rd'], pipeline_config=config)

        if _engine == 'rust':
            # Rust resolver takes strategy as a string argument
            success = resolver.resolve_all_hazards(hazards, strategy=strategy)
        else:
            resolution_strategy = HazardResolutionStrategy.BYPASS if strategy == 'bypass' else HazardResolutionStrategy.STALL
            for hazard in hazards:
                hazard.resolution = resolution_strategy
            success = resolver.resolve_all_hazards(hazards)

        return success, resolver
    else:
        print("No hazards detected by analyzer (expected for merged graphs)")
        resolver = HazardResolver(graph, isa_states_to_gate=['pc_rd'], pipeline_config=config)
        return True, resolver


def generate_pipelined_rtl(graph: ResourceGraph, backend: str, output_dir: str, config: PipelineConfig, hazard_strategy: str = 'stall', no_verify: bool = False, write_read_fwd: bool = False):
    """Generate RTL code for the pipelined processor with specified backend."""
    print("\n" + "=" * 70)
    print(f"GENERATING {backend.upper()} TO {output_dir}")
    print("=" * 70)

    os.makedirs(output_dir, exist_ok=True)

    # Use stage count and hazard strategy in module name for differentiation
    suffix = "_bypass" if hazard_strategy == 'bypass' else ""
    if write_read_fwd:
        suffix += "_wrf"
    module_name = f"riscv64i_pipelined_{config.num_stages}stage{suffix}"

    if backend == 'verilog':
        generator = VerilogGenerator(graph, module_name=module_name)
        verilog_code = generator.generate()

        verilog_file = os.path.join(output_dir, f"{module_name}.v")
        with open(verilog_file, 'w') as f:
            f.write(verilog_code)

        print(f"  Generated: {verilog_file}")
        print(f"  Lines: {len(verilog_code.splitlines())}")
        
        return verilog_file, module_name
        
    elif backend == 'vhdl':
        from backends.vhdl import generate_vhdl
        
        vhdl_code = generate_vhdl(graph, entity_name=module_name)
        
        vhdl_file = os.path.join(output_dir, f"{module_name}.vhd")
        with open(vhdl_file, 'w') as f:
            f.write(vhdl_code)
        
        print(f"  Generated: {vhdl_file}")
        print(f"  Lines: {len(vhdl_code.splitlines())}")
        
        return vhdl_file, module_name
        
    elif backend == 'pyrtl':
        import pyrtl
        from backends.pyrtl import generate_pyrtl as gen_pyrtl, generate_pyrtl_testbench_files, PyRTLTestbenchConfig
        from pathlib import Path

        # Generate PyRTL design
        pyrtl_block = gen_pyrtl(graph, module_name)

        # Create testbench configuration
        # Use larger memory sizes for RV64 (16384 to ensure sufficient space)
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
            instructions=RV64I_INSTRUCTIONS,
            arch='riscv64'
        )

        # Also output the PyRTL block as Verilog for debugging and synthesis compatibility
        verilog_file = output_path / f"{module_name}.v"
        with open(verilog_file, 'w') as f:
            pyrtl.output_to_verilog(f, block=pyrtl_block)
        files['verilog'] = verilog_file

        print(f"  Generated PyRTL design:")
        print(f"    {len(list(pyrtl_block.logic))} logic operations")
        print(f"    {len(list(pyrtl_block.wirevector_set))} wires")
        print(f"    {len(pyrtl_block.memblock_by_name)} memories")
        print(f"  Exported to Verilog: {verilog_file}")
        print(f"  Generated testbench: {files.get('testbench')}")
        print(f"  Generated test runner: {files.get('test_runner')}")

        return str(verilog_file), module_name

    elif backend == 'circt':
        from pathlib import Path
        from backends.circt.circt_generator import generate_circt as gen_circt_mlir
        from backends.circt.circt_testbench import generate_circt_testbench

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        mlir_output = gen_circt_mlir(graph, module_name)
        mlir_file = output_path / f'{module_name}.mlir'
        with open(mlir_file, 'w') as f:
            f.write(mlir_output)
        print(f"  Generated MLIR: {mlir_file} ({len(mlir_output)} bytes)")

        firtool_path = shutil.which('firtool')
        if firtool_path is None:
            raise RuntimeError("firtool not found in PATH. Please install CIRCT.")

        import subprocess
        sv_file = output_path / f'{module_name}.sv'
        result = subprocess.run(
            [firtool_path, str(mlir_file), '-o', str(sv_file)],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            with open(sv_file, 'r') as f:
                content = f.read()
            content = re.sub(r'reg\s+\[(\d+):0\]\[(\d+):0\]\s+umem;', r'reg [\2:0] umem [0:\1];', content)
            with open(sv_file, 'w') as f:
                f.write(content)
            print(f"  Generated SystemVerilog: {sv_file}")
            print("  Post-processed for Verilator compatibility")

            tb_files = generate_circt_testbench(str(sv_file), module_name, 'riscv64', RV64I_INSTRUCTIONS)
            print(f"  Generated testbench: {tb_files.get('testbench')}")
            print(f"  Generated test runner: {tb_files.get('test_runner')}")
        else:
            print(f"  firtool failed: {result.stderr[:200]}")

        return str(sv_file), module_name

    elif backend == 'chisel':
        from pathlib import Path
        from backends.chisel import generate_chisel as gen_chisel

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Create src/main/scala directory structure
        scala_dir = output_path / "src" / "main" / "scala"
        scala_dir.mkdir(parents=True, exist_ok=True)

        # Generate Chisel Scala source
        scala_code = gen_chisel(graph, module_name)
        class_name = ''.join(p.capitalize() for p in module_name.replace('-', '_').split('_'))
        scala_file = scala_dir / f"{class_name}.scala"
        scala_file.write_text(scala_code)
        print(f"  Generated Scala: {scala_file} ({len(scala_code):,} bytes)")

        # Generate build.sbt
        build_sbt = output_path / "build.sbt"
        build_sbt.write_text(f"""ThisBuild / scalaVersion := "2.13.14"
lazy val root = (project in file("."))
  .settings(
    name := "{module_name}",
    libraryDependencies ++= Seq("org.chipsalliance" %% "chisel" % "6.6.0"),
    scalacOptions ++= Seq("-language:reflectiveCalls", "-deprecation", "-feature", "-Xcheckinit"),
    addCompilerPlugin("org.chipsalliance" % "chisel-plugin" % "6.6.0" cross CrossVersion.full),
  )
""")
        project_dir = output_path / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "build.properties").write_text("sbt.version=1.10.7\n")
        print(f"  Generated sbt build files")

        from backends.chisel.toolchain import (
            find_jars, download_jars, compile_scala, emit_firrtl, firrtl_to_verilog,
        )

        # Compile pipeline: Scala -> FIRRTL -> Verilog
        jar_dir = find_jars()
        if not jar_dir:
            print("  Chisel JARs not found, downloading from Maven Central...")
            jar_dir = download_jars(Path.home() / '.cache' / 'isacomp' / 'chisel_deps')

        verilog_file = str(output_path / f"{module_name}.v")

        if not list(jar_dir.glob('*.jar')):
            print("  ERROR: No Chisel JARs available, cannot compile")
            return str(scala_file), module_name

        classes_dir = output_path / "classes"
        try:
            print("  Compiling Scala with scalac...")
            compile_scala(scala_file, class_name, jar_dir, classes_dir)
            print("  Scala compilation successful")
        except Exception as e:
            print(f"  ERROR: Scala compilation failed: {e}")
            return str(scala_file), module_name

        firrtl_dir = output_path / "generated"
        try:
            firrtl_file = emit_firrtl(class_name, jar_dir, classes_dir, firrtl_dir)
        except Exception as e:
            print(f"  ERROR: FIRRTL emission failed: {e}")
            return str(scala_file), module_name

        try:
            print("  Converting FIRRTL to Verilog via firtool...")
            firrtl_to_verilog(firrtl_file, verilog_file)
            v_size = Path(verilog_file).stat().st_size
            print(f"  Generated Verilog: {verilog_file} ({v_size:,} bytes)")
        except Exception as e:
            print(f"  ERROR: firtool conversion failed: {e}")
            return str(scala_file), module_name

        return verilog_file, module_name

    elif backend == 'sim-cpp':
        from pathlib import Path
        from backends.sim_cpp import generate_cpp_sim as gen_cpp_sim

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Generate C++ simulation code
        cpp_code = gen_cpp_sim(graph, module_name)

        # Write header file
        header_file = output_path / f"{module_name}.hpp"
        header_file.write_text(cpp_code)
        print(f"  Generated C++ header: {header_file} ({len(cpp_code)} bytes)")

        # Generate testbench
        testbench_code = generate_cpp_testbench_for_pipelined_rv64(module_name, config.num_stages)
        tb_file = output_path / f"{module_name}_tb.cpp"
        tb_file.write_text(testbench_code)
        print(f"  Generated testbench: {tb_file}")

        # Generate Makefile
        makefile_code = generate_cpp_makefile_for_pipelined_rv64(module_name)
        makefile = output_path / "Makefile"
        makefile.write_text(makefile_code)
        print(f"  Generated Makefile: {makefile}")

        # Generate test runner script
        test_script = generate_cpp_test_script_for_pipelined_rv64(module_name)
        script_file = output_path / "run_all_tests.sh"
        script_file.write_text(test_script)
        script_file.chmod(0o755)
        print(f"  Generated test script: {script_file}")

        return str(header_file), module_name


def _generate_chisel_testbench_64(tb_file, module_name, class_name, pipelined=False,
                                  num_stages=5, verilog_path=None):
    """Generate a 64-bit SystemVerilog testbench for Chisel-generated Verilog.

    Mirrors _generate_chisel_testbench from generate_riscv32i_complete.py but
    adapted for 64-bit data/address widths used by RV64I.
    """
    from pathlib import Path
    import re as _re

    if pipelined:
        # Try auto-detecting signal names from generated Verilog
        exec_pc_sig = None
        exec_valid_sig = None

        if verilog_path and Path(verilog_path).exists():
            verilog_text = Path(verilog_path).read_text()
            pc_matches = _re.findall(r'\b(pIPE_\w*pc_rd\w*PIPE\w*)\b', verilog_text)
            if pc_matches:
                best = max(set(pc_matches), key=lambda s: s.count('_PIPE'))
                exec_pc_sig = best
            valid_matches = _re.findall(r'\b(pIPE_\w+_valid_PIPE)\b', verilog_text)
            if valid_matches:
                for candidate in sorted(set(valid_matches)):
                    if 'Execute' in candidate:
                        exec_valid_sig = candidate
                        break
                if not exec_valid_sig and valid_matches:
                    exec_valid_sig = sorted(set(valid_matches))[0]

        # Fall back to construction from num_stages
        if not exec_pc_sig or not exec_valid_sig:
            if num_stages >= 4:
                exec_stage = "Execute"
                decode_stage = "Decode"
            elif num_stages == 3:
                exec_stage = "ExecuteMemoryWriteback"
                decode_stage = "Decode"
            else:
                exec_stage = "ExecuteMemoryWriteback"
                decode_stage = "FetchDecode"

            if not exec_pc_sig:
                exec_pc_sig = f"pIPE_{exec_stage}_PIPE_{decode_stage}_pc_rd_PIPE_PIPE"
            if not exec_valid_sig:
                exec_valid_sig = f"pIPE_{exec_stage}_valid_PIPE"

        pass_fail_check = f"""\
    wire [63:0] exec_pc = dut.{exec_pc_sig};
    wire exec_valid = dut.{exec_valid_sig};
    wire exec_at_pass = exec_valid && (exec_pc == pass_addr);
    wire exec_at_fail = exec_valid && (exec_pc == fail_addr);"""
        pass_cond = "exec_at_pass"
        fail_cond = "exec_at_fail"
    else:
        pass_fail_check = ""
        pass_cond = "dut.pc == pass_addr"
        fail_cond = "dut.pc == fail_addr"

    tb = f"""`timescale 1ns/1ps
module simple_tb;
    reg clk, reset_s;

    {class_name} dut (
        .clock(clk),
        .reset(reset_s),
        .io_pc_out()
    );

    reg [63:0] pass_addr, fail_addr;
    integer i;
    always #5 clk = ~clk;
{pass_fail_check}

    initial begin
        clk = 0; reset_s = 1;
        if (!$value$plusargs("pass_addr=%h", pass_addr)) pass_addr = 64'hFFFFFFFFFFFFFFFF;
        if (!$value$plusargs("fail_addr=%h", fail_addr)) fail_addr = 64'hFFFFFFFFFFFFFFFE;
        // firtool generates memory as a separate module instantiated as umem_ext
        $readmemh("umem.hex", dut.umem_ext.Memory);
        // Initialize register file (firtool extracts Mem to separate module)
        for (i = 0; i < 32; i = i + 1) dut.rf_ext.Memory[i] = 64'h0;
        repeat(3) @(posedge clk);
        reset_s = 0;
        for (i = 0; i < 10000; i = i + 1) begin
            @(posedge clk);
            if ({pass_cond}) begin $display("TEST PASSED"); $finish; end
            if ({fail_cond}) begin
                $display("TEST FAILED at pc=%h testnum=%d", dut.pc, dut.rf_ext.Memory[3]);
                $finish;
            end
        end
        $display("TIMEOUT");
        $finish;
    end
endmodule
"""
    Path(tb_file).write_text(tb)


def _generate_chisel_test_runner_64(runner_file, module_name):
    """Generate a test runner script for RV64I riscv-tests on Chisel Verilog."""
    # RV64I test list (base + loads/stores + word ops)
    tests_base = "add addi sub lui auipc and andi or ori xor xori sll slli srl srli sra srai slt slti sltu sltiu beq bne blt bltu bge bgeu jal jalr"
    tests_mem = "lw lh lhu lb lbu lwu ld sw sh sb sd"
    tests_word = "addiw slliw srliw sraiw addw subw sllw srlw sraw"

    script = f"""#!/bin/bash
# Test all RV64I instructions using Chisel-generated Verilog
# Usage: ./run_all_tests.sh

SIMULATOR=${{SIMULATOR:-iverilog}}

echo "Compiling Chisel-generated Verilog testbench with $SIMULATOR..."

if [ "$SIMULATOR" = "verilator" ]; then
    if [ ! -f "test_simple" ] || [ "{module_name}.v" -nt "test_simple" ] || [ "simple_tb.sv" -nt "test_simple" ]; then
        verilator --timing --exe --binary \\
            -Wno-fatal -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-TIMESCALEMOD \\
            -o test_simple {module_name}.v simple_tb.sv
        if [ $? -ne 0 ]; then echo "ERROR: Verilator compilation failed!"; exit 1; fi
        # Move binary from obj_dir and ensure it exists
        if ! mv obj_dir/test_simple . 2>/dev/null; then
            echo "ERROR: Failed to move Verilator sim binary from obj_dir/test_simple"
            exit 1
        fi
        if [ ! -x "./test_simple" ]; then
            echo "ERROR: Verilator sim binary './test_simple' not found or not executable"
            exit 1
        fi
    fi
    TEST_CMD="./test_simple"
else
    if [ ! -f "test_simple" ] || [ "{module_name}.v" -nt "test_simple" ] || [ "simple_tb.sv" -nt "test_simple" ]; then
        iverilog -g2012 -DSYNTHESIS -o test_simple {module_name}.v simple_tb.sv
        if [ $? -ne 0 ]; then echo "ERROR: Icarus Verilog compilation failed!"; exit 1; fi
    fi
    TEST_CMD="vvp test_simple"
fi

TESTS="{tests_base} {tests_mem} {tests_word}"

PASS=0
FAIL=0
SKIP=0

for test in $TESTS; do
    echo -n "Testing $test... "

    TEST_BASE="../../../isa/riscv64/riscv-tests/isa/rv64ui-isacomp-$test"

    if [ ! -f "$TEST_BASE.hex" ]; then
        echo "SKIP (no hex file)"
        SKIP=$((SKIP + 1))
        continue
    fi

    if [ ! -f "$TEST_BASE.addrs" ]; then
        echo "SKIP (no addrs file)"
        SKIP=$((SKIP + 1))
        continue
    fi

    read PASS_ADDR FAIL_ADDR < "$TEST_BASE.addrs"

    python3 -c "
import sys
data = {{}}
with open('$TEST_BASE.hex', 'r') as f:
    for line in f:
        line = line.strip()
        if not line.startswith(':'):
            continue
        byte_count = int(line[1:3], 16)
        address = int(line[3:7], 16)
        record_type = int(line[7:9], 16)
        if record_type == 0:
            for i in range(byte_count):
                byte_val = int(line[9+i*2:11+i*2], 16)
                data[address + i] = byte_val
        elif record_type == 1:
            break
if not data:
    sys.exit(1)
# Write umem (64-bit words, 8 bytes each)
with open('umem.hex', 'w') as f:
    for word_idx in range(8192):
        word = 0
        for byte_offset in range(8):
            addr = word_idx * 8 + byte_offset
            if addr in data:
                word |= data[addr] << (byte_offset * 8)
        f.write(f'{{word:016x}}\\n')
"

    RESULT=$(timeout 5 $TEST_CMD +pass_addr=$PASS_ADDR +fail_addr=$FAIL_ADDR 2>&1)
    EXIT_CODE=$?

    if echo "$RESULT" | grep -q "TEST PASSED"; then
        echo "PASS"
        PASS=$((PASS + 1))
    elif echo "$RESULT" | grep -q "TEST FAILED"; then
        echo "FAIL"
        FAIL=$((FAIL + 1))
    elif [ $EXIT_CODE -eq 124 ]; then
        echo "TIMEOUT"
        FAIL=$((FAIL + 1))
    else
        echo "ERROR"
        FAIL=$((FAIL + 1))
    fi
done

echo ""
echo "================================"
echo "Results: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
echo "================================"

if [ $FAIL -gt 0 ]; then
    echo "FAILED: $FAIL test(s) failed"
    exit 1
fi

if [ $PASS -eq 0 ]; then
    echo "FAILED: No tests passed (all skipped)"
    exit 1
fi

echo "SUCCESS: All $PASS tests passed"
exit 0
"""
    from pathlib import Path
    Path(runner_file).write_text(script)
    Path(runner_file).chmod(0o755)


def _generate_rv64_benchmark_script(output_path: str):
    """Generate run_benchmarks.sh for RV64I processors."""
    script = r'''#!/bin/bash

# Run RISC-V benchmarks on ISAComp RV64I pipelined processor
# Uses the same testbench as ISA tests, with +max_cycles for longer timeout
# Set SIMULATOR=verilator to use Verilator instead of Icarus Verilog

SIMULATOR=${SIMULATOR:-iverilog}

echo "Running RV64I benchmarks with $SIMULATOR..."

DIR_NAME=$(basename "$PWD")
VERILOG_FILE="${DIR_NAME}.v"
TB_FILE="simple_tb_new.sv"

if [ ! -f "$VERILOG_FILE" ]; then
    echo "ERROR: Verilog file '$VERILOG_FILE' not found!"
    exit 1
fi
if [ ! -f "$TB_FILE" ]; then
    echo "ERROR: Testbench '$TB_FILE' not found! Run the pipeline generator first."
    exit 1
fi

if [ "$SIMULATOR" = "verilator" ]; then
    if [ ! -f "bench_sim" ] || [ "$VERILOG_FILE" -nt "bench_sim" ] || [ "$TB_FILE" -nt "bench_sim" ]; then
        verilator --timing --exe --binary \
            -Wno-fatal -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-TIMESCALEMOD \
            -o bench_sim "$VERILOG_FILE" "$TB_FILE"
        if [ $? -ne 0 ]; then echo "ERROR: Verilator compilation failed!"; exit 1; fi
        mv obj_dir/bench_sim . 2>/dev/null || true
    fi
    TEST_CMD="./bench_sim"
else
    if [ ! -f "bench_sim" ] || [ "$VERILOG_FILE" -nt "bench_sim" ] || [ "$TB_FILE" -nt "bench_sim" ]; then
        iverilog -g2012 -o bench_sim "$VERILOG_FILE" "$TB_FILE"
        if [ $? -ne 0 ]; then echo "ERROR: Compilation failed!"; exit 1; fi
    fi
    TEST_CMD="vvp bench_sim"
fi

python3 -c "
with open('rf.hex', 'w') as f:
    for i in range(32):
        f.write('0000000000000000\n')
"

BENCHMARKS="median memcpy multiply qsort rsort towers vvadd"
PASS=0; FAIL=0; SKIP=0; FAILED_TESTS=""; TOTAL_CYCLES=0

for bench in $BENCHMARKS; do
    echo -n "Benchmark $bench... "
    BENCH_BASE="../../../riscv-tests/benchmarks/$bench"

    if [ ! -f "$BENCH_BASE.hex" ]; then
        echo "SKIP (no hex file - run build_riscv_benchmarks.sh first)"
        SKIP=$((SKIP + 1)); continue
    fi
    if [ ! -f "$BENCH_BASE.addrs" ]; then
        echo "SKIP (no addrs file)"
        SKIP=$((SKIP + 1)); continue
    fi

    read PASS_ADDR FAIL_ADDR < "$BENCH_BASE.addrs"

    python3 -c "
import sys
data = []
with open('$BENCH_BASE.hex', 'r') as f:
    for line in f:
        line = line.strip()
        if line: data.append(int(line, 16))
if not data: sys.exit(1)
if len(data) > 8192 * 8:
    print(f'ERROR: benchmark too large ({len(data)} bytes > {8192*8} byte memory)', file=sys.stderr)
    sys.exit(1)
with open('umem.hex', 'w') as f:
    for dword_idx in range(8192):
        dword = 0; addr = dword_idx * 8
        for byte_offset in range(8):
            byte_addr = addr + byte_offset
            if byte_addr < len(data): dword |= data[byte_addr] << (byte_offset * 8)
        f.write(f'{dword:016x}\n')
"

    RESULT=$(timeout 600 $TEST_CMD +pass_addr=$PASS_ADDR +fail_addr=$FAIL_ADDR +max_cycles=10000000 2>&1)
    EXIT_CODE=$?

    if echo "$RESULT" | grep -q "TEST PASSED"; then
        CYCLES=$(echo "$RESULT" | grep "TEST PASSED" | sed 's/.*in \([0-9]*\) cycles.*/\1/')
        if [ -n "$CYCLES" ]; then
            echo "PASS ($CYCLES cycles)"; TOTAL_CYCLES=$((TOTAL_CYCLES + CYCLES))
        else echo "PASS"; fi
        PASS=$((PASS + 1))
    elif echo "$RESULT" | grep -q "TEST FAILED"; then
        echo "FAIL"; FAIL=$((FAIL + 1)); FAILED_TESTS="$FAILED_TESTS $bench"
    elif [ $EXIT_CODE -eq 124 ]; then
        echo "TIMEOUT"; FAIL=$((FAIL + 1)); FAILED_TESTS="$FAILED_TESTS $bench"
    else
        echo "ERROR"; FAIL=$((FAIL + 1)); FAILED_TESTS="$FAILED_TESTS $bench"
    fi
done

echo ""
echo "================================"
echo "Results: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
if [ -n "$FAILED_TESTS" ]; then echo "Failed:$FAILED_TESTS"; fi
if [ $TOTAL_CYCLES -gt 0 ]; then echo "Total cycles: $TOTAL_CYCLES"; fi
echo "================================"

if [ $FAIL -gt 0 ]; then echo "FAILED: $FAIL benchmark(s) failed"; exit 1; fi
if [ $PASS -eq 0 ]; then echo "FAILED: No benchmarks passed (all skipped)"; exit 1; fi
echo "SUCCESS: All $PASS benchmarks passed"
'''
    with open(output_path, 'w') as f:
        f.write(script)
    import stat
    os.chmod(output_path, 0o755)


def main(num_stages: int = 5, hazard_strategy: str = 'stall', write_read_fwd: bool = False,
         mem_min_latency: int = 1, mem_max_latency: int = 1, backend: str = 'verilog',
         no_verify: bool = False, enable_ras: bool = False, ras_depth: int = 8):
    """Main pipeline creation function.

    Args:
        num_stages: Number of pipeline stages (2-5)
        hazard_strategy: 'stall' for stalling or 'bypass' for forwarding
        write_read_fwd: Enable write-to-read forwarding on register file
        mem_min_latency: Minimum memory latency cycles (default 1)
        mem_max_latency: Maximum memory latency cycles (default 1)
        backend: Output backend ('verilog', 'circt', 'pyrtl')
        no_verify: Skip verification for VHDL backend
        enable_ras: Enable Return Address Stack optimization
        ras_depth: RAS stack depth (default 8)
    """
    # Get pipeline configuration
    config = get_pipeline_config(num_stages)

    print("=" * 70)
    print(f"{num_stages}-STAGE PIPELINED RISC-V 64-BIT PROCESSOR ({backend.upper()} backend)")
    print(f"Stages: {' -> '.join(config.stage_names)}")
    print(f"Hazard Resolution: {hazard_strategy.upper()}")
    print(f"Write-Read Forwarding: {'ENABLED' if write_read_fwd else 'DISABLED'}")
    if mem_min_latency == mem_max_latency:
        print(f"Memory Latency: {mem_min_latency} cycles (static)")
    else:
        print(f"Memory Latency: {mem_min_latency}-{mem_max_latency} cycles (random)")
    print("=" * 70)

    # Step 1: Build merged graph
    graph = build_merged_graph()

    # Step 1.4: Apply write-read forwarding optimization if enabled
    mem_transform = MemoryAccessTransform(graph)
    if write_read_fwd:
        print("\n" + "=" * 70)
        print("APPLYING WRITE-READ FORWARDING OPTIMIZATION")
        print("=" * 70)
        result = mem_transform.enable_write_read_forwarding('rf')
        if result.get('enabled'):
            print(f"  Write-read forwarding enabled on rf")
        else:
            print(f"  Failed to enable: {result.get('reason', 'unknown')}")

    # Step 1.5: Apply memory port width transformation
    # RV64I uses 64-bit data path, so we transform to 64-bit port width
    print("\n" + "=" * 70)
    print("APPLYING MEMORY PORT WIDTH TRANSFORMATION")
    print("=" * 70)
    umem_spec = MemoryAccessTransformSpec(
        memory='umem',
        strategy='set_port_width',
        current_width=8,
        target_width=64,
        direction='forward'
    )
    result = mem_transform.apply_transformation(umem_spec)
    if _engine == 'rust':
        # Rust MemoryAccessTransform takes ownership — get updated graph back
        graph = mem_transform.get_graph()
    if result.get('transformed'):
        print(f"  Memory transformation successful: {result.get('num_accesses_transformed', 0)} accesses transformed")
    else:
        print(f"  Memory transformation skipped: {result.get('reason', 'unknown')}")

    # Step 1.6: Set umem to variable latency
    print("\n" + "=" * 70)
    print("SETTING UMEM TO VARIABLE LATENCY")
    print("=" * 70)
    success = set_memory_variable_latency(graph, 'umem', enable=True,
                                          min_latency=mem_min_latency,
                                          max_latency=mem_max_latency)
    if success:
        print("  umem configured for variable latency")
    else:
        print("  WARNING: Failed to set umem variable latency")

    # Step 2: Select pipeline cut edges
    cuts = select_pipeline_cut_edges_generic(graph, config)

    # Step 3: Apply pipeline transformations
    success, graph = apply_pipeline_transforms(graph, cuts, config)

    if not success:
        print("\nPipeline transformation failed. Exiting.")
        return None

    # Step 3.5: Wire variable latency memory signals BEFORE hazard resolution
    # This creates the validity-gated access enable signals that hazard resolution needs
    print("\n" + "=" * 70)
    print("WIRING VARIABLE LATENCY MEMORY SIGNALS")
    print("=" * 70)
    if wire_memory_start_signal(graph, 'umem'):
        print("  umem start signal wired")
    else:
        print("  WARNING: Could not wire umem start signal")

    # Step 4: Apply hazard resolution
    # Note: Memory latency stalls are automatically added by resolve_all_hazards()
    # via _add_automatic_memory_latency_stalls() which ORs the memory stall condition
    # into the existing Decode stall controller.
    success, resolver = apply_hazard_resolution(graph, config, strategy=hazard_strategy)

    # Step 5: Add control hazard handling
    # RISC-V conditional branches and their condition signals
    branch_conditions = {
        'beq': 'beq_res',
        'bne': 'bne_res',
        'blt': 'blt_res',
        'bge': 'bge_res',
        'bltu': 'bltu_res',
        'bgeu': 'bgeu_res'
    }
    # RISC-V unconditional jumps (always cause flush when enabled)
    jump_types = ['jal', 'jalr']
    resolver.add_control_hazard_handling(branch_conditions=branch_conditions, jump_types=jump_types, pc_mux_id='pc_wr_mux')

    # Step 6: Gate write enables with validity signals
    resolver.gate_write_enables_with_validity()

    # Rust engine: get updated graph back from resolver
    if _engine == 'rust':
        graph = resolver.get_graph()

    # Step 7: Apply branch prediction
    apply_branch_prediction(graph, config)

    # Step 7.5: Apply Return Address Stack (RAS) optimization (if enabled)
    # Must run AFTER branch prediction so predicted_pc exists
    if enable_ras and apply_return_address_stack is None:
        print(f"\n  WARNING: --ras not supported with {_engine} engine, skipping")
        enable_ras = False
    if enable_ras:
        print("\n" + "=" * 70)
        print("APPLYING RETURN ADDRESS STACK (RAS) OPTIMIZATION")
        print("=" * 70)

        # Find the default prediction node (PC+4) - created by branch prediction
        default_prediction_id = None
        for name in ['(pc + 4)', 'pc_add_4', 'pc_plus_4']:
            if name in graph.nodes:
                default_prediction_id = name
                break
        if not default_prediction_id:
            print("  ERROR: Could not find PC+4 node for RAS")
            print("  Skipping RAS optimization")
        else:
            # Use Decode stage for call/return detection (all signals from same instruction)
            # and PIPE_Decode_pc_add_4_PIPE for the return address (PC+4 of the call instruction)
            #
            # When JAL/JALR is being decoded (jal_enable/jalr_enable are high):
            # - PIPE_Decode_pc_add_4_PIPE contains that instruction's PC+4
            # This is cleaner than mixing pipeline stages

            ras_spec = RASSpec(
                call_specs=[
                    # JAL can be a call when rd is a link register
                    CallSpec(
                        enable_node_id='jal_enable',
                        dest_reg_node_id='rd',
                        return_addr_node_id='PIPE_Decode_pc_add_4_PIPE'
                    ),
                    # JALR can be a call when rd is a link register
                    CallSpec(
                        enable_node_id='jalr_enable',
                        dest_reg_node_id='rd',
                        return_addr_node_id='PIPE_Decode_pc_add_4_PIPE'
                    ),
                ],
                return_specs=[
                    # JALR is a return when rs1 is a link register and rd is x0
                    ReturnSpec(
                        enable_node_id='jalr_enable',
                        src_reg_node_id='rs1',
                        dest_reg_node_id='rd'
                    ),
                ],
                link_registers=[1, 5],  # x1 (ra) and x5 (t0) are link registers
                ras_depth=ras_depth,
                ras_width=64,  # 64-bit addresses for RV64I
                predicted_pc_node_id='predicted_pc',
                default_prediction_node_id=default_prediction_id,
                control_hazard_flush_node_id='control_hazard_flush',
                jalr_target_node_id='jalr_jump_dest',
            )

            ras_success = apply_return_address_stack(graph, ras_spec)
            if ras_success:
                print("  RAS optimization applied successfully")
            else:
                print("  WARNING: RAS optimization could not be applied")

    # Step 7b: Re-infer timing after all graph modifications
    print("\nRe-inferring timing after hazard resolution and branch prediction...")
    graph.infer_uarch_time(force_reinfer=True)
    graph.infer_pipe_time(force_reinfer=True)

    # Step 8: Generate RTL with specified backend
    suffix = "_bypass" if hazard_strategy == 'bypass' else ""
    if write_read_fwd:
        suffix += "_wrf"
    if backend == 'circt':
        output_dir = os.path.join(_project_root, f"examples/verilog/circt_riscv64i_pipelined_{config.num_stages}stage{suffix}")
    elif backend == 'pyrtl':
        output_dir = os.path.join(_project_root, f"examples/pyrtl/riscv64i_pipelined_{config.num_stages}stage{suffix}")
    elif backend == 'chisel':
        output_dir = os.path.join(_project_root, f"examples/chisel/riscv64i_pipelined_{config.num_stages}stage{suffix}")
    elif backend == 'verilog':
        output_dir = os.path.join(_project_root, f"examples/verilog/riscv64i_pipelined_{config.num_stages}stage{suffix}")
    else:
        output_dir = os.path.join(_project_root, f"{backend}/riscv64i_pipelined_{config.num_stages}stage{suffix}")
    rtl_file, module_name = generate_pipelined_rtl(graph, backend, output_dir, config, hazard_strategy, no_verify, write_read_fwd)

    # Step 9: Save the pipelined graph
    graph.save_to_file(os.path.join(output_dir, f"{module_name}.rgraph"))
    print(f"\nSaved pipelined graph to {output_dir}/{module_name}.rgraph")

    # Step 10: Generate testbench (only for verilog backend for now)
    if backend == 'verilog':
        from isa.riscv64.generators.generate_testbench_64 import generate_testbench_64

        dst_tb = os.path.join(output_dir, "simple_tb_new.sv")
        generate_testbench_64(rtl_file, dst_tb)
        print(f"  Created testbench: {dst_tb}")

        # Copy test script with updated filenames
        src_script = os.path.join(_project_root, "examples/verilog/riscv64i_pipelined/run_riscv_tests.sh")
        if os.path.exists(src_script):
            with open(src_script, 'r') as f:
                script_content = f.read()
            script_content = script_content.replace('riscv64i_pipelined', module_name)
            dst_script = os.path.join(output_dir, "run_riscv_tests.sh")
            with open(dst_script, 'w') as f:
                f.write(script_content)
            os.chmod(dst_script, 0o755)
            print(f"  Created test script: {dst_script}")

        # Generate benchmark script
        dst_bench = os.path.join(output_dir, "run_benchmarks.sh")
        _generate_rv64_benchmark_script(dst_bench)
        print(f"  Created benchmark script: {dst_bench}")

    elif backend == 'chisel':
        from pathlib import Path

        output_path = Path(output_dir)
        class_name = ''.join(p.capitalize() for p in module_name.replace('-', '_').split('_'))

        tb_file = output_path / "simple_tb.sv"
        _generate_chisel_testbench_64(tb_file, module_name, class_name, pipelined=True,
                                      num_stages=config.num_stages, verilog_path=rtl_file)
        print(f"  Created testbench: {tb_file}")

        runner_file = output_path / "run_all_tests.sh"
        _generate_chisel_test_runner_64(runner_file, module_name)
        print(f"  Created test runner: {runner_file}")

    print("\n" + "=" * 70)
    print("PIPELINE CREATION COMPLETE")
    print("=" * 70)
    print(f"Generated files:")
    print(f"  - {rtl_file}")
    print(f"  - {output_dir}/{module_name}.rgraph")
    if backend == 'verilog':
        print(f"\nNext steps:")
        print(f"  cd {output_dir}")
        print(f"  ./run_riscv_tests.sh")
    elif backend == 'chisel':
        print(f"\nNext steps:")
        print(f"  cd {output_dir}")
        print(f"  bash run_all_tests.sh")
    else:
        print(f"\nNext steps:")
        print(f"  Review generated output in {output_dir}/")

    return graph


def generate_cpp_testbench_for_pipelined_rv64(module_name, num_stages=5):
    """Generate C++ testbench for pipelined RISC-V 64-bit simulation.

    Uses Execute stage PC and valid signals for pass/fail detection,
    matching the pattern used in Verilog testbenches.
    """
    # Determine Execute stage signal names based on pipeline depth
    if num_stages >= 4:
        exec_pc_getter = "get_PIPE_Execute_PIPE_Decode_pc_rd_PIPE_PIPE"
        exec_valid_getter = "get_PIPE_Execute_valid_PIPE"
    elif num_stages == 3:
        exec_pc_getter = "get_PIPE_ExecuteMemoryWriteback_PIPE_Decode_pc_rd_PIPE_PIPE"
        exec_valid_getter = "get_PIPE_ExecuteMemoryWriteback_valid_PIPE"
    else:  # 2 stages - FetchDecode -> ExecuteMemoryWriteback, PC comes directly from pc_rd
        exec_pc_getter = "get_PIPE_ExecuteMemoryWriteback_pc_rd_PIPE"
        exec_valid_getter = "get_PIPE_ExecuteMemoryWriteback_valid_PIPE"

    return f'''// C++ Testbench for {module_name}
// Compatible with riscv-tests suite (RV64I)

#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <cstdlib>
#include <cstdint>
#include <vector>
#include "{module_name}.hpp"

// Load unified memory hex file (doubleword-addressed for RV64, little-endian)
bool load_umem_hex(const std::string& filename, {module_name}& cpu) {{
    std::ifstream file(filename);
    if (!file) {{
        std::cerr << "Error: Cannot open " << filename << std::endl;
        return false;
    }}

    std::string line;
    size_t addr = 0;
    while (std::getline(file, line) && addr < 16384) {{
        if (line.empty() || line[0] == '/' || line[0] == '#') continue;
        uint64_t dword = std::stoull(line, nullptr, 16);
        cpu.write_umem(addr, dword);
        addr++;
    }}
    return true;
}}

int main(int argc, char* argv[]) {{
    // Parse command line arguments
    std::string hex_file = "umem.hex";
    uint64_t pass_addr = 0xFFFFFFFFFFFFFFFFULL;
    uint64_t fail_addr = 0xFFFFFFFFFFFFFFFEULL;
    uint64_t max_cycles = 50000;  // Higher for pipelined (more cycles per instruction)
    bool trace = false;

    for (int i = 1; i < argc; i++) {{
        std::string arg = argv[i];
        if (arg.substr(0, 11) == "+pass_addr=") {{
            pass_addr = std::stoull(arg.substr(11), nullptr, 16);
        }} else if (arg.substr(0, 11) == "+fail_addr=") {{
            fail_addr = std::stoull(arg.substr(11), nullptr, 16);
        }} else if (arg.substr(0, 12) == "+max_cycles=") {{
            max_cycles = std::stoull(arg.substr(12));
        }} else if (arg == "+trace") {{
            trace = true;
        }} else if (arg.substr(0, 10) == "+hex_file=") {{
            hex_file = arg.substr(10);
        }}
    }}

    // Create processor instance
    {module_name} cpu;
    cpu.reset();

    // Load program
    if (!load_umem_hex(hex_file, cpu)) {{
        std::cerr << "Failed to load " << hex_file << std::endl;
        return 1;
    }}

    // Run simulation
    // Use Execute stage PC and valid signal for pass/fail detection.
    // This matches the Verilog testbench approach - we check when an
    // instruction actually reaches the Execute stage, not just when fetched.
    for (uint64_t cycle = 0; cycle < max_cycles; cycle++) {{
        if (trace) {{
            cpu.dump_state();
        }}

        cpu.cycle();

        // Get Execute stage PC and valid signal
        uint64_t exec_pc = cpu.{exec_pc_getter}();
        uint8_t exec_valid = cpu.{exec_valid_getter}();

        // Check for pass/fail when instruction is valid in Execute stage
        if (exec_valid) {{
            if (exec_pc == pass_addr) {{
                std::cout << "TEST PASSED" << std::endl;
                return 0;
            }}
            if (exec_pc == fail_addr) {{
                // For riscv-tests, x28 (t3) contains the test number
                std::cout << "TEST FAILED at pc=0x" << std::hex << exec_pc;
                std::cout << " testnum=" << std::dec << cpu.read_rf(28) << std::endl;
                return 1;
            }}
        }}
    }}

    std::cout << "TIMEOUT" << std::endl;
    return 1;
}}
'''


def generate_cpp_makefile_for_pipelined_rv64(module_name):
    """Generate Makefile for C++ pipelined RISC-V 64-bit simulation."""
    return f'''# Makefile for {module_name} C++ simulation

CXX = g++
CXXFLAGS = -O3 -std=c++17 -Wall

all: {module_name}_sim

{module_name}_sim: {module_name}_tb.cpp {module_name}.hpp
\t$(CXX) $(CXXFLAGS) -o $@ {module_name}_tb.cpp

clean:
\trm -f {module_name}_sim umem.hex

.PHONY: all clean
'''


def generate_cpp_test_script_for_pipelined_rv64(module_name):
    """Generate test runner script for C++ pipelined RISC-V 64-bit simulation."""
    return f'''#!/bin/bash

# Test all RV64I instructions using pipelined C++ simulation
# This script mirrors run_all_tests.sh for the Verilog backend

echo "Building C++ simulation..."
make -s
if [ $? -ne 0 ]; then
    echo "ERROR: Compilation failed!"
    exit 1
fi

# RV64I tests - using rv32ui tests which are compatible with RV64 base integer
TESTS="add addi sub lui auipc and andi or ori xor xori sll slli srl srli sra srai slt slti sltu sltiu beq bne blt bltu bge bgeu jal jalr lw lh lhu lb lbu sw sh sb"

PASS=0
FAIL=0
SKIP=0

for test in $TESTS; do
    echo -n "Testing $test... "

    TEST_BASE="../../../isa/riscv64/riscv-tests/isa/rv32ui-isacomp-$test"

    if [ ! -f "$TEST_BASE.hex" ]; then
        echo "SKIP (no hex file)"
        SKIP=$((SKIP + 1))
        continue
    fi

    if [ ! -f "$TEST_BASE.addrs" ]; then
        echo "SKIP (no addrs file)"
        SKIP=$((SKIP + 1))
        continue
    fi

    # Get pass/fail addresses
    read PASS_ADDR FAIL_ADDR < "$TEST_BASE.addrs"

    # Convert Intel HEX to unified memory format (umem.hex)
    # For RV64, we need to convert to 64-bit doublewords
    python3 -c "
import sys
data = {{}}
with open('$TEST_BASE.hex', 'r') as f:
    for line in f:
        line = line.strip()
        if not line.startswith(':'):
            continue
        byte_count = int(line[1:3], 16)
        address = int(line[3:7], 16)
        record_type = int(line[7:9], 16)
        if record_type == 0:  # Data record
            for i in range(byte_count):
                byte_val = int(line[9+i*2:11+i*2], 16)
                data[address + i] = byte_val
        elif record_type == 1:  # EOF
            break

if not data:
    sys.exit(1)

max_addr = max(data.keys())
with open('umem.hex', 'w') as f:
    for dword_addr in range((max_addr // 8) + 1):
        byte_addr = dword_addr * 8
        dword = 0
        for i in range(8):
            if byte_addr + i in data:
                dword |= data[byte_addr + i] << (i * 8)
        f.write(f'{{dword:016x}}\\n')
" 2>/dev/null

    if [ $? -ne 0 ]; then
        echo "ERROR (hex conversion failed)"
        FAIL=$((FAIL + 1))
        continue
    fi

    # Run simulation (add 0x prefix to hex addresses)
    ./{module_name}_sim +pass_addr=0x$PASS_ADDR +fail_addr=0x$FAIL_ADDR +hex_file=umem.hex > /tmp/sim_out.txt 2>&1
    result=$?

    if grep -q "TEST PASSED" /tmp/sim_out.txt; then
        echo "PASS"
        PASS=$((PASS + 1))
    elif grep -q "TEST FAILED" /tmp/sim_out.txt; then
        echo "FAIL"
        cat /tmp/sim_out.txt
        FAIL=$((FAIL + 1))
    elif grep -q "TIMEOUT" /tmp/sim_out.txt; then
        echo "TIMEOUT"
        FAIL=$((FAIL + 1))
    else
        echo "ERROR"
        cat /tmp/sim_out.txt
        FAIL=$((FAIL + 1))
    fi
done

echo ""
echo "================================"
echo "Results: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
echo "================================"

if [ $FAIL -eq 0 ] && [ $SKIP -eq 0 ]; then
    echo "SUCCESS: All $PASS tests passed"
    exit 0
elif [ $FAIL -eq 0 ]; then
    echo "PARTIAL: $PASS tests passed, $SKIP skipped"
    exit 0
else
    echo "FAILURE: $FAIL tests failed"
    exit 1
fi
'''


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Create a pipelined RISC-V 64-bit processor.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python create_rv64i_pipeline.py              # Create 5-stage pipeline (default) with stalling
  python create_rv64i_pipeline.py --stages 5   # Create 5-stage pipeline with stalling
  python create_rv64i_pipeline.py --stages 4   # Create 4-stage pipeline with stalling
  python create_rv64i_pipeline.py --stages 3   # Create 3-stage pipeline with stalling
  python create_rv64i_pipeline.py --stages 2   # Create 2-stage pipeline with stalling
  python create_rv64i_pipeline.py --hazard-resolution bypass  # Use bypassing/forwarding
  python create_rv64i_pipeline.py -s 5 -hr bypass  # 5-stage with bypass
  python create_rv64i_pipeline.py --mem-latency 1 5  # Memory latency 1-5 cycles
        """
    )
    parser.add_argument(
        '--engine', '-e',
        type=str,
        default='python',
        choices=['python', 'rust'],
        help='Engine: python (default) or rust (isacomp_core)'
    )
    parser.add_argument(
        '--stages', '-s',
        type=int,
        default=5,
        choices=[2, 3, 4, 5],
        help='Number of pipeline stages (default: 5)'
    )
    parser.add_argument(
        '--hazard-resolution', '-hr',
        type=str,
        default='stall',
        choices=['stall', 'bypass'],
        help='Hazard resolution strategy: stall (default) or bypass'
    )
    parser.add_argument(
        '--backend', '-b',
        type=str,
        default='verilog',
        choices=['verilog', 'vhdl', 'pyrtl', 'circt', 'chisel', 'sim-cpp'],
        help='Output backend: verilog (default), vhdl, pyrtl, circt, chisel, or sim-cpp'
    )
    parser.add_argument(
        '--no-verify',
        action='store_true',
        default=False,
        help='Skip GHDL compilation verification for VHDL backend'
    )
    parser.add_argument(
        '--write-read-fwd',
        action='store_true',
        default=False,
        help='Enable write-to-read forwarding on register file (default: disabled)'
    )
    parser.add_argument(
        '--mem-latency', '-ml',
        type=int,
        nargs='+',
        default=[2, 15],
        metavar='CYCLES',
        help='Memory latency: single value for static latency, two values (MIN MAX) for random. Default: 2 15'
    )
    parser.add_argument(
        '--ras',
        action='store_true',
        default=False,
        help='Enable Return Address Stack (RAS) for return address prediction'
    )
    parser.add_argument(
        '--ras-depth',
        type=int,
        default=8,
        help='RAS stack depth (default: 8)'
    )

    args = parser.parse_args()

    # Initialize engine before anything else
    _init_engine(args.engine)

    # Parse memory latency: single value = static, two values = random range
    if len(args.mem_latency) == 1:
        mem_min = mem_max = args.mem_latency[0]
    elif len(args.mem_latency) >= 2:
        mem_min = args.mem_latency[0]
        mem_max = args.mem_latency[1]
    else:
        mem_min, mem_max = 2, 15  # default

    graph = main(
        num_stages=args.stages,
        hazard_strategy=args.hazard_resolution,
        write_read_fwd=args.write_read_fwd,
        mem_min_latency=mem_min,
        mem_max_latency=mem_max,
        backend=args.backend,
        no_verify=args.no_verify,
        enable_ras=args.ras,
        ras_depth=args.ras_depth
    )
