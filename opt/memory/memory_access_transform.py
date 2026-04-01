"""
Memory access transformation optimization for ResourceGraphs.

This module implements bidirectional algorithms to transform memory accesses:
1. serialize_parallelize: Multi-cycle with counter (like operation_serialization.py)
   - Forward (narrowing): Add counter to serialize wide accesses
   - Reverse (widening): Remove counter to parallelize back to wide
   - Update (re-narrowing): Update counter width for different granularity

2. split_merge: Multi-port without counter
   - Forward (narrowing): Split into multiple parallel ports
   - Reverse (widening): Merge multiple ports into one wide port

3. write_read_forwarding: Enable same-cycle write-to-read forwarding on a memory
   - When enabled, reads return the write data if reading an address being written
   - Reduces pipeline stalls and eliminates need for bypass from writeback stage
"""

from typing import Dict, List, Set, Tuple, Optional
from core.resource_graph import ResourceGraph, Node, Edge
from core.mux_utils import MuxBuilder, MuxType
import math


class MemoryAccessTransformSpec:
    """Specification for memory access transformation."""

    def __init__(
        self,
        memory: str,
        strategy: str,
        current_width: int,
        target_width: int,
        direction: str,
        merge_from: Optional[List[str]] = None,
        endianness: str = 'little',
        alignment: str = 'port_width'
    ):
        self.memory = memory  # Memory node name (e.g., 'dmem')
        self.strategy = strategy  # 'serialize_parallelize' | 'split_merge' | 'set_port_width'
        self.current_width = current_width  # Current access width
        self.target_width = target_width  # Target memory width (port_width)
        self.direction = direction  # 'forward' | 'reverse' | 'update'
        self.merge_from = merge_from or []  # For split_merge reverse
        self.endianness = endianness  # 'little' or 'big' - affects byte/word selection
        self.alignment = alignment  # 'port_width' (aligned) or 'unaligned' (cross-word support)

        # Validate strategy
        if strategy not in ['serialize_parallelize', 'split_merge', 'set_port_width']:
            raise ValueError(f"Unknown strategy: {strategy}")

        # Validate direction
        if direction not in ['forward', 'reverse', 'update']:
            raise ValueError(f"Unknown direction: {direction}")

        # Validate endianness
        if endianness not in ['little', 'big']:
            raise ValueError(f"Unknown endianness: {endianness}")

        # Validate alignment
        if alignment not in ['port_width', 'unaligned']:
            raise ValueError(f"Unknown alignment: {alignment}")

    def __str__(self):
        return f"{self.strategy} {self.direction}: {self.memory} {self.current_width}→{self.target_width} bits"


class MemoryAccessTransform:
    """Transforms memory accesses to match memory width constraints."""

    def __init__(self, graph: ResourceGraph):
        self.graph = graph

    def apply_transformation(
        self,
        spec: MemoryAccessTransformSpec,
        dry_run: bool = False
    ) -> Dict[str, any]:
        """
        Apply bidirectional memory access transformation.

        Returns a dict with transformation info.
        """
        print(f"\nApplying memory transformation: {spec}")

        if spec.strategy == 'serialize_parallelize':
            return self.apply_serialize_parallelize(spec, dry_run)
        elif spec.strategy == 'split_merge':
            return self.apply_split_merge(spec, dry_run)
        elif spec.strategy == 'set_port_width':
            return self.apply_set_port_width(spec, dry_run)
        else:
            raise ValueError(f"Unknown strategy: {spec.strategy}")

    # =========================================================================
    # SERIALIZE/PARALLELIZE STRATEGY (Multi-cycle with counter)
    # =========================================================================

    def apply_serialize_parallelize(
        self,
        spec: MemoryAccessTransformSpec,
        dry_run: bool = False
    ) -> Dict[str, any]:
        """
        Apply serialize/parallelize transformation (bidirectional).

        Direction determined by current vs target width:
        - forward: Narrowing (add counter)
        - reverse: Widening (remove counter)
        - update: Re-narrowing (update counter)
        """
        if spec.direction == 'forward':
            return self._serialize_forward(spec, dry_run)
        elif spec.direction == 'reverse':
            return self._serialize_reverse(spec, dry_run)
        elif spec.direction == 'update':
            return self._serialize_update(spec, dry_run)
        else:
            raise ValueError(f"Unknown direction: {spec.direction}")

    def _serialize_forward(
        self,
        spec: MemoryAccessTransformSpec,
        dry_run: bool = False
    ) -> Dict[str, any]:
        """
        Forward serialization: Add counter to serialize wide accesses.

        Takes a wide memory access (e.g., 32-bit) and serializes it into
        multiple narrow accesses (e.g., 16-bit) over multiple cycles.
        """
        print(f"  Serializing {spec.current_width}→{spec.target_width} bits")

        # Calculate serialization parameters
        num_cycles = math.ceil(spec.current_width / spec.target_width)
        cycles_added = num_cycles - 1  # Additional cycles beyond first

        print(f"  Will serialize into {num_cycles} cycles")

        # Find memory accesses to transform
        memory_node = self.graph.nodes.get(spec.memory)
        if not memory_node:
            return {
                'transformed': False,
                'reason': f"Memory {spec.memory} not found"
            }

        # Find all access nodes for this memory
        access_nodes = self._find_memory_access_nodes(spec.memory)
        if not access_nodes:
            return {
                'transformed': False,
                'reason': f"No memory accesses found for {spec.memory}"
            }

        print(f"  Found {len(access_nodes)} memory access nodes to transform")

        if dry_run:
            return {
                'transformed': True,
                'direction': 'forward',
                'old_width': spec.current_width,
                'new_width': spec.target_width,
                'num_accesses_affected': len(access_nodes),
                'cycles_added': cycles_added,
                'nodes_added': [],
                'nodes_removed': [],
                'nodes_updated': [],
                'dry_run': True
            }

        # Create serialization counter
        counter_node = self._create_access_counter(spec.memory, num_cycles)

        # Transform each memory access
        nodes_added = [counter_node.id]
        nodes_removed = []
        nodes_updated = []

        for access_node in access_nodes:
            result = self._transform_access_to_serialized(
                access_node,
                spec,
                counter_node,
                num_cycles
            )
            nodes_added.extend(result['nodes_added'])
            nodes_removed.extend(result['nodes_removed'])

        return {
            'transformed': True,
            'direction': 'forward',
            'old_width': spec.current_width,
            'new_width': spec.target_width,
            'num_accesses_affected': len(access_nodes),
            'cycles_added': cycles_added,
            'nodes_added': nodes_added,
            'nodes_removed': nodes_removed,
            'nodes_updated': nodes_updated
        }

    def _serialize_reverse(
        self,
        spec: MemoryAccessTransformSpec,
        dry_run: bool = False
    ) -> Dict[str, any]:
        """
        Reverse serialization: Remove counter to parallelize back to wide.

        Detects existing serialization pattern and removes it.
        """
        print(f"  Parallelizing (removing serialization) {spec.current_width}→{spec.target_width} bits")

        # Find serialization counter
        counter_node = self._find_serialization_counter(spec.memory)
        if not counter_node:
            return {
                'transformed': False,
                'reason': f"No serialization counter found for {spec.memory}"
            }

        print(f"  Found serialization counter: {counter_node.id}")

        # Analyze serialization structure
        analysis = self._analyze_serialization_structure(counter_node)
        if not analysis['can_parallelize']:
            return {
                'transformed': False,
                'reason': analysis.get('reason', 'Cannot parallelize')
            }

        print(f"  Removing serialization (was {analysis['num_cycles']} cycles)")

        if dry_run:
            return {
                'transformed': True,
                'direction': 'reverse',
                'old_width': spec.current_width,
                'new_width': spec.target_width,
                'num_accesses_affected': len(analysis['access_nodes']),
                'cycles_removed': analysis['num_cycles'] - 1,
                'nodes_added': [],
                'nodes_removed': [counter_node.id],
                'nodes_updated': [],
                'dry_run': True
            }

        # Remove serialization pattern
        nodes_removed = [counter_node.id]
        nodes_added = []

        for access_info in analysis['access_nodes']:
            result = self._restore_direct_access(access_info, spec)
            nodes_removed.extend(result['nodes_removed'])
            nodes_added.extend(result['nodes_added'])

        # Remove counter node
        self.graph.remove_node(counter_node.id)

        return {
            'transformed': True,
            'direction': 'reverse',
            'old_width': spec.current_width,
            'new_width': spec.target_width,
            'num_accesses_affected': len(analysis['access_nodes']),
            'cycles_removed': analysis['num_cycles'] - 1,
            'nodes_added': nodes_added,
            'nodes_removed': nodes_removed,
            'nodes_updated': []
        }

    def _serialize_update(
        self,
        spec: MemoryAccessTransformSpec,
        dry_run: bool = False
    ) -> Dict[str, any]:
        """
        Update existing serialization: Change counter width for new granularity.

        Updates counter max_count, bit_width, and associated logic.
        """
        print(f"  Updating serialization {spec.current_width}→{spec.target_width} bits")

        # Find existing serialization counter
        counter_node = self._find_serialization_counter(spec.memory)
        if not counter_node:
            return {
                'transformed': False,
                'reason': f"No serialization counter found for {spec.memory}"
            }

        # Get the ORIGINAL wide access width (not current narrow width)
        # This is stored in the merge node's output_width
        analysis = self._analyze_serialization_structure(counter_node)
        if not analysis['can_parallelize']:
            return {
                'transformed': False,
                'reason': analysis.get('reason', 'Cannot analyze serialization')
            }

        merge_node = analysis['access_nodes'][0]['merge_node']
        original_wide_width = merge_node.data.get('output_width')

        # Calculate new parameters based on ORIGINAL wide width
        old_num_cycles = counter_node.data.get('max_count', 0) + 1
        new_num_cycles = math.ceil(original_wide_width / spec.target_width)

        print(f"  Updating counter: {old_num_cycles} cycles → {new_num_cycles} cycles")

        if dry_run:
            return {
                'transformed': True,
                'direction': 'update',
                'old_width': spec.current_width,
                'new_width': spec.target_width,
                'cycles_added': new_num_cycles - 1,
                'nodes_added': [],
                'nodes_removed': [],
                'nodes_updated': [counter_node.id],
                'dry_run': True
            }

        # Update counter
        nodes_updated = [counter_node.id]
        self._update_counter_width(counter_node, new_num_cycles, spec.target_width)

        # Update spec to use original wide width for recreation
        update_spec = MemoryAccessTransformSpec(
            memory=spec.memory,
            strategy=spec.strategy,
            current_width=original_wide_width,  # Use original wide width
            target_width=spec.target_width,
            direction=spec.direction,
            merge_from=spec.merge_from
        )

        # Update associated logic (bit slices, muxes, merge logic)
        for access_info in analysis['access_nodes']:
            self._update_serialization_logic(access_info, update_spec, new_num_cycles)
            nodes_updated.extend(access_info.get('associated_nodes', []))

        return {
            'transformed': True,
            'direction': 'update',
            'old_width': spec.current_width,
            'new_width': spec.target_width,
            'num_accesses_affected': len(analysis['access_nodes']),
            'cycles_added': new_num_cycles - 1,
            'nodes_added': [],
            'nodes_removed': [],
            'nodes_updated': nodes_updated
        }

    # =========================================================================
    # SPLIT/MERGE STRATEGY (Multi-port without counter)
    # =========================================================================

    def apply_split_merge(
        self,
        spec: MemoryAccessTransformSpec,
        dry_run: bool = False
    ) -> Dict[str, any]:
        """
        Apply split/merge transformation (bidirectional).

        Direction determined by current vs target width:
        - forward: Narrowing (split into ports)
        - reverse: Widening (merge ports)
        """
        if spec.direction == 'forward':
            return self._split_forward(spec, dry_run)
        elif spec.direction == 'reverse':
            return self._merge_reverse(spec, dry_run)
        else:
            raise ValueError(f"Split/merge does not support 'update' direction")

    def _split_forward(
        self,
        spec: MemoryAccessTransformSpec,
        dry_run: bool = False
    ) -> Dict[str, any]:
        """
        Forward split: Create multiple parallel ports.

        Takes a wide memory access and splits it into multiple narrow
        ports that are accessed in parallel (NO counter, unlike serialize).

        Key difference from serialize: All ports accessed in SAME cycle (parallel),
        not across multiple cycles.
        """
        print(f"  Splitting {spec.current_width}→{spec.target_width} bits into multiple ports")

        # Calculate number of ports needed
        num_ports = math.ceil(spec.current_width / spec.target_width)

        print(f"  Will create {num_ports} parallel memory ports")

        # Find memory accesses to transform
        memory_node = self.graph.nodes.get(spec.memory)
        if not memory_node:
            return {
                'transformed': False,
                'reason': f"Memory {spec.memory} not found"
            }

        # Find all access nodes for this memory
        access_nodes = self._find_memory_access_nodes(spec.memory)
        if not access_nodes:
            return {
                'transformed': False,
                'reason': f"No memory accesses found for {spec.memory}"
            }

        print(f"  Found {len(access_nodes)} memory access nodes to transform")

        if dry_run:
            return {
                'transformed': True,
                'direction': 'forward',
                'old_width': spec.current_width,
                'new_width': spec.target_width,
                'num_accesses_affected': len(access_nodes),
                'ports_required': num_ports,
                'nodes_added': [],
                'nodes_removed': [],
                'dry_run': True
            }

        # Transform each memory access
        nodes_added = []
        nodes_removed = []

        for access_node in access_nodes:
            result = self._transform_access_to_split_ports(
                access_node,
                spec,
                num_ports
            )
            nodes_added.extend(result['nodes_added'])
            nodes_removed.extend(result['nodes_removed'])

        return {
            'transformed': True,
            'direction': 'forward',
            'old_width': spec.current_width,
            'new_width': spec.target_width,
            'num_accesses_affected': len(access_nodes),
            'ports_required': num_ports,
            'nodes_added': nodes_added,
            'nodes_removed': nodes_removed
        }

    def _transform_access_to_split_ports(
        self,
        access_node: Node,
        spec: MemoryAccessTransformSpec,
        num_ports: int
    ) -> Dict[str, List[str]]:
        """
        Transform a single memory access into split parallel ports.

        Similar to _transform_access_to_serialized but:
        - NO counter (all ports accessed in parallel)
        - Create separate memory PORT nodes (not just narrow accesses)
        - All ports accessed in SAME cycle

        Returns dict with nodes_added and nodes_removed.
        """
        print(f"    Transforming access: {access_node.id}")

        access_mode = access_node.data.get('access_mode', 'read')
        nodes_added = []

        # Step 1: Create separate memory port nodes (not narrow accesses)
        port_accesses = self._create_memory_port_nodes(
            access_node, spec, num_ports
        )
        nodes_added.extend([n.id for n in port_accesses])
        print(f"      Created {len(port_accesses)} memory port nodes")

        # Step 2: Create address offset nodes for each port
        # Each port accesses a different byte offset: addr+0, addr+bytes, etc.
        bytes_per_port = spec.target_width // 8
        offset_nodes = []

        # Get base address (skip memory node, we want the actual address)
        base_addr_node = None
        for edge in access_node.incoming_edges:
            if edge.data.get('type') == 'array_index':
                # Skip if source is the memory node itself
                if edge.source.data.get('is_memory'):
                    continue
                base_addr_node = edge.source
                break

        if base_addr_node:
            for i in range(num_ports):
                byte_offset = i * bytes_per_port
                offset_name = f"{access_node.id}_port{i}_offset"

                offset_data = {
                    'type': 'port_address_offset',
                    'name': offset_name,
                    'display_name': f"{base_addr_node.id}+{byte_offset}" if byte_offset > 0 else base_addr_node.id,
                    'base_address': base_addr_node.id,
                    'port_index': i,
                    'byte_offset': byte_offset,
                    'memory': spec.memory
                }

                offset_node = Node(offset_name, offset_data, is_uarch_state=False)
                offset_node.uarch_time = 0  # All in same cycle
                self.graph.add_node(offset_node)

                # Connect base address to offset
                addr_edge = Edge(base_addr_node, offset_node, data={
                    'type': 'address_with_offset' if byte_offset > 0 else 'base_address',
                    'offset': byte_offset
                })
                self.graph.add_edge(addr_edge)

                # Connect offset to port access
                port_edge = Edge(offset_node, port_accesses[i], data={
                    'type': 'memory_address',
                    'port': i
                })
                self.graph.add_edge(port_edge)

                offset_nodes.append(offset_node)

            nodes_added.extend([n.id for n in offset_nodes])
            print(f"      Created {len(offset_nodes)} port address offsets")

        if access_mode == 'read':
            # Step 3: Create data merge logic (parallel reads)
            merge_node = self._create_port_merge_logic(
                access_node, port_accesses, spec, num_ports
            )
            nodes_added.append(merge_node.id)
            print(f"      Created port merge node: {merge_node.id}")

            # Step 4: Redirect original read destinations
            self._redirect_read_destinations(access_node, merge_node)

        else:  # write
            # For writes: create bit slices for data
            write_data_node = self._find_write_data_source(access_node)
            if write_data_node:
                data_slices = self._create_write_data_slices(
                    access_node, write_data_node, spec, num_ports
                )
                nodes_added.extend([n.id for n in data_slices])
                print(f"      Created {len(data_slices)} write data slices")

                # Connect slices to port writes with assignment edges
                # This allows Verilog generator to recognize them as memory writes
                for i, (port_access, data_slice) in enumerate(zip(port_accesses, data_slices)):
                    assignment_edge = Edge(data_slice, port_access, data={
                        'type': 'assignment',
                        'port': i,
                        'left': port_access.data.get('expression', {}),
                        'right': {'type': 'identifier', 'name': data_slice.id}
                    })
                    self.graph.add_edge(assignment_edge)

                print(f"      Connected data slices to port writes")

        return {
            'nodes_added': nodes_added,
            'nodes_removed': []
        }

    def _create_memory_port_nodes(
        self,
        access_node: Node,
        spec: MemoryAccessTransformSpec,
        num_ports: int
    ) -> List[Node]:
        """
        Create separate memory PORT nodes.

        These are actual separate memory ports, not just narrow accesses.
        """
        port_nodes = []
        access_mode = access_node.data.get('access_mode', 'read')
        suffix = 'wr' if access_mode == 'write' else 'rd'

        for i in range(num_ports):
            port_name = f"{spec.memory}_port{i}"

            port_data = {
                'type': 'isa_state mem',  # Prefix with isa_state (split ports are ISA state)
                'name': port_name,
                'display_name': f"{spec.memory} port {i}",
                'memory': spec.memory,
                'port_index': i,
                'bit_width': spec.target_width,
                'original_memory': spec.memory,
                'is_split_port': True,
                'supports_byte_enable': True,  # Enable byte-level writes
                'supports_unaligned': True,  # Enable unaligned access handling
                'array_depth': 1024  # Default, will be overridden if needed
            }

            port_node = Node(port_name, port_data, is_uarch_state=False)
            self.graph.add_node(port_node)
            port_nodes.append(port_node)

        return port_nodes

    def _create_port_merge_logic(
        self,
        access_node: Node,
        port_accesses: List[Node],
        spec: MemoryAccessTransformSpec,
        num_ports: int
    ) -> Node:
        """
        Create merge logic for parallel port reads.

        Similar to _create_data_merge_logic but for ports (not serial cycles).
        """
        merge_name = f"{spec.memory}_port_merge"

        merge_data = {
            'type': 'port_data_merge',
            'name': merge_name,
            'display_name': f"{spec.memory} port merge",
            'memory': spec.memory,
            'num_ports': num_ports,
            'port_width': spec.target_width,
            'output_width': spec.current_width,
            'original_access': access_node.id,
            'is_parallel': True  # All ports in same cycle
        }

        merge_node = Node(merge_name, merge_data, is_uarch_state=False)
        merge_node.uarch_time = 0  # All in same cycle
        self.graph.add_node(merge_node)

        # Connect all port reads to merge node
        for i, port_access in enumerate(port_accesses):
            merge_edge = Edge(port_access, merge_node, data={
                'type': 'port_data',
                'port_index': i
            })
            self.graph.add_edge(merge_edge)

        return merge_node

    def _merge_reverse(
        self,
        spec: MemoryAccessTransformSpec,
        dry_run: bool = False
    ) -> Dict[str, any]:
        """
        Reverse merge: Merge multiple ports into one wide port.

        User provides one port name in merge_from, we automatically
        find the other related ports and merge them all.
        """
        print(f"  Merging ports back into {spec.memory}")

        if not spec.merge_from or len(spec.merge_from) == 0:
            return {
                'transformed': False,
                'reason': 'No ports specified in merge_from'
            }

        # User provides at least one port, find the others automatically
        first_port = spec.merge_from[0]
        print(f"  Starting from port: {first_port}")

        # Find all related ports
        all_ports = self._find_related_ports(first_port, spec.memory)
        if not all_ports:
            return {
                'transformed': False,
                'reason': f"Could not find related ports for {first_port}"
            }

        print(f"  Found {len(all_ports)} related ports: {[p.id for p in all_ports]}")

        # Find merge node
        merge_node = None
        for node in self.graph.nodes.values():
            if node.data.get('type') == 'port_data_merge':
                if node.data.get('memory') == spec.memory:
                    merge_node = node
                    break

        if not merge_node:
            return {
                'transformed': False,
                'reason': f"No port merge node found for {spec.memory}"
            }

        print(f"  Found merge node: {merge_node.id}")

        # Find original access (from merge metadata)
        original_access_id = merge_node.data.get('original_access')
        original_access = self.graph.nodes.get(original_access_id) if original_access_id else None

        # Find port offset nodes
        offset_nodes = []
        for node in self.graph.nodes.values():
            if node.data.get('type') == 'port_address_offset':
                if node.data.get('memory') == spec.memory:
                    offset_nodes.append(node)

        if dry_run:
            return {
                'transformed': True,
                'direction': 'reverse',
                'old_width': spec.current_width,
                'new_width': spec.target_width,
                'ports_merged': len(all_ports),
                'nodes_added': [],
                'nodes_removed': [p.id for p in all_ports] + [merge_node.id] + [o.id for o in offset_nodes],
                'dry_run': True
            }

        # Restore original wide access
        nodes_removed = []

        if original_access and original_access.id in self.graph.nodes:
            print(f"  Restoring original access: {original_access.id}")

            # Update original access to wide width
            original_access.data['bit_width'] = spec.target_width

            # Find merge destinations
            merge_destinations = []
            for edge in merge_node.outgoing_edges:
                if edge.data.get('type') == 'assignment':
                    merge_destinations.append(edge.target)

            # Reconnect to original access
            for dest in merge_destinations:
                # Remove old edge from merge
                old_edges = [e for e in merge_node.outgoing_edges
                           if e.target == dest and e.data.get('type') == 'assignment']
                for old_edge in old_edges:
                    old_edge.remove_from_nodes()
                    if old_edge.id in self.graph.edges:
                        del self.graph.edges[old_edge.id]

                # Create new edge from original access
                new_edge = Edge(original_access, dest, data={
                    'type': 'assignment',
                    'from_merged_ports': True
                })
                self.graph.add_edge(new_edge)
                print(f"    Reconnected {original_access.id} → {dest.id}")

        # Remove all port nodes
        for port in all_ports:
            self._remove_node_and_edges(port)
            nodes_removed.append(port.id)

        # Remove offset nodes
        for offset in offset_nodes:
            self._remove_node_and_edges(offset)
            nodes_removed.append(offset.id)

        # Remove merge node
        self._remove_node_and_edges(merge_node)
        nodes_removed.append(merge_node.id)

        print(f"  Removed {len(nodes_removed)} split nodes")

        return {
            'transformed': True,
            'direction': 'reverse',
            'old_width': spec.current_width,
            'new_width': spec.target_width,
            'ports_merged': len(all_ports),
            'nodes_added': [],
            'nodes_removed': nodes_removed
        }

    def _find_related_ports(self, port_name: str, memory: str) -> List[Node]:
        """
        Find all related memory ports.

        Given one port (e.g., dmem_port0), find all others (dmem_port1, dmem_port2, etc.)
        """
        # Extract base name (e.g., dmem_port from dmem_port0)
        import re
        match = re.match(r'(.+_port)\d+$', port_name)
        if not match:
            # Try without index
            base_pattern = f"{memory}_port"
        else:
            base_pattern = match.group(1)

        # Find all ports with this base pattern
        related_ports = []
        for node in self.graph.nodes.values():
            if node.data.get('type') == 'isa_state mem' and node.data.get('is_split_port'):
                if node.data.get('memory') == memory:
                    if node.id.startswith(base_pattern):
                        related_ports.append(node)

        # Sort by port index
        related_ports.sort(key=lambda n: n.data.get('port_index', 0))
        return related_ports

    # =========================================================================
    # SET PORT WIDTH STRATEGY (Word-addressed with byte muxing)
    # =========================================================================

    def apply_set_port_width(
        self,
        spec: MemoryAccessTransformSpec,
        dry_run: bool = False
    ) -> Dict[str, any]:
        """
        Apply port width setting with byte-selection mux generation.

        This strategy:
        1. Sets port_width on the memory node (e.g., 32 for word-addressed)
        2. Transforms accesses to use word address (addr[31:2])
        3. Generates byte-selection mux for sub-word accesses (8/16-bit)
        4. Leaves full-word accesses unchanged

        Unlike serialize_parallelize: No counter, single cycle
        Unlike split_merge: No multiple ports, single unified memory

        Direction determines operation:
        - forward: Add word-addressing and byte muxing
        - reverse: Remove word-addressing and byte muxing
        """
        if spec.direction == 'forward':
            return self._set_port_width_forward(spec, dry_run)
        elif spec.direction == 'reverse':
            return self._set_port_width_reverse(spec, dry_run)
        else:
            raise ValueError(f"set_port_width does not support '{spec.direction}' direction")

    # =========================================================================
    # WRITE-READ FORWARDING (Same-cycle write-to-read bypass)
    # =========================================================================

    def enable_write_read_forwarding(self, memory_name: str) -> Dict[str, any]:
        """
        Enable write-to-read forwarding on a memory node.

        When enabled, the memory will forward write data to reads of the same
        address in the same cycle. This is sometimes called "write-first" or
        "transparent" memory behavior.

        Effects on hazard resolution:
        - Stalling: No stall needed when write and read are in the same cycle
        - Bypassing: No bypass needed from writeback stage (memory handles it)

        The Verilog generator will emit bypass logic for the memory reads:
            assign rf_rd = (write_en && write_addr == read_addr) ? write_data : rf[read_addr];

        Args:
            memory_name: Name of the memory node (e.g., 'rf', 'dmem')

        Returns:
            Dict with 'enabled' bool and details
        """
        print(f"\nEnabling write-read forwarding for {memory_name}")

        # Find the memory node
        memory_node = self.graph.nodes.get(memory_name)
        if not memory_node:
            return {
                'enabled': False,
                'reason': f"Memory node '{memory_name}' not found"
            }

        # Verify it's a memory/array type
        if not memory_node.data.get('is_memory', False):
            # Check if it looks like a memory (has array accesses)
            is_array = any(
                'array_access' in n.data.get('type', '')
                for n in self.graph.nodes.values()
                if memory_name in n.id
            )
            if not is_array:
                return {
                    'enabled': False,
                    'reason': f"Node '{memory_name}' is not a memory"
                }

        # Set the write_read_fwd property
        memory_node.data['write_read_fwd'] = True

        print(f"  Set write_read_fwd=True on {memory_name}")

        return {
            'enabled': True,
            'memory': memory_name,
            'property': 'write_read_fwd'
        }

    def disable_write_read_forwarding(self, memory_name: str) -> Dict[str, any]:
        """
        Disable write-to-read forwarding on a memory node.

        Args:
            memory_name: Name of the memory node

        Returns:
            Dict with 'disabled' bool and details
        """
        memory_node = self.graph.nodes.get(memory_name)
        if not memory_node:
            return {
                'disabled': False,
                'reason': f"Memory node '{memory_name}' not found"
            }

        if 'write_read_fwd' in memory_node.data:
            del memory_node.data['write_read_fwd']
            print(f"  Removed write_read_fwd from {memory_name}")

        return {
            'disabled': True,
            'memory': memory_name
        }

    def has_write_read_forwarding(self, memory_name: str) -> bool:
        """
        Check if a memory has write-read forwarding enabled.

        Args:
            memory_name: Name of the memory node

        Returns:
            True if write_read_fwd is enabled on the memory
        """
        memory_node = self.graph.nodes.get(memory_name)
        if not memory_node:
            return False
        return memory_node.data.get('write_read_fwd', False)

    def _set_port_width_forward(
        self,
        spec: MemoryAccessTransformSpec,
        dry_run: bool = False
    ) -> Dict[str, any]:
        """
        Forward: Set port_width and generate word-addressed byte muxing.

        For RISC-V word-addressed memory:
        - Set port_width=32 on memory node
        - Find shared memory read and its sub-word destination nodes
        - Insert byte selection mux nodes between memory read and sub-word destinations
        """
        print(f"  Setting port_width={spec.target_width} for {spec.memory}")

        # Find memory node
        memory_node = self.graph.nodes.get(spec.memory)
        if not memory_node:
            return {
                'transformed': False,
                'reason': f"Memory {spec.memory} not found"
            }

        # Check if already has port_width set
        existing_port_width = memory_node.data.get('port_width')
        if existing_port_width == spec.target_width:
            print(f"  port_width already set to {spec.target_width}")
            # Even if port_width is already set, we still need to transform byte_enable_computation nodes
            # that may have been created during graph merging
            be_nodes_transformed = self._transform_byte_enable_computation_nodes(
                spec.memory, spec.target_width, [], [], spec.endianness,
                alignment=spec.alignment
            )
            if be_nodes_transformed > 0:
                print(f"  Transformed {be_nodes_transformed} byte_enable_computation nodes to standard ops")
            return {
                'transformed': False,
                'reason': f"port_width already {spec.target_width}"
            }

        if dry_run:
            return {
                'transformed': True,
                'direction': 'forward',
                'old_port_width': existing_port_width,
                'new_port_width': spec.target_width,
                'nodes_added': [],
                'nodes_updated': [spec.memory],
                'dry_run': True
            }

        # Set port_width and endianness on memory node
        memory_node.data['port_width'] = spec.target_width
        memory_node.data['endianness'] = spec.endianness

        # Check if ALL access widths match the port width. If so, there are no
        # sub-word accesses, meaning ISA addresses are word indices and no
        # byte-to-word address scaling is needed.
        access_widths = memory_node.data.get('access_widths', [])
        all_full_width = access_widths and all(w == spec.target_width for w in access_widths)
        if all_full_width:
            memory_node.data['word_addressed'] = True
            print(f"  Set {spec.memory}.port_width = {spec.target_width}, word_addressed = True (all accesses full-width)")
        else:
            print(f"  Set {spec.memory}.port_width = {spec.target_width}, endianness = {spec.endianness}")

        # Find all memory read nodes for this memory
        # After merging, these are shared nodes like "dmem[addr]_rd"
        read_nodes = self._find_memory_read_nodes(spec.memory)
        if read_nodes:
            print(f"  Found {len(read_nodes)} memory read nodes")
        else:
            print(f"  No memory read nodes found for {spec.memory}")

        nodes_added = []
        nodes_updated = [spec.memory]

        for read_node in read_nodes:
            # Find all address nodes for this read
            # Skip array_base edges (from memory node) - we want array_index (from address node)
            addr_sources = []  # List of (addr_node, edge)
            for edge in read_node.incoming_edges:
                if edge.data.get('type') == 'array_index':
                    # Skip if source is the memory node itself
                    if edge.source.data.get('is_memory'):
                        continue
                    addr_sources.append((edge.source, edge))

            if not addr_sources:
                print(f"    Warning: No address node found for {read_node.id}")
                continue

            # Check if we have multiple unique address sources
            unique_addrs = set(src[0].id for src in addr_sources)
            if len(unique_addrs) > 1:
                # Create an address mux for multiple sources
                print(f"    Found {len(unique_addrs)} unique address sources for {read_node.id}")
                addr_node, mux_added = self._create_read_address_mux(
                    read_node, addr_sources, spec.target_width
                )
                nodes_added.extend(mux_added)
            else:
                # Single address source - use it directly
                addr_node = addr_sources[0][0]

            # Find sub-word destination nodes (assignment targets with width < port_width)
            subword_destinations = []
            fullword_destinations = []
            spanning_subword_destinations = []  # Sub-word accesses that may span word boundaries
            for edge in list(read_node.outgoing_edges):
                if edge.data.get('type') == 'assignment':
                    dest_node = edge.target
                    dest_width = dest_node.data.get('bit_width')
                    if dest_width and dest_width < spec.target_width:
                        # Check if this sub-word access could span word boundaries
                        # For halfword-aligned accesses (C extension), spanning occurs when:
                        # - The access width is >= half the port width
                        # - AND alignment='unaligned' is enabled
                        # E.g., 32-bit instruction fetch from 64-bit memory can span
                        if spec.alignment == 'unaligned' and dest_width > 8:
                            spanning_subword_destinations.append((dest_node, dest_width, edge))
                            print(f"    Found spanning sub-word destination: {dest_node.id} ({dest_width} bits from {spec.target_width}-bit port)")
                        else:
                            subword_destinations.append((dest_node, dest_width, edge))
                            print(f"    Found sub-word destination: {dest_node.id} ({dest_width} bits)")
                    elif dest_width and dest_width == spec.target_width and spec.alignment == 'unaligned':
                        fullword_destinations.append((dest_node, dest_width, edge))
                        print(f"    Found full-word destination needing unaligned support: {dest_node.id} ({dest_width} bits)")

            # Insert byte selection mux for each sub-word destination
            for dest_node, dest_width, orig_edge in subword_destinations:
                result = self._insert_byte_selection_mux(
                    read_node,
                    dest_node,
                    addr_node,
                    dest_width,
                    spec.target_width,
                    orig_edge,
                    spec.endianness
                )
                nodes_added.extend(result['nodes_added'])
                nodes_updated.extend(result['nodes_updated'])

            # Insert unaligned word merge for full-word destinations when alignment='unaligned'
            for dest_node, dest_width, orig_edge in fullword_destinations:
                result = self._insert_unaligned_word_merge(
                    read_node,
                    dest_node,
                    addr_node,
                    spec,
                    orig_edge,
                    access_width=dest_width  # Full-word: access_width == port_width
                )
                nodes_added.extend(result['nodes_added'])
                nodes_updated.extend(result['nodes_updated'])

            # Insert spanning sub-word merge for sub-word accesses that may span word boundaries
            # This handles cases like 32-bit instruction fetch from 64-bit memory
            for dest_node, dest_width, orig_edge in spanning_subword_destinations:
                result = self._insert_unaligned_word_merge(
                    read_node,
                    dest_node,
                    addr_node,
                    spec,
                    orig_edge,
                    access_width=dest_width  # Sub-word: access_width < port_width
                )
                nodes_added.extend(result['nodes_added'])
                nodes_updated.extend(result['nodes_updated'])

        print(f"  Added {len(nodes_added)} byte selection mux nodes")

        # Transform byte_enable_computation nodes created by graph_merger into standard ops
        be_nodes_transformed = self._transform_byte_enable_computation_nodes(
            spec.memory, spec.target_width, nodes_added, nodes_updated, spec.endianness,
            alignment=spec.alignment
        )
        if be_nodes_transformed > 0:
            print(f"  Transformed {be_nodes_transformed} byte_enable_computation nodes to standard ops")

        return {
            'transformed': True,
            'direction': 'forward',
            'old_port_width': existing_port_width,
            'new_port_width': spec.target_width,
            'nodes_added': nodes_added,
            'nodes_updated': nodes_updated
        }

    def _add_word_addressed_byte_mux_multi_width(
        self,
        access_node: Node,
        spec: MemoryAccessTransformSpec,
        dests_by_width: Dict[int, List[tuple]]
    ) -> Dict[str, List[str]]:
        """
        Transform a memory access to use word-addressing with multiple byte-selection muxes.

        For merged graphs where one access node serves multiple destinations with
        different widths (e.g., byte_data[8], halfword_data[16], data[32]).

        Creates:
        1. Word address extraction: word_addr = addr[31:offset_bits]
        2. Byte offset extraction: byte_offset = addr[offset_bits-1:0]
        3. Byte selection mux for each sub-word width
        4. Full-word destinations remain connected directly
        """
        import math

        print(f"    Adding multi-width byte muxes for {access_node.id}")
        print(f"    Destination widths: {list(dests_by_width.keys())}")

        access_mode = access_node.data.get('access_mode', 'read')
        nodes_added = []
        nodes_updated = [access_node.id]

        # Find the address node (not the array base)
        addr_node = None
        for edge in access_node.incoming_edges:
            if edge.data.get('type') == 'array_index':
                # Skip the array base (the memory itself)
                if edge.source.data.get('is_memory') or edge.source.data.get('type') in ['isa_state mem', 'mem']:
                    continue
                addr_node = edge.source
                break

        if not addr_node:
            print(f"      Warning: No address node found")
            return {'nodes_added': [], 'nodes_updated': []}

        # Mark access node as word-addressed
        access_node.data['word_addressed'] = True
        access_node.data['port_width'] = spec.target_width

        # Calculate offset bits based on port width (generic for any port width)
        port_width_bytes = spec.target_width // 8
        offset_bits = int(math.log2(port_width_bytes))
        addr_width = addr_node.data.get('bit_width') or 32  # Default to 32-bit address

        print(f"      Port width: {spec.target_width} bits ({port_width_bytes} bytes)")
        print(f"      Offset bits needed: {offset_bits} (addr[{offset_bits-1}:0])")

        # Create word address extraction node (once)
        word_addr_name = f"{access_node.id}_word_addr"
        word_addr_data = {
            'type': 'bit_slice',
            'name': word_addr_name,
            'display_name': f"{addr_node.id}[{addr_width-1}:{offset_bits}]",
            'bit_width': addr_width - offset_bits,
            'expression': {
                'type': 'bit_slice',
                'range': [addr_width - 1, offset_bits],
                'operand': {'type': 'identifier', 'name': addr_node.id}
            }
        }
        word_addr_node = Node(word_addr_name, word_addr_data, is_uarch_state=False)
        self.graph.add_node(word_addr_node)
        nodes_added.append(word_addr_name)

        # Connect addr -> word_addr
        word_addr_edge = Edge(addr_node, word_addr_node, data={
            'type': 'operand',
            'label': 'bitslice_operand'
        })
        self.graph.add_edge(word_addr_edge)

        # Create byte offset extraction node (once)
        byte_offset_name = f"{access_node.id}_byte_offset"
        byte_offset_data = {
            'type': 'bit_slice',
            'name': byte_offset_name,
            'display_name': f"{addr_node.id}[{offset_bits-1}:0]",
            'bit_width': offset_bits,
            'offset_bits': offset_bits,
            'expression': {
                'type': 'bit_slice',
                'range': [offset_bits - 1, 0],
                'operand': {'type': 'identifier', 'name': addr_node.id}
            }
        }
        byte_offset_node = Node(byte_offset_name, byte_offset_data, is_uarch_state=False)
        self.graph.add_node(byte_offset_node)
        nodes_added.append(byte_offset_name)

        # Connect addr -> byte_offset
        byte_offset_edge = Edge(addr_node, byte_offset_node, data={
            'type': 'operand',
            'label': 'bitslice_operand'
        })
        self.graph.add_edge(byte_offset_edge)

        # Update ALL array_index edges to use word address instead of full address
        # This is important when multiple instructions with different EA computations
        # are merged - we need to remove ALL address edges and replace with the single
        # word_addr edge to ensure consistency between memory index and byte offset
        edges_removed = []
        for edge in list(access_node.incoming_edges):
            if edge.data.get('type') == 'array_index':
                # Skip the memory array itself
                if edge.source.data.get('is_memory') or edge.source.data.get('type') in ['isa_state mem', 'mem']:
                    continue
                edge.remove_from_nodes()
                if edge.id in self.graph.edges:
                    del self.graph.edges[edge.id]
                edges_removed.append(edge.source.id)

        # Create single new edge from word_addr_node
        new_edge = Edge(word_addr_node, access_node, data={
            'type': 'array_index',
            'original_addr': addr_node.id,
            'replaced_edges': edges_removed
        })
        self.graph.add_edge(new_edge)

        if access_mode == 'read':
            # For reads: Create byte-selection mux for each sub-word width
            for dest_width, dests in dests_by_width.items():
                if dest_width >= spec.target_width:
                    # Full-word destinations stay connected directly
                    print(f"      {dest_width}-bit destinations: direct (no mux needed)")
                    continue

                # Create mux for this width
                mux_type = 'byte' if dest_width == 8 else 'halfword' if dest_width == 16 else f'{dest_width}bit'
                mux_name = f"{access_node.id}_{mux_type}_mux"
                mux_data = {
                    'type': 'byte_selection_mux',
                    'name': mux_name,
                    'display_name': f"{mux_type}_mux({access_node.id})",
                    'bit_width': dest_width,
                    'port_width': spec.target_width,
                    'access_width': dest_width,
                    'mux_type': mux_type,
                    'offset_bits': offset_bits
                }
                mux_node = Node(mux_name, mux_data, is_uarch_state=False)
                self.graph.add_node(mux_node)
                nodes_added.append(mux_name)

                # Connect word_data (from memory) to mux
                mux_data_edge = Edge(access_node, mux_node, data={
                    'type': 'operand',
                    'label': 'mux_data'
                })
                self.graph.add_edge(mux_data_edge)

                # Connect byte_offset to mux as selector
                mux_sel_edge = Edge(byte_offset_node, mux_node, data={
                    'type': 'operand',
                    'label': 'mux_select'
                })
                self.graph.add_edge(mux_sel_edge)

                # Redirect destinations of this width to use mux output
                for old_edge, dest in dests:
                    old_edge.remove_from_nodes()
                    if old_edge.id in self.graph.edges:
                        del self.graph.edges[old_edge.id]

                    new_edge = Edge(mux_node, dest, data={
                        'type': 'assignment',
                        'from_byte_mux': True,
                        'original_access': access_node.id
                    })
                    self.graph.add_edge(new_edge)

                print(f"      Created {mux_name} for {len(dests)} {dest_width}-bit destination(s)")

        else:  # write
            # For writes: Add byte_offset as input for byte-enable generation
            # Group by width and add byte_offset connection for sub-word writes
            for dest_width, dests in dests_by_width.items():
                if dest_width >= spec.target_width:
                    continue
                # Add byte_offset connection to access_node for writes
                byte_enable_edge = Edge(byte_offset_node, access_node, data={
                    'type': 'operand',
                    'label': 'byte_enable_select',
                    'write_width': dest_width
                })
                self.graph.add_edge(byte_enable_edge)
                print(f"      Added byte enable for {dest_width}-bit writes")

        return {'nodes_added': nodes_added, 'nodes_updated': nodes_updated}

    def _add_word_addressed_byte_mux(
        self,
        access_node: Node,
        spec: MemoryAccessTransformSpec,
        access_width: int
    ) -> Dict[str, List[str]]:
        """
        Transform a memory access to use word-addressing with byte-selection mux.

        For reads (LB/LH):
        1. Extract word address: word_addr = addr[31:2]
        2. Extract byte offset: byte_offset = addr[1:0]
        3. Read full word: word_data = mem[word_addr]
        4. Generate byte mux: data = mux(byte_offset, word_data)

        For writes (SB/SH):
        1. Extract word address: word_addr = addr[31:2]
        2. Extract byte offset: byte_offset = addr[1:0]
        3. Generate byte enables based on offset and access width
        4. Write to mem[word_addr] with byte enables
        """
        print(f"    Adding word-addressed byte mux for {access_node.id}")

        access_mode = access_node.data.get('access_mode', 'read')
        nodes_added = []
        nodes_updated = [access_node.id]

        # Find the address node (not the array base)
        addr_node = None
        for edge in access_node.incoming_edges:
            if edge.data.get('type') == 'array_index':
                # Skip the array base (the memory itself)
                if edge.source.data.get('is_memory') or edge.source.data.get('type') in ['isa_state mem', 'mem']:
                    continue
                addr_node = edge.source
                break

        if not addr_node:
            print(f"      Warning: No address node found")
            return {'nodes_added': [], 'nodes_updated': []}

        # Mark access node as word-addressed
        access_node.data['word_addressed'] = True
        access_node.data['port_width'] = spec.target_width
        access_node.data['byte_access_width'] = access_width

        # Calculate offset bits based on port width (generic for any port width)
        # port_width_bytes = port_width / 8 (e.g., 32-bit port = 4 bytes)
        # offset_bits = log2(port_width_bytes) (e.g., log2(4) = 2 bits for addr[1:0])
        import math
        port_width_bytes = spec.target_width // 8
        offset_bits = int(math.log2(port_width_bytes))
        addr_width = addr_node.data.get('bit_width', 32)

        print(f"      Port width: {spec.target_width} bits ({port_width_bytes} bytes)")
        print(f"      Offset bits needed: {offset_bits} (addr[{offset_bits-1}:0])")
        print(f"      Word address: addr[{addr_width-1}:{offset_bits}]")

        # Create word address extraction node: addr[addr_width-1:offset_bits]
        word_addr_name = f"{access_node.id}_word_addr"
        word_addr_data = {
            'type': 'bit_slice',
            'name': word_addr_name,
            'display_name': f"{addr_node.id}[{addr_width-1}:{offset_bits}]",
            'bit_width': addr_width - offset_bits,
            'expression': {
                'type': 'bit_slice',
                'range': [addr_width - 1, offset_bits],
                'operand': {'type': 'identifier', 'name': addr_node.id}
            }
        }
        word_addr_node = Node(word_addr_name, word_addr_data, is_uarch_state=False)
        self.graph.add_node(word_addr_node)
        nodes_added.append(word_addr_name)

        # Connect addr -> word_addr
        word_addr_edge = Edge(addr_node, word_addr_node, data={
            'type': 'operand',
            'label': 'bitslice_operand'
        })
        self.graph.add_edge(word_addr_edge)

        # Create byte offset extraction node: addr[offset_bits-1:0]
        byte_offset_name = f"{access_node.id}_byte_offset"
        byte_offset_data = {
            'type': 'bit_slice',
            'name': byte_offset_name,
            'display_name': f"{addr_node.id}[{offset_bits-1}:0]",
            'bit_width': offset_bits,
            'offset_bits': offset_bits,  # Store for later use
            'expression': {
                'type': 'bit_slice',
                'range': [offset_bits - 1, 0],
                'operand': {'type': 'identifier', 'name': addr_node.id}
            }
        }
        byte_offset_node = Node(byte_offset_name, byte_offset_data, is_uarch_state=False)
        self.graph.add_node(byte_offset_node)
        nodes_added.append(byte_offset_name)

        # Connect addr -> byte_offset
        byte_offset_edge = Edge(addr_node, byte_offset_node, data={
            'type': 'operand',
            'label': 'bitslice_operand'
        })
        self.graph.add_edge(byte_offset_edge)

        # Update ALL array_index edges to use word address instead of full address
        # This is important when multiple instructions with different EA computations
        # are merged - we need to remove ALL address edges and replace with the single
        # word_addr edge to ensure consistency between memory index and byte offset
        edges_removed = []
        for edge in list(access_node.incoming_edges):
            if edge.data.get('type') == 'array_index':
                # Skip the memory array itself
                if edge.source.data.get('is_memory') or edge.source.data.get('type') in ['isa_state mem', 'mem']:
                    continue
                edge.remove_from_nodes()
                if edge.id in self.graph.edges:
                    del self.graph.edges[edge.id]
                edges_removed.append(edge.source.id)

        # Create single new edge from word_addr_node
        new_edge = Edge(word_addr_node, access_node, data={
            'type': 'array_index',
            'original_addr': addr_node.id,
            'replaced_edges': edges_removed
        })
        self.graph.add_edge(new_edge)

        if access_mode == 'read':
            # For reads: Add byte-selection mux after the memory read using standard priority mux
            mux_name = f"{access_node.id}_byte_mux"

            # Determine selector and slices based on access width
            if access_width == 8:
                # Byte access: 4 positions
                num_inputs = 4
                slice_ranges = [(7, 0), (15, 8), (23, 16), (31, 24)]
                # For big-endian, reverse slice_ranges
                if spec.endianness == 'big':
                    slice_ranges = list(reversed(slice_ranges))
                selector_node = byte_offset_node
            elif access_width == 16:
                # Halfword access: 2 positions, use bit 1 of offset
                num_inputs = 2
                slice_ranges = [(15, 0), (31, 16)]
                # For big-endian, reverse slice_ranges
                if spec.endianness == 'big':
                    slice_ranges = list(reversed(slice_ranges))
                selector_name = f"{access_node.id}_halfword_select"
                selector_data = {
                    'type': 'bit_slice',
                    'name': selector_name,
                    'display_name': f"{addr_node.id}[1]",
                    'bit_width': 1,
                    'expression': {
                        'type': 'bit_slice',
                        'range': [1, 1],
                        'operand': {'type': 'identifier', 'name': addr_node.id}
                    }
                }
                selector_node = Node(selector_name, selector_data, is_uarch_state=False)
                self.graph.add_node(selector_node)
                nodes_added.append(selector_name)
                sel_edge = Edge(addr_node, selector_node, data={
                    'type': 'operand',
                    'label': 'bitslice_operand'
                })
                self.graph.add_edge(sel_edge)
            else:
                raise ValueError(f"Unsupported access width: {access_width}")

            # Create bit slice nodes for each byte/halfword position
            slice_nodes = []
            for i, (high, low) in enumerate(slice_ranges):
                # Include bit range in name to differentiate byte vs halfword slices
                slice_name = f"{access_node.id}_slice_{high}_{low}"
                slice_data = {
                    'type': 'bit_slice',
                    'name': slice_name,
                    'display_name': f"{access_node.id}[{high}:{low}]",
                    'bit_width': access_width,
                    'expression': {
                        'type': 'bit_slice',
                        'range': [high, low],
                        'operand': {'type': 'identifier', 'name': access_node.id}
                    }
                }
                slice_node = Node(slice_name, slice_data, is_uarch_state=False)
                self.graph.add_node(slice_node)
                nodes_added.append(slice_name)
                slice_edge = Edge(access_node, slice_node, data={
                    'type': 'operand',
                    'label': 'bitslice_operand'
                })
                self.graph.add_edge(slice_edge)
                slice_nodes.append(slice_node)

            # Create comparison nodes for selector conditions
            compare_nodes = []
            selector_width = 2 if access_width == 8 else 1
            for i in range(num_inputs):
                cmp_name = f"{mux_name}_sel_{i}"
                cmp_data = {
                    'type': 'comparison',
                    'name': cmp_name,
                    'display_name': f"{selector_node.id} == {i}",
                    'bit_width': 1,
                    'operator': '==',
                    'compare_value': i,
                    'expression': {
                        'type': 'comparison',
                        'operator': '==',
                        'left': {'type': 'identifier', 'name': selector_node.id},
                        'right': {'type': 'literal', 'value': i, 'width': selector_width}
                    }
                }
                cmp_node = Node(cmp_name, cmp_data, is_uarch_state=False)
                self.graph.add_node(cmp_node)
                nodes_added.append(cmp_name)
                cmp_edge = Edge(selector_node, cmp_node, data={
                    'type': 'operand',
                    'label': 'left_operand'
                })
                self.graph.add_edge(cmp_edge)
                compare_nodes.append(cmp_node)

            # Create priority mux using MuxBuilder
            builder = MuxBuilder(self.graph, mux_name, MuxType.PRIORITY)
            builder.create_or_get_mux(display_name=f"byte_mux({access_node.id})")
            builder.mux_node.data['bit_width'] = access_width
            mux_node = builder.mux_node

            # Add inputs with their select signals
            for i, (slice_node, cmp_node) in enumerate(zip(slice_nodes, compare_nodes)):
                builder.add_input(slice_node, cmp_node, input_index=i)

            nodes_added.append(mux_name)

            # Redirect all original destinations to use mux output
            edges_to_redirect = []
            for edge in list(access_node.outgoing_edges):
                if edge.data.get('type') == 'assignment':
                    edges_to_redirect.append((edge, edge.target))

            for old_edge, dest in edges_to_redirect:
                # Remove old edge
                old_edge.remove_from_nodes()
                if old_edge.id in self.graph.edges:
                    del self.graph.edges[old_edge.id]

                # Add new edge from mux
                new_edge = Edge(mux_node, dest, data={
                    'type': 'assignment',
                    'from_byte_mux': True,
                    'original_access': access_node.id
                })
                self.graph.add_edge(new_edge)

            print(f"      Added byte-selection mux: {mux_name}")

        else:  # write
            # For writes: Generate byte-enable and positioned write data nodes
            # This mirrors the load path structure for consistency

            # Determine parameters based on access width
            port_width = spec.target_width
            num_byte_lanes = port_width // 8  # e.g., 4 for 32-bit
            bytes_per_access = access_width // 8  # e.g., 1 for byte, 2 for halfword

            if access_width == 8:
                # Byte store: 4 positions, use full 2-bit offset
                num_positions = num_byte_lanes
                selector_node = byte_offset_node
                selector_width = 2
            elif access_width == 16:
                # Halfword store: 2 positions, use bit 1 of offset
                num_positions = num_byte_lanes // 2
                selector_name = f"{access_node.id}_halfword_select"
                selector_node = self.graph.nodes.get(selector_name)
                if not selector_node:
                    selector_data = {
                        'type': 'bit_slice',
                        'name': selector_name,
                        'display_name': f"{addr_node.id}[1]",
                        'bit_width': 1,
                        'expression': {
                            'type': 'bit_slice',
                            'range': [1, 1],
                            'operand': {'type': 'identifier', 'name': addr_node.id}
                        }
                    }
                    selector_node = Node(selector_name, selector_data, is_uarch_state=False)
                    self.graph.add_node(selector_node)
                    nodes_added.append(selector_name)
                    sel_edge = Edge(addr_node, selector_node, data={
                        'type': 'operand',
                        'label': 'bitslice_operand'
                    })
                    self.graph.add_edge(sel_edge)
                selector_width = 1
            else:
                # Full-width store: no byte selection needed
                print(f"      Full-width store, no byte selection needed")
                return {'nodes_added': nodes_added, 'nodes_updated': nodes_updated}

            # Create comparison nodes for each byte-lane position (like load path)
            compare_nodes = []
            for i in range(num_positions):
                cmp_name = f"{access_node.id}_byte_sel_{i}"
                cmp_node = self.graph.nodes.get(cmp_name)
                if not cmp_node:
                    cmp_data = {
                        'type': 'comparison',
                        'name': cmp_name,
                        'display_name': f"{selector_node.id} == {i}",
                        'bit_width': 1,
                        'operator': '==',
                        'compare_value': i,
                        'expression': {
                            'type': 'comparison',
                            'operator': '==',
                            'left': {'type': 'identifier', 'name': selector_node.id},
                            'right': {'type': 'literal', 'value': i, 'width': selector_width}
                        }
                    }
                    cmp_node = Node(cmp_name, cmp_data, is_uarch_state=False)
                    self.graph.add_node(cmp_node)
                    nodes_added.append(cmp_name)

                    # Connect selector -> comparison
                    cmp_edge = Edge(selector_node, cmp_node, data={
                        'type': 'operand',
                        'label': 'left_operand'
                    })
                    self.graph.add_edge(cmp_edge)
                compare_nodes.append(cmp_node)

            # Create byte-enable signal using standard shift operation
            # For 8-bit: BE = 4'b0001 << byte_offset[1:0]
            # For 16-bit: BE = 4'b0011 << {byte_offset[1], 1'b0}
            byte_enable_name = f"{access_node.id}_byte_enable"

            # Create base mask literal node
            base_mask_name = f"{access_node.id}_be_mask"
            base_mask_value = (1 << bytes_per_access) - 1  # 1 for 8-bit, 3 for 16-bit
            base_mask_data = {
                'type': 'literal',
                'name': base_mask_name,
                'display_name': f"{num_byte_lanes}'b{base_mask_value:0{num_byte_lanes}b}",
                'bit_width': num_byte_lanes,
                'value': base_mask_value,
                'expression': {
                    'type': 'literal',
                    'value': base_mask_value,
                    'width': num_byte_lanes
                }
            }
            base_mask_node = Node(base_mask_name, base_mask_data, is_uarch_state=False)
            self.graph.add_node(base_mask_node)
            nodes_added.append(base_mask_name)

            # Determine shift amount node
            if access_width == 8:
                # 8-bit: shift by byte_offset directly
                shift_amount_node = byte_offset_node
            else:
                # 16-bit: shift by {byte_offset[1], 1'b0} = byte_offset[1] << 1
                # Create concatenation: {selector_node, 1'b0}
                shift_amount_name = f"{access_node.id}_be_shift"
                zero_bit_name = f"{access_node.id}_zero_bit"

                # Create zero literal for low bit
                zero_bit_data = {
                    'type': 'literal',
                    'name': zero_bit_name,
                    'display_name': "1'b0",
                    'bit_width': 1,
                    'value': 0,
                    'expression': {'type': 'literal', 'value': 0, 'width': 1}
                }
                zero_bit_node = Node(zero_bit_name, zero_bit_data, is_uarch_state=False)
                self.graph.add_node(zero_bit_node)
                nodes_added.append(zero_bit_name)

                # Create concatenation {selector_node, 0}
                shift_amount_data = {
                    'type': 'concatenation',
                    'name': shift_amount_name,
                    'display_name': f"{{{selector_node.id}, 1'b0}}",
                    'bit_width': 2,
                    'expression': {
                        'type': 'concatenation',
                        'parts': [
                            {'type': 'identifier', 'name': selector_node.id},
                            {'type': 'literal', 'value': 0, 'width': 1}
                        ]
                    }
                }
                shift_amount_node = Node(shift_amount_name, shift_amount_data, is_uarch_state=False)
                self.graph.add_node(shift_amount_node)
                nodes_added.append(shift_amount_name)

                # Connect inputs to concatenation
                concat_edge1 = Edge(selector_node, shift_amount_node, data={
                    'type': 'concatenation_input', 'position': 0
                })
                concat_edge2 = Edge(zero_bit_node, shift_amount_node, data={
                    'type': 'concatenation_input', 'position': 1
                })
                self.graph.add_edge(concat_edge1)
                self.graph.add_edge(concat_edge2)

            # Create shift operation node: base_mask << shift_amount
            byte_enable_data = {
                'type': 'operation',
                'name': byte_enable_name,
                'display_name': f"{base_mask_name} << {shift_amount_node.id}",
                'bit_width': num_byte_lanes,
                'operator': '<<',
                'expression': {
                    'type': 'binary_op',
                    'operator': '<<',
                    'left': {'type': 'identifier', 'name': base_mask_name},
                    'right': {'type': 'identifier', 'name': shift_amount_node.id}
                }
            }
            byte_enable_node = Node(byte_enable_name, byte_enable_data, is_uarch_state=False)
            self.graph.add_node(byte_enable_node)
            nodes_added.append(byte_enable_name)

            # Connect operands to shift operation
            shift_edge1 = Edge(base_mask_node, byte_enable_node, data={
                'type': 'operand', 'label': 'left_operand'
            })
            shift_edge2 = Edge(shift_amount_node, byte_enable_node, data={
                'type': 'operand', 'label': 'right_operand'
            })
            self.graph.add_edge(shift_edge1)
            self.graph.add_edge(shift_edge2)

            # Create positioned write data node using standard repetition type
            # For 8-bit to 32-bit: {4{data[7:0]}}
            # For 16-bit to 32-bit: {2{data[15:0]}}
            write_data_node = self._find_write_data_source(access_node)
            if write_data_node:
                positioned_data_name = f"{access_node.id}_positioned_data"
                num_replications = port_width // access_width
                positioned_data_data = {
                    'type': 'repetition',
                    'name': positioned_data_name,
                    'display_name': f"{{{num_replications}{{{write_data_node.id}}}}}",
                    'bit_width': port_width,
                    'count': num_replications,
                    'expression': {
                        'type': 'repetition',
                        'count': num_replications,
                        'expression': {'type': 'identifier', 'name': write_data_node.id}
                    }
                }
                positioned_data_node = Node(positioned_data_name, positioned_data_data, is_uarch_state=False)
                self.graph.add_node(positioned_data_node)
                nodes_added.append(positioned_data_name)

                # Connect write data to repetition using standard edge type
                write_data_edge = Edge(write_data_node, positioned_data_node, data={
                    'type': 'repetition_input'
                })
                self.graph.add_edge(write_data_edge)
            else:
                positioned_data_node = None

            # Connect byte_enable and positioned_data to access node
            be_access_edge = Edge(byte_enable_node, access_node, data={
                'type': 'store_byte_enable'
            })
            self.graph.add_edge(be_access_edge)

            if positioned_data_node:
                pd_access_edge = Edge(positioned_data_node, access_node, data={
                    'type': 'store_data'
                })
                self.graph.add_edge(pd_access_edge)

            # Store metadata on access node for verilog generator
            access_node.data['store_byte_enable_node'] = byte_enable_name
            if positioned_data_node:
                access_node.data['store_data_node'] = positioned_data_name
            access_node.data['store_byte_sel_nodes'] = [n.id for n in compare_nodes]

            print(f"      Added store byte-enable: {byte_enable_name}")
            if positioned_data_node:
                print(f"      Added store positioned data: {positioned_data_name}")

        return {
            'nodes_added': nodes_added,
            'nodes_updated': nodes_updated
        }

    def _set_port_width_reverse(
        self,
        spec: MemoryAccessTransformSpec,
        dry_run: bool = False
    ) -> Dict[str, any]:
        """
        Reverse: Remove port_width and byte-muxing logic.

        Restores direct byte-addressed memory access.
        """
        print(f"  Removing port_width from {spec.memory}")

        # Find memory node
        memory_node = self.graph.nodes.get(spec.memory)
        if not memory_node:
            return {
                'transformed': False,
                'reason': f"Memory {spec.memory} not found"
            }

        # Check if has port_width set
        existing_port_width = memory_node.data.get('port_width')
        if not existing_port_width:
            return {
                'transformed': False,
                'reason': f"No port_width set on {spec.memory}"
            }

        # Find all byte mux nodes and related nodes to remove
        nodes_to_remove = []
        for node in self.graph.nodes.values():
            node_type = node.data.get('type')
            # Check for byte mux (standard multiplexer with byte_mux in name)
            is_byte_mux = (node_type == 'multiplexer' and 'byte_mux' in node.id)
            # Check for bit_slice nodes created for byte selection
            is_slice_node = (node_type == 'bit_slice' and
                           ('word_addr' in node.id or 'byte_offset' in node.id or
                            '_slice_' in node.id or 'halfword_select' in node.id))
            # Check for comparison nodes created for byte mux selection
            is_cmp_node = (node_type == 'comparison' and 'byte_mux_sel_' in node.id)
            if is_byte_mux or is_slice_node or is_cmp_node:
                if spec.memory in node.id:
                    nodes_to_remove.append(node)

        if dry_run:
            return {
                'transformed': True,
                'direction': 'reverse',
                'old_port_width': existing_port_width,
                'new_port_width': None,
                'nodes_removed': [n.id for n in nodes_to_remove],
                'nodes_updated': [spec.memory],
                'dry_run': True
            }

        # Remove port_width and endianness from memory node
        del memory_node.data['port_width']
        if 'endianness' in memory_node.data:
            del memory_node.data['endianness']
        print(f"  Removed port_width and endianness from {spec.memory}")

        # Remove all transformation nodes
        for node in nodes_to_remove:
            self._remove_node_and_edges(node)

        print(f"  Removed {len(nodes_to_remove)} transformation nodes")

        return {
            'transformed': True,
            'direction': 'reverse',
            'old_port_width': existing_port_width,
            'new_port_width': None,
            'nodes_removed': [n.id for n in nodes_to_remove],
            'nodes_updated': [spec.memory]
        }

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _find_memory_access_nodes(self, memory: str) -> List[Node]:
        """
        Find all memory access nodes for a given memory.

        This handles both:
        1. array_access type nodes (before splitting)
        2. Split _rd/_wr nodes (after graph merger splits them)
           Pattern: [instr_]memname[...]_rd or [instr_]memname[...]_wr
        """
        access_nodes = []

        for node in self.graph.nodes.values():
            # Check for array_access type nodes (pre-split)
            if node.data.get('type') == 'array_access':
                # Check if this accesses our memory by examining the expression
                expr = node.data.get('expression', {})
                array_expr = expr.get('target', {})

                # The array expression should be an identifier with the memory name
                if array_expr.get('type') == 'identifier' and array_expr.get('name') == memory:
                    access_nodes.append(node)
                continue

            # Check for split memory access nodes (post-merge)
            # Pattern: [instr_]memname[...]_rd or [instr_]memname[...]_wr
            if f'{memory}[' in node.id and ('_rd' in node.id or '_wr' in node.id):
                # Determine access mode from suffix
                if '_rd' in node.id:
                    node.data['access_mode'] = 'read'
                else:
                    node.data['access_mode'] = 'write'
                access_nodes.append(node)

        return access_nodes

    def _create_read_address_mux(
        self,
        read_node: Node,
        addr_sources: List[Tuple[Node, 'Edge']],
        port_width: int
    ) -> Tuple[Node, List[str]]:
        """
        Create an address mux for a memory read with multiple address sources.

        When multiple instructions (e.g., lbz, lbzx, lwz) share a memory read node
        but have different effective address computations, we need a mux to select
        the correct address based on which instruction is active.

        Uses existing collision mux enable signals (e.g., lbz_ea_mux_enable_or_0)
        from the graph merger rather than parsing instruction names.

        Args:
            read_node: The memory read node (e.g., dmem[addr]_rd)
            addr_sources: List of (addr_node, edge) tuples
            port_width: The memory port width

        Returns:
            Tuple of (address_mux_node, list_of_added_node_ids)
        """
        nodes_added = []

        # Create a sanitized name for the mux
        sanitized_read_id = read_node.id.replace('[', '_').replace(']', '')
        addr_mux_id = f"{sanitized_read_id}_addr_mux"

        # Determine address width from first source
        first_addr = addr_sources[0][0]
        addr_width = first_addr.data.get('bit_width', 64)

        # Group sources by unique address node
        # Map addr_node_id -> addr_node
        addr_groups = {}
        for addr_node, edge in addr_sources:
            if addr_node.id not in addr_groups:
                addr_groups[addr_node.id] = addr_node

        # Create the mux node with metadata about its inputs
        # Look for existing collision mux enable signals from the graph merger
        mux_inputs = []
        import re
        for addr_id, addr_node in sorted(addr_groups.items()):
            enable_signal = None

            # Try 1: Look for collision mux enable signals like "{ea_node}_mux_enable_or_0"
            mux_enable_id = f"{addr_node.id}_mux_enable_or_0"
            if self.graph.nodes.get(mux_enable_id):
                enable_signal = mux_enable_id
            else:
                # Try 2: Find ALL instruction enables that share this address node
                # Address nodes may be shared between instructions with different prefixes
                # (e.g., dd_ld_a_bc_mem_addr is shared by dd_ld_a_bc_mem and ld_a_bc_mem)
                match = re.match(r'^(.+)_addr$', addr_node.id)
                if match:
                    instr_name = match.group(1)

                    # Find instruction enables that use this address node
                    # IMPORTANT: We need to distinguish between:
                    # 1. Address nodes that ARE shared between prefix variants (e.g., LD A,(BC)
                    #    where the address is just the BC register - same for all prefixes)
                    # 2. Address nodes that are NOT shared (e.g., LD A,(nn) where the address
                    #    comes from PC-relative bytes - different for each prefix)
                    #
                    # To detect this: if the address node name starts with a prefix (dd_, fd_)
                    # and there's a SEPARATE unprefixed address node, then they're not shared.
                    # Otherwise, they ARE shared.
                    matching_enables = []

                    # First, check the exact instruction enable
                    instr_enable_id = f"{instr_name}_enable"
                    if self.graph.nodes.get(instr_enable_id):
                        matching_enables.append(instr_enable_id)

                    # Check for related instructions with different prefixes (dd_, fd_, ed_)
                    base_name = instr_name
                    prefixes = ['dd_', 'fd_', 'ed_']
                    has_prefix = False

                    # If instr_name starts with a prefix, extract the base name
                    for prefix in prefixes:
                        if instr_name.startswith(prefix):
                            base_name = instr_name[len(prefix):]
                            has_prefix = True
                            break

                    # Only OR enables together if the address is truly shared
                    # (i.e., there's no separate unprefixed address node)
                    unprefixed_addr_id = f"{base_name}_addr"
                    if has_prefix and self.graph.nodes.get(unprefixed_addr_id):
                        # There's a separate unprefixed address node, so DON'T share enables
                        # Each prefix variant has its own address computation
                        print(f"        NOT sharing enables: {unprefixed_addr_id} exists separately")
                    else:
                        # No separate unprefixed address node, so the address IS shared
                        # Look for enables with all prefix variants and unprefixed
                        variants_to_check = [base_name]  # unprefixed
                        for prefix in prefixes:
                            variants_to_check.append(f"{prefix}{base_name}")

                        for variant in variants_to_check:
                            variant_enable_id = f"{variant}_enable"
                            if variant_enable_id != instr_enable_id:  # Don't duplicate
                                if self.graph.nodes.get(variant_enable_id):
                                    matching_enables.append(variant_enable_id)

                    if len(matching_enables) == 1:
                        enable_signal = matching_enables[0]
                        print(f"        Using instruction enable: {enable_signal}")
                    elif len(matching_enables) > 1:
                        # Create an OR node for multiple enables
                        or_node_id = f"{addr_node.id}_enable_or"
                        if not self.graph.nodes.get(or_node_id):
                            or_node = Node(or_node_id, {
                                'type': 'logical_or',
                                'operation': '||',
                                'bit_width': 1,
                                'display_name': f"{addr_node.id} enables OR",
                                'source_enables': matching_enables
                            })
                            self.graph.add_node(or_node)
                            nodes_added.append(or_node_id)

                            # Connect all enable signals to the OR node
                            for enable_id in matching_enables:
                                enable_node = self.graph.nodes[enable_id]
                                edge = Edge(enable_node, or_node, data={'type': 'logic_input'})
                                self.graph.add_edge(edge)

                            print(f"        Created OR of enables: {' || '.join(matching_enables)}")

                        enable_signal = or_node_id

            mux_inputs.append({
                'source_node': addr_node.id,
                'enable_node': enable_signal  # Node ID of enable signal, or None for default
            })

        # Create the address mux node
        addr_mux_data = {
            'type': 'one_hot_mux',
            'name': addr_mux_id,
            'display_name': f"{sanitized_read_id} Address MUX",
            'bit_width': addr_width,
            'mux_inputs': mux_inputs,
            'is_address_mux': True,
            'memory_read_node': read_node.id
        }
        addr_mux_node = Node(addr_mux_id, addr_mux_data, is_uarch_state=False)
        self.graph.add_node(addr_mux_node)
        nodes_added.append(addr_mux_id)
        print(f"      Created address mux: {addr_mux_id}")

        # Connect address sources to mux with metadata
        for i, (addr_id, addr_node) in enumerate(sorted(addr_groups.items())):
            edge_data = {
                'type': 'mux_input',
                'input_index': i
            }
            edge = Edge(addr_node, addr_mux_node, data=edge_data)
            self.graph.add_edge(edge)
            print(f"        Input {i}: {addr_node.id}")

        # Remove the old array_index edges from read_node
        # and replace with a single edge from the mux
        for addr_node, old_edge in addr_sources:
            if old_edge.id in self.graph.edges:
                old_edge.remove_from_nodes()
                del self.graph.edges[old_edge.id]

        # Connect mux output to read_node as the new index
        new_index_edge = Edge(addr_mux_node, read_node, data={
            'type': 'array_index',
            'from_address_mux': True
        })
        self.graph.add_edge(new_index_edge)

        return addr_mux_node, nodes_added

    def _find_memory_read_nodes(self, memory: str) -> List[Node]:
        """
        Find all memory read nodes for a given memory.

        After merging, these are shared nodes like "dmem[addr]_rd" that have
        outgoing assignment edges to destination variables.
        """
        read_nodes = []

        for node in self.graph.nodes.values():
            # Check for split memory read nodes (post-merge)
            # Pattern: memname[...]_rd
            if f'{memory}[' in node.id and '_rd' in node.id:
                read_nodes.append(node)

        return read_nodes

    def _instruction_uses_hl_addr(self, instr_prefix: str, addr_node: Node) -> bool:
        """
        Check if an instruction uses an HL-based address (or same pattern as addr_node).

        This is used to determine if an instruction should be included in the enable
        OR for a shared address mux entry.

        For Z80-like ISAs where many instructions use {H, L} as the address,
        we check if the instruction is in the set that uses (HL) addressing.
        """
        # Get the address expression/pattern from the addr_node
        addr_expression = addr_node.data.get('expression', {})

        # Common patterns for HL-based addresses
        hl_patterns = ['_hl_mem', '_hl_addr', 'hl_addr', 'adc_a_hl_mem_addr']

        # Check if the addr_node ID suggests HL addressing
        is_hl_addr = any(p in addr_node.id.lower() for p in hl_patterns)

        if is_hl_addr:
            # Check if the instruction also uses HL addressing
            # Z80 instructions with (HL) have patterns like: ld_X_hl_mem, add_a_hl_mem, etc.
            hl_instr_patterns = ['_hl_mem', '_hl_addr']
            return any(p in instr_prefix.lower() for p in hl_instr_patterns)

        # For other address patterns, check if the instruction has a corresponding addr node
        # with the same base pattern
        instr_addr_id = f"{instr_prefix}_addr"
        if self.graph.nodes.get(instr_addr_id):
            # This instruction has its own address node - check if it matches
            instr_addr_node = self.graph.nodes[instr_addr_id]
            instr_expr = instr_addr_node.data.get('expression', {})
            # Compare expressions (simplified comparison)
            return str(addr_expression) == str(instr_expr)

        return False

    def _transform_byte_enable_computation_nodes(
        self,
        memory: str,
        port_width: int,
        nodes_added: List[str],
        nodes_updated: List[str],
        endianness: str = 'little',
        alignment: str = 'aligned'
    ) -> int:
        """
        Transform byte_enable_computation nodes into standard operations.

        These nodes are created by graph_merger for sub-word stores.
        We replace them with: literal << shift_amount

        For 8-bit stores: BE = 4'b0001 << addr[1:0]
        For 16-bit stores: BE = 4'b0011 << {addr[1], 1'b0}

        When alignment='unaligned', uses full byte offset for non-byte stores
        so that stores at any byte offset are positioned correctly.

        Also creates positioned data nodes and stores mappings on write port
        for use by verilog_generator.
        """
        transformed_count = 0

        # Find the write port node for this memory
        write_port_node = None
        for node in self.graph.nodes.values():
            if node.data.get('type') == 'memory_write_port':
                if node.data.get('base_memory') == memory:
                    write_port_node = node
                    break

        # Find data mux to get data sources per instruction
        data_mux_node = None
        data_sources_by_instr = {}
        for node in self.graph.nodes.values():
            if 'write_data_mux' in node.id and memory in node.id:
                data_mux_node = node
                # Extract data sources from incoming mux_input edges
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'mux_input':
                        instr = edge.data.get('source_instruction')
                        if instr:
                            data_sources_by_instr[instr] = edge.source
                break

        # Initialize mappings on write port
        store_byte_enables = {}
        store_positioned_data = {}
        store_raw_data = {}  # Maps instruction -> raw (unpositioned) data node ID for spanning writes

        for node in list(self.graph.nodes.values()):
            if node.data.get('type') != 'byte_enable_computation':
                continue

            data_width = node.data.get('data_width', 8)
            memory_width = node.data.get('memory_width', 32)

            # Skip byte enable computation for full-word or larger writes
            # This can happen when access_widths incorrectly includes values like 33
            if data_width >= port_width:
                print(f"    Skipping byte enable for {node.id}: data_width ({data_width}) >= port_width ({port_width})")
                # Remove the byte_enable_computation node since it's not needed
                # The full-word write will use all byte lanes enabled
                if node.id in self.graph.nodes:
                    del self.graph.nodes[node.id]
                continue

            num_byte_lanes = memory_width // 8
            bytes_per_access = data_width // 8
            instruction = node.data.get('instruction')

            can_span = (alignment == 'unaligned' and bytes_per_access > 1 and port_width > data_width)
            if bytes_per_access > 1:
                print(f"    SPAN_CHECK: {node.id}: alignment={alignment} bpa={bytes_per_access} pw={port_width} dw={data_width} can_span={can_span}")

            # Find address source from incoming edges
            addr_node = None
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'byte_enable_address':
                    addr_node = edge.source
                    break

            if not addr_node:
                print(f"    Warning: No address node for {node.id}")
                continue

            # Create base mask literal: 1 for 8-bit, 3 for 16-bit
            base_mask_name = f"{node.id}_mask"
            base_mask_value = (1 << bytes_per_access) - 1
            base_mask_data = {
                'type': 'literal',
                'name': base_mask_name,
                'display_name': f"{num_byte_lanes}'b{base_mask_value:0{num_byte_lanes}b}",
                'bit_width': num_byte_lanes,
                'value': base_mask_value,
                'expression': {'type': 'literal', 'value': base_mask_value, 'width': num_byte_lanes}
            }
            base_mask_node = Node(base_mask_name, base_mask_data, is_uarch_state=False)
            self.graph.add_node(base_mask_node)
            nodes_added.append(base_mask_name)

            # Create byte offset extraction: addr[N-1:0] where N = log2(port_width/8)
            import math
            offset_bits = int(math.log2(port_width // 8))  # 3 for 64-bit, 2 for 32-bit
            byte_offset_name = f"{node.id}_offset"
            byte_offset_data = {
                'type': 'bit_slice',
                'name': byte_offset_name,
                'display_name': f"{addr_node.id}[{offset_bits-1}:0]",
                'bit_width': offset_bits,
                'expression': {'type': 'bit_slice', 'range': [offset_bits-1, 0],
                              'operand': {'type': 'identifier', 'name': addr_node.id}}
            }
            byte_offset_node = Node(byte_offset_name, byte_offset_data, is_uarch_state=False)
            self.graph.add_node(byte_offset_node)
            nodes_added.append(byte_offset_name)

            offset_edge = Edge(addr_node, byte_offset_node, data={'type': 'operand'})
            self.graph.add_edge(offset_edge)

            # Determine shift amount for byte enable
            # General formula for any data_width on port_width memory:
            # - position_bits = log2(data_width/8) = log2(bytes_per_access)
            # - num_positions = port_width / data_width
            # - selector_bits = log2(num_positions)
            # - selector = addr[offset_bits-1:position_bits]
            # - BE shift = {selector, {position_bits}'b0}
            position_bits = int(math.log2(bytes_per_access))  # 0 for byte, 1 for hw, 2 for word

            if data_width == 8:
                # 8-bit: use full byte offset, no padding needed
                selector_node = byte_offset_node  # For data positioning later

                # For big-endian, invert the byte offset for byte enable
                # This puts byte at address 0 in the MSB position
                if endianness == 'big':
                    max_offset_value = (port_width // 8) - 1  # 3 for 32-bit port
                    max_offset_name = f"{node.id}_be_max_offset"
                    max_offset_data = {
                        'type': 'literal',
                        'name': max_offset_name,
                        'display_name': f"{offset_bits}'d{max_offset_value}",
                        'bit_width': offset_bits,
                        'value': max_offset_value,
                        'expression': {'type': 'literal', 'value': max_offset_value, 'width': offset_bits}
                    }
                    max_offset_node = Node(max_offset_name, max_offset_data, is_uarch_state=False)
                    self.graph.add_node(max_offset_node)
                    nodes_added.append(max_offset_name)

                    inverted_offset_name = f"{node.id}_be_inv_offset"
                    inverted_offset_data = {
                        'type': 'operation',
                        'name': inverted_offset_name,
                        'display_name': f"{max_offset_name} ^ {byte_offset_node.id}",
                        'bit_width': offset_bits,
                        'operator': '^',
                        'expression': {
                            'type': 'binary_op', 'operator': '^',
                            'left': {'type': 'identifier', 'name': max_offset_name},
                            'right': {'type': 'identifier', 'name': byte_offset_node.id}
                        }
                    }
                    inverted_offset_node = Node(inverted_offset_name, inverted_offset_data, is_uarch_state=False)
                    self.graph.add_node(inverted_offset_node)
                    nodes_added.append(inverted_offset_name)
                    self.graph.add_edge(Edge(max_offset_node, inverted_offset_node, data={'type': 'left_operand'}))
                    self.graph.add_edge(Edge(byte_offset_node, inverted_offset_node, data={'type': 'right_operand'}))

                    be_shift_amount_node = inverted_offset_node
                else:
                    be_shift_amount_node = byte_offset_node
            else:
                # 16-bit, 32-bit, etc: need selector and padding
                # num_positions = how many data_width slots fit in port_width
                num_positions = port_width // data_width
                port_bytes = port_width // 8

                if alignment == 'unaligned':
                    # Unaligned: use full byte offset for byte-level positioning
                    # This allows stores at any byte offset, not just naturally-aligned ones
                    selector_node = byte_offset_node  # Full addr[2:0] for data positioning

                    if endianness == 'big':
                        # BE shift = max_non_spanning - byte_offset
                        # max_non_spanning = port_bytes - bytes_per_access
                        max_non_spanning = port_bytes - bytes_per_access
                        max_offset_name = f"{node.id}_be_max"
                        max_offset_data = {
                            'type': 'literal',
                            'name': max_offset_name,
                            'display_name': f"{offset_bits}'d{max_non_spanning}",
                            'bit_width': offset_bits,
                            'value': max_non_spanning,
                            'expression': {'type': 'literal', 'value': max_non_spanning, 'width': offset_bits}
                        }
                        max_offset_node = Node(max_offset_name, max_offset_data, is_uarch_state=False)
                        self.graph.add_node(max_offset_node)
                        nodes_added.append(max_offset_name)

                        inverted_offset_name = f"{node.id}_be_inv_sel"
                        inverted_offset_data = {
                            'type': 'operation',
                            'name': inverted_offset_name,
                            'display_name': f"{max_offset_name} - {byte_offset_node.id}",
                            'bit_width': offset_bits,
                            'operator': '-',
                            'expression': {
                                'type': 'binary_op', 'operator': '-',
                                'left': {'type': 'identifier', 'name': max_offset_name},
                                'right': {'type': 'identifier', 'name': byte_offset_node.id}
                            }
                        }
                        be_selector_node = Node(inverted_offset_name, inverted_offset_data, is_uarch_state=False)
                        self.graph.add_node(be_selector_node)
                        nodes_added.append(inverted_offset_name)
                        self.graph.add_edge(Edge(max_offset_node, be_selector_node, data={'type': 'left_operand'}))
                        self.graph.add_edge(Edge(byte_offset_node, be_selector_node, data={'type': 'right_operand'}))
                    else:
                        be_selector_node = byte_offset_node

                    # BE shift = inverted byte offset directly (no zero padding needed)
                    be_shift_amount_node = be_selector_node

                else:
                    # Aligned: use truncated selector with zero padding
                    selector_bits = int(math.log2(num_positions)) if num_positions > 1 else 1
                    selector_high = offset_bits - 1  # Top of byte offset range
                    selector_low = position_bits     # Skip alignment bits

                    selector_name = f"{node.id}_sel"
                    selector_data = {
                        'type': 'bit_slice',
                        'name': selector_name,
                        'display_name': f"{addr_node.id}[{selector_high}:{selector_low}]",
                        'bit_width': selector_bits,
                        'expression': {'type': 'bit_slice', 'range': [selector_high, selector_low],
                                      'operand': {'type': 'identifier', 'name': addr_node.id}}
                    }
                    selector_node = Node(selector_name, selector_data, is_uarch_state=False)
                    self.graph.add_node(selector_node)
                    nodes_added.append(selector_name)
                    sel_edge = Edge(addr_node, selector_node, data={'type': 'operand'})
                    self.graph.add_edge(sel_edge)

                    # For big-endian, invert the selector for both byte enable and data positioning
                    # This puts low addresses at high bit positions (big-endian convention)
                    if endianness == 'big':
                        max_selector_value = (1 << selector_bits) - 1
                        max_selector_name = f"{node.id}_be_max"
                        max_selector_data = {
                            'type': 'literal',
                            'name': max_selector_name,
                            'display_name': f"{selector_bits}'d{max_selector_value}",
                            'bit_width': selector_bits,
                            'value': max_selector_value,
                            'expression': {'type': 'literal', 'value': max_selector_value, 'width': selector_bits}
                        }
                        max_selector_node = Node(max_selector_name, max_selector_data, is_uarch_state=False)
                        self.graph.add_node(max_selector_node)
                        nodes_added.append(max_selector_name)

                        inverted_selector_name = f"{node.id}_be_inv_sel"
                        inverted_selector_data = {
                            'type': 'operation',
                            'name': inverted_selector_name,
                            'display_name': f"{max_selector_name} ^ {selector_name}",
                            'bit_width': selector_bits,
                            'operator': '^',
                            'expression': {
                                'type': 'binary_op', 'operator': '^',
                                'left': {'type': 'identifier', 'name': max_selector_name},
                                'right': {'type': 'identifier', 'name': selector_name}
                            }
                        }
                        be_selector_node = Node(inverted_selector_name, inverted_selector_data, is_uarch_state=False)
                        self.graph.add_node(be_selector_node)
                        nodes_added.append(inverted_selector_name)
                        self.graph.add_edge(Edge(max_selector_node, be_selector_node, data={'type': 'left_operand'}))
                        self.graph.add_edge(Edge(selector_node, be_selector_node, data={'type': 'right_operand'}))
                    else:
                        # Little-endian: use selector directly
                        be_selector_node = selector_node

                    zero_name = f"{node.id}_zero"
                    zero_data = {
                        'type': 'literal', 'name': zero_name, 'display_name': f"{position_bits}'b0",
                        'bit_width': position_bits, 'value': 0,
                        'expression': {'type': 'literal', 'value': 0, 'width': position_bits}
                    }
                    zero_node = Node(zero_name, zero_data, is_uarch_state=False)
                    self.graph.add_node(zero_node)
                    nodes_added.append(zero_name)

                    shift_amount_name = f"{node.id}_shift"
                    be_selector_id = be_selector_node.id
                    selector_bits_actual = selector_node.data.get('bit_width', selector_bits)
                    shift_amount_data = {
                        'type': 'concatenation',
                        'name': shift_amount_name,
                        'display_name': f"{{{be_selector_id}, {position_bits}'b0}}",
                        'bit_width': selector_bits_actual + position_bits,
                        'expression': {'type': 'concatenation', 'expressions': [
                            {'type': 'identifier', 'name': be_selector_id},
                            {'type': 'literal', 'value': 0, 'width': position_bits}
                        ]}
                    }
                    be_shift_amount_node = Node(shift_amount_name, shift_amount_data, is_uarch_state=False)
                    self.graph.add_node(be_shift_amount_node)
                    nodes_added.append(shift_amount_name)

                    self.graph.add_edge(Edge(be_selector_node, be_shift_amount_node,
                                            data={'type': 'concatenation_input', 'position': 0}))
                    self.graph.add_edge(Edge(zero_node, be_shift_amount_node,
                                            data={'type': 'concatenation_input', 'position': 1}))

            # Update the node to be an operation instead of byte_enable_computation
            node.data['type'] = 'operation'
            node.data['operator'] = '<<'
            node.data['display_name'] = f"{base_mask_name} << {be_shift_amount_node.id}"
            node.data['expression'] = {
                'type': 'binary_op', 'operator': '<<',
                'left': {'type': 'identifier', 'name': base_mask_name},
                'right': {'type': 'identifier', 'name': be_shift_amount_node.id}
            }
            nodes_updated.append(node.id)

            # Remove old incoming edges and add new operand edges
            for edge in list(node.incoming_edges):
                edge.remove_from_nodes()
                if edge.id in self.graph.edges:
                    del self.graph.edges[edge.id]

            self.graph.add_edge(Edge(base_mask_node, node, data={'type': 'left_operand'}))
            self.graph.add_edge(Edge(be_shift_amount_node, node, data={'type': 'right_operand'}))

            # Store byte enable mapping
            if instruction:
                store_byte_enables[instruction] = node.id

            # Create positioned data node: data << (selector * data_width)
            # General formula: data << {selector, log2(data_width)'b0}
            # - 8-bit: data << {addr[2:0], 3'b0} = shift by 0,8,16,24,32,40,48,56
            # - 16-bit: data << {addr[2:1], 4'b0} = shift by 0,16,32,48
            # - 32-bit: data << {addr[2], 5'b0} = shift by 0,32
            # Data shift zeros = log2(data_width) = position_bits + 3
            data_source = data_sources_by_instr.get(instruction) if instruction else None
            if data_source:
                positioned_data_name = f"{instruction}_positioned_data"

                # Create data shift amount: selector concatenated with zeros
                if alignment == 'unaligned' and data_width > 8:
                    # Unaligned: full byte offset * 8, so just 3 zero bits
                    data_shift_zeros_width = 3
                else:
                    # Aligned: selector * data_width, so log2(data_width) zero bits
                    data_shift_zeros_width = position_bits + 3  # log2(data_width) = log2(8 * bytes_per_access)
                data_shift_zeros_name = f"{instruction}_data_shift_zeros"
                data_shift_zeros_data = {
                    'type': 'literal',
                    'name': data_shift_zeros_name,
                    'display_name': f"{data_shift_zeros_width}'b0",
                    'bit_width': data_shift_zeros_width,
                    'value': 0,
                    'expression': {'type': 'literal', 'value': 0, 'width': data_shift_zeros_width}
                }
                data_shift_zeros_node = Node(data_shift_zeros_name, data_shift_zeros_data, is_uarch_state=False)
                self.graph.add_node(data_shift_zeros_node)
                nodes_added.append(data_shift_zeros_name)

                # selector_node is either byte_offset_node (8-bit) or the extracted selector (16/32-bit)
                selector_width = selector_node.data.get('bit_width', offset_bits)

                # For big-endian, invert the selector to put low addresses at high bit positions
                if endianness == 'big':
                    if alignment == 'unaligned' and data_width > 8:
                        # Unaligned: use subtraction (max_non_spanning - byte_offset)
                        # since max_non_spanning is not always 2^n-1, XOR won't work
                        max_non_spanning = port_width // 8 - bytes_per_access
                        max_selector_name = f"{instruction}_be_max_selector"
                        max_selector_data = {
                            'type': 'literal',
                            'name': max_selector_name,
                            'display_name': f"{selector_width}'d{max_non_spanning}",
                            'bit_width': selector_width,
                            'value': max_non_spanning,
                            'expression': {'type': 'literal', 'value': max_non_spanning, 'width': selector_width}
                        }
                        max_selector_node = Node(max_selector_name, max_selector_data, is_uarch_state=False)
                        self.graph.add_node(max_selector_node)
                        nodes_added.append(max_selector_name)

                        inverted_selector_name = f"{instruction}_be_inverted_selector"
                        inverted_selector_data = {
                            'type': 'operation',
                            'name': inverted_selector_name,
                            'display_name': f"{max_selector_name} - {selector_node.id}",
                            'bit_width': selector_width,
                            'operator': '-',
                            'expression': {
                                'type': 'binary_op', 'operator': '-',
                                'left': {'type': 'identifier', 'name': max_selector_name},
                                'right': {'type': 'identifier', 'name': selector_node.id}
                            }
                        }
                        inverted_selector_node = Node(inverted_selector_name, inverted_selector_data, is_uarch_state=False)
                        self.graph.add_node(inverted_selector_node)
                        nodes_added.append(inverted_selector_name)

                        self.graph.add_edge(Edge(max_selector_node, inverted_selector_node, data={'type': 'left_operand'}))
                        self.graph.add_edge(Edge(selector_node, inverted_selector_node, data={'type': 'right_operand'}))
                    else:
                        # Aligned: XOR works since max_selector = 2^n - 1
                        max_selector_value = (1 << selector_width) - 1
                        max_selector_name = f"{instruction}_be_max_selector"
                        max_selector_data = {
                            'type': 'literal',
                            'name': max_selector_name,
                            'display_name': f"{selector_width}'d{max_selector_value}",
                            'bit_width': selector_width,
                            'value': max_selector_value,
                            'expression': {'type': 'literal', 'value': max_selector_value, 'width': selector_width}
                        }
                        max_selector_node = Node(max_selector_name, max_selector_data, is_uarch_state=False)
                        self.graph.add_node(max_selector_node)
                        nodes_added.append(max_selector_name)

                        inverted_selector_name = f"{instruction}_be_inverted_selector"
                        inverted_selector_data = {
                            'type': 'operation',
                            'name': inverted_selector_name,
                            'display_name': f"{max_selector_name} ^ {selector_node.id}",
                            'bit_width': selector_width,
                            'operator': '^',
                            'expression': {
                                'type': 'binary_op', 'operator': '^',
                                'left': {'type': 'identifier', 'name': max_selector_name},
                                'right': {'type': 'identifier', 'name': selector_node.id}
                            }
                        }
                        inverted_selector_node = Node(inverted_selector_name, inverted_selector_data, is_uarch_state=False)
                        self.graph.add_node(inverted_selector_node)
                        nodes_added.append(inverted_selector_name)

                        self.graph.add_edge(Edge(max_selector_node, inverted_selector_node, data={'type': 'left_operand'}))
                        self.graph.add_edge(Edge(selector_node, inverted_selector_node, data={'type': 'right_operand'}))

                    # Use inverted selector for shift calculation
                    shift_selector_node = inverted_selector_node
                    shift_selector_id = inverted_selector_name
                else:
                    # Little-endian: use selector directly
                    shift_selector_node = selector_node
                    shift_selector_id = selector_node.id

                data_shift_name = f"{instruction}_data_shift_amount"
                data_shift_data = {
                    'type': 'concatenation',
                    'name': data_shift_name,
                    'display_name': f"{{{shift_selector_id}, {data_shift_zeros_width}'b0}}",
                    'bit_width': selector_width + data_shift_zeros_width,
                    'expression': {'type': 'concatenation', 'parts': [
                        {'type': 'identifier', 'name': shift_selector_id},
                        {'type': 'literal', 'value': 0, 'width': data_shift_zeros_width}
                    ]}
                }
                data_shift_node = Node(data_shift_name, data_shift_data, is_uarch_state=False)
                self.graph.add_node(data_shift_node)
                nodes_added.append(data_shift_name)

                self.graph.add_edge(Edge(shift_selector_node, data_shift_node,
                                        data={'type': 'concatenation_input', 'position': 0}))
                self.graph.add_edge(Edge(data_shift_zeros_node, data_shift_node,
                                        data={'type': 'concatenation_input', 'position': 1}))

                # Zero-extend data source to port_width before shifting
                data_zext_name = f"{data_source.id}_zext"
                data_zext_node = self.graph.nodes.get(data_zext_name)
                if not data_zext_node:
                    pad_bits = port_width - data_width
                    data_zext_data = {
                        'type': 'zero_extend',
                        'name': data_zext_name,
                        'display_name': f"{{{pad_bits}'d0, {data_source.id}}}",
                        'bit_width': port_width,
                        'original_width': data_width,
                        'expression': {'type': 'zero_extend', 'operand': {'type': 'identifier', 'name': data_source.id}, 'width': port_width}
                    }
                    data_zext_node = Node(data_zext_name, data_zext_data, is_uarch_state=False)
                    self.graph.add_node(data_zext_node)
                    nodes_added.append(data_zext_name)
                    self.graph.add_edge(Edge(data_source, data_zext_node, data={'type': 'operand'}))

                # Create positioned data: zext_data << data_shift_amount
                positioned_data_data = {
                    'type': 'operation',
                    'name': positioned_data_name,
                    'display_name': f"{data_zext_name} << {data_shift_name}",
                    'bit_width': port_width,
                    'operator': '<<',
                    'expression': {
                        'type': 'binary_op', 'operator': '<<',
                        'left': {'type': 'identifier', 'name': data_zext_name},
                        'right': {'type': 'identifier', 'name': data_shift_name}
                    }
                }
                positioned_data_node = Node(positioned_data_name, positioned_data_data, is_uarch_state=False)
                self.graph.add_node(positioned_data_node)
                nodes_added.append(positioned_data_name)

                self.graph.add_edge(Edge(data_zext_node, positioned_data_node, data={'type': 'left_operand'}))
                self.graph.add_edge(Edge(data_shift_node, positioned_data_node, data={'type': 'right_operand'}))

                store_positioned_data[instruction] = positioned_data_name
                # For spanning-capable writers, also save raw data source name
                # so verilog_generator can use it for spanning write correction
                if can_span:
                    store_raw_data[instruction] = data_source.id
                print(f"      Created positioned data node: {positioned_data_name}")

                # Rewire the data mux to use positioned_data instead of original data source
                if data_mux_node:
                    # Find and remove the old mux_input edge from data_source
                    for edge in list(data_mux_node.incoming_edges):
                        if (edge.data.get('type') == 'mux_input' and
                            edge.data.get('source_instruction') == instruction and
                            edge.source == data_source):
                            # Copy input_index from old edge
                            old_input_index = edge.data.get('input_index')
                            # Remove old edge
                            edge.remove_from_nodes()
                            if edge.id in self.graph.edges:
                                del self.graph.edges[edge.id]
                            # Add new edge from positioned_data to mux
                            new_edge_data = {'type': 'mux_input',
                                            'source_instruction': instruction}
                            if old_input_index is not None:
                                new_edge_data['input_index'] = old_input_index
                            new_edge = Edge(positioned_data_node, data_mux_node,
                                          data=new_edge_data)
                            self.graph.add_edge(new_edge)
                            print(f"      Rewired mux input: {data_source.id} -> {positioned_data_name}")
                            break

            transformed_count += 1
            print(f"    Transformed {node.id} to standard shift operation")

        # Store mappings on write port node for verilog generator
        if write_port_node and (store_byte_enables or store_positioned_data):
            write_port_node.data['store_byte_enables'] = store_byte_enables
            write_port_node.data['store_positioned_data'] = store_positioned_data
            if store_raw_data:
                write_port_node.data['store_raw_data'] = store_raw_data
                print(f"    Stored raw data mappings for spanning writers: {list(store_raw_data.keys())[:5]}... ({len(store_raw_data)} total)")
            print(f"    Stored byte enable mappings on {write_port_node.id}: {list(store_byte_enables.keys())[:5]}...")

        return transformed_count

    def _insert_byte_selection_mux(
        self,
        read_node: Node,
        dest_node: Node,
        addr_node: Node,
        dest_width: int,
        port_width: int,
        orig_edge: 'Edge',
        endianness: str = 'little'
    ) -> Dict[str, List[str]]:
        """
        Insert a standard priority mux between a memory read and a sub-word destination.

        This transforms:
            read_node --assignment--> dest_node

        Into:
            read_node --> slice_0 --> mux --> dest_node
                     --> slice_1 -----^
                     --> slice_2 -----^
                     --> slice_3 -----^
            addr[1:0] --> cmp_0 ------^
                     --> cmp_1 ------^
                     --> cmp_2 ------^
                     --> cmp_3 ------^

        For byte access (8-bit): 4 slices, 4 comparisons (offset == 0/1/2/3)
        For halfword access (16-bit): 2 slices, 2 comparisons (offset[1] == 0/1)
        """
        mux_name = f"{dest_node.id}_byte_mux"
        print(f"    Creating byte selection mux: {mux_name}")

        nodes_added = []
        nodes_updated = []

        # Create byte offset extraction node if not already present
        # For 64-bit port, need 3 bits; for 32-bit port, need 2 bits
        import math
        offset_bits = int(math.log2(port_width // 8))  # 3 for 64-bit, 2 for 32-bit

        # Name the byte_offset after the memory read, not a specific address
        # The verilog generator will find the actual address by traversing from the memory read
        sanitized_read_id = read_node.id.replace('[', '_').replace(']', '')
        byte_offset_name = f"{sanitized_read_id}_byte_offset"

        byte_offset_node = self.graph.nodes.get(byte_offset_name)

        if not byte_offset_node:
            # Use the addr_node directly - this is either:
            # - A single EA node (e.g., lbz_ea) when there's only one address source
            # - An address mux node (e.g., dmem_ea_rd_addr_mux) when there are multiple sources
            addr_signal_name = addr_node.id

            byte_offset_data = {
                'type': 'bit_slice',
                'name': byte_offset_name,
                'display_name': f"{addr_signal_name}[{offset_bits-1}:0]",
                'bit_width': offset_bits,
                'expression': {
                    'type': 'bit_slice',
                    'range': [offset_bits-1, 0],
                    # Reference the address directly (mux output or single EA)
                    'operand': {'type': 'identifier', 'name': addr_signal_name}
                },
                # Store reference to memory read and address source for verilog generation
                'memory_read_node': read_node.id,
                'address_source': addr_node.id
            }
            byte_offset_node = Node(byte_offset_name, byte_offset_data, is_uarch_state=False)
            self.graph.add_node(byte_offset_node)
            nodes_added.append(byte_offset_name)

            # Connect addr -> byte_offset (edge is for graph structure, verilog uses memory read's address)
            offset_edge = Edge(addr_node, byte_offset_node, data={
                'type': 'operand',
                'label': 'bitslice_operand'
            })
            self.graph.add_edge(offset_edge)

        # Determine number of mux inputs based on access width and port width
        if dest_width == 8:
            if port_width == 32:
                # Byte access on 32-bit port: 4 positions
                num_inputs = 4
                slice_ranges = [(7, 0), (15, 8), (23, 16), (31, 24)]
            elif port_width == 64:
                # Byte access on 64-bit port: 8 positions
                num_inputs = 8
                slice_ranges = [(7, 0), (15, 8), (23, 16), (31, 24), (39, 32), (47, 40), (55, 48), (63, 56)]
            else:
                raise ValueError(f"Unsupported port width {port_width} for byte access")
            # Use full offset bits for selection
            selector_node = byte_offset_node
        elif dest_width == 16:
            if port_width == 32:
                # Halfword access on 32-bit port: 2 positions
                num_inputs = 2
                slice_ranges = [(15, 0), (31, 16)]
                selector_bit = 1
            elif port_width == 64:
                # Halfword access on 64-bit port: 4 positions
                num_inputs = 4
                slice_ranges = [(15, 0), (31, 16), (47, 32), (63, 48)]
                selector_bit = 2  # Need 2 bits for 4 positions
            else:
                raise ValueError(f"Unsupported port width {port_width} for halfword access")
            # Use bit 1 (or 1:2) of offset for selection
            selector_name = f"{sanitized_read_id}_halfword_select"
            selector_node = self.graph.nodes.get(selector_name)
            if not selector_node:
                # Use the addr_node directly (address mux or single EA)
                addr_signal_name = addr_node.id

                if port_width == 64:
                    # For 64-bit port, need addr[2:1] for 4 halfword positions
                    selector_data = {
                        'type': 'bit_slice',
                        'name': selector_name,
                        'display_name': f"{addr_signal_name}[2:1]",
                        'bit_width': 2,
                        'expression': {
                            'type': 'bit_slice',
                            'range': [2, 1],
                            'operand': {'type': 'identifier', 'name': addr_signal_name}
                        },
                        'memory_read_node': read_node.id,
                        'address_source': addr_node.id
                    }
                else:
                    selector_data = {
                        'type': 'bit_slice',
                        'name': selector_name,
                        'display_name': f"{addr_signal_name}[1]",
                        'bit_width': 1,
                        'expression': {
                            'type': 'bit_slice',
                            'range': [1, 1],
                            'operand': {'type': 'identifier', 'name': addr_signal_name}
                        },
                        'memory_read_node': read_node.id,
                        'address_source': addr_node.id
                    }
                selector_node = Node(selector_name, selector_data, is_uarch_state=False)
                self.graph.add_node(selector_node)
                nodes_added.append(selector_name)

                # Connect addr -> halfword_select
                sel_edge = Edge(addr_node, selector_node, data={
                    'type': 'operand',
                    'label': 'bitslice_operand'
                })
                self.graph.add_edge(sel_edge)
        elif dest_width == 32:
            if port_width == 64:
                # Word access on 64-bit port: 2 positions
                num_inputs = 2
                slice_ranges = [(31, 0), (63, 32)]
                # Use bit 2 of offset for selection (addr[2])
                selector_name = f"{sanitized_read_id}_word_select"
                selector_node = self.graph.nodes.get(selector_name)
                if not selector_node:
                    # Use the addr_node directly (address mux or single EA)
                    addr_signal_name = addr_node.id

                    selector_data = {
                        'type': 'bit_slice',
                        'name': selector_name,
                        'display_name': f"{addr_signal_name}[2]",
                        'bit_width': 1,
                        'expression': {
                            'type': 'bit_slice',
                            'range': [2, 2],
                            'operand': {'type': 'identifier', 'name': addr_signal_name}
                        },
                        'memory_read_node': read_node.id,
                        'address_source': addr_node.id
                    }
                    selector_node = Node(selector_name, selector_data, is_uarch_state=False)
                    self.graph.add_node(selector_node)
                    nodes_added.append(selector_name)

                    # Connect addr -> word_select
                    sel_edge = Edge(addr_node, selector_node, data={
                        'type': 'operand',
                        'label': 'bitslice_operand'
                    })
                    self.graph.add_edge(sel_edge)
            else:
                raise ValueError(f"32-bit word access requires 64-bit port (got {port_width})")
        else:
            raise ValueError(f"Unsupported sub-word access width: {dest_width}")

        # For big-endian, reverse slice_ranges so byte_offset=0 selects MSB
        # Little-endian: byte_offset=0 -> LSB (e.g., bits[7:0])
        # Big-endian: byte_offset=0 -> MSB (e.g., bits[63:56] for 64-bit)
        if endianness == 'big':
            slice_ranges = list(reversed(slice_ranges))

        # Create bit slice nodes for each byte/halfword position
        slice_nodes = []
        for i, (high, low) in enumerate(slice_ranges):
            # Include bit range in name to differentiate byte vs halfword slices
            slice_name = f"{read_node.id}_slice_{high}_{low}"
            slice_node = self.graph.nodes.get(slice_name)
            if not slice_node:
                slice_data = {
                    'type': 'bit_slice',
                    'name': slice_name,
                    'display_name': f"{read_node.id}[{high}:{low}]",
                    'bit_width': dest_width,
                    'expression': {
                        'type': 'bit_slice',
                        'range': [high, low],
                        'operand': {'type': 'identifier', 'name': read_node.id}
                    }
                }
                slice_node = Node(slice_name, slice_data, is_uarch_state=False)
                self.graph.add_node(slice_node)
                nodes_added.append(slice_name)

                # Connect read_node -> slice
                slice_edge = Edge(read_node, slice_node, data={
                    'type': 'operand',
                    'label': 'bitslice_operand'
                })
                self.graph.add_edge(slice_edge)
            slice_nodes.append(slice_node)

        # Create comparison nodes for selector conditions
        compare_nodes = []
        # Selector width based on number of inputs
        import math
        selector_width = max(1, int(math.ceil(math.log2(num_inputs)))) if num_inputs > 1 else 1
        for i in range(num_inputs):
            cmp_name = f"{mux_name}_sel_{i}"
            cmp_node = self.graph.nodes.get(cmp_name)
            if not cmp_node:
                cmp_data = {
                    'type': 'comparison',
                    'name': cmp_name,
                    'display_name': f"{selector_node.id} == {i}",
                    'bit_width': 1,
                    'operator': '==',
                    'compare_value': i,
                    'expression': {
                        'type': 'comparison',
                        'operator': '==',
                        'left': {'type': 'identifier', 'name': selector_node.id},
                        'right': {'type': 'literal', 'value': i, 'width': selector_width}
                    }
                }
                cmp_node = Node(cmp_name, cmp_data, is_uarch_state=False)
                self.graph.add_node(cmp_node)
                nodes_added.append(cmp_name)

                # Connect selector -> comparison
                cmp_edge = Edge(selector_node, cmp_node, data={
                    'type': 'operand',
                    'label': 'left_operand'
                })
                self.graph.add_edge(cmp_edge)
            compare_nodes.append(cmp_node)

        # Create priority mux using MuxBuilder
        builder = MuxBuilder(self.graph, mux_name, MuxType.PRIORITY)
        builder.create_or_get_mux(display_name=f"byte_mux({dest_node.id})")
        builder.mux_node.data['bit_width'] = dest_width

        # Add inputs with their select signals
        for i, (slice_node, cmp_node) in enumerate(zip(slice_nodes, compare_nodes)):
            builder.add_input(slice_node, cmp_node, input_index=i)

        nodes_added.append(mux_name)

        # Remove original edge from read_node to dest_node
        orig_edge.remove_from_nodes()
        if orig_edge.id in self.graph.edges:
            del self.graph.edges[orig_edge.id]

        # Connect mux -> dest_node
        builder.connect_output(dest_node, edge_type='assignment')

        nodes_updated.append(dest_node.id)

        return {
            'nodes_added': nodes_added,
            'nodes_updated': nodes_updated
        }

    def _insert_unaligned_word_merge(
        self,
        read_node: Node,
        dest_node: Node,
        addr_node: Node,
        spec: MemoryAccessTransformSpec,
        orig_edge: 'Edge',
        access_width: Optional[int] = None
    ) -> Dict[str, List[str]]:
        """
        Insert unaligned word merge for accesses that may span two memory words.

        This handles both:
        - Full-word accesses (access_width == port_width): e.g., 32-bit fetch from 32-bit memory
        - Sub-word accesses (access_width < port_width): e.g., 32-bit fetch from 64-bit memory

        For halfword-aligned accesses, spanning occurs when the access crosses a word boundary.
        The spanning condition depends on access_width and port_width:
        - 32-bit from 32-bit: spans when addr[1] == 1 (byte offset 2)
        - 32-bit from 64-bit: spans when addr[2:1] == 3 (byte offset 6)

        This creates:
        1. A second memory read port for next_word
        2. Bit slices for the spanning case
        3. Concatenation for spanning case
        4. Byte selection mux for aligned case (sub-word only)
        5. Mux to select between aligned and spanning results
        """
        port_width = spec.target_width
        if access_width is None:
            access_width = port_width  # Default to full-word

        mux_name = f"{dest_node.id}_unaligned_mux"
        print(f"    Creating unaligned word merge: {mux_name} ({access_width}-bit access from {port_width}-bit port)")

        nodes_added = []
        nodes_updated = []

        # Get sanitized read ID for naming
        sanitized_read_id = read_node.id.replace('[', '_').replace(']', '')
        addr_signal_name = addr_node.id

        # Calculate parametric values
        port_bytes = port_width // 8  # Bytes per memory word
        access_bytes = access_width // 8  # Bytes per access
        half_access_bits = access_width // 2  # Half the access width in bits

        # For spanning detection: check full byte offset
        # Spanning occurs when byte_offset + access_bytes > port_bytes
        # For 32-bit from 32-bit (4 from 4): spans when byte_offset >= 1 (offsets 1, 2, 3 span)
        # For 32-bit from 64-bit (4 from 8): spans when byte_offset >= 5 (offsets 5, 6, 7 span)
        port_offset_bits = int(math.log2(port_bytes))  # Number of bits for byte offset

        # Number of non-spanning byte offsets: port_bytes - access_bytes + 1
        # For 4-from-4: 4 - 4 + 1 = 1 (only offset 0)
        # For 4-from-8: 8 - 4 + 1 = 5 (offsets 0, 1, 2, 3, 4)
        num_non_spanning_bytes = port_bytes - access_bytes + 1
        first_spanning_byte = num_non_spanning_bytes  # First byte offset that spans

        # For sub-word accesses (access_width < port_width), the original memory was
        # access_width-wide and always returned access-aligned data. E.g., a 16-bit
        # memory read at byte_addr always returned the 16-bit word at (byte_addr & ~1),
        # because the index operation (byte_addr >> 1) drops the LSB.
        # The wider memory's aligned_mux must preserve this: select the correct
        # access-aligned sub-word (step by access_bytes), not byte-shifted windows.
        # This prevents byte extraction bugs: addr[0] selects within a word-aligned
        # 16-bit value, not within a byte-shifted 16-bit window.
        sub_word_access_aligned = (access_width < port_width)

        # 1. Create next-word address node: addr + port_bytes
        next_addr_name = f"{sanitized_read_id}_next_addr"
        next_addr_node = self.graph.nodes.get(next_addr_name)
        if not next_addr_node:
            next_addr_data = {
                'type': 'binary_op',
                'name': next_addr_name,
                'display_name': f"{addr_signal_name} + {port_bytes}",
                'bit_width': addr_node.data.get('bit_width', 64),
                'operator': '+',
                'expression': {
                    'type': 'binary_op',
                    'operator': '+',
                    'left': {'type': 'identifier', 'name': addr_signal_name},
                    'right': {'type': 'literal', 'value': port_bytes, 'width': 32}
                }
            }
            next_addr_node = Node(next_addr_name, next_addr_data, is_uarch_state=False)
            self.graph.add_node(next_addr_node)
            nodes_added.append(next_addr_name)

            # Connect addr -> next_addr
            addr_edge = Edge(addr_node, next_addr_node, data={
                'type': 'operand',
                'label': 'left_operand'
            })
            self.graph.add_edge(addr_edge)

        # 2. Create second memory read port for next word
        # Use port-specific name so each source gets its own next-word port
        # (instruction fetch vs data load need different addresses)
        next_read_name = f"{sanitized_read_id}_next_rd"
        next_read_node = self.graph.nodes.get(next_read_name)
        if not next_read_node:
            next_read_data = {
                'type': 'array_access',
                'name': next_read_name,
                'display_name': f"{spec.memory}[{next_addr_name}]",
                'access_mode': 'read',
                'memory': spec.memory,
                'bit_width': port_width,
                'is_next_word_port': True,  # Mark as next-word read port
                'expression': {
                    'type': 'array_access',
                    'array': {'type': 'identifier', 'name': spec.memory},
                    'index': {'type': 'identifier', 'name': next_addr_name}
                }
            }
            next_read_node = Node(next_read_name, next_read_data, is_uarch_state=False)
            self.graph.add_node(next_read_node)
            nodes_added.append(next_read_name)

            # Connect memory -> next_read (array_base)
            memory_node = self.graph.nodes.get(spec.memory)
            if memory_node:
                base_edge = Edge(memory_node, next_read_node, data={
                    'type': 'array_base'
                })
                self.graph.add_edge(base_edge)

            # Connect next_addr -> next_read (array_index)
            index_edge = Edge(next_addr_node, next_read_node, data={
                'type': 'array_index'
            })
            self.graph.add_edge(index_edge)

        # 3. Create bit slices for the spanning case
        # Spanning access: some bytes from current DW, rest from next DW.
        # The slices take half_access_bits from each word as an approximation.
        #
        # For little-endian: upper bits of current word + lower bits of next word
        #   Current: [port_width-1 : port_width-half_access_bits]
        #   Next:    [half_access_bits-1 : 0]
        #   Concat:  {next_lower, current_upper} (next is MSB in result)
        #
        # For big-endian: lower bits of current word (trailing bytes) +
        #   upper bits of next word (leading bytes)
        #   Current: [half_access_bits-1 : 0]
        #   Next:    [port_width-1 : port_width-half_access_bits]
        #   Concat:  {current_lower, next_upper} (current trailing is MSB in result)
        if spec.endianness == 'big':
            current_upper_hi = half_access_bits - 1
            current_upper_lo = 0
            next_lower_hi = port_width - 1
            next_lower_lo = port_width - half_access_bits
        else:
            current_upper_hi = port_width - 1
            current_upper_lo = port_width - half_access_bits
            next_lower_hi = half_access_bits - 1
            next_lower_lo = 0

        # Use access-width-specific names so 32-bit and 64-bit merge hardware don't collide
        aw_suffix = f"_{access_width}b"

        current_upper_name = f"{sanitized_read_id}_upper_half{aw_suffix}"
        current_upper_node = self.graph.nodes.get(current_upper_name)
        if not current_upper_node:
            current_upper_data = {
                'type': 'bit_slice',
                'name': current_upper_name,
                'display_name': f"{read_node.id}[{current_upper_hi}:{current_upper_lo}]",
                'bit_width': half_access_bits,
                'expression': {
                    'type': 'bit_slice',
                    'range': [current_upper_hi, current_upper_lo],
                    'operand': {'type': 'identifier', 'name': read_node.id}
                }
            }
            current_upper_node = Node(current_upper_name, current_upper_data, is_uarch_state=False)
            self.graph.add_node(current_upper_node)
            nodes_added.append(current_upper_name)

            slice_edge = Edge(read_node, current_upper_node, data={
                'type': 'operand',
                'label': 'bitslice_operand'
            })
            self.graph.add_edge(slice_edge)

        next_lower_name = f"{next_read_name}_lower_half{aw_suffix}"
        next_lower_node = self.graph.nodes.get(next_lower_name)
        if not next_lower_node:
            next_lower_data = {
                'type': 'bit_slice',
                'name': next_lower_name,
                'display_name': f"{next_read_node.id}[{next_lower_hi}:{next_lower_lo}]",
                'bit_width': half_access_bits,
                'expression': {
                    'type': 'bit_slice',
                    'range': [next_lower_hi, next_lower_lo],
                    'operand': {'type': 'identifier', 'name': next_read_node.id}
                }
            }
            next_lower_node = Node(next_lower_name, next_lower_data, is_uarch_state=False)
            self.graph.add_node(next_lower_node)
            nodes_added.append(next_lower_name)

            slice_edge = Edge(next_read_node, next_lower_node, data={
                'type': 'operand',
                'label': 'bitslice_operand'
            })
            self.graph.add_edge(slice_edge)

        # 4. Create concatenation node for spanning case
        # Little-endian: {next_lower, current_upper} — next word provides MSB
        # Big-endian: {current_lower, next_upper} — current trailing bytes are MSB
        concat_name = f"{sanitized_read_id}_unaligned_concat{aw_suffix}"
        concat_node = self.graph.nodes.get(concat_name)
        if not concat_node:
            if spec.endianness == 'big':
                # Big-endian: current DW trailing bytes (low bits) are MSB of result
                msb_name = current_upper_name  # "upper" name but actually low bits for big-endian
                lsb_name = next_lower_name     # "lower" name but actually high bits of next DW
            else:
                msb_name = next_lower_name
                lsb_name = current_upper_name
            concat_data = {
                'type': 'concatenation',
                'name': concat_name,
                'display_name': f"{{{msb_name}, {lsb_name}}}",
                'bit_width': access_width,  # Output is access_width, not port_width
                'expression': {
                    'type': 'concatenation',
                    'expressions': [
                        {'type': 'identifier', 'name': msb_name},  # MSB part
                        {'type': 'identifier', 'name': lsb_name}   # LSB part
                    ]
                }
            }
            concat_node = Node(concat_name, concat_data, is_uarch_state=False)
            self.graph.add_node(concat_node)
            nodes_added.append(concat_name)

            # Connect parts to concatenation
            if spec.endianness == 'big':
                msb_node = current_upper_node
                lsb_node = next_lower_node
            else:
                msb_node = next_lower_node
                lsb_node = current_upper_node
            concat_edge1 = Edge(msb_node, concat_node, data={
                'type': 'concatenation_input',
                'position': 0  # MSB position
            })
            concat_edge2 = Edge(lsb_node, concat_node, data={
                'type': 'concatenation_input',
                'position': 1  # LSB position
            })
            self.graph.add_edge(concat_edge1)
            self.graph.add_edge(concat_edge2)

        # 5. Create alignment check: spans when addr[port_offset_bits-1:0] >= first_spanning_byte
        # For 32-from-32 (4 from 4): spans when byte_offset >= 1
        # For 32-from-64 (4 from 8): spans when byte_offset >= 5
        align_check_name = f"{sanitized_read_id}_spans_boundary{aw_suffix}"
        align_check_node = self.graph.nodes.get(align_check_name)
        if not align_check_node:
            align_check_data = {
                'type': 'comparison',
                'name': align_check_name,
                'display_name': f"{addr_signal_name}[{port_offset_bits-1}:0] >= {first_spanning_byte}",
                'bit_width': 1,
                'operation': '>=',  # Use 'operation' for verilog_generator compatibility
                'compare_value': first_spanning_byte,
                'is_unaligned_check': True,
                'address_source': addr_node.id,
                'expression': {
                    'type': 'comparison',
                    'operator': '>=',
                    'left': {
                        'type': 'bit_slice',
                        'range': [port_offset_bits - 1, 0],
                        'operand': {'type': 'identifier', 'name': addr_signal_name}
                    },
                    'right': {'type': 'literal', 'value': first_spanning_byte, 'width': port_offset_bits}
                }
            }
            align_check_node = Node(align_check_name, align_check_data, is_uarch_state=False)
            self.graph.add_node(align_check_node)
            nodes_added.append(align_check_name)

            # Connect addr -> alignment check
            check_edge = Edge(addr_node, align_check_node, data={
                'type': 'operand',
                'label': 'left_operand'
            })
            self.graph.add_edge(check_edge)

        # Also create the aligned (not spanning) case check
        align_ok_name = f"{sanitized_read_id}_aligned{aw_suffix}"
        align_ok_node = self.graph.nodes.get(align_ok_name)
        if not align_ok_node:
            align_ok_data = {
                'type': 'comparison',
                'name': align_ok_name,
                'display_name': f"{addr_signal_name}[{port_offset_bits-1}:0] < {first_spanning_byte}",
                'bit_width': 1,
                'operation': '<',  # Use 'operation' for verilog_generator compatibility
                'compare_value': first_spanning_byte,
                'is_aligned_check': True,
                'address_source': addr_node.id,
                'expression': {
                    'type': 'comparison',
                    'operator': '<',
                    'left': {
                        'type': 'bit_slice',
                        'range': [port_offset_bits - 1, 0],
                        'operand': {'type': 'identifier', 'name': addr_signal_name}
                    },
                    'right': {'type': 'literal', 'value': first_spanning_byte, 'width': port_offset_bits}
                }
            }
            align_ok_node = Node(align_ok_name, align_ok_data, is_uarch_state=False)
            self.graph.add_node(align_ok_node)
            nodes_added.append(align_ok_name)

            check_edge = Edge(addr_node, align_ok_node, data={
                'type': 'operand',
                'label': 'left_operand'
            })
            self.graph.add_edge(check_edge)

        # 6. For sub-word accesses, create byte selection mux for aligned case
        # For full-word accesses, use the read directly
        if access_width < port_width:
            # Sub-word: need to select the correct bytes from current word using a mux
            # For truly unaligned access, we need to handle all non-spanning byte offsets
            # For 32-bit from 64-bit: byte offsets 0-4 are non-spanning; 5-7 span
            # - offset 0: bits [31:0]
            # - offset 1: bits [39:8]
            # - offset 2: bits [47:16]
            # - offset 3: bits [55:24]
            # - offset 4: bits [63:32]
            # - offset 5-7: spanning (handled by concat)

            # Step by access_bytes to match original port alignment
            access_offset_bits = int(math.log2(access_bytes)) if access_bytes > 1 else 0
            aligned_byte_offsets = list(range(0, port_bytes, access_bytes))

            print(f"      Sub-word aligned case: {len(aligned_byte_offsets)} access-aligned offsets (step={access_bytes})")

            # Create slice and condition nodes for each access-aligned byte offset
            aligned_slice_nodes = []
            aligned_cond_nodes = []

            for byte_offset in aligned_byte_offsets:
                # Calculate bit slice range for this byte offset
                if spec.endianness == 'big':
                    # Big-endian: byte 0 is at MSB (high bits)
                    # byte offset 0 → [port_width-1 : port_width-access_width]
                    # byte offset N → [port_width-1-N*8 : port_width-N*8-access_width]
                    slice_hi = port_width - 1 - byte_offset * 8
                    slice_lo = slice_hi - access_width + 1
                else:
                    # Little-endian: byte 0 is at LSB (low bits)
                    slice_lo = byte_offset * 8
                    slice_hi = slice_lo + access_width - 1

                # Create slice node for this offset
                slice_name = f"{sanitized_read_id}_aligned{aw_suffix}_{byte_offset}"
                slice_node = self.graph.nodes.get(slice_name)
                if not slice_node:
                    slice_data = {
                        'type': 'bit_slice',
                        'name': slice_name,
                        'display_name': f"{read_node.id}[{slice_hi}:{slice_lo}]",
                        'bit_width': access_width,
                        'expression': {
                            'type': 'bit_slice',
                            'range': [slice_hi, slice_lo],
                            'operand': {'type': 'identifier', 'name': read_node.id}
                        }
                    }
                    slice_node = Node(slice_name, slice_data, is_uarch_state=False)
                    self.graph.add_node(slice_node)
                    nodes_added.append(slice_name)

                    slice_edge = Edge(read_node, slice_node, data={
                        'type': 'operand',
                        'label': 'bitslice_operand'
                    })
                    self.graph.add_edge(slice_edge)

                aligned_slice_nodes.append(slice_node)

                # Create condition using access-aligned address bits
                # For 16-bit from 32-bit: use addr[1:1] == slot (not addr[1:0] == byte_offset)
                # This groups adjacent bytes into the same access-aligned slot
                slot = byte_offset // access_bytes
                selector_bits_hi = port_offset_bits - 1
                selector_bits_lo = access_offset_bits
                selector_width = max(1, selector_bits_hi - selector_bits_lo + 1)

                cond_name = f"{sanitized_read_id}_sel{aw_suffix}_{byte_offset}"
                cond_node = self.graph.nodes.get(cond_name)
                if not cond_node:
                    cond_data = {
                        'type': 'comparison',
                        'name': cond_name,
                        'display_name': f"{addr_signal_name}[{selector_bits_hi}:{selector_bits_lo}] == {slot}",
                        'bit_width': 1,
                        'operation': '==',
                        'expression': {
                            'type': 'comparison',
                            'operator': '==',
                            'left': {
                                'type': 'bit_slice',
                                'range': [selector_bits_hi, selector_bits_lo],
                                'operand': {'type': 'identifier', 'name': addr_signal_name}
                            },
                            'right': {'type': 'literal', 'value': slot, 'width': selector_width}
                        }
                    }
                    cond_node = Node(cond_name, cond_data, is_uarch_state=False)
                    self.graph.add_node(cond_node)
                    nodes_added.append(cond_name)

                    cond_edge = Edge(addr_node, cond_node, data={
                        'type': 'operand',
                        'label': 'left_operand'
                    })
                    self.graph.add_edge(cond_edge)

                aligned_cond_nodes.append(cond_node)

            # Create byte selection mux for aligned case with all non-spanning options
            aligned_mux_name = f"{sanitized_read_id}_aligned_mux{aw_suffix}"
            aligned_builder = MuxBuilder(self.graph, aligned_mux_name, MuxType.PRIORITY)
            aligned_builder.create_or_get_mux(display_name=f"aligned_select({dest_node.id})")
            aligned_builder.mux_node.data['bit_width'] = access_width

            # Add inputs for each non-spanning byte offset
            for idx, (slice_node, cond_node) in enumerate(zip(aligned_slice_nodes, aligned_cond_nodes)):
                aligned_builder.add_input(slice_node, cond_node, input_index=idx)
            nodes_added.append(aligned_mux_name)

            aligned_input_node = aligned_builder.mux_node
            print(f"      Created {len(aligned_byte_offsets)}-way byte selection mux for aligned case: {aligned_mux_name}")
        else:
            # Full-word (access_width == port_width): Create per-offset mux covering all byte offsets.
            # Each non-zero offset needs a different {current_trailing, next_leading} concatenation.
            # Offset 0: use current DW directly
            # Offset N (1-7): {current[pw-1-N*8:0], next[pw-1:pw-N*8]} for big-endian
            #                  {next[N*8-1:0], current[pw-1:N*8]} for little-endian
            print(f"      Full-word spanning case: creating {port_bytes}-way mux for all byte offsets")

            fullword_mux_name = f"{sanitized_read_id}_fullword_mux{aw_suffix}"
            fw_builder = MuxBuilder(self.graph, fullword_mux_name, MuxType.PRIORITY)
            fw_builder.create_or_get_mux(display_name=f"fullword_unaligned({dest_node.id})")
            fw_builder.mux_node.data['bit_width'] = access_width

            for byte_offset in range(port_bytes):
                # Create condition: addr[port_offset_bits-1:0] == byte_offset
                fw_cond_name = f"{sanitized_read_id}_fwsel{aw_suffix}_{byte_offset}"
                fw_cond_node = self.graph.nodes.get(fw_cond_name)
                if not fw_cond_node:
                    fw_cond_data = {
                        'type': 'comparison',
                        'name': fw_cond_name,
                        'display_name': f"{addr_signal_name}[{port_offset_bits-1}:0] == {byte_offset}",
                        'bit_width': 1,
                        'operation': '==',
                        'expression': {
                            'type': 'comparison',
                            'operator': '==',
                            'left': {
                                'type': 'bit_slice',
                                'range': [port_offset_bits - 1, 0],
                                'operand': {'type': 'identifier', 'name': addr_signal_name}
                            },
                            'right': {'type': 'literal', 'value': byte_offset, 'width': port_offset_bits}
                        }
                    }
                    fw_cond_node = Node(fw_cond_name, fw_cond_data, is_uarch_state=False)
                    self.graph.add_node(fw_cond_node)
                    nodes_added.append(fw_cond_name)
                    cond_edge = Edge(addr_node, fw_cond_node, data={
                        'type': 'operand', 'label': 'left_operand'
                    })
                    self.graph.add_edge(cond_edge)

                if byte_offset == 0:
                    # Offset 0: aligned, use current DW directly
                    fw_builder.add_input(read_node, fw_cond_node, input_index=byte_offset)
                else:
                    # Create {current_trailing, next_leading} concatenation for this offset
                    shift_bits = byte_offset * 8
                    if spec.endianness == 'big':
                        # Big-endian: current trailing bytes are MSB of result
                        cur_hi = port_width - 1 - shift_bits
                        cur_lo = 0
                        cur_width = cur_hi - cur_lo + 1  # port_width - shift_bits
                        nxt_hi = port_width - 1
                        nxt_lo = port_width - shift_bits
                        nxt_width = nxt_hi - nxt_lo + 1  # shift_bits
                    else:
                        # Little-endian: next leading bytes are MSB of result
                        cur_hi = port_width - 1
                        cur_lo = shift_bits
                        cur_width = cur_hi - cur_lo + 1  # port_width - shift_bits
                        nxt_hi = shift_bits - 1
                        nxt_lo = 0
                        nxt_width = nxt_hi - nxt_lo + 1  # shift_bits

                    # Create current DW trailing slice
                    fw_cur_name = f"{sanitized_read_id}_fwcur{aw_suffix}_{byte_offset}"
                    fw_cur_node = self.graph.nodes.get(fw_cur_name)
                    if not fw_cur_node:
                        fw_cur_data = {
                            'type': 'bit_slice',
                            'name': fw_cur_name,
                            'display_name': f"{read_node.id}[{cur_hi}:{cur_lo}]",
                            'bit_width': cur_width,
                            'expression': {
                                'type': 'bit_slice',
                                'range': [cur_hi, cur_lo],
                                'operand': {'type': 'identifier', 'name': read_node.id}
                            }
                        }
                        fw_cur_node = Node(fw_cur_name, fw_cur_data, is_uarch_state=False)
                        self.graph.add_node(fw_cur_node)
                        nodes_added.append(fw_cur_name)
                        slice_edge = Edge(read_node, fw_cur_node, data={
                            'type': 'operand', 'label': 'bitslice_operand'
                        })
                        self.graph.add_edge(slice_edge)

                    # Create next DW leading slice
                    fw_nxt_name = f"{next_read_name}_fwnxt{aw_suffix}_{byte_offset}"
                    fw_nxt_node = self.graph.nodes.get(fw_nxt_name)
                    if not fw_nxt_node:
                        fw_nxt_data = {
                            'type': 'bit_slice',
                            'name': fw_nxt_name,
                            'display_name': f"{next_read_node.id}[{nxt_hi}:{nxt_lo}]",
                            'bit_width': nxt_width,
                            'expression': {
                                'type': 'bit_slice',
                                'range': [nxt_hi, nxt_lo],
                                'operand': {'type': 'identifier', 'name': next_read_node.id}
                            }
                        }
                        fw_nxt_node = Node(fw_nxt_name, fw_nxt_data, is_uarch_state=False)
                        self.graph.add_node(fw_nxt_node)
                        nodes_added.append(fw_nxt_name)
                        slice_edge = Edge(next_read_node, fw_nxt_node, data={
                            'type': 'operand', 'label': 'bitslice_operand'
                        })
                        self.graph.add_edge(slice_edge)

                    # Create concatenation: {current_trailing, next_leading} for big-endian
                    #                       {next_leading, current_trailing} for little-endian
                    fw_cat_name = f"{sanitized_read_id}_fwcat{aw_suffix}_{byte_offset}"
                    fw_cat_node = self.graph.nodes.get(fw_cat_name)
                    if not fw_cat_node:
                        if spec.endianness == 'big':
                            msb_n, lsb_n = fw_cur_name, fw_nxt_name
                            msb_node, lsb_node = fw_cur_node, fw_nxt_node
                        else:
                            msb_n, lsb_n = fw_nxt_name, fw_cur_name
                            msb_node, lsb_node = fw_nxt_node, fw_cur_node
                        fw_cat_data = {
                            'type': 'concatenation',
                            'name': fw_cat_name,
                            'display_name': f"{{{msb_n}, {lsb_n}}}",
                            'bit_width': access_width,
                            'expression': {
                                'type': 'concatenation',
                                'expressions': [
                                    {'type': 'identifier', 'name': msb_n},
                                    {'type': 'identifier', 'name': lsb_n}
                                ]
                            }
                        }
                        fw_cat_node = Node(fw_cat_name, fw_cat_data, is_uarch_state=False)
                        self.graph.add_node(fw_cat_node)
                        nodes_added.append(fw_cat_name)
                        cat_e1 = Edge(msb_node, fw_cat_node, data={
                            'type': 'concatenation_input', 'position': 0
                        })
                        cat_e2 = Edge(lsb_node, fw_cat_node, data={
                            'type': 'concatenation_input', 'position': 1
                        })
                        self.graph.add_edge(cat_e1)
                        self.graph.add_edge(cat_e2)

                    fw_builder.add_input(fw_cat_node, fw_cond_node, input_index=byte_offset)

            nodes_added.append(fullword_mux_name)
            aligned_input_node = fw_builder.mux_node
            print(f"      Created {port_bytes}-way fullword unaligned mux: {fullword_mux_name}")

        # 7. Create final priority mux: select spanning if boundary crossed, else aligned
        if access_width == port_width:
            # Full-word: the fullword mux already handles all offsets.
            # Mark it as the unaligned mux and connect directly to dest_node.
            fw_mux = aligned_input_node  # This is the fullword mux node
            fw_mux.data['is_unaligned_mux'] = True
            fw_mux.data['access_width'] = access_width
            fw_mux.data['port_width'] = port_width
            final_mux_node = fw_mux
        elif sub_word_access_aligned:
            # Sub-word with access-aligned selectors: spanning never occurs because
            # access-aligned sub-word reads always fit within the port word.
            # Use the aligned_mux directly as the final result.
            aligned_input_node.data['is_unaligned_mux'] = True
            aligned_input_node.data['access_width'] = access_width
            aligned_input_node.data['port_width'] = port_width
            final_mux_node = aligned_input_node
            print(f"      Sub-word access-aligned: using aligned_mux directly (no spanning)")
        else:
            # Sub-word: use aligned/spanning two-way mux
            # The spanning case needs per-offset concatenations because each spanning
            # offset has a different current/next byte split (e.g., for 32-bit in 64-bit:
            # offset 5 needs 3+1 bytes, offset 6 needs 2+2, offset 7 needs 1+3).
            num_spanning_offsets = port_bytes - first_spanning_byte

            if num_spanning_offsets <= 1:
                # Only one spanning offset - the old fixed concat is correct
                spanning_node = concat_node
            else:
                # Multiple spanning offsets - create per-offset spanning mux
                spanning_mux_name = f"{sanitized_read_id}_spanning_mux{aw_suffix}"
                span_builder = MuxBuilder(self.graph, spanning_mux_name, MuxType.PRIORITY)
                span_builder.create_or_get_mux(display_name=f"spanning_select({dest_node.id})")
                span_builder.mux_node.data['bit_width'] = access_width

                print(f"      Creating {num_spanning_offsets}-way spanning mux for offsets {first_spanning_byte}-{port_bytes-1}")

                for idx, byte_offset in enumerate(range(first_spanning_byte, port_bytes)):
                    # Calculate per-offset bit slices
                    cur_bytes = port_bytes - byte_offset  # bytes remaining in current DW
                    nxt_bytes = access_width // 8 - cur_bytes  # bytes needed from next DW
                    cur_bits = cur_bytes * 8
                    nxt_bits = nxt_bytes * 8

                    if spec.endianness == 'big':
                        cur_hi = cur_bits - 1
                        cur_lo = 0
                        nxt_hi = port_width - 1
                        nxt_lo = port_width - nxt_bits
                    else:
                        cur_hi = port_width - 1
                        cur_lo = port_width - cur_bits
                        nxt_hi = nxt_bits - 1
                        nxt_lo = 0

                    # Create condition: addr[offset_bits-1:0] == byte_offset
                    sp_cond_name = f"{sanitized_read_id}_spsel{aw_suffix}_{byte_offset}"
                    sp_cond_node = self.graph.nodes.get(sp_cond_name)
                    if not sp_cond_node:
                        sp_cond_data = {
                            'type': 'comparison',
                            'name': sp_cond_name,
                            'display_name': f"{addr_signal_name}[{port_offset_bits-1}:0] == {byte_offset}",
                            'bit_width': 1,
                            'operation': '==',
                            'expression': {
                                'type': 'comparison',
                                'operator': '==',
                                'left': {
                                    'type': 'bit_slice',
                                    'range': [port_offset_bits - 1, 0],
                                    'operand': {'type': 'identifier', 'name': addr_signal_name}
                                },
                                'right': {'type': 'literal', 'value': byte_offset, 'width': port_offset_bits}
                            }
                        }
                        sp_cond_node = Node(sp_cond_name, sp_cond_data, is_uarch_state=False)
                        self.graph.add_node(sp_cond_node)
                        nodes_added.append(sp_cond_name)
                        cond_edge = Edge(addr_node, sp_cond_node, data={
                            'type': 'operand', 'label': 'left_operand'
                        })
                        self.graph.add_edge(cond_edge)

                    # Create current DW trailing slice
                    sp_cur_name = f"{sanitized_read_id}_spcur{aw_suffix}_{byte_offset}"
                    sp_cur_node = self.graph.nodes.get(sp_cur_name)
                    if not sp_cur_node:
                        sp_cur_data = {
                            'type': 'bit_slice',
                            'name': sp_cur_name,
                            'display_name': f"{read_node.id}[{cur_hi}:{cur_lo}]",
                            'bit_width': cur_bits,
                            'expression': {
                                'type': 'bit_slice',
                                'range': [cur_hi, cur_lo],
                                'operand': {'type': 'identifier', 'name': read_node.id}
                            }
                        }
                        sp_cur_node = Node(sp_cur_name, sp_cur_data, is_uarch_state=False)
                        self.graph.add_node(sp_cur_node)
                        nodes_added.append(sp_cur_name)
                        slice_edge = Edge(read_node, sp_cur_node, data={
                            'type': 'operand', 'label': 'bitslice_operand'
                        })
                        self.graph.add_edge(slice_edge)

                    # Create next DW leading slice
                    sp_nxt_name = f"{next_read_name}_spnxt{aw_suffix}_{byte_offset}"
                    sp_nxt_node = self.graph.nodes.get(sp_nxt_name)
                    if not sp_nxt_node:
                        sp_nxt_data = {
                            'type': 'bit_slice',
                            'name': sp_nxt_name,
                            'display_name': f"{next_read_node.id}[{nxt_hi}:{nxt_lo}]",
                            'bit_width': nxt_bits,
                            'expression': {
                                'type': 'bit_slice',
                                'range': [nxt_hi, nxt_lo],
                                'operand': {'type': 'identifier', 'name': next_read_node.id}
                            }
                        }
                        sp_nxt_node = Node(sp_nxt_name, sp_nxt_data, is_uarch_state=False)
                        self.graph.add_node(sp_nxt_node)
                        nodes_added.append(sp_nxt_name)
                        slice_edge = Edge(next_read_node, sp_nxt_node, data={
                            'type': 'operand', 'label': 'bitslice_operand'
                        })
                        self.graph.add_edge(slice_edge)

                    # Create concatenation: {current_trailing, next_leading} for big-endian
                    sp_cat_name = f"{sanitized_read_id}_spcat{aw_suffix}_{byte_offset}"
                    sp_cat_node = self.graph.nodes.get(sp_cat_name)
                    if not sp_cat_node:
                        if spec.endianness == 'big':
                            msb_n, lsb_n = sp_cur_name, sp_nxt_name
                            msb_node, lsb_node = sp_cur_node, sp_nxt_node
                        else:
                            msb_n, lsb_n = sp_nxt_name, sp_cur_name
                            msb_node, lsb_node = sp_nxt_node, sp_cur_node
                        sp_cat_data = {
                            'type': 'concatenation',
                            'name': sp_cat_name,
                            'display_name': f"{{{msb_n}, {lsb_n}}}",
                            'bit_width': access_width,
                            'expression': {
                                'type': 'concatenation',
                                'expressions': [
                                    {'type': 'identifier', 'name': msb_n},
                                    {'type': 'identifier', 'name': lsb_n}
                                ]
                            }
                        }
                        sp_cat_node = Node(sp_cat_name, sp_cat_data, is_uarch_state=False)
                        self.graph.add_node(sp_cat_node)
                        nodes_added.append(sp_cat_name)
                        cat_e1 = Edge(msb_node, sp_cat_node, data={
                            'type': 'concatenation_input', 'position': 0
                        })
                        cat_e2 = Edge(lsb_node, sp_cat_node, data={
                            'type': 'concatenation_input', 'position': 1
                        })
                        self.graph.add_edge(cat_e1)
                        self.graph.add_edge(cat_e2)

                    span_builder.add_input(sp_cat_node, sp_cond_node, input_index=idx)

                nodes_added.append(spanning_mux_name)
                spanning_node = span_builder.mux_node
                print(f"      Created {num_spanning_offsets}-way spanning mux: {spanning_mux_name}")

            builder = MuxBuilder(self.graph, mux_name, MuxType.PRIORITY)
            builder.create_or_get_mux(display_name=f"unaligned_mux({dest_node.id})")
            builder.mux_node.data['bit_width'] = access_width
            builder.mux_node.data['is_unaligned_mux'] = True
            builder.mux_node.data['access_width'] = access_width
            builder.mux_node.data['port_width'] = port_width

            # Input 0: aligned case - use byte-selected or full word
            builder.add_input(aligned_input_node, align_ok_node, input_index=0)

            # Input 1: spanning case - use per-offset spanning mux
            builder.add_input(spanning_node, align_check_node, input_index=1)

            nodes_added.append(mux_name)
            final_mux_node = builder.mux_node

        # Remove original edge from read_node to dest_node
        orig_edge.remove_from_nodes()
        if orig_edge.id in self.graph.edges:
            del self.graph.edges[orig_edge.id]

        # Connect final mux -> dest_node
        output_edge = Edge(final_mux_node, dest_node, data={'type': 'assignment'})
        self.graph.add_edge(output_edge)

        # Fix the dest_node bit_slice range to extract from the mux's low bits.
        #
        # The original bit_slice (e.g., [31:16]) was an extraction range for the
        # full-width dmem read. But the unaligned mux output has the data in its
        # LOW bits [access_width-1:0], not at the original position. The Verilog
        # generator uses bitslice metadata for BOTH:
        #   1. Extraction: assign dest = source[high:low]  (line ~6381)
        #   2. Width inference: source must be >= high+1 bits wide (line ~362)
        #
        # If we leave bitslice as (31,16) for a 16-bit access:
        #   - Width inference inflates the 16-bit mux to 32 bits
        #   - 16-bit data zero-extends to 32 bits in the mux register
        #   - [31:16] extracts ZEROS, losing the high-word data
        #
        # Destination positioning is handled by wire NAME patterns (_31_16, _15_0)
        # in _generate_bit_slice_concatenations(), not by bitslice metadata.
        # So changing bitslice to (15,0) fixes extraction without breaking positioning.
        if dest_node.data.get('type') == 'bit_slice':
            if 'expression' in dest_node.data:
                expr = dest_node.data['expression']
                if expr.get('type') == 'bit_slice' and 'range' in expr:
                    old_range = expr['range']
                    range_width = old_range[0] - old_range[1] + 1
                    new_range = [access_width - 1, 0]
                    if range_width == access_width and list(old_range) != new_range:
                        print(f"      Fixed bit_slice range: [{old_range[0]}:{old_range[1]}] -> [{new_range[0]}:{new_range[1]}]")
                        expr['range'] = new_range
            if 'bitslice' in dest_node.data:
                old_bs = dest_node.data['bitslice']
                bs_width = old_bs[0] - old_bs[1] + 1
                new_bs = (access_width - 1, 0)
                if bs_width == access_width and old_bs != new_bs:
                    print(f"      Fixed bitslice: ({old_bs[0]},{old_bs[1]}) -> ({new_bs[0]},{new_bs[1]})")
                    dest_node.data['bitslice'] = new_bs

        nodes_updated.append(dest_node.id)

        print(f"      Created next-word read port: {next_read_name}")
        print(f"      Created unaligned mux with concat: {mux_name}")

        return {
            'nodes_added': nodes_added,
            'nodes_updated': nodes_updated
        }

    def _find_serialization_counter(self, memory: str) -> Optional[Node]:
        """Find serialization counter for a memory."""
        counter_name = f"{memory}_access_counter"
        return self.graph.nodes.get(counter_name)

    def _create_access_counter(self, memory: str, num_cycles: int) -> Node:
        """Create serialization counter for memory accesses."""
        counter_name = f"{memory}_access_counter"
        counter_width = math.ceil(math.log2(num_cycles + 1))

        counter_data = {
            'type': 'memory_access_counter',
            'name': counter_name,
            'display_name': f"{memory} access counter",
            'bit_width': counter_width,
            'max_count': num_cycles - 1,
            'memory': memory
        }

        counter_node = Node(counter_name, counter_data, is_uarch_state=True)
        counter_node.uarch_time = 0  # Counter starts at cycle 0
        self.graph.add_node(counter_node)

        print(f"    Created counter: {counter_name} (width={counter_width}, max={num_cycles-1})")

        return counter_node

    def _update_counter_width(self, counter_node: Node, new_num_cycles: int, granularity: int):
        """Update counter for new number of cycles."""
        new_counter_width = math.ceil(math.log2(new_num_cycles + 1))
        old_max = counter_node.data.get('max_count', 0)

        counter_node.data['max_count'] = new_num_cycles - 1
        counter_node.data['bit_width'] = new_counter_width
        counter_node.data['granularity'] = granularity

        print(f"    Updated counter: max_count {old_max}→{new_num_cycles-1}, bit_width={new_counter_width}")

    def _transform_access_to_serialized(
        self,
        access_node: Node,
        spec: MemoryAccessTransformSpec,
        counter_node: Node,
        num_cycles: int
    ) -> Dict[str, List[str]]:
        """
        Transform a single memory access into serialized form.

        Following the pattern from operation_serialization.py:
        1. Create narrow memory access nodes (one per cycle)
        2. Create address offset logic (addr, addr+bytes, etc.)
        3. Create mux to select which offset based on counter
        4. Create merge logic to combine results (for reads)
        5. Wire up edges

        Returns dict with nodes_added and nodes_removed.
        """
        print(f"    Transforming access: {access_node.id}")

        access_mode = access_node.data.get('access_mode', 'read')
        nodes_added = []

        # Step 1: Create narrow memory access nodes (one per word)
        narrow_accesses = self._create_narrow_memory_accesses(
            access_node, spec, num_cycles
        )
        nodes_added.extend([n.id for n in narrow_accesses])
        print(f"      Created {len(narrow_accesses)} narrow memory access nodes")

        # Step 2: Create address offset nodes
        # For each cycle, calculate addr + (i * bytes_per_access)
        bytes_per_access = spec.target_width // 8
        offset_nodes = self._create_address_offset_logic(
            access_node, spec, counter_node, num_cycles, bytes_per_access
        )
        nodes_added.extend([n.id for n in offset_nodes])
        print(f"      Created {len(offset_nodes)} address offset nodes")

        # Step 3: Connect offsets to narrow accesses
        for i, (offset_node, narrow_access) in enumerate(zip(offset_nodes, narrow_accesses)):
            # Connect offset to narrow access as address input
            offset_edge = Edge(offset_node, narrow_access, data={
                'type': 'memory_address',
                'cycle': i
            })
            self.graph.add_edge(offset_edge)

        if access_mode == 'read':
            # Step 4: Create data merge logic to combine narrow reads
            merge_node = self._create_data_merge_logic(
                access_node, narrow_accesses, spec, counter_node, num_cycles
            )
            nodes_added.append(merge_node.id)
            print(f"      Created data merge node: {merge_node.id}")

            # Step 5: Redirect original read destinations to merged result
            self._redirect_read_destinations(access_node, merge_node)

        else:  # write
            # For writes: create bit slice logic for data
            write_data_node = self._find_write_data_source(access_node)
            if write_data_node:
                # Create bit slices for write data
                data_slices = self._create_write_data_slices(
                    access_node, write_data_node, spec, num_cycles
                )
                nodes_added.extend([n.id for n in data_slices])
                print(f"      Created {len(data_slices)} write data slices")

                # Connect slices to narrow writes with assignment edges
                # This allows Verilog generator to recognize them as memory writes
                for i, (narrow_access, data_slice) in enumerate(zip(narrow_accesses, data_slices)):
                    # Connect data slice to narrow write as assignment edge
                    # (similar to how normal memory writes work)
                    assignment_edge = Edge(data_slice, narrow_access, data={
                        'type': 'assignment',
                        'cycle': i,
                        'left': narrow_access.data.get('expression', {}),
                        'right': {'type': 'identifier', 'name': data_slice.id}
                    })
                    self.graph.add_edge(assignment_edge)

                print(f"      Connected data slices to narrow writes")
            else:
                print(f"      Warning: No write data source found")

        return {
            'nodes_added': nodes_added,
            'nodes_removed': []  # We don't remove the original yet
        }

    def _create_narrow_memory_accesses(
        self,
        access_node: Node,
        spec: MemoryAccessTransformSpec,
        num_cycles: int
    ) -> List[Node]:
        """
        Create narrow memory access nodes (one per word).

        Similar to creating narrow operation units in operation_serialization.py.
        """
        narrow_accesses = []
        access_mode = access_node.data.get('access_mode', 'read')
        suffix = 'wr' if access_mode == 'write' else 'rd'

        for i in range(num_cycles):
            access_name = f"{spec.memory}_narrow_{suffix}_word{i}"

            # Create as array_access so it goes through existing Verilog generation
            # which already handles byte-enable and unaligned access
            access_data = {
                'type': 'array_access',  # Use array_access type for proper Verilog generation
                'name': access_name,
                'display_name': f"{spec.memory}[word{i}]_{suffix}",
                'memory': spec.memory,
                'word_index': i,
                'access_mode': access_mode,
                'bit_width': spec.target_width,
                'word_width': spec.target_width,  # Width of each narrow access
                'original_access': access_node.id,
                'original_width': spec.current_width,  # Original wide access width
                'is_narrow_access': True,  # Mark as transformation-created
                'supports_byte_enable': True,  # Enable byte-level writes
                'supports_unaligned': True,  # Enable unaligned access handling
                # Add expression metadata for array_access compatibility
                'expression': {
                    'type': 'array_access',
                    'array': {'type': 'identifier', 'name': spec.memory},
                    'index': {'type': 'identifier', 'name': f'offset_{i}'}  # Will be connected via edge
                }
            }

            narrow_node = Node(access_name, access_data, is_uarch_state=True)
            narrow_node.uarch_time = i  # Each word accessed at cycle i
            self.graph.add_node(narrow_node)
            narrow_accesses.append(narrow_node)

        return narrow_accesses

    def _create_address_offset_logic(
        self,
        access_node: Node,
        spec: MemoryAccessTransformSpec,
        counter_node: Node,
        num_cycles: int,
        bytes_per_access: int
    ) -> List[Node]:
        """
        Create address offset logic: addr, addr+bytes, addr+2*bytes, etc.

        For each cycle, compute the byte offset and add to base address.
        Similar to bit slice extraction in operation_serialization.py.
        """
        offset_nodes = []

        # Get the base address from the original access node
        # Find the address operand from incoming edges (skip memory node)
        base_addr_node = None
        for edge in access_node.incoming_edges:
            if edge.data.get('type') == 'array_index':
                # Skip if source is the memory node itself
                if edge.source.data.get('is_memory'):
                    continue
                base_addr_node = edge.source
                break

        if not base_addr_node:
            print(f"      Warning: No base address found for {access_node.id}")
            # Create dummy nodes for now
            for i in range(num_cycles):
                offset_name = f"{spec.memory}_offset_{i}"
                offset_data = {
                    'type': 'address_offset',
                    'name': offset_name,
                    'display_name': f"addr+{i*bytes_per_access}",
                    'word_index': i,
                    'byte_offset': i * bytes_per_access,
                    'memory': spec.memory
                }
                offset_node = Node(offset_name, offset_data, is_uarch_state=True)
                self.graph.add_node(offset_node)
                offset_nodes.append(offset_node)
            return offset_nodes

        # Create offset nodes for each word
        for i in range(num_cycles):
            byte_offset = i * bytes_per_access
            offset_name = f"{access_node.id}_offset_{i}"

            offset_data = {
                'type': 'address_offset',
                'name': offset_name,
                'display_name': f"{base_addr_node.id}+{byte_offset}" if byte_offset > 0 else base_addr_node.id,
                'base_address': base_addr_node.id,
                'word_index': i,
                'byte_offset': byte_offset,
                'memory': spec.memory
            }

            offset_node = Node(offset_name, offset_data, is_uarch_state=True)
            self.graph.add_node(offset_node)

            # Connect base address to offset
            if byte_offset == 0:
                # Word 0: just use base address directly
                addr_edge = Edge(base_addr_node, offset_node, data={
                    'type': 'base_address',
                    'offset': 0
                })
            else:
                # Word i: add offset to base
                addr_edge = Edge(base_addr_node, offset_node, data={
                    'type': 'address_with_offset',
                    'offset': byte_offset
                })
            self.graph.add_edge(addr_edge)

            offset_nodes.append(offset_node)

        return offset_nodes

    def _create_data_merge_logic(
        self,
        access_node: Node,
        narrow_accesses: List[Node],
        spec: MemoryAccessTransformSpec,
        counter_node: Node,
        num_cycles: int
    ) -> Node:
        """
        Create merge logic to combine narrow reads into wide result.

        Similar to result accumulation in operation_serialization.py, but
        for memory reads we concatenate the narrow words.
        """
        merge_name = f"{spec.memory}_data_merge"

        merge_data = {
            'type': 'memory_data_merge',
            'name': merge_name,
            'display_name': f"{spec.memory} data merge",
            'memory': spec.memory,
            'num_words': num_cycles,
            'word_width': spec.target_width,
            'output_width': spec.current_width,
            'original_access': access_node.id
        }

        merge_node = Node(merge_name, merge_data, is_uarch_state=True)
        merge_node.uarch_time = num_cycles - 1  # Result ready at final cycle
        self.graph.add_node(merge_node)

        # Connect all narrow reads to merge node
        for i, narrow_access in enumerate(narrow_accesses):
            merge_edge = Edge(narrow_access, merge_node, data={
                'type': 'memory_word',
                'word_index': i
            })
            self.graph.add_edge(merge_edge)

        # Connect counter to merge (to know when all words are ready)
        counter_edge = Edge(counter_node, merge_node, data={
            'type': 'merge_enable',
            'condition': f"{counter_node.id} == {num_cycles - 1}"
        })
        self.graph.add_edge(counter_edge)

        return merge_node

    def _redirect_read_destinations(self, original_access: Node, merge_node: Node):
        """
        Redirect edges from original access to merge node.

        The merge node now provides the data instead of the original access.
        """
        # Find all assignment edges from original access
        edges_to_redirect = []
        for edge in original_access.outgoing_edges:
            if edge.data.get('type') == 'assignment':
                edges_to_redirect.append((edge, edge.target))

        # Create new edges from merge to destinations
        for old_edge, destination in edges_to_redirect:
            new_edge = Edge(merge_node, destination, data={
                'type': 'assignment',
                'from_serialized': True,
                'original_access': original_access.id
            })
            self.graph.add_edge(new_edge)
            print(f"      Redirected {original_access.id} → {destination.id} to use merge")

        # Remove old edges
        for old_edge, _ in edges_to_redirect:
            old_edge.remove_from_nodes()
            if old_edge.id in self.graph.edges:
                del self.graph.edges[old_edge.id]

    def _find_write_data_source(self, access_node: Node) -> Optional[Node]:
        """
        Find the source of data being written to memory.

        For a write like dmem[addr] = r2, find the r2 node.
        """
        # Look for incoming edges with assignment type
        for edge in access_node.incoming_edges:
            if edge.data.get('type') == 'assignment':
                return edge.source
        return None

    def _create_write_data_slices(
        self,
        access_node: Node,
        write_data_node: Node,
        spec: MemoryAccessTransformSpec,
        num_cycles: int
    ) -> List[Node]:
        """
        Create bit slice nodes for write data.

        Similar to bit slice extraction in operation_serialization.py, but for memory writes.
        Splits wide write data (e.g., 32-bit) into narrow slices (e.g., 16-bit).
        """
        data_slices = []

        for i in range(num_cycles):
            low_bit = i * spec.target_width
            high_bit = min((i + 1) * spec.target_width - 1, spec.current_width - 1)

            slice_name = f"{access_node.id}_data_slice_{i}"

            slice_data = {
                'type': 'write_data_slice',
                'name': slice_name,
                'display_name': f"{write_data_node.id}[{high_bit}:{low_bit}]",
                'source_data': write_data_node.id,
                'slice_index': i,
                'high_bit': high_bit,
                'low_bit': low_bit,
                'slice_width': high_bit - low_bit + 1,
                'memory': spec.memory
            }

            slice_node = Node(slice_name, slice_data, is_uarch_state=True)
            slice_node.uarch_time = i  # Each slice at its corresponding cycle
            self.graph.add_node(slice_node)

            # Connect write data to slice extractor
            slice_edge = Edge(write_data_node, slice_node, data={
                'type': 'bit_slice',
                'slice_index': i
            })
            self.graph.add_edge(slice_edge)

            data_slices.append(slice_node)

        return data_slices

    def _analyze_serialization_structure(self, counter_node: Node) -> Dict:
        """
        Analyze existing serialization to determine if it can be reversed.

        Finds all the serialization nodes created by forward transformation:
        - Counter node
        - Narrow access nodes
        - Address offset nodes
        - Merge node
        - Original access node
        """
        memory = counter_node.data.get('memory', '')
        num_cycles = counter_node.data.get('max_count', 0) + 1

        # Find narrow access nodes for this memory
        narrow_accesses = []
        for node in self.graph.nodes.values():
            # Changed to array_access with is_narrow_access flag
            if node.data.get('type') == 'array_access' and node.data.get('is_narrow_access'):
                if node.data.get('memory') == memory:
                    narrow_accesses.append(node)

        if not narrow_accesses:
            return {
                'can_parallelize': False,
                'reason': 'No narrow memory accesses found',
                'num_cycles': num_cycles,
                'memory': memory
            }

        # Find merge node
        merge_node = None
        for node in self.graph.nodes.values():
            if node.data.get('type') == 'memory_data_merge':
                if node.data.get('memory') == memory:
                    merge_node = node
                    break

        if not merge_node:
            return {
                'can_parallelize': False,
                'reason': 'No merge node found',
                'num_cycles': num_cycles,
                'memory': memory
            }

        # Find original access node (from merge metadata)
        original_access_id = merge_node.data.get('original_access')
        original_access = self.graph.nodes.get(original_access_id) if original_access_id else None

        # Find address offset nodes
        offset_nodes = []
        for node in self.graph.nodes.values():
            if node.data.get('type') == 'address_offset':
                if node.data.get('memory') == memory:
                    offset_nodes.append(node)

        # Group information about this serialized access
        access_info = {
            'narrow_accesses': narrow_accesses,
            'merge_node': merge_node,
            'original_access': original_access,
            'offset_nodes': offset_nodes,
            'counter': counter_node
        }

        return {
            'can_parallelize': True,
            'num_cycles': num_cycles,
            'access_nodes': [access_info],  # Wrap in list for consistency
            'memory': memory
        }

    def _restore_direct_access(
        self,
        access_info: Dict,
        spec: MemoryAccessTransformSpec
    ) -> Dict[str, List[str]]:
        """
        Restore direct wide access from serialized pattern.

        Reverses what _transform_access_to_serialized did:
        1. Find destinations of merge node
        2. Restore original access node (or create new wide access)
        3. Reconnect destinations to original/wide access
        4. Remove all serialization nodes
        """
        merge_node = access_info['merge_node']
        original_access = access_info['original_access']
        narrow_accesses = access_info['narrow_accesses']
        offset_nodes = access_info['offset_nodes']

        nodes_removed = []
        nodes_added = []

        print(f"      Restoring direct access from {len(narrow_accesses)} narrow accesses")

        # Find what the merge node feeds into
        merge_destinations = []
        for edge in merge_node.outgoing_edges:
            if edge.data.get('type') == 'assignment':
                merge_destinations.append(edge.target)

        # If original access still exists, restore edges to it
        if original_access and original_access.id in self.graph.nodes:
            print(f"      Restoring original access: {original_access.id}")

            # Update original access to wide width
            original_access.data['bit_width'] = spec.target_width

            # Reconnect merge destinations to original access
            for dest in merge_destinations:
                # Remove old edge from merge
                old_edges = [e for e in merge_node.outgoing_edges
                           if e.target == dest and e.data.get('type') == 'assignment']
                for old_edge in old_edges:
                    old_edge.remove_from_nodes()
                    if old_edge.id in self.graph.edges:
                        del self.graph.edges[old_edge.id]

                # Create new edge from original access
                new_edge = Edge(original_access, dest, data={
                    'type': 'assignment',
                    'from_parallelized': True
                })
                self.graph.add_edge(new_edge)
                print(f"        Reconnected {original_access.id} → {dest.id}")

        else:
            print(f"      Original access not found, creating new wide access")
            # TODO: Create new wide access node if original doesn't exist

        # Remove all serialization nodes
        # 1. Remove narrow accesses
        for narrow in narrow_accesses:
            self._remove_node_and_edges(narrow)
            nodes_removed.append(narrow.id)

        # 2. Remove offset nodes
        for offset in offset_nodes:
            self._remove_node_and_edges(offset)
            nodes_removed.append(offset.id)

        # 3. Remove merge node
        self._remove_node_and_edges(merge_node)
        nodes_removed.append(merge_node.id)

        print(f"      Removed {len(nodes_removed)} serialization nodes")

        return {
            'nodes_added': nodes_added,
            'nodes_removed': nodes_removed
        }

    def _remove_node_and_edges(self, node: Node):
        """Remove a node and all its edges from the graph."""
        # Remove all edges
        edges_to_remove = list(node.incoming_edges) + list(node.outgoing_edges)
        for edge in edges_to_remove:
            edge.remove_from_nodes()
            if edge.id in self.graph.edges:
                del self.graph.edges[edge.id]

        # Remove node
        if node.id in self.graph.nodes:
            del self.graph.nodes[node.id]

    def _update_serialization_logic(
        self,
        access_info: Dict,
        spec: MemoryAccessTransformSpec,
        new_num_cycles: int
    ):
        """
        Update existing serialization logic for new granularity.

        When changing memory width (e.g., 16→8 bits), we need to:
        1. Update or recreate narrow access nodes (2 → 4 words)
        2. Update or recreate offset nodes (new byte offsets)
        3. Update merge node metadata
        """
        print(f"      Updating serialization logic for new granularity")

        merge_node = access_info['merge_node']
        narrow_accesses = access_info['narrow_accesses']
        offset_nodes = access_info['offset_nodes']
        original_access = access_info['original_access']
        counter_node = access_info['counter']

        old_num_cycles = len(narrow_accesses)

        print(f"        Need to change from {old_num_cycles} cycles to {new_num_cycles} cycles")

        if new_num_cycles == old_num_cycles:
            print(f"        Same number of cycles, just updating widths")
            # Update node metadata without recreating
            for narrow in narrow_accesses:
                narrow.data['bit_width'] = spec.target_width
            if merge_node:
                merge_node.data['word_width'] = spec.target_width
                merge_node.data['num_words'] = new_num_cycles
        else:
            print(f"        Number of cycles changed, recreating nodes")

            # Remove old serialization nodes
            for narrow in narrow_accesses:
                self._remove_node_and_edges(narrow)
            for offset in offset_nodes:
                self._remove_node_and_edges(offset)
            if merge_node:
                self._remove_node_and_edges(merge_node)

            # Recreate with new granularity
            # Original access should still exist
            if original_access and original_access.id in self.graph.nodes:
                result = self._transform_access_to_serialized(
                    original_access,
                    spec,
                    counter_node,
                    new_num_cycles
                )
                print(f"        Recreated {len(result['nodes_added'])} nodes for new granularity")
