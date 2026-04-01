#!/usr/bin/env python3
"""
Create a pipelined 6502 processor with 3 stages (stalling-based).

6502 Architecture Characteristics:
- 8-bit data bus, 16-bit address bus
- Individual registers: A, X, Y, S (stack pointer), PC
- Status flags: N, V, B, D, I, Z, C
- Variable-length instructions (1-3 bytes)
- Unified mainmem for instructions and data
- No delay slots

Pipeline Stages (3-stage with stalling):
- Fetch (F): Read opcode from mainmem[pc]
- Decode (D): Decode instruction, read operands from mainmem[(pc+1)/(pc+2)],
              read registers A/X/Y/S, compute addresses
- ExecuteMemoryWriteback (XMW): ALU ops, data memory access, register writeback

Based on actual graph analysis:
- CUT 1 (F/D): ~5 edges
- CUT 2 (D/XMW): ~1089 edges

Usage:
    python create_6502_pipeline.py [--backend verilog|vhdl|pyrtl]
"""

import os
import re
import sys
import argparse

# Add project root to path for imports
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from pathlib import Path
from core.resource_graph import ResourceGraph, Node, Edge
from core.graph_merger import merge_instructions
from opt.pipeline.pipelining_optimization import PipelineTransform
from opt.fetch.branch_prediction_not_taken import apply_branch_prediction_not_taken
from opt.pipeline.hazard_resolution import HazardAnalyzer, HazardResolver, HazardResolutionStrategy
from opt.fetch.instruction_buffer_optimization import (
    InstructionBufferOptimization, InstructionBufferSpec,
    create_instr_length_node, create_pc_redirect_signal
)
from backends.verilog.verilog_generator import VerilogGenerator
from core.pipeline_config import PipelineConfig, PipelineCut

# 6502 instruction categories for reference
INSTRUCTIONS_6502 = [
    # Load/Store
    'lda_imm', 'lda_zp', 'lda_zp_x', 'lda_abs', 'lda_abs_x', 'lda_abs_y',
    'lda_ind_x', 'lda_ind_y',
    'ldx_imm', 'ldx_zp', 'ldx_zp_y', 'ldx_abs', 'ldx_abs_y',
    'ldy_imm', 'ldy_zp', 'ldy_zp_x', 'ldy_abs', 'ldy_abs_x',
    'sta_zp', 'sta_zp_x', 'sta_abs', 'sta_abs_x', 'sta_abs_y',
    'sta_ind_x', 'sta_ind_y',
    'stx_zp', 'stx_zp_y', 'stx_abs',
    'sty_zp', 'sty_zp_x', 'sty_abs',
    # Arithmetic
    'adc_imm', 'adc_zp', 'adc_zp_x', 'adc_abs', 'adc_abs_x', 'adc_abs_y',
    'adc_ind_x', 'adc_ind_y',
    'sbc_imm', 'sbc_zp', 'sbc_zp_x', 'sbc_abs', 'sbc_abs_x', 'sbc_abs_y',
    'sbc_ind_x', 'sbc_ind_y',
    # Compare
    'cmp_imm', 'cmp_zp', 'cmp_zp_x', 'cmp_abs', 'cmp_abs_x', 'cmp_abs_y',
    'cmp_ind_x', 'cmp_ind_y',
    'cpx_imm', 'cpx_zp', 'cpx_abs',
    'cpy_imm', 'cpy_zp', 'cpy_abs',
    # Logical
    'and_imm', 'and_zp', 'and_zp_x', 'and_abs', 'and_abs_x', 'and_abs_y',
    'and_ind_x', 'and_ind_y',
    'ora_imm', 'ora_zp', 'ora_zp_x', 'ora_abs', 'ora_abs_x', 'ora_abs_y',
    'ora_ind_x', 'ora_ind_y',
    'eor_imm', 'eor_zp', 'eor_zp_x', 'eor_abs', 'eor_abs_x', 'eor_abs_y',
    'eor_ind_x', 'eor_ind_y',
    'bit_zp', 'bit_abs',
    # Shift/Rotate
    'asl_acc', 'asl_zp', 'asl_zp_x', 'asl_abs', 'asl_abs_x',
    'lsr_acc', 'lsr_zp', 'lsr_zp_x', 'lsr_abs', 'lsr_abs_x',
    'rol_acc', 'rol_zp', 'rol_zp_x', 'rol_abs', 'rol_abs_x',
    'ror_acc', 'ror_zp', 'ror_zp_x', 'ror_abs', 'ror_abs_x',
    # Increment/Decrement
    'inc_zp', 'inc_zp_x', 'inc_abs', 'inc_abs_x',
    'dec_zp', 'dec_zp_x', 'dec_abs', 'dec_abs_x',
    'inx', 'iny', 'dex', 'dey',
    # Branch
    'bcc', 'bcs', 'beq', 'bne', 'bmi', 'bpl', 'bvc', 'bvs',
    # Jump/Call
    'jmp_abs', 'jmp_ind', 'jsr', 'rts', 'rti', 'brk',
    # Transfer
    'tax', 'tay', 'txa', 'tya', 'tsx', 'txs',
    # Stack
    'pha', 'pla', 'php', 'plp',
    # Flags
    'clc', 'sec', 'cld', 'sed', 'cli', 'sei', 'clv',
    # Other
    'nop',
]


def create_6502_3_stage_config() -> PipelineConfig:
    """
    Create 3-stage pipeline configuration for 6502.

    F  -> D   -> XMW
    |      |      |
    v      v      v
    Opcode Decode Execute/Memory/Writeback
    fetch  +RF rd +Data access
           +Addr  +ALU ops
           calc   +Register WB
    """
    return PipelineConfig(
        num_stages=3,
        stage_names=["Fetch", "Decode", "ExecuteMemoryWriteback"],
        cuts=[
            PipelineCut("Decode", "F/D boundary - opcode fetch complete", 1),
            PipelineCut("ExecuteMemoryWriteback", "D/XMW boundary - decode complete", 2),
        ],
        register_read_stage="Decode",
        register_write_stage="ExecuteMemoryWriteback",
        memory_stage="ExecuteMemoryWriteback",
        branch_resolution_stage="ExecuteMemoryWriteback",
    )


def build_merged_graph():
    """Build merged graph of all 6502 instructions."""
    print("Building merged 6502 graph...")

    isa_dir = Path(_project_root) / "isa" / "6502"
    isa_files = sorted(isa_dir.glob("*.isa"))
    instruction_files = {f.stem: str(f) for f in isa_files}

    print(f"  Found {len(instruction_files)} ISA files")

    # Merge with BCD support for standard 6502
    merged = merge_instructions(instruction_files, defines={'CPU_6502_BCD': '1'})

    # CRITICAL: Set 8-bit memory port width for 6502's byte-addressable memory
    mainmem_node = merged.nodes.get('mainmem')
    if mainmem_node:
        mainmem_node.data['port_width'] = 8
        mainmem_node.data['element_width'] = 8
        print("  Set mainmem port_width=8 for byte-addressable memory")

    merged.infer_uarch_time()

    print(f"  Nodes: {len(merged.nodes)}")
    print(f"  Edges: {len(merged.edges)}")

    return merged


def extract_opcode_lengths(graph):
    """Extract opcode value -> instruction length mapping from graph.

    Traces from select_pc_plus_N nodes backwards through instruction enables
    to instr_eq_N comparison nodes to determine which opcodes map to which
    instruction byte lengths (1, 2, or 3).

    Returns:
        dict mapping opcode (int) -> length (int), e.g. {0xAA: 1, 0xA2: 2, ...}
    """
    opcode_lengths = {}

    for node_id, node in graph.nodes.items():
        if not node_id.startswith('select_pc_plus_'):
            continue
        try:
            length = int(node_id.split('select_pc_plus_')[1])
        except (ValueError, IndexError):
            continue

        # BFS backwards to find all instr_eq_N nodes
        visited = set()
        queue = [node]
        while queue:
            current = queue.pop(0)
            if current.id in visited:
                continue
            visited.add(current.id)

            if current.id.startswith('instr_eq_'):
                try:
                    opcode = int(current.id.split('instr_eq_')[1])
                    opcode_lengths[opcode] = length
                except (ValueError, IndexError):
                    pass
                continue  # Don't traverse past comparison nodes

            # Stop at instr node and literals
            if current.id in ('instr', 'mainmem_ibuf_data_0'):
                continue
            if current.data and current.data.get('type') == 'literal':
                continue

            for edge in current.incoming_edges:
                if edge.source.id not in visited:
                    queue.append(edge.source)

    return opcode_lengths


def apply_instruction_buffer(graph: ResourceGraph):
    """Apply instruction buffer optimization for the 6502's variable-length instructions.

    The 6502 fetches 1-3 bytes per instruction from mainmem using PC-relative
    addresses: mainmem[pc], mainmem[pc+1], mainmem[pc+2]. The instruction buffer
    decouples the fetch stage from decode by prefetching bytes into a FIFO buffer.

    After this transformation:
    - mainmem[pc]_rd       -> ibuf output port 0 (opcode byte)
    - mainmem[(pc+1)]_rd   -> ibuf output port 1 (operand byte 1)
    - mainmem[pc_plus_1]_rd -> ibuf output port 1 (shared)
    - mainmem[((pc+1)+1)]_rd -> ibuf output port 2 (operand byte 2)
    - mainmem[pc_plus_2]_rd -> ibuf output port 2 (shared)

    The buffer manages its own fetch address FSM, so fetch is decoupled from the
    pipeline PC. This allows 1 IPC throughput instead of 1/3 IPC.

    Returns:
        True if successfully applied, False otherwise.
    """
    print("\n" + "=" * 70)
    print("APPLYING INSTRUCTION BUFFER OPTIMIZATION")
    print("=" * 70)

    # Step 1: Create instruction length signal from pc_increment_mux select signals.
    # select_pc_plus_1 = OR of 1-byte instructions enables
    # select_pc_plus_2 = OR of 2-byte instruction enables
    # select_pc_plus_3 = OR of 3-byte instruction enables
    # The instruction length node outputs: (sel_1 ? 1 : 0) | (sel_2 ? 2 : 0) | (sel_3 ? 3 : 0)
    instr_len_id = create_instr_length_node(graph, 'ibuf_instr_length')
    if instr_len_id is None:
        print("  WARNING: Could not create instruction length node, skipping ibuf")
        return False

    # Step 2: Apply the instruction buffer.
    # For 6502: 8-bit data bus, 16-bit address, byte-addressable.
    # fetch_width=32 (4 bytes per fetch) to fill the buffer quickly.
    # buffer_size=4 entries = 16 bytes deep (enough for ~5 instructions).
    # flush/redirect wired later after control hazard setup.
    spec = InstructionBufferSpec(
        imem_node='mainmem',
        pc_node='pc_rd',
        instr_width_node=instr_len_id,
        fetch_width=32,
        buffer_size=4,
        data_width=8,
        address_width=16,
        flush_node=None,      # Wired after control hazard handling
        redirect_node=None,   # Wired after control hazard handling
    )

    ibuf = InstructionBufferOptimization(graph)
    success = ibuf.apply(spec)

    if success:
        print("  Instruction buffer applied successfully")
        # Re-infer timing with the new buffer node
        graph.infer_uarch_time(force_reinfer=True)

        # Extract opcode->length mapping for raw consume_bytes decoder.
        # The ibuf_instr_length signal is computed from the PIPED opcode
        # (PIPE_Decode_mainmem_ibuf_data_0_PIPE), which lags one cycle behind
        # the ibuf head.  When consecutive instructions have different lengths,
        # the ibuf read pointer advances by the wrong amount.  Store the
        # mapping so the Verilog generator can emit a combinational decoder
        # that reads the RAW ibuf output (mainmem_ibuf_data_0) directly.
        opcode_lengths = extract_opcode_lengths(graph)
        if opcode_lengths:
            buf_node = graph.nodes.get('mainmem_ibuf')
            if buf_node:
                buf_node.data['raw_opcode_lengths'] = opcode_lengths
                print(f"  Stored opcode->length mapping ({len(opcode_lengths)} opcodes) "
                      f"for raw consume_bytes decoder")
        # Pre-pipeline PC management: these are consequences of ibuf setup.
        # 1. Add default to pc_increment_mux (hold pc_rd when idle)
        from opt.fetch.instruction_buffer_optimization import add_pc_increment_default
        add_pc_increment_default(graph)

        # 2. Remove sequential PC entries from pc_wr_mux (handled by ibuf now)
        from opt.fetch.instruction_buffer_optimization import remove_sequential_pc_entries
        n = remove_sequential_pc_entries(graph)
        if n > 0:
            print(f"  Removed {n} sequential PC entries from pc_wr_mux")
    else:
        print("  WARNING: Instruction buffer optimization failed")

    return success


def select_pipeline_cut_edges(graph: ResourceGraph, config: PipelineConfig,
                              has_ibuf: bool = False):
    """
    Select edges for 6502 3-stage pipeline cuts.

    Based on actual graph analysis:
    - CUT 1 (F/D): ~5 edges (or ~1 + ibuf ports with instruction buffer)
    - CUT 2 (D/XMW): ~1089 edges

    Args:
        has_ibuf: If True, instruction buffer has replaced PC-relative memory
                  reads with ibuf output ports. Cut those instead.
    """

    print("\n" + "=" * 70)
    print("PIPELINE CUT EDGE SELECTION (3-stage 6502)")
    print(f"Stages: Fetch -> Decode -> ExecuteMemoryWriteback (ibuf={has_ibuf})")
    print("=" * 70)

    cuts = {cut.name: [] for cut in config.cuts}

    # Helper functions
    def find_edge(src_id, tgt_id):
        for edge_id, edge in graph.edges.items():
            if edge.source.id == src_id and edge.target.id == tgt_id:
                return edge_id
        return None

    def find_edges_from(src_id):
        return [(eid, e.target.id) for eid, e in graph.edges.items()
                if e.source.id == src_id]

    # ========================================
    # CUT 1: F/D - Fetch -> Decode
    # ========================================
    print("\nCUT 1: Fetch -> Decode")
    print("-" * 50)

    if has_ibuf:
        # With instruction buffer: ibuf output ports replace mainmem[pc+N]_rd.
        # The ibuf data ports (mainmem_ibuf_data_0, _1, _2) are in Fetch;
        # their consumers (instr, operand bytes) are in Decode.
        # Cut all outgoing edges from ibuf data ports.
        #
        # CRITICAL: Some consumers need TWO-stage piping (F->D->XMW):
        #   - Immediate operand aliases (adc_imm_imm, lda_imm_imm, sbc_imm_data)
        #     feed into ALU computations and register write muxes in XMW.
        # Other consumers only need ONE-stage piping (F->D):
        #   - Address calculations (contain 'addr' or 'base') stay in Decode
        #   - Branch offset ('offset') stays in Decode (piped to sync with opcode)
        #   - Instruction decode ('instr') stays in Decode
        # Putting an edge in both CUT 1 and CUT 2 makes the pipeline transform
        # extend the chain: source -> PIPE_Decode -> PIPE_XMW -> consumer.
        ibuf_xmw_edges = []  # Collect edges needing two-stage piping
        for node_id in sorted(graph.nodes.keys()):
            if node_id.startswith('mainmem_ibuf_data_'):
                for eid, tgt in find_edges_from(node_id):
                    cuts['Decode'].append(eid)
                    # Check if this consumer needs XMW-stage value
                    decode_only = (tgt == 'instr' or tgt == 'offset' or
                                   'addr' in tgt or 'base' in tgt)
                    if decode_only:
                        print(f"  [F/D] {node_id} -> {tgt} (Decode-only)")
                    else:
                        ibuf_xmw_edges.append((eid, node_id, tgt))
                        print(f"  [F/D+D/XMW] {node_id} -> {tgt} (needs two-stage pipe)")
    else:
        # Without instruction buffer: cut the original mainmem[pc]_rd -> instr edge
        eid = find_edge('mainmem[pc]_rd', 'instr')
        if eid:
            cuts['Decode'].append(eid)
            print(f"  [F/D] mainmem[pc]_rd -> instr (8-bit opcode)")

    # 1.2 PC value for operand addresses and mux default
    # Pipeline PC to Decode so it can compute (pc+1), (pc+2) for operand fetches.
    # The mux_default_input edge (pc_rd -> pc_increment_mux) must NOT be piped:
    # it provides the raw current PC as the default so the mux holds PC during
    # pipeline fill/flush (when no select is active).
    #
    # With ibuf, pc_rd is the fetch-side PC (may be ahead of Decode). The pipe
    # register must source from pc_wr (combinational write input) not pc_rd
    # (registered output), otherwise there's a double-register delay. We reroute
    # the graph edges from pc_rd -> target to pc_wr -> target before cutting, so
    # the pipeline infrastructure creates the pipe register with the correct source.
    pc_decode_targets = {'(pc + 1)', 'pc_plus_1', 'pc_plus_2', 'pc_plus_3', 'pc_increment_mux'}
    pc_wr_node = graph.nodes.get('pc_wr') if has_ibuf else None
    for eid, tgt in find_edges_from('pc_rd'):
        if tgt in pc_decode_targets:
            edge = graph.edges.get(eid)
            if edge and edge.data.get('type') == 'mux_default_input':
                print(f"  [SKIP] pc_rd -> {tgt} (mux_default_input, must stay un-piped)")
                continue
            if has_ibuf and pc_wr_node:
                # Reroute: pc_rd -> target becomes pc_wr -> target
                # This makes the pipe register source from pc_wr (correct timing)
                target_node = edge.target
                edge_data = dict(edge.data)
                graph.remove_edge(eid)
                new_edge = Edge(pc_wr_node, target_node, data=edge_data)
                graph.add_edge(new_edge)
                cuts['Decode'].append(new_edge.id)
                print(f"  [F/D] pc_wr -> {tgt} (PC for Decode, rerouted from pc_rd)")
            else:
                cuts['Decode'].append(eid)
                print(f"  [F/D] pc_rd -> {tgt} (PC for Decode)")

    print(f"  Cut 1 edges: {len(cuts['Decode'])}")

    # ========================================
    # CUT 2: D/XMW - Decode -> ExecuteMemoryWriteback (~1089 edges)
    # ========================================
    print("\nCUT 2: Decode -> ExecuteMemoryWriteback")
    print("-" * 50)

    xmw = 'ExecuteMemoryWriteback'

    # 2.0 ibuf data two-stage piping (F->D->XMW)
    # Edges collected during CUT 1 that need XMW-stage values.
    # Adding the same edge_id to both CUT 1 and CUT 2 makes the pipeline
    # transform extend the chain through both stages.
    if has_ibuf and ibuf_xmw_edges:
        print("\n  2.0 ibuf data -> XMW (two-stage pipe extensions):")
        for eid, src, tgt in ibuf_xmw_edges:
            cuts[xmw].append(eid)
            print(f"      {src} -> {tgt}")
        print(f"      {len(ibuf_xmw_edges)} edges added to CUT 2")

    # Helper: detect constant/literal nodes that may not have type='constant'
    import re
    _const_re = re.compile(r"^(\d+|(\d+)'[hHbBdD][0-9a-fA-F_]+)$")
    def is_constant_node(node):
        """Check if node is a constant/literal value."""
        if node.data.get('type') == 'constant':
            return True
        return bool(_const_re.match(node.id))

    # Build set of address computation nodes that must stay in Decode.
    # When moving ALL memory reads to Decode, the addresses for indirect
    # and stack reads are now also computed in Decode. These intermediate
    # computation nodes must NOT have their input edges piped.
    xmw_indirect_addrs = {
        'ind_x_target_addr',             # (ind,X) target address
        'ind_y_target_addr',             # (ind,Y) target address
        '{target_hi, target_lo}',        # (ind,X) pointer read for AND/EOR/ORA
        '({base_hi, base_lo} + Y)',      # (ind,Y) pointer+Y read for AND/EOR/ORA
    }

    decode_addr_computation_nodes = set()
    # Start from nodes that form addresses for previously-XMW memory reads
    addr_seed_names = list(xmw_indirect_addrs)
    # Also add stack address nodes
    for nid in graph.nodes:
        if ('stack_addr' in nid and not nid.startswith('PIPE_')
                and not nid.startswith('mainmem')):
            addr_seed_names.append(nid)
    # BFS backwards from each seed, following only data-path edges
    # (not mux_select/control edges which lead to instruction enables)
    data_edge_types = {
        'operand', 'left_operand', 'right_operand',
        'mux_input', 'mux_default_input', 'assignment',
        'pipeline_input', 'concat_input', None,
    }
    control_edge_types = {
        'mux_select', 'write_enable', 'enable', 'control',
        'stall', 'ibuf_flush', 'ibuf_redirect_addr',
    }
    for seed_name in addr_seed_names:
        seed = graph.nodes.get(seed_name)
        if not seed:
            continue
        queue = [seed]
        visited = set()
        while queue:
            node = queue.pop(0)
            if node.id in visited:
                continue
            visited.add(node.id)
            decode_addr_computation_nodes.add(node.id)
            for edge in node.incoming_edges:
                src = edge.source
                # Only follow data-path edges, skip control edges
                edge_type = edge.data.get('type')
                if edge_type in control_edge_types:
                    continue
                # Stop at memory reads, register reads, constants
                if (src.id.startswith('mainmem[') or
                        src.id.startswith('mainmem_ibuf') or
                        src.id in ('A_rd', 'X_rd', 'Y_rd', 'S_rd') or
                        is_constant_node(src)):
                    continue
                queue.append(src)

    print(f"\n  Decode address computation nodes ({len(decode_addr_computation_nodes)}):")
    for nid in sorted(decode_addr_computation_nodes):
        print(f"    {nid}")

    # 2.1 CPU Register reads: A_rd, X_rd, Y_rd, S_rd
    # Cut edges from register reads to XMW consumers.
    #
    # SKIP feedback/hold paths: each register's write mux has a
    # mux_default_input edge from the register's read port (e.g.,
    # A_rd -> A_wr_mux). This "hold" path keeps the register value
    # when no instruction writes. Piping it would make the default
    # one cycle stale, causing registers to oscillate.
    #
    # SKIP Decode-stage address computations: X_rd/Y_rd edges to address
    # adders (e.g., base_addr_add_X = base + X_rd) must stay in Decode
    # because the base address is from ibuf_data (Decode-stage). Piping
    # X/Y would make the adder use XMW-piped values that correspond to a
    # different instruction, producing wrong addresses.
    # All indirect and stack address computation nodes also stay in Decode
    # since all memory reads are now Decode-stage.
    print("\n  2.1 Register reads (A, X, Y, S):")
    reg_count = 0
    reg_skip = 0

    # Address adder targets that should use Decode-stage X/Y values.
    # These are the graph node IDs (not Verilog names) for address adders
    # whose base address comes from ibuf_data (Decode-stage operand bytes)
    # or from Decode-stage pointer data (now that all reads are in Decode).
    decode_addr_adder_targets = {
        '(base_addr + X)',              # abs,X: operand_base + X
        'adc_abs_y_(base_addr + Y)',    # abs,Y: operand_base + Y
        '({addr_hi, addr_lo} + X)',     # 16-bit indexed: {hi,lo} + X
        '({addr_hi, addr_lo} + Y)',     # 16-bit indexed: {hi,lo} + Y
        '(zp_base + X)',               # zp,X / ind,X ZP base: zp + X
        '(zp_base + Y)',               # zp,Y: zp + Y
        # Indirect Y now computed in Decode (pointer data is Decode-stage)
        '({base_hi, base_lo} + Y)',     # ind,Y: pointer + Y
        'adc_ind_y_(base_addr + Y)',    # ind,Y ADC variant
    }

    for reg in ['A_rd', 'X_rd', 'Y_rd', 'S_rd']:
        if reg in graph.nodes:
            wr_mux = reg.replace('_rd', '_wr_mux')
            edges = find_edges_from(reg)
            for eid, tgt in edges:
                edge = graph.edges[eid]
                # Skip feedback/hold path (register read -> own write mux default)
                if tgt == wr_mux and edge.data.get('type') == 'mux_default_input':
                    print(f"      SKIP (feedback/hold): {reg} -> {tgt}")
                    reg_skip += 1
                    continue
                # Skip Decode-stage address adder inputs
                if tgt in decode_addr_adder_targets:
                    print(f"      SKIP (Decode addr): {reg} -> {tgt}")
                    reg_skip += 1
                    continue
                # Skip address computation nodes that must stay in Decode
                if tgt in decode_addr_computation_nodes:
                    print(f"      SKIP (Decode addr computation): {reg} -> {tgt}")
                    reg_skip += 1
                    continue
                cuts[xmw].append(eid)
                reg_count += 1
    print(f"      {reg_count} edges pipelined, {reg_skip} skipped")

    # 2.2 Flag reads
    # Cut edges from flag reads to XMW consumers.
    # SKIP feedback/hold paths: same as section 2.1, each flag's write
    # mux has a mux_default_input from the flag's read port.
    # notflag_* nodes don't have write muxes, so no skip needed for those.
    print("\n  2.2 Flag reads:")
    flag_count = 0
    flag_skip = 0
    for flag in ['flag_C_rd', 'flag_Z_rd', 'flag_N_rd', 'flag_V_rd',
                 'flag_D_rd', 'flag_I_rd',
                 'notflag_C_rd', 'notflag_Z_rd', 'notflag_N_rd', 'notflag_V_rd']:
        if flag in graph.nodes:
            wr_mux = flag.replace('_rd', '_wr_mux')
            edges = find_edges_from(flag)
            for eid, tgt in edges:
                edge = graph.edges[eid]
                # Skip feedback/hold path (flag read -> own write mux default)
                if tgt == wr_mux and edge.data.get('type') == 'mux_default_input':
                    print(f"      SKIP (feedback/hold): {flag} -> {tgt}")
                    flag_skip += 1
                    continue
                cuts[xmw].append(eid)
                flag_count += 1
    print(f"      {flag_count} edges pipelined, {flag_skip} feedback paths skipped")

    # 2.3 Memory data reads (operands, zero-page, indirect, stack)
    #
    # ALL data memory reads are now Decode-stage (address computation moved
    # to Decode). Only skip: opcode fetch (mainmem[pc]_rd), ibuf fetch.
    # Memory RAW hazards (store-to-load) are resolved by enable-only stalling
    # in apply_hazard_resolution().
    #
    # For edges going to address computation nodes (decode_addr_computation_nodes),
    # we skip piping: those edges carry data needed for computing addresses of
    # OTHER reads within the same Decode stage.
    #
    # Without ibuf: only PC-relative and constant addresses are Decode-stage
    # (same as before).
    #
    # EXCEPTION: mainmem[pc_plus_1]_rd -> offset must NOT be cut (without ibuf).
    # With ibuf, the offset is handled via ibuf_data port (already cut in CUT 1).
    print("\n  2.3 Memory data reads (all Decode-stage):")
    mem_count = 0
    mem_skip = 0
    for node_id in sorted(graph.nodes.keys()):
        if not (node_id.startswith('mainmem[') and node_id.endswith(']_rd')):
            continue
        if node_id == 'mainmem[pc]_rd':
            continue  # Opcode fetch stays in Fetch stage

        # Skip ibuf fetch access (internal to buffer, not a Decode read)
        if 'ibuf' in node_id:
            continue

        # Extract address part from mainmem[ADDRESS]_rd
        addr_part = node_id[len('mainmem['):-len(']_rd')]

        # Check if address is Decode-stage.
        # With ibuf: ALL non-fetch memory reads are Decode-stage.
        # Without ibuf: only PC-relative and constant addresses are Decode-stage.
        if has_ibuf:
            is_decode_addr = True  # All non-fetch reads are now Decode-stage
        else:
            is_decode_addr = (addr_part.startswith('pc') or
                              addr_part.startswith('(pc') or
                              addr_part.startswith("16'h") or
                              addr_part.startswith('16_h'))

        if not is_decode_addr:
            # Without ibuf: XMW-stage read - skip
            mem_skip += 1
            continue

        edges = find_edges_from(node_id)
        for eid, tgt in edges:
            # Keep branch offset in Decode for correct branch dest computation
            if tgt == 'offset':
                print(f"      SKIP (Decode branch dest): {node_id} -> {tgt}")
                continue
            # Skip edges feeding into address computation for other reads
            if tgt in decode_addr_computation_nodes:
                print(f"      SKIP (addr computation, stays in Decode): {node_id} -> {tgt}")
                continue
            cuts[xmw].append(eid)
            mem_count += 1
    print(f"      {mem_count} edges piped (Decode-stage reads)")
    print(f"      {mem_skip} reads skipped (non-Decode addresses)")

    # 2.4 Instruction enable signals
    # These control which operation executes in XMW stage.
    # Skip *_rd_enable nodes (these gate register/memory reads in Decode).
    # Skip composite enables (ORs of individual enables, e.g. mainmem_write_enable)
    # because they would be double-piped: individual enables are piped by this section,
    # making the composite an XMW signal. Piping the composite again would delay it
    # by an extra cycle, causing memory writes to fire with wrong data/addresses.
    print("\n  2.4 Instruction enable signals:")

    # Identify degenerate AND nodes on pc_wr_mux: compound selects where both
    # operands come from the same enable (e.g., jsr_enable && jsr_enable).
    # These must stay in Decode as a unit — piping the operand edges individually
    # causes cross-timing (one gets piped, one doesn't). Instead, pipe the
    # compound select's mux_select output edge to XMW.
    pc_wr_mux_compound_selects = set()
    pc_wr_mux_node = graph.nodes.get('pc_wr_mux')
    if pc_wr_mux_node:
        for edge in pc_wr_mux_node.incoming_edges:
            if edge.data.get('type') != 'mux_select':
                continue
            select_node = edge.source
            operand_edges = [e for e in select_node.incoming_edges
                             if e.data.get('type') == 'operand']
            operand_sources = set(e.source.id for e in operand_edges)
            if len(operand_sources) == 1 and len(operand_edges) == 2:
                pc_wr_mux_compound_selects.add(select_node.id)
                cuts[xmw].append(edge.id)
                print(f"    Compound select ({select_node.id}): "
                      f"pipe output to XMW, operands stay in Decode")

    # Build skip list for source enables
    skip_source = set()
    for node_id in graph.nodes:
        if node_id.endswith('_rd_enable'):
            skip_source.add(node_id)

    # Also skip composite enables (those with inputs from other _enable nodes).
    # These are computed from piped enables in XMW and must not be piped again.
    for eid in graph.edges:
        edge = graph.edges[eid]
        if (edge.source.id.endswith('_enable') and
                edge.target.id.endswith('_enable') and
                edge.target.id not in skip_source):
            skip_source.add(edge.target.id)
            print(f"    SKIP composite enable: {edge.target.id} (input from {edge.source.id})")

    # Decode-stage address mux enable OR nodes. These select which address
    # feeds the memory read port. Since ALL address computation now happens
    # in Decode (all reads moved to Decode), ALL mux enables must stay in
    # Decode — including indirect target mux enables.
    decode_addr_mux_enables = {
        'abs_x_addr_mux_enable_or_0',
        'adc_abs_y_addr_mux_enable_or_0',
        'ind_x_zp_addr_mux_enable_or_0',
        'zp_y_addr_mux_enable_or_0',
        'adc_zp_x_zp_x_addr_mux_enable_or_0',
        # Indirect target mux enables (address now computed in Decode)
        'ind_y_target_addr_mux_enable_or_0',
        'ind_x_target_addr_mux_enable_or_0',
    }
    # Also dynamically add any enable nodes that are in decode_addr_computation_nodes
    for nid in decode_addr_computation_nodes:
        if nid.endswith('_enable_or_0') or nid.endswith('_mux_enable_or_0'):
            decode_addr_mux_enables.add(nid)
    # For mux nodes in the set, their enables must also stay in Decode.
    # Enable names follow pattern: {mux_name}_enable_or_0
    # These enables aren't in the set (BFS skips control edges) but must be un-piped.
    for nid in decode_addr_computation_nodes:
        if nid.endswith('_mux') and not nid.startswith('PIPE_'):
            enable_name = nid + '_enable_or_0'
            if enable_name in graph.nodes:
                decode_addr_mux_enables.add(enable_name)
                print(f"    Added Decode mux enable: {enable_name} (for {nid})")

    enable_count = 0
    enable_skip_pc = 0
    enable_skip_addr = 0
    for node_id in sorted(graph.nodes.keys()):
        if not node_id.endswith('_enable'):
            continue
        if node_id in skip_source:
            continue

        edges = find_edges_from(node_id)
        for eid, tgt in edges:
            # Skip edges to read enables (stay in Decode)
            if tgt.endswith('_rd_enable'):
                continue
            # Skip edges to PC length select signals (stay in Decode).
            # select_pc_plus_1/2/3 must use raw Decode-stage enables so that
            # pc_increment_mux computes the next PC from the currently-decoded
            # instruction, not the retired XMW instruction. Without this, PC
            # only advances when XMW is valid, causing stall deadlocks.
            if tgt.startswith('select_pc_plus_') or tgt.startswith('select_pc_add_'):
                enable_skip_pc += 1
                continue
            # Skip edges to Decode-stage address mux enable OR nodes.
            # These must stay in Decode to match the Decode-stage address
            # computation from ibuf_data + X/Y.
            if tgt in decode_addr_mux_enables:
                enable_skip_addr += 1
                continue
            # Skip edges to compound select nodes (X && X) — their output
            # is already piped to XMW; operands must stay raw in Decode.
            if tgt in pc_wr_mux_compound_selects:
                continue
            cuts[xmw].append(eid)
            enable_count += 1
    print(f"      {enable_count} edges")
    if enable_skip_pc:
        print(f"      {enable_skip_pc} edges kept in Decode (PC length selects)")
    if enable_skip_addr:
        print(f"      {enable_skip_addr} edges kept in Decode (addr mux enables)")

    # 2.5 Branch/jump targets and PC values
    #
    # pc_plus_1/2/3 and (pc + 1) feed into both:
    #   - Memory address calculations (stay in Decode - these are read addresses)
    #   - PC update logic (must be pipelined to XMW for correct next-PC)
    #   - Branch destination computation (Decode-internal)
    #
    # We cut ALL edges EXCEPT those to:
    #   - Memory read ports (mainmem[*]_rd) — stay in Decode
    #   - Internal Decode computations like (pc_plus_1 + 1), ((pc+1)+1)
    #   - Branch dest computation: (pc_plus_2 + sign_ext_offset)
    #   - ibuf-related nodes (buffer internals)
    print("\n  2.5 Branch/jump targets and PC values:")
    target_count = 0

    # 2.5.1 PC increment values and (pc + 1) -> XMW consumers
    # Decode-internal targets: memory reads, intermediate calcs, ibuf signals
    decode_only_patterns = ['mainmem', '((pc', 'ibuf']
    # Also skip edges to intermediate PC calculations that stay in Decode:
    # (pc + 1) -> pc_plus_1 (assignment), pc_plus_1 -> (pc_plus_1 + 1), etc.
    decode_intermediate_targets = {
        '(pc + 1)': {'pc_plus_1', '((pc + 1) + 1)', 'mainmem[(pc + 1)]_rd'},
        'pc_plus_1': {'(pc_plus_1 + 1)', 'mainmem[pc_plus_1]_rd', 'pc_increment_mux'},
        'pc_plus_2': {'(pc_plus_2 + sign_ext_offset)', 'mainmem[pc_plus_2]_rd', 'pc_increment_mux'},
        'pc_plus_3': {'pc_increment_mux'},
    }

    for pc_node in ['(pc + 1)', 'pc_plus_1', 'pc_plus_2', 'pc_plus_3']:
        if pc_node not in graph.nodes:
            continue
        intermediates = decode_intermediate_targets.get(pc_node, set())
        edges = find_edges_from(pc_node)
        for eid, tgt in edges:
            # Skip Decode-internal targets
            if tgt in intermediates:
                print(f"      SKIP (Decode-internal): {pc_node} -> {tgt}")
                continue
            # Skip targets matching Decode-only patterns
            if any(pat in tgt for pat in decode_only_patterns):
                print(f"      SKIP (Decode-only): {pc_node} -> {tgt}")
                continue
            cuts[xmw].append(eid)
            target_count += 1
            print(f"      {pc_node} -> {tgt}")

    # 2.5.2 Jump/branch target addresses
    #
    # Without ibuf: These targets are computed from piped memory reads
    # (section 2.3), so they're already in XMW. No cuts needed.
    #
    # With ibuf: ALL jump/branch targets are now computed in Decode
    # (since all memory reads moved to Decode). They must all be piped
    # to XMW for PC update.
    if has_ibuf:
        # With ibuf: all targets now Decode-stage, need piping to XMW
        ibuf_jump_targets = [
            'jmp_abs_target_addr', 'jsr_target_addr',
            # Return addresses now computed in Decode (stack reads moved)
            'rti_return_addr', 'return_addr_add_1', '(return_addr + 1)',
            'jmp_ind_target_addr',  # JMP indirect target now in Decode too
            'irq_addr',  # BRK vector address now in Decode
        ]
        xmw_jump_targets = []  # All targets are now Decode-stage
        for target in ibuf_jump_targets:
            if target in graph.nodes:
                edges = find_edges_from(target)
                for eid, tgt in edges:
                    cuts[xmw].append(eid)
                    target_count += 1
                    print(f"      {target} -> {tgt} (Decode-stage, needs piping)")
        for target in xmw_jump_targets:
            if target in graph.nodes:
                edges = find_edges_from(target)
                for eid, tgt in edges:
                    print(f"      SKIP (already XMW): {target} -> {tgt}")
    else:
        # Without ibuf: all targets computed from piped reads, already XMW
        jump_targets = [
            'jmp_abs_target_addr', 'jsr_target_addr', 'jmp_ind_target_addr',
            'irq_addr', 'rti_return_addr', '(return_addr + 1)',
            'return_addr_add_1',
        ]
        for target in jump_targets:
            if target in graph.nodes:
                edges = find_edges_from(target)
                for eid, tgt in edges:
                    print(f"      SKIP (already XMW): {target} -> {tgt}")

    # 2.5.3 Branch destination: (pc_plus_2 + sign_ext_offset) -> branch_dest_mux
    # This is computed in Decode from piped PC and Decode-local sign_ext_offset.
    # It must be piped to XMW because branch_dest_mux's enable is piped (section 2.4).
    branch_dest_node = '(pc_plus_2 + sign_ext_offset)'
    if branch_dest_node in graph.nodes:
        edges = find_edges_from(branch_dest_node)
        for eid, tgt in edges:
            cuts[xmw].append(eid)
            target_count += 1
            print(f"      {branch_dest_node} -> {tgt}")
    # 2.5.4 Return address values for JSR/BRK
    # jsr_return_addr and brk_return_addr are computed combinationally from
    # PIPE_Decode_pc_rd_PIPE (via the (pc+1)→(+1)→(+1)→(-1) chain).
    # They feed into XMW-stage memory write data muxes but are not piped.
    # Without piping, they recompute from the CURRENT Decode PC at XMW time
    # (wrong instruction). Piping captures the correct value when JSR/BRK
    # is actually in Decode.
    return_addr_nodes = ['jsr_return_addr', 'brk_return_addr']
    for ra_node in return_addr_nodes:
        if ra_node in graph.nodes:
            edges = find_edges_from(ra_node)
            for eid, tgt in edges:
                cuts[xmw].append(eid)
                target_count += 1
                print(f"      {ra_node} -> {tgt} (return addr, needs piping)")

    print(f"      {target_count} edges total")

    # 2.6 Memory write addresses (ibuf mode)
    #
    # With ibuf: ALL write addresses are now computed in Decode (since all
    # reads and address computations moved to Decode). Pipe all non-piped
    # address inputs to the write address mux so they arrive at XMW for writes.
    # Stack addresses and indirect target addresses are no longer exceptions —
    # they're Decode-stage now too and need piping.
    if has_ibuf:
        print("\n  2.6 Memory write addresses (ibuf mode):")
        write_addr_count = 0
        write_addr_skip = 0

        for node_id in sorted(graph.nodes.keys()):
            if not node_id.startswith('mainmem_write_addr_mux'):
                continue
            # Find all incoming mux_input edges (data, not selects) to this mux
            edges_in = [(eid, e.source.id) for eid, e in graph.edges.items()
                        if e.target.id == node_id
                        and e.data and e.data.get('type') == 'mux_input']
            for eid, src in edges_in:
                # Skip already-piped sources
                if src.startswith('PIPE_'):
                    print(f"      SKIP (already piped): {src} -> {node_id}")
                    write_addr_skip += 1
                    continue
                # All Decode-stage addresses need piping to XMW
                cuts[xmw].append(eid)
                write_addr_count += 1
                print(f"      {src} -> {node_id}")

        print(f"      {write_addr_count} write addr edges piped")
        print(f"      {write_addr_skip} skipped")

    # 2.7 Pipe Decode-stage computation results to register write muxes
    #
    # Some nodes in decode_addr_computation_nodes serve dual purposes:
    # address computation (stays in Decode) AND register write data (needs
    # piping to XMW). For example, pla_new_S = S+1 computes both the stack
    # read address AND the new S value to write back.
    #
    # For DIRECT edges (set node -> wr_mux), pipe that edge.
    # For TRANSITIVE paths (set node -> intermediate(s) -> wr_mux), pipe
    # the BOUNDARY edge (set node -> first intermediate), NOT the wr_mux
    # edge. This ensures intermediate muxes compute in XMW where their
    # piped enables are also available.
    if has_ibuf:
        print("\n  2.7 Decode computation results -> register write muxes:")
        wr_mux_count = 0
        wr_mux_names = set()
        for nid in graph.nodes:
            if nid.endswith('_wr_mux') and not nid.startswith('PIPE_'):
                wr_mux_names.add(nid)

        # First handle DIRECT edges: set node -> wr_mux
        for comp_node_id in sorted(decode_addr_computation_nodes):
            comp_node = graph.nodes.get(comp_node_id)
            if not comp_node:
                continue
            for edge in comp_node.outgoing_edges:
                tgt = edge.target.id
                if tgt in wr_mux_names:
                    cuts[xmw].append(edge.id)
                    wr_mux_count += 1
                    print(f"      {comp_node_id} -> {tgt} (direct)")

        # Then handle TRANSITIVE paths: pipe boundary edges from set to
        # non-set nodes that eventually feed wr_mux.
        # For each outgoing data edge from a set node to a non-set node,
        # check if that non-set node transitively feeds a wr_mux.
        for comp_node_id in sorted(decode_addr_computation_nodes):
            comp_node = graph.nodes.get(comp_node_id)
            if not comp_node:
                continue
            for edge in comp_node.outgoing_edges:
                tgt = edge.target
                tgt_id = tgt.id
                # Skip if target is in the set (internal edge, stays in Decode)
                if tgt_id in decode_addr_computation_nodes:
                    continue
                # Skip if target is already a wr_mux (handled above as direct)
                if tgt_id in wr_mux_names:
                    continue
                # Skip if target is a PIPE_ node or control edge
                if tgt_id.startswith('PIPE_'):
                    continue
                etype = edge.data.get('type')
                if etype in control_edge_types:
                    continue
                # Skip edges to memory read/write nodes (handled by other sections)
                if (tgt_id.startswith('mainmem[') or
                        tgt_id.startswith('mainmem_write') or
                        tgt_id.startswith('mainmem_shared')):
                    continue
                # Forward BFS from target to check if it (transitively) feeds wr_mux
                visited_fwd = set()
                queue_fwd = [tgt]
                feeds_wr_mux = False
                while queue_fwd and not feeds_wr_mux:
                    n = queue_fwd.pop(0)
                    if n.id in visited_fwd:
                        continue
                    visited_fwd.add(n.id)
                    for out_edge in n.outgoing_edges:
                        out_tgt = out_edge.target.id
                        if out_tgt in wr_mux_names:
                            feeds_wr_mux = True
                            break
                        # Only follow through non-set, non-piped computation nodes
                        if (out_tgt in decode_addr_computation_nodes or
                                out_tgt.startswith('PIPE_')):
                            continue
                        out_etype = out_edge.data.get('type')
                        if out_etype in control_edge_types:
                            continue
                        out_node = graph.nodes.get(out_tgt)
                        if out_node:
                            queue_fwd.append(out_node)
                if feeds_wr_mux:
                    cuts[xmw].append(edge.id)
                    wr_mux_count += 1
                    print(f"      {comp_node_id} -> {tgt_id} (boundary, feeds wr_mux)")

        print(f"      {wr_mux_count} edges piped")

    # Remove duplicates
    for stage in cuts:
        cuts[stage] = list(set(cuts[stage]))

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
    print(f"  Stage order: {stage_order}")
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
            print(f"  Stage {stage_name}: {len(cuts[stage_name])} edges (pipe_time={cut.stage_index})")

    # Apply pipeline stages
    print("\nInserting pipeline registers...")
    success = transform.add_multiple_pipeline_stages(cut_specs)

    if success:
        summary = transform.get_pipeline_summary()
        print(f"\nPipeline transformation successful!")
        print(f"  Total stages: {summary['total_stages']}")
        print(f"  Max uarch_time: {summary['max_uarch_time']}")
    else:
        print("Pipeline transformation FAILED!")

    return success


def apply_hazard_resolution(graph: ResourceGraph, config: PipelineConfig):
    """
    Analyze and resolve data hazards for 6502.

    Uses the unified analyze_hazards() which discovers both:
    - Individual ISA state hazards (A, X, Y, S, flags) — non-indexed
    - Array-indexed hazards (mainmem) — indexed
    """
    print("\n" + "=" * 70)
    print("ANALYZING AND RESOLVING DATA HAZARDS")
    print("Strategy: STALL (6502 individual ISA states)")
    print("=" * 70)

    analyzer = HazardAnalyzer(graph, pc_name='pc')
    analyzer.identify_pipeline_stages()

    # Unified hazard detection: discovers both individual registers (A, X, Y, S, flags)
    # and array-indexed resources (mainmem) in a single pass
    print("\nAnalyzing all hazards...")
    all_hazards = analyzer.analyze_hazards()

    # Separate for reporting and per-category resolution strategy
    individual_hazards = [h for h in all_hazards if not h.is_indexed]
    indexed_hazards = [h for h in all_hazards if h.is_indexed]

    print(f"\nDetected {len(individual_hazards)} individual ISA state hazard(s)")
    print(f"Detected {len(indexed_hazards)} array-indexed hazard(s)")

    if individual_hazards:
        print("\nIndividual ISA state hazards (first 15):")
        for i, hazard in enumerate(individual_hazards[:15]):
            print(f"  {i+1}. {hazard}")
        if len(individual_hazards) > 15:
            print(f"  ... and {len(individual_hazards) - 15} more")

    # Create resolver - gate PC during stalls
    resolver = HazardResolver(graph, isa_states_to_gate=['pc_rd'], pipeline_config=config)

    # Set individual register hazards to STALL resolution
    for hazard in individual_hazards:
        hazard.resolution = HazardResolutionStrategy.STALL

    # Memory hazards: report but don't auto-resolve with stalling.
    # Memory RAW hazards (store-to-load) are currently handled by
    # fix_memory_write_forwarding which adds data forwarding logic.
    # Stalling on every memory write would be too conservative since
    # almost every instruction reads from memory (at least for fetch).
    mem_hazards = [h for h in indexed_hazards if h.resource != 'rf']
    rf_hazards = [h for h in indexed_hazards if h.resource == 'rf']
    data_hazards = []  # Populated from mem_hazards below (excluding fetch hazards)

    if mem_hazards:
        print(f"\nMemory hazards detected ({len(mem_hazards)}):")
        # Group by resource, then show writes and reads with stages
        from collections import defaultdict
        by_resource = defaultdict(list)
        for h in mem_hazards:
            by_resource[h.resource].append(h)
        for res, hazards_group in sorted(by_resource.items()):
            # Collect unique writes and reads with stages
            writes = {}
            reads = {}
            for h in hazards_group:
                wkey = (h.write_index_name, h.write_stage_name)
                rkey = (h.read_index_name, h.read_stage_name)
                writes[wkey] = h.write_stage
                reads[rkey] = h.read_stage
            print(f"\n  {res} writes ({len(writes)}):")
            for (idx, stage_name), stage in sorted(writes.items(), key=lambda x: x[1]):
                print(f"    stage {stage} ({stage_name}): {res}[{idx}]")
            print(f"  {res} reads ({len(reads)}):")
            for (idx, stage_name), stage in sorted(reads.items(), key=lambda x: x[1]):
                print(f"    stage {stage} ({stage_name}): {res}[{idx}]")

        # Set resolution per-hazard: STALL_ENABLE_ONLY for Decode reads, skip instruction fetch
        fetch_hazards = []
        for h in mem_hazards:
            # Instruction fetch reads are at stage 0 (Fetch) or have ibuf_fetch in index
            is_fetch = (h.read_stage == 0 or
                        (h.read_index_name and 'ibuf_fetch' in h.read_index_name) or
                        h.read_index_name in ("16'hFFFE", "16'hFFFF"))
            if is_fetch:
                fetch_hazards.append(h)
                h.resolution = HazardResolutionStrategy.NONE
            else:
                data_hazards.append(h)
                h.resolution = HazardResolutionStrategy.STALL_ENABLE_ONLY

        if fetch_hazards:
            print(f"\n  {len(fetch_hazards)} instruction fetch hazards (unresolved - by design)")
        if data_hazards:
            print(f"\n  {len(data_hazards)} data memory hazards -> enable-only stall")

    for hazard in rf_hazards:
        hazard.resolution = HazardResolutionStrategy.STALL

    success = True

    # Resolve all hazards through the unified path:
    # - Individual (1D) hazards: write_enable && stage_valid
    # - RF (indexed) hazards: index_cmp && write_enable && stage_valid
    # - Memory (STALL_ENABLE_ONLY): write_enable && stage_valid (no index comparison)
    hazards_to_resolve = individual_hazards + rf_hazards + data_hazards
    if hazards_to_resolve:
        print(f"\nResolving {len(hazards_to_resolve)} hazards through unified path...")
        success = resolver.resolve_all_hazards(hazards_to_resolve)
        if success:
            print("  All hazards resolved successfully")
        else:
            print("  WARNING: Some hazards could not be resolved")

    return success, resolver


def apply_control_hazard_handling(graph: ResourceGraph, config: PipelineConfig, resolver):
    """
    Apply control hazard handling for 6502 branches and jumps.

    6502 has variable-length instructions (1-3 bytes), so speculative fetch
    after a branch can fetch garbage. We use conservative stall-based approach:
    stall when a branch/jump is detected until it resolves.

    Branches (conditional):
    - beq: branch if Z=1
    - bne: branch if Z=0
    - bcc: branch if C=0
    - bcs: branch if C=1
    - bmi: branch if N=1
    - bpl: branch if N=0
    - bvc: branch if V=0
    - bvs: branch if V=1

    Jumps (unconditional):
    - jmp_abs, jmp_ind: direct jumps
    - jsr: jump to subroutine
    - rts: return from subroutine
    - rti: return from interrupt
    """
    print("\n" + "=" * 70)
    print("APPLYING CONTROL HAZARD HANDLING")
    print("Strategy: Stall on branch/jump detection, flush on taken")
    print("=" * 70)

    # Define 6502 branch conditions - map instruction to condition node
    # For 6502, the "branch taken" condition is flag-dependent
    # We'll use the pipelined flag read values combined with enable signals
    branch_conditions = {
        'beq': 'flag_Z_rd',      # branch if Z=1
        'bne': 'notflag_Z_rd',   # branch if Z=0
        'bcc': 'notflag_C_rd',   # branch if C=0
        'bcs': 'flag_C_rd',      # branch if C=1
        'bmi': 'flag_N_rd',      # branch if N=1
        'bpl': 'notflag_N_rd',   # branch if N=0
        'bvc': 'notflag_V_rd',   # branch if V=0
        'bvs': 'flag_V_rd',      # branch if V=1
    }

    # Unconditional jumps - always cause control hazard
    jump_types = ['jmp_abs', 'jmp_ind', 'jsr', 'rts', 'rti']

    # Apply control hazard handling
    print("\nAdding control hazard flush logic...")
    try:
        resolver.add_control_hazard_handling(
            branch_conditions=branch_conditions,
            jump_types=jump_types,
            pc_mux_id=None,  # Let it find PC mux automatically
            resolution_stage='ExecuteMemoryWriteback'
        )
        print("  Control hazard handling added successfully")

        # Gate write enables with validity to prevent invalid instructions
        # from modifying architectural state
        print("\nGating write enables with validity signals...")
        resolver.gate_write_enables_with_validity()
        print("  Write enables gated successfully")

        return True
    except Exception as e:
        print(f"  WARNING: Control hazard handling failed: {e}")
        import traceback
        traceback.print_exc()
        return False


    # fix_register_writeback_defaults removed: now handled by edge selection
    # in select_pipeline_cut_edges() sections 2.1 and 2.2, which skip
    # mux_default_input edges from register reads to their write muxes.


    # fix_pc_increment_mux_verilog removed: the Verilog generator now
    # handles one_hot mux default_signal natively. The graph-level default
    # edge (pc_rd -> pc_increment_mux, type=mux_default_input) is added by
    # fix_pc_increment_mux_default().
    #
    # Other removed post-processing functions and their graph-level replacements:
    # - fix_pc_pipe_source -> edge selection section 1.2 (reroutes pc_rd -> pc_wr)
    # - fix_pc_wr_mux_pipeline -> remove_sequential_pc_overrides(),
    #   edge selection section 2.4 (compound selects), gate_write_enables_with_validity()
    # - fix_multicycle_pc_selects -> edge selection section 2.4 (compound selects)
    # - fix_return_addr_stage -> edge selection section 2.5.4
    # - fix_indexed_addr_stage -> edge selection sections 2.1, 2.4
    # - fix_indirect_addr_stage -> edge selection sections 2.3, 2.6


    # fix_memory_write_forwarding removed: memory RAW hazards are now
    # resolved by enable-only stalling in apply_hazard_resolution(). All data
    # memory reads happen in Decode; Decode stalls whenever XMW has an active
    # memory write. This eliminates the need for store-to-load forwarding.

    # fix_indexed_addr_stage removed: now handled by edge selection in
    # select_pipeline_cut_edges() sections 2.1 (skip X/Y → addr adder edges)
    # and 2.4 (skip enable → addr mux enable OR edges).

    # fix_indirect_addr_stage removed: now handled by edge selection in
    # sections 2.3 (all reads are Decode-stage) and 2.6 (all write addresses piped)

    # fix_return_addr_stage removed: now handled by edge selection in
    # section 2.5.4 (pipe jsr_return_addr/brk_return_addr to XMW) combined
    # with edge selection section 1.2 (reroutes pc_rd -> pc_wr for correct PC source)


def generate_rtl(graph: ResourceGraph, backend: str, output_dir: str, module_name: str):
    """Generate RTL code for the pipelined processor."""
    print("\n" + "=" * 70)
    print(f"GENERATING {backend.upper()} TO {output_dir}")
    print("=" * 70)

    os.makedirs(output_dir, exist_ok=True)

    if backend == 'verilog':
        generator = VerilogGenerator(graph, module_name=module_name)
        code = generator.generate()

        # fix_pc_increment_mux_verilog removed: the Verilog generator now
        # handles one_hot mux default_signal (pc_rd added at graph level by
        # fix_pc_increment_mux_default)
        print("\n  Post-processing Verilog...")
        # fix_pc_pipe_source removed: now handled by edge selection section 1.2
        # which reroutes pc_rd -> pc_wr edges before cutting, so the pipeline
        # register is created with the correct source from the start
        # fix_pc_wr_mux_pipeline removed: sequential PC overrides handled by
        # remove_sequential_pc_overrides(), branch select validity gating handled
        # by generic gate_write_enables_with_validity() in hazard_resolution.py
        # fix_multicycle_pc_selects removed: now handled by graph pre-processing
        # in edge selection section 2.4 which detects compound select nodes
        # with direct enable edges before pipeline cuts
        # fix_memory_write_forwarding removed: memory RAW hazards are now
        # resolved by enable-only stalling (all reads in Decode, stall on write)
        # fix_indexed_addr_stage removed: now handled by edge selection
        # in sections 2.1 (skip X/Y addr adder edges) and 2.4 (skip
        # addr mux enable edges)
        # fix_indirect_addr_stage removed: now handled by edge selection
        # in sections 2.3 (skip XMW indirect memory reads) and 2.6 (skip
        # indirect target addr sources)
        # fix_return_addr_stage removed: now handled by edge selection
        # in section 2.5.4 (pipe jsr_return_addr/brk_return_addr to XMW)
        # combined with edge selection section 1.2 (reroutes pc_rd -> pc_wr)

        output_file = os.path.join(output_dir, f"{module_name}.v")
        with open(output_file, 'w') as f:
            f.write(code)

        print(f"  Generated: {output_file}")
        print(f"  Lines: {len(code.splitlines())}")

        return output_file, generator

    elif backend == 'vhdl':
        from backends.vhdl import generate_vhdl

        code = generate_vhdl(graph, entity_name=module_name)

        output_file = os.path.join(output_dir, f"{module_name}.vhd")
        with open(output_file, 'w') as f:
            f.write(code)

        print(f"  Generated: {output_file}")
        print(f"  Lines: {len(code.splitlines())}")

        return output_file, None

    elif backend == 'pyrtl':
        from backends.pyrtl import generate_pyrtl

        code = generate_pyrtl(graph, module_name=module_name)

        output_file = os.path.join(output_dir, f"{module_name}.py")
        with open(output_file, 'w') as f:
            f.write(code)

        print(f"  Generated: {output_file}")
        print(f"  Lines: {len(code.splitlines())}")

        return output_file, None

    else:
        raise ValueError(f"Unknown backend: {backend}")


def apply_branch_prediction(graph: ResourceGraph, config: PipelineConfig):
    """
    Apply not-taken branch prediction optimization.

    For 6502 with variable-length instructions:
    - The "not taken" path is pc_increment_mux (selects pc_plus_1/2/3 by instr length)
    - This node is the default input to pc_wr_mux
    - Branch prediction handles self-hazard prevention through validity tracking
    """
    print("\n" + "=" * 70)
    print("APPLYING BRANCH PREDICTION (NOT-TAKEN)")
    print("=" * 70)

    pc_node_id = 'pc_wr'
    pc_mux_id = 'pc_wr_mux'
    not_taken_input_id = 'pc_increment_mux'

    print(f"  Architectural specification:")
    print(f"    PC register: {pc_node_id}")
    print(f"    PC mux: {pc_mux_id}")
    print(f"    Not-taken path (speculative): {not_taken_input_id}")
    print(f"    Branch resolution stage: {config.branch_resolution_stage}")

    success = apply_branch_prediction_not_taken(
        graph,
        pc_node_id=pc_node_id,
        pc_mux_id=pc_mux_id,
        not_taken_input_id=not_taken_input_id,
    )

    if success:
        print("\n  Branch prediction applied successfully!")
    else:
        print("\n  Branch prediction not applicable")

    return success


def main():
    parser = argparse.ArgumentParser(
        description='Create pipelined 6502 processor with 3 stages'
    )
    parser.add_argument(
        '--backend',
        default='verilog',
        choices=['verilog', 'vhdl', 'pyrtl'],
        help='Output backend (default: verilog)'
    )
    parser.add_argument(
        '--output-dir',
        default=None,
        help='Output directory (default: examples/verilog/6502_pipelined_3stage)'
    )
    parser.add_argument(
        '--no-ibuf',
        action='store_true',
        help='Disable instruction buffer optimization'
    )
    args = parser.parse_args()

    print("=" * 70)
    print("6502 3-STAGE PIPELINED PROCESSOR GENERATOR")
    print("=" * 70)

    # 1. Build merged graph
    graph = build_merged_graph()

    # fix_rd_enable_signals removed: the graph_merger's rd_enable signals
    # include write-only instructions (e.g., LDA in A_rd_enable), but this
    # no longer causes infinite stall oscillation thanks to validity gating
    # of write enables in hazard_resolution.py's gate_write_enables_with_validity().

    # 2. Get pipeline config
    config = create_6502_3_stage_config()
    print(f"\nPipeline Configuration:")
    print(f"  Stages: {config.num_stages}")
    print(f"  Stage names: {' -> '.join(config.stage_names)}")
    print(f"  Register read stage: {config.register_read_stage}")
    print(f"  Register write stage: {config.register_write_stage}")
    print(f"  Memory stage: {config.memory_stage}")
    print(f"  Branch resolution stage: {config.branch_resolution_stage}")

    # 2.5. Apply instruction buffer optimization (before pipeline cuts).
    # The 6502 has variable-length instructions (1-3 bytes). The instruction
    # buffer decouples fetch from decode, replacing mainmem[pc+N]_rd with
    # ibuf output ports. This enables 1 IPC throughput.
    # Also handles: pc_increment_mux default, sequential PC removal.
    has_ibuf = False
    if not args.no_ibuf:
        has_ibuf = apply_instruction_buffer(graph)
    else:
        print("\n  Instruction buffer disabled (--no-ibuf)")

    # 3. Select cut edges
    cuts = select_pipeline_cut_edges(graph, config, has_ibuf=has_ibuf)

    # 4. Apply pipeline transforms
    success = apply_pipeline_transforms(graph, cuts, config)
    if not success:
        print("\nERROR: Pipeline transformation failed!")
        sys.exit(1)

    # 4.5. PC pipe source for ibuf is handled in edge selection (section 1.2):
    # edges are rerouted from pc_rd -> target to pc_wr -> target, so the
    # pipeline register is created with the correct source from the start.

    # 5. Apply hazard resolution (stalling)
    success, resolver = apply_hazard_resolution(graph, config)
    if not success:
        print("\nWARNING: Some hazards could not be resolved")
        # Continue anyway - partial hazard resolution may still be useful

    # 6. Apply control hazard handling (branch/jump flush)
    control_success = apply_control_hazard_handling(graph, config, resolver)
    if not control_success:
        print("\nWARNING: Control hazard handling failed")
        # Continue anyway - may still work for non-branch code

    # 6.5. Apply branch prediction (not-taken)
    # This also handles self-hazard prevention through validity tracking.
    # The not-taken path for 6502 is pc_increment_mux (variable-length instructions).
    apply_branch_prediction(graph, config)

    # 6.7. Wire ibuf pipeline control (flush, redirect, consume stall, pc_wr valid gate).
    if has_ibuf:
        from opt.fetch.instruction_buffer_optimization import wire_ibuf_pipeline_control
        wire_ibuf_pipeline_control(graph)

    # 7. Generate RTL output
    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = os.path.join(_project_root, "examples", "verilog", "6502_pipelined_3stage")

    module_name = "cpu_6502_pipelined_3stage"

    output_file, generator = generate_rtl(graph, args.backend, output_dir, module_name)

    # 8. Generate testbench
    tb_file = os.path.join(output_dir, "simple_tb.sv")
    generate_testbench(output_file, tb_file, module_name)

    print("\n" + "=" * 70)
    print("GENERATION COMPLETE")
    print("=" * 70)
    print(f"Output: {output_file}")
    print(f"Testbench: {tb_file}")
    print(f"Module: {module_name}")

    return 0


def generate_testbench(rtl_file, tb_file, module_name):
    """Generate a SystemVerilog testbench from the generated RTL ports.

    Parses the module declaration to extract input ports, then creates
    a testbench that ties all reset ports to appropriate default values.
    """
    print("\n" + "=" * 70)
    print("GENERATING TESTBENCH")
    print("=" * 70)

    # Parse input ports from the generated Verilog
    with open(rtl_file, 'r') as f:
        rtl = f.read()

    # Extract module declaration (from 'module ...' to first ');')
    mod_match = re.search(r'module\s+\w+\s*\((.*?)\);', rtl, re.DOTALL)
    if not mod_match:
        print("ERROR: Could not find module declaration")
        return

    ports_text = mod_match.group(1)
    # Parse each input port: "input wire [W:0] name" or "input wire name"
    port_pattern = re.compile(
        r'input\s+wire\s+(?:\[(\d+):0\]\s+)?(\w+)'
    )
    ports = []  # list of (width, name)
    for m in port_pattern.finditer(ports_text):
        width = int(m.group(1)) + 1 if m.group(1) else 1
        name = m.group(2)
        ports.append((width, name))

    print(f"  Found {len(ports)} input ports")

    # Default reset values for architectural state
    arch_defaults = {
        'reset_pc_rd': ('16', "16'h0400"),
        'reset_A': ('8', "8'h00"),
        'reset_S': ('8', "8'hFF"),
        'reset_X': ('8', "8'h00"),
        'reset_Y': ('8', "8'h00"),
        'reset_flag_C': ('1', "1'b0"),
        'reset_flag_N_rd': ('1', "1'b0"),
        'reset_flag_V_rd': ('1', "1'b0"),
        'reset_flag_Z_rd': ('1', "1'b0"),
        'reset_flag_D_rd': ('1', "1'b0"),
        'reset_flag_I_rd': ('1', "1'b1"),  # IRQ disabled on reset
    }

    # Build testbench
    tb = []
    tb.append("`timescale 1ns/1ps")
    tb.append("// Auto-generated testbench for 6502 3-stage pipelined processor")
    tb.append("")
    tb.append(f"module {module_name}_tb;")
    tb.append("")
    tb.append("    // Clock and reset")
    tb.append("    reg clk;")
    tb.append("    reg reset;")
    tb.append("")

    # Declare architectural reset value registers
    tb.append("    // Architectural state reset values")
    for port_name, (width, default_val) in arch_defaults.items():
        if int(width) > 1:
            tb.append(f"    reg [{int(width)-1}:0] {port_name}_val;")
        else:
            tb.append(f"    reg {port_name}_val;")
    tb.append("")

    # Zero wires for pipeline reset ports
    max_width = max(w for w, _ in ports)
    tb.append("    // Zero wires for pipeline register reset")
    for w in sorted(set(width for width, name in ports
                        if name.startswith('reset_') and name not in arch_defaults
                        and name not in ('clk', 'reset'))):
        if w == 1:
            tb.append(f"    wire zero1 = 1'b0;")
        else:
            tb.append(f"    wire [{w-1}:0] zero{w} = {w}'d0;")
    tb.append("")

    # DUT instantiation
    tb.append(f"    // Device Under Test")
    tb.append(f"    {module_name} dut (")
    tb.append(f"        .clk(clk),")
    tb.append(f"        .reset(reset),")

    # Build port connections (skip clk and reset, already handled)
    port_lines = []
    for width, name in ports:
        if name in ('clk', 'reset'):
            continue
        if name in arch_defaults:
            port_lines.append(f"        .{name}({name}_val)")
        else:
            # Pipeline register reset - tie to zero of appropriate width
            port_lines.append(f"        .{name}(zero{width})")

    tb.append(",\n".join(port_lines))
    tb.append("    );")
    tb.append("")

    # Clock generation
    tb.append("    // Clock generation")
    tb.append("    initial clk = 0;")
    tb.append("    always #5 clk = ~clk;  // 10ns period = 100MHz")
    tb.append("")

    # Test execution
    tb.append("    // Test execution")
    tb.append("    integer cycle_count;")
    tb.append("    reg [15:0] prev_pc;")
    tb.append("    integer pc_stall_count;")
    tb.append("    reg [15:0] pass_pc;")
    tb.append("    reg [15:0] fail_pc;")
    tb.append("")
    tb.append("    initial begin")
    tb.append("        // Get pass/fail addresses from plusargs, with defaults")
    tb.append("        if (!$value$plusargs(\"pass_addr=%h\", pass_pc)) pass_pc = 16'h040d;")
    tb.append("        if (!$value$plusargs(\"fail_addr=%h\", fail_pc)) fail_pc = 16'h0410;")
    tb.append("")
    tb.append('        $display("6502 3-Stage Pipelined Processor Testbench");')
    tb.append('        $display("Pass address: 0x%04x", pass_pc);')
    tb.append('        $display("Fail address: 0x%04x", fail_pc);')
    tb.append("")

    # Set default reset values
    tb.append("        // Default reset values")
    for port_name, (width, default_val) in arch_defaults.items():
        tb.append(f"        {port_name}_val = {default_val};")
    tb.append("")

    # Load memory
    tb.append("        // Load memory from imem.hex")
    tb.append('        $display("Loading memory from imem.hex");')
    tb.append('        $readmemh("imem.hex", dut.mainmem);')
    tb.append("")

    # Reset sequence
    tb.append("        // Reset sequence")
    tb.append("        cycle_count = 0;")
    tb.append("        pc_stall_count = 0;")
    tb.append("        prev_pc = 16'h0;")
    tb.append("        reset = 1;")
    tb.append("")
    tb.append("        repeat(5) @(posedge clk);")
    tb.append("        reset = 0;")
    tb.append("")
    tb.append('        $display("Reset released, starting execution at PC=0x%04x", dut.pc_rd);')
    tb.append("")

    # Monitor execution
    tb.append("        // Monitor execution")
    tb.append("        forever begin")
    tb.append("            @(posedge clk);")
    tb.append("            cycle_count = cycle_count + 1;")
    tb.append("")
    tb.append("            // Progress report every 10000 cycles")
    tb.append("            if (cycle_count % 10000 == 0) begin")
    tb.append('                $display("Cycle %0d: PC = 0x%04x A=0x%02x X=0x%02x Y=0x%02x",')
    tb.append("                         cycle_count, dut.pc_rd, dut.A, dut.X, dut.Y);")
    tb.append("            end")
    tb.append("")
    tb.append("            // Check for pass address")
    tb.append("            if (dut.pc_rd == pass_pc) begin")
    tb.append('                $display("");')
    tb.append('                $display("*** TEST PASSED ***");')
    tb.append('                $display("Reached pass address 0x%04x at cycle %0d", pass_pc, cycle_count);')
    tb.append('                $display("Final state: A=0x%02x X=0x%02x Y=0x%02x S=0x%02x",')
    tb.append("                         dut.A, dut.X, dut.Y, dut.S);")
    tb.append("                $finish;")
    tb.append("            end")
    tb.append("")
    tb.append("            // Check for fail address")
    tb.append("            if (dut.pc_rd == fail_pc) begin")
    tb.append('                $display("");')
    tb.append('                $display("*** TEST FAILED ***");')
    tb.append('                $display("Reached fail address 0x%04x at cycle %0d", fail_pc, cycle_count);')
    tb.append('                $display("Final state: A=0x%02x X=0x%02x Y=0x%02x S=0x%02x",')
    tb.append("                         dut.A, dut.X, dut.Y, dut.S);")
    tb.append("                $finish;")
    tb.append("            end")
    tb.append("")
    tb.append("            // Check for PC stall (infinite loop)")
    tb.append("            if (dut.pc_rd == prev_pc) begin")
    tb.append("                pc_stall_count = pc_stall_count + 1;")
    tb.append("                if (pc_stall_count >= 50) begin")
    tb.append('                    $display("");')
    tb.append('                    $display("*** PC STALLED ***");')
    tb.append('                    $display("PC stuck at 0x%04x for %0d cycles", dut.pc_rd, pc_stall_count);')
    tb.append('                    $display("Final state: A=0x%02x X=0x%02x Y=0x%02x S=0x%02x",')
    tb.append("                             dut.A, dut.X, dut.Y, dut.S);")
    tb.append("                    $finish;")
    tb.append("                end")
    tb.append("            end else begin")
    tb.append("                pc_stall_count = 0;")
    tb.append("            end")
    tb.append("            prev_pc = dut.pc_rd;")
    tb.append("")
    tb.append("            // Timeout after many cycles")
    tb.append("            if (cycle_count > 10000000) begin")
    tb.append('                $display("");')
    tb.append('                $display("*** TIMEOUT ***");')
    tb.append('                $display("Exceeded maximum cycles");')
    tb.append("                $finish;")
    tb.append("            end")
    tb.append("        end")
    tb.append("    end")
    tb.append("")
    tb.append("endmodule")
    tb.append("")

    with open(tb_file, 'w') as f:
        f.write("\n".join(tb))

    print(f"  Generated: {tb_file}")


if __name__ == '__main__':
    sys.exit(main())
