#!/usr/bin/env python3
"""
Create a pipelined RISC-V 32-bit processor with configurable stages.

This script applies pipeline transformations to create 2, 3, 4, or 5-stage pipelines.
Pipeline cut decisions are made here by the architect.

Supports --engine python (default) or --engine rust for the Rust isacomp_core backend.
Supports Verilog, VHDL, PyRTL, CIRCT, HardCaml, and Chisel backends via --backend argument.

Usage:
    python create_rv32i_pipeline.py [--engine ENGINE] [--stages N] [--hazard-resolution STRATEGY]

Arguments:
    --engine ENGINE             Engine: 'python' or 'rust'. Default: python
    --stages N                  Number of pipeline stages (2, 3, 4, or 5). Default: 5
    --hazard-resolution STRATEGY  Hazard resolution strategy: 'stall' or 'bypass'. Default: stall
    --backend BACKEND           Output backend: 'verilog', 'vhdl', 'pyrtl', 'circt', 'hardcaml', or 'chisel'. Default: verilog
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
# Declared here so that functions at module scope can reference them.
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
MemoryExternalizationSpec = None
apply_memory_externalization = None
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
BTBSpec = None
apply_branch_target_buffer = None
RegisterRenamingSpec = None
RegisterRenamingOptimization = None
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
    global MemoryExternalizationSpec, apply_memory_externalization
    global apply_branch_prediction_not_taken
    global ReadOnlyCacheSpec, apply_read_only_cache, wire_cache_start_signal
    global add_cache_latency_stalls, connect_cache_refill_to_memory
    global ReadWriteCacheSpec, apply_read_write_cache, wire_rwcache_start_signal
    global add_rwcache_latency_stalls, connect_rwcache_write_through
    global BTBSpec, apply_branch_target_buffer
    global RegisterRenamingSpec, RegisterRenamingOptimization
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
            print("  cd rust_core && cargo build --release && cp target/release/libisacomp_core.so isacomp_core.so")
            sys.exit(1)

        # Graph operations
        ResourceGraphMerger = None  # Not needed — merge_instructions() used directly
        PipelineTransform = _rc.PipelineTransform
        HazardAnalyzer = _rc.HazardAnalyzer
        HazardResolver = _rc.HazardResolver
        VerilogGenerator = _rc.VerilogGenerator
        MemoryAccessTransform = _rc.MemoryAccessTransform
        MemoryAccessTransformSpec = _rc.MemoryAccessTransformSpec
        get_pipeline_config = _rc.get_pipeline_config
        set_memory_variable_latency = _rc.set_memory_variable_latency
        wire_memory_start_signal = _rc.wire_memory_start_signal
        apply_branch_prediction_not_taken = _rc.apply_branch_prediction_not_taken
        apply_memory_externalization = _rc.apply_memory_externalization

        # PipelineStageMapper is pure Python — same for both engines
        from core.pipeline_config import PipelineStageMapper as _PSM
        PipelineStageMapper = _PSM

        # Advanced features — Rust function-based API with Python-compatible wrappers
        add_memory_access_arbiter = _rc.add_memory_access_arbiter
        wire_cache_start_signal = _rc.wire_cache_start_signal
        add_cache_latency_stalls = _rc.add_cache_latency_stalls
        connect_cache_refill_to_memory = _rc.connect_cache_refill_to_memory
        wire_rwcache_start_signal = _rc.wire_rwcache_start_signal
        add_rwcache_latency_stalls = _rc.add_rwcache_latency_stalls
        connect_rwcache_write_through = _rc.connect_rwcache_write_through
        Node = _rc.Node
        Edge = _rc.Edge

        # Wrapper classes to match Python API (class constructor → Rust function call)
        class ReadOnlyCacheSpec:
            def __init__(self, **kwargs):
                self._kwargs = kwargs
        class ReadWriteCacheSpec:
            def __init__(self, **kwargs):
                self._kwargs = kwargs

        def _apply_read_only_cache(graph, spec):
            return _rc.apply_read_only_cache(graph, **spec._kwargs)
        apply_read_only_cache = _apply_read_only_cache

        def _apply_read_write_cache(graph, spec):
            return _rc.apply_read_write_cache(graph, **spec._kwargs)
        apply_read_write_cache = _apply_read_write_cache

        # BTB — Rust apply_branch_target_buffer takes individual params
        class BTBSpec:
            def __init__(self, **kwargs):
                self._kwargs = kwargs
        def _apply_branch_target_buffer(graph, spec):
            k = spec._kwargs
            return _rc.apply_branch_target_buffer(
                graph,
                branch_enable_nodes=k['branch_enable_nodes'],
                branch_outcome_node=k['branch_outcome_node'],
                branch_target_node=k['branch_target_node'],
                fetch_pc_node=k['fetch_pc_node'],
                branch_pc_node=k['branch_pc_node'],
                predicted_pc_node_id=k['predicted_pc_node_id'],
                default_prediction_node_id=k['default_prediction_node_id'],
                control_hazard_flush_node_id=k['control_hazard_flush_node_id'],
                num_entries=k.get('num_entries', 64),
                pc_width=k.get('pc_width', 32),
            )
        apply_branch_target_buffer = _apply_branch_target_buffer

        # Register renaming — Rust uses function-based API
        apply_register_renaming = _rc.apply_register_renaming
        class RegisterRenamingSpec:
            def __init__(self, **kwargs):
                self._kwargs = kwargs
        class RegisterRenamingOptimization:
            def __init__(self, graph):
                self._graph = graph
            def apply(self, spec):
                return _rc.apply_register_renaming(self._graph, **spec._kwargs)

        # RAS — Rust uses function-based API
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
            add_memory_access_arbiter as _amaa,
        )
        from opt.memory.memory_externalization import MemoryExternalizationSpec as _MES, apply_memory_externalization as _AME
        from opt.memory.cache_optimization import (
            ReadOnlyCacheSpec as _ROCS, apply_read_only_cache as _AROC,
            wire_cache_start_signal as _WCSS, add_cache_latency_stalls as _ACLS,
            connect_cache_refill_to_memory as _CCRTM,
            ReadWriteCacheSpec as _RWCS, apply_read_write_cache as _ARWC,
            wire_rwcache_start_signal as _WRWCSS, add_rwcache_latency_stalls as _ARWCLS,
            connect_rwcache_write_through as _CRWCWT,
        )
        from opt.fetch.branch_target_buffer_optimization import BTBSpec as _BTBS, apply_branch_target_buffer as _ABTB
        from opt.ooo.register_renaming_optimization import RegisterRenamingSpec as _RRS, RegisterRenamingOptimization as _RRO

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
        MemoryExternalizationSpec = _MES
        apply_memory_externalization = _AME
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
        BTBSpec = _BTBS
        apply_branch_target_buffer = _ABTB
        RegisterRenamingSpec = _RRS
        RegisterRenamingOptimization = _RRO
        RASSpec = _RASS
        CallSpec = _CS
        ReturnSpec = _RS
        apply_return_address_stack = _aras
        Node = _Node
        Edge = _Edge

        print(f"  Using Python engine")


# Note: _init_engine() is called from __main__ or by callers before use.
# Not called at module level to allow importing without engine dependencies.

# RV32I instruction list for testbench generation
RV32I_INSTRUCTIONS = [
    # R-type
    'add', 'sub', 'and', 'or', 'xor', 'sll', 'srl', 'sra', 'slt', 'sltu',
    # I-type
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


def get_rv32i_instructions():
    """Get all RV32I base instructions."""
    rv32i_dir = os.path.join(_project_root, "isa/riscv32")
    instructions = {}

    base_instrs = [
        # R-type
        'add', 'sub', 'and', 'or', 'xor', 'sll', 'srl', 'sra', 'slt', 'sltu',
        # I-type
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
        # Fence (Zifencei extension - flushes icache)
        'fence_i',
    ]

    for instr in base_instrs:
        isa_file = os.path.join(rv32i_dir, f"{instr}.isa")
        if os.path.exists(isa_file):
            instructions[instr] = isa_file

    return instructions


def build_merged_graph():
    """Build merged graph of all RV32I instructions."""
    print(f"Building merged RV32I graph ({_engine} engine)...")

    instructions = get_rv32i_instructions()
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


def select_pipeline_cut_edges_generic(graph, config):
    """
    Select edges for each pipeline cut based on the pipeline configuration.

    This is a generic version that works with 3, 4, or 5-stage pipelines.
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

        # Instruction word from umem (unified memory) or icache if cache is enabled
        eid = find_edge('umem[pc]_rd', 'instr')
        if eid:
            cuts[decode_stage].append(eid)
            print(f"  [F/{decode_stage[0]}] umem[pc]_rd -> instr")
        else:
            # When icache is enabled, the instruction comes from icache_data_0
            # (the cache read data output, before NOP gating which happens later)
            eid = find_edge('icache_data_0', 'instr')
            if eid:
                cuts[decode_stage].append(eid)
                print(f"  [F/{decode_stage[0]}] icache_data_0 -> instr (via icache)")

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

        # Register file read values (r1/r2 may be instruction-prefixed like add_r1, sw_r2)
        for eid, tgt in find_edges_to_suffix('rf[rs1]_rd', 'r1'):
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] rf[rs1]_rd -> {tgt} (source reg 1 value)")

        for eid, tgt in find_edges_to_suffix('rf[rs2]_rd', 'r2'):
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] rf[rs2]_rd -> {tgt} (source reg 2 value)")

        # Destination register index - flows through subsequent stages
        for eid, tgt in find_edges_from('rd'):
            if tgt != '(rd != 0)':  # Comparison stays in Decode
                # Skip edges to renamer nodes - the renamer receives Decode-stage rd
                # for RAT lookup; the write allocation is controlled by a piped write_valid
                tgt_node = graph.nodes.get(tgt)
                if tgt_node and tgt_node.data.get('type') == 'renamer':
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP rd -> {tgt} (renamer stays at Decode)")
                    continue
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
                if node_id in ['sh_byte_enable', 'sb_byte_enable']:
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} (byte enable computed at {memory_stage} from address)")
                    continue
                # Skip cache write-through byte enable - it's a cache output, not a pipeline signal
                if 'write_through_byte_enable' in node_id:
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} (cache output)")
                    continue
                # Skip cache_wt_enable - it's a cache write-through enable, must stay synchronized with cache outputs
                if node_id == 'cache_wt_enable':
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} (cache output)")
                    continue
                # Skip umem_pc_rd_enable - it's for instruction fetch in Fetch stage, not data access
                if node_id == 'umem_pc_rd_enable':
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} (instruction fetch stays at Fetch)")
                    continue
                for eid, tgt in find_edges_from(node_id):
                    # Skip edges to _rd_enable (read enables stay at Decode)
                    # Exception: umem_addr_rd_enable needs to reach Memory for stall detection
                    if '_rd_enable' in tgt and tgt != 'umem_addr_rd_enable':
                        print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} -> {tgt} (read enable stays at Decode)")
                        continue
                    # Skip edges to rf_rd_ne_0_enables - it's computed at Decode from D-stage enables
                    if tgt == 'rf_rd_ne_0_enables':
                        print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} -> {tgt} (rf_rd_ne_0_enables stays at Decode)")
                        continue
                    # Skip edges to cache read_req nodes - dcache reads at Memory stage
                    # (consistent with non-cache memory read at Memory stage)
                    tgt_node = graph.nodes.get(tgt)
                    if tgt_node and tgt_node.data.get('type') == 'cache_read_req':
                        print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} -> {tgt} (cache read_req stays at Memory)")
                        continue
                    cuts[execute_stage].append(eid)
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] {node_id} -> {tgt} (control)")

        # Shamt for shift instructions
        eid = find_edge('instr[24:20]', 'shamt')
        if eid:
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] instr[24:20] -> shamt")

        # DON'T cut edges TO rf_rd_ne_0_guarded_enable - it stays at Decode
        # rf_rd_ne_0_guarded_enable = rf_rd_ne_0_enables && (rd != 0), computed at Decode
        # Instead, cut edges FROM rf_rd_ne_0_guarded_enable to pipeline the combined signal
        for eid, tgt in find_edges_from('rf_rd_ne_0_guarded_enable'):
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] rf_rd_ne_0_guarded_enable -> {tgt} (pipeline combined write enable)")

        # Pipeline (rd != 0) -> rf[rd]_wr write enable if it exists
        # (alternative write-enable structure used when guarded_enable is absent)
        eid = find_edge('(rd != 0)', 'rf[rd]_wr')
        if eid:
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] (rd != 0) -> rf[rd]_wr (write enable)")

        # Note: Store data (sb_byte_data, sh_halfword_data) are computed IN Execute stage from pipelined r2
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

        # Register file read values (r1/r2 may be instruction-prefixed like add_r1, sw_r2)
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
                if node_id in ['sh_byte_enable', 'sb_byte_enable']:
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} (byte enable computed at {execute_stage[0]} from address)")
                    continue
                # Skip cache write-through byte enable - it's a cache output, not a pipeline signal
                if 'write_through_byte_enable' in node_id:
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} (cache output)")
                    continue
                # Skip cache_wt_enable - it's a cache write-through enable, must stay synchronized with cache outputs
                if node_id == 'cache_wt_enable':
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] SKIP {node_id} (cache output)")
                    continue
                for eid, tgt in find_edges_from(node_id):
                    if '_rd_enable' in tgt or tgt == 'rf_rd_ne_0_enables' or tgt == 'umem_write_enable':
                        continue
                    cuts[execute_stage].append(eid)
                    print(f"  [{decode_stage[0]}/{execute_stage[0]}] {node_id} -> {tgt} (control)")

        # shamt
        eid = find_edge('instr[24:20]', 'shamt')
        if eid:
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] instr[24:20] -> shamt")

        # Combined enables
        for eid, tgt in find_edges_from('rf_rd_ne_0_guarded_enable'):
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] rf_rd_ne_0_guarded_enable -> {tgt}")

        for eid, tgt in find_edges_from('umem_write_enable'):
            cuts[execute_stage].append(eid)
            print(f"  [{decode_stage[0]}/{execute_stage[0]}] umem_write_enable -> {tgt}")

        # Memory addresses - skip for 3-stage where XMW are all combined
        # For 3-stage: lb_addr/sb_addr computed IN XMW from pipelined r1+imm, used IN XMW
        # For 4-stage: would cut here if Execute==Memory, but 4-stage has Execute!=Memory
        if execute_stage != writeback_stage:
            # Only apply for 4/5-stage pipelines, not 3-stage
            # Discover memory address nodes dynamically
            mem_addr_nodes_3s = set()
            for node_id in graph.nodes:
                if node_id.endswith('_addr'):
                    for eid, tgt in find_edges_from(node_id):
                        if 'umem' in tgt or 'byte_enable' in tgt or 'positioned' in tgt:
                            mem_addr_nodes_3s.add(node_id)
            for addr_node in sorted(mem_addr_nodes_3s):
                for eid, tgt in find_edges_from(addr_node):
                    if 'umem' in tgt or 'byte_enable' in tgt or 'positioned' in tgt:
                        cuts[execute_stage].append(eid)
                        print(f"  [{decode_stage[0]}/{execute_stage[0]}] {addr_node} -> {tgt} (memory address)")
        else:
            print(f"  NOTE: memory addresses not pipelined (computed and used within {execute_stage})")

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

        # Data cache read address: pipeline to Memory stage so cache reads
        # are synchronized with byte muxes and stall detection (matches
        # non-cache behavior where umem is read at Memory stage)
        for node_id in list(graph.nodes.keys()):
            if '_read_addr_' in node_id and not node_id.startswith('icache') and not node_id.startswith('imem'):
                for eid, src in find_edges_to(node_id):
                    src_node = graph.nodes.get(src)
                    if src_node:
                        src_type = src_node.data.get('type', '')
                        if src_type not in ('read_write_cache', 'read_only_cache'):
                            cuts[memory_stage].append(eid)
                            print(f"  [{execute_stage[0]}/{memory_stage[0]}] {src} -> {node_id} (cache read address)")

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
            'add_res', 'sub_res', 'and_res', 'or_res', 'xor_res',
            'sll_res', 'srl_res', 'sra_res', 'slt_res', 'sltu_res',
            'addi_res', 'andi_res', 'ori_res', 'xori_res',
            'slli_res', 'srli_res', 'srai_res', 'slti_res', 'sltiu_res',
            'lui_res', 'auipc_res',
        ]
        for res in alu_results:
            for eid, tgt in find_edges_from(res):
                if tgt == 'rf_write_data_mux':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {res} -> rf_write_data_mux")

        # Store data (r2 may be instruction-prefixed like sw_r2)
        for eid, src in find_edges_from_suffix('r2', 'umem_write_data_mux'):
            cuts[memory_stage].append(eid)
            print(f"  [{execute_stage[0]}/{memory_stage[0]}] {src} -> umem_write_data_mux (store data)")

        # Store enables - cut to umem_write_data_mux
        for store_enable in ['sb_enable', 'sh_enable', 'sw_enable']:
            for eid, tgt in find_edges_from(store_enable):
                if tgt == 'umem_write_data_mux':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_enable} -> {tgt} (store enable)")
                elif tgt == 'umem_write_enable':
                    # Also cut edges to umem write enable
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_enable} -> {tgt} (store enable to write)")

        # Load enables - pipeline to Memory stage for memory stall detection
        for load_enable in ['lb_enable', 'lh_enable', 'lw_enable', 'lbu_enable', 'lhu_enable']:
            for eid, tgt in find_edges_from(load_enable):
                if tgt == 'umem_addr_rd_enable':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {load_enable} -> {tgt} (load enable)")

        # Store byte/halfword data
        for store_data in ['sb_byte_data', 'sh_halfword_data']:
            for eid, tgt in find_edges_from(store_data):
                if tgt == 'umem_write_data_mux':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_data} -> {tgt} (store data)")

        # Store address to byte_enable nodes
        for eid, tgt in find_edges_from('sb_addr'):
            if 'byte_enable' in tgt or 'positioned' in tgt or 'shift' in tgt:
                cuts[memory_stage].append(eid)
                print(f"  [{execute_stage[0]}/{memory_stage[0]}] sb_addr -> {tgt} (store address to byte enable)")

        # Store data to positioned_data nodes
        for store_data in ['sb_byte_data', 'sh_halfword_data']:
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
            'add_res', 'sub_res', 'and_res', 'or_res', 'xor_res',
            'sll_res', 'srl_res', 'sra_res', 'slt_res', 'sltu_res',
            'addi_res', 'andi_res', 'ori_res', 'xori_res',
            'slli_res', 'srli_res', 'srai_res', 'slti_res', 'sltiu_res',
            'lui_res', 'auipc_res',
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
        mem_addr_nodes_4s = set()
        for node_id in graph.nodes:
            if node_id.endswith('_addr'):
                for eid, tgt in find_edges_from(node_id):
                    if 'umem' in tgt:
                        mem_addr_nodes_4s.add(node_id)
        for addr_node in sorted(mem_addr_nodes_4s):
            for eid, tgt in find_edges_from(addr_node):
                if 'umem' in tgt and not tgt.endswith('_byte_offset') and not tgt.endswith('_halfword_select') and not tgt.endswith('_word_select'):
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {addr_node} -> {tgt}")

        # Byte offset nodes - dynamically find nodes that handle byte/halfword selection
        for node_id, node in graph.nodes.items():
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
        ]
        for res in all_results:
            for eid, tgt in find_edges_from(res):
                if tgt == 'rf_write_data_mux':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {res} -> rf_write_data_mux")

        # Store data and control (r2 may be instruction-prefixed like sw_r2)
        for eid, src in find_edges_from_suffix('r2', 'umem_write_data_mux'):
            cuts[memory_stage].append(eid)
            print(f"  [{execute_stage[0]}/{memory_stage[0]}] {src} -> umem_write_data_mux")

        # Store enables - cut to umem_write_data_mux
        for store_enable in ['sb_enable', 'sh_enable', 'sw_enable']:
            for eid, tgt in find_edges_from(store_enable):
                if tgt == 'umem_write_data_mux':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_enable} -> {tgt} (store enable)")
                elif tgt == 'umem_write_enable':
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_enable} -> {tgt} (store enable to write)")

        for store_data in ['sb_byte_data', 'sh_halfword_data']:
            for eid, tgt in find_edges_from(store_data):
                if tgt == 'umem_write_data_mux' or 'zext' in tgt or 'positioned' in tgt:
                    cuts[memory_stage].append(eid)
                    print(f"  [{execute_stage[0]}/{memory_stage[0]}] {store_data} -> {tgt}")

        for eid, tgt in find_edges_from('sb_addr'):
            if 'byte_enable' in tgt or 'positioned' in tgt or 'shift' in tgt:
                cuts[memory_stage].append(eid)
                print(f"  [{execute_stage[0]}/{memory_stage[0]}] sb_addr -> {tgt}")

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

    if config.num_stages == 2:
        combined_stage = execute_stage  # This will be ExecuteMemoryWriteback
        print(f"\nCUT 1: FetchDecode -> {combined_stage} (single cut, 2-stage pipeline)")
        print("-" * 50)

        # Register file read values (r1/r2 may be instruction-prefixed like add_r1, sw_r2)
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
                if node_id in ['sh_byte_enable', 'sb_byte_enable']:
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

        # Shamt for shift instructions
        eid = find_edge('instr[24:20]', 'shamt')
        if eid:
            cuts[combined_stage].append(eid)
            print(f"  [FD/{combined_stage[0]}] instr[24:20] -> shamt")

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


def apply_pipeline_transforms(graph, cuts, config):
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


def apply_branch_prediction(graph, config):
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


def apply_hazard_resolution(graph, config, strategy: str = 'stall'):
    """
    Analyze and resolve data hazards.

    Args:
        graph: The resource graph to resolve hazards in
        config: Pipeline configuration
        strategy: 'stall' for stalling or 'bypass' for forwarding/bypassing

    Returns:
        (success, resolver) tuple
    """
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


def generate_pipelined_rtl(graph, backend: str, output_dir: str, config,
                          hazard_strategy: str = 'stall', externalize_memory: bool = False,
                          write_read_fwd: bool = False):
    """Generate RTL code for the pipelined processor with specified backend."""
    print("\n" + "=" * 70)
    print(f"GENERATING {backend.upper()} TO {output_dir}")
    print("=" * 70)

    os.makedirs(output_dir, exist_ok=True)

    # Use stage count and hazard strategy in module name for differentiation
    suffix = "_bypass" if hazard_strategy == 'bypass' else ""
    if write_read_fwd:
        suffix += "_wrf"
    ext_suffix = "_ext" if externalize_memory else ""
    module_name = f"riscv32i_pipelined_{config.num_stages}stage{suffix}{ext_suffix}"

    if backend == 'verilog':
        generator = VerilogGenerator(graph, module_name=module_name)
        verilog_code = generator.generate()

        verilog_file = os.path.join(output_dir, f"{module_name}.v")
        with open(verilog_file, 'w') as f:
            f.write(verilog_code)

        print(f"  Generated: {verilog_file}")
        print(f"  Lines: {len(verilog_code.splitlines())}")

        # Generate memory wrappers for externalized memories
        if externalize_memory and hasattr(generator, 'externalized_memories') and generator.externalized_memories:
            from pathlib import Path
            for mem_name in generator.externalized_memories:
                wrapper_code = generator.generate_memory_wrapper(mem_name)
                if wrapper_code:
                    wrapper_file = os.path.join(output_dir, f"{mem_name}_memory.v")
                    with open(wrapper_file, 'w') as f:
                        f.write(wrapper_code)
                    print(f"  Generated memory wrapper: {wrapper_file}")

        return verilog_file, module_name, generator
        
    elif backend == 'vhdl':
        from backends.vhdl import generate_vhdl

        vhdl_code = generate_vhdl(graph, entity_name=module_name)

        vhdl_file = os.path.join(output_dir, f"{module_name}.vhd")
        with open(vhdl_file, 'w') as f:
            f.write(vhdl_code)

        print(f"  Generated: {vhdl_file}")
        print(f"  Lines: {len(vhdl_code.splitlines())}")

        return vhdl_file, module_name, None
        
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
            arch='riscv32'
        )

        # Generate testbench files with instructions list for test runner
        output_path = Path(output_dir)
        files = generate_pyrtl_testbench_files(
            pyrtl_block,
            module_name=module_name,
            output_dir=output_path,
            config=config,
            instructions=RV32I_INSTRUCTIONS,
            arch='riscv32'
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

        return str(verilog_file), module_name, None

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

            tb_files = generate_circt_testbench(str(sv_file), module_name, 'riscv32', RV32I_INSTRUCTIONS)
            print(f"  Generated testbench: {tb_files.get('testbench')}")
            print(f"  Generated test runner: {tb_files.get('test_runner')}")
        else:
            print(f"  firtool failed: {result.stderr[:200]}")

        return str(sv_file), module_name, None

    elif backend == 'clash':
        from pathlib import Path

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Detect if this is a pipelined design by checking for pipeline registers
        has_pipeline_regs = any(
            n.data.get('type') == 'pipeline_register'
            for n in graph.nodes.values()
        )

        if has_pipeline_regs:
            from backends.clash.clash_graph_generator import generate_clash_pipeline
            clash_code = generate_clash_pipeline(graph, module_name)
        else:
            from backends.clash.clash_generator import generate_clash
            clash_code = generate_clash(graph, module_name)

        # Derive the canonical Haskell module name (same capitalization as
        # the Clash generators use) so the file name, build script, and
        # expected Verilog output path all agree.
        hs_module_name = module_name[0].upper() + module_name[1:] if module_name else "Processor"

        clash_file = output_path / f'{hs_module_name}.hs'
        with open(clash_file, 'w') as f:
            f.write(clash_code)

        line_count = len(clash_code.splitlines())
        print(f"  Generated: {clash_file}")
        print(f"  Lines: {line_count}")

        # Create a simple build script
        build_script = output_path / 'build.sh'
        with open(build_script, 'w') as f:
            f.write(f'''#!/bin/bash
# Build Clash-generated processor
cd "$(dirname "$0")"

echo "Compiling {hs_module_name}.hs with Clash..."
clash {hs_module_name}.hs --verilog

if [ $? -eq 0 ]; then
    echo "Verilog output in examples/verilog/{hs_module_name}.topEntity/"
else
    echo "Clash compilation failed"
    exit 1
fi
''')
        os.chmod(build_script, 0o755)
        print(f"  Created build script: {build_script}")

        # Copy test infrastructure (gen_tb.py, run_all_tests.sh)
        from backends.clash.testbench_generator import copy_test_infrastructure
        tb_files = copy_test_infrastructure(output_dir)
        for name, path in tb_files.items():
            print(f"  Copied {name} -> {path}")

        return str(clash_file), module_name, None

    elif backend == 'hardcaml':
        from pathlib import Path
        from backends.hardcaml import generate_hardcaml as gen_hardcaml

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Generate OCaml source
        ocaml_code = gen_hardcaml(graph, module_name)
        ml_file = output_path / f"{module_name}.ml"
        ml_file.write_text(ocaml_code)
        print(f"  Generated OCaml: {ml_file} ({len(ocaml_code):,} bytes)")

        # Generate dune build file
        dune_file = output_path / "dune"
        dune_content = f"""(executable
 (name {module_name})
 (libraries hardcaml))
"""
        dune_file.write_text(dune_content)

        # Generate dune-project file
        dune_project = output_path / "dune-project"
        dune_project.write_text("(lang dune 3.0)\n")
        print(f"  Generated dune build files")

        # Try to compile and produce Verilog
        import subprocess as sp

        ocaml_switch = os.environ.get('OCAML_SWITCH', '4.14.1')
        opam_env = {}
        try:
            env_result = sp.run(
                ["opam", "env", f"--switch={ocaml_switch}", "--set-switch"],
                capture_output=True, text=True, timeout=10
            )
            if env_result.returncode == 0:
                for line in env_result.stdout.strip().split('\n'):
                    if '=' in line and 'export' in line:
                        var_part = line.split(';')[0]
                        key, val = var_part.split('=', 1)
                        opam_env[key.strip()] = val.strip().strip("'\"")
        except (FileNotFoundError, sp.TimeoutExpired):
            # opam not installed or not responding; fall back to default environment
            pass

        build_env = os.environ.copy()
        build_env.update(opam_env)

        verilog_file = str(output_path / f"{module_name}.v")
        try:
            result = sp.run(
                ["dune", "build"],
                capture_output=True, text=True, timeout=120,
                cwd=str(output_path), env=build_env
            )
            if result.returncode == 0:
                print("  OCaml compilation successful!")
                run_result = sp.run(
                    ["dune", "exec", f"./{module_name}.exe"],
                    capture_output=True, text=True, timeout=60,
                    cwd=str(output_path), env=build_env
                )
                if run_result.returncode == 0:
                    with open(verilog_file, 'w') as f:
                        f.write(run_result.stdout)
                    print(f"  Generated Verilog via HardCaml: {verilog_file} ({len(run_result.stdout):,} bytes)")
                else:
                    print(f"  HardCaml execution failed:")
                    print(f"    {run_result.stderr[:1000]}")
            else:
                print(f"  OCaml compilation failed:")
                print(f"    {result.stderr[:1000]}")
        except FileNotFoundError:
            print("  dune not found in PATH, skipping compilation")
        except sp.TimeoutExpired:
            print("  Build timed out")
        except Exception as e:
            print(f"  Error during build: {e}")

        return verilog_file, module_name, None

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
            return str(scala_file), module_name, None

        classes_dir = output_path / "classes"
        try:
            print("  Compiling Scala with scalac...")
            compile_scala(scala_file, class_name, jar_dir, classes_dir)
            print("  Scala compilation successful")
        except Exception as e:
            print(f"  ERROR: Scala compilation failed: {e}")
            return str(scala_file), module_name, None

        firrtl_dir = output_path / "generated"
        try:
            firrtl_file = emit_firrtl(class_name, jar_dir, classes_dir, firrtl_dir)
        except Exception as e:
            print(f"  ERROR: FIRRTL emission failed: {e}")
            return str(scala_file), module_name, None

        try:
            print("  Converting FIRRTL to Verilog via firtool...")
            firrtl_to_verilog(firrtl_file, verilog_file)
            v_size = Path(verilog_file).stat().st_size
            print(f"  Generated Verilog: {verilog_file} ({v_size:,} bytes)")
        except Exception as e:
            print(f"  ERROR: firtool conversion failed: {e}")
            return str(scala_file), module_name, None

        return verilog_file, module_name, None

    elif backend == 'rtlil':
        import shutil
        from pathlib import Path
        from backends.rtlil import (
            RTLILGenerator, rtlil_to_cxxrtl, rtlil_to_verilog,
            CXXRTLTestbenchConfig, generate_cxxrtl_testbench,
            copy_test_scripts,
        )

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Generate RTLIL
        generator = RTLILGenerator(graph, module_name)
        rtlil_code = generator.generate()

        il_file = output_path / f"{module_name}.il"
        il_file.write_text(rtlil_code)
        print(f"  Generated RTLIL: {il_file} ({len(rtlil_code):,} bytes)")

        # Convert to CXXRTL C++ via Yosys
        yosys_path = shutil.which('yosys')
        cc_file = None
        if yosys_path:
            cc_file = output_path / f"{module_name}.cc"
            try:
                rtlil_to_cxxrtl(str(il_file), str(cc_file))
                print(f"  Generated CXXRTL C++: {cc_file}")
            except Exception as e:
                print(f"  CXXRTL conversion failed: {e}")
                cc_file = None

            # Also generate Verilog via Yosys for inspection
            v_file = output_path / f"{module_name}_from_rtlil.v"
            try:
                rtlil_to_verilog(str(il_file), str(v_file))
                print(f"  Generated Verilog (via Yosys): {v_file}")
            except Exception as e:
                print(f"  Verilog conversion failed: {e}")
        else:
            print("  Yosys not found in PATH, skipping CXXRTL/Verilog conversion")

        # Generate CXXRTL testbench (graph-dependent for pipeline stage detection)
        tb_config = CXXRTLTestbenchConfig(module_name=module_name)
        tb_files = generate_cxxrtl_testbench(graph, tb_config, output_dir)
        print(f"  Generated testbench: {tb_files['testbench']}")

        # Copy test scripts from canonical template with module-name substitution
        template_dir = os.path.join(_project_root, "examples/rtlil/riscv32i_pipelined")
        scripts = copy_test_scripts(template_dir, output_dir, module_name)
        for name, path in scripts.items():
            print(f"  Copied {name} -> {path}")

        return str(il_file), module_name, None

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
        testbench_code = generate_cpp_testbench_for_pipelined_riscv(module_name, config.num_stages)
        tb_file = output_path / f"{module_name}_tb.cpp"
        tb_file.write_text(testbench_code)
        print(f"  Generated testbench: {tb_file}")

        # Generate Makefile
        makefile_code = generate_cpp_makefile_for_pipelined(module_name)
        makefile = output_path / "Makefile"
        makefile.write_text(makefile_code)
        print(f"  Generated Makefile: {makefile}")

        # Generate test runner script
        test_script = generate_cpp_test_script_for_pipelined(module_name)
        script_file = output_path / "run_all_tests.sh"
        script_file.write_text(test_script)
        script_file.chmod(0o755)
        print(f"  Generated test script: {script_file}")

        return str(header_file), module_name, None


def generate_externalized_memory_testbench(generator, module_name, output_path):
    """Generate a testbench for a processor with externalized memory.

    This testbench:
    1. Instantiates the processor module
    2. Creates multi-port memory model
    3. Connects the external memory ports
    4. Loads test programs via $readmemh into external memory
    """
    from pathlib import Path

    # Collect information about externalized memory ports
    ext_memories = list(generator.externalized_memories)
    if not ext_memories:
        return ""

    # Build port lists for each externalized memory
    memory_ports = {}
    for mem_name in ext_memories:
        memory_ports[mem_name] = {
            'read_ports': [],
            'write_ports': [],
            'data_width': 32,
            'addr_width': 32,
        }

        # Get info from generator
        mem_info = generator.memory_declarations.get(mem_name, {})
        memory_ports[mem_name]['data_width'] = mem_info.get('bit_width', 32)
        # For externalized memory ports, use full 32-bit addresses (not ISA-limited addr_width)
        memory_ports[mem_name]['addr_width'] = mem_info.get('externalized_addr_width', 32)
        memory_ports[mem_name]['use_valid_ready'] = mem_info.get('use_valid_ready', True)
        # Get latency specification from memory node (set by set_memory_variable_latency)
        memory_ports[mem_name]['min_latency'] = mem_info.get('min_latency', 0)
        memory_ports[mem_name]['max_latency'] = mem_info.get('max_latency', 0)

        # Find read ports for this memory
        tracked_read = set()
        for rp in generator.memory_read_ports:
            if rp['mem'] == mem_name:
                ext_port = rp.get('ext_port_name', mem_name)
                if ext_port not in tracked_read:
                    tracked_read.add(ext_port)
                    memory_ports[mem_name]['read_ports'].append(ext_port)

        # Find write ports for this memory
        tracked_write = set()
        for wp in generator.memory_write_ports:
            if wp['mem'] == mem_name:
                ext_port = wp.get('ext_port_name', mem_name)
                if ext_port not in tracked_write:
                    tracked_write.add(ext_port)
                    memory_ports[mem_name]['write_ports'].append(ext_port)

    # Generate testbench
    tb = []
    tb.append("`timescale 1ns/1ps\n")
    tb.append(f"module simple_tb;\n")
    tb.append("    reg clk, reset;\n")
    tb.append("    wire [31:0] zero32 = 32'd0;\n\n")

    # Declare wires for external memory connections
    tb.append("    // External memory interface signals\n")
    for mem_name, ports in memory_ports.items():
        data_width = ports['data_width']
        addr_width = ports['addr_width']

        for rp in ports['read_ports']:
            tb.append(f"    wire [{addr_width-1}:0] {rp}_read_req_addr;\n")
            tb.append(f"    wire {rp}_read_req_valid;\n")
            tb.append(f"    wire [{data_width-1}:0] {rp}_read_resp_data;\n")
            if ports['use_valid_ready']:
                tb.append(f"    wire {rp}_read_resp_ready;\n")

        for wp in ports['write_ports']:
            num_bytes = max(1, data_width // 8)
            tb.append(f"    wire [{addr_width-1}:0] {wp}_write_req_addr;\n")
            tb.append(f"    wire [{data_width-1}:0] {wp}_write_req_data;\n")
            tb.append(f"    wire [{num_bytes-1}:0] {wp}_write_req_we;\n")
            tb.append(f"    wire {wp}_write_req_valid;\n")
            if ports['use_valid_ready']:
                tb.append(f"    wire {wp}_write_resp_ready;\n")
    tb.append("\n")

    # Instantiate the processor
    tb.append(f"    // Device Under Test\n")
    tb.append(f"    {module_name} dut (\n")
    tb.append("        .clk(clk),\n")
    tb.append("        .reset(reset),\n")
    tb.append("        .reset_pc_rd(zero32)")

    # Connect external memory ports
    for mem_name, ports in memory_ports.items():
        for rp in ports['read_ports']:
            tb.append(f",\n        .{rp}_read_req_addr({rp}_read_req_addr)")
            tb.append(f",\n        .{rp}_read_req_valid({rp}_read_req_valid)")
            tb.append(f",\n        .{rp}_read_resp_data({rp}_read_resp_data)")
            if ports['use_valid_ready']:
                tb.append(f",\n        .{rp}_read_resp_ready({rp}_read_resp_ready)")

        for wp in ports['write_ports']:
            tb.append(f",\n        .{wp}_write_req_addr({wp}_write_req_addr)")
            tb.append(f",\n        .{wp}_write_req_data({wp}_write_req_data)")
            tb.append(f",\n        .{wp}_write_req_we({wp}_write_req_we)")
            tb.append(f",\n        .{wp}_write_req_valid({wp}_write_req_valid)")
            if ports['use_valid_ready']:
                tb.append(f",\n        .{wp}_write_resp_ready({wp}_write_resp_ready)")

    tb.append("\n    );\n\n")

    # For each externalized memory, create a multi-port memory model
    for mem_name, ports in memory_ports.items():
        data_width = ports['data_width']
        addr_width = ports['addr_width']
        depth = 16384  # 64KB for 32-bit words
        num_bytes = max(1, data_width // 8)
        word_addr_bits = 2 if data_width == 32 else 3  # log2(bytes per word)

        # Get latency from memory specification (set by set_memory_variable_latency)
        min_latency = ports.get('min_latency', 0)
        max_latency = ports.get('max_latency', 0)

        tb.append(f"    // {mem_name} - multi-port memory model\n")
        tb.append(f"    // Latency specification from memory node: min={min_latency}, max={max_latency}\n")
        tb.append(f"    parameter {mem_name.upper()}_MEM_LATENCY = {min_latency};  // 0 = combinational, >0 = N-cycle latency\n")
        tb.append(f"    reg [{data_width-1}:0] {mem_name}_mem [0:{depth-1}];\n\n")

        # Read ports - use counter-based FSM matching internal memory behavior
        mem_latency_param = f"{mem_name.upper()}_MEM_LATENCY"
        for rp in ports['read_ports']:
            tb.append(f"    // {rp} read interface - counter-based latency FSM\n")
            tb.append(f"    generate\n")
            tb.append(f"        if ({mem_latency_param} == 0) begin : {rp}_comb\n")
            tb.append(f"            // Combinational read (no latency)\n")
            tb.append(f"            assign {rp}_read_resp_data = {mem_name}_mem[{rp}_read_req_addr[{addr_width-1}:{word_addr_bits}]];\n")
            if ports['use_valid_ready']:
                tb.append(f"            assign {rp}_read_resp_ready = {rp}_read_req_valid;\n")
            tb.append(f"        end else begin : {rp}_latency\n")
            tb.append(f"            // Counter-based latency FSM\n")
            tb.append(f"            // After LATENCY cycles, asserts resp_ready for one cycle\n")
            tb.append(f"            reg [7:0] counter;\n")
            tb.append(f"            reg [{data_width-1}:0] latched_data;\n")
            tb.append(f"            always @(posedge clk) begin\n")
            tb.append(f"                if (reset) begin\n")
            tb.append(f"                    counter <= 0;\n")
            tb.append(f"                    latched_data <= 0;\n")
            tb.append(f"                end else if ({rp}_read_req_valid) begin\n")
            tb.append(f"                    if (counter == 0) begin\n")
            tb.append(f"                        // Start: latch address and data, begin counting\n")
            tb.append(f"                        counter <= 1;\n")
            tb.append(f"                        latched_data <= {mem_name}_mem[{rp}_read_req_addr[{addr_width-1}:{word_addr_bits}]];\n")
            tb.append(f"                    end else if (counter == {mem_latency_param}) begin\n")
            tb.append(f"                        // Complete: reset for next request\n")
            tb.append(f"                        counter <= 0;\n")
            tb.append(f"                    end else begin\n")
            tb.append(f"                        // Counting toward completion\n")
            tb.append(f"                        counter <= counter + 1;\n")
            tb.append(f"                    end\n")
            tb.append(f"                end else begin\n")
            tb.append(f"                    counter <= 0;\n")
            tb.append(f"                end\n")
            tb.append(f"            end\n")
            tb.append(f"            assign {rp}_read_resp_data = latched_data;\n")
            if ports['use_valid_ready']:
                tb.append(f"            assign {rp}_read_resp_ready = (counter == {mem_latency_param});\n")
            tb.append(f"        end\n")
            tb.append(f"    endgenerate\n\n")

        # Write ports with byte enables
        for wp in ports['write_ports']:
            tb.append(f"    // {wp} write interface\n")
            tb.append(f"    always @(posedge clk) begin\n")
            tb.append(f"        if (!reset && {wp}_write_req_valid) begin\n")
            for b in range(num_bytes):
                tb.append(f"            if ({wp}_write_req_we[{b}]) {mem_name}_mem[{wp}_write_req_addr[{addr_width-1}:{word_addr_bits}]][{b*8} +: 8] <= {wp}_write_req_data[{b*8} +: 8];\n")
            tb.append(f"        end\n")
            tb.append(f"    end\n")
            if ports['use_valid_ready']:
                tb.append(f"    assign {wp}_write_resp_ready = {wp}_write_req_valid;\n")
            tb.append("\n")

    # Test logic - use Execute stage PC for accurate pass/fail detection in pipelined designs
    # The Fetch stage PC (pc_rd) is ahead of execution, so we check when instructions
    # actually reach the Execute stage and are valid (not flushed/bubbled)
    tb.append("    reg [31:0] pass_addr, fail_addr;\n")
    tb.append("    integer i;\n")
    tb.append("    always #5 clk = ~clk;\n\n")

    # Use Execute stage PC and valid signals for pass/fail detection (pipelined design)
    # These are the standard signal names for 5-stage pipeline
    tb.append("    // Execute stage signals for accurate pass/fail detection\n")
    tb.append("    wire [31:0] exec_pc = dut.PIPE_Execute_PIPE_Decode_pc_rd_PIPE_PIPE;\n")
    tb.append("    wire exec_valid = dut.PIPE_Execute_valid_PIPE;\n")
    tb.append("    wire exec_at_pass = exec_valid && (exec_pc == pass_addr);\n")
    tb.append("    wire exec_at_fail = exec_valid && (exec_pc == fail_addr);\n\n")

    tb.append("    initial begin\n")
    tb.append("        clk = 0; reset = 1;\n")
    tb.append("        if (!$value$plusargs(\"pass_addr=%h\", pass_addr)) pass_addr = 32'hFFFFFFFF;\n")
    tb.append("        if (!$value$plusargs(\"fail_addr=%h\", fail_addr)) fail_addr = 32'hFFFFFFFE;\n")

    # Load memory - use the first externalized memory name
    if ext_memories:
        mem_name = ext_memories[0]
        tb.append(f"        $readmemh(\"{mem_name}.hex\", {mem_name}_mem);\n")

    tb.append("        repeat(3) @(posedge clk);\n")
    tb.append("        reset = 0;\n")
    tb.append("        for (i = 0; i < 10000; i = i + 1) begin\n")
    tb.append("            @(posedge clk);\n")
    tb.append("            if (exec_at_pass) begin $display(\"TEST PASSED in %0d cycles\", i); $finish; end\n")
    tb.append("            if (exec_at_fail) begin $display(\"TEST FAILED at test %0d\", dut.rf[3]); $finish; end\n")
    tb.append("        end\n")
    tb.append("        $display(\"TIMEOUT\");\n")
    tb.append("        $finish;\n")
    tb.append("    end\n")
    tb.append("endmodule\n")

    return "".join(tb)


def _generate_rv32_benchmark_script(output_path: str):
    """Generate run_benchmarks.sh for RV32I processors."""
    script = r'''#!/bin/bash

# Run RISC-V benchmarks on ISAComp RV32I pipelined processor
# Uses the same testbench as ISA tests, with +max_cycles for longer timeout
# Set SIMULATOR=verilator to use Verilator instead of Icarus Verilog

SIMULATOR=${SIMULATOR:-iverilog}

echo "Running RV32I benchmarks with $SIMULATOR..."

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
        f.write('00000000\n')
"

BENCHMARKS="median memcpy multiply qsort rsort towers vvadd"
PASS=0; FAIL=0; SKIP=0; FAILED_TESTS=""; TOTAL_CYCLES=0

for bench in $BENCHMARKS; do
    echo -n "Benchmark $bench... "
    BENCH_BASE="../../../riscv32/riscv-benchmarks/$bench"

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
if len(data) > 8192 * 4:
    print(f'ERROR: benchmark too large ({len(data)} bytes > {8192*4} byte memory)', file=sys.stderr)
    sys.exit(1)
with open('umem.hex', 'w') as f:
    for word_idx in range(8192):
        word = 0; addr = word_idx * 4
        for byte_offset in range(4):
            byte_addr = addr + byte_offset
            if byte_addr < len(data): word |= data[byte_addr] << (byte_offset * 8)
        f.write(f'{word:08x}\n')
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
    os.chmod(output_path, 0o755)


def main(num_stages: int = 5, hazard_strategy: str = 'stall', write_read_fwd: bool = False,
         mem_min_latency: int = 1, mem_max_latency: int = 1,
         imem_min_latency: int = 1, imem_max_latency: int = 1,
         backend: str = 'verilog',
         icache: bool = False, icache_size: int = 64, icache_assoc: int = 1,
         dcache: bool = False, dcache_size: int = 64, dcache_assoc: int = 1,
         externalize_memory: bool = False,
         enable_ras: bool = False, ras_depth: int = 8,
         enable_btb: bool = False, btb_entries: int = 64, btb_assoc: int = 1,
         enable_rename: bool = False, num_phys_regs: int = 64):
    """
    Main pipeline creation function.

    Args:
        num_stages: Number of pipeline stages (2, 3, 4, or 5)
        hazard_strategy: 'stall' for stalling or 'bypass' for forwarding
        write_read_fwd: Enable write-to-read forwarding on register file
        mem_min_latency: Minimum dmem latency cycles (default 1)
        mem_max_latency: Maximum dmem latency cycles (default 1)
        imem_min_latency: Minimum imem latency cycles (default 1)
        imem_max_latency: Maximum imem latency cycles (default 1)
        backend: Output backend (verilog, vhdl, pyrtl, circt)
        icache: Enable instruction cache on imem
        icache_size: Number of cache rows (default 64)
        icache_assoc: Cache associativity (1=direct-mapped, 2/4/8=set-associative)
        dcache: Enable data cache on umem (for load/store)
        dcache_size: Number of cache rows (default 64)
        dcache_assoc: Cache associativity (1=direct-mapped, 2/4/8=set-associative)
        externalize_memory: Externalize umem with valid-ready handshake interface
        enable_btb: Enable Branch Target Buffer
        btb_entries: Number of BTB entries (default 64)
        btb_assoc: BTB associativity (default 1 = direct-mapped)
        enable_rename: Enable register renaming for WAW/WAR elimination
        num_phys_regs: Number of physical registers for renaming (default 64)
    """
    # Get pipeline configuration
    config = get_pipeline_config(num_stages)

    print("=" * 70)
    print(f"{num_stages}-STAGE PIPELINED RISC-V 32-BIT PROCESSOR ({backend.upper()} backend)")
    print(f"Stages: {' -> '.join(config.stage_names)}")
    print(f"Hazard Resolution: {hazard_strategy.upper()}")
    print(f"Write-Read Forwarding: {'ENABLED' if write_read_fwd else 'DISABLED'}")
    if mem_min_latency == mem_max_latency:
        print(f"Data Memory Latency: {mem_min_latency} cycles (static)")
    else:
        print(f"Data Memory Latency: {mem_min_latency}-{mem_max_latency} cycles (random)")
    if imem_min_latency == imem_max_latency:
        print(f"Instruction Memory Latency: {imem_min_latency} cycles (static)")
    else:
        print(f"Instruction Memory Latency: {imem_min_latency}-{imem_max_latency} cycles (random)")
    if icache:
        print(f"Instruction Cache: {icache_size} rows, {icache_assoc}-way associative")
    if dcache:
        print(f"Data Cache: {dcache_size} rows, {dcache_assoc}-way associative")
    if enable_btb:
        print(f"Branch Target Buffer: {btb_entries} entries, {btb_assoc}-way associative")
    if enable_rename:
        print(f"Register Renaming: ENABLED ({num_phys_regs} physical registers)")
    print("=" * 70)

    # Step 1: Build merged graph
    graph = build_merged_graph()

    # Step 1.1: Apply register renaming if enabled
    if enable_rename:
        if RegisterRenamingOptimization is None:
            print(f"\n  WARNING: --rename not supported with {_engine} engine, skipping")
            enable_rename = False
        else:
            print("\n" + "=" * 70)
            print("APPLYING REGISTER RENAMING OPTIMIZATION")
            print("=" * 70)
            rename_spec = RegisterRenamingSpec(
                resource_name='rf',
                num_physical_regs=num_phys_regs,
                target_indices=None,  # Rename all indices
                separate_regfiles=False  # Use index renaming (not separate physical RF)
            )
            renaming_opt = RegisterRenamingOptimization(graph)
            success = renaming_opt.apply(rename_spec)
            if not success:
                print(f"  WARNING: Register renaming failed")

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

    # Step 1.6b: Set instruction fetch latency via icache
    # With unified memory (umem), instruction fetch latency is handled by the icache.
    # The --imem-latency option now configures memory latency that icache hides.
    if imem_min_latency > 1 or imem_max_latency > 1:
        print(f"\n  Note: Instruction fetch latency ({imem_min_latency}-{imem_max_latency} cycles) will be hidden by icache")
        if not icache:
            print("  WARNING: --imem-latency specified but --icache not enabled. Latency has no effect.")

    # Step 1.7: Add instruction cache if enabled
    if icache and ReadOnlyCacheSpec is None:
        print(f"\n  WARNING: --icache not supported with {_engine} engine, skipping")
        icache = False
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
    if dcache and ReadWriteCacheSpec is None:
        print(f"\n  WARNING: --dcache not supported with {_engine} engine, skipping")
        dcache = False
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

    # Step 1.9: Apply memory externalization if enabled
    if externalize_memory:
        print("\n" + "=" * 70)
        print("APPLYING MEMORY EXTERNALIZATION")
        print("=" * 70)

        # Note: When caches are enabled, they sit between CPU and umem.
        # Externalizing umem means cache refill/writeback goes to external memory.
        if icache or dcache:
            print("  Note: Caches enabled - cache misses will access external memory")

        # Create externalization spec for umem
        # The latency specification was already set by set_memory_variable_latency
        if _engine == 'rust':
            ext_success = apply_memory_externalization(graph, 'umem',
                                                       create_read_port=True,
                                                       create_write_port=True,
                                                       variable_latency=True)
        else:
            ext_spec = MemoryExternalizationSpec(
                memory_name='umem',
                create_read_port=True,
                create_write_port=True,
                variable_latency=True
            )
            ext_success = apply_memory_externalization(graph, ext_spec)

        if ext_success:
            print("  Memory externalization applied successfully")
            print(f"    Latency: {mem_min_latency}-{mem_max_latency} cycles")
        else:
            print("  WARNING: Failed to apply memory externalization")

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

    # Wire imem start signal if imem has variable latency
    if imem_min_latency > 1 or imem_max_latency > 1:
        if wire_memory_start_signal(graph, 'imem'):
            print("  imem start signal wired")
        else:
            print("  WARNING: Could not wire imem start signal")

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
    _, resolver = apply_hazard_resolution(graph, config, strategy=hazard_strategy)

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

    # Fix dcache refill address pipeline register: must be ungated.
    # The cache outputs dcache_refill_addr when it detects a miss. The pipeline
    # register PIPE_Memory_dcache_refill_addr_PIPE must capture this address
    # immediately, even during a cache stall (the stall is caused BY the miss).
    # Remove stall and valid_gate edges so the Verilog generator creates an
    # ungated register (matching the Rust engine behavior).
    if dcache and _engine == 'python':
        refill_reg_id = 'PIPE_Memory_dcache_refill_addr_PIPE'
        refill_reg = graph.nodes.get(refill_reg_id)
        if refill_reg:
            for edge in list(refill_reg.incoming_edges):
                if edge.data.get('type') in ('stall', 'valid_gate'):
                    graph.remove_edge(edge.id)
                    print(f"  Removed {edge.data['type']} edge from {refill_reg_id}: {edge.source.id}")

    # Flag for BTB - we'll apply it after branch prediction (see Step 7.5b)
    btb_enabled = enable_btb

    # Step 7: Apply branch prediction (creates predicted_pc and PC recovery mux)
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
        # The node might be named 'pc_add_4' or '(pc + 4)'
        default_prediction_id = None
        for name in ['pc_add_4', '(pc + 4)', 'pc+4']:
            if name in graph.nodes:
                default_prediction_id = name
                break
        if not default_prediction_id:
            print("  ERROR: Could not find PC+4 node for RAS")
            print("  Skipping RAS optimization")
        else:
            # Use Decode stage for call/return detection (all signals from same instruction)
            # and PIPE_Decode_pc_add_4_PIPE for the return address (PC+4 of the call instruction)
            # Note: We detect calls at Decode stage, which means:
            # - jal_enable/jalr_enable fire when instruction is being decoded
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
                    # JALR can also be a call when rd is a link register
                    CallSpec(
                        enable_node_id='jalr_enable',
                        dest_reg_node_id='rd',
                        return_addr_node_id='PIPE_Decode_pc_add_4_PIPE'
                    ),
                ],
                return_specs=[
                    # JALR is a return when rs1 is a link register and rd == 0
                    ReturnSpec(
                        enable_node_id='jalr_enable',
                        src_reg_node_id='rs1',
                        dest_reg_node_id='rd'
                    ),
                ],
                link_registers=[1, 5],  # x1 (ra) and x5 (t0)
                ras_depth=ras_depth,
                ras_width=32,
                # Structural node references (required)
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

    # Step 7.5: Apply Branch Target Buffer (BTB) optimization AFTER branch prediction
    # BTB modifies the predicted_pc node which is created by branch prediction
    if btb_enabled and apply_branch_target_buffer is None:
        print(f"\n  WARNING: --btb not supported with {_engine} engine, skipping")
        btb_enabled = False
    if btb_enabled:
        print("\n" + "=" * 70)
        print("APPLYING BRANCH TARGET BUFFER (BTB) OPTIMIZATION")
        print("=" * 70)

        # Now that branch prediction has run, predicted_pc should exist
        predicted_pc_node = graph.nodes.get('predicted_pc')
        default_prediction_node = graph.nodes.get('pc_add_4')

        # Find pc_add_4 if not found by exact name
        if not default_prediction_node:
            for candidate in ['(pc + 4)', 'pc_plus_4', '(pc + 2)']:
                if candidate in graph.nodes:
                    default_prediction_node = graph.nodes[candidate]
                    break

        # Find control hazard flush signal
        control_flush_node = graph.nodes.get('control_hazard_flush')

        # Get branch PC at execute stage
        branch_pc_node = graph.nodes.get('PIPE_Execute_PIPE_Decode_pc_rd_PIPE_PIPE')
        if not branch_pc_node:
            for node_id in graph.nodes:
                if 'Execute' in node_id and 'pc' in node_id.lower() and 'PIPE' in node_id and node_id.endswith('_PIPE_PIPE'):
                    branch_pc_node = graph.nodes[node_id]
                    break

        if predicted_pc_node and control_flush_node and branch_pc_node and default_prediction_node:
            # Create a combined branch_taken signal for BTB update

            # Look for individual branch taken signals at Execute stage
            branch_taken_signals = []
            for branch in ['beq', 'bne', 'blt', 'bge', 'bltu', 'bgeu']:
                taken_node = graph.nodes.get(f'{branch}_branch_taken_execute')
                if taken_node:
                    branch_taken_signals.append(taken_node)

            # Also include unconditional jumps (always taken when enabled)
            for jump in ['jal', 'jalr']:
                enable_node = graph.nodes.get(f'PIPE_Execute_{jump}_enable_PIPE')
                if enable_node:
                    branch_taken_signals.append(enable_node)

            # Create OR of all branch taken signals
            branch_outcome_node_id = 'beq_res'  # Fallback
            if len(branch_taken_signals) > 0:
                # Create combined branch_taken node
                combined_taken = Node('branch_taken_combined', data={
                    'type': 'var',
                    'name': 'branch_taken_combined',
                    'bit_width': 1
                }, uarch_time=2)  # Execute stage
                graph.add_node(combined_taken)

                # Create OR operation
                current = branch_taken_signals[0]
                for sig in branch_taken_signals[1:]:
                    or_node = Node(f'branch_taken_or_{sig.id}', data={
                        'type': 'operation',
                        'operator': '||',
                        'bit_width': 1
                    }, uarch_time=2)
                    graph.add_node(or_node)
                    graph.add_edge(Edge(current, or_node, data={'type': 'operand', 'position': 'left'}))
                    graph.add_edge(Edge(sig, or_node, data={'type': 'operand', 'position': 'right'}))
                    current = or_node

                # Connect final OR result to combined_taken
                graph.add_edge(Edge(current, combined_taken, data={'type': 'assignment'}))
                branch_outcome_node_id = 'branch_taken_combined'
                print(f"  Created combined branch_taken signal from {len(branch_taken_signals)} sources")

            btb_spec = BTBSpec(
                # Branch instructions at Execute stage (piped enables)
                # These must be Execute stage signals for correct BTB update timing
                branch_enable_nodes=[
                    'PIPE_Execute_beq_enable_PIPE', 'PIPE_Execute_bne_enable_PIPE',
                    'PIPE_Execute_blt_enable_PIPE', 'PIPE_Execute_bge_enable_PIPE',
                    'PIPE_Execute_bltu_enable_PIPE', 'PIPE_Execute_bgeu_enable_PIPE',
                    'PIPE_Execute_jal_enable_PIPE', 'PIPE_Execute_jalr_enable_PIPE'
                ],

                # Execute stage signals
                branch_outcome_node=branch_outcome_node_id,
                branch_target_node='branch_target' if 'branch_target' in graph.nodes else 'pc_wr_mux',

                # PC nodes
                fetch_pc_node='pc_rd',
                branch_pc_node=branch_pc_node.id,

                # Infrastructure
                predicted_pc_node_id=predicted_pc_node.id,
                default_prediction_node_id=default_prediction_node.id,
                control_hazard_flush_node_id='control_hazard_flush',

                # BTB configuration
                num_entries=btb_entries,
                associativity=btb_assoc,
                pc_width=32,
                btb_name='btb'
            )

            btb_success = apply_branch_target_buffer(graph, btb_spec)
            if btb_success:
                print("  BTB optimization applied successfully")
            else:
                print("  WARNING: BTB optimization could not be applied")
        else:
            missing = []
            if not predicted_pc_node:
                missing.append("predicted_pc")
            if not default_prediction_node:
                missing.append("pc_add_4")
            if not control_flush_node:
                missing.append("control_hazard_flush")
            if not branch_pc_node:
                missing.append("branch_pc (Execute stage)")
            print(f"  WARNING: BTB requires infrastructure nodes: {', '.join(missing)}")
            print("  BTB optimization skipped")

    # Step 8: Generate RTL with specified backend
    suffix = "_bypass" if hazard_strategy == 'bypass' else ""
    if write_read_fwd:
        suffix += "_wrf"
    ext_suffix = "_ext" if externalize_memory else ""
    if backend == 'circt':
        output_dir = os.path.join(_project_root, f"examples/verilog/circt_riscv32i_pipelined_{config.num_stages}stage{suffix}{ext_suffix}")
    elif backend == 'pyrtl':
        output_dir = os.path.join(_project_root, f"examples/pyrtl/riscv32i_pipelined_{config.num_stages}stage{suffix}{ext_suffix}")
    elif backend == 'hardcaml':
        output_dir = os.path.join(_project_root, f"examples/hardcaml/riscv32i_pipelined_{config.num_stages}stage{suffix}{ext_suffix}")
    elif backend == 'chisel':
        output_dir = os.path.join(_project_root, f"examples/chisel/riscv32i_pipelined_{config.num_stages}stage{suffix}{ext_suffix}")
    elif backend == 'rtlil':
        output_dir = os.path.join(_project_root, f"examples/rtlil/riscv32i_pipelined_{config.num_stages}stage{suffix}{ext_suffix}")
    elif backend == 'verilog':
        output_dir = os.path.join(_project_root, f"examples/verilog/riscv32i_pipelined_{config.num_stages}stage{suffix}{ext_suffix}")
    else:
        output_dir = os.path.join(_project_root, f"{backend}/riscv32i_pipelined_{config.num_stages}stage{suffix}{ext_suffix}")
    rtl_file, module_name, generator = generate_pipelined_rtl(
        graph, backend, output_dir, config, hazard_strategy, externalize_memory,
        write_read_fwd
    )

    # Step 9: Save the pipelined graph
    graph.save_to_file(os.path.join(output_dir, f"{module_name}.rgraph"))
    print(f"\nSaved pipelined graph to {output_dir}/{module_name}.rgraph")

    # Step 10: Generate testbench
    if backend == 'verilog':
        if externalize_memory and generator and hasattr(generator, 'externalized_memories') and generator.externalized_memories:
            # Generate externalized memory testbench
            from pathlib import Path
            testbench_code = generate_externalized_memory_testbench(
                generator, module_name, Path(output_dir)
            )
            tb_file = os.path.join(output_dir, "simple_tb.sv")
            with open(tb_file, 'w') as f:
                f.write(testbench_code)
            print(f"  Created externalized memory testbench: {tb_file}")
        else:
            # Use standard testbench generation
            from isa.riscv32.generators.generate_testbench import generate_testbench

            dst_tb = os.path.join(output_dir, "simple_tb_new.sv")
            generate_testbench(rtl_file, dst_tb)
            print(f"  Created testbench: {dst_tb}")

        # Copy test script with updated filenames
        src_script = os.path.join(_project_root, "examples/verilog/riscv32i_pipelined/run_riscv_tests.sh")
        if os.path.exists(src_script):
            with open(src_script, 'r') as f:
                script_content = f.read()
            script_content = script_content.replace('riscv32i_pipelined', module_name)
            dst_script = os.path.join(output_dir, "run_riscv_tests.sh")
            with open(dst_script, 'w') as f:
                f.write(script_content)
            os.chmod(dst_script, 0o755)
            print(f"  Created test script: {dst_script}")

        # Generate benchmark script
        dst_bench = os.path.join(output_dir, "run_benchmarks.sh")
        _generate_rv32_benchmark_script(dst_bench)
        print(f"  Created benchmark script: {dst_bench}")

    elif backend == 'hardcaml':
        # Copy test infrastructure from canonical location with module name substitution
        src_dir = os.path.join(_project_root, "examples/hardcaml/riscv32i_pipelined")
        for script_name in ['gen_tb.py', 'run_all_tests.sh', 'load_test.py']:
            src = os.path.join(src_dir, script_name)
            if os.path.exists(src):
                with open(src, 'r') as f:
                    content = f.read()
                content = content.replace('riscv32i_pipelined', module_name)
                dst = os.path.join(output_dir, script_name)
                with open(dst, 'w') as f:
                    f.write(content)
                os.chmod(dst, 0o755)
                print(f"  Copied {script_name} -> {dst}")

    elif backend == 'chisel':
        from isa.riscv32.generators.generate_riscv32i_complete import (
            _generate_chisel_testbench, _generate_chisel_test_runner,
        )
        from pathlib import Path

        output_path = Path(output_dir)
        class_name = ''.join(p.capitalize() for p in module_name.replace('-', '_').split('_'))

        tb_file = output_path / "simple_tb.sv"
        _generate_chisel_testbench(tb_file, module_name, class_name, pipelined=True,
                                   num_stages=config.num_stages, verilog_path=rtl_file)
        print(f"  Created testbench: {tb_file}")

        runner_file = output_path / "run_all_tests.sh"
        _generate_chisel_test_runner(runner_file, module_name)
        print(f"  Created test runner: {runner_file}")

    print("\n" + "=" * 70)
    print("PIPELINE CREATION COMPLETE")
    print("=" * 70)
    print(f"Generated files:")
    print(f"  - {rtl_file}")
    print(f"  - {output_dir}/{module_name}.rgraph")
    print(f"\nNext steps:")
    if backend == 'verilog':
        print(f"  cd {output_dir}")
        print(f"  ./run_riscv_tests.sh")
    elif backend == 'circt':
        print(f"  - {output_dir}/simple_tb.sv")
        print(f"  - {output_dir}/run_all_tests.sh")
        print(f"\nNext steps:")
        print(f"  cd {output_dir}")
        print(f"  ./run_all_tests.sh")
    elif backend == 'hardcaml':
        print(f"  cd {output_dir}")
        print(f"  bash run_all_tests.sh")
    elif backend == 'clash':
        hs_mod = module_name[0].upper() + module_name[1:] if module_name else "Processor"
        print(f"  bash build.sh                      # compile Haskell to Verilog")
        print(f"  cd {output_dir}/examples/verilog/{hs_mod}.topEntity")
        print(f"  bash ../../run_all_tests.sh         # run riscv-tests")
    elif backend == 'chisel':
        print(f"  cd {output_dir}")
        print(f"  bash run_all_tests.sh")
    elif backend == 'rtlil':
        print(f"  cd {output_dir}")
        print(f"  bash run_all_tests.sh")
    elif backend == 'sim-cpp':
        print(f"  cd {output_dir}")
        print(f"  ./run_all_tests.sh")
    else:
        print(f"  Review generated output in {output_dir}/")

    return graph


def generate_cpp_testbench_for_pipelined_riscv(module_name, num_stages=5):
    """Generate C++ testbench for pipelined RISC-V 32-bit simulation.

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
// Compatible with riscv-tests suite (RV32I)

#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <cstdlib>
#include <cstdint>
#include <vector>
#include "{module_name}.hpp"

// Load unified memory hex file (word-addressed, little-endian)
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
        uint32_t word = std::stoul(line, nullptr, 16);
        cpu.write_umem(addr, word);
        addr++;
    }}
    return true;
}}

int main(int argc, char* argv[]) {{
    // Parse command line arguments
    std::string hex_file = "umem.hex";
    uint32_t pass_addr = 0xFFFFFFFF;
    uint32_t fail_addr = 0xFFFFFFFE;
    uint64_t max_cycles = 50000;  // Higher for pipelined (more cycles per instruction)
    bool trace = false;

    for (int i = 1; i < argc; i++) {{
        std::string arg = argv[i];
        if (arg.substr(0, 11) == "+pass_addr=") {{
            pass_addr = static_cast<uint32_t>(std::stoull(arg.substr(11), nullptr, 16));
        }} else if (arg.substr(0, 11) == "+fail_addr=") {{
            fail_addr = static_cast<uint32_t>(std::stoull(arg.substr(11), nullptr, 16));
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
    for (uint64_t cycle = 0; cycle < max_cycles; cycle++) {{
        if (trace) {{
            cpu.dump_state();
        }}

        cpu.cycle();

        // Get Execute stage PC and valid signal
        uint32_t exec_pc = cpu.{exec_pc_getter}();
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


def generate_cpp_makefile_for_pipelined(module_name):
    """Generate Makefile for C++ pipelined RISC-V simulation."""
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


def generate_cpp_test_script_for_pipelined(module_name):
    """Generate test runner script for C++ pipelined RISC-V simulation."""
    return f'''#!/bin/bash

# Test all RV32I instructions using pipelined C++ simulation
# This script mirrors run_all_tests.sh for the Verilog backend

echo "Building C++ simulation..."
make -s
if [ $? -ne 0 ]; then
    echo "ERROR: Compilation failed!"
    exit 1
fi

TESTS="add addi sub lui auipc and andi or ori xor xori sll slli srl srli sra srai slt slti sltu sltiu beq bne blt bltu bge bgeu jal jalr lw lh lhu lb lbu sw sh sb"

PASS=0
FAIL=0
SKIP=0

for test in $TESTS; do
    echo -n "Testing $test... "

    TEST_BASE="../../../riscv32/riscv-tests/isa/rv32ui-isacomp-$test"

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
    for word_addr in range((max_addr // 4) + 1):
        byte_addr = word_addr * 4
        word = 0
        for i in range(4):
            if byte_addr + i in data:
                word |= data[byte_addr + i] << (i * 8)
        f.write(f'{{word:08x}}\\n')
" 2>/dev/null

    if [ $? -ne 0 ]; then
        echo "ERROR (hex conversion failed)"
        FAIL=$((FAIL + 1))
        continue
    fi

    # Run simulation (addresses are already hex from .addrs file)
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

if [ $FAIL -gt 0 ]; then
    echo "FAILED: $FAIL test(s) failed"
    exit 1
else
    echo "SUCCESS: All $PASS tests passed"
    exit 0
fi
'''


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Create a pipelined RISC-V 32-bit processor.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python create_rv32i_pipeline.py              # Create 5-stage pipeline (default) with stalling
  python create_rv32i_pipeline.py --stages 5   # Create 5-stage pipeline with stalling
  python create_rv32i_pipeline.py --stages 4   # Create 4-stage pipeline with stalling
  python create_rv32i_pipeline.py --stages 3   # Create 3-stage pipeline with stalling
  python create_rv32i_pipeline.py --stages 2   # Create 2-stage pipeline with stalling
  python create_rv32i_pipeline.py --hazard-resolution bypass  # Use forwarding/bypassing
  python create_rv32i_pipeline.py -s 5 -hr bypass  # 5-stage with forwarding
  python create_rv32i_pipeline.py --mem-latency 1 5  # Data memory latency 1-5 cycles
  python create_rv32i_pipeline.py --imem-latency 3   # Instruction memory latency 3 cycles
  python create_rv32i_pipeline.py --icache     # Enable instruction cache (64 rows, direct-mapped)
  python create_rv32i_pipeline.py --icache --icache-size 128 --icache-assoc 2  # 128-row 2-way cache
  python create_rv32i_pipeline.py --icache --imem-latency 5  # icache hides 5-cycle imem latency
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
        choices=['verilog', 'vhdl', 'pyrtl', 'circt', 'clash', 'hardcaml', 'chisel', 'rtlil', 'sim-cpp'],
        help='Output backend: verilog (default), vhdl, pyrtl, circt, clash, hardcaml, chisel, rtlil, or sim-cpp'
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
        help='Data memory (dmem) latency: single value for static, two values (MIN MAX) for random. Default: 1'
    )
    parser.add_argument(
        '--imem-latency', '-il',
        type=int,
        nargs='+',
        default=[1, 1],
        metavar='CYCLES',
        help='Instruction memory (imem) latency: single value for static, two values (MIN MAX) for random. Default: 1'
    )
    parser.add_argument(
        '--icache',
        action='store_true',
        default=False,
        help='Enable instruction cache on imem'
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
        help='Cache associativity: 1=direct-mapped, 2/4/8=set-associative (default: 1)'
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
        help='Data cache associativity: 1=direct-mapped, 2/4/8=set-associative (default: 1)'
    )
    parser.add_argument(
        '--externalize-memory',
        action='store_true',
        default=False,
        help='Externalize unified memory (umem) with valid-ready handshake interface'
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
        '--btb',
        action='store_true',
        default=False,
        help='Enable Branch Target Buffer (BTB) for branch target prediction'
    )
    parser.add_argument(
        '--btb-entries',
        type=int,
        default=64,
        help='Number of BTB entries (default: 64, must be power of 2)'
    )
    parser.add_argument(
        '--btb-assoc',
        type=int,
        default=1,
        choices=[1, 2, 4, 8],
        help='BTB associativity: 1=direct-mapped, 2/4/8=set-associative (default: 1)'
    )
    parser.add_argument(
        '--rename',
        action='store_true',
        default=False,
        help='Enable register renaming for WAW/WAR hazard elimination'
    )
    parser.add_argument(
        '--num-phys-regs',
        type=int,
        default=64,
        help='Number of physical registers for renaming (default: 64)'
    )

    args = parser.parse_args()

    # Parse dmem latency: single value = static, two values = random range
    if len(args.mem_latency) == 1:
        mem_min = mem_max = args.mem_latency[0]
    elif len(args.mem_latency) >= 2:
        mem_min = args.mem_latency[0]
        mem_max = args.mem_latency[1]
    else:
        mem_min, mem_max = 1, 1  # default (single-cycle)

    # Parse imem latency: single value = static, two values = random range
    if len(args.imem_latency) == 1:
        imem_min = imem_max = args.imem_latency[0]
    elif len(args.imem_latency) >= 2:
        imem_min = args.imem_latency[0]
        imem_max = args.imem_latency[1]
    else:
        imem_min, imem_max = 1, 1  # default (single-cycle)

    _init_engine(args.engine)

    graph = main(
        num_stages=args.stages,
        hazard_strategy=args.hazard_resolution,
        write_read_fwd=args.write_read_fwd,
        mem_min_latency=mem_min,
        mem_max_latency=mem_max,
        imem_min_latency=imem_min,
        imem_max_latency=imem_max,
        backend=args.backend,
        icache=args.icache,
        icache_size=args.icache_size,
        icache_assoc=args.icache_assoc,
        dcache=args.dcache,
        dcache_size=args.dcache_size,
        dcache_assoc=args.dcache_assoc,
        externalize_memory=args.externalize_memory,
        enable_ras=args.ras,
        ras_depth=args.ras_depth,
        enable_btb=args.btb,
        btb_entries=args.btb_entries,
        btb_assoc=args.btb_assoc,
        enable_rename=args.rename,
        num_phys_regs=args.num_phys_regs
    )
