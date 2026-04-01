#!/usr/bin/env python3
"""
TLB (Translation Lookaside Buffer) Optimization for isacomp.

This module extends the cache optimization framework to provide TLB support
with multi-level tag matching and PTW (Page Table Walk) serialization.

Key features:
- Multi-level tag matching: Entries have "depth" indicating how many VPN fields to match
- Fill all levels: During PTW, cache entries at every level traversed
- PTW serialization: On TLB miss, serialize memory reads via counter-based FSM
- ISA-agnostic: Works with any page table structure (RISC-V Sv32/39/48, OpenPOWER, etc.)

The TLB caches raw PTE data and lets the existing graph logic handle interpretation
(permission checks, PA construction, superpage detection, etc.).
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
import math

from core.resource_graph import ResourceGraph, Node, Edge


@dataclass
class VPNFieldInfo:
    """Information about a VPN field inferred from the graph."""
    level: int              # 0 = leaf, higher = closer to root
    bit_slice_node: str     # Node ID of the bit_slice (e.g., 'pc[31:22]')
    source_node: str        # Source VA node (e.g., 'pc', 'addr')
    high_bit: int           # High bit of VPN in VA
    low_bit: int            # Low bit of VPN in VA
    width: int              # Width in bits


@dataclass
class PTWLevelInfo:
    """Information about a single PTW level inferred from the graph."""
    level: int              # 0 = leaf, higher = closer to root
    depth: int              # 1 = root only, 2 = root+next, etc.
    read_node_id: str       # The array_access node (e.g., 'umem[pte1_addr]_rd')
    address_node_id: str    # The address node (e.g., 'pte1_addr')
    pte_node_id: str        # The PTE output node (e.g., 'pte1')
    vpn_fields: List[VPNFieldInfo]  # VPN fields needed for tag at this depth
    enable_condition: Optional[str]  # Condition for this read (e.g., 'vm_enabled')
    ternary_node_id: Optional[str]   # The ternary selecting this read
    leaf_indicator: Optional[str] = None  # Node ID indicating this level is a leaf (e.g., 'is_leaf_pte1')


@dataclass
class TLBSpec:
    """
    TLB specification - minimal designer input, rest is inferred.

    The designer provides PTW read node IDs in root-to-leaf order.
    Everything else (VPN widths, PTE format, number of levels) is inferred
    from the resource graph.

    Example:
        spec = TLBSpec(
            ptw_reads=['umem[pte1_addr]_rd', 'umem[pte0_addr]_rd'],
            leaf_indicators=['is_leaf_pte1', None],  # pte1 can be superpage, pte0 is always leaf
            tlb_name='itlb',
        )
    """
    # PTW reads in root-to-leaf order (e.g., ['pte1_read', 'pte0_read'])
    ptw_reads: List[str] = field(default_factory=list)

    # Leaf indicators in same order as ptw_reads - node IDs that indicate when
    # each level is a leaf (superpage). Use None for levels that are always leaf
    # or never leaf. The last level is implicitly always a leaf.
    # Example for Sv32: ['is_leaf_pte1', None] - pte1 can be superpage, pte0 is always leaf
    leaf_indicators: List[Optional[str]] = field(default_factory=list)

    # Standard cache parameters
    num_entries: int = 64
    associativity: int = 4
    tlb_name: str = 'tlb'
    replacement_policy: str = 'lru'

    # Inferred during analysis (not set by designer)
    _levels: List[PTWLevelInfo] = field(default_factory=list, repr=False)
    _num_levels: int = 0
    _total_vpn_width: int = 0
    _pte_width: int = 32
    _source_va_node: str = ''

    def __post_init__(self):
        self._num_levels = len(self.ptw_reads)
        # Pad leaf_indicators to match ptw_reads length
        while len(self.leaf_indicators) < len(self.ptw_reads):
            self.leaf_indicators.append(None)


class TLBOptimization:
    """
    TLB optimization with multi-level tag matching and PTW serialization.

    This optimization:
    1. Analyzes the graph to find PTW reads and infer VPN structure
    2. Creates a TLB with depth-aware entries
    3. For each PTW read, inserts TLB lookup and muxes in cached data on hit
    4. Serializes PTW reads on miss using a counter-based FSM
    5. Fills TLB entries at each level after PTW completion
    """

    def __init__(self, graph: ResourceGraph):
        self.graph = graph
        self.created_nodes: List[Node] = []
        self.created_edges: List[Edge] = []
        self.removed_edges: List[str] = []

    def apply(self, spec: TLBSpec) -> bool:
        """
        Apply TLB optimization to the graph.

        Args:
            spec: TLB specification with PTW read node IDs

        Returns:
            True if successful, False otherwise
        """
        print(f"\n{'='*70}")
        print(f"TLB OPTIMIZATION: {spec.tlb_name}")
        print(f"{'='*70}")
        print(f"PTW reads (root→leaf): {spec.ptw_reads}")
        print(f"Entries: {spec.num_entries}, Associativity: {spec.associativity}")

        # Phase 1: ANALYSIS - infer PTW structure from graph
        print(f"\nPhase 1: Analyzing PTW structure...")
        if not self._analyze(spec):
            print("  ERROR: Failed to analyze PTW structure")
            return False

        # Phase 2: PLANNING - compute TLB parameters
        print(f"\nPhase 2: Planning TLB structure...")
        tlb_params = self._plan(spec)

        # Phase 3: STRUCTURE - create TLB node
        print(f"\nPhase 3: Creating TLB node...")
        tlb_node = self._build_structure(spec, tlb_params)

        # Phase 4: HARDWARE - create lookup and match logic
        print(f"\nPhase 4: Generating TLB hardware...")
        self._generate_hardware(spec, tlb_node)

        # Phase 5: CONNECTION - wire TLB to PTW, create bypass muxes
        print(f"\nPhase 5: Wiring TLB to PTW...")
        self._wire_components(spec, tlb_node)

        # Phase 6: CLEANUP
        print(f"\nPhase 6: Cleanup...")
        self._cleanup()

        # Phase 7: TIMING
        print(f"\nPhase 7: Updating timing...")
        self._update_timing()

        print(f"\nTLB optimization complete: {spec.tlb_name}")
        print(f"  Levels: {spec._num_levels}")
        print(f"  Total VPN width: {spec._total_vpn_width} bits")
        print(f"  PTE width: {spec._pte_width} bits")

        return True

    # =========================================================================
    # PHASE 1: ANALYSIS
    # =========================================================================

    def _analyze(self, spec: TLBSpec) -> bool:
        """
        Analyze the graph to infer PTW structure.

        For each PTW read, we find:
        - The address node and trace back to find VPN extraction
        - The PTE output node
        - The enable condition (ternary guard)
        """
        spec._levels = []

        for i, ptw_read_id in enumerate(spec.ptw_reads):
            # Level: 0 = leaf, higher = closer to root
            # Since ptw_reads is root-to-leaf, level = num_reads - 1 - i
            level = len(spec.ptw_reads) - 1 - i
            depth = i + 1  # Depth for matching: 1 = root only, 2 = root+next, etc.

            print(f"  Analyzing level {level} (depth {depth}): {ptw_read_id}")

            # Find the PTW read node
            if ptw_read_id not in self.graph.nodes:
                print(f"    ERROR: Node {ptw_read_id} not found")
                return False

            read_node = self.graph.nodes[ptw_read_id]

            # Find address node (via array_index edge)
            address_node_id = None
            for edge in read_node.incoming_edges:
                if edge.data and edge.data.get('type') == 'array_index':
                    address_node_id = edge.source.id
                    break

            if not address_node_id:
                print(f"    ERROR: No address node found for {ptw_read_id}")
                return False
            print(f"    Address node: {address_node_id}")

            # Find PTE output node (what the read assigns to, via ternary)
            pte_node_id = None
            ternary_node_id = None
            enable_condition = None

            for edge in read_node.outgoing_edges:
                target = edge.target
                if target.data and target.data.get('type') == 'ternary_op':
                    ternary_node_id = target.id
                    # Find the condition
                    for te in target.incoming_edges:
                        if te.data and te.data.get('type') == 'ternary_condition':
                            enable_condition = te.source.id
                            break
                    # Find what the ternary assigns to
                    for te in target.outgoing_edges:
                        if te.data and te.data.get('type') == 'assignment':
                            pte_node_id = te.target.id
                            break
                    break

            if not pte_node_id:
                # Maybe direct assignment without ternary
                for edge in read_node.outgoing_edges:
                    if edge.data and edge.data.get('type') == 'assignment':
                        pte_node_id = edge.target.id
                        break

            # Method 2: If ternary path failed, try mux path (for merged aspects like DTLB)
            # The aspect merger creates multiplexers when combining multiple instruction paths,
            # which can disconnect the ternary from its output. The mux captures the combined path.
            if not pte_node_id:
                for edge in read_node.outgoing_edges:
                    target = edge.target
                    if target.data and target.data.get('type') == 'multiplexer':
                        # Follow mux to find the PTE output via assignment edge
                        for mux_out_edge in target.outgoing_edges:
                            if mux_out_edge.data and mux_out_edge.data.get('type') == 'assignment':
                                pte_node_id = mux_out_edge.target.id
                                break
                        if pte_node_id:
                            break

            if not pte_node_id:
                print(f"    ERROR: No PTE output node found for {ptw_read_id}")
                return False
            print(f"    PTE output: {pte_node_id}")
            print(f"    Ternary: {ternary_node_id}")
            print(f"    Enable condition: {enable_condition}")

            # Trace VPN fields from address node
            vpn_fields = self._trace_vpn_fields(address_node_id, depth)
            print(f"    VPN fields: {[(v.level, v.width, f'{v.high_bit}:{v.low_bit}') for v in vpn_fields]}")

            # Get leaf indicator for this level (if provided)
            leaf_indicator = spec.leaf_indicators[i] if i < len(spec.leaf_indicators) else None
            print(f"    Leaf indicator: {leaf_indicator}")

            level_info = PTWLevelInfo(
                level=level,
                depth=depth,
                read_node_id=ptw_read_id,
                address_node_id=address_node_id,
                pte_node_id=pte_node_id,
                vpn_fields=vpn_fields,
                enable_condition=enable_condition,
                ternary_node_id=ternary_node_id,
                leaf_indicator=leaf_indicator,
            )
            spec._levels.append(level_info)

        # Compute total VPN width and find source VA node
        if spec._levels and spec._levels[-1].vpn_fields:
            all_vpn_fields = spec._levels[-1].vpn_fields  # Leaf level has all VPNs
            spec._total_vpn_width = sum(v.width for v in all_vpn_fields)
            spec._source_va_node = all_vpn_fields[0].source_node if all_vpn_fields else ''

        # Get PTE width from memory
        if spec._levels:
            read_node = self.graph.nodes.get(spec._levels[0].read_node_id)
            if read_node:
                spec._pte_width = read_node.data.get('bit_width', 32)

        return True

    def _trace_vpn_fields(self, address_node_id: str, depth: int) -> List[VPNFieldInfo]:
        """
        Trace from address node back to find VPN bit extractions.

        For depth D, we need VPN fields for levels N-1 down to N-D (root to current).

        The trace follows this path (for RISC-V Sv32 ITLB):
          pte1_addr <- ((satp_ppn << 12) | (vpn1 << 2))  [assignment]
                    <- (vpn1 << 2)                        [operand]
                    <- vpn1                               [operand]
                    <- pc[31:22]                          [assignment]

        So we need to trace through assignment, operand, and other edge types.
        """
        vpn_fields = []
        visited = set()

        def trace_back(node_id: str, current_depth: int):
            # Allow deeper traces - address computation can be several layers deep
            if node_id in visited or current_depth > 10:
                return
            visited.add(node_id)

            node = self.graph.nodes.get(node_id)
            if not node:
                return

            node_type = node.data.get('type', '') if node.data else ''

            # Look for bit_slice nodes that extract VPN
            if node_type == 'bit_slice':
                expr = node.data.get('expression', {})
                rng = expr.get('range', [])
                if rng and len(rng) >= 2:
                    high_bit, low_bit = rng[0], rng[1]
                    width = high_bit - low_bit + 1

                    # Find source (the VA node)
                    source_node = ''
                    for edge in node.incoming_edges:
                        if edge.data and edge.data.get('type') == 'bit_access':
                            source_node = edge.source.id
                            break

                    # Check if this looks like a VPN extraction (10 bits for Sv32, 9 for Sv39)
                    if width in [9, 10, 11, 12] and source_node:
                        vpn_info = VPNFieldInfo(
                            level=len(vpn_fields),  # Will be corrected later
                            bit_slice_node=node_id,
                            source_node=source_node,
                            high_bit=high_bit,
                            low_bit=low_bit,
                            width=width,
                        )
                        vpn_fields.append(vpn_info)
                        # Don't return - continue to find more VPNs

            # Trace through ALL incoming edges to find operands
            for edge in node.incoming_edges:
                edge_type = edge.data.get('type', '') if edge.data else ''
                # Follow most edge types - we want to find all VPN inputs
                if edge_type in ['operand', 'assignment', 'ternary_true', 'ternary_false',
                                 'mux_input', 'mux_default_input', 'logic_input']:
                    trace_back(edge.source.id, current_depth + 1)

        trace_back(address_node_id, 0)

        # Sort VPN fields by bit position (highest first = root level)
        vpn_fields.sort(key=lambda v: -v.high_bit)

        # Assign correct levels (0 = leaf, higher = root)
        for i, vpn in enumerate(vpn_fields):
            vpn.level = len(vpn_fields) - 1 - i

        return vpn_fields

    # =========================================================================
    # PHASE 2: PLANNING
    # =========================================================================

    def _plan(self, spec: TLBSpec) -> Dict[str, Any]:
        """
        Plan TLB structure based on analyzed PTW levels.
        """
        params = {
            'num_levels': spec._num_levels,
            'vpn_widths': [],
            'total_tag_width': 0,
            'pte_width': spec._pte_width,
            'depth_width': max(1, int(math.ceil(math.log2(spec._num_levels + 1)))),
            'index_width': int(math.ceil(math.log2(spec.num_entries // spec.associativity))),
        }

        # Collect unique VPN widths from ALL levels
        # Each level may find different VPN fields used in address calculation
        seen_vpns = set()  # Track by bit range to avoid duplicates
        all_vpn_fields = []

        if spec._levels:
            for level in spec._levels:
                for vpn in level.vpn_fields:
                    # Use (high_bit, low_bit) as unique key
                    vpn_key = (vpn.high_bit, vpn.low_bit)
                    if vpn_key not in seen_vpns:
                        seen_vpns.add(vpn_key)
                        all_vpn_fields.append(vpn)

            # Sort by bit position (highest first = VPN1 before VPN0 for Sv32)
            all_vpn_fields.sort(key=lambda v: -v.high_bit)

            for vpn in all_vpn_fields:
                params['vpn_widths'].append(vpn.width)
            params['total_tag_width'] = sum(params['vpn_widths'])

        print(f"  Levels: {params['num_levels']}")
        print(f"  VPN widths: {params['vpn_widths']}")
        print(f"  Total tag width: {params['total_tag_width']} bits")
        print(f"  Depth field width: {params['depth_width']} bits")
        print(f"  PTE width: {params['pte_width']} bits")

        # Calculate entry width
        entry_width = 1  # valid
        entry_width += params['depth_width']  # depth
        entry_width += params['total_tag_width']  # VPN tags
        entry_width += params['pte_width']  # PTE data
        params['entry_width'] = entry_width
        print(f"  Entry width: {entry_width} bits")

        return params

    # =========================================================================
    # PHASE 3: STRUCTURE
    # =========================================================================

    def _build_structure(self, spec: TLBSpec, params: Dict) -> Node:
        """
        Create the TLB node with multi-level tag matching support.
        """
        # Build per-level info for verilog generator
        level_info_list = []
        for level in spec._levels:
            level_info_list.append({
                'depth': level.depth,
                'read_node_id': level.read_node_id,
                'pte_node_id': level.pte_node_id,
                'leaf_indicator': level.leaf_indicator,
            })

        tlb_node = Node(
            node_id=spec.tlb_name,
            data={
                'type': 'tlb_cache',
                'name': spec.tlb_name,
                'display_name': spec.tlb_name,
                'num_entries': spec.num_entries,
                'associativity': spec.associativity,
                'num_levels': params['num_levels'],
                'vpn_widths': params['vpn_widths'],
                'total_tag_width': params['total_tag_width'],
                'depth_width': params['depth_width'],
                'pte_width': params['pte_width'],
                'entry_width': params['entry_width'],
                'index_width': params['index_width'],
                'replacement_policy': spec.replacement_policy,
                'has_flush_input': True,
                'flush_signals': [],
                # Control signals
                'has_start_input': True,
                'has_idle_output': True,
                'has_complete_output': True,
                # PTW read info for update signal generation
                'ptw_reads': [level.read_node_id for level in spec._levels],
                'leaf_read_node': spec._levels[-1].read_node_id if spec._levels else None,
                # Per-level info for superpage support
                'level_info': level_info_list,
            },
            variable_latency=True,
            latency=1  # Minimum latency (TLB hit)
        )

        self.graph.add_node(tlb_node)
        self.created_nodes.append(tlb_node)

        # Create control signals
        self._create_control_signals(tlb_node, spec)

        # Create per-depth lookup result nodes
        for level_info in spec._levels:
            self._create_depth_lookup_nodes(tlb_node, spec, level_info)

        print(f"  Created TLB node: {spec.tlb_name}")

        return tlb_node

    def _create_control_signals(self, tlb_node: Node, spec: TLBSpec):
        """Create TLB control signals (start, idle, complete, flush)."""
        tlb_name = spec.tlb_name

        # Start signal
        start_node = Node(
            node_id=f"{tlb_name}_start",
            data={
                'type': 'control_signal',
                'signal_type': 'start',
                'tlb': tlb_name,
                'bit_width': 1,
            }
        )
        self.graph.add_node(start_node)
        self.created_nodes.append(start_node)
        self.graph.add_edge(Edge(start_node, tlb_node, data={'type': 'control', 'signal_type': 'start'}))

        # Idle signal
        idle_node = Node(
            node_id=f"{tlb_name}_idle",
            data={
                'type': 'control_signal',
                'signal_type': 'idle',
                'tlb': tlb_name,
                'bit_width': 1,
            }
        )
        self.graph.add_node(idle_node)
        self.created_nodes.append(idle_node)
        self.graph.add_edge(Edge(tlb_node, idle_node, data={'type': 'control', 'signal_type': 'idle'}))

        # Complete signal
        complete_node = Node(
            node_id=f"{tlb_name}_complete",
            data={
                'type': 'control_signal',
                'signal_type': 'complete',
                'tlb': tlb_name,
                'bit_width': 1,
            }
        )
        self.graph.add_node(complete_node)
        self.created_nodes.append(complete_node)
        self.graph.add_edge(Edge(tlb_node, complete_node, data={'type': 'control', 'signal_type': 'complete'}))

        # Store signal references
        tlb_node.data['start_signal'] = start_node.id
        tlb_node.data['idle_signal'] = idle_node.id
        tlb_node.data['complete_signal'] = complete_node.id

        print(f"  Created control signals: {start_node.id}, {idle_node.id}, {complete_node.id}")

    def _create_depth_lookup_nodes(self, tlb_node: Node, spec: TLBSpec, level_info: PTWLevelInfo):
        """Create TLB lookup result nodes for a specific depth."""
        tlb_name = spec.tlb_name
        depth = level_info.depth

        # Hit signal for this depth
        hit_node_id = f"{tlb_name}_hit_depth{depth}"
        hit_node = Node(
            node_id=hit_node_id,
            data={
                'type': 'tlb_hit',
                'name': hit_node_id,
                'tlb': tlb_name,
                'depth': depth,
                'bit_width': 1,
            }
        )
        self.graph.add_node(hit_node)
        self.created_nodes.append(hit_node)
        self.graph.add_edge(Edge(tlb_node, hit_node, data={'type': 'tlb_hit', 'depth': depth}))

        # Data output for this depth
        data_node_id = f"{tlb_name}_data_depth{depth}"
        data_node = Node(
            node_id=data_node_id,
            data={
                'type': 'tlb_data',
                'name': data_node_id,
                'tlb': tlb_name,
                'depth': depth,
                'bit_width': spec._pte_width,
            },
            variable_latency=True
        )
        self.graph.add_node(data_node)
        self.created_nodes.append(data_node)
        self.graph.add_edge(Edge(tlb_node, data_node, data={'type': 'tlb_data', 'depth': depth}))

        print(f"    Created depth {depth} lookup: {hit_node_id}, {data_node_id}")

    # =========================================================================
    # PHASE 4: HARDWARE
    # =========================================================================

    def _generate_hardware(self, spec: TLBSpec, tlb_node: Node):
        """
        Generate TLB lookup hardware (multi-level tag matching).

        The actual Verilog is generated by the backend; here we just
        ensure the graph has the right structure.
        """
        # Create VPN input nodes from ALL unique VPN fields across all levels
        seen_vpns = set()
        all_vpn_fields = []

        if spec._levels:
            for level in spec._levels:
                for vpn in level.vpn_fields:
                    vpn_key = (vpn.high_bit, vpn.low_bit)
                    if vpn_key not in seen_vpns:
                        seen_vpns.add(vpn_key)
                        all_vpn_fields.append(vpn)

            # Sort by bit position (highest first = VPN1 before VPN0)
            all_vpn_fields.sort(key=lambda v: -v.high_bit)

            # Assign sequential levels (0 = highest/root, N-1 = lowest/leaf)
            for i, vpn in enumerate(all_vpn_fields):
                vpn.level = i

            for vpn_info in all_vpn_fields:
                vpn_input_id = f"{spec.tlb_name}_vpn{vpn_info.level}_in"

                # Check if we already have this VPN from the bit slice
                if vpn_info.bit_slice_node in self.graph.nodes:
                    # Create a connection from the bit slice to the TLB
                    bit_slice_node = self.graph.nodes[vpn_info.bit_slice_node]

                    # Create var node for VPN input
                    vpn_node = Node(
                        node_id=vpn_input_id,
                        data={
                            'type': 'var',
                            'name': vpn_input_id,
                            'bit_width': vpn_info.width,
                            'tlb': spec.tlb_name,
                            'vpn_level': vpn_info.level,
                        }
                    )
                    self.graph.add_node(vpn_node)
                    self.created_nodes.append(vpn_node)

                    # Connect bit slice to VPN input
                    self.graph.add_edge(Edge(
                        bit_slice_node, vpn_node,
                        data={'type': 'assignment'}
                    ))

                    # Connect VPN input to TLB
                    self.graph.add_edge(Edge(
                        vpn_node, tlb_node,
                        data={'type': 'tlb_vpn_input', 'vpn_level': vpn_info.level}
                    ))

                    print(f"  Created VPN input: {vpn_input_id} from {vpn_info.bit_slice_node}")

        print(f"  Hardware structure complete")

    # =========================================================================
    # PHASE 5: CONNECTION
    # =========================================================================

    def _wire_components(self, spec: TLBSpec, tlb_node: Node):
        """
        Wire TLB to PTW reads:
        1. For each level, insert mux between TLB data and memory read
        2. Gate memory reads by TLB miss
        3. Create PTW update logic to fill TLB after memory reads
        """
        for level_info in spec._levels:
            self._wire_level_bypass(spec, tlb_node, level_info)

        # Wire flush signal (from sfence_vma)
        self._wire_flush_signals(tlb_node, spec.tlb_name)

        # Create PTW FSM for serialized memory access on miss
        self._create_ptw_fsm(spec, tlb_node)

    def _wire_level_bypass(self, spec: TLBSpec, tlb_node: Node, level_info: PTWLevelInfo):
        """
        Wire TLB bypass for a single PTW level.

        Transforms:
            pte = vm_enabled ? umem[pte_addr] : 0
        To:
            pte = vm_enabled ? (tlb_hit ? tlb_data : umem[pte_addr]) : 0

        We do this by modifying the ternary node's inputs.
        """
        tlb_name = spec.tlb_name
        depth = level_info.depth
        pte_node_id = level_info.pte_node_id
        ternary_node_id = level_info.ternary_node_id
        read_node_id = level_info.read_node_id

        print(f"  Wiring level {level_info.level} (depth {depth}): {pte_node_id}")

        # Get the TLB hit and data nodes for this depth
        hit_node = self.graph.nodes.get(f"{tlb_name}_hit_depth{depth}")
        data_node = self.graph.nodes.get(f"{tlb_name}_data_depth{depth}")

        if not hit_node or not data_node:
            print(f"    ERROR: TLB hit/data nodes not found for depth {depth}")
            return

        # Find the ternary node and its true input (the memory read)
        if not ternary_node_id or ternary_node_id not in self.graph.nodes:
            print(f"    WARNING: No ternary node for {pte_node_id}, skipping bypass")
            return

        ternary_node = self.graph.nodes[ternary_node_id]

        # Create inner mux: tlb_hit ? tlb_data : memory_read
        inner_mux_id = f"{pte_node_id}_tlb_mux"
        inner_mux = Node(
            node_id=inner_mux_id,
            data={
                'type': 'ternary_op',
                'name': inner_mux_id,
                'display_name': f'{pte_node_id} TLB mux',
                'bit_width': spec._pte_width,
            }
        )
        self.graph.add_node(inner_mux)
        self.created_nodes.append(inner_mux)

        # Connect TLB hit as condition
        self.graph.add_edge(Edge(hit_node, inner_mux, data={'type': 'ternary_condition'}))

        # Connect TLB data as true branch
        self.graph.add_edge(Edge(data_node, inner_mux, data={'type': 'ternary_true'}))

        # Find the memory read edge (true input to original ternary)
        read_node = self.graph.nodes.get(read_node_id)
        if read_node:
            # Connect memory read as false branch
            self.graph.add_edge(Edge(read_node, inner_mux, data={'type': 'ternary_false'}))

        # Now rewire the original ternary to use our mux instead of direct memory read
        # Find and remove the edge from read_node to ternary
        for edge in list(ternary_node.incoming_edges):
            if edge.source.id == read_node_id:
                edge_type = edge.data.get('type', '') if edge.data else ''
                if edge_type == 'ternary_true':
                    # Remove old edge
                    edge.remove_from_nodes()
                    if edge.id in self.graph.edges:
                        del self.graph.edges[edge.id]
                    self.removed_edges.append(edge.id)

                    # Add new edge from inner_mux to ternary
                    self.graph.add_edge(Edge(inner_mux, ternary_node, data={'type': 'ternary_true'}))
                    print(f"    Rewired {ternary_node_id} true input to {inner_mux_id}")
                    break

        # Gate the memory read by TLB miss
        # Create: read_enable = original_enable && !tlb_hit
        original_enable = level_info.enable_condition
        if original_enable and original_enable in self.graph.nodes:
            gated_enable_id = f"{read_node_id}_gated_enable"

            # Create NOT(tlb_hit)
            not_hit_id = f"{tlb_name}_miss_depth{depth}"
            not_hit = Node(
                node_id=not_hit_id,
                data={
                    'type': 'operation',
                    'operator': '~',
                    'bit_width': 1,
                }
            )
            self.graph.add_node(not_hit)
            self.created_nodes.append(not_hit)
            self.graph.add_edge(Edge(hit_node, not_hit, data={'type': 'operand'}))

            # Create AND(original_enable, !tlb_hit)
            gated_enable = Node(
                node_id=gated_enable_id,
                data={
                    'type': 'operation',
                    'operator': '&',
                    'bit_width': 1,
                }
            )
            self.graph.add_node(gated_enable)
            self.created_nodes.append(gated_enable)

            enable_node = self.graph.nodes[original_enable]
            self.graph.add_edge(Edge(enable_node, gated_enable, data={'type': 'operand', 'operand_position': 0}))
            self.graph.add_edge(Edge(not_hit, gated_enable, data={'type': 'operand', 'operand_position': 1}))

            # Store gated enable reference
            if read_node:
                read_node.data['gated_enable'] = gated_enable_id

            print(f"    Created gated enable: {gated_enable_id}")

    def _wire_flush_signals(self, tlb_node: Node, tlb_name: str):
        """Wire flush signals from sfence_vma to TLB."""
        # Find flush_target_placeholder nodes for 'tlb'
        placeholders_to_remove = []
        flush_signals = []

        for node_id, node in list(self.graph.nodes.items()):
            if node.data and node.data.get('type') == 'flush_target_placeholder':
                target_cache = node.data.get('cache_name', '')
                if target_cache == 'tlb' or target_cache == tlb_name:
                    # Find incoming flush edge
                    for edge in list(node.incoming_edges):
                        if edge.data and edge.data.get('type') == 'cache_flush':
                            flush_signal = edge.source

                            # Remove placeholder edge
                            self.graph.remove_edge(edge.id)

                            # Create edge from flush signal to TLB
                            self.graph.add_edge(Edge(
                                flush_signal, tlb_node,
                                data={'type': 'cache_flush', 'signal_type': 'flush'}
                            ))

                            flush_signals.append(flush_signal.id)
                            print(f"  Wired flush signal {flush_signal.id} to {tlb_name}")

                    placeholders_to_remove.append(node_id)

        # Remove placeholders
        for node_id in placeholders_to_remove:
            self.graph.remove_node(node_id)

        # Update TLB metadata
        if flush_signals:
            tlb_node.data['flush_signals'] = flush_signals

    def _create_ptw_fsm(self, spec: TLBSpec, tlb_node: Node):
        """
        Create PTW FSM for serialized memory access on TLB miss.

        The FSM:
        - On TLB miss, serializes memory reads across levels
        - After each level read, updates TLB with entry at that depth
        - Uses counter to track current PTW level
        """
        tlb_name = spec.tlb_name
        num_levels = spec._num_levels

        if num_levels <= 1:
            print(f"  PTW FSM not needed (single level)")
            return

        # Create PTW counter (tracks which level we're reading)
        counter_width = max(1, int(math.ceil(math.log2(num_levels))))
        counter_id = f"{tlb_name}_ptw_counter"
        counter_node = Node(
            node_id=counter_id,
            data={
                'type': 'uarch_counter',
                'name': counter_id,
                'bit_width': counter_width,
                'max_value': num_levels - 1,
                'tlb': tlb_name,
            },
            is_uarch_state=True
        )
        self.graph.add_node(counter_node)
        self.created_nodes.append(counter_node)

        # Create PTW active signal (high during page table walk)
        ptw_active_id = f"{tlb_name}_ptw_active"
        ptw_active = Node(
            node_id=ptw_active_id,
            data={
                'type': 'control_signal',
                'signal_type': 'ptw_active',
                'tlb': tlb_name,
                'bit_width': 1,
            }
        )
        self.graph.add_node(ptw_active)
        self.created_nodes.append(ptw_active)

        # Create TLB update signal (pulsed after each level read)
        update_id = f"{tlb_name}_update"
        update_node = Node(
            node_id=update_id,
            data={
                'type': 'control_signal',
                'signal_type': 'tlb_update',
                'tlb': tlb_name,
                'bit_width': 1,
            }
        )
        self.graph.add_node(update_node)
        self.created_nodes.append(update_node)
        self.graph.add_edge(Edge(update_node, tlb_node, data={'type': 'tlb_update'}))

        # Store FSM references in TLB node
        tlb_node.data['ptw_counter'] = counter_id
        tlb_node.data['ptw_active'] = ptw_active_id
        tlb_node.data['ptw_update'] = update_id

        print(f"  Created PTW FSM: counter={counter_id}, active={ptw_active_id}, update={update_id}")

    # =========================================================================
    # PHASE 6: CLEANUP
    # =========================================================================

    def _cleanup(self):
        """Remove disconnected nodes and clean up graph."""
        self.graph.cleanup_disconnected_nodes()
        print(f"  Cleanup complete")

    # =========================================================================
    # PHASE 7: TIMING
    # =========================================================================

    def _update_timing(self):
        """Re-infer timing with TLB's variable latency."""
        self.graph.infer_uarch_time(force_reinfer=True)
        print(f"  Timing updated")


def apply_tlb_optimization(graph: ResourceGraph, spec: TLBSpec) -> bool:
    """
    Convenience function to apply TLB optimization.

    Args:
        graph: Resource graph to modify
        spec: TLB specification

    Returns:
        True if successful, False otherwise

    Example:
        spec = TLBSpec(
            ptw_reads=['umem[pte1_addr]_rd', 'umem[pte0_addr]_rd'],
            num_entries=64,
            associativity=4,
            tlb_name='itlb',
        )
        success = apply_tlb_optimization(graph, spec)
    """
    optimization = TLBOptimization(graph)
    return optimization.apply(spec)


def get_tlb_nodes(graph: ResourceGraph) -> List[Node]:
    """Get all TLB nodes in the graph."""
    return [
        node for node in graph.nodes.values()
        if node.data and node.data.get('type') == 'tlb_cache'
    ]


def wire_tlb_start_signal(graph: ResourceGraph, tlb_name: str) -> bool:
    """
    Wire the start signal for a TLB.

    start = idle && vm_enabled && any_ptw_miss
    """
    tlb = graph.nodes.get(tlb_name)
    if not tlb:
        print(f"ERROR: TLB {tlb_name} not found")
        return False

    start_id = tlb.data.get('start_signal')
    idle_id = tlb.data.get('idle_signal')

    if not start_id or not idle_id:
        print(f"ERROR: TLB {tlb_name} missing start or idle signal")
        return False

    # For now, start = idle (simplified)
    # In full implementation, start = idle && vm_enabled && miss
    start_node = graph.nodes.get(start_id)
    idle_node = graph.nodes.get(idle_id)

    if start_node and idle_node:
        graph.add_edge(Edge(idle_node, start_node, data={'type': 'assignment'}))
        print(f"  Wired {start_id} = {idle_id}")

    return True
