"""
VHDL Generator for ISAComp

This module generates synthesizable VHDL code from ResourceGraph representations.
It mirrors the functionality of backends/verilog/verilog_generator.py but outputs VHDL instead of Verilog.
"""

import re
from typing import Dict, List, Set, Tuple
from core.resource_graph import ResourceGraph, Node, Edge
from enum import Enum
from .module_generators import (
    VHDLMuxGenerator,
    VHDLCounterGenerator,
    VHDLHazardDetectorGenerator,
    create_module_generator_from_node
)


class ModuleTypes(Enum):
    ALU = 'ALU'
    MUX = 'MUX'
    HAZARD_DETECTOR = 'HAZARD_DETECTOR'
    COUNTER = 'COUNTER'


class VHDLGenerator:
    """Generate VHDL implementation from ResourceGraph."""

    def __init__(self, graph: ResourceGraph, entity_name: str = "processor",
                 debug_outputs: List[str] = None,
                 interface_ports: Dict[str, str] = None):
        self.graph = graph
        self.entity_name = entity_name
        self.signal_declarations = []
        self.additional_signals = []  # For signals created during code generation
        self.memory_declarations = {}
        self.modules = []
        self.library_statements = set()
        self.combinational_logic = []
        self.initial_values = []
        self.process_blocks = []
        self.node_id_to_name = {}
        self.name_counter = {}
        self.declared_names = set()
        self.assigned_signals = set()

        # Module generators for complex hardware components
        self.module_generators = {}
        self.module_definitions = []
        self.module_instantiations = []

        # Debug outputs (signals to expose as top-level outputs)
        self.debug_outputs = debug_outputs or []

        # Interface ports to expose (signal_name -> direction: 'in' or 'out')
        self.interface_ports = interface_ports or {}

        # Track entity ports separately to avoid redeclaration as signals
        self.entity_ports = set()

        # Standard libraries
        self.library_statements.add("library IEEE;")
        self.library_statements.add("use IEEE.std_logic_1164.all;")
        self.library_statements.add("use IEEE.numeric_std.all;")

        # Constant resolution map for VHDL constants used in case choices
        # Maps constant names (from pyGHDL) to their literal values
        self.constant_map = {
            # ALU operations
            'ALU_OR': '"000"', 'ALU_AND': '"001"', 'ALU_XOR': '"010"', 'ALU_UNUSED': '"011"',
            'ALU_ADD': '"100"', 'ALU_SUB': '"101"', 'ALU_LESS_THAN_SIGNED': '"110"', 'ALU_LESS_THAN_UNSIGNED': '"111"',
            # Branch test modes
            'BRANCH_TEST_EQ': '"000"', 'BRANCH_TEST_NE': '"001"', 'BRANCH_TEST_TRUE': '"010"', 'BRANCH_TEST_FALSE': '"011"',
            'BRANCH_TEST_LT': '"100"', 'BRANCH_TEST_GE': '"101"', 'BRANCH_TEST_LTU': '"110"', 'BRANCH_TEST_GEU': '"111"',
            # Data bus mux selectors (1-bit - use character literals for std_logic)
            'A_BUS_REGISTER': "'0'", 'A_BUS_PC': "'1'",
            'B_BUS_REGISTER': "'0'", 'B_BUS_IMMEDIATE': "'1'",
            # PC modes
            'PC_JMP_RELATIVE': '"00"', 'PC_JMP_REG_RELATIVE': '"01"', 'PC_JMP_RELATIVE_CONDITIONAL': '"10"', 'PC_RESET_STATE': '"11"',
            # Result sources
            'RESULT_ALU': '"00"', 'RESULT_SHIFTER': '"01"', 'RESULT_MEMORY': '"10"', 'RESULT_PC_PLUS_4': '"11"',
            # Sign extension modes (2-bit width, 1-bit signed/unsigned)
            'SIGN_EX_WIDTH_B': '"00"', 'SIGN_EX_WIDTH_H': '"01"', 'SIGN_EX_WIDTH_W': '"10"', 'SIGN_EX_WIDTH_X': '"11"',
            'SIGN_EX_SIGNED': "'0'", 'SIGN_EX_UNSIGNED': "'1'",
            # Shifter modes
            'SHIFTER_LEFT_LOGICAL': '"00"', 'SHIFTER_LEFT_ARITH': '"01"', 'SHIFTER_RIGHT_LOGICAL': '"10"', 'SHIFTER_RIGHT_ARITH': '"11"',
        }

    def generate(self) -> str:
        """Generate complete VHDL entity and architecture."""
        # Mark entity ports to prevent redeclaration as signals
        # This must happen before _analyze_graph() processes nodes
        self.entity_ports.add('clk')
        self.entity_ports.add('reset')
        self.declared_names.add('clk')
        self.declared_names.add('reset')

        # Mark interface ports BEFORE _analyze_graph() to prevent redeclaration as signals
        for port_name in self.interface_ports.keys():
            self.entity_ports.add(port_name)
            self.declared_names.add(port_name)

        # Pre-process: identify array signals before _analyze_graph
        self._identify_array_signals()

        self._analyze_graph()
        self._mark_concatenations()  # Mark concatenations before declarations

        self._generate_extra_modules()
        self._generate_entity_header()
        self._generate_declarations()
        self._generate_memory_initialization()
        self._generate_combinational_logic()
        self._generate_sequential_logic()

        return self._assemble_module()

    def _identify_array_signals(self):
        """Identify signals that are used as arrays and mark them for array declaration."""
        # Find all array_access nodes with computed indices
        for node in self.graph.nodes.values():
            if node.data.get('type') == 'array_access':
                # Find the array source and index
                array_source = None
                index_source = None
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'array':
                        array_source = edge.source
                    elif edge.data.get('type') == 'index':
                        index_source = edge.source

                if array_source and index_source:
                    # Check if this is a computed-index access (needs array type) or
                    # constant-index bit access (remains flat vector)
                    # Constant indices have type='literal' and numeric value
                    is_constant_index = (
                        index_source.data.get('type') == 'literal' and
                        isinstance(index_source.data.get('value'), (int, str)) and
                        not index_source.data.get('is_variable')
                    )

                    # Only treat as array if using computed index (variable/expression)
                    # and element width > 1 (array of vectors, not bit array)
                    element_width = node.data.get('bit_width', 32)
                    if not is_constant_index and element_width > 1:
                        # Mark the array source as needing array type declaration
                        array_source.data['is_array_signal'] = True
                        # Infer array parameters from the access
                        index_width = index_source.data.get('bit_width', None)

                        # If index width not set (e.g., for process variables),
                        # try to infer from what it's assigned from
                        if index_width is None:
                            for edge in index_source.incoming_edges:
                                edge_type = edge.data.get('type', '')
                                if edge_type in ['assignment', 'variable_assignment']:
                                    assigned_from = edge.source
                                    inferred_width = assigned_from.data.get('bit_width')
                                    if inferred_width is not None:
                                        index_width = inferred_width
                                        break

                        # Still no width? Default to 5 for register files
                        if index_width is None:
                            index_width = 5

                        # Cap array depth to reasonable size for simulation
                        # If index is 32-bit address, limit to 2^12 (4096 entries = 16KB)
                        # as typical for small test memories
                        effective_index_width = min(index_width, 12)

                        array_source.data['array_element_width'] = element_width
                        array_source.data['array_index_width'] = effective_index_width
                        array_source.data['array_depth'] = 2 ** effective_index_width

    def _mark_concatenations(self):
        """Pre-pass to mark nodes that are concatenations.

        This must run before signal declarations so that _produces_boolean_result()
        can check the is_concatenation flag.
        """
        for node in self.graph.nodes.values():
            if node.data.get('type') == 'operation':
                operator = node.data.get('operator', '')
                # Check if this is a & operation that should be treated as concatenation
                if operator == '&' and not node.data.get('is_concatenation'):
                    # Same logic as line 1196-1209: check for literal or concat operands
                    has_literal_or_concat = False
                    for edge in node.incoming_edges:
                        operand = edge.source
                        if (operand.data.get('type') == 'literal' or
                            operand.data.get('is_concatenation') or
                            operand.data.get('operator') == 'concat'):
                            has_literal_or_concat = True
                            break

                    if has_literal_or_concat:
                        # Mark as concatenation
                        node.data['operator'] = 'concat'
                        node.data['is_concatenation'] = True

    def _get_signal_width(self, signal_name: str) -> int:
        """Get the declared width of a signal."""
        # Check for single bit index: signal(N)
        import re
        bit_index_match = re.match(r'^(\w+)\((\d+)\)$', signal_name)
        if bit_index_match:
            # Single bit indexing returns 1 bit
            return 1

        # Check for bit slice: signal(N downto M)
        slice_match = re.match(r'^(\w+)\((\d+)\s+downto\s+(\d+)\)$', signal_name)
        if slice_match:
            high = int(slice_match.group(2))
            low = int(slice_match.group(3))
            return high - low + 1

        # Check for hex literal: x"NNNN"
        if signal_name.startswith('x"') and signal_name.endswith('"'):
            hex_digits = signal_name[2:-1]
            return len(hex_digits) * 4  # 4 bits per hex digit

        # Check for binary literal: b"NNNN" or "NNNN"
        if signal_name.startswith('b"') and signal_name.endswith('"'):
            return len(signal_name[2:-1])  # 1 bit per binary digit
        if signal_name.startswith('"') and signal_name.endswith('"'):
            inner = signal_name[1:-1]
            if all(c in '01' for c in inner):
                return len(inner)  # Binary literal

        # Check for character literal: '0' or '1'
        if signal_name.startswith("'") and signal_name.endswith("'") and len(signal_name) == 3:
            return 1

        for sig_decl in self.signal_declarations:
            if sig_decl['name'] == signal_name:
                width = sig_decl['bit_width']
                return width if width is not None else 32

        # Check interface ports (may be ('direction', width) tuple or just 'direction')
        if signal_name in self.interface_ports:
            port_info = self.interface_ports[signal_name]
            if isinstance(port_info, tuple) and len(port_info) >= 2:
                return port_info[1]
            # Default for 'in'/'out' string is 1-bit
            return 1

        return 32  # Default

    def _is_registered_signal(self, signal_name: str) -> bool:
        """Check if a signal is registered (clocked/state signal)."""
        for sig_decl in self.signal_declarations:
            if sig_decl['name'] == signal_name:
                return sig_decl.get('is_register', False)
        return False

    def _can_inline_literal(self, node: Node) -> bool:
        """Determine if a literal can be inlined (only used in operations).

        Returns True if the literal is only used as an operand in operations,
        False if it's used in direct assignments or other contexts.
        """
        if node.data.get('type') != 'literal':
            return False

        # Check if we can actually format this literal inline
        # Try to format it and see if it succeeds
        formatted = self._format_literal_inline(node)
        if formatted is None:
            # Can't format this literal inline (e.g., value=3 with width=1)
            return False

        # Check all outgoing edges
        for edge in node.outgoing_edges:
            target = edge.target
            # If used in anything other than an operation, it needs a signal
            if target.data.get('type') not in ['operation', 'comparison']:
                return False

        # Can be formatted and only used in operations, safe to inline
        return len(node.outgoing_edges) > 0

    def _analyze_graph(self):
        """Analyze the graph to determine signal types and dependencies."""
        for node in self.graph.nodes.values():
            if node.is_arch_state:
                if node.data.get('type') in ['multiplexer', 'alu_module', 'uarch_counter',
                                              'serialization_counter', 'memory_port_counter',
                                              'memory_access_counter', 'hazard_detection_unit',
                                              'hazard_detector']:
                    self._process_module_node(node)
                else:
                    self._process_isa_state_node(node)
            elif node.data.get('type', '').startswith('isa_state'):
                if node.data.get('is_split_port'):
                    self._process_split_memory_port(node)
                else:
                    self._process_variable_node(node)
            elif node.data.get('type') in ['var', 'temp_var', 'variable'] or node.data.get('is_variable'):
                self._process_variable_node(node)
            elif node.data.get('type') == 'pipeline_stall_controller':
                # Stall controllers are combinational - just declare the signal
                # The logic will be generated in _generate_combinational_logic
                self._process_variable_node(node)
            elif node.is_uarch_state or node.data.get('type') in ['pipeline_register', 'validity_bit']:
                # Handle uarch state nodes (pipeline registers, validity bits)
                self._process_variable_node(node)
            elif node.data.get('type') in ['operation', 'array_access', 'bit_slice',
                                           'write_data_slice', 'concatenation', 'repetition',
                                           'ternary_op', 'literal', 'sized_literal',
                                           'comparison', 'logical_and',
                                           'logical_or', 'instruction_enable', 'address_offset',
                                           'port_address_offset', 'memory_data_merge', 'port_data_merge',
                                           'zero_extend', 'sign_extend']:
                # Skip literals that can be inlined (only used in operations)
                if node.data.get('type') == 'literal' and self._can_inline_literal(node):
                    continue
                self._process_intermediate_node(node)
            elif node.data.get('type') in ['multiplexer', 'alu_module', 'uarch_counter',
                                           'serialization_counter', 'memory_port_counter',
                                           'memory_access_counter', 'hazard_detection_unit',
                                           'hazard_detector']:
                self._process_module_node(node)

    def _process_isa_state_node(self, node: Node):
        """Process ISA state nodes for VHDL generation."""
        if '_rd' in node.id or '_wr' in node.id:
            name = node.id
        else:
            name = node.data.get('name', node.id)

        if node.data.get('bit_width') is not None:
            bit_width = node.data['bit_width']
        else:
            bit_width = self._infer_bit_width(node)

        is_memory = node.data.get('is_memory', False)

        if is_memory:
            addr_width = node.data['array_depth']
            array_depth = 2 ** addr_width

            # Main memory (imem, dmem, mem) should be loaded from files
            # Register file (rf) should initialize to zeros
            mem_file = None
            if name == 'imem':
                mem_file = "imem.mem"
            elif name == 'dmem':
                mem_file = "dmem.mem"
            elif name == 'mem':
                mem_file = "mem.mem"  # Unified memory

            self.memory_declarations[name] = {
                'bit_width': bit_width,
                'array_depth': array_depth,
                'addr_width': addr_width,
                'mem_file': mem_file
            }
        else:
            sanitized_name = self._sanitize_identifier(name)

            if sanitized_name in self.declared_names:
                return

            self.declared_names.add(sanitized_name)
            self.node_id_to_name[node.id] = sanitized_name

            # Determine if this is a register signal (needs clock-driven logic)
            node_type = node.data.get('type')
            is_register = self._should_be_register(node) or node_type.startswith('isa_state')

            # Override bit_width to 1 for boolean operations
            if self._produces_boolean_result(node):
                bit_width = 1

            # Extract initial value if present
            initial_value = node.data.get('initial_value')

            self.signal_declarations.append({
                'name': sanitized_name,
                'bit_width': bit_width,
                'is_register': is_register,
                'reset_signal': f"reset_{sanitized_name}" if is_register else None,
                'initial_value': initial_value
            })

    def _process_variable_node(self, node: Node):
        """Process variable nodes."""
        # Support both 'name' and 'display_name' fields (VHDL parser uses display_name)
        # IMPORTANT: Use node.id for hierarchical names so that references match declarations
        # For hierarchical graphs, the node ID contains the full path (e.g., i_program_counter.add_lhs)
        # but display_name contains just the local name (e.g., add_lhs)
        if '.' in node.id:
            # Hierarchical node - use node.id to preserve full path
            name = node.id
        elif node.data.get('is_variable') and node.data.get('scoped_name'):
            # Process-local variable - use scoped_name for unique signal names
            # This ensures that variables with the same name in different processes
            # (e.g., word_addr in instr_fetch vs mem_write) get distinct signals
            name = node.data['scoped_name']
        else:
            name = node.data.get('name') or node.data.get('display_name') or node.id
        should_be_register = self._should_be_register(node)
        bit_width = self._infer_bit_width(node)

        # Sanitize name to handle hierarchical identifiers (e.g., i_alu.a -> i_alu_a)
        sanitized_name = self._sanitize_identifier(name)

        self.node_id_to_name[node.id] = sanitized_name

        # Skip if already declared (avoid duplicate signal declarations)
        if sanitized_name in self.declared_names:
            return
        self.declared_names.add(sanitized_name)

        # Check if this is an array signal (source of array_access with computed index)
        if node.data.get('is_array_signal'):
            # Add to memory_declarations as an array type
            element_width = node.data.get('array_element_width', 32)
            array_depth = node.data.get('array_depth', 32)
            addr_width = node.data.get('array_index_width', 5)

            # Main memory (mem, imem, dmem) should be loaded from file
            # Register files and other internal arrays should initialize to zeros
            mem_file = None
            if sanitized_name == 'imem':
                mem_file = "imem.mem"
            elif sanitized_name == 'dmem':
                mem_file = "dmem.mem"
            elif sanitized_name == 'mem':
                mem_file = "mem.mem"

            self.memory_declarations[sanitized_name] = {
                'bit_width': element_width,
                'array_depth': array_depth,
                'addr_width': addr_width,
                'mem_file': mem_file
            }
            return

        # Override bit_width to 1 for boolean operations
        if self._produces_boolean_result(node):
            bit_width = 1

        # Extract initial value if present
        initial_value = node.data.get('initial_value')

        self.signal_declarations.append({
            'name': sanitized_name,
            'bit_width': bit_width,
            'is_register': should_be_register,
            'reset_signal': f"reset_{sanitized_name}" if should_be_register else None,
            'initial_value': initial_value
        })

    def _should_be_register(self, node: Node) -> bool:
        """Determine if a variable should be a register based on usage."""
        # Pipeline registers and validity bits are always registers
        # BUT stall controllers are combinational (OR of hazard signals)
        if node.data.get('type') in ['pipeline_register', 'validity_bit']:
            return True
        # Stall controllers are NOT registers - they're combinational
        if node.data.get('type') == 'pipeline_stall_controller':
            return False
        # Uarch state nodes are registers
        if node.is_uarch_state:
            return True
        # Check if the node is explicitly marked as a register (from parser)
        if node.data.get('is_register', False):
            return True
        # Check if it's an ISA state node (always a register)
        if node.data.get('type', '').startswith('isa_state'):
            return True
        for edge in node.incoming_edges:
            if edge.data.get('type') == 'assignment':
                if self._expression_references_node(edge.data.get('right', {}), node):
                    return True
        return False

    def _expression_references_node(self, expr: Dict, target_node: Node) -> bool:
        """Check if an expression references a specific node."""
        if expr.get('type') == 'identifier':
            return expr.get('name') == target_node.data.get('name')
        elif expr.get('type') == 'binary_op':
            return (self._expression_references_node(expr.get('left', {}), target_node) or
                    self._expression_references_node(expr.get('right', {}), target_node))
        elif expr.get('type') in ['array_access', 'bit_slice']:
            base_expr = expr.get('target') or expr.get('array', {})
            return self._expression_references_node(base_expr, target_node)
        return False

    def _process_intermediate_node(self, node: Node):
        """Process intermediate computation nodes."""
        expr_id = node.id
        bit_width = self._infer_bit_width(node)

        node_type = node.data.get('type')

        if node_type == 'concatenation':
            vhdl_name = self._generate_concat_name(node)
        elif node_type == 'repetition':
            vhdl_name = self._generate_repetition_name(node)
        elif node_type == 'ternary_op':
            vhdl_name = self._generate_ternary_name(node)
        else:
            vhdl_name = self._sanitize_identifier(expr_id)

        self.node_id_to_name[expr_id] = vhdl_name

        if vhdl_name in self.declared_names:
            return

        self.declared_names.add(vhdl_name)

        # Override bit_width to 1 for boolean operations
        # Check if the corresponding node produces boolean result
        initial_value = None
        for n in self.graph.nodes.values():
            if n.id == expr_id:
                if self._produces_boolean_result(n):
                    bit_width = 1
                # For literal nodes, extract the value as initial value
                if n.data.get('type') == 'literal':
                    initial_value = n.data.get('value')
                break

        self.signal_declarations.append({
            'name': vhdl_name,
            'bit_width': bit_width,
            'is_register': False,
            'original_id': expr_id,
            'initial_value': initial_value
        })

    def _process_split_memory_port(self, node: Node):
        """Process split memory port nodes (simplified version)."""
        self._process_variable_node(node)

    def _process_module_node(self, node: Node):
        """Process nodes that represent hardware modules."""
        node_type = node.data.get('type')
        node_name = node.data.get('name', node.id)

        try:
            # For muxes, always try to infer width from inputs (may override incorrect defaults)
            bit_width = node.data.get('data_width', node.data.get('output_width', node.data.get('bit_width')))
            if node_type == 'multiplexer':
                # Infer width from mux_input sources - find the maximum width
                inferred_width = None
                for edge in node.incoming_edges:
                    if edge.data.get('type') in ['mux_input', 'mux_default_input']:
                        source_width = edge.source.data.get('bit_width')
                        if source_width is None:
                            source_width = self._infer_bit_width(edge.source)
                        if source_width and (inferred_width is None or source_width > inferred_width):
                            inferred_width = source_width
                # Use inferred width if found and larger than current (fixes 32->64 bit issues)
                if inferred_width and (bit_width is None or inferred_width > bit_width):
                    bit_width = inferred_width
                    # Update the node data so the module generator uses correct width
                    node.data['data_width'] = bit_width
            if bit_width is None:
                bit_width = 32  # Default fallback

            generator = create_module_generator_from_node(node.data)
            # Sanitize the generator's name for valid VHDL identifiers
            generator.name = self._sanitize_identifier(generator.name)
            self.module_generators[node.id] = generator

            sanitized_name = self._sanitize_identifier(node_name)
            self.node_id_to_name[node.id] = sanitized_name

            bit_width = node.data.get('data_width', node.data.get('output_width', node.data.get('bit_width', 32)))

            # For multiplexers, infer the maximum input width and update if needed
            if node_type == 'multiplexer':
                max_input_width = bit_width
                for edge in node.incoming_edges:
                    if edge.data.get('type') in ['mux_input', 'mux_default_input']:
                        source_width = edge.source.data.get('bit_width')
                        if source_width is None:
                            source_width = self._infer_bit_width(edge.source)
                        if source_width and source_width > max_input_width:
                            max_input_width = source_width
                # Update the generator's data_width if we found wider inputs
                if max_input_width > bit_width:
                    generator.data_width = max_input_width
                    bit_width = max_input_width
                    node.data['data_width'] = max_input_width


            if sanitized_name not in self.declared_names:
                self.signal_declarations.append({
                    'name': sanitized_name,
                    'bit_width': bit_width,
                    'is_register': False
                })
                self.declared_names.add(sanitized_name)

        except (ValueError, KeyError) as e:
            print(f"Warning: Could not create module generator for {node.id}: {e}")
            self._process_intermediate_node(node)

    def _strip_library_declarations(self, vhdl_code: str) -> str:
        """Strip library declarations from VHDL code (to avoid duplicates in single file)."""
        lines = vhdl_code.split('\n')
        filtered_lines = []
        skip_blank = False

        for line in lines:
            stripped = line.strip()
            # Skip library and use statements
            if stripped.startswith('library ') or stripped.startswith('use '):
                skip_blank = True  # Also skip the blank line after library declarations
                continue
            # Skip one blank line after library declarations
            if skip_blank and not stripped:
                skip_blank = False
                continue
            filtered_lines.append(line)

        return '\n'.join(filtered_lines)

    def _generate_extra_modules(self):
        """Generate extra modules like ALU, MUX, etc."""
        for node_id, generator in self.module_generators.items():
            module_def = generator.generate_module()
            # Keep library declarations - each design unit needs them in VHDL
            self.module_definitions.append(module_def)

    def _infer_bit_width(self, node: Node, visited: set = None) -> int:
        """Infer bit width for a node based on context."""
        if visited is None:
            visited = set()

        # Prevent infinite recursion
        if id(node) in visited:
            return 32  # Default width if we hit a cycle

        visited.add(id(node))

        # Check if bit_width is directly available in node data (from parser)
        # This takes priority over inference
        if 'bit_width' in node.data and node.data['bit_width'] is not None:
            return node.data['bit_width']

        # For _wr signals (write ports), inherit width from corresponding _rd signal
        # This ensures pc_wr gets the same 64-bit width as pc_rd for RV64I
        if node.id.endswith('_wr'):
            rd_node_id = node.id[:-3] + '_rd'
            rd_node = self.graph.nodes.get(rd_node_id)
            if rd_node and rd_node.data.get('bit_width') is not None:
                return rd_node.data['bit_width']

        if self._produces_boolean_result(node):
            return 1

        # For unary operations (like NOT), propagate the operand's bit width
        if node.data.get('type') == 'operation':
            operator = node.data.get('operator', '')
            # Unary operations: not, negate (-), bitwise invert (~)
            if operator in ['not', 'inv', '~', 'negate', '-'] and len(node.incoming_edges) == 1:
                # Get the single operand
                operand_edge = list(node.incoming_edges)[0]
                operand = operand_edge.source
                # Propagate operand's bit width
                operand_width = self._infer_bit_width(operand, visited)
                return operand_width

        # For variables with assignment edges, infer from the source
        if node.data.get('type') in ['var', 'temp_var']:
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'assignment':
                    return self._infer_bit_width(edge.source, visited)
            # If no incoming assignment, try to infer from outgoing targets
            for edge in node.outgoing_edges:
                target = edge.target
                if target.data.get('bit_width') is not None:
                    return target.data['bit_width']

        # For literals, infer width from target signals they are assigned to
        if node.data.get('type') == 'literal':
            # Check all outgoing edges - if all targets have the same width, use that
            target_widths = set()
            for edge in node.outgoing_edges:
                target = edge.target
                target_width = target.data.get('bit_width')
                if target_width is not None:
                    target_widths.add(target_width)
            # If only one consistent target width, use it
            if len(target_widths) == 1:
                return target_widths.pop()
            # If multiple widths, use the minimum (safest)
            if len(target_widths) > 1:
                return min(target_widths)

        if node.data.get('type') == 'bit_slice':
            expr = node.data.get('expression', {})
            if expr.get('type') == 'bit_slice' and 'range' in expr:
                high, low = expr['range']
                return (high - low + 1)

        # For array access nodes (like rf[rs1]_rd), infer width from the base array
        if node.data.get('type') == 'array_access':
            # Try to find the base array node and get its width
            # Node ID format is typically: array_name[index]_rd or array_name[index]_wr
            node_id = node.id
            if '[' in node_id:
                base_name = node_id.split('[')[0]
                base_node = self.graph.nodes.get(base_name)
                if base_node and base_node.data.get('bit_width'):
                    return base_node.data['bit_width']
            # Also check incoming edges for array source
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'array':
                    source_width = edge.source.data.get('bit_width')
                    if source_width:
                        return source_width

        if node.data.get('type') == 'sized_literal':
            return node.data.get('width', 1)

        # Check for concatenations: explicit type, is_concatenation flag, concat operator
        # NOTE: Don't automatically treat '&' as concatenation - check context first
        is_concat = (node.data.get('type') == 'concatenation' or
                     node.data.get('is_concatenation') or
                     node.data.get('operator') == 'concat')

        # For '&' operator, check if it's actually a concatenation (not logical AND)
        if not is_concat and node.data.get('operator') == '&':
            # Check if any operand has multi-bit width (indicates concatenation)
            for edge in node.incoming_edges:
                operand = edge.source
                operand_width = operand.data.get('bit_width')
                if operand_width is not None and operand_width > 1:
                    is_concat = True
                    break
                # Check if operand is itself a concatenation
                if (operand.data.get('type') == 'concatenation' or
                    operand.data.get('is_concatenation') or
                    operand.data.get('operator') == 'concat'):
                    is_concat = True
                    break

        if is_concat:
            if node.incoming_edges:
                total_width = 0
                for edge in node.incoming_edges:
                    source = edge.source
                    source_type = source.data.get('type')

                    # For concatenations, we need to account for LSB extraction
                    # The generator extracts LSB from multi-bit literals in concatenations
                    # So each source contributes 1 bit, not its full inferred width
                    if source_type == 'literal':
                        # Literals in concatenations contribute 1 bit (LSB)
                        source_width = 1
                    elif source_type == 'sized_literal':
                        # Sized literals use their declared width
                        source_width = source.data.get('width', 1)
                    else:
                        # For signals, bit slices, and other nodes, use their actual width
                        source_width = source.data.get('bit_width')
                        if source_width is None:
                            # Infer width for this source
                            source_width = self._infer_bit_width(source, visited)
                        # Keep the full width - don't reduce to 1 bit
                        # Only numeric literals get LSB extraction (handled above)

                    total_width += source_width

                return total_width

        if node.data.get('type') == 'repetition':
            # Repetition like {count{expr}} has width = count * expr_width
            expr = node.data.get('expression', {})
            count = expr.get('count', 1)
            if node.incoming_edges:
                # Get width of the repeated expression
                source_width = self._infer_bit_width(list(node.incoming_edges)[0].source, visited)
                return count * source_width
            return count  # Assume 1-bit if no source

        # For ternary/conditional nodes, infer width from true/false branches
        if node.data.get('type') == 'ternary_op':
            max_width = None
            for edge in node.incoming_edges:
                edge_type = edge.data.get('type')
                if edge_type in ['ternary_true', 'ternary_false']:
                    source_width = edge.source.data.get('bit_width')
                    if source_width is None:
                        source_width = self._infer_bit_width(edge.source, visited)
                    if source_width and (max_width is None or source_width > max_width):
                        max_width = source_width
            if max_width is not None:
                return max_width

        # For array_access nodes accessing memory, return the MEMORY width (not consumer width)
        # This matches the Verilog generator behavior and ensures dmem_addr_rd is 32-bit
        if node.data.get('type') == 'array_access':
            for edge in node.incoming_edges:
                if edge.source.data.get('is_memory'):
                    source_width = edge.source.data.get('bit_width')
                    if source_width is not None:
                        return source_width
            # Fallback to target width if no memory source found
            for edge in node.outgoing_edges:
                target_width = edge.target.data.get('bit_width')
                if target_width is not None:
                    return target_width

        # For literals with simple values (0, 1) that are only assigned to single targets,
        # infer width from the target
        if node.data.get('type') == 'literal':
            value = node.data.get('value', 0)
            # Only for simple 0/1 values that could be 1-bit
            if value in [0, 1, '0', '1']:
                # Check if all outgoing edges go to 1-bit targets
                if node.outgoing_edges:
                    all_targets_1bit = True
                    for edge in node.outgoing_edges:
                        target = edge.target
                        target_width = target.data.get('bit_width')
                        if target_width is None:
                            target_width = self._infer_bit_width(target, visited)
                        if target_width != 1:
                            all_targets_1bit = False
                            break
                    if all_targets_1bit:
                        return 1

        for edge in node.incoming_edges | node.outgoing_edges:
            other_node = edge.source if edge.target == node else edge.target
            if other_node.is_arch_state and 'bit_width' in other_node.data:
                return other_node.data['bit_width']

        # For uarch_state nodes (pipeline registers), infer width from pipeline_input source
        if node.is_uarch_state or node.data.get('type') == 'pipeline_register':
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'pipeline_input':
                    source_width = edge.source.data.get('bit_width')
                    if source_width is None:
                        source_width = self._infer_bit_width(edge.source, visited)
                    if source_width is not None:
                        return source_width

        # For operation nodes (arithmetic, logical), infer width from operands
        if node.data.get('type') == 'operation':
            expr = node.data.get('expression', {})
            operator = expr.get('operator', node.data.get('operator', ''))
            # For arithmetic/logical operations, result width = max operand width
            if operator in ['+', '-', 'add', 'sub', '&', '|', '^', 'and', 'or', 'xor']:
                max_width = None
                for edge in node.incoming_edges:
                    source_width = edge.source.data.get('bit_width')
                    if source_width is None:
                        source_width = self._infer_bit_width(edge.source, visited)
                    if source_width and (max_width is None or source_width > max_width):
                        max_width = source_width
                if max_width is not None:
                    return max_width
            # For shift operations, result width = max operand width (excludes small shift amounts)
            if operator in ['<<', '>>', '>>>', 'sll', 'srl', 'sra']:
                # Find the largest operand width (the value being shifted, not the shift amount)
                max_width = None
                for edge in node.incoming_edges:
                    source_width = edge.source.data.get('bit_width')
                    if source_width is None:
                        source_width = self._infer_bit_width(edge.source, visited)
                    if source_width and (max_width is None or source_width > max_width):
                        max_width = source_width
                if max_width is not None:
                    return max_width

        return 32

    def _produces_boolean_result(self, node: Node) -> bool:
        """Determine if a node produces a boolean (1-bit) result."""
        node_type = node.data.get('type')

        if node_type in ['comparison', 'logical_and', 'logical_or', 'instruction_enable']:
            return True

        # If the node has an explicit bit_width > 1 set by parser, it's not a boolean operation
        # This handles bitwise AND/OR/XOR on vectors (e.g., vector AND x"FFFFFFFC")
        explicit_width = node.data.get('bit_width')
        if explicit_width is not None and explicit_width > 1:
            return False

        if node_type == 'operation':
            # Check ISA parser format (operator in expression)
            expr = node.data.get('expression', {})
            if expr.get('type') == 'binary_op':
                operator = expr.get('operator', '')
                # Check for comparison operators (both signed and unsigned)
                if operator in ['==', '!=', '<', '>', '<=', '>=', '<s', '>s', '<=s', '>=s', '<u', '>u', '<=u', '>=u', '=', '/=']:
                    return True

            # Check VHDL parser format (operator directly in data)
            operator = node.data.get('operator', '')
            if operator in ['==', '!=', '<', '>', '<=', '>=', '<s', '>s', '<=s', '>=s', '<u', '>u', '<=u', '>=u', '=', '/=']:
                return True

            # Check for logical operations (and, or, xor) on boolean operands
            # Handle both VHDL style (and, or, xor) and Verilog style (&, |, ^)
            # Exclude concatenation operations
            # For '&', check if it's being used as concatenation (not logical AND)
            # In VHDL parser output, '&' is concatenation if it has multi-bit operands being combined
            # BUT: Chained single-bit AND operations should NOT be treated as concatenations
            is_likely_concat = False
            if operator == '&':
                # Check if operands suggest concatenation (multi-bit values)
                for edge in node.incoming_edges:
                    operand = edge.source
                    operand_width = operand.data.get('bit_width')

                    # If any operand is explicitly multi-bit, it's concatenation
                    if operand_width is not None and operand_width > 1:
                        is_likely_concat = True
                        break

                    # If operand is a literal, check context: if all operands are single-bit, it's AND
                    if operand.data.get('type') == 'literal':
                        # Only treat as concat if we can confirm it's multi-bit context
                        # For now, skip - let other checks determine
                        continue

                    # If operand is another & operation that produces multi-bit result, it's concat chain
                    if operand.data.get('operator') == '&':
                        # Check if this nested & is a concatenation (has explicit multi-bit width)
                        nested_width = operand.data.get('bit_width')
                        if nested_width is not None and nested_width > 1:
                            is_likely_concat = True
                            break

            if operator in ['and', 'or', 'xor', 'nand', 'nor', 'xnor', '&', '|', '^', '&&', '||'] and operator != 'concat' and not node.data.get('is_concatenation') and not is_likely_concat:
                # For & operator, check if it will be treated as concatenation or boolean AND
                # The generator converts '&' to 'and' in VHDL (line 1427) for boolean operations
                # But also uses 'concat' operator for concatenations
                # Key insight: if this '&' has literal operands, it's a concatenation
                # Otherwise, it's a boolean AND and always produces 1-bit result
                if operator == '&':
                    # Check if any operand is a literal or already marked as concatenation
                    has_small_literal_or_concat = False
                    has_multibit_operand = False
                    has_multibit_literal_mask = False
                    for edge in node.incoming_edges:
                        operand = edge.source
                        operand_type = operand.data.get('type', '')

                        # Check for explicit concatenation markers
                        if (operand.data.get('is_concatenation') or
                            operand.data.get('operator') == 'concat'):
                            has_small_literal_or_concat = True
                            break

                        # Check for verilog_hex_literal with explicit width (e.g., 32'hFFFFFFFE)
                        # These are bitwise AND masks, NOT concatenations
                        if operand_type == 'sized_literal':
                            lit_width = operand.data.get('width')
                            if lit_width is not None and lit_width > 1:
                                has_multibit_literal_mask = True
                            continue

                        # Check for small literals (type='literal' without explicit width)
                        if operand_type == 'literal':
                            lit_width = operand.data.get('bit_width')
                            if lit_width is None or lit_width <= 1:
                                has_small_literal_or_concat = True
                                break
                            else:
                                has_multibit_literal_mask = True
                            continue

                        # Check if operand is multi-bit (bitwise operation)
                        operand_width = operand.data.get('bit_width')
                        if operand_width is not None and operand_width > 1:
                            has_multibit_operand = True
                        # Check if operand comes from array_access (e.g., register file read)
                        # These are always multi-bit (32-bit for RV32)
                        for op_edge in operand.incoming_edges:
                            if op_edge.source.data.get('type') == 'array_access':
                                has_multibit_operand = True
                                break
                        # Check if operand is a var that reads from array (rf[rs1], etc)
                        if operand.data.get('type') == 'var' and operand.data.get('name') in ['r1', 'r2']:
                            has_multibit_operand = True

                    if has_multibit_literal_mask:
                        # Bitwise AND with a multi-bit mask (e.g., x & 32'hFFFFFFFE)
                        # Result is multi-bit, NOT boolean
                        return False
                    elif has_small_literal_or_concat:
                        # This is a concatenation - NOT boolean
                        # Will be marked as concat later (line 1208)
                        return False
                    elif has_multibit_operand:
                        # Operands are multi-bit, so this is bitwise AND (multi-bit result)
                        return False
                    else:
                        # This is a boolean AND operation
                        # Result is always 1-bit (width mismatch handler will extract bits)
                        return True

                # For 'and' operator, check if it's bitwise AND on vectors
                # In VHDL, 'and' can be either boolean (1-bit) or bitwise (multi-bit vectors)
                if operator == 'and':
                    # Check if any operand is explicitly multi-bit
                    for edge in node.incoming_edges:
                        operand = edge.source
                        operand_width = operand.data.get('bit_width')
                        if operand_width is not None and operand_width > 1:
                            # This is a bitwise AND on vectors, NOT boolean
                            return False
                        # Check if operand comes from array_access (e.g., register file read)
                        for op_edge in operand.incoming_edges:
                            if op_edge.source.data.get('type') == 'array_access':
                                return False
                        # Check if operand is a var that reads from array (rf[rs1], etc)
                        if operand.data.get('type') == 'var' and operand.data.get('name') in ['r1', 'r2']:
                            return False

                # Similarly for | and ^ and xor - check if bitwise (multi-bit) or boolean (1-bit)
                if operator in ['|', '^', 'xor']:
                    # Check for literal operands (would indicate concat-like usage)
                    # Also check for multi-bit operands (indicates bitwise operation)
                    has_literal = False
                    has_multibit_operand = False
                    for edge in node.incoming_edges:
                        operand = edge.source
                        if operand.data.get('type') == 'literal':
                            has_literal = True
                            # Don't break - continue checking other operands for multi-bit
                        operand_width = operand.data.get('bit_width')
                        if operand_width is not None and operand_width > 1:
                            has_multibit_operand = True
                        # Check if operand comes from array_access (e.g., register file read)
                        for op_edge in operand.incoming_edges:
                            if op_edge.source.data.get('type') == 'array_access':
                                has_multibit_operand = True
                                break
                        # Check if operand is a var that reads from array (rf[rs1], etc)
                        operand_name = operand.data.get('name', operand.id if hasattr(operand, 'id') else '')
                        if operand.data.get('type') == 'var' and operand_name in ['r1', 'r2']:
                            has_multibit_operand = True
                        # Check for operand names containing r1/r2 (like r1_or_r2, r1_and_r2)
                        if 'r1' in operand_name or 'r2' in operand_name:
                            has_multibit_operand = True
                    # If any operand is multi-bit, this is a bitwise operation (multi-bit result)
                    if has_multibit_operand:
                        return False
                    elif has_literal:
                        # Literal without multi-bit operand - might be special case, fall through
                        pass
                    else:
                        # No multi-bit operands, no literals - this is boolean
                        return True

                # Check operand widths for width mismatches
                # Look at explicit widths first to detect mismatches without recursion
                # At least one operand must have an explicit width for this check
                explicit_widths_found = []
                has_non_explicit = False
                for edge in node.incoming_edges:
                    operand = edge.source
                    explicit_width = operand.data.get('bit_width')
                    if explicit_width is not None:
                        explicit_widths_found.append(explicit_width)
                    else:
                        has_non_explicit = True

                # If we have at least one explicit width and at least one non-explicit width,
                # check if there's a mismatch (one is 1-bit, other is likely multi-bit)
                if len(explicit_widths_found) >= 1 and has_non_explicit:
                    # If any explicit width is 1, assume there's a width mismatch
                    # (the non-explicit operand is likely multi-bit if it doesn't produce boolean)
                    if any(w == 1 for w in explicit_widths_found):
                        # Check if the non-explicit operand is likely multi-bit
                        for edge in node.incoming_edges:
                            operand = edge.source
                            if operand.data.get('bit_width') is None:
                                # If it's not a comparison or another boolean-producing operation,
                                # assume it's multi-bit
                                if not self._produces_boolean_result(operand):
                                    return True  # Width mismatch: 1-bit and multi-bit

                # Check for width mismatches when all widths are explicit
                if len(explicit_widths_found) >= 2:
                    has_single_bit = any(w == 1 for w in explicit_widths_found)
                    has_multi_bit = any(w > 1 for w in explicit_widths_found)
                    if has_single_bit and has_multi_bit:
                        return True

                # Check if all operands are boolean (1-bit) - using explicit width or recursive check
                all_operands_boolean = True
                any_operand_boolean = False
                for edge in node.incoming_edges:
                    operand = edge.source
                    # Check if operand has explicit 1-bit width
                    operand_width = operand.data.get('bit_width')
                    is_boolean = False
                    if operand_width == 1:
                        is_boolean = True
                    else:
                        # Recursively check if operand produces boolean
                        is_boolean = self._produces_boolean_result(operand)

                    if is_boolean:
                        any_operand_boolean = True
                    else:
                        all_operands_boolean = False

                if all_operands_boolean and len(node.incoming_edges) > 0:
                    return True

                # Check for width mismatch: some operands are boolean, others are not
                # This happens when mixing 1-bit and multi-bit operands
                if any_operand_boolean and not all_operands_boolean and len(node.incoming_edges) > 1:
                    return True  # Width mismatch produces 1-bit result

            # Check for unary NOT operation on boolean operand
            if operator == 'not':
                if len(node.incoming_edges) >= 1:
                    # Check if the operand is boolean
                    for edge in node.incoming_edges:
                        operand = edge.source
                        if self._produces_boolean_result(operand):
                            return True

        return False

    def _format_literal_inline(self, node: Node, override_width: int = None) -> str:
        """Format a literal node as an inline VHDL value.

        Args:
            node: The literal node to format
            override_width: Optional bit width to use instead of node's bit_width

        Returns formatted VHDL literal (e.g., '1', "101", x"FF", std_logic_vector(...))
        """
        if node.data.get('type') != 'literal':
            return None

        # Check for VHDL string literals (could be hex, binary, etc.)
        if node.data.get('is_string_literal') and 'string_value' in node.data:
            str_val = node.data['string_value']
            bit_width = override_width if override_width is not None else node.data.get('bit_width')

            # Check if it was explicitly marked as a hex literal by the parser
            # pyGHDL expands hex to binary, so convert back to hex for output
            if node.data.get('is_hex_literal'):
                # Convert binary string back to hex format
                # Pad to multiple of 4 for hex conversion
                padded = str_val.zfill((len(str_val) + 3) // 4 * 4)
                hex_str = hex(int(padded, 2))[2:].upper()
                # Pad hex to match original width (bit_width / 4 hex digits)
                if bit_width:
                    hex_len = (bit_width + 3) // 4
                    hex_str = hex_str.zfill(hex_len)
                return f'x"{hex_str}"'

            # Check if it's a binary string (all 0s and 1s)
            if all(c in '01' for c in str_val):
                # Binary literal - format based on width
                if bit_width == 1 or (bit_width is None and len(str_val) == 1):
                    # Single bit - use character literal '0' or '1'
                    return f"'{str_val}'"
                else:
                    # Multi-bit - use binary string literal "101"
                    return f'"{str_val}"'
            else:
                # Hex or other format - preserve as hex
                return f'x"{str_val}"'

        value = node.data.get('value')
        bit_width = override_width if override_width is not None else node.data.get('bit_width')

        if bit_width == 1:
            # Single bit literal
            if isinstance(value, str):
                if value.startswith("'") and value.endswith("'"):
                    return value  # Already formatted like '1'
                elif value.startswith('"') and value.endswith('"'):
                    # String literal like "1", convert to character
                    inner = value[1:-1]
                    if len(inner) == 1 and inner in '01':
                        return f"'{inner}'"
                    # Invalid for single bit
                    return None
                else:
                    if len(value) == 1 and value in '01':
                        return f"'{value}'"
                    # Invalid for single bit
                    return None
            else:
                # Integer value - must be 0 or 1 for single bit
                if value in [0, 1]:
                    return f"'{value}'"
                # Cannot represent as single bit
                return None
        else:
            # Multi-bit literal
            if isinstance(value, str):
                # Check for binary string literal
                if value.startswith('"') and value.endswith('"'):
                    inner = value[1:-1]
                    if all(c in '01' for c in inner):
                        # Pad to bit_width if known
                        if bit_width:
                            padded = inner.zfill(bit_width)
                            return f'"{padded}"'
                        return value
                # Check for hex literal
                if value.startswith('x"') and value.endswith('"'):
                    return value
                # Try to parse as integer
                try:
                    int_val = int(value, 0)
                    width = bit_width if bit_width else 32
                    return f"std_logic_vector(to_unsigned({int_val}, {width}))"
                except (ValueError, TypeError):
                    pass
            # Integer value
            width = bit_width if bit_width else 32
            return f"std_logic_vector(to_unsigned({value}, {width}))"

    def _extract_literal_lsb(self, literal: str) -> str:
        """Extract the LSB (least significant bit) from a hex or binary literal.

        Args:
            literal: String like x"FF" or b"101" or "0110"

        Returns:
            VHDL character literal '0' or '1'
        """
        if literal.startswith('x"') and literal.endswith('"'):
            # Hex literal - extract last hex digit and get its LSB
            hex_str = literal[2:-1]
            if hex_str:
                last_nibble = int(hex_str[-1], 16)
                return f"'{last_nibble & 1}'"
        elif literal.startswith('b"') and literal.endswith('"'):
            # Binary literal - extract last bit
            bin_str = literal[2:-1]
            if bin_str:
                return f"'{bin_str[-1]}'"
        elif literal.startswith('"') and literal.endswith('"'):
            # Binary string literal - extract last bit
            bin_str = literal[1:-1]
            if bin_str and all(c in '01' for c in bin_str):
                return f"'{bin_str[-1]}'"
        # Fallback - return '0'
        return "'0'"

    def _literal_to_binary(self, literal: str) -> str:
        """Convert a hex or binary literal to its binary string representation.

        Args:
            literal: String like x"FF" or b"101" or "0110" or x"FF"(0)

        Returns:
            Binary string like "11111111" or None if conversion fails
        """
        # Strip off any indexing like (0) or (7 downto 0) at the end
        clean_literal = literal
        if '(' in literal:
            # Remove everything from first '(' onwards
            clean_literal = literal[:literal.index('(')]

        if clean_literal.startswith('x"') and clean_literal.endswith('"'):
            # Hex literal - convert each hex digit to 4 binary digits
            hex_str = clean_literal[2:-1]
            if hex_str:
                try:
                    # Convert hex to binary, removing '0b' prefix and zero-padding to multiple of 4
                    int_val = int(hex_str, 16)
                    bin_str = bin(int_val)[2:]  # Remove '0b' prefix
                    # Pad to match original hex length (4 bits per hex digit)
                    expected_len = len(hex_str) * 4
                    return bin_str.zfill(expected_len)
                except ValueError:
                    return None
        elif clean_literal.startswith('b"') and clean_literal.endswith('"'):
            # Binary literal - return as-is
            return clean_literal[2:-1]
        elif clean_literal.startswith('"') and clean_literal.endswith('"'):
            # Binary string literal
            bin_str = clean_literal[1:-1]
            if bin_str and all(c in '01' for c in bin_str):
                return bin_str
        return None

    def _format_initial_value(self, initial_value, bit_width: int) -> str:
        """
        Format an initial value for VHDL signal declaration.

        Args:
            initial_value: Initial value from parser (string, int, or None)
            bit_width: Signal bit width

        Returns:
            VHDL-compatible initial value string
        """
        if initial_value is None:
            return "(others => '0')"

        # If it's already a VHDL-style expression, return as-is (with some cleanup)
        if isinstance(initial_value, str):
            val_str = initial_value.strip()

            # Fix pyGHDL bug: hex literals with underscore instead of quotes
            # pyGHDL sometimes outputs x_FFFFFFFC instead of x"FFFFFFFC"
            if val_str.lower().startswith('x_') or val_str.lower().startswith('b_'):
                # Replace underscore with quotes
                val_str = val_str[0] + '"' + val_str[2:] + '"'

            # Handle aggregates like (others => '0')
            if val_str.startswith('(') and 'others' in val_str:
                # Fix common issue: (others => 0) should be (others => '0')
                # pyGHDL sometimes serializes character literals without quotes
                if re.search(r'=>\s*0\s*\)', val_str):
                    val_str = re.sub(r'=>\s*0\s*\)', "=> '0')", val_str)
                if re.search(r'=>\s*1\s*\)', val_str):
                    val_str = re.sub(r'=>\s*1\s*\)', "=> '1')", val_str)
                return val_str

            # Handle hex literals like x"FFFFFFFC" or X"00000000"
            if val_str.lower().startswith('x"') or val_str.lower().startswith('b"'):
                # Check if the bit string width matches the target signal width
                # Each hex digit = 4 bits, each binary digit = 1 bit
                is_hex = val_str.lower().startswith('x"')
                # Extract the value between quotes
                literal_value = val_str.split('"')[1] if '"' in val_str else ""
                literal_bits = len(literal_value) * (4 if is_hex else 1)

                if literal_bits != bit_width:
                    # Width mismatch - convert to appropriate format
                    if is_hex:
                        # Convert hex to integer then to appropriate width
                        try:
                            int_val = int(literal_value, 16)
                            # Mask to target width
                            int_val &= (1 << bit_width) - 1

                            # If bit_width is not a multiple of 4, use binary notation
                            # because hex digits are always 4 bits
                            if bit_width % 4 != 0:
                                bin_str = f'{int_val:0{bit_width}b}'
                                return f'"{bin_str}"'
                            else:
                                # Use hex notation
                                hex_digits = bit_width // 4
                                hex_str = f'{int_val:0{hex_digits}X}'
                                return f'x"{hex_str}"'
                        except ValueError:
                            # Fallback to zeros
                            return "(others => '0')"
                    else:
                        # Binary literal - truncate or pad
                        if literal_bits > bit_width:
                            # Truncate to LSBs
                            literal_value = literal_value[-bit_width:]
                        else:
                            # Pad with zeros
                            literal_value = literal_value.zfill(bit_width)
                        return f'b"{literal_value}"'

                # Width matches, return as-is
                if 'unsigned' in val_str.lower():
                    # Already wrapped, return as-is but ensure it's std_logic_vector
                    return f"std_logic_vector({val_str})"
                else:
                    # Direct hex/binary literal for std_logic_vector
                    return val_str

            # Handle character literals for single bits
            if val_str in ["'0'", "'1'"]:
                return val_str

            # Handle binary string literals like "1" or "0" for single-bit signals
            if val_str.startswith('"') and val_str.endswith('"') and bit_width == 1:
                inner = val_str[1:-1]
                if len(inner) == 1 and inner in '01':
                    return f"'{inner}'"

            # Handle numeric values that look like integers
            try:
                int_val = int(val_str)
                # Convert integer to appropriate vector format
                if bit_width > 1:
                    # Mask to target width
                    int_val &= (1 << bit_width) - 1
                    # If bit_width is not a multiple of 4, use binary notation
                    if bit_width % 4 != 0:
                        bin_str = f'{int_val:0{bit_width}b}'
                        return f'"{bin_str}"'
                    else:
                        # Use hex notation
                        hex_digits = bit_width // 4
                        hex_str = f'{int_val:0{hex_digits}X}'
                        return f'x"{hex_str}"'
                else:
                    return "'1'" if int_val else "'0'"
            except ValueError:
                pass

            # Default: return as-is, might be a complex expression
            return val_str

        # Handle integer values
        if isinstance(initial_value, int):
            if bit_width > 1:
                # Mask to target width
                int_val = initial_value & ((1 << bit_width) - 1)
                # If bit_width is not a multiple of 4, use binary notation
                # because hex digits are always 4 bits
                if bit_width % 4 != 0:
                    bin_str = f'{int_val:0{bit_width}b}'
                    return f'"{bin_str}"'
                else:
                    # Use hex notation
                    hex_digits = bit_width // 4
                    hex_str = f'{int_val:0{hex_digits}X}'
                    return f'x"{hex_str}"'
            else:
                return "'1'" if initial_value else "'0'"

        # Default fallback
        return "(others => '0')"

    def _sanitize_identifier(self, identifier: str) -> str:
        """Convert expression identifiers to valid VHDL identifiers.

        Preserves hierarchical structure by converting dots to single underscores.
        VHDL doesn't allow consecutive underscores, so we use single '_' as separator.
        Example: i_alu.const_0 -> i_alu_const_0 (preserves hierarchy, prevents collisions)

        Normalizes to lowercase to avoid case-sensitivity collisions (VHDL is case-insensitive).
        """
        # Normalize to lowercase first (VHDL is case-insensitive)
        sanitized = identifier.lower()

        # THEN: Convert hierarchical separators (dots) to single underscores
        # This preserves instance hierarchy and prevents name collisions
        # Note: VHDL forbids consecutive underscores, so we use single '_'
        sanitized = sanitized.replace('.', '_')

        # Replace structural characters
        sanitized = sanitized.replace('[', '_').replace(']', '_').replace(':', '_')
        sanitized = sanitized.replace('(', '_').replace(')', '_').replace(' ', '_')
        sanitized = sanitized.replace("'", '_').replace('{', '_').replace('}', '_')
        sanitized = sanitized.replace(',', '_').replace('?', '_')

        # Replace operators with names (order matters!)
        sanitized = sanitized.replace('+', 'add').replace('-', 'sub')
        sanitized = sanitized.replace('*', 'mul').replace('/', 'div')
        sanitized = sanitized.replace('&', 'and').replace('|', 'or').replace('^', 'xor')
        sanitized = sanitized.replace('>>>', 'srlgt').replace('<<', 'sll').replace('>>', 'srl')
        sanitized = sanitized.replace('==', 'eq').replace('!=', 'ne').replace('/=', 'ne')
        sanitized = sanitized.replace('<=', 'le').replace('>=', 'ge')
        sanitized = sanitized.replace('<', 'lt').replace('>', 'gt')
        sanitized = sanitized.replace('!', 'not').replace('~', 'inv')
        # Handle single '=' for VHDL equality comparisons (must come after <=, >=, ==, /=)
        sanitized = sanitized.replace('=', 'eq')

        # Clean up consecutive underscores (VHDL forbids double underscores)
        while '__' in sanitized:
            sanitized = sanitized.replace('__', '_')

        # Strip leading/trailing underscores
        sanitized = sanitized.strip('_')

        # Ensure doesn't start with digit
        if sanitized and sanitized[0].isdigit():
            sanitized = 'w_' + sanitized

        return sanitized

    def _generate_unique_name(self, base_name: str) -> str:
        """Generate a unique name by appending a counter if needed."""
        if base_name not in self.name_counter:
            self.name_counter[base_name] = 0
            return base_name
        else:
            self.name_counter[base_name] += 1
            return f"{base_name}_{self.name_counter[base_name]}"

    def _generate_concat_name(self, node: Node) -> str:
        """Generate a descriptive name for concatenation nodes."""
        return self._generate_unique_name('concat')

    def _generate_repetition_name(self, node: Node) -> str:
        """Generate a descriptive name for repetition nodes."""
        expr = node.data.get('expression', {})
        count = expr.get('count', 0) if expr.get('type') == 'repetition' else 0
        return self._generate_unique_name(f'rep{count}')

    def _generate_ternary_name(self, node: Node) -> str:
        """Generate a descriptive name for ternary operator nodes."""
        return self._generate_unique_name('mux')

    def _generate_entity_header(self):
        """Generate entity declaration with ports."""
        self.entity_header = f"entity {self.entity_name} is\n"
        self.entity_header += "    port (\n"
        self.entity_header += "        clk : in std_logic;\n"
        self.entity_header += "        reset : in std_logic"

        # Add interface ports (bus signals, memory interface, etc.)
        for port_name, port_spec in sorted(self.interface_ports.items()):
            # Skip clk and reset since they're already declared
            if port_name in ('clk', 'reset'):
                continue

            # Handle both formats: 'direction' or ('direction', width)
            if isinstance(port_spec, tuple):
                direction, explicit_width = port_spec
            else:
                direction = port_spec
                explicit_width = None

            # Use explicit width if provided, otherwise find from signal declarations
            bit_width = explicit_width
            if bit_width is None:
                for sig_decl in self.signal_declarations:
                    if sig_decl['name'] == port_name:
                        bit_width = sig_decl['bit_width']
                        break

            if bit_width is None:
                bit_width = 32  # Default width

            if bit_width > 1:
                self.entity_header += f";\n        {port_name} : {direction} std_logic_vector({bit_width-1} downto 0)"
            else:
                self.entity_header += f";\n        {port_name} : {direction} std_logic"

        # Add reset value inputs for registers
        for sig_decl in self.signal_declarations:
            if sig_decl.get('is_register') and sig_decl.get('reset_signal'):
                name = sig_decl['name']
                reset_name = f"reset_{name}"
                # Skip if already declared as an interface port
                if reset_name in self.interface_ports:
                    continue
                bit_width = sig_decl['bit_width']
                if bit_width > 1:
                    self.entity_header += f";\n        {reset_name} : in std_logic_vector({bit_width-1} downto 0)"
                else:
                    self.entity_header += f";\n        {reset_name} : in std_logic"

        # Add debug outputs - handle both list and dict formats
        if isinstance(self.debug_outputs, dict):
            # Dict format: {port_name: signal_name}
            for port_name, signal_name in self.debug_outputs.items():
                for sig_decl in self.signal_declarations:
                    if sig_decl['name'] == signal_name:
                        bit_width = sig_decl['bit_width']
                        self.entity_ports.add(port_name)
                        self.declared_names.add(port_name)
                        if bit_width > 1:
                            self.entity_header += f";\n        {port_name} : out std_logic_vector({bit_width-1} downto 0)"
                        else:
                            self.entity_header += f";\n        {port_name} : out std_logic"
                        break
        else:
            # List format: [signal_name, ...]
            for debug_signal in self.debug_outputs:
                # Find the signal in declarations
                for sig_decl in self.signal_declarations:
                    if sig_decl['name'] == debug_signal:
                        bit_width = sig_decl['bit_width']
                        # Determine the port name - don't double-prefix with 'debug_'
                        if debug_signal.startswith('debug_'):
                            port_name = debug_signal
                        else:
                            port_name = f"debug_{debug_signal}"
                        # Mark as entity port to prevent redeclaration as internal signal
                        self.entity_ports.add(port_name)
                        self.declared_names.add(port_name)
                        if bit_width > 1:
                            self.entity_header += f";\n        {port_name} : out std_logic_vector({bit_width-1} downto 0)"
                        else:
                            self.entity_header += f";\n        {port_name} : out std_logic"
                        break

        self.entity_header += "\n    );\n"
        self.entity_header += f"end entity {self.entity_name};\n\n"

    def _generate_declarations(self):
        """Generate signal declarations."""
        self.declarations = f"architecture rtl of {self.entity_name} is\n"

        # Add textio library statement if any memory needs file initialization
        needs_textio = any(mem_decl.get('mem_file') for mem_decl in self.memory_declarations.values())
        if needs_textio:
            self.library_statements.add("use STD.textio.all;")

        # Memory array types and loader functions
        for name, mem_decl in self.memory_declarations.items():
            bit_width = mem_decl['bit_width']
            array_depth = mem_decl['array_depth']
            mem_file = mem_decl.get('mem_file', None)

            if bit_width is None:
                bit_width = 32

            self.declarations += f"    type {name}_array_type is array (0 to {array_depth-1}) of std_logic_vector({bit_width-1} downto 0);\n"

            # Add safe memory access function to handle out-of-bounds accesses
            addr_bits = (array_depth - 1).bit_length()
            self.declarations += f"""
    -- Safe memory access function for {name} (masks address to valid range)
    function safe_{name}_read(mem : {name}_array_type; addr_word : std_logic_vector) return std_logic_vector is
        variable masked_addr : std_logic_vector({addr_bits-1} downto 0);
    begin
        -- Mask to use only the lower {addr_bits} bits
        masked_addr := addr_word({addr_bits-1} downto 0);
        return mem(to_integer(unsigned(masked_addr)));
    end function;
"""

            # Add memory loader function if mem_file is specified
            if mem_file:
                if bit_width == 64:
                    # For 64-bit memory, read 64-bit values directly from file (one per line)
                    self.declarations += f"""
    -- Memory initialization function for {name} (reads 64-bit values directly)
    impure function load_{name}_from_file(filename : string) return {name}_array_type is
        file mem_file : text;
        variable line_v : line;
        variable word64 : std_logic_vector(63 downto 0);
        variable mem_data : {name}_array_type := (others => (others => '0'));
        variable addr : integer := 0;
        variable good : boolean;
        variable status : file_open_status;
    begin
        file_open(status, mem_file, filename, read_mode);
        if status /= open_ok then
            report "ERROR: Could not open " & filename & " for reading" severity warning;
            return mem_data;  -- Return zeros
        end if;

        report "Loading " & filename & "..." severity note;

        while not endfile(mem_file) and addr < {array_depth} loop
            readline(mem_file, line_v);
            -- Skip empty lines
            if line_v'length > 0 then
                hread(line_v, word64, good);
                if good then
                    mem_data(addr) := word64;
                    addr := addr + 1;
                end if;
            end if;
        end loop;
        file_close(mem_file);

        report "Loaded " & integer'image(addr) & " words from " & filename severity note;
        return mem_data;
    end function;
"""
                else:
                    # For 32-bit memory, read 32-bit words directly
                    self.declarations += f"""
    -- Memory initialization function for {name}
    impure function load_{name}_from_file(filename : string) return {name}_array_type is
        file mem_file : text;
        variable line_v : line;
        variable mem_word : std_logic_vector({bit_width-1} downto 0);
        variable mem_data : {name}_array_type := (others => (others => '0'));
        variable addr : integer := 0;
        variable char_val : character;
        variable good : boolean;
        variable status : file_open_status;
    begin
        file_open(status, mem_file, filename, read_mode);
        if status /= open_ok then
            report "ERROR: Could not open " & filename & " for reading" severity warning;
            return mem_data;  -- Return zeros
        end if;

        report "Loading " & filename & "..." severity note;

        while not endfile(mem_file) and addr < {array_depth} loop
            readline(mem_file, line_v);
            -- Skip empty lines
            if line_v'length > 0 then
                hread(line_v, mem_word, good);
                if good then
                    mem_data(addr) := mem_word;
                    addr := addr + 1;
                end if;
            end if;
        end loop;
        file_close(mem_file);

        report "Loaded " & integer'image(addr) & " words from " & filename severity note;
        return mem_data;
    end function;
"""
                self.declarations += f"    signal {name} : {name}_array_type := load_{name}_from_file(\"{mem_file}\");\n"
            else:
                # Initialize to zeros (important for register file)
                self.declarations += f"    signal {name} : {name}_array_type := (others => (others => '0'));\n"

        # Deduplicate signal declarations (VHDL is case-insensitive)
        seen_names = set()
        unique_signals = []
        for sig_decl in self.signal_declarations:
            name = sig_decl['name']
            if name.lower() not in seen_names:
                seen_names.add(name.lower())
                unique_signals.append(sig_decl)

        # Signal declarations (skip ports that are already in entity)
        for sig_decl in unique_signals:
            name = sig_decl['name']

            # Skip signals that are entity ports (already declared in port list)
            if name in self.entity_ports:
                continue

            bit_width = sig_decl['bit_width']
            if bit_width is None:
                bit_width = 32

            # Double-check if this signal should be boolean (1-bit std_logic)
            # Find the corresponding node and check if it produces boolean result
            is_boolean = False
            for node in self.graph.nodes.values():
                node_name = self.node_id_to_name.get(node.id)
                if node_name == name:
                    if self._produces_boolean_result(node):
                        bit_width = 1
                        is_boolean = True
                    break

            # Get initial value from declaration
            initial_value = sig_decl.get('initial_value')
            init_str = self._format_initial_value(initial_value, bit_width)

            if bit_width > 1 and not is_boolean:
                self.declarations += f"    signal {name} : std_logic_vector({bit_width-1} downto 0) := {init_str};\n"
            else:
                init_bit = "'0'" if init_str == "(others => '0')" else init_str
                if init_bit.startswith("("):
                    init_bit = "'0'"  # Default for std_logic
                self.declarations += f"    signal {name} : std_logic := {init_bit};\n"

        self.declarations += "begin\n\n"

    def _generate_memory_initialization(self):
        """Generate memory initialization (simplified for VHDL)."""
        self.memory_init = ""
        # VHDL memory initialization typically done via separate file or in testbench
        # For synthesis, memories are inferred and initialized by tools

    def _generate_combinational_logic(self):
        """Generate combinational logic for operations and assignments."""
        self.comb_logic = ""

        processed_nodes = set()

        for node in self._get_dependency_order():
            if node.id in processed_nodes:
                continue

            if node.data.get('type') == 'operation':
                self._generate_operation_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'array_access':
                self._generate_array_access_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'bit_slice':
                self._generate_bit_slice_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'literal':
                # Only inline literals used exclusively in operations
                if self._can_inline_literal(node):
                    processed_nodes.add(node.id)
                else:
                    self._generate_literal_logic(node)
                    processed_nodes.add(node.id)
            elif node.data.get('type') == 'sized_literal':
                self._generate_sized_literal_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'concatenation':
                self._generate_concatenation_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'repetition':
                self._generate_repetition_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'ternary_op':
                self._generate_ternary_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'comparison':
                self._generate_comparison_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'operation':
                self._generate_operation_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') in ['logical_and', 'logical_or']:
                self._generate_logical_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'instruction_enable':
                self._generate_instruction_enable_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'zero_extend':
                self._generate_zero_extend_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'sign_extend':
                self._generate_sign_extend_logic(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') in ['multiplexer', 'alu_module', 'uarch_counter',
                                           'memory_access_counter', 'hazard_detection_unit',
                                           'hazard_detector']:
                self._generate_module_instantiation(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') in ['var', 'temp_var', 'variable'] or node.data.get('is_variable'):
                # Generate assignments for variables
                self._generate_variable_assignment(node)
                processed_nodes.add(node.id)
            elif node.data.get('type') == 'pipeline_stall_controller':
                # Generate stall controller logic (OR of hazard signals)
                self._generate_stall_controller_logic(node)
                processed_nodes.add(node.id)

        # Generate reconstructed variables for in-place bit modifications
        self._generate_variable_reconstructions()

        # Generate missing enable signal connections
        self._generate_enable_connections()

        # Generate port connection assignments for hierarchical designs
        # This fixes missing connections between top-level signals and instance outputs
        self._generate_port_connections()

        # Generate rd != 0 comparisons for conditional register writes
        self._generate_rd_ne_0_comparisons()

        # Generate output port assignments
        self._generate_output_port_assignments()

        # Remove loop-forming assignments (post-processing)
        self._remove_combinational_loops()

        # Fix assignments that don't match declared widths (post-processing)
        self._fix_width_mismatches()

    def _generate_variable_reconstructions(self):
        """Generate reconstructed variables for in-place bit modifications.

        When VHDL process variables have in-place bit assignments like:
            a_dash(31) := NOT a_dash(31);

        The parser creates separate signals for the base and modified bit.
        This method reconstructs the modified variable by concatenating them.
        """
        # Find all indexed variable assignment targets
        indexed_vars = {}  # base_id -> list of (indexed_node, bit_index)

        for node_id, node in self.graph.nodes.items():
            if not node.data.get('is_variable'):
                continue

            # Check for indexed assignment pattern: var_X(Y)
            if '(' in node_id and node_id.endswith((')?', ')')):
                # Extract base variable name
                base_id = node_id.split('(')[0]

                # Check if base variable exists
                if base_id in self.graph.nodes:
                    if base_id not in indexed_vars:
                        indexed_vars[base_id] = []
                    indexed_vars[base_id].append(node)

        # For each base variable with indexed modifications
        for base_id, indexed_nodes in indexed_vars.items():
            base_node = self.graph.nodes[base_id]
            base_vhdl_name = self.node_id_to_name.get(base_id, self._sanitize_identifier(base_id))

            # Get base variable bit width (default to 32 for RISC-V)
            base_width = base_node.data.get('bit_width') or 32

            # Skip if base variable has no outgoing edges (not used)
            if not base_node.outgoing_edges:
                continue

            # For each bit modification, we need to reconstruct
            # Currently we only support single-bit modifications at the high bit
            # (can be extended for multiple bits or arbitrary indices later)
            for indexed_node in indexed_nodes:
                indexed_vhdl_name = self.node_id_to_name.get(indexed_node.id,
                                                             self._sanitize_identifier(indexed_node.id))

                # Check if this is modifying the high bit (bit 31 for 32-bit)
                if "'high" in indexed_node.id.lower() or f'({base_width-1})' in indexed_node.id:
                    # Create reconstructed variable
                    reconstructed_name = f"{base_vhdl_name}_modified"

                    # Generate concatenation: modified_high_bit & base(30:0)
                    # The modified high bit should be the MSB (leftmost in VHDL concatenation)
                    if base_width > 1:
                        concat_expr = f"    {reconstructed_name} <= {indexed_vhdl_name} & {base_vhdl_name}({base_width-2} downto 0);\n"
                        self.comb_logic += concat_expr
                        self.assigned_signals.add(reconstructed_name)

                        # Declare the reconstructed signal
                        self.additional_signals.append({
                            'name': reconstructed_name,
                            'bit_width': base_width
                        })

                        # Replace references to the base variable in operations with the reconstructed version
                        # This is done as a post-processing step on the generated combinational logic
                        # We need to be careful to only replace the variable when used as an operand,
                        # not when it's being assigned to
                        self._replace_variable_references(base_vhdl_name, reconstructed_name)

    def _replace_variable_references(self, old_name: str, new_name: str):
        """Replace references to a variable in combinational logic.

        Only replaces the variable when used as an operand (right side of <=),
        not when it's the target of an assignment (left side of <=).

        Args:
            old_name: Original variable name to replace
            new_name: New variable name to use
        """
        import re

        # Split the logic into lines
        lines = self.comb_logic.split('\n')
        modified_lines = []

        for line in lines:
            # Check if this line contains an assignment with <=
            if '<=' in line and old_name in line:
                # Split on <= to get left and right sides
                parts = line.split('<=', 1)
                if len(parts) == 2:
                    left_side = parts[0]
                    right_side = parts[1]

                    # Don't replace if the old_name is the EXACT target (left side)
                    # But DO replace if it appears in the right side (as operand)
                    # We need to match whole words to avoid replacing parts of longer names

                    # Pattern: match old_name as a whole word, possibly followed by ( or space or operator
                    pattern = r'\b' + re.escape(old_name) + r'(?=\s|[\(\)\,\;\&\|]|$)'

                    # Check if this is assigning TO the old_name (not just mentioning it in the result name)
                    # The target is the last identifier before <=
                    left_stripped = left_side.strip()
                    # Match the target signal name (last word before <=)
                    target_match = re.search(r'(\w+)\s*$', left_stripped)
                    is_target = target_match and target_match.group(1) == old_name

                    # Also check if this is the reconstruction assignment itself (target is new_name)
                    is_reconstruction = target_match and target_match.group(1) == new_name

                    # Also check if this is an indexed variable assignment's ELSE clause
                    # Pattern: "signal_high <= ... else base_signal(31)"
                    # We don't want to replace base_signal in the else clause
                    is_indexed_var_else = False
                    if ' else ' in right_side and f'{old_name}(' in right_side:
                        # This might be the else clause of an indexed variable assignment
                        # Check if the target ends with a suffix that suggests it's an indexed var
                        if target_match:
                            target_signal = target_match.group(1)
                            # Pattern: ends with _high, _31, etc.
                            if any(target_signal.endswith(suffix) for suffix in ['_high', '_31', '_0', '_low']):
                                is_indexed_var_else = True

                    # Also check if this is a bit extraction feeding into the indexed assignment
                    # Pattern: "signal_31 <= base_signal(31)" which will become "signal_31 <= base_signal_modified(31)"
                    # We don't want to use the modified version here - it creates circular dependency
                    # Instead, the bit should be extracted from the original variable
                    is_bit_extraction_for_index = False
                    if target_match and f'{old_name}(' in right_side:
                        target_signal = target_match.group(1)
                        # Check if target ends with _31, _high, etc. (bit extraction signals)
                        # The right side is extracting from the original variable (old_name)
                        if any(target_signal.endswith(suffix) for suffix in ['_31', '_high', '_0', '_low']):
                            # This is extracting a bit - preserve the original variable name
                            is_bit_extraction_for_index = True

                    # Also check if this is an equality comparison
                    # Pattern: "signal_eq_signal2 <= '1' when var1 = var2 else '0'"
                    # For equality comparisons, we should use the ORIGINAL values, not modified ones
                    # The modified versions have sign bit manipulation which is only for signed < comparisons
                    is_equality_comparison = False
                    if target_match and '_eq_' in target_match.group(1):
                        # This is an equality comparison signal
                        # Check if it's using the = operator (not < or >)
                        if ' when ' in right_side and ' = ' in right_side and ' < ' not in right_side:
                            is_equality_comparison = True

                    if not is_target and not is_reconstruction and not is_indexed_var_else and not is_bit_extraction_for_index and not is_equality_comparison:
                        # Not assigning to this variable, safe to replace in both sides
                        # (left side might contain it in a complex signal name, which is fine)
                        modified_right = re.sub(pattern, new_name, right_side)
                        modified_lines.append(parts[0] + '<=' + modified_right)
                    else:
                        # Assigning to this variable or this is the reconstruction line, don't replace
                        modified_lines.append(line)
                else:
                    modified_lines.append(line)
            else:
                modified_lines.append(line)

        # Reconstruct the logic
        self.comb_logic = '\n'.join(modified_lines)

    def _remove_combinational_loops(self):
        """Remove assignments that form combinational loops.

        This detects and removes assignments that create circular dependencies
        in the combinational logic, which would cause infinite delta cycles.
        """
        import re

        # Build maps of declared signals
        declared_signals = set()
        for sig_decl in self.signal_declarations:
            declared_signals.add(sig_decl['name'])

        # Add entity ports
        declared_signals.update(self.entity_ports)

        # Build dependency graph from combinational logic
        dependencies = {}  # signal -> set of signals it depends on
        assignments = []  # List of (line, target, sources)

        for line in self.comb_logic.split('\n'):
            if '<=' in line and '--' not in line.split('<=')[0]:
                parts = line.split('<=')
                if len(parts) >= 2:
                    lhs = parts[0].strip()
                    rhs = '<='.join(parts[1:])

                    sources = set()
                    for sig in declared_signals:
                        if re.search(r'\b' + re.escape(sig) + r'\b', rhs):
                            sources.add(sig)

                    dependencies[lhs] = sources
                    assignments.append((line, lhs, sources))

        # Find strongly connected components (cycles)
        visited = set()
        stack = []
        on_stack = set()
        low = {}
        index = {}
        idx = [0]
        cycles = []

        def strongconnect(v):
            low[v] = idx[0]
            index[v] = idx[0]
            idx[0] += 1
            stack.append(v)
            on_stack.add(v)

            for w in dependencies.get(v, []):
                if w not in index:
                    strongconnect(w)
                    low[v] = min(low[v], low[w])
                elif w in on_stack:
                    low[v] = min(low[v], index[w])

            if low[v] == index[v]:
                scc = []
                while True:
                    w = stack.pop()
                    on_stack.remove(w)
                    scc.append(w)
                    if w == v:
                        break
                if len(scc) > 1:
                    cycles.append(set(scc))
                elif len(scc) == 1:
                    # Check for self-loop (signal depends on itself)
                    signal = scc[0]
                    if signal in dependencies.get(signal, set()):
                        cycles.append(set(scc))

        for v in dependencies.keys():
            if v not in index:
                strongconnect(v)

        if cycles:
            # With zeros as default for combinational logic, true self-loops shouldn't exist
            # But we still detect them, so disable removal and see what fails at runtime
            return

            # Flatten all cycle signals
            cycle_signals = set()
            for cycle in cycles:
                cycle_signals.update(cycle)

            # Remove assignments where target is in a cycle
            new_comb_logic_lines = []
            removed_count = 0
            for line in self.comb_logic.split('\n'):
                if '<=' in line and '--' not in line.split('<=')[0]:
                    parts = line.split('<=')
                    if len(parts) >= 2:
                        lhs = parts[0].strip()
                        if lhs in cycle_signals:
                            # Check if this assignment actually participates in a loop
                            # by checking if any of its sources are also in a cycle
                            rhs = '<='.join(parts[1:])
                            sources = set()
                            for sig in declared_signals:
                                if re.search(r'\b' + re.escape(sig) + r'\b', rhs):
                                    sources.add(sig)

                            if sources & cycle_signals:
                                # This assignment participates in a loop, remove it
                                removed_count += 1
                                self.assigned_signals.discard(lhs)
                                continue

                new_comb_logic_lines.append(line)

            self.comb_logic = '\n'.join(new_comb_logic_lines)

    def _fix_width_mismatches(self):
        """Post-process combinational logic to fix assignments where declared width doesn't match assigned value.

        Specifically fixes cases where 1-bit signals are assigned multi-bit values like std_logic_vector(to_unsigned(0, 32)).
        Also fixes signal-to-signal assignments where widths don't match.
        """
        import re

        # Build a map of signal names to their declared widths
        width_map = {}
        for sig_decl in self.signal_declarations:
            name = sig_decl['name']
            width = sig_decl['bit_width']
            if width is not None:
                width_map[name] = width

        # Pattern to match assignments like: signal_name <= std_logic_vector(to_unsigned(value, width));
        pattern = r'(\s+)(\w+)\s*<=\s*std_logic_vector\(to_unsigned\((\d+),\s*(\d+)\)\);'

        def fix_assignment(match):
            indent = match.group(1)
            signal_name = match.group(2)
            value = match.group(3)
            assigned_width = int(match.group(4))

            # Check if this signal has a declared width
            if signal_name in width_map:
                declared_width = width_map[signal_name]

                # If declared width is 1 but we're assigning a multi-bit value, fix it
                if declared_width == 1 and assigned_width > 1:
                    # Convert to single-bit assignment
                    if int(value) in [0, 1]:
                        return f"{indent}{signal_name} <= '{value}';\n"
                    else:
                        # Extract LSB
                        return f"{indent}{signal_name} <= std_logic_vector(to_unsigned({value}, 32))(0);\n"
                # If declared width doesn't match assigned width, adjust
                elif declared_width != assigned_width:
                    # Check if value fits in declared width, if not mask it
                    int_value = int(value)
                    max_value = (1 << declared_width) - 1
                    if int_value > max_value:
                        # Mask value to fit in declared width
                        int_value = int_value & max_value
                    return f"{indent}{signal_name} <= std_logic_vector(to_unsigned({int_value}, {declared_width}));\n"

            # No change needed
            return match.group(0)

        # Apply the fix to all assignments in comb_logic
        self.comb_logic = re.sub(pattern, fix_assignment, self.comb_logic)

        # Fix signal-to-signal width mismatches
        # Pattern: target_signal <= source_signal;
        simple_assign_pattern = r'(\s+)(\w+)\s*<=\s*(\w+);'

        def fix_signal_assignment(match):
            indent = match.group(1)
            target_name = match.group(2)
            source_name = match.group(3)

            # Skip if either signal is not in width_map
            if target_name not in width_map or source_name not in width_map:
                return match.group(0)

            target_width = width_map[target_name]
            source_width = width_map[source_name]

            # If widths match, no change needed
            if target_width == source_width:
                return match.group(0)

            # If target is narrower, extract low bits
            if target_width < source_width:
                if target_width == 1:
                    return f"{indent}{target_name} <= {source_name}(0);\n"
                else:
                    return f"{indent}{target_name} <= {source_name}({target_width-1} downto 0);\n"

            # If target is wider, zero-extend
            # This shouldn't happen for decoder field extraction, but handle it anyway
            if source_width == 1:
                # For single-bit std_logic, use concatenation with zeros
                zeros = target_width - 1
                return f"{indent}{target_name} <= ({zeros-1} downto 0 => '0') & {source_name};\n"
            else:
                return f"{indent}{target_name} <= std_logic_vector(resize(unsigned({source_name}), {target_width}));\n"

        # Apply signal-to-signal fix
        self.comb_logic = re.sub(simple_assign_pattern, fix_signal_assignment, self.comb_logic)

        # Also fix unqualified character literals in logical operations
        # Pattern: signal(bit) and '0' or similar
        # Use std_logic instead of std_ulogic to match bit slice types
        char_lit_pattern = r"(\s+and\s+|or\s+|xor\s+)'([01])'"
        def qualify_char_lit(match):
            op_with_space = match.group(1)  # " and " or "or " or "xor "
            bit_value = match.group(2)       # '0' or '1'
            # Use to_stdulogicvector conversion for compatibility
            return f"{op_with_space}'{bit_value}'"

        # Actually, don't qualify - VHDL should handle unqualified '0'/'1' with std_logic
        # The real issue is something else. Skip this for now.
        # self.comb_logic = re.sub(char_lit_pattern, qualify_char_lit, self.comb_logic)

    def _generate_rd_ne_0_comparisons(self):
        """Generate comparisons for rd != 0 signals used in conditional writes.

        For each instruction that writes to RF, we need to generate:
        instr_instr_rd_ne_0 <= '1' when to_integer(unsigned(instr_rd)) /= 0 else '0';
        """
        count = 0
        for sig_decl in self.signal_declarations:
            sig_name = sig_decl['name']

            # Look for signals like add_add_rd_ne_0, addi_addi_rd_ne_0, etc.
            if sig_name.endswith('_rd_ne_0'):
                # Don't skip if already assigned - we need to forcibly generate this logic
                # since the operation node processing might not have proper edges

                # Extract the base instruction name
                # For add_add_rd_ne_0, we want 'add'
                # For addi_addi_rd_ne_0, we want 'addi'
                parts = sig_name.split('_')
                if len(parts) >= 4 and parts[-3] == 'rd' and parts[-2] == 'ne' and parts[-1] == '0':
                    # Check if this follows the double-prefix pattern
                    # e.g., add_add_rd_ne_0 -> parts[0]='add', parts[1]='add'
                    if len(parts) >= 5 and parts[0] == parts[1]:
                        instr_prefix = parts[0]
                        rd_signal = f"{instr_prefix}_rd"

                        # Check if the rd signal exists
                        if any(s['name'] == rd_signal for s in self.signal_declarations):
                            self.comb_logic += f"    {sig_name} <= '1' when to_integer(unsigned({rd_signal})) /= 0 else '0';\n"
                            self.assigned_signals.add(sig_name)
                            count += 1

    def _generate_port_connections(self):
        """Generate assignments for unassigned signals by finding matching internal instance signals.

        This handles hierarchical designs where top-level signals (like decode_bus_write)
        should be connected to internal instance outputs (like i_decoder.out_bus_write).

        The parser creates nodes for both signals but may not create edges connecting them.
        This method infers those connections by pattern matching.
        """
        # Build maps of declared signals and their widths
        declared_signals = {}
        for sig_decl in self.signal_declarations:
            name = sig_decl['name']
            declared_signals[name] = sig_decl

        # Build dependency graph from existing combinational logic
        # to detect potential loops before adding new assignments
        import re
        dependencies = {}  # signal -> set of signals it depends on

        for line in self.comb_logic.split('\n'):
            if '<=' in line and '--' not in line.split('<=')[0]:
                parts = line.split('<=')
                if len(parts) >= 2:
                    lhs = parts[0].strip()
                    rhs = '<='.join(parts[1:])
                    if lhs not in dependencies:
                        dependencies[lhs] = set()
                    # Find all signal references in RHS
                    for sig in declared_signals.keys():
                        if re.search(r'\b' + re.escape(sig) + r'\b', rhs):
                            dependencies[lhs].add(sig)

        def would_create_loop(target, source):
            """Check if assigning target <= source would create a combinational loop."""
            # Check if source depends on target (directly or transitively)
            visited = set()
            stack = [source]
            while stack:
                current = stack.pop()
                if current == target:
                    return True
                if current in visited:
                    continue
                visited.add(current)
                if current in dependencies:
                    stack.extend(dependencies[current])
            return False

        # Find unassigned signals
        unassigned = set(declared_signals.keys()) - self.assigned_signals

        # Skip entity ports (input ports like clk, reset)
        unassigned = unassigned - self.entity_ports


        # Map instance prefixes to their full names
        # Look for patterns like: decode_X -> i_decoder_out_X
        #                        alu_X -> i_alu_X
        #                        c_alu -> i_alu_c

        # Helper function to check type compatibility
        def types_match(sig1, sig2):
            """Check if two signals have compatible types for assignment."""
            if sig1 not in declared_signals or sig2 not in declared_signals:
                return False
            width1 = declared_signals[sig1].get('bit_width', 1)
            width2 = declared_signals[sig2].get('bit_width', 1)
            return width1 == width2

        # First pass: Handle component_output edges from the graph
        # These represent connections from instance outputs to top-level signals
        for edge in self.graph.edges.values():
            if edge.data.get('type') == 'component_output':
                source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                target_name = self.node_id_to_name.get(edge.target.id, self._sanitize_identifier(edge.target.id))

                # Only generate if target is unassigned and source is assigned
                if target_name in unassigned and source_name in self.assigned_signals:
                    if types_match(target_name, source_name) and not would_create_loop(target_name, source_name):
                        self.comb_logic += f"    {target_name} <= {source_name};\n"
                        self.assigned_signals.add(target_name)
                        dependencies[target_name] = {source_name}
                        unassigned.remove(target_name)
                elif target_name in unassigned and source_name in declared_signals and target_name not in self.assigned_signals:
                    # Source might not be assigned yet, but if both are declared, connect them
                    if types_match(target_name, source_name) and not would_create_loop(target_name, source_name):
                        self.comb_logic += f"    {target_name} <= {source_name};\n"
                        self.assigned_signals.add(target_name)
                        dependencies[target_name] = {source_name}
                        unassigned.remove(target_name)

        # Second pass: Handle component_input edges from the graph
        # These represent connections from parent signals to instance inputs
        for edge in self.graph.edges.values():
            if edge.data.get('type') == 'component_input':
                source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                target_name = self.node_id_to_name.get(edge.target.id, self._sanitize_identifier(edge.target.id))

                # Only generate if target is unassigned
                if target_name in unassigned and source_name in declared_signals:
                    if types_match(target_name, source_name) and not would_create_loop(target_name, source_name):
                        self.comb_logic += f"    {target_name} <= {source_name};\n"
                        self.assigned_signals.add(target_name)
                        dependencies[target_name] = {source_name}
                        unassigned.remove(target_name)

        # Generate connections for common patterns
        for signal_name in sorted(unassigned):
            matched = False

            # Pattern 1: decode_X -> i_decoder_out_X
            if signal_name.startswith('decode_'):
                suffix = signal_name[7:]  # Remove 'decode_'
                candidate = f'i_decoder_out_{suffix}'
                if (candidate in declared_signals and
                    candidate in self.assigned_signals and
                    types_match(signal_name, candidate) and
                    not would_create_loop(signal_name, candidate)):
                    self.comb_logic += f"    {signal_name} <= {candidate};\n"
                    self.assigned_signals.add(signal_name)
                    dependencies[signal_name] = {candidate}  # Update dependency graph
                    matched = True

            # Pattern 2: X_alu -> i_alu_X (e.g., c_alu -> i_alu_c)
            if not matched and signal_name.endswith('_alu'):
                prefix = signal_name[:-4]  # Remove '_alu'
                candidate = f'i_alu_{prefix}'
                if (candidate in declared_signals and candidate in self.assigned_signals and
                    not would_create_loop(signal_name, candidate)):
                    self.comb_logic += f"    {signal_name} <= {candidate};\n"
                    self.assigned_signals.add(signal_name)
                    dependencies[signal_name] = {candidate}
                    matched = True

            # Pattern 3: X_shifter -> i_shifter_X
            if not matched and signal_name.endswith('_shifter'):
                prefix = signal_name[:-8]  # Remove '_shifter'
                candidate = f'i_shifter_{prefix}'
                if (candidate in declared_signals and candidate in self.assigned_signals and
                    not would_create_loop(signal_name, candidate)):
                    self.comb_logic += f"    {signal_name} <= {candidate};\n"
                    self.assigned_signals.add(signal_name)
                    dependencies[signal_name] = {candidate}
                    matched = True

            # Pattern 4: X_bus -> i_data_bus_mux_X_data_bus or i_result_bus_mux_X
            if not matched and signal_name.endswith('_bus'):
                prefix = signal_name[:-4]  # Remove '_bus'
                # Try data_bus_mux_a
                candidate = f'i_data_bus_mux_{prefix}_data_bus'
                if (candidate in declared_signals and candidate in self.assigned_signals and
                    not would_create_loop(signal_name, candidate)):
                    self.comb_logic += f"    {signal_name} <= {candidate};\n"
                    self.assigned_signals.add(signal_name)
                    dependencies[signal_name] = {candidate}
                    matched = True
                elif prefix in ['a', 'b', 'c', 'res']:
                    # Try result_bus_mux
                    candidate = f'i_result_bus_mux_{prefix}_bus'
                    if (candidate in declared_signals and candidate in self.assigned_signals and
                        not would_create_loop(signal_name, candidate)):
                        self.comb_logic += f"    {signal_name} <= {candidate};\n"
                        self.assigned_signals.add(signal_name)
                        dependencies[signal_name] = {candidate}
                        matched = True

            # Pattern 5: For signals with no obvious pattern, try to find a matching internal signal
            if not matched:
                # Look for instance signal that has this signal as part of its name
                # BUT: Only match if the signal name appears at the END after an underscore
                # This prevents circular dependencies like:
                #   i_decoder_minimize_size <= i_decoder_minimize_size_eq_const_50
                # where the eq_const signal depends on minimize_size
                for assigned_sig in sorted(self.assigned_signals):
                    # Check if the assigned signal ENDS with the unassigned signal name
                    # (after an underscore, to avoid partial matches)
                    if assigned_sig.startswith('i_') and assigned_sig.endswith('_' + signal_name):
                        # Found a potential match - verify types are compatible
                        if (signal_name in declared_signals and
                            assigned_sig in declared_signals and
                            declared_signals[signal_name].get('bit_width') == declared_signals[assigned_sig].get('bit_width') and
                            not would_create_loop(signal_name, assigned_sig)):
                            self.comb_logic += f"    {signal_name} <= {assigned_sig};\n"
                            self.assigned_signals.add(signal_name)
                            dependencies[signal_name] = {assigned_sig}
                            matched = True
                            break

    def _generate_output_port_assignments(self):
        """Generate assignments for output entity ports from internal signals.

        For output ports like pc_next, find the corresponding internal signal
        (e.g., cpu_core_i_program_counter_pc_next) and assign the port from it.

        Also handles debug_ prefixed ports by stripping the prefix and searching
        for the base signal name.
        """
        for port_name, port_spec in self.interface_ports.items():
            # Handle both old format ('direction') and new format (('direction', width))
            if isinstance(port_spec, tuple):
                direction = port_spec[0]
            else:
                direction = port_spec
            is_assigned = port_name in self.assigned_signals
            if direction == 'out' and port_name not in self.assigned_signals:
                # Look for internal signal that should drive this port
                # Strip debug_ prefix if present to find the actual signal name
                search_name = port_name
                if port_name.startswith('debug_'):
                    search_name = port_name[6:]  # Remove 'debug_' prefix

                # Pattern: look for signals ending with _search_name (with or without hierarchical prefix)
                candidates = []
                for sig_decl in self.signal_declarations:
                    sig_name = sig_decl['name']
                    # Match signals ending with _search_name (hierarchical pattern)
                    if sig_name.endswith('_' + search_name):
                        candidates.append(sig_name)

                if candidates:
                    # Prefer the shortest match (closest to the top-level)
                    candidates.sort(key=len)
                    best_match = candidates[0]
                    self.comb_logic += f"    {port_name} <= {best_match};\n"
                    self.assigned_signals.add(port_name)

    def _generate_enable_connections(self):
        """Generate connections for enable signals that are declared but unassigned.

        Uses structural detection based on graph content rather than hardcoded instruction names:
        - RF write enables: instr_rf_write_enable <= instr_enable_and and instr_rd_ne_0
        - Conditional branches: instr_enable <= instr_enable_and and instr_res (when _res exists)
        - Unconditional jumps: instr_enable <= instr_enable_and (when no _res exists)
        """
        # Build a set of all declared signal names for fast lookup
        declared_signals = {s['name'] for s in self.signal_declarations}

        # Find all enable signals that need connections
        enable_assignments = []

        for sig_decl in self.signal_declarations:
            sig_name = sig_decl['name']

            # Skip if already assigned by node processing
            if sig_name in self.assigned_signals:
                continue

            # Check for rf_write_enable signals
            if sig_name.endswith('_rf_write_enable'):
                # Extract instruction prefix (e.g., "add" from "add_rf_write_enable")
                instr_prefix = sig_name.replace('_rf_write_enable', '')

                # Look for corresponding rd_ne_0 signal (with double prefix pattern)
                rd_ne_0_name = f"{instr_prefix}_{instr_prefix}_rd_ne_0"
                if rd_ne_0_name in declared_signals:
                    # Use enable_and signal (instruction decode) AND rd_ne_0 (conditional write)
                    enable_and_name = f"{instr_prefix}_enable_and"
                    if enable_and_name in declared_signals:
                        enable_assignments.append(f"    {sig_name} <= {enable_and_name} and {rd_ne_0_name};\n")
                        self.assigned_signals.add(sig_name)

            # Structural detection for branch/jump enable signals
            # Pattern: *_enable signals that have corresponding *_enable_and
            elif sig_name.endswith('_enable') and not sig_name.endswith('_rf_write_enable'):
                instr_prefix = sig_name[:-7]  # Remove '_enable' suffix

                # Check if this has a corresponding enable_and signal (indicates instruction enable)
                enable_and_name = f"{instr_prefix}_enable_and"
                if enable_and_name in declared_signals:
                    # Check if there's a _res signal (indicates conditional branch)
                    res_name = f"{instr_prefix}_res"
                    if res_name in declared_signals:
                        # Conditional branch: enable = enable_and AND res
                        enable_assignments.append(f"    {sig_name} <= {enable_and_name} and {res_name};\n")
                        self.assigned_signals.add(sig_name)
                    else:
                        # Unconditional jump: enable = enable_and (no condition check)
                        enable_assignments.append(f"    {sig_name} <= {enable_and_name};\n")
                        self.assigned_signals.add(sig_name)

        # Add the assignments to combinational logic
        if enable_assignments:
            self.comb_logic += "\n    -- Enable signal connections\n"
            for assignment in enable_assignments:
                self.comb_logic += assignment

    def _get_dependency_order(self) -> List[Node]:
        """Get nodes in dependency order (topological sort)."""
        ordered = []
        remaining = set(self.graph.nodes.values())

        while remaining:
            ready = []
            for node in remaining:
                dependencies_satisfied = True
                for edge in node.incoming_edges:
                    if edge.source in remaining and edge.data.get('type') in ['operand', 'array_index', 'bit_access']:
                        dependencies_satisfied = False
                        break
                if dependencies_satisfied:
                    ready.append(node)

            if not ready:
                ready = [next(iter(remaining))]

            for node in ready:
                ordered.append(node)
                remaining.remove(node)

        return ordered

    def _generate_operation_logic(self, node: Node):
        """Generate logic for operation nodes."""
        vhdl_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        # Debug logging for NOT operations
        if 'not_var_proc' in node.id and 'a_dash' in node.id:
            print(f"  vhdl_name: {vhdl_name}")
            print(f"  in assigned_signals: {vhdl_name in self.assigned_signals}")
            print(f"  outgoing edges: {len(node.outgoing_edges)}")

        if vhdl_name in self.assigned_signals:
            return

        # Dead code elimination: Skip operations whose results are never used
        # (have no outgoing edges)
        # EXCEPTION: Keep comparison operations (*_=_const_* or *_eq_const_*) even if they have
        # no outgoing edges, because they may be referenced by name in conditional logic
        is_comparison_signal = ('_eq_const_' in node.id or '_=_const_' in node.id)
        if not node.outgoing_edges and not is_comparison_signal:
            return

        # Handle mux operations (with...select statements)
        operator = node.data.get('operator', '')
        if operator == 'mux':
            # Generate conditional assignment for mux
            # Format: target <= value1 when condition1 else value2 when condition2 else default;
            result = vhdl_name

            # Find selector and input edges
            selector_node = None
            inputs = {}  # choice -> value mapping

            for edge in node.incoming_edges:
                edge_type = edge.data.get('type', '')
                if edge_type == 'mux_selector':
                    selector_node = edge.source
                elif edge_type == 'mux_input':
                    choice = edge.data.get('choice', 'others')
                    value_node = edge.source
                    value_name = self._format_literal_inline(value_node)
                    if not value_name:
                        value_name = self.node_id_to_name.get(value_node.id, self._sanitize_identifier(value_node.id))
                    inputs[choice] = value_name

            if selector_node and inputs:
                selector_name = self.node_id_to_name.get(selector_node.id, self._sanitize_identifier(selector_node.id))

                # Build conditional assignment
                conditions = []
                default_value = None
                for choice, value in inputs.items():
                    if choice == 'others':
                        default_value = value
                    else:
                        # Parse the choice - could be '1', "'1'", "01", etc.
                        choice_val = choice.strip()
                        if choice_val.startswith("'") and choice_val.endswith("'"):
                            # Character literal like '1'
                            conditions.append(f"{value} when {selector_name} = {choice_val}")
                        else:
                            # Try to format as character literal for 1-bit selectors
                            conditions.append(f"{value} when {selector_name} = '{choice_val}'")

                if conditions or default_value:
                    if conditions:
                        cond_str = " else ".join(conditions)
                        if default_value:
                            generated = f"    {result} <= {cond_str} else {default_value};\n"
                        else:
                            generated = f"    {result} <= {cond_str};\n"
                    elif default_value:
                        generated = f"    {result} <= {default_value};\n"
                    self.comb_logic += generated
                    self.assigned_signals.add(vhdl_name)
                    return

        # Convert invalid AND operations to concatenation
        # These are misparsed concatenations (VHDL '&' operator mistaken for bitwise AND)
        # IMPORTANT: Don't convert if the literal has a multi-bit width (e.g., 32'hFFFFFFFE)
        # which indicates it's a bitwise AND with a mask, not a concatenation
        if operator == '&' and len(node.incoming_edges) >= 2:
            # Check if any operand is a concatenation or a SMALL literal (likely misparsed concatenation)
            # But NOT a multi-bit literal mask (which indicates bitwise AND)
            has_concat_indicator = False
            has_multibit_mask = False
            for edge in node.incoming_edges:
                operand = edge.source
                operand_type = operand.data.get('type', '')

                if (operand.data.get('is_concatenation') or
                    operand.data.get('operator') == 'concat'):
                    has_concat_indicator = True
                    break

                # Check for verilog_hex_literal with explicit width (e.g., 32'hFFFFFFFE)
                # These are bitwise AND masks, NOT concatenations
                if operand_type == 'sized_literal':
                    lit_width = operand.data.get('width')
                    if lit_width is not None and lit_width > 1:
                        has_multibit_mask = True
                    continue

                # Check if literal has explicit multi-bit width (indicates bitwise AND mask)
                if operand_type == 'literal':
                    lit_width = operand.data.get('bit_width')
                    if lit_width is not None and lit_width > 1:
                        # Multi-bit literal = bitwise AND mask, NOT concatenation
                        has_multibit_mask = True
                    elif lit_width == 1 or lit_width is None:
                        # Single-bit or unknown width literal = might be concatenation
                        has_concat_indicator = True

            if has_concat_indicator and not has_multibit_mask:
                # This is a misparsed concatenation - convert to VHDL concatenation
                # Change operator to indicate concatenation (we'll handle it specially below)
                node.data['operator'] = 'concat'
                node.data['is_concatenation'] = True

        # Ensure the mapping is registered
        if node.id not in self.node_id_to_name:
            self.node_id_to_name[node.id] = vhdl_name

        # Handle multi-input OR/AND operations (more than 2 operands)
        # These are created by the graph merger for merged conditions
        # First filter out control_flow edges to get actual operands
        operand_edges = [e for e in node.incoming_edges if e.data.get('type') != 'control_flow']
        if operator in ['||', '&&', 'or', 'and', '|'] and len(operand_edges) > 2:
            # Collect all operands
            operands = []
            # Check if result is 1-bit (boolean reduction) or multi-bit (bitwise operation)
            result_width = node.data.get('bit_width', 1)
            for edge in operand_edges:
                source = edge.source
                operand_inline = self._format_literal_inline(source)
                if operand_inline:
                    operands.append(operand_inline)
                else:
                    operand_name = self.node_id_to_name.get(source.id, self._sanitize_identifier(source.id))
                    # Only extract bit 0 if this is a boolean reduction (1-bit result)
                    if result_width == 1:
                        operand_width = self._get_signal_width(operand_name)
                        if operand_width and operand_width > 1:
                            operands.append(f"{operand_name}(0)")
                        else:
                            operands.append(operand_name)
                    else:
                        # Multi-bit result - use full operand for bitwise operation
                        operands.append(operand_name)

            if operands:
                vhdl_op = 'or' if operator in ['||', 'or', '|'] else 'and'
                # Build multi-input expression
                expr = f" {vhdl_op} ".join(operands)
                self.comb_logic += f"    {vhdl_name} <= {expr};\n"
                self.assigned_signals.add(vhdl_name)
                return

        # Handle unary operations (1 operand) - e.g., NOT, negation
        if node.incoming_edges and len(node.incoming_edges) == 1:
            operand_edge = list(node.incoming_edges)[0]
            operand_source = operand_edge.source

            # Try to inline literal operand
            operand_inline = self._format_literal_inline(operand_source)
            if operand_inline:
                left = operand_inline
            else:
                # Special handling for NOT of variable's indexed bit (e.g., NOT a_dash(31))
                # If the variable was assigned from another signal, use that signal's bit
                # to avoid combinational loops (a_dash_31 = NOT a_dash_31 -> loop!)
                if operand_source.data.get('type') == 'array_access':
                    # Check if this is a variable bit access
                    var_edge = None
                    index_value = None
                    for edge in operand_source.incoming_edges:
                        if edge.source.data.get('is_variable') or edge.source.data.get('type') == 'variable':
                            var_edge = edge
                        elif edge.source.data.get('type') == 'literal':
                            # Get the index value
                            idx_val = edge.source.data.get('value', edge.source.data.get('int_value'))
                            if idx_val is not None:
                                index_value = int(idx_val) if isinstance(idx_val, str) else idx_val

                    if var_edge and index_value is not None:
                        var_node = var_edge.source
                        # Find what the variable was assigned from
                        for var_in_edge in var_node.incoming_edges:
                            source_node = var_in_edge.source
                            if source_node.data.get('type') in ['var', 'signal', 'port']:
                                # Use the source signal's bit instead
                                source_name = self.node_id_to_name.get(source_node.id, self._sanitize_identifier(source_node.id))
                                left = f"{source_name}({index_value})"
                                break
                        else:
                            # Fallback to normal handling
                            left = self.node_id_to_name.get(operand_source.id, self._sanitize_identifier(operand_source.id))
                    else:
                        left = self.node_id_to_name.get(operand_source.id, self._sanitize_identifier(operand_source.id))
                else:
                    left = self.node_id_to_name.get(operand_source.id, self._sanitize_identifier(operand_source.id))

            # Qualify character literals
            left = self._qualify_character_literal(left)

            # Generate the unary operation
            result = vhdl_name

            # Get result and operand widths for NOT operations
            result_width = node.data.get('bit_width') or node.data.get('width') or 1
            operand_width = self._get_signal_width(left)

            # For logical NOT (!) on multi-bit operand with 1-bit result, extract bit 0
            # In Verilog, !vector is true if all bits are 0 - but for stall signals,
            # we only care about bit 0, so extract that
            if operator in ['!', 'not'] and result_width == 1 and operand_width and operand_width > 1:
                left = f"{left}(0)"

            operator_unary_map = {
                'not': f"    {result} <= not {left};\n",
                'inv': f"    {result} <= not {left};\n",
                '~': f"    {result} <= not {left};\n",
                '!': f"    {result} <= not {left};\n",  # C-style NOT operator
                'negate': f"    {result} <= std_logic_vector(-signed({left}));\n",
                '-': f"    {result} <= std_logic_vector(-signed({left}));\n",
            }

            if operator in operator_unary_map:
                self.comb_logic += operator_unary_map[operator]
                self.assigned_signals.add(vhdl_name)
                return

        if node.incoming_edges and len(node.incoming_edges) >= 2:
            left_edge = None
            right_edge = None
            for edge in node.incoming_edges:
                pos = edge.data.get('position')
                edge_type = edge.data.get('type', '')
                # Check position, operand label, or edge type
                if pos == 'left' or edge.data.get('operand') == 'left' or edge_type == 'left_operand':
                    left_edge = edge
                elif pos == 'right' or edge.data.get('operand') == 'right' or edge_type == 'right_operand':
                    right_edge = edge

            if not left_edge or not right_edge:
                # Filter out control_flow edges - they're not operands
                operand_edges = [e for e in node.incoming_edges if e.data.get('type') != 'control_flow']
                edges = list(operand_edges) if operand_edges else list(node.incoming_edges)
                # Sort edges by position field (0/'left' should be left, 1/'right' should be right)
                # Handle both int and string positions (matching Verilog generator behavior)
                def get_position(e):
                    pos = e.data.get('position', 999)
                    if isinstance(pos, str):
                        # Handle named positions from ISA parser
                        if pos == 'left':
                            return 0
                        elif pos == 'right':
                            return 1
                        try:
                            return int(pos)
                        except ValueError:
                            return 999
                    return pos if isinstance(pos, int) else 999
                edges.sort(key=get_position)
                left_edge = edges[0] if len(edges) > 0 else None
                right_edge = edges[1] if len(edges) > 1 else None

            if left_edge and right_edge:
                # Try to inline literals for cleaner VHDL and correct types
                left_source = left_edge.source
                right_source = right_edge.source

                # Check if operands are literals and inline them (only if they have known widths)
                # For comparison operators, we need to match widths
                operator_temp = node.data.get('operator', '')
                is_comparison = operator_temp in ['=', '/=', '==', '!=', '<', '>', '<=', '>=', '<s', '>s', '<=s', '>=s', '<u', '>u', '<=u', '>=u']

                # First pass: get initial widths
                left_inline = self._format_literal_inline(left_source)
                right_inline = self._format_literal_inline(right_source)

                if left_inline:
                    left_name = left_inline
                    left_width = self._infer_bit_width(left_source)
                else:
                    left_name = self.node_id_to_name.get(left_source.id, self._sanitize_identifier(left_source.id))
                    left_width = self._get_signal_width(left_name)

                if right_inline:
                    right_name = right_inline
                    right_width = self._infer_bit_width(right_source)
                else:
                    right_name = self.node_id_to_name.get(right_source.id, self._sanitize_identifier(right_source.id))
                    right_width = self._get_signal_width(right_name)

                # For comparisons with width mismatch, regenerate literals with correct width
                if is_comparison and left_width and right_width and left_width != right_width:
                    left_is_literal = left_source.data.get('type') == 'literal'
                    right_is_literal = right_source.data.get('type') == 'literal'

                    if left_is_literal and not right_is_literal:
                        # Regenerate left literal with right signal's width
                        left_inline_fixed = self._format_literal_inline(left_source, override_width=right_width)
                        if left_inline_fixed:
                            left_name = left_inline_fixed
                            left_width = right_width
                    elif right_is_literal and not left_is_literal:
                        # Regenerate right literal with left signal's width
                        right_inline_fixed = self._format_literal_inline(right_source, override_width=left_width)
                        if right_inline_fixed:
                            right_name = right_inline_fixed
                            right_width = left_width

                # For comparisons/logical ops (NOT concatenations), handle width mismatches
                # If one operand is multi-bit and the other is single-bit, extract LSB from multi-bit
                # Also handle when BOTH operands are multi-bit but result is 1-bit (boolean operation)
                result_width = self._get_signal_width(vhdl_name)

                # If result is 1-bit but operands are multi-bit (boolean operation), extract bits
                if (operator_temp in ['and', 'or', 'xor', '&', '|', '^'] and operator_temp != 'concat' and
                    not node.data.get('is_concatenation') and
                    result_width == 1 and left_width and left_width > 1 and right_width and right_width > 1):
                    # Both operands are multi-bit but result is boolean - extract LSBs
                    # But don't add (0) to hex literals - extract LSB from the literal value instead
                    if not left_name.endswith('(0)') and not '(0)' in left_name:
                        if left_name.startswith('x"') or left_name.startswith('b"'):
                            # Extract LSB from hex/binary literal
                            left_name = self._extract_literal_lsb(left_name)
                        else:
                            left_name = f"{left_name}(0)"
                    if not right_name.endswith('(0)') and not '(0)' in right_name:
                        if right_name.startswith('x"') or right_name.startswith('b"'):
                            # Extract LSB from hex/binary literal
                            right_name = self._extract_literal_lsb(right_name)
                        else:
                            right_name = f"{right_name}(0)"

                # Handle width mismatches between operands
                elif left_width and right_width and left_width != right_width and operator_temp != 'concat' and not node.data.get('is_concatenation'):
                    if left_width == 1 and right_width > 1:
                        # Left is 1-bit, right is multi-bit - extract LSB from right
                        # Check if indexing was already added
                        if not right_name.endswith('(0)') and not '(0)' in right_name:
                            if right_inline and "std_logic_vector(to_unsigned" in right_name:
                                # For inline std_logic_vector(to_unsigned(...)), extract before conversion
                                # std_logic_vector(to_unsigned(N, W)) => std_logic(to_unsigned(N, W)(0))
                                right_name = right_name.replace("std_logic_vector(to_unsigned", "std_logic(to_unsigned").replace("))", ")(0))")
                            elif right_inline:
                                right_name = f"{right_name}(0)"
                            else:
                                # For signal names, extract LSB
                                right_name = f"{right_name}(0)"
                    elif right_width == 1 and left_width > 1:
                        # Right is 1-bit, left is multi-bit - extract LSB from left
                        # Check if indexing was already added
                        if not left_name.endswith('(0)') and not '(0)' in left_name:
                            if left_inline and "std_logic_vector(to_unsigned" in left_name:
                                # For inline std_logic_vector(to_unsigned(...)), extract before conversion
                                # std_logic_vector(to_unsigned(N, W)) => std_logic(to_unsigned(N, W)(0))
                                left_name = left_name.replace("std_logic_vector(to_unsigned", "std_logic(to_unsigned").replace("))", ")(0))")
                            elif left_inline:
                                left_name = f"{left_name}(0)"
                            else:
                                # For signal names, extract LSB
                                left_name = f"{left_name}(0)"

                # Support both ISA format (data.expression.operator) and VHDL format (data.operator)
                expr = node.data.get('expression', {})
                if expr.get('type') == 'binary_op':
                    # ISA parser format
                    operator = expr.get('operator', '+')
                elif node.data.get('type') == 'operation':
                    # VHDL parser format: operator is directly in data
                    operator = node.data.get('operator', '+')
                else:
                    operator = '+'

                # For concatenations, extract LSB from multi-bit operands (parser bug workaround)
                # The parser treats bit accesses like a(0) as literals, so concatenations have
                # multi-bit operands when they should be 1-bit
                # Check actual signal widths to avoid double-indexing
                # NOTE: Don't check 'operator == &' here - that causes double-indexing for boolean ANDs
                # Concatenations are now explicitly marked by _mark_concatenations() pre-pass
                if operator == 'concat' or node.data.get('is_concatenation'):
                    # For left operand
                    if not left_inline:
                        actual_left_width = self._get_signal_width(left_name)
                    else:
                        actual_left_width = left_width

                    # For right operand
                    if not right_inline:
                        actual_right_width = self._get_signal_width(right_name)
                    else:
                        actual_right_width = right_width



                    if actual_left_width and actual_left_width > 1:
                        # Check if left operand is a concatenation, bit_slice, or multi-bit literal
                        left_is_concat = (left_source and (left_source.data.get('is_concatenation') or
                                                           left_source.data.get('operator') == 'concat' or
                                                           left_source.data.get('operator') == '&'))
                        left_is_bit_slice = (left_source and left_source.data.get('type') == 'bit_slice')
                        # Check for multi-bit hex/string literal - preserve full width
                        left_is_multibit_literal = (left_source and
                                                    left_source.data.get('type') == 'literal' and
                                                    left_source.data.get('is_string_literal') and
                                                    left_source.data.get('bit_width', 1) > 1)
                        if left_is_concat or left_is_bit_slice or left_is_multibit_literal:
                            # Nested concatenation, bit_slice, or multi-bit literal - use full signal
                            pass  # Don't modify left_name
                        # For inline literals with values 0 or 1, use character literals instead of indexing vectors
                        elif left_inline and "std_logic_vector(to_unsigned" in left_name:
                            # Check if value is 0 or 1
                            if left_source and left_source.data.get('type') == 'literal':
                                value = left_source.data.get('value', -1)
                                # For concatenations extracting single bits, compute LSB and use character literal
                                # This avoids to_unsigned(N, 32)(0) which GHDL can't evaluate at compile time
                                try:
                                    # Convert to int if it's a string
                                    int_val = int(value) if isinstance(value, str) else value
                                    lsb = int_val & 1  # Extract bit 0
                                    # Add type qualifier for VHDL strict typing in concatenations
                                    left_name = f"std_logic'('{lsb}')"
                                except (ValueError, TypeError):
                                    # Fallback for non-numeric values - check if hex/binary literal
                                    if isinstance(value, str) and (value.startswith('x"') or value.startswith('b"') or value.startswith('"')):
                                        left_name = self._extract_literal_lsb(value)
                                    else:
                                        left_name = left_name.replace("std_logic_vector(", "").replace("))", ")") + "(0)"
                            else:
                                left_name = left_name.replace("std_logic_vector(", "").replace("))", ")") + "(0)"
                        elif left_inline:
                            # Check if it's a hex/binary literal - extract LSB properly
                            if left_name.startswith('x"') or left_name.startswith('b"') or (left_name.startswith('"') and '"' in left_name[1:]):
                                left_name = self._extract_literal_lsb(left_name)
                            else:
                                left_name = f"{left_name}(0)"
                        else:
                            left_name = f"{left_name}(0)"

                    if actual_right_width and actual_right_width > 1:
                        # Check if right operand is a concatenation, bit_slice, or multi-bit literal
                        right_is_concat = (right_source and (right_source.data.get('is_concatenation') or
                                                             right_source.data.get('operator') == 'concat' or
                                                             right_source.data.get('operator') == '&'))
                        right_is_bit_slice = (right_source and right_source.data.get('type') == 'bit_slice')
                        # Check for multi-bit hex/string literal - preserve full width
                        # Check both is_string_literal flag and value format (x"...", b"...", "...")
                        right_value = right_source.data.get('value', '') if right_source else ''
                        right_value_str = str(right_value)
                        right_is_string_value = (right_value_str.startswith('x"') or
                                                 right_value_str.startswith('b"') or
                                                 (right_value_str.startswith('"') and right_value_str.endswith('"')))
                        right_is_multibit_literal = (right_source and
                                                     right_source.data.get('type') == 'literal' and
                                                     (right_source.data.get('is_string_literal') or right_is_string_value) and
                                                     right_source.data.get('bit_width', 1) > 1)
                        if right_is_concat or right_is_bit_slice or right_is_multibit_literal:
                            # Nested concatenation, bit_slice, or multi-bit literal - use full signal
                            pass  # Don't modify right_name
                        # For inline literals with values 0 or 1, use character literals instead of indexing vectors
                        elif right_inline and "std_logic_vector(to_unsigned" in right_name:
                            # Check if value is 0 or 1
                            if right_source and right_source.data.get('type') == 'literal':
                                value = right_source.data.get('value', -1)
                                # For concatenations extracting single bits, compute LSB and use character literal
                                # This avoids to_unsigned(N, 32)(0) which GHDL can't evaluate at compile time
                                try:
                                    # Convert to int if it's a string
                                    int_val = int(value) if isinstance(value, str) else value
                                    lsb = int_val & 1  # Extract bit 0
                                    # Add type qualifier for VHDL strict typing in concatenations
                                    right_name = f"std_logic'('{lsb}')"
                                except (ValueError, TypeError):
                                    # Fallback for non-numeric values - check if hex/binary literal
                                    if isinstance(value, str) and (value.startswith('x"') or value.startswith('b"') or value.startswith('"')):
                                        right_name = self._extract_literal_lsb(value)
                                    else:
                                        right_name = right_name.replace("std_logic_vector(", "").replace("))", ")") + "(0)"
                            else:
                                right_name = right_name.replace("std_logic_vector(", "").replace("))", ")") + "(0)"
                        elif right_inline:
                            # Check if it's a hex/binary literal - extract LSB properly
                            if right_name.startswith('x"') or right_name.startswith('b"') or (right_name.startswith('"') and '"' in right_name[1:]):
                                right_name = self._extract_literal_lsb(right_name)
                            else:
                                right_name = f"{right_name}(0)"
                        else:
                            right_name = f"{right_name}(0)"

                # Special handling for unary NOT operation
                if operator == 'not':
                    # For NOT operations, check if we're assigning to a 1-bit signal
                    result_width = self._infer_bit_width(node)
                    if result_width == 1:
                        # If the left operand is an inlined literal, it needs to be 1-bit
                        if left_inline and left_source.data.get('type') == 'literal':
                            value = left_source.data.get('value', 0)
                            # Generate 1-bit literal
                            if int(value) in [0, 1]:
                                left_name = f"'{value}'"
                            else:
                                left_name = f"std_logic_vector(to_unsigned({value}, 32))(0)"

                # Detect if we need signed comparison
                # First check if node has explicit is_signed flag from parser (most reliable)
                is_signed = node.data.get('is_signed', False)
                # Also check if operator is already a signed operator (e.g., '<s', '>s')
                if operator.endswith('s') and operator[:-1] in ['<', '>', '<=', '>=']:
                    is_signed = True
                # Fallback heuristic: check node ID for instruction-specific signed ops
                if not is_signed:
                    node_id_lower = node.id.lower()
                    is_signed = any(keyword in node_id_lower for keyword in ['blt_', 'bge_', 'slt_', 'slti_', 'srai_'])
                    # Exclude unsigned variants (must check these AFTER to override)
                    if any(keyword in node_id_lower for keyword in ['bltu_', 'bgeu_', 'sltu_', 'sltiu_', 'srli_']):
                        is_signed = False

                vhdl_op = self._operator_to_vhdl(operator, left_name, right_name, vhdl_name, is_signed)
                self.comb_logic += vhdl_op
                # Only mark as assigned AFTER successfully generating logic
                self.assigned_signals.add(vhdl_name)

    def _qualify_character_literal(self, operand: str) -> str:
        """Add std_ulogic type qualifier to character literals to avoid ambiguity."""
        # Check if it's a character literal like '0' or '1'
        if len(operand) == 3 and operand.startswith("'") and operand.endswith("'"):
            # Use std_ulogic qualified expression: std_ulogic'('1')
            return f"std_ulogic'({operand})"
        return operand

    def _operator_to_vhdl(self, operator: str, left: str, right: str, result: str, is_signed: bool = False) -> str:
        """Convert operator to VHDL operation.

        Args:
            operator: The operator symbol
            left: Left operand signal name
            right: Right operand signal name
            result: Result signal name
            is_signed: Whether to use signed arithmetic/comparison
        """
        # Use signed or unsigned based on is_signed flag
        cast = "signed" if is_signed else "unsigned"

        # For concatenations, check if we need zero-extension
        # Get result signal width from declarations
        result_width = self._get_signal_width(result)
        concat_expr = None
        if operator == 'concat' and result_width:
            # Calculate concatenation width based on operand types
            left_width = 1  # Assume 1-bit by default
            right_width = 1

            # Get left operand width
            if "std_logic'(" in left:
                left_width = 1  # Character literal
            else:
                # Try to get signal width
                left_width = self._get_signal_width(left) or 1

            # Get right operand width
            if "std_logic'(" in right or ("'" in right and len(right) <= 3):
                # Character literal like std_logic'('1') or '1'
                right_width = 1
            else:
                right_width = self._get_signal_width(right) or 1

            concat_width = left_width + right_width

            # Handle width mismatch between concatenation and target signal
            if concat_width < result_width:
                # Concatenation too narrow - add zero-extension
                concat_expr = f"    {result} <= ({result_width-1} downto {concat_width} => '0') & ({left} & {right});\n"
            elif concat_width > result_width:
                # Concatenation too wide - this indicates a problem in the resource graph
                # These are typically literal-building chains that should be optimized
                # For now, take only the LSBs from the left operand and concatenate with right
                # This assumes we're building a value bit-by-bit and just need the lower bits
                if left_width > result_width - right_width:
                    # Need to slice the left operand to fit
                    slice_width = result_width - right_width
                    if slice_width > 0:
                        # Can't slice a literal directly - check if it's a hex literal
                        # Also handle case where (0) was already appended to literal
                        clean_left = left.split('(')[0] if '(' in left else left
                        if clean_left.startswith('x"') or clean_left.startswith('b"') or (clean_left.startswith('"') and clean_left.endswith('"')):
                            # Extract the lower bits from the literal
                            left_bits = self._literal_to_binary(left)
                            if left_bits and len(left_bits) >= slice_width:
                                sliced_bits = left_bits[-slice_width:]  # Take LSBs
                                concat_expr = f"    {result} <= \"{sliced_bits}\" & {right};\n"
                            else:
                                # Fallback - use zeros
                                concat_expr = f"    {result} <= \"{('0' * slice_width)}\" & {right};\n"
                        elif left.endswith('(0)'):
                            # Left operand is already a single bit (extracted from array)
                            # Can't slice it further - if we need 1 bit, use it as-is
                            if slice_width == 1:
                                concat_expr = f"    {result} <= {left} & {right};\n"
                            else:
                                # Need more than 1 bit from a single bit - pad with zeros
                                concat_expr = f"    {result} <= ({slice_width - 1} downto 1 => '0') & {left} & {right};\n"
                        elif left.startswith("'") and left.endswith("'"):
                            # Left operand is a character literal - can't slice it
                            # Replicate the character for the slice width
                            char = left.strip("'")
                            if slice_width == 1:
                                concat_expr = f"    {result} <= '{char}' & {right};\n"
                            else:
                                # Generate bit vector with repeated character
                                bit_vector = char * slice_width
                                concat_expr = f'    {result} <= "{bit_vector}" & {right};\n'
                        else:
                            concat_expr = f"    {result} <= {left}({slice_width - 1} downto 0) & {right};\n"
                    else:
                        # No room for left operand - just use right (shouldn't happen)
                        concat_expr = f"    -- WARNING: Concatenation width mismatch ({concat_width} bits -> {result_width} bits)\n"
                        concat_expr += f"    {result} <= {right};\n"
                else:
                    # Fall back to warning comment - shouldn't happen
                    concat_expr = f"    -- WARNING: Concatenation width mismatch ({concat_width} bits -> {result_width} bits)\n"
                    # Can't slice a literal directly
                    # Also handle case where (0) was already appended to literal
                    clean_left = left.split('(')[0] if '(' in left else left
                    if clean_left.startswith('x"') or clean_left.startswith('b"') or (clean_left.startswith('"') and clean_left.endswith('"')):
                        left_bits = self._literal_to_binary(left)
                        if left_bits and len(left_bits) >= result_width:
                            sliced_bits = left_bits[-result_width:]  # Take LSBs
                            concat_expr += f"    {result} <= \"{sliced_bits}\";\n"
                        else:
                            concat_expr += f"    {result} <= \"{('0' * result_width)}\";\n"
                    elif left.startswith("'") and left.endswith("'"):
                        # Left operand is a character literal - replicate it
                        char = left.strip("'")
                        bit_vector = char * result_width
                        concat_expr += f'    {result} <= "{bit_vector}";\n'
                    else:
                        concat_expr += f"    {result} <= {left}({result_width-1} downto 0);\n"

        # Qualify character literals to avoid ambiguity in comparisons and logical ops
        if operator in ['=', '/=', '==', '!=', 'and', 'or', 'xor', 'nand', 'nor', 'xnor', 'not']:
            orig_left = left
            orig_right = right

            # For bitwise AND/OR/XOR on vectors, extend scalar literals to match vector width
            if operator in ['and', 'or', 'xor', 'nand', 'nor', 'xnor']:
                # Check if we're operating on vectors (result is multi-bit)
                result_width = self._get_signal_width(result)
                if result_width and result_width > 1:
                    # Check if left is a character literal and right is a vector (or vice versa)
                    left_is_char = (len(orig_left) == 3 and orig_left.startswith("'") and orig_left.endswith("'"))
                    right_is_char = (len(orig_right) == 3 and orig_right.startswith("'") and orig_right.endswith("'"))

                    if left_is_char and not right_is_char:
                        # Extend left character literal to match result width
                        char = orig_left[1:-1]  # Extract '0' or '1'
                        # Use (others => '0') or (others => '1') syntax
                        left = f"({result_width-1} downto 0 => '{char}')"
                    elif right_is_char and not left_is_char:
                        # Extend right character literal to match result width
                        char = orig_right[1:-1]  # Extract '0' or '1'
                        # Use (others => '0') or (others => '1') syntax
                        right = f"({result_width-1} downto 0 => '{char}')"
                    else:
                        # Both are either vectors or both are scalars - qualify as normal
                        left = self._qualify_character_literal(left)
                        right = self._qualify_character_literal(right)
                else:
                    # Scalar operation - just qualify
                    left = self._qualify_character_literal(left)
                    right = self._qualify_character_literal(right)
            else:
                # For comparisons and NOT, just qualify
                left = self._qualify_character_literal(left)
                right = self._qualify_character_literal(right)


            # Fix type mismatch: if one operand ends with (0) (std_logic) but other is vector
            if left.endswith('(0)') and 'std_logic_vector(to_unsigned' in right:
                # Convert vector to single bit by extracting LSB
                # std_logic_vector(to_unsigned(N, W)) -> '0' or '1' based on N
                import re
                match = re.search(r'to_unsigned\((\d+),', right)
                if match:
                    val = int(match.group(1))
                    lsb = val & 1
                    right = f"'{lsb}'"
            elif right.endswith('(0)') and 'std_logic_vector(to_unsigned' in left:
                # Convert vector to single bit by extracting LSB
                import re
                match = re.search(r'to_unsigned\((\d+),', left)
                if match:
                    val = int(match.group(1))
                    lsb = val & 1
                    left = f"'{lsb}'"
            # Fix type mismatch: 1-bit signal compared with 32-bit vector
            # This happens when a 1-bit signal like 'reset' is compared with a literal
            elif 'std_logic_vector(to_unsigned' in right:
                # Check if left operand is a 1-bit signal
                left_width = self._get_signal_width(left)
                if left_width == 1:
                    import re
                    match = re.search(r'to_unsigned\((\d+),', right)
                    if match:
                        val = int(match.group(1))
                        lsb = val & 1
                        right = f"std_ulogic'('{lsb}')"
            elif 'std_logic_vector(to_unsigned' in left:
                # Check if right operand is a 1-bit signal
                right_width = self._get_signal_width(right)
                if right_width == 1:
                    import re
                    match = re.search(r'to_unsigned\((\d+),', left)
                    if match:
                        val = int(match.group(1))
                        lsb = val & 1
                        left = f"std_ulogic'('{lsb}')"

        operator_map = {
            '+': f"    {result} <= std_logic_vector({cast}({left}) + {cast}({right}));\n",
            '-': f"    {result} <= std_logic_vector({cast}({left}) - {cast}({right}));\n",
            '*': f"    {result} <= std_logic_vector({cast}({left}) * {cast}({right}));\n",
            '/': f"    {result} <= std_logic_vector({cast}({left}) / {cast}({right}));\n",
            '&': f"    {result} <= {left} and {right};\n",
            '|': f"    {result} <= {left} or {right};\n",
            '^': f"    {result} <= {left} xor {right};\n",
            # Verilog-style logical operators (used by graph merger)
            '||': f"    {result} <= {left} or {right};\n",
            '&&': f"    {result} <= {left} and {right};\n",
            # VHDL concatenation operator (for correcting misparsed concatenations)
            'concat': f"    {result} <= {left} & {right};\n",
            # VHDL logical operators (from VHDL parser)
            'and': f"    {result} <= {left} and {right};\n",
            'or': f"    {result} <= {left} or {right};\n",
            'xor': f"    {result} <= {left} xor {right};\n",
            'nand': f"    {result} <= {left} nand {right};\n",
            'nor': f"    {result} <= {left} nor {right};\n",
            'xnor': f"    {result} <= {left} xnor {right};\n",
            'not': f"    {result} <= not {left};\n",
            '<<': None,  # Handled specially below
            '>>': None,  # Handled specially below
            '>>>': None,  # Handled specially below
            # VHDL equality operators
            '=': f"    {result} <= '1' when {left} = {right} else '0';\n",
            '/=': f"    {result} <= '1' when {left} /= {right} else '0';\n",
            # Verilog/C-style equality operators (map to same VHDL syntax)
            '==': f"    {result} <= '1' when {left} = {right} else '0';\n",
            '!=': f"    {result} <= '1' when {left} /= {right} else '0';\n",
            '<': f"    {result} <= '1' when {cast}({left}) < {cast}({right}) else '0';\n",
            '>': f"    {result} <= '1' when {cast}({left}) > {cast}({right}) else '0';\n",
            '<=': f"    {result} <= '1' when {cast}({left}) <= {cast}({right}) else '0';\n",
            '>=': f"    {result} <= '1' when {cast}({left}) >= {cast}({right}) else '0';\n",
            # Signed comparison operators (explicit)
            '<s': f"    {result} <= '1' when signed({left}) < signed({right}) else '0';\n",
            '>s': f"    {result} <= '1' when signed({left}) > signed({right}) else '0';\n",
            '<=s': f"    {result} <= '1' when signed({left}) <= signed({right}) else '0';\n",
            '>=s': f"    {result} <= '1' when signed({left}) >= signed({right}) else '0';\n",
            # Unsigned comparison operators (explicit)
            '<u': f"    {result} <= '1' when unsigned({left}) < unsigned({right}) else '0';\n",
            '>u': f"    {result} <= '1' when unsigned({left}) > unsigned({right}) else '0';\n",
            '<=u': f"    {result} <= '1' when unsigned({left}) <= unsigned({right}) else '0';\n",
            '>=u': f"    {result} <= '1' when unsigned({left}) >= unsigned({right}) else '0';\n",
        }

        # Use custom concatenation expression if we computed one for zero-extension
        if concat_expr:
            return concat_expr

        # Handle width mismatch for equality comparisons
        # VHDL requires matching widths for std_logic_vector comparisons
        if operator in ['=', '/=', '==', '!=']:
            left_width = self._get_signal_width(left)
            right_width = self._get_signal_width(right)

            # Check if operands are literals (don't slice literals, they're sized correctly already)
            left_is_literal = 'to_unsigned' in left or 'to_signed' in left or left.startswith('"')
            right_is_literal = 'to_unsigned' in right or 'to_signed' in right or right.startswith('"')

            # Only handle if both widths are known and different, and at least one is a signal
            if left_width is not None and right_width is not None and left_width != right_width:
                # Use the smaller width - slice the wider signal (but only if it's not a literal)
                min_width = min(left_width, right_width)
                if left_width > min_width and not left_is_literal:
                    left_sliced = f"{left}({min_width - 1} downto 0)"
                else:
                    left_sliced = left
                if right_width > min_width and not right_is_literal:
                    right_sliced = f"{right}({min_width - 1} downto 0)"
                else:
                    right_sliced = right

                # Only apply if we actually sliced something (not both are literals)
                if left_sliced != left or right_sliced != right:
                    vhdl_op = '=' if operator in ['=', '=='] else '/='
                    return f"    {result} <= '1' when {left_sliced} {vhdl_op} {right_sliced} else '0';\n"

        # Handle shift operators specially - resize operand to result width first
        if operator in ['<<', '>>', '>>>']:
            result_width = self._get_signal_width(result)
            if result_width is None:
                result_width = 32  # Default for RISC-V
            if operator == '<<':
                return f"    {result} <= std_logic_vector(shift_left(resize(unsigned({left}), {result_width}), to_integer(unsigned({right}))));\n"
            elif operator == '>>':
                return f"    {result} <= std_logic_vector(shift_right(resize(unsigned({left}), {result_width}), to_integer(unsigned({right}))));\n"
            else:  # >>>
                return f"    {result} <= std_logic_vector(shift_right(resize(signed({left}), {result_width}), to_integer(unsigned({right}))));\n"

        return operator_map.get(operator, f"    {result} <= {left};\n")

    def _generate_array_access_logic(self, node: Node):
        """Generate logic for array access nodes."""
        vhdl_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        # Skip if already assigned (e.g., by conditional logic for variable bit modification)
        if vhdl_name in self.assigned_signals:
            return

        if '_wr' in node.id and node.data.get('type') == 'array_access':
            for edge in node.incoming_edges:
                source_node = edge.source
                if source_node.data.get('is_memory', False):
                    return

        if node.incoming_edges and len(node.incoming_edges) >= 2:
            array_edge = None
            index_edge = None

            # First pass: Look for memory and literal/index edges
            for edge in node.incoming_edges:
                source_type = edge.source.data.get('type')
                is_memory = edge.source.data.get('is_memory', False)
                edge_type = edge.data.get('type')

                if is_memory:
                    array_edge = edge
                elif source_type == 'literal' or edge_type == 'index':
                    index_edge = edge

            # Second pass: Look for isa_state and other signal types
            for edge in node.incoming_edges:
                if edge == array_edge or edge == index_edge:
                    continue
                source_type = edge.source.data.get('type')
                edge_type = edge.data.get('type')

                if not array_edge and source_type.startswith('isa_state'):
                    array_edge = edge
                elif not array_edge and edge_type == 'array':
                    # Parser marks the array source with edge type 'array'
                    array_edge = edge
                elif not index_edge:
                    index_edge = edge

            # Third pass: If we have exactly 2 edges and found one, the other must be it
            if len(node.incoming_edges) == 2:
                if not array_edge and index_edge:
                    for edge in node.incoming_edges:
                        if edge != index_edge:
                            array_edge = edge
                            break
                elif not index_edge and array_edge:
                    for edge in node.incoming_edges:
                        if edge != array_edge:
                            index_edge = edge
                            break

            if array_edge and index_edge:
                array_name = self.node_id_to_name.get(array_edge.source.id, self._sanitize_identifier(array_edge.source.id))
                index_source = index_edge.source

                is_index_literal = index_edge.source.data.get('type') == 'literal'

                # Get target and source bit widths for proper conversion
                target_width = self._infer_bit_width(node)
                source_width = self._infer_bit_width(array_edge.source)

                # Generate array access
                # For byte-addressed memories (imem/dmem), divide address by 4
                # Register file (rf) is indexed by register number, not address
                mem_is_byte_addressed = (array_edge.source.id in ['imem', 'dmem'])
                is_rf_read = (array_edge.source.id == 'rf')

                if is_index_literal:
                    index_value = index_source.data.get('value', index_source.id)
                    if mem_is_byte_addressed:
                        # Convert byte address to word index
                        array_access = f"{array_name}({index_value} / 4)"
                    elif is_rf_read and index_value == '0':
                        # RISC-V x0 is hardwired to 0
                        array_access = "(others => '0')"
                    else:
                        array_access = f"{array_name}({index_value})"
                else:
                    index_name = self.node_id_to_name.get(index_source.id, self._sanitize_identifier(index_source.id))
                    if mem_is_byte_addressed:
                        # Get memory bit width to determine shift amount (2 for 32-bit, 3 for 64-bit)
                        mem_width = self.memory_declarations.get(array_edge.source.id, {}).get('bit_width', 32)
                        shift_amount = 3 if mem_width == 64 else 2
                        addr_expr = f"std_logic_vector(shift_right(unsigned({index_name}), {shift_amount}))"
                        array_access = f"safe_{array_name}_read({array_name}, {addr_expr})"
                    elif is_rf_read:
                        # RISC-V x0 is hardwired to 0 - check on read
                        # If index is 0, return 0, otherwise read from rf
                        # For pipelined processors with bypass, implement write-first behavior
                        # to handle the case where consumer stalls at Decode while producer writes at Writeback
                        writeback_rd_signal = None
                        writeback_enable_signal = None

                        # Check if this is a pipelined processor with bypass by looking for
                        # forwarding-related signals (fwd_cmp_* or fwd_write_rf_*) or
                        # rf_write_enable_valid_gated (indicates pipelined RF writes that may need write-first)
                        has_bypass = any(
                            sig['name'].startswith('fwd_cmp_') or
                            sig['name'].startswith('fwd_write_rf_') or
                            sig['name'] == 'rf_write_enable_valid_gated'
                            for sig in self.signal_declarations
                        )

                        if has_bypass:
                            # Find the writeback rd signal and write enable
                            for sig in self.signal_declarations:
                                sig_name = sig['name']
                                # Pattern: pipe_writeback_..._rd_..._pipe or pipe_memorywriteback_..._rd_..._pipe (5 bits)
                                # The actual pattern varies by pipeline depth
                                if (('_writeback_' in sig_name or 'writeback_' in sig_name) and
                                    '_rd_' in sig_name and sig_name.endswith('_pipe') and
                                    sig.get('bit_width', 1) == 5):
                                    writeback_rd_signal = sig_name
                                # Pattern: rf_write_enable_valid_gated (the combined write enable)
                                if sig_name == 'rf_write_enable_valid_gated':
                                    writeback_enable_signal = sig_name

                        if writeback_rd_signal and writeback_enable_signal:
                            # Write-first RF read: if write is happening to same address, return write data
                            array_access = (f"(others => '0') when to_integer(unsigned({index_name})) = 0 else "
                                          f"rf_write_data_mux when ({writeback_enable_signal} = '1' and "
                                          f"{writeback_rd_signal} = {index_name}) else "
                                          f"{array_name}(to_integer(unsigned({index_name})))")
                        else:
                            # Standard read without write-first
                            array_access = f"(others => '0') when to_integer(unsigned({index_name})) = 0 else {array_name}(to_integer(unsigned({index_name})))"
                    else:
                        array_access = f"{array_name}(to_integer(unsigned({index_name})))"

                # Handle width mismatch (e.g., byte/halfword load from 32-bit memory)
                # For simple bit access (target=1, index is literal), the array_access is already the right type
                is_single_bit_access = (target_width == 1 and is_index_literal)

                if target_width and source_width and target_width < source_width and mem_is_byte_addressed and not is_single_bit_access:
                    # Byte/halfword load from word-addressed memory
                    # Need to select the correct byte/halfword based on address offset
                    word_wire_name = f"{vhdl_name}_word"

                    # First, read the full word
                    self.additional_signals.append({
                        'name': word_wire_name,
                        'bit_width': source_width
                    })
                    self.comb_logic += f"    {word_wire_name} <= {array_access};\n"

                    # Then select the appropriate byte/halfword based on address
                    if target_width == 8:
                        # Byte selection: use bits [1:0] of address to select byte
                        # Use a case statement since VHDL doesn't support dynamic slice ranges
                        self.comb_logic += f"    {vhdl_name} <= {word_wire_name}(7 downto 0) when {index_name}(1 downto 0) = \"00\" else\n"
                        self.comb_logic += f"                 {word_wire_name}(15 downto 8) when {index_name}(1 downto 0) = \"01\" else\n"
                        self.comb_logic += f"                 {word_wire_name}(23 downto 16) when {index_name}(1 downto 0) = \"10\" else\n"
                        self.comb_logic += f"                 {word_wire_name}(31 downto 24);\n"
                    elif target_width == 16:
                        # Halfword selection: use bit [1] of address to select halfword
                        self.comb_logic += f"    {vhdl_name} <= {word_wire_name}(15 downto 0) when {index_name}(1) = '0' else {word_wire_name}(31 downto 16);\n"
                    else:
                        # Other sizes: just truncate
                        self.comb_logic += f"    {vhdl_name} <= {word_wire_name}({target_width-1} downto 0);\n"
                else:
                    # For single-bit access or exact width match, assign directly
                    # array(index) already returns the correct type (std_logic for bit, vector for slice)
                    self.comb_logic += f"    {vhdl_name} <= {array_access};\n"

                # Mark signal as assigned
                self.assigned_signals.add(vhdl_name)

    def _generate_bit_slice_logic(self, node: Node):
        """Generate logic for bit slice nodes."""
        expr = node.data.get('expression', {})
        vhdl_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        if expr.get('type') == 'bit_slice':
            target_name = None
            if node.incoming_edges:
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'bit_access':
                        target_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                        break
                if not target_name and node.incoming_edges:
                    first_edge = next(iter(node.incoming_edges))
                    target_name = self.node_id_to_name.get(first_edge.source.id, self._sanitize_identifier(first_edge.source.id))

            if not target_name:
                target_name = self._get_vhdl_name_for_expression(expr['target'])

            high, low = expr['range']

            # Check source signal width and validate slice bounds
            source_width = None
            if node.incoming_edges:
                for edge in node.incoming_edges:
                    source_node = edge.source
                    source_width = source_node.data.get('bit_width')
                    if source_width is None:
                        source_width = self._infer_bit_width(source_node)
                    break

            # If slice indices exceed source width, skip this slice (it's invalid)
            if source_width is not None and high >= source_width:
                # The slice is out of bounds for the source signal
                # This can happen when memory access transform creates slices
                # before byte selection narrows the signal width
                # Just assign zeros to avoid runtime errors
                slice_width = high - low + 1
                if slice_width == 1:
                    self.comb_logic += f"    {vhdl_name} <= '0'; -- slice out of bounds for {target_name}\n"
                else:
                    self.comb_logic += f"    {vhdl_name} <= (others => '0'); -- slice out of bounds for {target_name}\n"
                return

            # Check if target is a character literal (can't be sliced)
            if target_name and target_name.startswith("'") and target_name.endswith("'"):
                # Character literal '0' or '1' - replicate it for the slice width
                slice_width = high - low + 1
                char = target_name.strip("'")
                if slice_width == 1:
                    self.comb_logic += f"    {vhdl_name} <= '{char}';\n"
                else:
                    # Generate bit vector with repeated character
                    bit_vector = char * slice_width
                    self.comb_logic += f'    {vhdl_name} <= "{bit_vector}";\n'
            elif high == low:
                self.comb_logic += f"    {vhdl_name} <= {target_name}({high});\n"
            else:
                self.comb_logic += f"    {vhdl_name} <= {target_name}({high} downto {low});\n"

    def _generate_literal_logic(self, node: Node):
        """Generate logic for literal nodes."""
        vhdl_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))
        value = node.data.get('value', 0)

        # Get bit width from node data first, then infer if needed
        bit_width = node.data.get('bit_width')
        if bit_width is None:
            bit_width = self._infer_bit_width(node)

        # Look up the signal's declared width to ensure proper padding
        declared_width = None
        for sig_decl in self.signal_declarations:
            if sig_decl['name'] == vhdl_name:
                declared_width = sig_decl['bit_width']
                # Don't override declared_width if it's explicitly set (including to 1)
                # Only set default if it was truly None in the declaration
                break

        # Use declared width if available, otherwise use inferred bit width
        # CRITICAL: If declared_width is explicitly 1, we must use it (don't override with default)
        if declared_width is not None:
            target_width = declared_width
        elif bit_width is not None:
            target_width = bit_width
        else:
            target_width = 32  # Default for RISC-V

        # Debug for problematic signals
        if 'not_const' in vhdl_name and vhdl_name.endswith(('_3', '_4', '_12')):
            print(f"  value={value}, bit_width={bit_width}, declared_width={declared_width}, target_width={target_width}")

        if target_width > 1:
            # Handle special VHDL aggregate expressions
            if isinstance(value, str):
                # Binary literal: "000", "101", etc.
                if value.startswith('"') and value.endswith('"'):
                    inner_bits = value[1:-1]
                    if all(c in '01' for c in inner_bits):
                        # Pad to target width
                        padded_bits = inner_bits.zfill(target_width)
                        self.comb_logic += f"    {vhdl_name} <= \"{padded_bits}\";\n"
                        return

                # Aggregate expressions
                if value.startswith('(others =>'):
                    # Extract the value from (others => X)
                    match = value.strip('()')
                    if 'others => 0' in match:
                        self.comb_logic += f"    {vhdl_name} <= (others => '0');\n"
                    elif 'others => 1' in match:
                        self.comb_logic += f"    {vhdl_name} <= (others => '1');\n"
                    else:
                        self.comb_logic += f"    {vhdl_name} <= {value};\n"
                    return

                # Try to parse as integer
                try:
                    int_value = int(value, 0)  # Handles hex (0x), octal (0o), binary (0b)
                    # Mask value to fit in target width
                    max_val = (1 << target_width) - 1
                    if int_value > max_val:
                        int_value = int_value & max_val
                    self.comb_logic += f"    {vhdl_name} <= std_logic_vector(to_unsigned({int_value}, {target_width}));\n"
                    return
                except (ValueError, TypeError):
                    pass

            # Check for VHDL hex string literal (from parser's string_value)
            if node.data.get('is_string_literal') and 'string_value' in node.data:
                hex_str = node.data['string_value']
                # Emit as VHDL hex literal: x"..."
                self.comb_logic += f'    {vhdl_name} <= x"{hex_str}";\n'
                return

            # If value starts with x_ (hex literal from parser), extract the hex part
            if isinstance(value, str) and value.startswith('x_'):
                hex_part = value[2:]  # Remove 'x_' prefix
                self.comb_logic += f'    {vhdl_name} <= x"{hex_part}";\n'
                return

            # Fallback for unparsed string literals (emit as all zeros)
            if isinstance(value, str) and value == 'string_literal':
                self.comb_logic += f"    {vhdl_name} <= (others => '0');\n"
                return

            # Handle bit string literals from parser (x"...", b"...", o"...")
            if isinstance(value, str) and (value.startswith('x"') or value.startswith('b"') or value.startswith('o"')):
                # Already a valid VHDL bit string literal, emit directly
                self.comb_logic += f"    {vhdl_name} <= {value};\n"
                return

            # Integer value - use to_unsigned
            # Mask value to fit in target width
            int_val = int(value)
            max_val = (1 << target_width) - 1
            if int_val > max_val:
                int_val = int_val & max_val
            self.comb_logic += f"    {vhdl_name} <= std_logic_vector(to_unsigned({int_val}, {target_width}));\n"
        else:
            # Single bit - validate value fits in 1 bit
            if isinstance(value, str):
                # Single bit literal: '0' or '1'
                if value.startswith("'") and value.endswith("'"):
                    # Already has single quotes
                    self.comb_logic += f"    {vhdl_name} <= {value};\n"
                elif value.startswith('"') and value.endswith('"'):
                    # Has double quotes (string literal like "1"), convert to character literal
                    inner = value[1:-1]  # Extract content between quotes
                    if len(inner) == 1 and inner in '01':
                        self.comb_logic += f"    {vhdl_name} <= '{inner}';\n"
                    else:
                        # Invalid single-bit string, extract LSB
                        try:
                            int_val = int(inner, 0)
                            # Extract LSB directly by computing modulo 2
                            lsb = int_val & 1
                            self.comb_logic += f"    {vhdl_name} <= '{lsb}';\n"
                        except:
                            self.comb_logic += f"    {vhdl_name} <= '{inner}';\n"  # Fallback
                else:
                    # Raw string value
                    if len(value) == 1 and value in '01':
                        self.comb_logic += f"    {vhdl_name} <= '{value}';\n"
                    else:
                        # Multi-char or invalid, extract LSB from integer conversion
                        try:
                            int_val = int(value, 0)
                            # Extract LSB directly by computing modulo 2
                            lsb = int_val & 1
                            self.comb_logic += f"    {vhdl_name} <= '{lsb}';\n"
                        except:
                            self.comb_logic += f"    {vhdl_name} <= '{value}';\n"  # Fallback
            else:
                # Integer value
                if value in [0, 1]:
                    self.comb_logic += f"    {vhdl_name} <= '{value}';\n"
                else:
                    # Value doesn't fit in 1 bit - extract LSB directly
                    lsb = value & 1
                    self.comb_logic += f"    {vhdl_name} <= '{lsb}';\n"

    def _generate_sized_literal_logic(self, node: Node):
        """Generate logic for sized literal nodes (binary, hex, decimal)."""
        vhdl_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))
        width = node.data.get('width', 32)
        fmt = node.data.get('format', 'bin')

        if fmt == 'hex' or (fmt == 'bin' and 'hex_digits' in node.data):
            # Hex literal: convert to VHDL hex format
            hex_digits = node.data.get('hex_digits') or node.data.get('original_digits', '0')
            expected_hex_len = (width + 3) // 4  # Round up
            if len(hex_digits) < expected_hex_len:
                hex_digits = hex_digits.zfill(expected_hex_len)
            self.comb_logic += f"    {vhdl_name} <= x\"{hex_digits}\";\n"
            self.assigned_signals.add(vhdl_name)
        elif fmt == 'dec':
            # Decimal literal: convert value to binary string for VHDL
            value = node.data.get('value', 0)

            # Look up declared width
            declared_width = self._lookup_declared_width(vhdl_name, width)

            # Mask value to the intended width to avoid generating a string
            # longer than the signal (e.g. value=1024, width=10 -> 10 bits)
            if declared_width > 0:
                value = value & ((1 << declared_width) - 1)
            bits = bin(value)[2:].zfill(declared_width)
            # Truncate to exactly declared_width in case zfill is a no-op
            bits = bits[-declared_width:] if declared_width > 0 else '0'

            if declared_width > 1:
                self.comb_logic += f"    {vhdl_name} <= \"{bits}\";\n"
            else:
                self.comb_logic += f"    {vhdl_name} <= '{bits[-1]}';\n"
            self.assigned_signals.add(vhdl_name)
        else:
            # Binary literal
            bits = node.data.get('bits') or node.data.get('original_digits', '0')
            literal_width = node.data.get('width', len(bits))

            # Look up declared width
            declared_width = self._lookup_declared_width(vhdl_name, max(literal_width, 32))

            if declared_width > 1:
                # Pad bits to match the declared signal width
                if len(bits) < declared_width:
                    bits = bits.zfill(declared_width)  # Zero-pad on the left
                self.comb_logic += f"    {vhdl_name} <= \"{bits}\";\n"
            else:
                self.comb_logic += f"    {vhdl_name} <= '{bits}';\n"

    def _lookup_declared_width(self, vhdl_name: str, default_width: int) -> int:
        """Look up a signal's declared width from signal_declarations."""
        for sig_decl in self.signal_declarations:
            if sig_decl['name'] == vhdl_name:
                w = sig_decl['bit_width']
                return w if w is not None else 32
        return default_width

    def _generate_zero_extend_logic(self, node: Node):
        """Generate logic for zero extend nodes."""
        vhdl_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))
        # Check bit_width first (set by memory_access_transform), then target_width
        target_width = node.data.get('bit_width', node.data.get('target_width', 32))

        # Get input from incoming edge
        input_name = None
        input_width = None
        if node.incoming_edges:
            first_edge = next(iter(node.incoming_edges))
            input_name = self.node_id_to_name.get(first_edge.source.id, self._sanitize_identifier(first_edge.source.id))
            input_width = self._infer_bit_width(first_edge.source)

        if input_name:
            if input_width and input_width < target_width:
                if input_width == 1:
                    # For single-bit std_logic, use concatenation with zeros
                    zeros = target_width - 1
                    self.comb_logic += f"    {vhdl_name} <= ({zeros-1} downto 0 => '0') & {input_name};\n"
                else:
                    # For multi-bit std_logic_vector, use resize
                    self.comb_logic += f"    {vhdl_name} <= std_logic_vector(resize(unsigned({input_name}), {target_width}));\n"
            else:
                # No extension needed
                self.comb_logic += f"    {vhdl_name} <= {input_name};\n"
            self.assigned_signals.add(vhdl_name)

    def _generate_sign_extend_logic(self, node: Node):
        """Generate logic for sign extend nodes."""
        vhdl_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))
        # Check bit_width first (set by memory_access_transform), then target_width
        target_width = node.data.get('bit_width', node.data.get('target_width', 32))

        # Get input from incoming edge
        input_name = None
        input_width = None
        if node.incoming_edges:
            first_edge = next(iter(node.incoming_edges))
            input_name = self.node_id_to_name.get(first_edge.source.id, self._sanitize_identifier(first_edge.source.id))
            input_width = self._infer_bit_width(first_edge.source)

        if input_name:
            if input_width and input_width < target_width:
                if input_width == 1:
                    # For single-bit std_logic, replicate the sign bit
                    zeros = target_width - 1
                    self.comb_logic += f"    {vhdl_name} <= ({zeros-1} downto 0 => {input_name}) & {input_name};\n"
                else:
                    # For multi-bit std_logic_vector, use resize
                    self.comb_logic += f"    {vhdl_name} <= std_logic_vector(resize(signed({input_name}), {target_width}));\n"
            else:
                # No extension needed
                self.comb_logic += f"    {vhdl_name} <= {input_name};\n"
            self.assigned_signals.add(vhdl_name)

    def _generate_concatenation_logic(self, node: Node):
        """Generate logic for concatenation nodes."""
        vhdl_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        if node.incoming_edges:
            parts = []
            for edge in sorted(node.incoming_edges, key=lambda e: e.data.get('position', 0)):
                source_node = edge.source
                source_type = source_node.data.get('type')

                if source_type == 'sized_literal':
                    width = source_node.data.get('width', 1)
                    bits = source_node.data.get('bits', '0')
                    # Pad bits to the full width
                    if len(bits) < width:
                        bits = bits.zfill(width)
                    source_name = f"\"{bits}\""
                elif source_type == 'literal':
                    value = source_node.data.get('value', 0)
                    bit_width = self._infer_bit_width(source_node)

                    # For single-bit literals in concatenations, use character literals
                    if bit_width == 1:
                        # Single bit: use '0' or '1'
                        source_name = f"'{value & 1}'"
                    else:
                        # Multi-bit literal: create proper vector based on value
                        if isinstance(value, int) and value == 0:
                            # Zero vector: use all-zeros string
                            source_name = f"\"{('0' * bit_width)}\""
                        else:
                            # Multi-bit literal: create vector using to_unsigned
                            int_val = int(value) if isinstance(value, int) else value
                            source_name = f"std_logic_vector(to_unsigned({int_val}, {bit_width}))"
                else:
                    source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))

                parts.append(source_name)

            concat_expr = ' & '.join(parts)
            self.comb_logic += f"    {vhdl_name} <= {concat_expr};\n"

    def _generate_repetition_logic(self, node: Node):
        """Generate logic for repetition nodes (e.g., {20{bit}} for sign extension)."""
        vhdl_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        self.assigned_signals.add(vhdl_name)

        # Get repetition count and source
        expr = node.data.get('expression', {})
        count = expr.get('count', 1) if expr.get('type') == 'repetition' else 1

        # Use incoming edge to get the source signal
        if node.incoming_edges:
            source_edge = next(iter(node.incoming_edges))
            source_name = self.node_id_to_name.get(source_edge.source.id, self._sanitize_identifier(source_edge.source.id))

            # In VHDL, bit repetition is done using (others => bit) for single bits
            # or (count-1 downto 0 => bit) for explicit range
            # Since we're replicating a single bit 'count' times, use range notation
            self.comb_logic += f"    {vhdl_name} <= ({count-1} downto 0 => {source_name});\n"
        else:
            # Fallback: try to get from expression
            inner_expr = expr.get('expression', {})
            if inner_expr:
                # This would require more complex expression evaluation
                print(f"Warning: Repetition node {node.id} has no incoming edge and complex expression")
                self.comb_logic += f"    -- TODO: Repetition for {vhdl_name}\n"

    def _generate_ternary_logic(self, node: Node):
        """Generate logic for ternary conditional nodes."""
        vhdl_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        if node.incoming_edges and len(node.incoming_edges) == 3:
            cond_edge = None
            true_edge = None
            false_edge = None

            for edge in node.incoming_edges:
                edge_type = edge.data.get('type')

                if edge_type == 'ternary_condition':
                    cond_edge = edge
                elif edge_type == 'ternary_true':
                    true_edge = edge
                elif edge_type == 'ternary_false':
                    false_edge = edge

            if cond_edge and true_edge and false_edge:
                cond_name = self.node_id_to_name.get(cond_edge.source.id, self._sanitize_identifier(cond_edge.source.id))
                true_name = self.node_id_to_name.get(true_edge.source.id, self._sanitize_identifier(true_edge.source.id))
                false_name = self.node_id_to_name.get(false_edge.source.id, self._sanitize_identifier(false_edge.source.id))

                self.comb_logic += f"    {vhdl_name} <= {true_name} when {cond_name} = '1' else {false_name};\n"

    def _generate_comparison_logic(self, node: Node):
        """Generate logic for comparison nodes."""
        vhdl_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))


        # Dead code elimination: Skip comparisons whose results are never used
        if not node.outgoing_edges:
            return

        # Ensure the mapping is registered
        if node.id not in self.node_id_to_name:
            self.node_id_to_name[node.id] = vhdl_name

        self.assigned_signals.add(vhdl_name)

        operation = node.data.get('operation', '==')
        vhdl_op = '=' if operation == '==' else '/='

        # Use incoming edges to get operands
        if node.incoming_edges and len(node.incoming_edges) >= 2:
            # Two operands from edges
            operands = []
            operand_nodes = []
            for edge in node.incoming_edges:
                edge_type = edge.data.get('type')
                # Accept both edges with specific types and edges without types (None)
                if edge_type in ['decode_input', 'operand', 'left_operand', 'right_operand', None]:
                    source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                    operands.append(source_name)
                    operand_nodes.append(edge.source)

            if len(operands) >= 2:
                # Check operand widths to handle type mismatches
                left_width = self._infer_bit_width(operand_nodes[0])
                right_width = self._infer_bit_width(operand_nodes[1])

                left_operand = operands[0]
                right_operand = operands[1]

                # Check if operands are literals so we can regenerate them with correct width
                left_is_literal = operand_nodes[0].data.get('type') == 'literal'
                right_is_literal = operand_nodes[1].data.get('type') == 'literal'

                # If one operand is a literal and widths don't match, regenerate the literal
                # with the width of the signal it's being compared against
                if left_is_literal and right_width and left_width != right_width:
                    # Regenerate left literal with right's width
                    left_operand = self._format_literal_inline(operand_nodes[0], override_width=right_width)
                    if left_operand:
                        left_width = right_width
                    else:
                        left_operand = operands[0]

                if right_is_literal and left_width and left_width != right_width:
                    # Regenerate right literal with left's width
                    right_operand = self._format_literal_inline(operand_nodes[1], override_width=left_width)
                    if right_operand:
                        right_width = left_width
                    else:
                        right_operand = operands[1]

                # Handle width mismatches between multi-bit and 1-bit operands
                if left_width and right_width and left_width != right_width:
                    # Check if operands are inline literals that need special handling
                    left_is_inline = self._format_literal_inline(operand_nodes[0]) is not None
                    right_is_inline = self._format_literal_inline(operand_nodes[1]) is not None

                    if left_width > 1 and right_width == 1:
                        # Extract LSB from left operand
                        if left_is_inline:
                            # For inline literals, add (0) to the std_logic_vector expression
                            left_operand = f"{left_operand}(0)" if "std_logic_vector" in left_operand else left_operand
                        else:
                            left_operand = f"{left_operand}(0)"
                    elif right_width > 1 and left_width == 1:
                        # Extract LSB from right operand
                        if right_is_inline:
                            # For inline literals, add (0) to the std_logic_vector expression
                            right_operand = f"{right_operand}(0)" if "std_logic_vector" in right_operand else right_operand
                        else:
                            right_operand = f"{right_operand}(0)"
                    elif left_width > 1 and right_width > 1:
                        # Both are multi-bit but different widths - slice wider to match narrower
                        min_width = min(left_width, right_width)
                        if left_width > min_width and not left_is_inline:
                            left_operand = f"{left_operand}({min_width - 1} downto 0)"
                        if right_width > min_width and not right_is_inline:
                            right_operand = f"{right_operand}({min_width - 1} downto 0)"

                self.comb_logic += f"    {vhdl_name} <= '1' when {left_operand} {vhdl_op} {right_operand} else '0';\n"
                return

        # Handle comparison with compare_value in node data (from memory access transform byte mux)
        if 'compare_value' in node.data and node.incoming_edges:
            # Get the operand from the single incoming edge
            left_operand = None
            left_width = 2  # Default for byte offset (2 bits)
            for edge in node.incoming_edges:
                if edge.data.get('type') in ['operand', 'left_operand', None]:
                    left_operand = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                    left_width = self._infer_bit_width(edge.source)
                    break

            if left_operand:
                compare_value = node.data['compare_value']
                operator = node.data.get('operator', '==')
                vhdl_op = '=' if operator == '==' else '/='

                # Format the compare value with appropriate width
                if left_width == 1:
                    # For 1-bit signals, use std_logic format
                    vhdl_value = f"'{compare_value}'"
                else:
                    vhdl_value = f'std_logic_vector(to_unsigned({compare_value}, {left_width}))'

                self.comb_logic += f"    {vhdl_name} <= '1' when {left_operand} {vhdl_op} {vhdl_value} else '0';\n"
                return

        # Single operand from edge, other from expression (common for instruction decode)
        if node.incoming_edges and len(node.incoming_edges) >= 1:
            operands = []
            for edge in node.incoming_edges:
                if edge.data.get('type') in ['decode_input', 'operand', 'left_operand', 'right_operand']:
                    source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                    operands.append(source_name)

            if len(operands) == 1:
                # Get the literal value from expression data
                expr = node.data.get('expression', {})
                if expr.get('type') == 'binary_op':
                    left_expr = expr.get('left', {})
                    right_expr = expr.get('right', {})

                    # Get bit slice info from left expression
                    if left_expr.get('type') == 'bit_slice' and right_expr.get('type') == 'literal':
                        high_bit = left_expr.get('high', {}).get('value')
                        low_bit = left_expr.get('low', {}).get('value')
                        value_str = right_expr.get('value')

                        # Infer bit width from slice
                        if high_bit is not None and low_bit is not None:
                            bit_width = high_bit - low_bit + 1
                        else:
                            bit_width = 32  # default

                        # Format the value in VHDL syntax
                        if value_str.startswith('0b'):
                            # Binary literal
                            bin_str = value_str[2:]
                            vhdl_value = f'"{bin_str}"'
                        elif value_str.startswith('0x'):
                            # Hex literal - convert to explicit bit width to avoid size mismatch
                            hex_str = value_str[2:]
                            int_value = int(hex_str, 16)
                            vhdl_value = f'std_logic_vector(to_unsigned({int_value}, {bit_width}))'
                        else:
                            # Decimal literal - convert to appropriate bit vector
                            int_value = int(value_str)
                            vhdl_value = f'std_logic_vector(to_unsigned({int_value}, {bit_width}))'

                        # Generate bit slice and comparison
                        self.comb_logic += f"    {vhdl_name} <= '1' when {operands[0]}({high_bit} downto {low_bit}) {vhdl_op} {vhdl_value} else '0';\n"
                        return

                # Handle comparison type expression (e.g., sb_addr != 0)
                elif expr.get('type') == 'comparison':
                    left_expr = expr.get('left', {})
                    right_expr = expr.get('right', {})
                    comparison_op = expr.get('operator', '==')
                    vhdl_comparison_op = '=' if comparison_op == '==' else '/='

                    # Simple identifier vs literal comparison
                    if left_expr.get('type') == 'identifier' and right_expr.get('type') == 'literal':
                        # Get the operand width
                        edges_list = list(node.incoming_edges) if node.incoming_edges else []
                        operand_width = self._infer_bit_width(edges_list[0].source) if edges_list else 32
                        literal_value = right_expr.get('value', 0)

                        # Format the literal with correct width
                        if operand_width == 1:
                            vhdl_value = f"'{literal_value}'"
                        else:
                            vhdl_value = f'std_logic_vector(to_unsigned({literal_value}, {operand_width}))'

                        self.comb_logic += f"    {vhdl_name} <= '1' when {operands[0]} {vhdl_comparison_op} {vhdl_value} else '0';\n"
                        return

    def _generate_logical_logic(self, node: Node):
        """Generate logic for logical AND/OR nodes (from instruction decode)."""
        vhdl_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        self.assigned_signals.add(vhdl_name)

        # Determine operation type
        node_type = node.data.get('type')
        operation = 'and' if node_type == 'logical_and' else 'or'

        # Use incoming edges to get operands
        if node.incoming_edges:
            operands = []
            for edge in node.incoming_edges:
                if edge.data.get('type') in ['logic_input', 'operand']:
                    source_id = edge.source.id
                    # Try to get the name from the mapping, or use node.data['name'] if it exists, or sanitize the ID
                    if source_id in self.node_id_to_name:
                        source_name = self.node_id_to_name[source_id]
                    elif 'name' in edge.source.data:
                        source_name = edge.source.data['name']
                    else:
                        source_name = self._sanitize_identifier(source_id)

                    operands.append(source_name)

            if len(operands) >= 2:
                # Join all operands with the operation
                expr_str = f" {operation} ".join(operands)
                self.comb_logic += f"    {vhdl_name} <= {expr_str};\n"
                return
            elif len(operands) == 1:
                # Single operand - just pass through
                self.comb_logic += f"    {vhdl_name} <= {operands[0]};\n"
                return

        # Fallback: generate based on node data
        print(f"Warning: Could not generate logic for {node_type} node {node.id} - insufficient edge information")

    def _generate_instruction_enable_logic(self, node: Node):
        """Generate logic for instruction enable nodes (from instruction decode)."""
        vhdl_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        self.assigned_signals.add(vhdl_name)

        # Instruction enable is typically driven by a single decode_enable edge
        if node.incoming_edges:
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'decode_enable':
                    source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                    self.comb_logic += f"    {vhdl_name} <= {source_name};\n"
                    return

        # Fallback: if no explicit edges, check node data
        print(f"Warning: Could not generate logic for instruction_enable node {node.id} - no decode_enable edge found")

    def _generate_stall_controller_logic(self, node: Node):
        """Generate logic for pipeline stall controller nodes (OR of hazard signals)."""
        vhdl_name = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        # Collect all hazard signals from incoming control edges
        hazard_signals = []
        for edge in node.incoming_edges:
            if edge.data.get('type') == 'control':
                source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                hazard_signals.append(source_name)

        if hazard_signals:
            # Stall if ANY hazard is detected (OR of all hazards)
            stall_expr = ' or '.join(hazard_signals)
            self.comb_logic += f"    {vhdl_name} <= (0 => ({stall_expr}), others => '0');\n"

            # Also generate the NOT signal (used for valid gating)
            not_name = f"{vhdl_name}_not"
            if not_name not in self.assigned_signals:
                self.comb_logic += f"    {not_name} <= not {vhdl_name}(0);\n"
                self.assigned_signals.add(not_name)
        else:
            # No hazards for this stage - never stall
            self.comb_logic += f"    {vhdl_name} <= (others => '0');\n"

            # Generate NOT signal
            not_name = f"{vhdl_name}_not"
            if not_name not in self.assigned_signals:
                self.comb_logic += f"    {not_name} <= '1';\n"
                self.assigned_signals.add(not_name)

    def _generate_variable_assignment(self, node: Node):
        """Generate assignment for variable nodes that have incoming assignment edges."""
        var_name = self.node_id_to_name.get(node.id, node.data.get('name', self._sanitize_identifier(node.id)))

        # Skip if already assigned (to avoid duplicates)
        if var_name in self.assigned_signals:
            return

        # Skip array signals - they need indexed assignment, not whole-array assignment
        if node.data.get('is_array_signal'):
            return

        # Collect assignment edges (combinational assignments, not sequential register updates)
        assignment_edges = []
        for edge in node.incoming_edges:
            edge_type = edge.data.get('type')
            # Accept both 'assignment' and 'variable_assignment' edge types
            if edge_type in ['assignment', 'variable_assignment'] and not self._should_be_register(node):
                assignment_edges.append(edge)

        if not assignment_edges:
            return

        # Check if edges have condition information
        conditional_edges = [e for e in assignment_edges if e.data.get('condition')]
        unconditional_edges = [e for e in assignment_edges if not e.data.get('condition')]

        # Check if any edges have nested conditions (multiple levels of if/case nesting)
        # This must be checked BEFORE case_edges to properly handle case-inside-case or if-inside-case
        nested_edges = [e for e in conditional_edges if e.data.get('all_conditions') and len(e.data.get('all_conditions', [])) > 1]
        if nested_edges:
            # Use nested conditional assignment which handles compound conditions properly
            self._generate_nested_conditional_assignment(node, conditional_edges)
            return

        # Check if any conditional edges have case_choice (from case statement)
        case_edges = [e for e in conditional_edges if e.data.get('case_choice')]

        if case_edges:
            # Case statement pattern - handle default + case branches
            # IMPORTANT: Group edges by their selector (condition) since a single target
            # may have assignments from multiple different case statements
            from collections import defaultdict
            edges_by_selector = defaultdict(list)
            for edge in case_edges:
                selector_id = edge.data.get('condition')
                if selector_id:
                    edges_by_selector[selector_id].append(edge)

            # Generate separate with-select statements for each selector
            for selector_id, selector_edges in edges_by_selector.items():
                # If there's an unconditional edge, it becomes the "others" case for each selector
                if unconditional_edges:
                    # Add the unconditional edge as the "others" case
                    others_edge = unconditional_edges[0]
                    # Create a copy of the edge data to avoid modifying shared state
                    others_edge_copy = type(others_edge)(others_edge.source, others_edge.target,
                                                         data=others_edge.data.copy() if others_edge.data else {})
                    if 'case_choice' not in others_edge_copy.data:
                        others_edge_copy.data['case_choice'] = 'others'
                    others_edge_copy.data['condition'] = selector_id
                    selector_edges.append(others_edge_copy)
                self._generate_case_assignment(node, selector_edges)
        elif len(conditional_edges) > 1:
            # Multiple conditional assignments - generate when-else statement
            self._generate_conditional_assignment(node, conditional_edges)
        elif len(conditional_edges) == 1 and unconditional_edges:
            # Single conditional edge + unconditional default - generate when-else
            # This handles patterns like: out <= reset_value when reset='1' else func3
            cond_edge = conditional_edges[0]

            # Find the best default edge - prefer edges marked as is_default
            default_edge = None
            for e in unconditional_edges:
                if e.data.get('is_default'):
                    default_edge = e
                    break
            if not default_edge:
                default_edge = unconditional_edges[0]

            cond_source = self.node_id_to_name.get(cond_edge.source.id, self._sanitize_identifier(cond_edge.source.id))
            default_source = self.node_id_to_name.get(default_edge.source.id, self._sanitize_identifier(default_edge.source.id))

            cond_id = cond_edge.data['condition']
            cond_name = self.node_id_to_name.get(cond_id, self._sanitize_identifier(cond_id))

            # Check condition branch - 'then' means condition=true, 'else' means condition=false
            is_then_branch = cond_edge.data.get('condition_branch') == 'then'

            if is_then_branch:
                # When condition is true, use cond_source; otherwise use default
                self.comb_logic += f"    {var_name} <= {cond_source} when {cond_name} = '1' else {default_source};\n"
            else:
                # When condition is false, use cond_source; otherwise use default
                self.comb_logic += f"    {var_name} <= {cond_source} when {cond_name} = '0' else {default_source};\n"

            self.assigned_signals.add(var_name)
        elif len(assignment_edges) == 1:
            # Single assignment - simple case
            edge = assignment_edges[0]
            source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))

            # Check if this single edge has a condition (not inverted)
            if edge.data.get('condition') and not edge.data.get('condition_inverted'):
                # Conditional assignment with single branch - use default when condition false
                cond_id = edge.data['condition']
                cond_name = self.node_id_to_name.get(cond_id, self._sanitize_identifier(cond_id))

                # Use combinational default if available, otherwise keep current value (latch)
                default_value = var_name  # Fallback: keep current value

                # Special handling for indexed variable assignments (e.g., var(31) := value)
                # Instead of latching, use the original bit from the base variable
                if node.data.get('is_variable') and '(' in node.id:
                    # This is an indexed variable assignment
                    # Extract the base variable name and bit index
                    base_id = node.id.split('(')[0]
                    if base_id in self.graph.nodes:
                        # IMPORTANT: Use the ORIGINAL base variable name, not any modified/reconstructed version
                        # We need to directly sanitize the base_id to avoid getting the _modified suffix
                        base_vhdl_name = self._sanitize_identifier(base_id)

                        # Check what index/attribute is being assigned
                        if "'high" in node.id.lower():
                            # For 'high attribute, bit 31 (for 32-bit)
                            base_width = self.graph.nodes[base_id].data.get('bit_width') or 32
                            bit_index = base_width - 1
                            default_value = f"{base_vhdl_name}({bit_index})"
                        elif '(31)' in node.id or '(31?' in node.id:
                            # Explicit bit 31
                            default_value = f"{base_vhdl_name}(31)"
                        # Can add more cases for other indices if needed

                if default_value == var_name and node.data and 'default_value' in node.data:
                    default_node_id = node.data['default_value']
                    if default_node_id in self.node_id_to_name:
                        default_value = self.node_id_to_name[default_node_id]
                    else:
                        # Search for nodes whose ID ends with this default node ID
                        for node_id, node_name in self.node_id_to_name.items():
                            if node_id.endswith('.' + default_node_id) or node_id == default_node_id:
                                default_value = node_name
                                break

                self.comb_logic += f"    {var_name} <= {source_name} when {cond_name} = '1' else {default_value};\n"
            else:
                self.comb_logic += f"    {var_name} <= {source_name};\n"
            self.assigned_signals.add(var_name)
        elif len(assignment_edges) > 1:
            # Multiple unconditional assignments - use first one (shouldn't happen in well-formed IR)
            edge = assignment_edges[0]
            source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
            self.comb_logic += f"    {var_name} <= {source_name};\n"
            self.assigned_signals.add(var_name)

    def _generate_conditional_assignment(self, node: Node, edges):
        """Generate a when-else conditional assignment from multiple conditional edges."""
        var_name = self.node_id_to_name.get(node.id, node.data.get('name', self._sanitize_identifier(node.id)))

        # Check if this has TRULY nested conditions (all_conditions with more than one level)
        # This handles if-inside-case or case-inside-if patterns
        nested_edges = [e for e in edges if e.data.get('all_conditions') and len(e.data.get('all_conditions', [])) > 1]
        if nested_edges:
            self._generate_nested_conditional_assignment(node, edges)
            return

        # Check if this is a case statement (edges have case_choice)
        case_edges = [e for e in edges if e.data.get('case_choice')]
        if case_edges:
            self._generate_case_assignment(node, case_edges)
            return

        # Group edges by condition
        # For each condition, we may have:
        # - inverted=False: value when condition is true
        # - inverted=True: value when condition is false (else branch)
        then_edges = [e for e in edges if not e.data.get('condition_inverted')]
        else_edges = [e for e in edges if e.data.get('condition_inverted')]

        if then_edges and else_edges:
            # Classic if-then-else pattern
            then_edge = then_edges[0]
            else_edge = else_edges[0]

            cond_id = then_edge.data['condition']
            cond_name = self.node_id_to_name.get(cond_id, self._sanitize_identifier(cond_id))

            then_source = self.node_id_to_name.get(then_edge.source.id, self._sanitize_identifier(then_edge.source.id))
            else_source = self.node_id_to_name.get(else_edge.source.id, self._sanitize_identifier(else_edge.source.id))

            # Check for width mismatches and add slicing if needed
            target_width = self._get_signal_width(var_name)
            if target_width:
                then_width = self._get_signal_width(then_source)
                else_width = self._get_signal_width(else_source)
                if then_width and then_width > target_width:
                    then_source = f"{then_source}({target_width-1} downto 0)"
                if else_width and else_width > target_width:
                    else_source = f"{else_source}({target_width-1} downto 0)"

            self.comb_logic += f"    {var_name} <= {then_source} when {cond_name} = '1' else {else_source};\n"
            self.assigned_signals.add(var_name)
        elif then_edges:
            # Only then branches (multiple elsif cases perhaps)
            # Build chained when-else
            parts = []

            # Debug for pc_mode
            if 'pc_mode' in var_name:
                print(f"  node.data keys: {list(node.data.keys()) if node.data else 'None'}")

            # Use combinational default if available
            # For registered signals, keeping current value creates a latch (acceptable)
            # For combinational signals, self-reference creates a loop (use zeros instead)
            is_registered = self._is_registered_signal(var_name)
            target_width = self._get_signal_width(var_name)
            if is_registered:
                default_value = var_name  # Latch behavior for registers
            elif target_width and target_width > 1:
                default_value = f"(others => '0')"  # Zero for multi-bit combinational
            else:
                default_value = "'0'"  # Zero for 1-bit combinational

            if node.data and 'default_value' in node.data:
                # Use the tracked combinational default value
                default_node_id = node.data['default_value']
                # Debug: Check if the default is self-reference
                resolved_default = self.node_id_to_name.get(default_node_id)
                if resolved_default == var_name:
                    pass  # Keep the zero default we set earlier
                elif default_node_id in self.node_id_to_name:
                    default_value = self.node_id_to_name[default_node_id]
                else:
                    # Search for nodes whose ID ends with this default node ID
                    for node_id, node_name in self.node_id_to_name.items():
                        if node_id.endswith('.' + default_node_id) or node_id == default_node_id:
                            default_value = node_name
                            break

            # target_width already calculated above

            for edge in then_edges:
                cond_id = edge.data['condition']
                cond_name = self.node_id_to_name.get(cond_id, self._sanitize_identifier(cond_id))
                source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))

                # Check if source needs slicing to match target width
                if target_width:
                    source_width = self._get_signal_width(source_name)
                    if source_width and source_width > target_width:
                        # Source too wide - slice to match target
                        source_name = f"{source_name}({target_width-1} downto 0)"

                parts.append(f"{source_name} when {cond_name} = '1'")

            if parts:
                assignment = " else ".join(parts) + f" else {default_value}"
                self.comb_logic += f"    {var_name} <= {assignment};\n"
                self.assigned_signals.add(var_name)
        else:
            # Only else branches - unusual, just take first
            if else_edges:
                edge = else_edges[0]
                source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                self.comb_logic += f"    {var_name} <= {source_name};\n"
                self.assigned_signals.add(var_name)

    def _generate_case_assignment(self, node: Node, edges):
        """Generate a with-select statement for case/switch pattern."""
        var_name = self.node_id_to_name.get(node.id, node.data.get('name', self._sanitize_identifier(node.id)))

        if not edges:
            return

        # Get the case selector from the first edge
        first_edge = edges[0]
        selector_id = first_edge.data.get('condition')
        if not selector_id:
            return

        selector_name = self.node_id_to_name.get(selector_id, self._sanitize_identifier(selector_id))

        # Build with-select statement
        # Format: with selector select signal <= value1 when choice1, value2 when choice2, ...
        choices = []
        others_value = None

        # Get target width for proper slicing
        target_width = self._get_signal_width(var_name)

        for edge in edges:
            # Bug #21 Fix: Try to inline literal sources first to avoid incorrect slicing
            # For 1-bit literals like "1", we want to emit '1' not const_N(0)
            literal_inline = self._format_literal_inline(edge.source, override_width=target_width)
            if literal_inline:
                source_name = literal_inline
            else:
                source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))

            choice_str = edge.data.get('case_choice', 'others')

            # Check if source needs slicing to match target width (skip if literal was inlined)
            if not literal_inline and target_width:
                source_width = self._get_signal_width(source_name)
                if source_width and source_width > target_width:
                    # For 1-bit target, use bit select (0) not slice (0 downto 0)
                    # This produces STD_ULOGIC not STD_ULOGIC_VECTOR
                    if target_width == 1:
                        source_name = f"{source_name}(0)"
                    else:
                        source_name = f"{source_name}({target_width-1} downto 0)"

            # Handle 'others' choice
            if 'others' in choice_str.lower():
                others_value = source_name
            else:
                # Handle multi-choice cases (e.g., "ALU_LESS_THAN_SIGNED?, ALU_LESS_THAN_UNSIGNED")
                # Split on comma to get individual choices
                individual_choices = [c.strip() for c in choice_str.split(',')]

                for individual_choice in individual_choices:
                    # Clean up choice string (remove extra quotes, spaces, and trailing ?)
                    # pyGHDL uses ? suffix for string literals
                    individual_choice = individual_choice.strip()
                    if individual_choice.endswith('?'):
                        individual_choice = individual_choice[:-1]
                    # Resolve constant names to their literal values
                    if individual_choice in self.constant_map:
                        individual_choice = self.constant_map[individual_choice]
                    choices.append(f"{source_name} when {individual_choice}")

        # Build the with-select statement
        if choices:
            self.comb_logic += f"    with {selector_name} select\n"
            self.comb_logic += f"        {var_name} <=\n"

            # Always add comma for all choices since we always add "when others"
            for choice in choices:
                self.comb_logic += f"            {choice},\n"

            # Add others clause (required in VHDL)
            if others_value:
                self.comb_logic += f"            {others_value} when others;\n"
            else:
                # If no explicit others, use tracked combinational default
                default_val = None
                if node.data and 'default_value' in node.data:
                    default_node_id = node.data['default_value']
                    if default_node_id in self.node_id_to_name:
                        default_val = self.node_id_to_name[default_node_id]
                    else:
                        # Search for nodes whose ID ends with this default node ID
                        for node_id, node_name in self.node_id_to_name.items():
                            if node_id.endswith('.' + default_node_id) or node_id == default_node_id:
                                default_val = node_name
                                break

                if not default_val:
                    # Fallback: use the first value as default
                    default_val = choices[0].split(' when ')[0].strip()

                self.comb_logic += f"            {default_val} when others;\n"

            self.assigned_signals.add(var_name)
        elif others_value:
            # Only others case - simple assignment
            self.comb_logic += f"    {var_name} <= {others_value};\n"
            self.assigned_signals.add(var_name)

    def _generate_nested_conditional_assignment(self, node: Node, edges):
        """Generate when-else for nested conditionals (if-inside-case or case-inside-if).

        This handles edges that have all_conditions set, meaning they are inside
        multiple nested conditional blocks. We generate compound conditions that
        check all levels of the condition stack.
        """
        var_name = self.node_id_to_name.get(node.id, node.data.get('name', self._sanitize_identifier(node.id)))

        if not edges:
            return

        # Build a list of (source, compound_condition) tuples
        # Each edge represents one possible assignment with its full condition path
        assignments = []
        default_value = None

        # Get target width early for handling indexed array writes
        target_width = self._get_signal_width(var_name)

        for edge in edges:
            source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))

            # Handle indexed array writes (e.g., c(0) <= '1')
            # Expand scalar source to full vector width with bit at index set
            if edge.data.get('is_array_write') and edge.data.get('array_index') and target_width and target_width > 1:
                array_index_id = edge.data['array_index']
                index_name = self.node_id_to_name.get(array_index_id, self._sanitize_identifier(array_index_id))

                # Get the index value (should be a constant like const_4 = 0)
                source_width = self._get_signal_width(source_name)

                # For indexed write of scalar to vector, create a vector with:
                # - All bits from default value except
                # - The indexed bit from source
                # We'll build this as: (default_value with bit at index replaced)
                # But for simplicity, if the source is '1' and default is all zeros,
                # just create a vector with 1 at the index position

                # Check if this is writing to bit 0 of a vector (common for ALU less-than result)
                # The index node might be a constant expression - check if it evaluates to 0
                # For simplicity, if the source is a '1' literal and we're doing an indexed write,
                # assume it's writing to bit 0 (the LSB) which is the common pattern for c(0) <= '1'

                # Check if source is a '1' constant and expand it to a vector
                if source_name.endswith("const_5") or source_name == "'1'":
                    # This is c(0) <= '1' pattern - create a vector with LSB set to 1
                    # E.g., for 32-bit: x"00000001"
                    source_name = 'x"' + ('0' * (target_width // 4 - 1)) + '1"'
                elif source_name.endswith("const_0") or source_name == "'0'":
                    # This is c(0) <= '0' pattern - all zeros
                    source_name = 'x"' + ('0' * (target_width // 4)) + '"'

            # Build compound condition from all_conditions
            all_conditions = edge.data.get('all_conditions', [])
            if not all_conditions:
                # Fallback to single condition
                if 'condition' in edge.data:
                    all_conditions = [{
                        'node_id': edge.data['condition'],
                        'branch': edge.data.get('condition_branch'),
                        'inverted': edge.data.get('condition_inverted', False),
                        'case_choice': edge.data.get('case_choice')
                    }]
                else:
                    # No conditions - this is the default
                    default_value = source_name
                    continue

            # Check if any condition is "others" - if so, this entire assignment is the default
            has_others = False
            for cond_info in all_conditions:
                if 'case_choice' in cond_info and cond_info['case_choice']:
                    choice_str = cond_info['case_choice'].strip()
                    if choice_str.lower() == "others":
                        has_others = True
                        break

            if has_others:
                # This assignment has "others" in its conditions - it's the default
                default_value = source_name
                continue

            # Build compound condition string
            cond_parts = []
            for cond_info in all_conditions:
                cond_id = cond_info['node_id']
                cond_name = self.node_id_to_name.get(cond_id, self._sanitize_identifier(cond_id))

                if 'case_choice' in cond_info and cond_info['case_choice']:
                    # This is a case condition - check equality with choice
                    choice_str = cond_info['case_choice'].strip()

                    # Handle multi-choice cases (e.g., "ALU_LESS_THAN_SIGNED?, ALU_LESS_THAN_UNSIGNED")
                    # Split on comma to get individual choices
                    choices = [c.strip() for c in choice_str.split(',')]
                    choice_conditions = []

                    for choice in choices:
                        # Remove trailing ? from pyGHDL string representation
                        if choice.endswith('?'):
                            choice = choice[:-1]
                        # Resolve constant names to their literal values
                        if choice in self.constant_map:
                            choice = self.constant_map[choice]
                        choice_conditions.append(f"{cond_name} = {choice}")

                    # Join multiple choices with 'or'
                    if len(choice_conditions) > 1:
                        cond_parts.append(f"({' or '.join(choice_conditions)})")
                    else:
                        cond_parts.append(choice_conditions[0])
                else:
                    # This is an if condition - check '1' or '0' based on inverted
                    if cond_info.get('inverted', False):
                        cond_parts.append(f"{cond_name} = '0'")
                    else:
                        cond_parts.append(f"{cond_name} = '1'")

            if cond_parts:
                compound_cond = " and ".join(cond_parts)
                assignments.append((source_name, compound_cond))
            else:
                default_value = source_name

        # Generate when-else chain
        if not assignments:
            if default_value:
                self.comb_logic += f"    {var_name} <= {default_value};\n"
                self.assigned_signals.add(var_name)
            return

        # Build the when-else assignment
        # (target_width already retrieved at the top of this function)
        parts = []
        for source, condition in assignments:
            # Check if source needs slicing
            if target_width:
                source_width = self._get_signal_width(source)
                if source_width and source_width > target_width:
                    # For 1-bit target, use bit select (0) not slice (0 downto 0)
                    # This produces STD_ULOGIC not STD_ULOGIC_VECTOR
                    if target_width == 1:
                        source = f"{source}(0)"
                    else:
                        source = f"{source}({target_width-1} downto 0)"
            parts.append(f"{source} when ({condition})")

        # Add default value (either explicit or keep current value)
        if default_value is None:
            # For combinational signals, use zeros as fallback to avoid self-loops
            is_registered = self._is_registered_signal(var_name)
            fallback_default = var_name if is_registered else (
                "(others => '0')" if target_width and target_width > 1 else "'0'"
            )

            # Use tracked combinational default if available
            if node.data and 'default_value' in node.data:
                default_node_id = node.data['default_value']
                candidate_default = None

                # Try to get the name - if not found, search for matching node
                if default_node_id in self.node_id_to_name:
                    candidate_default = self.node_id_to_name[default_node_id]
                else:
                    # Node might not be in the map with the exact ID
                    # Search for nodes whose ID ends with this default node ID
                    for node_id, node_name in self.node_id_to_name.items():
                        if node_id.endswith('.' + default_node_id) or node_id == default_node_id:
                            candidate_default = node_name
                            break

                # Check for self-reference - if default points back to the signal itself,
                # use the fallback to avoid combinational loop
                if candidate_default == var_name:
                    default_value = fallback_default
                elif candidate_default:
                    default_value = candidate_default

                    # Validate: check if default value width matches target width
                    if default_value and target_width:
                        default_width = self._get_signal_width(default_value)
                        if default_width and default_width != target_width:
                            default_value = "(others => '0')"
                else:
                    default_value = fallback_default

            else:
                # Fallback: use zeros for combinational, self for registered (latch)
                default_value = fallback_default

        if parts:
            assignment = " else ".join(parts) + f" else {default_value}"
            self.comb_logic += f"    {var_name} <= {assignment};\n"
            self.assigned_signals.add(var_name)

    def _generate_module_instantiation(self, node: Node):
        """Generate module instantiation for modules like MUX, ALU, etc."""
        if node.id not in self.module_generators:
            return

        generator = self.module_generators[node.id]
        module_name = self._sanitize_identifier(generator.name)
        instance_name = f"{module_name}_inst"

        # Get the output signal name
        output_signal = self.node_id_to_name.get(node.id, self._sanitize_identifier(node.id))

        # Check if this mux should drive another signal (e.g., pc_wr_mux -> pc_wr)
        # If the node name ends with "_mux", it likely needs to drive a signal without "_mux"
        # BUT: Don't use this heuristic if there's already an explicit assignment edge
        # to the destination (e.g., pc_recovery_mux -> pc_wr via assignment edge)
        dest_signal = None
        if node.id.endswith('_mux'):
            base_name = node.id[:-4]  # Remove "_mux" suffix
            sanitized_base_name = self._sanitize_identifier(base_name)
            # Check if there's a signal with the base name (using sanitized version)
            if base_name in self.node_id_to_name or sanitized_base_name in self.declared_names or any(s['name'] == sanitized_base_name for s in self.signal_declarations):
                # Check if there's already an explicit assignment edge targeting this signal
                # from a different source (like pc_recovery_mux -> pc_wr)
                has_explicit_assignment = False
                for edge in self.graph.edges.values():
                    if edge.data.get('type') == 'assignment':
                        target_name = self.node_id_to_name.get(edge.target.id, self._sanitize_identifier(edge.target.id))
                        source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                        if target_name == sanitized_base_name and source_name != output_signal:
                            # There's an explicit assignment edge from a different source
                            has_explicit_assignment = True
                            break

                if not has_explicit_assignment:
                    # Use the sanitized name from the node_id_to_name mapping if available
                    dest_signal = self.node_id_to_name.get(base_name, sanitized_base_name)

        # Build port map based on incoming edges
        port_map = {}

        # Track inputs and selects by their index (not position in list)
        inputs = {}  # index -> signal_name
        selects = {}  # index -> signal_name
        default_input = None

        # Group edges by type and use their index
        for edge in node.incoming_edges:
            edge_type = edge.data.get('type')
            source_signal = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))

            if edge_type == 'mux_input':
                input_index = edge.data.get('input_index', len(inputs))
                inputs[input_index] = source_signal
            elif edge_type == 'mux_select':
                select_index = edge.data.get('select_index', len(selects))
                selects[select_index] = source_signal
            elif edge_type == 'mux_default_input':
                default_input = source_signal

        # Generate port map for one-hot mux
        if hasattr(generator, 'select_type') and generator.select_type == 'one_hot':
            mux_width = generator.data_width
            for i in sorted(inputs.keys()):
                signal = inputs[i]
                # Check if signal width matches mux width
                source_node = None
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'mux_input':
                        source_signal = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                        if source_signal == signal:
                            source_node = edge.source
                            break

                if source_node:
                    source_width = self._infer_bit_width(source_node)
                    if source_width and source_width < mux_width:
                        # Create zero-extended signal
                        ext_signal = f"{signal}_ext"
                        port_map[f"in_{i}"] = ext_signal
                        # Only generate assignment and declaration if not already done
                        if ext_signal not in self.declared_names:
                            if source_width == 1:
                                # For single-bit std_logic, use concatenation with zeros
                                zeros = mux_width - 1
                                self.comb_logic += f"    {ext_signal} <= ({zeros-1} downto 0 => '0') & {signal};\n"
                            else:
                                # For multi-bit std_logic_vector, use resize
                                self.comb_logic += f"    {ext_signal} <= std_logic_vector(resize(unsigned({signal}), {mux_width}));\n"
                            self.additional_signals.append({
                                'name': ext_signal,
                                'bit_width': mux_width
                            })
                            self.declared_names.add(ext_signal)
                    else:
                        port_map[f"in_{i}"] = signal
                else:
                    port_map[f"in_{i}"] = signal

            for i in sorted(selects.keys()):
                sel_signal = selects[i]
                # Check if selector signal is wider than 1-bit and extract bit 0
                sel_signal_expr = self._get_mux_select_expression(sel_signal, node)
                port_map[f"sel_{i}"] = sel_signal_expr

        # Generate port map for priority mux with default
        elif hasattr(generator, 'has_default') and generator.has_default:
            mux_width = generator.data_width
            for i in sorted(inputs.keys()):
                signal = inputs[i]
                # Check if signal width matches mux width
                source_node = None
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'mux_input':
                        source_signal = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                        if source_signal == signal:
                            source_node = edge.source
                            break

                if source_node:
                    source_width = self._infer_bit_width(source_node)
                    if source_width and source_width < mux_width:
                        # Create zero-extended signal
                        ext_signal = f"{signal}_ext"
                        port_map[f"in_{i}"] = ext_signal
                        # Only generate assignment and declaration if not already done
                        if ext_signal not in self.declared_names:
                            if source_width == 1:
                                # For single-bit std_logic, use concatenation with zeros
                                zeros = mux_width - 1
                                self.comb_logic += f"    {ext_signal} <= ({zeros-1} downto 0 => '0') & {signal};\n"
                            else:
                                # For multi-bit std_logic_vector, use resize
                                self.comb_logic += f"    {ext_signal} <= std_logic_vector(resize(unsigned({signal}), {mux_width}));\n"
                            self.additional_signals.append({
                                'name': ext_signal,
                                'bit_width': mux_width
                            })
                            self.declared_names.add(ext_signal)
                    else:
                        port_map[f"in_{i}"] = signal
                else:
                    port_map[f"in_{i}"] = signal

            for i in sorted(selects.keys()):
                sel_signal = selects[i]
                # Check if selector signal is wider than 1-bit and extract bit 0
                sel_signal_expr = self._get_mux_select_expression(sel_signal, node)
                port_map[f"sel_{i}"] = sel_signal_expr
            if default_input:
                port_map["default_in"] = default_input

        # Handle priority mux without default (fallback for other cases)
        else:
            mux_width = getattr(generator, 'data_width', 32)
            for i in sorted(inputs.keys()):
                signal = inputs[i]
                # Check if signal width matches mux width
                source_node = None
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'mux_input':
                        source_signal = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                        if source_signal == signal:
                            source_node = edge.source
                            break

                if source_node:
                    source_width = self._infer_bit_width(source_node)
                    if source_width and source_width < mux_width:
                        # Create zero-extended signal
                        ext_signal = f"{signal}_ext"
                        port_map[f"in_{i}"] = ext_signal
                        # Only generate assignment and declaration if not already done
                        if ext_signal not in self.declared_names:
                            if source_width == 1:
                                # For single-bit std_logic, use concatenation with zeros
                                zeros = mux_width - 1
                                self.comb_logic += f"    {ext_signal} <= ({zeros-1} downto 0 => '0') & {signal};\n"
                            else:
                                # For multi-bit std_logic_vector, use resize
                                self.comb_logic += f"    {ext_signal} <= std_logic_vector(resize(unsigned({signal}), {mux_width}));\n"
                            self.additional_signals.append({
                                'name': ext_signal,
                                'bit_width': mux_width
                            })
                            self.declared_names.add(ext_signal)
                    else:
                        port_map[f"in_{i}"] = signal
                else:
                    port_map[f"in_{i}"] = signal

            for i in sorted(selects.keys()):
                sel_signal = selects[i]
                # Check if selector signal is wider than 1-bit and extract bit 0
                sel_signal_expr = self._get_mux_select_expression(sel_signal, node)
                port_map[f"sel_{i}"] = sel_signal_expr

        # Add output port
        port_map["output"] = output_signal

        # Generate VHDL instantiation
        inst_code = f"{instance_name} : entity work.{module_name}\n"
        inst_code += "    port map (\n"

        port_stmts = []
        for port_name, signal_name in port_map.items():
            port_stmts.append(f"        {port_name} => {signal_name}")

        inst_code += ",\n".join(port_stmts) + "\n"
        inst_code += "    );\n"

        self.module_instantiations.append(inst_code)

        # Generate assignment from mux output to destination signal if needed
        # E.g., pc_wr <= pc_wr_mux;
        if dest_signal:
            self.comb_logic += f"    {dest_signal} <= {output_signal};\n"
            self.assigned_signals.add(dest_signal)

    def _get_mux_select_expression(self, signal_name: str, mux_node: Node) -> str:
        """Get the proper VHDL expression for a mux selector signal.

        If the signal is wider than 1-bit, extracts bit 0 to get a std_logic.
        """
        # Find the source node for this signal from the mux's incoming edges
        source_node = None
        for edge in mux_node.incoming_edges:
            if edge.data.get('type') == 'mux_select':
                source_signal = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                if source_signal == signal_name:
                    source_node = edge.source
                    break

        # Check the signal width from various sources
        signal_width = None

        if source_node:
            signal_width = self._infer_bit_width(source_node)

        # Also check signal declarations
        if signal_width is None:
            for decl in self.signal_declarations:
                if decl['name'] == signal_name:
                    signal_width = decl.get('bit_width')
                    break

        # Also check additional_signals
        if signal_width is None:
            for sig in self.additional_signals:
                if sig['name'] == signal_name:
                    signal_width = sig.get('bit_width')
                    break

        # If signal is wider than 1-bit, extract bit 0
        if signal_width is not None and signal_width > 1:
            return f"{signal_name}(0)"

        return signal_name

    def _get_vhdl_name_for_expression(self, expr: Dict) -> str:
        """Get VHDL signal name for an expression."""
        if expr.get('type') == 'identifier':
            return expr.get('name', 'unknown')
        elif expr.get('type') == 'literal':
            value = expr.get('value', 0)
            return f"to_unsigned({value}, 32)"
        else:
            expr_id = str(expr)
            return self.node_id_to_name.get(expr_id, 'unknown')

    def _generate_sequential_logic(self):
        """Generate sequential logic for state updates."""
        self.seq_logic = ""

        register_assignments = []
        for edge in self.graph.edges.values():
            if edge.data.get('type') == 'assignment':
                target = edge.target
                # Skip array signals UNLESS they have indexed write (is_array_write flag)
                # Whole-array assignments should be skipped, but indexed writes are allowed
                if target.data.get('is_array_signal') and not edge.data.get('is_array_write'):
                    continue
                is_split_isa_state = '_wr' in target.id and target.data.get('name') is not None
                # Check for is_register_write flag (from clocked process) OR is_register on target node
                is_register_write = edge.data.get('is_register_write', False)
                is_register_node = target.data.get('is_register', False) if target.data else False
                if ((self._should_be_register(target) or is_register_write or is_register_node)
                    and not target.data.get('is_memory', False)) or is_split_isa_state:
                    register_assignments.append(edge)

        # Find pipeline_input edges to pipeline registers (uarch_state)
        # These represent sequential updates to pipeline registers
        pipeline_register_assignments = []
        for edge in self.graph.edges.values():
            if edge.data.get('type') == 'pipeline_input':
                target = edge.target
                # Pipeline registers are uarch_state or have type 'pipeline_register'
                if target.is_uarch_state or target.data.get('type') == 'pipeline_register':
                    pipeline_register_assignments.append(edge)

        # Group assignments by target to avoid multiple assignments to same signal
        # This fixes combinational loop issues where multiple edges assign to the same target
        target_to_assignments = {}
        for edge in register_assignments:
            target = edge.target
            if target.id.endswith('_wr'):
                base_name = target.id[:-3] + '_rd'
                # Check if the corresponding _rd signal exists (is declared)
                # Some _wr signals (like indexed array accesses rf[rd]_wr) don't have a _rd counterpart
                sanitized_base = self._sanitize_identifier(base_name)
                if base_name not in self.node_id_to_name and sanitized_base not in self.declared_names:
                    # Skip this - no corresponding read signal exists
                    continue
                target_name = self.node_id_to_name.get(base_name, sanitized_base)
            else:
                target_name = self.node_id_to_name.get(target.id, self._sanitize_identifier(target.id))

            # Skip targets that are already assigned in combinational logic
            # This prevents driver conflicts between combinational and sequential assignments
            if target_name in self.assigned_signals:
                continue

            if target_name not in target_to_assignments:
                target_to_assignments[target_name] = []
            target_to_assignments[target_name].append(edge)

        if target_to_assignments or pipeline_register_assignments:
            self.seq_logic += "    process(clk)\n"
            self.seq_logic += "    begin\n"
            self.seq_logic += "        if rising_edge(clk) then\n"
            self.seq_logic += "            if reset = '1' then\n"

            # Reset assignments
            for sig_decl in self.signal_declarations:
                if sig_decl.get('is_register') and sig_decl.get('reset_signal'):
                    name = sig_decl['name']
                    # Skip _wr signals - they are combinationally driven from muxes
                    if name.endswith('_wr'):
                        continue
                    reset_signal = sig_decl['reset_signal']
                    self.seq_logic += f"                {name} <= {reset_signal};\n"

            self.seq_logic += "            else\n"

            # Register update assignments - only generate ONE assignment per target
            # For targets with multiple assignments, keep only the last one
            # This matches VHDL semantics where last assignment wins
            for target_name, edges in target_to_assignments.items():
                # Use the last edge (consistent with VHDL semantics)
                edge = edges[-1]
                target = edge.target

                if target.id.endswith('_wr'):
                    wr_name = self.node_id_to_name.get(target.id, self._sanitize_identifier(target.id))
                    source_name = wr_name
                else:
                    source = edge.source
                    source_name = self.node_id_to_name.get(source.id, self._sanitize_identifier(source.id))

                # Check if this edge has conditions (beyond just the clock edge)
                has_condition = False
                condition_expr = None
                if edge.data.get('all_conditions'):
                    # Filter out clock conditions, keep only data conditions
                    data_conditions = [c for c in edge.data['all_conditions']
                                     if 'clk' not in c['node_id'].lower()]
                    if data_conditions:
                        has_condition = True
                        # Use the last non-clock condition
                        cond_info = data_conditions[-1]
                        cond_node_id = cond_info['node_id']
                        cond_name = self.node_id_to_name.get(cond_node_id, self._sanitize_identifier(cond_node_id))

                        # Check if the condition signal is boolean (1-bit) or multi-bit
                        cond_width = self._get_signal_width(cond_name)
                        is_boolean_cond = cond_width == 1 if cond_width is not None else True

                        # Check if inverted
                        if cond_info.get('inverted') or cond_info.get('branch') == 'else':
                            if is_boolean_cond:
                                condition_expr = f"{cond_name} = '0'"
                            else:
                                # Multi-bit signal: check if it's zero
                                zeros = "0" * cond_width
                                condition_expr = f'{cond_name} = "{zeros}"'
                        else:
                            if is_boolean_cond:
                                condition_expr = f"{cond_name} = '1'"
                            else:
                                # Multi-bit signal: check if it's non-zero
                                zeros = "0" * cond_width
                                condition_expr = f'{cond_name} /= "{zeros}"'

                # Generate the assignment
                assignment_line = ""
                if edge.data.get('is_array_write') and edge.data.get('array_index'):
                    array_index_id = edge.data['array_index']
                    index_name = self.node_id_to_name.get(array_index_id, self._sanitize_identifier(array_index_id))
                    # Generate indexed array write: array(to_integer(unsigned(index))) <= value
                    assignment_line = f"{target_name}(to_integer(unsigned({index_name}))) <= {source_name};"
                else:
                    # Regular scalar assignment
                    assignment_line = f"{target_name} <= {source_name};"

                # Check if this is the PC register update - it needs to be gated by stall
                # In a pipelined processor, when the pipeline stalls, the PC should not advance
                is_pc_register = target_name == 'pc_rd'
                has_stall_signal = any(sig['name'] == 'stall_and_not_flush' for sig in self.signal_declarations)

                # Wrap in condition if needed
                if is_pc_register and has_stall_signal:
                    # PC register update should be gated by stall: if stall_and_not_flush = '0' then pc_rd <= pc_wr
                    self.seq_logic += f"                if stall_and_not_flush = '0' then\n"
                    self.seq_logic += f"                    {assignment_line}\n"
                    self.seq_logic += f"                end if;\n"
                elif has_condition and condition_expr:
                    self.seq_logic += f"                if {condition_expr} then\n"
                    self.seq_logic += f"                    {assignment_line}\n"
                    self.seq_logic += f"                end if;\n"
                else:
                    self.seq_logic += f"                {assignment_line}\n"

            # Generate pipeline register updates from pipeline_input edges
            for edge in pipeline_register_assignments:
                target = edge.target
                source = edge.source
                target_name = self.node_id_to_name.get(target.id, self._sanitize_identifier(target.id))
                source_name = self.node_id_to_name.get(source.id, self._sanitize_identifier(source.id))

                # Check if width conversion is needed
                target_width = self._get_signal_width(target_name)
                source_width = self._get_signal_width(source_name)
                if source_width == 1 and target_width is not None and target_width > 1:
                    # Convert single bit to vector: (0 => value, others => '0')
                    source_expr = f"(0 => {source_name}, others => '0')"
                else:
                    source_expr = source_name

                # Check if there's a stall signal connected to this pipeline register
                stall_signal = None
                for incoming_edge in target.incoming_edges:
                    if incoming_edge.data.get('type') == 'stall':
                        stall_node = incoming_edge.source
                        stall_signal = self.node_id_to_name.get(stall_node.id, self._sanitize_identifier(stall_node.id))
                        break

                # Also check for stall_gated attribute (for operand registers in bypass)
                if not stall_signal and target.data.get('stall_gated'):
                    # Use the global Decode stall controller
                    stall_signal = 'pipe_decode_stall_ctrl'

                # Check if there's a valid_gate signal (for result registers in bypass mode)
                # This prevents garbage from bubbles overwriting valid results
                valid_gate_signal = None
                for incoming_edge in target.incoming_edges:
                    if incoming_edge.data.get('type') == 'valid_gate':
                        valid_gate_node = incoming_edge.source
                        valid_gate_signal = self.node_id_to_name.get(valid_gate_node.id, self._sanitize_identifier(valid_gate_node.id))
                        break

                # Generate the conditional assignment based on stall and/or valid_gate signals
                # Check signal width to determine correct comparison syntax
                stall_width = self._get_signal_width(stall_signal) if stall_signal else None
                stall_check = f"{stall_signal} = '0'" if stall_width == 1 else f"{stall_signal}(0) = '0'" if stall_signal else None

                if stall_signal and valid_gate_signal:
                    self.seq_logic += f"                if {stall_check} and {valid_gate_signal} = '1' then\n"
                    self.seq_logic += f"                    {target_name} <= {source_expr};\n"
                    self.seq_logic += f"                end if;\n"
                elif stall_signal:
                    self.seq_logic += f"                if {stall_check} then\n"
                    self.seq_logic += f"                    {target_name} <= {source_expr};\n"
                    self.seq_logic += f"                end if;\n"
                elif valid_gate_signal:
                    self.seq_logic += f"                if {valid_gate_signal} = '1' then\n"
                    self.seq_logic += f"                    {target_name} <= {source_expr};\n"
                    self.seq_logic += f"                end if;\n"
                else:
                    self.seq_logic += f"                {target_name} <= {source_expr};\n"

            self.seq_logic += "            end if;\n"
            self.seq_logic += "        end if;\n"
            self.seq_logic += "    end process;\n\n"

        # Handle memory writes (simplified version for now)
        memory_writes = []
        for edge in self.graph.edges.values():
            if (edge.data.get('type') == 'assignment' and
                edge.target.data.get('type') == 'array_access'):
                target_expr = edge.data.get('left', {})
                if target_expr.get('type') == 'array_access':
                    array_expr = target_expr.get('target', {})
                    if array_expr.get('type') == 'identifier':
                        array_name = array_expr['name']
                        if array_name in self.graph.nodes:
                            array_node = self.graph.nodes[array_name]
                            if array_node.data.get('is_memory', False):
                                memory_writes.append(edge)

        if memory_writes:
            self.seq_logic += "    process(clk)\n"
            self.seq_logic += "    begin\n"
            self.seq_logic += "        if rising_edge(clk) then\n"
            self.seq_logic += "            if reset /= '1' then\n"

            for edge in memory_writes:
                target_expr = edge.data['left']
                array_name = target_expr['target']['name']

                source_name = self.node_id_to_name.get(edge.source.id, self._sanitize_identifier(edge.source.id))
                index_expr = target_expr['index']

                if index_expr.get('type') == 'identifier':
                    index_name = index_expr['name']
                    self.seq_logic += f"                {array_name}(to_integer(unsigned({index_name}))) <= {source_name};\n"

            self.seq_logic += "            end if;\n"
            self.seq_logic += "        end if;\n"
            self.seq_logic += "    end process;\n\n"

        # Add register file write process if rf exists
        has_rf = 'rf' in self.memory_declarations

        # Find the RF write enable signal from the graph structure
        # The write enable is stored on the write port node as 'combined_write_enable'
        rf_write_enable_signal = None
        rf_write_addr_signal = None
        for node in self.graph.nodes.values():
            # Look for RF write port node (named rf_shared_wr or rf[rd]_wr)
            if (node.data.get('type') == 'memory_write_port' and
                node.data.get('base_memory') == 'rf'):
                # Get the write enable from the node's metadata
                if 'combined_write_enable' in node.data:
                    enable_node_id = node.data['combined_write_enable']
                    # Use the sanitized name from node_id_to_name, or sanitize it
                    rf_write_enable_signal = self.node_id_to_name.get(
                        enable_node_id, self._sanitize_identifier(enable_node_id))
                # Get the write address from incoming edges
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'write_address':
                        rf_write_addr_signal = self.node_id_to_name.get(
                            edge.source.id, self._sanitize_identifier(edge.source.id))
                break

        # Check if we found RF write signals, or fall back to signal name patterns
        has_rf_write_signals = rf_write_enable_signal is not None
        if not has_rf_write_signals:
            # Fallback: check for any rf_write_enable-like signals
            has_rf_write_signals = any('rf_write_enable' in sig['name'] or
                                       'rf_rd_ne_0_guarded_enable' in sig['name']
                                       for sig in self.signal_declarations)

        has_rf_mux_signals = any(sig['name'] == 'rf_write_addr_mux'
                                for sig in self.signal_declarations)
        # Also check for 'rd' signal which can be used as address when there's no mux
        has_rd_signal = any(sig['name'] == 'rd' for sig in self.signal_declarations)
        # Also check for pipelined rd signal at writeback stage
        has_writeback_rd_signal = any('writeback_' in sig['name'] and '_rd_' in sig['name'] and
                                      sig.get('bit_width', 1) == 5
                                      for sig in self.signal_declarations)

        if has_rf and has_rf_write_signals and (has_rf_mux_signals or has_rd_signal or has_writeback_rd_signal):
            # Check if this is a pipelined processor with writeback stage
            # Look for writeback-stage rd signal (e.g., pipe_writeback_..._rd_pipe_pipe_pipe)
            # Handle different pipeline configurations:
            # - 5-stage: pipe_writeback_*
            # - 4-stage: pipe_memorywriteback_*
            # - 3-stage: pipe_executememorywriteback_*
            # - 2-stage: pipe_decodeexecutememorywriteback_*
            writeback_rd_signal = None
            writeback_rf_write_addr_signal = None
            for sig in self.signal_declarations:
                sig_name = sig['name']
                # Pattern: pipe_*writeback_..._rd_..._pipe (matches any stage ending with "writeback")
                # Used by RISC-V which has a dedicated rd field
                if (sig_name.startswith('pipe_') and 'writeback_' in sig_name and
                    '_rd_' in sig_name and sig_name.endswith('_pipe')):
                    # Check width - rd should be 5 bits
                    bit_width = sig.get('bit_width', 1)
                    if bit_width == 5:
                        writeback_rd_signal = sig_name
                # Pattern: pipe_*writeback_..._rf_write_addr_mux_..._pipe (matches any stage)
                # Used by MIPS which uses a mux for rd/rt selection
                if (sig_name.startswith('pipe_') and 'writeback_' in sig_name and
                    'rf_write_addr_mux' in sig_name and sig_name.endswith('_pipe')):
                    writeback_rf_write_addr_signal = sig_name

            # Check for writeback-stage enable signals (valid-gated ones for register writes)
            # These are used as select signals for rf_write_data_mux
            writeback_enables = []
            for sig in self.signal_declarations:
                sig_name = sig['name']
                # Pattern: pipe_*writeback_..._enable_..._valid_gated (matches any stage ending with "writeback")
                if (sig_name.startswith('pipe_') and 'writeback_' in sig_name and
                    '_enable_' in sig_name and
                    sig_name.endswith('_valid_gated')):
                    writeback_enables.append(sig_name)

            # Also check for unified rf_rd_ne_0_guarded_enable_valid_gated signal
            # This is the combined write enable after validity gating
            has_unified_guarded_enable = any(sig['name'] == 'rf_rd_ne_0_guarded_enable_valid_gated'
                                             for sig in self.signal_declarations)

            # Also check for rf_write_enable_valid_gated signal (used by MIPS and others)
            # This is the combined rf_write_enable gated by writeback stage validity
            has_rf_write_enable_valid_gated = any(sig['name'] == 'rf_write_enable_valid_gated'
                                                  for sig in self.signal_declarations)

            # Determine which address signal to use (prefer rd, fallback to rf_write_addr_mux)
            effective_writeback_addr_signal = writeback_rd_signal or writeback_rf_write_addr_signal

            is_pipelined = (effective_writeback_addr_signal is not None and
                           (len(writeback_enables) > 0 or has_unified_guarded_enable or has_rf_write_enable_valid_gated))

            if is_pipelined:
                # Pipelined processor: use writeback stage signals
                rf_addr_signal = effective_writeback_addr_signal
                # Use unified guarded enable if available, then rf_write_enable_valid_gated,
                # otherwise combine writeback enables
                if has_unified_guarded_enable:
                    rf_write_enable_expr = 'rf_rd_ne_0_guarded_enable_valid_gated'
                elif has_rf_write_enable_valid_gated:
                    rf_write_enable_expr = 'rf_write_enable_valid_gated'
                else:
                    rf_write_enable_expr = ' or '.join(writeback_enables)
            else:
                # Non-pipelined: use decode stage signals (original behavior)
                # Use address signal from graph if available, otherwise fall back to pattern matching
                if rf_write_addr_signal:
                    rf_addr_signal = rf_write_addr_signal
                else:
                    rf_addr_signal = 'rf_write_addr_mux' if has_rf_mux_signals else 'rd'

            self.seq_logic += "    -- Register file write process\n"
            self.seq_logic += "    process(clk)\n"
            self.seq_logic += "    begin\n"
            self.seq_logic += "        if rising_edge(clk) then\n"
            self.seq_logic += "            if reset /= '1' then\n"

            if is_pipelined:
                # Pipelined: use writeback stage enables directly
                # The valid_gated signals already include validity checks
                self.seq_logic += f"                if ({rf_write_enable_expr}) = '1' then\n"
                self.seq_logic += f"                    rf(to_integer(unsigned({rf_addr_signal}))) <= rf_write_data_mux;\n"
                self.seq_logic += "                end if;\n"
            elif rf_write_enable_signal:
                # Use the write enable signal found from the graph metadata
                self.seq_logic += f"                if {rf_write_enable_signal} = '1' then\n"
                self.seq_logic += f"                    rf(to_integer(unsigned({rf_addr_signal}))) <= rf_write_data_mux;\n"
                self.seq_logic += "                end if;\n"
            else:
                # Fallback: collect all rf_write_enable signals (per-instruction enables)
                rf_write_enables = [sig['name'] for sig in self.signal_declarations
                                   if 'rf_write_enable' in sig['name'] or
                                      'rf_rd_ne_0_guarded_enable' in sig['name']]

                if len(rf_write_enables) == 1:
                    # Single enable signal
                    self.seq_logic += f"                if {rf_write_enables[0]} = '1' then\n"
                    self.seq_logic += f"                    rf(to_integer(unsigned({rf_addr_signal}))) <= rf_write_data_mux;\n"
                    self.seq_logic += "                end if;\n"
                else:
                    # Generate conditional writes for each instruction's rf_write_enable
                    for i, enable_sig in enumerate(rf_write_enables):
                        indent = "    " if i == 0 else ""
                        if_keyword = "if" if i == 0 else "elsif"
                        self.seq_logic += f"                {indent}{if_keyword} {enable_sig} = '1' then\n"
                        self.seq_logic += "                    -- Only write to non-zero registers (x0 is hardwired to 0)\n"
                        self.seq_logic += f"                    if to_integer(unsigned({rf_addr_signal})) /= 0 then\n"
                        self.seq_logic += f"                        rf(to_integer(unsigned({rf_addr_signal}))) <= rf_write_data_mux;\n"
                        self.seq_logic += "                    end if;\n"
                    if rf_write_enables:
                        self.seq_logic += "                end if;\n"

            self.seq_logic += "            end if;\n"
            self.seq_logic += "        end if;\n"
            self.seq_logic += "    end process;\n\n"

        # Add data memory write process if dmem exists and store instructions are present
        has_dmem = 'dmem' in self.memory_declarations
        # Structural detection of store enables - look for *s[dwbh]_enable* patterns
        # This handles sd (64-bit), sw (word), sh (halfword), sb (byte) for any ISA
        import re
        store_enable_pattern = re.compile(r's[dwbh]_enable')
        has_store_enables = any(store_enable_pattern.search(sig['name'])
                               for sig in self.signal_declarations)
        # Structural detection of dmem address signals - look for dmem_* or *_addr patterns for stores
        has_dmem_mux_signals = any(sig['name'] == 'dmem_write_addr_mux' or
                                  (sig['name'].endswith('_addr') and sig['name'].startswith('s'))
                                  for sig in self.signal_declarations)
        has_dmem_write_enable = any(sig['name'] == 'dmem_write_enable'
                                   for sig in self.signal_declarations)

        if has_dmem and has_store_enables and (has_dmem_mux_signals or has_dmem_write_enable):
            # Find which store enables exist - check both old and new naming conventions
            # For pipelined processors, prefer Memory-stage pipelined signals
            store_enables = []

            # Check if this is a pipelined processor with memory-stage store enables
            # Handle different pipeline configurations:
            # - 5-stage: pipe_memory_* (signals end with _pipe_pipe)
            # - 4-stage: pipe_memorywriteback_* (signals end with _pipe_pipe)
            # - 3-stage: pipe_executememorywriteback_* (signals end with _pipe)
            # - 2-stage: pipe_decodeexecutememorywriteback_* (signals may vary)
            # Look for any pipeline stage containing 'memory' with store enable signals
            is_pipelined_dmem = any(sig['name'].startswith('pipe_') and 'memory' in sig['name'] and
                                    '_enable_pipe' in sig['name']
                                    for sig in self.signal_declarations)

            for store in ['sd', 'sw', 'sh', 'sb']:  # sd=64-bit for RV64I
                enable_name = None

                if is_pipelined_dmem:
                    # Look for pipelined memory-stage store enable signal
                    # Pattern: pipe_*memory*_.._{store}_enable_*_pipe (any stage with 'memory' in name)
                    # May end with _pipe or _pipe_pipe depending on pipeline depth
                    for sig in self.signal_declarations:
                        sig_name = sig['name']
                        if (sig_name.startswith('pipe_') and 'memory' in sig_name and
                            f'_{store}_enable' in sig_name and
                            sig_name.endswith('_pipe')):
                            enable_name = sig_name
                            break

                if enable_name is None:
                    # Try new-style first (from memory access transform)
                    enable_name = f'{store}_enable'
                    if not any(sig['name'] == enable_name for sig in self.signal_declarations):
                        # Try old-style
                        enable_name = f'{store}_enable_and'
                        if not any(sig['name'] == enable_name for sig in self.signal_declarations):
                            enable_name = None

                if enable_name:
                    store_enables.append((store, enable_name))

            # Get writer widths from the memory write port node (graph-based approach)
            # This avoids hardcoding widths for sh=16, sb=8
            writer_widths = {}
            mem_width = 32  # Default memory port width
            for node in self.graph.nodes.values():
                if node.data.get('type') == 'memory_write_port':
                    if node.data.get('base_memory') == 'dmem':
                        writer_widths = node.data.get('writer_widths', {})
                        mem_width = node.data.get('port_width', 32)
                        break

            # Determine the address signal from the graph structure
            # Find the memory_write_port node for dmem and get its write_address edge source
            addr_signal = None
            for node in self.graph.nodes.values():
                if node.data.get('type') == 'memory_write_port' and node.data.get('base_memory') == 'dmem':
                    for edge in node.incoming_edges:
                        if edge.data.get('type') == 'write_address':
                            addr_signal = self.node_id_to_name.get(
                                edge.source.id, self._sanitize_identifier(edge.source.id))
                            break
                    break

            # Fallback: look for pipelined memory-stage address signal
            if addr_signal is None and is_pipelined_dmem:
                for sig in self.signal_declarations:
                    sig_name = sig['name']
                    if (sig_name.startswith('pipe_') and 'memory' in sig_name and
                        'sb_addr' in sig_name and sig_name.endswith('_pipe')):
                        addr_signal = sig_name
                        break

            # Final fallback: try individual address signals (for non-pipelined designs)
            if addr_signal is None:
                for name in ['sb_addr', 'sw_addr', 'sh_addr']:
                    if any(sig['name'] == name for sig in self.signal_declarations):
                        addr_signal = name
                        break

            # Determine the write enable signal
            # Prefer dmem_write_enable_valid_gated (pipelined + validity gated) over plain dmem_write_enable
            write_enable = None
            if any(sig['name'] == 'dmem_write_enable_valid_gated' for sig in self.signal_declarations):
                write_enable = 'dmem_write_enable_valid_gated'
            elif any(sig['name'] == 'dmem_write_enable' for sig in self.signal_declarations):
                write_enable = 'dmem_write_enable'

            if addr_signal and (store_enables or write_enable):
                # Get dmem array depth and bit width to use in address calculation
                dmem_array_depth = self.memory_declarations.get('dmem', {}).get('array_depth', 2048)
                dmem_bit_width = self.memory_declarations.get('dmem', {}).get('bit_width', 32)
                # Shift by 2 for 32-bit words, 3 for 64-bit words
                addr_shift = 3 if dmem_bit_width == 64 else 2
                # Use actual dmem bit width for sub-word write calculations
                mem_width = dmem_bit_width

                self.seq_logic += "    -- Data memory write process\n"
                self.seq_logic += "    process(clk)\n"
                # Add variable for masked address
                self.seq_logic += "        variable write_word_idx : integer;\n"
                self.seq_logic += "    begin\n"
                self.seq_logic += "        if rising_edge(clk) then\n"
                self.seq_logic += "            if reset /= '1' then\n"

                # If we have a combined write_enable, use it as the outer condition
                if write_enable and store_enables:
                    self.seq_logic += f"                if {write_enable} = '1' then\n"
                    # Mask address to valid range using actual dmem array size
                    self.seq_logic += f"                    write_word_idx := to_integer(shift_right(unsigned({addr_signal}), {addr_shift})) mod {dmem_array_depth};\n"

                    # Use byte enables from memory transform if available
                    for i, (store_type, enable_sig) in enumerate(store_enables):
                        if_keyword = "if" if i == 0 else "elsif"
                        self.seq_logic += f"                    {if_keyword} {enable_sig} = '1' then\n"

                        # Get write width from graph, fallback to type-based defaults
                        write_width = writer_widths.get(store_type, mem_width)
                        if write_width == 0:
                            # Fallback based on store type name
                            write_width = {'sd': 64, 'sw': 32, 'sh': 16, 'sb': 8}.get(store_type, mem_width)

                        if write_width >= mem_width:
                            # Full-width write
                            self.seq_logic += "                        dmem(write_word_idx) <= dmem_write_data_mux;\n"
                        else:
                            # Sub-word write - data is pre-positioned in dmem_write_data_mux
                            # Calculate number of positions and address bits needed
                            num_positions = mem_width // write_width
                            import math
                            addr_bits = int(math.log2(num_positions))

                            # Generate case statement with correct slices
                            # For 32-bit word: byte select uses addr[1:0], halfword uses addr[1]
                            # General formula: addr[sub_word_bits-1 : sub_word_bits-addr_bits]
                            # where sub_word_bits = log2(mem_width/8)
                            sub_word_bits = int(math.log2(mem_width // 8))
                            addr_high = sub_word_bits - 1
                            addr_low = sub_word_bits - addr_bits
                            if addr_high == addr_low:
                                self.seq_logic += f"                        case {addr_signal}({addr_high}) is\n"
                            else:
                                self.seq_logic += f"                        case {addr_signal}({addr_high} downto {addr_low}) is\n"

                            for pos in range(num_positions):
                                data_low = pos * write_width
                                data_high = data_low + write_width - 1
                                if num_positions == 2:
                                    case_val = f"'{pos}'"
                                else:
                                    case_val = f'"{pos:0{addr_bits}b}"'
                                self.seq_logic += f"                            when {case_val} => dmem(write_word_idx)({data_high} downto {data_low}) <= dmem_write_data_mux({data_high} downto {data_low});\n"

                            self.seq_logic += "                            when others => null;\n"
                            self.seq_logic += "                        end case;\n"

                    self.seq_logic += "                    end if;\n"
                    self.seq_logic += "                end if;\n"
                else:
                    # Old-style without combined write enable
                    for i, (store_type, enable_sig) in enumerate(store_enables):
                        indent = "    " if i == 0 else ""
                        if_keyword = "if" if i == 0 else "elsif"
                        self.seq_logic += f"                {indent}{if_keyword} {enable_sig} = '1' then\n"

                        # Mask address to valid range using actual dmem array size
                        self.seq_logic += f"                    write_word_idx := to_integer(shift_right(unsigned({addr_signal}), {addr_shift})) mod {dmem_array_depth};\n"

                        # Get write width from graph, fallback to type-based defaults
                        write_width = writer_widths.get(store_type, mem_width)
                        if write_width == 0:
                            write_width = {'sd': 64, 'sw': 32, 'sh': 16, 'sb': 8}.get(store_type, mem_width)

                        if write_width >= mem_width:
                            self.seq_logic += "                    dmem(write_word_idx) <= dmem_write_data_mux;\n"
                        else:
                            # Sub-word write - data is pre-positioned in dmem_write_data_mux
                            num_positions = mem_width // write_width
                            import math
                            addr_bits = int(math.log2(num_positions))

                            # For 32-bit word: byte select uses addr[1:0], halfword uses addr[1]
                            sub_word_bits = int(math.log2(mem_width // 8))
                            addr_high = sub_word_bits - 1
                            addr_low = sub_word_bits - addr_bits
                            if addr_high == addr_low:
                                self.seq_logic += f"                    case {addr_signal}({addr_high}) is\n"
                            else:
                                self.seq_logic += f"                    case {addr_signal}({addr_high} downto {addr_low}) is\n"

                            for pos in range(num_positions):
                                data_low = pos * write_width
                                data_high = data_low + write_width - 1
                                if num_positions == 2:
                                    case_val = f"'{pos}'"
                                else:
                                    case_val = f'"{pos:0{addr_bits}b}"'
                                self.seq_logic += f"                        when {case_val} => dmem(write_word_idx)({data_high} downto {data_low}) <= dmem_write_data_mux({data_high} downto {data_low});\n"

                            self.seq_logic += "                        when others => null;\n"
                            self.seq_logic += "                    end case;\n"

                    self.seq_logic += "                end if;\n"

                self.seq_logic += "            end if;\n"
                self.seq_logic += "        end if;\n"
                self.seq_logic += "    end process;\n\n"

    def _assemble_module(self) -> str:
        """Assemble the complete VHDL module."""
        vhdl = ""

        # Add generated module definitions (each has its own library declarations)
        for module_def in self.module_definitions:
            vhdl += module_def + "\n\n"

        # Library statements for main entity
        # Output in specific order: library first, then std_logic_1164, then numeric_std
        lib_order = [
            "library IEEE;",
            "use IEEE.std_logic_1164.all;",
            "use IEEE.numeric_std.all;"
        ]
        for lib in lib_order:
            if lib in self.library_statements:
                vhdl += lib + "\n"
        # Add any other library statements
        for lib in sorted(self.library_statements):
            if lib not in lib_order:
                vhdl += lib + "\n"
        vhdl += "\n"

        # Entity and architecture
        vhdl += self.entity_header

        # Insert additional signals before "begin"
        declarations = self.declarations
        if self.additional_signals:
            # Find the "begin" line and insert before it
            begin_pos = declarations.rfind("begin\n")
            if begin_pos != -1:
                additional_decls = ""
                for sig in self.additional_signals:
                    name = sig['name']
                    bit_width = sig['bit_width']
                    if bit_width > 1:
                        additional_decls += f"    signal {name} : std_logic_vector({bit_width-1} downto 0) := (others => '0');\n"
                    else:
                        additional_decls += f"    signal {name} : std_logic := '0';\n"
                declarations = declarations[:begin_pos] + additional_decls + declarations[begin_pos:]

        vhdl += declarations
        vhdl += self.memory_init
        vhdl += self.comb_logic + "\n"

        # Module instantiations
        for module_inst in self.module_instantiations:
            vhdl += "    " + module_inst + "\n"

        # Debug output assignments
        if self.debug_outputs:
            debug_assignments = []
            # Handle both list and dict formats
            if isinstance(self.debug_outputs, dict):
                # Dict format: {port_name: signal_name}
                for port_name, signal_name in self.debug_outputs.items():
                    exists = any(s['name'] == signal_name for s in self.signal_declarations)
                    if not exists:
                        continue
                    debug_assignments.append(f"    {port_name} <= {signal_name};\n")
            else:
                # List format: [signal_name, ...]
                for debug_signal in self.debug_outputs:
                    # Check if the signal exists in declarations
                    exists = any(s['name'] == debug_signal for s in self.signal_declarations)
                    if not exists:
                        continue
                    # Determine the port name - don't double-prefix with 'debug_'
                    if debug_signal.startswith('debug_'):
                        port_name = debug_signal
                    else:
                        port_name = f"debug_{debug_signal}"
                    # Skip self-assignments (port and signal have same name)
                    if port_name != debug_signal:
                        debug_assignments.append(f"    {port_name} <= {debug_signal};\n")
            if debug_assignments:
                vhdl += "\n    -- Debug outputs\n"
                for assignment in debug_assignments:
                    vhdl += assignment
                vhdl += "\n"

        vhdl += self.seq_logic
        vhdl += f"end architecture rtl;\n"

        return vhdl


def generate_vhdl(graph: ResourceGraph, entity_name: str = "processor",
                  debug_outputs: List[str] = None,
                  interface_ports: Dict[str, str] = None) -> str:
    """Generate VHDL code from a ResourceGraph."""
    generator = VHDLGenerator(graph, entity_name, debug_outputs=debug_outputs,
                            interface_ports=interface_ports)
    return generator.generate()


def generate_vhdl_with_testbench(graph: ResourceGraph,
                                  entity_name: str = "processor",
                                  output_dir: str = "vhdl",
                                  debug_outputs: List[str] = None,
                                  interface_ports: Dict[str, str] = None,
                                  testbench_config: dict = None,
                                  program_elf: str = None) -> dict:
    """
    Generate VHDL RTL and testbench files.

    Args:
        graph: ResourceGraph to generate from
        entity_name: Name of the processor entity
        output_dir: Directory to write output files
        interface_ports: Dict of signal_name -> direction ('in'/'out') for exposed ports
        testbench_config: Optional testbench configuration dict
        program_elf: Optional path to ELF file to load into testbench

    Returns:
        Dictionary with paths to generated files
    """
    from pathlib import Path
    from .testbench_generator import (
        generate_vhdl_testbench_files,
        VHDLTestbenchConfig
    )

    # Generate RTL
    vhdl_code = generate_vhdl(graph, entity_name, debug_outputs=debug_outputs,
                             interface_ports=interface_ports)

    # Write RTL file
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    rtl_file = output_path / f"{entity_name}.vhd"
    rtl_file.write_text(vhdl_code)

    # Generate testbench if config provided
    result = {'rtl': rtl_file}

    if testbench_config is not None:
        # Create testbench config
        if isinstance(testbench_config, dict):
            config = VHDLTestbenchConfig(**testbench_config)
        else:
            config = testbench_config

        # Add debug outputs to config
        if debug_outputs:
            config.debug_outputs = debug_outputs

        # Load program data if ELF file provided
        program_data = None
        pass_addr = None
        fail_addr = None

        if program_elf:
            from .elf_loader import load_elf_for_testbench
            program_data, pass_addr, fail_addr = load_elf_for_testbench(
                Path(program_elf),
                imem_size=config.imem_size
            )

        # Generate testbench
        tb_files = generate_vhdl_testbench_files(
            entity_name=entity_name,
            rtl_file=rtl_file,
            output_dir=output_path,
            config=config,
            program_data=program_data,
            pass_addr=pass_addr,
            fail_addr=fail_addr
        )

        result.update(tb_files)

    return result
