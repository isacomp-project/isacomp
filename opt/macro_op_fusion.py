#!/usr/bin/env python3
"""
Macro-Op Fusion Optimization Pass.

Detects specific multi-instruction idioms and fuses them into single
macro-operations that bypass intermediate register writes. The fused graph
fetches two consecutive instructions, checks decode eligibility, and executes
the combined datapath with a single set of architectural state commits.

The key structural constraint is the *destructive destination*: when
instruction 2 writes a destination register, it must be the same register
as instruction 1's destination (rd2 == rd1). This is enforced automatically
as a decode assumption, keeping the register file write-port budget at 1.

See the Celio et al. whitepaper for the full design.
"""

from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from core.resource_graph import ResourceGraph, Node, Edge
from core.graph_utils import deep_copy_graph
import re
import copy


@dataclass
class FusionCandidate:
    """Specification for a pair of instructions that can be fused.

    Attributes:
        name: Human-readable name for this fusion (e.g., 'lui_addi').
        instr1_name: Name of the first instruction (e.g., 'lui').
        instr1_file: Path to the .isa file for instruction 1.
        instr2_name: Name of the second instruction (e.g., 'addi').
        instr2_file: Path to the .isa file for instruction 2.
        producer_write: Register field name in instr1 that is written (e.g., 'rd').
        consumer_read: Register field name in instr2 that reads the forwarded
            value (e.g., 'rs1'). Must equal producer_write at runtime.
        regfile_name: Name of the register file ISA state (e.g., 'rf', 'xregs').
            Defaults to 'rf'.
        pc_name: Name of the program counter ISA state. Defaults to 'pc'.
        instr_mem_name: Name of the instruction memory. Defaults to 'umem'.
        pc_increment: Size of one instruction in bytes. Defaults to 4.
    """
    name: str
    instr1_name: str
    instr1_file: str
    instr2_name: str
    instr2_file: str
    producer_write: str   # e.g., 'rd' — the field instr1 writes to in regfile
    consumer_read: str    # e.g., 'rs1' — the field instr2 reads from regfile
    regfile_name: str = 'rf'
    pc_name: str = 'pc'
    instr_mem_name: str = 'umem'
    pc_increment: int = 4


@dataclass
class FusionResult:
    """Result of applying a fusion candidate.

    Attributes:
        candidate: The FusionCandidate that was applied.
        fused_graph: The resulting fused ResourceGraph.
        assumptions_added: List of assume expression dicts added for decode eligibility.
        forwarded_value_node: Node ID of the wire that replaced the rf bypass.
        instr2_has_rd: Whether instruction 2 writes a destination register
            (if True, rd2==rd1 was enforced).
    """
    candidate: FusionCandidate
    fused_graph: ResourceGraph
    assumptions_added: List[dict] = field(default_factory=list)
    forwarded_value_node: Optional[str] = None
    instr2_has_rd: bool = False


class MacroOpFusion:
    """Fuses pairs of instruction graphs into single macro-operations.

    Given two parsed instruction ResourceGraphs (after arch state splitting),
    this class:

    1. Prefixes all nodes to avoid ID collisions (i1_ / i2_).
    2. Replaces instruction 2's PC read with pc+N (since it would execute at
       the next sequential address).
    3. Connects instruction 1's rf[rd] write value directly to instruction 2's
       rf[rs] read (bypassing the register file — the forwarding link).
    4. Eliminates instruction 1's rf write and pc write.
    5. Adjusts instruction 2's sequential pc write from pc+N to pc+2N.
    6. Adds decode eligibility assumptions:
       - All original assume conditions from both instructions (with prefixed instr refs).
       - The forwarding link: instr2[consumer_read_bits] == instr1[producer_write_bits].
       - The destructive destination: instr2[rd_bits] == instr1[rd_bits] (when instr2 has rd).
    """

    def __init__(self):
        self.results: List[FusionResult] = []

    def fuse(self, candidate: FusionCandidate) -> FusionResult:
        """Fuse two instructions according to the candidate specification.

        Args:
            candidate: A FusionCandidate describing the pair to fuse.

        Returns:
            FusionResult with the fused graph and metadata.
        """
        print(f"\n{'=' * 60}")
        print(f"MACRO-OP FUSION: {candidate.name}")
        print(f"  {candidate.instr1_name} + {candidate.instr2_name}")
        print(f"  Forwarding: {candidate.instr1_name}.{candidate.producer_write} -> "
              f"{candidate.instr2_name}.{candidate.consumer_read}")
        print(f"{'=' * 60}")

        # Parse both instruction graphs
        graph1 = ResourceGraph.from_isa_file(candidate.instr1_file)
        graph2 = ResourceGraph.from_isa_file(candidate.instr2_file)

        print(f"\n  Parsed {candidate.instr1_name}: {len(graph1.nodes)} nodes, {len(graph1.edges)} edges")
        print(f"  Parsed {candidate.instr2_name}: {len(graph2.nodes)} nodes, {len(graph2.edges)} edges")

        # Build the fused graph
        fused = ResourceGraph()

        # Step 1: Copy both graphs into fused graph with prefixes
        print("\n  Step 1: Copying graphs with prefixes i1_/i2_...")
        mapping1 = self._copy_with_prefix(graph1, fused, "i1_", candidate)
        mapping2 = self._copy_with_prefix(graph2, fused, "i2_", candidate)
        print(f"    i1: {len(mapping1)} nodes, i2: {len(mapping2)} nodes")

        # Step 2: Create shared ISA state nodes (the "real" architectural state)
        print("\n  Step 2: Creating shared ISA state...")
        shared_state = self._create_shared_state(fused, graph1, graph2, candidate, mapping1, mapping2)

        # Step 3: Replace i2's PC read with pc + increment
        print(f"\n  Step 3: Replacing i2 PC read with {candidate.pc_name}+{candidate.pc_increment}...")
        self._replace_i2_pc(fused, candidate, mapping2)

        # Step 4: Forward i1's rf write value to i2's rf read (bypass)
        print(f"\n  Step 4: Forwarding {candidate.instr1_name}.{candidate.producer_write} -> "
              f"{candidate.instr2_name}.{candidate.consumer_read}...")
        forwarded_node = self._forward_rf_value(fused, graph1, graph2, candidate, mapping1, mapping2)
        if forwarded_node is None:
            print(f"\n  FAILED: Could not establish forwarding link for {candidate.name}")
            return FusionResult(candidate=candidate, fused_graph=None,
                                assumptions_added=[], forwarded_value_node=None,
                                instr2_has_rd=False)

        # Step 5: Eliminate i1's rf write and pc write
        print("\n  Step 5: Eliminating i1's intermediate state writes...")
        self._eliminate_i1_writes(fused, graph1, candidate, mapping1)

        # Step 6: PC write adjustment is handled automatically.
        # Step 3 redirected i2's pc reads from pc_rd to pc+N, so i2's
        # sequential pc write (originally pc+N) becomes (pc+N)+N = pc+2N.
        print(f"\n  Step 6: Adjusting i2 PC write to pc+{2 * candidate.pc_increment}...")
        print(f"    Handled by step 3 (i2 pc read redirect)")

        # Step 7: Set up dual-fetch (i1 fetches from pc, i2 fetches from pc+N)
        print("\n  Step 7: Setting up dual fetch...")
        self._setup_dual_fetch(fused, candidate, mapping1, mapping2)

        # Step 8: Add decode eligibility assumptions
        print("\n  Step 8: Adding decode eligibility assumptions...")
        assumptions, instr2_has_rd = self._add_decode_assumptions(
            fused, graph1, graph2, candidate, mapping1, mapping2
        )

        # Copy assume_expressions from both graphs, adjusting instr references
        self._merge_assume_expressions(fused, graph1, graph2, candidate)

        # Re-infer timing
        fused.infer_uarch_time(force_reinfer=True)

        result = FusionResult(
            candidate=candidate,
            fused_graph=fused,
            assumptions_added=assumptions,
            forwarded_value_node=forwarded_node,
            instr2_has_rd=instr2_has_rd,
        )
        self.results.append(result)

        print(f"\n  Fusion complete: {len(fused.nodes)} nodes, {len(fused.edges)} edges")
        return result

    # =========================================================================
    # Internal: Copy with prefix
    # =========================================================================

    def _copy_with_prefix(self, source: ResourceGraph, target: ResourceGraph,
                          prefix: str, candidate: FusionCandidate) -> Dict[str, str]:
        """Copy all nodes from source into target, prefixing non-shared node IDs.

        ISA state nodes (pc, rf, umem, etc.) are NOT copied here — they'll be
        created as shared nodes in a later step.

        Returns:
            Mapping from original node ID to prefixed node ID.
        """
        mapping = {}

        # Identify ISA state node IDs to skip (they'll be shared)
        isa_state_ids = set()
        for node in source.nodes.values():
            if node.is_arch_state:
                isa_state_ids.add(node.id)

        # Copy non-ISA-state nodes with prefix
        for node_id, node in source.nodes.items():
            if node_id in isa_state_ids:
                # Map ISA state to itself (will be shared)
                mapping[node_id] = node_id
                continue

            new_id = f"{prefix}{node_id}"
            mapping[node_id] = new_id

            new_data = node.data.copy() if node.data else {}
            # Update 'name' and 'display_name' to include prefix so the
            # Verilog generator doesn't map prefixed nodes back to shared signals
            if 'name' in new_data:
                new_data['name'] = f"{prefix}{new_data['name']}"
            if 'display_name' in new_data:
                new_data['display_name'] = f"{prefix}{new_data['display_name']}"
            new_node = Node(
                node_id=new_id,
                data=new_data,
                is_arch_state=node.is_arch_state,
                used_as_index=node.used_as_index,
                is_uarch_state=node.is_uarch_state,
                uarch_time=node.uarch_time,
                pipe_time=node.pipe_time,
                from_isa_spec=node.from_isa_spec,
                latency=node.latency,
                is_shared=node.is_shared,
            )
            # Preserve indexed_by reference — will be remapped after all nodes are added
            new_node._orig_indexed_by_id = node.indexed_by.id if node.indexed_by else None
            target.add_node(new_node)

        # Copy edges, remapping source/target IDs
        for edge_id, edge in source.edges.items():
            src_id = mapping.get(edge.source.id, edge.source.id)
            tgt_id = mapping.get(edge.target.id, edge.target.id)
            if src_id in target.nodes and tgt_id in target.nodes:
                new_edge = Edge(
                    target.nodes[src_id],
                    target.nodes[tgt_id],
                    edge_id=f"{prefix}{edge_id}",
                    data=edge.data.copy() if edge.data else {},
                )
                target.add_edge(new_edge)

        # Fix indexed_by references
        for node_id, node in source.nodes.items():
            new_id = mapping[node_id]
            if new_id in target.nodes:
                new_node = target.nodes[new_id]
                orig_ib = getattr(new_node, '_orig_indexed_by_id', None)
                if orig_ib is not None:
                    mapped_ib = mapping.get(orig_ib, orig_ib)
                    if mapped_ib in target.nodes:
                        new_node.indexed_by = target.nodes[mapped_ib]
                    del new_node._orig_indexed_by_id
                elif hasattr(new_node, '_orig_indexed_by_id'):
                    del new_node._orig_indexed_by_id

        return mapping

    # =========================================================================
    # Internal: Shared state
    # =========================================================================

    def _create_shared_state(self, fused: ResourceGraph,
                             graph1: ResourceGraph, graph2: ResourceGraph,
                             candidate: FusionCandidate,
                             mapping1: Dict[str, str],
                             mapping2: Dict[str, str]) -> Dict[str, Node]:
        """Create shared ISA state nodes and connect prefixed nodes to them.

        Both instruction graphs share the same architectural state (pc, rf, umem).
        We create a single set of shared state nodes and re-wire both prefixed
        graphs to use them.
        """
        shared = {}

        # Gather all ISA state nodes from both graphs
        isa_state_nodes = {}
        for graph in [graph1, graph2]:
            for node_id, node in graph.nodes.items():
                if node.is_arch_state and node_id not in isa_state_nodes:
                    isa_state_nodes[node_id] = node

        # Create shared nodes in fused graph
        for node_id, node in isa_state_nodes.items():
            new_data = node.data.copy() if node.data else {}
            shared_node = Node(
                node_id=node_id,
                data=new_data,
                is_arch_state=True,
                is_uarch_state=node.is_uarch_state,
                uarch_time=node.uarch_time,
                pipe_time=node.pipe_time,
                from_isa_spec=node.from_isa_spec,
                is_shared=True,
            )
            fused.add_node(shared_node)
            shared[node_id] = shared_node

        # Now re-wire prefixed edges that reference ISA state nodes.
        # For each edge in the fused graph, if an endpoint was mapped to an
        # ISA state ID (i.e., mapping[orig_id] == orig_id), the shared node
        # is already the correct target.

        # Connect prefixed nodes to shared state by finding edges that should
        # point to/from shared nodes.
        for prefix, mapping, graph in [("i1_", mapping1, graph1), ("i2_", mapping2, graph2)]:
            for edge_id, edge in list(graph.edges.items()):
                src_orig = edge.source.id
                tgt_orig = edge.target.id
                src_mapped = mapping.get(src_orig, src_orig)
                tgt_mapped = mapping.get(tgt_orig, tgt_orig)

                # If source is shared ISA state and target is prefixed
                if src_orig in shared and tgt_mapped != tgt_orig:
                    prefixed_edge_id = f"{prefix}{edge_id}"
                    if prefixed_edge_id in fused.edges:
                        # Edge already exists from _copy_with_prefix but source
                        # might not be connected to the shared node — fix it
                        existing = fused.edges[prefixed_edge_id]
                        if existing.source.id != src_orig and src_orig in fused.nodes:
                            # Re-wire to shared node
                            existing.source.remove_outgoing_edge(existing)
                            existing.source = fused.nodes[src_orig]
                            fused.nodes[src_orig].add_outgoing_edge(existing)
                    else:
                        # Edge was lost during _copy_with_prefix because
                        # ISA state node didn't exist in target yet — create it now
                        tgt_node = fused.nodes.get(tgt_mapped)
                        if tgt_node and src_orig in fused.nodes:
                            new_edge = Edge(
                                fused.nodes[src_orig], tgt_node,
                                edge_id=prefixed_edge_id,
                                data=edge.data.copy() if edge.data else {},
                            )
                            fused.add_edge(new_edge)

                # If target is shared ISA state and source is prefixed
                if tgt_orig in shared and src_mapped != src_orig:
                    prefixed_edge_id = f"{prefix}{edge_id}"
                    if prefixed_edge_id in fused.edges:
                        existing = fused.edges[prefixed_edge_id]
                        if existing.target.id != tgt_orig and tgt_orig in fused.nodes:
                            existing.target.remove_incoming_edge(existing)
                            existing.target = fused.nodes[tgt_orig]
                            fused.nodes[tgt_orig].add_incoming_edge(existing)
                    else:
                        # Edge was lost — create it now
                        src_node = fused.nodes.get(src_mapped)
                        if src_node and tgt_orig in fused.nodes:
                            new_edge = Edge(
                                src_node, fused.nodes[tgt_orig],
                                edge_id=prefixed_edge_id,
                                data=edge.data.copy() if edge.data else {},
                            )
                            fused.add_edge(new_edge)

        return shared

    # =========================================================================
    # Internal: Replace i2 PC read
    # =========================================================================

    def _replace_i2_pc(self, fused: ResourceGraph, candidate: FusionCandidate,
                       mapping2: Dict[str, str]):
        """Replace instruction 2's reads of pc_rd with pc_rd + increment.

        In the fused pair, instruction 2 would have seen pc+4 (or pc+N) as
        its PC value. We create a shared 'pc_plus_N' adder node and redirect
        all of i2's pc_rd consumers to use it.
        """
        pc_rd_id = f"{candidate.pc_name}_rd"
        inc = candidate.pc_increment

        # Create the pc+N node if it doesn't exist
        pc_plus_n_id = f"fusion_pc_plus_{inc}"
        if pc_plus_n_id not in fused.nodes:
            pc_plus_n_node = Node(
                node_id=pc_plus_n_id,
                data={
                    'type': 'operation',
                    'operator': '+',
                    'display_name': f"({candidate.pc_name} + {inc})",
                    'expression': {'operator': '+'},
                },
            )
            fused.add_node(pc_plus_n_node)

            # Connect pc_rd -> pc+N
            if pc_rd_id in fused.nodes:
                e1 = Edge(fused.nodes[pc_rd_id], pc_plus_n_node,
                          data={'type': 'operand'})
                fused.add_edge(e1)

            # Create increment literal
            inc_lit_id = f"fusion_literal_{inc}"
            if inc_lit_id not in fused.nodes:
                inc_lit = Node(inc_lit_id, data={
                    'type': 'literal', 'value': inc,
                    'display_name': str(inc),
                })
                fused.add_node(inc_lit)
            e2 = Edge(fused.nodes[inc_lit_id], pc_plus_n_node,
                      data={'type': 'operand'})
            fused.add_edge(e2)

        # Find all edges from pc_rd that go to i2_ prefixed nodes and redirect
        if pc_rd_id in fused.nodes:
            pc_rd_node = fused.nodes[pc_rd_id]
            edges_to_redirect = []
            for edge in list(pc_rd_node.outgoing_edges):
                # Only redirect edges to i2_ nodes (not i1_ or shared)
                if edge.target.id.startswith("i2_"):
                    # Don't redirect the fetch edge (umem[pc] array_index) — that's
                    # handled separately in _setup_dual_fetch
                    if edge.data.get('type') == 'array_index':
                        continue
                    edges_to_redirect.append(edge)

            for edge in edges_to_redirect:
                # Re-wire: pc_rd -> i2_X becomes fusion_pc_plus_N -> i2_X
                pc_rd_node.remove_outgoing_edge(edge)
                edge.source = fused.nodes[pc_plus_n_id]
                fused.nodes[pc_plus_n_id].add_outgoing_edge(edge)

    # =========================================================================
    # Internal: Forward rf value (bypass)
    # =========================================================================

    def _forward_rf_value(self, fused: ResourceGraph,
                          graph1: ResourceGraph, graph2: ResourceGraph,
                          candidate: FusionCandidate,
                          mapping1: Dict[str, str],
                          mapping2: Dict[str, str]) -> Optional[str]:
        """Connect i1's register write value directly to i2's register read.

        This is the core of the fusion: the value that i1 would write to
        rf[rd] is fed directly into i2's datapath where it reads rf[rs],
        bypassing the register file entirely.

        Returns the node ID of the forwarded value, or None if not found.
        """
        rf_name = candidate.regfile_name
        producer = candidate.producer_write
        consumer = candidate.consumer_read

        # Find i1's rf write value: the node that feeds into rf[rd]_wr via assignment
        i1_rf_wr_id = mapping1.get(f"{rf_name}[{producer}]_wr")
        if not i1_rf_wr_id or i1_rf_wr_id not in fused.nodes:
            print(f"    WARNING: Could not find i1 rf write node '{rf_name}[{producer}]_wr'")
            return None

        i1_rf_wr = fused.nodes[i1_rf_wr_id]

        # The value being written is the source of the 'assignment' edge into rf[rd]_wr
        value_node_id = None
        for edge in i1_rf_wr.incoming_edges:
            if edge.data.get('type') == 'assignment':
                value_node_id = edge.source.id
                break

        if not value_node_id:
            print(f"    WARNING: No assignment edge into {i1_rf_wr_id}")
            return None

        print(f"    Forwarding value from node '{value_node_id}'")

        # Find i2's rf read: rf[rs]_rd
        i2_rf_rd_id = mapping2.get(f"{rf_name}[{consumer}]_rd")
        if not i2_rf_rd_id or i2_rf_rd_id not in fused.nodes:
            print(f"    WARNING: Could not find i2 rf read node '{rf_name}[{consumer}]_rd'")
            return None

        i2_rf_rd = fused.nodes[i2_rf_rd_id]

        # Find the variable that rf[rs]_rd assigns to (e.g., r1)
        # Then redirect: instead of rf[rs]_rd -> r1, use value_node -> r1
        for edge in list(i2_rf_rd.outgoing_edges):
            if edge.data.get('type') == 'assignment':
                target = edge.target
                # Remove old edge from rf read
                fused.remove_edge(edge.id)
                # Add new edge from forwarded value
                new_edge = Edge(
                    fused.nodes[value_node_id], target,
                    data={'type': 'assignment'},
                )
                fused.add_edge(new_edge)
                print(f"    Bypassed: {value_node_id} -> {target.id} (was {i2_rf_rd_id} -> {target.id})")
                break

        # Remove the now-dead rf read node and its incoming edges
        self._remove_dead_node(fused, i2_rf_rd_id)

        return value_node_id

    # =========================================================================
    # Internal: Eliminate i1 writes
    # =========================================================================

    def _eliminate_i1_writes(self, fused: ResourceGraph, graph1: ResourceGraph,
                             candidate: FusionCandidate, mapping1: Dict[str, str]):
        """Remove instruction 1's architectural state writes (rf and pc).

        The rf write is eliminated because:
        - If i2 has a rd (destructive), rd2==rd1 means i2's write supersedes.
        - If i2 has no rd (stores/branches), i1's rd is dead.

        The pc write (pc = pc + N) is eliminated because the fused pair
        advances pc by 2N (handled by i2's adjusted pc write).
        """
        rf_name = candidate.regfile_name
        producer = candidate.producer_write

        # Eliminate i1's rf write
        i1_rf_wr_id = mapping1.get(f"{rf_name}[{producer}]_wr")
        if i1_rf_wr_id and i1_rf_wr_id in fused.nodes:
            self._remove_dead_node(fused, i1_rf_wr_id)
            print(f"    Eliminated i1 rf write: {i1_rf_wr_id}")

            # Also remove the write_enable node if it exists
            # Look for nodes like i1_(rd != 0) that fed write_enable to the now-removed write
            self._cleanup_orphaned_nodes(fused, "i1_")

        # Eliminate i1's pc write.
        # pc_wr is a shared ISA state node — don't remove it entirely,
        # just disconnect i1's assignment edge to it.
        i1_pc_wr_id = mapping1.get(f"{candidate.pc_name}_wr")
        if i1_pc_wr_id and i1_pc_wr_id in fused.nodes:
            pc_wr_node = fused.nodes[i1_pc_wr_id]
            # Remove only i1-prefixed edges feeding into pc_wr
            for edge in list(pc_wr_node.incoming_edges):
                if edge.source.id.startswith("i1_"):
                    fused.remove_edge(edge.id)
            print(f"    Eliminated i1 pc write: {i1_pc_wr_id}")

            # Also remove i1's (pc + N) operation if it's now orphaned
            self._cleanup_orphaned_nodes(fused, "i1_")

    # =========================================================================
    # Internal: Adjust i2 PC write
    # =========================================================================

    def _adjust_i2_pc_write(self, fused: ResourceGraph, graph2: ResourceGraph,
                             candidate: FusionCandidate, mapping2: Dict[str, str]):
        """Adjust instruction 2's PC write from pc+N to pc+2N.

        For sequential instructions, i2 originally writes pc = pc + N.
        In the fused pair, we need pc = pc + 2N. For jumps/branches,
        the PC write is already computed from pc+N (which we've already
        redirected), so no adjustment is needed.
        """
        inc = candidate.pc_increment
        pc_wr_id = mapping2.get(f"{candidate.pc_name}_wr")
        if not pc_wr_id or pc_wr_id not in fused.nodes:
            return

        pc_wr = fused.nodes[pc_wr_id]

        # Find the node that assigns to pc_wr
        for edge in pc_wr.incoming_edges:
            if edge.data.get('type') == 'assignment':
                src = edge.source
                # Check if this is a simple "pc + N" operation
                if src.data.get('type') == 'operation' and src.data.get('operator') == '+':
                    # Check if one operand is the PC increment literal
                    for op_edge in src.incoming_edges:
                        op_src = op_edge.source
                        if (op_src.data.get('type') == 'literal' and
                                op_src.data.get('value') == inc):
                            # Replace the increment literal with 2*N
                            op_src.data['value'] = 2 * inc
                            op_src.data['display_name'] = str(2 * inc)
                            op_src.id = f"i2_{2 * inc}"
                            # Re-register in fused graph
                            print(f"    Adjusted: pc increment {inc} -> {2 * inc}")
                            return

        # If we get here, i2's PC write is not a simple pc+N — it's a jump/branch.
        # The target is already computed correctly because we replaced i2's pc_rd
        # with pc+N in _replace_i2_pc.
        print(f"    i2 PC write is computed (jump/branch) — no increment adjustment needed")

    # =========================================================================
    # Internal: Dual fetch
    # =========================================================================

    def _setup_dual_fetch(self, fused: ResourceGraph, candidate: FusionCandidate,
                          mapping1: Dict[str, str], mapping2: Dict[str, str]):
        """Set up dual instruction fetch: i1 from umem[pc], i2 from umem[pc+N].

        Both instructions need to be fetched. i1's fetch is already wired to
        umem[pc]. For i2's fetch, we redirect the array index from pc_rd to
        the fusion_pc_plus_N node.
        """
        inc = candidate.pc_increment
        pc_plus_n_id = f"fusion_pc_plus_{inc}"
        mem_name = candidate.instr_mem_name

        # Find i2's instruction fetch (umem[pc]_rd mapped to i2_umem[pc]_rd)
        i2_fetch_id = mapping2.get(f"{mem_name}[{candidate.pc_name}]_rd")
        if not i2_fetch_id or i2_fetch_id not in fused.nodes:
            # Try alternative naming patterns
            for orig_id, mapped_id in mapping2.items():
                if orig_id.startswith(f"{mem_name}[") and orig_id.endswith("]_rd"):
                    if mapped_id in fused.nodes:
                        i2_fetch_id = mapped_id
                        break
            if not i2_fetch_id:
                print(f"    WARNING: Could not find i2 fetch node")
                return

        i2_fetch = fused.nodes[i2_fetch_id]

        # Find the array_index edge and redirect it to pc+N
        pc_rd_id = f"{candidate.pc_name}_rd"
        for edge in list(i2_fetch.incoming_edges):
            if edge.data.get('type') == 'array_index' and edge.source.id == pc_rd_id:
                if pc_plus_n_id in fused.nodes:
                    # Redirect from pc_rd to pc+N
                    edge.source.remove_outgoing_edge(edge)
                    edge.source = fused.nodes[pc_plus_n_id]
                    fused.nodes[pc_plus_n_id].add_outgoing_edge(edge)
                    print(f"    i2 fetch now uses {pc_plus_n_id} as address")
                break

    # =========================================================================
    # Internal: Decode assumptions
    # =========================================================================

    def _add_decode_assumptions(self, fused: ResourceGraph,
                                graph1: ResourceGraph, graph2: ResourceGraph,
                                candidate: FusionCandidate,
                                mapping1: Dict[str, str],
                                mapping2: Dict[str, str]) -> Tuple[List[dict], bool]:
        """Add the fusion-specific decode eligibility assumptions.

        These go beyond the individual instruction decode conditions:
        1. Forwarding link: instr2.consumer_read field == instr1.producer_write field
        2. Destructive destination: instr2.rd field == instr1.rd field (auto-forced
           when instr2 has a destination register)

        Returns:
            (list of assumption dicts, whether instr2 has rd)
        """
        assumptions = []

        producer = candidate.producer_write
        consumer = candidate.consumer_read
        rf_name = candidate.regfile_name

        # Determine bit ranges for the register fields from the original graphs.
        # In RISC-V, rd is instr[11:7], rs1 is instr[19:15], rs2 is instr[24:20].
        # We find these by looking at what bit-slices feed into the field variables.

        i1_rd_bits = self._find_field_bits(graph1, producer)
        i2_consumer_bits = self._find_field_bits(graph2, consumer)

        # 1. Forwarding link: instr2[consumer_bits] == instr1[rd_bits]
        if i1_rd_bits and i2_consumer_bits:
            assume_fwd = self._make_cross_instr_assume(
                'instr2', i2_consumer_bits, 'instr1', i1_rd_bits
            )
            assumptions.append(assume_fwd)
            fused.assume_expressions.append(assume_fwd)
            print(f"    Added forwarding link: instr2[{i2_consumer_bits}] == instr1[{i1_rd_bits}]")

        # 2. Destructive destination: check if instr2 has a write to rf
        instr2_has_rd = self._instr_has_rf_write(graph2, rf_name)

        if instr2_has_rd:
            i2_rd_bits = self._find_field_bits(graph2, 'rd')
            if not i2_rd_bits:
                # Some ISAs use a different name for the destination
                # Try to find any field that indexes rf writes
                i2_rd_bits = self._find_rf_write_index_bits(graph2, rf_name)

            if i1_rd_bits and i2_rd_bits:
                assume_dest = self._make_cross_instr_assume(
                    'instr2', i2_rd_bits, 'instr1', i1_rd_bits
                )
                assumptions.append(assume_dest)
                fused.assume_expressions.append(assume_dest)
                print(f"    Added destructive dest: instr2[{i2_rd_bits}] == instr1[{i1_rd_bits}]")
        else:
            print(f"    i2 has no rf write — i1's rd is dead (store/branch fusion)")

        # 3. Producer destination != 0: The forwarding bypasses the register file's
        # x0-hardwiring, so we must ensure rd1 != 0 to avoid incorrectly forwarding
        # a computed value when the architectural read should return 0.
        if i1_rd_bits:
            assume_rd_ne_0 = {
                'type': 'binary_op',
                'operator': '!=',
                'left': {
                    'type': 'bit_slice',
                    'target': {'type': 'identifier', 'name': 'instr1'},
                    'range': i1_rd_bits,
                },
                'right': {
                    'type': 'literal',
                    'value': 0,
                },
            }
            assumptions.append(assume_rd_ne_0)
            fused.assume_expressions.append(assume_rd_ne_0)
            print(f"    Added rd1 != 0 guard: instr1[{i1_rd_bits}] != 0")

        return assumptions, instr2_has_rd

    # =========================================================================
    # Internal: Merge assume expressions
    # =========================================================================

    def _merge_assume_expressions(self, fused: ResourceGraph,
                                   graph1: ResourceGraph, graph2: ResourceGraph,
                                   candidate: FusionCandidate):
        """Copy assume expressions from both instruction graphs into the fused graph.

        The 'instr' references in each graph's assumes need to be distinguished:
        graph1's assumes reference 'instr1' (i1's instruction word),
        graph2's assumes reference 'instr2' (i2's instruction word).
        """
        for assume in getattr(graph1, 'assume_expressions', []):
            renamed = self._rename_instr_refs(assume, 'instr', 'instr1')
            fused.assume_expressions.append(renamed)

        for assume in getattr(graph2, 'assume_expressions', []):
            renamed = self._rename_instr_refs(assume, 'instr', 'instr2')
            fused.assume_expressions.append(renamed)

    # =========================================================================
    # Helpers
    # =========================================================================

    def _find_field_bits(self, graph: ResourceGraph, field_name: str) -> Optional[Tuple[int, int]]:
        """Find the bit range of an instruction field (e.g., rd -> (11, 7)).

        Looks for bit_slice nodes of 'instr' that feed into the field variable.
        """
        # Look for a node named field_name (e.g., 'rd', 'rs1')
        if field_name not in graph.nodes:
            return None

        field_node = graph.nodes[field_name]

        # Find the bit_slice that assigns to this field
        for edge in field_node.incoming_edges:
            if edge.data.get('type') == 'assignment':
                src = edge.source
                if src.data.get('type') == 'bit_slice':
                    # Range may be in data['expression']['range'] or data['range']
                    expr = src.data.get('expression', {})
                    return expr.get('range') or src.data.get('range')

        return None

    def _find_rf_write_index_bits(self, graph: ResourceGraph, rf_name: str) -> Optional[Tuple[int, int]]:
        """Find the bit range of the register index used for rf writes.

        Fallback when the destination field isn't named 'rd'.
        """
        # Find rf[*]_wr nodes
        for node_id, node in graph.nodes.items():
            if node_id.startswith(f"{rf_name}[") and node_id.endswith("]_wr"):
                # Find the array_index edge
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'array_index':
                        idx_node = edge.source
                        # Follow back to bit_slice
                        for idx_edge in idx_node.incoming_edges:
                            if idx_edge.data.get('type') == 'assignment':
                                src = idx_edge.source
                                if src.data.get('type') == 'bit_slice':
                                    expr = src.data.get('expression', {})
                                    return expr.get('range') or src.data.get('range')
        return None

    def _instr_has_rf_write(self, graph: ResourceGraph, rf_name: str) -> bool:
        """Check if an instruction graph writes to the register file."""
        for node_id in graph.nodes:
            if node_id.startswith(f"{rf_name}[") and node_id.endswith("]_wr"):
                return True
        return False

    def _make_cross_instr_assume(self, instr_a: str, bits_a: Tuple[int, int],
                                  instr_b: str, bits_b: Tuple[int, int]) -> dict:
        """Create an assume expression AST: instrA[hi:lo] == instrB[hi:lo]."""
        return {
            'type': 'binary_op',
            'operator': '==',
            'left': {
                'type': 'bit_slice',
                'target': {'type': 'identifier', 'name': instr_a},
                'range': bits_a,
            },
            'right': {
                'type': 'bit_slice',
                'target': {'type': 'identifier', 'name': instr_b},
                'range': bits_b,
            },
        }

    def _rename_instr_refs(self, expr: dict, old_name: str, new_name: str) -> dict:
        """Recursively rename identifier references in an assume AST."""
        if not expr or not isinstance(expr, dict):
            return expr

        result = expr.copy()

        if result.get('type') == 'identifier' and result.get('name') == old_name:
            result['name'] = new_name
        elif result.get('type') == 'bit_slice':
            result['target'] = self._rename_instr_refs(result.get('target', {}), old_name, new_name)
        elif result.get('type') == 'binary_op':
            result['left'] = self._rename_instr_refs(result.get('left', {}), old_name, new_name)
            result['right'] = self._rename_instr_refs(result.get('right', {}), old_name, new_name)
        elif result.get('type') == 'array_access':
            result['target'] = self._rename_instr_refs(result.get('target', {}), old_name, new_name)
            result['index'] = self._rename_instr_refs(result.get('index', {}), old_name, new_name)

        return result

    def _remove_dead_node(self, graph: ResourceGraph, node_id: str):
        """Remove a node and all its edges from the graph."""
        if node_id in graph.nodes:
            graph.remove_node(node_id)

    def _cleanup_orphaned_nodes(self, graph: ResourceGraph, prefix: str):
        """Remove nodes with the given prefix that have no outgoing edges
        and are not ISA state (i.e., they're dead computation).
        """
        changed = True
        while changed:
            changed = False
            for node_id in list(graph.nodes.keys()):
                if not node_id.startswith(prefix):
                    continue
                node = graph.nodes[node_id]
                if node.is_arch_state:
                    continue
                if not node.outgoing_edges:
                    graph.remove_node(node_id)
                    changed = True


# =============================================================================
# Public API: apply_macro_op_fusion
# =============================================================================

def apply_macro_op_fusion(candidates: List[FusionCandidate]) -> List[FusionResult]:
    """Apply macro-op fusion for a list of fusion candidates.

    Each candidate produces an independent fused graph. These can then be
    merged alongside unfused instructions using the standard graph_merger
    infrastructure.

    Args:
        candidates: List of FusionCandidate specifications.

    Returns:
        List of FusionResult objects, one per candidate.
    """
    fusion = MacroOpFusion()
    results = []

    for candidate in candidates:
        try:
            result = fusion.fuse(candidate)
            results.append(result)
        except Exception as e:
            print(f"ERROR: Failed to fuse {candidate.name}: {e}")
            import traceback
            traceback.print_exc()

    return results


def add_fused_instruction_to_merger(merger, name: str, fused_graph: ResourceGraph,
                                    instr1_node_id: str = 'i1_instr',
                                    instr2_node_id: str = 'i2_instr') -> bool:
    """Add a pre-built fused instruction graph to a ResourceGraphMerger.

    The fused graph has two instruction fetch nodes (instr1, instr2) and
    assume expressions that reference both. The decode info is extracted
    from assume_expressions, mapping 'instr1'/'instr2' prefixes to the
    actual graph node IDs.

    Args:
        merger: ResourceGraphMerger instance to add the fused instruction to.
        name: Name of the fused instruction (e.g., 'lui_addi').
        fused_graph: The fused ResourceGraph from MacroOpFusion.fuse().
        instr1_node_id: Node ID for the first instruction fetch.
        instr2_node_id: Node ID for the second instruction fetch.
    """
    from core.graph_merger import InstructionDecodeInfo, ResourceGraphMerger
    from core.timing_utils import reinfer_timing

    try:
        reinfer_timing(fused_graph)

        instr_node_id = instr1_node_id

        # Map assume expression identifiers to actual graph node names:
        # instr1 -> i1_instr, instr2 -> i2_instr
        instr_map = {'instr1': instr1_node_id, 'instr2': instr2_node_id}

        def _map_instr_refs(expr_str: str) -> str:
            for old, new in instr_map.items():
                if expr_str.startswith(old + '[') or expr_str == old:
                    expr_str = new + expr_str[len(old):]
            return expr_str

        decode_info = InstructionDecodeInfo(name)
        for assume_expr in getattr(fused_graph, 'assume_expressions', []):
            if assume_expr.get('type') == 'binary_op' and assume_expr.get('operator') in ('==', '!='):
                left_str = ResourceGraphMerger._assume_expr_to_string(assume_expr.get('left', {}))
                right_str = ResourceGraphMerger._assume_expr_to_string(assume_expr.get('right', {}))
                left_str = _map_instr_refs(left_str)
                right_str = _map_instr_refs(right_str)
                decode_info.add_assume_condition(left_str, assume_expr['operator'], right_str)

        merger.graphs[name] = fused_graph
        merger.decode_info[name] = decode_info
        merger.instruction_nodes[name] = instr_node_id

        print(f"Added fused instruction: {decode_info}")
        return True

    except Exception as e:
        print(f"Error adding fused instruction {name}: {e}")
        import traceback
        traceback.print_exc()
        return False


def merge_instructions_with_fusion(instruction_files: Dict[str, str],
                                   fused_graphs: Dict[str, ResourceGraph] = None,
                                   fusion_pairs: Dict[str, str] = None,
                                   memory_constraints: Dict[str, int] = None,
                                   pc_name: str = "pc",
                                   defines: Dict[str, str] = None) -> ResourceGraph:
    """Merge instruction ISA files and fused instruction graphs into a unified ResourceGraph.

    Extends the standard merge_instructions() to also include pre-built fused
    instruction graphs from macro-op fusion. Handles instruction length
    overrides for fused pairs and adds mutual exclusion logic so base
    instruction enables are suppressed when their fused variant fires.

    Args:
        instruction_files: Dict mapping instruction names to ISA file paths
        fused_graphs: Dict mapping fused instruction names to ResourceGraph objects
        fusion_pairs: Dict mapping fused instruction names to their i1 base
            instruction name (e.g., {'lui_addi': 'lui', 'auipc_addi': 'auipc'}).
        memory_constraints: Optional memory width constraints
        pc_name: Name of the program counter register (default "pc")
        defines: Optional preprocessor defines

    Returns:
        Merged ResourceGraph with both base and fused instructions
    """
    from core.graph_merger import ResourceGraphMerger, _create_pc_increment_mux
    from core.instruction_length_analyzer import analyze_instruction_length, remove_intermediate_pc_writes

    merger = ResourceGraphMerger(defines=defines)

    if memory_constraints:
        merger.memory_constraints = memory_constraints

    # Add all base instructions
    for instr_name, isa_file in instruction_files.items():
        success = merger.add_instruction(instr_name, isa_file)
        if not success:
            raise ValueError(f"Failed to add instruction {instr_name}")

    # Add fused instructions
    if fused_graphs:
        for fused_name, fused_graph in fused_graphs.items():
            success = add_fused_instruction_to_merger(merger, fused_name, fused_graph)
            if not success:
                print(f"Warning: Failed to add fused instruction {fused_name}")

    # Analyze instruction lengths
    print("\nAnalyzing instruction lengths...")
    instruction_lengths = {}
    for instr_name, graph in merger.graphs.items():
        length = analyze_instruction_length(graph, pc_name)
        if length is not None:
            instruction_lengths[instr_name] = length
            print(f"  {instr_name}: {length} bytes")
        else:
            print(f"  {instr_name}: computed destination (no fixed increment)")

    # Override fused instruction lengths: they consume 2 instructions,
    # so their PC increment is 2x the base increment
    if fused_graphs:
        base_lengths = [l for n, l in instruction_lengths.items() if n not in fused_graphs]
        if base_lengths:
            base_increment = min(base_lengths)
        else:
            base_increment = 4
        for fused_name in fused_graphs:
            fused_length = 2 * base_increment
            instruction_lengths[fused_name] = fused_length
            print(f"  {fused_name}: {fused_length} bytes (fused, 2 × {base_increment})")

    if instruction_lengths:
        max_length = max(instruction_lengths.values())
        print(f"  Maximum instruction length: {max_length} bytes")
    else:
        max_length = 0
        print(f"  No fixed PC increment patterns found")

    remove_intermediate_pc_writes(merger.graphs, pc_name)

    merged_graph = merger.merge_graphs(pc_name=pc_name)

    # Add mutual exclusion: suppress base instruction enables when fused variant fires.
    # Without this, both lui_enable and lui_addi_enable fire simultaneously for fusible
    # pairs, corrupting the OR-based mux outputs.
    if fusion_pairs:
        print("\nAdding fusion exclusion logic...")
        for fused_name, base_i1_name in fusion_pairs.items():
            fused_enable_id = f"{fused_name}_enable"
            base_enable_id = f"{base_i1_name}_enable"
            fused_enable = merged_graph.nodes.get(fused_enable_id)
            base_enable = merged_graph.nodes.get(base_enable_id)
            if fused_enable and base_enable:
                excl_edge = Edge(
                    source=fused_enable,
                    target=base_enable,
                    edge_id=f"{fused_enable_id}_excludes_{base_enable_id}",
                    data={'type': 'decode_exclude'},
                )
                merged_graph.add_edge(excl_edge)
                print(f"  {base_i1_name}_enable suppressed by {fused_name}_enable")
            else:
                if not fused_enable:
                    print(f"  Warning: {fused_enable_id} not found in merged graph")
                if not base_enable:
                    print(f"  Warning: {base_enable_id} not found in merged graph")

    unique_lengths = set(instruction_lengths.values())
    if len(unique_lengths) > 1:
        print(f"\nCreating PC increment multiplexer for variable-length instructions...")
        _create_pc_increment_mux(merged_graph, instruction_lengths, pc_name)

    return merged_graph
