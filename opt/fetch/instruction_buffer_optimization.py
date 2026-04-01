#!/usr/bin/env python3
"""
Instruction Buffer Optimization

This optimization inserts an instruction buffer between an instruction memory
(imem) and the decode stage. The buffer prefetches instructions at a configurable
fetch width and stores them in a FIFO buffer of configurable depth, then uses
the final decoded instruction width to advance through the buffer and output
the next instruction at the same point the original imem output was connected.

This is useful for:
- Variable-length ISAs (x86, 6502, etc.) where decode determines instruction size
- Decoupling fetch bandwidth from decode bandwidth
- Absorbing fetch latency by prefetching ahead

PC-Based Access Detection:
- The user specifies the PC node and the imem node
- The optimization automatically finds all imem[pc], imem[pc+1], imem[pc+2], etc.
  accesses in the graph by tracing the array_index edges back to the PC
- Each access is assigned a byte offset from the PC, and the buffer provides
  multiple output ports at those offsets: ibuf[0], ibuf[1], ibuf[2], etc.
- The original imem[pc+N] consumers are redirected to the corresponding ibuf[N]

Flush + Redirect Interface:
- For pipelined designs with branch prediction, the buffer supports a flush
  signal and a redirect address input
- On branch misprediction, the flush signal clears the buffer contents and
  the redirect address tells the fetch FSM where to start fetching from
- This integrates with the existing control_hazard_flush infrastructure

Integration with Memory Latency Infrastructure:
- Creates start/idle/complete control signals compatible with HazardResolver
- Buffer empty triggers pipeline stalls via standard stall infrastructure
- Buffer hit (data available) bypasses stall logic
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from core.resource_graph import ResourceGraph, Node, Edge
from core.hardware_builders import HardwareBuilderFactory

# Prefixes identifying sequential PC select signals in pc_wr_mux.
# These select signals choose PC+N increments (sequential flow) as opposed
# to branches/jumps/returns (non-sequential flow).
# Used by both create_pc_redirect_signal() and remove_sequential_pc_entries().
SEQUENTIAL_PC_SELECT_PREFIXES = ('select_pc_plus_', 'select_pc_+_')


@dataclass
class InstructionBufferSpec:
    """Specification for instruction buffer insertion.

    Args:
        imem_node: Name/ID of the instruction memory node to buffer
        pc_node: Name/ID of the program counter node. The optimization will
                 automatically find all imem[pc+N] accesses and compute byte
                 offsets from the PC for each access.
        instr_width_node: Name/ID of the node providing decoded instruction width
                          (in bytes). This is the output of decode that tells the
                          buffer how many bytes to consume for the current instruction.
        fetch_width: Width of each fetch from imem in bits (e.g., 32 for 4-byte fetch)
        buffer_size: Number of fetch-width entries in the buffer FIFO
        data_width: Width of the instruction output in bits (inherited from imem if None)
        address_width: Address width in bits for the fetch address
        buffer_name: Optional custom name (default: {imem_node}_ibuf)
        flush_node: Optional name/ID of a flush signal node (e.g., control_hazard_flush).
                    When asserted, the buffer is flushed and fetch restarts from redirect_addr.
        redirect_node: Optional name/ID of a redirect address node (e.g., branch target).
                       Used with flush_node to set the new fetch address after flush.
    """

    imem_node: str                      # Target memory node name (e.g., 'imem', 'mainmem')
    pc_node: str                        # Program counter node name (e.g., 'pc', 'pc_rd')
    instr_width_node: str               # Node providing decoded instruction width in bytes
    fetch_width: int = 32               # Fetch width in bits (e.g., 32 = 4 bytes per fetch)
    buffer_size: int = 4                # Number of entries in the buffer FIFO
    data_width: Optional[int] = None    # Output data width in bits (inherited from memory if None)
    address_width: int = 32             # Address width in bits
    buffer_name: Optional[str] = None   # Optional custom name (default: {imem_node}_ibuf)
    flush_node: Optional[str] = None    # Optional flush signal node (e.g., 'control_hazard_flush')
    redirect_node: Optional[str] = None # Optional redirect address node (e.g., 'branch_target')

    def __post_init__(self):
        """Validate and set defaults."""
        if self.buffer_name is None:
            self.buffer_name = f"{self.imem_node}_ibuf"

        # Validate fetch_width is positive and a multiple of 8
        if self.fetch_width <= 0:
            raise ValueError(f"fetch_width must be positive, got {self.fetch_width}")
        if self.fetch_width % 8 != 0:
            raise ValueError(f"fetch_width must be a multiple of 8 bits, got {self.fetch_width}")

        # Validate buffer_size is at least 2
        if self.buffer_size < 2:
            raise ValueError(f"buffer_size must be at least 2, got {self.buffer_size}")

    @property
    def fetch_bytes(self) -> int:
        """Number of bytes fetched per cycle."""
        return self.fetch_width // 8

    @property
    def buffer_capacity_bits(self) -> int:
        """Total buffer capacity in bits."""
        return self.buffer_size * self.fetch_width

    @property
    def buffer_capacity_bytes(self) -> int:
        """Total buffer capacity in bytes."""
        return self.buffer_size * self.fetch_bytes

    @property
    def ptr_width(self) -> int:
        """Width of buffer read/write pointers in bits."""
        # Need enough bits to index buffer_size * fetch_bytes bytes
        total_bytes = self.buffer_capacity_bytes
        return (total_bytes - 1).bit_length()

    @property
    def has_flush(self) -> bool:
        """Whether flush+redirect is configured."""
        return self.flush_node is not None

    def __str__(self) -> str:
        s = (f"InstructionBufferSpec(imem={self.imem_node}, "
             f"pc={self.pc_node}, "
             f"fetch_width={self.fetch_width}b, "
             f"buffer_size={self.buffer_size}, "
             f"capacity={self.buffer_capacity_bytes}B, "
             f"instr_width_node={self.instr_width_node}")
        if self.flush_node:
            s += f", flush={self.flush_node}"
        if self.redirect_node:
            s += f", redirect={self.redirect_node}"
        return s + ")"


class InstructionBufferOptimization:
    """
    Inserts an instruction buffer between instruction memory and decode.

    This optimization follows the 7-phase pattern:
    1. ANALYSIS: Find imem node, PC node, detect imem[pc+N] accesses with offsets
    2. PLANNING: Calculate buffer parameters and output port offsets
    3. STRUCTURE: Create buffer node with control signals
    4. HARDWARE: (Backend handles internals)
    5. CONNECTION: Wire buffer to imem, redirect pc+N accesses to ibuf[N] outputs,
                   wire flush+redirect interface
    6. CLEANUP: Remove bypassed edges
    7. TIMING: Re-infer with variable latency
    """

    def __init__(self, graph: ResourceGraph):
        self.graph = graph
        self.hw_factory = HardwareBuilderFactory(graph)
        self.created_nodes: List[Node] = []
        self.created_edges: List[Edge] = []

    def apply(self, spec: InstructionBufferSpec) -> bool:
        """
        Apply instruction buffer optimization to the graph.

        Args:
            spec: Instruction buffer specification

        Returns:
            True if successful, False otherwise
        """
        print(f"Applying instruction buffer optimization: {spec}")

        # PHASE 1: Analysis
        analysis = self._analyze(spec)
        if analysis is None:
            return False

        # PHASE 2: Planning
        buf_params = self._plan(spec, analysis)
        print(f"  Buffer parameters: fetch_width={buf_params['fetch_width']}b, "
              f"buffer_size={buf_params['buffer_size']}, "
              f"capacity={buf_params['buffer_capacity_bytes']}B, "
              f"output_offsets={buf_params['output_offsets']}")

        # PHASE 3: Structure
        buf_node = self._build_structure(spec, buf_params, analysis)
        print(f"  Created buffer node: {buf_node.id}")

        # PHASE 4: Hardware (backend handles internals)
        # No additional hardware generation needed here

        # PHASE 5: Connection
        self._wire_components(spec, buf_node, analysis, buf_params)
        num_accesses = len(analysis['pc_accesses'])
        num_ports = len(buf_params['output_offsets'])
        print(f"  Wired {num_accesses} PC-based read access(es) through {num_ports} buffer port(s)")

        # PHASE 6: Cleanup
        self._cleanup(analysis)

        # PHASE 7: Timing
        self._update_timing()
        print(f"  Updated timing with variable_latency=True")

        print(f"Successfully added instruction buffer '{spec.buffer_name}' "
              f"before memory '{spec.imem_node}'")
        return True

    # =========================================================================
    # PHASE 1: ANALYSIS
    # =========================================================================

    def _analyze(self, spec: InstructionBufferSpec) -> Optional[Dict]:
        """
        Analyze the graph to find the target memory, PC node, detect all
        imem[pc+N] accesses, and find the instruction width node.

        Returns:
            Analysis dict or None if failed
        """
        # Find the memory node
        memory_node = self._find_memory_node(spec.imem_node)
        if memory_node is None:
            print(f"Error: Memory '{spec.imem_node}' not found in graph")
            return None

        # Get memory properties
        bit_width = memory_node.data.get('bit_width', 32)
        addr_width = memory_node.data.get('array_depth', 10)

        print(f"  Found memory '{spec.imem_node}':")
        print(f"    Data width: {bit_width} bits")
        print(f"    Address width: {addr_width} bits")

        # Find the PC node
        pc_node = self._find_node_by_name(spec.pc_node)
        if pc_node is None:
            print(f"Error: PC node '{spec.pc_node}' not found in graph")
            return None

        print(f"  Found PC node: {pc_node.id}")

        # Find the instruction width node
        instr_width_node = self._find_node_by_name(spec.instr_width_node)
        if instr_width_node is None:
            print(f"Error: Instruction width node '{spec.instr_width_node}' not found in graph")
            return None

        print(f"  Found instruction width node: {instr_width_node.id}")

        # Find all read accesses to this memory that use PC-based addressing
        all_read_accesses = self._find_read_accesses(memory_node, spec.imem_node)
        if not all_read_accesses:
            print(f"Error: No read accesses found for memory '{spec.imem_node}'")
            return None

        # Classify accesses: detect which ones are imem[pc], imem[pc+1], etc.
        pc_accesses = self._detect_pc_offset_accesses(
            all_read_accesses, pc_node, spec.imem_node)

        if not pc_accesses:
            print(f"Error: No PC-based read accesses found for memory '{spec.imem_node}' "
                  f"with PC node '{spec.pc_node}'")
            return None

        for acc in pc_accesses:
            print(f"    Detected {spec.imem_node}[{spec.pc_node}+{acc['offset']}] "
                  f"-> {acc['array_access_node'].id}")

        # Find flush and redirect nodes if specified
        flush_node = None
        redirect_node = None

        if spec.flush_node:
            flush_node = self._find_node_by_name(spec.flush_node)
            if flush_node is None:
                print(f"Warning: Flush node '{spec.flush_node}' not found, "
                      f"flush support disabled")
            else:
                print(f"  Found flush node: {flush_node.id}")

        if spec.redirect_node:
            redirect_node = self._find_node_by_name(spec.redirect_node)
            if redirect_node is None:
                print(f"Warning: Redirect node '{spec.redirect_node}' not found, "
                      f"redirect support disabled")
            else:
                print(f"  Found redirect node: {redirect_node.id}")

        return {
            'memory_node': memory_node,
            'bit_width': bit_width,
            'addr_width': addr_width,
            'pc_node': pc_node,
            'instr_width_node': instr_width_node,
            'pc_accesses': pc_accesses,
            'all_read_accesses': all_read_accesses,
            'flush_node': flush_node,
            'redirect_node': redirect_node,
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
                    if (node.data.get('is_memory', False) or
                            node.data.get('type') == 'isa_state mem' or
                            node.data.get('type') == 'isa_state'):
                        return node
        return None

    def _find_node_by_name(self, name: str) -> Optional[Node]:
        """Find a node by name or ID."""
        # Direct ID lookup
        if name in self.graph.nodes:
            return self.graph.nodes[name]
        # Search by name field
        for node in self.graph.nodes.values():
            if node.data and node.data.get('name') == name:
                return node
        return None

    def _find_read_accesses(self, memory_node: Node, memory_name: str) -> List[Dict]:
        """
        Find all read accesses to the given memory.

        Read access pattern:
          memory --[array_base]--> array_access <--[array_index]-- address
          array_access --[assignment]--> target

        Returns:
            List of dicts with keys: array_access_node, address_node, memory_edge, target_edges
        """
        read_accesses = []

        for node in self.graph.nodes.values():
            if node.data and node.data.get('type') == 'array_access':
                # Check if this is a read access
                if node.data.get('access_mode') != 'read':
                    continue

                is_accessing_memory = False
                address_node = None
                memory_edge = None

                for in_edge in node.incoming_edges:
                    edge_type = in_edge.data.get('type') if in_edge.data else None
                    source = in_edge.source
                    source_name = source.data.get('name', source.id) if source.data else source.id

                    if edge_type == 'array_base':
                        if source_name == memory_name or source.id == memory_name:
                            is_accessing_memory = True
                            memory_edge = in_edge
                    elif edge_type == 'array_index':
                        address_node = source

                if is_accessing_memory:
                    target_edges = [
                        edge for edge in node.outgoing_edges
                        if edge.data.get('type') in ('assignment', 'operand', 'ternary_true',
                                                      'ternary_false', 'mux_input')
                    ]

                    if target_edges or node.outgoing_edges:
                        read_accesses.append({
                            'array_access_node': node,
                            'address_node': address_node,
                            'memory_edge': memory_edge,
                            'target_edges': target_edges
                        })

        return read_accesses

    def _detect_pc_offset_accesses(self, read_accesses: List[Dict],
                                   pc_node: Node,
                                   memory_name: str) -> List[Dict]:
        """
        Detect which memory read accesses are PC-relative and compute their
        byte offsets from the PC.

        Patterns detected:
        - imem[pc]        -> offset 0 (address_node is pc directly)
        - imem[pc+1]      -> offset 1 (address_node is operation pc + literal)
        - imem[pc+N]      -> offset N (address_node is operation pc + literal)
        - Intermediate value references (pc updated then read) via _trace_to_pc

        Returns:
            List of dicts extending read_accesses with 'offset' key, sorted by offset
        """
        pc_accesses = []

        for access in read_accesses:
            address_node = access['address_node']
            if address_node is None:
                continue

            offset = self._compute_pc_offset(address_node, pc_node)
            if offset is not None:
                acc = dict(access)
                acc['offset'] = offset
                pc_accesses.append(acc)

        # Sort by offset (byte 0 first)
        pc_accesses.sort(key=lambda a: a['offset'])
        return pc_accesses

    def _compute_pc_offset(self, address_node: Node, pc_node: Node) -> Optional[int]:
        """
        Compute the byte offset of an address expression relative to the PC.

        Handles:
        - Direct PC reference: address_node == pc_node -> offset 0
        - PC + literal: address_node is an operation with pc_node and a literal -> offset = literal
        - Intermediate value chain: trace through assignments to find PC base

        Returns:
            Integer byte offset or None if not PC-relative
        """
        # Case 1: Direct PC reference (imem[pc])
        if address_node.id == pc_node.id:
            return 0

        # Case 2: Check if address_node is a (pc + N) operation
        offset = self._check_pc_plus_literal(address_node, pc_node)
        if offset is not None:
            return offset

        # Case 3: Trace through intermediate assignments
        # The 6502 pattern: pc = pc + 1; imm = mainmem[pc]; uses the UPDATED pc
        # After graph construction, the address might be an intermediate value
        # that traces back to (pc + N) through assignment chains
        offset = self._trace_pc_offset(address_node, pc_node, visited=set())
        if offset is not None:
            return offset

        return None

    def _check_pc_plus_literal(self, node: Node, pc_node: Node) -> Optional[int]:
        """
        Check if a node represents (pc + N) where N is a literal constant.

        Examines the node's incoming operand edges to find if it's an addition
        of the PC and a literal value.

        Returns:
            The literal offset N, or None if not matching
        """
        node_type = node.data.get('type', '') if node.data else ''
        operator = node.data.get('operator', '') if node.data else ''

        if node_type != 'operation' or operator != '+':
            return None

        # Find operands
        left_source = None
        right_source = None
        for edge in node.incoming_edges:
            edge_type = edge.data.get('type') if edge.data else None
            if edge_type == 'operand':
                pos = edge.data.get('operand_position', edge.data.get('operand_index'))
                if pos == 0 or (pos is None and left_source is None):
                    left_source = edge.source
                elif pos == 1 or (pos is None and left_source is not None):
                    right_source = edge.source

        if left_source is None or right_source is None:
            return None

        # Check: pc + literal
        if left_source.id == pc_node.id and self._is_literal(right_source):
            return self._get_literal_value(right_source)

        # Check: literal + pc (commutative)
        if right_source.id == pc_node.id and self._is_literal(left_source):
            return self._get_literal_value(left_source)

        return None

    def _trace_pc_offset(self, node: Node, pc_node: Node,
                         visited: set, depth: int = 0) -> Optional[int]:
        """
        Trace backward through assignment chains and additive chains to find
        PC-relative offset.

        This handles several common ISA patterns:

        Pattern 1 - Read-then-increment (ADC IMM):
            instr = mainmem[pc];  pc = pc + 1;
            imm = mainmem[pc];    pc = pc + 1;
            After graph construction, the second read's address traces back
            through an assignment to (pc + 1), giving offset 1.

        Pattern 2 - Chained addition (JMP ABS):
            pc_plus_1 = pc + 1;
            pc_plus_2 = pc_plus_1 + 1;
            addr_lo = mainmem[pc_plus_1];  // offset 1
            addr_hi = mainmem[pc_plus_2];  // offset 2
            Here pc_plus_2 = (pc + 1) + 1. We trace through the addition:
            one operand is literal 1, the other (pc_plus_1) traces to pc+1,
            so total offset = 1 + 1 = 2.

        Returns:
            Integer offset or None
        """
        if depth > 10 or node.id in visited:
            return None
        visited.add(node.id)

        # Check if this node is directly a PC+N operation
        offset = self._check_pc_plus_literal(node, pc_node)
        if offset is not None:
            return offset

        # Check for chained addition: (expr) + literal or literal + (expr)
        # where expr traces back to pc+M, giving total offset M + literal
        chained = self._check_chained_addition(node, pc_node, visited, depth)
        if chained is not None:
            return chained

        # Trace through incoming assignment edges
        for edge in node.incoming_edges:
            edge_type = edge.data.get('type') if edge.data else None
            if edge_type == 'assignment':
                source = edge.source
                # Check if the source is pc_node (offset 0)
                if source.id == pc_node.id:
                    return 0
                # Recursively check the source
                result = self._trace_pc_offset(source, pc_node, visited, depth + 1)
                if result is not None:
                    return result

        return None

    def _check_chained_addition(self, node: Node, pc_node: Node,
                                visited: set, depth: int) -> Optional[int]:
        """
        Check if a node is (expr + literal) where expr traces to pc+M.

        Handles patterns like: pc_plus_2 = pc_plus_1 + 1
        where pc_plus_1 = pc + 1, giving total offset 2.

        Returns:
            Total offset (M + literal) or None
        """
        node_type = node.data.get('type', '') if node.data else ''
        operator = node.data.get('operator', '') if node.data else ''

        if node_type != 'operation' or operator != '+':
            return None

        # Find operands
        left_source = None
        right_source = None
        for edge in node.incoming_edges:
            edge_type = edge.data.get('type') if edge.data else None
            if edge_type == 'operand':
                pos = edge.data.get('operand_position', edge.data.get('operand_index'))
                if pos == 0 or (pos is None and left_source is None):
                    left_source = edge.source
                elif pos == 1 or (pos is None and left_source is not None):
                    right_source = edge.source

        if left_source is None or right_source is None:
            return None

        # Case: expr + literal (where expr traces to pc+M)
        if self._is_literal(right_source):
            literal_val = self._get_literal_value(right_source)
            if literal_val is not None:
                base_offset = self._trace_pc_offset(
                    left_source, pc_node, set(visited), depth + 1)
                if base_offset is not None:
                    return base_offset + literal_val

        # Case: literal + expr (commutative)
        if self._is_literal(left_source):
            literal_val = self._get_literal_value(left_source)
            if literal_val is not None:
                base_offset = self._trace_pc_offset(
                    right_source, pc_node, set(visited), depth + 1)
                if base_offset is not None:
                    return base_offset + literal_val

        return None

    def _is_literal(self, node: Node) -> bool:
        """Check if a node is a literal/constant value."""
        if not node.data:
            return False
        node_type = node.data.get('type', '')
        return node_type in ('literal', 'binary_literal', 'decimal_literal',
                             'verilog_hex_literal', 'verilog_dec_literal')

    def _get_literal_value(self, node: Node) -> Optional[int]:
        """Extract the integer value from a literal node."""
        if not node.data:
            return None
        value = node.data.get('value')
        if value is not None:
            return int(value)
        # Try parsing from display_name or name
        name = node.data.get('display_name', node.data.get('name', node.id))
        try:
            return int(name)
        except (ValueError, TypeError):
            return None

    # =========================================================================
    # PHASE 2: PLANNING
    # =========================================================================

    def _plan(self, spec: InstructionBufferSpec, analysis: Dict) -> Dict:
        """
        Calculate buffer parameters based on spec and memory analysis.

        Returns:
            Dict with derived buffer parameters including output port offsets
        """
        data_width = spec.data_width
        if data_width is None:
            data_width = analysis['bit_width']
        spec.data_width = data_width

        # Collect unique byte offsets from PC-based accesses
        output_offsets = sorted(set(acc['offset'] for acc in analysis['pc_accesses']))

        return {
            'data_width': data_width,
            'address_width': spec.address_width,
            'fetch_width': spec.fetch_width,
            'buffer_size': spec.buffer_size,
            'fetch_bytes': spec.fetch_bytes,
            'buffer_capacity_bytes': spec.buffer_capacity_bytes,
            'ptr_width': spec.ptr_width,
            'num_read_ports': len(output_offsets),
            'output_offsets': output_offsets,
            'max_offset': max(output_offsets) if output_offsets else 0,
            'has_flush': analysis['flush_node'] is not None,
        }

    # =========================================================================
    # PHASE 3: STRUCTURE
    # =========================================================================

    def _build_structure(self, spec: InstructionBufferSpec, buf_params: Dict,
                         analysis: Dict) -> Node:
        """
        Create the instruction buffer node and control signals.

        Creates:
        - Buffer node with variable_latency=True
        - Control signals: start, idle, complete (compatible with HazardResolver)

        Returns:
            The created buffer node
        """
        buf_node = Node(
            node_id=spec.buffer_name,
            data={
                'type': 'instruction_buffer',
                'name': spec.buffer_name,
                'display_name': spec.buffer_name,
                'imem_node': spec.imem_node,
                'pc_node': spec.pc_node,
                'instr_width_node': spec.instr_width_node,
                'fetch_width': spec.fetch_width,
                'buffer_size': spec.buffer_size,
                'address_width': spec.address_width,
                'data_width': buf_params['data_width'],
                'fetch_bytes': buf_params['fetch_bytes'],
                'buffer_capacity_bytes': buf_params['buffer_capacity_bytes'],
                'ptr_width': buf_params['ptr_width'],
                'num_read_ports': buf_params['num_read_ports'],
                'output_offsets': buf_params['output_offsets'],
                'max_offset': buf_params['max_offset'],
                'has_flush_input': buf_params['has_flush'],
                # Control signal metadata (compatible with memory latency infrastructure)
                'has_start_input': True,
                'has_idle_output': True,
                'has_complete_output': True,
            },
            variable_latency=True,
            latency=1  # Minimum latency (buffer hit case)
        )

        self.graph.add_node(buf_node)
        self.created_nodes.append(buf_node)

        # Create control signals following memory latency patterns
        self._create_control_signals(buf_node, spec)

        return buf_node

    def _create_control_signals(self, buf_node: Node, spec: InstructionBufferSpec):
        """
        Create control signals for the buffer (start, idle, complete).

        Signals:
        - start: Input indicating a new buffer read has started
        - idle: Output indicating buffer has data available (not empty)
        - complete: Output indicating buffer read is done (data valid)
        """
        buf_name = spec.buffer_name

        # Create start signal node (input to buffer)
        start_node = Node(
            node_id=f"{buf_name}_start",
            data={
                'type': 'control_signal',
                'signal_type': 'start',
                'buffer': buf_name,
                'direction': 'input',
                'description': f"Start signal for {buf_name} (new read request)",
                'bit_width': 1
            }
        )
        self.graph.add_node(start_node)
        self.created_nodes.append(start_node)

        # Edge: start -> buffer
        start_edge = Edge(
            source=start_node,
            target=buf_node,
            data={
                'type': 'control',
                'signal_type': 'start',
                'description': f"Start signal for {buf_name}"
            }
        )
        self.graph.add_edge(start_edge)
        self.created_edges.append(start_edge)

        # Create idle signal node (output from buffer)
        idle_node = Node(
            node_id=f"{buf_name}_idle",
            data={
                'type': 'control_signal',
                'signal_type': 'idle',
                'buffer': buf_name,
                'direction': 'output',
                'description': f"Idle signal for {buf_name} (buffer has data or empty ready)",
                'bit_width': 1
            }
        )
        self.graph.add_node(idle_node)
        self.created_nodes.append(idle_node)

        # Edge: buffer -> idle
        idle_edge = Edge(
            source=buf_node,
            target=idle_node,
            data={
                'type': 'control',
                'signal_type': 'idle',
                'description': f"Idle signal from {buf_name}"
            }
        )
        self.graph.add_edge(idle_edge)
        self.created_edges.append(idle_edge)

        # Create complete signal node (output from buffer)
        complete_node = Node(
            node_id=f"{buf_name}_complete",
            data={
                'type': 'control_signal',
                'signal_type': 'complete',
                'buffer': buf_name,
                'direction': 'output',
                'description': f"Completion signal for {buf_name} (data valid at output)",
                'bit_width': 1
            }
        )
        self.graph.add_node(complete_node)
        self.created_nodes.append(complete_node)

        # Edge: buffer -> complete
        complete_edge = Edge(
            source=buf_node,
            target=complete_node,
            data={
                'type': 'control',
                'signal_type': 'complete',
                'description': f"Completion signal from {buf_name}"
            }
        )
        self.graph.add_edge(complete_edge)
        self.created_edges.append(complete_edge)

        # Store signal references in buffer node metadata
        buf_node.data['start_signal'] = start_node.id
        buf_node.data['idle_signal'] = idle_node.id
        buf_node.data['complete_signal'] = complete_node.id

        print(f"  Created control signals: {start_node.id}, {idle_node.id}, {complete_node.id}")

    # =========================================================================
    # PHASE 4: HARDWARE
    # =========================================================================

    # Backend handles all internal hardware (buffer storage, FSM, shifting, etc.)
    # No additional graph nodes needed here

    # =========================================================================
    # PHASE 5: CONNECTION
    # =========================================================================

    def _wire_components(self, spec: InstructionBufferSpec, buf_node: Node,
                         analysis: Dict, buf_params: Dict):
        """
        Wire the buffer node to the memory and redirect read accesses.

        Creates:
        - Fetch interface: buffer -> fetch_addr (output), imem[fetch_addr] -> fetch_data (input)
        - Instruction width input: instr_width_node -> buffer
        - Offset-based data outputs: ibuf[N] for each detected PC+N access
        - Flush + redirect interface (if configured)
        """
        memory_node = analysis['memory_node']
        instr_width_node = analysis['instr_width_node']

        # Wire the fetch interface (buffer fetches from imem)
        self._create_fetch_interface(buf_node, memory_node, spec)

        # Wire the instruction width input (decode tells buffer how many bytes consumed)
        self._wire_instr_width(buf_node, instr_width_node, spec)

        # Process each PC-based read access with its byte offset.
        # Multiple accesses at the same offset share a single output port.
        offset_to_port = {}  # byte_offset -> (port_idx, data_node)
        next_port_idx = 0
        for access in analysis['pc_accesses']:
            byte_offset = access['offset']
            if byte_offset in offset_to_port:
                # Reuse existing port for same offset
                port_idx, data_node = offset_to_port[byte_offset]
                self._redirect_access_to_existing_port(
                    access, data_node, port_idx, byte_offset, spec)
            else:
                # Create a new output port for this offset
                port_idx = next_port_idx
                data_node = self._wire_output_port(
                    buf_node, access, port_idx, byte_offset, spec)
                offset_to_port[byte_offset] = (port_idx, data_node)
                next_port_idx += 1

        # Wire flush + redirect interface if configured
        if analysis['flush_node'] is not None:
            self._wire_flush_redirect(buf_node, analysis['flush_node'],
                                      analysis['redirect_node'], spec)

    def _create_fetch_interface(self, buf_node: Node, memory_node: Node,
                                spec: InstructionBufferSpec):
        """Create the fetch interface between buffer and backing memory.

        The buffer generates fetch addresses and reads fetch_width bits per cycle.

        Creates:
        - fetch_addr: output from buffer (address to read from memory)
        - fetch_data = memory[fetch_addr]: array access from backing memory
        - fetch_req: output from buffer (request signal)
        - fetch_valid: input to buffer (data ready signal)
        """
        buf_name = spec.buffer_name
        imem_name = spec.imem_node

        # Create fetch address node (output from buffer module)
        fetch_addr_name = f"{buf_name}_fetch_addr"
        fetch_addr_node = Node(
            node_id=fetch_addr_name,
            data={
                'type': 'ibuf_fetch_addr',
                'name': fetch_addr_name,
                'display_name': f'{buf_name} fetch addr',
                'bit_width': spec.address_width,
                'buffer_name': buf_name,
            }
        )
        self.graph.add_node(fetch_addr_node)
        self.created_nodes.append(fetch_addr_node)

        # Edge: buffer -> fetch_addr
        self.graph.add_edge(Edge(
            source=buf_node,
            target=fetch_addr_node,
            data={'type': 'ibuf_fetch_addr', 'buffer_interface': True}
        ))

        # Create array access node for memory[fetch_addr]
        fetch_access_name = f"{imem_name}[{fetch_addr_name}]_rd"
        fetch_access_node = Node(
            node_id=fetch_access_name,
            data={
                'type': 'array_access',
                'display_name': fetch_access_name,
                'access_mode': 'read',
                'bit_width': spec.fetch_width,
                'is_buffer_fetch': True,
                'buffer_name': buf_name,
            }
        )
        self.graph.add_node(fetch_access_node)
        self.created_nodes.append(fetch_access_node)

        # Edge: memory -> array_access (array_base)
        self.graph.add_edge(Edge(
            source=memory_node,
            target=fetch_access_node,
            data={'type': 'array_base'}
        ))

        # Edge: fetch_addr -> array_access (array_index)
        self.graph.add_edge(Edge(
            source=fetch_addr_node,
            target=fetch_access_node,
            data={'type': 'array_index'}
        ))

        # Create fetch data node (input to buffer module)
        fetch_data_name = f"{buf_name}_fetch_data"
        fetch_data_node = Node(
            node_id=fetch_data_name,
            data={
                'type': 'var',
                'name': fetch_data_name,
                'display_name': f'{buf_name} fetch data',
                'bit_width': spec.fetch_width,
                'buffer_name': buf_name,
                'buffer_interface': 'fetch_data',
            }
        )
        self.graph.add_node(fetch_data_node)
        self.created_nodes.append(fetch_data_node)

        # Edge: array_access -> fetch_data (assignment)
        self.graph.add_edge(Edge(
            source=fetch_access_node,
            target=fetch_data_node,
            data={'type': 'assignment'}
        ))

        # Edge: fetch_data -> buffer
        self.graph.add_edge(Edge(
            source=fetch_data_node,
            target=buf_node,
            data={'type': 'ibuf_fetch_data', 'buffer_interface': True}
        ))

        # Create fetch request node (output from buffer)
        fetch_req_name = f"{buf_name}_fetch_req"
        fetch_req_node = Node(
            node_id=fetch_req_name,
            data={
                'type': 'ibuf_fetch_req',
                'name': fetch_req_name,
                'bit_width': 1,
                'buffer_name': buf_name,
            }
        )
        self.graph.add_node(fetch_req_node)
        self.created_nodes.append(fetch_req_node)

        # Edge: buffer -> fetch_req
        self.graph.add_edge(Edge(
            source=buf_node,
            target=fetch_req_node,
            data={'type': 'ibuf_fetch_req', 'buffer_interface': True}
        ))

        # Create fetch valid node (input to buffer)
        fetch_valid_name = f"{buf_name}_fetch_valid"
        fetch_valid_node = Node(
            node_id=fetch_valid_name,
            data={
                'type': 'var',
                'name': fetch_valid_name,
                'bit_width': 1,
                'buffer_name': buf_name,
                'buffer_interface': 'fetch_valid',
            }
        )
        self.graph.add_node(fetch_valid_node)
        self.created_nodes.append(fetch_valid_node)

        # Check if backing memory has variable latency
        mem_complete_id = memory_node.data.get('complete_signal')
        if mem_complete_id and mem_complete_id in self.graph.nodes:
            mem_complete = self.graph.nodes[mem_complete_id]
            self.graph.add_edge(Edge(
                source=mem_complete,
                target=fetch_valid_node,
                data={'type': 'assignment'}
            ))
            print(f"  Wired {fetch_valid_name} = {mem_complete_id} (variable latency)")
        else:
            # 1-cycle memory - immediate response
            self.graph.add_edge(Edge(
                source=fetch_req_node,
                target=fetch_valid_node,
                data={'type': 'assignment'}
            ))
            print(f"  Wired {fetch_valid_name} = {fetch_req_name} (1-cycle memory)")

        # Edge: fetch_valid -> buffer
        self.graph.add_edge(Edge(
            source=fetch_valid_node,
            target=buf_node,
            data={'type': 'ibuf_fetch_valid', 'buffer_interface': True}
        ))

        print(f"  Created fetch interface: {fetch_data_name} = {imem_name}[{fetch_addr_name}]")

    def _wire_instr_width(self, buf_node: Node, instr_width_node: Node,
                          spec: InstructionBufferSpec):
        """Wire the instruction width signal from decode to the buffer.

        The decoded instruction width tells the buffer how many bytes to consume
        from the front of the buffer for the current instruction.
        """
        buf_name = spec.buffer_name

        # Create a var node for the instruction width input
        consume_name = f"{buf_name}_consume_bytes"
        consume_node = Node(
            node_id=consume_name,
            data={
                'type': 'var',
                'name': consume_name,
                'display_name': f'{buf_name} consume bytes',
                'bit_width': instr_width_node.data.get('bit_width', 8),
                'buffer_name': buf_name,
                'buffer_interface': 'consume_bytes',
            }
        )
        self.graph.add_node(consume_node)
        self.created_nodes.append(consume_node)

        # Edge: instr_width_node -> consume_node (assignment)
        self.graph.add_edge(Edge(
            source=instr_width_node,
            target=consume_node,
            data={'type': 'assignment'}
        ))

        # Edge: consume_node -> buffer (instruction width input)
        self.graph.add_edge(Edge(
            source=consume_node,
            target=buf_node,
            data={'type': 'ibuf_consume_bytes', 'buffer_interface': True}
        ))

        # Store the consume bytes node reference
        buf_node.data['consume_bytes_signal'] = consume_name

        print(f"  Wired instruction width: {consume_name} = {instr_width_node.id}")

    def _redirect_access_to_existing_port(self, access: Dict, data_node: Node,
                                          port_idx: int, byte_offset: int,
                                          spec: InstructionBufferSpec):
        """Redirect an access that shares a byte offset to an existing output port.

        When multiple array_access nodes have the same PC+N offset, they share
        the same buffer output port rather than creating duplicate ports.
        """
        array_access_node = access['array_access_node']
        memory_edge = access['memory_edge']

        # Redirect consumers of the array_access node to the existing data node
        outgoing_edges = list(array_access_node.outgoing_edges)
        for edge in outgoing_edges:
            target = edge.target
            edge_data = dict(edge.data) if edge.data else {}
            new_edge = Edge(
                source=data_node,
                target=target,
                data=edge_data
            )
            self.graph.add_edge(new_edge)
            self.created_edges.append(new_edge)

            edge.remove_from_nodes()
            if edge.id in self.graph.edges:
                del self.graph.edges[edge.id]

            print(f"    Redirected {array_access_node.id} -> {target.id} "
                  f"to {data_node.id}[offset={byte_offset}] -> {target.id}")

        # Remove the memory->array_access edge (array_base)
        if memory_edge:
            memory_edge.remove_from_nodes()
            if memory_edge.id in self.graph.edges:
                del self.graph.edges[memory_edge.id]

        # Remove address->array_access edges (array_index)
        for edge in list(array_access_node.incoming_edges):
            edge_type = edge.data.get('type') if edge.data else None
            if edge_type == 'array_index':
                edge.remove_from_nodes()
                if edge.id in self.graph.edges:
                    del self.graph.edges[edge.id]

    def _wire_output_port(self, buf_node: Node, access: Dict, port_idx: int,
                          byte_offset: int, spec: InstructionBufferSpec):
        """Wire a single output port from the buffer at a specific byte offset.

        For imem[pc+N], creates ibuf_data_N which reads byte_offset N from the
        buffer's read pointer position, replacing the original array access consumers.

        Returns:
            The created output data node (for reuse by same-offset accesses).
        """
        array_access_node = access['array_access_node']
        memory_edge = access['memory_edge']

        # Create buffer data output node with byte offset metadata
        output_data_name = f"{spec.buffer_name}_data_{port_idx}"
        output_data_node = Node(
            node_id=output_data_name,
            data={
                'type': 'ibuf_read_data',
                'name': output_data_name,
                'display_name': f'{spec.buffer_name}[{byte_offset}]',
                'bit_width': spec.data_width,
                'buffer_name': spec.buffer_name,
                'port_index': port_idx,
                'byte_offset': byte_offset,
            },
            variable_latency=True
        )
        self.graph.add_node(output_data_node)
        self.created_nodes.append(output_data_node)

        # Edge: buffer -> output_data (with byte offset metadata)
        buf_out_edge = Edge(
            source=buf_node,
            target=output_data_node,
            data={
                'type': 'ibuf_read_data',
                'port_index': port_idx,
                'byte_offset': byte_offset,
                'buffer_interface': True
            }
        )
        self.graph.add_edge(buf_out_edge)
        self.created_edges.append(buf_out_edge)

        # Redirect consumers of the array_access node to use buffer data output
        # Original flow: imem[pc+N]_rd -> consumer
        # New flow:      ibuf_data_N  -> consumer
        outgoing_edges = list(array_access_node.outgoing_edges)

        for edge in outgoing_edges:
            target = edge.target
            edge_data = dict(edge.data) if edge.data else {}

            # Create new edge from buffer data to the original target
            new_edge = Edge(
                source=output_data_node,
                target=target,
                data=edge_data
            )
            self.graph.add_edge(new_edge)
            self.created_edges.append(new_edge)

            # Remove the old edge from array_access
            edge.remove_from_nodes()
            if edge.id in self.graph.edges:
                del self.graph.edges[edge.id]

            print(f"    Redirected {array_access_node.id} -> {target.id} "
                  f"to {output_data_name}[offset={byte_offset}] -> {target.id}")

        # Remove the memory->array_access edge (array_base)
        if memory_edge:
            memory_edge.remove_from_nodes()
            if memory_edge.id in self.graph.edges:
                del self.graph.edges[memory_edge.id]

        # Remove the address->array_access edge (array_index)
        for edge in list(array_access_node.incoming_edges):
            edge_type = edge.data.get('type') if edge.data else None
            if edge_type == 'array_index':
                edge.remove_from_nodes()
                if edge.id in self.graph.edges:
                    del self.graph.edges[edge.id]

        # Create valid output node for this port
        valid_name = f"{spec.buffer_name}_valid_{port_idx}"
        valid_node = Node(
            node_id=valid_name,
            data={
                'type': 'ibuf_valid',
                'name': valid_name,
                'display_name': f'{spec.buffer_name} valid port {port_idx}',
                'bit_width': 1,
                'buffer_name': spec.buffer_name,
                'port_index': port_idx,
                'byte_offset': byte_offset,
            }
        )
        self.graph.add_node(valid_node)
        self.created_nodes.append(valid_node)

        # Edge: buffer -> valid
        valid_edge = Edge(
            source=buf_node,
            target=valid_node,
            data={
                'type': 'ibuf_valid',
                'port_index': port_idx,
                'byte_offset': byte_offset,
                'buffer_interface': True
            }
        )
        self.graph.add_edge(valid_edge)
        self.created_edges.append(valid_edge)

        # Connect control signals for port 0 (primary port)
        if port_idx == 0:
            # complete = valid_0 (complete when data valid)
            complete_id = buf_node.data.get('complete_signal')
            if complete_id and complete_id in self.graph.nodes:
                complete_node = self.graph.nodes[complete_id]
                complete_node.data['type'] = 'var'
                complete_node.data['name'] = complete_id
                complete_edge = Edge(
                    source=valid_node,
                    target=complete_node,
                    data={'type': 'assignment'}
                )
                self.graph.add_edge(complete_edge)
                self.created_edges.append(complete_edge)

            # idle = 1'b1 (always ready, FSM handles internally)
            idle_id = buf_node.data.get('idle_signal')
            if idle_id and idle_id in self.graph.nodes:
                idle_node = self.graph.nodes[idle_id]
                idle_node.data['type'] = 'var'
                idle_node.data['name'] = idle_id

                idle_const_id = f"{spec.buffer_name}_always_idle"
                idle_const_node = Node(
                    node_id=idle_const_id,
                    data={
                        'type': 'literal',
                        'value': 1,
                        'bit_width': 1,
                        'display_name': f'{spec.buffer_name} always idle'
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

        return output_data_node

    def _wire_flush_redirect(self, buf_node: Node, flush_node: Node,
                             redirect_node: Optional[Node],
                             spec: InstructionBufferSpec):
        """Wire the flush and redirect interface for branch misprediction recovery.

        Creates:
        - flush signal: input to buffer (clears buffer contents)
        - redirect_addr: input to buffer (new fetch address after flush)
        """
        buf_name = spec.buffer_name

        # Wire flush signal -> buffer
        flush_var_name = f"{buf_name}_flush"
        flush_var_node = Node(
            node_id=flush_var_name,
            data={
                'type': 'var',
                'name': flush_var_name,
                'display_name': f'{buf_name} flush',
                'bit_width': 1,
                'buffer_name': buf_name,
                'buffer_interface': 'flush',
            }
        )
        self.graph.add_node(flush_var_node)
        self.created_nodes.append(flush_var_node)

        # Edge: flush_node -> flush_var (assignment)
        self.graph.add_edge(Edge(
            source=flush_node,
            target=flush_var_node,
            data={'type': 'assignment'}
        ))

        # Edge: flush_var -> buffer (ibuf_flush)
        self.graph.add_edge(Edge(
            source=flush_var_node,
            target=buf_node,
            data={'type': 'ibuf_flush', 'buffer_interface': True}
        ))

        buf_node.data['flush_signal'] = flush_var_name
        buf_node.data['flush_signals'] = [flush_var_name]
        print(f"  Wired flush: {flush_var_name} = {flush_node.id}")

        # Wire redirect address -> buffer
        if redirect_node is not None:
            redirect_var_name = f"{buf_name}_redirect_addr"
            redirect_var_node = Node(
                node_id=redirect_var_name,
                data={
                    'type': 'var',
                    'name': redirect_var_name,
                    'display_name': f'{buf_name} redirect addr',
                    'bit_width': spec.address_width,
                    'buffer_name': buf_name,
                    'buffer_interface': 'redirect_addr',
                }
            )
            self.graph.add_node(redirect_var_node)
            self.created_nodes.append(redirect_var_node)

            # Edge: redirect_node -> redirect_var (assignment)
            self.graph.add_edge(Edge(
                source=redirect_node,
                target=redirect_var_node,
                data={'type': 'assignment'}
            ))

            # Edge: redirect_var -> buffer (ibuf_redirect_addr)
            self.graph.add_edge(Edge(
                source=redirect_var_node,
                target=buf_node,
                data={'type': 'ibuf_redirect_addr', 'buffer_interface': True}
            ))

            buf_node.data['redirect_addr_signal'] = redirect_var_name
            print(f"  Wired redirect: {redirect_var_name} = {redirect_node.id}")

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
        """Re-infer timing with buffer's variable latency."""
        self.graph.infer_uarch_time(force_reinfer=True)


def apply_instruction_buffer(graph: ResourceGraph, spec: InstructionBufferSpec) -> bool:
    """
    Convenience function to apply instruction buffer optimization.

    Args:
        graph: Resource graph to modify
        spec: Instruction buffer specification

    Returns:
        True if successful, False otherwise

    Example:
        spec = InstructionBufferSpec(
            imem_node='imem',
            pc_node='pc',
            instr_width_node='instr_len',
            fetch_width=32,
            buffer_size=4,
            address_width=32,
            flush_node='control_hazard_flush',
            redirect_node='branch_target'
        )
        success = apply_instruction_buffer(graph, spec)
    """
    optimization = InstructionBufferOptimization(graph)
    return optimization.apply(spec)


def create_instr_length_node(graph: ResourceGraph,
                             node_name: str = 'ibuf_instr_length') -> Optional[str]:
    """
    Create an instruction length node from the merged graph's PC increment
    select signals.

    After graph_merger creates a pc_increment_mux, the merged graph has:
    - select_pc_plus_N nodes (one-hot enables for instructions of length N)
    - pc_increment_N literal nodes (constant values 1, 2, 3, ...)

    This function creates a new node that outputs the numeric instruction
    length in bytes, suitable for use as the instr_width_node in an
    InstructionBufferSpec.

    The output is: (select_pc_plus_1 & 1) | (select_pc_plus_2 & 2) | ...

    Args:
        graph: Merged ResourceGraph (must have been created by merge_instructions
               with variable-length instruction support)
        node_name: Name for the created node (default: 'ibuf_instr_length')

    Returns:
        Node ID of the created instruction length node, or None if the
        required select signals weren't found.
    """
    # Find all select_pc_plus_N and enable signals by length
    length_selects = {}  # length -> select node

    for node_id, node in graph.nodes.items():
        # Look for select_pc_plus_N OR nodes (multi-instruction groups)
        if node_id.startswith('select_pc_plus_'):
            try:
                length = int(node_id.split('select_pc_plus_')[1])
                length_selects[length] = node
            except (ValueError, IndexError):
                continue

    # Also check for single-instruction lengths using instruction_enable nodes
    # that feed directly into the pc_increment_mux
    pc_mux_node = graph.nodes.get('pc_increment_mux')
    if pc_mux_node:
        for edge in pc_mux_node.incoming_edges:
            metadata = edge.data if edge.data else {}
            instr_len = metadata.get('instruction_length')
            if instr_len is not None and instr_len not in length_selects:
                # The select signal is the mux_select edge source
                if metadata.get('type') == 'mux_select':
                    length_selects[instr_len] = edge.source

    if not length_selects:
        print(f"Warning: No select_pc_plus_N signals found in graph. "
              f"Cannot create instruction length node.")
        return None

    print(f"Creating instruction length node '{node_name}' from "
          f"length selects: {sorted(length_selects.keys())}")

    # Determine bit width needed to encode the max instruction length
    max_length = max(length_selects.keys())
    bit_width = max(max_length.bit_length(), 1)

    # Create the instruction length output node
    length_node = Node(
        node_id=node_name,
        data={
            'type': 'var',
            'name': node_name,
            'display_name': 'instruction length (bytes)',
            'bit_width': bit_width,
            'is_instruction_length': True,
        }
    )
    graph.add_node(length_node)

    # For each length group, create: literal(N) AND select_signal -> contribute to output
    # Use a one-hot OR pattern: result = (sel_1 ? 1 : 0) | (sel_2 ? 2 : 0) | ...
    contrib_nodes = []
    for length in sorted(length_selects.keys()):
        select_node = length_selects[length]

        # Create literal for this length value
        lit_id = f"{node_name}_lit_{length}"
        lit_node = Node(lit_id, {
            'type': 'literal',
            'value': length,
            'bit_width': bit_width,
            'display_name': str(length)
        })
        graph.add_node(lit_node)

        # Create zero literal
        zero_id = f"{node_name}_zero_{length}"
        zero_node = Node(zero_id, {
            'type': 'literal',
            'value': 0,
            'bit_width': bit_width,
            'display_name': '0'
        })
        graph.add_node(zero_node)

        # Create ternary: select ? length : 0
        tern_id = f"{node_name}_sel_{length}"
        tern_node = Node(tern_id, {
            'type': 'ternary_op',
            'display_name': f'{select_node.id} ? {length} : 0',
            'bit_width': bit_width,
        })
        graph.add_node(tern_node)

        # Wire condition -> ternary
        graph.add_edge(Edge(select_node, tern_node,
            data={'type': 'ternary_condition'}))
        graph.add_edge(Edge(lit_node, tern_node,
            data={'type': 'ternary_true'}))
        graph.add_edge(Edge(zero_node, tern_node,
            data={'type': 'ternary_false'}))

        contrib_nodes.append(tern_node)
        print(f"  Length {length}: {select_node.id} ? {length} : 0")

    # Combine contributions with OR
    if len(contrib_nodes) == 1:
        # Single length - connect directly
        graph.add_edge(Edge(contrib_nodes[0], length_node,
            data={'type': 'assignment'}))
    else:
        # Multiple lengths - OR them together
        current = contrib_nodes[0]
        for i in range(1, len(contrib_nodes)):
            or_id = f"{node_name}_or_{i}"
            or_node = Node(or_id, {
                'type': 'operation',
                'operator': '|',
                'display_name': f'{node_name} OR stage {i}',
                'bit_width': bit_width,
            })
            graph.add_node(or_node)
            graph.add_edge(Edge(current, or_node,
                data={'type': 'operand', 'operand_position': 0}))
            graph.add_edge(Edge(contrib_nodes[i], or_node,
                data={'type': 'operand', 'operand_position': 1}))
            current = or_node

        # Final OR output -> length_node
        graph.add_edge(Edge(current, length_node,
            data={'type': 'assignment'}))

    print(f"  Created {node_name} with bit_width={bit_width}")
    return node_name


def create_pc_redirect_signal(graph: ResourceGraph,
                              pc_wr_mux_name: str = 'pc_wr_mux',
                              node_name: str = 'ibuf_pc_redirect') -> Optional[str]:
    """Create a 1-bit signal that is asserted when the PC takes a non-sequential value.

    Examines the pc_wr_mux node in the merged graph and ORs together all the
    mux select signals that correspond to non-sequential PC changes (branches,
    jumps, returns, interrupts).  Sequential PC increments (select_pc_plus_N,
    select_pc_+_1_pc_merged, etc.) are excluded.

    Returns the node ID of the created signal, or None if the mux was not found.
    """
    mux_node = graph.nodes.get(pc_wr_mux_name)
    if mux_node is None:
        print(f"Warning: {pc_wr_mux_name} not found, cannot create redirect signal")
        return None

    # Collect all mux_select edges and classify them as sequential or non-sequential.
    # Sequential selects match these patterns (they just choose a PC+N increment):
    #   select_pc_plus_N, select_pc_+_1_pc_merged, select_pc_+_1_+_1_pc_merged, etc.
    sequential_prefixes = SEQUENTIAL_PC_SELECT_PREFIXES

    non_seq_selects = []
    for edge in mux_node.incoming_edges:
        if edge.data.get('type') != 'mux_select':
            continue
        src_id = edge.source.id
        is_sequential = any(src_id.startswith(p) for p in sequential_prefixes)
        if not is_sequential:
            non_seq_selects.append(edge.source)

    if not non_seq_selects:
        print(f"Warning: No non-sequential PC select signals found in {pc_wr_mux_name}")
        return None

    print(f"Creating PC redirect signal '{node_name}' from {len(non_seq_selects)} "
          f"non-sequential selects:")
    for s in non_seq_selects:
        print(f"  {s.id}")

    # Build an OR-tree of all non-sequential select signals
    if len(non_seq_selects) == 1:
        # Single signal – just create a var alias
        redirect_node = Node(node_name, {
            'type': 'var', 'name': node_name, 'bit_width': 1,
            'display_name': 'PC redirect (flush)',
        })
        graph.add_node(redirect_node)
        graph.add_edge(Edge(non_seq_selects[0], redirect_node,
                            data={'type': 'assignment'}))
    else:
        current = non_seq_selects[0]
        for i in range(1, len(non_seq_selects)):
            or_id = f"{node_name}_or_{i}"
            or_node = Node(or_id, {
                'type': 'operation', 'operator': '|',
                'display_name': f'{node_name} OR stage {i}',
                'bit_width': 1,
            })
            graph.add_node(or_node)
            graph.add_edge(Edge(current, or_node,
                                data={'type': 'operand', 'operand_position': 0}))
            graph.add_edge(Edge(non_seq_selects[i], or_node,
                                data={'type': 'operand', 'operand_position': 1}))
            current = or_node

        redirect_node = Node(node_name, {
            'type': 'var', 'name': node_name, 'bit_width': 1,
            'display_name': 'PC redirect (flush)',
        })
        graph.add_node(redirect_node)
        graph.add_edge(Edge(current, redirect_node,
                            data={'type': 'assignment'}))

    print(f"  Created {node_name}")
    return node_name


def remove_sequential_pc_entries(graph: ResourceGraph,
                                  pc_wr_mux_name: str = 'pc_wr_mux') -> int:
    """Remove sequential PC override entries from the PC write mux.

    In a merged single-cycle graph, pc_wr_mux has explicit entries for
    sequential PC flow (e.g., select_pc_+_1 -> (pc+1), select_pc_plus_2 -> pc_plus_2).
    When an instruction buffer is present, sequential flow is handled by
    pc_increment_mux (the mux_default_input of pc_wr_mux). The explicit
    sequential entries are redundant and harmful in a pipeline: they have
    higher priority than branch/jump entries, causing stale piped values
    to override correct non-sequential targets.

    Returns the number of entries removed.
    """
    mux_node = graph.nodes.get(pc_wr_mux_name)
    if mux_node is None:
        return 0

    removed = 0
    # First pass: find sequential mux_select edges and their select_index
    seq_indices = []  # (select_edge, select_index)
    for edge in list(mux_node.incoming_edges):
        if edge.data.get('type') != 'mux_select':
            continue
        src_id = edge.source.id
        is_seq = any(src_id.startswith(p) for p in SEQUENTIAL_PC_SELECT_PREFIXES)
        if is_seq:
            seq_indices.append((edge, edge.data.get('select_index')))

    # Second pass: remove each sequential entry (select + paired input)
    for sel_edge, idx in seq_indices:
        src_id = sel_edge.source.id
        graph.remove_edge(sel_edge.id)
        removed += 1
        print(f"  Removed sequential mux_select: {src_id}")
        # Remove the matching mux_input edge (paired by input_index == select_index)
        for e2 in list(mux_node.incoming_edges):
            if (e2.data.get('type') == 'mux_input' and
                e2.data.get('input_index') == idx):
                graph.remove_edge(e2.id)
                removed += 1
                print(f"  Removed sequential mux_input: {e2.source.id}")
                break
        # Remove orphaned select node
        sel_node = graph.nodes.get(src_id)
        if sel_node and not sel_node.outgoing_edges:
            graph.remove_node(src_id)
            print(f"  Removed orphaned node: {src_id}")

    return removed


def add_pc_increment_default(graph: ResourceGraph,
                              pc_rd_name: str = 'pc_rd',
                              mux_name: str = 'pc_increment_mux') -> bool:
    """Add a default input to pc_increment_mux so it holds pc_rd when idle.

    The pc_increment_mux is a one-hot OR-based mux that outputs 0 when no
    select is active (during pipeline fill/flush). Adding pc_rd as the
    mux_default_input makes it hold the current PC value when idle.

    Returns True if the default was added (or already present).
    """
    mux_node = graph.nodes.get(mux_name)
    pc_rd = graph.nodes.get(pc_rd_name)
    if mux_node is None or pc_rd is None:
        return False

    for edge in mux_node.incoming_edges:
        if edge.data.get('type') == 'mux_default_input':
            return True  # Already has default

    graph.add_edge(Edge(pc_rd, mux_node, data={'type': 'mux_default_input'}))
    print(f"  Added {pc_rd_name} as mux_default_input to {mux_name}")
    return True


def wire_ibuf_pipeline_control(graph: ResourceGraph,
                                buffer_name: str = 'mainmem_ibuf',
                                flush_signal: str = 'control_hazard_flush',
                                redirect_source: str = 'pc_wr_mux',
                                stall_signal: str = 'PIPE_Decode_stall_ctrl',
                                pc_wr_pipe: str = 'PIPE_Decode_pc_wr_PIPE',
                                decode_valid: str = 'PIPE_Decode_valid_PIPE',
                                pc_reset_value: str = 'reset_pc_rd') -> bool:
    """Wire pipeline control signals to the instruction buffer.

    Called after pipeline transforms, hazard resolution, and control hazard
    handling have created the necessary signals. Wires:
    1. Flush: control_hazard_flush -> ibuf flush input
    2. Redirect: pc_wr_mux -> ibuf redirect address
    3. Consume stall: PIPE_Decode_stall_ctrl -> ibuf consume_stall_signal
    4. PC pipe valid gate: gate PIPE_Decode_pc_wr_PIPE with Decode validity
       so the pc_wr -> pc_increment_mux feedback loop doesn't corrupt during
       invalid cycles (pipeline fill/flush)

    Returns True if all signals were successfully wired.
    """
    buf_node = graph.nodes.get(buffer_name)
    if buf_node is None:
        print(f"  WARNING: {buffer_name} not found")
        return False

    success = True

    # 1. Wire flush signal
    flush_node = graph.nodes.get(flush_signal)
    if flush_node is None:
        for alt in ['pipeline_flush', 'branch_flush']:
            flush_node = graph.nodes.get(alt)
            if flush_node:
                break

    if flush_node is not None:
        flush_var_name = f'{buffer_name}_flush'
        if flush_var_name not in graph.nodes:
            flush_var = Node(flush_var_name, {
                'type': 'var', 'name': flush_var_name, 'bit_width': 1,
                'buffer_name': buffer_name, 'buffer_interface': 'flush',
            })
            graph.add_node(flush_var)
            graph.add_edge(Edge(flush_node, flush_var, data={'type': 'assignment'}))
            graph.add_edge(Edge(flush_var, buf_node,
                data={'type': 'ibuf_flush', 'buffer_interface': True}))
            buf_node.data['flush_signal'] = flush_var_name
            buf_node.data['flush_signals'] = [flush_var_name]
            buf_node.data['has_flush_input'] = True
            print(f"  Wired flush: {flush_var_name} = {flush_node.id}")
    else:
        print(f"  WARNING: No flush signal found")
        success = False

    # 2. Wire redirect address
    redirect_node = graph.nodes.get(redirect_source)
    if redirect_node is not None:
        redirect_var_name = f'{buffer_name}_redirect_addr'
        if redirect_var_name not in graph.nodes:
            redirect_var = Node(redirect_var_name, {
                'type': 'var', 'name': redirect_var_name, 'bit_width': 16,
                'buffer_name': buffer_name, 'buffer_interface': 'redirect_addr',
            })
            graph.add_node(redirect_var)
            graph.add_edge(Edge(redirect_node, redirect_var,
                data={'type': 'assignment'}))
            graph.add_edge(Edge(redirect_var, buf_node,
                data={'type': 'ibuf_redirect_addr', 'buffer_interface': True}))
            buf_node.data['redirect_addr_signal'] = redirect_var_name
            print(f"  Wired redirect: {redirect_var_name} = {redirect_node.id}")
    else:
        print(f"  WARNING: {redirect_source} not found")
        success = False

    # 3. Wire consume stall
    stall_node = graph.nodes.get(stall_signal)
    if stall_node is not None:
        buf_node.data['consume_stall_signal'] = stall_signal
        print(f"  Set consume_stall_signal = {stall_signal}")
    else:
        print(f"  WARNING: {stall_signal} not found")
        success = False

    # 4. Gate pc_wr pipeline register with Decode validity.
    # The ibuf creates a feedback loop: pc_wr -> pc_increment_mux -> pc_wr_mux
    # -> pc_wr.  During invalid Decode cycles (pipeline fill/flush), false
    # instruction enables corrupt this feedback.  Adding a valid_gate ensures
    # the pipe register only captures pc_wr when Decode has a valid instruction.
    # The reset value is set to match pc_rd's reset so the held value during
    # fill equals the initial PC address.
    pc_wr_node = graph.nodes.get(pc_wr_pipe)
    valid_node = graph.nodes.get(decode_valid)
    if pc_wr_node is not None and valid_node is not None:
        has_gate = any(e.data.get('type') == 'valid_gate'
                       for e in pc_wr_node.incoming_edges)
        if not has_gate:
            graph.add_edge(Edge(valid_node, pc_wr_node,
                                data={'type': 'valid_gate'}))
            pc_wr_node.data['reset_value'] = pc_reset_value
            print(f"  Gated {pc_wr_pipe} with {decode_valid}")
            print(f"  Set reset value to {pc_reset_value}")
    elif pc_wr_node is None:
        print(f"  WARNING: {pc_wr_pipe} not found")
    elif valid_node is None:
        print(f"  WARNING: {decode_valid} not found")

    return success


def get_ibuf_nodes(graph: ResourceGraph) -> List[Node]:
    """Get all instruction buffer nodes in the graph."""
    return [
        node for node in graph.nodes.values()
        if node.data and node.data.get('type') == 'instruction_buffer'
    ]


def get_ibuf_info(graph: ResourceGraph, buffer_name: str) -> Optional[Dict]:
    """
    Get information about an instruction buffer node.

    Args:
        graph: Resource graph
        buffer_name: Name of the instruction buffer

    Returns:
        Dict with buffer info or None if not found
    """
    if buffer_name not in graph.nodes:
        return None

    buf_node = graph.nodes[buffer_name]
    if buf_node.data.get('type') != 'instruction_buffer':
        return None

    return {
        'name': buf_node.data.get('name'),
        'imem_node': buf_node.data.get('imem_node'),
        'pc_node': buf_node.data.get('pc_node'),
        'instr_width_node': buf_node.data.get('instr_width_node'),
        'fetch_width': buf_node.data.get('fetch_width'),
        'buffer_size': buf_node.data.get('buffer_size'),
        'data_width': buf_node.data.get('data_width'),
        'address_width': buf_node.data.get('address_width'),
        'fetch_bytes': buf_node.data.get('fetch_bytes'),
        'buffer_capacity_bytes': buf_node.data.get('buffer_capacity_bytes'),
        'ptr_width': buf_node.data.get('ptr_width'),
        'num_read_ports': buf_node.data.get('num_read_ports'),
        'output_offsets': buf_node.data.get('output_offsets'),
        'start_signal': buf_node.data.get('start_signal'),
        'idle_signal': buf_node.data.get('idle_signal'),
        'complete_signal': buf_node.data.get('complete_signal'),
        'consume_bytes_signal': buf_node.data.get('consume_bytes_signal'),
        'flush_signal': buf_node.data.get('flush_signal'),
        'redirect_addr_signal': buf_node.data.get('redirect_addr_signal'),
    }
