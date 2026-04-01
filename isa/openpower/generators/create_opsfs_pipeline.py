#!/usr/bin/env python3
from __future__ import annotations
"""
Create a pipelined OpenPOWER Scalar Fixed-point Subset (SFS) processor with configurable stages.

This script applies pipeline transformations to create 2, 3, 4, or 5-stage pipelines.
Pipeline cut decisions are made here by the architect.

Supports --engine python (default) or --engine rust for the Rust isacomp_core backend.
Supports Verilog, VHDL, PyRTL, and CIRCT backends via --backend argument.

Usage:
    python create_opsfs_pipeline.py [--engine ENGINE] [--stages N] [--hazard-resolution STRATEGY]

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
# Python-only advanced features (set to None when using Rust engine)
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
            print("  cd rust_core && maturin develop")
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

        # Advanced features not yet in Rust engine
        RASSpec = None
        CallSpec = None
        ReturnSpec = None
        apply_return_address_stack = None
        Node = None
        Edge = None

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

# OpenPOWER SFS instruction list (85 instructions)
OPSFS_INSTRUCTIONS = [
    # Fixed-point Arithmetic - Register (9)
    'add', 'subf', 'neg', 'mullw', 'mulld', 'divw', 'divwu', 'divd', 'divdu',

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

    # Rotate Doubleword - MD-form (2)
    'rldicl', 'rldicr',

    # Rotate Word - M-form (1)
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


def get_opsfs_instructions():
    """Get all OpenPOWER SFS instructions."""
    opsfs_dir = os.path.join(_project_root, "isa", "openpower")
    instructions = {}

    for instr in OPSFS_INSTRUCTIONS:
        isa_file = os.path.join(opsfs_dir, f"{instr}.isa")
        if os.path.exists(isa_file):
            instructions[instr] = isa_file

    return instructions


def build_merged_graph():
    """Build merged graph of all OpenPOWER SFS instructions."""
    print("Building merged OpenPOWER SFS graph...")

    instructions = get_opsfs_instructions()
    print(f"  Found {len(instructions)} instructions")

    if _engine == 'rust':
        _rc = _init_engine._rc
        graph = _rc.merge_instructions(instructions)
    else:
        merger = ResourceGraphMerger()
        for name, path in instructions.items():
            merger.add_instruction(name, path)
        graph = merger.merge_graphs()

    graph.infer_uarch_time()

    print(f"  Nodes: {len(graph.nodes)}")
    print(f"  Edges: {len(graph.edges)}")

    return graph


def select_pipeline_cut_edges_generic(graph: ResourceGraph, config: PipelineConfig):
    """
    Select edges for each pipeline cut based on the pipeline configuration.

    OpenPOWER uses different register naming than RISC-V:
    - rt (target register) instead of rd
    - ra, rb (source registers) instead of rs1, rs2
    - rs (source for stores)
    - Special registers: LR (Link Register), CTR (Count Register), CR (Condition Register)
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

        # Return address for bl/bla (pc + 4)
        eid = find_edge('(pc + 4)', 'return_addr')
        if eid:
            cuts[decode_stage].append(eid)
            print(f"  [F/{decode_stage[0]}] (pc + 4) -> return_addr (BL return address)")

        # Also check for bl_return_addr if that's what the merger created
        for eid, tgt in find_edges_from('(pc + 4)'):
            if 'return' in tgt.lower() or 'ret' in tgt.lower():
                if eid not in cuts[decode_stage]:
                    cuts[decode_stage].append(eid)
                    print(f"  [F/{decode_stage[0]}] (pc + 4) -> {tgt} (return address)")

        # Branch immediates (li for b/bl) need to be pipelined starting at F/D
        # because li comes from instr which is fetched in F. The D/E cut is added later.
        if 'sign_ext_li' in graph.nodes:
            for eid, src in find_edges_to('sign_ext_li'):
                if eid not in cuts[decode_stage]:
                    cuts[decode_stage].append(eid)
                    print(f"  [F/{decode_stage[0]}] {src} -> sign_ext_li (branch immediate for b/bl)")

    # ========================================
    # CUT 2: D/X - Decode / Execute
    # ========================================
    if config.num_stages >= 4 and execute_stage in cuts and execute_stage != decode_stage:
        print(f"\nCUT 2: {decode_stage} -> {execute_stage}")
        print("-" * 50)

        # Register file read values - OpenPOWER uses ra, rb, rs
        # After merging, these become rf[ra]_rd -> ra_val, rf[rb]_rd -> rb_val, etc.
        # Also cut edges to 32-bit slices like rf[ra]_rd -> rf[ra]_rd[31:0] (similar to MIPS32)
        for reg_read in ['rf[ra]_rd', 'rf[rb]_rd', 'rf[rs]_rd']:
            for eid, tgt in find_edges_from(reg_read):
                # Cut edges to _val nodes and to bit slice nodes [31:0]
                if '_val' in tgt or tgt in ['ra_val', 'rb_val', 'rs_val'] or '[31:0]' in tgt:
                    cuts[execute_stage].append(eid)
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] {reg_read} -> {tgt} (source reg value)")

        # Special Purpose Register reads - CR, LR, CTR
        # These architectural state reads need to be pipelined to Execute stage
        # for mfcr (reads CR), mfspr (reads LR/CTR), and branch instructions
        for spr_read in ['cr_rd', 'lr_rd', 'ctr_rd']:
            for eid, tgt in find_edges_from(spr_read):
                # Don't cut edges to write muxes - those stay in the write path
                if tgt.endswith('_wr_mux') or tgt.endswith('_wr'):
                    continue
                # Cut all other edges from SPR reads - they're used in Execute stage
                if eid not in cuts[execute_stage]:
                    cuts[execute_stage].append(eid)
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] {spr_read} -> {tgt} (SPR read)")

        # (ra == 0) condition - needs to be pipelined to Execute stage so it's available
        # when computing ra_or_zero (which uses add_ra_val from bypass network)
        for eid, tgt in find_edges_from('(ra == 0)'):
            if eid not in cuts[execute_stage]:
                cuts[execute_stage].append(eid)
                print(f"  [{decode_stage[0]}/{execute_stage[0]}] (ra == 0) -> {tgt} (ra==0 condition for mux)")

        # NOTE: ra_or_zero mux output is NOT pipelined - the mux is computed in Execute
        # from the already-pipelined inputs (PIPE_Execute_ra_eqeq_0_PIPE and PIPE_Execute_rf_ra_rd_PIPE).
        # The mux result is used directly in Execute stage, not pipelined again.

        # Destination register index (rt) - flows through subsequent stages
        # Skip edges to rf_write_addr_mux - the mux is computed in Decode and its output is pipelined
        for eid, tgt in find_edges_from('rt'):
            if tgt != '(rt != 0)' and tgt != 'rf_write_addr_mux':  # Comparison and mux stay in Decode
                cuts[execute_stage].append(eid)
                print(f"  [{decode_stage[0]}/{execute_stage[0]}] rt -> {tgt} (dest reg index)")

        # NOTE: ra -> rf_write_addr_mux edges are NOT pipelined - mux is computed in Decode
        # NOTE: rlwinm_ra -> rf_write_addr_mux edges are NOT pipelined - mux is computed in Decode

        # Pipeline the OUTPUT of rf_write_addr_mux - this computes the mux at Decode
        # and pipelines the result, so hazard detection can track the write address at each stage
        if 'rf_write_addr_mux' in graph.nodes:
            for eid, tgt in find_edges_from('rf_write_addr_mux'):
                cuts[execute_stage].append(eid)
                print(f"  [{decode_stage[0]}/{execute_stage[0]}] rf_write_addr_mux -> {tgt} (dest reg addr)")

        # Pipeline the OUTPUT of rf_write_enable - computed in Decode, pipelined as one signal
        # so hazard detection can check write enable at each pipeline stage
        for eid, tgt in find_edges_from('rf_write_enable'):
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] rf_write_enable -> {tgt} (pipeline combined enable)")

        # PC for branch/jump calculations
        for eid, tgt in find_edges_from('pc_rd'):
            if '(pc +' in tgt and tgt != '(pc + 4)':
                cuts[execute_stage].append(eid)
                print(f"  [{decode_stage[0]}/{execute_stage[0]}] pc_rd -> {tgt} (PC for target calc)")

        # Sign-extended and zero-extended immediates for OpenPOWER
        # Match both sign_ext_*/zero_ext_* variables AND instruction-specific versions
        # But NOT computation expressions like (pc + sign_ext_bd) that contain operators
        # Also include shifted_ui which is UI << 16 for andis/oris/xoris instructions
        for node_id in graph.nodes:
            # Skip computation expressions (contain operators or parentheses)
            if '(' in node_id or '+' in node_id or '{' in node_id or '*' in node_id:
                continue
            # Match sign_ext_* (e.g., sign_ext_bd) or *_sign_ext_* (e.g., addi_sign_ext_si)
            # Also match zero_ext_* or *_zero_ext_* (e.g., andi_zero_ext_ui)
            # Also match shifted_ui (UI << 16 for andis/oris/xoris)
            if (node_id.startswith('sign_ext_') or '_sign_ext_' in node_id or
                node_id.startswith('zero_ext_') or '_zero_ext_' in node_id or
                node_id == 'shifted_ui'):
                # Skip sign_ext_li - it's already cut at F/D (needs only 1 stage, not 2)
                if node_id == 'sign_ext_li':
                    continue
                for eid, src in find_edges_to(node_id):
                    if eid not in cuts[execute_stage]:
                        cuts[execute_stage].append(eid)
                        print(f"  [{decode_stage[0]}/{execute_stage[0]}] {src} -> {node_id} (extended immediate)")

        # CR-related instruction fields - used in Execute for CR operations
        # These are decoded from instruction bits but used for comparisons and CR updates
        # Also includes 'bo' which is used for conditional branch condition encoding
        cr_fields = ['bf', 'bfa', 'bt', 'ba', 'bb', 'bi', 'bo', 'fxm']
        for field in cr_fields:
            if field in graph.nodes:
                for eid, tgt in find_edges_from(field):
                    if eid not in cuts[execute_stage]:
                        cuts[execute_stage].append(eid)
                        print(f"  [{decode_stage[0]}/{execute_stage[0]}] {field} -> {tgt} (CR instr field)")

        # CR bit reads - these read specific bits from CR for CR logical operations
        # (crand, cror, crxor, crnand, crnor, etc.)
        # The bit index (ba, bb) is pipelined, so the CR read must also be pipelined
        cr_bit_read_nodes = ['cr_31_sub_ba_rd', 'cr_31_sub_bb_rd', 'cr_31_sub_bi_rd']
        for node_id in cr_bit_read_nodes:
            if node_id in graph.nodes:
                for eid, src in find_edges_to(node_id):
                    if eid not in cuts[execute_stage]:
                        cuts[execute_stage].append(eid)
                        print(f"  [{decode_stage[0]}/{execute_stage[0]}] {src} -> {node_id} (CR bit read)")

        # SPR field comparisons for mfspr/mtspr - these select which SPR (LR/CTR) to read/write
        # The comparisons use the decoded SPR field but the muxes use pipelined LR/CTR values
        # So we need to pipeline the comparison results to Execute stage
        spr_compare_nodes = ["(spr == 10'h8)", "(spr == 10'h9)"]  # LR and CTR comparisons
        for node_id in spr_compare_nodes:
            if node_id in graph.nodes:
                for eid, tgt in find_edges_from(node_id):
                    if eid not in cuts[execute_stage]:
                        cuts[execute_stage].append(eid)
                        print(f"  [{decode_stage[0]}/{execute_stage[0]}] {node_id} -> {tgt} (SPR select)")

        # Return address pipeline chain - only to Execute stage
        # LR writes use return_addr in Execute stage, so we don't need to pipeline further
        for eid, tgt in find_edges_from('(pc + 4)'):
            if 'return' in tgt.lower() or 'ret' in tgt.lower():
                cuts[execute_stage].append(eid)
                # NOTE: Do NOT extend to Memory/Writeback - lr_wr_mux uses this in Execute
                print(f"  [{decode_stage[0]}/{execute_stage[0]}] (pc + 4) -> {tgt} (return address to Execute)")

        # All instruction enable signals
        for node_id in graph.nodes:
            if node_id.endswith('_enable') and not node_id.startswith('rf_rt_ne_0'):
                # Skip rf_write_enable - it's computed from pipelined per-instruction enables
                # and should not be pipelined again
                if node_id == 'rf_write_enable':
                    continue
                # Skip umem_write_enable for 4/5-stage
                if node_id == 'umem_write_enable' and memory_stage != execute_stage:
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} (computed at {memory_stage} from store enables)")
                    continue
                # Skip byte enables
                if 'byte_enable' in node_id:
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} (byte enable computed at {memory_stage} from address)")
                    continue
                for eid, tgt in find_edges_from(node_id):
                    # Skip non-memory read enables - they stay at Decode for stall logic
                    # BUT pipeline edges to umem_ea_rd_enable (load enables need to reach Memory)
                    if '_rd_enable' in tgt and 'umem' not in tgt:
                        print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} -> {tgt} (non-memory rd_enable stays at Decode)")
                        continue
                    if tgt == 'rf_rt_ne_0_enables':
                        print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} -> {tgt} (rf_rt_ne_0_enables stays at Decode)")
                        continue
                    # Skip edges TO rf_write_enable - it's computed in Decode and pipelined as one signal
                    if tgt == 'rf_write_enable':
                        print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} -> {tgt} (rf_write_enable stays at Decode)")
                        continue
                    # Skip edges TO rf_write_addr_mux - mux select stays at Decode, only output is pipelined
                    if tgt == 'rf_write_addr_mux':
                        print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} -> {tgt} (mux select stays at Decode)")
                        continue
                    cuts[execute_stage].append(eid)
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] {node_id} -> {tgt} (control)")

        # Shift amounts for OpenPOWER
        # NOTE: Be careful not to match enable signals like 'extsh_enable' which contain 'sh'
        shamt_nodes = ['sh', 'mb', 'me', 'shamt']
        for shamt in shamt_nodes:
            for node_id in graph.nodes:
                # Skip enable signals - they should NOT be treated as shift amounts
                if node_id.endswith('_enable'):
                    continue
                if shamt in node_id.lower() and 'instr' in str(find_edges_to(node_id)):
                    for eid, tgt in find_edges_from(node_id):
                        if eid not in cuts[execute_stage]:
                            cuts[execute_stage].append(eid)
                            print(f"  [{decode_stage[0]}/{execute_stage[0]}] {node_id} -> {tgt} (shift amount)")

        # Pipeline combined write enable
        for eid, tgt in find_edges_from('rf_rt_ne_0_guarded_enable'):
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] rf_rt_ne_0_guarded_enable -> {tgt} (pipeline combined write enable)")

        # For 4/5-stage: umem_write_enable handling
        if memory_stage == execute_stage:
            for eid, tgt in find_edges_from('umem_write_enable'):
                cuts[execute_stage].append(eid)
                print(f"  [{decode_stage[0]}/{execute_stage[0]}] umem_write_enable -> {tgt} (pipeline combined write enable)")

    # For 3-stage pipeline where Execute/Memory/Writeback is combined
    # Use same D/X cuts as 5-stage, since D/XMW = D/X
    elif config.num_stages == 3:
        print(f"\nCUT 2 (combined X/M/W): {decode_stage} -> {execute_stage}")
        print("-" * 50)

        # Register file read values - same as 5-stage D/X
        for reg_read in ['rf[ra]_rd', 'rf[rb]_rd', 'rf[rs]_rd']:
            for eid, tgt in find_edges_from(reg_read):
                if '_val' in tgt or tgt in ['ra_val', 'rb_val', 'rs_val'] or '[31:0]' in tgt:
                    if eid not in cuts[execute_stage]:
                        cuts[execute_stage].append(eid)
                        print(f"  [{decode_stage[0]}/{execute_stage[0]}] {reg_read} -> {tgt} (source reg value)")

        # Special Purpose Register reads - CR, LR, CTR - same as 5-stage D/X
        for spr_read in ['cr_rd', 'lr_rd', 'ctr_rd']:
            for eid, tgt in find_edges_from(spr_read):
                if tgt.endswith('_wr_mux') or tgt.endswith('_wr'):
                    continue
                if eid not in cuts[execute_stage]:
                    cuts[execute_stage].append(eid)
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] {spr_read} -> {tgt} (SPR read)")

        # (ra == 0) condition - same as 5-stage D/X
        for eid, tgt in find_edges_from('(ra == 0)'):
            if eid not in cuts[execute_stage]:
                cuts[execute_stage].append(eid)
                print(f"  [{decode_stage[0]}/{execute_stage[0]}] (ra == 0) -> {tgt} (ra==0 condition for mux)")

        # Destination register index (rt) - same as 5-stage D/X
        for eid, tgt in find_edges_from('rt'):
            if tgt != '(rt != 0)' and tgt != 'rf_write_addr_mux':
                if eid not in cuts[execute_stage]:
                    cuts[execute_stage].append(eid)
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] rt -> {tgt} (dest reg index)")

        # Pipeline rf_write_addr_mux output - same as 5-stage D/X
        if 'rf_write_addr_mux' in graph.nodes:
            for eid, tgt in find_edges_from('rf_write_addr_mux'):
                if eid not in cuts[execute_stage]:
                    cuts[execute_stage].append(eid)
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] rf_write_addr_mux -> {tgt} (dest reg addr)")

        # Pipeline rf_write_enable output - same as 5-stage D/X
        for eid, tgt in find_edges_from('rf_write_enable'):
            if eid not in cuts[execute_stage]:
                cuts[execute_stage].append(eid)
                print(f"  [{decode_stage[0]}/{execute_stage[0]}] rf_write_enable -> {tgt} (pipeline combined enable)")

        # PC for branch/jump calculations - same as 5-stage D/X
        for eid, tgt in find_edges_from('pc_rd'):
            if '(pc +' in tgt and tgt != '(pc + 4)':
                if eid not in cuts[execute_stage]:
                    cuts[execute_stage].append(eid)
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] pc_rd -> {tgt} (PC for target calc)")

        # Sign-extended, zero-extended immediates and shifted_ui - same as 5-stage D/X
        for node_id in graph.nodes:
            if '(' in node_id or '+' in node_id or '{' in node_id or '*' in node_id:
                continue
            if (node_id.startswith('sign_ext_') or '_sign_ext_' in node_id or
                node_id.startswith('zero_ext_') or '_zero_ext_' in node_id or
                node_id == 'shifted_ui'):
                if node_id == 'sign_ext_li':
                    continue  # Already cut at F/D
                for eid, src in find_edges_to(node_id):
                    if eid not in cuts[execute_stage]:
                        cuts[execute_stage].append(eid)
                        print(f"  [{decode_stage[0]}/{execute_stage[0]}] {src} -> {node_id} (extended immediate)")

        # CR-related instruction fields - same as 5-stage D/X
        cr_fields = ['bf', 'bfa', 'bt', 'ba', 'bb', 'bi', 'bo', 'fxm']
        for field in cr_fields:
            if field in graph.nodes:
                for eid, tgt in find_edges_from(field):
                    if eid not in cuts[execute_stage]:
                        cuts[execute_stage].append(eid)
                        print(f"  [{decode_stage[0]}/{execute_stage[0]}] {field} -> {tgt} (CR instr field)")

        # CR bit reads - same as 5-stage D/X
        cr_bit_read_nodes = ['cr_31_sub_ba_rd', 'cr_31_sub_bb_rd', 'cr_31_sub_bi_rd']
        for node_id in cr_bit_read_nodes:
            if node_id in graph.nodes:
                for eid, src in find_edges_to(node_id):
                    if eid not in cuts[execute_stage]:
                        cuts[execute_stage].append(eid)
                        print(f"  [{decode_stage[0]}/{execute_stage[0]}] {src} -> {node_id} (CR bit read)")

        # SPR field comparisons - same as 5-stage D/X
        spr_compare_nodes = ["(spr == 10'h8)", "(spr == 10'h9)"]
        for node_id in spr_compare_nodes:
            if node_id in graph.nodes:
                for eid, tgt in find_edges_from(node_id):
                    if eid not in cuts[execute_stage]:
                        cuts[execute_stage].append(eid)
                        print(f"  [{decode_stage[0]}/{execute_stage[0]}] {node_id} -> {tgt} (SPR select)")

        # Return address - same as 5-stage D/X
        for eid, tgt in find_edges_from('(pc + 4)'):
            if 'return' in tgt.lower() or 'ret' in tgt.lower():
                if eid not in cuts[execute_stage]:
                    cuts[execute_stage].append(eid)
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] (pc + 4) -> {tgt} (return address)")

        # Instruction enable signals - same as 5-stage D/X
        for node_id in graph.nodes:
            if node_id.startswith('PIPE_'):
                continue
            if node_id == 'rf_write_enable':
                continue
            # Skip umem_write_enable - it's computed from pipelined store enables
            # and should not be pipelined again
            if node_id == 'umem_write_enable':
                continue
            if node_id.endswith('_enable') and not node_id.startswith('rf_rt_ne_0'):
                if 'byte_enable' in node_id:
                    continue
                for eid, tgt in find_edges_from(node_id):
                    if '_rd_enable' in tgt and 'umem' not in tgt:
                        continue
                    if tgt == 'rf_rt_ne_0_enables':
                        continue
                    if tgt == 'rf_write_enable':
                        continue
                    if tgt == 'rf_write_addr_mux':
                        continue
                    if eid not in cuts[execute_stage]:
                        cuts[execute_stage].append(eid)
                        print(f"  [{decode_stage[0]}/{execute_stage[0]}] {node_id} -> {tgt} (control)")

        # Shift amounts - same as 5-stage D/X
        shamt_nodes = ['sh', 'mb', 'me', 'shamt']
        for shamt in shamt_nodes:
            for node_id in graph.nodes:
                if node_id.endswith('_enable'):
                    continue
                if shamt in node_id.lower() and 'instr' in str(find_edges_to(node_id)):
                    for eid, tgt in find_edges_from(node_id):
                        if eid not in cuts[execute_stage]:
                            cuts[execute_stage].append(eid)
                            print(f"  [{decode_stage[0]}/{execute_stage[0]}] {node_id} -> {tgt} (shift amount)")

        # Combined enables - same as 5-stage D/X
        for eid, tgt in find_edges_from('rf_rt_ne_0_guarded_enable'):
            if eid not in cuts[execute_stage]:
                cuts[execute_stage].append(eid)
                print(f"  [{decode_stage[0]}/{execute_stage[0]}] rf_rt_ne_0_guarded_enable -> {tgt}")

        # NOTE: Do NOT pipeline umem_write_enable for 3-stage
        # Individual store enables are already pipelined above.
        # umem_write_enable is computed from those pipelined enables,
        # so it's already at the correct timing.

    # ========================================
    # CUT 3: X/M - Execute / Memory
    # ========================================
    if memory_stage in cuts and memory_stage != execute_stage and memory_stage != writeback_stage:
        print(f"\nCUT 3: {execute_stage} -> {memory_stage}")
        print("-" * 50)

        # Memory addresses - OpenPOWER uses 'ea' (effective address)
        # The address mux (umem_ea_rd_addr_mux) is computed in Execute from ea signals.
        # We pipeline the MUX OUTPUT to Memory, not the individual inputs.
        # Only cut edge to memory read index - byte_offset/word_select/halfword_select are slices
        # that should be emitted using the pipelined address in the code generator.
        for node_id in graph.nodes:
            if node_id == 'umem_ea_rd_addr_mux':
                for eid, tgt in find_edges_from(node_id):
                    # Only cut edge to memory array index, not to slice operations
                    if tgt == 'umem[ea]_rd' and eid not in cuts[memory_stage]:
                        cuts[memory_stage].append(eid)
                        print(f"  [{execute_stage[0]}/{memory_stage[0]}] {node_id} -> {tgt} (memory read address)")
            # Also pipeline individual ea signals to umem write address mux
            elif ('ea' in node_id.lower() or 'addr' in node_id.lower()) and '_rd' not in node_id and node_id != 'umem_ea_rd_addr_mux':
                for eid, tgt in find_edges_from(node_id):
                    if 'umem_write' in tgt and eid not in cuts[memory_stage]:
                        cuts[memory_stage].append(eid)
                        print(f"  [{execute_stage[0]}/{memory_stage[0]}] {node_id} -> {tgt} (memory write address)")

        # Byte offset nodes - these are computed in Execute from the effective address
        # Include umem_ea_rd_* nodes - they're at pipe_time=2 and need to be pipelined
        # to Memory stage to match memory read timing
        # Skip instruction fetch related nodes (umem_pc_rd_*) - they operate in Fetch stage
        for node_id, node in graph.nodes.items():
            # Skip instruction fetch byte selection (operates in Fetch, not Memory)
            if 'umem_pc_rd' in node_id or 'umem[pc]' in node_id:
                continue

            is_byte_offset = node_id.endswith('_byte_offset')
            is_halfword_select = node_id.endswith('_halfword_select')
            is_word_select = node_id.endswith('_word_select')

            if is_byte_offset or is_halfword_select or is_word_select:
                for eid, tgt in find_edges_from(node_id):
                    if eid not in cuts[memory_stage]:
                        cuts[memory_stage].append(eid)
                        print(f"  [{execute_stage[0]}/{memory_stage[0]}] {node_id} -> {tgt} (byte selection offset)")

        # ALU results going to writeback mux
        # Exclude load results (lbz_result, lwz_result, etc.) - those are Memory-stage, not Execute
        load_result_prefixes = ['lbz_', 'lbzx_', 'lhz_', 'lhzx_', 'lha_', 'lwz_', 'lwzx_', 'lwa_', 'ld_', 'ldx_']
        result_patterns = ['_res', 'result']
        for node_id in graph.nodes:
            # Skip load results - they're computed in Memory stage
            is_load_result = any(node_id.startswith(prefix) for prefix in load_result_prefixes)
            if is_load_result:
                continue
            for pattern in result_patterns:
                if pattern in node_id:
                    for eid, tgt in find_edges_from(node_id):
                        if tgt == 'rf_write_data_mux':
                            if eid not in cuts[memory_stage]:
                                cuts[memory_stage].append(eid)
                                print(f"  [{execute_stage[0]}/{memory_stage[0]}] {node_id} -> rf_write_data_mux")

        # Store data - OpenPOWER uses rs_val for store data
        # Only pipeline rs_val edges to umem_write_data_mux (for std/stdx)
        # Don't pipeline rs_val to other targets - that would break shift/logic ops
        # Note: rs_val may be split into and_rs_val, mtspr_xer_rs_val, mtspr_rs_val
        for eid, src in find_edges_from_suffix('rs_val', 'umem_write_data_mux'):
            if eid not in cuts[memory_stage]:
                cuts[memory_stage].append(eid)
                print(f"  [{execute_stage[0]}/{memory_stage[0]}] {src} -> umem_write_data_mux (store data)")

        # Pipeline store data zext nodes to positioned_data nodes
        # The positioned_data is computed in Memory (uses address offset), so data must also be in Memory
        store_data_zexts = ['stb_byte_data_zext_zext', 'sth_half_data_zext_zext', 'stw_word_data_zext_zext']
        positioned_data_nodes = ['stb_positioned_data', 'stbx_positioned_data',
                                 'sth_positioned_data', 'sthx_positioned_data',
                                 'stw_positioned_data', 'stwx_positioned_data']
        for zext_node in store_data_zexts:
            if zext_node in graph.nodes:
                for eid, tgt in find_edges_from(zext_node):
                    if tgt in positioned_data_nodes and eid not in cuts[memory_stage]:
                        cuts[memory_stage].append(eid)
                        print(f"  [{execute_stage[0]}/{memory_stage[0]}] {zext_node} -> {tgt} (store data to Memory)")

        # Store enables - must be at Memory stage to match EA timing
        # EA is pipelined E/M, so enables to addr mux must also be pipelined E/M
        store_instrs = ['stb', 'stbx', 'sth', 'sthx', 'stw', 'stwx', 'std', 'stdx']
        for store_instr in store_instrs:
            store_enable = f'{store_instr}_enable'
            for eid, tgt in find_edges_from(store_enable):
                if tgt in ['umem_write_data_mux', 'umem_write_addr_mux', 'umem_write_enable']:
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_enable} -> {tgt}")

        # Load enables for stall detection
        load_instrs = ['lbz', 'lbzx', 'lhz', 'lhzx', 'lha', 'lwz', 'lwzx', 'lwa', 'ld', 'ldx']
        for load_instr in load_instrs:
            load_enable = f'{load_instr}_enable'
            for eid, tgt in find_edges_from(load_enable):
                if tgt == 'umem_addr_rd_enable':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {load_enable} -> {tgt}")

        # Propagate rt through Memory stage (for rf write, NOT to mux - mux is computed in Decode)
        for eid, tgt in find_edges_from('rt'):
            if tgt in ['rf[rt]_wr', 'rf_shared_wr']:  # Skip rf_write_addr_mux - mux is in Decode
                cuts[memory_stage].append(eid)
                print(f"  [{execute_stage[0]}/{memory_stage[0]}] rt -> {tgt} (dest reg index)")

        # NOTE: ra -> rf_write_addr_mux edges are NOT pipelined - mux is computed in Decode
        # NOTE: rlwinm_ra -> rf_write_addr_mux edges are NOT pipelined - mux is computed in Decode

        # Pipeline the OUTPUT of rf_write_addr_mux through Memory stage
        if 'rf_write_addr_mux' in graph.nodes:
            for eid, tgt in find_edges_from('rf_write_addr_mux'):
                cuts[memory_stage].append(eid)
                print(f"  [{execute_stage[0]}/{memory_stage[0]}] rf_write_addr_mux -> {tgt} (dest reg addr)")

        # Pipeline the OUTPUT of rf_write_enable through Memory stage
        for eid, tgt in find_edges_from('rf_write_enable'):
            cuts[memory_stage].append(eid)
            print(f"  [{execute_stage[0]}/{memory_stage[0]}] rf_write_enable -> {tgt} (pipeline combined enable)")

        # Propagate enable signals to rf_write_data_mux only
        # NOTE: Skip rf_write_addr_mux - it's computed in Decode and its output is already pipelined
        # NOTE: Skip rf_write_enable - it's computed in Decode and pipelined as one signal
        for node_id in graph.nodes:
            if node_id.endswith('_enable') and not node_id.startswith('rf_rt_ne_0') and node_id != 'umem_write_enable':
                for eid, tgt in find_edges_from(node_id):
                    if tgt == 'rf_write_data_mux':  # Skip rf_write_addr_mux and rf_write_enable
                        cuts[memory_stage].append(eid)
                        print(f"  [{execute_stage[0]}/{memory_stage[0]}] {node_id} -> {tgt}")

        # Pipeline combined write enable
        for eid, tgt in find_edges_from('rf_rt_ne_0_guarded_enable'):
            cuts[memory_stage].append(eid)
            print(f"  [{execute_stage[0]}/{memory_stage[0]}] rf_rt_ne_0_guarded_enable -> {tgt}")

        print(f"  NOTE: pc_wr_mux inputs stay in {execute_stage} stage")
        print(f"  NOTE: Branch conditions stay in {execute_stage} - branches resolve in {execute_stage} stage")

    # ========================================
    # CUT 4: M/W - Memory / Writeback
    # ========================================
    if writeback_stage in cuts and writeback_stage != memory_stage:
        print(f"\nCUT 4: {memory_stage} -> {writeback_stage}")
        print("-" * 50)

        # Memory read results
        # NOTE: Use exact suffix matching to avoid 'data' matching 'word_data' etc.
        # Also check for duplicates since multiple patterns could match
        memory_result_suffixes = ['_byte_data', '_halfword_data', '_word_data', '_dword_data']
        for node_id in graph.nodes:
            for suffix in memory_result_suffixes:
                if node_id.endswith(suffix) or node_id == suffix[1:]:  # Handle 'byte_data' etc without prefix
                    for eid, tgt in find_edges_from(node_id):
                        if tgt == 'rf_write_data_mux' and eid not in cuts[writeback_stage]:
                            cuts[writeback_stage].append(eid)
                            print(f"  [{memory_stage[0]}/{writeback_stage[0]}] {node_id} -> rf_write_data_mux")

        # ALU results: Need to pipeline at M/W boundary too
        # Results computed in Execute need 2 stages of pipelining to reach Writeback (E->M, M->W)
        result_patterns = ['_res', 'result']
        for node_id in graph.nodes:
            for pattern in result_patterns:
                if pattern in node_id:
                    for eid, tgt in find_edges_from(node_id):
                        if tgt == 'rf_write_data_mux':
                            if eid not in cuts[writeback_stage]:
                                cuts[writeback_stage].append(eid)
                                print(f"  [{memory_stage[0]}/{writeback_stage[0]}] {node_id} -> rf_write_data_mux")

        # Propagate rt through Writeback (for rf write, NOT to mux - mux is computed in Decode)
        for eid, tgt in find_edges_from('rt'):
            if tgt in ['rf[rt]_wr', 'rf_shared_wr']:  # Skip rf_write_addr_mux - mux is in Decode
                cuts[writeback_stage].append(eid)
                print(f"  [{memory_stage[0]}/{writeback_stage[0]}] rt -> {tgt} (dest reg index)")

        # NOTE: ra -> rf_write_addr_mux edges are NOT pipelined - mux is computed in Decode
        # NOTE: rlwinm_ra -> rf_write_addr_mux edges are NOT pipelined - mux is computed in Decode

        # Pipeline the OUTPUT of rf_write_addr_mux through Writeback stage
        if 'rf_write_addr_mux' in graph.nodes:
            for eid, tgt in find_edges_from('rf_write_addr_mux'):
                cuts[writeback_stage].append(eid)
                print(f"  [{memory_stage[0]}/{writeback_stage[0]}] rf_write_addr_mux -> {tgt} (dest reg addr)")

        # Pipeline the OUTPUT of rf_write_enable through Writeback stage
        for eid, tgt in find_edges_from('rf_write_enable'):
            cuts[writeback_stage].append(eid)
            print(f"  [{memory_stage[0]}/{writeback_stage[0]}] rf_write_enable -> {tgt} (pipeline combined enable)")

        # Propagate enable signals to Writeback (rf_write_data_mux only)
        # NOTE: Skip rf_write_addr_mux - it's computed in Decode and its output is already pipelined
        # NOTE: Skip rf_write_enable - it's computed in Decode and pipelined as one signal
        for node_id in graph.nodes:
            if node_id.endswith('_enable') and not node_id.startswith('rf_rt_ne_0') and node_id != 'umem_write_enable':
                for eid, tgt in find_edges_from(node_id):
                    if tgt == 'rf_write_data_mux':  # Skip rf_write_addr_mux and rf_write_enable
                        cuts[writeback_stage].append(eid)
                        print(f"  [{memory_stage[0]}/{writeback_stage[0]}] {node_id} -> {tgt}")

        # Pipeline combined write enable
        for eid, tgt in find_edges_from('rf_rt_ne_0_guarded_enable'):
            cuts[writeback_stage].append(eid)
            print(f"  [{memory_stage[0]}/{writeback_stage[0]}] rf_rt_ne_0_guarded_enable -> {tgt}")

    # For 4-stage pipeline, Memory/Writeback is combined - use same logic as 5-stage X/M cut
    elif writeback_stage == memory_stage and memory_stage in cuts and memory_stage != execute_stage:
        print(f"\nCUT 3: {execute_stage} -> {memory_stage} (Memory+Writeback combined)")
        print("-" * 50)

        # Memory addresses - same as 5-stage X/M
        for node_id in graph.nodes:
            if node_id.startswith('PIPE_'):
                continue
            if node_id == 'umem_ea_rd_addr_mux':
                for eid, tgt in find_edges_from(node_id):
                    if tgt == 'umem[ea]_rd' and eid not in cuts[memory_stage]:
                        cuts[memory_stage].append(eid)
                        print(f"  [{execute_stage[0]}/{memory_stage[0]}] {node_id} -> {tgt} (memory read address)")
            elif ('ea' in node_id.lower() or 'addr' in node_id.lower()) and '_rd' not in node_id and node_id != 'umem_ea_rd_addr_mux':
                for eid, tgt in find_edges_from(node_id):
                    if 'umem_write' in tgt and eid not in cuts[memory_stage]:
                        cuts[memory_stage].append(eid)
                        print(f"  [{execute_stage[0]}/{memory_stage[0]}] {node_id} -> {tgt} (memory write address)")

        # Byte offset nodes - same as 5-stage X/M
        # Skip instruction fetch related nodes (umem_pc_rd_*) - they operate in Fetch stage
        for node_id, node in graph.nodes.items():
            if node_id.startswith('PIPE_'):
                continue
            # Skip instruction fetch byte selection (operates in Fetch, not Memory)
            if 'umem_pc_rd' in node_id or 'umem[pc]' in node_id:
                continue

            is_byte_offset = node_id.endswith('_byte_offset')
            is_halfword_select = node_id.endswith('_halfword_select')
            is_word_select = node_id.endswith('_word_select')

            if is_byte_offset or is_halfword_select or is_word_select:
                for eid, tgt in find_edges_from(node_id):
                    if eid not in cuts[memory_stage]:
                        cuts[memory_stage].append(eid)
                        print(f"  [{execute_stage[0]}/{memory_stage[0]}] {node_id} -> {tgt} (byte selection offset)")

        # ALU results going to writeback mux - same as 5-stage X/M
        # Exclude load results - those are computed in this combined stage
        load_result_prefixes = ['lbz_', 'lbzx_', 'lhz_', 'lhzx_', 'lha_', 'lwz_', 'lwzx_', 'lwa_', 'ld_', 'ldx_']
        result_patterns = ['_res', 'result']
        for node_id in graph.nodes:
            if node_id.startswith('PIPE_'):
                continue
            is_load_result = any(node_id.startswith(prefix) for prefix in load_result_prefixes)
            if is_load_result:
                continue
            for pattern in result_patterns:
                if pattern in node_id:
                    for eid, tgt in find_edges_from(node_id):
                        if tgt == 'rf_write_data_mux' and eid not in cuts[memory_stage]:
                            cuts[memory_stage].append(eid)
                            print(f"  [{execute_stage[0]}/{memory_stage[0]}] {node_id} -> rf_write_data_mux")

        # Store data - same as 5-stage X/M
        # Note: rs_val may be split into and_rs_val, mtspr_xer_rs_val, mtspr_rs_val
        for eid, src in find_edges_from_suffix('rs_val', 'umem_write_data_mux'):
            if eid not in cuts[memory_stage]:
                cuts[memory_stage].append(eid)
                print(f"  [{execute_stage[0]}/{memory_stage[0]}] {src} -> umem_write_data_mux (store data)")

        # Pipeline store data zext nodes - same as 5-stage X/M
        store_data_zexts = ['stb_byte_data_zext_zext', 'sth_half_data_zext_zext', 'stw_word_data_zext_zext']
        positioned_data_nodes = ['stb_positioned_data', 'stbx_positioned_data',
                                 'sth_positioned_data', 'sthx_positioned_data',
                                 'stw_positioned_data', 'stwx_positioned_data']
        for zext_node in store_data_zexts:
            if zext_node in graph.nodes:
                for eid, tgt in find_edges_from(zext_node):
                    if tgt in positioned_data_nodes and eid not in cuts[memory_stage]:
                        cuts[memory_stage].append(eid)
                        print(f"  [{execute_stage[0]}/{memory_stage[0]}] {zext_node} -> {tgt} (store data)")

        # Store enables - same as 5-stage X/M
        store_instrs = ['stb', 'stbx', 'sth', 'sthx', 'stw', 'stwx', 'std', 'stdx']
        for store_instr in store_instrs:
            store_enable = f'{store_instr}_enable'
            for eid, tgt in find_edges_from(store_enable):
                if tgt in ['umem_write_data_mux', 'umem_write_addr_mux', 'umem_write_enable']:
                    if eid not in cuts[memory_stage]:
                        cuts[memory_stage].append(eid)
                        print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_enable} -> {tgt}")

        # Load enables for stall detection - same as 5-stage X/M
        load_instrs = ['lbz', 'lbzx', 'lhz', 'lhzx', 'lha', 'lwz', 'lwzx', 'lwa', 'ld', 'ldx']
        for load_instr in load_instrs:
            load_enable = f'{load_instr}_enable'
            for eid, tgt in find_edges_from(load_enable):
                if tgt == 'umem_addr_rd_enable' and eid not in cuts[memory_stage]:
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {load_enable} -> {tgt}")

        # Propagate rt - same as 5-stage X/M
        for eid, tgt in find_edges_from('rt'):
            if tgt in ['rf[rt]_wr', 'rf_shared_wr'] and eid not in cuts[memory_stage]:
                cuts[memory_stage].append(eid)
                print(f"  [{execute_stage[0]}/{memory_stage[0]}] rt -> {tgt} (dest reg index)")

        # Pipeline rf_write_addr_mux output - same as 5-stage X/M
        if 'rf_write_addr_mux' in graph.nodes:
            for eid, tgt in find_edges_from('rf_write_addr_mux'):
                if eid not in cuts[memory_stage]:
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] rf_write_addr_mux -> {tgt} (dest reg addr)")

        # Pipeline rf_write_enable output - same as 5-stage X/M
        for eid, tgt in find_edges_from('rf_write_enable'):
            if eid not in cuts[memory_stage]:
                cuts[memory_stage].append(eid)
                print(f"  [{execute_stage[0]}/{memory_stage[0]}] rf_write_enable -> {tgt} (pipeline combined enable)")

        # Propagate enable signals to rf_write_data_mux - same as 5-stage X/M
        for node_id in graph.nodes:
            if node_id.startswith('PIPE_'):
                continue
            if node_id.endswith('_enable') and not node_id.startswith('rf_rt_ne_0') and node_id != 'umem_write_enable':
                for eid, tgt in find_edges_from(node_id):
                    if tgt == 'rf_write_data_mux' and eid not in cuts[memory_stage]:
                        cuts[memory_stage].append(eid)
                        print(f"  [{execute_stage[0]}/{memory_stage[0]}] {node_id} -> {tgt}")

        # Pipeline combined write enable - same as 5-stage X/M
        for eid, tgt in find_edges_from('rf_rt_ne_0_guarded_enable'):
            if eid not in cuts[memory_stage]:
                cuts[memory_stage].append(eid)
                print(f"  [{execute_stage[0]}/{memory_stage[0]}] rf_rt_ne_0_guarded_enable -> {tgt}")

    # For 2-stage pipeline - use same pattern as 3-stage
    if config.num_stages == 2:
        combined_stage = execute_stage
        print(f"\nCUT 1: FetchDecode -> {combined_stage} (single cut, 2-stage pipeline)")
        print("-" * 50)

        # Register file read values - same as 3-stage
        for reg_read in ['rf[ra]_rd', 'rf[rb]_rd', 'rf[rs]_rd']:
            for eid, tgt in find_edges_from(reg_read):
                if '_val' in tgt or tgt in ['ra_val', 'rb_val', 'rs_val'] or '[31:0]' in tgt:
                    if eid not in cuts[combined_stage]:
                        cuts[combined_stage].append(eid)
                        print(f"  [FD/{combined_stage[0]}] {reg_read} -> {tgt} (source reg value)")

        # Special Purpose Register reads - NOT pipelined in 2-stage
        # In 2-stage, cr_rd, lr_rd, and ctr_rd should NOT be pipelined because:
        # 1. Conditional branches need current CR value (bc after cmpw)
        # 2. mfspr needs current LR/CTR value (mfspr after mtspr)
        # The stall logic ensures hazards are resolved, but pipelining the reads
        # causes the stale value to be used. Use the ISA state directly instead.
        # NOTE: This is different from 3+ stage pipelines where the values
        # need to be pipelined through multiple stages.
        print(f"  [FD/{combined_stage[0]}] SKIP cr_rd, lr_rd, ctr_rd (SPR reads not pipelined in 2-stage)")

        # (ra == 0) condition - same as 3-stage
        for eid, tgt in find_edges_from('(ra == 0)'):
            if eid not in cuts[combined_stage]:
                cuts[combined_stage].append(eid)
                print(f"  [FD/{combined_stage[0]}] (ra == 0) -> {tgt} (ra==0 condition for mux)")

        # Destination register index (rt) - same as 3-stage
        for eid, tgt in find_edges_from('rt'):
            if tgt != '(rt != 0)' and tgt != 'rf_write_addr_mux':
                if eid not in cuts[combined_stage]:
                    cuts[combined_stage].append(eid)
                    print(f"  [FD/{combined_stage[0]}] rt -> {tgt} (dest reg index)")

        # Pipeline rf_write_addr_mux output - same as 3-stage
        if 'rf_write_addr_mux' in graph.nodes:
            for eid, tgt in find_edges_from('rf_write_addr_mux'):
                if eid not in cuts[combined_stage]:
                    cuts[combined_stage].append(eid)
                    print(f"  [FD/{combined_stage[0]}] rf_write_addr_mux -> {tgt} (dest reg addr)")

        # Pipeline rf_write_enable output - same as 3-stage
        for eid, tgt in find_edges_from('rf_write_enable'):
            if eid not in cuts[combined_stage]:
                cuts[combined_stage].append(eid)
                print(f"  [FD/{combined_stage[0]}] rf_write_enable -> {tgt} (pipeline combined enable)")

        # PC for branch/jump calculations - same as 3-stage
        for eid, tgt in find_edges_from('pc_rd'):
            if '(pc +' in tgt and tgt != '(pc + 4)':
                if eid not in cuts[combined_stage]:
                    cuts[combined_stage].append(eid)
                    print(f"  [FD/{combined_stage[0]}] pc_rd -> {tgt} (PC for target calc)")

        # Sign-extended, zero-extended immediates and shifted_ui - same as 3-stage
        # NOTE: For 2-stage, sign_ext_li MUST be included (not skipped like 3/4/5 stage)
        # because there's no F/D boundary - only FD/XMW boundary
        for node_id in graph.nodes:
            if '(' in node_id or '+' in node_id or '{' in node_id or '*' in node_id:
                continue
            if (node_id.startswith('sign_ext_') or '_sign_ext_' in node_id or
                node_id.startswith('zero_ext_') or '_zero_ext_' in node_id or
                node_id == 'shifted_ui'):
                # For 2-stage, include ALL sign extensions including sign_ext_li
                # (In 3+ stage pipelines, sign_ext_li is cut at F/D, but 2-stage has no F/D)
                for eid, src in find_edges_to(node_id):
                    if eid not in cuts[combined_stage]:
                        cuts[combined_stage].append(eid)
                        print(f"  [FD/{combined_stage[0]}] {src} -> {node_id} (extended immediate)")

        # CR-related instruction fields - same as 3-stage
        cr_fields = ['bf', 'bfa', 'bt', 'ba', 'bb', 'bi', 'bo', 'fxm']
        for field in cr_fields:
            if field in graph.nodes:
                for eid, tgt in find_edges_from(field):
                    if eid not in cuts[combined_stage]:
                        cuts[combined_stage].append(eid)
                        print(f"  [FD/{combined_stage[0]}] {field} -> {tgt} (CR instr field)")

        # CR bit reads - same as 3-stage
        cr_bit_read_nodes = ['cr_31_sub_ba_rd', 'cr_31_sub_bb_rd', 'cr_31_sub_bi_rd']
        for node_id in cr_bit_read_nodes:
            if node_id in graph.nodes:
                for eid, src in find_edges_to(node_id):
                    if eid not in cuts[combined_stage]:
                        cuts[combined_stage].append(eid)
                        print(f"  [FD/{combined_stage[0]}] {src} -> {node_id} (CR bit read)")

        # SPR field comparisons - same as 3-stage
        spr_compare_nodes = ["(spr == 10'h8)", "(spr == 10'h9)"]
        for node_id in spr_compare_nodes:
            if node_id in graph.nodes:
                for eid, tgt in find_edges_from(node_id):
                    if eid not in cuts[combined_stage]:
                        cuts[combined_stage].append(eid)
                        print(f"  [FD/{combined_stage[0]}] {node_id} -> {tgt} (SPR select)")

        # Return address - same as 3-stage
        for eid, tgt in find_edges_from('(pc + 4)'):
            if 'return' in tgt.lower() or 'ret' in tgt.lower():
                if eid not in cuts[combined_stage]:
                    cuts[combined_stage].append(eid)
                    print(f"  [FD/{combined_stage[0]}] (pc + 4) -> {tgt} (return address)")

        # Instruction enable signals - same as 3-stage
        for node_id in graph.nodes:
            if node_id.startswith('PIPE_'):
                continue
            if node_id == 'rf_write_enable':
                continue
            # Skip umem_write_enable - it's computed from pipelined store enables
            if node_id == 'umem_write_enable':
                continue
            if node_id.endswith('_enable') and not node_id.startswith('rf_rt_ne_0'):
                if 'byte_enable' in node_id:
                    continue
                for eid, tgt in find_edges_from(node_id):
                    if '_rd_enable' in tgt and 'umem' not in tgt:
                        continue
                    if tgt == 'rf_rt_ne_0_enables':
                        continue
                    if tgt == 'rf_write_enable':
                        continue
                    if tgt == 'rf_write_addr_mux':
                        continue
                    if eid not in cuts[combined_stage]:
                        cuts[combined_stage].append(eid)
                        print(f"  [FD/{combined_stage[0]}] {node_id} -> {tgt} (control)")

        # Shift amounts - same as 3-stage
        shamt_nodes = ['sh', 'mb', 'me', 'shamt']
        for shamt in shamt_nodes:
            for node_id in graph.nodes:
                if node_id.endswith('_enable'):
                    continue
                if shamt in node_id.lower() and 'instr' in str(find_edges_to(node_id)):
                    for eid, tgt in find_edges_from(node_id):
                        if eid not in cuts[combined_stage]:
                            cuts[combined_stage].append(eid)
                            print(f"  [FD/{combined_stage[0]}] {node_id} -> {tgt} (shift amount)")

        # Combined enables - same as 3-stage
        for eid, tgt in find_edges_from('rf_rt_ne_0_guarded_enable'):
            if eid not in cuts[combined_stage]:
                cuts[combined_stage].append(eid)
                print(f"  [FD/{combined_stage[0]}] rf_rt_ne_0_guarded_enable -> {tgt}")

        # NOTE: Do NOT pipeline umem_write_enable for 2-stage
        # Individual store enables are already pipelined above.
        # umem_write_enable is computed from those pipelined enables,
        # so it's already at the correct timing.

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
    """Apply pipeline transformations to the graph."""
    print("\n" + "=" * 70)
    print("APPLYING PIPELINE TRANSFORMATIONS")
    print("=" * 70)

    transform = PipelineTransform(graph)

    # Set explicit stage order for validity signal creation
    stage_order = [cut.name for cut in config.cuts]
    stage_indices = {cut.name: cut.stage_index for cut in config.cuts}
    transform.set_stage_order(stage_order, stage_indices)
    print(f"  Using explicit stage order: {stage_order}")
    print(f"  Stage indices: {stage_indices}")

    # Build cut specifications
    cut_specs = []
    for cut in config.cuts:
        stage_name = cut.name
        if stage_name in cuts and cuts[stage_name]:
            cut_specs.append({
                'edges': cuts[stage_name],
                'after_stage': stage_name,
                'stage_index': cut.stage_index
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

    if _engine == 'rust':
        graph = transform.get_graph()
    return success, graph


def apply_branch_prediction(graph: ResourceGraph, config: PipelineConfig):
    """
    Apply not-taken branch prediction optimization for OpenPOWER.

    OpenPOWER branches:
    - b/ba/bl/bla: Unconditional branches
    - bc/bcl/bclr/bclrl/bcctr/bcctrl: Conditional branches
    """
    print("\n" + "=" * 70)
    print("APPLYING BRANCH PREDICTION (NOT-TAKEN)")
    print("=" * 70)

    pc_node_id = 'pc_wr'
    pc_mux_id = 'pc_wr_mux'
    not_taken_input_id = 'pc_add_4'

    # Find a taken path representative (unconditional branch target)
    taken_input_id = 'b_target'  # or 'target' depending on how merger names it

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


def apply_hazard_resolution(graph, config, strategy: str = 'stall'):
    """
    Analyze and resolve data hazards for OpenPOWER.
    """
    print("\n" + "=" * 70)
    print("ANALYZING AND RESOLVING DATA HAZARDS")
    print(f"Strategy: {strategy.upper()}")
    print("=" * 70)

    # analyze_hazards() discovers both indexed (RF) and non-indexed (CR, LR, CTR, XER) hazards
    analyzer = HazardAnalyzer(graph, pc_name='pc')
    analyzer.identify_pipeline_stages()
    all_hazards = analyzer.analyze_hazards()

    # PC is the main element that needs to be held during stalls
    resolver = HazardResolver(graph, isa_states_to_gate=['pc_rd'], pipeline_config=config)

    if _engine == 'rust':
        # Rust engine handles hazards directly (hazards are dicts)
        if all_hazards:
            print(f"\nDetected {len(all_hazards)} RF data hazard(s):")
            for i, hazard in enumerate(all_hazards):
                print(f"  {i+1}. {hazard['write_access_node_id']} -> {hazard['read_access_node_id']}")
            success = resolver.resolve_all_hazards(all_hazards, strategy=strategy)
        else:
            print("No RF hazards detected by analyzer (expected for merged graphs)")
        graph = resolver.get_graph()
    else:
        # Python engine: unified path through analyze_hazards()
        # Separate indexed and non-indexed hazards for reporting and strategy assignment
        indexed_hazards = [h for h in all_hazards if h.is_indexed]
        individual_hazards = [h for h in all_hazards if not h.is_indexed]

        if indexed_hazards:
            print(f"\nDetected {len(indexed_hazards)} RF data hazard(s):")
            for i, hazard in enumerate(indexed_hazards):
                print(f"  {i+1}. {hazard.write_access_node.id} -> {hazard.read_access_node.id}")
                print(f"     Write at stage {hazard.write_stage} ({hazard.write_stage_name})")
                print(f"     Read at stage {hazard.read_stage} ({hazard.read_stage_name})")
                print(f"     Hazard distance: {hazard.get_forwarding_distance()}")

            # Set the resolution strategy for indexed hazards
            resolution_strategy = HazardResolutionStrategy.BYPASS if strategy == 'bypass' else HazardResolutionStrategy.STALL
            for hazard in indexed_hazards:
                hazard.resolution = resolution_strategy
        else:
            print("No RF hazards detected by analyzer (expected for merged graphs)")

        if individual_hazards:
            print(f"\nDetected {len(individual_hazards)} individual ISA state hazard(s):")
            for i, hazard in enumerate(individual_hazards):
                print(f"  {i+1}. {hazard}")

            # Individual hazards always use stalling (bypassing not yet supported)
            for hazard in individual_hazards:
                hazard.resolution = HazardResolutionStrategy.STALL
        else:
            print("No individual ISA state hazards detected")

        # Resolve all hazards through the unified path
        resolver.resolve_all_hazards(all_hazards)

    return True, resolver


def generate_pipelined_rtl(graph: ResourceGraph, backend: str, output_dir: str, config: PipelineConfig, hazard_strategy: str = 'stall'):
    """Generate RTL code for the pipelined processor."""
    print("\n" + "=" * 70)
    print(f"GENERATING {backend.upper()} TO {output_dir}")
    print("=" * 70)

    os.makedirs(output_dir, exist_ok=True)

    suffix = "_bypass" if hazard_strategy == 'bypass' else ""
    module_name = f"openpower_sfs_pipelined_{config.num_stages}stage{suffix}"

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

        pyrtl_block = gen_pyrtl(graph, module_name)

        tb_config = PyRTLTestbenchConfig(
            module_name=module_name,
            timeout_cycles=10000,
            imem_size=16384,
            umem_size=16384,
            arch='openpower'
        )

        output_path = Path(output_dir)
        files = generate_pyrtl_testbench_files(
            pyrtl_block,
            module_name=module_name,
            output_dir=output_path,
            config=tb_config,
            instructions=OPSFS_INSTRUCTIONS,
            arch='openpower'
        )

        verilog_file = output_path / f"{module_name}.v"
        with open(verilog_file, 'w') as f:
            pyrtl.output_to_verilog(f, block=pyrtl_block)
        files['verilog'] = verilog_file

        print(f"  Generated PyRTL design:")
        print(f"    {len(list(pyrtl_block.logic))} logic operations")
        print(f"    {len(list(pyrtl_block.wirevector_set))} wires")
        print(f"    {len(pyrtl_block.memblock_by_name)} memories")
        print(f"  Exported to Verilog: {verilog_file}")

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

            tb_files = generate_circt_testbench(str(sv_file), module_name, 'openpower', OPSFS_INSTRUCTIONS)
            print(f"  Generated testbench: {tb_files.get('testbench')}")
            print(f"  Generated test runner: {tb_files.get('test_runner')}")
        else:
            print(f"  firtool failed: {result.stderr[:200]}")

        return str(sv_file), module_name


def main(num_stages: int = 5, hazard_strategy: str = 'stall', write_read_fwd: bool = False,
         mem_min_latency: int = 1, mem_max_latency: int = 1, backend: str = 'verilog',
         enable_ras: bool = False, ras_depth: int = 8):
    """
    Main pipeline creation function for OpenPOWER SFS.

    Args:
        num_stages: Number of pipeline stages (2, 3, 4, or 5)
        hazard_strategy: 'stall' for stalling or 'bypass' for forwarding
        write_read_fwd: Enable write-to-read forwarding on register file
        mem_min_latency: Minimum memory latency cycles (default 1)
        mem_max_latency: Maximum memory latency cycles (default 1)
        backend: Output backend ('verilog', 'vhdl', 'pyrtl', 'circt')
        enable_ras: Enable Return Address Stack optimization
        ras_depth: RAS stack depth (default 8)
    """
    # Get pipeline configuration
    config = get_pipeline_config(num_stages)

    print("=" * 70)
    print(f"{num_stages}-STAGE PIPELINED OPENPOWER SFS PROCESSOR ({backend.upper()} backend)")
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
    # OpenPOWER SFS is 64-bit, so we transform to 64-bit port width
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
    if result.get('transformed'):
        print(f"  Memory transformation successful: {result.get('num_accesses_transformed', 0)} accesses transformed")
    else:
        print(f"  Memory transformation skipped: {result.get('reason', 'unknown')}")

    if _engine == 'rust':
        graph = mem_transform.get_graph()

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

    # Step 3.5: Wire variable latency memory signals
    print("\n" + "=" * 70)
    print("WIRING VARIABLE LATENCY MEMORY SIGNALS")
    print("=" * 70)
    if wire_memory_start_signal(graph, 'umem'):
        print("  umem start signal wired")
    else:
        print("  WARNING: Could not wire umem start signal")

    # Step 4: Apply hazard resolution
    success, resolver = apply_hazard_resolution(graph, config, strategy=hazard_strategy)

    # Step 5: Add control hazard handling
    # OpenPOWER conditional branch instructions and their condition signals
    # Note: bc/bcl/bclr/bclrl all use bc_take_branch, bcctr/bcctrl use bcctr_take_branch
    branch_conditions = {
        'bc': 'bc_take_branch',
        'bcl': 'bc_take_branch',
        'bclr': 'bc_take_branch',
        'bclrl': 'bc_take_branch',
        'bcctr': 'bcctr_take_branch',
        'bcctrl': 'bcctr_take_branch',
    }
    # OpenPOWER unconditional branches (always cause flush when enabled)
    # Use exact instruction names - these match the enable signal pattern
    jump_types = ['b', 'ba', 'bl', 'bla']
    resolver.add_control_hazard_handling(branch_conditions=branch_conditions, jump_types=jump_types, pc_mux_id='pc_wr_mux')

    # Step 6: Gate write enables with validity signals
    resolver.gate_write_enables_with_validity()

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
            # Don't add extra validity gating - the RAS already gates push/pop with
            # control_hazard_flush via ras_push_valid and ras_pop_valid signals.
            # Additional gating caused timing issues where valid calls/returns
            # were incorrectly suppressed.
            ras_return_enable = 'bclr_enable'
            ras_bl_enable = 'bl_enable'
            ras_bla_enable = 'bla_enable'
            print("  Using ungated enables for RAS (flush gating done in RAS logic)")

            # OpenPOWER call/return conventions:
            # - LR (Link Register) holds return address
            # - bl, bla - branch and link (calls) - always update LR
            # - bcl - branch conditional and link (conditional call)
            # - bclr - branch to LR (return when LK=0)
            # - bclrl - branch to LR and link (not a simple return)
            #
            # For RAS:
            # - Push on: bl, bla (and potentially bcl, bcctrl, bclrl)
            # - Pop on: bclr (LK=0, so doesn't update LR)

            ras_spec = RASSpec(
                call_specs=[
                    # bl - branch and link (unconditional call)
                    # Use validity-gated enable to prevent RAS corruption on flushed instructions
                    # Use PIPE_Decode_pc_add_4_PIPE (registered), NOT (pc + 4) (combinational)
                    # because when bl_enable fires in Decode, pc_rd has already advanced to
                    # the next fetch address. PIPE_Decode_pc_add_4_PIPE captured the correct
                    # return address (bl_addr + 4) at the end of the previous cycle.
                    CallSpec(
                        enable_node_id=ras_bl_enable,  # validity-gated
                        dest_reg_node_id=None,  # Always writes to LR
                        return_addr_node_id='PIPE_Decode_pc_add_4_PIPE'
                    ),
                    # bla - branch and link absolute (unconditional call)
                    CallSpec(
                        enable_node_id=ras_bla_enable,  # validity-gated
                        dest_reg_node_id=None,  # Always writes to LR
                        return_addr_node_id='PIPE_Decode_pc_add_4_PIPE'
                    ),
                ],
                return_specs=[
                    # bclr - branch conditional to LR (return when branch taken)
                    # Use validity-gated bclr_enable for RAS pop/prediction
                    # This prevents RAS from triggering on flushed instructions
                    # Misprediction is detected when:
                    # 1. Branch not taken (prediction was wrong)
                    # 2. Branch taken but wrong return address
                    ReturnSpec(
                        enable_node_id=ras_return_enable,  # validity-gated
                        src_reg_node_id=None,  # Always reads from LR
                        dest_reg_node_id=None  # LK=0, doesn't write
                    ),
                ],
                link_registers=[],  # OpenPOWER uses dedicated LR, not GPR
                ras_depth=ras_depth,
                ras_width=64,  # 64-bit addresses for OpenPOWER
                predicted_pc_node_id='predicted_pc',
                default_prediction_node_id=default_prediction_id,
                control_hazard_flush_node_id='control_hazard_flush',
                jalr_target_node_id='bclr_target',  # bclr target for misprediction
                # OpenPOWER bclr is CONDITIONAL - need to detect when branch not taken
                # bclr_branch_taken_execute = PIPE_Execute_bclr_enable_PIPE && bc_take_branch
                return_branch_taken_node_id='bclr_branch_taken_execute',
                # OpenPOWER has no delay slots. We tested both registered and combinational validity:
                # - Registered (PIPE_Decode_valid_PIPE): 85/88 (3 failures)
                # - Combinational (PIPE_Decode_valid_not_flush): 82/88 (6 failures)
                # Registered validity works better for some reason.
                use_combinational_validity=False,
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
    if backend == 'circt':
        output_dir = os.path.join(_project_root, f"examples/verilog/circt_openpower_sfs_pipelined_{config.num_stages}stage{suffix}")
    elif backend == 'pyrtl':
        output_dir = os.path.join(_project_root, f"examples/pyrtl/openpower_sfs_pipelined_{config.num_stages}stage{suffix}")
    elif backend == 'verilog':
        output_dir = os.path.join(_project_root, f"examples/verilog/openpower_sfs_pipelined_{config.num_stages}stage{suffix}")
    else:
        output_dir = os.path.join(_project_root, f"{backend}/openpower_sfs_pipelined_{config.num_stages}stage{suffix}")
    rtl_file, module_name = generate_pipelined_rtl(graph, backend, output_dir, config, hazard_strategy)

    # Step 9: Save the pipelined graph
    graph.save_to_file(os.path.join(output_dir, f"{module_name}.rgraph"))
    print(f"\nSaved pipelined graph to {output_dir}/{module_name}.rgraph")

    # Step 10: Generate testbench and run script (only for verilog backend)
    if backend == 'verilog':
        from isa.openpower.generators.generate_testbench_openpower import generate_testbench_openpower, generate_run_script

        dst_tb = os.path.join(output_dir, "simple_tb.sv")
        generate_testbench_openpower(rtl_file, dst_tb)
        print(f"  Created testbench: {dst_tb}")

        generate_run_script(output_dir, module_name)

    print("\n" + "=" * 70)
    print("PIPELINE CREATION COMPLETE")
    print("=" * 70)
    print(f"Generated files:")
    print(f"  - {rtl_file}")
    print(f"  - {output_dir}/{module_name}.rgraph")
    if backend == 'verilog':
        print(f"  - {output_dir}/simple_tb.sv")
        print(f"  - {output_dir}/run_tests.sh")
        print(f"\nNext steps:")
        print(f"  cd {output_dir}")
        print(f"  ./run_tests.sh")
    else:
        print(f"\nNext steps:")
        print(f"  Review generated output in {output_dir}/")

    return graph


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Create a pipelined OpenPOWER SFS processor.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python create_opsfs_pipeline.py              # Create 5-stage pipeline (default) with stalling
  python create_opsfs_pipeline.py --stages 5   # Create 5-stage pipeline with stalling
  python create_opsfs_pipeline.py --stages 4   # Create 4-stage pipeline with stalling
  python create_opsfs_pipeline.py --stages 3   # Create 3-stage pipeline with stalling
  python create_opsfs_pipeline.py --stages 2   # Create 2-stage pipeline with stalling
  python create_opsfs_pipeline.py --hazard-resolution bypass  # Use forwarding/bypassing
  python create_opsfs_pipeline.py -s 5 -hr bypass  # 5-stage with forwarding
  python create_opsfs_pipeline.py --mem-latency 1 5  # Memory latency 1-5 cycles
        """
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
        choices=['verilog', 'vhdl', 'pyrtl', 'circt'],
        help='Output backend: verilog (default), vhdl, pyrtl, or circt'
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
        default=[1, 1],
        metavar='CYCLES',
        help='Memory latency: single value for static latency, two values (MIN MAX) for random. Default: 1 (single-cycle)'
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
    parser.add_argument(
        '--engine', '-e',
        type=str,
        default='python',
        choices=['python', 'rust'],
        help='Engine: python (default) or rust'
    )

    args = parser.parse_args()

    _init_engine(args.engine)

    # Parse memory latency
    if len(args.mem_latency) == 1:
        mem_min = mem_max = args.mem_latency[0]
    elif len(args.mem_latency) >= 2:
        mem_min = args.mem_latency[0]
        mem_max = args.mem_latency[1]
    else:
        mem_min, mem_max = 1, 1

    graph = main(
        num_stages=args.stages,
        hazard_strategy=args.hazard_resolution,
        write_read_fwd=args.write_read_fwd,
        mem_min_latency=mem_min,
        mem_max_latency=mem_max,
        backend=args.backend,
        enable_ras=args.ras,
        ras_depth=args.ras_depth
    )
