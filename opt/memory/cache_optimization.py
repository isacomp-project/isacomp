#!/usr/bin/env python3
"""
Read-Only Cache Optimization

This optimization inserts a read-only cache before a specified memory node,
redirecting read accesses from the memory to the cache. The cache handles
hit/miss logic internally, with a refill interface connecting to the original
memory for cache misses.

This is useful for:
- Instruction caches (imem)
- Read-only data caches
- Any memory with read-heavy access patterns

The cache is represented as a minimal graph node with configurable parameters.
Backend generation (Verilog) handles all internal logic including:
- Tag and data arrays
- Hit/miss detection
- Refill FSM
- Replacement policy

Integration with Memory Latency Infrastructure:
- Creates start/idle/complete control signals compatible with HazardResolver
- Cache miss triggers pipeline stalls via add_memory_latency_stalls()
- Cache hit (1 cycle) bypasses stall logic
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from core.resource_graph import ResourceGraph, Node, Edge
from core.hardware_builders import HardwareBuilderFactory


@dataclass
class ReadOnlyCacheSpec:
    """Specification for read-only cache insertion."""

    memory_name: str                    # Target memory node name (e.g., 'imem', 'dmem')
    block_size: int = 32                # Cache line size in bytes
    associativity: int = 1              # 1 = direct-mapped, 2/4/8 = set-associative
    num_rows: int = 64                  # Number of cache rows/sets
    address_width: int = 32             # Address width in bits
    data_width: Optional[int] = None    # Data width in bits (inherited from memory if None)
    cache_name: Optional[str] = None    # Optional custom name (default: {memory}_cache)
    replacement_policy: str = 'lru'     # Replacement policy: 'lru', 'random', 'fifo'
    cached_ports: Optional[List[str]] = None  # Read ports to cache (None = all ports)
                                              # List of patterns to match against address node IDs
                                              # e.g., ['ptw'] to cache only PTW ports

    def __post_init__(self):
        """Validate and set defaults."""
        if self.cache_name is None:
            self.cache_name = f"{self.memory_name}_cache"

        # Validate associativity is power of 2
        if self.associativity & (self.associativity - 1) != 0:
            raise ValueError(f"Associativity must be a power of 2, got {self.associativity}")

        # Validate num_rows is power of 2
        if self.num_rows & (self.num_rows - 1) != 0:
            raise ValueError(f"Number of rows must be a power of 2, got {self.num_rows}")

        # Validate block_size is power of 2
        if self.block_size & (self.block_size - 1) != 0:
            raise ValueError(f"Block size must be a power of 2, got {self.block_size}")

    @property
    def offset_width(self) -> int:
        """Calculate offset bits needed within a cache line."""
        return (self.block_size - 1).bit_length()

    @property
    def index_width(self) -> int:
        """Calculate index bits needed to select a cache row."""
        return (self.num_rows - 1).bit_length()

    @property
    def tag_width(self) -> int:
        """Calculate tag bits (remaining address bits after offset and index)."""
        return self.address_width - self.offset_width - self.index_width

    def __str__(self) -> str:
        return (f"ReadOnlyCacheSpec(memory={self.memory_name}, "
                f"block_size={self.block_size}, assoc={self.associativity}, "
                f"rows={self.num_rows}, tag={self.tag_width}b, "
                f"index={self.index_width}b, offset={self.offset_width}b)")


@dataclass
class ReadWriteCacheSpec:
    """Specification for read-write cache with write-through policy.

    This cache supports both read and write operations:
    - Read hit: Returns data in 1 cycle
    - Read miss: Refills from backing memory (variable latency)
    - Write hit: Updates cache AND writes through to backing memory
    - Write miss (no-allocate): Writes directly to backing memory
    - Write miss (write-allocate): Refills line first, then updates and writes through

    Write-through policy ensures backing memory is always up-to-date,
    eliminating the need for dirty bits or writeback logic.
    """

    memory_name: str                    # Target memory node name (e.g., 'dmem', 'umem')
    block_size: int = 32                # Cache line size in bytes
    associativity: int = 1              # 1 = direct-mapped, 2/4/8 = set-associative
    num_rows: int = 64                  # Number of cache rows/sets
    address_width: int = 32             # Address width in bits
    data_width: Optional[int] = None    # Data width in bits (inherited from memory if None)
    cache_name: Optional[str] = None    # Optional custom name (default: {memory}_rwcache)
    replacement_policy: str = 'lru'     # Replacement policy: 'lru', 'random', 'fifo'

    # Port selection (patterns to match against node IDs)
    cached_read_ports: Optional[List[str]] = None   # Read ports to cache (None = all)
    cached_write_ports: Optional[List[str]] = None  # Write ports to cache (None = all)

    # Write policy options
    write_allocate: bool = False        # On write miss: allocate line? (False = simpler)
    write_read_fwd: bool = False        # Forward writes to same-cycle reads?

    def __post_init__(self):
        """Validate and set defaults."""
        if self.cache_name is None:
            self.cache_name = f"{self.memory_name}_rwcache"

        # Validate associativity is power of 2
        if self.associativity & (self.associativity - 1) != 0:
            raise ValueError(f"Associativity must be a power of 2, got {self.associativity}")

        # Validate num_rows is power of 2
        if self.num_rows & (self.num_rows - 1) != 0:
            raise ValueError(f"Number of rows must be a power of 2, got {self.num_rows}")

        # Validate block_size is power of 2
        if self.block_size & (self.block_size - 1) != 0:
            raise ValueError(f"Block size must be a power of 2, got {self.block_size}")

        # Validate replacement policy
        valid_policies = ('lru', 'random', 'fifo')
        if self.replacement_policy not in valid_policies:
            raise ValueError(f"Replacement policy must be one of {valid_policies}, "
                           f"got {self.replacement_policy}")

    @property
    def offset_width(self) -> int:
        """Calculate offset bits needed within a cache line."""
        return (self.block_size - 1).bit_length()

    @property
    def index_width(self) -> int:
        """Calculate index bits needed to select a cache row."""
        return (self.num_rows - 1).bit_length()

    @property
    def tag_width(self) -> int:
        """Calculate tag bits (remaining address bits after offset and index)."""
        return self.address_width - self.offset_width - self.index_width

    def __str__(self) -> str:
        return (f"ReadWriteCacheSpec(memory={self.memory_name}, "
                f"block_size={self.block_size}, assoc={self.associativity}, "
                f"rows={self.num_rows}, tag={self.tag_width}b, "
                f"index={self.index_width}b, offset={self.offset_width}b, "
                f"write_allocate={self.write_allocate}, write_read_fwd={self.write_read_fwd})")


class ReadOnlyCacheOptimization:
    """
    Inserts a read-only cache before a memory node.

    This optimization follows the 7-phase pattern:
    1. ANALYSIS: Find memory node and read accesses
    2. PLANNING: Calculate cache parameters
    3. STRUCTURE: Create cache node
    4. HARDWARE: (Backend handles internals)
    5. CONNECTION: Wire cache to memory and read accesses
    6. CLEANUP: Remove bypassed edges
    7. TIMING: Re-infer with variable latency
    """

    def __init__(self, graph: ResourceGraph):
        self.graph = graph
        self.hw_factory = HardwareBuilderFactory(graph)
        self.created_nodes: List[Node] = []
        self.created_edges: List[Edge] = []

    def apply(self, spec: ReadOnlyCacheSpec) -> bool:
        """
        Apply cache optimization to the graph.

        Args:
            spec: Cache specification

        Returns:
            True if successful, False otherwise
        """
        print(f"Applying read-only cache optimization: {spec}")

        # PHASE 1: Analysis
        analysis = self._analyze(spec)
        if analysis is None:
            return False

        # PHASE 2: Planning
        cache_params = self._plan(spec, analysis)
        print(f"  Cache parameters: tag={cache_params['tag_width']}b, "
              f"index={cache_params['index_width']}b, offset={cache_params['offset_width']}b")

        # PHASE 3: Structure
        cache_node = self._build_structure(spec, cache_params, analysis)
        print(f"  Created cache node: {cache_node.id}")

        # PHASE 4: Hardware (backend handles internals)
        # No additional hardware generation needed here

        # PHASE 5: Connection
        self._wire_components(spec, cache_node, analysis)
        print(f"  Wired {len(analysis['read_accesses'])} read port(s) to cache")

        # PHASE 5b: Wire any flush signals from ISA (fence.i, sfence.vma, etc.)
        self._wire_flush_signals(cache_node, spec.cache_name)

        # PHASE 6: Cleanup
        self._cleanup(analysis)

        # PHASE 7: Timing
        self._update_timing()
        print(f"  Updated timing with variable_latency=True")

        print(f"Successfully added cache '{spec.cache_name}' before memory '{spec.memory_name}'")
        return True

    # =========================================================================
    # PHASE 1: ANALYSIS
    # =========================================================================

    def _analyze(self, spec: ReadOnlyCacheSpec) -> Optional[Dict]:
        """
        Analyze the graph to find the target memory and its read accesses.

        Returns:
            Analysis dict with memory_node and read_accesses, or None if failed
        """
        # Find the memory node
        memory_node = self._find_memory_node(spec.memory_name)
        if memory_node is None:
            print(f"Error: Memory '{spec.memory_name}' not found in graph")
            return None

        # Get memory properties
        bit_width = memory_node.data.get('bit_width', 32)
        addr_width = memory_node.data.get('array_depth', 10)

        print(f"  Found memory '{spec.memory_name}':")
        print(f"    Data width: {bit_width} bits")
        print(f"    Address width: {addr_width} bits")

        # Find all read accesses to this memory (optionally filtered by cached_ports)
        read_accesses = self._find_read_accesses(memory_node, spec.memory_name, spec.cached_ports)
        if spec.cached_ports:
            print(f"    Read accesses: {len(read_accesses)} (filtered by: {spec.cached_ports})")
        else:
            print(f"    Read accesses: {len(read_accesses)} (all ports)")

        if not read_accesses:
            if spec.cached_ports:
                print(f"Error: No read accesses found for memory '{spec.memory_name}' matching {spec.cached_ports}")
            else:
                print(f"Error: No read accesses found for memory '{spec.memory_name}'")
            return None

        return {
            'memory_node': memory_node,
            'bit_width': bit_width,
            'addr_width': addr_width,
            'read_accesses': read_accesses
        }

    def _find_memory_node(self, memory_name: str) -> Optional[Node]:
        """Find a memory node by name."""
        for node in self.graph.nodes.values():
            if node.data:
                # Check by name
                if node.data.get('name') == memory_name:
                    if node.data.get('is_memory', False) or node.data.get('type') == 'isa_state mem':
                        return node
                # Check by ID
                if node.id == memory_name:
                    if node.data.get('is_memory', False) or node.data.get('type') == 'isa_state mem':
                        return node
        return None

    def _find_read_accesses(self, memory_node: Node, memory_name: str,
                            cached_ports: Optional[List[str]] = None) -> List[Dict]:
        """
        Find all read accesses to the given memory.

        Read access pattern:
          memory --[array_base]--> array_access <--[array_index]-- address
          array_access --[assignment]--> target

        Args:
            memory_node: The memory node to find accesses for
            memory_name: Name of the memory
            cached_ports: Optional list of patterns to filter which ports to cache.
                         If None or empty, cache all read ports.
                         Patterns are matched against address node IDs (substring match).
                         e.g., ['ptw'] matches 'ptw_level0_addr', 'dmem_ptw_addr', etc.

        Returns:
            List of dicts with keys: array_access_node, address_node, target_edges
        """
        read_accesses = []

        for node in self.graph.nodes.values():
            if node.data and node.data.get('type') == 'array_access':
                # Check if this is a read access (access_mode == 'read')
                if node.data.get('access_mode') != 'read':
                    continue

                # Check if this array_access is accessing our memory
                is_accessing_memory = False
                address_node = None
                memory_edge = None

                for in_edge in node.incoming_edges:
                    edge_type = in_edge.data.get('type') if in_edge.data else None
                    source = in_edge.source
                    source_name = source.data.get('name', source.id) if source.data else source.id

                    # Memory connects via array_base edge
                    if edge_type == 'array_base':
                        if source_name == memory_name or source.id == memory_name:
                            is_accessing_memory = True
                            memory_edge = in_edge
                    # Address connects via array_index edge
                    elif edge_type == 'array_index':
                        address_node = source

                if is_accessing_memory:
                    # Check if this is a read (has outgoing edges that use the data)
                    # Accept assignment edges OR operand edges (for ternary expressions)
                    target_edges = [
                        edge for edge in node.outgoing_edges
                        if edge.data.get('type') in ('assignment', 'operand', 'ternary_true',
                                                      'ternary_false', 'mux_input')
                    ]

                    if target_edges or node.outgoing_edges:
                        # Filter by cached_ports if specified
                        if cached_ports:
                            # Get address node ID for matching
                            addr_id = address_node.id if address_node else ''
                            # Also check the array_access node ID
                            access_id = node.id

                            # Check if any pattern matches
                            matches = any(
                                pattern in addr_id or pattern in access_id
                                for pattern in cached_ports
                            )
                            if not matches:
                                continue  # Skip this port - not in cached_ports list

                        read_accesses.append({
                            'array_access_node': node,
                            'address_node': address_node,
                            'memory_edge': memory_edge,
                            'target_edges': target_edges
                        })

        return read_accesses

    # =========================================================================
    # PHASE 2: PLANNING
    # =========================================================================

    def _plan(self, spec: ReadOnlyCacheSpec, analysis: Dict) -> Dict:
        """
        Calculate cache parameters based on spec and memory analysis.

        Returns:
            Dict with derived cache parameters
        """
        # Use data width from memory if not specified
        data_width = spec.data_width
        if data_width is None:
            data_width = analysis['bit_width']

        # Update spec with inherited data width
        spec.data_width = data_width

        return {
            'data_width': data_width,
            'address_width': spec.address_width,
            'tag_width': spec.tag_width,
            'index_width': spec.index_width,
            'offset_width': spec.offset_width,
            'num_read_ports': len(analysis['read_accesses'])
        }

    # =========================================================================
    # PHASE 3: STRUCTURE
    # =========================================================================

    def _build_structure(self, spec: ReadOnlyCacheSpec, cache_params: Dict,
                         analysis: Dict) -> Node:
        """
        Create the cache node and control signals.

        Creates:
        - Cache node with variable_latency=True
        - Control signals: start, idle, complete (compatible with HazardResolver)

        Returns:
            The created cache node
        """
        cache_node = Node(
            node_id=spec.cache_name,
            data={
                'type': 'read_only_cache',
                'name': spec.cache_name,
                'display_name': spec.cache_name,
                'memory_name': spec.memory_name,
                'block_size': spec.block_size,
                'associativity': spec.associativity,
                'num_rows': spec.num_rows,
                'address_width': spec.address_width,
                'data_width': cache_params['data_width'],
                'tag_width': cache_params['tag_width'],
                'index_width': cache_params['index_width'],
                'offset_width': cache_params['offset_width'],
                'num_read_ports': cache_params['num_read_ports'],
                'replacement_policy': spec.replacement_policy,
                # Control signal metadata (compatible with memory latency infrastructure)
                'has_start_input': True,
                'has_idle_output': True,
                'has_complete_output': True,
                # Flush support - will be populated by _wire_flush_signals if flush signals exist
                'has_flush_input': False,
                'flush_signals': [],
            },
            variable_latency=True,
            latency=1  # Minimum latency (hit case)
        )

        self.graph.add_node(cache_node)
        self.created_nodes.append(cache_node)

        # Create control signals following memory latency patterns
        self._create_control_signals(cache_node, spec)

        return cache_node

    def _create_control_signals(self, cache_node: Node, spec: ReadOnlyCacheSpec):
        """
        Create control signals for the cache (start, idle, complete).

        These signals follow the same conventions as set_memory_variable_latency()
        to enable integration with HazardResolver.add_memory_latency_stalls().

        Signals:
        - start: Input indicating a new cache access has started
        - idle: Output indicating cache is ready for new request (not in refill)
        - complete: Output indicating cache access has finished (hit or refill done)
        """
        cache_name = spec.cache_name

        # Create start signal node (input to cache)
        start_node = Node(
            node_id=f"{cache_name}_start",
            data={
                'type': 'control_signal',
                'signal_type': 'start',
                'cache': cache_name,
                'direction': 'input',
                'description': f"Start signal for {cache_name} (new access begun)",
                'bit_width': 1
            }
        )
        self.graph.add_node(start_node)
        self.created_nodes.append(start_node)

        # Edge: start -> cache
        start_edge = Edge(
            source=start_node,
            target=cache_node,
            data={
                'type': 'control',
                'signal_type': 'start',
                'description': f"Start signal for {cache_name}"
            }
        )
        self.graph.add_edge(start_edge)
        self.created_edges.append(start_edge)

        # Create idle signal node (output from cache)
        idle_node = Node(
            node_id=f"{cache_name}_idle",
            data={
                'type': 'control_signal',
                'signal_type': 'idle',
                'cache': cache_name,
                'direction': 'output',
                'description': f"Idle signal for {cache_name} (ready for new request)",
                'bit_width': 1
            }
        )
        self.graph.add_node(idle_node)
        self.created_nodes.append(idle_node)

        # Edge: cache -> idle
        idle_edge = Edge(
            source=cache_node,
            target=idle_node,
            data={
                'type': 'control',
                'signal_type': 'idle',
                'description': f"Idle signal from {cache_name}"
            }
        )
        self.graph.add_edge(idle_edge)
        self.created_edges.append(idle_edge)

        # Create complete signal node (output from cache)
        # Complete = hit OR refill_done
        complete_node = Node(
            node_id=f"{cache_name}_complete",
            data={
                'type': 'control_signal',
                'signal_type': 'complete',
                'cache': cache_name,
                'direction': 'output',
                'description': f"Completion signal for {cache_name} (hit or refill done)",
                'bit_width': 1
            }
        )
        self.graph.add_node(complete_node)
        self.created_nodes.append(complete_node)

        # Edge: cache -> complete
        complete_edge = Edge(
            source=cache_node,
            target=complete_node,
            data={
                'type': 'control',
                'signal_type': 'complete',
                'description': f"Completion signal from {cache_name}"
            }
        )
        self.graph.add_edge(complete_edge)
        self.created_edges.append(complete_edge)

        # Store signal references in cache node metadata
        cache_node.data['start_signal'] = start_node.id
        cache_node.data['idle_signal'] = idle_node.id
        cache_node.data['complete_signal'] = complete_node.id

        print(f"  Created control signals: {start_node.id}, {idle_node.id}, {complete_node.id}")

    # =========================================================================
    # PHASE 4: HARDWARE
    # =========================================================================

    # Backend handles all internal hardware (tag arrays, comparators, etc.)
    # No additional graph nodes needed here

    # =========================================================================
    # PHASE 5: CONNECTION
    # =========================================================================

    def _wire_components(self, spec: ReadOnlyCacheSpec, cache_node: Node,
                         analysis: Dict):
        """
        Wire the cache node to the memory and read accesses.

        Creates:
        - Edges from address nodes to cache (read requests)
        - Edges from cache to array_access nodes (cache data out)
        - Edges from cache to memory (refill address)
        - Edges from memory to cache (refill data)
        - Valid output nodes for each read port
        """
        memory_node = analysis['memory_node']

        # Create refill interface edges
        self._create_refill_interface(cache_node, memory_node, spec)

        # Process each read access
        for port_idx, access in enumerate(analysis['read_accesses']):
            self._wire_read_port(cache_node, access, port_idx, spec)

    def _create_refill_interface(self, cache_node: Node, memory_node: Node,
                                 spec: ReadOnlyCacheSpec):
        """Create the refill interface between cache and backing memory.

        Creates graph structure for:
        - refill_addr: output from cache (address to read from memory)
        - refill_data = memory[refill_addr]: array access from backing memory
        - refill_valid = refill_req: immediate response for single-cycle memory
        """
        cache_name = spec.cache_name
        memory_name = spec.memory_name

        # Create refill address node (output from cache module)
        refill_addr_name = f"{cache_name}_refill_addr"
        refill_addr_node = Node(
            node_id=refill_addr_name,
            data={
                'type': 'cache_refill_addr',
                'name': refill_addr_name,
                'display_name': f'{cache_name} refill addr',
                'bit_width': spec.address_width,
                'cache_name': cache_name,
            }
        )
        self.graph.add_node(refill_addr_node)
        self.created_nodes.append(refill_addr_node)

        # Edge: cache -> refill_addr
        self.graph.add_edge(Edge(
            source=cache_node,
            target=refill_addr_node,
            data={'type': 'refill_addr', 'cache_interface': True}
        ))

        # Create array access node for memory[refill_addr]
        # This follows the same pattern as imem[pc]_rd
        refill_access_name = f"{memory_name}[{refill_addr_name}]_rd"
        refill_access_node = Node(
            node_id=refill_access_name,
            data={
                'type': 'array_access',
                'display_name': refill_access_name,
                'access_mode': 'read',
                'bit_width': spec.data_width,
                'is_refill': True,
                'cache_name': cache_name,  # Store source cache name for nested cache handling
            }
        )
        self.graph.add_node(refill_access_node)
        self.created_nodes.append(refill_access_node)

        # Edge: memory -> array_access (array_base)
        self.graph.add_edge(Edge(
            source=memory_node,
            target=refill_access_node,
            data={'type': 'array_base'}
        ))

        # Edge: refill_addr -> array_access (array_index)
        self.graph.add_edge(Edge(
            source=refill_addr_node,
            target=refill_access_node,
            data={'type': 'array_index'}
        ))

        # Create refill data node (input to cache module)
        # Use type='var' so Verilog generator creates assignment
        refill_data_name = f"{cache_name}_refill_data"
        refill_data_node = Node(
            node_id=refill_data_name,
            data={
                'type': 'var',
                'name': refill_data_name,
                'display_name': f'{cache_name} refill data',
                'bit_width': spec.data_width,
                'cache_name': cache_name,
                'cache_interface': 'refill_data',
            }
        )
        self.graph.add_node(refill_data_node)
        self.created_nodes.append(refill_data_node)

        # Edge: array_access -> refill_data (assignment: refill_data = memory[refill_addr])
        self.graph.add_edge(Edge(
            source=refill_access_node,
            target=refill_data_node,
            data={'type': 'assignment'}
        ))

        # Edge: refill_data -> cache
        self.graph.add_edge(Edge(
            source=refill_data_node,
            target=cache_node,
            data={'type': 'refill_data', 'cache_interface': True}
        ))

        # Create refill_req/refill_valid interface
        refill_req_name = f"{cache_name}_refill_req"
        refill_valid_name = f"{cache_name}_refill_valid"

        # refill_req is output from cache
        refill_req_node = Node(
            node_id=refill_req_name,
            data={
                'type': 'cache_refill_req',
                'name': refill_req_name,
                'bit_width': 1,
                'cache_name': cache_name,
            }
        )
        self.graph.add_node(refill_req_node)
        self.created_nodes.append(refill_req_node)

        # Edge: cache -> refill_req
        self.graph.add_edge(Edge(
            source=cache_node,
            target=refill_req_node,
            data={'type': 'refill_req', 'cache_interface': True}
        ))

        # Note: refill_req -> access_enable connection is made later by
        # connect_cache_refill_to_memory() after wire_memory_start_signal()
        # creates the access_enable node.

        # refill_valid is input to cache
        # For variable latency memory: refill_valid = memory_complete
        # For 1-cycle memory: refill_valid = refill_req (immediate)
        refill_valid_node = Node(
            node_id=refill_valid_name,
            data={
                'type': 'var',
                'name': refill_valid_name,
                'bit_width': 1,
                'cache_name': cache_name,
                'cache_interface': 'refill_valid',
            }
        )
        self.graph.add_node(refill_valid_node)
        self.created_nodes.append(refill_valid_node)

        # Check if backing memory has variable latency
        mem_complete_id = memory_node.data.get('complete_signal')
        if mem_complete_id and mem_complete_id in self.graph.nodes:
            # Variable latency memory - wire refill_valid to memory complete
            mem_complete = self.graph.nodes[mem_complete_id]
            self.graph.add_edge(Edge(
                source=mem_complete,
                target=refill_valid_node,
                data={'type': 'assignment'}
            ))
            print(f"  Wired {refill_valid_name} = {mem_complete_id} (variable latency)")
        else:
            # 1-cycle memory - immediate response
            self.graph.add_edge(Edge(
                source=refill_req_node,
                target=refill_valid_node,
                data={'type': 'assignment'}
            ))
            print(f"  Wired {refill_valid_name} = {refill_req_name} (1-cycle memory)")

        # Edge: refill_valid -> cache
        self.graph.add_edge(Edge(
            source=refill_valid_node,
            target=cache_node,
            data={'type': 'refill_valid', 'cache_interface': True}
        ))

        print(f"  Created refill interface: {refill_data_name} = {memory_name}[{refill_addr_name}]")

    def _wire_read_port(self, cache_node: Node, access: Dict, port_idx: int,
                        spec: ReadOnlyCacheSpec):
        """Wire a single read port through the cache."""
        array_access_node = access['array_access_node']
        address_node = access['address_node']
        memory_edge = access['memory_edge']

        # Create cache read port address input as a var node
        # Then create assignment edge from address_node to it
        read_addr_name = f"{spec.cache_name}_read_addr_{port_idx}"
        if address_node:
            read_addr_node = Node(
                node_id=read_addr_name,
                data={
                    'type': 'var',
                    'name': read_addr_name,
                    'display_name': f'{spec.cache_name} read addr port {port_idx}',
                    'bit_width': spec.address_width,
                    'cache_name': spec.cache_name,
                    'port_index': port_idx,
                }
            )
            self.graph.add_node(read_addr_node)
            self.created_nodes.append(read_addr_node)

            # Assignment edge: address_node -> read_addr (icache_read_addr_0 = pc_rd)
            read_addr_edge = Edge(
                source=address_node,
                target=read_addr_node,
                data={'type': 'assignment'}
            )
            self.graph.add_edge(read_addr_edge)
            self.created_edges.append(read_addr_edge)

            # Also connect to cache for port info (used by Verilog generator for instantiation)
            addr_to_cache_edge = Edge(
                source=read_addr_node,
                target=cache_node,
                data={
                    'type': 'cache_read_addr',
                    'port_index': port_idx,
                    'cache_interface': True
                }
            )
            self.graph.add_edge(addr_to_cache_edge)
            self.created_edges.append(addr_to_cache_edge)

        # Create cache data output node for this port
        read_data_name = f"{spec.cache_name}_data_{port_idx}"
        read_data_node = Node(
            node_id=read_data_name,
            data={
                'type': 'cache_read_data',
                'name': read_data_name,
                'display_name': f'{spec.cache_name} data port {port_idx}',
                'bit_width': spec.data_width,
                'cache_name': spec.cache_name,
                'port_index': port_idx,
            },
            variable_latency=True
        )
        self.graph.add_node(read_data_node)
        self.created_nodes.append(read_data_node)

        # Edge: cache -> read_data (cache outputs data)
        cache_out_edge = Edge(
            source=cache_node,
            target=read_data_node,
            data={
                'type': 'cache_read_data',
                'port_index': port_idx,
                'cache_interface': True
            }
        )
        self.graph.add_edge(cache_out_edge)
        self.created_edges.append(cache_out_edge)

        # Redirect consumers of the array_access node to use cache data output instead
        # The array_access represents imem[pc]_rd - we want its consumers to read from cache
        #
        # Original flow: imem[pc]_rd -> instr
        # New flow:      icache_data_0 -> instr
        #
        # So we need to:
        # 1. Find all outgoing edges from array_access
        # 2. Create new edges from cache_data to those targets
        # 3. Remove the old edges from array_access

        # Collect outgoing edges first (we'll modify during iteration)
        outgoing_edges = list(array_access_node.outgoing_edges)

        for edge in outgoing_edges:
            target = edge.target
            edge_data = dict(edge.data) if edge.data else {}

            # Create new edge from cache data to the original target
            new_edge = Edge(
                source=read_data_node,
                target=target,
                data=edge_data
            )
            self.graph.add_edge(new_edge)
            self.created_edges.append(new_edge)

            # Remove the old edge from array_access
            edge.remove_from_nodes()
            if edge.id in self.graph.edges:
                del self.graph.edges[edge.id]

            print(f"    Redirected {array_access_node.id} -> {target.id} to {read_data_name} -> {target.id}")

        # Remove the memory->array_access edge (array_base)
        if memory_edge:
            memory_edge.remove_from_nodes()
            if memory_edge.id in self.graph.edges:
                del self.graph.edges[memory_edge.id]

        # Also remove the address->array_access edge (array_index)
        # since the cache now handles the address internally
        # We still need address_node -> cache, which was added above
        for edge in list(array_access_node.incoming_edges):
            edge_type = edge.data.get('type') if edge.data else None
            if edge_type == 'array_index':
                edge.remove_from_nodes()
                if edge.id in self.graph.edges:
                    del self.graph.edges[edge.id]

        # The array_access node is now disconnected and will be cleaned up

        # Create cache read request node for this port
        # Connect it to the original read_enable signal if available
        read_req_name = f"{spec.cache_name}_read_req_{port_idx}"
        read_req_node = Node(
            node_id=read_req_name,
            data={
                'type': 'cache_read_req',
                'name': read_req_name,
                'display_name': f'{spec.cache_name} read req port {port_idx}',
                'bit_width': 1,
                'cache_name': spec.cache_name,
                'port_index': port_idx,
            }
        )
        self.graph.add_node(read_req_node)
        self.created_nodes.append(read_req_node)

        # For instruction cache (imem), always request since we're in Fetch stage
        # The read_enable from decode stage doesn't apply here - we always fetch
        # For data cache, we could use a read_enable, but for icache it's constant 1
        # Check if this is an instruction cache by:
        # 1. Memory name contains 'imem' or 'instr'
        # 2. Port index contains 'pc' (instruction fetch is always from PC)
        is_instruction_cache = (
            'imem' in spec.memory_name.lower() or
            'instr' in spec.memory_name.lower() or
            (spec.cached_ports and any('pc' in port.lower() for port in spec.cached_ports))
        )

        if not is_instruction_cache:
            # Check if the original array_access has a read_enable signal
            read_enable_id = array_access_node.data.get('read_enable')
            if read_enable_id and read_enable_id in self.graph.nodes:
                read_enable_node = self.graph.nodes[read_enable_id]
                # Edge: read_enable -> read_req (assignment)
                req_edge = Edge(
                    source=read_enable_node,
                    target=read_req_node,
                    data={'type': 'assignment'}
                )
                self.graph.add_edge(req_edge)
                self.created_edges.append(req_edge)
                print(f"    Connected {read_enable_id} -> {read_req_name}")
            else:
                is_instruction_cache = True  # Fall through to constant 1 path

        if is_instruction_cache:
            # For instruction cache, default to always requesting (1'b1)
            # Create a constant 1 node
            const_one_id = f"{spec.cache_name}_read_active_{port_idx}"
            const_one_node = Node(
                node_id=const_one_id,
                data={
                    'type': 'literal',
                    'value': 1,
                    'bit_width': 1,
                    'display_name': f'{spec.cache_name} always active'
                }
            )
            self.graph.add_node(const_one_node)
            self.created_nodes.append(const_one_node)

            # Edge: const_1 -> read_req
            req_edge = Edge(
                source=const_one_node,
                target=read_req_node,
                data={'type': 'assignment'}
            )
            self.graph.add_edge(req_edge)
            self.created_edges.append(req_edge)
            print(f"    Created constant read request for {read_req_name}")

        # Edge: read_req -> cache (input to cache module)
        req_to_cache_edge = Edge(
            source=read_req_node,
            target=cache_node,
            data={
                'type': 'cache_read_req',
                'port_index': port_idx,
                'cache_interface': True
            }
        )
        self.graph.add_edge(req_to_cache_edge)
        self.created_edges.append(req_to_cache_edge)

        # Create valid output node for this port
        valid_name = f"{spec.cache_name}_valid_{port_idx}"
        valid_node = Node(
            node_id=valid_name,
            data={
                'type': 'cache_valid',
                'name': valid_name,
                'display_name': f'{spec.cache_name} valid port {port_idx}',
                'bit_width': 1,
                'cache_name': spec.cache_name,
                'port_index': port_idx,
            }
        )
        self.graph.add_node(valid_node)
        self.created_nodes.append(valid_node)

        # Edge: cache -> valid
        valid_edge = Edge(
            source=cache_node,
            target=valid_node,
            data={
                'type': 'cache_valid',
                'port_index': port_idx,
                'cache_interface': True
            }
        )
        self.graph.add_edge(valid_edge)
        self.created_edges.append(valid_edge)

        # Connect control signals for port 0 (primary port)
        if port_idx == 0:
            # icache_complete = icache_valid_0 (complete when data valid)
            complete_id = cache_node.data.get('complete_signal')
            if complete_id and complete_id in self.graph.nodes:
                complete_node = self.graph.nodes[complete_id]
                # Change type to 'var' so assignment is generated
                complete_node.data['type'] = 'var'
                complete_node.data['name'] = complete_id
                complete_edge = Edge(
                    source=valid_node,
                    target=complete_node,
                    data={'type': 'assignment'}
                )
                self.graph.add_edge(complete_edge)
                self.created_edges.append(complete_edge)

            # icache_idle = 1'b1 (always ready, FSM handles internally)
            idle_id = cache_node.data.get('idle_signal')
            if idle_id and idle_id in self.graph.nodes:
                idle_node = self.graph.nodes[idle_id]
                # Change type to 'var' so assignment is generated
                idle_node.data['type'] = 'var'
                idle_node.data['name'] = idle_id

                # Create constant 1 for idle
                idle_const_id = f"{spec.cache_name}_always_idle"
                idle_const_node = Node(
                    node_id=idle_const_id,
                    data={
                        'type': 'literal',
                        'value': 1,
                        'bit_width': 1,
                        'display_name': f'{spec.cache_name} always idle'
                    }
                )
                self.graph.add_node(idle_const_node)
                self.created_nodes.append(idle_const_node)

                idle_edge = Edge(
                    source=idle_const_node,
                    target=idle_node,
                    data={'type': 'assignment'}
                )
                self.graph.add_edge(idle_edge)
                self.created_edges.append(idle_edge)

    # =========================================================================
    # PHASE 5b: FLUSH SIGNAL WIRING
    # =========================================================================

    def _wire_flush_signals(self, cache_node: Node, cache_name: str):
        """
        Wire any untied flush signals to this cache.

        Searches for flush_target_placeholder nodes matching this cache name
        and replaces them with actual cache connections. This enables ISA-level
        flush instructions (fence.i, sfence.vma) to control cache invalidation.

        The flush signal will trigger a full cache invalidation when asserted.
        For read-only caches, this simply clears all valid bits.

        Args:
            cache_node: The cache node to wire flush signals to
            cache_name: Name of the cache (used to match placeholder nodes)
        """
        # Find placeholder nodes for this cache
        placeholders_to_remove = []
        flush_signals_connected = []

        for node_id, node in list(self.graph.nodes.items()):
            if node.data and node.data.get('type') == 'flush_target_placeholder':
                if node.data.get('cache_name') == cache_name:
                    # Find the incoming flush edge(s)
                    for edge in list(node.incoming_edges):
                        if edge.data and edge.data.get('type') == 'cache_flush':
                            flush_signal = edge.source

                            # Remove the placeholder edge
                            self.graph.remove_edge(edge.id)

                            # Create proper edge from flush signal to cache
                            new_edge = Edge(
                                source=flush_signal,
                                target=cache_node,
                                data={
                                    'type': 'cache_flush',
                                    'signal_type': 'flush',
                                    'cache_interface': True,
                                }
                            )
                            self.graph.add_edge(new_edge)
                            self.created_edges.append(new_edge)

                            # Track the connected flush signal
                            flush_signals_connected.append(flush_signal.id)

                            print(f"  Wired flush signal {flush_signal.id} to cache {cache_name}")

                    placeholders_to_remove.append(node_id)

        # Remove placeholder nodes
        for node_id in placeholders_to_remove:
            self.graph.remove_node(node_id)

        # Update cache metadata
        if flush_signals_connected:
            cache_node.data['has_flush_input'] = True
            cache_node.data['flush_signals'] = flush_signals_connected
            print(f"  Cache {cache_name} now has {len(flush_signals_connected)} flush signal(s)")

    # =========================================================================
    # PHASE 6: CLEANUP
    # =========================================================================

    def _cleanup(self, analysis: Dict):
        """Remove any bypassed edges and nodes."""
        # The memory node is still needed for refills, so we don't remove it
        # The memory_edge has already been removed in _wire_read_port
        self.graph.cleanup_disconnected_nodes()

    # =========================================================================
    # PHASE 7: TIMING
    # =========================================================================

    def _update_timing(self):
        """Re-infer timing with cache's variable latency."""
        self.graph.infer_uarch_time(force_reinfer=True)


def apply_read_only_cache(graph: ResourceGraph, spec: ReadOnlyCacheSpec) -> bool:
    """
    Convenience function to apply read-only cache optimization.

    Args:
        graph: Resource graph to modify
        spec: Cache specification

    Returns:
        True if successful, False otherwise

    Example:
        spec = ReadOnlyCacheSpec(
            memory_name='imem',
            block_size=32,
            associativity=2,
            num_rows=128,
            address_width=32
        )
        success = apply_read_only_cache(graph, spec)
    """
    optimization = ReadOnlyCacheOptimization(graph)
    return optimization.apply(spec)


def get_cache_nodes(graph: ResourceGraph) -> List[Node]:
    """Get all cache nodes in the graph."""
    return [
        node for node in graph.nodes.values()
        if node.data and node.data.get('type') == 'read_only_cache'
    ]


def get_cache_info(graph: ResourceGraph, cache_name: str) -> Optional[Dict]:
    """
    Get information about a cache node.

    Args:
        graph: Resource graph
        cache_name: Name of the cache

    Returns:
        Dict with cache info or None if not found
    """
    if cache_name not in graph.nodes:
        return None

    cache_node = graph.nodes[cache_name]
    if cache_node.data.get('type') != 'read_only_cache':
        return None

    return {
        'name': cache_node.data.get('name'),
        'memory_name': cache_node.data.get('memory_name'),
        'block_size': cache_node.data.get('block_size'),
        'associativity': cache_node.data.get('associativity'),
        'num_rows': cache_node.data.get('num_rows'),
        'address_width': cache_node.data.get('address_width'),
        'data_width': cache_node.data.get('data_width'),
        'num_read_ports': cache_node.data.get('num_read_ports'),
        'tag_width': cache_node.data.get('tag_width'),
        'index_width': cache_node.data.get('index_width'),
        'offset_width': cache_node.data.get('offset_width'),
        'replacement_policy': cache_node.data.get('replacement_policy'),
        'start_signal': cache_node.data.get('start_signal'),
        'idle_signal': cache_node.data.get('idle_signal'),
        'complete_signal': cache_node.data.get('complete_signal'),
    }


def connect_cache_refill_to_memory(graph: ResourceGraph, cache_name: str, memory_name: str) -> bool:
    """
    Connect a cache's refill_req signal to the memory's access_enable.

    This must be called AFTER wire_memory_start_signal() creates the access_enable.

    Args:
        graph: ResourceGraph with cache and memory
        cache_name: Name of the cache (e.g., 'icache')
        memory_name: Name of the backing memory (e.g., 'umem')

    Returns:
        True if successfully connected, False otherwise
    """
    # Find the refill_req node
    refill_req_id = f"{cache_name}_refill_req"
    refill_req_node = graph.nodes.get(refill_req_id)
    if not refill_req_node:
        print(f"  WARNING: {refill_req_id} not found")
        return False

    # Find the memory's access_enable node
    access_enable_id = f"{memory_name}_access_enable"
    access_enable_node = graph.nodes.get(access_enable_id)
    if not access_enable_node:
        print(f"  WARNING: {access_enable_id} not found")
        return False

    # Find how many inputs the OR gate already has
    existing_inputs = len([e for e in access_enable_node.incoming_edges
                           if e.data.get('type') == 'logic_input'])

    # Add refill_req as another input to the access_enable OR gate
    graph.add_edge(Edge(
        source=refill_req_node,
        target=access_enable_node,
        data={'type': 'logic_input', 'operand_position': existing_inputs}
    ))
    print(f"  Connected {refill_req_id} to {access_enable_id} (input {existing_inputs})")
    return True


def wire_cache_start_signal(graph: ResourceGraph, cache_name: str) -> bool:
    """
    Wire the start signal for a cache using graph structure.

    The start signal should be: idle && read_request
    where read_request indicates a cache read operation.

    This follows the same pattern as wire_memory_start_signal() from
    multi_cycle_operations.py.

    Args:
        graph: ResourceGraph with the cache
        cache_name: Name of the cache

    Returns:
        True if successfully wired, False otherwise
    """
    cache = graph.nodes.get(cache_name)
    if not cache:
        print(f"ERROR: Cache {cache_name} not found")
        return False

    if cache.data.get('type') != 'read_only_cache':
        print(f"ERROR: Node {cache_name} is not a read_only_cache")
        return False

    # Get signal nodes
    start_signal_id = cache.data.get('start_signal')
    idle_signal_id = cache.data.get('idle_signal')

    if not start_signal_id or not idle_signal_id:
        print(f"ERROR: Cache {cache_name} missing start or idle signal")
        return False

    start_signal = graph.nodes.get(start_signal_id)
    idle_signal = graph.nodes.get(idle_signal_id)

    if not start_signal or not idle_signal:
        print(f"ERROR: Could not find start or idle signal nodes")
        return False

    # Find cache read request signals (from cache_read_addr edges)
    read_req_nodes = []
    for edge in cache.incoming_edges:
        if edge.data.get('type') == 'cache_read_addr':
            # The read request is active when address is provided
            # Create a read_req signal for this port
            port_idx = edge.data.get('port_index', 0)
            read_req_id = f"{cache_name}_read_req_{port_idx}"

            if read_req_id not in graph.nodes:
                # Create a read request signal (1'b1 when address is valid)
                read_req_node = Node(
                    node_id=read_req_id,
                    data={
                        'type': 'cache_read_req',
                        'name': read_req_id,
                        'cache': cache_name,
                        'port_index': port_idx,
                        'bit_width': 1,
                        'description': f'Read request for {cache_name} port {port_idx}'
                    }
                )
                graph.add_node(read_req_node)
                read_req_nodes.append(read_req_node)
            else:
                read_req_nodes.append(graph.nodes[read_req_id])

    if not read_req_nodes:
        print(f"  Warning: No read request signals found for {cache_name}")
        # Create a default read request that's always 1 for simplicity
        read_req_id = f"{cache_name}_read_req"
        read_req_node = Node(
            node_id=read_req_id,
            data={
                'type': 'cache_read_req',
                'name': read_req_id,
                'cache': cache_name,
                'bit_width': 1,
                'description': f'Read request for {cache_name}'
            }
        )
        graph.add_node(read_req_node)
        read_req_nodes = [read_req_node]

    # Create OR of all read requests if multiple ports
    if len(read_req_nodes) == 1:
        access_enable_node = read_req_nodes[0]
    else:
        or_gate_id = f"{cache_name}_read_any"
        or_gate = Node(
            node_id=or_gate_id,
            data={
                'type': 'logical_or',
                'description': f'Any read request to {cache_name}',
                'pipeline_component': True,
                'bit_width': 1
            }
        )
        graph.add_node(or_gate)

        for i, req_node in enumerate(read_req_nodes):
            graph.add_edge(Edge(req_node, or_gate, data={
                'type': 'logic_input', 'operand_position': i
            }))

        access_enable_node = or_gate
        print(f"  Created read_any OR with {len(read_req_nodes)} inputs")

    # Create AND gate: idle && access_enable
    and_gate_id = f"{cache_name}_start_condition"
    and_gate = Node(
        node_id=and_gate_id,
        data={
            'type': 'logical_and',
            'description': f'Start condition for {cache_name}: idle && read_req',
            'pipeline_component': True,
            'bit_width': 1
        }
    )
    graph.add_node(and_gate)

    # Connect idle -> AND gate
    graph.add_edge(Edge(idle_signal, and_gate, data={
        'type': 'logic_input', 'operand_position': 0
    }))

    # Connect access_enable -> AND gate
    graph.add_edge(Edge(access_enable_node, and_gate, data={
        'type': 'logic_input', 'operand_position': 1
    }))

    # Connect AND gate -> start signal
    graph.add_edge(Edge(and_gate, start_signal, data={
        'type': 'operand',
        'description': f'Start condition for {cache_name}'
    }))

    print(f"  Wired {start_signal_id} = {idle_signal_id} && {access_enable_node.id}")

    # Store access_enable node for use by stall logic
    cache.data['access_enable_signal'] = access_enable_node.id

    return True


def add_cache_latency_stalls(graph: ResourceGraph, cache_name: str,
                              stage_name: str = None) -> bool:
    """
    Add pipeline stall logic for cache miss handling.

    This integrates with HazardResolver.add_memory_latency_stalls() patterns
    to stall the pipeline on cache misses.

    Args:
        graph: ResourceGraph with the cache and pipeline
        cache_name: Name of the cache
        stage_name: Optional stage name where cache operates (auto-detected if None)

    Returns:
        True if successfully added stalls, False otherwise
    """
    cache = graph.nodes.get(cache_name)
    if not cache:
        print(f"ERROR: Cache {cache_name} not found")
        return False

    if cache.data.get('type') != 'read_only_cache':
        print(f"ERROR: Node {cache_name} is not a read_only_cache")
        return False

    # The cache has variable_latency=True and complete_signal set up
    # We can use the existing HazardResolver infrastructure

    print(f"\nAdding cache latency stalls for {cache_name}...")

    # First wire the start signal if not already done
    if not cache.data.get('access_enable_signal'):
        wire_cache_start_signal(graph, cache_name)

    # The cache node has the same structure as a variable latency memory:
    # - complete_signal: signals when data is ready
    # - access_enable_signal: signals when a read is requested

    # Create stall condition: !complete && access_enable
    complete_signal_id = cache.data.get('complete_signal')
    access_enable_id = cache.data.get('access_enable_signal')

    if not complete_signal_id:
        print(f"  ERROR: Cache {cache_name} missing complete signal")
        return False

    complete_signal = graph.nodes.get(complete_signal_id)
    access_enable = graph.nodes.get(access_enable_id) if access_enable_id else None

    if not complete_signal:
        print(f"  ERROR: Complete signal {complete_signal_id} not found")
        return False

    # Create !complete
    not_complete_id = f"{cache_name}_not_complete"
    if not_complete_id not in graph.nodes:
        not_complete = Node(
            node_id=not_complete_id,
            data={
                'type': 'operation',
                'operator': '!',
                'name': not_complete_id,
                'description': f'Stall while {cache_name} not complete (miss)',
                'pipeline_component': True,
                'bit_width': 1
            }
        )
        graph.add_node(not_complete)
        graph.add_edge(Edge(complete_signal, not_complete, data={
            'type': 'operand',
            'operand_position': 0
        }))
    else:
        not_complete = graph.nodes[not_complete_id]

    # Create stall condition: !complete && access_enable
    stall_signal = not_complete
    if access_enable:
        stall_and_id = f"{cache_name}_stall_condition"
        if stall_and_id not in graph.nodes:
            stall_and = Node(
                node_id=stall_and_id,
                data={
                    'type': 'operation',
                    'operator': '&&',
                    'name': stall_and_id,
                    'description': f'Stall: !complete && is_cache_access',
                    'pipeline_component': True,
                    'bit_width': 1
                }
            )
            graph.add_node(stall_and)
            graph.add_edge(Edge(not_complete, stall_and, data={'type': 'operand', 'operand_index': 0}))
            graph.add_edge(Edge(access_enable, stall_and, data={'type': 'operand', 'operand_index': 1}))
            stall_signal = stall_and
        else:
            stall_signal = graph.nodes[stall_and_id]
        print(f"  Created stall condition: !{complete_signal_id} && {access_enable_id}")
    else:
        print(f"  Created stall condition: !{complete_signal_id}")

    # Find or create a stall controller
    # Use the provided stage_name or try to detect it
    if stage_name is None:
        # Default to 'Fetch' stage for instruction cache, 'Memory' for data
        memory_name = cache.data.get('memory_name', '')
        if 'imem' in memory_name.lower():
            stage_name = 'Fetch'
        else:
            stage_name = 'Memory'

    stall_controller_id = f"PIPE_{stage_name}_{cache_name}_stall_ctrl"

    stall_controller = graph.nodes.get(stall_controller_id)
    if not stall_controller:
        # Check for existing stage stall controller (try various naming conventions)
        # HazardResolver uses different names: PIPE_Decode_stall_ctrl, PIPE_f_stall_ctrl, etc.
        possible_names = [
            f"PIPE_{stage_name}_stall_ctrl",
            f"PIPE_{stage_name.lower()}_stall_ctrl",
            f"PIPE_{stage_name[0].lower()}_stall_ctrl",  # e.g., PIPE_f_stall_ctrl for Fetch
            "PIPE_Decode_stall_ctrl",  # Main RAW stall controller
        ]
        for name in possible_names:
            if name in graph.nodes:
                stall_controller = graph.nodes[name]
                print(f"  Found existing stall controller: {name}")
                break

    # Store the stall condition on the cache node for hazard resolution to use
    # The actual stall/bubble gating logic should be handled by HazardResolver
    cache.data['stall_condition_node'] = stall_signal.id
    cache.data['stall_stage'] = stage_name
    print(f"  Marked cache with stall_condition={stall_signal.id} for hazard resolution")

    print(f"  Cache latency stalls configured for {cache_name}")
    return True


# =============================================================================
# READ-WRITE CACHE (Write-Through)
# =============================================================================

class ReadWriteCacheOptimization:
    """
    Inserts a read-write cache with write-through policy before a memory node.

    This optimization follows the 7-phase pattern:
    1. ANALYSIS: Find memory node, read accesses, and write port
    2. PLANNING: Calculate cache parameters
    3. STRUCTURE: Create cache node with read/write support
    4. HARDWARE: (Backend handles internals)
    5. CONNECTION: Wire cache to memory for reads and write-through
    6. CLEANUP: Remove bypassed edges
    7. TIMING: Re-infer with variable latency

    Write-through policy:
    - All writes immediately update backing memory
    - Cache is updated on write hit (using byte enables for sub-word writes)
    - No dirty bits needed (cache always clean)
    """

    def __init__(self, graph: 'ResourceGraph'):
        self.graph = graph
        self.hw_factory = HardwareBuilderFactory(graph)
        self.created_nodes: List[Node] = []
        self.created_edges: List[Edge] = []

    def apply(self, spec: ReadWriteCacheSpec) -> bool:
        """
        Apply read-write cache optimization to the graph.

        Args:
            spec: Cache specification

        Returns:
            True if successful, False otherwise
        """
        print(f"Applying read-write cache optimization: {spec}")

        # PHASE 1: Analysis
        analysis = self._analyze(spec)
        if analysis is None:
            return False

        # PHASE 2: Planning
        cache_params = self._plan(spec, analysis)
        print(f"  Cache parameters: tag={cache_params['tag_width']}b, "
              f"index={cache_params['index_width']}b, offset={cache_params['offset_width']}b")

        # PHASE 3: Structure
        cache_node = self._build_structure(spec, cache_params, analysis)
        print(f"  Created cache node: {cache_node.id}")

        # PHASE 4: Hardware (backend handles internals)
        # No additional hardware generation needed here

        # PHASE 5: Connection
        self._wire_components(spec, cache_node, analysis)

        # PHASE 6: Cleanup
        self._cleanup(analysis)

        # PHASE 7: Timing
        self._update_timing()
        print(f"  Updated timing with variable_latency=True")

        print(f"Successfully added RW cache '{spec.cache_name}' before memory '{spec.memory_name}'")
        return True

    # =========================================================================
    # PHASE 1: ANALYSIS
    # =========================================================================

    def _analyze(self, spec: ReadWriteCacheSpec) -> Optional[Dict]:
        """
        Analyze the graph to find the target memory, read accesses, and write port.

        Returns:
            Analysis dict with memory_node, read_accesses, and write_port, or None if failed
        """
        # Find the memory node
        memory_node = self._find_memory_node(spec.memory_name)
        if memory_node is None:
            print(f"Error: Memory '{spec.memory_name}' not found in graph")
            return None

        # Get memory properties
        bit_width = memory_node.data.get('bit_width', 32)
        addr_width = memory_node.data.get('array_depth', 10)

        print(f"  Found memory '{spec.memory_name}':")
        print(f"    Data width: {bit_width} bits")
        print(f"    Address width: {addr_width} bits")

        # Find all read accesses to this memory (optionally filtered)
        read_accesses = self._find_read_accesses(memory_node, spec.memory_name,
                                                  spec.cached_read_ports)
        if spec.cached_read_ports:
            print(f"    Read accesses: {len(read_accesses)} (filtered by: {spec.cached_read_ports})")
        else:
            print(f"    Read accesses: {len(read_accesses)} (all ports)")

        # Find the write port for this memory
        write_port = self._find_write_port(spec.memory_name, spec.cached_write_ports)
        if write_port:
            print(f"    Write port: {write_port.id}")
        else:
            print(f"    Write port: None (read-only cache behavior)")

        if not read_accesses and not write_port:
            print(f"Error: No read accesses or write port found for memory '{spec.memory_name}'")
            return None

        return {
            'memory_node': memory_node,
            'bit_width': bit_width,
            'addr_width': addr_width,
            'read_accesses': read_accesses,
            'write_port': write_port
        }

    def _find_memory_node(self, memory_name: str) -> Optional[Node]:
        """Find a memory node by name."""
        for node in self.graph.nodes.values():
            if node.data:
                # Check by name
                if node.data.get('name') == memory_name:
                    if node.data.get('is_memory', False) or node.data.get('type') == 'isa_state mem':
                        return node
                # Check by ID
                if node.id == memory_name:
                    if node.data.get('is_memory', False) or node.data.get('type') == 'isa_state mem':
                        return node
        return None

    def _find_read_accesses(self, memory_node: Node, memory_name: str,
                            cached_ports: Optional[List[str]] = None) -> List[Dict]:
        """
        Find all read accesses to the given memory.

        This reuses the same pattern as ReadOnlyCacheOptimization._find_read_accesses().
        """
        read_accesses = []

        for node in self.graph.nodes.values():
            if node.data and node.data.get('type') == 'array_access':
                # Check if this is a read access (access_mode == 'read')
                if node.data.get('access_mode') != 'read':
                    continue

                # Skip cache refill accesses - they should bypass this cache
                # and access the backing memory directly. Otherwise, icache refills
                # would go through dcache, which has incompatible block sizes.
                if node.data.get('is_refill'):
                    print(f"    Skipping cache refill access: {node.id} (direct to backing memory)")
                    continue

                # Check if this array_access is accessing our memory
                is_accessing_memory = False
                address_node = None
                memory_edge = None

                for in_edge in node.incoming_edges:
                    edge_type = in_edge.data.get('type') if in_edge.data else None
                    source = in_edge.source
                    source_name = source.data.get('name', source.id) if source.data else source.id

                    # Memory connects via array_base edge
                    if edge_type == 'array_base':
                        if source_name == memory_name or source.id == memory_name:
                            is_accessing_memory = True
                            memory_edge = in_edge
                    # Address connects via array_index edge
                    elif edge_type == 'array_index':
                        address_node = source

                if is_accessing_memory:
                    # Check if this is a read (has outgoing edges that use the data)
                    target_edges = [
                        edge for edge in node.outgoing_edges
                        if edge.data.get('type') in ('assignment', 'operand', 'ternary_true',
                                                      'ternary_false', 'mux_input')
                    ]

                    if target_edges or node.outgoing_edges:
                        # Filter by cached_ports if specified
                        if cached_ports:
                            addr_id = address_node.id if address_node else ''
                            access_id = node.id

                            matches = any(
                                pattern in addr_id or pattern in access_id
                                for pattern in cached_ports
                            )
                            if not matches:
                                continue

                        read_accesses.append({
                            'array_access_node': node,
                            'address_node': address_node,
                            'memory_edge': memory_edge,
                            'target_edges': target_edges
                        })

        return read_accesses

    def _find_write_port(self, memory_name: str,
                         cached_write_ports: Optional[List[str]] = None) -> Optional[Node]:
        """
        Find the memory_write_port node for the given memory.

        The write port is identified by:
        - type == 'memory_write_port'
        - base_memory == memory_name
        - Has outgoing 'memory_write' edge to the memory

        Args:
            memory_name: Name of the target memory
            cached_write_ports: Optional patterns to filter write ports

        Returns:
            The memory_write_port node, or None if not found
        """
        for node in self.graph.nodes.values():
            if not node.data:
                continue

            if node.data.get('type') != 'memory_write_port':
                continue

            # Check if this write port targets our memory
            base_memory = node.data.get('base_memory')
            if base_memory != memory_name:
                continue

            # Verify it has an edge to the memory
            has_memory_edge = False
            for edge in node.outgoing_edges:
                if edge.data.get('type') == 'memory_write':
                    target_name = edge.target.data.get('name', edge.target.id) if edge.target.data else edge.target.id
                    if target_name == memory_name or edge.target.id == memory_name:
                        has_memory_edge = True
                        break

            if has_memory_edge:
                # Optional: filter by cached_write_ports patterns
                if cached_write_ports:
                    # Check if any writer matches the patterns
                    writers = node.data.get('writers', [])
                    # For now, accept if the write port exists - filtering by
                    # individual writers would require more complex logic
                    pass

                return node

        return None

    # =========================================================================
    # PHASE 2: PLANNING
    # =========================================================================

    def _plan(self, spec: ReadWriteCacheSpec, analysis: Dict) -> Dict:
        """Calculate cache parameters based on spec and memory analysis."""
        data_width = spec.data_width
        if data_width is None:
            data_width = analysis['bit_width']

        spec.data_width = data_width

        return {
            'data_width': data_width,
            'address_width': spec.address_width,
            'tag_width': spec.tag_width,
            'index_width': spec.index_width,
            'offset_width': spec.offset_width,
            'num_read_ports': len(analysis['read_accesses']),
            'has_write_port': analysis['write_port'] is not None
        }

    # =========================================================================
    # PHASE 3: STRUCTURE
    # =========================================================================

    def _build_structure(self, spec: ReadWriteCacheSpec, cache_params: Dict,
                         analysis: Dict) -> Node:
        """Create the cache node and control signals."""
        cache_node = Node(
            node_id=spec.cache_name,
            data={
                'type': 'read_write_cache',
                'name': spec.cache_name,
                'display_name': spec.cache_name,
                'memory_name': spec.memory_name,
                'block_size': spec.block_size,
                'associativity': spec.associativity,
                'num_rows': spec.num_rows,
                'address_width': spec.address_width,
                'data_width': cache_params['data_width'],
                'tag_width': cache_params['tag_width'],
                'index_width': cache_params['index_width'],
                'offset_width': cache_params['offset_width'],
                'num_read_ports': cache_params['num_read_ports'],
                'has_write_port': cache_params['has_write_port'],
                'replacement_policy': spec.replacement_policy,
                'write_allocate': spec.write_allocate,
                'write_read_fwd': spec.write_read_fwd,
                # Control signal metadata
                'has_start_input': True,
                'has_idle_output': True,
                'has_complete_output': True,
            },
            variable_latency=True,
            latency=1  # Minimum latency (hit case)
        )

        self.graph.add_node(cache_node)
        self.created_nodes.append(cache_node)

        # Create control signals
        self._create_control_signals(cache_node, spec)

        return cache_node

    def _create_control_signals(self, cache_node: Node, spec: ReadWriteCacheSpec):
        """Create control signals for the cache (start, idle, complete)."""
        cache_name = spec.cache_name

        # Create start signal node
        start_node = Node(
            node_id=f"{cache_name}_start",
            data={
                'type': 'control_signal',
                'signal_type': 'start',
                'cache': cache_name,
                'direction': 'input',
                'description': f"Start signal for {cache_name}",
                'bit_width': 1
            }
        )
        self.graph.add_node(start_node)
        self.created_nodes.append(start_node)

        start_edge = Edge(
            source=start_node,
            target=cache_node,
            data={'type': 'control', 'signal_type': 'start'}
        )
        self.graph.add_edge(start_edge)
        self.created_edges.append(start_edge)

        # Create idle signal node
        idle_node = Node(
            node_id=f"{cache_name}_idle",
            data={
                'type': 'control_signal',
                'signal_type': 'idle',
                'cache': cache_name,
                'direction': 'output',
                'description': f"Idle signal for {cache_name}",
                'bit_width': 1
            }
        )
        self.graph.add_node(idle_node)
        self.created_nodes.append(idle_node)

        idle_edge = Edge(
            source=cache_node,
            target=idle_node,
            data={'type': 'control', 'signal_type': 'idle'}
        )
        self.graph.add_edge(idle_edge)
        self.created_edges.append(idle_edge)

        # Create complete signal node
        complete_node = Node(
            node_id=f"{cache_name}_complete",
            data={
                'type': 'control_signal',
                'signal_type': 'complete',
                'cache': cache_name,
                'direction': 'output',
                'description': f"Completion signal for {cache_name}",
                'bit_width': 1
            }
        )
        self.graph.add_node(complete_node)
        self.created_nodes.append(complete_node)

        complete_edge = Edge(
            source=cache_node,
            target=complete_node,
            data={'type': 'control', 'signal_type': 'complete'}
        )
        self.graph.add_edge(complete_edge)
        self.created_edges.append(complete_edge)

        # Create write_complete signal node (for write-through completion)
        write_complete_node = Node(
            node_id=f"{cache_name}_write_complete",
            data={
                'type': 'control_signal',
                'signal_type': 'write_complete',
                'cache': cache_name,
                'direction': 'output',
                'description': f"Write-through completion signal for {cache_name}",
                'bit_width': 1
            }
        )
        self.graph.add_node(write_complete_node)
        self.created_nodes.append(write_complete_node)

        write_complete_edge = Edge(
            source=cache_node,
            target=write_complete_node,
            data={'type': 'control', 'signal_type': 'write_complete'}
        )
        self.graph.add_edge(write_complete_edge)
        self.created_edges.append(write_complete_edge)

        # Store signal references
        cache_node.data['start_signal'] = start_node.id
        cache_node.data['idle_signal'] = idle_node.id
        cache_node.data['complete_signal'] = complete_node.id
        cache_node.data['write_complete_signal'] = write_complete_node.id

        print(f"  Created control signals: {start_node.id}, {idle_node.id}, {complete_node.id}, {write_complete_node.id}")

    # =========================================================================
    # PHASE 5: CONNECTION
    # =========================================================================

    def _wire_components(self, spec: ReadWriteCacheSpec, cache_node: Node,
                         analysis: Dict):
        """Wire the cache node to memory for reads and write-through."""
        memory_node = analysis['memory_node']
        write_port = analysis['write_port']

        # Create refill interface for read misses (same as ROCache)
        self._create_refill_interface(cache_node, memory_node, spec)

        # Wire read ports (reuse ROCache pattern)
        for port_idx, access in enumerate(analysis['read_accesses']):
            self._wire_read_port(cache_node, access, port_idx, spec)

        print(f"  Wired {len(analysis['read_accesses'])} read port(s) to cache")

        # Wire write port through cache
        if write_port:
            self._wire_write_port(cache_node, write_port, memory_node, spec)
            print(f"  Wired write port through cache with write-through")

    def _create_refill_interface(self, cache_node: Node, memory_node: Node,
                                 spec: ReadWriteCacheSpec):
        """Create the refill interface between cache and backing memory.

        This is similar to ROCache but for the RW cache.
        """
        cache_name = spec.cache_name
        memory_name = spec.memory_name

        # Create refill address node
        refill_addr_name = f"{cache_name}_refill_addr"
        refill_addr_node = Node(
            node_id=refill_addr_name,
            data={
                'type': 'cache_refill_addr',
                'name': refill_addr_name,
                'display_name': f'{cache_name} refill addr',
                'bit_width': spec.address_width,
                'cache_name': cache_name,
            }
        )
        self.graph.add_node(refill_addr_node)
        self.created_nodes.append(refill_addr_node)

        self.graph.add_edge(Edge(
            source=cache_node,
            target=refill_addr_node,
            data={'type': 'refill_addr', 'cache_interface': True}
        ))

        # Create array access for memory[refill_addr]
        refill_access_name = f"{memory_name}[{refill_addr_name}]_rd"
        refill_access_node = Node(
            node_id=refill_access_name,
            data={
                'type': 'array_access',
                'display_name': refill_access_name,
                'access_mode': 'read',
                'bit_width': spec.data_width,
                'is_refill': True,
                'cache_name': cache_name,
            }
        )
        self.graph.add_node(refill_access_node)
        self.created_nodes.append(refill_access_node)

        # memory -> array_access (array_base)
        self.graph.add_edge(Edge(
            source=memory_node,
            target=refill_access_node,
            data={'type': 'array_base'}
        ))

        # refill_addr -> array_access (array_index)
        self.graph.add_edge(Edge(
            source=refill_addr_node,
            target=refill_access_node,
            data={'type': 'array_index'}
        ))

        # Create refill data node
        refill_data_name = f"{cache_name}_refill_data"
        refill_data_node = Node(
            node_id=refill_data_name,
            data={
                'type': 'var',
                'name': refill_data_name,
                'display_name': f'{cache_name} refill data',
                'bit_width': spec.data_width,
                'cache_name': cache_name,
                'cache_interface': 'refill_data',
            }
        )
        self.graph.add_node(refill_data_node)
        self.created_nodes.append(refill_data_node)

        # array_access -> refill_data (assignment)
        self.graph.add_edge(Edge(
            source=refill_access_node,
            target=refill_data_node,
            data={'type': 'assignment'}
        ))

        # refill_data -> cache
        self.graph.add_edge(Edge(
            source=refill_data_node,
            target=cache_node,
            data={'type': 'refill_data', 'cache_interface': True}
        ))

        # Create refill_req/refill_valid
        refill_req_name = f"{cache_name}_refill_req"
        refill_valid_name = f"{cache_name}_refill_valid"

        refill_req_node = Node(
            node_id=refill_req_name,
            data={
                'type': 'cache_refill_req',
                'name': refill_req_name,
                'bit_width': 1,
                'cache_name': cache_name,
            }
        )
        self.graph.add_node(refill_req_node)
        self.created_nodes.append(refill_req_node)

        self.graph.add_edge(Edge(
            source=cache_node,
            target=refill_req_node,
            data={'type': 'refill_req', 'cache_interface': True}
        ))

        refill_valid_node = Node(
            node_id=refill_valid_name,
            data={
                'type': 'var',
                'name': refill_valid_name,
                'bit_width': 1,
                'cache_name': cache_name,
                'cache_interface': 'refill_valid',
            }
        )
        self.graph.add_node(refill_valid_node)
        self.created_nodes.append(refill_valid_node)

        # Check if backing memory has variable latency
        mem_complete_id = memory_node.data.get('complete_signal')
        if mem_complete_id and mem_complete_id in self.graph.nodes:
            mem_complete = self.graph.nodes[mem_complete_id]
            self.graph.add_edge(Edge(
                source=mem_complete,
                target=refill_valid_node,
                data={'type': 'assignment'}
            ))
            print(f"  Wired {refill_valid_name} = {mem_complete_id} (variable latency)")
        else:
            self.graph.add_edge(Edge(
                source=refill_req_node,
                target=refill_valid_node,
                data={'type': 'assignment'}
            ))
            print(f"  Wired {refill_valid_name} = {refill_req_name} (1-cycle memory)")

        self.graph.add_edge(Edge(
            source=refill_valid_node,
            target=cache_node,
            data={'type': 'refill_valid', 'cache_interface': True}
        ))

        print(f"  Created refill interface: {refill_data_name} = {memory_name}[{refill_addr_name}]")

    def _wire_read_port(self, cache_node: Node, access: Dict, port_idx: int,
                        spec: ReadWriteCacheSpec):
        """Wire a single read port through the cache.

        This follows the same pattern as ROCache._wire_read_port().
        """
        array_access_node = access['array_access_node']
        address_node = access['address_node']
        memory_edge = access['memory_edge']

        # Create cache read address input
        # IMPORTANT: Use Memory stage pipelined address for cache read, not Execute stage.
        # This is because when a load stalls (cache miss), the Execute stage may have
        # moved on to the next instruction, but the cache still needs the original
        # address to complete the read. The Memory stage holds the stalled address.
        read_addr_name = f"{spec.cache_name}_read_addr_{port_idx}"
        if address_node:
            # Look for Memory stage pipelined version of the address
            # Pattern: PIPE_Memory_{original_name}_PIPE
            mem_addr_id = f"PIPE_Memory_{address_node.id}_PIPE"
            mem_addr_node = self.graph.nodes.get(mem_addr_id)

            if mem_addr_node:
                print(f"    Using Memory stage address: {mem_addr_id}")
                cache_addr_source = mem_addr_node
            else:
                # Fall back to Execute stage address
                print(f"    WARNING: Memory stage address {mem_addr_id} not found, using Execute stage")
                cache_addr_source = address_node

            read_addr_node = Node(
                node_id=read_addr_name,
                data={
                    'type': 'var',
                    'name': read_addr_name,
                    'display_name': f'{spec.cache_name} read addr port {port_idx}',
                    'bit_width': spec.address_width,
                    'cache_name': spec.cache_name,
                    'port_index': port_idx,
                }
            )
            self.graph.add_node(read_addr_node)
            self.created_nodes.append(read_addr_node)

            # Memory stage address -> read_addr (assignment)
            read_addr_edge = Edge(
                source=cache_addr_source,
                target=read_addr_node,
                data={'type': 'assignment'}
            )
            self.graph.add_edge(read_addr_edge)
            self.created_edges.append(read_addr_edge)

            # read_addr -> cache
            addr_to_cache_edge = Edge(
                source=read_addr_node,
                target=cache_node,
                data={
                    'type': 'cache_read_addr',
                    'port_index': port_idx,
                    'cache_interface': True
                }
            )
            self.graph.add_edge(addr_to_cache_edge)
            self.created_edges.append(addr_to_cache_edge)

        # Create cache data output
        read_data_name = f"{spec.cache_name}_data_{port_idx}"
        read_data_node = Node(
            node_id=read_data_name,
            data={
                'type': 'cache_read_data',
                'name': read_data_name,
                'display_name': f'{spec.cache_name} data port {port_idx}',
                'bit_width': spec.data_width,
                'cache_name': spec.cache_name,
                'port_index': port_idx,
            },
            variable_latency=True
        )
        self.graph.add_node(read_data_node)
        self.created_nodes.append(read_data_node)

        cache_out_edge = Edge(
            source=cache_node,
            target=read_data_node,
            data={
                'type': 'cache_read_data',
                'port_index': port_idx,
                'cache_interface': True
            }
        )
        self.graph.add_edge(cache_out_edge)
        self.created_edges.append(cache_out_edge)

        # Redirect consumers to cache data output
        outgoing_edges = list(array_access_node.outgoing_edges)
        for edge in outgoing_edges:
            target = edge.target
            edge_data = dict(edge.data) if edge.data else {}

            new_edge = Edge(
                source=read_data_node,
                target=target,
                data=edge_data
            )
            self.graph.add_edge(new_edge)
            self.created_edges.append(new_edge)

            edge.remove_from_nodes()
            if edge.id in self.graph.edges:
                del self.graph.edges[edge.id]

        # Remove memory->array_access edge
        if memory_edge:
            memory_edge.remove_from_nodes()
            if memory_edge.id in self.graph.edges:
                del self.graph.edges[memory_edge.id]

        # Remove address->array_access edge
        for edge in list(array_access_node.incoming_edges):
            edge_type = edge.data.get('type') if edge.data else None
            if edge_type == 'array_index':
                edge.remove_from_nodes()
                if edge.id in self.graph.edges:
                    del self.graph.edges[edge.id]

        # Create read request node
        read_req_name = f"{spec.cache_name}_read_req_{port_idx}"
        read_req_node = Node(
            node_id=read_req_name,
            data={
                'type': 'cache_read_req',
                'name': read_req_name,
                'display_name': f'{spec.cache_name} read req port {port_idx}',
                'bit_width': 1,
                'cache_name': spec.cache_name,
                'port_index': port_idx,
            }
        )
        self.graph.add_node(read_req_node)
        self.created_nodes.append(read_req_node)

        # For RW cache read request, we need to OR the Execute stage and Memory stage signals:
        # - Execute stage signal (mux enable): for early cache lookup
        # - Memory stage signal (rd_enable): to continue read after write completes
        # This handles the case where a write is in progress when a load arrives;
        # after the write completes, the load is in Memory stage and needs the cache
        # to process its read request.
        read_enable_source = None
        exec_stage_enable = None
        mem_stage_enable = None

        # Get Memory stage signal from backing memory's rd_enable
        backing_mem_name = spec.memory_name
        mem_rd_enable_id = f"{backing_mem_name}_addr_rd_enable" if backing_mem_name else None
        if mem_rd_enable_id and mem_rd_enable_id in self.graph.nodes:
            mem_stage_enable = self.graph.nodes[mem_rd_enable_id]
            print(f"    Found Memory stage rd_enable: {mem_rd_enable_id}")

        if address_node:
            addr_type = address_node.data.get('type', '')
            print(f"    Address node: {address_node.id}, type: {addr_type}")

            # Check if address node itself is a mux
            mux_node = None
            if addr_type in ['one_hot_mux', 'collision_mux', 'mux', 'inline_mux']:
                mux_node = address_node
            else:
                # Look for a mux in the address node's incoming edges
                # Pattern: lb_addr is assigned from lb_addr_mux
                for edge in address_node.incoming_edges:
                    source = edge.source
                    source_type = source.data.get('type', '')
                    if source_type in ['one_hot_mux', 'collision_mux', 'mux', 'inline_mux']:
                        mux_node = source
                        print(f"    Found mux source: {source.id}, type: {source_type}")
                        break
                    # Also check for "_mux" suffix in name (inline muxes may have different type)
                    if source.id.endswith('_mux'):
                        mux_node = source
                        print(f"    Found mux source by name: {source.id}")
                        break

            if mux_node:
                mux_enable_id = f"{mux_node.id}_enable_or_0"
                if mux_enable_id in self.graph.nodes:
                    read_enable_source = self.graph.nodes[mux_enable_id]
                    print(f"    Using mux enable {mux_enable_id} for read request (Execute stage)")
                else:
                    print(f"    Mux enable {mux_enable_id} not found in graph")

        # Fall back to read_enable if no mux enable available
        if not read_enable_source:
            read_enable_id = array_access_node.data.get('read_enable')
            if read_enable_id and read_enable_id in self.graph.nodes:
                read_enable_source = self.graph.nodes[read_enable_id]

        # Use Execute stage signal for cache read request (not Memory stage,
        # as the address mux uses Execute stage enables)
        if read_enable_source:
            req_edge = Edge(
                source=read_enable_source,
                target=read_req_node,
                data={'type': 'assignment'}
            )
            self.graph.add_edge(req_edge)
            self.created_edges.append(req_edge)
            print(f"    Using Execute stage signal {read_enable_source.id} for read request")
        else:
            # Check if this is a cache refill port - use the source cache's refill_req
            # instead of a constant 1
            is_refill_port = array_access_node.data.get('is_refill')
            source_cache_name = array_access_node.data.get('cache_name') if is_refill_port else None
            source_refill_req = None
            if source_cache_name:
                source_refill_req_id = f"{source_cache_name}_refill_req"
                source_refill_req = self.graph.nodes.get(source_refill_req_id)

            if source_refill_req:
                # Use the source cache's refill_req signal
                req_edge = Edge(
                    source=source_refill_req,
                    target=read_req_node,
                    data={'type': 'assignment'}
                )
                self.graph.add_edge(req_edge)
                self.created_edges.append(req_edge)
                print(f"    Using {source_refill_req.id} for read request (cache refill)")
            else:
                # Default: use constant 1 (always active)
                const_one_id = f"{spec.cache_name}_read_active_{port_idx}"
                const_one_node = Node(
                    node_id=const_one_id,
                    data={
                        'type': 'literal',
                        'value': 1,
                        'bit_width': 1,
                        'display_name': f'{spec.cache_name} always active'
                    }
                )
                self.graph.add_node(const_one_node)
                self.created_nodes.append(const_one_node)

                req_edge = Edge(
                    source=const_one_node,
                    target=read_req_node,
                    data={'type': 'assignment'}
                )
                self.graph.add_edge(req_edge)
                self.created_edges.append(req_edge)

        # read_req -> cache
        req_to_cache_edge = Edge(
            source=read_req_node,
            target=cache_node,
            data={
                'type': 'cache_read_req',
                'port_index': port_idx,
                'cache_interface': True
            }
        )
        self.graph.add_edge(req_to_cache_edge)
        self.created_edges.append(req_to_cache_edge)

        # Create valid output
        valid_name = f"{spec.cache_name}_valid_{port_idx}"
        valid_node = Node(
            node_id=valid_name,
            data={
                'type': 'cache_valid',
                'name': valid_name,
                'display_name': f'{spec.cache_name} valid port {port_idx}',
                'bit_width': 1,
                'cache_name': spec.cache_name,
                'port_index': port_idx,
            }
        )
        self.graph.add_node(valid_node)
        self.created_nodes.append(valid_node)

        valid_edge = Edge(
            source=cache_node,
            target=valid_node,
            data={
                'type': 'cache_valid',
                'port_index': port_idx,
                'cache_interface': True
            }
        )
        self.graph.add_edge(valid_edge)
        self.created_edges.append(valid_edge)

        # For RW cache, complete and idle are MODULE OUTPUTS from the cache FSM
        # Do NOT create assignment edges - the VerilogGenerator will wire them
        # as module outputs directly
        if port_idx == 0:
            # Just mark these as cache module outputs (no assignment edges)
            complete_id = cache_node.data.get('complete_signal')
            if complete_id and complete_id in self.graph.nodes:
                complete_node = self.graph.nodes[complete_id]
                complete_node.data['type'] = 'cache_complete'
                complete_node.data['is_module_output'] = True
                complete_node.data['cache_name'] = spec.cache_name
                print(f"    RW cache {complete_id} is module output (not assigned)")

            idle_id = cache_node.data.get('idle_signal')
            if idle_id and idle_id in self.graph.nodes:
                idle_node = self.graph.nodes[idle_id]
                idle_node.data['type'] = 'cache_idle'
                idle_node.data['is_module_output'] = True
                idle_node.data['cache_name'] = spec.cache_name
                print(f"    RW cache {idle_id} is module output (not assigned)")

        # If this read port was intercepting another cache's refill, we need to
        # update the source cache's refill_valid signal to use THIS cache's valid
        # signal for the port, not the original memory's complete signal.
        is_refill = array_access_node.data.get('is_refill')
        if is_refill:
            source_cache_name = array_access_node.data.get('cache_name')
            if source_cache_name:
                source_refill_valid_id = f"{source_cache_name}_refill_valid"
                source_refill_valid = self.graph.nodes.get(source_refill_valid_id)
                if source_refill_valid:
                    # Remove the old assignment edge (from umem_complete to refill_valid)
                    old_edges = list(source_refill_valid.incoming_edges)
                    for edge in old_edges:
                        if edge.data.get('type') == 'assignment':
                            edge.remove_from_nodes()
                            if edge.id in self.graph.edges:
                                del self.graph.edges[edge.id]
                            print(f"    Removed old {source_refill_valid_id} assignment")

                    # Connect this cache's valid signal to the source cache's refill_valid
                    new_valid_edge = Edge(
                        source=valid_node,
                        target=source_refill_valid,
                        data={'type': 'assignment'}
                    )
                    self.graph.add_edge(new_valid_edge)
                    self.created_edges.append(new_valid_edge)
                    print(f"    Rewired {source_refill_valid_id} = {valid_name} (cache port valid)")

    def _wire_write_port(self, cache_node: Node, write_port: Node,
                         memory_node: Node, spec: ReadWriteCacheSpec):
        """
        Wire the write port through the cache for write-through.

        This intercepts the memory_write_port -> memory edge and routes
        it through the cache, then creates a write-through path to memory.
        """
        cache_name = spec.cache_name

        # Find and remove the old edge: write_port -> memory
        old_memory_edge = None
        for edge in list(write_port.outgoing_edges):
            if edge.data.get('type') == 'memory_write':
                old_memory_edge = edge
                break

        if old_memory_edge:
            old_memory_edge.remove_from_nodes()
            if old_memory_edge.id in self.graph.edges:
                del self.graph.edges[old_memory_edge.id]

        # Create new edge: write_port -> cache
        write_to_cache_edge = Edge(
            source=write_port,
            target=cache_node,
            data={
                'type': 'cache_write_input',
                'cache_interface': True,
                'description': 'Write port input to cache'
            }
        )
        self.graph.add_edge(write_to_cache_edge)
        self.created_edges.append(write_to_cache_edge)

        # Create write-through address node (output from cache)
        wt_addr_name = f"{cache_name}_write_through_addr"
        wt_addr_node = Node(
            node_id=wt_addr_name,
            data={
                'type': 'var',
                'name': wt_addr_name,
                'bit_width': spec.address_width,
                'cache_name': cache_name,
                'cache_interface': 'write_through_addr',
            }
        )
        self.graph.add_node(wt_addr_node)
        self.created_nodes.append(wt_addr_node)

        # Create write-through data node (output from cache)
        wt_data_name = f"{cache_name}_write_through_data"
        wt_data_node = Node(
            node_id=wt_data_name,
            data={
                'type': 'var',
                'name': wt_data_name,
                'bit_width': spec.data_width,
                'cache_name': cache_name,
                'cache_interface': 'write_through_data',
            }
        )
        self.graph.add_node(wt_data_node)
        self.created_nodes.append(wt_data_node)

        # Create the actual cache output node (uses standard naming for port connection)
        wt_byte_en_cache_name = f"{cache_name}_write_through_byte_enable"
        byte_enable_width = spec.data_width // 8
        wt_byte_en_cache_node = Node(
            node_id=wt_byte_en_cache_name,
            data={
                'type': 'var',
                'name': wt_byte_en_cache_name,
                'bit_width': byte_enable_width,
                'cache_name': cache_name,
                'cache_interface': 'write_through_byte_enable',
            }
        )
        self.graph.add_node(wt_byte_en_cache_node)
        self.created_nodes.append(wt_byte_en_cache_node)

        # Create write-through byte mask node (used in write logic)
        # Named "byte_mask" instead of "byte_enable" to avoid pipelining pattern match
        wt_byte_en_name = f"{cache_name}_write_through_byte_mask"
        wt_byte_en_node = Node(
            node_id=wt_byte_en_name,
            data={
                'type': 'var',
                'name': wt_byte_en_name,
                'bit_width': byte_enable_width,
            }
        )
        self.graph.add_node(wt_byte_en_node)
        self.created_nodes.append(wt_byte_en_node)

        # Create write-through enable node (output from cache)
        # Named "cache_wt_enable" so generator extracts writer name as "cache_wt"
        wt_enable_name = f"cache_wt_enable"
        wt_enable_node = Node(
            node_id=wt_enable_name,
            data={
                'type': 'var',
                'name': wt_enable_name,
                'bit_width': 1,
                'cache_name': cache_name,
                'cache_interface': 'write_through_req',
            }
        )
        self.graph.add_node(wt_enable_node)
        self.created_nodes.append(wt_enable_node)

        # Also create write_through_req as an alias (for access_enable connection)
        wt_req_name = f"{cache_name}_write_through_req"
        wt_req_node = Node(
            node_id=wt_req_name,
            data={
                'type': 'var',
                'name': wt_req_name,
                'bit_width': 1,
                'cache_name': cache_name,
                'cache_interface': 'write_through_req',
            }
        )
        self.graph.add_node(wt_req_node)
        self.created_nodes.append(wt_req_node)

        # Connect cache to write-through outputs
        self.graph.add_edge(Edge(cache_node, wt_addr_node,
            data={'type': 'write_through_addr', 'cache_interface': True}))
        self.graph.add_edge(Edge(cache_node, wt_data_node,
            data={'type': 'write_through_data', 'cache_interface': True}))
        # Connect cache's byte_enable output to the cache output node
        self.graph.add_edge(Edge(cache_node, wt_byte_en_cache_node,
            data={'type': 'write_through_byte_enable', 'cache_interface': True}))
        # Assign byte_mask = byte_enable (to avoid pipelining pattern match on byte_enable)
        self.graph.add_edge(Edge(wt_byte_en_cache_node, wt_byte_en_node,
            data={'type': 'assignment'}))
        # Only connect cache to wt_req (which is dcache_write_through_req)
        # wt_enable (cache_wt_enable) is assigned from wt_req
        self.graph.add_edge(Edge(cache_node, wt_req_node,
            data={'type': 'write_through_req', 'cache_interface': True}))
        # Assign cache_wt_enable = dcache_write_through_req
        self.graph.add_edge(Edge(wt_req_node, wt_enable_node,
            data={'type': 'assignment'}))

        # Create a data mux node - the Verilog generator looks for mux_select edges on this
        # to find write enable signals
        wt_data_mux_name = f"{cache_name}_write_through_data_mux"
        wt_data_mux_node = Node(
            node_id=wt_data_mux_name,
            data={
                'type': 'memory_data_merge',  # Generator recognizes this type
                'name': wt_data_mux_name,
                'bit_width': spec.data_width,
            }
        )
        self.graph.add_node(wt_data_mux_node)
        self.created_nodes.append(wt_data_mux_node)

        # Connect data to mux as input
        self.graph.add_edge(Edge(
            source=wt_data_node,
            target=wt_data_mux_node,
            data={'type': 'mux_input'}
        ))

        # Connect enable to mux as select (generator finds this)
        self.graph.add_edge(Edge(
            source=wt_enable_node,
            target=wt_data_mux_node,
            data={'type': 'mux_select'}
        ))

        # Create write-through port node (memory_write_port type for Verilog generator)
        wt_port_name = f"{cache_name}_write_through_port"
        wt_port_node = Node(
            node_id=wt_port_name,
            data={
                'type': 'memory_write_port',
                'name': wt_port_name,
                'cache_name': cache_name,
                'base_memory': spec.memory_name,
                'bit_width': spec.data_width,
                # Single writer: the cache write-through
                # Use width 8 to trigger byte-lane logic in Verilog generator
                'writers': ['cache_wt'],
                'writer_widths': {'cache_wt': 8},  # Trigger byte-lane logic
                # Byte enables from cache
                'store_byte_enables': {'cache_wt': wt_byte_en_name},
                'store_positioned_data': {'cache_wt': wt_data_name},
                'combined_write_enable': wt_enable_name,
            }
        )
        self.graph.add_node(wt_port_node)
        self.created_nodes.append(wt_port_node)

        # Connect data mux to write port (generator expects this)
        self.graph.add_edge(Edge(
            source=wt_data_mux_node,
            target=wt_port_node,
            data={'type': 'write_data'}
        ))

        # Connect address to write port
        self.graph.add_edge(Edge(
            source=wt_addr_node,
            target=wt_port_node,
            data={'type': 'write_address'}
        ))

        # Connect byte enable to write port
        self.graph.add_edge(Edge(
            source=wt_byte_en_node,
            target=wt_port_node,
            data={'type': 'byte_enable', 'instruction': 'cache_wt'}
        ))

        # Connect write enable to write port
        self.graph.add_edge(Edge(
            source=wt_enable_node,
            target=wt_port_node,
            data={'type': 'write_enable'}
        ))

        # write_through_port -> memory
        wt_to_memory_edge = Edge(
            source=wt_port_node,
            target=memory_node,
            data={
                'type': 'memory_write',
                'description': 'Write-through to backing memory'
            }
        )
        self.graph.add_edge(wt_to_memory_edge)
        self.created_edges.append(wt_to_memory_edge)

        # Store write port reference in cache node
        cache_node.data['write_port'] = write_port.id
        cache_node.data['write_through_port'] = wt_port_name

        # Copy relevant write port metadata to cache
        cache_node.data['combined_write_enable'] = write_port.data.get('combined_write_enable')
        cache_node.data['store_byte_enables'] = write_port.data.get('store_byte_enables')
        cache_node.data['writers'] = write_port.data.get('writers')

        # Create write_through_complete signal (input to cache from memory)
        # This indicates when a write-through operation has completed
        wt_complete_name = f"{cache_name}_write_through_complete"
        wt_complete_node = Node(
            node_id=wt_complete_name,
            data={
                'type': 'var',
                'name': wt_complete_name,
                'bit_width': 1,
                'cache_name': cache_name,
                'cache_interface': 'write_through_complete',
            }
        )
        self.graph.add_node(wt_complete_node)
        self.created_nodes.append(wt_complete_node)

        # Wire write_through_complete to memory's complete signal
        mem_complete_id = memory_node.data.get('complete_signal')
        if mem_complete_id and mem_complete_id in self.graph.nodes:
            mem_complete = self.graph.nodes[mem_complete_id]
            self.graph.add_edge(Edge(
                source=mem_complete,
                target=wt_complete_node,
                data={'type': 'assignment'}
            ))
            print(f"  Wired {wt_complete_name} = {mem_complete_id} (variable latency)")
        else:
            # For 1-cycle memory, write completes immediately
            # Create a constant '1' node or wire to write_req
            const_one_name = f"{cache_name}_wt_always_complete"
            const_one_node = Node(
                node_id=const_one_name,
                data={
                    'type': 'literal',
                    'value': 1,
                    'bit_width': 1,
                    'name': const_one_name,
                }
            )
            self.graph.add_node(const_one_node)
            self.created_nodes.append(const_one_node)
            self.graph.add_edge(Edge(
                source=const_one_node,
                target=wt_complete_node,
                data={'type': 'assignment'}
            ))
            print(f"  Wired {wt_complete_name} = 1 (1-cycle memory)")

        # Edge: write_through_complete -> cache
        self.graph.add_edge(Edge(
            source=wt_complete_node,
            target=cache_node,
            data={'type': 'write_through_complete', 'cache_interface': True}
        ))

        cache_node.data['write_through_complete'] = wt_complete_name

    # =========================================================================
    # PHASE 6: CLEANUP
    # =========================================================================

    def _cleanup(self, analysis: Dict):
        """Remove any bypassed edges and nodes."""
        self.graph.cleanup_disconnected_nodes()

    # =========================================================================
    # PHASE 7: TIMING
    # =========================================================================

    def _update_timing(self):
        """Re-infer timing with cache's variable latency."""
        self.graph.infer_uarch_time(force_reinfer=True)


def apply_read_write_cache(graph: 'ResourceGraph', spec: ReadWriteCacheSpec) -> bool:
    """
    Convenience function to apply read-write cache optimization.

    Args:
        graph: Resource graph to modify
        spec: Cache specification

    Returns:
        True if successful, False otherwise

    Example:
        spec = ReadWriteCacheSpec(
            memory_name='dmem',
            cache_name='dcache',
            block_size=32,
            associativity=2,
            num_rows=64,
            cached_read_ports=['addr'],
            cached_write_ports=['addr'],
            write_allocate=False,
        )
        success = apply_read_write_cache(graph, spec)
    """
    optimization = ReadWriteCacheOptimization(graph)
    return optimization.apply(spec)


def wire_rwcache_start_signal(graph: 'ResourceGraph', cache_name: str) -> bool:
    """
    Wire the start signal for a read-write cache.

    The start signal should be: idle && (read_request || write_request)

    Args:
        graph: ResourceGraph with the cache
        cache_name: Name of the cache

    Returns:
        True if successfully wired, False otherwise
    """
    cache = graph.nodes.get(cache_name)
    if not cache:
        print(f"ERROR: Cache {cache_name} not found")
        return False

    if cache.data.get('type') != 'read_write_cache':
        print(f"ERROR: Node {cache_name} is not a read_write_cache")
        return False

    # Get signal nodes
    start_signal_id = cache.data.get('start_signal')
    idle_signal_id = cache.data.get('idle_signal')

    if not start_signal_id or not idle_signal_id:
        print(f"ERROR: Cache {cache_name} missing start or idle signal")
        return False

    start_signal = graph.nodes.get(start_signal_id)
    idle_signal = graph.nodes.get(idle_signal_id)

    if not start_signal or not idle_signal:
        print(f"ERROR: Could not find start or idle signal nodes")
        return False

    # Find cache read request signals
    read_req_nodes = []
    for edge in cache.incoming_edges:
        if edge.data.get('type') == 'cache_read_req':
            port_idx = edge.data.get('port_index', 0)
            read_req_id = f"{cache_name}_read_req_{port_idx}"
            if read_req_id in graph.nodes:
                read_req_nodes.append(graph.nodes[read_req_id])

    # Check for write request (from write port)
    write_enable_id = cache.data.get('combined_write_enable')
    write_enable_node = graph.nodes.get(write_enable_id) if write_enable_id else None

    # Combine read and write requests
    request_nodes = read_req_nodes[:]
    if write_enable_node:
        request_nodes.append(write_enable_node)

    if not request_nodes:
        print(f"  Warning: No request signals found for {cache_name}")
        return False

    # Create OR of all requests
    if len(request_nodes) == 1:
        access_enable_node = request_nodes[0]
    else:
        or_gate_id = f"{cache_name}_access_any"
        or_gate = Node(
            node_id=or_gate_id,
            data={
                'type': 'logical_or',
                'description': f'Any access to {cache_name}',
                'pipeline_component': True,
                'bit_width': 1
            }
        )
        graph.add_node(or_gate)

        for i, req_node in enumerate(request_nodes):
            graph.add_edge(Edge(req_node, or_gate, data={
                'type': 'logic_input', 'operand_position': i
            }))

        access_enable_node = or_gate
        print(f"  Created access_any OR with {len(request_nodes)} inputs")

    # Create AND gate: idle && access_enable
    and_gate_id = f"{cache_name}_start_condition"
    and_gate = Node(
        node_id=and_gate_id,
        data={
            'type': 'logical_and',
            'description': f'Start condition for {cache_name}',
            'pipeline_component': True,
            'bit_width': 1
        }
    )
    graph.add_node(and_gate)

    graph.add_edge(Edge(idle_signal, and_gate, data={
        'type': 'logic_input', 'operand_position': 0
    }))
    graph.add_edge(Edge(access_enable_node, and_gate, data={
        'type': 'logic_input', 'operand_position': 1
    }))
    graph.add_edge(Edge(and_gate, start_signal, data={
        'type': 'operand',
        'description': f'Start condition for {cache_name}'
    }))

    print(f"  Wired {start_signal_id} = {idle_signal_id} && {access_enable_node.id}")

    cache.data['access_enable_signal'] = access_enable_node.id
    return True


def add_rwcache_latency_stalls(graph: 'ResourceGraph', cache_name: str,
                                stage_name: str = None) -> bool:
    """
    Add pipeline stall logic for read-write cache.

    Creates separate stall conditions for reads and writes:
    - read_stall = read_req && !complete
    - write_stall = write_enable && !write_complete
    - stall_condition = read_stall || write_stall

    This allows writes to complete (unstall) even when reads are pending.

    Args:
        graph: ResourceGraph with the cache and pipeline
        cache_name: Name of the cache
        stage_name: Optional stage name where cache operates

    Returns:
        True if successfully added stalls, False otherwise
    """
    cache = graph.nodes.get(cache_name)
    if not cache:
        print(f"ERROR: Cache {cache_name} not found")
        return False

    if cache.data.get('type') != 'read_write_cache':
        print(f"ERROR: Node {cache_name} is not a read_write_cache")
        return False

    print(f"\nAdding cache latency stalls for {cache_name}...")

    # Wire start signal if not done
    if not cache.data.get('access_enable_signal'):
        wire_rwcache_start_signal(graph, cache_name)

    complete_signal_id = cache.data.get('complete_signal')
    write_complete_signal_id = cache.data.get('write_complete_signal')

    if not complete_signal_id:
        print(f"  ERROR: Cache {cache_name} missing complete signal")
        return False

    complete_signal = graph.nodes.get(complete_signal_id)
    write_complete_signal = graph.nodes.get(write_complete_signal_id) if write_complete_signal_id else None

    if not complete_signal:
        print(f"  ERROR: Complete signal {complete_signal_id} not found")
        return False

    # Get read and write request signals
    read_req_nodes = []
    for edge in cache.incoming_edges:
        if edge.data.get('type') == 'cache_read_req':
            port_idx = edge.data.get('port_index', 0)
            read_req_id = f"{cache_name}_read_req_{port_idx}"
            if read_req_id in graph.nodes:
                read_req_nodes.append(graph.nodes[read_req_id])

    write_enable_id = cache.data.get('combined_write_enable')
    write_enable_node = graph.nodes.get(write_enable_id) if write_enable_id else None

    # For the write stall condition, we need a validity-gated version of write_enable
    # to prevent stalling when the instruction in Memory stage is invalid
    write_enable_valid_gated_node = None
    if write_enable_id:
        # Try to find an existing validity-gated version
        gated_id = f"{write_enable_id}_valid_gated"
        if gated_id in graph.nodes:
            write_enable_valid_gated_node = graph.nodes[gated_id]
            print(f"  Found validity-gated write enable: {gated_id}")
        elif write_enable_node:
            # Create the validity-gated version
            # Find the Memory stage valid signal
            mem_valid_id = "PIPE_Memory_valid_PIPE"
            mem_valid = graph.nodes.get(mem_valid_id)
            if mem_valid:
                gated_node = Node(
                    node_id=gated_id,
                    data={
                        'type': 'operation',
                        'operator': '&&',
                        'name': gated_id,
                        'description': f'Validity-gated write enable for stall condition',
                        'pipeline_component': True,
                        'bit_width': 1
                    }
                )
                graph.add_node(gated_node)
                graph.add_edge(Edge(write_enable_node, gated_node, data={'type': 'operand', 'operand_index': 0}))
                graph.add_edge(Edge(mem_valid, gated_node, data={'type': 'operand', 'operand_index': 1}))
                write_enable_valid_gated_node = gated_node
                print(f"  Created validity-gated write enable: {gated_id} = {write_enable_id} && {mem_valid_id}")

    # Create !complete for reads
    not_complete_id = f"{cache_name}_not_complete"
    if not_complete_id not in graph.nodes:
        not_complete = Node(
            node_id=not_complete_id,
            data={
                'type': 'operation',
                'operator': '!',
                'name': not_complete_id,
                'description': f'Read stall while {cache_name} not complete',
                'pipeline_component': True,
                'bit_width': 1
            }
        )
        graph.add_node(not_complete)
        graph.add_edge(Edge(complete_signal, not_complete, data={
            'type': 'operand',
            'operand_position': 0
        }))
    else:
        not_complete = graph.nodes[not_complete_id]

    stall_conditions = []

    # For the read stall, we need to use the Memory stage load enable signal,
    # not the Execute stage read_req signal. This is because when a load is
    # in Execute and a store is in Memory, the store should be able to complete
    # its write without being blocked by the load's pending read miss.
    #
    # The backing memory's rd_enable (e.g., umem_addr_rd_enable) uses Memory stage signals.
    backing_mem_name = cache.data.get('memory_name')
    mem_rd_enable_id = f"{backing_mem_name}_addr_rd_enable" if backing_mem_name else None
    mem_rd_enable = graph.nodes.get(mem_rd_enable_id) if mem_rd_enable_id else None

    # For the read stall condition, we also need a validity-gated version
    # to prevent stalling when the instruction in Memory stage is invalid
    mem_rd_enable_gated = None
    if mem_rd_enable_id:
        gated_rd_id = f"{mem_rd_enable_id}_valid_gated"
        if gated_rd_id in graph.nodes:
            mem_rd_enable_gated = graph.nodes[gated_rd_id]
            print(f"  Found validity-gated read enable: {gated_rd_id}")
        elif mem_rd_enable:
            # Create the validity-gated version
            mem_valid_id = "PIPE_Memory_valid_PIPE"
            mem_valid = graph.nodes.get(mem_valid_id)
            if mem_valid:
                gated_rd_node = Node(
                    node_id=gated_rd_id,
                    data={
                        'type': 'operation',
                        'operator': '&&',
                        'name': gated_rd_id,
                        'description': f'Validity-gated read enable for stall condition',
                        'pipeline_component': True,
                        'bit_width': 1
                    }
                )
                graph.add_node(gated_rd_node)
                graph.add_edge(Edge(mem_rd_enable, gated_rd_node, data={'type': 'operand', 'operand_index': 0}))
                graph.add_edge(Edge(mem_valid, gated_rd_node, data={'type': 'operand', 'operand_index': 1}))
                mem_rd_enable_gated = gated_rd_node
                print(f"  Created validity-gated read enable: {gated_rd_id} = {mem_rd_enable_id} && {mem_valid_id}")

    # Create read stall condition: mem_rd_enable_gated && !complete
    # Use validity-gated Memory stage signal to avoid stalling for invalid instructions
    stall_rd_enable = mem_rd_enable_gated if mem_rd_enable_gated else mem_rd_enable
    if stall_rd_enable:
        stall_rd_enable_id = stall_rd_enable.id
        read_stall_id = f"{cache_name}_read_stall"
        if read_stall_id not in graph.nodes:
            read_stall = Node(
                node_id=read_stall_id,
                data={
                    'type': 'operation',
                    'operator': '&&',
                    'name': read_stall_id,
                    'description': f'Read stall: mem_rd_enable_valid && !complete',
                    'pipeline_component': True,
                    'bit_width': 1
                }
            )
            graph.add_node(read_stall)
            graph.add_edge(Edge(stall_rd_enable, read_stall, data={'type': 'operand', 'operand_index': 0}))
            graph.add_edge(Edge(not_complete, read_stall, data={'type': 'operand', 'operand_index': 1}))
            print(f"  Created read stall: {stall_rd_enable_id} && !{complete_signal_id}")
        else:
            read_stall = graph.nodes[read_stall_id]
        stall_conditions.append(read_stall)
    elif read_req_nodes:
        # Fallback: use read_req nodes if Memory stage signal not found
        if len(read_req_nodes) == 1:
            read_req_or = read_req_nodes[0]
        else:
            read_req_or_id = f"{cache_name}_read_req_any"
            if read_req_or_id not in graph.nodes:
                read_req_or = Node(
                    node_id=read_req_or_id,
                    data={
                        'type': 'logical_or',
                        'description': f'Any read request to {cache_name}',
                        'pipeline_component': True,
                        'bit_width': 1
                    }
                )
                graph.add_node(read_req_or)
                for i, req_node in enumerate(read_req_nodes):
                    graph.add_edge(Edge(req_node, read_req_or, data={
                        'type': 'logic_input', 'operand_position': i
                    }))
            else:
                read_req_or = graph.nodes[read_req_or_id]

        read_stall_id = f"{cache_name}_read_stall"
        if read_stall_id not in graph.nodes:
            read_stall = Node(
                node_id=read_stall_id,
                data={
                    'type': 'operation',
                    'operator': '&&',
                    'name': read_stall_id,
                    'description': f'Read stall: read_req && !complete',
                    'pipeline_component': True,
                    'bit_width': 1
                }
            )
            graph.add_node(read_stall)
            graph.add_edge(Edge(read_req_or, read_stall, data={'type': 'operand', 'operand_index': 0}))
            graph.add_edge(Edge(not_complete, read_stall, data={'type': 'operand', 'operand_index': 1}))
        else:
            read_stall = graph.nodes[read_stall_id]
        stall_conditions.append(read_stall)
        print(f"  Created read stall (fallback): {read_req_or.id} && !{complete_signal_id}")

    # Create write stall condition: write_enable && !write_complete
    if write_enable_node and write_complete_signal:
        not_write_complete_id = f"{cache_name}_not_write_complete"
        if not_write_complete_id not in graph.nodes:
            not_write_complete = Node(
                node_id=not_write_complete_id,
                data={
                    'type': 'operation',
                    'operator': '!',
                    'name': not_write_complete_id,
                    'description': f'Write not complete for {cache_name}',
                    'pipeline_component': True,
                    'bit_width': 1
                }
            )
            graph.add_node(not_write_complete)
            graph.add_edge(Edge(write_complete_signal, not_write_complete, data={
                'type': 'operand',
                'operand_position': 0
            }))
        else:
            not_write_complete = graph.nodes[not_write_complete_id]

        write_stall_id = f"{cache_name}_write_stall"
        if write_stall_id not in graph.nodes:
            # Use validity-gated write enable if available, otherwise fall back to raw write_enable
            stall_enable_node = write_enable_valid_gated_node if write_enable_valid_gated_node else write_enable_node
            stall_enable_id = stall_enable_node.id if stall_enable_node else write_enable_id

            write_stall = Node(
                node_id=write_stall_id,
                data={
                    'type': 'operation',
                    'operator': '&&',
                    'name': write_stall_id,
                    'description': f'Write stall: write_enable_valid && !write_complete',
                    'pipeline_component': True,
                    'bit_width': 1
                }
            )
            graph.add_node(write_stall)
            graph.add_edge(Edge(stall_enable_node, write_stall, data={'type': 'operand', 'operand_index': 0}))
            graph.add_edge(Edge(not_write_complete, write_stall, data={'type': 'operand', 'operand_index': 1}))
            print(f"  Created write stall: {stall_enable_id} && !{write_complete_signal_id}")
        else:
            write_stall = graph.nodes[write_stall_id]
        stall_conditions.append(write_stall)

    # Combine stall conditions with OR
    if len(stall_conditions) == 0:
        print(f"  WARNING: No stall conditions created for {cache_name}")
        stall_signal = not_complete
    elif len(stall_conditions) == 1:
        stall_signal = stall_conditions[0]
    else:
        stall_or_id = f"{cache_name}_stall_condition"
        if stall_or_id not in graph.nodes:
            stall_or = Node(
                node_id=stall_or_id,
                data={
                    'type': 'logical_or',
                    'description': f'Combined stall: read_stall || write_stall',
                    'pipeline_component': True,
                    'bit_width': 1
                }
            )
            graph.add_node(stall_or)
            for i, cond in enumerate(stall_conditions):
                graph.add_edge(Edge(cond, stall_or, data={
                    'type': 'logic_input', 'operand_position': i
                }))
            stall_signal = stall_or
        else:
            stall_signal = graph.nodes[stall_or_id]
        print(f"  Created combined stall: {' || '.join(c.id for c in stall_conditions)}")

    # Determine stage
    if stage_name is None:
        stage_name = 'Memory'

    cache.data['stall_condition_node'] = stall_signal.id
    cache.data['stall_stage'] = stage_name
    print(f"  Marked cache with stall_condition={stall_signal.id} for hazard resolution")

    # Create ternary selection for cache read address:
    # Use Memory stage address when load is in Memory, otherwise use Execute stage address.
    # This is critical because when a load stalls (cache miss), the Execute stage may have
    # moved on to the next instruction, but the cache needs the original address.
    backing_mem_name = cache.data.get('memory_name')
    mem_rd_enable_id = f"{backing_mem_name}_addr_rd_enable" if backing_mem_name else None
    mem_rd_enable = graph.nodes.get(mem_rd_enable_id)

    for edge in cache.incoming_edges:
        if edge.data.get('type') == 'cache_read_addr':
            port_idx = edge.data.get('port_index', 0)
            read_addr_node_id = f"{cache_name}_read_addr_{port_idx}"
            read_addr_node = graph.nodes.get(read_addr_node_id)

            if not read_addr_node:
                continue

            # Find the source of the read address (Execute stage signal)
            exec_addr_source = None
            for addr_edge in read_addr_node.incoming_edges:
                if addr_edge.data.get('type') == 'assignment':
                    exec_addr_source = addr_edge.source
                    break

            if not exec_addr_source:
                print(f"  WARNING: No source found for {read_addr_node_id}")
                continue

            # Look for Memory stage pipelined version
            mem_addr_id = f"PIPE_Memory_{exec_addr_source.id}_PIPE"
            mem_addr_node = graph.nodes.get(mem_addr_id)

            if mem_addr_node and mem_rd_enable:
                # Create ternary selection: mem_rd_enable ? mem_addr : exec_addr
                ternary_node_id = f"{cache_name}_read_addr_sel_{port_idx}"
                ternary_node = Node(
                    node_id=ternary_node_id,
                    data={
                        'type': 'ternary_op',
                        'operator': '?:',
                        'name': ternary_node_id,
                        'description': f'Select cache read address: Memory stage if load in Memory',
                        'bit_width': exec_addr_source.data.get('bit_width', 32),
                    }
                )
                graph.add_node(ternary_node)

                # Connect ternary inputs: condition, true_value, false_value
                graph.add_edge(Edge(mem_rd_enable, ternary_node, data={
                    'type': 'ternary_condition'
                }))
                graph.add_edge(Edge(mem_addr_node, ternary_node, data={
                    'type': 'ternary_true'
                }))
                graph.add_edge(Edge(exec_addr_source, ternary_node, data={
                    'type': 'ternary_false'
                }))

                # Remove old edge and connect ternary output to read_addr_node
                for addr_edge in list(read_addr_node.incoming_edges):
                    if addr_edge.data.get('type') == 'assignment' and addr_edge.source == exec_addr_source:
                        graph.remove_edge(addr_edge.id)
                        break

                graph.add_edge(Edge(ternary_node, read_addr_node, data={'type': 'assignment'}))
                print(f"  Created cache address selector: {ternary_node_id}")
                print(f"    {mem_rd_enable_id} ? {mem_addr_id} : {exec_addr_source.id}")
            else:
                if not mem_addr_node:
                    print(f"  WARNING: Memory stage address {mem_addr_id} not found")
                if not mem_rd_enable:
                    print(f"  WARNING: Memory rd_enable {mem_rd_enable_id} not found")

    # Fix the cache read request signal to use ONLY Memory-stage enables.
    # The cache read address is a Memory-stage signal (PIPE_Memory_lb_addr_PIPE),
    # so the read request must also be Memory-stage to avoid reading at wrong addresses.
    # The Execute-stage source (lb_addr_mux_enable_or_0) would cause cache reads
    # with the previous instruction's address, leading to spurious misses/refills.
    for edge in cache.incoming_edges:
        if edge.data.get('type') == 'cache_read_req':
            port_idx = edge.data.get('port_index', 0)
            read_req_node_id = f"{cache_name}_read_req_{port_idx}"
            read_req_node = graph.nodes.get(read_req_node_id)

            if not read_req_node:
                continue

            # Find the source of the read request (Execute stage signal)
            exec_req_source = None
            for req_edge in read_req_node.incoming_edges:
                if req_edge.data.get('type') == 'assignment':
                    exec_req_source = req_edge.source
                    break

            if not exec_req_source:
                print(f"  WARNING: No source found for {read_req_node_id}")
                continue

            # Skip creating OR for cache refill ports - they use the source cache's
            # refill_req signal directly and shouldn't be ORed with load enables
            if exec_req_source.id.endswith('_refill_req'):
                print(f"  Skipping read request OR for {read_req_node_id} (cache refill port)")
                continue

            if mem_rd_enable:
                # Replace Execute-stage source with Memory-stage source directly.
                # No OR needed - the read request should only use Memory-stage enables
                # to match the Memory-stage read address.
                for req_edge in list(read_req_node.incoming_edges):
                    if req_edge.data.get('type') == 'assignment' and req_edge.source == exec_req_source:
                        graph.remove_edge(req_edge.id)
                        break

                graph.add_edge(Edge(mem_rd_enable, read_req_node, data={'type': 'assignment'}))
                print(f"  Replaced cache read request source: {exec_req_source.id} -> {mem_rd_enable_id}")
            else:
                print(f"  WARNING: Could not replace read request source - mem_rd_enable not found")

    print(f"  Cache latency stalls configured for {cache_name}")
    return True


def connect_rwcache_write_through(graph: 'ResourceGraph', cache_name: str,
                                   memory_name: str) -> bool:
    """
    Connect the cache's write-through interface properly.

    This ensures:
    1. The write-through path from cache to memory is complete
    2. The write_through_req signal is added to memory's access_enable

    Args:
        graph: ResourceGraph with cache and memory
        cache_name: Name of the cache
        memory_name: Name of the backing memory

    Returns:
        True if successfully connected, False otherwise
    """
    cache = graph.nodes.get(cache_name)
    if not cache:
        print(f"  WARNING: {cache_name} not found")
        return False

    wt_port_id = cache.data.get('write_through_port')
    if not wt_port_id:
        print(f"  No write-through port for {cache_name} (read-only)")
        return True  # Not an error, just no writes

    wt_port = graph.nodes.get(wt_port_id)
    if not wt_port:
        print(f"  WARNING: Write-through port {wt_port_id} not found")
        return False

    # Verify connection to memory exists
    has_memory_edge = False
    for edge in wt_port.outgoing_edges:
        if edge.data.get('type') == 'memory_write':
            has_memory_edge = True
            break

    if not has_memory_edge:
        print(f"  WARNING: Write-through port not connected to memory")
        return False

    print(f"  Write-through path verified: {cache_name} -> {memory_name}")

    # Connect write_through_req to memory's access_enable
    # This allows write-through operations to trigger the memory
    wt_req_id = f"{cache_name}_write_through_req"
    wt_req_node = graph.nodes.get(wt_req_id)
    if not wt_req_node:
        print(f"  WARNING: {wt_req_id} not found - creating it")
        # Create the write_through_req node if it doesn't exist
        wt_req_node = Node(
            node_id=wt_req_id,
            data={
                'type': 'var',
                'name': wt_req_id,
                'bit_width': 1,
                'cache_name': cache_name,
                'cache_interface': 'write_through_req',
            }
        )
        graph.add_node(wt_req_node)

    # Find the memory's access_enable node
    access_enable_id = f"{memory_name}_access_enable"
    access_enable_node = graph.nodes.get(access_enable_id)
    if not access_enable_node:
        print(f"  WARNING: {access_enable_id} not found")
        return False

    # Find how many inputs the OR gate already has
    existing_inputs = len([e for e in access_enable_node.incoming_edges
                           if e.data.get('type') == 'logic_input'])

    # Add write_through_req as another input to the access_enable OR gate
    graph.add_edge(Edge(
        source=wt_req_node,
        target=access_enable_node,
        data={'type': 'logic_input', 'operand_position': existing_inputs}
    ))
    print(f"  Connected {wt_req_id} to {access_enable_id} (input {existing_inputs})")

    return True


def cleanup_unreferenced_flush_placeholders(graph: ResourceGraph) -> int:
    """
    Remove any flush_target_placeholder nodes that were not wired to a cache.

    This should be called after all cache optimizations have been applied.
    If a flush statement in an ISA file references a cache that was never created
    (e.g., 'flush icache;' when no icache optimization is applied), this function
    will remove the orphaned placeholder nodes and warn the developer.

    Args:
        graph: The resource graph to clean up

    Returns:
        Number of placeholder nodes removed
    """
    placeholders_removed = 0
    nodes_to_remove = []

    for node_id, node in list(graph.nodes.items()):
        if node.data and node.data.get('type') == 'flush_target_placeholder':
            cache_name = node.data.get('cache_name', 'unknown')
            print(f"  WARNING: Flush placeholder for '{cache_name}' cache was never wired. "
                  f"No cache optimization was applied for this cache name. "
                  f"The flush statement will have no effect.")

            # Remove incoming edges (flush signals pointing to this placeholder)
            for edge in list(node.incoming_edges):
                graph.remove_edge(edge.id)

            nodes_to_remove.append(node_id)
            placeholders_removed += 1

    # Remove the placeholder nodes
    for node_id in nodes_to_remove:
        graph.remove_node(node_id)

    if placeholders_removed > 0:
        print(f"  Removed {placeholders_removed} unreferenced flush placeholder(s)")

    return placeholders_removed
