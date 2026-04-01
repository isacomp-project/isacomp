#!/usr/bin/env python3
"""
Hazard resolution strategies for pipelined processors.

This module implements both stalling and bypassing/forwarding strategies
for resolving pipeline hazards.
"""

import re
from typing import Dict, List, Set, Tuple, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.pipeline_config import PipelineConfig
from dataclasses import dataclass
from enum import Enum
from core.resource_graph import ResourceGraph, Node, Edge
from core.hardware_builders import HardwareBuilderFactory
from core.array_access_utils import ArrayAccessAnalyzer


class HazardResolutionStrategy(Enum):
    """Strategy for resolving a detected hazard."""
    STALL = "stall"
    STALL_ENABLE_ONLY = "stall_enable_only"  # Stall based on write-enable only (no index comparison)
    BYPASS = "bypass"
    NONE = "none"  # User explicitly chose no resolution


@dataclass
class PipelineStageInfo:
    """Information about a pipeline stage."""
    stage_index: int
    stage_name: str
    pipeline_register: Node
    nodes_in_stage: List[Node]


@dataclass
class DetectedHazard:
    """A detected pipeline hazard with its characteristics.

    Supports both indexed (2D) hazards (e.g., register files accessed via rf[rd])
    and non-indexed (1D) hazards (e.g., individual registers like A, X, flags).

    For non-indexed hazards, the index fields (write_index_node, write_index_name,
    read_index_node, read_index_name) are None, and no index comparison is needed
    during resolution — the stall/bypass condition is purely enable-based.
    """
    hazard_type: str  # 'RAW', 'WAR', 'WAW'
    resource: str  # e.g., 'rf' for indexed, 'A' or 'flag_Z' for non-indexed

    # Write information
    write_stage: int
    write_stage_name: str  # e.g., "PIPE_stage_2"
    write_access_node: Node  # e.g., rf[rd]_wr (indexed) or A_wr (non-indexed)
    write_index_node: Optional[Node] = None  # e.g., rd (None for non-indexed)
    write_index_name: Optional[str] = None  # e.g., "rd" (None for non-indexed)

    # Read information
    read_stage: int = 0
    read_stage_name: str = ""  # e.g., "PIPE_stage_0"
    read_access_node: Optional[Node] = None  # e.g., rf[rs]_rd (indexed) or A_rd (non-indexed)
    read_index_node: Optional[Node] = None  # e.g., rs (None for non-indexed)
    read_index_name: Optional[str] = None  # e.g., "rs" (None for non-indexed)

    # Resolution strategy (to be chosen by user)
    resolution: HazardResolutionStrategy = HazardResolutionStrategy.STALL

    # Pipeline information (for superscalar/dual-issue processors)
    # Empty string means single-pipeline (no cross-pipeline distinction)
    write_pipeline: str = ''  # e.g., 'primary' or 'secondary'
    read_pipeline: str = ''   # e.g., 'primary' or 'secondary'

    @property
    def is_indexed(self) -> bool:
        """Whether this hazard involves indexed (array) access requiring index comparison."""
        return self.write_index_node is not None

    def is_cross_pipeline(self) -> bool:
        """Check if this hazard crosses pipeline boundaries (superscalar only)."""
        return self.write_pipeline != self.read_pipeline and self.write_pipeline != '' and self.read_pipeline != ''

    def __str__(self):
        pipeline_info = ''
        if self.write_pipeline and self.read_pipeline:
            pipeline_info = f"{self.write_pipeline}→{self.read_pipeline} "
        if self.is_indexed:
            return (f"{pipeline_info}{self.hazard_type} hazard: "
                    f"{self.write_stage_name}(write {self.resource}[{self.write_index_name}]) → "
                    f"{self.read_stage_name}(read {self.resource}[{self.read_index_name}])")
        else:
            return (f"{pipeline_info}{self.hazard_type} hazard on {self.resource}: "
                    f"write@{self.write_stage_name}(stage {self.write_stage}) -> "
                    f"read@{self.read_stage_name}(stage {self.read_stage})")

    def get_forwarding_distance(self) -> int:
        """Get the number of stages between write and read."""
        return self.write_stage - self.read_stage


class HazardAnalyzer:
    """Analyzes pipeline for hazards and identifies resolution opportunities."""

    def __init__(self, graph: ResourceGraph, pc_name: str, time_field: str = 'pipe_time'):
        """
        Initialize the hazard analyzer.

        Args:
            graph: ResourceGraph to analyze
            pc_name: Name of the program counter ISA state (e.g., 'pc', 'PC').
                     Required because PC is updated every cycle and should not
                     trigger data hazard detection.
            time_field: The node attribute to use for timing comparisons.
                       'pipe_time' for single-issue pipelines (default).
                       'dual_issue_time' for dual-issue superscalar pipelines.
        """
        self.graph = graph
        self.pipeline_stages = []
        self.hazards = []
        self.pc_name = pc_name
        self.time_field = time_field

    def get_node_time(self, node: 'Node') -> Optional[int]:
        """
        Get the relevant time value for a node based on configured time_field.

        For single-issue: uses pipe_time
        For dual-issue: uses dual_issue_time

        Falls back to pipe_time, then uarch_time if the configured field is None.

        Args:
            node: The node to get timing for

        Returns:
            The time value, or None if not available
        """
        # Try the configured time field first
        time_val = getattr(node, self.time_field, None)
        if time_val is not None:
            return time_val

        # Fall back to pipe_time if using dual_issue_time and it's not set
        if self.time_field == 'dual_issue_time':
            time_val = getattr(node, 'pipe_time', None)
            if time_val is not None:
                return time_val

        # Final fallback to uarch_time for backward compatibility
        return getattr(node, 'uarch_time', None)

    def identify_pipeline_stages(self) -> List[PipelineStageInfo]:
        """Identify all pipeline stages in the graph."""
        # Find all pipeline registers - sorted for determinism
        pipeline_regs = []
        for node_id, node in sorted(self.graph.nodes.items()):
            if node.data.get('type') == 'pipeline_register':
                pipeline_regs.append(node)

        # Group pipeline registers by stage name
        # Support both single-issue (PIPE_<StageName>_*_PIPE)
        # and dual-issue (p0_PIPE_<StageName>_*_PIPE, p1_PIPE_<StageName>_*_PIPE)
        stages_dict = {}
        for reg in pipeline_regs:
            # Extract stage name from node ID
            node_id = reg.id

            # Strip dual-issue prefix if present
            if node_id.startswith('p0_') or node_id.startswith('p1_'):
                node_id = node_id[3:]  # Remove pX_ prefix

            if node_id.startswith('PIPE_') and '_PIPE' in node_id:
                parts = node_id.split('_')
                if len(parts) >= 3:
                    stage_name = parts[1]
                    if stage_name not in stages_dict:
                        stages_dict[stage_name] = []
                    stages_dict[stage_name].append(reg)

        # Create stage info, one per unique stage name
        # Stage indices start at 1 (stage 0 is before the first pipeline cut)
        stages = []
        for i, (stage_name, regs) in enumerate(sorted(stages_dict.items())):
            stage = PipelineStageInfo(
                stage_index=i + 1,  # +1 because stage 0 is before first cut
                stage_name=stage_name,
                pipeline_register=regs[0],  # Use first register as representative
                nodes_in_stage=[]
            )
            stages.append(stage)

        self.pipeline_stages = stages
        return stages

    def determine_node_stage(self, node: Node) -> Optional[int]:
        """
        Determine which pipeline stage a node belongs to.

        Returns the stage index (0 = earliest, higher = later stages).
        Returns None if node is not in any stage or is before all stages.
        """
        if not self.pipeline_stages:
            return None

        # DFS backward from node to see which pipeline registers we encounter
        visited = set()
        stages_encountered = set()

        def dfs_backward(n: Node):
            if n.id in visited:
                return
            visited.add(n.id)

            # Check if this is a pipeline register
            for i, stage in enumerate(self.pipeline_stages):
                if n.id == stage.pipeline_register.id:
                    stages_encountered.add(i)
                    return  # Don't go further back from a pipeline register

            # Continue backward
            for edge in n.incoming_edges:
                dfs_backward(edge.source)

        dfs_backward(node)

        # Node is in the stage AFTER the latest pipeline register encountered
        # (or stage 0 if no pipeline registers encountered)
        if stages_encountered:
            return max(stages_encountered) + 1
        else:
            return 0

    def _trace_write_index_through_pipeline(self, final_index_node: Node, index_name: str) -> List[dict]:
        """
        Trace a write index backwards through pipeline registers to find all stages
        where the index exists.

        For example, if final_index_node is PIPE_Writeback_PIPE_Memory_PIPE_Execute_rd_PIPE_PIPE_PIPE,
        this traces back to find:
        - PIPE_Writeback_..._rd_... at Writeback stage
        - PIPE_Memory_..._rd_... at Memory stage
        - PIPE_Execute_rd_PIPE at Execute stage

        Returns list of dicts with 'node' and 'stage' keys.
        The stage is determined by the pipeline register's depth (counting _PIPE suffixes),
        not by uarch_time (which represents when the value was computed).
        """
        result = []
        current_node = final_index_node

        # Count _PIPE suffixes to determine pipeline depth
        # PIPE_Execute_*_PIPE has 1 suffix -> stage 2 (Execute)
        # PIPE_Memory_*_PIPE_PIPE has 2 suffixes -> stage 3 (Memory)
        # PIPE_Writeback_*_PIPE_PIPE_PIPE has 3 suffixes -> stage 4 (Writeback)
        def count_pipe_depth(node_id: str) -> int:
            # Count trailing _PIPE suffixes
            depth = 0
            parts = node_id.split('_')
            for i in range(len(parts) - 1, -1, -1):
                if parts[i] == 'PIPE':
                    depth += 1
                else:
                    break
            return depth

        # Add the final stage
        if current_node.data.get('type') == 'pipeline_register':
            pipe_depth = count_pipe_depth(current_node.id)
            stage = pipe_depth + 1  # Stage is 1-indexed (Fetch=0, Decode=1, Execute=2, etc.)
            # Clamp to max stage (for pipelines where the heuristic overcounts, like 2-stage)
            max_stage = max(s.stage_index for s in self.pipeline_stages) if self.pipeline_stages else stage
            stage = min(stage, max_stage)
            result.append({
                'node': current_node,
                'stage': stage
            })

        # Trace backwards through pipeline registers
        visited = set()
        while current_node and current_node.id not in visited:
            visited.add(current_node.id)

            # Check if this is a pipeline register - if so, trace its input
            if current_node.data.get('type') == 'pipeline_register':
                # Find the pipeline_input edge
                for edge in current_node.incoming_edges:
                    if edge.data.get('type') == 'pipeline_input':
                        source = edge.source
                        # Check if source is also a pipeline register for the same signal.
                        # Use both name-based matching (index_name in source.id) and
                        # structural matching: if the source is a pipeline_register and
                        # feeds into the current pipeline_register via pipeline_input,
                        # it represents the same signal one stage earlier.
                        if source.data.get('type') == 'pipeline_register' and (
                            index_name in source.id or
                            # Structural match: the nested PIPE naming convention embeds
                            # the source stage name in the target. Check if stripping the
                            # outermost PIPE_<Stage>_ prefix and one _PIPE suffix from
                            # current_node gives the source name.
                            self._is_pipeline_predecessor(source.id, current_node.id)
                        ):
                            # Add this stage
                            pipe_depth = count_pipe_depth(source.id)
                            stage = pipe_depth + 1
                            # Clamp to max stage
                            max_stage = max(s.stage_index for s in self.pipeline_stages) if self.pipeline_stages else stage
                            stage = min(stage, max_stage)
                            result.append({
                                'node': source,
                                'stage': stage
                            })
                            current_node = source
                            break
                        else:
                            # Hit the original signal (not a pipeline register)
                            current_node = None
                            break
                else:
                    # No pipeline_input edge found
                    current_node = None
            else:
                # Not a pipeline register, stop tracing
                current_node = None

        return result

    @staticmethod
    def _count_pipe_depth(node_id: str) -> int:
        """Count trailing _PIPE suffixes to determine pipeline depth."""
        depth = 0
        parts = node_id.split('_')
        for i in range(len(parts) - 1, -1, -1):
            if parts[i] == 'PIPE':
                depth += 1
            else:
                break
        return depth

    @staticmethod
    def _is_pipeline_predecessor(source_id: str, target_id: str) -> bool:
        """
        Check if source_id is the pipeline predecessor of target_id.

        In the PIPE naming convention, a pipeline register at stage N+1 has
        a name that wraps the stage N register name. For example:
        - Stage 2: p0_PIPE_Execute_rd_PIPE
        - Stage 3: p0_PIPE_MemoryWriteback_PIPE_Execute_rd_PIPE_PIPE

        The target (stage 3) contains the source name with the outermost
        PIPE_<Stage>_ prefix and trailing _PIPE removed. This method checks
        that structural relationship.
        """
        # Strip dual-issue prefix (p0_, p1_) from both for comparison
        prefix_re = re.compile(r'^(p\d+_)')
        s = prefix_re.sub('', source_id)
        t = prefix_re.sub('', target_id)

        # The target wraps the source: target = PIPE_<Stage>_<source>_PIPE
        # So stripping the outermost PIPE_<Stage>_ prefix and one trailing _PIPE
        # from the target should give us the source name.
        m = re.match(r'^PIPE_[A-Za-z]+_(.+)$', t)
        if m:
            inner = m.group(1)
            # Strip one trailing _PIPE from inner (the outermost suffix)
            if inner.endswith('_PIPE'):
                inner = inner[:-5]
            # Now inner should equal source
            if inner == s:
                return True

        return False

    def analyze_hazards(self) -> List[DetectedHazard]:
        """
        Analyze the graph for all pipeline hazards — both indexed and non-indexed.

        Discovers:
        1. Indexed ISA state resources (register files, memories, etc.) that use
           array access (e.g., rf[rd]) and require index comparison for hazard detection.
        2. Non-indexed (individual) ISA state elements (e.g., A, X, Y, flags, CR, LR)
           that are single registers not accessed via array indexing.

        Returns a unified list of DetectedHazard objects. Non-indexed hazards have
        their index fields set to None (hazard.is_indexed == False).
        """
        self.hazards = []

        # Make sure we have stage information
        if not self.pipeline_stages:
            self.identify_pipeline_stages()

        # --- Phase 1: Discover indexed ISA state resources ---
        # Uses ArrayAccessAnalyzer to find register files, memories, and any
        # other indexed isa_state. We filter to only resources whose base
        # node is marked is_arch_state to avoid picking up temporary vars that
        # happen to use array indexing.
        analyzer = ArrayAccessAnalyzer(self.graph)
        all_accesses = analyzer.get_all_array_accesses()  # No filter - get everything

        # Group accesses by resource name, filtering to ISA state
        resources = {}
        for access_info in all_accesses:
            res = access_info.base_resource
            # Check that the base resource is actually ISA state
            base_node = self.graph.nodes.get(res)
            if base_node and (base_node.is_arch_state or
                              base_node.data.get('type') == 'isa_state'):
                # Skip variable-latency memories — they have dedicated stall
                # handling via _add_automatic_memory_latency_stalls() which
                # creates memory-specific stall conditions using access_enable
                # and complete_signal. Generic RAW resolution would be redundant
                # and over-aggressive (stalling the entire pipeline vs targeted).
                if getattr(base_node, 'variable_latency', False):
                    continue
                if res not in resources:
                    resources[res] = []
                resources[res].append(access_info)

        if resources:
            print(f"Discovered indexed ISA state resources: {sorted(resources.keys())}")
        else:
            print("No indexed ISA state resources found")

        # Analyze hazards for each indexed resource
        for resource_name in sorted(resources.keys()):
            self._analyze_resource_hazards(analyzer, resource_name)

        # --- Phase 2: Discover non-indexed (individual) ISA state elements ---
        # Finds registers like A, X, Y, S, flags, CR, LR, CTR, XER that are
        # individual named elements (no array indexing).
        # Pass the set of already-discovered indexed resource names so we don't
        # double-count resources like 'rf' that have both indexed accesses
        # (rf[rs1]_rd) and non-indexed base nodes (rf_rd, rf_wr).
        indexed_resource_names = set(resources.keys())
        self._analyze_individual_isa_state_hazards(indexed_resource_names)

        return self.hazards

    def _analyze_resource_hazards(self, analyzer: ArrayAccessAnalyzer, resource_name: str):
        """Analyze RAW hazards for a single indexed resource (rf, memory, etc.)."""
        read_accesses, write_accesses = analyzer.get_reads_and_writes(resource_name)

        # Build reads list with stage information
        res_reads = []
        for access_info in read_accesses:
            # Use pipe_time for stage determination (same scale as writes).
            # For dual-issue, get_node_time() returns dual_issue_time which is
            # on a different numeric scale than determine_node_stage()/pipe_time
            # used for writes, causing hazard detection to fail. Using pipe_time
            # for both reads and writes ensures correct comparison and produces
            # the pipe_time values the resolver expects.
            stage = getattr(access_info.node, 'pipe_time', None)
            if stage is None:
                stage = self.determine_node_stage(access_info.node)
            if stage is not None:
                # If the index node is a renamed (physical) index, resolve back to
                # the original architectural index for hazard comparison.
                # Hazard detection must compare architectural registers (rd vs rs1)
                # regardless of renaming, because renaming doesn't eliminate RAW hazards.
                index_node = access_info.index_node
                index_name = access_info.index
                if index_node and index_node.data.get('type') == 'uarch_index':
                    arch_idx_id = index_node.data.get('architectural_index')
                    if arch_idx_id and arch_idx_id in self.graph.nodes:
                        index_node = self.graph.nodes[arch_idx_id]
                        index_name = arch_idx_id

                # For dual-issue, use the actual index node ID (e.g., p0_rs1, p1_rs1)
                # as the index name so that hazard comparisons and stall signals
                # get unique names per pipe. Without this, both P0 and P1 reads
                # would generate the same comp_id, causing node collisions.
                read_pipe_id = getattr(access_info.node, 'pipe_id', None)
                if read_pipe_id is not None and index_node is not None:
                    index_name = index_node.id

                res_reads.append({
                    'node': access_info.node,
                    'index': index_name,
                    'index_node': index_node,
                    'stage': stage
                })

        # Build writes list with stage information
        res_writes = []
        for access_info in write_accesses:
            stage = self.determine_node_stage(access_info.node)
            if stage is not None:
                res_writes.append({
                    'node': access_info.node,
                    'index': access_info.index,
                    'index_node': access_info.index_node,
                    'stage': stage
                })

        # Also check for memory_write_port nodes (used by merged processors)
        # These have write_address edges that indicate the index, or
        # write_enable edges (for merged processors with address muxes).
        for node_id, node in sorted(self.graph.nodes.items()):
            if node.data.get('type') == 'memory_write_port' and resource_name in node_id:
                # Find the index from write_address edge
                index_node = None
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'write_address':
                        index_node = edge.source
                        break

                # For merged processors: the write port may not have a
                # write_address edge directly. Instead, the address comes
                # through the write_addr_mux. Find the write enable as
                # the "index" - for memory hazards we can stall based on
                # write_enable vs read_enable without comparing addresses.
                if not index_node:
                    # Use the write enable signal as the index for hazard
                    # detection. This creates a conservative stall: any
                    # memory write in XMW stalls any memory read in Decode.
                    for edge in node.incoming_edges:
                        if edge.data.get('type') == 'write_enable':
                            index_node = edge.source
                            break

                if not index_node:
                    continue

                # Extract a base name for tracing through pipeline registers
                index_name = index_node.id

                # Strip PIPE_ prefixes and _PIPE suffixes to get core name
                core_name = index_name
                while core_name.startswith('PIPE_'):
                    parts = core_name.split('_', 2)
                    if len(parts) >= 3:
                        core_name = parts[2]
                    else:
                        break
                while core_name.endswith('_PIPE'):
                    core_name = core_name[:-5]

                index_name = core_name if core_name else index_node.id

                # For register files, the index signal is piped across stages
                # and we need to trace through pipeline registers to find all
                # stages. For memories, the address comes through a mux in the
                # write stage - use the write port's stage directly.
                all_write_stages = self._trace_write_index_through_pipeline(index_node, index_name)
                if all_write_stages:
                    for stage_info in all_write_stages:
                        res_writes.append({
                            'node': node,
                            'index': index_name,
                            'index_node': stage_info['node'],
                            'stage': stage_info['stage']
                        })
                else:
                    # Fallback: if index isn't a pipeline register chain, use the write port's stage directly
                    # Use pipe_time for consistency with read stages (both use pipe_time scale)
                    write_stage = getattr(node, 'pipe_time', None)
                    if write_stage is None:
                        write_stage = self.determine_node_stage(node)
                    if write_stage is not None:
                        res_writes.append({
                            'node': node,
                            'index': index_name,
                            'index_node': index_node,
                            'stage': write_stage
                        })

        print(f"Found {len(res_reads)} {resource_name} reads, {len(res_writes)} {resource_name} writes")

        # Detect RAW hazards: write in later stage, read in earlier stage
        for write in res_writes:
            for read in res_reads:
                # Only create hazard if write is in a later stage than read
                if write['stage'] > read['stage']:
                    write_stage_name = self._stage_name_for_time(write['stage'])
                    read_stage_name = self._stage_name_for_time(read['stage'])

                    hazard = DetectedHazard(
                        hazard_type='RAW',
                        resource=resource_name,
                        write_stage=write['stage'],
                        write_stage_name=write_stage_name,
                        write_access_node=write['node'],
                        write_index_node=write['index_node'],
                        write_index_name=write['index'],
                        read_stage=read['stage'],
                        read_stage_name=read_stage_name,
                        read_access_node=read['node'],
                        read_index_node=read['index_node'],
                        read_index_name=read['index']
                    )
                    self.hazards.append(hazard)
                    print(f"  Detected: {hazard}")

    def _stage_name_for_time(self, pipe_time: int) -> str:
        """Map a pipe_time value to a stage name."""
        if pipe_time > 0 and pipe_time - 1 < len(self.pipeline_stages):
            return self.pipeline_stages[pipe_time - 1].stage_name
        elif pipe_time == 0:
            return "f"
        elif len(self.pipeline_stages) > 0:
            return self.pipeline_stages[-1].stage_name
        else:
            return f"stage_{pipe_time}"

    def _analyze_individual_isa_state_hazards(self, indexed_resource_names: Optional[set] = None):
        """
        Discover non-indexed (individual) ISA state elements and detect RAW hazards.

        Appends DetectedHazard objects (with is_indexed=False) to self.hazards.

        This handles architectures like 6502 where registers are individual named
        elements (A, X, Y, S, flags) rather than entries in an indexed register file,
        as well as non-indexed ISA state in RISC architectures (e.g., OpenPower CR, LR).

        Args:
            indexed_resource_names: Set of resource names already discovered as indexed
                resources (e.g., 'rf', 'mainmem'). These are excluded from individual
                detection to avoid double-counting resources that have both indexed
                accesses (rf[rs1]_rd) and non-indexed base nodes (rf_rd, rf_wr).
        """
        get_node_pipe_time = self.get_node_time

        # Find all individual ISA state elements by looking for _rd and _wr node pairs
        # that don't involve array indexing
        isa_state_reads = {}  # isa_state_name -> list of (node, pipe_time)
        isa_state_writes = {}  # isa_state_name -> list of (node, pipe_time)

        for node_id, node in self.graph.nodes.items():
            node_type = node.data.get('type')

            # Look for ISA state read nodes (e.g., A_rd, X_rd, flag_Z_rd)
            if node_id.endswith('_rd') and node_type == 'isa_state':
                # Check it's not an array access (no '[' in the name)
                base_name = node_id[:-3]  # Remove '_rd'
                if '[' not in base_name:
                    ptime = get_node_pipe_time(node)
                    if ptime is not None:
                        if base_name not in isa_state_reads:
                            isa_state_reads[base_name] = []
                        isa_state_reads[base_name].append((node, ptime))

            # Look for ISA state write nodes (e.g., A_wr, X_wr, flag_Z_wr)
            # Also check for is_arch_state_target which is set by ISA merger for write targets
            elif node_id.endswith('_wr') and (node_type == 'isa_state' or node.data.get('is_arch_state_target')):
                base_name = node_id[:-3]  # Remove '_wr'
                if '[' not in base_name:
                    ptime = get_node_pipe_time(node)
                    if ptime is not None:
                        if base_name not in isa_state_writes:
                            isa_state_writes[base_name] = []
                        isa_state_writes[base_name].append((node, ptime))

            # Also look for shared write nodes (used by merged processors)
            elif '_shared_wr' in node_id or node_type == 'memory_write_port':
                # Extract base name from shared write node
                # Pattern: {base}_shared_wr or similar
                for suffix in ['_shared_wr', '_wr_mux']:
                    if suffix in node_id:
                        base_name = node_id.split(suffix)[0]
                        if '[' not in base_name and base_name:
                            ptime = get_node_pipe_time(node)
                            if ptime is not None:
                                if base_name not in isa_state_writes:
                                    isa_state_writes[base_name] = []
                                isa_state_writes[base_name].append((node, ptime))
                        break

        # Also check for pipelined versions of reads/writes
        for node_id, node in self.graph.nodes.items():
            if node.data.get('type') != 'pipeline_register':
                continue

            # Check if this is a pipelined version of an ISA state read/write
            # Pattern: PIPE_StageName_..._rd_PIPE or PIPE_StageName_..._wr_PIPE
            for base_name in sorted(set(list(isa_state_reads.keys()) + list(isa_state_writes.keys()))):
                if f"_{base_name}_rd_" in node_id or node_id.endswith(f"_{base_name}_rd_PIPE"):
                    ptime = get_node_pipe_time(node)
                    if ptime is not None:
                        if base_name not in isa_state_reads:
                            isa_state_reads[base_name] = []
                        # Avoid duplicates
                        if not any(n.id == node_id for n, _ in isa_state_reads[base_name]):
                            isa_state_reads[base_name].append((node, ptime))

                if f"_{base_name}_wr_" in node_id or node_id.endswith(f"_{base_name}_wr_PIPE"):
                    ptime = get_node_pipe_time(node)
                    if ptime is not None:
                        if base_name not in isa_state_writes:
                            isa_state_writes[base_name] = []
                        if not any(n.id == node_id for n, _ in isa_state_writes[base_name]):
                            isa_state_writes[base_name].append((node, ptime))

        # Skip PC from hazard detection - it's updated every cycle and
        # handled specially by control flow logic, not data hazard resolution.
        # Also skip resources already handled as indexed (e.g., 'rf') to avoid
        # double-counting — their base rf_rd/rf_wr nodes would otherwise be
        # picked up here.
        skip_elements = {self.pc_name}
        if indexed_resource_names:
            skip_elements |= indexed_resource_names

        # Find ISA state elements that have both reads and writes
        isa_states_with_hazards = set(isa_state_reads.keys()) & set(isa_state_writes.keys())
        isa_states_with_hazards -= skip_elements

        print(f"  Found {len(isa_states_with_hazards)} individual ISA state elements with potential hazards")

        # Detect RAW hazards for each ISA state element
        for isa_state_name in sorted(isa_states_with_hazards):
            reads = isa_state_reads.get(isa_state_name, [])
            writes = isa_state_writes.get(isa_state_name, [])

            for write_node, write_time in writes:
                for read_node, read_time in reads:
                    # RAW hazard: write in later stage, read in earlier stage
                    if write_time > read_time:
                        hazard = DetectedHazard(
                            hazard_type='RAW',
                            resource=isa_state_name,
                            write_stage=write_time,
                            write_stage_name=self._stage_name_for_time(write_time),
                            write_access_node=write_node,
                            # No index nodes for individual ISA state
                            write_index_node=None,
                            write_index_name=None,
                            read_stage=read_time,
                            read_stage_name=self._stage_name_for_time(read_time),
                            read_access_node=read_node,
                            read_index_node=None,
                            read_index_name=None,
                        )
                        self.hazards.append(hazard)
                        print(f"    Detected: {hazard}")



class HazardResolver:
    """Implements hazard resolution strategies (stalling and bypassing)."""

    @staticmethod
    def _count_pipe_depth(node_id: str) -> int:
        """Count trailing _PIPE suffixes to determine pipeline depth."""
        depth = 0
        parts = node_id.split('_')
        for i in range(len(parts) - 1, -1, -1):
            if parts[i] == 'PIPE':
                depth += 1
            else:
                break
        return depth

    @staticmethod
    def _extract_core_name(node_id: str) -> str:
        """Extract core signal name from pipelined name.

        Strips dual-issue prefix (p0_, p1_), PIPE_Stage_ prefixes,
        and trailing _PIPE suffixes.

        e.g. "p0_PIPE_MW_PIPE_Exec_rf_enable_PIPE_PIPE" -> "rf_enable"
        e.g. "PIPE_Writeback_rf_enable_PIPE" -> "rf_enable"
        """
        core_name = node_id
        # Strip dual-issue prefix (p0_, p1_)
        core_name = re.sub(r'^p\d+_', '', core_name)
        # Strip all PIPE_StageName_ prefixes
        while core_name.startswith('PIPE_'):
            parts = core_name.split('_', 2)
            if len(parts) >= 3:
                core_name = parts[2]
            else:
                break
        # Strip trailing _PIPE suffixes
        while core_name.endswith('_PIPE'):
            core_name = core_name[:-5]
        return core_name

    def __init__(self, graph: ResourceGraph, isa_states_to_gate: Optional[List[str]] = None,
                 pipeline_config=None):
        """
        Initialize the hazard resolver.

        Args:
            graph: ResourceGraph to resolve hazards in
            isa_states_to_gate: Optional list of ISA state node IDs that should be
                               gated when stalling (e.g., ['pc_rd']). If not provided,
                               ISA state elements at uarch_time 0 will be auto-detected.
            pipeline_config: Optional PipelineConfig for stage information
        """
        self.graph = graph
        self.hw_factory = HardwareBuilderFactory(graph)  # Hardware builder factory
        self.isa_states_to_gate = isa_states_to_gate
        self.pipeline_config = pipeline_config
        # Track bypass muxes created to handle multiple hazards to same read port
        self.bypass_muxes = {}  # read_index_name -> bypass_mux_node
        # Track hazards that were resolved with bypass muxes
        self.bypass_hazards = {}  # mux_id -> hazard
        # Track all hazards for combined resolution
        self.pending_hazards = []
        # Track stall integrations that couldn't find a controller yet
        self._pending_stall_integrations = []  # [(stall_node, reason), ...]

    def _memory_has_write_read_fwd(self, memory_name: str) -> bool:
        """
        Check if a memory has write-to-read forwarding enabled.

        When enabled, the memory handles same-cycle forwarding in hardware,
        so we don't need to add explicit forwarding logic for the case where
        write and read happen at the same clock edge.

        Args:
            memory_name: Name of the memory (e.g., 'rf', 'dmem')

        Returns:
            True if write_read_fwd is enabled on the memory
        """
        memory_node = self.graph.nodes.get(memory_name)
        if not memory_node:
            return False
        return memory_node.data.get('write_read_fwd', False)

    def _find_cache_for_memory(self, memory_node: 'Node') -> Optional['Node']:
        """
        Find a cache that fronts this memory using structural graph traversal.

        When a cache is present for a memory, the cache should take precedence
        for hazard detection because:
        - The cache is accessed first (pipeline sees cache latency)
        - The cache's complete_signal determines when data is ready
        - Memory is only accessed on cache misses (refill/write-through)

        Detection methods:
        1. Check incoming edges for cache_write_through (RW cache write path)
        2. Check outgoing edges for refill array_access nodes (cache read path)

        Args:
            memory_node: The memory node to check

        Returns:
            The cache node if found, None otherwise
        """
        if not memory_node:
            return None

        # Method 1: Check incoming edges for cache write-through connection
        # Pattern: cache -> write_through_port -> memory
        for edge in memory_node.incoming_edges:
            edge_type = edge.data.get('type') if edge.data else None

            # Direct cache_write_through edge
            if edge_type == 'cache_write_through':
                source = edge.source
                if source.data.get('type') in ('read_write_cache', 'read_only_cache'):
                    return source

            # Or via write_through_port node
            if edge_type == 'memory_write':
                source = edge.source
                if source.data.get('type') == 'cache_write_through_port':
                    cache_name = source.data.get('cache_name')
                    if cache_name and cache_name in self.graph.nodes:
                        return self.graph.nodes[cache_name]

        # Method 2: Check outgoing edges for refill interface
        # Pattern: memory -> array_access(is_refill=True) -> ... -> cache
        for edge in memory_node.outgoing_edges:
            edge_type = edge.data.get('type') if edge.data else None

            if edge_type == 'array_base':
                access_node = edge.target
                if access_node.data.get('is_refill'):
                    # This is a cache refill access - find the cache
                    cache_name = access_node.data.get('cache_name')
                    if cache_name and cache_name in self.graph.nodes:
                        return self.graph.nodes[cache_name]

                    # Or traverse forward through refill_data to cache
                    for out_edge in access_node.outgoing_edges:
                        if out_edge.data.get('type') == 'assignment':
                            refill_data = out_edge.target
                            for data_edge in refill_data.outgoing_edges:
                                if data_edge.data.get('type') == 'refill_data':
                                    target = data_edge.target
                                    if target.data.get('type') in ('read_write_cache', 'read_only_cache'):
                                        return target

        return None  # No cache found

    def _get_effective_latency_source(self, memory_name: str) -> 'Node':
        """
        Get the effective source for latency/stall signals.

        If the memory has a cache, returns the cache (which handles latency).
        Otherwise returns the memory itself.

        Args:
            memory_name: Name of the memory

        Returns:
            The cache node if present, otherwise the memory node
        """
        memory_node = self.graph.nodes.get(memory_name)
        if not memory_node:
            return None

        cache = self._find_cache_for_memory(memory_node)
        if cache:
            return cache

        return memory_node

    def _find_pipelined_index_at_write(self, hazard: DetectedHazard) -> Optional[Node]:
        """
        Find the pipelined version of the write index that actually feeds the write.

        Traces from the original write_index_node forward through pipeline registers
        to find which one provides the array_index edge to the write_access_node.
        """
        # Start by checking which node provides the array_index to the write access
        # (excluding the base array itself)
        for edge in hazard.write_access_node.incoming_edges:
            if edge.data.get('type') in ('array_index', 'write_address') and edge.source.id != hazard.resource:
                # This is the node providing the index at the write location
                candidate = edge.source

                # Check if this candidate is reachable from the original write_index_node
                # by tracing forward through pipeline registers
                if self._is_pipelined_version_of(candidate, hazard.write_index_node):
                    return candidate

        return None

    def _is_pipelined_version_of(self, candidate: Node, original: Node) -> bool:
        """
        Check if candidate is a pipelined version of original.

        Traces backward from candidate to see if we can reach original.
        """
        if candidate.id == original.id:
            return True

        # If candidate is a pipeline register, check its input
        if candidate.data.get('type') == 'pipeline_register':
            for edge in candidate.incoming_edges:
                if edge.data.get('type') == 'pipeline_input':
                    if self._is_pipelined_version_of(edge.source, original):
                        return True

        return False

    def _find_pipelined_index_at_read(self, hazard: DetectedHazard) -> Optional[Node]:
        """
        Find the pipelined version of the read index at the Execute stage.

        For bypass mux forwarding, we need to compare the write address against
        the read index at the Execute stage (where the bypass mux is).
        """
        # The read_index_node is the source index (e.g., rs, rt, rs1, rs2)
        # We need to find its pipelined version at Execute stage (pipe_time = 2 typically)

        # First, look for a pipelined version by following pipeline_output edges
        for edge in hazard.read_index_node.outgoing_edges:
            if edge.data.get('type') == 'pipeline_input':
                # Found a pipelined version
                pipelined = edge.target
                # Check if it's at the right stage (Execute, typically pipe_time=2)
                # Use pipe_time for stage, fall back to uarch_time for compatibility
                ptime = getattr(pipelined, 'pipe_time', None)
                if ptime is None:
                    ptime = getattr(pipelined, 'uarch_time', None)
                if ptime == 2:
                    return pipelined
                # If not, keep tracing forward
                for edge2 in pipelined.outgoing_edges:
                    if edge2.data.get('type') == 'pipeline_input':
                        next_pipelined = edge2.target
                        next_ptime = getattr(next_pipelined, 'pipe_time', None)
                        if next_ptime is None:
                            next_ptime = getattr(next_pipelined, 'uarch_time', None)
                        if next_ptime == 2:
                            return next_pipelined

        # Fallback: search for a node with the read index name in Execute stage
        read_idx_name = hazard.read_index_name
        for node_id, node in sorted(self.graph.nodes.items()):
            if f'Execute_{read_idx_name}' in node_id or f'Execute_{read_idx_name.lower()}' in node_id:
                ptime = getattr(node, 'pipe_time', None)
                if ptime is None:
                    ptime = getattr(node, 'uarch_time', None)
                if 'PIPE' in node_id and ptime == 2:
                    return node

        return None

    def resolve_with_stalling(self, hazard: DetectedHazard) -> bool:
        """
        Resolve a hazard by adding stall logic.

        This creates a comparator and stall signal that prevents the
        earlier stage from advancing when a hazard is detected.
        """
        print(f"Resolving with STALL: {hazard}")

        # Check if memory has write_read_fwd enabled
        # If so, skip stalling for hazards at the memory's read/write stage pair
        # because the memory handles same-cycle forwarding in hardware
        if self._memory_has_write_read_fwd(hazard.resource):
            # Structurally check if hazard is at the memory's canonical read/write positions
            # Use pipe_time for stage comparison, fall back to uarch_time for compatibility
            read_time = getattr(hazard.read_access_node, 'pipe_time', None)
            if read_time is None:
                read_time = getattr(hazard.read_access_node, 'uarch_time', None)
            write_time = getattr(hazard.write_access_node, 'pipe_time', None)
            if write_time is None:
                write_time = getattr(hazard.write_access_node, 'uarch_time', None)
            if read_time is not None and write_time is not None:
                if hazard.read_stage == read_time and hazard.write_stage == write_time:
                    print(f"  Skipping stall - {hazard.resource} has write_read_fwd enabled")
                    print(f"  Memory handles same-cycle forwarding at read/write stages")
                    return True

        # Build the stall condition: [comparator] && write_enable && stage_valid [&& read_enable]
        # Comparator is present only for indexed hazards that need index comparison.
        stall_signal_node, write_stage_name, read_enable_node = self._build_stall_condition(hazard)

        # For enable-only stalls, suppress read enable gating (conservative: stall
        # whenever any write is active, regardless of read instruction)
        if hazard.resolution == HazardResolutionStrategy.STALL_ENABLE_ONLY:
            read_enable_node = None

        if stall_signal_node is None:
            # Resolution helper couldn't build a stall condition (e.g., missing signals)
            print(f"  Warning: Could not build stall condition for {hazard}")
            return False

        # Step 4: AND with read_enable if available
        # This gates the stall so it only fires when the current instruction actually uses this register
        # (e.g., JAL/LUI/AUIPC don't use rs1/rs2 - those fields contain immediate values)
        if read_enable_node:
            and_with_read_enable_id = f"{stall_signal_node.id}_with_rd_en"
            and_with_read_enable = Node(and_with_read_enable_id, data={
                'type': 'operation',
                'operator': '&&',
                'name': and_with_read_enable_id,
                'display_name': f'Stall gated by read enable',
                'hazard_type': hazard.hazard_type,
                'resolution': 'stall',
                'target_stage': hazard.read_stage,
                'bit_width': 1
            })
            self.graph.add_node(and_with_read_enable)

            edge_stall = Edge(stall_signal_node, and_with_read_enable, data={
                'type': 'left_operand',
                'position': 'left'
            })
            self.graph.add_edge(edge_stall)

            edge_rd_en = Edge(read_enable_node, and_with_read_enable, data={
                'type': 'right_operand',
                'position': 'right'
            })
            self.graph.add_edge(edge_rd_en)

            stall_signal_node = and_with_read_enable
            print(f"  Added read enable gating: {and_with_read_enable_id}")

        # Determine if this is a dual-issue pipeline by checking pipe_id on reading node
        read_pipe_id = getattr(hazard.read_access_node, 'pipe_id', None)

        # For dual-issue, create per-pipeline stall controllers
        # For single-issue (pipe_id=None), use the original naming
        if read_pipe_id is not None:
            pipe_prefix = f"p{read_pipe_id}_"
            pipe_reg_pattern_prefix = f"{pipe_prefix}PIPE_"
        else:
            pipe_prefix = ""
            pipe_reg_pattern_prefix = "PIPE_"

        # For non-indexed hazards at pre-pipeline stages (like "f"), there are
        # no PIPE_f_*_PIPE registers to gate.  Determine the effective gate
        # stage: fall back to the earliest pipeline stage that has registers.
        # This matches the old resolve_individual_hazard_with_stalling() logic.
        gate_stage_name = hazard.read_stage_name
        if not hazard.is_indexed:
            _prefix = f"{pipe_prefix}PIPE_{hazard.read_stage_name}_"
            _has_regs = any(
                n.data.get('type') == 'pipeline_register'
                and nid.startswith(_prefix) and nid.endswith('_PIPE')
                for nid, n in self.graph.nodes.items()
            )
            if not _has_regs:
                earliest_time = None
                earliest_stage = None
                _pipe_reg_pfx = f'{pipe_prefix}PIPE_'
                for nid, n in self.graph.nodes.items():
                    if (n.data.get('type') == 'pipeline_register'
                            and nid.startswith(_pipe_reg_pfx) and nid.endswith('_PIPE')):
                        ptime = getattr(n, 'pipe_time', None)
                        if ptime is not None and (earliest_time is None or ptime < earliest_time):
                            after = nid[len(_pipe_reg_pfx):]
                            stage_part = after.split('_')[0]
                            if stage_part:
                                earliest_time = ptime
                                earliest_stage = stage_part
                if earliest_stage:
                    gate_stage_name = earliest_stage
                    print(f"  Pre-pipeline read stage '{hazard.read_stage_name}': "
                          f"gating at '{gate_stage_name}' (earliest pipeline stage)")

        # Find or create stall controller.
        # For pre-pipeline stages, try: read_stage_name first, then gate_stage_name.
        # This allows merging with existing stall controllers at the gate boundary
        # (e.g., RF hazards at Decode share the same controller as individual hazards
        # that read at pre-pipeline "f" stage).
        stall_controller_id = f"{pipe_prefix}PIPE_{hazard.read_stage_name}_stall_ctrl"
        stall_controller = self.graph.nodes.get(stall_controller_id)

        if not stall_controller and gate_stage_name != hazard.read_stage_name:
            alt_id = f"{pipe_prefix}PIPE_{gate_stage_name}_stall_ctrl"
            stall_controller = self.graph.nodes.get(alt_id)
            if stall_controller:
                stall_controller_id = alt_id

        is_new_controller = stall_controller is None

        if is_new_controller:
            # Create at gate_stage_name so later stalls at the same boundary
            # (e.g., memory hazards) can share this controller.
            stall_controller_id = f"{pipe_prefix}PIPE_{gate_stage_name}_stall_ctrl"

        stall_controller = self.hw_factory.stall_logic.create_or_get_stall_controller(
            controller_id=stall_controller_id,
            stage_name=gate_stage_name,
            pipeline_prefix=f'{pipe_prefix}PIPE' if pipe_prefix else 'PIPE',
            metadata={'pipeline_component': True, 'pipe_id': read_pipe_id}
        )

        if is_new_controller:
            print(f"  Created stall controller: {stall_controller_id}")
            if read_pipe_id is not None:
                print(f"    (pipeline-specific: pipe_id={read_pipe_id})")

            # Connect stall controller to pipeline registers for the NEXT stage
            # (the stage that the read stage feeds into)
            # When stalling Decode, we prevent data from advancing to Execute.
            # Pipeline registers are named PIPE_{stage}_{signal}_PIPE
            # For dual-issue: p0_PIPE_{stage}_{signal}_PIPE or p1_PIPE_{stage}_{signal}_PIPE
            # PIPE_Execute_* means "going into Execute stage", so these are Decode->Execute boundary

            # Find the next stage by looking at all pipeline registers and determining order
            # Extract unique stage names from pipeline register node IDs (for this pipeline)
            stage_names = set()
            for node_id, node in sorted(self.graph.nodes.items()):
                if (node.data.get('type') == 'pipeline_register' and
                    node_id.startswith(pipe_reg_pattern_prefix) and node_id.endswith('_PIPE')):
                    # Extract stage name: [p0_]PIPE_{stage}_{signal}_PIPE
                    # Remove prefix to get PIPE_{stage}_{signal}_PIPE, then split
                    stripped = node_id[len(pipe_prefix):] if pipe_prefix else node_id
                    parts = stripped.split('_')
                    if len(parts) >= 3:
                        stage_names.add(parts[1])

            # Try to order stages by their pipe_time (preferred) or uarch_time (fallback)
            # Use hazard.read_stage (the numeric time) directly rather than matching by name.
            # For pre-pipeline stages (gate_stage_name != read_stage_name), use the
            # gate stage's time so the gating logic targets the correct boundary.
            read_stage_time = hazard.read_stage
            stage_times = {}
            for stage in sorted(stage_names):
                for node_id, node in sorted(self.graph.nodes.items()):
                    # For dual-issue: p0_PIPE_{stage}_ or p1_PIPE_{stage}_
                    # For single-issue: PIPE_{stage}_
                    if (node.data.get('type') == 'pipeline_register' and
                        node_id.startswith(f'{pipe_prefix}PIPE_{stage}_') and node_id.endswith('_PIPE')):
                        # Use pipe_time for stage ordering, fall back to uarch_time
                        ptime = getattr(node, 'pipe_time', None)
                        if ptime is None:
                            ptime = node.uarch_time
                        if ptime is not None:
                            stage_times[stage] = ptime
                            break

            # For pre-pipeline stages, adjust read_stage_time to the gate stage's
            # time so that the gating logic targets the correct boundary.
            if gate_stage_name != hazard.read_stage_name and gate_stage_name in stage_times:
                read_stage_time = stage_times[gate_stage_name]
                print(f"  Adjusted read_stage_time to {read_stage_time} "
                      f"(gate stage '{gate_stage_name}')")

            # When stalling a stage due to a hazard:
            # 1. Stall the read stage and all earlier stages (gate their pipeline registers)
            #    - If Decode is stalled, gate Fetch->Decode and PC
            # 2. Insert a bubble (valid=0) into the next stage
            #    - If Decode is stalled, Execute gets a bubble
            stages_to_stall = []

            # Get write stage time for structural determination
            # Use pipe_time for stage comparison, fall back to uarch_time
            write_stage_time = None
            if hazard.write_stage_name:
                write_stage_time = stage_times.get(hazard.write_stage_name)

            # Gate pipeline registers based on hazard distance
            # With pipe_time semantics: pipeline registers have time of stage they feed INTO
            if read_stage_time is not None and write_stage_time is not None:
                if read_stage_time == write_stage_time:
                    # Same-stage hazard: read and write at same stage
                    # If we reach here, write-read-fwd is NOT enabled (would have been skipped earlier)
                    # Stall the stage at read_time to hold data entering this stage
                    for stage, time in sorted(stage_times.items()):
                        if time == read_stage_time:
                            stages_to_stall.append(stage)
                            print(f"  Stalling stage: {stage} (time={time}, same-stage hazard at time={read_stage_time})")
                else:
                    # Multi-stage hazard: stall stages before and including the read stage
                    # Gate stages where: time <= read_time
                    for stage, time in sorted(stage_times.items()):
                        if time <= read_stage_time:
                            stages_to_stall.append(stage)
                            print(f"  Stalling stage: {stage} (time={time}, read={read_stage_time} write={write_stage_time})")
            elif read_stage_time is not None:
                # Fallback: if we don't have write_stage_time, use old logic but with <= instead of <
                # This at least gates the stage at read_time
                for stage, time in sorted(stage_times.items()):
                    if time <= read_stage_time:
                        stages_to_stall.append(stage)
                        print(f"  Stalling stage: {stage} (time={time}, fallback logic)")
            else:
                # Final fallback: use the gate stage name
                stages_to_stall.append(gate_stage_name)
                print(f"  Stalling stage: {gate_stage_name} (name-based fallback)")

            # Find the stage to bubble (set valid=0)
            # This is the NEXT stage after the read stage
            # With new pipe_time semantics, pipeline registers have pipe_time = stage they feed INTO
            # So if read is at time N, we want the stage with time N+1
            bubble_stage_name = None
            if read_stage_time is not None:
                for stage, time in sorted(stage_times.items()):
                    if time == read_stage_time + 1:
                        bubble_stage_name = stage
                        break

            if bubble_stage_name:
                print(f"  Will insert bubble into: {pipe_prefix}{bubble_stage_name}")

                # Implement bubble injection: bubble_stage_valid = prev_valid AND NOT stall
                # Find the valid signal for the bubble stage (with pipeline prefix for dual-issue)
                bubble_stage_valid_id = f"{pipe_prefix}PIPE_{bubble_stage_name}_valid_PIPE"
                next_valid = self.graph.nodes.get(bubble_stage_valid_id)

                # For prev_valid, try to find the previous stage's valid signal
                # For 2-stage pipelines or first stage, use a constant 1
                prev_valid = None

                # First try to find the gate stage's valid signal (with pipeline prefix)
                # For pre-pipeline stages, gate_stage_name is the earliest pipeline stage.
                prev_stage_valid_id = f"{pipe_prefix}PIPE_{gate_stage_name}_valid_PIPE"
                if prev_stage_valid_id in self.graph.nodes:
                    prev_valid = self.graph.nodes[prev_stage_valid_id]
                else:
                    # Look for a stage at time immediately before bubble_stage
                    bubble_time = stage_times.get(bubble_stage_name)
                    if bubble_time is not None:
                        for stage, time in sorted(stage_times.items()):
                            if time == bubble_time - 1:
                                candidate_id = f"{pipe_prefix}PIPE_{stage}_valid_PIPE"
                                if candidate_id in self.graph.nodes:
                                    prev_valid = self.graph.nodes[candidate_id]
                                    break

                # If no previous valid found, use a constant (for first/only pipeline stage)
                if prev_valid is None:
                    for node_id, node in sorted(self.graph.nodes.items()):
                        if node_id.startswith('const_valid') or node_id == 'const_1':
                            prev_valid = node
                            break

                if prev_valid and next_valid:
                    # Create NOT gate for stall signal
                    not_stall_id = f"{stall_controller.id}_not"
                    not_stall = None
                    if not_stall_id not in self.graph.nodes:
                        not_stall = Node(not_stall_id, data={
                            'type': 'operation',
                            'operator': '!',
                            'name': not_stall_id,
                            'width': 1,
                            'bit_width': 1
                        })
                        self.graph.add_node(not_stall)
                        edge = Edge(stall_controller, not_stall, data={'type': 'operand'})
                        self.graph.add_edge(edge)
                        print(f"    Created NOT gate: {not_stall_id}")
                    else:
                        not_stall = self.graph.nodes[not_stall_id]

                    # Create AND gate: prev_valid AND NOT stall
                    # Include pipe prefix for dual-issue
                    and_id = f"{pipe_prefix}PIPE_{bubble_stage_name}_valid_and_not_stall"
                    and_node = Node(and_id, data={
                        'type': 'operation',
                        'operator': '&&',
                        'name': and_id,
                        'width': 1,
                        'bit_width': 1
                    })
                    self.graph.add_node(and_node)
                    print(f"    Created AND gate: {and_id}")

                    # Remove existing pipeline_input edge to next_valid
                    for edge in sorted(next_valid.incoming_edges, key=lambda e: (e.source.id, e.target.id)):
                        if edge.data.get('type') == 'pipeline_input':
                            self.graph.remove_edge(edge.id)
                            print(f"    Removed old pipeline_input edge to {bubble_stage_valid_id}")

                    # Connect prev_valid -> AND left operand
                    edge1 = Edge(prev_valid, and_node, data={
                        'type': 'operand',
                        'operand_index': 0
                    })
                    self.graph.add_edge(edge1)

                    # Connect NOT stall -> AND right operand
                    edge2 = Edge(not_stall, and_node, data={
                        'type': 'operand',
                        'operand_index': 1
                    })
                    self.graph.add_edge(edge2)

                    # Connect AND -> next_valid (pipeline_input)
                    edge3 = Edge(and_node, next_valid, data={
                        'type': 'pipeline_input',
                        'pipeline_component': True
                    })
                    self.graph.add_edge(edge3)
                    print(f"    Bubble injection: {bubble_stage_name}_valid = const AND NOT stall")

            connected_count = 0
            # Gate pipeline registers for stages BEFORE the read stage
            # Use pipe_prefix for dual-issue to only gate registers in the same pipeline
            for stage_name in sorted(stages_to_stall):
                stage_pattern = f"{pipe_prefix}PIPE_{stage_name}_"
                for node_id, node in sorted(self.graph.nodes.items()):
                    if (node.data.get('type') == 'pipeline_register' and
                        node_id.startswith(stage_pattern) and node_id.endswith('_PIPE')):
                        # Connect stall controller to this pipeline register
                        self.hw_factory.stall_logic.connect_controller_to_register(
                            controller_node=stall_controller,
                            pipeline_register=node,
                            metadata={'pipeline_component': True}
                        )
                        connected_count += 1
                        print(f"    Connected stall controller to {node_id}")

            # Note: We do NOT gate the bubble stage's data registers.
            # The bubble stage gets valid=0 (via bubble injection above), which
            # is sufficient to prevent architectural side effects.  Freezing the
            # bubble stage's data registers would also freeze write-enable signals,
            # which in shallow pipelines (where the bubble stage IS the write stage)
            # causes instructions to re-execute when the stall releases.

            # Gate ISA state elements at or before the read stage time.
            # This is done OUTSIDE the stages_to_stall loop because for 2-stage
            # pipelines there may be no earlier stages, but we still need to gate PC.
            #
            # For dual-issue: Only p0 stalls gate shared ISA state (like PC).
            # p1 stalls only affect p1's pipeline registers, not shared state.
            # PC advancement is handled separately by the PC advancement logic
            # which considers both p0_stalled and p1_stalled.
            #
            should_gate_shared_isa_state = (read_pipe_id is None or read_pipe_id == 0)

            if read_stage_time is not None and should_gate_shared_isa_state:
                # If designer specified which ISA states to gate, use those
                if self.isa_states_to_gate:
                    for isa_state_id in self.isa_states_to_gate:
                        isa_node = self.graph.nodes.get(isa_state_id)
                        if isa_node and isa_node.data.get('type') == 'isa_state':
                            isa_time = getattr(isa_node, 'pipe_time', None)
                            if isa_time is None:
                                isa_time = getattr(isa_node, 'uarch_time', 0)
                            if isa_time is not None and isa_time <= read_stage_time:
                                self.hw_factory.stall_logic.connect_controller_to_register(
                                    controller_node=stall_controller,
                                    pipeline_register=isa_node,
                                    metadata={'pipeline_component': True}
                                )
                                connected_count += 1
                                print(f"    Connected stall controller to {isa_state_id} (pipe_time={isa_time})")
                else:
                    # Auto-detect: find ISA state elements at pipe_time <= read_stage_time
                    for node_id, node in sorted(self.graph.nodes.items()):
                        if node.data.get('type') == 'isa_state':
                            node_time = getattr(node, 'pipe_time', None)
                            if node_time is None:
                                node_time = getattr(node, 'uarch_time', None)
                            if node_time is not None and node_time <= read_stage_time:
                                self.hw_factory.stall_logic.connect_controller_to_register(
                                    controller_node=stall_controller,
                                    pipeline_register=node,
                                    metadata={'pipeline_component': True}
                                )
                                connected_count += 1
                                print(f"    Connected stall controller to {node_id} (auto-detected, pipe_time={node_time})")
            elif read_stage_time is not None and read_pipe_id == 1:
                print(f"    Skipping shared ISA state gating (p1 stall doesn't gate shared state)")

            if connected_count > 0:
                print(f"  Connected stall controller to {connected_count} pipeline registers")
            else:
                # Fallback: try old naming scheme for backwards compatibility
                pipeline_reg_id = f"PIPE_{hazard.read_stage_name}_reg"
                pipeline_reg = self.graph.nodes.get(pipeline_reg_id)
                if pipeline_reg:
                    self.hw_factory.stall_logic.connect_controller_to_register(
                        controller_node=stall_controller,
                        pipeline_register=pipeline_reg,
                        metadata={'pipeline_component': True}
                    )
                    print(f"  Connected stall controller to pipeline register (legacy)")
                else:
                    print(f"  Warning: Could not find any pipeline registers for stage {gate_stage_name}")

        # Connect stall signal to stall controller
        self.hw_factory.stall_logic.connect_stall_to_controller(
            stall_node=stall_signal_node,
            controller_node=stall_controller
        )

        stall_id = stall_signal_node.id
        print(f"  Created stall logic: {stall_id}")

        return True

    def _find_forwarding_value_at_stage(self, stage_name: str, write_stage_num: int) -> Optional[Node]:
        """
        Find the value that would be written to RF from a given pipeline stage.

        For bypassing, we need the value that will eventually be written to the register file.
        This is typically the output of rf_write_data_mux at the appropriate pipeline stage.

        Args:
            stage_name: Name of the pipeline stage (e.g., 'Execute', 'Memory', 'Writeback')
            write_stage_num: The numeric stage number

        Returns:
            Node containing the forwarding value, or None if not found
        """
        # The forwarding value is what gets selected by rf_write_data_mux
        # At each stage, we need to find the pipelined version of this value

        # For ALU instructions, the value is the ALU result (e.g., add_res, sub_res)
        # For load instructions, the value is the memory read result (e.g., data)
        # The rf_write_data_mux selects among all these based on instruction enables

        # Find rf_write_data_mux output at this stage
        # This could be pipelined version of rf_write_data_mux or the mux itself

        # First try to find pipelined version of rf_write_data_mux
        pipelined_mux_patterns = [
            f"PIPE_{stage_name}_rf_write_data_mux_PIPE",
            f"PIPE_{stage_name}_PIPE_*_rf_write_data_mux_*",
        ]

        # Look for the rf_write_data_mux output at this stage
        for node_id, node in sorted(self.graph.nodes.items()):
            if 'rf_write_data_mux' in node_id and node.data.get('type') == 'pipeline_register':
                if node_id.startswith(f'PIPE_{stage_name}_'):
                    # Check if it's at the right depth - use pipe_time, fall back to uarch_time
                    ptime = getattr(node, 'pipe_time', None)
                    if ptime is None:
                        ptime = getattr(node, 'uarch_time', None)
                    if ptime == write_stage_num:
                        print(f"    Found pipelined rf_write_data_mux at stage {stage_name}: {node_id}")
                        return node

        # If not found, the rf_write_data_mux might not be pipelined
        # In this case, look at the stage's ALU results directly
        print(f"    No pipelined rf_write_data_mux found for stage {stage_name}, using direct results")
        return None

    def _build_stall_condition(self, hazard: DetectedHazard) -> Tuple[Optional[Node], Optional[str], Optional[Node]]:
        """
        Build the stall condition for any hazard type.

        Unified builder for indexed (2D) and non-indexed (1D/enable-only) hazards.
        The algorithm is the same skeleton for all types:
            [optional_comparator] && write_enable && stage_valid

        For indexed hazards, a comparator (idx == read_idx) is created and AND'd
        with the write enable. For non-indexed hazards, only write_enable && stage_valid
        is used. The write-enable and read-enable discovery strategies differ between
        indexed and non-indexed paths, but the final AND-chain assembly is shared.

        Returns:
            Tuple of (stall_signal_node, write_stage_name, read_enable_node)
            stall_signal_node may be None if no valid stall condition can be built.
        """
        needs_comparison = hazard.is_indexed and hazard.resolution != HazardResolutionStrategy.STALL_ENABLE_ONLY

        # ── Step 1: Index comparison (indexed hazards only) ────────────────
        comp_node = None
        anchor_node = None  # Pipeline-depth anchor for indexed enable discovery

        if needs_comparison:
            # Find the ACTUAL index node at the write location by tracing from the original
            # index node through pipeline registers to find which one feeds the write
            actual_write_index_node = self._find_pipelined_index_at_write(hazard)

            if not actual_write_index_node:
                print(f"  Warning: Could not find actual write index node, using original")
                actual_write_index_node = hazard.write_index_node

            # For in-flight hazards (where the hazard's write stage is earlier than the
            # actual RF write stage), use the hazard's write_index_node directly.
            # This compares against the rd at the correct intermediate stage and ensures
            # the write enable is also found at the correct depth.
            if hazard.write_index_node and hazard.write_index_node.data.get('type') == 'pipeline_register':
                hazard_depth = self._count_pipe_depth(hazard.write_index_node.id)
                actual_depth = self._count_pipe_depth(actual_write_index_node.id)
                if hazard_depth < actual_depth:
                    actual_write_index_node = hazard.write_index_node
                    print(f"  Using intermediate stage index: {actual_write_index_node.id} (depth {hazard_depth} vs {actual_depth})")

            # Create comparator node for index match
            comp_id = f"stall_{hazard.resource}_{hazard.write_index_name}_{hazard.read_index_name}_s{hazard.write_stage}_s{hazard.read_stage}_cmp"
            display_name = f'{hazard.write_index_name}=={hazard.read_index_name}'

            comp_node = self.hw_factory.comparators.create_index_comparator(
                comp_id=comp_id,
                left_node=actual_write_index_node,
                right_node=hazard.read_index_node,
                operator='==',
                display_name=display_name,
                metadata={
                    'hazard_type': hazard.hazard_type,
                    'resolution': 'stall',
                    'target_stage': hazard.read_stage
                }
            )
            anchor_node = actual_write_index_node

            print(f"  Connected write index: {actual_write_index_node.id}")
            print(f"  Connected read index: {hazard.read_index_node.id}")
        else:
            print(f"  Building non-comparison stall condition for {hazard.resource}")

        # ── Step 2: Write enable discovery ─────────────────────────────────
        write_enable_node = None
        stage_enable_nodes = []  # Only populated by indexed path

        if needs_comparison:
            # Indexed path: depth-aware discovery anchored to the write index node
            write_enable_node, stage_enable_nodes = self._find_indexed_write_enable(hazard, anchor_node)
        else:
            # Non-indexed path: pattern-based discovery via _find_or_create_write_enable
            write_enable_node, actual_write_stage = self._find_or_create_write_enable_for_hazard(hazard)

        # ── Step 3: Read enable discovery ──────────────────────────────────
        read_enable_node = None

        if needs_comparison:
            # Indexed path: look for {resource}_{read_index}_rd_enable
            read_enable_id = f"{hazard.resource}_{hazard.read_index_name}_rd_enable"
            if read_enable_id in self.graph.nodes:
                read_enable_node = self.graph.nodes[read_enable_id]
                print(f"  Found read enable signal: {read_enable_id}")
            else:
                print(f"  No read enable signal found ({read_enable_id}) - all instructions may use this register")
        else:
            # Non-indexed path: find via helper
            read_enable_node = self._find_or_create_read_enable_for_hazard(hazard)

        # ── Step 4: Stage valid discovery ──────────────────────────────────
        write_stage_valid_node = None
        write_stage_name = None

        if needs_comparison:
            # Extract stage name from the anchor node's pipelined ID
            write_stage_name, write_stage_valid_node = self._find_stage_valid_from_anchor(anchor_node)
        else:
            # Use hazard's write_stage_name directly, with dual-issue prefix
            read_pipe_id = getattr(hazard.read_access_node, 'pipe_id', None) if hazard.read_access_node else None
            pipe_prefix = f"p{read_pipe_id}_" if read_pipe_id is not None else ""

            effective_write_stage = actual_write_stage if (not needs_comparison and actual_write_stage) else hazard.write_stage_name
            write_stage_name = effective_write_stage

            write_stage_valid_id = f"{pipe_prefix}PIPE_{effective_write_stage}_valid_PIPE"
            write_stage_valid_node = self.graph.nodes.get(write_stage_valid_id)

            if not needs_comparison and actual_write_stage and effective_write_stage != hazard.write_stage_name:
                print(f"    Using effective write stage: {effective_write_stage} (hazard reported: {hazard.write_stage_name})")

        # ── Step 5: Build the AND chain ────────────────────────────────────
        # Assemble: [comparator] && effective_enable && [stage_valid]
        #
        # For indexed hazards, OR multiple stage enables if needed, then AND
        # with comparator and stage valid.
        # For non-indexed hazards, AND write_enable with stage valid.

        # Determine the effective write enable (OR multiple stage enables for indexed path)
        effective_enable_node = write_enable_node
        if stage_enable_nodes:
            if len(stage_enable_nodes) == 1:
                effective_enable_node = stage_enable_nodes[0]
            else:
                stall_id_base = self._stall_id(hazard)
                or_enable_id = f"{stall_id_base}_combined_enable"
                effective_enable_node = self._create_or_node(or_enable_id, stage_enable_nodes)
                print(f"  Created OR of {len(stage_enable_nodes)} enables: {or_enable_id}")

        stall_id = self._stall_id(hazard)

        if comp_node is not None:
            # Indexed: comp && enable && valid
            return self._and_chain_indexed(hazard, comp_node, effective_enable_node, write_stage_valid_node,
                                           stall_id, read_enable_node, write_stage_name)
        else:
            # Non-indexed: enable && valid (or just valid if no enable)
            return self._and_chain_non_indexed(hazard, effective_enable_node, write_stage_valid_node,
                                               stall_id, read_enable_node, write_stage_name)

    def _stall_id(self, hazard: DetectedHazard) -> str:
        """Generate a base stall ID string for a hazard."""
        if hazard.is_indexed and hazard.resolution != HazardResolutionStrategy.STALL_ENABLE_ONLY:
            return f"stall_{hazard.resource}_{hazard.write_index_name}_{hazard.read_index_name}_s{hazard.write_stage}_s{hazard.read_stage}"
        return f"stall_{hazard.resource}_s{hazard.write_stage}_s{hazard.read_stage}"

    def _find_indexed_write_enable(self, hazard: DetectedHazard, anchor_node: Node) -> Tuple[Optional[Node], list]:
        """
        Find write enable for an indexed hazard using depth-aware discovery.

        Walks the combined_write_enable's predecessors, extracts their core signal
        names, then finds pipelined versions at the same pipeline depth as the
        anchor node (the write index).

        Returns:
            Tuple of (fallback_write_enable_node, stage_enable_nodes_list)
        """
        combined_write_enable_name = hazard.write_access_node.data.get('combined_write_enable')
        if not combined_write_enable_name:
            combined_write_enable_name = f"{hazard.resource}_write_enable"

        write_enable_predecessors = []
        if combined_write_enable_name in self.graph.nodes:
            we_node = self.graph.nodes[combined_write_enable_name]
            for edge in we_node.incoming_edges:
                src = edge.source
                if 'valid' in src.id.lower():
                    continue
                core_name = self._extract_core_name(src.id)
                write_enable_predecessors.append(core_name)
            print(f"  Write enable predecessors (core names): {write_enable_predecessors}")

        target_depth = self._count_pipe_depth(anchor_node.id)
        print(f"  Target pipeline depth: {target_depth}")

        # Determine the pipe prefix from the anchor node (e.g., "p0_" or "p1_")
        _pipe_prefix_match = re.match(r'^(p\d+_)', anchor_node.id)
        write_pipe_prefix = _pipe_prefix_match.group(1) if _pipe_prefix_match else ''

        stage_enable_nodes = []
        for pred_base in write_enable_predecessors:
            best_match = None
            for node_id, node in sorted(self.graph.nodes.items()):
                if node.data.get('type') == 'pipeline_register':
                    if pred_base in node_id and self._count_pipe_depth(node_id) == target_depth:
                        if write_pipe_prefix and node_id.startswith(write_pipe_prefix):
                            best_match = node
                            break  # Exact prefix match
                        elif not best_match:
                            best_match = node
            if best_match:
                stage_enable_nodes.append(best_match)
                print(f"  Found stage enable: {best_match.id}")

        write_enable_node = None
        if stage_enable_nodes:
            print(f"  Using {len(stage_enable_nodes)} stage-specific enable(s)")
            write_enable_node = stage_enable_nodes[0] if len(stage_enable_nodes) == 1 else None
        else:
            gated_enable_name = f"{combined_write_enable_name}_valid_gated"
            if gated_enable_name in self.graph.nodes:
                write_enable_node = self.graph.nodes[gated_enable_name]
                print(f"  Using existing {gated_enable_name} (pipe_time={getattr(write_enable_node, 'pipe_time', None)})")
            elif combined_write_enable_name in self.graph.nodes:
                write_enable_node = self.graph.nodes[combined_write_enable_name]
                print(f"  Using existing {combined_write_enable_name} (pipe_time={getattr(write_enable_node, 'pipe_time', None)})")

        return write_enable_node, stage_enable_nodes

    def _find_stage_valid_from_anchor(self, anchor_node: Node) -> Tuple[Optional[str], Optional[Node]]:
        """
        Find the stage valid signal at the same pipeline stage as an anchor node.

        Parses the anchor node's ID to extract the stage name, handling
        dual-issue prefixes (p0_, p1_, p2_, etc.).

        Returns:
            Tuple of (write_stage_name, stage_valid_node)
        """
        write_stage_name = None
        check_id = anchor_node.id
        pipe_prefix = ''
        prefix_match = re.match(r'^(p\d+_)', check_id)
        if prefix_match:
            pipe_prefix = prefix_match.group(1)
            check_id = check_id[len(pipe_prefix):]
        if check_id.startswith('PIPE_'):
            parts = check_id.split('_')
            if len(parts) >= 2:
                write_stage_name = parts[1]

        if write_stage_name:
            # Try with dual-issue prefix first, then without
            valid_signal_id = f"{pipe_prefix}PIPE_{write_stage_name}_valid_PIPE"
            if valid_signal_id in self.graph.nodes:
                print(f"  Found write stage valid: {valid_signal_id}")
                return write_stage_name, self.graph.nodes[valid_signal_id]
            valid_signal_id_no_prefix = f"PIPE_{write_stage_name}_valid_PIPE"
            if valid_signal_id_no_prefix in self.graph.nodes:
                print(f"  Found write stage valid: {valid_signal_id_no_prefix}")
                return write_stage_name, self.graph.nodes[valid_signal_id_no_prefix]
            print(f"  Warning: Could not find valid signal for write stage: {valid_signal_id}")
        else:
            print(f"  Warning: Could not extract stage name from anchor node: {anchor_node.id}")

        return write_stage_name, None

    def _and_chain_indexed(self, hazard, comp_node, effective_enable_node, write_stage_valid_node,
                           stall_id, read_enable_node, write_stage_name):
        """Build AND chain for indexed hazard: comp && enable && valid."""
        if effective_enable_node:
            # comp && enable
            and_with_enable_id = f"{stall_id}_with_enable"
            and_with_enable = Node(and_with_enable_id, data={
                'type': 'operation', 'operator': '&&',
                'name': and_with_enable_id, 'bit_width': 1
            })
            self.graph.add_node(and_with_enable)
            self.graph.add_edge(Edge(comp_node, and_with_enable, data={'type': 'left_operand', 'position': 'left'}))
            self.graph.add_edge(Edge(effective_enable_node, and_with_enable, data={'type': 'right_operand', 'position': 'right'}))

            # ... && valid
            if write_stage_valid_node:
                and_node = Node(stall_id, data={
                    'type': 'operation', 'operator': '&&', 'name': stall_id,
                    'display_name': f'Stall {hazard.read_stage_name} ({hazard.write_index_name}=={hazard.read_index_name})',
                    'hazard_type': hazard.hazard_type, 'resolution': 'stall',
                    'target_stage': hazard.read_stage, 'bit_width': 1
                })
                self.graph.add_node(and_node)
                self.graph.add_edge(Edge(and_with_enable, and_node, data={'type': 'left_operand', 'position': 'left'}))
                self.graph.add_edge(Edge(write_stage_valid_node, and_node, data={'type': 'right_operand', 'position': 'right'}))
                print(f"  Created stall logic with write enable and valid check: {stall_id}")
                return and_node, write_stage_name, read_enable_node
            else:
                print(f"  Created stall logic with write enable check (no valid): {and_with_enable_id}")
                return and_with_enable, write_stage_name, read_enable_node
        else:
            print(f"  Warning: No write enable found, using simple index comparison")
            return comp_node, write_stage_name, read_enable_node

    def _and_chain_non_indexed(self, hazard, write_enable_node, write_stage_valid_node,
                               stall_id, read_enable_node, write_stage_name):
        """Build AND chain for non-indexed hazard: enable && valid."""
        if write_enable_node and write_stage_valid_node:
            stall_with_enable_id = f"{stall_id}_with_enable"
            stall_with_enable = Node(stall_with_enable_id, data={
                'type': 'operation', 'operator': '&&',
                'name': stall_with_enable_id,
                'display_name': f'Stall on {hazard.resource} (with enable)',
                'bit_width': 1
            })
            self.graph.add_node(stall_with_enable)
            self.graph.add_edge(Edge(write_enable_node, stall_with_enable, data={'type': 'left_operand', 'position': 'left'}))
            self.graph.add_edge(Edge(write_stage_valid_node, stall_with_enable, data={'type': 'right_operand', 'position': 'right'}))
            print(f"    Created stall_with_enable: {stall_with_enable_id}")
            return stall_with_enable, write_stage_name, read_enable_node

        elif write_stage_valid_node:
            pipe_prefix = ""
            read_pipe_id = getattr(hazard.read_access_node, 'pipe_id', None) if hazard.read_access_node else None
            if read_pipe_id is not None:
                pipe_prefix = f"p{read_pipe_id}_"
            write_stage_valid_id = f"{pipe_prefix}PIPE_{write_stage_name}_valid_PIPE"
            print(f"    WARNING: Using write stage valid as stall (conservative): {write_stage_valid_id}")
            return write_stage_valid_node, write_stage_name, read_enable_node

        else:
            stall_node = Node(stall_id, data={
                'type': 'constant', 'value': 0, 'bit_width': 1
            })
            self.graph.add_node(stall_node)
            print(f"    Warning: No write enable or stage valid found, created constant 0 stall")
            return stall_node, write_stage_name, read_enable_node

    def _find_or_create_write_enable_for_hazard(self, hazard: DetectedHazard) -> Tuple[Optional[Node], Optional[str]]:
        """Find or create a write enable signal for a non-indexed ISA state hazard."""
        return self._find_or_create_write_enable(hazard)

    def _find_or_create_read_enable_for_hazard(self, hazard: DetectedHazard) -> Optional[Node]:
        """Find or create a read enable signal for a non-indexed ISA state hazard."""
        return self._find_or_create_read_enable(hazard)

    def _get_load_instructions(self) -> Set[str]:
        """Get set of load instruction names that need stalling (not bypassing)."""
        return {'lb', 'lh', 'lw', 'lbu', 'lhu'}

    def _is_load_use_hazard(self, hazard: DetectedHazard) -> bool:
        """
        Check if this hazard requires stalling because it's a load-use hazard.

        Load-use hazards occur when a load instruction is followed by an instruction
        that uses the loaded value. The loaded value isn't available until after the
        memory access completes, so we can't forward it in time and must stall.

        For a 5-stage pipeline:
        - Load in Execute stage: can't forward (value not computed yet)
        - Load in Memory stage: can forward (value available after memory read)

        Returns:
            True if this is a load-use hazard requiring a stall
        """
        # Check if the hazard distance is 1 (immediate dependency)
        # and if loads are involved in the producing stage
        # For load-use, we need to check if the write comes from a load instruction
        # and the load is only 1 stage ahead (so value isn't ready yet)

        # Get the forwarding distance
        distance = hazard.get_forwarding_distance()

        if distance <= 1:
            # Check if any load instruction enables are active at this stage
            # This is a heuristic - proper implementation would track instruction types
            # For now, we'll handle load-use hazards by detecting memory stage involvement
            if self.pipeline_config:
                memory_stage = self.pipeline_config.memory_stage
                # If the write is at the memory stage boundary (distance 1 from read)
                # and involves memory operations, it's likely a load-use
                if 'Memory' in hazard.write_stage_name:
                    # Check if this is the stage right after Execute (where loads compute address)
                    # For simplicity, assume distance 1 hazards from memory stage need stalling
                    return True

        return False

    # =====================================================================
    # Structural Bypassing Infrastructure
    # =====================================================================
    # These methods implement a fully structural approach to bypass/forwarding
    # that traces the graph structure rather than relying on hardcoded names.

    def _get_one_hot_mux_inputs(self, mux_node: Node) -> List[Tuple[Node, Node, int]]:
        """
        Extract all inputs from a one-hot multiplexer.

        Returns:
            List of (data_node, enable_node, index) tuples
        """
        # Collect data inputs with their indices
        data_by_index = {}
        for edge in mux_node.incoming_edges:
            if edge.data.get('type') == 'mux_input':
                idx = edge.data.get('input_index', 0)
                data_by_index[idx] = edge.source

        # Collect select/enable inputs with their indices
        select_by_index = {}
        for edge in mux_node.incoming_edges:
            if edge.data.get('type') == 'mux_select':
                idx = edge.data.get('select_index', 0)
                select_by_index[idx] = edge.source

        # Pair them up
        result = []
        for idx in sorted(data_by_index.keys()):
            if idx in select_by_index:
                result.append((data_by_index[idx], select_by_index[idx], idx))

        return result

    def _trace_back_to_compute_source(self, node: Node, visited: Optional[set] = None) -> Tuple[Node, Optional[str]]:
        """
        Trace a node backward through pipeline registers and assignments
        to find where the value was actually computed.

        Returns:
            (source_node, source_stage) where source_stage is the pipeline stage
            name where the value originates, or None if not in a pipeline stage.
        """
        if visited is None:
            visited = set()

        if node.id in visited:
            return node, self._get_node_stage(node)
        visited.add(node.id)

        node_type = node.data.get('type')

        # If this is a pipeline register, trace back through pipeline_input edge
        if node_type == 'pipeline_register':
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'pipeline_input':
                    return self._trace_back_to_compute_source(edge.source, visited)
            # No pipeline_input found, this is the source
            return node, self._get_node_stage(node)

        # If this is an intermediate node with single assignment input, continue tracing
        # But stop if it's a computation (operation, memory read, etc.)
        # Include 'var' so we trace through nodes like ret_addr (jal/jalr return
        # address) which is a var assigned from a pipelined pc_add_4 value.
        if node_type in ('wire', 'signal', 'var', None):
            # Check incoming edges for single operand/assignment
            assignment_sources = []
            for edge in node.incoming_edges:
                if edge.data.get('type') in ('assignment', 'operand'):
                    assignment_sources.append(edge.source)

            # If exactly one assignment source and it's a pipe reg, trace through
            if len(assignment_sources) == 1:
                source = assignment_sources[0]
                if source.data.get('type') == 'pipeline_register':
                    return self._trace_back_to_compute_source(source, visited)

        # This node is a compute source (operation, memory, etc.) or we can't trace further
        return node, self._get_node_stage(node)

    def _get_node_stage(self, node: Node) -> Optional[str]:
        """
        Determine which pipeline stage a node belongs to.

        Returns stage name (e.g., 'Memory', 'Execute') or None.

        Uses pipe_time (preferred) or uarch_time (fallback) to determine stage.
        pipe_time for all nodes (including pipeline registers) represents the
        stage where the value is available/used.
        """
        # Use pipe_time for stage determination, fall back to uarch_time
        ptime = getattr(node, 'pipe_time', None)
        if ptime is None:
            ptime = getattr(node, 'uarch_time', None)
        if ptime is None:
            return None
        if not self.pipeline_config:
            return None

        if not isinstance(ptime, (int, float)):
            return None

        # pipe_time directly represents the stage index for all nodes
        # (pipeline registers have pipe_time set to their output stage)
        output_time = int(ptime)

        if 0 <= output_time < len(self.pipeline_config.stage_names):
            return self.pipeline_config.stage_names[output_time]

        return None

    def _find_write_data_mux(self, hazard: DetectedHazard) -> Optional[Node]:
        """
        Find the write data mux for the ISA state being written.

        Traces from the write access node to find the mux feeding it.
        """
        # The write access node (e.g., rf[rd]_wr) should have a data edge from the mux
        for edge in hazard.write_access_node.incoming_edges:
            edge_type = edge.data.get('type')
            # Look for data/value edges, not index or enable edges
            if edge_type in ('operand', 'assignment', 'shared_array_data'):
                source = edge.source
                if source.data.get('type') == 'multiplexer':
                    return source

        # Try to find by common naming pattern as fallback
        resource = hazard.resource
        mux_candidates = [f'{resource}_write_data_mux', f'rf_write_data_mux']
        for mux_id in mux_candidates:
            if mux_id in self.graph.nodes:
                return self.graph.nodes[mux_id]

        return None

    def _find_write_index_mux(self, hazard: DetectedHazard) -> Optional[Node]:
        """
        Find the write index/address mux for the ISA state being written.

        Traces from the write access node to find the mux providing the write address.
        """
        # The write access node should have an array_index edge from the index mux
        for edge in hazard.write_access_node.incoming_edges:
            if edge.data.get('type') == 'array_index':
                source = edge.source
                if source.data.get('type') == 'multiplexer':
                    return source
                # The index might come from a pipelined mux
                # Trace back to find the mux
                traced, _ = self._trace_back_to_compute_source(source)
                if traced.data.get('type') == 'multiplexer':
                    return traced

        # Try common naming pattern
        resource = hazard.resource
        mux_candidates = [f'{resource}_write_addr_mux', f'rf_write_addr_mux']
        for mux_id in mux_candidates:
            if mux_id in self.graph.nodes:
                return self.graph.nodes[mux_id]

        return None

    def _build_forwardable_values_by_stage(self, hazard: DetectedHazard) -> Dict[str, List[Tuple[Node, Node, Node]]]:
        """
        Build a mapping of stage -> forwardable values by tracing the write muxes.

        For each input to the write data mux:
        1. Trace the data value back to its compute source
        2. Find the corresponding write index at the same mux input
        3. Trace the write index back similarly
        4. Group by the stage where the data value is computed

        Returns:
            Dict mapping stage_name -> list of (data_node, enable_node, write_index_node)
            where each node is at the appropriate pipeline depth for that stage.
        """
        write_data_mux = self._find_write_data_mux(hazard)
        write_index_mux = self._find_write_index_mux(hazard)

        if not write_data_mux:
            print(f"    Could not find write data mux for {hazard.resource}")
            return {}

        # Get inputs from write data mux: (data_node, enable_node, index)
        data_mux_inputs = self._get_one_hot_mux_inputs(write_data_mux)

        # Get inputs from write index mux if available: (index_node, enable_node, idx)
        index_mux_inputs = {}
        if write_index_mux:
            for idx_node, enable_node, idx in self._get_one_hot_mux_inputs(write_index_mux):
                index_mux_inputs[idx] = (idx_node, enable_node)

        # Build stage -> values mapping
        values_by_stage: Dict[str, List[Tuple[Node, Node, Node]]] = {}

        for data_node, enable_node, mux_idx in data_mux_inputs:
            # Trace data value back to its compute source
            compute_source, compute_stage = self._trace_back_to_compute_source(data_node)

            if not compute_stage:
                # Try to get stage from the data node itself
                compute_stage = self._get_node_stage(data_node)

            if not compute_stage:
                print(f"      Could not determine stage for {data_node.id}")
                continue

            # Find corresponding write index
            write_index_node = None
            if mux_idx in index_mux_inputs:
                write_index_node, _ = index_mux_inputs[mux_idx]
            else:
                # Try to find pipelined version of write index at this stage
                # by matching enable signals
                write_index_node = self._find_write_index_at_stage(hazard, compute_stage, enable_node)

            if not write_index_node:
                print(f"      Could not find write index for mux input {mux_idx}")
                continue

            # Find the pipelined versions at this stage
            # The data value at the mux is at Writeback; we need versions at compute_stage
            data_at_stage = self._find_pipelined_version_at_stage(data_node, compute_stage)
            enable_at_stage = self._find_pipelined_version_at_stage(enable_node, compute_stage)
            index_at_stage = self._find_pipelined_version_at_stage(write_index_node, compute_stage)

            if not data_at_stage:
                # The compute source IS at this stage
                data_at_stage = compute_source

            if not enable_at_stage:
                enable_at_stage = enable_node

            if not index_at_stage:
                index_at_stage = write_index_node

            # Add to stage mapping
            if compute_stage not in values_by_stage:
                values_by_stage[compute_stage] = []

            values_by_stage[compute_stage].append((data_at_stage, enable_at_stage, index_at_stage))

        return values_by_stage

    def _find_write_index_at_stage(self, hazard: DetectedHazard, stage_name: str,
                                   enable_node: Node) -> Optional[Node]:
        """
        Find the write index node at a specific stage.

        Falls back to tracing from the hazard's write_index_node.
        """
        # First try: find pipelined version of the original write index
        pipelined = self._find_pipelined_at_stage(hazard.write_index_node, stage_name)
        if pipelined:
            return pipelined

        # Second try: look for a node that matches the stage pattern
        # and is connected to similar enables
        return None

    def _find_pipelined_version_at_stage(self, node: Node, target_stage: str) -> Optional[Node]:
        """
        Find the version of a node that exists at a specific pipeline stage.

        Traces forward through pipeline registers to find the version at target_stage.
        """
        # Check if node is already at target stage
        node_stage = self._get_node_stage(node)
        if node_stage == target_stage:
            return node

        # Trace forward through pipeline outputs
        current = node
        visited = set()

        while current and current.id not in visited:
            visited.add(current.id)

            for edge in current.outgoing_edges:
                if edge.data.get('type') == 'pipeline_input':
                    next_node = edge.target
                    next_stage = self._get_node_stage(next_node)
                    if next_stage == target_stage:
                        return next_node
                    current = next_node
                    break
            else:
                # No more pipeline stages
                break

        return None

    def _find_pipelined_at_stage(self, node: Node, target_stage: str) -> Optional[Node]:
        """
        Find a pipelined version of node at the target stage by searching the graph.
        """
        # Look for nodes that reference this node's base name at the target stage
        base_name = node.id.replace('_PIPE', '').split('_')[-1]

        for node_id, candidate in sorted(self.graph.nodes.items()):
            if target_stage in node_id and base_name in node_id:
                if candidate.data.get('type') == 'pipeline_register':
                    return candidate

        return None

    def _get_stage_index(self, stage_name: str) -> int:
        """Get numeric index for a stage name. Lower index = earlier stage."""
        if self.pipeline_config:
            try:
                return self.pipeline_config.stage_names.index(stage_name)
            except ValueError:
                pass

        # Fallback for standard MIPS/RISC-V stages
        standard_stages = ['Fetch', 'Decode', 'Execute', 'Memory', 'Writeback']
        try:
            return standard_stages.index(stage_name)
        except ValueError:
            return -1

    def _find_forwarding_value_mux_at_stage(self, stage_name: str) -> Optional[Node]:
        """
        Find or create a forwarding value mux at the given pipeline stage.

        Uses structural tracing from the write data mux to find all values
        that are computed BEFORE this stage (so they're available here).

        Values computed AT or AFTER this stage cannot be forwarded from here.
        """
        mux_id = f"forward_data_{stage_name}"

        # Check if we already created this mux
        if mux_id in self.graph.nodes:
            return self.graph.nodes[mux_id]

        # We need a hazard context to find the write mux
        # For now, try to find the write data mux directly
        write_data_mux = self.graph.nodes.get('rf_write_data_mux')
        if not write_data_mux:
            print(f"    Could not find rf_write_data_mux")
            return None

        # Get all inputs from the write data mux
        data_mux_inputs = self._get_one_hot_mux_inputs(write_data_mux)

        if not data_mux_inputs:
            print(f"    No inputs found in write data mux")
            return None

        # Get target stage index
        target_stage_idx = self._get_stage_index(stage_name)

        # Find values that are computed BEFORE the target stage
        # (so the result is available in target_stage's pipeline register)
        result_nodes = []
        unavailable_enables = []  # Track enables for values not available at this stage

        for data_node, enable_node, mux_idx in data_mux_inputs:
            # Trace back to find compute source and its stage
            compute_source, compute_stage = self._trace_back_to_compute_source(data_node)

            compute_stage_idx = self._get_stage_index(compute_stage) if compute_stage else -1

            # Only include values computed BEFORE the target stage
            # Values computed at Execute are available at Memory (target_stage_idx > compute_stage_idx)
            if compute_stage_idx >= 0 and compute_stage_idx < target_stage_idx:
                # Find the pipelined data value at target stage
                debug_trace = (mux_idx == 0)
                data_at_stage = self._find_pipelined_version_at_stage_by_tracing(data_node, stage_name, debug=debug_trace)
                enable_at_stage = self._find_pipelined_version_at_stage_by_tracing(enable_node, stage_name, debug=False)

                if mux_idx < 3:  # Debug output
                    print(f"      Input {mux_idx}: AVAILABLE at {stage_name}")
                    print(f"        data_node={data_node.id} (type={data_node.data.get('type')})")
                    print(f"        compute_source={compute_source.id}, compute_stage={compute_stage} (idx={compute_stage_idx})")
                    print(f"        data_at_stage={data_at_stage.id if data_at_stage else None}")
                    # Show incoming edges for debugging
                    if mux_idx == 0:
                        print(f"        data_node.incoming_edges ({len(data_node.incoming_edges)}):")
                        for e in list(data_node.incoming_edges)[:5]:
                            print(f"          {e.source.id} -[{e.data.get('type')}]-> {e.target.id}")

                if data_at_stage and enable_at_stage:
                    result_nodes.append((data_at_stage, enable_at_stage, f"input_{mux_idx}"))
            else:
                # Value not available at this stage - need to track for stalling
                enable_at_stage = self._find_pipelined_version_at_stage_by_tracing(enable_node, stage_name)
                if enable_at_stage:
                    unavailable_enables.append(enable_at_stage)

                if mux_idx < 3:  # Debug output
                    print(f"      Input {mux_idx}: NOT available at {stage_name}")
                    print(f"        compute_source={compute_source.id}, compute_stage={compute_stage} (idx={compute_stage_idx})")

        # Store unavailable enables for stall generation
        self._unavailable_at_stage = getattr(self, '_unavailable_at_stage', {})
        self._unavailable_at_stage[stage_name] = unavailable_enables

        if not result_nodes:
            print(f"    No forwardable values at stage {stage_name}")
            return None

        # Infer data width from result nodes (use first available, default 32)
        data_width = 32
        for data_node, enable_node, label in result_nodes:
            node_width = data_node.data.get('bit_width')
            if node_width:
                data_width = node_width
                break

        # Create the forwarding value mux
        mux_data = {
            'type': 'multiplexer',
            'name': mux_id,
            'display_name': f'Forward Data Mux ({stage_name})',
            'num_inputs': len(result_nodes),
            'operation': 'one_hot_select',
            'bit_width': data_width,
            'data_width': data_width,
            'output_width': data_width,
            'default_value': f"{data_width}'b0"
        }
        mux_node = Node(mux_id, mux_data)

        # Set pipe_time and uarch_time from a node at this stage
        for node_id, node in sorted(self.graph.nodes.items()):
            if f"PIPE_{stage_name}_valid_PIPE" == node_id:
                mux_node.pipe_time = getattr(node, 'pipe_time', None)
                mux_node.uarch_time = getattr(node, 'uarch_time', None)
                break

        self.graph.add_node(mux_node)

        # Connect all result values to the mux
        for i, (data_node, enable_node, label) in enumerate(result_nodes):
            data_edge = Edge(data_node, mux_node, data={
                'type': 'mux_input',
                'input_index': i,
                'source_label': label
            })
            self.graph.add_edge(data_edge)

            sel_edge = Edge(enable_node, mux_node, data={
                'type': 'mux_select',
                'select_index': i
            })
            self.graph.add_edge(sel_edge)

        available_count = len(result_nodes)
        unavailable_count = len(unavailable_enables)
        print(f"    Created forwarding mux {mux_id} with {available_count} inputs ({unavailable_count} unavailable, need stall)")
        return mux_node

    def _find_pipelined_version_at_stage_by_tracing(self, node: Node, target_stage: str, debug: bool = False) -> Optional[Node]:
        """
        Find the pipelined version of a node at the target stage by tracing
        backward through pipeline registers.

        The node at the write mux is at the final stage; we trace back to find
        the version at an earlier stage.
        """
        # First check if node itself is at target stage
        node_stage = self._get_node_stage(node)
        if node_stage == target_stage:
            if debug:
                print(f"        [TRACE] Already at target stage: {node.id}")
            return node

        if debug:
            print(f"        [TRACE] {node.id} (stage={node_stage}) -> target {target_stage}")

        # Trace backward through pipeline_input edges
        current = node
        visited = set()

        while current and current.id not in visited:
            visited.add(current.id)

            current_stage = self._get_node_stage(current)
            if debug:
                print(f"          current={current.id}, stage={current_stage}, type={current.data.get('type')}")

            if current_stage == target_stage:
                if debug:
                    print(f"          FOUND at target stage!")
                return current

            # If this is a pipeline register, trace back through pipeline_input
            if current.data.get('type') == 'pipeline_register':
                found_input = False
                for edge in current.incoming_edges:
                    if edge.data.get('type') == 'pipeline_input':
                        if debug:
                            print(f"          -> following pipeline_input to {edge.source.id}")
                        current = edge.source
                        found_input = True
                        break
                if not found_input:
                    if debug:
                        print(f"          No pipeline_input edge found, stopping")
                    break
            else:
                # For non-pipeline nodes, look for single incoming assignment
                found = False
                for edge in current.incoming_edges:
                    if edge.data.get('type') in ('assignment', 'operand'):
                        if edge.source.data.get('type') == 'pipeline_register':
                            if debug:
                                print(f"          -> following {edge.data.get('type')} to pipeline reg {edge.source.id}")
                            current = edge.source
                            found = True
                            break
                if not found:
                    if debug:
                        print(f"          No assignment/operand to pipeline reg found, stopping")
                    break

        if debug:
            print(f"          FAILED to find target stage")
        return None

    def _create_forwarding_condition(self, hazard: DetectedHazard, stage_name: str,
                                       unavailable_enables: Optional[List[Node]] = None) -> Optional[Node]:
        """
        Create the forwarding condition for a given hazard and stage.

        Condition: (write_addr_at_stage == read_index) && rf_write_enable_at_stage && stage_valid
                   && NOT(any_unavailable_enable)

        The unavailable_enables parameter contains enables for values that are NOT available
        at this stage (e.g., load enables when forwarding from Memory stage, since loads
        are computed AT Memory, not before). When any of these enables is active, forwarding
        should NOT occur from this stage.

        Uses structural tracing to find pipelined signals, avoiding hardcoded ISA-specific patterns.
        """
        # Helper functions for pipeline analysis
        def count_pipe_depth(node_id: str) -> int:
            """Count trailing _PIPE suffixes to determine pipeline depth."""
            depth = 0
            parts = node_id.split('_')
            for i in range(len(parts) - 1, -1, -1):
                if parts[i] == 'PIPE':
                    depth += 1
                else:
                    break
            return depth

        def extract_core_name(node_id: str) -> str:
            """Extract base signal name from pipelined name."""
            core_name = node_id
            while core_name.startswith('PIPE_'):
                parts = core_name.split('_', 2)
                if len(parts) >= 3:
                    core_name = parts[2]
                else:
                    break
            while core_name.endswith('_PIPE'):
                core_name = core_name[:-5]
            return core_name

        # Find pipelined write address at this stage using structural approach
        # Same approach as stalling: trace from write_index_node to find pipelined version
        rd_at_stage = None

        # First, use the structural approach: find the actual write index at the write location
        actual_write_index = self._find_pipelined_index_at_write(hazard)
        if actual_write_index:
            # Now find the version at the requested stage by looking at pipeline depth
            # The actual_write_index is at the final write stage (e.g., Writeback)
            # We need to find the version at an earlier stage (e.g., Memory or Execute)

            # Get the core name of the write index (e.g., "rd" or "rf_write_addr_mux")
            core_write_index = extract_core_name(actual_write_index.id)

            # Find pipelined version at the target stage - sorted for determinism
            for node_id in sorted(self.graph.nodes):
                if stage_name in node_id and node_id.endswith('PIPE'):
                    node_core = extract_core_name(node_id)
                    if node_core == core_write_index:
                        rd_at_stage = self.graph.nodes[node_id]
                        print(f"    Found pipelined write addr at {stage_name}: {node_id}")
                        break

        # Fallback: search for common patterns if structural approach fails
        if not rd_at_stage:
            # Try to find pipelined rd or rf_write_addr_mux at the target stage
            for node_id in sorted(self.graph.nodes):
                if stage_name in node_id and node_id.endswith('PIPE'):
                    # Check for common write address patterns (rd, rf_write_addr_mux)
                    if 'noteq' not in node_id and 'ne_0' not in node_id and 'not_zero' not in node_id:
                        # Match patterns like _rd_PIPE or _rf_write_addr_mux_PIPE
                        if re.search(r'_(rd|rf_write_addr_mux)(_PIPE)+$', node_id):
                            rd_at_stage = self.graph.nodes[node_id]
                            print(f"    Found pipelined write addr (fallback): {node_id}")
                            break

        if not rd_at_stage:
            print(f"    Could not find pipelined write addr at stage {stage_name}")
            return None

        # Find the write enable at this stage by tracing from the write access node
        # Same approach as stalling: get combined_write_enable, trace predecessors, find at target depth
        # (count_pipe_depth and extract_core_name are defined above)

        # Determine target depth from rd_at_stage
        target_depth = count_pipe_depth(rd_at_stage.id)
        print(f"    Target pipeline depth: {target_depth}")

        # Get the combined write enable from the write access node
        combined_write_enable_name = hazard.write_access_node.data.get('combined_write_enable')
        if not combined_write_enable_name:
            combined_write_enable_name = f"{hazard.resource}_write_enable"

        # Find write enable predecessors and their pipelined versions at target depth
        write_enable = None
        stage_enable_nodes = []

        if combined_write_enable_name in self.graph.nodes:
            we_node = self.graph.nodes[combined_write_enable_name]
            # Get all incoming edges to find the signals being OR'd together
            write_enable_predecessors = []
            for edge in we_node.incoming_edges:
                src = edge.source
                # Skip if this is the valid gating
                if 'valid' in src.id.lower():
                    continue
                core_name = extract_core_name(src.id)
                write_enable_predecessors.append(core_name)

            print(f"    Write enable predecessors: {write_enable_predecessors}")

            # Find pipelined versions at target depth - sorted for determinism
            for pred_base in sorted(write_enable_predecessors):
                for node_id, node in sorted(self.graph.nodes.items()):
                    if node.data.get('type') == 'pipeline_register':
                        if pred_base in node_id and count_pipe_depth(node_id) == target_depth:
                            stage_enable_nodes.append(node)
                            print(f"    Found stage enable: {node_id}")
                            break

        # Use the found enables, or fall back to the combined enable
        if stage_enable_nodes:
            write_enable = stage_enable_nodes[0] if len(stage_enable_nodes) == 1 else None
            # TODO: If multiple enables, OR them together like stalling does
        elif combined_write_enable_name in self.graph.nodes:
            write_enable = self.graph.nodes[combined_write_enable_name]
            print(f"    Using combined write enable: {combined_write_enable_name}")

        # No need for separate rd_noteq_0 check - it's included in the write enable logic
        rd_noteq_0 = None

        # Find valid signal at this stage
        valid_signal = self.graph.nodes.get(f"PIPE_{stage_name}_valid_PIPE")

        # Find pipelined read index at Execute stage using structural approach
        # The bypass mux is at Execute, so we need to compare with Execute's read index
        # not Decode's read index
        rs_index_name = hazard.read_index_name  # e.g., 'rs1', 'rs2', 'rs', 'rt'
        pipelined_rs = None

        # Structural approach: trace forward from hazard.read_index_node to find pipelined version
        # The read_index_node should have pipeline_input edges to pipelined versions
        original_rs = hazard.read_index_node

        # First, look for pipelined version by tracing forward from the original
        for edge in original_rs.outgoing_edges:
            if edge.data.get('type') == 'pipeline_input':
                candidate = edge.target
                if candidate.data.get('type') == 'pipeline_register':
                    if 'Execute' in candidate.id:
                        pipelined_rs = candidate
                        print(f"    Found pipelined rs index via forward trace: {candidate.id}")
                        break

        # If not found via forward trace, search by pattern matching on the core name
        if not pipelined_rs:
            for node_id in sorted(self.graph.nodes):
                if 'Execute' in node_id and node_id.endswith('PIPE'):
                    node_core = extract_core_name(node_id)
                    # Match if core name equals the read index name
                    if node_core == rs_index_name:
                        pipelined_rs = self.graph.nodes[node_id]
                        print(f"    Found pipelined rs index via pattern: {node_id}")
                        break

        # If not found, create the pipelined version for the read index
        if not pipelined_rs:
            print(f"    Creating pipelined {rs_index_name} for Execute stage")

            # Create a pipeline register for the rs index
            pipelined_rs_id = f"PIPE_Execute_{rs_index_name}_PIPE"
            if pipelined_rs_id not in self.graph.nodes:
                # Get bit width from original node if available
                bit_width = original_rs.data.get('bit_width', 5)
                if not bit_width:
                    bit_width = 5  # Default for register indices

                pipelined_rs = Node(pipelined_rs_id, {
                    'type': 'pipeline_register',
                    'name': pipelined_rs_id,
                    'display_name': f'Pipelined {rs_index_name}',
                    'bit_width': bit_width,
                    'pipeline_component': True
                })
                pipelined_rs.pipe_time = 2  # Execute stage (pipeline depth)
                pipelined_rs.uarch_time = 2  # Execute stage
                self.graph.add_node(pipelined_rs)

                # Connect original_rs -> pipelined_rs
                edge = Edge(original_rs, pipelined_rs, data={
                    'type': 'pipeline_input',
                    'pipeline_component': True
                })
                self.graph.add_edge(edge)
                print(f"    Created pipelined read index: {pipelined_rs_id}")
            else:
                pipelined_rs = self.graph.nodes[pipelined_rs_id]
                print(f"    Using existing pipelined read index: {pipelined_rs_id}")

        # Find or create pipelined read enable signal
        # This tells us if the instruction at Execute actually reads this register
        # (e.g., LUI doesn't read rs1 even though the field exists in the instruction)
        read_enable_id = f"{hazard.resource}_{rs_index_name}_rd_enable"
        pipelined_read_enable = None

        if read_enable_id in self.graph.nodes:
            read_enable_node = self.graph.nodes[read_enable_id]
            print(f"    Found read enable signal: {read_enable_id}")

            # Look for pipelined version at Execute
            pipelined_re_id = f"PIPE_Execute_{read_enable_id}_PIPE"
            if pipelined_re_id in self.graph.nodes:
                pipelined_read_enable = self.graph.nodes[pipelined_re_id]
                print(f"    Found pipelined read enable: {pipelined_re_id}")
            else:
                # Try searching by pattern - sorted for determinism
                for node_id in sorted(self.graph.nodes):
                    if 'Execute' in node_id and read_enable_id in node_id and node_id.endswith('PIPE'):
                        pipelined_read_enable = self.graph.nodes[node_id]
                        print(f"    Found pipelined read enable via pattern: {node_id}")
                        break

                # Create if not found
                if not pipelined_read_enable:
                    pipelined_read_enable = Node(pipelined_re_id, {
                        'type': 'pipeline_register',
                        'name': pipelined_re_id,
                        'display_name': f'Pipelined {read_enable_id}',
                        'bit_width': 1,
                        'pipeline_component': True
                    })
                    pipelined_read_enable.pipe_time = 2  # Execute stage (pipeline depth)
                    pipelined_read_enable.uarch_time = 2  # Execute stage
                    self.graph.add_node(pipelined_read_enable)

                    edge = Edge(read_enable_node, pipelined_read_enable, data={
                        'type': 'pipeline_input',
                        'pipeline_component': True
                    })
                    self.graph.add_edge(edge)
                    print(f"    Created pipelined read enable: {pipelined_re_id}")
        else:
            print(f"    No read enable signal found ({read_enable_id}) - all instructions may use this register")

        # Create comparator: rd_at_stage == pipelined_rs_index
        cmp_id = f"fwd_cmp_{stage_name}_{hazard.read_index_name}"
        cmp_node = self.hw_factory.comparators.create_index_comparator(
            comp_id=cmp_id,
            left_node=rd_at_stage,
            right_node=pipelined_rs,
            operator='==',
            display_name=f'Forward Compare ({stage_name})',
            metadata={'resolution': 'bypass'}
        )

        # Build condition: cmp && write_enable && read_enable && valid
        # Use 'left_operand'/'right_operand' edge types for Verilog generator compatibility
        current = cmp_node

        if write_enable:
            and_id = f"{cmp_id}_we"
            and_node = Node(and_id, {'type': 'operation', 'operator': '&&', 'name': and_id, 'bit_width': 1})
            self.graph.add_node(and_node)
            self.graph.add_edge(Edge(current, and_node, data={'type': 'left_operand', 'position': 'left'}))
            self.graph.add_edge(Edge(write_enable, and_node, data={'type': 'right_operand', 'position': 'right'}))
            current = and_node

        if rd_noteq_0:
            and_id = f"{cmp_id}_nz"
            and_node = Node(and_id, {'type': 'operation', 'operator': '&&', 'name': and_id, 'bit_width': 1})
            self.graph.add_node(and_node)
            self.graph.add_edge(Edge(current, and_node, data={'type': 'left_operand', 'position': 'left'}))
            self.graph.add_edge(Edge(rd_noteq_0, and_node, data={'type': 'right_operand', 'position': 'right'}))
            current = and_node

        # Gate with pipelined read enable if available
        # This prevents forwarding when the instruction doesn't actually read this register
        if pipelined_read_enable:
            and_id = f"{cmp_id}_rd_en"
            and_node = Node(and_id, {'type': 'operation', 'operator': '&&', 'name': and_id, 'bit_width': 1})
            self.graph.add_node(and_node)
            self.graph.add_edge(Edge(current, and_node, data={'type': 'left_operand', 'position': 'left'}))
            self.graph.add_edge(Edge(pipelined_read_enable, and_node, data={'type': 'right_operand', 'position': 'right'}))
            current = and_node
            print(f"    Added read enable gating to forwarding condition")

        if valid_signal:
            and_id = f"{cmp_id}_valid"
            and_node = Node(and_id, {'type': 'operation', 'operator': '&&', 'name': and_id, 'bit_width': 1})
            self.graph.add_node(and_node)
            self.graph.add_edge(Edge(current, and_node, data={'type': 'left_operand', 'position': 'left'}))
            self.graph.add_edge(Edge(valid_signal, and_node, data={'type': 'right_operand', 'position': 'right'}))
            current = and_node

        # Gate with NOT(any_unavailable_enable) - this prevents forwarding when the
        # producing instruction's result is not yet available at this stage.
        # E.g., load instructions compute their result AT Memory stage, so they can't
        # be forwarded FROM Memory stage (only from Writeback).
        if unavailable_enables and len(unavailable_enables) > 0:
            # OR all unavailable enables together
            if len(unavailable_enables) == 1:
                unavailable_or = unavailable_enables[0]
            else:
                unavailable_or = unavailable_enables[0]
                for i, enable in enumerate(unavailable_enables[1:], 1):
                    or_id = f"{cmp_id}_unavail_or_{i}"
                    or_node = Node(or_id, {'type': 'operation', 'operator': '||', 'name': or_id, 'bit_width': 1})
                    self.graph.add_node(or_node)
                    self.graph.add_edge(Edge(unavailable_or, or_node, data={'type': 'left_operand', 'position': 'left'}))
                    self.graph.add_edge(Edge(enable, or_node, data={'type': 'right_operand', 'position': 'right'}))
                    unavailable_or = or_node

            # Create NOT(unavailable_or)
            not_id = f"{cmp_id}_not_unavail"
            not_node = Node(not_id, {'type': 'operation', 'operator': '!', 'name': not_id, 'bit_width': 1})
            self.graph.add_node(not_node)
            self.graph.add_edge(Edge(unavailable_or, not_node, data={'type': 'operand', 'operand_position': 0}))

            # AND with current condition
            and_id = f"{cmp_id}_avail"
            and_node = Node(and_id, {'type': 'operation', 'operator': '&&', 'name': and_id, 'bit_width': 1})
            self.graph.add_node(and_node)
            self.graph.add_edge(Edge(current, and_node, data={'type': 'left_operand', 'position': 'left'}))
            self.graph.add_edge(Edge(not_node, and_node, data={'type': 'right_operand', 'position': 'right'}))
            current = and_node

            print(f"    Added NOT(unavailable) gate with {len(unavailable_enables)} enables")

        return current

    def _add_load_use_stall(self, hazard: DetectedHazard, stage_name: str,
                            unavailable_enables: List[Node],
                            stall_stage: Optional[str] = None) -> None:
        """
        Add a stall condition for load-use hazards.

        When a late-producing instruction (e.g., load) is at a stage where its result
        is not yet available, and a dependent instruction is in Decode, we must stall.

        Key insight: Compare stage_rd with DECODE's raw rs (hazard.read_index_node),
        NOT the pipelined Execute rs. The dependent is in Decode, not Execute!

        Args:
            stage_name: The forwarding stage (used as default stall stage)
            unavailable_enables: Enables for instructions whose results aren't available
                at the forwarding stage. If stall_stage differs from stage_name, these
                are looked up at the stall_stage instead.
            stall_stage: The stage where the stall should be detected. For distance-1
                hazards, this is 'Execute' (one stage before the forwarding stage
                'Memory'), because the stall must fire while the load is still in
                Execute to prevent the dependent from advancing. If None, defaults
                to stage_name.

        This creates a stall signal: (stall_stage_rd == decode_rs) && (stall_stage_valid) &&
                                      (write_enable) && (any_unavailable_enable)
        """
        if stall_stage is None:
            stall_stage = stage_name
        rs_name = hazard.read_index_name  # e.g., 'rs1', 'rs2'
        stall_id = f"load_use_stall_{stall_stage}_{rs_name}"

        # Check if we already created this stall
        if stall_id in self.graph.nodes:
            print(f"    Load-use stall {stall_id} already exists")
            return

        # Find the pipelined write address at the stall detection stage.
        # Structural: find the write index at the write access, then trace it back
        # to the stall stage via pipeline_input edges (works for any ISA).
        rd_at_stage = None

        actual_write_index = self._find_pipelined_index_at_write(hazard)
        if actual_write_index:
            rd_at_stage = self._find_pipelined_version_at_stage_by_tracing(actual_write_index, stall_stage)
            if rd_at_stage:
                print(f"    Found write addr at {stall_stage}: {rd_at_stage.id}")

        if not rd_at_stage:
            print(f"    Warning: Could not find pipelined write addr at {stall_stage}")
            return

        # CRITICAL: Use Decode's raw rs (from hazard.read_index_node), NOT pipelined rs!
        # The dependent is in Decode, not Execute
        decode_rs = hazard.read_index_node
        print(f"    Using Decode rs: {decode_rs.id}")

        # Create comparator: stall_stage_rd == decode_rs
        cmp_id = f"stall_cmp_{stall_stage}_{rs_name}"
        cmp_node = self.hw_factory.comparators.create_index_comparator(
            comp_id=cmp_id,
            left_node=rd_at_stage,
            right_node=decode_rs,
            operator='==',
            display_name=f'Load-use stall compare ({stall_stage} to Decode)',
            metadata={'resolution': 'bypass_stall'}
        )

        # Find write enable at stall detection stage.
        # Structural: trace from the write_access_node's incoming write_enable edge,
        # then trace back to the stall stage via pipeline_input edges.
        # The write_enable source may be a validity-gated AND node (not a pipeline
        # register), so we drill through operation nodes to find the underlying
        # pipeline register first, then trace backward from there.
        write_enable_at_stage = None
        for edge in hazard.write_access_node.incoming_edges:
            if edge.data.get('type') == 'write_enable':
                we_node = edge.source
                # Try direct tracing first
                write_enable_at_stage = self._find_pipelined_version_at_stage_by_tracing(we_node, stall_stage)
                if write_enable_at_stage:
                    print(f"    Found write enable at {stall_stage}: {write_enable_at_stage.id}")
                    break
                # If the write enable is a gated node (AND with valid), drill through
                # its operand edges to find the pipeline register input
                if we_node.data.get('type') == 'operation':
                    for op_edge in we_node.incoming_edges:
                        src = op_edge.source
                        if src.data.get('type') == 'pipeline_register':
                            write_enable_at_stage = self._find_pipelined_version_at_stage_by_tracing(src, stall_stage)
                            if write_enable_at_stage:
                                print(f"    Found write enable at {stall_stage}: {write_enable_at_stage.id} (via gated node)")
                                break
                if write_enable_at_stage:
                    break

        # Find stage valid signal at the stall detection stage
        stage_valid = self.graph.nodes.get(f"PIPE_{stall_stage}_valid_PIPE")

        # Find read enable at Decode (raw)
        read_enable_id = f"{hazard.resource}_{rs_name}_rd_enable"
        read_enable = self.graph.nodes.get(read_enable_id)

        # Build condition chain: cmp && write_enable && stage_valid && read_enable && any_unavailable
        current = cmp_node

        if write_enable_at_stage:
            and_id = f"{stall_id}_we"
            and_node = Node(and_id, {'type': 'operation', 'operator': '&&', 'name': and_id, 'bit_width': 1})
            self.graph.add_node(and_node)
            self.graph.add_edge(Edge(current, and_node, data={'type': 'left_operand', 'position': 'left'}))
            self.graph.add_edge(Edge(write_enable_at_stage, and_node, data={'type': 'right_operand', 'position': 'right'}))
            current = and_node

        if stage_valid:
            and_id = f"{stall_id}_valid"
            and_node = Node(and_id, {'type': 'operation', 'operator': '&&', 'name': and_id, 'bit_width': 1})
            self.graph.add_node(and_node)
            self.graph.add_edge(Edge(current, and_node, data={'type': 'left_operand', 'position': 'left'}))
            self.graph.add_edge(Edge(stage_valid, and_node, data={'type': 'right_operand', 'position': 'right'}))
            current = and_node

        if read_enable:
            and_id = f"{stall_id}_rd_en"
            and_node = Node(and_id, {'type': 'operation', 'operator': '&&', 'name': and_id, 'bit_width': 1})
            self.graph.add_node(and_node)
            self.graph.add_edge(Edge(current, and_node, data={'type': 'left_operand', 'position': 'left'}))
            self.graph.add_edge(Edge(read_enable, and_node, data={'type': 'right_operand', 'position': 'right'}))
            current = and_node

        # OR all unavailable enables together
        if len(unavailable_enables) == 1:
            unavail_or = unavailable_enables[0]
        else:
            unavail_or = unavailable_enables[0]
            for i, enable in enumerate(unavailable_enables[1:], 1):
                or_id = f"{stall_id}_unavail_or_{i}"
                or_node = Node(or_id, {'type': 'operation', 'operator': '||', 'name': or_id, 'bit_width': 1})
                self.graph.add_node(or_node)
                self.graph.add_edge(Edge(unavail_or, or_node, data={'type': 'left_operand', 'position': 'left'}))
                self.graph.add_edge(Edge(enable, or_node, data={'type': 'right_operand', 'position': 'right'}))
                unavail_or = or_node

        # Final AND with unavailable enables
        stall_node = Node(stall_id, {
            'type': 'operation',
            'operator': '&&',
            'name': stall_id,
            'description': f'Load-use stall: {stall_stage} has load matching {rs_name}',
            'bit_width': 1,
            'pipeline_component': True
        })
        self.graph.add_node(stall_node)
        self.graph.add_edge(Edge(current, stall_node, data={'type': 'left_operand', 'position': 'left'}))
        self.graph.add_edge(Edge(unavail_or, stall_node, data={'type': 'right_operand', 'position': 'right'}))

        print(f"    Created load-use stall: {stall_id}")
        print(f"      Compares {rd_at_stage.id} == {decode_rs.id}")

        # Add this stall to the pipeline stall controller
        self._integrate_stall_into_controller(stall_node, f"load_use_{stall_stage}_{rs_name}")

    def _integrate_stall_into_controller(self, stall_condition: Node, reason: str) -> None:
        """
        Integrate a stall condition into the pipeline's stall controller.

        This ORs the new stall condition with existing stall conditions.
        """
        # Find the stall controller - typically PIPE_Decode_stall_ctrl or similar
        stall_ctrl = self.graph.nodes.get('PIPE_Decode_stall_ctrl')

        if not stall_ctrl:
            # Try to find via _with_umem_stall variant
            stall_ctrl = self.graph.nodes.get('PIPE_Decode_stall_ctrl_with_umem_stall')

        if not stall_ctrl:
            # Try to find via pc_rd stall edge
            pc_rd = self.graph.nodes.get('pc_rd')
            if pc_rd:
                for edge in pc_rd.incoming_edges:
                    if edge.data.get('type') == 'stall':
                        stall_ctrl = edge.source
                        break

        if not stall_ctrl:
            print(f"    Deferring stall integration for {stall_condition.id} (controller not yet created)")
            self._pending_stall_integrations.append((stall_condition, reason))
            return

        # Check if already connected
        for edge in stall_ctrl.incoming_edges:
            if edge.source == stall_condition:
                print(f"    Stall {stall_condition.id} already connected to {stall_ctrl.id}")
                return

        # Find existing control/operand inputs to stall controller
        existing_inputs = [e.source for e in stall_ctrl.incoming_edges
                          if e.data.get('type') in ('control', 'operand', 'left_operand', 'right_operand')]

        if stall_condition in existing_inputs:
            print(f"    Stall {stall_condition.id} already in inputs of {stall_ctrl.id}")
            return

        if existing_inputs:
            # OR the new stall with existing stall conditions
            or_id = f"{stall_ctrl.id}_with_{reason}"
            if or_id not in self.graph.nodes:
                or_node = Node(or_id, data={
                    'type': 'operation',
                    'operator': '||',
                    'name': or_id,
                    'description': f'Combined stall: existing OR {reason}',
                    'bit_width': 1,
                    'pipeline_component': True
                })
                self.graph.add_node(or_node)

                # Connect existing inputs to OR
                for idx, inp in enumerate(existing_inputs):
                    self.graph.add_edge(Edge(inp, or_node, data={'type': 'operand', 'operand_index': idx}))
                # Connect new stall to OR
                self.graph.add_edge(Edge(stall_condition, or_node, data={'type': 'operand', 'operand_index': len(existing_inputs)}))

                # Remove old control edges from stall controller
                for e in list(stall_ctrl.incoming_edges):
                    if e.data.get('type') in ('control', 'operand', 'left_operand', 'right_operand'):
                        e.remove_from_nodes()
                        if e.id in self.graph.edges:
                            del self.graph.edges[e.id]

                # Connect OR output to stall controller
                self.graph.add_edge(Edge(or_node, stall_ctrl, data={'type': 'control', 'reason': f'combined_with_{reason}'}))
                print(f"    ORed {stall_condition.id} with existing stalls into {stall_ctrl.id}")
            else:
                # OR node already exists, add new stall to it
                existing_or = self.graph.nodes[or_id]
                next_idx = len([e for e in existing_or.incoming_edges if e.data.get('type') == 'operand'])
                self.graph.add_edge(Edge(stall_condition, existing_or, data={'type': 'operand', 'operand_index': next_idx}))
                print(f"    Added {stall_condition.id} to existing OR node {or_id}")
        else:
            # No existing inputs, connect directly
            self.graph.add_edge(Edge(stall_condition, stall_ctrl, data={'type': 'control', 'reason': reason}))
            print(f"    Connected {stall_condition.id} directly to {stall_ctrl.id}")

    def _retry_pending_stall_integrations(self) -> None:
        """Retry stall integrations that were deferred because the controller didn't exist yet."""
        if not self._pending_stall_integrations:
            return

        print(f"\n  Retrying {len(self._pending_stall_integrations)} deferred stall integrations...")
        pending = list(self._pending_stall_integrations)
        self._pending_stall_integrations = []

        for stall_node, reason in pending:
            self._integrate_stall_into_controller(stall_node, reason)

        if self._pending_stall_integrations:
            print(f"    Warning: {len(self._pending_stall_integrations)} stall integrations still pending (no controller found)")

        # Ensure bubble injection exists for all stall controllers.
        # When stalls are deferred (e.g., load-use stalls in bypass mode with WRF),
        # the controller may have been created by _add_automatic_memory_latency_stalls
        # without setting up bubble injection.  Without this, the stall holds Decode
        # but doesn't suppress Execute valid, causing double execution.
        self._ensure_bubble_injection_for_stall_controllers()

    def _ensure_bubble_injection_for_stall_controllers(self) -> None:
        """Ensure every stall controller has a corresponding bubble injection node."""
        if not self.pipeline_config:
            return

        stage_names = self.pipeline_config.stage_names
        for node_id, node in sorted(self.graph.nodes.items()):
            if node.data.get('type') != 'pipeline_stall_controller':
                continue
            # Only process Decode-level stall controllers (PIPE_{stage}_stall_ctrl).
            # Memory-specific controllers like PIPE_Memory_umem_stall_ctrl freeze
            # the pipeline; they must NOT inject bubbles.
            if not (node_id.startswith('PIPE_') and node_id == f"PIPE_{node_id.split('_')[1]}_stall_ctrl"):
                continue

            ctrl_stage = node_id.split('_')[1]
            try:
                ctrl_idx = stage_names.index(ctrl_stage)
            except ValueError:
                continue
            if ctrl_idx + 1 >= len(stage_names):
                continue

            next_stage = stage_names[ctrl_idx + 1]
            valid_and_not_stall_id = f"PIPE_{next_stage}_valid_and_not_stall"
            if valid_and_not_stall_id in self.graph.nodes:
                continue  # Already set up

            next_valid_id = f"PIPE_{next_stage}_valid_PIPE"
            next_valid = self.graph.nodes.get(next_valid_id)
            if not next_valid:
                continue

            # Find the current pipeline_input source for next_valid.
            # It may already be gated by flush logic (e.g., valid_input_not_flush),
            # so we must compose with it rather than replacing it with prev_valid.
            current_input_edge = None
            for edge in next_valid.incoming_edges:
                if edge.data.get('type') == 'pipeline_input':
                    current_input_edge = edge
                    break

            if current_input_edge is None:
                # No existing input — fall back to prev-stage valid register
                prev_valid_id = f"PIPE_{ctrl_stage}_valid_PIPE"
                current_input_source = self.graph.nodes.get(prev_valid_id)
                if not current_input_source:
                    continue
            else:
                current_input_source = current_input_edge.source

            print(f"    Setting up bubble injection: {next_stage}_valid = {current_input_source.id} AND NOT {node_id}")

            # Create or reuse NOT gate for stall
            not_stall_id = f"{node_id}_not"
            if not_stall_id not in self.graph.nodes:
                not_stall = Node(not_stall_id, data={
                    'type': 'operation', 'operator': '!',
                    'name': not_stall_id, 'bit_width': 1
                })
                self.graph.add_node(not_stall)
                self.graph.add_edge(Edge(node, not_stall, data={'type': 'operand'}))
            not_stall = self.graph.nodes[not_stall_id]

            # Create AND: current_input_source AND NOT stall
            # This composes with any existing gating (e.g., flush) already in the chain.
            and_node = Node(valid_and_not_stall_id, data={
                'type': 'operation', 'operator': '&&',
                'name': valid_and_not_stall_id, 'bit_width': 1
            })
            self.graph.add_node(and_node)

            # Remove the old pipeline_input edge to next_valid (we replace it below)
            if current_input_edge is not None:
                self.graph.remove_edge(current_input_edge.id)

            # Wire up: current_input_source -> AND -> next_valid
            self.graph.add_edge(Edge(current_input_source, and_node, data={
                'type': 'operand', 'operand_index': 0
            }))
            self.graph.add_edge(Edge(not_stall, and_node, data={
                'type': 'operand', 'operand_index': 1
            }))
            self.graph.add_edge(Edge(and_node, next_valid, data={
                'type': 'pipeline_input', 'pipeline_component': True
            }))

    def resolve_with_bypassing(self, hazard: DetectedHazard) -> bool:
        """
        Resolve a hazard by adding bypass/forwarding logic.

        This creates forwarding paths from later pipeline stages to the read stage,
        with a mux to select between the forwarded value and the normal RF value.

        For load-use hazards, we fall back to stalling since the loaded value
        isn't available in time for pure forwarding.

        For non-indexed hazards, bypassing is not yet implemented — falls back
        to stalling.
        """
        print(f"Resolving with BYPASS: {hazard}")

        # Non-indexed (individual) ISA state hazards: bypass not yet implemented.
        # These are typically control signals (flags, status registers) where
        # stalling is sufficient. Full bypass support can be added later.
        if not hazard.is_indexed:
            print(f"  Non-indexed hazard on {hazard.resource}: bypassing not yet supported, using stalling")
            return self.resolve_with_stalling(hazard)

        # Check if this hazard is at the memory's read/write stage pair.
        # If the read and write happen at their canonical positions (the stages where
        # the RF is actually read/written), bypass can't help without write_read_fwd.
        # This catches same-cycle hazards AND cases like 4-stage pipelines where the
        # distance-2 hazard IS at canonical positions (MemoryWriteback write, Decode read).
        # For 5-stage pipelines, distance-2 hazards have write at Memory (non-canonical),
        # so this check correctly allows them through to forwarding.
        read_time = getattr(hazard.read_access_node, 'pipe_time', None)
        if read_time is None:
            read_time = getattr(hazard.read_access_node, 'uarch_time', None)
        write_time = getattr(hazard.write_access_node, 'pipe_time', None)
        if write_time is None:
            write_time = getattr(hazard.write_access_node, 'uarch_time', None)

        if read_time is not None and write_time is not None:
            # If hazard stages match the access nodes' pipe_time, we're at canonical positions
            if hazard.read_stage == read_time and hazard.write_stage == write_time:
                if self._memory_has_write_read_fwd(hazard.resource):
                    # write_read_fwd handles same-cycle forwarding in RF hardware
                    print(f"  Hazard at canonical positions with write_read_fwd - already resolved by RF")
                    return True
                else:
                    print(f"  Hazard at canonical positions without write_read_fwd - using stalling")
                    print(f"  (Read at stage {hazard.read_stage}, Write at stage {hazard.write_stage})")
                    return self.resolve_with_stalling(hazard)

        # For distance 1+ hazards, use SELECTIVE stalling + forwarding.
        # Only stall when the producer's result is not yet available at the
        # forwarding stage (e.g., loads compute at Memory, so for distance-1
        # forwarding from Memory, loads need a stall while ALU results don't).
        # ALU instructions compute at Execute, so their results ARE available at
        # Memory and can be forwarded without stalling.
        #
        # The load-use stall is added later in this method after we determine
        # which enables are unavailable at the forwarding stage.
        distance = hazard.get_forwarding_distance()
        print(f"  Distance {distance} hazard: implementing forwarding with selective load-use stalling")

        read_index_name = hazard.read_index_name  # e.g., 'rs1' or 'rs2'
        mux_id = f"bypass_mux_{read_index_name}"

        # Check if bypass mux already exists for this read port
        if mux_id in self.bypass_muxes:
            bypass_mux = self.bypass_muxes[mux_id]
            print(f"  Using existing bypass mux: {mux_id}")
        else:
            # Need to create a new bypass mux - find the pipelined RF read and its consumer
            # Graph structure: rf[rs1]_rd -> PIPE_Execute_rf_rs1_rd_PIPE -> r1
            pipelined_rf_read = None
            read_consumer = None  # e.g., r1 or r2

            # First, follow the pipeline_input edge to get the pipelined version
            for edge in hazard.read_access_node.outgoing_edges:
                if edge.data.get('type') == 'pipeline_input':
                    pipelined_rf_read = edge.target
                    break

            # If no pipeline_input edge, look for the pipelined node directly
            if not pipelined_rf_read:
                for node_id, node in sorted(self.graph.nodes.items()):
                    if f'rf_{read_index_name}_rd' in node_id:
                        if 'PIPE' in node_id and 'Execute' in node_id:
                            pipelined_rf_read = node
                            break

            # Now find ALL consumers from the pipelined read (there may be multiple: r1, base, sw_base, pc_wr_mux, etc.)
            read_consumers = []
            if pipelined_rf_read:
                for edge in pipelined_rf_read.outgoing_edges:
                    edge_type = edge.data.get('type')
                    # Include assignment edges (for r1, base, etc.), mux_input edges (for pc_wr_mux),
                    # and bit_access edges (for sb/sh partial byte/halfword operations)
                    if edge_type in ('assignment', 'mux_input', 'bit_access'):
                        read_consumers.append((edge, edge.target))

            if not pipelined_rf_read or not read_consumers:
                print(f"  Could not find pipelined RF read or consumers, falling back to stalling")
                return self.resolve_with_stalling(hazard)

            print(f"  Found {len(read_consumers)} consumers of {pipelined_rf_read.id}: {[c[1].id for c in read_consumers]}")

            # Get data width from the pipelined RF read node (default 32 for RV32, 64 for RV64)
            data_width = pipelined_rf_read.data.get('bit_width')
            if data_width is None:
                # Try to infer from the source node chain
                for edge in pipelined_rf_read.incoming_edges:
                    source = edge.source
                    source_width = source.data.get('bit_width')
                    if source_width:
                        data_width = source_width
                        break
                    # If source is array_access (rf[rs1]_rd), trace to the array base (rf)
                    if source.data.get('type') == 'array_access':
                        for arr_edge in source.incoming_edges:
                            if arr_edge.data.get('type') == 'array_base':
                                rf_width = arr_edge.source.data.get('bit_width')
                                if rf_width:
                                    data_width = rf_width
                                    break
            if data_width is None:
                # Last resort: look for the resource in the hazard
                if hasattr(hazard, 'resource') and hazard.resource:
                    resource_node = self.graph.nodes.get(hazard.resource)
                    if resource_node:
                        data_width = resource_node.data.get('bit_width', 32)
            if data_width is None:
                data_width = 32

            # Create new bypass mux using 'multiplexer' type for Verilog generator compatibility
            mux_data = {
                'type': 'multiplexer',
                'name': mux_id,
                'display_name': f'Bypass Mux for {read_index_name}',
                'num_inputs': 0,  # Will grow as we add forwarding paths (excludes default)
                'operation': 'priority_select',  # Priority mux: first matching condition wins
                'bit_width': data_width,
                'data_width': data_width,
                'output_width': data_width,
                'has_default': True  # Priority mux has default input
            }
            bypass_mux = Node(mux_id, mux_data)
            bypass_mux.pipe_time = getattr(pipelined_rf_read, 'pipe_time', None)
            if bypass_mux.pipe_time is None:
                bypass_mux.pipe_time = getattr(pipelined_rf_read, 'uarch_time', 1)
            bypass_mux.uarch_time = getattr(pipelined_rf_read, 'uarch_time', 1)
            self.graph.add_node(bypass_mux)

            # Reconnect: pipelined_rf_read -> bypass_mux -> all read_consumers
            # First, remove all edges from pipelined_rf_read to consumers
            for edge, consumer in read_consumers:
                edge.remove_from_nodes()
                if edge.id in self.graph.edges:
                    del self.graph.edges[edge.id]

            # Connect pipelined_rf_read -> bypass_mux as default input
            # For priority mux, the default is used when no select is active
            normal_edge = Edge(pipelined_rf_read, bypass_mux, data={
                'type': 'mux_default_input',
                'label': 'normal'
            })
            self.graph.add_edge(normal_edge)

            # Connect bypass_mux -> ALL read_consumers (preserving edge types)
            for orig_edge, consumer in read_consumers:
                # Preserve the original edge type and other metadata
                edge_data = {'type': orig_edge.data.get('type', 'assignment')}
                # Copy other metadata from original edge
                for key in orig_edge.data:
                    if key != 'type':
                        edge_data[key] = orig_edge.data[key]
                output_edge = Edge(bypass_mux, consumer, data=edge_data)
                self.graph.add_edge(output_edge)
                print(f"    Connected bypass mux to consumer: {consumer.id} (edge type: {edge_data['type']})")

            self.bypass_muxes[mux_id] = bypass_mux
            self.bypass_hazards[mux_id] = hazard
            print(f"  Created bypass mux: {mux_id} for resource: {hazard.resource}")

        # Now add forwarding path for this hazard
        # Determine forwarding source stage based on forwarding distance
        # Distance tells us how far ahead the producer is:
        #   Distance 2: producer at MEM, consumer at EX -> forward from Memory
        #   Distance 3: producer at WB, consumer at EX -> forward from Writeback
        distance = hazard.get_forwarding_distance()
        stage_name = None

        # Map distance to forwarding source stage using pipeline_config for accuracy.
        # By the time the consumer reaches Execute (one cycle after Decode), the
        # producer has advanced one more stage:
        #   Distance 1: producer was at write_stage, now at write_stage+1
        #   Distance 2: producer was at write_stage, now at write_stage+1 (= Writeback)
        #   Distance 3: canonical WB→Decode case; resolved by stall earlier if no WRF
        #
        # For 5-stage (F-D-E-M-W): distance-1 write_stage=Execute(2), fwd=Memory(3)
        # For 4-stage (F-D-E-MW): distance-1 write_stage=Execute(2), fwd=MemoryWriteback(3)
        # Both use the pipeline_config to find the actual stage name at write_stage+1.
        if self.pipeline_config and hazard.write_stage >= 0:
            fwd_idx = hazard.write_stage + 1
            if fwd_idx < len(self.pipeline_config.stage_names):
                candidate = self.pipeline_config.stage_names[fwd_idx]
                # For distance 2+, we want the LAST stage (Writeback equivalent)
                # since we're forwarding from the register file write data mux.
                if distance >= 2:
                    # Use the last stage before the write port (highest index stage)
                    stage_name = self.pipeline_config.stage_names[-1]
                else:
                    stage_name = candidate
        # Fallback for pipelines without config: use conventional names
        if not stage_name:
            if distance == 1:
                stage_name = 'Memory'
            elif distance >= 2:
                stage_name = 'Writeback'

        # Fallback: try to extract from hazard.write_stage_name
        if not stage_name:
            if 'Writeback' in hazard.write_stage_name:
                stage_name = 'Writeback'
            elif 'Memory' in hazard.write_stage_name:
                stage_name = 'Memory'

        print(f"  Forwarding from stage: {stage_name} (distance={distance})")

        if not stage_name:
            print(f"  Could not determine forwarding stage, falling back to stalling")
            return self.resolve_with_stalling(hazard)

        # Find forwarding value at this stage
        # Use rf_write_data_mux if we're at Writeback, otherwise create stage-specific mux
        forward_value = None
        unavailable_enables = []
        if stage_name == 'Writeback':
            forward_value = self.graph.nodes.get('rf_write_data_mux')
            # No unavailable enables at Writeback - all values have been computed
        else:
            forward_value = self._find_forwarding_value_mux_at_stage(stage_name)
            # Get unavailable enables that were tracked during mux construction
            # These are enables for values computed AT or AFTER this stage (e.g., loads at Memory)
            unavailable_enables = getattr(self, '_unavailable_at_stage', {}).get(stage_name, [])

        if not forward_value:
            print(f"  Could not find forwarding value at {stage_name}, falling back to stalling")
            return self.resolve_with_stalling(hazard)

        # Create forwarding condition, gated by NOT(unavailable_enables)
        # This ensures we don't forward from a stage when the value isn't ready yet
        forward_cond = self._create_forwarding_condition(hazard, stage_name, unavailable_enables)
        if not forward_cond:
            print(f"  Could not create forwarding condition, falling back to stalling")
            return self.resolve_with_stalling(hazard)

        # Create load-use stall condition when there are unavailable values
        # This stalls the pipeline when forwarding would match but the value isn't ready
        # E.g., load instruction in Execute, dependent instruction in Decode
        if unavailable_enables and len(unavailable_enables) > 0:
            # For distance-1 hazards, the stall must fire one stage earlier than the
            # forwarding stage.  Forwarding is from Memory (producer moved to Memory
            # when consumer reaches Execute), but the stall must detect the load while
            # it is still in Execute (one cycle earlier) so we can freeze Decode in time.
            # We find the Execute-stage versions of the unavailable enables to use in
            # the stall condition.
            if distance == 1 and self.pipeline_config:
                # stall_stage = the stage the producer is in when we need to detect the stall,
                # which is hazard.write_stage (e.g., Execute).  fwd_idx = write_stage+1.
                stall_stage_idx = hazard.write_stage
                if 0 <= stall_stage_idx < len(self.pipeline_config.stage_names):
                    stall_stage = self.pipeline_config.stage_names[stall_stage_idx]
                    # Find the stall-stage versions of the unavailable enables
                    stall_stage_enables = []
                    for mem_enable in unavailable_enables:
                        exec_enable = self._find_pipelined_version_at_stage(mem_enable, stall_stage)
                        if not exec_enable:
                            exec_enable = self._find_pipelined_version_at_stage_by_tracing(mem_enable, stall_stage)
                        if exec_enable:
                            stall_stage_enables.append(exec_enable)
                            print(f"    Mapped {mem_enable.id} -> {exec_enable.id} at {stall_stage}")
                        else:
                            print(f"    Warning: Could not find {stall_stage} version of {mem_enable.id}")
                    if stall_stage_enables:
                        self._add_load_use_stall(hazard, stage_name, stall_stage_enables,
                                                 stall_stage=stall_stage)
                    else:
                        print(f"    Warning: No stall-stage enables found, falling back to forwarding-stage stall")
                        self._add_load_use_stall(hazard, stage_name, unavailable_enables)
                else:
                    self._add_load_use_stall(hazard, stage_name, unavailable_enables)
            else:
                self._add_load_use_stall(hazard, stage_name, unavailable_enables)

        # Add forwarding input to bypass mux
        # For priority mux: num_inputs counts forwarding paths (not default)
        # input_index and select_index must match
        num_inputs = bypass_mux.data.get('num_inputs', 0)
        input_index = num_inputs  # This will be 0, 1, 2, ... for forwarding paths
        bypass_mux.data['num_inputs'] = num_inputs + 1

        # Connect forwarding value to mux
        fwd_edge = Edge(forward_value, bypass_mux, data={
            'type': 'mux_input',
            'input_index': input_index,
            'label': f'forward_{stage_name}'
        })
        self.graph.add_edge(fwd_edge)

        # Connect forwarding condition as select (same index as input)
        sel_edge = Edge(forward_cond, bypass_mux, data={
            'type': 'mux_select',
            'select_index': input_index
        })
        self.graph.add_edge(sel_edge)

        print(f"  Added forwarding from {stage_name} (input {input_index})")
        return True

    def _resolve_with_bypassing_full(self, hazard: DetectedHazard) -> bool:
        """
        Full bypassing implementation (work in progress).

        This method contains the framework for proper bypass mux insertion.
        It is not yet complete and is kept for reference during development.
        """
        # Find the target node that consumes the RF read value
        # e.g., rf[rs1]_rd -> r1, so r1 is the target
        read_target_node = None
        for edge in hazard.read_access_node.outgoing_edges:
            if edge.data.get('type') == 'assignment':
                read_target_node = edge.target
                break

        if not read_target_node:
            print(f"  ERROR: Could not find target of read value")
            return False

        # Get the read value name (e.g., 'r1' or 'r2')
        read_value_name = read_target_node.id  # Should be 'r1' or 'r2'

        # Find the pipelined version of the read value at the stage where it's consumed
        # For a 5-stage pipeline, r1/r2 are read in Decode and consumed in Execute
        # So we need PIPE_Execute_r1_PIPE or similar

        # Find the ACTUAL index node at the write location
        actual_write_index_node = self._find_pipelined_index_at_write(hazard)
        if not actual_write_index_node:
            print(f"  Warning: Could not find actual write index node, using original")
            actual_write_index_node = hazard.write_index_node

        # Find the write enable signal at the write stage
        write_enable_node = None
        rd_not_zero_node = None
        write_stage_valid_node = None

        if actual_write_index_node.id.startswith('PIPE_'):
            # Extract stage name and find matching signals
            parts = actual_write_index_node.id.split('_')
            if len(parts) >= 2:
                write_stage_name = parts[1]

                # Find matching rf_write_any_enable signal
                # Use pipe_time for stage comparison, fall back to uarch_time
                actual_ptime = getattr(actual_write_index_node, 'pipe_time', None)
                if actual_ptime is None:
                    actual_ptime = getattr(actual_write_index_node, 'uarch_time', None)
                for node_id, node in sorted(self.graph.nodes.items()):
                    if 'rf_write_any_enable' in node_id and node.data.get('type') == 'pipeline_register':
                        node_ptime = getattr(node, 'pipe_time', None)
                        if node_ptime is None:
                            node_ptime = getattr(node, 'uarch_time', None)
                        if node_ptime is not None and actual_ptime is not None:
                            if node_ptime == actual_ptime:
                                write_enable_node = node
                                break

                # Find rd_noteq_0 signal at the same pipeline stage
                for node_id, node in sorted(self.graph.nodes.items()):
                    if 'rd_noteq_0' in node_id or 'rd_not_zero' in node_id or 'rd_ne_0' in node_id:
                        if node.data.get('type') == 'pipeline_register':
                            node_ptime = getattr(node, 'pipe_time', None)
                            if node_ptime is None:
                                node_ptime = getattr(node, 'uarch_time', None)
                            if node_ptime is not None and actual_ptime is not None:
                                if node_ptime == actual_ptime:
                                    rd_not_zero_node = node
                                    break

                # Find valid signal at the write stage
                valid_signal_id = f"PIPE_{write_stage_name}_valid_PIPE"
                if valid_signal_id in self.graph.nodes:
                    write_stage_valid_node = self.graph.nodes[valid_signal_id]

        # Create or get the bypass mux for this read port
        mux_id = f"bypass_mux_{hazard.resource}_{hazard.read_index_name}"

        if mux_id in self.bypass_muxes:
            # Mux already exists, add this as another forwarding source
            mux_node = self.bypass_muxes[mux_id]
            print(f"  Adding to existing bypass mux: {mux_id}")
        else:
            # Create new mux
            # Use pipe_time for stage, fall back to uarch_time
            read_pipe_time = getattr(hazard.read_access_node, 'pipe_time', None)
            if read_pipe_time is None:
                read_pipe_time = getattr(hazard.read_access_node, 'uarch_time', None)
            read_uarch_time = getattr(hazard.read_access_node, 'uarch_time', None)

            mux_data = {
                'type': 'bypass_mux',
                'display_name': f'Bypass Mux for {hazard.resource}[{hazard.read_index_name}]',
                'num_inputs': 1,  # Start with just the normal value
                'resolution': 'bypass',
                'read_index': hazard.read_index_name,
                'forwarding_sources': []  # Track which stages forward to this mux
            }
            mux_node = Node(mux_id, mux_data)
            mux_node.pipe_time = read_pipe_time
            mux_node.uarch_time = read_uarch_time
            self.graph.add_node(mux_node)

            # Disconnect original read->target edge and reroute through mux
            for edge in sorted(hazard.read_access_node.outgoing_edges, key=lambda e: (e.source.id, e.target.id)):
                if edge.data.get('type') == 'assignment' and edge.target == read_target_node:
                    # Remove original edge
                    edge.remove_from_nodes()
                    if edge.id in self.graph.edges:
                        del self.graph.edges[edge.id]

                    # Connect read -> mux (input 0: normal path)
                    normal_edge = Edge(hazard.read_access_node, mux_node, data={
                        'type': 'mux_input',
                        'mux_input': 0,
                        'label': 'normal',
                        'priority': 0  # Lowest priority
                    })
                    self.graph.add_edge(normal_edge)

                    # Connect mux -> target
                    output_edge = Edge(mux_node, read_target_node, data={
                        'type': 'assignment'
                    })
                    self.graph.add_edge(output_edge)
                    break

            self.bypass_muxes[mux_id] = mux_node
            print(f"  Created bypass mux: {mux_id}")

        # Find the value to forward from the write stage
        # This is typically rf_write_data_mux or a pipelined version of it
        # For simplicity, we'll create a forwarding path from rf_write_data_mux

        # Get the current number of inputs to determine the new input index
        current_inputs = mux_node.data.get('num_inputs', 1)
        forwarding_input = current_inputs
        mux_node.data['num_inputs'] = current_inputs + 1

        # Find the forwarding value - we need the value that will be written to RF
        # This is rf_write_data_mux at the write stage's pipeline depth
        forwarding_value = self.graph.nodes.get('rf_write_data_mux')
        if not forwarding_value:
            print(f"  ERROR: Could not find rf_write_data_mux")
            return False

        # Connect forwarding value to mux
        forward_edge = Edge(forwarding_value, mux_node, data={
            'type': 'mux_input',
            'mux_input': forwarding_input,
            'label': f'forward_s{hazard.write_stage}',
            'priority': hazard.write_stage  # Higher stage = higher priority
        })
        self.graph.add_edge(forward_edge)

        # Create the forwarding condition: (rd == rs1) && rf_write_enable && (rd != 0) && stage_valid
        # Start with the comparator
        bypass_comp_id = f"bypass_cmp_{hazard.resource}_{hazard.write_index_name}_{hazard.read_index_name}_s{hazard.write_stage}"
        display_name = f'{hazard.write_index_name}=={hazard.read_index_name} (stage {hazard.write_stage})'

        bypass_comp = self.hw_factory.comparators.create_index_comparator(
            comp_id=bypass_comp_id,
            left_node=actual_write_index_node,
            right_node=hazard.read_index_node,
            operator='==',
            display_name=display_name,
            metadata={
                'hazard_type': hazard.hazard_type,
                'resolution': 'bypass'
            }
        )

        print(f"  Created comparator: {bypass_comp_id}")
        print(f"    Write index: {actual_write_index_node.id}")
        print(f"    Read index: {hazard.read_index_node.id}")

        # Build the full bypass enable condition
        current_signal = bypass_comp

        # AND with rd != 0
        if rd_not_zero_node:
            and_id = f"{bypass_comp_id}_rd_nz"
            and_node = Node(and_id, data={
                'type': 'operation',
                'operator': '&&',
                'name': and_id,
                'bit_width': 1
            })
            self.graph.add_node(and_node)

            edge1 = Edge(current_signal, and_node, data={'type': 'left_operand', 'position': 'left'})
            self.graph.add_edge(edge1)
            edge2 = Edge(rd_not_zero_node, and_node, data={'type': 'right_operand', 'position': 'right'})
            self.graph.add_edge(edge2)

            current_signal = and_node

        # AND with write enable
        if write_enable_node:
            and_id = f"{bypass_comp_id}_we"
            and_node = Node(and_id, data={
                'type': 'operation',
                'operator': '&&',
                'name': and_id,
                'bit_width': 1
            })
            self.graph.add_node(and_node)

            edge1 = Edge(current_signal, and_node, data={'type': 'left_operand', 'position': 'left'})
            self.graph.add_edge(edge1)
            edge2 = Edge(write_enable_node, and_node, data={'type': 'right_operand', 'position': 'right'})
            self.graph.add_edge(edge2)

            current_signal = and_node

        # AND with stage validity
        if write_stage_valid_node:
            and_id = f"{bypass_comp_id}_valid"
            and_node = Node(and_id, data={
                'type': 'operation',
                'operator': '&&',
                'name': and_id,
                'bit_width': 1
            })
            self.graph.add_node(and_node)

            edge1 = Edge(current_signal, and_node, data={'type': 'left_operand', 'position': 'left'})
            self.graph.add_edge(edge1)
            edge2 = Edge(write_stage_valid_node, and_node, data={'type': 'right_operand', 'position': 'right'})
            self.graph.add_edge(edge2)

            current_signal = and_node

        # Connect the forwarding enable to the mux select
        select_edge = Edge(current_signal, mux_node, data={
            'type': 'mux_select',
            'selects_input': forwarding_input,
            'stage': hazard.write_stage
        })
        self.graph.add_edge(select_edge)

        # Track this forwarding source
        mux_node.data['forwarding_sources'].append({
            'stage': hazard.write_stage,
            'stage_name': hazard.write_stage_name,
            'input_index': forwarding_input,
            'select_signal': current_signal.id
        })

        print(f"  Created forwarding path from {hazard.write_stage_name} to {hazard.read_stage_name}")
        print(f"    Forwarding value: {forwarding_value.id}")
        print(f"    Select signal: {current_signal.id}")

        return True

    def resolve_hazard(self, hazard: DetectedHazard) -> bool:
        """Resolve a hazard based on its chosen strategy."""
        if hazard.resolution in (HazardResolutionStrategy.STALL, HazardResolutionStrategy.STALL_ENABLE_ONLY):
            return self.resolve_with_stalling(hazard)
        elif hazard.resolution == HazardResolutionStrategy.BYPASS:
            return self.resolve_with_bypassing(hazard)
        elif hazard.resolution == HazardResolutionStrategy.NONE:
            print(f"No resolution chosen for: {hazard}")
            return True
        else:
            print(f"Unknown resolution strategy: {hazard.resolution}")
            return False

    def add_control_hazard_handling(self, branch_conditions, jump_types=None, pc_mux_id=None, resolution_stage=None, stage_order_override=None):
        """
        Add control hazard resolution for branches and jumps.

        Generic implementation that:
        1. Detects which pipeline stage branches actually resolve in
        2. Flushes all earlier stages when a branch is taken
        3. Allows the resolution stage and later stages to continue

        Args:
            branch_conditions: Dict mapping branch type to condition node IDs.
                               Keys are branch instruction names (e.g., 'beq', 'bc'),
                               values are the condition signal names (e.g., 'beq_res', 'bc_take_branch').
                               Required parameter - no hardcoded defaults.
            jump_types: List of unconditional jump instruction names (e.g., ['jal', 'jalr'] for RISC-V,
                        ['b', 'bl'] for OpenPOWER). These always cause a flush when enabled.
                        If None, no unconditional jumps are handled.
            pc_mux_id: ID of the PC mux node (optional)
            resolution_stage: Explicitly specify branch resolution stage (e.g., 'Execute')
            stage_order_override: Explicit list of stage names in order (e.g., ['Decode', 'Execute', 'Memory', 'Writeback'])
        """
        print("\n" + "=" * 70)
        print("ADDING CONTROL HAZARD HANDLING (PIPELINE FLUSH)")
        print("=" * 70)

        print(f"  Branch conditions: {branch_conditions}")
        print(f"  Jump types: {jump_types}")

        # Find the validity signals for each stage and determine stage ordering
        valid_signals = {}

        for node_id, node in sorted(self.graph.nodes.items()):
            if node_id.startswith('PIPE_') and node_id.endswith('_valid_PIPE'):
                # Extract stage name (e.g., PIPE_Execute_valid_PIPE -> Execute)
                stage = node_id.replace('PIPE_', '').replace('_valid_PIPE', '')
                valid_signals[stage] = node

        # Use explicit stage order if provided, otherwise infer from pipe_time (or uarch_time)
        if stage_order_override:
            stage_names = [s for s in stage_order_override if s in valid_signals]
            print(f"  Using explicitly provided stage order: {stage_names}")
        else:
            # Infer from pipe_time (preferred) or uarch_time (fallback)
            stage_order = []
            for stage, node in sorted(valid_signals.items()):
                ptime = getattr(node, 'pipe_time', None)
                utime = getattr(node, 'uarch_time', None)
                if ptime is None:
                    ptime = utime
                if ptime is not None:
                    stage_order.append((stage, ptime))
                    print(f"  Using {'pipe_time' if getattr(node, 'pipe_time', None) is not None else 'uarch_time'} for {stage}: {ptime}")
            stage_order.sort(key=lambda x: x[1])
            stage_names = [stage for stage, _ in stage_order]

            # Fallback: if no timing info available, use alphabetical order as heuristic
            # This tends to work because: Decode < Execute < Memory/MemoryWriteback < Writeback
            if not stage_names:
                stage_names = sorted(valid_signals.keys())
                print(f"  WARNING: No timing info available, using alphabetical order")

        print(f"  Found validity signals: {list(valid_signals.keys())}")
        print(f"  Pipeline stage order: {stage_names}")

        # Step 1: Determine which stage branch conditions are in
        # Look for branch condition nodes in the graph
        branch_types = list(branch_conditions.keys())
        print(f"  Branch types to look for: {branch_types}")

        # Use explicitly provided resolution_stage if given
        if resolution_stage:
            print(f"  Using explicitly provided resolution stage: {resolution_stage}")

        # Check each stage for branch condition nodes (only if not explicitly provided)
        if not resolution_stage:
            for stage_name in stage_names:
                # Look for pipelined branch condition in this stage
                # Pattern: PIPE_StageName_branchtype_res_PIPE or just branchtype_res
                for branch_type in branch_types:
                    cond_id = branch_conditions.get(branch_type, f"{branch_type}_res") if branch_conditions else f"{branch_type}_res"

                    # Check if condition exists in graph (unpipelined, original)
                    if cond_id in self.graph.nodes:
                        cond_node = self.graph.nodes[cond_id]
                        # Check if it has been pipelined to this stage
                        pipelined_id = f"PIPE_{stage_name}_{cond_id}_PIPE"
                        if pipelined_id in self.graph.nodes:
                            resolution_stage = stage_name
                            print(f"  Branch conditions pipelined to {resolution_stage} stage")
                            break
                        # Check if it's used directly (not pipelined yet)
                        elif resolution_stage is None:
                            # Find which stage uses it by looking at enable nodes
                            for node_id in sorted(self.graph.nodes.keys()):
                                if f"PIPE_{stage_name}_{branch_type}_enable_PIPE" in node_id:
                                    # This stage has the enable, check if condition is accessible
                                    resolution_stage = stage_name
                                    print(f"  Branch conditions found in {resolution_stage} stage (unpipelined)")
                                    break

                if resolution_stage:
                    break

        if not resolution_stage:
            # Default: use second stage (after Decode) where branch conditions are typically resolved
            # This uses stage ordering rather than name matching
            if len(stage_names) > 1:
                resolution_stage = stage_names[1]  # Second stage (after first stage)
                print(f"  Branch resolution stage determined by ordering: {resolution_stage}")
            else:
                print(f"  WARNING: Could not determine branch resolution stage")

        if not resolution_stage or resolution_stage not in valid_signals:
            print(f"  ERROR: Resolution stage {resolution_stage} not found, cannot add control hazard handling")
            return

        # Step 2: Find all branch/jump enables in the resolution stage
        branch_enables = []
        jump_enables = []

        # Helper to extract instruction name from enable signal
        # Pattern: PIPE_ResolutionStage_{instr_name}_enable_PIPE
        prefix = f'PIPE_{resolution_stage}_'
        suffix = '_enable_PIPE'

        for node_id in sorted(self.graph.nodes.keys()):
            # Look for enables in resolution stage
            if node_id.startswith(prefix) and node_id.endswith(suffix):
                # Extract exact instruction name
                instr_name = node_id[len(prefix):-len(suffix)]

                if instr_name in branch_types:
                    branch_enables.append(node_id)
                elif jump_types and instr_name in jump_types:
                    jump_enables.append(node_id)

        print(f"  {resolution_stage} stage branch enables: {branch_enables}")
        print(f"  {resolution_stage} stage jump enables: {jump_enables}")

        # Step 3: Create taken detection for each instruction type
        # For JAL/JALR: always taken when enabled
        # For branches: taken when enabled AND condition is true

        flush_components = []

        # Add jump enables (always cause flush - unconditional jumps)
        for enable_id in jump_enables:
            enable_node = self.graph.nodes.get(enable_id)
            if enable_node:
                flush_components.append(enable_node)
                print(f"    Flush on: {enable_id} (jump always taken)")

        # For branches, detect taken: enable && condition
        for branch_type in branch_types:
            # Get the branch condition node first to determine timing
            # First try pipelined version in resolution stage
            cond_node_id = f"PIPE_{resolution_stage}_{branch_type}_res_PIPE"
            cond_node = self.graph.nodes.get(cond_node_id)

            # If not pipelined, try original
            if not cond_node:
                cond_node_id = branch_conditions.get(branch_type, f"{branch_type}_res") if branch_conditions else f"{branch_type}_res"
                cond_node = self.graph.nodes.get(cond_node_id)

            # Determine the pipe_time of the condition (or uarch_time as fallback)
            # The condition depends on r1/r2, so find their pipe_time
            cond_time = None
            if cond_node:
                cond_time = getattr(cond_node, 'pipe_time', None)
                if cond_time is None:
                    cond_time = getattr(cond_node, 'uarch_time', None)
            if cond_time is None:
                # Check predecessors of the condition for their pipe_time
                # The condition typically depends on r1/r2 comparisons
                for edge in sorted(self.graph.edges.values(), key=lambda e: (e.source.id, e.target.id)):
                    if edge.target == cond_node:
                        src = edge.source
                        src_time = getattr(src, 'pipe_time', None)
                        if src_time is None:
                            src_time = getattr(src, 'uarch_time', None)
                        if src_time is not None:
                            cond_time = src_time
                            break

            # Find the corresponding enable at the same pipe_time as the condition
            # For combined stages with multiple depths, we need to match timing
            enable_node = None
            enable_id = None

            # First try the simple pattern
            simple_enable_id = f"PIPE_{resolution_stage}_{branch_type}_enable_PIPE"
            simple_enable_node = self.graph.nodes.get(simple_enable_id)

            if simple_enable_node:
                simple_time = getattr(simple_enable_node, 'pipe_time', None)
                if simple_time is None:
                    simple_time = getattr(simple_enable_node, 'uarch_time', None)

                # If times match, use this enable
                if simple_time == cond_time or cond_time is None:
                    enable_node = simple_enable_node
                    enable_id = simple_enable_id
                else:
                    # Times don't match - look for a deeper pipelined enable
                    # For combined stages, look for PIPE_Stage_PIPE_Stage_enable_PIPE_PIPE pattern
                    # Find the deepest enable (closest to cond_time) for this branch type
                    deepest_enable = None
                    deepest_time = simple_time

                    for node_id, node in sorted(self.graph.nodes.items()):
                        if (f'_{branch_type}_enable_' in node_id and
                            node.data.get('type') == 'pipeline_register'):
                            node_time = getattr(node, 'pipe_time', None)
                            if node_time is None:
                                node_time = getattr(node, 'uarch_time', None)
                            if node_time is not None:
                                if node_time == cond_time:
                                    # Exact match found
                                    enable_node = node
                                    enable_id = node_id
                                    print(f"    Using matched-timing enable: {enable_id} (time={node_time})")
                                    break
                                elif node_time > deepest_time:
                                    # Keep track of deepest enable we've seen
                                    deepest_enable = node
                                    deepest_time = node_time

                    # If no exact match, use the deepest available enable
                    if not enable_node:
                        if deepest_enable and deepest_time > simple_time:
                            enable_node = deepest_enable
                            enable_id = deepest_enable.id
                            print(f"    Using deepest available enable: {enable_id} (time={deepest_time}, cond_time={cond_time})")
                        else:
                            print(f"    WARNING: Could not find enable at time={cond_time} for {branch_type}, using time={simple_time}")
                            enable_node = simple_enable_node
                            enable_id = simple_enable_id

            if not enable_node:
                # No enable found - for branches without register writes (like MIPS beq/bne),
                # use the condition directly as the flush component
                if cond_node:
                    print(f"    Flush on: {cond_node.id} (branch condition, no enable)")
                    flush_components.append(cond_node)
                continue

            if not cond_node:
                print(f"    WARNING: Branch condition for {branch_type} not found, using enable-only flush")
                flush_components.append(enable_node)
                continue

            # Create AND node to detect taken branches: branch_taken = enable && condition
            taken_id = f"{branch_type}_branch_taken_{resolution_stage.lower()}"
            taken_node = Node(taken_id, data={
                'type': 'operation',
                'operator': '&&',
                'name': taken_id,
                'display_name': f'{branch_type.upper()} branch taken ({resolution_stage} stage)',
                'bit_width': 1
            })
            self.graph.add_node(taken_node)

            # Connect enable -> AND (left operand)
            edge1 = Edge(enable_node, taken_node, data={
                'type': 'left_operand',
                'position': 'left'
            })
            self.graph.add_edge(edge1)

            # Connect condition -> AND (right operand)
            edge2 = Edge(cond_node, taken_node, data={
                'type': 'right_operand',
                'position': 'right'
            })
            self.graph.add_edge(edge2)

            flush_components.append(taken_node)
            print(f"    Flush on: {taken_id} = {enable_node.id} && {cond_node.id}")

        if not flush_components:
            print(f"  No branch/jump enables found in {resolution_stage} stage, skipping control hazard handling")
            return

        # Step 4: Create flush signal as OR of all components
        # flush = jal_enable || jalr_enable || beq_taken || ...
        # AND gate with resolution stage validity to ensure we only flush for valid instructions
        # (bubbles in Execute stage should NOT trigger flushes)

        # First, AND each component with resolution stage validity
        # CRITICAL FIX: Also gate with NOT(load_use_stall) to prevent branches
        # from firing during load-use stalls. During a load-use stall:
        # - The stall is detected combinationally
        # - But PIPE_Execute_valid_PIPE is a register, still TRUE from previous cycle
        # - Branch operands may be wrong (old values, not yet forwarded)
        # - Without this gating, wrong branch decisions override the stall
        valid_gated_components = []
        resolution_valid = valid_signals[resolution_stage]

        # Look for load_use_stall signals created by hazard resolution
        load_use_stall_signals = []
        for node_id in sorted(self.graph.nodes.keys()):
            # Pattern: load_use_stall_{Stage}_{rs_name}
            if node_id.startswith('load_use_stall_') and not any(x in node_id for x in ['_rd_en', '_unavail', '_valid', '_we']):
                load_use_stall_signals.append(self.graph.nodes[node_id])
                print(f"    Found load_use_stall signal: {node_id}")

        # If load_use_stall signals exist, create combined validity signal
        if load_use_stall_signals:
            print(f"    Gating branch taken with NOT(load_use_stall) signals")

            # Create NOT signals for each stall
            # Use resolution_stage prefix to avoid ID collisions across pipelines/cores
            not_stall_nodes = []
            for stall_node in load_use_stall_signals:
                not_id = f"{resolution_stage}_{stall_node.id}_not"
                # Reuse existing node if already created (e.g., from a previous call)
                if not_id in self.graph.nodes:
                    not_stall_nodes.append(self.graph.nodes[not_id])
                    continue
                not_node = Node(not_id, data={
                    'type': 'operation',
                    'operator': '!',
                    'name': not_id,
                    'bit_width': 1
                })
                self.graph.add_node(not_node)
                edge = Edge(stall_node, not_node, data={'type': 'operand'})
                self.graph.add_edge(edge)
                not_stall_nodes.append(not_node)

            # AND all NOT(stall) signals with resolution_valid
            combined_valid = resolution_valid
            for i, not_stall in enumerate(not_stall_nodes):
                and_id = f"{resolution_stage}_valid_with_stall_{i}"
                and_node = Node(and_id, data={
                    'type': 'operation',
                    'operator': '&&',
                    'name': and_id,
                    'bit_width': 1
                })
                self.graph.add_node(and_node)
                edge1 = Edge(combined_valid, and_node, data={'type': 'left_operand', 'position': 'left'})
                self.graph.add_edge(edge1)
                edge2 = Edge(not_stall, and_node, data={'type': 'right_operand', 'position': 'right'})
                self.graph.add_edge(edge2)
                combined_valid = and_node

            resolution_valid = combined_valid
            print(f"    Created combined validity signal: {resolution_valid.id}")

        for component in flush_components:
            # Create: component && resolution_stage_valid
            gated_id = f"{component.id}_valid_gated"
            gated_node = Node(gated_id, data={
                'type': 'operation',
                'operator': '&&',
                'name': gated_id,
                'bit_width': 1
            })
            self.graph.add_node(gated_node)

            # Connect component -> AND left
            edge1 = Edge(component, gated_node, data={
                'type': 'left_operand',
                'position': 'left'
            })
            self.graph.add_edge(edge1)

            # Connect resolution_stage_valid -> AND right
            edge2 = Edge(resolution_valid, gated_node, data={
                'type': 'right_operand',
                'position': 'right'
            })
            self.graph.add_edge(edge2)

            valid_gated_components.append(gated_node)

        # Now OR all the valid-gated enables
        if len(valid_gated_components) == 1:
            flush_signal = valid_gated_components[0]
        else:
            # Create OR tree
            current_or = valid_gated_components[0]
            for i, component in enumerate(valid_gated_components[1:], 1):
                or_id = f"flush_or_{i}"
                or_node = Node(or_id, data={
                    'type': 'operation',
                    'operator': '||',
                    'name': or_id,
                    'bit_width': 1
                })
                self.graph.add_node(or_node)

                # Connect current OR result
                edge1 = Edge(current_or, or_node, data={
                    'type': 'left_operand',
                    'position': 'left'
                })
                self.graph.add_edge(edge1)

                # Connect next component
                edge2 = Edge(component, or_node, data={
                    'type': 'right_operand',
                    'position': 'right'
                })
                self.graph.add_edge(edge2)

                current_or = or_node
            flush_signal = current_or

        # Rename the final flush signal
        flush_signal.id = 'control_hazard_flush'
        flush_signal.data['name'] = 'control_hazard_flush'
        flush_signal.data['display_name'] = 'Pipeline flush on control hazard'
        self.graph.nodes['control_hazard_flush'] = flush_signal

        print(f"  Created flush signal: control_hazard_flush")

        # Step 4: Update PC mux to use validity-gated select signals
        # DISABLED: The branch/jump target muxes (e.g., beq_res_branch_dest_pc_add_4)
        # already encode the branch decision. When a branch is not taken, the mux
        # outputs PC+4, so selecting it has no effect on the PC recovery path.
        # When a branch is taken, control_hazard_flush triggers and the correct
        # target is selected. Gating with validity here creates timing issues.
        #
        # TODO: If invalid instructions in Memory stage cause pc_wr_mux to output
        # garbage, a different approach is needed - perhaps ensuring the default
        # pc_wr_mux output is always valid (pc_add_4).
        if False and pc_mux_id:
            pc_mux_node = self.graph.nodes.get(pc_mux_id)
            if pc_mux_node:
                print(f"\n  Updating {pc_mux_id} to use validity-gated select signals...")

                # Helper function to extract stage name from pipelined signal
                def get_stage_name(pipelined_id):
                    """
                    Extract the outermost stage name from a pipelined signal.
                    e.g., PIPE_Memory_PIPE_Execute_beq_enable_PIPE_PIPE -> Memory
                    e.g., PIPE_Execute_jal_enable_PIPE -> Execute
                    """
                    if pipelined_id.startswith('PIPE_'):
                        rest = pipelined_id[5:]  # Skip 'PIPE_'
                        if '_' in rest:
                            return rest.split('_')[0]
                    return None

                # Find all mux_select edges and create validity-gated versions
                edges_to_update = []
                for edge in pc_mux_node.incoming_edges:
                    if edge.data.get('type') == 'mux_select':
                        source_id = edge.source.id
                        source_node = edge.source

                        # Determine which stage this select signal is from
                        select_stage = get_stage_name(source_id)
                        if not select_stage:
                            print(f"    Skipping non-pipelined select: {source_id}")
                            continue

                        # Find the validity signal for this stage
                        validity_id = f"PIPE_{select_stage}_valid_PIPE"
                        validity_node = self.graph.nodes.get(validity_id)

                        if not validity_node:
                            print(f"    No validity signal for stage {select_stage}, skipping: {source_id}")
                            continue

                        # Create a validity-gated version of this select signal
                        # gated = enable && stage_valid
                        gated_id = f"{source_id}_valid_gated"

                        # Check if already exists
                        if gated_id in self.graph.nodes:
                            gated_node = self.graph.nodes[gated_id]
                            print(f"    Reusing existing gated signal: {gated_id}")
                        else:
                            # Create AND node
                            gated_node = Node(gated_id, data={
                                'type': 'operation',
                                'operator': '&&',
                                'name': gated_id,
                                'display_name': f'{source_id} gated with {select_stage} validity',
                                'bit_width': 1
                            })
                            self.graph.add_node(gated_node)

                            # Connect enable -> AND left
                            edge1 = Edge(source_node, gated_node, data={
                                'type': 'left_operand',
                                'position': 'left'
                            })
                            self.graph.add_edge(edge1)

                            # Connect validity -> AND right
                            edge2 = Edge(validity_node, gated_node, data={
                                'type': 'right_operand',
                                'position': 'right'
                            })
                            self.graph.add_edge(edge2)
                            print(f"    Created gated signal: {gated_id} = {source_id} && {validity_id}")

                        edges_to_update.append((edge, gated_node))

                # Update the edges
                for old_edge, gated_node in edges_to_update:
                    # Create new edge from gated node to pc_mux
                    new_edge = Edge(gated_node, pc_mux_node, data=old_edge.data.copy())
                    self.graph.add_edge(new_edge)

                    # Remove old edge
                    self.graph.remove_edge(old_edge.id)
                    print(f"    Updated select edge: {gated_node.id} -> {pc_mux_id}")

                print(f"  Updated {len(edges_to_update)} select signals in {pc_mux_id}")

        # Step 5: Gate validity signal inputs with NOT flush
        # When flush is active:
        # - All stages BEFORE the resolution stage must be invalidated
        # - The resolution stage and later stages continue normally

        # Determine which stages to flush (all before resolution_stage)
        resolution_index = stage_names.index(resolution_stage)
        stages_to_flush = stage_names[:resolution_index]

        print(f"  Resolution stage: {resolution_stage} (index {resolution_index})")
        print(f"  Stages to flush: {stages_to_flush}")

        # Create NOT flush
        not_flush_id = 'control_hazard_flush_not'
        not_flush = Node(not_flush_id, data={
            'type': 'operation',
            'operator': '!',
            'name': not_flush_id,
            'bit_width': 1
        })
        self.graph.add_node(not_flush)

        edge = Edge(flush_signal, not_flush, data={'type': 'operand'})
        self.graph.add_edge(edge)

        print(f"  Created NOT flush signal: {not_flush_id}")

        # Step 6: Modify validity signal inputs to AND with NOT flush for stages to flush
        # Find edges that feed into validity signals and insert AND gate

        for stage_to_flush in stages_to_flush:
            if stage_to_flush not in valid_signals:
                continue

            stage_valid = valid_signals[stage_to_flush]

            # Find the current input to this stage's validity
            current_input_edge = None
            for edge in stage_valid.incoming_edges:
                if edge.data.get('type') == 'pipeline_input':
                    current_input_edge = edge
                    break

            if current_input_edge:
                # Create AND gate: current_input && NOT flush
                and_id = f'PIPE_{stage_to_flush}_valid_not_flush'
                and_node = Node(and_id, data={
                    'type': 'operation',
                    'operator': '&&',
                    'name': and_id,
                    'bit_width': 1
                })
                self.graph.add_node(and_node)

                # Connect current input source -> AND left
                edge1 = Edge(current_input_edge.source, and_node, data={
                    'type': 'left_operand',
                    'position': 'left'
                })
                self.graph.add_edge(edge1)

                # Connect NOT flush -> AND right
                edge2 = Edge(not_flush, and_node, data={
                    'type': 'right_operand',
                    'position': 'right'
                })
                self.graph.add_edge(edge2)

                # Remove old edge and create new one from AND to stage valid
                current_input_edge.remove_from_nodes()
                if current_input_edge.id in self.graph.edges:
                    del self.graph.edges[current_input_edge.id]

                new_edge = Edge(and_node, stage_valid, data={
                    'type': 'pipeline_input',
                    'pipeline_component': True
                })
                self.graph.add_edge(new_edge)

                print(f"  {stage_to_flush} validity gated with NOT flush")

        # Step 6b: Also gate PIPE_*_valid_and_not_stall signals with NOT flush
        # These signals control what value moves INTO the next stage
        # For example, when Execute flushes Decode, PIPE_Execute_valid_and_not_stall
        # must also be gated so the Decode instruction doesn't move into Execute as valid
        for stage_to_flush in stages_to_flush:
            # Find the next stage in pipeline order
            stage_idx = stage_names.index(stage_to_flush) if stage_to_flush in stage_names else -1
            if stage_idx < 0 or stage_idx + 1 >= len(stage_names):
                continue

            next_stage = stage_names[stage_idx + 1]
            valid_and_not_stall_id = f"PIPE_{next_stage}_valid_and_not_stall"

            if valid_and_not_stall_id not in self.graph.nodes:
                # Fallback: When valid_and_not_stall doesn't exist (e.g., when write_read_fwd
                # eliminates all stalls), directly gate the valid_PIPE's input with NOT flush.
                # This ensures flushed instructions are properly invalidated.
                valid_pipe_id = f"PIPE_{next_stage}_valid_PIPE"
                if valid_pipe_id in self.graph.nodes:
                    valid_pipe = self.graph.nodes[valid_pipe_id]

                    # Find the current pipeline_input edge to valid_PIPE
                    current_input_edge = None
                    for edge in valid_pipe.incoming_edges:
                        if edge.data.get('type') == 'pipeline_input':
                            current_input_edge = edge
                            break

                    if current_input_edge:
                        # Check if already gated (avoid double-gating)
                        gated_id = f"PIPE_{next_stage}_valid_input_not_flush"
                        if gated_id not in self.graph.nodes:
                            # Create AND gate: current_input && NOT flush
                            gated_node = Node(gated_id, data={
                                'type': 'operation',
                                'operator': '&&',
                                'name': gated_id,
                                'bit_width': 1
                            })
                            self.graph.add_node(gated_node)

                            # Connect current input source -> AND left
                            edge1 = Edge(current_input_edge.source, gated_node, data={
                                'type': 'left_operand',
                                'position': 'left'
                            })
                            self.graph.add_edge(edge1)

                            # Connect NOT flush -> AND right
                            edge2 = Edge(not_flush, gated_node, data={
                                'type': 'right_operand',
                                'position': 'right'
                            })
                            self.graph.add_edge(edge2)

                            # Remove old edge and create new one from AND to valid_PIPE
                            current_input_edge.remove_from_nodes()
                            if current_input_edge.id in self.graph.edges:
                                del self.graph.edges[current_input_edge.id]

                            new_edge = Edge(gated_node, valid_pipe, data={
                                'type': 'pipeline_input',
                                'pipeline_component': True
                            })
                            self.graph.add_edge(new_edge)

                            print(f"  {next_stage} valid_PIPE input gated with NOT flush (no stall signal)")
                continue

            valid_and_not_stall = self.graph.nodes[valid_and_not_stall_id]

            # Find the outgoing edge to the next stage's valid signal
            outgoing_edge = None
            for edge in valid_and_not_stall.outgoing_edges:
                if edge.target.id == f"PIPE_{next_stage}_valid_PIPE":
                    outgoing_edge = edge
                    break

            if not outgoing_edge:
                # The valid_and_not_stall feeds directly into valid
                # We need to insert an AND gate between them
                print(f"    Warning: No outgoing edge from {valid_and_not_stall_id}")
                continue

            # Create new AND gate: valid_and_not_stall && NOT flush
            gated_id = f"PIPE_{next_stage}_valid_and_not_stall_not_flush"
            gated_node = Node(gated_id, data={
                'type': 'operation',
                'operator': '&&',
                'name': gated_id,
                'bit_width': 1
            })
            self.graph.add_node(gated_node)

            # Connect valid_and_not_stall -> new AND left
            edge1 = Edge(valid_and_not_stall, gated_node, data={
                'type': 'left_operand',
                'position': 'left'
            })
            self.graph.add_edge(edge1)

            # Connect NOT flush -> new AND right
            edge2 = Edge(not_flush, gated_node, data={
                'type': 'right_operand',
                'position': 'right'
            })
            self.graph.add_edge(edge2)

            # Remove old edge from valid_and_not_stall to valid signal
            target_valid = outgoing_edge.target
            outgoing_edge.remove_from_nodes()
            if outgoing_edge.id in self.graph.edges:
                del self.graph.edges[outgoing_edge.id]

            # Create new edge from gated AND to valid signal
            new_edge = Edge(gated_node, target_valid, data={
                'type': 'pipeline_input',
                'pipeline_component': True
            })
            self.graph.add_edge(new_edge)

            print(f"  {next_stage} stage input (valid_and_not_stall) gated with NOT flush")

        # Step 6c: For pipelines with no stages before resolution (e.g., 2-stage pipelines),
        # we still need to gate the resolution stage's valid_and_not_stall with NOT flush.
        # This ensures that when a branch is taken, the speculatively fetched instruction
        # in the PIPE register is invalidated.
        if len(stages_to_flush) == 0 and resolution_stage:
            valid_and_not_stall_id = f"PIPE_{resolution_stage}_valid_and_not_stall"
            if valid_and_not_stall_id in self.graph.nodes:
                gated_id = f"PIPE_{resolution_stage}_valid_and_not_stall_not_flush"

                # Check if already gated (shouldn't be, but be safe)
                if gated_id not in self.graph.nodes:
                    valid_and_not_stall = self.graph.nodes[valid_and_not_stall_id]

                    # Find the outgoing edge to the valid signal
                    outgoing_edge = None
                    for edge in valid_and_not_stall.outgoing_edges:
                        if edge.target.id == f"PIPE_{resolution_stage}_valid_PIPE":
                            outgoing_edge = edge
                            break

                    if outgoing_edge:
                        # Create new AND gate: valid_and_not_stall && NOT flush
                        gated_node = Node(gated_id, data={
                            'type': 'operation',
                            'operator': '&&',
                            'name': gated_id,
                            'bit_width': 1
                        })
                        self.graph.add_node(gated_node)

                        # Connect valid_and_not_stall -> new AND left
                        edge1 = Edge(valid_and_not_stall, gated_node, data={
                            'type': 'left_operand',
                            'position': 'left'
                        })
                        self.graph.add_edge(edge1)

                        # Connect NOT flush -> new AND right
                        edge2 = Edge(not_flush, gated_node, data={
                            'type': 'right_operand',
                            'position': 'right'
                        })
                        self.graph.add_edge(edge2)

                        # Remove old edge and create new one
                        target_valid = outgoing_edge.target
                        outgoing_edge.remove_from_nodes()
                        if outgoing_edge.id in self.graph.edges:
                            del self.graph.edges[outgoing_edge.id]

                        new_edge = Edge(gated_node, target_valid, data={
                            'type': 'pipeline_input',
                            'pipeline_component': True
                        })
                        self.graph.add_edge(new_edge)

                        print(f"  {resolution_stage} stage valid_and_not_stall gated with NOT flush (no prior stages)")
            else:
                # Fallback: When valid_and_not_stall doesn't exist (e.g., write_read_fwd eliminated
                # all stalls), directly gate the valid_PIPE input with NOT flush.
                valid_pipe_id = f"PIPE_{resolution_stage}_valid_PIPE"
                if valid_pipe_id in self.graph.nodes:
                    valid_pipe = self.graph.nodes[valid_pipe_id]

                    # Find the current pipeline_input edge to valid_PIPE
                    current_input_edge = None
                    for edge in valid_pipe.incoming_edges:
                        if edge.data.get('type') == 'pipeline_input':
                            current_input_edge = edge
                            break

                    if current_input_edge:
                        gated_id = f"PIPE_{resolution_stage}_valid_input_not_flush"
                        if gated_id not in self.graph.nodes:
                            # Create AND gate: current_input && NOT flush
                            gated_node = Node(gated_id, data={
                                'type': 'operation',
                                'operator': '&&',
                                'name': gated_id,
                                'bit_width': 1
                            })
                            self.graph.add_node(gated_node)

                            # Connect current input source -> AND left
                            edge1 = Edge(current_input_edge.source, gated_node, data={
                                'type': 'left_operand',
                                'position': 'left'
                            })
                            self.graph.add_edge(edge1)

                            # Connect NOT flush -> AND right
                            edge2 = Edge(not_flush, gated_node, data={
                                'type': 'right_operand',
                                'position': 'right'
                            })
                            self.graph.add_edge(edge2)

                            # Remove old edge and create new one from AND to valid_PIPE
                            current_input_edge.remove_from_nodes()
                            if current_input_edge.id in self.graph.edges:
                                del self.graph.edges[current_input_edge.id]

                            new_edge = Edge(gated_node, valid_pipe, data={
                                'type': 'pipeline_input',
                                'pipeline_component': True
                            })
                            self.graph.add_edge(new_edge)

                            print(f"  {resolution_stage} valid_PIPE input gated with NOT flush (no stall signal, no prior stages)")

        # Step 7: Prevent stalled registers from being held when flushing
        # When flushing, pipeline registers should update to invalidate flushed instructions
        # Current gating: registers held when stalling
        # New gating: registers held when (stalling AND NOT flushing)
        #
        # IMPORTANT: We do NOT combine stall controllers. Each stall controller
        # gates only its own registers. For example:
        # - PIPE_Decode_stall_ctrl gates only Fetch, Decode, and Execute registers (for RAW hazards)
        # - PIPE_Memory_stall_ctrl gates only Fetch, Decode, Execute, and Memory registers (for memory latency)
        # Combining them would cause all stages to stall when any stage stalls.

        # Find all nodes with stall edges
        stall_edges = []
        for edge in sorted(self.graph.edges.values(), key=lambda e: (e.source.id, e.target.id)):
            if edge.data.get('type') == 'stall':
                stall_edges.append(edge)

        if stall_edges:
            # Find all unique stall controllers - sorted for determinism
            unique_stall_ctrls = sorted(set(e.source for e in stall_edges), key=lambda c: c.id)
            print(f"  Found {len(unique_stall_ctrls)} unique stall controller(s): {[c.id for c in unique_stall_ctrls]}")

            # Create a separate {controller}_and_not_flush for each stall controller
            # This preserves the original register-to-controller mapping
            ctrl_to_and_node = {}
            for ctrl in unique_stall_ctrls:
                and_id = f'{ctrl.id}_and_not_flush'
                and_node = Node(and_id, data={
                    'type': 'operation',
                    'operator': '&&',
                    'name': and_id,
                    'bit_width': 1
                })
                self.graph.add_node(and_node)

                # Connect ctrl -> AND left
                edge1 = Edge(ctrl, and_node, data={
                    'type': 'left_operand',
                    'position': 'left'
                })
                self.graph.add_edge(edge1)

                # Connect NOT flush -> AND right
                edge2 = Edge(not_flush, and_node, data={
                    'type': 'right_operand',
                    'position': 'right'
                })
                self.graph.add_edge(edge2)

                ctrl_to_and_node[ctrl] = and_node
                print(f"  Created {and_id} for stall controller {ctrl.id}")

            # Replace each stall edge with the appropriate controller's _and_not_flush node
            for stall_edge in stall_edges:
                # Skip edges marked to preserve raw stall behavior (e.g., for Writeback_valid)
                # These edges need the RAW stall signal, not stall_and_not_flush
                if stall_edge.data.get('skip_flush_transform'):
                    print(f"  Preserving RAW stall for {stall_edge.target.id} (skip_flush_transform=True)")
                    continue

                source_ctrl = stall_edge.source
                target_node = stall_edge.target
                and_node = ctrl_to_and_node[source_ctrl]

                stall_edge.remove_from_nodes()
                if stall_edge.id in self.graph.edges:
                    del self.graph.edges[stall_edge.id]

                new_stall_edge = Edge(and_node, target_node, data={
                    'type': 'stall',
                    'description': f'Gate register update: hold on {source_ctrl.id} stall, update on flush'
                })
                self.graph.add_edge(new_stall_edge)

                print(f"  Register gated: hold on ({source_ctrl.id} AND NOT flush) for {target_node.id}")

        print("  Control hazard handling added successfully")

    def gate_write_enables_with_validity(self):
        """
        Gate all write enables for ISA state with instruction validity signals.
        This ensures that flushed instructions don't corrupt state.

        Unified approach for both indexed (RF) and non-indexed (LR, CTR, CR) ISA state:
        1. Find all ISA state write nodes (by checking node type)
        2. For each write node, find the mux feeding it (by tracing incoming edges)
        3. For each mux, find select signals and gate them with stage validity
        """
        print("\nGating write enables with validity signals...")

        # Find the validity signals for each stage
        valid_signals = {}
        for node_id, node in sorted(self.graph.nodes.items()):
            if node_id.startswith('PIPE_') and node_id.endswith('_valid_PIPE'):
                # Extract stage name (e.g., PIPE_Execute_valid_PIPE -> Execute)
                stage = node_id.replace('PIPE_', '').replace('_valid_PIPE', '')
                valid_signals[stage] = node

        # Build pipe_time -> stage validity mapping
        # Each validity node's pipe_time tells us which pipe_time corresponds
        # to that stage.
        pipe_time_to_valid = {}
        for stage_name, valid_node in valid_signals.items():
            ptime = getattr(valid_node, 'pipe_time', None)
            if ptime is not None:
                pipe_time_to_valid[ptime] = valid_node

        print(f"  Found validity signals: {sorted(valid_signals.keys())}")

        if not valid_signals:
            print("  WARNING: No validity signals found, skipping write enable gating")
            return

        # Find all ISA state write nodes and their feeding muxes
        # ISA state writes are identified by node type, not by name patterns
        isa_state_muxes = []  # List of (mux_node, mux_id, isa_state_name)

        for node_id, node in sorted(self.graph.nodes.items()):
            node_type = node.data.get('type')
            is_isa_state = (node_type == 'isa_state' or
                           node.data.get('is_arch_state_target') or
                           node_type == 'register_file_write')

            if not is_isa_state:
                continue

            # Find the mux feeding this ISA state write node
            for edge in sorted(node.incoming_edges, key=lambda e: e.source.id):
                source = edge.source
                source_type = source.data.get('type', '')
                # Check if source is a mux (by type or by having mux_select edges)
                is_mux = (source_type in ('mux', 'priority_mux') or
                          any(e.data.get('type') in ('mux_select', 'select') for e in sorted(source.incoming_edges, key=lambda e: e.source.id)))
                if is_mux:
                    # Extract ISA state name from write node
                    if node_id.endswith('_wr'):
                        isa_state_name = node_id[:-3]
                    elif node_id.endswith('_write'):
                        isa_state_name = node_id[:-6]
                    else:
                        isa_state_name = node_id
                    isa_state_muxes.append((source, source.id, isa_state_name))
                    break

        print(f"  Found {len(isa_state_muxes)} ISA state write muxes: {[m[1] for m in isa_state_muxes]}")

        # For each ISA state mux, find and gate its select signals
        gated_count = 0
        for mux_node, mux_id, isa_state_name in isa_state_muxes:
            # Find select signals feeding this mux
            for edge in sorted(mux_node.incoming_edges, key=lambda e: e.source.id):
                edge_type = edge.data.get('type', '')
                if 'select' not in edge_type and edge_type != 'mux_select':
                    continue

                source = edge.source
                source_id = source.id

                # Determine the stage from the select signal's pipe_time.
                # Every node gets a pipe_time during pipeline transforms;
                # look up the validity signal for that pipe_time.
                stage_valid = None
                ptime = getattr(source, 'pipe_time', None)
                if ptime is not None:
                    stage_valid = pipe_time_to_valid.get(ptime)

                if not stage_valid:
                    continue

                # Gate this select signal with stage validity
                gated_id = f"{source_id}_valid_gated"

                if gated_id in self.graph.nodes:
                    gated_node = self.graph.nodes[gated_id]
                else:
                    # Create gated version: select AND stage_valid
                    gated_node = Node(gated_id, data={
                        'type': 'logical_and',
                        'operator': '&&',
                        'width': 1,
                        'description': f'Validity-gated version of {source_id}',
                        'bit_width': 1
                    })
                    self.graph.add_node(gated_node)

                    # Connect select -> AND left operand
                    edge1 = Edge(source, gated_node, data={
                        'type': 'operand',
                        'operand_index': 0,
                        'description': 'left operand'
                    })
                    self.graph.add_edge(edge1)

                    # Connect stage_valid -> AND right operand
                    edge2 = Edge(stage_valid, gated_node, data={
                        'type': 'operand',
                        'operand_index': 1,
                        'description': 'right operand (validity)'
                    })
                    self.graph.add_edge(edge2)

                # Rewire: replace edge from select to mux with edge from gated_node
                self.graph.remove_edge(edge.id)
                new_edge = Edge(gated_node, mux_node, data=edge.data.copy())
                self.graph.add_edge(new_edge)

                gated_count += 1
                print(f"    Gated {mux_id}: {source_id} -> {gated_id}")

        print(f"  Gated {gated_count} select signals with validity")

    def add_memory_latency_stalls(self, memory_name: str = 'dmem') -> bool:
        """
        Add stall logic for variable latency memory operations.

        Uses the existing stall infrastructure from hazard resolution.
        Note: Pipeline register pipe_time represents INPUT time.
        To get stage time (when signals are computed), add +1.

        Args:
            memory_name: Name of the variable latency memory (default 'dmem')

        Returns:
            True if successfully added stalls, False otherwise
        """
        print(f"\nAdding memory latency stalls for {memory_name}...")

        memory = self.graph.nodes.get(memory_name)
        if not memory:
            print(f"  Memory {memory_name} not found")
            return False

        if not getattr(memory, 'variable_latency', False):
            print(f"  Memory {memory_name} is not variable latency, skipping")
            return True  # Not an error, just nothing to do

        # Get complete signal
        complete_signal_id = memory.data.get('complete_signal')
        if not complete_signal_id:
            print(f"  Memory {memory_name} missing complete signal")
            return False

        complete_signal = self.graph.nodes.get(complete_signal_id)
        if not complete_signal:
            print(f"  Complete signal {complete_signal_id} not found")
            return False

        # Find memory write_enable to determine when memory ops happen
        # First try validity-gated version (more accurate timing)
        write_enable_node = self.graph.nodes.get(f'{memory_name}_write_enable_valid_gated')
        if not write_enable_node:
            write_enable_node = self.graph.nodes.get(f'{memory_name}_write_enable')
        if not write_enable_node:
            print(f"  Could not find {memory_name}_write_enable")
            return False

        print(f"  Found write enable: {write_enable_node.id}")

        # Get memory_time from write_enable, but we need to add 1 because:
        # - write_enable's pipe_time is when its inputs are available
        # - Memory operations actually occur in the NEXT cycle (after registers capture inputs)
        memory_time = getattr(write_enable_node, 'pipe_time', None)
        if memory_time is None:
            memory_time = getattr(write_enable_node, 'uarch_time', None)

        # The write_enable signal's pipe_time reflects when store enables arrive
        # from Execute stage. Memory operations actually happen one stage later.
        # Increment by 1 to get the actual Memory stage time.
        if memory_time is not None:
            memory_time = memory_time + 1

        print(f"  Memory operations at pipe_time={memory_time} (write_enable + 1)")

        # Build stage_times map from pipeline registers
        # Note: register.pipe_time is INPUT time, so stage time = register.pipe_time + 1
        stage_names = set()
        for node_id, node in sorted(self.graph.nodes.items()):
            if (node.data.get('type') == 'pipeline_register' and
                node_id.startswith('PIPE_') and node_id.endswith('_PIPE')):
                parts = node_id.split('_')
                if len(parts) >= 3:
                    stage_names.add(parts[1])

        stage_times = {}
        for stage in sorted(stage_names):
            for node_id, node in sorted(self.graph.nodes.items()):
                if (node.data.get('type') == 'pipeline_register' and
                    node_id.startswith(f'PIPE_{stage}_') and node_id.endswith('_PIPE')):
                    ptime = getattr(node, 'pipe_time', None)
                    if ptime is None:
                        ptime = getattr(node, 'uarch_time', None)
                    if ptime is not None:
                        # Stage time = register input time + 1 (output is available after register)
                        stage_times[stage] = ptime + 1
                        break

        print(f"  Discovered stages (output times): {dict(sorted(stage_times.items()))}")

        # Find which stage the memory is in and the next stage for bubble injection
        memory_stage_name = None
        bubble_stage_name = None
        for stage, time in sorted(stage_times.items()):
            if time == memory_time:
                memory_stage_name = stage
            if time == memory_time + 1:
                bubble_stage_name = stage

        print(f"  Memory stage: {memory_stage_name} (time={memory_time}), Bubble stage: {bubble_stage_name}")

        # Find memory access enable signal
        access_enable_signal_id = memory.data.get('access_enable_signal')
        access_enable_node = None
        if access_enable_signal_id:
            access_enable_node = self.graph.nodes.get(access_enable_signal_id)

        if not access_enable_node:
            # Fallback to write_enable
            for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
                if (f'{memory_name}_write_enable' in node.id and
                    'valid_gated' in node.id):
                    access_enable_node = node
                    break
            if not access_enable_node:
                access_enable_node = self.graph.nodes.get(f'{memory_name}_write_enable')

        # Create stall condition: !complete && access_enable
        not_complete_id = f"{memory_name}_not_complete"
        if not_complete_id not in self.graph.nodes:
            not_complete = Node(
                node_id=not_complete_id,
                data={
                    'type': 'operation',
                    'operator': '!',
                    'name': not_complete_id,
                    'description': f'Stall while {memory_name} not complete',
                    'pipeline_component': True,
                    'bit_width': 1
                }
            )
            self.graph.add_node(not_complete)
            self.graph.add_edge(Edge(complete_signal, not_complete, data={
                'type': 'operand',
                'operand_position': 0
            }))
        else:
            not_complete = self.graph.nodes[not_complete_id]

        stall_signal = not_complete
        if access_enable_node:
            stall_and_id = f"{memory_name}_stall_condition"
            if stall_and_id not in self.graph.nodes:
                stall_and = Node(
                    node_id=stall_and_id,
                    data={
                        'type': 'operation',
                        'operator': '&&',
                        'name': stall_and_id,
                        'description': f'Stall: !complete && is_memory_op',
                        'pipeline_component': True,
                        'bit_width': 1
                    }
                )
                self.graph.add_node(stall_and)
                self.graph.add_edge(Edge(not_complete, stall_and, data={'type': 'operand', 'operand_index': 0}))
                self.graph.add_edge(Edge(access_enable_node, stall_and, data={'type': 'operand', 'operand_index': 1}))
                stall_signal = stall_and
            else:
                stall_signal = self.graph.nodes[stall_and_id]
            print(f"  Created stall condition: !{complete_signal_id} && {access_enable_node.id}")
        else:
            print(f"  Created stall condition: !{complete_signal_id}")

        # Find or create stall controller for memory stage
        stall_controller_id = f"PIPE_{memory_stage_name or 'Memory'}_stall_ctrl"

        stall_controller = self.graph.nodes.get(stall_controller_id)
        if stall_controller:
            # Add to existing controller via OR
            existing_inputs = [e.source for e in sorted(stall_controller.incoming_edges, key=lambda e: (e.source.id, e.target.id))
                             if e.data.get('type') == 'control']
            if existing_inputs and stall_signal not in existing_inputs:
                or_id = f"{stall_controller_id}_combined"
                if or_id not in self.graph.nodes:
                    or_node = Node(or_id, data={
                        'type': 'operation',
                        'operator': '||',
                        'name': or_id,
                        'bit_width': 1,
                        'pipeline_component': True
                    })
                    self.graph.add_node(or_node)
                    for idx, inp in enumerate(sorted(existing_inputs, key=lambda n: n.id)):
                        self.graph.add_edge(Edge(inp, or_node, data={'type': 'operand', 'operand_index': idx}))
                    self.graph.add_edge(Edge(stall_signal, or_node, data={'type': 'operand', 'operand_index': len(existing_inputs)}))
                    for e in sorted(stall_controller.incoming_edges, key=lambda e: (e.source.id, e.target.id)):
                        if e.data.get('type') == 'control':
                            e.remove_from_nodes()
                            if e.id in self.graph.edges:
                                del self.graph.edges[e.id]
                    self.graph.add_edge(Edge(or_node, stall_controller, data={'type': 'control', 'reason': 'combined_stall'}))
                    print(f"  Added memory stall to existing controller via OR")
            else:
                self.graph.add_edge(Edge(stall_signal, stall_controller, data={'type': 'control', 'reason': 'variable_latency_memory'}))
                print(f"  Connected to existing stall controller: {stall_controller_id}")
        else:
            stall_controller = self.hw_factory.stall_logic.create_or_get_stall_controller(
                controller_id=stall_controller_id,
                stage_name=memory_stage_name or 'Memory',
                pipeline_prefix='PIPE',
                metadata={'pipeline_component': True}
            )
            self.graph.add_edge(Edge(stall_signal, stall_controller, data={'type': 'control', 'reason': 'variable_latency_memory'}))
            print(f"  Created stall controller: {stall_controller_id}")

        # Bubble injection into the next stage
        if bubble_stage_name and memory_time is not None:
            bubble_valid_id = f"PIPE_{bubble_stage_name}_valid_PIPE"
            bubble_valid = self.graph.nodes.get(bubble_valid_id)

            # Find previous stage's valid signal
            prev_valid = None
            if memory_stage_name:
                prev_valid_id = f"PIPE_{memory_stage_name}_valid_PIPE"
                prev_valid = self.graph.nodes.get(prev_valid_id)

            if prev_valid and bubble_valid:
                not_stall_id = f"{stall_controller_id}_not"
                if not_stall_id not in self.graph.nodes:
                    not_stall = Node(not_stall_id, data={
                        'type': 'operation', 'operator': '!', 'name': not_stall_id,
                        'bit_width': 1, 'pipeline_component': True
                    })
                    self.graph.add_node(not_stall)
                    self.graph.add_edge(Edge(stall_controller, not_stall, data={'type': 'operand'}))
                else:
                    not_stall = self.graph.nodes[not_stall_id]

                and_id = f"PIPE_{bubble_stage_name}_valid_and_not_mem_stall"
                if and_id not in self.graph.nodes:
                    and_node = Node(and_id, data={
                        'type': 'operation', 'operator': '&&', 'name': and_id,
                        'bit_width': 1, 'pipeline_component': True
                    })
                    self.graph.add_node(and_node)
                    self.graph.add_edge(Edge(prev_valid, and_node, data={'type': 'operand', 'operand_index': 0}))
                    self.graph.add_edge(Edge(not_stall, and_node, data={'type': 'operand', 'operand_index': 1}))

                    for edge in sorted(bubble_valid.incoming_edges, key=lambda e: (e.source.id, e.target.id)):
                        if edge.data.get('type') == 'pipeline_input':
                            edge.remove_from_nodes()
                            if edge.id in self.graph.edges:
                                del self.graph.edges[edge.id]

                    self.graph.add_edge(Edge(and_node, bubble_valid, data={'type': 'pipeline_input', 'pipeline_component': True}))
                    print(f"  Created bubble injection: {bubble_stage_name}_valid = {memory_stage_name}_valid && !stall")

        # Gate pipeline registers at and before memory stage
        # Note: register.pipe_time is INPUT time, stage time = register.pipe_time + 1
        # So to stall stages with time <= memory_time, we gate registers with pipe_time < memory_time
        # IMPORTANT: We gate ALL registers including valid registers for stalled stages.
        # Only the bubble stage's valid register is skipped (for bubble injection).
        stalled_count = 0
        bubble_valid_id = f"PIPE_{bubble_stage_name}_valid_PIPE" if bubble_stage_name else None

        if memory_time is not None:
            for stage, time in sorted(stage_times.items()):
                if time <= memory_time:
                    # This stage needs to be stalled - find its registers
                    stage_prefix = f"PIPE_{stage}_"
                    for node_id, node in sorted(self.graph.nodes.items()):
                        if (node.data.get('type') == 'pipeline_register' and
                            node_id.startswith(stage_prefix) and node_id.endswith('_PIPE')):
                            # Only skip the BUBBLE stage's valid (handled by bubble injection)
                            if node_id == bubble_valid_id:
                                continue
                            if not any(e.source == stall_controller for e in node.incoming_edges):
                                self.hw_factory.stall_logic.connect_controller_to_register(
                                    controller_node=stall_controller,
                                    pipeline_register=node,
                                    metadata={'pipeline_component': True}
                                )
                                stalled_count += 1

        # Also gate bubble stage DATA registers (but NOT the valid register - that's for bubble injection)
        if bubble_stage_name:
            bubble_prefix = f"PIPE_{bubble_stage_name}_"
            for node_id, node in sorted(self.graph.nodes.items()):
                if (node.data.get('type') == 'pipeline_register' and
                    node_id.startswith(bubble_prefix) and node_id.endswith('_PIPE')):
                    if node_id == bubble_valid_id:
                        continue
                    if not any(e.source == stall_controller for e in node.incoming_edges):
                        self.hw_factory.stall_logic.connect_controller_to_register(
                            controller_node=stall_controller,
                            pipeline_register=node,
                            metadata={'pipeline_component': True}
                        )
                        stalled_count += 1

        print(f"  Gated {stalled_count} pipeline registers with memory stall")
        return True

    def resolve_all_hazards(self, hazards: List[DetectedHazard]) -> bool:
        """Resolve all hazards according to their chosen strategies.

        Handles both indexed (2D) and non-indexed (1D) hazards.

        For indexed hazards, each hazard gets its own comparator + stall/bypass logic.
        For non-indexed hazards, hazards on the same ISA state element are grouped
        and only the one with the largest forwarding distance is resolved (to avoid
        duplicate stall logic for the same register).

        For bypass resolution, hazards are sorted by forwarding distance (smaller first)
        so that closer stages (Memory) get higher priority in the bypass mux than
        farther stages (Writeback). This ensures correct forwarding when both sources
        could provide a value.
        """
        print(f"\nResolving {len(hazards)} hazards...")

        # Separate hazards into two categories:
        # 1. Comparison hazards: indexed with full index comparison (STALL or BYPASS)
        #    Each gets its own comparator + stall/bypass logic.
        # 2. Non-comparison hazards: enable-only (STALL_ENABLE_ONLY) or non-indexed (1D)
        #    Grouped by resource — only the most conservative (max distance) is resolved.
        #    No index comparison; stalls fire based on write-enable + stage-valid.
        comparison_hazards = [h for h in hazards
                              if h.is_indexed and h.resolution != HazardResolutionStrategy.STALL_ENABLE_ONLY]
        non_comparison_hazards = [h for h in hazards if h not in comparison_hazards]

        # Sort comparison hazards by forwarding distance (smaller distance = higher priority)
        sorted_comparison = sorted(comparison_hazards, key=lambda h: h.get_forwarding_distance())

        success_count = 0

        # Resolve comparison hazards individually (each has unique comparator)
        for hazard in sorted_comparison:
            if self.resolve_hazard(hazard):
                success_count += 1

        # Group non-comparison hazards by resource and resolve one representative per resource
        if non_comparison_hazards:
            hazards_by_resource: Dict[str, List[DetectedHazard]] = {}
            for hazard in non_comparison_hazards:
                hazards_by_resource.setdefault(hazard.resource, []).append(hazard)

            for resource_name, resource_hazards in sorted(hazards_by_resource.items()):
                max_distance_hazard = max(resource_hazards, key=lambda h: h.get_forwarding_distance())
                print(f"  Non-comparison stall for {resource_name}: resolving representative hazard (distance={max_distance_hazard.get_forwarding_distance()})")
                if self.resolve_hazard(max_distance_hazard):
                    success_count += len(resource_hazards)

        print(f"Successfully resolved {success_count}/{len(hazards)} hazards")

        # After all hazards are resolved, ensure next-stage pipeline registers have stall gating
        # This is necessary for bypass mode - when stalled, operand registers must hold values
        # Only apply when bypass muxes exist; for pure stalling, the bubble injection on the
        # next stage's valid signal is sufficient to prevent incorrect execution.
        if self.bypass_muxes:
            self._add_next_stage_stall_gating()

        # Add distance-4 forwarding: RF write to Execute bypass
        # This handles the case where Writeback writes to RF at the same edge Execute reads
        if self.bypass_muxes:
            self._add_rf_write_forwarding()

        # Automatically detect and add memory latency stalls
        # This integrates with the existing stall controller rather than creating a separate one
        self._add_automatic_memory_latency_stalls()

        # Retry any load-use stall integrations that were deferred because the
        # stall controller didn't exist yet (bypass mode creates load-use stalls
        # before _add_automatic_memory_latency_stalls creates the controller)
        self._retry_pending_stall_integrations()

        # Automatically detect and add cache stalls (bubble insertion for instruction cache)
        self._add_automatic_cache_stalls()

        return success_count == len(hazards)

    def _find_or_create_write_enable(self, hazard: 'DetectedHazard') -> Tuple[Optional[Node], Optional[str]]:
        """
        Find or create a write enable signal for a non-indexed ISA state hazard.

        Strategy:
        1. Look for an explicit {resource}_write_enable node
        2. Look for a mux feeding the write port and OR together its pipelined select signals
        3. Return None if no write enable can be determined

        Returns:
            Tuple of (write_enable_node, actual_write_stage_name)
            The actual_write_stage_name may differ from hazard.write_stage_name if the
            controlling enables are at a different pipeline stage.
        """
        isa_state = hazard.resource
        write_stage = hazard.write_stage_name

        # Try to find explicit write enable
        for pattern in [f"{isa_state}_write_enable", f"{isa_state}_wr_enable"]:
            if pattern in self.graph.nodes:
                # Look for pipelined version
                pipelined_pattern = f"PIPE_{write_stage}_{pattern}_PIPE"
                if pipelined_pattern in self.graph.nodes:
                    print(f"    Found pipelined write enable: {pipelined_pattern}")
                    return self.graph.nodes[pipelined_pattern], write_stage
                print(f"    Found write enable: {pattern}")
                return self.graph.nodes[pattern], write_stage

        # Look for the mux that feeds the write port: {isa_state}_wr_mux
        mux_node = self.graph.nodes.get(f"{isa_state}_wr_mux")
        if not mux_node:
            mux_node = self.graph.nodes.get(f"{isa_state}_write_mux")

        if mux_node:
            # Find all select signals (instruction enables) for this mux
            select_signals = []
            already_pipelined = []
            actual_stage = None
            # Sort edges for deterministic iteration order
            for edge in sorted(mux_node.incoming_edges, key=lambda e: e.source.id):
                edge_type = edge.data.get('type', '')
                if 'select' in edge_type or edge_type == 'mux_select':
                    source_id = edge.source.id
                    # Check if already pipelined (PIPE_*_enable_PIPE)
                    if source_id.startswith('PIPE_') and source_id.endswith('_PIPE'):
                        already_pipelined.append(edge.source)
                        # Extract stage name from PIPE_{stage}_{signal}_PIPE
                        parts = source_id.split('_')
                        if len(parts) >= 3:
                            actual_stage = parts[1]  # e.g., "Execute" from PIPE_Execute_xxx_PIPE
                    elif source_id.endswith('_enable'):
                        select_signals.append(source_id)
                    elif source_id.endswith('_merged') or 'select' in source_id:
                        # This is a compound signal (e.g., select_return_addr_lr_merged,
                        # or a condition-gated select like mtspr_rs_val_(spr == 10'h8)_select)
                        # Trace through recursively to find underlying pipelined enables
                        # Need to trace multiple levels for nested combinational logic
                        def trace_pipelined_enables(node, visited=None, depth=0):
                            """Recursively trace through combinational logic to find pipelined enables."""
                            if visited is None:
                                visited = set()
                            if node.id in visited:
                                return []
                            visited.add(node.id)

                            # Check for condition-gated AND select nodes (e.g., mtspr_enable && (spr == 10'h8))
                            # These must preserve AND semantics - both inputs must be pipelined together
                            node_op = node.data.get('operator', '')
                            if node_op == '&&' and node.id.endswith('_select'):
                                pipelined_inputs = []
                                for sub_edge in sorted(node.incoming_edges, key=lambda e: e.source.id):
                                    sub_source_id = sub_edge.source.id
                                    if sub_source_id.startswith('PIPE_') and sub_source_id.endswith('_PIPE'):
                                        pipelined_inputs.append(sub_edge.source)
                                    else:
                                        for stage_name in [write_stage, 'ExecuteMemoryWriteback', 'Execute', 'Writeback']:
                                            pipelined_id = f"PIPE_{stage_name}_{sub_source_id}_PIPE"
                                            if pipelined_id in self.graph.nodes:
                                                pipelined_inputs.append(self.graph.nodes[pipelined_id])
                                                break
                                if len(pipelined_inputs) >= 2:
                                    pipelined_and_id = f"PIPE_{node.id}_PIPE"
                                    if pipelined_and_id not in self.graph.nodes:
                                        from core.resource_graph import Node as RGNode, Edge as RGEdge
                                        and_node = RGNode(pipelined_and_id, {
                                            'type': 'operation', 'operator': '&&',
                                            'display_name': f"Pipelined {node.id}", 'bit_width': 1
                                        })
                                        self.graph.add_node(and_node)
                                        for idx, inp in enumerate(pipelined_inputs):
                                            e = RGEdge(inp, and_node, data={'type': 'operand', 'operand_index': idx, 'position': idx})
                                            self.graph.add_edge(e)
                                    return [self.graph.nodes[pipelined_and_id]]
                                elif len(pipelined_inputs) == 1:
                                    return pipelined_inputs
                                return []

                            results = []
                            # Sort edges for deterministic ordering
                            for sub_edge in sorted(node.incoming_edges, key=lambda e: e.source.id):
                                sub_source_id = sub_edge.source.id
                                sub_node = sub_edge.source
                                if sub_source_id.startswith('PIPE_') and sub_source_id.endswith('_PIPE'):
                                    # Found a pipelined signal - only include if it's an actual enable
                                    # (not just a valid signal or other pipelined value)
                                    if '_enable_PIPE' in sub_source_id:
                                        results.append(sub_node)
                                elif (sub_node.data.get('type') in ('logical_and', 'operation', 'logical_or') or
                                      'select' in sub_source_id or sub_source_id.endswith('_merged')):
                                    # This is a combinational node - trace through it
                                    results.extend(trace_pipelined_enables(sub_node, visited, depth+1))
                            return results

                        traced_enables = trace_pipelined_enables(edge.source)
                        for enable_node in traced_enables:
                            already_pipelined.append(enable_node)
                            parts = enable_node.id.split('_')
                            if len(parts) >= 3:
                                actual_stage = parts[1]

            # Use already-pipelined enables if available
            if already_pipelined:
                write_enable_id = f"{isa_state}_write_enable"
                write_enable_node = self._create_or_node(write_enable_id, already_pipelined)
                # Use actual stage from the pipelined enables, not the hazard's write_stage
                effective_stage = actual_stage if actual_stage else write_stage
                print(f"    Created write enable from {len(already_pipelined)} already-pipelined instruction enables: {write_enable_id} (stage: {effective_stage})")
                return write_enable_node, effective_stage

            if select_signals:
                # Look for pipelined versions of these enables in the write stage
                pipelined_enables = []
                for sig in select_signals:
                    # Pattern: PIPE_{stage}_{signal}_PIPE
                    pipelined_id = f"PIPE_{write_stage}_{sig}_PIPE"
                    if pipelined_id in self.graph.nodes:
                        pipelined_enables.append(self.graph.nodes[pipelined_id])

                if pipelined_enables:
                    # Create OR of all pipelined enables
                    write_enable_id = f"{isa_state}_write_enable_{write_stage}"
                    write_enable_node = self._create_or_node(write_enable_id, pipelined_enables)
                    print(f"    Created write enable from {len(pipelined_enables)} pipelined instruction enables: {write_enable_id}")
                    return write_enable_node, write_stage
                else:
                    print(f"    Found mux selects but no pipelined versions in {write_stage}")

        # Try looking at write node's incoming edges
        write_node = hazard.write_access_node
        for edge in write_node.incoming_edges:
            if edge.data.get('type') in ('write_enable', 'enable'):
                source = edge.source
                # Look for pipelined version
                pipelined_id = f"PIPE_{write_stage}_{source.id}_PIPE"
                if pipelined_id in self.graph.nodes:
                    print(f"    Found pipelined write enable via edge: {pipelined_id}")
                    return self.graph.nodes[pipelined_id], write_stage
                print(f"    Found write enable via edge: {source.id}")
                return source, write_stage

        print(f"    WARNING: Could not find write enable for {isa_state}")
        return None, None

    def _find_or_create_read_enable(self, hazard: 'DetectedHazard') -> Optional[Node]:
        """
        Find or create a read enable signal for a non-indexed ISA state hazard.

        The read enable indicates which instructions in the read stage actually read
        from this ISA state element.

        Strategy:
        1. Look for an explicit {resource}_read_enable node
        2. Look at the read node's outgoing edges to find consuming instructions
        3. OR together the enables of instructions that use the read value
        """
        isa_state = hazard.resource
        read_stage = hazard.read_stage_name

        # Try to find explicit read enable
        for pattern in [f"{isa_state}_read_enable", f"{isa_state}_rd_enable"]:
            if pattern in self.graph.nodes:
                print(f"    Found read enable: {pattern}")
                return self.graph.nodes[pattern]

        # Look at the read node and find what instructions use its value
        read_node = hazard.read_access_node
        if not read_node:
            # Try to find the read node
            read_node = self.graph.nodes.get(f"{isa_state}_rd")

        if read_node:
            # Find instruction enables that are connected to computations using this read
            consuming_enables = set()

            # Walk outgoing edges to find operations, then find which instructions enable them
            visited = set()
            to_visit = [read_node]

            while to_visit:
                node = to_visit.pop()
                if node.id in visited:
                    continue
                visited.add(node.id)

                # Sort edges for deterministic iteration order
                for edge in sorted(node.outgoing_edges, key=lambda e: e.target.id):
                    target = edge.target
                    target_id = target.id

                    # If we find an instruction-specific node, extract the instruction name
                    # Pattern: {instr}_something or ends with _enable
                    if target_id.endswith('_enable'):
                        consuming_enables.add(target_id)
                    elif '_' in target_id and not target_id.startswith('PIPE_'):
                        # Try to extract instruction name from node patterns like {instr}_new_cr
                        parts = target_id.split('_')
                        instr_name = parts[0]
                        enable_id = f"{instr_name}_enable"
                        if enable_id in self.graph.nodes:
                            consuming_enables.add(enable_id)

                    # Don't recurse too deep - just look at immediate consumers
                    # and their direct children
                    if len(visited) < 100:
                        to_visit.append(target)

            # Note: Scalar ISA state read enables (cr, ctr, lr, xer) are now created
            # structurally by graph_merger.py's create_read_enable_signals() third pass.
            # They should be found by the explicit pattern check above.

            if consuming_enables:
                # Get the enable nodes (non-pipelined, at decode stage)
                # Sort for deterministic OR chain ordering
                enable_nodes = [self.graph.nodes[e] for e in sorted(consuming_enables) if e in self.graph.nodes]
                if enable_nodes:
                    read_enable_id = f"{isa_state}_read_enable"
                    read_enable_node = self._create_or_node(read_enable_id, enable_nodes)
                    print(f"    Created read enable from {len(enable_nodes)} instruction enables: {read_enable_id}")
                    return read_enable_node

        print(f"    WARNING: Could not find read enable for {isa_state}")
        return None

    def _create_or_node(self, node_id: str, inputs: List[Node]) -> Node:
        """Create an OR node that combines multiple input signals."""
        if len(inputs) == 1:
            return inputs[0]

        # Create a chain of OR operations
        result = inputs[0]
        for i, inp in enumerate(inputs[1:], 1):
            or_id = f"{node_id}_or_{i}" if i < len(inputs) - 1 else node_id
            or_node = Node(or_id, data={
                'type': 'operation',
                'operator': '||',
                'name': or_id,
                'bit_width': 1
            })
            self.graph.add_node(or_node)

            edge1 = Edge(result, or_node, data={
                'type': 'left_operand',
                'position': 'left'
            })
            self.graph.add_edge(edge1)

            edge2 = Edge(inp, or_node, data={
                'type': 'right_operand',
                'position': 'right'
            })
            self.graph.add_edge(edge2)

            result = or_node

        return result

    # NOTE: resolve_memory_hazards_with_enable_stalling() has been removed.
    # Memory hazards are now handled through the unified resolve_all_hazards() path
    # using HazardResolutionStrategy.STALL_ENABLE_ONLY, which routes through
    # _build_stall_condition() with needs_comparison=False (write_enable && stage_valid).

    def _add_next_stage_stall_gating(self):
        """Add stall gating for pipeline registers at the stage after each stall controller.

        In bypass mode, when an instruction stalls (e.g., for distance-1 hazard),
        the operand registers must hold their values. Without this gating, the
        bypass mux recomputes with new forwarding conditions when the stall ends,
        potentially giving wrong values.

        This is done structurally: for each stall controller PIPE_{stage}_stall_ctrl,
        we gate the pipeline registers at the next stage.
        """
        # Build ordered list of pipeline stages from graph structure
        stage_names = set()
        for node_id, node in sorted(self.graph.nodes.items()):
            if (node.data.get('type') == 'pipeline_register' and
                node_id.startswith('PIPE_') and node_id.endswith('_PIPE') and
                not node_id.endswith('_PIPE_PIPE')):
                parts = node_id.split('_')
                if len(parts) >= 3:
                    stage_names.add(parts[1])

        # Sort stages by their pipe_time (first register found at each stage)
        stage_times = {}
        for stage in stage_names:
            for node_id, node in sorted(self.graph.nodes.items()):
                if (node.data.get('type') == 'pipeline_register' and
                    node_id.startswith(f'PIPE_{stage}_') and node_id.endswith('_PIPE') and
                    not node_id.endswith('_PIPE_PIPE')):
                    pipe_time = getattr(node, 'pipe_time', 0)
                    if stage not in stage_times or pipe_time < stage_times[stage]:
                        stage_times[stage] = pipe_time
                    break

        # Create ordered stage list
        ordered_stages = sorted(stage_times.keys(), key=lambda s: stage_times.get(s, 0))

        # Find all stall controllers and their stages
        stall_controllers = {}
        for node_id, node in sorted(self.graph.nodes.items()):
            if node.data.get('type') == 'pipeline_stall_controller':
                # Extract stage name from PIPE_{stage}_stall_ctrl pattern
                if node_id.startswith('PIPE_') and node_id.endswith('_stall_ctrl'):
                    parts = node_id.split('_')
                    if len(parts) >= 3:
                        ctrl_stage = parts[1]
                        stall_controllers[ctrl_stage] = node

        if not stall_controllers:
            print("  No stall controllers found")
            return

        total_count = 0
        for ctrl_stage, stall_ctrl in sorted(stall_controllers.items()):
            # Find next stage in order
            try:
                ctrl_idx = ordered_stages.index(ctrl_stage)
                if ctrl_idx + 1 < len(ordered_stages):
                    next_stage = ordered_stages[ctrl_idx + 1]
                else:
                    continue  # No next stage
            except ValueError:
                continue  # Stage not in ordered list

            # Gate pipeline registers at next stage
            # Pattern: PIPE_{next_stage}_*_PIPE but NOT *_PIPE_PIPE (propagated) or *_valid_PIPE
            stall_count = 0
            for node_id, node in sorted(self.graph.nodes.items()):
                if (node_id.startswith(f'PIPE_{next_stage}_') and
                    node_id.endswith('_PIPE') and
                    not node_id.endswith('_PIPE_PIPE') and
                    not node_id.endswith('_valid_PIPE')):

                    # Check if already has a stall edge from this controller
                    has_stall_edge = any(
                        e.data.get('type') == 'stall' and e.source.id == stall_ctrl.id
                        for e in node.incoming_edges
                    )
                    if not has_stall_edge:
                        stall_edge = Edge(stall_ctrl, node, data={
                            'type': 'stall',
                            'description': f'Gate {next_stage} pipeline register when {ctrl_stage} stalls'
                        })
                        self.graph.add_edge(stall_edge)
                        stall_count += 1

            if stall_count > 0:
                print(f"  Added stall gating from {ctrl_stage} to {stall_count} {next_stage} pipeline registers")
                total_count += stall_count

        if total_count > 0:
            print(f"  Total: {total_count} pipeline registers gated by stall controllers")

    def _add_automatic_memory_latency_stalls(self):
        """Automatically detect memories with variable latency and add stall logic.

        This integrates memory stall conditions into the existing stall controller
        (typically PIPE_Decode_stall_ctrl) rather than creating separate controllers.
        This ensures coherent pipeline stalling behavior.
        """
        print("\n  Checking for variable latency memories...")

        # Find all memories with variable_latency attribute
        # Memories can have type 'memory', 'isa_state mem', or contain 'mem' in type
        variable_latency_memories = []
        for node_id, node in sorted(self.graph.nodes.items()):
            node_type = node.data.get('type', '')
            is_memory = (node_type == 'memory' or
                         'mem' in node_type or
                         node.data.get('is_memory', False))
            if is_memory and getattr(node, 'variable_latency', False):
                variable_latency_memories.append(node)

        if not variable_latency_memories:
            print("  No variable latency memories found")
            return

        # Find existing stall controller that gates ISA states (like PC)
        # RAW hazard resolution creates a stall controller and connects it to the PC.
        # We OR memory stall into that controller for proper backpropagation.
        stall_ctrl = None
        for node_id, node in sorted(self.graph.nodes.items()):
            if node.data.get('type') == 'isa_state':
                for edge in sorted(node.incoming_edges, key=lambda e: (e.source.id, e.target.id)):
                    if edge.data.get('type') == 'stall':
                        candidate = edge.source
                        if candidate.data.get('type') == 'pipeline_stall_controller':
                            stall_ctrl = candidate
                            print(f"  Found existing stall controller gating ISA state: {stall_ctrl.id}")
                            break
                if stall_ctrl:
                    break

        # Build stage_times map for determining which stages to stall
        stage_names = set()
        for node_id, node in sorted(self.graph.nodes.items()):
            if (node.data.get('type') == 'pipeline_register' and
                node_id.startswith('PIPE_') and node_id.endswith('_PIPE')):
                parts = node_id.split('_')
                if len(parts) >= 3:
                    stage_names.add(parts[1])

        stage_times = {}
        for stage in sorted(stage_names):
            for node_id, node in sorted(self.graph.nodes.items()):
                if (node.data.get('type') == 'pipeline_register' and
                    node_id.startswith(f'PIPE_{stage}_') and node_id.endswith('_PIPE')):
                    ptime = getattr(node, 'pipe_time', None)
                    if ptime is None:
                        ptime = getattr(node, 'uarch_time', None)
                    if ptime is not None:
                        stage_times[stage] = ptime
                        break

        for memory in variable_latency_memories:
            memory_name = memory.id
            print(f"  Processing variable latency memory: {memory_name}")

            # Get complete signal
            complete_signal_id = memory.data.get('complete_signal')
            if not complete_signal_id:
                print(f"    Warning: No complete signal for {memory_name}, skipping")
                continue

            complete_signal = self.graph.nodes.get(complete_signal_id)
            if not complete_signal:
                print(f"    Warning: Complete signal {complete_signal_id} not found, skipping")
                continue

            # Find memory access enable signal (includes BOTH reads and writes)
            # Must use access_enable (not just rd_enable) so stores also stall
            access_enable_node = None
            for candidate_id in [f'{memory_name}_access_enable',           # Both reads and writes
                                 f'{memory_name}_pc_rd_enable',            # imem uses pc-indexed read
                                 f'{memory_name}_addr_rd_enable_valid_gated',  # Fallback: read only
                                 f'{memory_name}_rd_enable_valid_gated',
                                 f'{memory_name}_addr_rd_enable',
                                 f'{memory_name}_rd_enable']:
                if candidate_id in self.graph.nodes:
                    access_enable_node = self.graph.nodes[candidate_id]
                    break

            if not access_enable_node:
                print(f"    Warning: No access enable found for {memory_name}, skipping")
                continue

            print(f"    Using access enable: {access_enable_node.id}")

            # Determine memory stage time
            memory_time = getattr(access_enable_node, 'pipe_time', None)
            if memory_time is None:
                memory_time = getattr(access_enable_node, 'uarch_time', None)

            print(f"    Memory access at pipe_time={memory_time}")

            # Create stall condition: !complete AND access_enable
            not_complete_id = f"{memory_name}_not_complete"
            if not_complete_id not in self.graph.nodes:
                not_complete = Node(
                    node_id=not_complete_id,
                    data={
                        'type': 'operation',
                        'operator': '!',
                        'name': not_complete_id,
                        'description': f'Memory {memory_name} not complete',
                        'pipeline_component': True,
                        'bit_width': 1
                    }
                )
                self.graph.add_node(not_complete)
                self.graph.add_edge(Edge(complete_signal, not_complete, data={
                    'type': 'operand',
                    'operand_position': 0
                }))
            else:
                not_complete = self.graph.nodes[not_complete_id]

            # Create stall condition
            # For instruction memory (imem): stall = !idle && !complete (always fetching when not idle)
            # For data memory (dmem): stall = access_enable && !complete (only stall during access)
            is_instruction_memory = memory_name == 'imem'
            stall_condition_id = f"{memory_name}_mem_stall_condition"

            if stall_condition_id not in self.graph.nodes:
                if is_instruction_memory:
                    # For imem: use !idle instead of access_enable
                    idle_signal_id = f"{memory_name}_idle"
                    idle_signal = self.graph.nodes.get(idle_signal_id)
                    if idle_signal:
                        # Create !idle node
                        not_idle_id = f"{memory_name}_not_idle"
                        if not_idle_id not in self.graph.nodes:
                            not_idle = Node(
                                node_id=not_idle_id,
                                data={
                                    'type': 'operation',
                                    'operator': '!',
                                    'name': not_idle_id,
                                    'description': f'{memory_name} not idle (fetching)',
                                    'pipeline_component': True,
                                    'bit_width': 1
                                }
                            )
                            self.graph.add_node(not_idle)
                            self.graph.add_edge(Edge(idle_signal, not_idle, data={'type': 'operand', 'operand_position': 0}))
                        else:
                            not_idle = self.graph.nodes[not_idle_id]

                        # Stall = !idle && !complete
                        stall_condition = Node(
                            node_id=stall_condition_id,
                            data={
                                'type': 'operation',
                                'operator': '&&',
                                'name': stall_condition_id,
                                'description': f'Stall: {memory_name} fetching && !complete',
                                'pipeline_component': True,
                                'bit_width': 1
                            }
                        )
                        self.graph.add_node(stall_condition)
                        self.graph.add_edge(Edge(not_complete, stall_condition, data={'type': 'operand', 'operand_index': 0}))
                        self.graph.add_edge(Edge(not_idle, stall_condition, data={'type': 'operand', 'operand_index': 1}))
                        print(f"    Created imem stall condition: !idle && !complete")
                    else:
                        print(f"    Warning: idle signal not found for {memory_name}")
                        continue
                else:
                    # For dmem/umem: stall = access_enable && !complete
                    stall_condition = Node(
                        node_id=stall_condition_id,
                        data={
                            'type': 'operation',
                            'operator': '&&',
                            'name': stall_condition_id,
                            'description': f'Stall: {memory_name} active && !complete',
                            'pipeline_component': True,
                            'bit_width': 1
                        }
                    )
                    self.graph.add_node(stall_condition)
                    self.graph.add_edge(Edge(not_complete, stall_condition, data={'type': 'operand', 'operand_index': 0}))
                    self.graph.add_edge(Edge(access_enable_node, stall_condition, data={'type': 'operand', 'operand_index': 1}))

                    # For unified memory (umem), create a data-only stall condition for Memory->Writeback
                    # This excludes instruction fetch (pc_rd) since that shouldn't block Memory stage
                    if memory_name == 'umem':
                        data_stall_id = f"{memory_name}_data_stall_condition"
                        if data_stall_id not in self.graph.nodes:
                            # Create data-only access enable (excludes pc_rd)
                            # IMPORTANT: Use validity-gated versions to prevent stalling on invalid instructions
                            data_access_id = f"{memory_name}_data_access_enable"

                            # Look for data access signals - prefer validity-gated versions
                            data_signals = []

                            # For write_enable, try validity-gated version first
                            write_enable_gated_id = f'{memory_name}_write_enable_valid_gated'
                            write_enable_id = f'{memory_name}_write_enable'
                            if write_enable_gated_id in self.graph.nodes:
                                data_signals.append(self.graph.nodes[write_enable_gated_id])
                            elif write_enable_id in self.graph.nodes:
                                # Create validity-gated version
                                write_enable_node = self.graph.nodes[write_enable_id]
                                mem_valid_id = "PIPE_Memory_valid_PIPE"
                                if mem_valid_id in self.graph.nodes:
                                    mem_valid = self.graph.nodes[mem_valid_id]
                                    gated_node = Node(write_enable_gated_id, data={
                                        'type': 'operation',
                                        'operator': '&&',
                                        'name': write_enable_gated_id,
                                        'description': f'Validity-gated write enable for data stall',
                                        'pipeline_component': True,
                                        'bit_width': 1
                                    })
                                    self.graph.add_node(gated_node)
                                    self.graph.add_edge(Edge(write_enable_node, gated_node,
                                        data={'type': 'operand', 'operand_index': 0}))
                                    self.graph.add_edge(Edge(mem_valid, gated_node,
                                        data={'type': 'operand', 'operand_index': 1}))
                                    data_signals.append(gated_node)
                                    print(f"    Created {write_enable_gated_id} for data stall")
                                else:
                                    # Fall back to non-gated version
                                    data_signals.append(write_enable_node)

                            # For addr_rd_enable (data reads), also stall Memory->Writeback
                            # Without this, load control signals advance to Writeback before
                            # the memory read completes, causing zero/stale data to be written
                            addr_rd_enable_gated_id = f'{memory_name}_addr_rd_enable_valid_gated'
                            addr_rd_enable_id = f'{memory_name}_addr_rd_enable'
                            if addr_rd_enable_gated_id in self.graph.nodes:
                                data_signals.append(self.graph.nodes[addr_rd_enable_gated_id])
                            elif addr_rd_enable_id in self.graph.nodes:
                                # Create validity-gated version
                                addr_rd_enable_node = self.graph.nodes[addr_rd_enable_id]
                                mem_valid_id = "PIPE_Memory_valid_PIPE"
                                if mem_valid_id in self.graph.nodes:
                                    mem_valid = self.graph.nodes[mem_valid_id]
                                    gated_node = Node(addr_rd_enable_gated_id, data={
                                        'type': 'operation',
                                        'operator': '&&',
                                        'name': addr_rd_enable_gated_id,
                                        'description': f'Validity-gated read enable for data stall',
                                        'pipeline_component': True,
                                        'bit_width': 1
                                    })
                                    self.graph.add_node(gated_node)
                                    self.graph.add_edge(Edge(addr_rd_enable_node, gated_node,
                                        data={'type': 'operand', 'operand_index': 0}))
                                    self.graph.add_edge(Edge(mem_valid, gated_node,
                                        data={'type': 'operand', 'operand_index': 1}))
                                    data_signals.append(gated_node)
                                    print(f"    Created {addr_rd_enable_gated_id} for data stall")
                                else:
                                    data_signals.append(addr_rd_enable_node)

                            # For dcache signals (already gated internally)
                            for sig_id in ['dcache_refill_req', 'dcache_write_through_req']:
                                if sig_id in self.graph.nodes:
                                    data_signals.append(self.graph.nodes[sig_id])

                            if data_signals:
                                if len(data_signals) == 1:
                                    data_access_node = data_signals[0]
                                else:
                                    # Create OR gate for data access signals
                                    data_access_node = Node(data_access_id, data={
                                        'type': 'operation',
                                        'operator': '||',
                                        'name': data_access_id,
                                        'description': f'{memory_name} data access enable (no pc_rd)',
                                        'pipeline_component': True,
                                        'bit_width': 1
                                    })
                                    self.graph.add_node(data_access_node)
                                    for idx, sig in enumerate(data_signals):
                                        self.graph.add_edge(Edge(sig, data_access_node,
                                            data={'type': 'operand', 'operand_index': idx}))

                                # Create data-only stall: data_access && !complete
                                data_stall = Node(data_stall_id, data={
                                    'type': 'operation',
                                    'operator': '&&',
                                    'name': data_stall_id,
                                    'description': f'{memory_name} data stall (excludes instruction fetch)',
                                    'pipeline_component': True,
                                    'bit_width': 1
                                })
                                self.graph.add_node(data_stall)
                                self.graph.add_edge(Edge(not_complete, data_stall,
                                    data={'type': 'operand', 'operand_index': 0}))
                                self.graph.add_edge(Edge(data_access_node, data_stall,
                                    data={'type': 'operand', 'operand_index': 1}))

                                # Store for later use in Memory stage stall
                                memory.data['data_stall_condition'] = data_stall_id
                                print(f"    Created data-only stall condition: {data_stall_id}")
            else:
                stall_condition = self.graph.nodes[stall_condition_id]

            print(f"    Created stall condition: {stall_condition_id}")

            # Now integrate with existing stall controller
            # IMPORTANT: Skip adding memory stall to main stall chain if caches are present.
            # When caches exist, they have their own stall conditions (icache_stall_condition,
            # dcache_stall_condition) that are added by _add_automatic_cache_stalls.
            # Adding umem_mem_stall_condition would cause redundant stalls and, worse,
            # would keep the pipeline stalled when icache is refilling even if dcache
            # has completed its operation.
            has_caches = any(
                node.data.get('type') in ('read_only_cache', 'read_write_cache') and
                node.data.get('memory_name') == memory_name
                for node in self.graph.nodes.values()
            )

            # Add memory stall to main stall chain
            # When caches are present, we need to add the DATA-ONLY stall condition
            # (umem_data_stall_condition) to prevent new instructions from entering Execute
            # while a store is pending in Memory stage. Without this, stores corrupt data.
            # The cache stall conditions (icache, dcache) are added by _add_automatic_cache_stalls.
            data_stall_condition = None
            if has_caches:
                # Use data-only stall (excludes icache refill) for unified memory with caches
                data_stall_id = memory.data.get('data_stall_condition')
                if data_stall_id and data_stall_id in self.graph.nodes:
                    data_stall_condition = self.graph.nodes[data_stall_id]
                    print(f"    Using data-only stall {data_stall_id} for main stall chain (caches present)")
                else:
                    print(f"    Warning: No data_stall_condition found for {memory_name}, using full stall")
                    data_stall_condition = stall_condition

            # Choose which stall condition to add to main chain
            stall_for_main_chain = data_stall_condition if has_caches else stall_condition

            if has_caches and not data_stall_condition:
                print(f"    Skipping main stall chain integration (no valid stall condition)")
            elif stall_ctrl:
                # Find existing control inputs to stall controller
                existing_inputs = [e.source for e in sorted(stall_ctrl.incoming_edges, key=lambda e: (e.source.id, e.target.id))
                                   if e.data.get('type') == 'control']

                if stall_for_main_chain in existing_inputs:
                    print(f"    Memory stall already connected to {stall_ctrl.id}")
                elif existing_inputs:
                    # OR the memory stall with existing stall conditions
                    or_id = f"{stall_ctrl.id}_with_{memory_name}_stall"
                    if or_id not in self.graph.nodes:
                        or_node = Node(or_id, data={
                            'type': 'operation',
                            'operator': '||',
                            'name': or_id,
                            'description': 'Combined RAW + memory latency stall',
                            'bit_width': 1,
                            'pipeline_component': True
                        })
                        self.graph.add_node(or_node)

                        # Connect all existing inputs plus the new memory stall
                        for idx, inp in enumerate(sorted(existing_inputs, key=lambda n: n.id)):
                            self.graph.add_edge(Edge(inp, or_node, data={'type': 'operand', 'operand_index': idx}))
                        self.graph.add_edge(Edge(stall_for_main_chain, or_node, data={'type': 'operand', 'operand_index': len(existing_inputs)}))

                        # Remove old control edges
                        for e in sorted(stall_ctrl.incoming_edges, key=lambda e: (e.source.id, e.target.id)):
                            if e.data.get('type') == 'control':
                                e.remove_from_nodes()
                                if e.id in self.graph.edges:
                                    del self.graph.edges[e.id]

                        # Connect OR output to stall controller
                        self.graph.add_edge(Edge(or_node, stall_ctrl, data={'type': 'control', 'reason': 'combined_stall'}))
                        print(f"    ORed memory stall with existing RAW stalls into {stall_ctrl.id}")
                    else:
                        # OR node already exists, just add memory stall to it
                        or_node = self.graph.nodes[or_id]
                        existing_or_inputs = [e.source for e in sorted(or_node.incoming_edges, key=lambda e: (e.source.id, e.target.id))]
                        if stall_for_main_chain not in existing_or_inputs:
                            self.graph.add_edge(Edge(stall_for_main_chain, or_node, data={'type': 'operand', 'operand_index': len(existing_or_inputs)}))
                            print(f"    Added memory stall to existing OR node {or_id}")
                else:
                    # No existing inputs, connect directly
                    self.graph.add_edge(Edge(stall_for_main_chain, stall_ctrl, data={'type': 'control', 'reason': 'memory_latency'}))
                    print(f"    Connected memory stall directly to {stall_ctrl.id}")

            # ALWAYS create Memory stage stall controller for data memories (regardless of cache presence)
            # This is needed to gate Memory stage registers during dcache stalls.
            # The cache stall conditions will be integrated via _add_automatic_cache_stalls.
            # IMPORTANT: Memory registers should NOT be gated by RAW stalls - only by memory latency stalls
            # RAW stalls hold Decode/Execute to wait for results, but Memory should continue processing
            # NOTE: Skip this for instruction memory (imem) since it accesses at Fetch stage, not Memory
            # NOTE: Use stage_times['Memory'] as fallback if memory_time is None
            effective_memory_time = memory_time
            if effective_memory_time is None and 'Memory' in stage_times:
                effective_memory_time = stage_times['Memory']
                print(f"    Using Memory stage time from stage_times: {effective_memory_time}")

            # Initialize decode_time here so it is always defined when
            # the `if not stall_ctrl` block below references it, even when
            # the `if effective_memory_time is not None` branch is skipped
            # (instruction memory, missing memory_time, or no Memory stage).
            decode_time = None

            if effective_memory_time is not None and not is_instruction_memory:
                # Create a dedicated memory stall controller for Memory stage registers
                mem_stall_ctrl_id = f"PIPE_Memory_{memory_name}_stall_ctrl"
                if mem_stall_ctrl_id not in self.graph.nodes:
                    mem_stall_ctrl = Node(mem_stall_ctrl_id, data={
                        'type': 'pipeline_stall_controller',
                        'stage': 'Memory',
                        'memory': memory_name,
                        'description': f'Memory stage stall controller for {memory_name} latency only',
                        'pipeline_component': True
                    })
                    self.graph.add_node(mem_stall_ctrl)
                    # For unified memory, use data-only stall (excludes instruction fetch)
                    # This prevents instruction fetch from blocking Memory->Writeback transfer
                    data_stall_id = memory.data.get('data_stall_condition')
                    if data_stall_id and data_stall_id in self.graph.nodes:
                        data_stall = self.graph.nodes[data_stall_id]
                        self.graph.add_edge(Edge(data_stall, mem_stall_ctrl, data={'type': 'control', 'reason': 'data_memory_latency_only'}))
                        print(f"    Connected data-only stall {data_stall_id} to Memory stage controller")
                    else:
                        # Fallback: use full stall condition
                        self.graph.add_edge(Edge(stall_condition, mem_stall_ctrl, data={'type': 'control', 'reason': 'memory_latency_only'}))
                else:
                    mem_stall_ctrl = self.graph.nodes[mem_stall_ctrl_id]

                # Gate pipeline registers at memory_time
                # Also gate at memory_time-1 if it's a separate Execute stage (not Decode)
                # Structural check: Decode stage has register file reads (rf[rs1]_rd, rf[rs2]_rd)
                # at that pipe_time. Execute stage does not.
                # Find Decode stage time by looking for register file read nodes
                for node_id, node in sorted(self.graph.nodes.items()):
                    if 'rf' in node_id and '_rd' in node_id and node.data.get('type') == 'array_access':
                        pt = getattr(node, 'pipe_time', None)
                        if pt is not None:
                            decode_time = pt
                            break

                stall_count = 0
                for node_id, node in sorted(self.graph.nodes.items()):
                    if (node.data.get('type') == 'pipeline_register' and
                        node_id.startswith('PIPE_') and node_id.endswith('_PIPE')):
                        reg_time = getattr(node, 'pipe_time', None)
                        if reg_time is None:
                            reg_time = getattr(node, 'uarch_time', None)
                        if reg_time is None:
                            continue

                        # Gate registers at effective_memory_time, effective_memory_time+1 (Writeback),
                        # and effective_memory_time-1 if it's NOT the Decode stage.
                        # Writeback gating is critical: without it, load control signals advance
                        # to Writeback before the memory read completes, causing zero/stale data
                        # to be written to the register file.
                        should_gate = (reg_time == effective_memory_time or
                                      reg_time == effective_memory_time + 1 or
                                      (reg_time == effective_memory_time - 1 and reg_time != decode_time))

                        if should_gate:
                            if not any(e.source == mem_stall_ctrl for e in node.incoming_edges if e.data.get('type') == 'stall'):
                                stall_edge = Edge(mem_stall_ctrl, node, data={
                                    'type': 'stall',
                                    'description': f'Gate register (pipe_time={reg_time}) for memory latency stall'
                                })
                                self.graph.add_edge(stall_edge)
                                stall_count += 1

                if stall_count > 0:
                    print(f"    Extended memory-only stall gating to {stall_count} Execute+Memory stage registers (including validity)")

            if not stall_ctrl:
                # No existing stall controller - create one
                print(f"    Warning: No existing stall controller found, creating PIPE_Decode_stall_ctrl")
                stall_ctrl = self.hw_factory.stall_logic.create_or_get_stall_controller(
                    controller_id='PIPE_Decode_stall_ctrl',
                    stage_name='Decode',
                    pipeline_prefix='PIPE',
                    metadata={'pipeline_component': True}
                )
                self.graph.add_edge(Edge(stall_condition, stall_ctrl, data={'type': 'control', 'reason': 'memory_latency'}))

                # Gate only Decode-level pipeline registers with this controller.
                # Execute/Memory/Writeback registers are already gated by the
                # memory-specific stall controller (mem_stall_ctrl).  Gating them
                # with the Decode controller would deadlock when load-use stalls
                # are integrated: the load in Execute can't advance because
                # Execute registers are frozen by the Decode stall it triggered.
                if decode_time is not None:
                    for node_id, node in sorted(self.graph.nodes.items()):
                        if (node.data.get('type') == 'pipeline_register' and
                            node_id.startswith('PIPE_') and node_id.endswith('_PIPE')):
                            reg_time = getattr(node, 'pipe_time', None)
                            if reg_time is None:
                                reg_time = getattr(node, 'uarch_time', None)
                            if reg_time is not None and reg_time == decode_time:
                                stall_edge = Edge(stall_ctrl, node, data={
                                    'type': 'stall',
                                    'description': f'Gate Decode register for stall'
                                })
                                self.graph.add_edge(stall_edge)

                    # Also gate ISA state elements at or before the memory stage.
                    # This prevents instruction fetch during stalls (critical for WRF mode
                    # where no RAW hazard stall creates the ISA state gating).
                    isa_state_count = 0
                    for node_id, node in sorted(self.graph.nodes.items()):
                        if node.data.get('type') == 'isa_state':
                            # Use pipe_time for stage comparison, fall back to uarch_time
                            node_time = getattr(node, 'pipe_time', None)
                            if node_time is None:
                                node_time = getattr(node, 'uarch_time', None)
                            if node_time is not None and node_time <= memory_time:
                                stall_edge = Edge(stall_ctrl, node, data={
                                    'type': 'stall',
                                    'description': f'Gate ISA state for memory stall (pipe_time={node_time})'
                                })
                                self.graph.add_edge(stall_edge)
                                isa_state_count += 1
                                print(f"    Connected stall controller to {node_id} (isa_state, pipe_time={node_time})")

                    if isa_state_count > 0:
                        print(f"    Gated {isa_state_count} ISA state element(s) for memory stall")

    def _add_automatic_cache_stalls(self):
        """Automatically detect caches and add bubble insertion logic.

        Unlike data memory stalls which freeze the entire pipeline, instruction cache
        stalls should insert bubbles: PC stalls but later stages continue draining.

        This implements bubble insertion by:
        1. Gating PC advancement with cache stall condition
        2. Gating Decode validity with NOT cache_stall (inserts bubble when cache misses)
        3. NOT gating Decode-to-Execute pipeline registers (let valid instructions pass)
        """
        print("\n  Checking for caches requiring bubble insertion...")

        # Find all cache nodes with stall conditions (read_only_cache and read_write_cache)
        caches = []
        for node_id, node in self.graph.nodes.items():
            if node.data.get('type') in ('read_only_cache', 'read_write_cache'):
                stall_cond_id = node.data.get('stall_condition_node')
                if stall_cond_id:
                    caches.append((node, stall_cond_id))

        if not caches:
            print("  No caches with stall conditions found")
            return

        for cache, stall_cond_id in caches:
            cache_name = cache.id
            print(f"  Processing cache: {cache_name}")

            stall_condition = self.graph.nodes.get(stall_cond_id)
            if not stall_condition:
                print(f"    Warning: Stall condition {stall_cond_id} not found, skipping")
                continue

            # Integrate cache stall into the existing stall controller
            # This follows the same approach as _add_memory_latency_stalls:
            # OR the cache stall into the stall controller's INPUTS, so ALL edges
            # from the stall controller (pc_rd, pipeline registers, etc.) get stalled.

            # Find the existing stall controller (typically PIPE_Decode_stall_ctrl)
            stall_ctrl = self.graph.nodes.get('PIPE_Decode_stall_ctrl')
            if not stall_ctrl:
                # Try to find it via pc_rd stall edge
                pc_rd = self.graph.nodes.get('pc_rd')
                if pc_rd:
                    for edge in pc_rd.incoming_edges:
                        if edge.data.get('type') == 'stall':
                            stall_ctrl = edge.source
                            break

            if stall_ctrl:
                # Find existing control inputs to stall controller
                existing_inputs = [e.source for e in stall_ctrl.incoming_edges
                                   if e.data.get('type') == 'control']

                if stall_condition in existing_inputs:
                    print(f"    Cache stall already connected to {stall_ctrl.id}")
                elif existing_inputs:
                    # OR the cache stall with existing stall conditions
                    or_id = f"{stall_ctrl.id}_with_{cache_name}_stall"
                    if or_id not in self.graph.nodes:
                        or_node = Node(or_id, data={
                            'type': 'operation',
                            'operator': '||',
                            'name': or_id,
                            'description': f'Combined stall: RAW hazards OR {cache_name} miss',
                            'bit_width': 1,
                            'pipeline_component': True
                        })
                        self.graph.add_node(or_node)

                        # Connect existing inputs to OR
                        for idx, inp in enumerate(existing_inputs):
                            self.graph.add_edge(Edge(inp, or_node, data={'type': 'operand', 'operand_index': idx}))
                        # Connect cache stall to OR
                        self.graph.add_edge(Edge(stall_condition, or_node, data={'type': 'operand', 'operand_index': len(existing_inputs)}))

                        # Remove old control edges from stall controller
                        for e in list(stall_ctrl.incoming_edges):
                            if e.data.get('type') == 'control':
                                e.remove_from_nodes()
                                if e.id in self.graph.edges:
                                    del self.graph.edges[e.id]

                        # Connect OR output to stall controller
                        self.graph.add_edge(Edge(or_node, stall_ctrl, data={'type': 'control', 'reason': 'combined_stall_with_cache'}))
                        print(f"    ORed cache stall with existing RAW stalls into {stall_ctrl.id}")
                    else:
                        # OR node already exists, add cache stall to it
                        existing_or = self.graph.nodes[or_id]
                        next_idx = len([e for e in existing_or.incoming_edges if e.data.get('type') == 'operand'])
                        self.graph.add_edge(Edge(stall_condition, existing_or, data={'type': 'operand', 'operand_index': next_idx}))
                        print(f"    Added cache stall to existing OR node {or_id}")
                else:
                    # No existing inputs, connect directly
                    self.graph.add_edge(Edge(stall_condition, stall_ctrl, data={'type': 'control', 'reason': 'cache_miss'}))
                    print(f"    Connected cache stall directly to {stall_ctrl.id}")

                print(f"    Cache {cache_name} stall integrated into stall controller")

                # Also integrate cache stall into Memory stage stall controller
                # This ensures Execute->Memory transition is also gated on cache miss
                # IMPORTANT: Only do this for DATA caches (read_write_cache), not instruction caches
                # Instruction cache stalls should NOT gate Memory stage - Memory should continue
                # to Writeback during icache refills. Only dcache stalls need to hold Memory.
                cache_type = cache.data.get('type', '')
                is_data_cache = cache_type == 'read_write_cache'

                mem_stall_ctrl_id = 'PIPE_Memory_umem_stall_ctrl'
                mem_stall_ctrl = self.graph.nodes.get(mem_stall_ctrl_id)
                if mem_stall_ctrl and is_data_cache:
                    # OR the cache stall into the Memory stage stall controller
                    mem_or_id = f"{mem_stall_ctrl_id}_with_{cache_name}_stall"
                    if mem_or_id not in self.graph.nodes:
                        # Find existing inputs to Memory stall controller
                        mem_existing = [e.source for e in mem_stall_ctrl.incoming_edges
                                       if e.data.get('type') == 'control']

                        if stall_condition not in mem_existing:
                            mem_or_node = Node(mem_or_id, data={
                                'type': 'operation',
                                'operator': '||',
                                'name': mem_or_id,
                                'description': f'Memory stall: umem latency OR {cache_name} miss',
                                'bit_width': 1,
                                'pipeline_component': True
                            })
                            self.graph.add_node(mem_or_node)

                            # Connect existing inputs to OR
                            for idx, inp in enumerate(mem_existing):
                                self.graph.add_edge(Edge(inp, mem_or_node, data={'type': 'operand', 'operand_index': idx}))
                            # Connect cache stall to OR
                            self.graph.add_edge(Edge(stall_condition, mem_or_node, data={'type': 'operand', 'operand_index': len(mem_existing)}))

                            # Remove old control edges from Memory stall controller
                            for e in list(mem_stall_ctrl.incoming_edges):
                                if e.data.get('type') == 'control':
                                    e.remove_from_nodes()
                                    if e.id in self.graph.edges:
                                        del self.graph.edges[e.id]

                            # Connect OR output to Memory stall controller
                            self.graph.add_edge(Edge(mem_or_node, mem_stall_ctrl, data={'type': 'control', 'reason': 'combined_mem_cache_stall'}))
                            print(f"    Extended cache stall to Memory stage via {mem_or_id}")
                    else:
                        print(f"    Cache stall already extended to Memory stage")

                # CRITICAL FIX: Gate ALL Memory-to-Writeback AND Execute-to-Memory registers
                # by Memory stall controller with 'skip_flush_transform'.
                #
                # When there's a cache miss stall AND a flush happens simultaneously,
                # the flush overrides the stall via stall_and_not_flush = stall && !flush = 0.
                # This has two problems:
                #
                # 1. Memory-to-Writeback: The stalled instruction (with X data from cache)
                #    could move to Writeback and write garbage to registers.
                #
                # 2. Execute-to-Memory: The instruction in Memory (waiting for cache data)
                #    could be overwritten by whatever is in Execute. This happens when a
                #    branch/jump in Execute triggers a flush while Memory is stalled.
                #    But the Memory instruction is OLDER than the Execute instruction,
                #    so it should NOT be flushed!
                #
                # We add stall edges with 'skip_flush_transform' flag to prevent the
                # normal stall-to-stall_and_not_flush transformation. This ensures
                # the RAW stall signal is used, keeping registers held during stalls.
                #
                # Registers to protect:
                # - PIPE_Writeback_valid_PIPE
                # - PIPE_Writeback_PIPE_Memory_* (Memory-to-Writeback flow)
                # - PIPE_Memory_valid_PIPE
                # - PIPE_Memory_PIPE_Execute_* (Execute-to-Memory flow)
                if mem_stall_ctrl:
                    registers_gated = 0
                    for node_id, node in self.graph.nodes.items():
                        should_gate = False
                        gate_reason = ''

                        # Gate Memory-to-Writeback registers
                        if node_id == 'PIPE_Writeback_valid_PIPE':
                            should_gate = True
                            gate_reason = 'Writeback valid'
                        elif node_id.startswith('PIPE_Writeback_PIPE_Memory_'):
                            should_gate = True
                            gate_reason = 'Memory-to-Writeback'

                        # Gate Execute-to-Memory registers
                        # These are already gated by Memory stall controller, but we need
                        # to ensure they use skip_flush_transform
                        elif node_id == 'PIPE_Memory_valid_PIPE':
                            should_gate = True
                            gate_reason = 'Memory valid'
                        elif node_id.startswith('PIPE_Memory_PIPE_Execute_'):
                            should_gate = True
                            gate_reason = 'Execute-to-Memory'

                        if should_gate:
                            # Check if stall edge with skip_flush_transform already exists
                            has_skip_flush_stall = any(
                                e.data.get('type') == 'stall' and
                                e.source.id == mem_stall_ctrl.id and
                                e.data.get('skip_flush_transform')
                                for e in node.incoming_edges
                            )
                            if not has_skip_flush_stall:
                                # Remove any existing stall edge without skip_flush_transform
                                for e in list(node.incoming_edges):
                                    if (e.data.get('type') == 'stall' and
                                        e.source.id == mem_stall_ctrl.id and
                                        not e.data.get('skip_flush_transform')):
                                        e.remove_from_nodes()
                                        if e.id in self.graph.edges:
                                            del self.graph.edges[e.id]

                                # Add stall edge with flag to skip flush transformation
                                stall_edge = Edge(mem_stall_ctrl, node, data={
                                    'type': 'stall',
                                    'skip_flush_transform': True,  # CRITICAL: Don't transform to stall_and_not_flush
                                    'description': f'Gate {gate_reason} register on Memory stall (dcache miss)'
                                })
                                self.graph.add_edge(stall_edge)
                                registers_gated += 1

                    if registers_gated > 0:
                        print(f"    Added skip_flush_transform stall edges to {registers_gated} Memory/Writeback registers from {mem_stall_ctrl.id}")
            else:
                # No stall controller found - add stall edge directly to pc_rd
                pc_rd = self.graph.nodes.get('pc_rd')
                if pc_rd:
                    stall_edge = Edge(stall_condition, pc_rd, data={
                        'type': 'stall',
                        'description': f'Gate PC on {cache_name} miss'
                    })
                    self.graph.add_edge(stall_edge)
                    print(f"    Added cache stall edge to pc_rd (no stall controller found)")

    def _add_rf_write_forwarding(self):
        """Add write-stage forwarding for memories without write_read_fwd.

        When the memory write stage is at its canonical position (e.g., Writeback writes
        to RF) at the same clock edge that the reader stage needs the value, the pipeline
        register contains stale data. We need to forward the write data if the write
        address matches the read address.

        This uses the hazard information structurally to find the write port signals.
        """
        print("  Adding memory write forwarding...")

        # For each bypass mux, use its hazard to find write signals structurally
        for mux_id, bypass_mux in sorted(self.bypass_muxes.items()):
            # Get the hazard that created this bypass mux
            hazard = self.bypass_hazards.get(mux_id)
            if not hazard:
                print(f"    No hazard info for {mux_id}, skipping")
                continue

            # Check if this memory has write_read_fwd enabled
            if self._memory_has_write_read_fwd(hazard.resource):
                print(f"    Skipping {mux_id} - {hazard.resource} has write_read_fwd enabled")
                continue

            # The write_access_node is the shared write port for this memory
            write_port = hazard.write_access_node

            # Verify it's a memory_write_port
            if write_port.data.get('type') != 'memory_write_port':
                print(f"    Write access is not a memory_write_port: {write_port.id}")
                continue

            # Get the write data and write address from the write port's incoming edges
            write_data = None
            write_addr = None
            write_enable = None

            for edge in sorted(write_port.incoming_edges, key=lambda e: (e.source.id, e.target.id)):
                edge_type = edge.data.get('type')
                if edge_type == 'write_data':
                    write_data = edge.source
                elif edge_type == 'write_address':
                    write_addr = edge.source
                elif edge_type == 'write_enable':
                    write_enable = edge.source

            # Find the write enable (may be gated with valid)
            if not write_enable:
                enable_name = write_port.data.get('combined_write_enable')
                if enable_name:
                    write_enable = self.graph.nodes.get(f"{enable_name}_valid_gated")
                    if not write_enable:
                        write_enable = self.graph.nodes.get(enable_name)

            if not write_data or not write_addr:
                print(f"    Could not find write data/addr for {hazard.resource}")
                continue

            # Find the pipelined read index at Execute stage (from the hazard)
            # Use the same approach as stalling to find the pipelined index
            exec_read_idx = self._find_pipelined_index_at_read(hazard)
            if not exec_read_idx:
                print(f"    Could not find Execute read index for {mux_id}")
                continue

            # Create comparison: write_addr == read_index
            read_idx_name = hazard.read_index_name
            cmp_id = f"fwd_write_{hazard.resource}_{read_idx_name}_cmp"
            cmp_node = Node(cmp_id, data={
                'type': 'comparison',
                'operator': '==',
                'name': cmp_id,
                'bit_width': 1
            })
            self.graph.add_node(cmp_node)

            self.graph.add_edge(Edge(write_addr, cmp_node, data={
                'type': 'left_operand', 'position': 'left'
            }))
            self.graph.add_edge(Edge(exec_read_idx, cmp_node, data={
                'type': 'right_operand', 'position': 'right'
            }))

            # AND with write enable (if available)
            if write_enable:
                and_id = f"fwd_write_{hazard.resource}_{read_idx_name}_valid"
                and_node = Node(and_id, data={
                    'type': 'operation',
                    'operator': '&&',
                    'name': and_id,
                    'bit_width': 1
                })
                self.graph.add_node(and_node)

                self.graph.add_edge(Edge(cmp_node, and_node, data={
                    'type': 'left_operand', 'position': 'left'
                }))
                self.graph.add_edge(Edge(write_enable, and_node, data={
                    'type': 'right_operand', 'position': 'right'
                }))
                fwd_cond = and_node
            else:
                fwd_cond = cmp_node

            # Find and AND with pipelined read enable signal
            # This prevents forwarding when the instruction doesn't actually read this register
            read_enable_id = f"{hazard.resource}_{read_idx_name}_rd_enable"
            pipelined_re_id = f"PIPE_Execute_{read_enable_id}_PIPE"
            pipelined_read_enable = self.graph.nodes.get(pipelined_re_id)

            if not pipelined_read_enable:
                # Try searching by pattern
                for node_id in sorted(self.graph.nodes):
                    if 'Execute' in node_id and read_enable_id in node_id and node_id.endswith('PIPE'):
                        pipelined_read_enable = self.graph.nodes[node_id]
                        break

            if pipelined_read_enable:
                and_id = f"fwd_write_{hazard.resource}_{read_idx_name}_rd_en"
                and_node = Node(and_id, data={
                    'type': 'operation',
                    'operator': '&&',
                    'name': and_id,
                    'bit_width': 1
                })
                self.graph.add_node(and_node)

                self.graph.add_edge(Edge(fwd_cond, and_node, data={
                    'type': 'left_operand', 'position': 'left'
                }))
                self.graph.add_edge(Edge(pipelined_read_enable, and_node, data={
                    'type': 'right_operand', 'position': 'right'
                }))
                fwd_cond = and_node
                print(f"    Added read enable gating to Writeback forwarding")

            # Add to bypass mux as lowest priority (last input)
            num_inputs = bypass_mux.data.get('num_inputs', 0)
            input_index = num_inputs
            bypass_mux.data['num_inputs'] = num_inputs + 1

            # Connect write_data as forwarding value
            fwd_edge = Edge(write_data, bypass_mux, data={
                'type': 'mux_input',
                'input_index': input_index,
                'label': f'forward_{hazard.resource}_write'
            })
            self.graph.add_edge(fwd_edge)

            # Connect condition as select
            sel_edge = Edge(fwd_cond, bypass_mux, data={
                'type': 'mux_select',
                'select_index': input_index
            })
            self.graph.add_edge(sel_edge)

            print(f"    Added {hazard.resource} write forwarding to {mux_id}")
