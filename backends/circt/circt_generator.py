"""
CIRCT MLIR Backend Generator for ISAComp

This module generates CIRCT MLIR (Multi-Level Intermediate Representation)
from a ResourceGraph. It uses the hw, comb, and seq dialects to represent
hardware modules, combinational logic, and sequential logic respectively.

The generated MLIR can be further processed by CIRCT tools like firtool
to generate Verilog, FIRRTL, or other hardware description formats.
"""

from typing import Dict, Set, List, Tuple, Optional
from core.resource_graph import ResourceGraph, Node, Edge


class CIRCTGenerator:
    """Generates CIRCT MLIR from a ResourceGraph."""

    def __init__(self, graph: ResourceGraph, module_name: str = "processor"):
        """
        Initialize the CIRCT generator.

        Args:
            graph: The ResourceGraph to generate MLIR from
            module_name: Name of the top-level hardware module
        """
        self.graph = graph
        self.module_name = module_name
        self.indent_level = 0
        self.lines: List[str] = []

        # Track node types for generation
        self.registers: Set[str] = set()
        self.wires: Set[str] = set()
        self.memories: Dict[str, Tuple[int, int]] = {}  # name -> (width, depth)

        # Track signal widths
        self.signal_widths: Dict[str, int] = {}

        # Value mapping for MLIR SSA (Static Single Assignment) form
        self.value_map: Dict[str, str] = {}
        self.ssa_counter = 0

    def _indent(self) -> str:
        """Return the current indentation string."""
        return "  " * self.indent_level

    def _emit(self, line: str):
        """Emit a line with current indentation."""
        if line.strip():
            self.lines.append(self._indent() + line)
        else:
            self.lines.append("")

    def _sanitize_ssa_name(self, name: str) -> str:
        """Sanitize a name to be a valid SSA identifier."""
        # Replace invalid characters with underscore
        import re
        # Replace anything that's not alphanumeric or underscore
        sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', name)
        # If it starts with a digit, prefix with underscore
        if sanitized and sanitized[0].isdigit():
            sanitized = '_' + sanitized
        # Remove consecutive underscores
        sanitized = re.sub(r'_+', '_', sanitized)
        return sanitized

    def _get_fresh_ssa_value(self, prefix: str = "v") -> str:
        """Generate a fresh SSA value name."""
        sanitized_prefix = self._sanitize_ssa_name(prefix) if prefix else "v"
        name = f"%{sanitized_prefix}_{self.ssa_counter}"
        self.ssa_counter += 1
        return name

    def _get_or_create_value(self, node_id: str) -> str:
        """Get or create an SSA value for a node."""
        if node_id in self.value_map:
            return self.value_map[node_id]

        # Use sanitized node_id as prefix
        value = self._get_fresh_ssa_value(node_id)
        self.value_map[node_id] = value
        return value

    def _get_width(self, node: Node) -> int:
        """
        Determine the bit width of a node's output.

        Args:
            node: The node to analyze

        Returns:
            The bit width (default 32 if not specified)
        """
        node_type = node.data.get('type', '')

        # For var nodes, check if we've explicitly set the width during generation
        # (e.g., for narrow loads from memory). This takes precedence over following
        # the alias chain.
        if node_type == 'var':
            if node.id in self.signal_widths:
                # Check if this is an explicitly extracted width (8 or 16 for narrow loads)
                stored_width = self.signal_widths[node.id]
                node_width = node.data.get('bit_width') or node.data.get('width')
                # If stored width matches declared width, use it (it was explicitly set)
                if node_width and stored_width == node_width:
                    return stored_width
            # Otherwise follow the alias chain to get width from source
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'assignment':
                    # Recursively get width from source
                    return self._get_width(edge.source)
            # If no assignment, try first incoming edge
            if node.incoming_edges:
                return self._get_width(list(node.incoming_edges)[0].source)
            # No source found, will fall through to other checks

        # For operations, prioritize dynamically computed widths (stored in signal_widths)
        # over static bit_width from node.data. This is critical for 64-bit architectures
        # where operations may need to be widened based on operand widths.
        if node_type == 'operation':
            if node.id in self.signal_widths:
                return self.signal_widths[node.id]
            # Fall back to node.data['bit_width'] if no dynamic width was computed
            if 'bit_width' in node.data:
                return node.data['bit_width']

        # Pipeline stall controller always produces 1-bit output
        if node_type == 'pipeline_stall_controller':
            return 1

        # For pipeline registers, inherit width from the data input source
        if node_type == 'pipeline_register':
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'pipeline_input':
                    source_width = self._get_width(edge.source)
                    if source_width:
                        return source_width
            # Fallthrough to other checks if no pipeline_input found

        # For certain node types, always recalculate width dynamically
        # Don't use stored width as it might be incorrect due to propagation
        # Multiplexer nodes have output_width in their data that should be used
        if node_type not in ['concatenation', 'repetition', 'bit_slice', 'multiplexer', 'operation']:
            if node.id in self.signal_widths:
                return self.signal_widths[node.id]

        # Check node data for width information
        if 'output_width' in node.data:
            return node.data['output_width']
        if 'data_width' in node.data:
            return node.data['data_width']
        if 'width' in node.data:
            return node.data['width']
        if 'bit_width' in node.data:
            return node.data['bit_width']

        # For bit slices, compute width from range
        if node.data.get('type') == 'bit_slice':
            if 'expression' in node.data and 'range' in node.data['expression']:
                high_bit, low_bit = node.data['expression']['range']
                return high_bit - low_bit + 1
            else:
                # Try to parse from node ID like "instr[19:15]"
                import re
                match = re.search(r'\[(\d+):(\d+)\]', node.id)
                if match:
                    high_bit = int(match.group(1))
                    low_bit = int(match.group(2))
                    return high_bit - low_bit + 1

        # For literals, infer from value
        if node.data.get('type') == 'literal':
            value = node.data.get('value', 0)
            if isinstance(value, int):
                if value == 0:
                    return 1
                return value.bit_length()

        # For repetitions, compute width from count * source width
        if node.data.get('type') == 'repetition':
            count = node.data.get('count', node.data.get('repetitions', 1))
            # Get source width
            source_edge = next((e for e in node.incoming_edges), None)
            if source_edge:
                source_width = self._get_width(source_edge.source)
                return count * source_width

        # For concatenations, sum of all part widths
        if node.data.get('type') == 'concatenation':
            total = 0
            for edge in node.incoming_edges:
                w = self._get_width(edge.source)
                if w is not None:
                    total += w
            if total > 0:
                return total

        # For multiplexer nodes, infer width from data inputs (similar to _generate_multiplexer)
        if node.data.get('type') == 'multiplexer':
            widths = []
            for edge in node.incoming_edges:
                edge_type = edge.data.get('type', '')
                if edge_type in ['mux_input', 'mux_default_input']:
                    w = self._get_width(edge.source)
                    if w:
                        widths.append(w)
            if widths:
                return max(widths)

        # For ternary_op nodes (like pc_recovery_mux), infer width from the data inputs
        # AND from architectural state targets (for SLT which writes to register file)
        if node.data.get('type') == 'ternary_op':
            widths = []
            for edge in node.incoming_edges:
                edge_type = edge.data.get('type', '')
                if edge_type in ['ternary_true', 'ternary_false']:
                    src = edge.source
                    # For literals, don't use their "natural" width - they'll be extended
                    if src.data.get('type') != 'literal':
                        w = self._get_width(src)
                        if w:
                            widths.append(w)
            # Also check outgoing edges - if the ternary result feeds an architectural
            # state (like rf), use that width (similar to VHDL generator logic)
            for edge in node.outgoing_edges:
                target = edge.target
                if target.is_arch_state:
                    arch_width = target.data.get('bit_width')
                    if arch_width:
                        widths.append(arch_width)
                    else:
                        # For _wr ports without bit_width, check corresponding _rd port
                        if target.id.endswith('_wr'):
                            rd_id = target.id[:-3] + '_rd'
                            rd_node = self.graph.nodes.get(rd_id)
                            if rd_node and rd_node.data.get('bit_width'):
                                widths.append(rd_node.data['bit_width'])
                # Also check if target is a var that eventually feeds arch state
                elif target.data.get('type') == 'var':
                    for out_edge in target.outgoing_edges:
                        if out_edge.target.is_arch_state:
                            arch_width = out_edge.target.data.get('bit_width')
                            if arch_width:
                                widths.append(arch_width)
                            else:
                                # Check corresponding _rd port
                                if out_edge.target.id.endswith('_wr'):
                                    rd_id = out_edge.target.id[:-3] + '_rd'
                                    rd_node = self.graph.nodes.get(rd_id)
                                    if rd_node and rd_node.data.get('bit_width'):
                                        widths.append(rd_node.data['bit_width'])
            if widths:
                return max(widths)

        # Default width
        return 32

    def _mlir_type(self, width: Optional[int]) -> str:
        """Convert bit width to MLIR type string."""
        if width is None:
            width = 32  # Default width
        return f"i{width}"

    def _infer_width_from_usage(self, ssa_val: str) -> int:
        """Infer width from how a value is used in the generated lines."""
        import re
        for line in self.lines:
            if ssa_val in line:
                # Check if it's used as mux selector (first arg after comb.mux)
                mux_match = re.search(r'comb\.mux\s+' + re.escape(ssa_val) + r',', line)
                if mux_match:
                    return 1  # Mux selector is always 1-bit

                # Check if there's a type annotation we can use
                type_match = re.search(re.escape(ssa_val) + r'\s*:\s*i(\d+)', line)
                if type_match:
                    return int(type_match.group(1))

        return 32  # Default

    def _get_memory_write_signals(self, memory_name: str):
        """
        Find signals needed for memory write-to-read forwarding structurally.

        Uses the shared write port's structure to find write enable, address, and data.

        Args:
            memory_name: Name of the memory (e.g., 'rf', 'dmem')

        Returns:
            Tuple of (write_enable_ssa, write_addr_ssa, write_data_ssa, addr_width, data_width) or None if not found.
        """
        # Find the shared write port for this memory
        shared_wr = self.graph.nodes.get(f'{memory_name}_shared_wr')
        if not shared_wr or shared_wr.data.get('type') != 'memory_write_port':
            return None

        # Get write enable from the combined_write_enable field
        # Look for the valid-gated version first
        enable_name = shared_wr.data.get('combined_write_enable')
        write_enable_ssa = None
        if enable_name:
            gated_enable = self.graph.nodes.get(f'{enable_name}_valid_gated')
            if gated_enable:
                write_enable_ssa = self._get_or_create_value(gated_enable.id)
            else:
                enable_node = self.graph.nodes.get(enable_name)
                if enable_node:
                    write_enable_ssa = self._get_or_create_value(enable_node.id)

        if not write_enable_ssa:
            return None

        # Get write address and data from incoming edges
        write_addr_ssa = None
        write_data_ssa = None
        addr_width = None
        data_width = None
        for edge in shared_wr.incoming_edges:
            edge_type = edge.data.get('type')
            if edge_type == 'write_address':
                write_addr_ssa = self._get_or_create_value(edge.source.id)
                addr_width = self._get_width(edge.source)
            elif edge_type == 'write_data':
                write_data_ssa = self._get_or_create_value(edge.source.id)
                data_width = self._get_width(edge.source)

        if not write_addr_ssa or not write_data_ssa:
            return None

        return (write_enable_ssa, write_addr_ssa, write_data_ssa, addr_width, data_width)

    def _analyze_graph(self):
        """Analyze the graph to categorize nodes and determine signal properties."""
        for node_id, node in self.graph.nodes.items():
            node_type = node.data.get('type', '')

            # Determine if this is a register or wire
            if node.is_arch_state or node.is_uarch_state:
                self.registers.add(node_id)
            elif node_type in ['operation', 'var', 'literal', 'multiplexer',
                              'ternary_op', 'comparison', 'bit_slice']:
                self.wires.add(node_id)

            # Track memory arrays
            # Handle both 'isa_state' and 'isa_state mem' types
            if node_type in ['isa_state', 'isa_state mem']:
                # Check for arrays/memories (have array_size or array_depth)
                if 'array_size' in node.data:
                    width = self._get_width(node)
                    depth = node.data['array_size']
                    self.memories[node_id] = (width, depth)
                    self.registers.add(node_id)
                elif 'array_depth' in node.data and node.data['array_depth'] is not None:
                    # array_depth is the number of address bits, convert to size
                    width = self._get_width(node)
                    array_depth = node.data['array_depth']
                    depth = 2 ** array_depth
                    self.memories[node_id] = (width, depth)
                    self.registers.add(node_id)
                else:
                    self.registers.add(node_id)

            # Store width information
            width = self._get_width(node)
            self.signal_widths[node_id] = width

            # For concatenations, ensure we recompute after all nodes are analyzed
            if node_type == 'concatenation':
                # Mark for recomputation
                pass  # Will be recomputed in _propagate_widths

        # Propagate widths from operations to literals (for type consistency)
        self._propagate_widths()

        # Pre-compute array access widths (critical for 64-bit architectures)
        self._precompute_array_access_widths()

    def _precompute_array_access_widths(self):
        """
        Pre-compute widths for array access and operation nodes.

        This is critical for 64-bit architectures where:
        - Register file element width (64 bits) must be known
        - Operations must compute width from their operands
        """
        # First pass: array accesses
        for node_id, node in self.graph.nodes.items():
            node_type = node.data.get('type', '')
            if node_type == 'array_access':
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'array_base':
                        array_node = edge.source
                        array_name = array_node.id
                        if array_name in self.memories:
                            array_width, _ = self.memories[array_name]
                            self.signal_widths[node_id] = array_width
                        break

        # Second pass: operation widths from operands (iterate to propagate)
        # Operations should have width = max(operand widths) for arithmetic ops
        changed = True
        iterations = 0
        while changed and iterations < 10:
            changed = False
            iterations += 1
            for node_id, node in self.graph.nodes.items():
                node_type = node.data.get('type', '')
                if node_type == 'operation':
                    current_width = self.signal_widths.get(node_id, 32)

                    # Compute max operand width
                    max_width = current_width
                    for edge in node.incoming_edges:
                        if edge.data.get('type') in ('operand', 'left_operand', 'right_operand'):
                            operand_width = self.signal_widths.get(edge.source.id, 32)
                            max_width = max(max_width, operand_width)

                    if max_width > current_width:
                        self.signal_widths[node_id] = max_width
                        changed = True

        # Third pass: var nodes that alias operations
        for node_id, node in self.graph.nodes.items():
            node_type = node.data.get('type', '')
            if node_type == 'var':
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'assignment':
                        source_width = self.signal_widths.get(edge.source.id)
                        if source_width:
                            self.signal_widths[node_id] = source_width
                        break

        # Fourth pass: zero_extend nodes inherit width from consuming operations
        # If a zero_extend feeds into a 64-bit operation, it should produce 64 bits
        for node_id, node in self.graph.nodes.items():
            node_type = node.data.get('type', '')
            if node_type == 'zero_extend':
                current_width = self.signal_widths.get(node_id, 32)
                # Check what operations consume this zero_extend
                for edge in node.outgoing_edges:
                    consumer = edge.target
                    consumer_width = self.signal_widths.get(consumer.id)
                    if consumer_width and consumer_width > current_width:
                        self.signal_widths[node_id] = consumer_width
                        current_width = consumer_width

    def _propagate_widths(self):
        """Propagate width information from operations to their operands (esp. literals)."""
        # Iterate multiple times to propagate through chains
        changed = True
        iterations = 0
        while changed and iterations < 10:
            changed = False
            iterations += 1

            for node_id, node in self.graph.nodes.items():
                node_type = node.data.get('type', '')

                # For operations, ensure all operands have the same width as the result
                # But don't propagate for comparisons (they can have different input/output widths)
                if node_type == 'operation' and not self._is_comparison_op(node):
                    result_width = self.signal_widths.get(node_id, 32)

                    for edge in node.incoming_edges:
                        if edge.data.get('type') == 'operand':
                            source_id = edge.source.id
                            source_type = edge.source.data.get('type', '')

                            # Update literal widths to match their usage, but not bit slices
                            if source_type == 'literal':
                                old_width = self.signal_widths.get(source_id, 0)
                                if old_width != result_width:
                                    self.signal_widths[source_id] = result_width
                                    changed = True

    def _is_comparison_op(self, node: Node) -> bool:
        """Check if a node is a comparison operation."""
        node_type = node.data.get('type', '')
        if node_type == 'comparison':
            return True
        # Check node ID for comparison operators
        for op in ['==', '!=', '<=', '>=', '<', '>']:
            if op in node.id:
                return True
        return False

    def _generate_module_ports(self) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
        """
        Determine module input and output ports.

        Returns:
            Tuple of (inputs, outputs) where each is a list of (name, type) pairs
        """
        inputs = [
            ("clk", "!seq.clock"),
            ("reset", "i1"),
        ]

        outputs = []

        # Memory is now internal (generated as arrays with seq.compreg)
        # No external ports needed for imem/dmem

        return inputs, outputs

    def _generate_module_header(self):
        """Generate the hw.module declaration."""
        inputs, outputs = self._generate_module_ports()

        # Build port list in correct CIRCT syntax
        port_list = []

        # Input ports: in %name : type
        for name, typ in inputs:
            value_name = self._get_fresh_ssa_value(name)
            self.value_map[name] = value_name
            port_list.append(f'in {value_name} : {typ}')

        # Output ports: out name : type (no % prefix)
        for name, typ in outputs:
            port_list.append(f'out {name} : {typ}')

        # Emit module header with all ports
        ports_str = ', '.join(port_list)
        self._emit(f'hw.module @{self.module_name}({ports_str}) {{')
        self.indent_level += 1

    def _compute_constant_widths(self) -> Dict[str, int]:
        """
        Compute required width for each constant by analyzing consumer operations.

        Constants need to match the width of operations that use them.
        For example, if a constant is used in a 64-bit add, it needs to be 64 bits.
        """
        constant_widths: Dict[str, int] = {}

        for node_id, node in self.graph.nodes.items():
            node_type = node.data.get('type', '')
            if node_type not in ['literal', 'sized_literal']:
                continue

            # Start with the node's declared width
            base_width = self._get_width(node)
            max_width = base_width
            has_wide_consumer = False
            only_logical_consumers = True

            # Check all operations that consume this constant
            for edge in node.outgoing_edges:
                consumer = edge.target
                consumer_type = consumer.data.get('type', '')

                # Logical operations always produce/expect 1-bit values
                if consumer_type in ['logical_and', 'logical_or', 'logical_not']:
                    continue  # Keep checking other consumers

                # For operations, check the operand widths
                if consumer_type == 'operation':
                    # Check if this is a logical operator (&&, ||)
                    operator = consumer.data.get('operator', '')
                    if operator in ['&&', '||']:
                        # Logical operations produce 1-bit results
                        continue

                    only_logical_consumers = False
                    has_wide_consumer = True

                    # Get the width this operation expects
                    # Check other operands to this operation
                    for op_edge in consumer.incoming_edges:
                        other_node = op_edge.source
                        if other_node.id != node_id:
                            other_width = self._get_width(other_node)
                            max_width = max(max_width, other_width)

                    # Also check any explicit width on the operation
                    op_width = consumer.data.get('bit_width') or consumer.data.get('width')
                    if op_width:
                        max_width = max(max_width, op_width)
                else:
                    # Other consumer types - keep original width behavior
                    only_logical_consumers = False

            # If this constant is only used in logical operations, it should be 1-bit
            if only_logical_consumers and not has_wide_consumer:
                max_width = 1

            constant_widths[node_id] = max_width

        return constant_widths

    def _generate_constants(self):
        """Generate constant declarations for literals in the graph."""
        # Pre-compute required widths for all constants
        constant_widths = self._compute_constant_widths()

        for node_id, node in self.graph.nodes.items():
            node_type = node.data.get('type', '')
            if node_type in ['literal', 'sized_literal']:
                value = node.data.get('value', 0)

                # Handle different value formats
                if isinstance(value, str):
                    # Try to parse hex or binary strings
                    if value.startswith('0x') or value.startswith('0X'):
                        value = int(value, 16)
                    elif value.startswith('0b') or value.startswith('0B'):
                        value = int(value, 2)
                    else:
                        try:
                            value = int(value)
                        except ValueError:
                            value = 0

                # Use the computed width that accounts for consumer requirements
                width = constant_widths.get(node_id, self._get_width(node))
                ssa_val = self._get_or_create_value(node_id)

                # Store the width for later reference
                self.signal_widths[node_id] = width

                self._emit(f'{ssa_val} = hw.constant {value} : {self._mlir_type(width)}')

    def _generate_placeholders_for_undefined_values(self):
        """Generate placeholder constants for any SSA values that are referenced but not defined."""
        # Collect all defined values (includes input ports and assigned values)
        defined = set()

        # Add input port SSA values (defined in module signature)
        inputs, _ = self._generate_module_ports()
        for name, _ in inputs:
            if name in self.value_map:
                defined.add(self.value_map[name])

        # Add values defined with assignments
        for line in self.lines:
            # Match SSA value definitions (lines with ` = `)
            if ' = ' in line:
                parts = line.split('=')[0].strip().split()
                if parts and parts[-1].startswith('%'):
                    defined.add(parts[-1])

        # Find all referenced but undefined values
        referenced = set()
        for line in self.lines:
            # Find all %value references
            import re
            for match in re.finditer(r'%\w+', line):
                referenced.add(match.group())

        undefined = referenced - defined

        # Identify which values will be defined by sequential logic
        # These are _rd nodes that have corresponding _wr nodes
        will_be_defined_by_seq = set()
        for node_id in self.registers:
            if node_id in self.value_map:
                # Skip memories (they're defined as arrays)
                if node_id in self.memories:
                    continue
                # Check if this _rd has a _wr node that will drive it
                if node_id.endswith('_rd'):
                    wr_node_id = node_id.replace('_rd', '_wr')
                    if wr_node_id in self.graph.nodes:
                        will_be_defined_by_seq.add(self.value_map[node_id])

        # Filter out values that will be defined by sequential logic
        undefined = undefined - will_be_defined_by_seq

        # Filter out values that will be defined by stateful memory registers
        # These are forward references to seq.compreg outputs
        will_be_defined_by_stateful_mem = set()
        if hasattr(self, 'stateful_reg_outputs'):
            for mem_name, reg_outputs in self.stateful_reg_outputs.items():
                for reg_ssa in reg_outputs:
                    will_be_defined_by_stateful_mem.add(reg_ssa)
        undefined = undefined - will_be_defined_by_stateful_mem

        # Filter out values that will be defined by pipeline registers
        will_be_defined_by_pipeline = set()
        for node_id, node in self.graph.nodes.items():
            if node.data.get('type') == 'pipeline_register':
                if node_id in self.value_map:
                    will_be_defined_by_pipeline.add(self.value_map[node_id])
            elif node.data.get('type') == 'validity_bit':
                if node_id in self.value_map:
                    will_be_defined_by_pipeline.add(self.value_map[node_id])
        undefined = undefined - will_be_defined_by_pipeline

        # Generate placeholders for undefined values
        if undefined:
            self._emit("// Placeholders for undefined values (array accesses, etc.)")
            for val in sorted(undefined):
                # Get the node_id for this SSA value
                node_id = None
                for nid, ssa in self.value_map.items():
                    if ssa == val:
                        node_id = nid
                        break

                if node_id:
                    node = self.graph.nodes.get(node_id)

                    # FIRST: Check naming patterns that ALWAYS indicate 1-bit signals
                    # This takes absolute priority - mux select signals are always 1-bit
                    if ('select_' in node_id.lower() or '_enable' in node_id.lower() or
                        '_cmp' in node_id or '_cmp_' in node_id or
                        '_valid' in node_id.lower() or '_flush' in node_id.lower() or
                        '_stall' in node_id.lower() or '_delayed' in node_id.lower()):
                        width = 1
                    else:
                        # Then try cached width
                        width = self.signal_widths.get(node_id)

                        # Infer width from node type if not cached
                        if width is None and node:
                            node_type = node.data.get('type', '')
                            operator = node.data.get('operator', '')
                            # 1-bit signals: comparisons, enables, logical ops
                            if node_type in ['comparison', 'instruction_enable', 'logical_and', 'logical_or', 'logical_not', 'validity_bit']:
                                width = 1
                            elif node_type == 'operation' and operator in ['||', '&&', '==', '!=', '<', '>', '<=', '>=']:
                                width = 1
                            elif node_type == 'multiplexer':
                                # Mux output width - try to get from data
                                width = node.data.get('data_width', 32)
                            else:
                                width = self._get_width(node)

                        # Try to infer from usage if still unknown
                        if width is None:
                            width = self._infer_width_from_usage(val)

                        if width is None:
                            width = 32

                    # Check if this is an array (register file or memory)
                    if node and (node.data.get('array_depth') is not None or node.data.get('is_memory')):
                        raise ValueError(f"CIRCT generator: Array '{node_id}' used but not properly generated. Node type: {node.data.get('type')}")
                    else:
                        raise ValueError(f"CIRCT generator: Signal '{node_id}' used but not defined. Node type: {node.data.get('type') if node else 'UNKNOWN'}")
                else:
                    raise ValueError(f"CIRCT generator: SSA value '{val}' used but has unknown source (no node found for '{node_id}')")

    def _generate_combinational_logic(self):
        """Generate combinational logic using comb dialect operations."""
        # Iterative topological sort to avoid recursion depth issues
        visited = set()
        visiting = set()  # Track nodes currently being visited (for cycle detection)
        visit_stack = []

        def has_cycle_from(node_id: str) -> bool:
            """Check if there's a cycle starting from this node."""
            if node_id in visited:
                return False
            if node_id in visiting:
                return True

            visiting.add(node_id)
            node = self.graph.nodes.get(node_id)
            if node:
                for edge in node.incoming_edges:
                    if has_cycle_from(edge.source.id):
                        return True
            visiting.remove(node_id)
            return False

        # Edge types that represent combinational dependencies
        # (other edge types like 'array_element' into ISA state cross register boundaries)
        # NOTE: 'stall' and 'valid_gate' edges are NOT included because they create
        # feedback loops (stall logic depends on decode, decode depends on pipeline reg,
        # pipeline reg depends on stall). These loops stabilize combinationally in hardware.
        comb_dep_edge_types = {
            'operand', 'left_operand', 'right_operand',
            'assignment',  # var assignments
            'control', 'logic_input', 'stall_input', 'hazard_input',
            'concat_input', 'concatenation_input',
            'condition', 'ternary_condition', 'ternary_true', 'ternary_false',  # ternary
            'select', 'data_input', 'default_value',  # mux
            'bit_access', 'source',  # bit slice, extend ops
            'pipeline_input',  # pipeline register data input
            'array_index',  # array index calculation
            # Excluded: 'valid_gate', 'stall' - these create feedback loops
        }

        def add_dependencies_to_stack(node_id: str):
            """Add node and its dependencies to stack in correct order."""
            if node_id in visited or node_id in visiting:
                return

            node = self.graph.nodes.get(node_id)
            if not node:
                return

            node_type = node.data.get('type', '')

            # Skip literals (already generated)
            if node_type == 'literal':
                visited.add(node_id)
                return

            # Skip ISA state nodes (arrays/memories/registers) - they don't need
            # combinational generation, their values come from sequential logic
            if node_type in ('isa_state', 'isa_state mem') or node.is_arch_state:
                # But still mark as visited so we don't try to process later
                visited.add(node_id)
                return

            visiting.add(node_id)

            # Add dependencies first (reversed so they process in correct order)
            # Only follow edges that represent combinational dependencies
            for edge in reversed(list(node.incoming_edges)):
                edge_type = edge.data.get('type', '')
                source_node = edge.source
                source_type = source_node.data.get('type', '')

                # Don't follow edges to ISA state (arrays/memories/registers)
                # These represent reading from sequential elements, not combinational deps
                if source_type in ('isa_state', 'isa_state mem') or source_node.is_arch_state:
                    continue

                # Only follow combinational dependency edge types
                if edge_type in comb_dep_edge_types:
                    add_dependencies_to_stack(edge.source.id)

            visiting.remove(node_id)

            if node_id not in visited:
                visit_stack.append(node_id)
                visited.add(node_id)

        # Visit all non-register, non-literal nodes
        nodes_to_visit = []
        for node_id, node in self.graph.nodes.items():
            node_type = node.data.get('type', '')
            # Skip literals, registers, and ISA state (but not array_access)
            if node_type not in ['literal', 'sized_literal', 'isa_state', 'isa_state mem']:
                # Include arch_state nodes that are: array_access, bit_slice, var (for _wr vars), multiplexer
                should_include = not node.is_arch_state
                if node.is_arch_state:
                    # _wr nodes that get their value from muxes need to be generated
                    if node_type in ['array_access', 'bit_slice', 'var', 'multiplexer']:
                        should_include = True
                if should_include:
                    nodes_to_visit.append(node_id)

        # Build dependency-sorted stack
        for node_id in nodes_to_visit:
            try:
                add_dependencies_to_stack(node_id)
            except RecursionError:
                # If we hit recursion limit, there's likely a cycle
                # Skip this node and continue
                self._emit(f'// WARNING: Skipping {node_id} due to circular dependency')
                continue

        # Generate code for each node in dependency order
        for node_id in visit_stack:
            node = self.graph.nodes.get(node_id)
            if not node:
                continue

            node_type = node.data.get('type', '')

            if node_type == 'var':
                # Variables are just aliases, find their source
                self._generate_var(node)
            elif node_type == 'operation':
                # Check operator first (for nodes from graph_merger)
                operator = node.data.get('operator', '')
                if operator == '||':
                    self._generate_logical_or(node)
                elif operator == '&&':
                    self._generate_logical_and(node)
                elif operator == '!':
                    self._generate_logical_not(node)
                elif operator in ['==', '!=', '<', '<=', '>', '>=']:
                    # Comparison operators
                    self._generate_comparison(node)
                else:
                    # Check if this is actually a comparison
                    op = self._get_operation_from_node(node)
                    if op in ['eq', 'ne', 'lt', 'le', 'gt', 'ge', 'ult', 'ule', 'ugt', 'uge']:
                        self._generate_comparison(node)
                    else:
                        self._generate_operation(node)
            elif node_type == 'comparison':
                self._generate_comparison(node)
            elif node_type == 'bit_slice':
                self._generate_bit_slice(node)
            elif node_type == 'ternary_op':
                self._generate_ternary(node)
            elif node_type == 'multiplexer':
                self._generate_multiplexer(node)
            elif node_type == 'array_access':
                self._generate_array_access(node)
            elif node_type == 'repetition':
                self._generate_repetition(node)
            elif node_type == 'concatenation':
                self._generate_concatenation(node)
            elif node_type == 'logical_and':
                self._generate_logical_and(node)
            elif node_type == 'logical_or':
                self._generate_logical_or(node)
            elif node_type == 'logical_not':
                self._generate_logical_not(node)
            elif node_type == 'instruction_enable':
                self._generate_instruction_enable(node)
            elif node_type == 'zero_extend':
                self._generate_zero_extend(node)
            elif node_type == 'sign_extend':
                self._generate_sign_extend(node)
            elif node_type == 'pipeline_stall_controller':
                self._generate_pipeline_stall_controller(node)
            elif node_type == 'pipeline_register':
                # Pipeline registers are handled in sequential logic
                # But we may need to generate a forward reference for reads
                pass
            elif node_type == 'validity_bit':
                # Validity bits are handled in sequential logic
                pass
            elif node_type in ['literal', 'sized_literal']:
                # Already handled in _generate_constants
                pass
            elif node_type == 'memory_write_port':
                # Memory write ports are handled in _generate_hlmem_writes
                pass
            elif node_type in ['isa_state', 'isa_state mem']:
                # ISA state (register files, memories) handled in array/sequential generation
                pass
            elif node_type == 'byte_enable_computation':
                # Byte enable nodes compute byte lane enables from address bits
                # We handle byte-lane logic directly in _generate_hlmem_writes using writer_widths
                # So we can skip these nodes here
                pass
            else:
                # Unknown node type - raise an error instead of silently skipping
                raise ValueError(f"CIRCT generator: Unsupported node type '{node_type}' for node '{node_id}'")

    def _generate_logical_and(self, node: Node):
        """Generate logical AND of multiple 1-bit inputs."""
        # Check if already generated
        if node.id in self.generated_nodes:
            return

        result = self._get_or_create_value(node.id)
        self.signal_widths[node.id] = 1  # Logical AND always produces 1-bit result

        # Get all inputs - check multiple possible edge types
        inputs = []
        for edge in node.incoming_edges:
            edge_type = edge.data.get('type')
            if edge_type in ('logic_input', 'operand', 'left_operand', 'right_operand'):
                inputs.append(self._get_or_create_value(edge.source.id))

        if not inputs:
            raise ValueError(f"CIRCT generator: logical_and '{node.id}' has no inputs (expected edges with type 'logic_input', 'operand', 'left_operand', or 'right_operand')")

        if len(inputs) == 1:
            self.value_map[node.id] = inputs[0]
            self.generated_nodes.add(node.id)
            return

        # Chain ANDs: (a & b & c) = and(and(a, b), c)
        current = inputs[0]
        for i, inp in enumerate(inputs[1:], 1):
            if i == len(inputs) - 1:
                # Final AND uses the result name
                self._emit(f'{result} = comb.and {current}, {inp} : i1')
            else:
                temp = self._get_fresh_ssa_value(f"and_temp_{node.id}")
                self._emit(f'{temp} = comb.and {current}, {inp} : i1')
                current = temp

        self.generated_nodes.add(node.id)

    def _generate_logical_or(self, node: Node):
        """Generate logical OR of multiple 1-bit inputs."""
        # Check if already generated
        if node.id in self.generated_nodes:
            return

        result = self._get_or_create_value(node.id)
        self.signal_widths[node.id] = 1  # Logical OR always produces 1-bit result

        # Get all inputs - check multiple possible edge types
        inputs = []
        for edge in node.incoming_edges:
            edge_type = edge.data.get('type')
            if edge_type in ('logic_input', 'operand', 'left_operand', 'right_operand'):
                inputs.append(self._get_or_create_value(edge.source.id))

        if not inputs:
            raise ValueError(f"CIRCT generator: logical_or '{node.id}' has no inputs (expected edges with type 'logic_input', 'operand', 'left_operand', or 'right_operand')")

        if len(inputs) == 1:
            self.value_map[node.id] = inputs[0]
            self.generated_nodes.add(node.id)
            return

        # Chain ORs: (a | b | c) = or(or(a, b), c)
        current = inputs[0]
        for i, inp in enumerate(inputs[1:], 1):
            if i == len(inputs) - 1:
                # Final OR uses the result name
                self._emit(f'{result} = comb.or {current}, {inp} : i1')
            else:
                temp = self._get_fresh_ssa_value(f"or_temp_{node.id}")
                self._emit(f'{temp} = comb.or {current}, {inp} : i1')
                current = temp

        self.generated_nodes.add(node.id)

    def _generate_logical_not(self, node: Node):
        """Generate logical NOT of a 1-bit input."""
        result = self._get_or_create_value(node.id)

        # Get the input - check both 'logic_input' and 'operand' edge types
        inp = None
        for edge in node.incoming_edges:
            edge_type = edge.data.get('type')
            if edge_type in ('logic_input', 'operand'):
                inp = self._get_or_create_value(edge.source.id)
                break

        if not inp:
            raise ValueError(f"CIRCT generator: logical_not '{node.id}' has no input (expected edge with type 'logic_input' or 'operand')")

        # NOT is XOR with 1 in CIRCT comb dialect
        one_val = self._get_fresh_ssa_value("not_one")
        self._emit(f'{one_val} = hw.constant 1 : i1')
        self._emit(f'{result} = comb.xor {inp}, {one_val} : i1')

    def _generate_instruction_enable(self, node: Node):
        """Generate instruction enable signal (comparison of opcode fields)."""
        result = self._get_or_create_value(node.id)

        # Find the comparison input
        for edge in node.incoming_edges:
            if edge.data.get('type') == 'decode_enable':
                source = self._get_or_create_value(edge.source.id)
                self.value_map[node.id] = source
                return

        # If no decode_enable, check for other inputs
        if node.incoming_edges:
            source_edge = list(node.incoming_edges)[0]
            source = self._get_or_create_value(source_edge.source.id)
            self.value_map[node.id] = source
            return

        raise ValueError(f"CIRCT generator: instruction_enable '{node.id}' has no source (expected edge with type 'decode_enable' or any incoming edge)")

    def _generate_pipeline_stall_controller(self, node: Node):
        """Generate pipeline stall controller (combinational logic for stall signal)."""
        result = self._get_or_create_value(node.id)
        self.signal_widths[node.id] = 1  # Stall signal is always 1 bit

        # Stall controller computes stall condition from hazard detection
        # Look for inputs from hazard detection or other stall sources
        inputs = []
        for edge in node.incoming_edges:
            edge_type = edge.data.get('type', '')
            if edge_type in ('stall_input', 'hazard_input', 'operand', 'logic_input', 'control'):
                inputs.append(self._get_or_create_value(edge.source.id))

        if not inputs:
            # Default to no stall if no inputs
            zero = self._get_fresh_ssa_value("no_stall")
            self._emit(f'{zero} = hw.constant 0 : i1')
            self.value_map[node.id] = zero
            return

        if len(inputs) == 1:
            # Single input - direct assignment
            self.value_map[node.id] = inputs[0]
            return

        # Multiple inputs - OR them together (stall if any hazard)
        current = inputs[0]
        for i, inp in enumerate(inputs[1:], 1):
            if i == len(inputs) - 1:
                self._emit(f'{result} = comb.or {current}, {inp} : i1')
            else:
                temp = self._get_fresh_ssa_value(f"stall_or_{node.id}")
                self._emit(f'{temp} = comb.or {current}, {inp} : i1')
                current = temp

    def _generate_var(self, node: Node):
        """Generate a variable (alias) assignment."""
        result = self._get_or_create_value(node.id)

        # Get the target width from node data (explicit width declaration)
        target_width = node.data.get('bit_width') or node.data.get('width')

        # Find the source value
        for edge in node.incoming_edges:
            if edge.data.get('type') == 'assignment':
                source_node = edge.source
                source_ssa = self._get_or_create_value(source_node.id)
                source_width = self._get_width(source_node)

                # Check if this is a narrow load from memory (byte_data, halfword_data)
                # If target has explicit narrower width than source, we need to extract bits
                is_memory_source = ('dmem' in source_node.id or 'imem' in source_node.id)

                if (target_width and source_width and target_width < source_width and
                    is_memory_source and target_width in [8, 16]):
                    # Narrow load from memory - need to select portion based on address
                    # Find the address/index node
                    index_node = None
                    for src_edge in source_node.incoming_edges:
                        edge_type = src_edge.data.get('type', '')
                        if edge_type == 'array_index':
                            index_node = src_edge.source
                            break

                    if index_node:
                        index_ssa = self._get_or_create_value(index_node.id)
                        index_width = self._get_width(index_node)

                        if target_width == 8:
                            # Byte selection: extract addr[1:0], multiply by 8, use as offset
                            # In MLIR: extract low 2 bits, then use comb.shru to shift
                            addr_low = self._get_fresh_ssa_value(f"{node.id}_addr_low")
                            self._emit(f'{addr_low} = comb.extract {index_ssa} from 0 : ({self._mlir_type(index_width)}) -> i2')

                            # Extend addr_low to source width for shift amount
                            shift_amt = self._get_fresh_ssa_value(f"{node.id}_shift_amt")
                            shift_const = self._get_fresh_ssa_value(f"{node.id}_shift3")
                            self._emit(f'{shift_const} = hw.constant 3 : i{source_width}')  # multiply by 8 = shift left by 3
                            addr_ext = self._get_fresh_ssa_value(f"{node.id}_addr_ext")
                            pad_width = source_width - 2
                            pad_zero = self._get_fresh_ssa_value(f"{node.id}_pad")
                            self._emit(f'{pad_zero} = hw.constant 0 : i{pad_width}')
                            self._emit(f'{addr_ext} = comb.concat {pad_zero}, {addr_low} : i{pad_width}, i2')
                            self._emit(f'{shift_amt} = comb.shl {addr_ext}, {shift_const} : i{source_width}')

                            # Shift right by shift amount
                            shifted = self._get_fresh_ssa_value(f"{node.id}_shifted")
                            self._emit(f'{shifted} = comb.shru {source_ssa}, {shift_amt} : i{source_width}')

                            # Extract low 8 bits
                            self._emit(f'{result} = comb.extract {shifted} from 0 : ({self._mlir_type(source_width)}) -> i8')
                            self.value_map[node.id] = result
                            # Update signal width to reflect the actual extracted width
                            self.signal_widths[node.id] = 8
                            return
                        elif target_width == 16:
                            # Halfword selection: extract addr[1], multiply by 16
                            addr_bit = self._get_fresh_ssa_value(f"{node.id}_addr_bit")
                            self._emit(f'{addr_bit} = comb.extract {index_ssa} from 1 : ({self._mlir_type(index_width)}) -> i1')

                            # Extend to source width and multiply by 16 (shift left by 4)
                            shift_const = self._get_fresh_ssa_value(f"{node.id}_shift4")
                            self._emit(f'{shift_const} = hw.constant 4 : i{source_width}')
                            addr_ext = self._get_fresh_ssa_value(f"{node.id}_addr_ext")
                            pad_width = source_width - 1
                            pad_zero = self._get_fresh_ssa_value(f"{node.id}_pad")
                            self._emit(f'{pad_zero} = hw.constant 0 : i{pad_width}')
                            self._emit(f'{addr_ext} = comb.concat {pad_zero}, {addr_bit} : i{pad_width}, i1')
                            shift_amt = self._get_fresh_ssa_value(f"{node.id}_shift_amt")
                            self._emit(f'{shift_amt} = comb.shl {addr_ext}, {shift_const} : i{source_width}')

                            # Shift right by shift amount
                            shifted = self._get_fresh_ssa_value(f"{node.id}_shifted")
                            self._emit(f'{shifted} = comb.shru {source_ssa}, {shift_amt} : i{source_width}')

                            # Extract low 16 bits
                            self._emit(f'{result} = comb.extract {shifted} from 0 : ({self._mlir_type(source_width)}) -> i16')
                            self.value_map[node.id] = result
                            # Update signal width to reflect the actual extracted width
                            self.signal_widths[node.id] = 16
                            return
                    else:
                        # No index found, just extract low bits
                        self._emit(f'{result} = comb.extract {source_ssa} from 0 : ({self._mlir_type(source_width)}) -> {self._mlir_type(target_width)}')
                        self.value_map[node.id] = result
                        # Update signal width to reflect the actual extracted width
                        self.signal_widths[node.id] = target_width
                        return

                # Default: just map to source (SSA alias)
                self.value_map[node.id] = source_ssa
                return

        # If no assignment found, it might be connected differently
        # Just create an alias comment for clarity
        if node.incoming_edges:
            source_edge = list(node.incoming_edges)[0]
            source = self._get_or_create_value(source_edge.source.id)
            self.value_map[node.id] = source

    def _get_operation_from_node(self, node: Node) -> Optional[str]:
        """Get the operation type from node data.

        Maps operator symbols to operation names.
        """
        # First check 'operation' field
        op = node.data.get('operation')
        if op:
            return op

        # Then check 'operator' field (from parser)
        operator = node.data.get('operator')
        if operator:
            op_map = {
                '+': 'add',
                '-': 'sub',
                '*': 'mul',
                '&': 'and',
                '|': 'or',
                '^': 'xor',
                '<<': 'shl',
                '>>>': 'ashr',  # Arithmetic shift right (signed)
                '>>': 'shr',    # Logical shift right
                '==': 'eq',
                '!=': 'ne',
                '<': 'ult',     # Unsigned less than
                '>': 'ugt',     # Unsigned greater than
                '<=': 'ule',
                '>=': 'uge',
                '<s': 'lt',     # Signed less than
                '>s': 'gt',     # Signed greater than
                '<=s': 'le',
                '>=s': 'ge',
                '!': 'not',     # Logical NOT
                '~': 'bitnot',  # Bitwise NOT
                '&&': 'and',    # Logical AND
                '||': 'or',     # Logical OR
            }
            return op_map.get(operator)

        return None

    def _generate_operation(self, node: Node):
        """Generate a comb dialect operation."""
        # Get operation from node data
        op = self._get_operation_from_node(node)
        if not op:
            self._emit(f'// Could not determine operation for: {node.id}')
            return

        result = self._get_or_create_value(node.id)

        # Get operands and their source nodes
        # Note: Due to graph merging, we may have multiple edges with the same position
        # (e.g., both shared and instruction-specific versions). Take only one per position.
        # Accept 'operand', 'left_operand', and 'right_operand' edge types
        operand_nodes = []
        operands = []
        seen_positions = set()

        # Sort left operands before right operands
        def sort_key(e):
            edge_type = e.data.get('type', '')
            pos = e.data.get('position')
            # Prioritize: explicit left position, left_operand type, then right
            if pos == 'left' or edge_type == 'left_operand':
                return (0, e.source.id)
            elif pos == 'right' or edge_type == 'right_operand':
                return (1, e.source.id)
            return (2, e.source.id)

        for edge in sorted(node.incoming_edges, key=sort_key):
            edge_type = edge.data.get('type', '')
            if edge_type in ('operand', 'left_operand', 'right_operand'):
                # Use edge type as position key if position is None
                position = edge.data.get('position')
                if position is None:
                    # Derive position from edge type
                    if edge_type == 'left_operand':
                        position = 'left'
                    elif edge_type == 'right_operand':
                        position = 'right'
                if position not in seen_positions:
                    seen_positions.add(position)
                    operand_nodes.append(edge.source)
                    operands.append(self._get_or_create_value(edge.source.id))

        if not operands:
            return

        # Compute operation width
        # For arithmetic operations (add, sub, and, or, xor), use max operand width
        # This ensures 64-bit operations when mixing 64-bit and 32-bit operands (e.g., pc + 4)
        node_width = self._get_width(node)
        operand_widths = [self._get_width(op_node) for op_node in operand_nodes]
        max_operand_width = max(operand_widths) if operand_widths else 32

        # Use the larger of node width and max operand width
        width = max(node_width or 32, max_operand_width)

        # Handle unary operations (NOT)
        if op.lower() in ['not', 'bitnot'] and len(operands) == 1:
            operand = operands[0]
            operand_width = operand_widths[0] if operand_widths else 1

            if op.lower() == 'not':
                # Logical NOT - for 1-bit values, use icmp eq with 0
                # For multi-bit values, compare with 0 to get 1-bit result
                if operand_width == 1:
                    # For 1-bit, NOT is equivalent to XOR with 1
                    one_val = self._get_fresh_ssa_value(f"{node.id}_one")
                    self._emit(f'{one_val} = hw.constant 1 : i1')
                    self._emit(f'{result} = comb.xor {operand}, {one_val} : i1')
                    self.signal_widths[node.id] = 1
                else:
                    # For multi-bit, compare with 0 to get boolean (true if zero)
                    # NOT of a value is true when the value is zero
                    zero_val = self._get_fresh_ssa_value(f"{node.id}_zero")
                    self._emit(f'{zero_val} = hw.constant 0 : {self._mlir_type(operand_width)}')
                    self._emit(f'{result} = comb.icmp eq {operand}, {zero_val} : {self._mlir_type(operand_width)}')
                    self.signal_widths[node.id] = 1
            else:  # bitnot
                # Bitwise NOT - XOR with all 1s
                ones_val = self._get_fresh_ssa_value(f"{node.id}_ones")
                all_ones = (1 << operand_width) - 1
                self._emit(f'{ones_val} = hw.constant {all_ones} : {self._mlir_type(operand_width)}')
                self._emit(f'{result} = comb.xor {operand}, {ones_val} : {self._mlir_type(operand_width)}')
                self.signal_widths[node.id] = operand_width
            return

        # Map operations to CIRCT comb operations
        op_map = {
            'add': 'comb.add',
            'sub': 'comb.sub',
            'mul': 'comb.mul',
            'and': 'comb.and',
            'or': 'comb.or',
            'xor': 'comb.xor',
            'shl': 'comb.shl',
            'shr': 'comb.shru',  # Logical shift right
            'ashr': 'comb.shrs',  # Arithmetic shift right
        }

        circt_op = op_map.get(op.lower())
        if not circt_op:
            raise ValueError(f"CIRCT generator: Unsupported operation '{op}' in node '{node.id}'. Known operations: {list(op_map.keys())}")

        # For shift operations, ensure operands have matching widths
        # CIRCT requires both operands to be the same width, matching the output width
        if op.lower() in ['shl', 'shr', 'ashr'] and len(operands) >= 2:
            lhs_width = self._get_width(operand_nodes[0])
            rhs_width = self._get_width(operand_nodes[1])

            # Both operands must match the output width
            if lhs_width < width:
                # Extend LHS to output width
                extended_lhs = self._get_fresh_ssa_value(f"{operand_nodes[0].id}_extended")
                zero_width = width - lhs_width
                zero_val = self._get_fresh_ssa_value("lhs_ext_zero")
                self._emit(f'{zero_val} = hw.constant 0 : {self._mlir_type(zero_width)}')
                self._emit(f'{extended_lhs} = comb.concat {zero_val}, {operands[0]} : {self._mlir_type(zero_width)}, {self._mlir_type(lhs_width)}')
                operands[0] = extended_lhs
                lhs_width = width

            if rhs_width != width:
                # Extend RHS to output width
                extended_rhs = self._get_fresh_ssa_value(f"{operand_nodes[1].id}_extended")
                if rhs_width < width:
                    # Pad with zeros on the left
                    zero_width = width - rhs_width
                    zero_val = self._get_fresh_ssa_value("shift_zero")
                    self._emit(f'{zero_val} = hw.constant 0 : {self._mlir_type(zero_width)}')
                    self._emit(f'{extended_rhs} = comb.concat {zero_val}, {operands[1]} : {self._mlir_type(zero_width)}, {self._mlir_type(rhs_width)}')
                else:
                    # Truncate (extract lower bits)
                    self._emit(f'{extended_rhs} = comb.extract {operands[1]} from 0 : ({self._mlir_type(rhs_width)}) -> {self._mlir_type(width)}')
                operands[1] = extended_rhs

        operand_str = ", ".join(operands)
        self._emit(f'{result} = {circt_op} {operand_str} : {self._mlir_type(width)}')

        # Store the output width for downstream operations
        self.signal_widths[node.id] = width

    def _generate_comparison(self, node: Node):
        """Generate a comparison operation."""
        # Get operation from node data
        op = self._get_operation_from_node(node)
        if not op:
            op = 'eq'  # Default

        result = self._get_or_create_value(node.id)

        # Get operands (use same edge finding as operations)
        # Accept 'operand', 'left_operand', 'right_operand' edge types
        operand_nodes = []
        operand_values = []
        for edge in sorted(node.incoming_edges, key=lambda e: (e.data.get('position') != 'left', e.data.get('position') != 'right')):
            edge_type = edge.data.get('type', '')
            if edge_type in ['operand', 'left_operand', 'right_operand']:
                operand_nodes.append(edge.source)
                operand_values.append(self._get_or_create_value(edge.source.id))

        if len(operand_values) < 2:
            import re

            # First check if compare_value is in node data (e.g., byte_mux_sel nodes)
            compare_value = node.data.get('compare_value')

            if compare_value is None:
                # Try to extract comparison target from node ID
                # e.g., "instr_6_0_eq_b0110011" -> compare with 0b0110011

                # Pattern for binary: _eq_b<binary> or _eq_0b<binary>
                bin_match = re.search(r'_eq_[0]?b([01]+)', node.id)
                # Pattern for hex: _eq_h<hex> or _eq_0x<hex>
                hex_match = re.search(r'_eq_[0]?[hx]([0-9a-fA-F]+)', node.id)
                # Pattern for decimal: _eq_<decimal>
                dec_match = re.search(r'_eq_(\d+)$', node.id)

                if bin_match:
                    compare_value = int(bin_match.group(1), 2)
                elif hex_match:
                    compare_value = int(hex_match.group(1), 16)
                elif dec_match:
                    compare_value = int(dec_match.group(1))

            if compare_value is not None and len(operand_values) == 1:
                # Extract bit range from node ID if present (e.g., instr_6_0 means bits 6:0)
                range_match = re.search(r'(\w+)_(\d+)_(\d+)_eq', node.id)
                if range_match:
                    high_bit = int(range_match.group(2))
                    low_bit = int(range_match.group(3))
                    slice_width = high_bit - low_bit + 1

                    # First extract the bits from the operand
                    source_width = self.signal_widths.get(operand_nodes[0].id, 32)
                    slice_val = self._get_fresh_ssa_value("cmp_slice")
                    self._emit(f'{slice_val} = comb.extract {operand_values[0]} from {low_bit} : ({self._mlir_type(source_width)}) -> {self._mlir_type(slice_width)}')

                    # Create constant for comparison
                    const_val = self._get_fresh_ssa_value("cmp_const")
                    self._emit(f'{const_val} = hw.constant {compare_value} : {self._mlir_type(slice_width)}')

                    # Emit comparison
                    self._emit(f'{result} = comb.icmp eq {slice_val}, {const_val} : {self._mlir_type(slice_width)}')
                    return
                else:
                    # No bit range, compare whole value
                    source_width = self.signal_widths.get(operand_nodes[0].id, 32)
                    const_val = self._get_fresh_ssa_value("cmp_const")
                    self._emit(f'{const_val} = hw.constant {compare_value} : {self._mlir_type(source_width)}')
                    self._emit(f'{result} = comb.icmp eq {operand_values[0]}, {const_val} : {self._mlir_type(source_width)}')
                    return

            # Couldn't handle, skip
            return

        # Get widths of both operands - use _get_width which properly follows
        # var assignment chains recursively (similar to VHDL generator's _infer_bit_width)
        width0 = self._get_width(operand_nodes[0])
        width1 = self._get_width(operand_nodes[1])

        # If widths differ, handle width mismatch
        if width0 != width1:
            # Check if either operand is a literal constant
            if operand_nodes[1].data.get('type') == 'literal':
                # Regenerate the constant with the correct width
                value = operand_nodes[1].data.get('value', 0)
                const_val = self._get_fresh_ssa_value("cmp_const")
                self._emit(f'{const_val} = hw.constant {value} : {self._mlir_type(width0)}')
                operand_values[1] = const_val
                operand_width = width0
            elif operand_nodes[0].data.get('type') == 'literal':
                # Regenerate the constant with the correct width
                value = operand_nodes[0].data.get('value', 0)
                const_val = self._get_fresh_ssa_value("cmp_const")
                self._emit(f'{const_val} = hw.constant {value} : {self._mlir_type(width1)}')
                operand_values[0] = const_val
                operand_width = width1
            else:
                # Use the smaller width - comparing register addresses should use the natural width
                # Extending to larger width is usually wrong for register address comparisons
                operand_width = min(width0, width1)
                if width0 > operand_width:
                    # Truncate operand 0 to match
                    truncated = self._get_fresh_ssa_value("cmp_trunc")
                    self._emit(f'{truncated} = comb.extract {operand_values[0]} from 0 : ({self._mlir_type(width0)}) -> {self._mlir_type(operand_width)}')
                    operand_values[0] = truncated
                if width1 > operand_width:
                    # Truncate operand 1 to match
                    truncated = self._get_fresh_ssa_value("cmp_trunc")
                    self._emit(f'{truncated} = comb.extract {operand_values[1]} from 0 : ({self._mlir_type(width1)}) -> {self._mlir_type(operand_width)}')
                    operand_values[1] = truncated
        else:
            operand_width = width0

        # Map comparison operations
        pred_map = {
            'eq': 'eq',
            'ne': 'ne',
            'lt': 'slt',   # Signed less than
            'le': 'sle',
            'gt': 'sgt',
            'ge': 'sge',
            'ult': 'ult',  # Unsigned less than
            'ule': 'ule',
            'ugt': 'ugt',
            'uge': 'uge',
        }

        pred = pred_map.get(op, 'eq')
        self._emit(f'{result} = comb.icmp {pred} {operand_values[0]}, {operand_values[1]} : {self._mlir_type(operand_width)}')

    def _generate_bit_slice(self, node: Node):
        """Generate bit extraction/slicing operation."""
        result = self._get_or_create_value(node.id)

        # Extract bit range from node data or node ID
        if 'expression' in node.data and 'range' in node.data['expression']:
            high_bit, low_bit = node.data['expression']['range']
        else:
            # Try to parse from node ID like "instr[19:15]"
            import re
            match = re.search(r'\[(\d+):(\d+)\]', node.id)
            if match:
                high_bit = int(match.group(1))
                low_bit = int(match.group(2))
            else:
                self._emit(f'// Could not determine bit range for: {node.id}')
                return

        # Get source operand (edge type might be 'bit_access' or 'operand')
        source_edge = next((e for e in node.incoming_edges if e.data.get('type') in ['operand', 'bit_access']), None)
        if not source_edge:
            self._emit(f'// No source found for bit slice: {node.id}')
            return

        source = self._get_or_create_value(source_edge.source.id)
        source_width = self._get_width(source_edge.source)
        result_width = high_bit - low_bit + 1

        self._emit(f'{result} = comb.extract {source} from {low_bit} : ({self._mlir_type(source_width)}) -> {self._mlir_type(result_width)}')

    def _generate_ternary(self, node: Node):
        """Generate ternary (mux) operation: condition ? true_val : false_val."""
        result = self._get_or_create_value(node.id)
        width = self._get_width(node)

        # Get operands: condition, true_value, false_value
        cond = None
        true_val = None
        false_val = None
        true_node = None
        false_node = None

        for edge in node.incoming_edges:
            edge_type = edge.data.get('type', '')
            if edge_type == 'ternary_condition':
                cond = self._get_or_create_value(edge.source.id)
            elif edge_type == 'ternary_true':
                true_node = edge.source
            elif edge_type == 'ternary_false':
                false_node = edge.source

        if cond and true_node and false_node:
            # For literals, generate fresh constants with the target width
            # This avoids reusing cached SSA values that may have different widths
            # (e.g., "1" used as i1 for boolean vs needing i64 for SLT result)
            if true_node.data.get('type') == 'literal':
                lit_val = true_node.data.get('value', 0)
                if isinstance(lit_val, str):
                    lit_val = int(lit_val, 0) if lit_val.startswith('0') else int(lit_val)
                true_val = self._get_fresh_ssa_value("ternary_true_const")
                self._emit(f'{true_val} = hw.constant {lit_val} : {self._mlir_type(width)}')
                true_width = width
            else:
                true_val = self._get_or_create_value(true_node.id)
                true_width = self._get_width(true_node)

            if false_node.data.get('type') == 'literal':
                lit_val = false_node.data.get('value', 0)
                if isinstance(lit_val, str):
                    lit_val = int(lit_val, 0) if lit_val.startswith('0') else int(lit_val)
                false_val = self._get_fresh_ssa_value("ternary_false_const")
                self._emit(f'{false_val} = hw.constant {lit_val} : {self._mlir_type(width)}')
                false_width = width
            else:
                false_val = self._get_or_create_value(false_node.id)
                false_width = self._get_width(false_node)

            # Extend true value if needed (for non-literal operands)
            if true_width < width:
                pad_bits = width - true_width
                pad_val = self._get_fresh_ssa_value("ternary_pad_true")
                self._emit(f'{pad_val} = hw.constant 0 : i{pad_bits}')
                extended_true = self._get_fresh_ssa_value("ternary_ext_true")
                self._emit(f'{extended_true} = comb.concat {pad_val}, {true_val} : i{pad_bits}, {self._mlir_type(true_width)}')
                true_val = extended_true

            # Extend false value if needed (for non-literal operands)
            if false_width < width:
                pad_bits = width - false_width
                pad_val = self._get_fresh_ssa_value("ternary_pad_false")
                self._emit(f'{pad_val} = hw.constant 0 : i{pad_bits}')
                extended_false = self._get_fresh_ssa_value("ternary_ext_false")
                self._emit(f'{extended_false} = comb.concat {pad_val}, {false_val} : i{pad_bits}, {self._mlir_type(false_width)}')
                false_val = extended_false

            self._emit(f'{result} = comb.mux {cond}, {true_val}, {false_val} : {self._mlir_type(width)}')

    def _generate_multiplexer(self, node: Node):
        """Generate multiplexer logic for ISAComp mux structure.

        ISAComp multiplexers have:
        - mux_input: data inputs (with input_index for ordering)
        - mux_select: select signals (with select_index for pairing with inputs)
        - mux_default_input: default value when no select is active
        """
        result = self._get_or_create_value(node.id)

        # Collect inputs and selects with their indices for proper pairing
        inputs = []  # (select_ssa, data_ssa, width) tuples
        default_val = None
        default_width = 32

        # First pass: collect all edges by type WITH their indices
        mux_inputs = []  # (index, source_node) tuples
        mux_selects = []  # (index, source_node) tuples

        for edge in node.incoming_edges:
            edge_type = edge.data.get('type', '')
            if edge_type == 'mux_input':
                # Get input_index from edge data (fallback to mux_select or 0)
                input_index = edge.data.get('input_index', edge.data.get('mux_select', 0))
                mux_inputs.append((input_index, edge.source))
            elif edge_type == 'mux_select':
                # Get select_index from edge data
                select_index = edge.data.get('select_index', 0)
                mux_selects.append((select_index, edge.source))
            elif edge_type == 'mux_default_input':
                default_val = self._get_or_create_value(edge.source.id)
                default_width = self._get_width(edge.source) or 32

        # Create a dict for selects keyed by their index for proper matching
        select_by_index = {idx: node for idx, node in mux_selects}

        # Sort inputs by index and pair with matching selects
        mux_inputs.sort(key=lambda x: x[0])

        # Pair inputs with selects by matching their index values
        for input_idx, input_node in mux_inputs:
            data_ssa = self._get_or_create_value(input_node.id)
            input_width = self._get_width(input_node) or 32
            if input_idx in select_by_index:
                sel_node = select_by_index[input_idx]
                sel_ssa = self._get_or_create_value(sel_node.id)
                inputs.append((sel_ssa, data_ssa, input_width))

        # Determine the output width - prefer explicit data_width/output_width over computed
        # This is critical for register file muxes where inputs may have incorrect inferred widths
        width = node.data.get('data_width') or node.data.get('output_width') or node.data.get('bit_width')
        if width is None:
            # Fall back to computing from inputs
            widths = [w for _, _, w in inputs]
            if default_val:
                widths.append(default_width)
            width = max(widths) if widths else 32

        if not inputs:
            if default_val:
                self._emit(f'// Mux with only default: {node.id}')
                # Create a constant zero select that's never taken
                self.value_map[node.id] = default_val
            else:
                self._emit(f'// Could not determine operation for: {node.id}')
            return

        # Generate nested muxes: priority encoder style
        # mux(sel0, val0, mux(sel1, val1, ... default))
        if default_val:
            # Adjust default width to match target width
            if default_width < width:
                ext_default = self._get_fresh_ssa_value("mux_ext_default")
                pad_bits = width - default_width
                pad_const = self._get_fresh_ssa_value("pad_zero")
                self._emit(f'{pad_const} = hw.constant 0 : i{pad_bits}')
                self._emit(f'{ext_default} = comb.concat {pad_const}, {default_val} : i{pad_bits}, i{default_width}')
                current_result = ext_default
            elif default_width > width:
                trunc_default = self._get_fresh_ssa_value("mux_trunc_default")
                self._emit(f'{trunc_default} = comb.extract {default_val} from 0 : (i{default_width}) -> i{width}')
                current_result = trunc_default
            else:
                current_result = default_val
        else:
            # If no default, use zero
            zero = self._get_fresh_ssa_value("mux_default_zero")
            self._emit(f'{zero} = hw.constant 0 : {self._mlir_type(width)}')
            current_result = zero

        # Build from last to first for priority ordering
        inputs_list = list(reversed(inputs))
        for i, (sel_ssa, data_ssa, input_width) in enumerate(inputs_list):
            # Adjust input width to match target width
            if input_width < width:
                # Extend narrower values with zero padding
                ext_data = self._get_fresh_ssa_value("mux_ext")
                pad_bits = width - input_width
                pad_const = self._get_fresh_ssa_value("pad_zero")
                self._emit(f'{pad_const} = hw.constant 0 : i{pad_bits}')
                self._emit(f'{ext_data} = comb.concat {pad_const}, {data_ssa} : i{pad_bits}, i{input_width}')
                data_ssa = ext_data
            elif input_width > width:
                # Truncate wider values (extract low bits)
                trunc_data = self._get_fresh_ssa_value("mux_trunc")
                self._emit(f'{trunc_data} = comb.extract {data_ssa} from 0 : (i{input_width}) -> i{width}')
                data_ssa = trunc_data

            # For the last mux in the chain, use the actual result name
            if i == len(inputs_list) - 1:
                self._emit(f'{result} = comb.mux {sel_ssa}, {data_ssa}, {current_result} : {self._mlir_type(width)}')
            else:
                temp = self._get_fresh_ssa_value("mux_temp")
                self._emit(f'{temp} = comb.mux {sel_ssa}, {data_ssa}, {current_result} : {self._mlir_type(width)}')
                current_result = temp

    def _generate_array_access(self, node: Node):
        """Generate array/memory access."""
        result = self._get_or_create_value(node.id)

        # Get array (array_base) and index (array_index) from edges
        array_node = None
        index_node = None

        for edge in node.incoming_edges:
            edge_type = edge.data.get('type', '')
            if edge_type == 'array_base':
                array_node = edge.source
            elif edge_type == 'array_index':
                index_node = edge.source

        if not array_node or not index_node:
            raise ValueError(f"CIRCT generator: Array access '{node.id}' missing array_base or array_index edge")

        array_name = array_node.id

        index_ssa = self._get_or_create_value(index_node.id)
        array_ssa = self._get_or_create_value(array_node.id)

        # Get array size and element width - use stored memory info first (most authoritative)
        if array_name in self.memories:
            array_width, array_size = self.memories[array_name]
        else:
            array_width = None
            if 'array_size' in array_node.data:
                array_size = array_node.data['array_size']
            elif 'array_depth' in array_node.data and array_node.data['array_depth'] is not None:
                array_size = 2 ** array_node.data['array_depth']
            else:
                array_size = 32  # Default for register file

        # Get element width - prefer array's stored width, then node's width
        node_width = self._get_width(node)
        width = array_width or node_width or 32

        # Calculate the index width
        import math
        index_width = max(1, math.ceil(math.log2(array_size))) if array_size > 1 else 1

        # Get actual index width - use _get_width for proper inference
        actual_index_width = self._get_width(index_node)

        # Determine if this is a byte-addressed memory (imem, dmem)
        # For byte-addressed memories, we need to shift the address by 2 to get word index
        is_byte_addressed = array_name in ['imem', 'dmem']
        bytes_per_element = width // 8  # e.g., 4 for 32-bit memory

        if is_byte_addressed and bytes_per_element > 1:
            # For byte-addressed memories, extract bits [index_width+shift-1:shift]
            # where shift = log2(bytes_per_element) = 2 for 32-bit words
            shift_bits = int(math.log2(bytes_per_element))
            high_bit = index_width + shift_bits - 1
            low_bit = shift_bits
            extracted_index = self._get_fresh_ssa_value(f"{index_node.id}_word_addr")
            self._emit(f'{extracted_index} = comb.extract {index_ssa} from {low_bit} : ({self._mlir_type(actual_index_width)}) -> {self._mlir_type(index_width)}')
            index_ssa = extracted_index
        elif actual_index_width != index_width:
            # For other arrays (like register file), just extract low bits
            extracted_index = self._get_fresh_ssa_value(f"{index_node.id}_extracted")
            self._emit(f'{extracted_index} = comb.extract {index_ssa} from 0 : ({self._mlir_type(actual_index_width)}) -> {self._mlir_type(index_width)}')
            index_ssa = extracted_index

        # Check if write_read_fwd is enabled - if so, we need to generate forwarding mux
        has_write_read_fwd = array_node.data.get('write_read_fwd', False)
        write_signals = None
        if has_write_read_fwd:
            write_signals = self._get_memory_write_signals(array_name)

        # Generate array read to either final result or temp (if forwarding needed)
        if has_write_read_fwd and write_signals:
            raw_read = self._get_fresh_ssa_value(f"{node.id}_raw")
        else:
            raw_read = result

        # Check if this is an sv.reg array (imem, dmem) - use sv.array_index_inout + sv.read_inout
        if hasattr(self, 'hlmem_arrays') and array_name in self.hlmem_arrays:
            # sv.array_index_inout to get reference to element
            elem_ref = self._get_fresh_ssa_value(f"{array_name}_elem_ref")
            self._emit(f'{elem_ref} = sv.array_index_inout {array_ssa}[{index_ssa}] : !hw.inout<!hw.array<{array_size} x i{width}>>, {self._mlir_type(index_width)}')
            # sv.read_inout to read the value
            self._emit(f'{raw_read} = sv.read_inout {elem_ref} : !hw.inout<i{width}>')
        else:
            # Regular hw.array - use hw.array_get
            self._emit(f'{raw_read} = hw.array_get {array_ssa}[{index_ssa}] : !hw.array<{array_size} x {self._mlir_type(width)}>, {self._mlir_type(index_width)}')

        # Generate write-to-read forwarding if enabled
        if has_write_read_fwd and write_signals:
            write_enable_ssa, write_addr_ssa, write_data_ssa, wr_addr_width, wr_data_width = write_signals

            # Use the original index for comparison (before extraction)
            # We need to compare at the extracted width since that's what was used for array access
            read_addr_ssa = index_ssa
            read_addr_width = index_width

            # Ensure write address has same width as read address for comparison
            if wr_addr_width != read_addr_width:
                # Extract low bits from write address to match read address width
                write_addr_extracted = self._get_fresh_ssa_value(f"{array_name}_wr_addr_ext")
                self._emit(f'{write_addr_extracted} = comb.extract {write_addr_ssa} from 0 : ({self._mlir_type(wr_addr_width)}) -> {self._mlir_type(read_addr_width)}')
                write_addr_ssa = write_addr_extracted

            # Generate address comparison: write_addr == read_addr
            addr_match = self._get_fresh_ssa_value(f"{node.id}_addr_match")
            self._emit(f'{addr_match} = comb.icmp eq {write_addr_ssa}, {read_addr_ssa} : {self._mlir_type(read_addr_width)}')

            # Generate combined condition: write_enable && addr_match
            fwd_cond = self._get_fresh_ssa_value(f"{node.id}_fwd_cond")
            self._emit(f'{fwd_cond} = comb.and {write_enable_ssa}, {addr_match} : i1')

            # Ensure write data has same width as read data
            if wr_data_width != width:
                if wr_data_width > width:
                    # Truncate write data
                    write_data_trunc = self._get_fresh_ssa_value(f"{array_name}_wr_data_trunc")
                    self._emit(f'{write_data_trunc} = comb.extract {write_data_ssa} from 0 : ({self._mlir_type(wr_data_width)}) -> {self._mlir_type(width)}')
                    write_data_ssa = write_data_trunc
                else:
                    # Zero-extend write data
                    pad_bits = width - wr_data_width
                    pad_val = self._get_fresh_ssa_value(f"{array_name}_wr_data_pad")
                    self._emit(f'{pad_val} = hw.constant 0 : i{pad_bits}')
                    write_data_ext = self._get_fresh_ssa_value(f"{array_name}_wr_data_ext")
                    self._emit(f'{write_data_ext} = comb.concat {pad_val}, {write_data_ssa} : i{pad_bits}, {self._mlir_type(wr_data_width)}')
                    write_data_ssa = write_data_ext

            # Generate forwarding mux: fwd_cond ? write_data : raw_read
            self._emit(f'// Write-to-read forwarding: forward write data if reading same address being written')
            self._emit(f'{result} = comb.mux {fwd_cond}, {write_data_ssa}, {raw_read} : {self._mlir_type(width)}')

        # Store the output width for later use in downstream operations
        self.signal_widths[node.id] = width

    def _generate_repetition(self, node: Node):
        """Generate bit repetition operation (e.g., {20{bit}} for sign extension)."""
        result = self._get_or_create_value(node.id)
        width = self._get_width(node)

        # Get the value to replicate and the count
        count = node.data.get('count', node.data.get('repetitions', 1))

        # Find the source value
        source_edge = next((e for e in node.incoming_edges), None)
        if not source_edge:
            raise ValueError(f"CIRCT generator: Repetition '{node.id}' has no source edge")

        source_ssa = self._get_or_create_value(source_edge.source.id)
        source_width = self._get_width(source_edge.source)
        if source_width is None:
            source_width = 1  # Default to 1-bit for repetition source

        # In CIRCT, use comb.replicate to replicate a value
        # comb.replicate replicates the input value multiple times
        result_width = source_width * count
        self._emit(f'{result} = comb.replicate {source_ssa} : ({self._mlir_type(source_width)}) -> {self._mlir_type(result_width)}')

    def _generate_zero_extend(self, node: Node):
        """Generate zero extension operation."""
        result = self._get_or_create_value(node.id)

        # Prioritize signal_widths (which may have propagated 64-bit widths)
        # over node.data['width'] which might have a stale 32-bit default
        target_width = self.signal_widths.get(node.id)
        if target_width is None:
            target_width = node.data.get('width')
        if target_width is None:
            target_width = self._get_width(node) or 32

        # Find the source value
        source_edge = next((e for e in node.incoming_edges), None)
        if not source_edge:
            raise ValueError(f"CIRCT generator: Zero extend '{node.id}' has no source edge")

        source_ssa = self._get_or_create_value(source_edge.source.id)
        source_width = self._get_width(source_edge.source)
        if source_width is None:
            source_width = 8  # Default to 8-bit for byte data

        if source_width >= target_width:
            # No extension needed, just truncate/extract
            self._emit(f'{result} = comb.extract {source_ssa} from 0 : ({self._mlir_type(source_width)}) -> {self._mlir_type(target_width)}')
        else:
            # Zero extend by concatenating with zeros
            extend_width = target_width - source_width
            zeros = self._get_fresh_ssa_value(f"{node.id}_zeros")
            self._emit(f'{zeros} = hw.constant 0 : {self._mlir_type(extend_width)}')
            self._emit(f'{result} = comb.concat {zeros}, {source_ssa} : {self._mlir_type(extend_width)}, {self._mlir_type(source_width)}')

    def _generate_sign_extend(self, node: Node):
        """Generate sign extension operation."""
        result = self._get_or_create_value(node.id)
        target_width = node.data.get('width', 32)
        if target_width is None:
            target_width = self._get_width(node)

        # Find the source value
        source_edge = next((e for e in node.incoming_edges), None)
        if not source_edge:
            raise ValueError(f"CIRCT generator: Sign extend '{node.id}' has no source edge")

        source_ssa = self._get_or_create_value(source_edge.source.id)
        source_width = self._get_width(source_edge.source)
        if source_width is None:
            source_width = 8  # Default to 8-bit

        if source_width >= target_width:
            # No extension needed, just truncate/extract
            self._emit(f'{result} = comb.extract {source_ssa} from 0 : ({self._mlir_type(source_width)}) -> {self._mlir_type(target_width)}')
        else:
            # Sign extend: extract sign bit, replicate it, concatenate
            sign_bit = self._get_fresh_ssa_value(f"{node.id}_sign")
            self._emit(f'{sign_bit} = comb.extract {source_ssa} from {source_width - 1} : ({self._mlir_type(source_width)}) -> i1')

            extend_width = target_width - source_width
            sign_ext = self._get_fresh_ssa_value(f"{node.id}_sign_ext")
            self._emit(f'{sign_ext} = comb.replicate {sign_bit} : (i1) -> {self._mlir_type(extend_width)}')

            self._emit(f'{result} = comb.concat {sign_ext}, {source_ssa} : {self._mlir_type(extend_width)}, {self._mlir_type(source_width)}')

    def _generate_concatenation(self, node: Node):
        """Generate bit concatenation operation (e.g., {a, b, c})."""
        result = self._get_or_create_value(node.id)
        width = self._get_width(node)

        # Get all parts to concatenate (in order)
        parts = []
        part_widths = []

        for edge in sorted(node.incoming_edges, key=lambda e: e.data.get('position', 0)):
            source_ssa = self._get_or_create_value(edge.source.id)
            source_width = self._get_width(edge.source)
            if source_width is None:
                source_width = 32  # Default width
            parts.append(source_ssa)
            part_widths.append(source_width)

        if not parts:
            raise ValueError(f"CIRCT generator: Concatenation '{node.id}' has no input parts")

        # In CIRCT, use comb.concat to concatenate values
        # comb.concat takes multiple values and concatenates them
        parts_str = ", ".join(parts)
        types_str = ", ".join(self._mlir_type(w) for w in part_widths)
        total_width = sum(part_widths)
        self._emit(f'{result} = comb.concat {parts_str} : {types_str}')

    def _generate_arrays(self):
        """Generate array structures for register files and memories.

        For memories with write ports, this creates a placeholder array with zeros.
        The actual stateful registers are created in _generate_stateful_memories()
        after combinational logic has been generated.
        """
        self._emit("")
        self._emit("// Array structures (register files, memories)")

        # All memories are now internal (including imem and dmem)

        # Track which arrays need stateful register implementations
        self.stateful_arrays = {}

        # Track which memories should use seq.hlmem (for proper Verilog array generation)
        self.hlmem_arrays = {}

        # Find memories that have write ports (naming convention: <mem>_shared_wr)
        memories_with_write_ports = set()
        for node_id, node in self.graph.nodes.items():
            if node.data.get('type') == 'memory_write_port':
                # Extract memory name from port name (e.g., rf_shared_wr -> rf)
                if node_id.endswith('_shared_wr'):
                    mem_name = node_id.rsplit('_shared_wr', 1)[0]
                    memories_with_write_ports.add(mem_name)

        # dmem always has writes (store instructions), add it to write ports
        if 'dmem' in self.memories:
            memories_with_write_ports.add('dmem')

        # For each memory/register file, create appropriate structure
        # Memory size limits for simulation
        # Small register files (rf) can use full seq.compreg expansion
        # Larger memories (imem, dmem) use seq.hlmem for proper Verilog arrays
        SMALL_MEM_LIMIT = 64   # Register files - full seq.compreg
        LARGE_MEM_LIMIT = 8192  # imem/dmem - capped for simulation

        for node_id in self.memories:
            width, depth = self.memories[node_id]

            # Cap memory depth for practical simulation
            if node_id in {'imem', 'dmem'}:
                if depth > LARGE_MEM_LIMIT:
                    self._emit(f"// Memory {node_id} capped from {depth} to {LARGE_MEM_LIMIT} elements for simulation")
                    depth = LARGE_MEM_LIMIT
                    self.memories[node_id] = (width, depth)  # Update for later use
                # Use seq.hlmem for imem/dmem - generates proper Verilog arrays
                import math
                addr_bits = max(1, math.ceil(math.log2(depth))) if depth > 1 else 1
                self._emit(f"// Memory {node_id} - seq.hlmem ({depth} elements, {addr_bits}-bit address)")
                self.hlmem_arrays[node_id] = (width, depth, addr_bits)
                continue  # Skip to next memory
            elif depth > SMALL_MEM_LIMIT:
                depth = SMALL_MEM_LIMIT
                self.memories[node_id] = (width, depth)

            # Check if this memory has a write port (needs stateful registers)
            if node_id in memories_with_write_ports and depth <= SMALL_MEM_LIMIT:
                # Mark for stateful register generation - array will be created later
                # by _generate_stateful_memory_arrays() with forward refs to registers
                self._emit(f"// Memory {node_id} - stateful (array created with forward refs)")
                self.stateful_arrays[node_id] = (width, depth)
                # Don't create placeholder - the stateful memory array function will
                # create the actual array with forward references to register outputs
            elif node_id in memories_with_write_ports:
                # Writable memory - should use stateful registers
                self._emit(f"// Memory {node_id} - writable ({depth} elements)")
                self.stateful_arrays[node_id] = (width, depth)
            else:
                # Read-only memory - generate as static array
                array_ssa = self._get_or_create_value(node_id)

                # For larger arrays, generate in chunks or use verbatim
                if depth > 64:
                    self._emit(f"// Read-only memory {node_id} ({depth} elements)")
                    # Generate in groups for readability
                    elements = []
                    for i in range(depth):
                        elem_val = self._get_fresh_ssa_value(f"{node_id}_elem_{i}")
                        self._emit(f'{elem_val} = hw.constant 0 : {self._mlir_type(width)}')
                        elements.append(elem_val)
                    elements_str = ", ".join(reversed(elements))
                    self._emit(f'{array_ssa} = hw.array_create {elements_str} : {self._mlir_type(width)}')
                else:
                    # Create individual zero constants for each element
                    elements = []
                    for i in range(depth):
                        elem_val = self._get_fresh_ssa_value(f"{node_id}_elem_{i}")
                        self._emit(f'{elem_val} = hw.constant 0 : {self._mlir_type(width)}')
                        elements.append(elem_val)
                    elements_str = ", ".join(reversed(elements))
                    self._emit(f'{array_ssa} = hw.array_create {elements_str} : {self._mlir_type(width)}')

    def _generate_hlmem_arrays(self):
        """Generate sv.reg declarations for large memories (imem, dmem).

        Uses sv.reg with array types to generate proper Verilog memory arrays
        that can be initialized with $readmemh.
        """
        if not hasattr(self, 'hlmem_arrays') or not self.hlmem_arrays:
            return

        self._emit("")
        self._emit("// Memory declarations (sv.reg arrays)")

        for mem_name, (width, depth, addr_bits) in self.hlmem_arrays.items():
            mem_ssa = self._get_or_create_value(mem_name)
            # sv.reg : !hw.inout<!hw.array<N x iW>>
            self._emit(f'{mem_ssa} = sv.reg name "{mem_name}" : !hw.inout<!hw.array<{depth} x i{width}>>')
            # Store the array type for later use
            self.value_map[f'{mem_name}_sv_type'] = f'!hw.inout<!hw.array<{depth} x i{width}>>'

    def _generate_hlmem_writes(self):
        """Generate sv.alwaysff blocks for writing to sv.reg array memories (dmem writes)."""
        if not hasattr(self, 'hlmem_arrays') or not self.hlmem_arrays:
            return

        clk = self.value_map.get("clk", "%clk_0")
        # Convert seq.clock to i1 for sv.alwaysff
        clk_i1 = self._get_fresh_ssa_value("clk_i1")
        self._emit(f'{clk_i1} = seq.from_clock {clk}')

        self._emit("")
        self._emit("// Memory write operations (sv.alwaysff)")

        for mem_name, (width, depth, addr_bits) in self.hlmem_arrays.items():
            # Find write port for this memory (naming convention: <mem>_shared_wr)
            wr_port_id = f'{mem_name}_shared_wr'
            wr_node = self.graph.nodes.get(wr_port_id)

            if not wr_node:
                # imem is typically read-only, dmem has writes
                if mem_name == 'dmem':
                    raise ValueError(f"CIRCT generator: dmem write port '{wr_port_id}' not found but dmem should be writable")
                continue

            # Get write signals from the write port node
            write_data_id = None
            write_addr_id = None
            write_enable_id = None

            for edge in wr_node.incoming_edges:
                edge_type = edge.data.get('type', '')
                if edge_type == 'write_data':
                    write_data_id = edge.source.id
                elif edge_type == 'write_address':
                    write_addr_id = edge.source.id
                elif edge_type == 'write_enable':
                    write_enable_id = edge.source.id

            if not all([write_data_id, write_addr_id, write_enable_id]):
                self._emit(f"// WARNING: Missing {mem_name} write signals")
                continue

            # Get SSA values for write signals
            write_data_ssa = self.value_map.get(write_data_id)
            write_addr_ssa = self.value_map.get(write_addr_id)
            write_enable_ssa = self.value_map.get(write_enable_id)

            if not all([write_data_ssa, write_addr_ssa, write_enable_ssa]):
                self._emit(f"// WARNING: Missing SSA values for {mem_name} write signals")
                continue

            mem_ssa = self.value_map.get(mem_name)
            if not mem_ssa:
                self._emit(f"// WARNING: Memory {mem_name} SSA not found")
                continue

            import math
            index_width = max(1, math.ceil(math.log2(depth))) if depth > 1 else 1

            # For byte-addressed memories (dmem, imem), we need to convert byte address to word address
            # by extracting bits [index_width+1:2] instead of [index_width-1:0]
            # This effectively divides the byte address by 4 (for 32-bit words)
            is_byte_addressed = mem_name in ['dmem', 'imem']

            # Get the actual width of the write address
            # For byte-addressed memories (dmem), addresses are typically 32-bit
            # For register files, the mux is already generated at the correct width (index_width)
            write_addr_node = self.graph.nodes.get(write_addr_id)
            write_addr_width = self._get_width(write_addr_node) if write_addr_node else None
            if write_addr_width is None:
                write_addr_width = self.signal_widths.get(write_addr_id)
            if write_addr_width is None:
                # Default: 32 for byte-addressed memories, index_width for others
                write_addr_width = 32 if is_byte_addressed else index_width

            # Save original byte address for narrow store mask computation
            original_byte_addr_ssa = write_addr_ssa
            original_byte_addr_width = write_addr_width

            if write_addr_width > index_width:
                extracted_addr = self._get_fresh_ssa_value(f"{mem_name}_wr_addr_extracted")
                if is_byte_addressed:
                    # Extract word address: skip low N bits (byte offset within word), take index_width bits
                    # N = log2(bytes_per_word): 2 for 32-bit words, 3 for 64-bit words
                    byte_offset_bits = int(math.log2(width // 8))
                    self._emit(f'{extracted_addr} = comb.extract {write_addr_ssa} from {byte_offset_bits} : (i{write_addr_width}) -> i{index_width}')
                else:
                    # Non-byte-addressed memory (e.g., register file): use lower bits directly
                    self._emit(f'{extracted_addr} = comb.extract {write_addr_ssa} from 0 : (i{write_addr_width}) -> i{index_width}')
                write_addr_ssa = extracted_addr

            # Check if we need read-modify-write for narrow stores using node data
            # The memory_access_transform attaches this data to the write port node
            writer_widths = wr_node.data.get('writer_widths', {})
            store_byte_enables = wr_node.data.get('store_byte_enables', {})

            # Build a mapping from writer name to enable signal by looking at
            # the combined write enable's inputs (each has 'instruction' data)
            writer_enables = {}  # writer -> enable_node_id

            # Helper function to recursively find instruction enable signals
            def find_instruction_enables(node_id, depth=0):
                if depth > 3:  # Prevent infinite recursion
                    return
                node = self.graph.nodes.get(node_id)
                if not node:
                    return

                for edge in node.incoming_edges:
                    src = edge.source
                    instr = src.data.get('instruction')
                    # For pipelined designs, the instruction field may not be set on pipeline
                    # registers. Try to extract instruction name from node ID patterns like:
                    # PIPE_Memory_PIPE_Execute_sb_enable_PIPE_PIPE -> sb
                    # PIPE_Memory_sb_enable_PIPE -> sb
                    if not instr:
                        import re
                        # Match patterns: {instr}_enable at end, or {instr}_enable_PIPE patterns
                        match = re.search(r'(?:^|_)([a-z]+)_enable(?:_PIPE)*$', src.id)
                        if match:
                            instr = match.group(1)
                    if instr and instr in writer_widths:
                        # For pipelined designs, find the pipeline register that has this enable as input
                        pipelined_enable_id = src.id
                        for edge in src.outgoing_edges:
                            target = edge.target
                            if target.data.get('type') == 'pipeline_register':
                                if edge.data.get('type') == 'pipeline_input':
                                    pipelined_enable_id = target.id
                                    break
                        writer_enables[instr] = pipelined_enable_id
                    # If this is an intermediate node (logical_or, operation, pipeline_register), recurse
                    elif src.data.get('type') in ('logical_or', 'operation', 'pipeline_register'):
                        find_instruction_enables(src.id, depth + 1)

            find_instruction_enables(write_enable_id)

            # Check if any writer is narrower than memory width (needs byte-lane logic)
            has_narrow_stores = any(w < width for w in writer_widths.values())

            # Generate sv.alwaysff block with conditional write
            self._emit(f'sv.alwaysff(posedge {clk_i1}) {{')
            self.indent_level += 1
            self._emit(f'sv.if {write_enable_ssa} {{')
            self.indent_level += 1

            # Get element reference
            elem_ref = self._get_fresh_ssa_value(f"{mem_name}_wr_elem_ref")
            self._emit(f'{elem_ref} = sv.array_index_inout {mem_ssa}[{write_addr_ssa}] : !hw.inout<!hw.array<{depth} x i{width}>>, i{index_width}')

            if has_narrow_stores and is_byte_addressed:
                # For narrow stores, we need read-modify-write
                # 1. Read current word
                current_word = self._get_fresh_ssa_value(f"{mem_name}_current_word")
                self._emit(f'{current_word} = sv.read_inout {elem_ref} : !hw.inout<i{width}>')

                # 2. Get byte enable signals from node data and expand to word masks
                # Create full mask (all 1s for full-width writes)
                full_mask = self._get_fresh_ssa_value(f"{mem_name}_full_mask")
                self._emit(f'{full_mask} = hw.constant -1 : i{width}')

                # Build word masks for each narrow writer from their byte enable signals
                writer_masks = {}  # writer -> (word_mask_ssa, enable_ssa)
                for writer, be_node_id in store_byte_enables.items():
                    be_ssa = self.value_map.get(be_node_id)
                    # Find enable signal for this writer from the writer_enables mapping
                    enable_id = writer_enables.get(writer)
                    enable_ssa = self.value_map.get(enable_id) if enable_id else None

                    if be_ssa and enable_ssa:
                        # Expand byte enable to word mask
                        # Each bit becomes 8 bits (0xFF or 0x00)
                        # For 64-bit memory: 8 bytes = 8-bit byte enable
                        # For 32-bit memory: 4 bytes = 4-bit byte enable
                        num_bytes = width // 8
                        be_width = num_bytes  # One bit per byte
                        word_mask_ssa = self._get_fresh_ssa_value(f"{mem_name}_{writer}_word_mask")
                        byte_masks = []
                        for i in range(num_bytes):
                            bit_extract = self._get_fresh_ssa_value(f"{mem_name}_{writer}_be_bit{i}")
                            self._emit(f'{bit_extract} = comb.extract {be_ssa} from {i} : (i{be_width}) -> i1')
                            byte_mask = self._get_fresh_ssa_value(f"{mem_name}_{writer}_byte{i}_mask")
                            self._emit(f'{byte_mask} = comb.replicate {bit_extract} : (i1) -> i8')
                            byte_masks.append(byte_mask)
                        # Concatenate: byteN-1, byteN-2, ..., byte1, byte0 -> word mask
                        parts_str = ", ".join(reversed(byte_masks))
                        types_str = ", ".join(["i8"] * num_bytes)
                        self._emit(f'{word_mask_ssa} = comb.concat {parts_str} : {types_str}')
                        writer_masks[writer] = (word_mask_ssa, enable_ssa)

                # If no explicit byte enables, generate masks from writer widths and address bits
                # This handles cases like RISC-V sb/sh/sw where byte enables aren't explicit
                if not store_byte_enables and writer_widths:
                    narrow_writers = {w: ww for w, ww in writer_widths.items() if ww < width}
                    if narrow_writers:
                        for writer, writer_width in narrow_writers.items():
                            enable_id = writer_enables.get(writer)
                            enable_ssa = self.value_map.get(enable_id) if enable_id else None
                            if enable_ssa:
                                # Generate mask based on writer width and address offset
                                # For 8-bit store: mask = 0xFF << (addr[1:0] * 8)
                                # For 16-bit store: mask = 0xFFFF << (addr[1] * 16)
                                # Use original byte address (before word-index extraction)
                                base_mask_val = (1 << writer_width) - 1  # 0xFF for 8-bit, 0xFFFF for 16-bit
                                base_mask = self._get_fresh_ssa_value(f"{mem_name}_{writer}_base_mask")
                                self._emit(f'{base_mask} = hw.constant {base_mask_val} : i{width}')

                                if writer_width == 8:
                                    # Byte store: shift by addr[1:0] * 8
                                    # Extract addr[1:0] from original byte address
                                    addr_bits = self._get_fresh_ssa_value(f"{mem_name}_{writer}_addr_bits")
                                    self._emit(f'{addr_bits} = comb.extract {original_byte_addr_ssa} from 0 : (i{original_byte_addr_width}) -> i2')
                                    # Extend to full width and multiply by 8 (concat with 3 zeros on right = shift left by 3)
                                    pad_bits = width - 5  # 2 bits + 3 for shift = 5 bits needed
                                    pad_zero = self._get_fresh_ssa_value(f"{mem_name}_{writer}_pad_zero")
                                    self._emit(f'{pad_zero} = hw.constant 0 : i{pad_bits}')
                                    three_bits = self._get_fresh_ssa_value(f"{mem_name}_{writer}_three_bits")
                                    self._emit(f'{three_bits} = hw.constant 0 : i3')
                                    shift_amt = self._get_fresh_ssa_value(f"{mem_name}_{writer}_shift_amt")
                                    self._emit(f'{shift_amt} = comb.concat {pad_zero}, {addr_bits}, {three_bits} : i{pad_bits}, i2, i3')
                                elif writer_width == 16:
                                    # Halfword store: shift by addr[1] * 16
                                    # Extract addr[1] from original byte address
                                    addr_bit = self._get_fresh_ssa_value(f"{mem_name}_{writer}_addr_bit")
                                    self._emit(f'{addr_bit} = comb.extract {original_byte_addr_ssa} from 1 : (i{original_byte_addr_width}) -> i1')
                                    # Extend to full width and multiply by 16 (concat with 4 zeros on right = shift left by 4)
                                    pad_bits = width - 5  # 1 bit + 4 for shift = 5 bits needed
                                    pad_zero = self._get_fresh_ssa_value(f"{mem_name}_{writer}_pad_zero")
                                    self._emit(f'{pad_zero} = hw.constant 0 : i{pad_bits}')
                                    four_bits = self._get_fresh_ssa_value(f"{mem_name}_{writer}_four_bits")
                                    self._emit(f'{four_bits} = hw.constant 0 : i4')
                                    shift_amt = self._get_fresh_ssa_value(f"{mem_name}_{writer}_shift_amt")
                                    self._emit(f'{shift_amt} = comb.concat {pad_zero}, {addr_bit}, {four_bits} : i{pad_bits}, i1, i4')
                                else:
                                    # Other narrow widths: no shift
                                    shift_amt = self._get_fresh_ssa_value(f"{mem_name}_{writer}_shift_amt")
                                    self._emit(f'{shift_amt} = hw.constant 0 : i{width}')

                                # Shift mask to correct position
                                word_mask_ssa = self._get_fresh_ssa_value(f"{mem_name}_{writer}_word_mask")
                                self._emit(f'{word_mask_ssa} = comb.shl {base_mask}, {shift_amt} : i{width}')
                                writer_masks[writer] = (word_mask_ssa, enable_ssa)

                # Find full-width writers (they use full mask)
                full_width_writers = [w for w, ww in writer_widths.items() if ww == width]

                # 3. Select word mask based on active writer
                word_mask = self._get_fresh_ssa_value(f"{mem_name}_word_mask")
                zero_mask = self._get_fresh_ssa_value(f"{mem_name}_zero_mask")
                self._emit(f'{zero_mask} = hw.constant 0 : i{width}')

                # Build mux chain: narrow writers -> full-width writers -> zero
                current_result = zero_mask
                for writer, (mask_ssa, enable_ssa) in writer_masks.items():
                    temp = self._get_fresh_ssa_value(f"{mem_name}_mask_temp")
                    self._emit(f'{temp} = comb.mux {enable_ssa}, {mask_ssa}, {current_result} : i{width}')
                    current_result = temp

                # Add full-width writers (use full mask)
                for writer in full_width_writers:
                    enable_id = writer_enables.get(writer)
                    enable_ssa = self.value_map.get(enable_id) if enable_id else None
                    if enable_ssa:
                        temp = self._get_fresh_ssa_value(f"{mem_name}_mask_temp")
                        self._emit(f'{temp} = comb.mux {enable_ssa}, {full_mask}, {current_result} : i{width}')
                        current_result = temp

                # Assign final mask
                if current_result != zero_mask:
                    self._emit(f'{word_mask} = comb.or {current_result}, {zero_mask} : i{width}')  # Just to assign to word_mask
                    word_mask = current_result
                else:
                    word_mask = zero_mask

                # 4. Merge: (current & ~mask) | (new_data & mask)
                inv_mask = self._get_fresh_ssa_value(f"{mem_name}_inv_mask")
                self._emit(f'{inv_mask} = comb.xor {word_mask}, {full_mask} : i{width}')
                preserved = self._get_fresh_ssa_value(f"{mem_name}_preserved")
                self._emit(f'{preserved} = comb.and {current_word}, {inv_mask} : i{width}')
                new_masked = self._get_fresh_ssa_value(f"{mem_name}_new_masked")
                self._emit(f'{new_masked} = comb.and {write_data_ssa}, {word_mask} : i{width}')
                merged_data = self._get_fresh_ssa_value(f"{mem_name}_merged_data")
                self._emit(f'{merged_data} = comb.or {preserved}, {new_masked} : i{width}')

                self._emit(f'sv.passign {elem_ref}, {merged_data} : i{width}')
            else:
                # Full-width write
                self._emit(f'sv.passign {elem_ref}, {write_data_ssa} : i{width}')

            self.indent_level -= 1
            self._emit('}')
            self.indent_level -= 1
            self._emit('}')

    def _generate_stateful_memory_arrays(self):
        """Generate array structures for stateful memories (forward references to registers)."""
        if not hasattr(self, 'stateful_arrays') or not self.stateful_arrays:
            return

        for mem_name, (width, depth) in self.stateful_arrays.items():
            self._generate_stateful_memory_array(mem_name, width, depth)

    def _generate_stateful_memory_all_registers(self):
        """Generate register definitions for all stateful memories."""
        if not hasattr(self, 'stateful_arrays') or not self.stateful_arrays:
            return

        for mem_name, (width, depth) in self.stateful_arrays.items():
            self._generate_stateful_memory_registers(mem_name, width, depth)

    def _generate_stateful_memory_array(self, mem_name: str, width: int, depth: int):
        """Generate the array portion of a stateful memory.

        This creates the register SSA names and builds an array from them
        using forward references. The actual registers are defined later
        in _generate_stateful_memory_registers().

        Args:
            mem_name: Name of the memory (e.g., 'rf')
            width: Bit width of each element
            depth: Number of elements
        """
        self._emit("")
        self._emit(f"// Stateful memory {mem_name} - register array (forward refs)")

        # Create register SSA names (these will be defined by seq.compreg later)
        reg_outputs = []
        for i in range(depth):
            reg_out = self._get_fresh_ssa_value(f"{mem_name}_reg_{i}")
            reg_outputs.append(reg_out)

        # Store for later use in register definition
        if not hasattr(self, 'stateful_reg_outputs'):
            self.stateful_reg_outputs = {}
        self.stateful_reg_outputs[mem_name] = reg_outputs

        # Create array from register outputs (forward references - allowed in CIRCT)
        mem_array = self._get_fresh_ssa_value(f"{mem_name}_array")
        elements_str = ", ".join(reversed(reg_outputs))
        self._emit(f'{mem_array} = hw.array_create {elements_str} : i{width}')

        # Update the memory value_map to point to this array
        self.value_map[mem_name] = mem_array

    def _generate_stateful_memory_registers(self, mem_name: str, width: int, depth: int):
        """Generate the register definitions for a stateful memory.

        This computes next values and creates seq.compreg for each register.
        Must be called AFTER combinational logic so write signals are available.

        Args:
            mem_name: Name of the memory (e.g., 'rf')
            width: Bit width of each element
            depth: Number of elements
        """
        self._emit("")
        self._emit(f"// Stateful memory {mem_name} - register definitions")

        clk = self.value_map.get("clk", "%clk_0")
        reset = self.value_map.get("reset", "%reset_1")

        # Get the pre-allocated register outputs
        if not hasattr(self, 'stateful_reg_outputs') or mem_name not in self.stateful_reg_outputs:
            self._emit(f"// WARNING: {mem_name} register outputs not allocated")
            return
        reg_outputs = self.stateful_reg_outputs[mem_name]

        # Find the memory write port (naming convention: <mem>_shared_wr)
        wr_port_id = f'{mem_name}_shared_wr'
        wr_node = self.graph.nodes.get(wr_port_id)

        # For read-only memories (like imem), generate simple registers without write logic
        is_read_only = (wr_node is None)
        if is_read_only:
            self._emit(f"// Read-only memory {mem_name} - registers hold reset values")
            for i in range(depth):
                reg_out = reg_outputs[i]
                # Create register that just holds its reset value
                reset_val = self._get_fresh_ssa_value(f"{mem_name}_reset_{i}")
                self._emit(f'{reset_val} = hw.constant 0 : i{width}')
                self._emit(f'{reg_out} = seq.compreg {reg_out}, {clk} reset {reset}, {reset_val} : i{width}')
            return

        # Get write_data, write_address, write_enable from the write port
        write_data_id = None
        write_addr_id = None
        write_enable_id = None

        for edge in wr_node.incoming_edges:
            edge_type = edge.data.get('type', '')
            if edge_type == 'write_data':
                write_data_id = edge.source.id
            elif edge_type == 'write_address':
                write_addr_id = edge.source.id
            elif edge_type == 'write_enable':
                write_enable_id = edge.source.id

        if not all([write_data_id, write_addr_id, write_enable_id]):
            self._emit(f"// WARNING: Missing {mem_name} write signals")
            return

        # Get SSA values for write signals (should be defined by now)
        write_data_ssa = self.value_map.get(write_data_id)
        write_addr_ssa = self.value_map.get(write_addr_id)
        write_enable_ssa = self.value_map.get(write_enable_id)

        if not all([write_data_ssa, write_addr_ssa, write_enable_ssa]):
            self._emit(f"// WARNING: Missing SSA values for {mem_name} write signals")
            return

        # Compute address width from depth
        import math
        addr_width = max(1, math.ceil(math.log2(depth))) if depth > 1 else 1

        # Get the actual width of the write address from the graph node
        # For register files, the mux is already generated at the correct width (addr_width)
        # so we should default to addr_width, not 32
        write_addr_node = self.graph.nodes.get(write_addr_id)
        write_addr_width = self._get_width(write_addr_node) if write_addr_node else None
        if write_addr_width is None:
            write_addr_width = self.signal_widths.get(write_addr_id)
        # Fallback to addr_width if we can't determine the width
        # This is the expected case for register files where the mux is already at correct width
        if write_addr_width is None:
            write_addr_width = addr_width

        # Extract lower bits of address if needed (for comparing with index)
        if write_addr_width > addr_width:
            extracted_addr = self._get_fresh_ssa_value(f"{mem_name}_addr_extracted")
            self._emit(f'{extracted_addr} = comb.extract {write_addr_ssa} from 0 : (i{write_addr_width}) -> i{addr_width}')
            write_addr_ssa_for_compare = extracted_addr
        else:
            write_addr_ssa_for_compare = write_addr_ssa

        # Check if this memory has a hardwired zero element (like RISC-V x0)
        has_hardwired_zero = False
        if 'rd' in write_addr_id.lower() or 'dest' in write_addr_id.lower():
            has_hardwired_zero = True

        # Generate write logic and registers
        for i in range(depth):
            reg_out = reg_outputs[i]

            # Constant for comparing addr == i
            idx_const = self._get_fresh_ssa_value(f"{mem_name}_idx_{i}")
            self._emit(f'{idx_const} = hw.constant {i} : i{addr_width}')

            # Compare: addr == i (using extracted/truncated address for correct width)
            addr_match = self._get_fresh_ssa_value(f"{mem_name}_addr_eq_{i}")
            self._emit(f'{addr_match} = comb.icmp eq {write_addr_ssa_for_compare}, {idx_const} : i{addr_width}')

            # AND with write_enable: write_enable && addr == i
            do_write = self._get_fresh_ssa_value(f"{mem_name}_write_{i}")
            self._emit(f'{do_write} = comb.and {write_enable_ssa}, {addr_match} : i1')

            # Next value: do_write ? write_data : reg_out
            # For element 0 in register files, always stay 0 (hardwired zero)
            if i == 0 and has_hardwired_zero:
                zero_val = self._get_fresh_ssa_value(f"{mem_name}_0_zero")
                self._emit(f'{zero_val} = hw.constant 0 : i{width}')
                reg_next = zero_val
            else:
                reg_next = self._get_fresh_ssa_value(f"{mem_name}_next_{i}")
                self._emit(f'{reg_next} = comb.mux {do_write}, {write_data_ssa}, {reg_out} : i{width}')

            # Create the register
            reset_val = self._get_fresh_ssa_value(f"{mem_name}_reset_{i}")
            self._emit(f'{reset_val} = hw.constant 0 : i{width}')
            self._emit(f'{reg_out} = seq.compreg {reg_next}, {clk} reset {reset}, {reset_val} : i{width}')

    def _generate_sequential_logic(self):
        """Generate sequential logic using seq dialect operations."""
        self._emit("")
        self._emit("// Sequential logic")

        # Generate clock and reset
        clk = self.value_map.get("clk", "%clk_0")
        reset = self.value_map.get("reset", "%reset_1")

        # Only create registers for actual state nodes (_rd nodes)
        # e.g., pc_rd should be driven by pc_wr
        for node_id in list(self.registers):
            # Only process _rd nodes (actual register state)
            if not node_id.endswith('_rd'):
                continue

            node = self.graph.nodes.get(node_id)
            if not node:
                continue

            # Skip memories and external memories
            if node_id in self.memories:
                continue
            if node_id in {'imem', 'dmem'}:
                continue

            width = self._get_width(node) or 32
            reg_val = self._get_or_create_value(node_id)

            # Find what drives this register by traversing the graph
            # For split rd/wr nodes, check the _wr node's incoming edges
            next_val = None

            # Check if there's a corresponding _wr node (for split rd/wr registers)
            wr_node_id = node_id.replace('_rd', '_wr')
            if wr_node_id in self.graph.nodes:
                wr_node = self.graph.nodes[wr_node_id]
                for edge in wr_node.incoming_edges:
                    edge_type = edge.data.get('type', '')
                    if edge_type == 'assignment':
                        next_val = self._get_or_create_value(edge.source.id)
                        break

            # Also check direct assignment edges on the _rd node itself
            if not next_val:
                for edge in node.incoming_edges:
                    edge_type = edge.data.get('type', '')
                    if edge_type in ['assignment', 'state_update']:
                        next_val = self._get_or_create_value(edge.source.id)
                        break

            if next_val:
                # Check for stall edges on this ISA state register
                # (similar to pipeline registers, ISA state should hold during stalls)
                stall_signal = None
                for edge in node.incoming_edges:
                    edge_type = edge.data.get('type', '')
                    if edge_type == 'stall':
                        stall_signal = self._get_or_create_value(edge.source.id)
                        break

                # Generate a register with the seq dialect
                # seq.compreg takes: input, clock, optional reset
                zero = self._get_fresh_ssa_value(f"zero_{node_id}")
                self._emit(f'{zero} = hw.constant 0 : {self._mlir_type(width)}')

                if stall_signal:
                    # When stalled, hold current value; when not stalled, update
                    one = self._get_fresh_ssa_value(f"one_{node_id}")
                    self._emit(f'{one} = hw.constant 1 : i1')
                    not_stall = self._get_fresh_ssa_value(f"not_stall_{node_id}")
                    self._emit(f'{not_stall} = comb.xor {stall_signal}, {one} : i1')
                    mux_result = self._get_fresh_ssa_value(f"mux_{node_id}")
                    self._emit(f'{mux_result} = comb.mux {not_stall}, {next_val}, {reg_val} : {self._mlir_type(width)}')
                    self._emit(f'{reg_val} = seq.compreg {mux_result}, {clk} reset {reset}, {zero} : {self._mlir_type(width)}')
                else:
                    self._emit(f'{reg_val} = seq.compreg {next_val}, {clk} reset {reset}, {zero} : {self._mlir_type(width)}')

        # Generate pipeline registers
        self._emit("")
        self._emit("// Pipeline registers")
        self._generate_pipeline_registers(clk, reset)

        # Generate validity bits
        self._emit("")
        self._emit("// Validity bits")
        self._generate_validity_bits(clk, reset)

    def _generate_pipeline_registers(self, clk: str, reset: str):
        """Generate pipeline register sequential logic."""
        for node_id, node in self.graph.nodes.items():
            if node.data.get('type') != 'pipeline_register':
                continue

            width = self._get_width(node) or 32
            reg_val = self._get_or_create_value(node_id)
            self.signal_widths[node_id] = width

            # Find data input (pipeline_input edge)
            data_input = None
            stall_signal = None
            valid_gate = None

            for edge in node.incoming_edges:
                edge_type = edge.data.get('type', '')
                if edge_type == 'pipeline_input':
                    data_input = self._get_or_create_value(edge.source.id)
                elif edge_type == 'stall':
                    stall_signal = self._get_or_create_value(edge.source.id)
                elif edge_type == 'valid_gate':
                    valid_gate = self._get_or_create_value(edge.source.id)

            if not data_input:
                raise ValueError(f"CIRCT generator: pipeline_register '{node_id}' has no data input (expected edge with type 'pipeline_input')")

            # Generate register with conditional enable based on stall and valid_gate
            zero = self._get_fresh_ssa_value(f"zero_{node_id}")
            self._emit(f'{zero} = hw.constant 0 : {self._mlir_type(width)}')

            if stall_signal and valid_gate:
                # Enable = !stall && valid_gate
                not_stall = self._get_fresh_ssa_value(f"not_stall_{node_id}")
                one = self._get_fresh_ssa_value(f"one_{node_id}")
                self._emit(f'{one} = hw.constant 1 : i1')
                self._emit(f'{not_stall} = comb.xor {stall_signal}, {one} : i1')
                enable = self._get_fresh_ssa_value(f"enable_{node_id}")
                self._emit(f'{enable} = comb.and {not_stall}, {valid_gate} : i1')
                # Use mux to select between current value (when disabled) and new value
                mux_result = self._get_fresh_ssa_value(f"mux_{node_id}")
                self._emit(f'{mux_result} = comb.mux {enable}, {data_input}, {reg_val} : {self._mlir_type(width)}')
                self._emit(f'{reg_val} = seq.compreg {mux_result}, {clk} reset {reset}, {zero} : {self._mlir_type(width)}')
            elif stall_signal:
                # Enable = !stall
                not_stall = self._get_fresh_ssa_value(f"not_stall_{node_id}")
                one = self._get_fresh_ssa_value(f"one_{node_id}")
                self._emit(f'{one} = hw.constant 1 : i1')
                self._emit(f'{not_stall} = comb.xor {stall_signal}, {one} : i1')
                mux_result = self._get_fresh_ssa_value(f"mux_{node_id}")
                self._emit(f'{mux_result} = comb.mux {not_stall}, {data_input}, {reg_val} : {self._mlir_type(width)}')
                self._emit(f'{reg_val} = seq.compreg {mux_result}, {clk} reset {reset}, {zero} : {self._mlir_type(width)}')
            elif valid_gate:
                # Enable = valid_gate
                mux_result = self._get_fresh_ssa_value(f"mux_{node_id}")
                self._emit(f'{mux_result} = comb.mux {valid_gate}, {data_input}, {reg_val} : {self._mlir_type(width)}')
                self._emit(f'{reg_val} = seq.compreg {mux_result}, {clk} reset {reset}, {zero} : {self._mlir_type(width)}')
            else:
                # No conditional - always update
                self._emit(f'{reg_val} = seq.compreg {data_input}, {clk} reset {reset}, {zero} : {self._mlir_type(width)}')

    def _generate_validity_bits(self, clk: str, reset: str):
        """Generate validity bit sequential logic."""
        for node_id, node in self.graph.nodes.items():
            if node.data.get('type') != 'validity_bit':
                continue

            reg_val = self._get_or_create_value(node_id)
            self.signal_widths[node_id] = 1

            # Find data input (from pipeline_valid edge or similar)
            data_input = None
            stall_signal = None

            for edge in node.incoming_edges:
                edge_type = edge.data.get('type', '')
                if edge_type in ['pipeline_valid', 'validity_input', 'pipeline_input']:
                    data_input = self._get_or_create_value(edge.source.id)
                elif edge_type == 'stall':
                    stall_signal = self._get_or_create_value(edge.source.id)

            # Validity bits reset to 1 (valid) initially
            one = self._get_fresh_ssa_value(f"one_{node_id}")
            self._emit(f'{one} = hw.constant 1 : i1')

            if not data_input:
                # No input - just create a constant 1 register
                self._emit(f'{reg_val} = seq.compreg {one}, {clk} reset {reset}, {one} : i1')
                continue

            if stall_signal:
                # Enable = !stall
                not_stall = self._get_fresh_ssa_value(f"not_stall_{node_id}")
                self._emit(f'{not_stall} = comb.xor {stall_signal}, {one} : i1')
                mux_result = self._get_fresh_ssa_value(f"mux_{node_id}")
                self._emit(f'{mux_result} = comb.mux {not_stall}, {data_input}, {reg_val} : i1')
                self._emit(f'{reg_val} = seq.compreg {mux_result}, {clk} reset {reset}, {one} : i1')
            else:
                self._emit(f'{reg_val} = seq.compreg {data_input}, {clk} reset {reset}, {one} : i1')

    def _generate_output_assignments(self):
        """Generate output port assignments."""
        self._emit("")
        self._emit("// Output assignments")

        _, outputs = self._generate_module_ports()

        # No external memory ports - all memory is internal
        # Just emit hw.output with no values
        self._emit('hw.output')

    def _generate_module_footer(self):
        """Generate module closing."""
        self.indent_level -= 1
        self._emit("}")

    def generate(self) -> str:
        """
        Generate CIRCT MLIR from the resource graph.

        Returns:
            MLIR text representation
        """
        self.lines = []
        self.ssa_counter = 0
        self.value_map = {}
        self.generated_nodes = set()  # Track nodes that have had MLIR code generated

        # Emit MLIR header
        self._emit("// Generated by ISAComp CIRCT Backend")
        self._emit("")

        # Analyze graph
        self._analyze_graph()

        # Generate module
        self._generate_module_header()
        self._emit("")

        # Generate constants
        self._emit("// Constants")
        self._generate_constants()
        self._emit("")

        # Generate arrays (register files, memories)
        # For stateful arrays (with write ports), just create placeholder
        self._generate_arrays()

        # Generate hlmem declarations for large memories (imem, dmem)
        self._generate_hlmem_arrays()

        # Generate stateful memory arrays (forward references to register outputs)
        # This creates rf_array etc. that will be used by combinational logic
        self._generate_stateful_memory_arrays()

        # Generate combinational logic
        # This will use the stateful memory arrays (with forward refs) for reads
        self._emit("// Combinational logic")
        self._generate_combinational_logic()

        # Generate placeholders for undefined values (excluding arrays)
        self._generate_placeholders_for_undefined_values()

        # Generate stateful memory registers (defines the forward-referenced registers)
        # Must be after combinational logic so write signals are available
        self._generate_stateful_memory_all_registers()

        # Generate hlmem write operations (dmem writes)
        # Must be after combinational logic so write signals are available
        self._generate_hlmem_writes()

        # Generate sequential logic (PC and other scalar registers)
        self._generate_sequential_logic()

        # Generate outputs
        self._generate_output_assignments()

        # Close module
        self._generate_module_footer()

        return "\n".join(self.lines)


def generate_circt(graph: ResourceGraph, module_name: str = "processor") -> str:
    """
    Convenience function to generate CIRCT MLIR from a ResourceGraph.

    Args:
        graph: The ResourceGraph to convert
        module_name: Name for the top-level module

    Returns:
        MLIR text as a string
    """
    generator = CIRCTGenerator(graph, module_name)
    return generator.generate()
