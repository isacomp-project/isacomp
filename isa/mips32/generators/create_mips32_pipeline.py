#!/usr/bin/env python3
from __future__ import annotations
"""
Create a pipelined MIPS32 processor with configurable stages.

This script applies pipeline transformations to create 2, 3, 4, or 5-stage pipelines.
Pipeline cut decisions are made here by the architect.

Supports --engine python (default) or --engine rust for the Rust isacomp_core backend.
Supports Verilog, VHDL, PyRTL, and CIRCT backends via --backend argument.

Usage:
    python create_mips32_pipeline.py [--engine ENGINE] [--stages N] [--hazard-resolution STRATEGY] [--backend BACKEND]

Arguments:
    --engine ENGINE             Engine: 'python' or 'rust'. Default: python
    --stages N                  Number of pipeline stages (2, 3, 4, or 5). Default: 5
    --hazard-resolution STRATEGY  Hazard resolution strategy: 'stall' or 'bypass'. Default: stall
    --backend BACKEND           Output backend: 'verilog', 'vhdl', 'pyrtl', or 'circt'. Default: verilog
"""

import sys
import os
import argparse
import re
import shutil
# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

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
add_memory_access_arbiter = None
apply_branch_prediction_not_taken = None
# Python-only advanced features (set to None when using Rust engine)
ReadOnlyCacheSpec = None
apply_read_only_cache = None
wire_cache_start_signal = None
add_cache_latency_stalls = None
connect_cache_refill_to_memory = None
ReadWriteCacheSpec = None
apply_read_write_cache = None
wire_rwcache_start_signal = None
add_rwcache_latency_stalls = None
connect_rwcache_write_through = None
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
    global set_memory_variable_latency, wire_memory_start_signal, add_memory_access_arbiter
    global apply_branch_prediction_not_taken
    global ReadOnlyCacheSpec, apply_read_only_cache, wire_cache_start_signal
    global add_cache_latency_stalls, connect_cache_refill_to_memory
    global ReadWriteCacheSpec, apply_read_write_cache, wire_rwcache_start_signal
    global add_rwcache_latency_stalls, connect_rwcache_write_through
    global RASSpec, CallSpec, ReturnSpec, apply_return_address_stack
    global Node, Edge

    _engine = engine

    if engine == 'rust':
        # Add rust_core to path for isacomp_core
        _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
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
        add_memory_access_arbiter = None
        ReadOnlyCacheSpec = None
        apply_read_only_cache = None
        wire_cache_start_signal = None
        add_cache_latency_stalls = None
        connect_cache_refill_to_memory = None
        ReadWriteCacheSpec = None
        apply_read_write_cache = None
        wire_rwcache_start_signal = None
        add_rwcache_latency_stalls = None
        connect_rwcache_write_through = None
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
            add_memory_access_arbiter as _amaa,
        )
        from opt.memory.cache_optimization import (
            ReadOnlyCacheSpec as _ROCS, apply_read_only_cache as _AROC,
            wire_cache_start_signal as _WCSS, add_cache_latency_stalls as _ACLS,
            connect_cache_refill_to_memory as _CCRTM,
            ReadWriteCacheSpec as _RWCS, apply_read_write_cache as _ARWC,
            wire_rwcache_start_signal as _WRWCSS, add_rwcache_latency_stalls as _ARWCLS,
            connect_rwcache_write_through as _CRWCWT,
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
        add_memory_access_arbiter = _amaa
        apply_branch_prediction_not_taken = _abpnt
        ReadOnlyCacheSpec = _ROCS
        apply_read_only_cache = _AROC
        wire_cache_start_signal = _WCSS
        add_cache_latency_stalls = _ACLS
        connect_cache_refill_to_memory = _CCRTM
        ReadWriteCacheSpec = _RWCS
        apply_read_write_cache = _ARWC
        wire_rwcache_start_signal = _WRWCSS
        add_rwcache_latency_stalls = _ARWCLS
        connect_rwcache_write_through = _CRWCWT
        RASSpec = _RASS
        CallSpec = _CS
        ReturnSpec = _RS
        apply_return_address_stack = _aras
        Node = _Node
        Edge = _Edge

        print(f"  Using Python engine")

# MIPS32 instruction list for testbench generation
MIPS32_INSTRUCTIONS = [
    # R-type arithmetic
    'add', 'addu', 'sub', 'subu', 'slt', 'sltu',
    # R-type logical
    'and', 'or', 'xor', 'nor',
    # R-type shifts - immediate
    'sll', 'srl', 'sra',
    # R-type shifts - variable
    'sllv', 'srlv', 'srav',
    # I-type arithmetic/logical
    'addi', 'addiu', 'andi', 'ori', 'xori', 'slti', 'sltiu', 'lui',
    # Loads
    'lw', 'lh', 'lhu', 'lb', 'lbu',
    # Stores
    'sw', 'sh', 'sb',
    # Branches
    'beq', 'bne',
    # Jumps
    'j', 'jal', 'jr', 'jalr',
]


def get_mips32_instructions():
    """Get all MIPS32 base instructions."""
    mips32_dir = "isa/mips32"
    instructions = {}

    # Complete MIPS32 instruction set (excluding ll/sc atomic and mult/div)
    # This covers all instructions from the MIPS Green Sheet Core Instruction Set
    # plus additional useful instructions (xor, xori, sra, variable shifts, jalr, signed loads)
    base_instrs = [
        # R-type arithmetic (6)
        'add', 'addu', 'sub', 'subu', 'nor', 'slt', 'sltu',

        # R-type logical (4)
        'and', 'or', 'xor', 'nor',

        # R-type shifts - immediate (3)
        'sll', 'srl', 'sra',

        # R-type shifts - variable (3)
        'sllv', 'srlv', 'srav',

        # I-type arithmetic/logical (9)
        'addi', 'addiu', 'andi', 'ori', 'xori', 'slti', 'sltiu', 'lui',

        # Loads - word and subword (5)
        'lw', 'lh', 'lhu', 'lb', 'lbu',

        # Stores - word and subword (3)
        'sw', 'sh', 'sb',

        # Branches (2)
        'beq', 'bne',

        # Jumps (4)
        'j', 'jal', 'jr', 'jalr',
    ]

    for instr in base_instrs:
        isa_file = os.path.join(mips32_dir, f"{instr}.isa")
        if os.path.exists(isa_file):
            instructions[instr] = isa_file

    return instructions


def build_merged_graph():
    """Build merged graph of all MIPS32 instructions."""
    print("Building merged MIPS32 graph...")

    instructions = get_mips32_instructions()
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


def select_pipeline_cut_edges_generic(graph: ResourceGraph, config: PipelineConfig, icache: bool = False):
    """
    Select edges for each pipeline cut based on the pipeline configuration.

    This is a generic version that works with 2, 3, 4, or 5-stage pipelines.
    The cuts are selected based on which stages are present in the configuration.

    Args:
        graph: The resource graph
        config: Pipeline configuration
        icache: Whether instruction cache is enabled (affects instruction source)
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

    # Helper to find all nodes matching a suffix pattern
    def find_nodes_with_suffix(suffix):
        """Find all nodes that are exactly 'suffix' or end with '_suffix'."""
        nodes = []
        for node_id in graph.nodes:
            if node_id == suffix or node_id.endswith('_' + suffix):
                nodes.append(node_id)
        return nodes

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

        # Instruction word from umem (unified memory) or icache if cache is enabled
        if icache:
            # When icache is enabled, the instruction comes from icache_data_0
            # (the cache read data output, before NOP gating which happens later)
            eid = find_edge('icache_data_0', 'instr')
            if eid:
                cuts[decode_stage].append(eid)
                print(f"  [F/{decode_stage[0]}] icache_data_0 -> instr (via icache)")
        else:
            eid = find_edge('umem[pc]_rd', 'instr')
            if eid:
                cuts[decode_stage].append(eid)
                print(f"  [F/{decode_stage[0]}] umem[pc]_rd -> instr")

        # PC value needs to be pipelined alongside the instruction it fetched
        for eid, tgt in find_edges_from('pc_rd'):
            if '(pc +' in tgt and tgt != '(pc + 4)':
                cuts[decode_stage].append(eid)
                print(f"  [F/{decode_stage[0]}] pc_rd -> {tgt} (PC value for instruction)")

        # JAL return address - DON'T cut (pc + 8) -> pc_plus_8 here
        # pc_plus_8 needs to stay combinational for jump target calculation
        # The return address path to rf_write_data_mux is cut later

    # ========================================
    # CUT 2: D/X - Decode / Execute
    # ========================================
    # This cut is present in 4 and 5-stage pipelines
    if config.num_stages >= 4 and execute_stage in cuts and execute_stage != decode_stage:
        print(f"\nCUT 2: {decode_stage} -> {execute_stage}")
        print("-" * 50)

        # Register file read values (MIPS uses rs and rt)
        # Pipeline ALL outgoing edges from rf_rs_rd and rf_rt_rd to ensure
        # consistent timing in Execute stage for comparisons, ALU ops, etc.
        # The graph merger may create multiple consumers with different names
        # (e.g., r1, r2, add_r2, jump_dest, etc.)
        rf_read_nodes = ['rf[rs]_rd', 'rf[rt]_rd', 'rf_rs_rd', 'rf_rt_rd']
        for rf_rd_node in rf_read_nodes:
            if rf_rd_node in graph.nodes:
                for eid, tgt in find_edges_from(rf_rd_node):
                    cuts[execute_stage].append(eid)
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] {rf_rd_node} -> {tgt} (source reg value)")

        # Destination register index - pipeline the OUTPUT of rf_write_addr_mux
        # This computes the mux at Decode and pipelines the result, so hazard detection
        # can compare against the actual write address at each stage
        if 'rf_write_addr_mux' in graph.nodes:
            for eid, tgt in find_edges_from('rf_write_addr_mux'):
                cuts[execute_stage].append(eid)
                print(f"  [{decode_stage[0]}/{execute_stage[0]}] rf_write_addr_mux -> {tgt} (dest reg addr)")

        # PC for branch/jump calculations
        # NOTE: Only exclude (pc + 4) from cuts because:
        # - (pc + 4) is used for sequential PC increment (Fetch stage)
        # - (pc + 8) MUST be pipelined to Execute stage for JAL/JALR return address
        #   because the return address is PC+8 where PC is the JAL's address
        # Branch offset calculations also need the Execute-stage PC
        for eid, tgt in find_edges_from('pc_rd'):
            if '(pc +' in tgt and tgt != '(pc + 4)':
                cuts[execute_stage].append(eid)
                print(f"  [{decode_stage[0]}/{execute_stage[0]}] pc_rd -> {tgt} (PC for target calc)")

        # Sign-extended immediates - find ALL variants (addi_sign_ext_imm, lw_sign_ext_imm, etc.)
        # Also include zero_ext_imm for ANDI/ORI/XORI
        for node_id in graph.nodes:
            if node_id.endswith('sign_ext_imm') or node_id == 'zero_ext_imm':
                for eid, src in find_edges_to(node_id):
                    cuts[execute_stage].append(eid)
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] {src} -> {node_id} (immediate)")

        # Branch offset computations - SKIP pipelining these because they are computed
        # from already-pipelined sign_ext_imm values. Double-pipelining would cause timing issues.
        # The branch offset is derived from sign_ext_imm which is pipelined above.
        # branch_offsets = ['beq_branch_offset', 'bne_branch_offset']
        # for offset in branch_offsets:
        #     if offset in graph.nodes:
        #         for eid, src in find_edges_to(offset):
        #             cuts[execute_stage].append(eid)
        #             print(f"  [{decode_stage[0]}/{execute_stage[0]}] {src} -> {offset} (branch offset)")

        # JAL return address - DON'T cut (pc + 8) -> pc_plus_8 here
        # pc_plus_8 needs to stay combinational for jal_jump_addr calculation
        # The return address is pipelined via pc_plus_8 -> rf_write_data_mux cuts at E/M and M/W

        # All instruction enable signals
        # Skip enables that feed into rf_write_addr_mux since the mux is computed in Decode
        # Also skip sh_byte_enable/sb_byte_enable - these are computed at Memory stage from umem_write_addr_mux
        for node_id in graph.nodes:
            if node_id.endswith('_enable') and not node_id.startswith('rf_write'):
                # Skip byte enables - computed at Memory stage from address, not Decode
                if node_id in ['sh_byte_enable', 'sb_byte_enable']:
                    continue
                # Skip cache write-through byte enable - it's a cache output, not a pipeline signal
                if 'write_through_byte_enable' in node_id:
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} (cache output)")
                    continue
                # Skip cache_wt_enable - it's a cache write-through enable, must stay synchronized with cache outputs
                if node_id == 'cache_wt_enable':
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} (cache output)")
                    continue
                # Skip umem_write_enable for 4/5-stage - it's computed in Memory stage from Memory-stage enables
                # For 5-stage: Memory stage exists separately, umem_write_enable computed there
                # For 4-stage: MemoryWriteback combined, umem_write_enable computed there
                if node_id == 'umem_write_enable' and memory_stage != execute_stage:
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} (computed at {memory_stage} from store enables)")
                    continue
                for eid, tgt in find_edges_from(node_id):
                    # Skip edges to rf_*_enables - these should stay in Decode stage
                    # so the guarded enable is computed in Decode and travels with the instruction
                    # This includes rf_add_rd_enables and rf_rt_enables
                    # Note: Only skip RF enables, not umem enables which need to be pipelined
                    if tgt.startswith('rf_') and tgt.endswith('_enables'):
                        print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} -> {tgt} (rf enables stays at Decode)")
                        continue
                    # Skip edges to rf_write_addr_mux - the mux is computed in Decode
                    # and its output is pipelined, so the select signals must stay in Decode
                    if tgt == 'rf_write_addr_mux':
                        print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} -> {tgt} (mux select stays at Decode)")
                        continue
                    # Skip edges to rf_write_enable - it's the OR of guarded enables,
                    # computed in Decode and pipelined as a single combined signal
                    if tgt == 'rf_write_enable':
                        print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} -> {tgt} (rf_write_enable stays at Decode)")
                        continue
                    # Skip edges from umem guarded enables to umem_write_enable
                    # umem_write_enable should be computed directly at Memory stage (not pipelined)
                    if node_id.startswith('umem_') and node_id.endswith('_guarded_enable') and tgt == 'umem_write_enable':
                        print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} -> {tgt} (umem_write_enable computed at Memory)")
                        continue
                    # Skip edges to non-memory *_rd_enable nodes - these are read enable signals for hazard detection
                    # They must stay at Decode stage so stall logic uses the consumer instruction's enables
                    # BUT pipeline edges to umem_addr_rd_enable (load enables need to reach Memory)
                    if tgt.endswith('_rd_enable') and 'umem' not in tgt:
                        print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} -> {tgt} (non-memory rd_enable stays at Decode)")
                        continue
                    cuts[execute_stage].append(eid)
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] {node_id} -> {tgt} (control)")

        # Shamt for shift instructions (MIPS uses instr[10:6] for shamt)
        eid = find_edge('instr[10:6]', 'shamt')
        if eid:
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] instr[10:6] -> shamt")

        # Jump address for J/JAL instructions (instr[25:0] -> j_addr)
        # This MUST be pipelined so Execute stage uses the correct jump target
        eid = find_edge('instr[25:0]', 'j_addr')
        if eid:
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] instr[25:0] -> j_addr (jump target)")

        # LUI upper immediate ({imm, 16'b0} -> upper)
        # This MUST be pipelined so LUI in Execute uses its own immediate, not Decode's
        eid = find_edge("{imm, 16'b0}", 'upper')
        if eid:
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] {{imm, 16'b0}} -> upper (LUI immediate)")

        # Zero-extended immediate for ORI/ANDI/XORI
        # This MUST be pipelined so these instructions use their own immediate
        # The merger may create instruction-specific nodes, so search for any *zero_ext_imm* target
        for eid, src in find_edges_to('zero_ext_imm'):
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] {src} -> zero_ext_imm")
        for eid, src in find_edges_to('andi_zero_ext_imm'):
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] {src} -> andi_zero_ext_imm")
        for eid, src in find_edges_to('ori_zero_ext_imm'):
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] {src} -> ori_zero_ext_imm")
        for eid, src in find_edges_to('xori_zero_ext_imm'):
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] {src} -> xori_zero_ext_imm")

        # DON'T cut edges TO rf_write_enable - we want rf_write_enable to stay at Decode
        # and be pipelined as a single combined signal. Instead, cut FROM rf_write_enable.
        # Note: (add_rd != 0) -> rf_add_rd_guarded_enable and (rt != 0) -> rf_rt_guarded_enable
        # should NOT be cut here - they stay in Decode stage along with the rf_*_enables inputs
        # so the guarded enable is computed in Decode and pipelined along with the instruction

        # Cut edge FROM rf_write_enable to pipeline it to Execute stage
        for eid, tgt in find_edges_from('rf_write_enable'):
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] rf_write_enable -> {tgt} (pipeline combined enable)")

    # ========================================
    # CUT 3: X/M - Execute / Memory
    # ========================================
    # This cut is present in 5-stage pipelines ONLY
    if memory_stage in cuts and memory_stage != execute_stage and memory_stage != writeback_stage:
        print(f"\nCUT 3: {execute_stage} -> {memory_stage}")
        print("-" * 50)

        # Memory addresses - dynamically discover address nodes that connect to umem
        mem_addr_nodes = set()
        for node_id in graph.nodes:
            if node_id.endswith('_addr') or node_id == 'addr':
                for eid, tgt in find_edges_from(node_id):
                    if 'umem' in tgt and not tgt.endswith('_byte_offset') and not tgt.endswith('_halfword_select') and not tgt.endswith('_word_select'):
                        mem_addr_nodes.add(node_id)
        for addr_node in sorted(mem_addr_nodes):
            for eid, tgt in find_edges_from(addr_node):
                if 'umem' in tgt:
                    # Don't cut edges to byte_offset/halfword_select/word_select
                    # nodes - they should use the pre-pipeline address.
                    # These nodes are separately pipelined via the byte
                    # selection offset cuts below.
                    if tgt.endswith('_byte_offset') or tgt.endswith('_halfword_select') or tgt.endswith('_word_select'):
                        continue
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {addr_node} -> {tgt} (memory address)")

        # Byte offset nodes - dynamically find nodes that handle byte/halfword selection
        # These are created by memory_access_transform and have specific suffixes
        for node_id, node in graph.nodes.items():
            # Match nodes by suffix pattern (structural approach)
            is_byte_offset = node_id.endswith('_byte_offset')
            is_halfword_select = node_id.endswith('_halfword_select')
            is_word_select = node_id.endswith('_word_select')

            if is_byte_offset or is_halfword_select or is_word_select:
                for eid, tgt in find_edges_from(node_id):
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {node_id} -> {tgt} (byte selection offset)")

        # ALU results going to writeback mux
        alu_results = [
            'add_res', 'addu_res', 'sub_res', 'subu_res',
            'and_res', 'or_res', 'xor_res', 'nor_res',
            'sll_res', 'srl_res', 'sra_res', 'slt_res', 'sltu_res',
            'sllv_res', 'srlv_res', 'srav_res',
            'addi_res', 'addiu_res', 'andi_res', 'ori_res', 'xori_res',
            'slti_res', 'sltiu_res', 'lui_res', 'upper',
        ]
        for res in alu_results:
            for eid, tgt in find_edges_from(res):
                if tgt == 'rf_write_data_mux':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {res} -> rf_write_data_mux")

        # JAL/JALR return address - handles both merged (pc_plus_8) and split (jal_pc_plus_8, jalr_pc_plus_8) naming
        for pc_plus_8_node in find_nodes_with_suffix('pc_plus_8'):
            for eid, tgt in find_edges_from(pc_plus_8_node):
                if tgt == 'rf_write_data_mux':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {pc_plus_8_node} -> rf_write_data_mux")

        # Store data - dynamically discover store data nodes
        store_data_nodes = set()
        for node_id in graph.nodes:
            if node_id.endswith('_data') and any(node_id.startswith(p) or node_id == n for p, n in [('sw_', 'sw_data'), ('sh_', 'sh_halfword_data'), ('sb_', 'sb_byte_data')]):
                store_data_nodes.add(node_id)
            # Also catch r2 variants that Rust merger may use for store data
            if node_id.startswith('r2') and node_id in graph.nodes:
                for eid, tgt in find_edges_from(node_id):
                    if 'umem_write_data_mux' in tgt:
                        store_data_nodes.add(node_id)
        for store_data in sorted(store_data_nodes):
            if store_data in graph.nodes:
                for eid, tgt in find_edges_from(store_data):
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_data} -> {tgt} (store data to Memory)")

        # Store enables - cut to umem_write_data_mux, umem_write_addr_mux, umem_addr_enables, and guarded enables
        for store_enable in ['sb_enable', 'sh_enable', 'sw_enable']:
            for eid, tgt in find_edges_from(store_enable):
                if tgt == 'umem_write_data_mux':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_enable} -> {tgt} (store enable)")
                elif tgt == 'umem_write_addr_mux':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_enable} -> {tgt} (store enable to addr mux)")
                elif tgt == 'umem_write_enable':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_enable} -> {tgt} (store enable to guarded addr)")
                elif tgt == 'umem_sw_addr_guarded_enable':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_enable} -> {tgt} (sw enable to guarded enable)")

        # Load enables - pipeline to Memory stage for memory stall detection
        for load_enable in ['lb_enable', 'lh_enable', 'lw_enable', 'lbu_enable', 'lhu_enable']:
            for eid, tgt in find_edges_from(load_enable):
                if tgt == 'umem_addr_rd_enable':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {load_enable} -> {tgt} (load enable)")

        # Pipeline addr != 0 signals to Memory stage for guarded enables
        for addr_ne_0 in ['(sw_addr != 0)', '(lb_addr != 0)']:
            for eid, tgt in find_edges_from(addr_ne_0):
                cuts[memory_stage].append(eid)
                print(f"  [{execute_stage[0]}/{memory_stage[0]}] {addr_ne_0} -> {tgt} (address check to Memory)")

        # NOTE: sh_byte_enable/sb_byte_enable are computed at Memory stage from umem_write_addr_mux
        # so they don't need pipelining - they're already at the right stage

        # Store byte/halfword data
        for store_data in ['byte_data', 'halfword_data']:
            for eid, tgt in find_edges_from(store_data):
                if tgt == 'umem_write_data_mux':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_data} -> {tgt} (store data)")

        # Propagate dest reg index through Memory stage (pipeline the mux output)
        if 'rf_write_addr_mux' in graph.nodes:
            for eid, tgt in find_edges_from('rf_write_addr_mux'):
                cuts[memory_stage].append(eid)
                print(f"  [{execute_stage[0]}/{memory_stage[0]}] rf_write_addr_mux -> {tgt} (dest reg addr)")

        # Propagate enable signals to rf_write_data_mux
        for node_id in graph.nodes:
            if node_id.endswith('_enable') and not node_id.startswith('rf_write'):
                for eid, tgt in find_edges_from(node_id):
                    if tgt == 'rf_write_data_mux':
                        cuts[memory_stage].append(eid)
                        print(f"  [{execute_stage[0]}/{memory_stage[0]}] {node_id} -> {tgt} (propagate control)")

        # DON'T cut edges TO rf_write_enable - it's computed in Decode and pipelined as one signal
        # Cut edge FROM rf_write_enable to pipeline it to Memory stage
        for eid, tgt in find_edges_from('rf_write_enable'):
            cuts[memory_stage].append(eid)
            print(f"  [{execute_stage[0]}/{memory_stage[0]}] rf_write_enable -> {tgt} (pipeline combined enable)")

        print(f"  NOTE: pc_wr_mux inputs stay in {execute_stage} stage")
        print(f"  NOTE: Branch conditions stay in {execute_stage} - branches resolve in {execute_stage} stage")

    # ========================================
    # CUT 4: M/W - Memory / Writeback
    # ========================================
    # This cut is present in 5-stage pipelines
    if writeback_stage in cuts and writeback_stage != memory_stage:
        print(f"\nCUT 4: {memory_stage} -> {writeback_stage}")
        print("-" * 50)

        # Memory read results
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
                    cuts[writeback_stage].append(eid)
                    print(f"  [{memory_stage[0]}/{writeback_stage[0]}] {res} -> rf_write_data_mux")

        # ALU results propagated to Writeback
        alu_results_for_wb = [
            'add_res', 'addu_res', 'sub_res', 'subu_res',
            'and_res', 'or_res', 'xor_res', 'nor_res',
            'sll_res', 'srl_res', 'sra_res', 'slt_res', 'sltu_res',
            'sllv_res', 'srlv_res', 'srav_res',
            'addi_res', 'addiu_res', 'andi_res', 'ori_res', 'xori_res',
            'slti_res', 'sltiu_res', 'lui_res', 'upper',
        ]
        for res in alu_results_for_wb:
            for eid, tgt in find_edges_from(res):
                if tgt == 'rf_write_data_mux':
                    cuts[writeback_stage].append(eid)
                    print(f"  [{memory_stage[0]}/{writeback_stage[0]}] {res} -> rf_write_data_mux (propagate to WB)")

        # JAL/JALR return address propagated to Writeback - handles both merged and split naming
        for pc_plus_8_node in find_nodes_with_suffix('pc_plus_8'):
            for eid, tgt in find_edges_from(pc_plus_8_node):
                if tgt == 'rf_write_data_mux':
                    cuts[writeback_stage].append(eid)
                    print(f"  [{memory_stage[0]}/{writeback_stage[0]}] {pc_plus_8_node} -> rf_write_data_mux (propagate to WB)")

        # Propagate dest reg index through Writeback (pipeline the mux output)
        if 'rf_write_addr_mux' in graph.nodes:
            for eid, tgt in find_edges_from('rf_write_addr_mux'):
                cuts[writeback_stage].append(eid)
                print(f"  [{memory_stage[0]}/{writeback_stage[0]}] rf_write_addr_mux -> {tgt} (dest reg addr)")

        # Propagate enable signals to Writeback
        for node_id in graph.nodes:
            if node_id.endswith('_enable') and not node_id.startswith('rf_write'):
                for eid, tgt in find_edges_from(node_id):
                    if tgt == 'rf_write_data_mux':
                        cuts[writeback_stage].append(eid)
                        print(f"  [{memory_stage[0]}/{writeback_stage[0]}] {node_id} -> {tgt} (propagate control to WB)")

        # DON'T cut edges TO rf_write_enable - it's computed in Decode and pipelined as one signal
        # Cut edge FROM rf_write_enable to pipeline it to Writeback stage
        for eid, tgt in find_edges_from('rf_write_enable'):
            cuts[writeback_stage].append(eid)
            print(f"  [{memory_stage[0]}/{writeback_stage[0]}] rf_write_enable -> {tgt} (pipeline combined enable)")

    # For 4-stage pipeline, Memory/Writeback is combined
    elif writeback_stage == memory_stage and memory_stage in cuts and memory_stage != execute_stage:
        print(f"\nCUT 3: {execute_stage} -> {memory_stage} (Memory+Writeback combined)")
        print("-" * 50)

        # Memory addresses - dynamically discover address nodes that connect to umem
        mem_addr_nodes = set()
        for node_id in graph.nodes:
            if node_id.endswith('_addr') or node_id == 'addr':
                for eid, tgt in find_edges_from(node_id):
                    if 'umem' in tgt and not tgt.endswith('_byte_offset') and not tgt.endswith('_halfword_select') and not tgt.endswith('_word_select'):
                        mem_addr_nodes.add(node_id)
        for addr_node in sorted(mem_addr_nodes):
            for eid, tgt in find_edges_from(addr_node):
                if 'umem' in tgt:
                    # Don't cut edges to byte_offset/halfword_select/word_select
                    # nodes - they should use the pre-pipeline address.
                    # These nodes are separately pipelined via the byte
                    # selection offset cuts below.
                    if tgt.endswith('_byte_offset') or tgt.endswith('_halfword_select') or tgt.endswith('_word_select'):
                        continue
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {addr_node} -> {tgt} (memory address)")

        # Byte offset nodes - dynamically find nodes that handle byte/halfword selection
        for node_id, node in graph.nodes.items():
            is_byte_offset = node_id.endswith('_byte_offset')
            is_halfword_select = node_id.endswith('_halfword_select')
            is_word_select = node_id.endswith('_word_select')

            if is_byte_offset or is_halfword_select or is_word_select:
                for eid, tgt in find_edges_from(node_id):
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {node_id} -> {tgt} (byte selection)")

        # ALL results going to writeback mux
        all_results = [
            'add_res', 'addu_res', 'sub_res', 'subu_res',
            'and_res', 'or_res', 'xor_res', 'nor_res',
            'sll_res', 'srl_res', 'sra_res', 'slt_res', 'sltu_res',
            'sllv_res', 'srlv_res', 'srav_res',
            'addi_res', 'addiu_res', 'andi_res', 'ori_res', 'xori_res',
            'slti_res', 'sltiu_res', 'lui_res', 'upper',
        ]
        for res in all_results:
            for eid, tgt in find_edges_from(res):
                if tgt == 'rf_write_data_mux':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {res} -> rf_write_data_mux")

        # JAL/JALR return address - handles both merged (pc_plus_8) and split (jal_pc_plus_8, jalr_pc_plus_8) naming
        for pc_plus_8_node in find_nodes_with_suffix('pc_plus_8'):
            for eid, tgt in find_edges_from(pc_plus_8_node):
                if tgt == 'rf_write_data_mux':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {pc_plus_8_node} -> rf_write_data_mux")

        # Store data - dynamically discover store data nodes
        store_data_nodes = set()
        for node_id in graph.nodes:
            if node_id.endswith('_data') and any(node_id.startswith(p) or node_id == n for p, n in [('sw_', 'sw_data'), ('sh_', 'sh_halfword_data'), ('sb_', 'sb_byte_data')]):
                store_data_nodes.add(node_id)
            # Also catch r2 variants that Rust merger may use for store data
            if node_id.startswith('r2') and node_id in graph.nodes:
                for eid, tgt in find_edges_from(node_id):
                    if 'umem_write_data_mux' in tgt:
                        store_data_nodes.add(node_id)
        for store_data in sorted(store_data_nodes):
            if store_data in graph.nodes:
                for eid, tgt in find_edges_from(store_data):
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_data} -> {tgt} (store data to MemoryWriteback)")

        # Store enables - cut to umem_write_data_mux, umem_write_addr_mux, and guarded enables
        for store_enable in ['sb_enable', 'sh_enable', 'sw_enable']:
            for eid, tgt in find_edges_from(store_enable):
                if tgt == 'umem_write_data_mux':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_enable} -> {tgt} (store enable)")
                elif tgt == 'umem_write_addr_mux':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_enable} -> {tgt} (store enable to addr mux)")
                elif tgt == 'umem_write_enable':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_enable} -> {tgt} (store enable to guarded addr)")
                elif tgt == 'umem_sw_addr_guarded_enable':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_enable} -> {tgt} (sw enable to guarded enable)")

        # Pipeline addr != 0 signals to Memory stage for guarded enables
        for addr_ne_0 in ['(sw_addr != 0)', '(lb_addr != 0)']:
            for eid, tgt in find_edges_from(addr_ne_0):
                cuts[memory_stage].append(eid)
                print(f"  [{execute_stage[0]}/{memory_stage[0]}] {addr_ne_0} -> {tgt} (address check)")

        # Propagate dest reg index through MemoryWriteback (pipeline the mux output)
        if 'rf_write_addr_mux' in graph.nodes:
            for eid, tgt in find_edges_from('rf_write_addr_mux'):
                cuts[memory_stage].append(eid)
                print(f"  [{execute_stage[0]}/{memory_stage[0]}] rf_write_addr_mux -> {tgt} (dest reg addr)")

        # Propagate enable signals to rf_write_data_mux
        for node_id in graph.nodes:
            if node_id.endswith('_enable') and not node_id.startswith('rf_write'):
                for eid, tgt in find_edges_from(node_id):
                    if tgt == 'rf_write_data_mux':
                        cuts[memory_stage].append(eid)
                        print(f"  [{execute_stage[0]}/{memory_stage[0]}] {node_id} -> {tgt} (propagate control)")

        # DON'T cut edges TO rf_write_enable - it's computed in Decode and pipelined as one signal
        # Cut edge FROM rf_write_enable to pipeline it to MemoryWriteback stage
        for eid, tgt in find_edges_from('rf_write_enable'):
            cuts[memory_stage].append(eid)
            print(f"  [{execute_stage[0]}/{memory_stage[0]}] rf_write_enable -> {tgt} (pipeline combined enable)")

    # For 3-stage pipeline, Execute/Memory/Writeback is combined
    if config.num_stages == 3:
        combined_stage = execute_stage
        print(f"\nCUT 2: {decode_stage} -> {combined_stage} (Execute+Memory+Writeback combined)")
        print("-" * 50)

        # Register file read values - pipeline ALL outgoing edges from rf reads
        rf_read_nodes = ['rf[rs]_rd', 'rf[rt]_rd', 'rf_rs_rd', 'rf_rt_rd']
        for rf_rd_node in rf_read_nodes:
            if rf_rd_node in graph.nodes:
                for eid, tgt in find_edges_from(rf_rd_node):
                    cuts[combined_stage].append(eid)
                    print(f"  [{decode_stage[0]}/{combined_stage[0]}] {rf_rd_node} -> {tgt} (source reg value)")

        # Destination register index - pipeline the OUTPUT of rf_write_addr_mux
        if 'rf_write_addr_mux' in graph.nodes:
            for eid, tgt in find_edges_from('rf_write_addr_mux'):
                cuts[combined_stage].append(eid)
                print(f"  [{decode_stage[0]}/{combined_stage[0]}] rf_write_addr_mux -> {tgt} (dest reg addr)")

        # PC for branch/jump calculations
        for eid, tgt in find_edges_from('pc_rd'):
            if '(pc +' in tgt and tgt != '(pc + 4)':
                cuts[combined_stage].append(eid)
                print(f"  [{decode_stage[0]}/{combined_stage[0]}] pc_rd -> {tgt}")

        # Sign-extended immediates - find ALL variants
        for node_id in graph.nodes:
            if node_id.endswith('sign_ext_imm') or node_id == 'zero_ext_imm':
                for eid, src in find_edges_to(node_id):
                    cuts[combined_stage].append(eid)
                    print(f"  [{decode_stage[0]}/{combined_stage[0]}] {src} -> {node_id} (immediate)")

        # Zero-extended immediate for ORI/ANDI/XORI (per-instruction nodes from Rust merger)
        for imm_node in ['andi_zero_ext_imm', 'ori_zero_ext_imm', 'xori_zero_ext_imm']:
            if imm_node in graph.nodes:
                for eid, src in find_edges_to(imm_node):
                    cuts[combined_stage].append(eid)
                    print(f"  [{decode_stage[0]}/{combined_stage[0]}] {src} -> {imm_node}")

        # JAL return address - DO NOT cut (pc + 8) -> pc_plus_8 for 3-stage!
        # In 3-stage, pc_add_8 is computed from the PIPELINED PC (PIPE_ExecuteMemoryWriteback_PIPE_Decode_pc_rd_PIPE_PIPE)
        # so pc_plus_8 should directly use pc_add_8 without additional pipelining.
        # Cutting this edge would add an extra cycle of delay, giving wrong return addresses.
        print(f"  [{decode_stage[0]}/{combined_stage[0]}] SKIP (pc + 8) -> pc_plus_8 (pc_add_8 uses pipelined PC)")

        # All instruction enable signals (except those that stay at Decode)
        for node_id in graph.nodes:
            if node_id.endswith('_enable') and not node_id.startswith('rf_write'):
                # Skip byte enables - computed at ExecuteMemoryWriteback stage from umem_write_addr_mux, not Decode
                if node_id in ['sh_byte_enable', 'sb_byte_enable']:
                    print(f"  [{decode_stage[0]}/{combined_stage[0]}] SKIP {node_id} (byte enable computed at {combined_stage[0]} from address)")
                    continue
                # Skip cache write-through byte enable - it's a cache output, not a pipeline signal
                if 'write_through_byte_enable' in node_id:
                    print(f"  [{decode_stage[0]}/{combined_stage[0]}] SKIP {node_id} (cache output)")
                    continue
                # Skip cache_wt_enable - it's a cache write-through enable, must stay synchronized with cache outputs
                if node_id == 'cache_wt_enable':
                    print(f"  [{decode_stage[0]}/{combined_stage[0]}] SKIP {node_id} (cache output)")
                    continue
                for eid, tgt in find_edges_from(node_id):
                    # Skip non-memory rd_enable targets, but pipeline umem_addr_rd_enable
                    if '_rd_enable' in tgt and 'umem' not in tgt:
                        continue
                    # Skip edges to rf_*_enables - these should stay in Decode
                    if tgt.startswith('rf_') and tgt.endswith('_enables'):
                        print(f"  [{decode_stage[0]}/{combined_stage[0]}] SKIP {node_id} -> {tgt} (rf enables stays at Decode)")
                        continue
                    if tgt == 'rf_write_addr_mux':
                        print(f"  [{decode_stage[0]}/{combined_stage[0]}] SKIP {node_id} -> {tgt} (mux select stays at Decode)")
                        continue
                    if tgt == 'rf_write_enable':
                        print(f"  [{decode_stage[0]}/{combined_stage[0]}] SKIP {node_id} -> {tgt} (rf_write_enable stays at Decode)")
                        continue
                    # umem_write_enable should be computed directly from guarded enables (not pipelined)
                    if tgt == 'umem_write_enable':
                        print(f"  [{decode_stage[0]}/{combined_stage[0]}] SKIP {node_id} -> {tgt} (umem_write_enable computed at {combined_stage[0]})")
                        continue
                    cuts[combined_stage].append(eid)
                    print(f"  [{decode_stage[0]}/{combined_stage[0]}] {node_id} -> {tgt}")

        # Shamt for shift instructions
        eid = find_edge('instr[10:6]', 'shamt')
        if eid:
            cuts[combined_stage].append(eid)
            print(f"  [{decode_stage[0]}/{combined_stage[0]}] instr[10:6] -> shamt")

        # Jump address for J/JAL instructions
        eid = find_edge('instr[25:0]', 'j_addr')
        if eid:
            cuts[combined_stage].append(eid)
            print(f"  [{decode_stage[0]}/{combined_stage[0]}] instr[25:0] -> j_addr (jump target)")

        # LUI upper immediate
        eid = find_edge("{imm, 16'b0}", 'upper')
        if eid:
            cuts[combined_stage].append(eid)
            print(f"  [{decode_stage[0]}/{combined_stage[0]}] {{imm, 16'b0}} -> upper (LUI immediate)")

        # Note: Store data (sw_data, sh_halfword_data, sb_byte_data) should NOT be pipelined
        # because they're already derived from pipelined register file reads (rf[rt]).
        # Pipelining them again would delay store data by an extra cycle.

        # Cut edge FROM rf_write_enable to pipeline the combined signal
        for eid, tgt in find_edges_from('rf_write_enable'):
            cuts[combined_stage].append(eid)
            print(f"  [{decode_stage[0]}/{combined_stage[0]}] rf_write_enable -> {tgt} (pipeline combined enable)")

    # For 2-stage pipeline
    if config.num_stages == 2:
        combined_stage = execute_stage
        print(f"\nCUT 1: FetchDecode -> {combined_stage} (single cut, 2-stage pipeline)")
        print("-" * 50)

        # Register file read values - pipeline ALL outgoing edges from rf reads
        rf_read_nodes = ['rf[rs]_rd', 'rf[rt]_rd', 'rf_rs_rd', 'rf_rt_rd']
        for rf_rd_node in rf_read_nodes:
            if rf_rd_node in graph.nodes:
                for eid, tgt in find_edges_from(rf_rd_node):
                    cuts[combined_stage].append(eid)
                    print(f"  [FD/{combined_stage[0]}] {rf_rd_node} -> {tgt} (source reg value)")

        # Destination register index - pipeline the OUTPUT of rf_write_addr_mux
        if 'rf_write_addr_mux' in graph.nodes:
            for eid, tgt in find_edges_from('rf_write_addr_mux'):
                cuts[combined_stage].append(eid)
                print(f"  [FD/{combined_stage[0]}] rf_write_addr_mux -> {tgt} (dest reg addr)")

        # PC for branch/jump calculations
        for eid, tgt in find_edges_from('pc_rd'):
            if '(pc +' in tgt and tgt != '(pc + 4)':
                cuts[combined_stage].append(eid)
                print(f"  [FD/{combined_stage[0]}] pc_rd -> {tgt}")

        # Sign-extended immediates - find ALL variants
        for node_id in graph.nodes:
            if node_id.endswith('sign_ext_imm') or node_id == 'zero_ext_imm':
                for eid, src in find_edges_to(node_id):
                    cuts[combined_stage].append(eid)
                    print(f"  [FD/{combined_stage[0]}] {src} -> {node_id} (immediate)")

        # Zero-extended immediate for ORI/ANDI/XORI (per-instruction nodes from Rust merger)
        for imm_node in ['andi_zero_ext_imm', 'ori_zero_ext_imm', 'xori_zero_ext_imm']:
            if imm_node in graph.nodes:
                for eid, src in find_edges_to(imm_node):
                    cuts[combined_stage].append(eid)
                    print(f"  [FD/{combined_stage[0]}] {src} -> {imm_node}")

        # JAL return address - DO NOT cut (pc + 8) -> pc_plus_8 for 2-stage!
        # pc_add_8 is calculated from the pipelined PC (PIPE_ExecuteMemoryWriteback_pc_rd_PIPE)
        # and is itself pipelined, so pc_plus_8 references PIPE_ExecuteMemoryWriteback_pc_add_8_PIPE.
        # Cutting this edge would add an extra cycle of delay.
        print(f"  [FD/{combined_stage[0]}] SKIP (pc + 8) -> pc_plus_8 (pc_add_8 uses pipelined PC)")

        # All instruction enable signals (except those that stay at Decode)
        for node_id in graph.nodes:
            if node_id.endswith('_enable') and not node_id.startswith('rf_write') and node_id != 'umem_write_enable':
                # Skip byte enables - computed at ExecuteMemoryWriteback stage from umem_write_addr_mux, not FetchDecode
                if node_id in ['sh_byte_enable', 'sb_byte_enable']:
                    print(f"  [FD/{combined_stage[0]}] SKIP {node_id} (byte enable computed at {combined_stage[0]} from address)")
                    continue
                # Skip cache write-through byte enable - it's a cache output, not a pipeline signal
                if 'write_through_byte_enable' in node_id:
                    print(f"  [FD/{combined_stage[0]}] SKIP {node_id} (cache output)")
                    continue
                # Skip cache_wt_enable - it's a cache write-through enable, must stay synchronized with cache outputs
                if node_id == 'cache_wt_enable':
                    print(f"  [FD/{combined_stage[0]}] SKIP {node_id} (cache output)")
                    continue
                for eid, tgt in find_edges_from(node_id):
                    # Skip edges to non-memory _rd_enable (umem, rf) - those stay at Decode
                    # BUT pipeline edges to umem_addr_rd_enable (load enables need to reach Memory)
                    if '_rd_enable' in tgt and 'umem' not in tgt:
                        print(f"  [FD/{combined_stage[0]}] SKIP {node_id} -> {tgt} (non-memory read enable stays at Decode)")
                        continue
                    # Skip edges to rf_*_enables
                    if tgt.startswith('rf_') and tgt.endswith('_enables'):
                        print(f"  [FD/{combined_stage[0]}] SKIP {node_id} -> {tgt} (rf enables stays at Decode)")
                        continue
                    if tgt == 'rf_write_addr_mux':
                        print(f"  [FD/{combined_stage[0]}] SKIP {node_id} -> {tgt} (mux select stays at Decode)")
                        continue
                    if tgt == 'rf_write_enable':
                        print(f"  [FD/{combined_stage[0]}] SKIP {node_id} -> {tgt} (rf_write_enable stays at Decode)")
                        continue
                    if tgt == 'umem_write_enable':
                        print(f"  [FD/{combined_stage[0]}] SKIP {node_id} -> {tgt} (umem_write_enable stays at Decode)")
                        continue
                    cuts[combined_stage].append(eid)
                    print(f"  [FD/{combined_stage[0]}] {node_id} -> {tgt}")

        # Shamt for shift instructions
        eid = find_edge('instr[10:6]', 'shamt')
        if eid:
            cuts[combined_stage].append(eid)
            print(f"  [FD/{combined_stage[0]}] instr[10:6] -> shamt")

        # Jump address for J/JAL instructions
        eid = find_edge('instr[25:0]', 'j_addr')
        if eid:
            cuts[combined_stage].append(eid)
            print(f"  [FD/{combined_stage[0]}] instr[25:0] -> j_addr (jump target)")

        # LUI upper immediate
        eid = find_edge("{imm, 16'b0}", 'upper')
        if eid:
            cuts[combined_stage].append(eid)
            print(f"  [FD/{combined_stage[0]}] {{imm, 16'b0}} -> upper (LUI immediate)")

        # Note: Store data (sw_data, sh_halfword_data, sb_byte_data) should NOT be pipelined
        # because they're already derived from pipelined register file reads (rf[rt]).

        # Cut edge FROM rf_write_enable to pipeline the combined signal
        for eid, tgt in find_edges_from('rf_write_enable'):
            cuts[combined_stage].append(eid)
            print(f"  [FD/{combined_stage[0]}] rf_write_enable -> {tgt} (pipeline combined enable)")

        # Cut edge FROM umem_write_enable to pipeline the combined signal
        for eid, tgt in find_edges_from('umem_write_enable'):
            cuts[combined_stage].append(eid)
            print(f"  [FD/{combined_stage[0]}] umem_write_enable -> {tgt} (pipeline combined enable)")

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
    # This ensures correct pipeline ordering even if uarch_time inference is unreliable
    stage_order = [cut.name for cut in config.cuts]
    stage_indices = {cut.name: cut.stage_index for cut in config.cuts}
    transform.set_stage_order(stage_order, stage_indices)
    print(f"  Using explicit stage order: {stage_order}")

    # Build cut specifications using the actual stage order from config
    cut_specs = []
    for stage_index, cut in enumerate(config.cuts):
        stage_name = cut.name
        if stage_name in cuts and cuts[stage_name]:
            cut_specs.append({
                'edges': cuts[stage_name],
                'after_stage': stage_name,
                'stage_index': stage_index + 1  # +1 because stage 0 is the initial fetch stage
            })
            print(f"  Stage {stage_name} (index={stage_index + 1}): {len(cuts[stage_name])} edges to cut")

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
    Apply not-taken branch prediction optimization.

    Architectural design for MIPS:
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
    # For MIPS, we need to find the appropriate taken input
    # Could be j_jump_addr, beq_branch_dest, or similar
    taken_input_id = 'j_jump_addr'  # Representative taken path

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
    """Analyze and resolve data hazards using stalling or bypassing."""
    print("\n" + "=" * 70)
    print("ANALYZING AND RESOLVING DATA HAZARDS")
    print(f"Strategy: {strategy.upper()}")
    print("=" * 70)

    analyzer = HazardAnalyzer(graph, pc_name='pc')
    analyzer.identify_pipeline_stages()
    hazards = analyzer.analyze_hazards()

    if hazards:
        print(f"\nDetected {len(hazards)} data hazard(s):")
        if _engine == 'rust':
            for i, hazard in enumerate(hazards):
                print(f"  {i+1}. {hazard['write_access_node_id']} -> {hazard['read_access_node_id']}")
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
            success = resolver.resolve_all_hazards(hazards, strategy=strategy)
        else:
            # Set the resolution strategy for all hazards
            resolution_strategy = HazardResolutionStrategy.BYPASS if strategy == 'bypass' else HazardResolutionStrategy.STALL
            for hazard in hazards:
                hazard.resolution = resolution_strategy
            # Use the resolver's resolve_all_hazards which handles sorting and priority
            success = resolver.resolve_all_hazards(hazards)

        return success, resolver
    else:
        print("No hazards detected by analyzer (expected for merged graphs)")
        resolver = HazardResolver(graph, isa_states_to_gate=['pc_rd'], pipeline_config=config)
        return True, resolver


def generate_pipelined_rtl(graph: ResourceGraph, backend: str, output_dir: str, config: PipelineConfig, hazard_strategy: str = 'stall'):
    """Generate RTL code for the pipelined processor with specified backend."""
    print("\n" + "=" * 70)
    print(f"GENERATING {backend.upper()} TO {output_dir}")
    print("=" * 70)

    os.makedirs(output_dir, exist_ok=True)

    # Use stage count and hazard strategy in module name for differentiation
    suffix = "_bypass" if hazard_strategy == 'bypass' else ""
    module_name = f"mips32_pipelined_{config.num_stages}stage{suffix}"

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
        config = PyRTLTestbenchConfig(
            module_name=module_name,
            timeout_cycles=10000,
            imem_size=4096,
            dmem_size=4096,
            arch='mips32'
        )

        # Generate testbench files with instructions list for test runner
        output_path = Path(output_dir)
        files = generate_pyrtl_testbench_files(
            pyrtl_block,
            module_name=module_name,
            output_dir=output_path,
            config=config,
            instructions=MIPS32_INSTRUCTIONS,
            arch='mips32'
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
            # Post-process for Verilator compatibility
            with open(sv_file, 'r') as f:
                content = f.read()
            content = re.sub(r'reg\s+\[(\d+):0\]\[(\d+):0\]\s+umem;', r'reg [\2:0] umem [0:\1];', content)
            with open(sv_file, 'w') as f:
                f.write(content)
            print(f"  Generated SystemVerilog: {sv_file}")
            print("  Post-processed for Verilator compatibility")

            tb_files = generate_circt_testbench(str(sv_file), module_name, 'mips32', MIPS32_INSTRUCTIONS)
            print(f"  Generated testbench: {tb_files.get('testbench')}")
            print(f"  Generated test runner: {tb_files.get('test_runner')}")
        else:
            print(f"  firtool failed: {result.stderr[:200]}")

        return str(sv_file), module_name


def main(num_stages: int = 5, hazard_strategy: str = 'stall', write_read_fwd: bool = False,
         mem_min_latency: int = 1, mem_max_latency: int = 1, backend: str = 'verilog',
         no_verify: bool = False,
         icache: bool = False, icache_size: int = 64, icache_assoc: int = 1,
         dcache: bool = False, dcache_size: int = 64, dcache_assoc: int = 1,
         enable_ras: bool = False, ras_depth: int = 8):
    """
    Main pipeline creation function.

    Args:
        num_stages: Number of pipeline stages (2, 3, 4, or 5)
        hazard_strategy: 'stall' for stalling or 'bypass' for forwarding
        write_read_fwd: Enable write-to-read forwarding on register file
        mem_min_latency: Minimum memory latency cycles (default 1)
        mem_max_latency: Maximum memory latency cycles (default 1)
        backend: Output backend ('verilog', 'circt', 'pyrtl')
        no_verify: Skip verification for VHDL backend
        icache: Enable instruction cache on umem
        icache_size: Number of cache rows (default 64)
        icache_assoc: Cache associativity (1=direct-mapped, 2/4/8=set-associative)
        dcache: Enable data cache on umem (for load/store)
        dcache_size: Number of cache rows (default 64)
        dcache_assoc: Cache associativity (1=direct-mapped, 2/4/8=set-associative)
        enable_ras: Enable Return Address Stack optimization
        ras_depth: RAS stack depth (default 8)
    """
    # Get pipeline configuration
    config = get_pipeline_config(num_stages)

    print("=" * 70)
    print(f"{num_stages}-STAGE PIPELINED MIPS32 PROCESSOR ({backend.upper()} backend)")
    print(f"Stages: {' -> '.join(config.stage_names)}")
    print(f"Hazard Resolution: {hazard_strategy.upper()}")
    print(f"Write-Read Forwarding: {'ENABLED' if write_read_fwd else 'DISABLED'}")
    if mem_min_latency == mem_max_latency:
        print(f"Memory Latency: {mem_min_latency} cycles (static)")
    else:
        print(f"Memory Latency: {mem_min_latency}-{mem_max_latency} cycles (random)")
    if icache:
        print(f"Instruction Cache: {icache_size} rows, {icache_assoc}-way associative")
    if dcache:
        print(f"Data Cache: {dcache_size} rows, {dcache_assoc}-way associative")
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
    print("\n" + "=" * 70)
    print("APPLYING MEMORY PORT WIDTH TRANSFORMATION")
    print("=" * 70)
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

    if icache and apply_read_only_cache is None:
        print(f"\n  WARNING: --icache not supported with {_engine} engine, skipping")
        icache = False
    if dcache and apply_read_write_cache is None:
        print(f"\n  WARNING: --dcache not supported with {_engine} engine, skipping")
        dcache = False

    # Step 1.7: Add instruction cache if enabled
    if icache:
        print("\n" + "=" * 70)
        print("APPLYING INSTRUCTION CACHE")
        print("=" * 70)
        icache_spec = ReadOnlyCacheSpec(
            memory_name='umem',
            cache_name='icache',
            block_size=32,  # 32-byte cache lines
            associativity=icache_assoc,
            num_rows=icache_size,
            address_width=32,
            data_width=32,
            replacement_policy='lru' if icache_assoc > 1 else 'lru',
            cached_ports=['pc']  # Only cache instruction fetches (umem[pc])
        )
        success = apply_read_only_cache(graph, icache_spec)
        if success:
            print(f"  Instruction cache applied: {icache_size} rows, {icache_assoc}-way")
            # Wire cache control signals
            wire_cache_start_signal(graph, 'icache')
        else:
            print("  WARNING: Failed to apply instruction cache")

    # Step 1.8: Add data cache if enabled
    if dcache:
        print("\n" + "=" * 70)
        print("APPLYING DATA CACHE (WRITE-THROUGH)")
        print("=" * 70)
        dcache_spec = ReadWriteCacheSpec(
            memory_name='umem',
            cache_name='dcache',
            block_size=4,  # 4-byte cache lines (1 word per line for single-word memory interface)
            associativity=dcache_assoc,
            num_rows=dcache_size,
            address_width=32,
            data_width=32,
            replacement_policy='lru' if dcache_assoc > 1 else 'lru',
            # Pattern 'addr' matches load/store addresses (umem[addr]) but NOT 'pc'
            # MIPS uses lb_addr for loads, sw_addr for stores
            cached_read_ports=['addr'],    # Cache load reads (LW/LH/LB/LBU/LHU)
            cached_write_ports=['addr'],   # Cache store writes (SW/SH/SB)
            write_allocate=False,          # No-allocate on write miss
            write_read_fwd=False,          # No same-cycle forwarding
        )
        success = apply_read_write_cache(graph, dcache_spec)
        if success:
            print(f"  Data cache applied: {dcache_size} rows, {dcache_assoc}-way, write-through")
            # Wire cache control signals
            wire_rwcache_start_signal(graph, 'dcache')
        else:
            print("  WARNING: Failed to apply data cache")

    # Step 2: Select pipeline cut edges
    cuts = select_pipeline_cut_edges_generic(graph, config, icache=icache)

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

    # Connect icache refill to umem access_enable (must be after wire_memory_start_signal)
    if icache:
        if connect_cache_refill_to_memory(graph, 'icache', 'umem'):
            print("  icache refill connected to umem access_enable")
        else:
            print("  WARNING: Could not connect icache refill to umem")

    # Connect dcache refill and write-through to umem
    if dcache:
        if connect_cache_refill_to_memory(graph, 'dcache', 'umem'):
            print("  dcache refill connected to umem access_enable")
        else:
            print("  WARNING: Could not connect dcache refill to umem")
        if connect_rwcache_write_through(graph, 'dcache', 'umem'):
            print("  dcache write-through connected to umem")
        else:
            print("  WARNING: Could not connect dcache write-through to umem")

    # Add memory access arbiter if multiple caches share umem
    if icache and dcache:
        if add_memory_access_arbiter(graph, 'umem'):
            print("  umem access arbiter configured")
        else:
            print("  WARNING: Could not add umem access arbiter")

    # Add cache latency stalls BEFORE hazard resolution so _add_automatic_cache_stalls can find them
    if icache:
        if add_cache_latency_stalls(graph, 'icache', stage_name='Fetch'):
            print("  icache latency stalls configured")
        else:
            print("  WARNING: Could not add icache latency stalls")

    if dcache:
        if add_rwcache_latency_stalls(graph, 'dcache', stage_name='Memory'):
            print("  dcache latency stalls configured")
        else:
            print("  WARNING: Could not add dcache latency stalls")

    # Step 4: Apply hazard resolution
    # Note: Memory latency stalls are automatically added by resolve_all_hazards()
    # via _add_automatic_memory_latency_stalls() which ORs the memory stall condition
    # into the existing Decode stall controller.
    success, resolver = apply_hazard_resolution(graph, config, hazard_strategy)

    # Step 5: Add control hazard handling for MIPS branches
    # Use the correct stage names based on the pipeline configuration
    # MIPS conditional branches and their condition signals
    branch_conditions = {
        'beq': 'beq_res',
        'bne': 'bne_res',
    }
    # MIPS unconditional jumps (always cause flush when enabled)
    jump_types = ['j', 'jal', 'jr', 'jalr']

    # Determine the correct resolution stage based on pipeline depth
    # Branches resolve in the Execute stage (or combined ExecuteMemoryWriteback for 3-stage)
    if config.num_stages >= 4:
        resolution_stage = 'Execute'
        stage_order = ['Decode', 'Execute', 'Memory', 'Writeback']
    elif config.num_stages == 3:
        resolution_stage = 'ExecuteMemoryWriteback'
        stage_order = ['Decode', 'ExecuteMemoryWriteback']
    else:  # 2-stage
        resolution_stage = 'ExecuteMemoryWriteback'
        stage_order = ['FetchDecode', 'ExecuteMemoryWriteback']

    # Use the resolver from hazard resolution (already configured)
    resolver.add_control_hazard_handling(
        branch_conditions=branch_conditions,
        jump_types=jump_types,
        pc_mux_id='pc_wr_mux',
        resolution_stage=resolution_stage,
        stage_order_override=stage_order
    )

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
            # MIPS32 call/return conventions:
            # - $31 (ra) is the link register
            # - JAL always writes to $31, so it's always a call
            # - JALR writes to rd - if rd==31, it's a call
            # - JR jumps to rs - if rs==31, it's a return
            # - JALR can be a return if rs==31 and rd==0
            #
            # Note: MIPS uses PC+8 for return address (branch delay slot)
            # but we use PIPE_Decode_pc_add_4_PIPE (the pipelined PC+4 value)
            # since branch delay slots are not modeled in this implementation

            # Find return address node
            # IMPORTANT: For MIPS delay slots, the return address is PC+8 (skip delay slot).
            # At Decode stage when JAL is at address A:
            #   - pc_rd = A (the JAL's address from architectural state read)
            #   - The correct return address is A+8
            #
            # We must use the (pc + 8) node, NOT (pc + 4), because:
            # - (pc + 4) is computed from Fetch stage PC which stalls during hazards
            # - (pc + 8) is computed from pc_rd (architectural state) which is always correct
            return_addr_id = None
            for name in ['(pc + 8)', 'jal_pc_plus_8', 'jalr_pc_plus_8']:
                if name in graph.nodes:
                    return_addr_id = name
                    break
            if return_addr_id:
                print(f"  Using existing return address node: {return_addr_id}")

            if not return_addr_id:
                print("  ERROR: Could not find return address node for RAS")
                print("  Skipping RAS optimization")
            else:
                # For the merged graph, the node names after merging are:
                # - rs: the shared rs field
                # - add_rd: the merged rd field for R-type instructions (including JALR)
                # - jump_dest: the JALR target (rf[rs])
                # - jal_pc_plus_8/jalr_pc_plus_8: return addresses
                # - (pc + 4): sequential PC increment
                ras_spec = RASSpec(
                    call_specs=[
                        # JAL always links to $31 (hardcoded), so always a call
                        CallSpec(
                            enable_node_id='jal_enable',
                            dest_reg_node_id=None,  # JAL always writes to $31 - unconditional call
                            return_addr_node_id=return_addr_id
                        ),
                        # JALR can be a call when rd == 31
                        CallSpec(
                            enable_node_id='jalr_enable',
                            dest_reg_node_id='add_rd',  # Merged rd field for R-type
                            return_addr_node_id=return_addr_id
                        ),
                    ],
                    return_specs=[
                        # JR is a return when rs == 31 (no rd field at all)
                        ReturnSpec(
                            enable_node_id='jr_enable',
                            src_reg_node_id='rs',
                            dest_reg_node_id=None  # JR has no rd - skip rd==0 check
                        ),
                        # JALR is a return when rs == 31 and rd == 0
                        ReturnSpec(
                            enable_node_id='jalr_enable',
                            src_reg_node_id='rs',
                            dest_reg_node_id='add_rd'  # Merged rd field for R-type
                        ),
                    ],
                    link_registers=[31],  # $31 (ra) is the only link register in MIPS
                    ras_depth=ras_depth,
                    ras_width=32,  # 32-bit addresses for MIPS32
                    predicted_pc_node_id='predicted_pc',
                    default_prediction_node_id=default_prediction_id,
                    control_hazard_flush_node_id='control_hazard_flush',
                    jalr_target_node_id='jump_dest',  # JALR target for misprediction check
                )

                ras_success = apply_return_address_stack(graph, ras_spec)
                if ras_success:
                    print("  RAS optimization applied successfully")
                else:
                    print("  WARNING: RAS optimization could not be applied")

    # Step 8: Generate RTL with specified backend
    suffix = "_bypass" if hazard_strategy == 'bypass' else ""
    if backend == 'circt':
        output_dir = f"examples/verilog/circt_mips32_pipelined_{config.num_stages}stage{suffix}"
    elif backend == 'pyrtl':
        output_dir = f"examples/pyrtl/mips32_pipelined_{config.num_stages}stage{suffix}"
    elif backend == 'verilog':
        output_dir = f"examples/verilog/mips32_pipelined_{config.num_stages}stage{suffix}"
    else:
        output_dir = f"{backend}/mips32_pipelined_{config.num_stages}stage{suffix}"
    rtl_file, module_name = generate_pipelined_rtl(graph, backend, output_dir, config, hazard_strategy)

    # Save the graph
    graph.save_to_file(os.path.join(output_dir, f"{module_name}.rgraph"))
    print(f"\nSaved pipelined graph to {output_dir}/{module_name}.rgraph")

    # Step 9: Generate test infrastructure (only for verilog backend)
    if backend == 'verilog':
        # Generate simple testbench
        testbench_content = f'''`timescale 1ns/1ps
module simple_tb;
    reg clk, reset;
    wire [31:0] zero32 = 32'd0;

    {module_name} dut (
        .clk(clk),
        .reset(reset),
        .reset_pc_rd(zero32)
    );

    reg [31:0] pass_addr, fail_addr;
    integer i;
    always #5 clk = ~clk;

    initial begin
        clk = 0; reset = 1;
        if (!$value$plusargs("pass_addr=%h", pass_addr)) pass_addr = 32'hFFFFFFFF;
        if (!$value$plusargs("fail_addr=%h", fail_addr)) fail_addr = 32'hFFFFFFFE;
        // Memory initialization is done by the processor module itself
        repeat(3) @(posedge clk);
        reset = 0;
        for (i = 0; i < 50000; i = i + 1) begin
            @(posedge clk);
            if (dut.pc_rd == pass_addr) begin $display("TEST PASSED"); $finish; end
            if (dut.pc_rd == fail_addr) begin $display("TEST FAILED at pc=%h", dut.pc_rd); $finish; end
        end
        $display("TIMEOUT");
        $finish;
    end
endmodule
'''
        tb_file = os.path.join(output_dir, "simple_tb.sv")
        with open(tb_file, 'w') as f:
            f.write(testbench_content)
        print(f"  Created testbench: {tb_file}")

        # Generate run_all_tests.sh (only for verilog backend)
        run_script = f'''#!/bin/bash
# Run MIPS32 tests for {config.num_stages}-stage pipeline

SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
cd "$SCRIPT_DIR"

# Compile testbench if needed
if [ ! -f "mips32_tb" ] || [ "{module_name}.v" -nt "mips32_tb" ] || [ "simple_tb.sv" -nt "mips32_tb" ]; then
    echo "Compiling testbench..."
    iverilog -g2012 -o mips32_tb {module_name}.v simple_tb.sv
    if [ $? -ne 0 ]; then
        echo "ERROR: Compilation failed!"
        exit 1
    fi
fi

# Create empty rf.hex
python3 -c "
with open('rf.hex', 'w') as f:
    for i in range(32):
        f.write('00000000\\n')
"

TESTS_DIR="../../../isa/mips32/mips-tests/isa"
PASS=0
FAIL=0

# Base MIPS32 instruction tests (38 instructions)
# Must match MIPS32_INSTRUCTIONS list in this script
BASE_TESTS=(
    add addu sub subu slt sltu
    and or xor nor
    sll srl sra
    sllv srlv srav
    addi addiu andi ori xori slti sltiu lui
    lw lh lhu lb lbu
    sw sh sb
    beq bne
    j jal jr jalr
)

for testname in "${{BASE_TESTS[@]}}"; do
    hexfile="$TESTS_DIR/mips32-isacomp-$testname.hex"
    [ -f "$hexfile" ] || continue
    addrsfile="${{hexfile%.hex}}.addrs"

    [ -f "$addrsfile" ] || continue

    read PASS_ADDR FAIL_ADDR < "$addrsfile"

    # Convert Intel HEX to umem.hex (unified memory, 32-bit words)
    python3 -c "
data = {{}}
with open('$hexfile', 'r') as f:
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
    exit(1)

# Write umem (unified memory) - 8192 words (32-bit each)
# Both code and data share this unified address space
with open('umem.hex', 'w') as f:
    for word_idx in range(8192):
        word = 0
        addr = word_idx * 4
        for byte_offset in range(4):
            byte_addr = addr + byte_offset
            if byte_addr in data:
                word |= data[byte_addr] << (byte_offset * 8)
        f.write(f'{{word:08x}}\\n')
"

    echo -n "Testing $testname... "
    RESULT=$(timeout 5 ./mips32_tb +pass_addr=$PASS_ADDR +fail_addr=$FAIL_ADDR 2>&1)

    if echo "$RESULT" | grep -q "TEST PASSED"; then
        echo "PASS"
        ((PASS++))
    else
        echo "FAIL"
        ((FAIL++))
    fi
done

echo ""
echo "Results: $PASS passed, $FAIL failed"

# Exit with error if any tests failed or no tests passed
if [ $FAIL -gt 0 ]; then
    echo "FAILED: $FAIL test(s) failed"
    exit 1
fi

if [ $PASS -eq 0 ]; then
    echo "FAILED: No tests passed"
    exit 1
fi

echo "SUCCESS: All $PASS tests passed"
exit 0
'''
        script_file = os.path.join(output_dir, "run_all_tests.sh")
        with open(script_file, 'w') as f:
            f.write(run_script)
        os.chmod(script_file, 0o755)
        print(f"  Created test script: {script_file}")

    # Step 10: Save the pipelined graph
    graph.save_to_file(os.path.join(output_dir, f"{module_name}.rgraph"))
    print(f"\nSaved pipelined graph to {output_dir}/{module_name}.rgraph")

    print("\n" + "=" * 70)
    print("PIPELINE CREATION COMPLETE")
    print("=" * 70)
    print(f"Generated files:")
    print(f"  - {rtl_file}")
    print(f"  - {output_dir}/{module_name}.rgraph")
    if backend == 'verilog':
        print(f"  - {output_dir}/simple_tb.sv")
        print(f"  - {output_dir}/run_all_tests.sh")
        print(f"\nNext steps:")
        print(f"  cd {output_dir}")
        print(f"  ./run_all_tests.sh")
    else:
        print(f"\nNext steps:")
        print(f"  Review generated output in {output_dir}/")

    return graph


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Create a pipelined MIPS32 processor.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python create_mips32_pipeline.py              # Create 5-stage pipeline (default)
  python create_mips32_pipeline.py --stages 5   # Create 5-stage pipeline
  python create_mips32_pipeline.py --stages 4   # Create 4-stage pipeline
  python create_mips32_pipeline.py --stages 3   # Create 3-stage pipeline
  python create_mips32_pipeline.py --stages 2   # Create 2-stage pipeline
  python create_mips32_pipeline.py --hazard-resolution bypass  # Use forwarding/bypassing
  python create_mips32_pipeline.py --mem-latency 1 5  # Memory latency 1-5 cycles
  python create_mips32_pipeline.py --icache     # Enable instruction cache (64 rows, direct-mapped)
  python create_mips32_pipeline.py --icache --icache-size 128 --icache-assoc 2  # 128-row 2-way cache
  python create_mips32_pipeline.py --icache --dcache  # Enable both instruction and data caches
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
        help='Hazard resolution strategy: stall (default) or bypass (forwarding)'
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
        default=[2, 15],
        metavar='CYCLES',
        help='Memory latency: single value for static latency, two values (MIN MAX) for random. Default: 2 15'
    )
    parser.add_argument(
        '--icache',
        action='store_true',
        default=False,
        help='Enable instruction cache on umem'
    )
    parser.add_argument(
        '--icache-size',
        type=int,
        default=64,
        help='Number of cache rows (default: 64)'
    )
    parser.add_argument(
        '--icache-assoc',
        type=int,
        default=1,
        choices=[1, 2, 4, 8],
        help='Instruction cache associativity: 1=direct-mapped (default), 2/4/8=set-associative'
    )
    parser.add_argument(
        '--dcache',
        action='store_true',
        default=False,
        help='Enable data cache on umem (write-through policy)'
    )
    parser.add_argument(
        '--dcache-size',
        type=int,
        default=64,
        help='Number of data cache rows (default: 64)'
    )
    parser.add_argument(
        '--dcache-assoc',
        type=int,
        default=1,
        choices=[1, 2, 4, 8],
        help='Data cache associativity: 1=direct-mapped (default), 2/4/8=set-associative'
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
        icache=args.icache,
        icache_size=args.icache_size,
        icache_assoc=args.icache_assoc,
        dcache=args.dcache,
        dcache_size=args.dcache_size,
        dcache_assoc=args.dcache_assoc,
        enable_ras=args.ras,
        ras_depth=args.ras_depth
    )
