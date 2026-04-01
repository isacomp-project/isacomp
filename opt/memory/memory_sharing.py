"""
Memory Port Sharing Optimization for ResourceGraph.

This module implements algorithms to share memory ports when multiple accesses
to the same memory occur simultaneously, trading latency for area.
"""

from typing import Dict, List, Set, Tuple, Optional
from core.resource_graph import ResourceGraph, Node, Edge


class MemoryPortSpec:
    """Specification for memory port constraints."""

    def __init__(self, read_ports: int = 1, write_ports: int = 1, read_write_ports: int = 0):
        self.read_ports = read_ports
        self.write_ports = write_ports
        self.read_write_ports = read_write_ports  # Ports that can do either read or write

    def __str__(self):
        if self.read_write_ports > 0:
            return f"{self.read_ports}R + {self.write_ports}W + {self.read_write_ports}RW"
        else:
            return f"{self.read_ports}R + {self.write_ports}W"

    def can_handle_accesses(self, num_reads: int, num_writes: int) -> bool:
        """Check if this port configuration can handle the given access pattern."""
        # Try to map accesses to available ports
        remaining_reads = num_reads
        remaining_writes = num_writes

        # Use dedicated read ports
        remaining_reads = max(0, remaining_reads - self.read_ports)

        # Use dedicated write ports
        remaining_writes = max(0, remaining_writes - self.write_ports)

        # Use read/write ports for remaining accesses
        total_remaining = remaining_reads + remaining_writes
        return total_remaining <= self.read_write_ports


class MemoryAccess:
    """Represents a single memory access."""

    def __init__(self, memory_name: str, access_node: Node, is_write: bool,
                 index_expr: str, time_slot: Optional[int] = None):
        self.memory_name = memory_name
        self.access_node = access_node
        self.is_write = is_write
        self.index_expr = index_expr
        self.time_slot = time_slot

    def __str__(self):
        access_type = "WRITE" if self.is_write else "READ"
        slot_info = f" [T{self.time_slot}]" if self.time_slot is not None else ""
        return f"{self.memory_name}[{self.index_expr}] {access_type}{slot_info}"


class MemoryPortSharingTransform:
    """Implements memory port sharing transformations on ResourceGraphs."""

    def __init__(self, graph: ResourceGraph):
        self.graph = graph
        self.memory_accesses: Dict[str, List[MemoryAccess]] = {}
        self.memory_specs: Dict[str, MemoryPortSpec] = {}

    def analyze_memory_accesses(self) -> Dict[str, List[MemoryAccess]]:
        """Analyze all memory accesses in the graph."""
        self.memory_accesses = {}

        # Find all memory nodes
        memory_nodes = {}
        for node_id, node in self.graph.nodes.items():
            if node.is_arch_state and node.data.get('is_memory', False):
                memory_nodes[node_id] = node
                self.memory_accesses[node_id] = []

        # Find all array access nodes that reference memories
        for node_id, node in self.graph.nodes.items():
            if node.data.get('type') == 'array_access':
                expr = node.data.get('expression', {})
                if expr.get('type') == 'array_access':
                    array_expr = expr.get('array', {})
                    if array_expr.get('type') == 'identifier':
                        memory_name = array_expr.get('name')

                        if memory_name in memory_nodes:
                            # Get index expression
                            index_expr = expr.get('index', {})
                            index_name = self._expression_to_string(index_expr)

                            # Determine if it's a read or write
                            is_write = self._is_write_access(node)

                            access = MemoryAccess(memory_name, node, is_write, index_name)
                            self.memory_accesses[memory_name].append(access)

        return self.memory_accesses

    def _expression_to_string(self, expr: Dict) -> str:
        """Convert expression to string representation."""
        if expr.get('type') == 'identifier':
            return expr.get('name', 'unknown')
        elif expr.get('type') == 'literal':
            return str(expr.get('value', 'unknown'))
        else:
            return 'complex_expr'

    def _is_write_access(self, access_node: Node) -> bool:
        """Determine if an array access node is a write."""
        for edge in self.graph.edges.values():
            if (edge.data.get('type') == 'assignment' and
                edge.target == access_node):
                return True
        return False

    def set_memory_port_spec(self, memory_name: str, spec: MemoryPortSpec):
        """Set port specification for a specific memory."""
        self.memory_specs[memory_name] = spec

    def apply_memory_port_sharing(self, memory_name: str) -> bool:
        """Apply port sharing transformation for a specific memory."""
        if memory_name not in self.memory_accesses:
            print(f"No accesses found for memory {memory_name}")
            return False

        accesses = self.memory_accesses[memory_name]
        if len(accesses) <= 1:
            print(f"Memory {memory_name} has only {len(accesses)} access(es), no sharing needed")
            return False

        spec = self.memory_specs.get(memory_name, MemoryPortSpec(1, 1, 0))

        # Count access types
        reads = [a for a in accesses if not a.is_write]
        writes = [a for a in accesses if a.is_write]

        print(f"Memory {memory_name}: {len(reads)} reads, {len(writes)} writes")
        print(f"Port specification: {spec}")

        # Check if sharing is needed
        if spec.can_handle_accesses(len(reads), len(writes)):
            print(f"No sharing needed - ports can handle accesses simultaneously")
            return False

        print(f"Port sharing required!")

        # Create time slots for accesses
        time_slots = self._create_time_slots(reads, writes, spec)

        # Create uarch counter for port arbitration
        self._create_memory_counter(memory_name, len(time_slots))

        # Insert timing cuts for each time slot
        for slot_idx, slot_accesses in enumerate(time_slots):
            for access in slot_accesses:
                access.time_slot = slot_idx
                self._insert_memory_access_cuts(access, slot_idx)

        # Gate memory accesses by time slot
        self._gate_memory_accesses(memory_name, time_slots)

        # Re-infer timing
        self.graph.infer_uarch_time()

        return True

    def _create_time_slots(self, reads: List[MemoryAccess], writes: List[MemoryAccess],
                          spec: MemoryPortSpec) -> List[List[MemoryAccess]]:
        """Create time slots that respect port constraints."""
        all_accesses = reads + writes
        time_slots = []
        remaining_accesses = all_accesses.copy()

        while remaining_accesses:
            # Create a new time slot
            slot_accesses = []
            slot_reads = 0
            slot_writes = 0

            # Greedily pack accesses into this slot
            i = 0
            while i < len(remaining_accesses):
                access = remaining_accesses[i]

                # Check if we can add this access to current slot
                test_reads = slot_reads + (0 if access.is_write else 1)
                test_writes = slot_writes + (1 if access.is_write else 0)

                if spec.can_handle_accesses(test_reads, test_writes):
                    # Add this access to the slot
                    slot_accesses.append(access)
                    slot_reads = test_reads
                    slot_writes = test_writes
                    remaining_accesses.pop(i)
                else:
                    i += 1

            if not slot_accesses:
                # Safety check - shouldn't happen with valid port specs
                print("Warning: Could not pack any accesses into time slot")
                break

            time_slots.append(slot_accesses)

        print(f"Created {len(time_slots)} time slots:")
        for i, slot in enumerate(time_slots):
            slot_reads = len([a for a in slot if not a.is_write])
            slot_writes = len([a for a in slot if a.is_write])
            print(f"  Slot {i}: {slot_reads}R + {slot_writes}W")
            for access in slot:
                print(f"    {access}")

        return time_slots

    def _create_memory_counter(self, memory_name: str, num_slots: int):
        """Create counter for memory port arbitration."""
        counter_name = f"{memory_name}_port_counter"
        counter_data = {
            'type': 'memory_port_counter',
            'name': counter_name,
            'display_name': counter_name,
            'bit_width': (num_slots - 1).bit_length() + 1,
            'max_value': num_slots - 1,
            'memory': memory_name
        }

        counter_node = Node(counter_name, counter_data, is_uarch_state=True)
        self.graph.add_node(counter_node)
        print(f"Created memory port counter: {counter_name} (0 to {num_slots-1})")

    def _insert_memory_access_cuts(self, access: MemoryAccess, time_slot: int):
        """Insert timing cuts around a memory access."""
        node = access.access_node
        memory_name = access.memory_name

        # Create input pipeline registers for address and data (if write)
        for edge in list(node.incoming_edges):
            source_node = edge.source
            edge_data = edge.data.copy()

            # Create pipeline register
            reg_name = f"{memory_name}_{source_node.id}_t{time_slot}_reg"
            reg_data = {
                'type': 'memory_pipeline_reg',
                'name': reg_name,
                'display_name': reg_name,
                'bit_width': 32,
                'time_slot': time_slot,
                'memory': memory_name
            }

            pipeline_reg = Node(reg_name, reg_data, is_uarch_state=True)
            self.graph.add_node(pipeline_reg)

            # Rewire: source -> pipeline_reg -> memory_access
            self.graph.remove_edge(edge.id)
            edge1 = Edge(source_node, pipeline_reg, data={'type': 'memory_pipeline'})
            edge2 = Edge(pipeline_reg, node, data=edge_data)
            self.graph.add_edge(edge1)
            self.graph.add_edge(edge2)

        # Create output pipeline registers for read data
        if not access.is_write:
            for edge in list(node.outgoing_edges):
                target_node = edge.target
                edge_data = edge.data.copy()

                # Create result register
                reg_name = f"{memory_name}_read_t{time_slot}_reg"
                reg_data = {
                    'type': 'memory_result_reg',
                    'name': reg_name,
                    'display_name': reg_name,
                    'bit_width': 32,
                    'time_slot': time_slot,
                    'memory': memory_name
                }

                result_reg = Node(reg_name, reg_data, is_uarch_state=True)
                self.graph.add_node(result_reg)

                # Rewire: memory_access -> result_reg -> target
                self.graph.remove_edge(edge.id)
                edge1 = Edge(node, result_reg, data={'type': 'memory_result'})
                edge2 = Edge(result_reg, target_node, data=edge_data)
                self.graph.add_edge(edge1)
                self.graph.add_edge(edge2)

    def _gate_memory_accesses(self, memory_name: str, time_slots: List[List[MemoryAccess]]):
        """Gate memory accesses by time slot."""
        for slot_idx, slot_accesses in enumerate(time_slots):
            for access in slot_accesses:
                # Mark this access as gated by the memory counter
                for edge in self.graph.edges.values():
                    if ((edge.source == access.access_node or edge.target == access.access_node) and
                        edge.data.get('type') in ['array_index', 'assignment']):
                        edge.data['memory_gated'] = True
                        edge.data['gate_condition'] = f"{memory_name}_port_counter == {slot_idx}"

    def get_memory_sharing_summary(self) -> str:
        """Generate summary of memory port sharing transformation."""
        summary = "Memory Port Sharing Summary:\n"
        summary += "=" * 50 + "\n\n"

        for memory_name, accesses in self.memory_accesses.items():
            if len(accesses) <= 1:
                continue

            summary += f"Memory: {memory_name}\n"
            reads = [a for a in accesses if not a.is_write]
            writes = [a for a in accesses if a.is_write]
            summary += f"  Original: {len(reads)} reads + {len(writes)} writes\n"

            spec = self.memory_specs.get(memory_name, MemoryPortSpec(1, 1, 0))
            summary += f"  Port spec: {spec}\n"

            # Count time slots used
            time_slots = set(a.time_slot for a in accesses if a.time_slot is not None)
            if time_slots:
                summary += f"  Time slots: {len(time_slots)}\n"

            summary += "\n"

        return summary


class ReadPortSharingTransform:
    """
    Shares memory read ports based on mutually exclusive read enables.

    This optimization reduces the number of physical read ports by muxing
    addresses when the read enables are mutually exclusive (e.g., instruction
    enables are one-hot decoded, so only one can be active at a time).

    Unlike time-multiplexing which adds latency, this optimization uses
    address muxing and has zero latency cost.
    """

    def __init__(self, graph: ResourceGraph):
        self.graph = graph

    def analyze_read_ports(self, memory_name: str) -> dict:
        """
        Analyze read ports for a memory and identify mutually exclusive groups.

        Returns a dict with:
            - 'read_nodes': list of (node, index_expr, read_enable_id, instruction_set)
            - 'single_instr_count': number of single-instruction read ports
            - 'multi_instr_count': number of multi-instruction read ports
            - 'always_enabled_count': number of always-enabled ports (e.g., PC fetch)
            - 'min_ports_needed': minimum ports needed due to non-overlapping enables
        """
        import re
        array_read_pattern = re.compile(rf'^{re.escape(memory_name)}\[(.+)\]_rd$')

        single_instr = []  # Single-instruction read enables
        multi_instr = []   # Multi-instruction OR'd enables
        always_enabled = []  # Always-enabled (e.g., PC read)
        unknown = []  # Unknown enable type

        for node_id, node in self.graph.nodes.items():
            match = array_read_pattern.match(node_id)
            if not match:
                continue

            index_expr = match.group(1)
            read_enable_id = node.data.get('read_enable')

            if not read_enable_id:
                # No read enable - might be always enabled or missing analysis
                unknown.append((node, index_expr, None, set()))
                continue

            enable_node = self.graph.nodes.get(read_enable_id)
            if not enable_node:
                unknown.append((node, index_expr, read_enable_id, set()))
                continue

            enable_type = enable_node.data.get('type', '')

            if enable_type == 'literal' and enable_node.data.get('value') == 1:
                always_enabled.append((node, index_expr, read_enable_id, set()))
            elif enable_type == 'logical_and':
                # Gated enable: condition && instruction_enable
                # e.g., rf_bank_add_rn_lo_rd_enable = add_rn_bk && add_enable
                # Need to find the instruction enable in the incoming edges
                instrs = set()
                for edge in enable_node.incoming_edges:
                    src_id = edge.source.id
                    if src_id.endswith('_enable'):
                        # Extract instruction name from the enable
                        instr_name = src_id[:-7]  # Remove '_enable'
                        instrs.add(instr_name)
                if not instrs:
                    unknown.append((node, index_expr, read_enable_id, set()))
                elif len(instrs) == 1:
                    # Gated single-instruction enable (e.g., add_rn_bk && add_enable)
                    # Can share with other single-instruction enables since instructions
                    # are mutually exclusive
                    single_instr.append((node, index_expr, read_enable_id, instrs))
                else:
                    # Gated multi-instruction enable
                    multi_instr.append((node, index_expr, read_enable_id, instrs))
            elif enable_type == 'logical_or':
                # Multi-instruction OR enable
                source_instrs = enable_node.data.get('source_instructions', [])
                if source_instrs:
                    multi_instr.append((node, index_expr, read_enable_id, set(source_instrs)))
                else:
                    # Try to get from edges
                    instrs = set()
                    for edge in enable_node.incoming_edges:
                        if edge.source.id.endswith('_enable'):
                            instrs.add(edge.source.id[:-7])
                    if instrs:
                        multi_instr.append((node, index_expr, read_enable_id, instrs))
                    else:
                        unknown.append((node, index_expr, read_enable_id, set()))
            elif read_enable_id.endswith('_enable'):
                # Simple instruction enable (e.g., add_enable)
                instr_name = read_enable_id[:-7]
                single_instr.append((node, index_expr, read_enable_id, {instr_name}))
            else:
                unknown.append((node, index_expr, read_enable_id, set()))

        # Calculate minimum ports needed using greedy graph coloring
        # Two ports can share if their instruction sets don't overlap
        min_ports = len(always_enabled)  # Always-enabled ports can't be shared
        min_ports += len(unknown)  # Unknown entries need separate ports

        # Group all single and multi-instruction enables
        all_enables = list(single_instr) + list(multi_instr)
        remaining = list(all_enables)

        while remaining:
            # Greedily build one group of mutually exclusive ports
            group_instrs = set()
            still_remaining = []

            for entry in remaining:
                instr_set = entry[3]
                if not (instr_set & group_instrs):
                    # Can add to this group
                    group_instrs.update(instr_set)
                else:
                    # Overlaps - needs different group
                    still_remaining.append(entry)

            min_ports += 1  # This group needs one port
            remaining = still_remaining

        return {
            'read_nodes': single_instr + multi_instr + always_enabled + unknown,
            'single_instr': single_instr,
            'multi_instr': multi_instr,
            'always_enabled': always_enabled,
            'unknown': unknown,
            'single_instr_count': len(single_instr),
            'multi_instr_count': len(multi_instr),
            'always_enabled_count': len(always_enabled),
            'unknown_count': len(unknown),
            'min_ports_needed': min_ports,
            'total_ports': len(single_instr) + len(multi_instr) + len(always_enabled) + len(unknown)
        }

    def share_read_ports(self, memory_name: str, target_read_ports: Optional[int] = None) -> dict:
        """
        Share read ports for a memory to meet target port count.

        Args:
            memory_name: Name of the memory (e.g., 'rf', 'umem', 'rf_bank')
            target_read_ports: Desired number of read ports, or None for auto-detect
                               (uses minimum ports based on mutually exclusive enables)

        Returns:
            Dict with sharing results:
                - 'success': whether sharing was applied
                - 'ports_before': original port count
                - 'ports_after': final port count
                - 'shared_port_ids': list of created shared port node IDs
        """
        from core.resource_graph import Node, Edge

        analysis = self.analyze_read_ports(memory_name)

        print(f"\n{'='*60}")
        print(f"READ PORT SHARING: {memory_name}")
        print(f"{'='*60}")
        print(f"  Total read ports: {analysis['total_ports']}")
        print(f"    Single-instruction enables: {analysis['single_instr_count']}")
        print(f"    Multi-instruction enables: {analysis['multi_instr_count']}")
        print(f"    Always-enabled: {analysis['always_enabled_count']}")
        print(f"    Unknown: {analysis['unknown_count']}")
        print(f"  Minimum ports needed: {analysis['min_ports_needed']}")

        if target_read_ports is None:
            target_read_ports = analysis['min_ports_needed']
            print(f"  Target ports (auto): {target_read_ports}")
        else:
            print(f"  Target ports (user): {target_read_ports}")

        if target_read_ports >= analysis['total_ports']:
            print(f"  No sharing needed - already at or below target")
            return {
                'success': False,
                'ports_before': analysis['total_ports'],
                'ports_after': analysis['total_ports'],
                'shared_port_ids': []
            }

        if target_read_ports < analysis['min_ports_needed']:
            print(f"  WARNING: Target {target_read_ports} is below minimum {analysis['min_ports_needed']}")
            print(f"  Will share to minimum possible")
            target_read_ports = analysis['min_ports_needed']

        # Build shareable groups using greedy graph coloring
        # Each group contains ports that are mutually exclusive (no instruction overlap)
        shared_port_ids = []
        singleton_ports = []  # Ports that can't be shared with anything

        # Combine all candidates (single and multi-instruction enables)
        all_candidates = list(analysis['single_instr']) + list(analysis['multi_instr'])
        remaining = list(all_candidates)  # Ports not yet assigned to a group

        group_idx = 0
        while remaining:
            # Start a new group
            group = []
            group_instrs = set()
            still_remaining = []

            for entry in remaining:
                node, index_expr, enable_id, instr_set = entry
                if not (instr_set & group_instrs):
                    # No overlap - can add to this group
                    group.append(entry)
                    group_instrs.update(instr_set)
                else:
                    # Overlaps - try in next group
                    still_remaining.append(entry)

            if len(group) >= 2:
                # Create shared port for this group
                shared_port_id = self._create_shared_port(
                    memory_name,
                    group,
                    group_idx
                )
                if shared_port_id:
                    shared_port_ids.append(shared_port_id)
                    group_idx += 1
            elif len(group) == 1:
                # Single port in group - can't share with remaining
                # Check if we're making progress
                if len(still_remaining) == len(remaining) - 1:
                    # We removed exactly one entry - mark it as singleton
                    singleton_ports.append(group[0])
                else:
                    # Put it back for another attempt
                    still_remaining.append(group[0])

            # Safety check to prevent infinite loop
            if len(still_remaining) >= len(remaining):
                # No progress made - all remaining are singletons
                singleton_ports.extend(still_remaining)
                break

            remaining = still_remaining

        # Count ports that couldn't be shared (always-enabled, unknown, singletons)
        non_shared_count = (
            analysis['always_enabled_count'] +
            analysis['unknown_count'] +
            len(singleton_ports)  # Ports that couldn't be grouped
        )

        ports_after = len(shared_port_ids) + non_shared_count

        print(f"\n  Sharing results:")
        print(f"    Shared port groups created: {len(shared_port_ids)}")
        print(f"    Non-shareable ports: {non_shared_count}")
        print(f"    Ports before: {analysis['total_ports']}")
        print(f"    Ports after: {ports_after}")

        return {
            'success': len(shared_port_ids) > 0,
            'ports_before': analysis['total_ports'],
            'ports_after': ports_after,
            'shared_port_ids': shared_port_ids
        }

    def _create_shared_port(self, memory_name: str, candidates: list, group_idx: int) -> Optional[str]:
        """Create a shared read port for a group of mutually exclusive read accesses."""
        from core.resource_graph import Node, Edge

        if len(candidates) < 2:
            return None

        shared_port_id = f"{memory_name}_shared_rd_{group_idx}"
        print(f"\n  Creating shared port: {shared_port_id} for {len(candidates)} reads")

        # Get bit width from first node
        first_node = candidates[0][0]
        bit_width = first_node.data.get('bit_width', 32)

        # Create address mux
        addr_mux_id = f"{shared_port_id}_addr_mux"
        addr_mux_data = {
            'type': 'one_hot_mux',
            'name': addr_mux_id,
            'display_name': f"{memory_name} Shared Read Address MUX",
            'mux_inputs': [],
            'is_shared_read_addr_mux': True
        }

        valid_inputs = []
        for node, index_expr, enable_id, instr_set in candidates:
            # Find address source
            addr_source = None
            for edge in node.incoming_edges:
                if edge.data and edge.data.get('type') == 'array_index':
                    addr_source = edge.source
                    break

            if not addr_source:
                print(f"    WARNING: Can't find address source for {node.id}")
                continue

            valid_inputs.append({
                'source_node': addr_source.id,
                'enable_node': enable_id,
                'original_read_node': node.id,
                'instructions': list(instr_set)
            })
            print(f"    Input: {addr_source.id} when {enable_id}")

        if len(valid_inputs) < 2:
            print(f"    Not enough valid inputs, skipping")
            return None

        addr_mux_data['mux_inputs'] = valid_inputs

        # Determine address width
        addr_width = 32
        for inp in valid_inputs:
            src = self.graph.nodes.get(inp['source_node'])
            if src:
                w = src.data.get('bit_width')
                if w:
                    addr_width = max(addr_width, w)
        addr_mux_data['bit_width'] = addr_width

        # Create nodes
        addr_mux_node = Node(addr_mux_id, addr_mux_data)
        self.graph.add_node(addr_mux_node)

        # Connect edges to mux
        for inp in valid_inputs:
            src = self.graph.nodes.get(inp['source_node'])
            enable = self.graph.nodes.get(inp['enable_node'])
            if src:
                edge = Edge(src, addr_mux_node, data={'type': 'mux_input', 'original_read': inp['original_read_node']})
                self.graph.add_edge(edge)
            if enable:
                edge = Edge(enable, addr_mux_node, data={'type': 'mux_select', 'original_read': inp['original_read_node']})
                self.graph.add_edge(edge)

        # Create shared port node
        shared_port_data = {
            'type': 'array_access',
            'name': shared_port_id,
            'display_name': f"{memory_name} Shared Read Port {group_idx}",
            'bit_width': bit_width,
            'is_shared_read_port': True,
            'shared_read_sources': [inp['original_read_node'] for inp in valid_inputs],
            'address_mux': addr_mux_id
        }
        shared_port_node = Node(shared_port_id, shared_port_data)
        self.graph.add_node(shared_port_node)

        # Connect memory and address mux to shared port
        memory_node = self.graph.nodes.get(memory_name)
        if memory_node:
            edge = Edge(memory_node, shared_port_node, data={'type': 'array_base', 'position': 0})
            self.graph.add_edge(edge)

        edge = Edge(addr_mux_node, shared_port_node, data={'type': 'array_index', 'position': 1})
        self.graph.add_edge(edge)

        # Create combined enable
        shared_enable_id = f"{shared_port_id}_enable"
        all_instrs = []
        for inp in valid_inputs:
            all_instrs.extend(inp['instructions'])
        shared_enable_data = {
            'type': 'logical_or',
            'operation': '||',
            'display_name': f"{memory_name} Shared Read Enable",
            'bit_width': 1,
            'source_instructions': all_instrs
        }
        shared_enable_node = Node(shared_enable_id, shared_enable_data)
        self.graph.add_node(shared_enable_node)

        for inp in valid_inputs:
            enable = self.graph.nodes.get(inp['enable_node'])
            if enable:
                edge = Edge(enable, shared_enable_node, data={'type': 'logic_input'})
                self.graph.add_edge(edge)

        shared_port_node.data['read_enable'] = shared_enable_id

        # Mark original nodes as superseded
        for inp in valid_inputs:
            original = self.graph.nodes.get(inp['original_read_node'])
            if original:
                original.data['superseded_by'] = shared_port_id
                original.data['shared_read_enable'] = inp['enable_node']

        return shared_port_id


def share_read_ports_by_enable(graph: ResourceGraph, memory_name: str,
                                target_read_ports: Optional[int] = None) -> dict:
    """
    Share read ports for a memory based on mutually exclusive read enables.

    This optimization reduces physical read ports by using address muxing when
    read enables are mutually exclusive (e.g., instruction enables are one-hot).

    Args:
        graph: ResourceGraph to transform
        memory_name: Name of the memory (e.g., 'rf', 'umem', 'rf_bank')
        target_read_ports: Desired number of read ports. Use None to auto-detect
                          the minimum based on truly mutually exclusive enables.

    Returns:
        Dict with sharing results including ports_before, ports_after, etc.

    Example usage in generator:
        from memory_sharing import share_read_ports_by_enable

        # Share rf_bank to 2 read ports
        share_read_ports_by_enable(merged_graph, 'rf_bank', target_read_ports=2)

        # Auto-detect minimum for umem
        share_read_ports_by_enable(merged_graph, 'umem', target_read_ports=None)
    """
    transform = ReadPortSharingTransform(graph)
    return transform.share_read_ports(memory_name, target_read_ports)


def apply_register_file_sharing(graph: ResourceGraph, read_ports: int = 1,
                               write_ports: int = 1, read_write_ports: int = 0) -> bool:
    """
    Apply memory port sharing to register file with specified port configuration.

    Args:
        graph: ResourceGraph to transform
        read_ports: Number of dedicated read ports
        write_ports: Number of dedicated write ports
        read_write_ports: Number of read/write ports
    """
    transform = MemoryPortSharingTransform(graph)

    # Analyze memory accesses
    accesses = transform.analyze_memory_accesses()

    if 'rf' not in accesses:
        print("No register file found")
        return False

    # Set port specification for register file
    spec = MemoryPortSpec(read_ports, write_ports, read_write_ports)
    transform.set_memory_port_spec('rf', spec)

    # Apply sharing
    success = transform.apply_memory_port_sharing('rf')

    if success:
        print("\nMemory Port Sharing Summary:")
        print(transform.get_memory_sharing_summary())

    return success