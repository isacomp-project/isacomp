"""
PyRTL Generator for ISAComp

This module generates PyRTL code from ResourceGraph representations.
PyRTL is a Python library for RTL design that allows direct hardware simulation.
"""

from typing import Dict, List, Set, Tuple, Optional
import re
from core.resource_graph import ResourceGraph, Node, Edge
import pyrtl


class PyRTLGenerator:
    """Generate PyRTL hardware design from a ResourceGraph."""

    def __init__(self, graph: ResourceGraph, module_name: str = "processor"):
        """
        Initialize the PyRTL generator.

        Args:
            graph: The ResourceGraph to generate from
            module_name: Name of the module (used for documentation)
        """
        self.graph = graph
        self.module_name = module_name
        
        # PyRTL will use its own working block for wire management
        pyrtl.reset_working_block()
        
        # Track node ID to PyRTL WireVector mappings
        self.node_to_wire: Dict[str, pyrtl.WireVector] = {}
        
        # Track signal widths
        self.signal_widths: Dict[str, int] = {}
        
        # Track memories
        self.memories: Dict[str, pyrtl.MemBlock] = {}

        # Track registers
        self.registers: Dict[str, pyrtl.Register] = {}

        # Track stall signals for architectural state registers
        # Key is base register name, value is stall wire
        self.register_stalls: Dict[str, pyrtl.WireVector] = {}

        # Track registers that have already had their .next set
        self.registers_with_next_set: Set[str] = set()

        # Track used wire names to avoid duplicates
        self.used_names: Set[str] = set()

        # Infer default width from register file (rf) if present
        self.default_width = 32
        rf_node = self.graph.nodes.get('rf')
        if rf_node and rf_node.data.get('bit_width'):
            self.default_width = rf_node.data['bit_width']

    def _get_width(self, node: Node) -> int:
        """
        Determine the bit width of a node's output.

        Args:
            node: The node to analyze

        Returns:
            The bit width (default 32 if not specified)
        """
        if node.id in self.signal_widths:
            return self.signal_widths[node.id]
        
        # Check node data for width information
        if 'bit_width' in node.data and node.data['bit_width'] is not None:
            width = node.data['bit_width']
            self.signal_widths[node.id] = width
            return width
        
        # For bit slices, compute width from range
        if node.data.get('type') == 'bit_slice':
            if 'expression' in node.data and 'range' in node.data['expression']:
                high_bit, low_bit = node.data['expression']['range']
                width = high_bit - low_bit + 1
                self.signal_widths[node.id] = width
                return width
        
        # For literals, infer from value or node ID
        if node.data.get('type', '') in ['literal', 'sized_literal', 'constant']:
            # Try to parse width from node ID (e.g., "12'b0", "32'hFFFFFFFE")
            match = re.match(r"(\d+)'([hbodHBOD])([0-9a-fA-F_]+)", node.id)
            if match:
                width = int(match.group(1))
                self.signal_widths[node.id] = width
                return width

            # Otherwise infer from value
            value = node.data.get('value', 0)
            if isinstance(value, int):
                # Use 32 bits for integer literals to match typical register width
                # This prevents issues with narrow constants in arithmetic operations
                width = 32
                self.signal_widths[node.id] = width
                return width
        
        # For concatenations, sum of all part widths
        if node.data.get('type') in ['concatenation', 'concat']:
            total = 0
            for edge in node.incoming_edges:
                w = self._get_width(edge.source)
                if w is not None:
                    total += w
            if total > 0:
                self.signal_widths[node.id] = total
                return total

        # For repetitions, count * source width
        if node.data.get('type') == 'repetition':
            count = node.data.get('count', node.data.get('repetitions', 1))
            if node.incoming_edges:
                source_width = self._get_width(next(iter(node.incoming_edges)).source)
                width = count * source_width
                self.signal_widths[node.id] = width
                return width
        
        # For variables, follow the source
        if node.data.get('type') in ['var', 'temp_var']:
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'assignment':
                    width = self._get_width(edge.source)
                    self.signal_widths[node.id] = width
                    return width

        # For array accesses (reads), get width from the array's data width
        if node.data.get('type') == 'array_access':
            # Find the array node that this access refers to
            for edge in node.incoming_edges:
                if edge.data.get('type') in ['array', 'array_base']:
                    array_node = edge.source
                    # Get the array's bit_width (element width)
                    array_width = array_node.data.get('bit_width')
                    if array_width:
                        self.signal_widths[node.id] = array_width
                        return array_width

        # For comparison operations, result is always 1 bit
        if node.data.get('type') in ['operation', 'comparison']:
            # Check both operator and operation - prefer operator since operation may be full expression
            operator = node.data.get('operator', '')
            operation = node.data.get('operation', '')
            comparison_ops = ['==', '!=', '<', '>', '<=', '>=', 'eq', 'ne', 'lt', 'gt', 'le', 'ge',
                              '<s', '>s', '<=s', '>=s', '<u', '>u', '<=u', '>=u', 'ult', 'ugt', 'ule', 'uge']
            if operator in comparison_ops or operation in comparison_ops:
                self.signal_widths[node.id] = 1
                return 1

        # Default width (inferred from register file, typically 32 or 64)
        self.signal_widths[node.id] = self.default_width
        return self.default_width
    
    def _sanitize_name(self, name: str, node_id: str = None) -> str:
        """Sanitize a name to be a valid Python identifier with uniqueness."""
        # Replace operators with descriptive text for better differentiation
        name = name.replace('>>>', '_ashr_')
        name = name.replace('>>', '_shr_')
        name = name.replace('<<', '_shl_')
        name = name.replace('>=', '_gte_')
        name = name.replace('<=', '_lte_')
        name = name.replace('!=', '_neq_')
        name = name.replace('==', '_eq_')
        name = name.replace('>', '_gt_')
        name = name.replace('<s', '_lts_')
        name = name.replace('<', '_lt_')
        name = name.replace('+', '_add_')
        name = name.replace('-', '_sub_')
        name = name.replace('*', '_mul_')
        name = name.replace('&', '_and_')
        name = name.replace('|', '_or_')
        name = name.replace('^', '_xor_')
        name = name.replace('~', '_not_')
        name = name.replace('?', '_sel_')
        name = name.replace(':', '_')

        # Replace invalid characters with underscore
        sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', name)
        # If it starts with a digit, prefix with underscore
        if sanitized and sanitized[0].isdigit():
            sanitized = '_' + sanitized
        # Remove consecutive underscores
        sanitized = re.sub(r'_+', '_', sanitized)
        # Strip leading/trailing underscores
        sanitized = sanitized.strip('_')

        if not sanitized:
            sanitized = 'wire'

        # Ensure uniqueness
        base_name = sanitized
        counter = 0
        while sanitized in self.used_names:
            counter += 1
            sanitized = f"{base_name}_{counter}"

        self.used_names.add(sanitized)
        return sanitized
    
    def _get_or_create_wire(self, node: Node) -> pyrtl.WireVector:
        """Get or create a PyRTL WireVector for a node."""
        if node.id in self.node_to_wire:
            return self.node_to_wire[node.id]
        
        width = self._get_width(node)
        name = self._sanitize_name(node.data.get('name', node.id))
        
        # Check node type to determine PyRTL wire type
        node_type = node.data.get('type', '')
        
        # ISA state, arch state, and pipeline registers should be registers
        if node.is_arch_state or node_type.startswith('isa_state') or node_type == 'pipeline_register':
            if node.data.get('is_memory', False):
                # Memory array
                if 'array_depth' in node.data and node.data['array_depth'] is not None:
                    addr_width = node.data['array_depth']
                    # Use port_width if set by memory transform, otherwise use bit_width
                    # port_width indicates the actual hardware memory width (e.g., 32-bit)
                    # while bit_width may be the access width (e.g., 8-bit for byte loads)
                    mem_width = node.data.get('port_width', width)
                    # Allow multiple write ports for memories with conditional writes
                    # Use asynchronous=True for single-cycle processor reads
                    mem = pyrtl.MemBlock(bitwidth=mem_width, addrwidth=addr_width, name=name,
                                         max_write_ports=None, asynchronous=True)
                    self.memories[node.id] = mem
                    # For memory nodes, we don't create a wire - reads/writes go through memory
                    # Create a constant wire as placeholder (connected to zero)
                    wire = pyrtl.Const(0, mem_width)
                    self.node_to_wire[node.id] = wire
                    return wire
            else:
                # Handle split read/write architectural state nodes
                # ISAComp splits pc into pc_rd and pc_wr - they should share the same register
                base_name = node.data.get('name', node.id)

                # Check if this is a _rd or _wr suffix node
                is_read = node.id.endswith('_rd') or node.data.get('display_name', '').endswith('_rd')
                is_write = node.id.endswith('_wr') or node.data.get('display_name', '').endswith('_wr')

                # Strip _rd/_wr suffix from base_name if present
                if base_name.endswith('_rd'):
                    base_name = base_name[:-3]
                elif base_name.endswith('_wr'):
                    base_name = base_name[:-3]

                # Use the base name for the register
                reg_key = base_name

                if reg_key in self.registers:
                    # Register already exists, reuse it
                    wire = self.registers[reg_key]
                else:
                    # Create new register with base name
                    # Sanitize without uniqueness check for registers
                    reg_name = re.sub(r'[^a-zA-Z0-9_]', '_', base_name)
                    reg_name = re.sub(r'_+', '_', reg_name).strip('_')
                    if reg_name and reg_name[0].isdigit():
                        reg_name = '_' + reg_name
                    if not reg_name:
                        reg_name = 'reg'
                    # Mark as used to prevent conflicts with other wires
                    self.used_names.add(reg_name)
                    wire = pyrtl.Register(width, name=reg_name)
                    self.registers[reg_key] = wire

                # For both read and write nodes, map to the register
                self.node_to_wire[node.id] = wire
                return wire
        else:
            # Regular wire
            wire = pyrtl.WireVector(width, name=name)
        
        self.node_to_wire[node.id] = wire
        return wire
    
    def _analyze_graph(self):
        """Analyze the graph to categorize nodes and create basic wires."""
        # First pass: create wires for all nodes (sorted for determinism)
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            # Skip some internal node types that will be inlined
            if node.data.get('type') in ['cast']:
                continue
            # Skip memory write ports - they don't produce output wires
            if node.data.get('type') == 'memory_write_port':
                continue
            self._get_or_create_wire(node)
    
    def _generate_constants(self):
        """Generate constant values for literals."""
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            node_type = node.data.get('type', '')
            if node_type in ['literal', 'sized_literal', 'constant']:
                # Try to parse value from node ID (e.g., "12'b0", "32'hFFFFFFFE", "4")
                value = node.data.get('value', 0)
                width = self._get_width(node)

                # Parse Verilog-style literal from node ID
                match = re.match(r"(\d+)'([hbodHBOD])([0-9a-fA-F_]+)", node.id)
                if match:
                    literal_width = int(match.group(1))
                    base = match.group(2).lower()
                    val_str = match.group(3).replace('_', '')
                    if base == 'h':
                        value = int(val_str, 16)
                    elif base == 'b':
                        value = int(val_str, 2)
                    elif base == 'o':
                        value = int(val_str, 8)
                    else:
                        value = int(val_str, 10)
                    width = literal_width

                wire = self._get_or_create_wire(node)

                # In PyRTL, constants are created using pyrtl.Const
                const_wire = pyrtl.Const(value, width)
                wire <<= const_wire
    
    def _generate_operations(self):
        """Generate combinational logic operations."""
        # Iterative topological sort to avoid recursion issues
        visited = set()
        visiting = set()  # Track nodes currently being visited (for cycle detection)
        
        def visit_node(node: Node):
            if node.id in visited:
                return
            
            # Detect cycles
            if node.id in visiting:
                # Cycle detected - skip to avoid infinite recursion
                return
            
            visiting.add(node.id)
            
            # Visit dependencies first (sorted for determinism)
            for edge in node.incoming_edges:
                if edge.source.id not in visited:
                    visit_node(edge.source)
            
            visiting.remove(node.id)
            visited.add(node.id)
            
            # Generate logic for this node
            node_type = node.data.get('type', '')
            
            # Skip nodes that are already handled
            if node_type in ['literal', 'sized_literal', 'constant', 'cast']:
                return
            
            # For ISA state (read port of registers), extract stall signals but don't generate logic
            # Note: var nodes with is_arch_state (write port) still need to be processed through _generate_variable
            if node_type.startswith('isa_state'):
                # Check for stall signals and record them for the base register
                is_read = node.id.endswith('_rd') or node.data.get('display_name', '').endswith('_rd')
                if is_read:
                    base_name = node.data.get('name', node.id)
                    if base_name.endswith('_rd'):
                        base_name = base_name[:-3]
                    for edge in node.incoming_edges:
                        if edge.data.get('type') == 'stall':
                            stall_wire = self._get_or_create_wire(edge.source)
                            self.register_stalls[base_name] = stall_wire
                            break
                return

            # For arch state that is NOT isa_state (e.g., var with is_arch_state=True),
            # process through normal var handling below
            
            # Process based on node type
            if node_type == 'operation':
                self._generate_operation(node)
            elif node_type == 'comparison':
                self._generate_comparison(node)
            elif node_type == 'bit_slice':
                self._generate_bit_slice(node)
            elif node_type == 'ternary_op':
                self._generate_ternary(node)
            elif node_type == 'array_access':
                self._generate_array_access(node)
            elif node_type == 'concatenation':
                self._generate_concatenation(node)
            elif node_type == 'repetition':
                self._generate_repetition(node)
            elif node_type in ['var', 'temp_var']:
                self._generate_variable(node)
            elif node_type in ['enable', 'logical_and']:
                self._generate_enable(node)
            elif node_type == 'logical_or':
                self._generate_logical_or(node)
            elif node_type in ['mux', 'multiplexer']:
                self._generate_mux(node)
            elif node_type in ['shared_write', 'shared_wr']:
                self._generate_shared_write(node)
            elif node_type == 'byte_enable_computation':
                self._generate_byte_enable(node)
            elif node_type == 'zero_extend':
                self._generate_zero_extend(node)
            elif node_type == 'memory_write_port':
                self._generate_memory_write_port(node)
            elif node_type == 'validity_bit':
                # Validity bits are created by branch prediction
                # If they have no incoming edges, default to constant 1 (valid)
                self._generate_validity_bit(node)
            elif node_type == 'pipeline_stall_controller':
                # Stall controllers OR all incoming control signals
                self._generate_stall_controller(node)
            elif node.incoming_edges:
                # For unknown types with incoming edges, try to handle as a passthrough
                self._generate_passthrough(node)
        
        # Visit all nodes in deterministic order (sorted by node ID)
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            if node.id not in visited:
                visit_node(node)
    
    def _generate_operation(self, node: Node):
        """Generate an arithmetic/logic operation."""
        # Prefer 'operator' over 'operation' since 'operation' may be full expression (e.g., "a == b")
        # while 'operator' is just the operator symbol (e.g., "==")
        operation = node.data.get('operator') or node.data.get('operation', '')

        # Get operands - support both edge type naming conventions
        left_operand = None
        right_operand = None
        operands = []

        for edge in node.incoming_edges:
            edge_type = edge.data.get('type', '')
            if edge_type == 'left_operand' or edge.data.get('position') == 'left':
                left_operand = self._get_or_create_wire(edge.source)
            elif edge_type == 'right_operand' or edge.data.get('position') == 'right':
                right_operand = self._get_or_create_wire(edge.source)
            elif edge_type == 'operand':
                operands.append(self._get_or_create_wire(edge.source))

        # Build operands list in correct order
        if left_operand is not None:
            operands = [left_operand]
            if right_operand is not None:
                operands.append(right_operand)
        elif right_operand is not None and operands:
            # We have operands with no position and a right operand
            # Treat the no-position operand as left
            operands = operands[:1] + [right_operand]
        elif right_operand is not None:
            # Only right operand specified - try to find left from any incoming edge
            for edge in node.incoming_edges:
                if edge.data.get('position') != 'right':
                    operands = [self._get_or_create_wire(edge.source), right_operand]
                    break
        elif not operands:
            # No explicit left/right labels - sort by numeric position (like Verilog)
            def get_position(e):
                pos = e.data.get('position', 999)
                if isinstance(pos, str):
                    try:
                        return int(pos)
                    except ValueError:
                        return 999
                return pos if isinstance(pos, int) else 999
            sorted_edges = sorted(node.incoming_edges, key=get_position)
            for edge in sorted_edges:
                operands.append(self._get_or_create_wire(edge.source))

        if len(operands) < 2:
            # For unary operations or passthrough
            if len(operands) == 1:
                result = self._get_or_create_wire(node)
                if operation in ['!', 'not', 'logical_not']:
                    # Logical NOT: result is 1 if operand is 0, 0 otherwise
                    result <<= operands[0] == 0
                elif operation in ['~', 'bitwise_not', 'invert']:
                    # Bitwise NOT
                    result <<= ~operands[0]
                else:
                    # Passthrough
                    result <<= operands[0]
            return
        
        result = self._get_or_create_wire(node)

        # Determine if this should use unsigned comparison based on node context
        # Check multiple sources: node ID, group_id, group_members, instruction
        node_id_lower = node.id.lower()
        group_id = (node.data.get('group_id') or '').lower()
        instruction = (node.data.get('instruction') or '').lower()
        group_members = [m.lower() for m in node.data.get('group_members', [])]

        unsigned_keywords = ['bltu', 'bgeu', 'sltu', 'sltiu']
        is_unsigned = (
            any(kw in node_id_lower for kw in unsigned_keywords) or
            any(kw == group_id for kw in unsigned_keywords) or
            any(kw == instruction for kw in unsigned_keywords) or
            any(kw in group_members for kw in unsigned_keywords)
        )
        # Check explicit is_signed flag (overrides heuristic)
        if node.data.get('is_signed'):
            is_unsigned = False

        # Map operations to PyRTL operations
        if operation in ['+', 'add']:
            result <<= operands[0] + operands[1]
        elif operation in ['-', 'sub']:
            result <<= operands[0] - operands[1]
        elif operation in ['*', 'mul']:
            result <<= operands[0] * operands[1]
        elif operation in ['&', 'and']:
            result <<= operands[0] & operands[1]
        elif operation in ['|', 'or']:
            result <<= operands[0] | operands[1]
        elif operation in ['^', 'xor']:
            result <<= operands[0] ^ operands[1]
        elif operation in ['<<', 'shl']:
            result <<= pyrtl.shift_left_logical(operands[0], operands[1])
        elif operation in ['>>', 'shr']:
            result <<= pyrtl.shift_right_logical(operands[0], operands[1])
        elif operation in ['>>>', 'ashr']:
            result <<= pyrtl.shift_right_arithmetic(operands[0], operands[1])
        # Comparison operations
        # Note: PyRTL's <, >, etc. are UNSIGNED. For signed, use pyrtl.signed_*
        elif operation in ['==', 'eq']:
            result <<= operands[0] == operands[1]
        elif operation in ['!=', 'ne']:
            result <<= operands[0] != operands[1]
        elif operation in ['<', 'lt', '<s']:
            if is_unsigned:
                result <<= operands[0] < operands[1]  # Unsigned comparison
            else:
                result <<= pyrtl.signed_lt(operands[0], operands[1])  # Signed comparison
        elif operation in ['<=', 'le', '<=s']:
            if is_unsigned:
                result <<= operands[0] <= operands[1]
            else:
                result <<= pyrtl.signed_le(operands[0], operands[1])
        elif operation in ['>', 'gt', '>s']:
            if is_unsigned:
                result <<= operands[0] > operands[1]
            else:
                result <<= pyrtl.signed_gt(operands[0], operands[1])
        elif operation in ['>=', 'ge', '>=s']:
            if is_unsigned:
                result <<= operands[0] >= operands[1]
            else:
                result <<= pyrtl.signed_ge(operands[0], operands[1])
        elif operation in ['<u', 'ult']:
            result <<= operands[0] < operands[1]
        elif operation in ['<=u', 'ule']:
            result <<= operands[0] <= operands[1]
        elif operation in ['>u', 'ugt']:
            result <<= operands[0] > operands[1]
        elif operation in ['>=u', 'uge']:
            result <<= operands[0] >= operands[1]
        # Logical operators (produce 1-bit result)
        elif operation in ['||', 'logical_or']:
            # Logical OR: true if any operand is non-zero
            # For 1-bit signals, this is the same as bitwise OR
            # For multi-bit signals, we need to reduce each to 1 bit first
            reduced = []
            for op in operands:
                if len(op) == 1:
                    reduced.append(op)
                else:
                    # Use comparison to produce 1-bit "is non-zero"
                    reduced.append(op != pyrtl.Const(0, len(op)))
            combined = reduced[0]
            for r in reduced[1:]:
                combined = combined | r
            result <<= combined
        elif operation in ['&&', 'logical_and']:
            # Logical AND: true if all operands are non-zero
            reduced = []
            for op in operands:
                if len(op) == 1:
                    reduced.append(op)
                else:
                    # Use comparison to produce 1-bit "is non-zero"
                    reduced.append(op != pyrtl.Const(0, len(op)))
            combined = reduced[0]
            for r in reduced[1:]:
                combined = combined & r
            result <<= combined
        else:
            # Default: just connect first operand
            result <<= operands[0]
    
    def _generate_comparison(self, node: Node):
        """Generate a comparison operation."""
        operation = node.data.get('operation') or node.data.get('operator', '')

        # Get operands - support both edge type naming conventions
        left_operand = None
        right_operand = None
        operands = []

        for edge in node.incoming_edges:
            edge_type = edge.data.get('type', '')
            if edge_type == 'left_operand' or edge.data.get('position') == 'left':
                left_operand = self._get_or_create_wire(edge.source)
            elif edge_type == 'right_operand' or edge.data.get('position') == 'right':
                right_operand = self._get_or_create_wire(edge.source)
            elif edge_type == 'operand':
                operands.append(self._get_or_create_wire(edge.source))

        # Build operands list in correct order
        if left_operand is not None:
            operands = [left_operand]
            if right_operand is not None:
                operands.append(right_operand)
        elif right_operand is not None and operands:
            # We have operands with no position and a right operand
            # Treat the no-position operand as left
            operands = operands[:1] + [right_operand]
        elif right_operand is not None:
            # Only right operand specified - try to find left from any incoming edge
            for edge in node.incoming_edges:
                if edge.data.get('position') != 'right':
                    operands = [self._get_or_create_wire(edge.source), right_operand]
                    break
        elif not operands:
            # No explicit left/right labels - sort by numeric position (like Verilog)
            def get_position(e):
                pos = e.data.get('position', 999)
                if isinstance(pos, str):
                    try:
                        return int(pos)
                    except ValueError:
                        return 999
                return pos if isinstance(pos, int) else 999
            sorted_edges = sorted(node.incoming_edges, key=get_position)
            for edge in sorted_edges:
                operands.append(self._get_or_create_wire(edge.source))

        if len(operands) < 2:
            # Check for embedded literal in expression
            expr = node.data.get('expression', {})
            # Handle both 'binary_op' and 'comparison' expression types
            if expr.get('type') in ('binary_op', 'comparison') and 'right' in expr:
                right = expr['right']
                if right.get('type') == 'literal':
                    # Extract the literal value
                    lit_val = right.get('value')
                    if isinstance(lit_val, str):
                        if lit_val.startswith('0b'):
                            lit_val = int(lit_val, 2)
                        elif lit_val.startswith('0x'):
                            lit_val = int(lit_val, 16)
                        else:
                            lit_val = int(lit_val)

                    # Get the operand (should be a bit slice of instr)
                    if len(operands) == 1:
                        result = self._get_or_create_wire(node)

                        # Check if left side is a bit_slice - need to extract bits
                        left = expr.get('left', {})
                        if left.get('type') == 'bit_slice':
                            high_bit = left.get('high', {}).get('value', 31)
                            low_bit = left.get('low', {}).get('value', 0)
                            # Extract the bits from the operand
                            operand_slice = operands[0][low_bit:high_bit+1]
                            slice_width = high_bit - low_bit + 1
                        else:
                            operand_slice = operands[0]
                            slice_width = len(operands[0])

                        # Create constant for comparison with correct width
                        const = pyrtl.Const(lit_val, slice_width)
                        # Get the operation
                        op = expr.get('operation', '==')
                        if op in ['==', 'eq']:
                            result <<= operand_slice == const
                        elif op in ['!=', 'ne']:
                            result <<= operand_slice != const
                        else:
                            result <<= operand_slice == const  # Default to equality
                        return

            # Single operand with no expression - pass through (may be wrong)
            if len(operands) == 1:
                result = self._get_or_create_wire(node)
                result <<= operands[0]
            return
        
        result = self._get_or_create_wire(node)

        # Determine if this should use unsigned comparison based on node context
        # Check multiple sources: node ID, group_id, group_members, instruction
        node_id_lower = node.id.lower()
        group_id = (node.data.get('group_id') or '').lower()
        instruction = (node.data.get('instruction') or '').lower()
        group_members = [m.lower() for m in node.data.get('group_members', [])]

        unsigned_keywords = ['bltu', 'bgeu', 'sltu', 'sltiu']
        is_unsigned = (
            any(kw in node_id_lower for kw in unsigned_keywords) or
            any(kw == group_id for kw in unsigned_keywords) or
            any(kw == instruction for kw in unsigned_keywords) or
            any(kw in group_members for kw in unsigned_keywords)
        )
        # Check explicit is_signed flag (overrides heuristic)
        if node.data.get('is_signed'):
            is_unsigned = False

        # Map comparison operations to PyRTL
        # Note: PyRTL's <, >, etc. are UNSIGNED. For signed, use pyrtl.signed_*
        if operation in ['==', 'eq']:
            result <<= operands[0] == operands[1]
        elif operation in ['!=', 'ne']:
            result <<= operands[0] != operands[1]
        elif operation in ['<', 'lt', '<s']:
            if is_unsigned:
                result <<= operands[0] < operands[1]  # Unsigned comparison
            else:
                result <<= pyrtl.signed_lt(operands[0], operands[1])  # Signed comparison
        elif operation in ['<=', 'le', '<=s']:
            if is_unsigned:
                result <<= operands[0] <= operands[1]
            else:
                result <<= pyrtl.signed_le(operands[0], operands[1])
        elif operation in ['>', 'gt', '>s']:
            if is_unsigned:
                result <<= operands[0] > operands[1]
            else:
                result <<= pyrtl.signed_gt(operands[0], operands[1])
        elif operation in ['>=', 'ge', '>=s']:
            if is_unsigned:
                result <<= operands[0] >= operands[1]
            else:
                result <<= pyrtl.signed_ge(operands[0], operands[1])
        elif operation in ['<u', 'ult']:
            result <<= operands[0] < operands[1]  # PyRTL comparisons are unsigned by default
        elif operation in ['<=u', 'ule']:
            result <<= operands[0] <= operands[1]
        elif operation in ['>u', 'ugt']:
            result <<= operands[0] > operands[1]
        elif operation in ['>=u', 'uge']:
            result <<= operands[0] >= operands[1]
        else:
            # Default: equality
            result <<= operands[0] == operands[1]
    
    def _generate_bit_slice(self, node: Node):
        """Generate bit extraction/slicing."""
        # Get bit range
        if 'expression' in node.data and 'range' in node.data['expression']:
            high_bit, low_bit = node.data['expression']['range']
        else:
            # Try to parse from node ID
            match = re.search(r'\[(\d+):(\d+)\]', node.id)
            if match:
                high_bit = int(match.group(1))
                low_bit = int(match.group(2))
            else:
                return
        
        # Get source
        source_edge = next((e for e in node.incoming_edges if e.data.get('type') in ['operand', 'bit_access']), None)
        if not source_edge:
            return
        
        source = self._get_or_create_wire(source_edge.source)
        result = self._get_or_create_wire(node)
        
        # PyRTL bit slice
        result <<= source[low_bit:high_bit+1]
    
    def _generate_ternary(self, node: Node):
        """Generate ternary (mux) operation."""
        # Get operands: condition, if_true, if_false
        cond = None
        true_val = None
        false_val = None

        for edge in node.incoming_edges:
            edge_type = edge.data.get('edge_type') or edge.data.get('type', '')
            if edge_type in ['condition', 'ternary_condition']:
                cond = self._get_or_create_wire(edge.source)
            elif edge_type == 'ternary_true':
                true_val = self._get_or_create_wire(edge.source)
            elif edge_type == 'ternary_false':
                false_val = self._get_or_create_wire(edge.source)

        if cond is not None and true_val is not None and false_val is not None:
            result = self._get_or_create_wire(node)

            # PyRTL select requires a 1-bit condition
            if len(cond) > 1:
                cond = cond[0]  # Take the LSB

            # Ensure all values have the same bit width
            target_width = self._get_width(node)
            true_width = len(true_val)
            false_width = len(false_val)

            # Zero-extend if needed
            if true_width < target_width:
                true_val = pyrtl.concat(pyrtl.Const(0, target_width - true_width), true_val)
            if false_width < target_width:
                false_val = pyrtl.concat(pyrtl.Const(0, target_width - false_width), false_val)

            result <<= pyrtl.select(cond, truecase=true_val, falsecase=false_val)

    def _get_memory_write_signals(self, memory_name: str):
        """
        Find signals needed for memory write-to-read forwarding structurally.

        Uses the shared write port's structure to find write enable, address, and data.

        Args:
            memory_name: Name of the memory (e.g., 'rf', 'dmem')

        Returns:
            Tuple of (write_enable_wire, write_addr_wire, write_data_wire) or None if not found.
        """
        # Find the shared write port for this memory
        shared_wr = self.graph.nodes.get(f'{memory_name}_shared_wr')
        if not shared_wr or shared_wr.data.get('type') != 'memory_write_port':
            return None

        # Get write enable from the combined_write_enable field
        # Look for the valid-gated version first
        enable_name = shared_wr.data.get('combined_write_enable')
        write_enable = None
        if enable_name:
            gated_enable = self.graph.nodes.get(f'{enable_name}_valid_gated')
            if gated_enable and gated_enable.id in self.node_to_wire:
                write_enable = self.node_to_wire[gated_enable.id]
            elif gated_enable:
                write_enable = self._get_or_create_wire(gated_enable)
            else:
                enable_node = self.graph.nodes.get(enable_name)
                if enable_node and enable_node.id in self.node_to_wire:
                    write_enable = self.node_to_wire[enable_node.id]
                elif enable_node:
                    write_enable = self._get_or_create_wire(enable_node)

        if write_enable is None:
            return None

        # Get write address and data from incoming edges
        write_addr = None
        write_data = None
        for edge in shared_wr.incoming_edges:
            edge_type = edge.data.get('type')
            if edge_type == 'write_address':
                if edge.source.id in self.node_to_wire:
                    write_addr = self.node_to_wire[edge.source.id]
                else:
                    write_addr = self._get_or_create_wire(edge.source)
            elif edge_type == 'write_data':
                if edge.source.id in self.node_to_wire:
                    write_data = self.node_to_wire[edge.source.id]
                else:
                    write_data = self._get_or_create_wire(edge.source)

        if write_addr is None or write_data is None:
            return None

        return (write_enable, write_addr, write_data)

    def _generate_array_access(self, node: Node):
        """Generate array/memory access."""
        # Find array and index
        array_node = None
        index_node = None

        for edge in node.incoming_edges:
            source = edge.source
            if source.data.get('is_memory') or source.id in self.memories:
                array_node = source
            else:
                index_node = source

        if not array_node or not index_node:
            return

        result = self._get_or_create_wire(node)

        # Memory read
        if array_node.id in self.memories:
            mem = self.memories[array_node.id]
            index = self._get_or_create_wire(index_node)

            # Check if this is a byte-addressed memory converted to word-addressed
            # (indicated by port_width being set). In this case, we need to convert
            # byte address to word address by shifting right.
            port_width = array_node.data.get('port_width')
            if port_width:
                # Shift right by 2 for 32-bit, 3 for 64-bit word addressing
                shift_amount = 3 if port_width == 64 else 2
                word_addr = pyrtl.shift_right_logical(index, shift_amount)
                index = word_addr

            # PyRTL requires that the index width <= address width
            # If the index is wider, truncate it to the address width
            index_width = len(index) if hasattr(index, '__len__') else self._get_width(index_node)
            addr_width = mem.addrwidth

            if index_width > addr_width:
                # Create truncated index - PyRTL uses [:n] for truncation
                truncated_index = index[:addr_width]
                final_index = truncated_index
            else:
                final_index = index

            # Check if write_read_fwd is enabled - if so, generate forwarding mux
            has_write_read_fwd = array_node.data.get('write_read_fwd', False)
            write_signals = None
            if has_write_read_fwd:
                write_signals = self._get_memory_write_signals(array_node.id)

            if has_write_read_fwd and write_signals:
                write_enable, write_addr, write_data = write_signals

                # Read from memory first
                raw_read = mem[final_index]

                # Ensure write_enable is 1-bit
                # The write enable signal may be multi-bit, but we only use bit 0
                # (consistent with how the RF write port uses it)
                write_enable_width = len(write_enable) if hasattr(write_enable, '__len__') else 1
                if write_enable_width > 1:
                    # Use only bit 0 - this matches what the RF write port uses
                    write_enable_1bit = write_enable[0]
                else:
                    write_enable_1bit = write_enable

                # Ensure write_addr width matches index width for comparison
                write_addr_width = len(write_addr) if hasattr(write_addr, '__len__') else 32
                read_addr_width = len(final_index) if hasattr(final_index, '__len__') else addr_width

                # Truncate write_addr if needed
                if write_addr_width > read_addr_width:
                    write_addr_cmp = write_addr[:read_addr_width]
                else:
                    write_addr_cmp = write_addr

                # Generate address comparison: write_addr == read_addr
                addr_match = write_addr_cmp == final_index

                # Generate combined condition: write_enable & addr_match (both are 1-bit)
                fwd_cond = write_enable_1bit & addr_match

                # Ensure write_data width matches memory width
                mem_width = mem.bitwidth
                write_data_width = len(write_data) if hasattr(write_data, '__len__') else mem_width

                if write_data_width > mem_width:
                    # Truncate write data
                    write_data_fwd = write_data[:mem_width]
                elif write_data_width < mem_width:
                    # Zero-extend write data
                    write_data_fwd = pyrtl.concat(pyrtl.Const(0, mem_width - write_data_width), write_data)
                else:
                    write_data_fwd = write_data

                # Generate forwarding mux: fwd_cond ? write_data : raw_read
                result <<= pyrtl.select(fwd_cond, truecase=write_data_fwd, falsecase=raw_read)
            else:
                # No forwarding - simple memory read
                result <<= mem[final_index]
    
    def _generate_concatenation(self, node: Node):
        """Generate bit concatenation."""
        # Get all parts - position 0 is MSB (leftmost in Verilog {a, b} syntax)
        parts = []
        for edge in sorted(node.incoming_edges, key=lambda e: e.data.get('position', 0)):
            parts.append(self._get_or_create_wire(edge.source))

        if parts:
            result = self._get_or_create_wire(node)
            # PyRTL concat is MSB-first: concat(a, b) = {a, b} where a is MSB
            # Parts are already in MSB-first order (position 0 = MSB)
            result <<= pyrtl.concat(*parts)
    
    def _generate_repetition(self, node: Node):
        """Generate bit repetition (for sign extension)."""
        count = node.data.get('count', node.data.get('repetitions', 1))
        
        source_edge = next((e for e in node.incoming_edges), None)
        if not source_edge:
            return

        source = self._get_or_create_wire(source_edge.source)
        result = self._get_or_create_wire(node)
        
        # Replicate the source value count times
        parts = [source] * count
        result <<= pyrtl.concat(*parts)
    
    def _generate_variable(self, node: Node):
        """Generate variable (alias) assignment."""
        result = self._get_or_create_wire(node)
        is_register = isinstance(result, pyrtl.Register)

        # Check if this is an architectural state write node
        is_arch_state = node.is_arch_state
        is_write = node.id.endswith('_wr') or node.data.get('display_name', '').endswith('_wr')

        base_name = node.data.get('name', node.id)
        if base_name.endswith('_rd'):
            base_name = base_name[:-3]
        elif base_name.endswith('_wr'):
            base_name = base_name[:-3]

        # Look up stall signal for architectural state registers
        stall_wire = None
        if is_arch_state and is_write:
            stall_wire = self.register_stalls.get(base_name)

        # Find source
        for edge in node.incoming_edges:
            if edge.data.get('type') == 'assignment':
                source = self._get_or_create_wire(edge.source)

                if is_register:
                    # For registers, need to use .next
                    if stall_wire is not None:
                        # When stalled, keep current value; otherwise, use new value
                        source_width = len(source)
                        reg_width = len(result)
                        if source_width < reg_width:
                            source = source.zero_extended(reg_width)
                        elif source_width > reg_width:
                            source = source[:reg_width]
                        result.next <<= pyrtl.select(stall_wire, result, source)
                    else:
                        result.next <<= source
                    # Mark this register as having its .next already set
                    self.registers_with_next_set.add(base_name)
                else:
                    result <<= source
                break

    def _generate_enable(self, node: Node):
        """Generate enable signal (ANDing of decode conditions)."""
        result = self._get_or_create_wire(node)

        # Get all incoming condition signals
        conditions = []
        for edge in node.incoming_edges:
            wire = self._get_or_create_wire(edge.source)
            conditions.append(wire)

        if len(conditions) == 0:
            # No conditions - default to 1
            result <<= pyrtl.Const(1, 1)
        elif len(conditions) == 1:
            result <<= conditions[0]
        else:
            # AND all conditions together
            combined = conditions[0]
            for cond in conditions[1:]:
                combined = combined & cond
            result <<= combined

    def _generate_logical_or(self, node: Node):
        """Generate logical OR of all inputs."""
        result = self._get_or_create_wire(node)

        # Get all incoming condition signals
        conditions = []
        for edge in node.incoming_edges:
            wire = self._get_or_create_wire(edge.source)
            conditions.append(wire)

        if len(conditions) == 0:
            # No conditions - default to 0
            result <<= pyrtl.Const(0, 1)
        elif len(conditions) == 1:
            result <<= conditions[0]
        else:
            # OR all conditions together
            combined = conditions[0]
            for cond in conditions[1:]:
                combined = combined | cond
            result <<= combined

    def _generate_mux(self, node: Node):
        """Generate multiplexer from mux node."""
        result = self._get_or_create_wire(node)

        # ISAComp mux structure: select/value pairs with input_index/select_index
        mux_inputs = []
        default_value = None

        # Collect inputs and selects by their index
        inputs_by_index = {}  # input_index -> (source_id, value wire)
        selects_by_index = {}  # select_index -> (source_id, select wire)

        # Also collect by source for fallback matching
        inputs_by_source = {}  # source_id -> value wire
        selects = []  # [(source_id, select_wire)]

        for edge in node.incoming_edges:
            edge_type = edge.data.get('edge_type') or edge.data.get('type', '')
            if edge_type in ['mux_default', 'mux_default_input']:
                default_value = self._get_or_create_wire(edge.source)
            elif edge_type in ['mux_input', 'mux_value']:
                # This is a value input
                wire = self._get_or_create_wire(edge.source)
                input_index = edge.data.get('input_index')
                if input_index is not None:
                    inputs_by_index[input_index] = (edge.source.id, wire)
                inputs_by_source[edge.source.id] = wire
            elif edge_type in ['mux_select', 'mux_condition']:
                # This is a select signal
                wire = self._get_or_create_wire(edge.source)
                select_index = edge.data.get('select_index')
                if select_index is not None:
                    selects_by_index[select_index] = (edge.source.id, wire)
                selects.append((edge.source.id, wire))

        # Primary matching: use input_index and select_index
        if inputs_by_index and selects_by_index:
            for idx in sorted(selects_by_index.keys()):
                sel_source, sel_wire = selects_by_index[idx]
                if idx in inputs_by_index:
                    inp_source, inp_wire = inputs_by_index[idx]
                    mux_inputs.append({
                        'value': inp_wire,
                        'select': sel_wire,
                        'priority': 0,
                        'name': sel_source,
                        'index': idx
                    })

        # Fallback: pair selects with inputs based on naming convention
        # Only use this if index-based matching didn't work
        if not mux_inputs:
            for sel_source, sel_wire in sorted(selects, key=lambda x: x[0]):
                # Try to find matching input
                matched = False
                for inp_source, inp_wire in sorted(inputs_by_source.items(), key=lambda x: x[0]):
                    # Check if select name references the input
                    if inp_source in sel_source or sel_source.replace('_select', '') in inp_source:
                        mux_inputs.append({
                            'value': inp_wire,
                            'select': sel_wire,
                            'priority': 0,
                            'name': sel_source
                        })
                        matched = True
                        break
                    # Check for instruction enable pattern (e.g., jal_enable for jal_jump_dest)
                    if sel_source.endswith('_enable'):
                        instr_name = sel_source.replace('_enable', '')
                        if inp_source.startswith(instr_name + '_'):
                            mux_inputs.append({
                                'value': inp_wire,
                                'select': sel_wire,
                                'priority': 0,
                                'name': sel_source
                            })
                            matched = True
                            break
                if not matched and inputs_by_source:
                    # Fallback: assign to first unmatched input
                    for inp_source, inp_wire in sorted(inputs_by_source.items(), key=lambda x: x[0]):
                        already_matched = any(inp.get('value') is inp_wire for inp in mux_inputs)
                        if not already_matched:
                            mux_inputs.append({
                                'value': inp_wire,
                                'select': sel_wire,
                                'priority': 0,
                                'name': sel_source
                            })
                            break

        # Build the mux using cascaded selects
        if not mux_inputs and default_value is not None:
            result <<= default_value
        elif mux_inputs:
            # Start with default or zero
            current = default_value if default_value is not None else pyrtl.Const(0, self._get_width(node))

            # Get target width from output
            target_width = self._get_width(node)

            # Apply each select/value pair - sort by index then by name for determinism
            for inp in sorted(mux_inputs, key=lambda x: (x.get('priority', 0), x.get('index', 999), x.get('name', ''))):
                if inp['select'] is not None and inp['value'] is not None:
                    # Ensure select is 1 bit
                    sel = inp['select']
                    if len(sel) > 1:
                        sel = sel[0]  # Take the LSB

                    # Ensure value width matches target
                    value = inp['value']
                    if len(value) < target_width:
                        # Zero-extend to match width
                        value = pyrtl.concat(pyrtl.Const(0, target_width - len(value)), value)
                    elif len(value) > target_width:
                        value = value[:target_width]

                    # Ensure current width matches target
                    if len(current) < target_width:
                        current = pyrtl.concat(pyrtl.Const(0, target_width - len(current)), current)
                    elif len(current) > target_width:
                        current = current[:target_width]

                    current = pyrtl.select(sel, truecase=value, falsecase=current)

            result <<= current

    def _generate_shared_write(self, node: Node):
        """Generate shared write port logic."""
        # Shared write nodes are handled by the mux that feeds them
        # Just pass through the input
        result = self._get_or_create_wire(node)

        for edge in node.incoming_edges:
            if edge.data.get('type') in ['data', 'assignment', 'operand']:
                source = self._get_or_create_wire(edge.source)
                result <<= source
                return

        # If no data edge found, set to zero
        result <<= pyrtl.Const(0, self._get_width(node))

    def _generate_byte_enable(self, node: Node):
        """Generate byte enable computation."""
        result = self._get_or_create_wire(node)

        # Byte enables are computed from address bits
        # This is typically (1 << addr[1:0]) for byte, (3 << addr[1]) for halfword
        for edge in node.incoming_edges:
            source = self._get_or_create_wire(edge.source)
            result <<= source
            return

        # Default to all bytes enabled
        result <<= pyrtl.Const(0xF, 4)

    def _generate_zero_extend(self, node: Node):
        """Generate zero extension."""
        result = self._get_or_create_wire(node)
        target_width = self._get_width(node)

        for edge in node.incoming_edges:
            source = self._get_or_create_wire(edge.source)
            source_width = self._get_width(edge.source)

            if source_width < target_width:
                # Zero extend by concatenating zeros
                zeros = pyrtl.Const(0, target_width - source_width)
                result <<= pyrtl.concat(zeros, source)
            else:
                result <<= source
            return

        # Default to zero
        result <<= pyrtl.Const(0, target_width)

    def _generate_memory_write_port(self, node: Node):
        """Generate memory write port with conditional enable and byte enables (RMW for sub-word stores)."""
        # Find the memory, address, data, and enable from incoming edges
        mem_wire = None
        addr_wire = None
        data_wire = None
        enable_wire = None
        mem_name = None
        mem_node = None

        for edge in node.incoming_edges:
            edge_type = edge.data.get('type', '')
            if edge_type == 'write_address' or edge_type == 'array_index':
                addr_wire = self._get_or_create_wire(edge.source)
            elif edge_type == 'write_data':
                data_wire = self._get_or_create_wire(edge.source)
            elif edge_type == 'write_enable':
                enable_wire = self._get_or_create_wire(edge.source)

        # Find the target memory from outgoing edges
        for edge in node.outgoing_edges:
            edge_type = edge.data.get('type', '')
            if edge_type == 'memory_write':
                mem_name = edge.target.id
                mem_node = edge.target
                break

        if mem_name and mem_name in self.memories and addr_wire is not None and data_wire is not None:
            mem = self.memories[mem_name]
            word_addr_wire = addr_wire  # Keep original for byte enables

            # Check if this is a byte-addressed memory converted to word-addressed
            # (indicated by port_width being set). In this case, we need to convert
            # byte address to word address by shifting right.
            port_width = None
            if mem_node:
                port_width = mem_node.data.get('port_width')
                if port_width:
                    # Shift right by 2 for 32-bit, 3 for 64-bit word addressing
                    shift_amount = 3 if port_width == 64 else 2
                    word_addr_wire = pyrtl.shift_right_logical(addr_wire, shift_amount)

            # Ensure enable is 1 bit
            if enable_wire is not None:
                if len(enable_wire) > 1:
                    enable_wire = enable_wire[0]  # Take LSB
            else:
                enable_wire = pyrtl.Const(1, 1)  # Always enabled if no enable specified

            # Truncate word address if needed
            if len(word_addr_wire) > mem.addrwidth:
                word_addr_wire = word_addr_wire[:mem.addrwidth]

            # Check if sub-word stores are present (need RMW)
            store_byte_enables = node.data.get('store_byte_enables', {})

            if store_byte_enables and port_width:
                # Sub-word stores present - implement read-modify-write
                # Get byte enable signals for each sub-word store type
                byte_enable_wires = {}
                for instr, be_name in store_byte_enables.items():
                    be_node = self.graph.nodes.get(be_name)
                    if be_node:
                        byte_enable_wires[instr] = self._get_or_create_wire(be_node)

                # Get instruction enables - use pipelined version for Memory stage if available
                instr_enables = {}
                for instr in store_byte_enables.keys():
                    enable_name = f'{instr}_enable'
                    # For pipelined processors, look for Memory stage pipelined enable signal
                    # Pattern: PIPE_Memory_PIPE_Execute_{instr}_enable_PIPE_PIPE
                    pipelined_enable_name = None
                    for node_name in self.graph.nodes:
                        if (f'{instr}_enable_PIPE' in node_name and
                            'Memory' in node_name and
                            self.graph.nodes[node_name].data.get('type') == 'pipeline_register'):
                            # Found pipelined version - prefer deeper pipelined signals
                            if pipelined_enable_name is None or len(node_name) > len(pipelined_enable_name):
                                pipelined_enable_name = node_name

                    # Use pipelined version if found, otherwise use original
                    actual_enable_name = pipelined_enable_name if pipelined_enable_name else enable_name
                    enable_node = self.graph.nodes.get(actual_enable_name)
                    if enable_node:
                        instr_enables[instr] = self._get_or_create_wire(enable_node)

                # Create combined byte enable by muxing based on instruction
                # Default to all bytes enabled - 0xF for 32-bit, 0xFF for 64-bit
                num_bytes = port_width // 8
                all_bytes_enabled = (1 << num_bytes) - 1  # 0xF for 4 bytes, 0xFF for 8 bytes
                combined_byte_enable = pyrtl.Const(all_bytes_enabled, num_bytes)
                for instr, be_wire in byte_enable_wires.items():
                    if instr in instr_enables:
                        # If this instruction is active, use its byte enable
                        enable = instr_enables[instr]
                        if len(enable) > 1:
                            enable = enable[0]
                        combined_byte_enable = pyrtl.select(enable, truecase=be_wire, falsecase=combined_byte_enable)

                # Expand byte enable to full-width mask based on port_width
                # Each bit of byte_enable corresponds to 8 bits of the mask
                num_bytes = port_width // 8  # 4 for 32-bit, 8 for 64-bit

                # Build byte mask dynamically based on port_width
                byte_masks = []
                for i in range(num_bytes):
                    if i < len(combined_byte_enable):
                        mask = pyrtl.select(combined_byte_enable[i],
                                           truecase=pyrtl.Const(0xFF, 8),
                                           falsecase=pyrtl.Const(0, 8))
                    else:
                        # For higher bytes not covered by byte_enable, use 0xFF (full word stores)
                        mask = pyrtl.Const(0xFF, 8)
                    byte_masks.append(mask)

                # Concatenate masks from MSB to LSB
                byte_mask = byte_masks[-1]
                for i in range(len(byte_masks) - 2, -1, -1):
                    byte_mask = pyrtl.concat(byte_mask, byte_masks[i])

                # Read current word from memory (asynchronous read)
                current_word = mem[word_addr_wire]

                # Read-modify-write: (current_word & ~mask) | (write_data & mask)
                inv_mask = ~byte_mask
                preserved_bits = current_word & inv_mask

                # Ensure data_wire matches port_width
                if len(data_wire) < port_width:
                    data_wire = pyrtl.concat(pyrtl.Const(0, port_width - len(data_wire)), data_wire)
                elif len(data_wire) > port_width:
                    data_wire = data_wire[:port_width]

                new_bits = data_wire & byte_mask
                combined_data = preserved_bits | new_bits

                # Write the combined data
                mem[word_addr_wire] <<= pyrtl.MemBlock.EnabledWrite(combined_data, enable_wire)
            else:
                # No sub-word stores - simple full word write
                mem[word_addr_wire] <<= pyrtl.MemBlock.EnabledWrite(data_wire, enable_wire)

    def _generate_passthrough(self, node: Node):
        """Generate passthrough for unknown node types with single input."""
        result_wire = self._get_or_create_wire(node)
        is_register = isinstance(result_wire, pyrtl.Register)

        source_wire = None
        stall_wire = None

        # Determine base register name for architectural state
        node_type = node.data.get('type', '')
        is_arch_state = node.is_arch_state
        is_read = node.id.endswith('_rd') or node.data.get('display_name', '').endswith('_rd')
        is_write = node.id.endswith('_wr') or node.data.get('display_name', '').endswith('_wr')

        base_name = node.data.get('name', node.id)
        if base_name.endswith('_rd'):
            base_name = base_name[:-3]
        elif base_name.endswith('_wr'):
            base_name = base_name[:-3]

        # Look for pipeline_input and stall edges for pipeline registers
        for edge in node.incoming_edges:
            edge_type = edge.data.get('type', '')
            if edge_type == 'pipeline_input':
                source_wire = self._get_or_create_wire(edge.source)
            elif edge_type == 'stall':
                stall_wire = self._get_or_create_wire(edge.source)
                # Store stall signal for architectural state registers
                if is_arch_state and base_name:
                    self.register_stalls[base_name] = stall_wire
            elif edge_type in ['assignment', 'data', 'operand', 'input']:
                if source_wire is None:
                    source_wire = self._get_or_create_wire(edge.source)

        # For isa_state read nodes with stall but no source, it's just the register value
        # Don't need to assign anything - just record the stall
        if (node_type == 'isa_state' or is_arch_state) and is_read:
            if stall_wire is not None and source_wire is None:
                return  # Read port with stall - nothing to assign

        # If no explicit type, just use first incoming edge (excluding stall)
        if source_wire is None and node.incoming_edges:
            for edge in node.incoming_edges:
                if edge.data.get('type') != 'stall':
                    source_wire = self._get_or_create_wire(edge.source)
                    break

        # No inputs - set to zero
        if source_wire is None:
            source_wire = pyrtl.Const(0, self._get_width(node))

        # For architectural state write nodes, look up stall signal from read node
        if is_arch_state and is_write and stall_wire is None:
            stall_wire = self.register_stalls.get(base_name)

        # Assign value, handling registers specially
        if is_register:
            # For pipeline registers with stall signal:
            # next = stall ? current_value : new_value
            if stall_wire is not None:
                # Match widths for the mux
                source_width = len(source_wire)
                reg_width = len(result_wire)
                if source_width < reg_width:
                    source_wire = source_wire.zero_extended(reg_width)
                elif source_width > reg_width:
                    source_wire = source_wire[:reg_width]
                result_wire.next <<= pyrtl.select(stall_wire, result_wire, source_wire)
            else:
                result_wire.next <<= source_wire
        else:
            result_wire <<= source_wire

    def _generate_validity_bit(self, node: Node):
        """Generate validity bit signal.

        Validity bits are used for pipeline validity tracking.
        If they have incoming edges, follow them (e.g., from flush logic).
        Otherwise, default to constant 1 (always valid).
        """
        result_wire = self._get_or_create_wire(node)
        is_register = isinstance(result_wire, pyrtl.Register)

        source_wire = None

        # Check for incoming edges (e.g., from flush/stall logic)
        for edge in node.incoming_edges:
            edge_type = edge.data.get('type', '')
            if edge_type in ['assignment', 'data', 'operand', 'input', 'validity']:
                source_wire = self._get_or_create_wire(edge.source)
                break

        # If no inputs, default to constant 1 (valid)
        if source_wire is None:
            source_wire = pyrtl.Const(1, 1)

        # Assign value, handling registers specially
        if is_register:
            result_wire.next <<= source_wire
        else:
            result_wire <<= source_wire

    def _generate_stall_controller(self, node: Node):
        """Generate stall controller by ORing all incoming control signals.

        Stall controllers combine multiple hazard detection signals with OR
        to determine if the pipeline stage should stall.
        """
        result_wire = self._get_or_create_wire(node)

        # Collect all incoming control signals
        control_signals = []
        for edge in node.incoming_edges:
            edge_type = edge.data.get('type', '')
            if edge_type == 'control':
                sig = self._get_or_create_wire(edge.source)
                # Ensure single-bit for OR operation
                if len(sig) > 1:
                    # Use reduction OR to convert to single bit
                    sig = sig != 0
                control_signals.append(sig)

        if not control_signals:
            # No inputs - default to no stall (0)
            result_wire <<= pyrtl.Const(0, len(result_wire))
        elif len(control_signals) == 1:
            # Single input - just pass through
            result_wire <<= control_signals[0]
        else:
            # Multiple inputs - OR them all together
            combined = control_signals[0]
            for sig in control_signals[1:]:
                combined = combined | sig
            result_wire <<= combined

    def _generate_sequential_logic(self):
        """Generate register updates."""
        # Process all registers (sorted for determinism)
        for reg_key, reg in sorted(self.registers.items(), key=lambda x: x[0]):
            # Skip registers that have already had their .next set
            if reg_key in self.registers_with_next_set:
                continue

            # The reg_key is the base name (e.g., 'pc')
            # Look for the write node which is either reg_key or reg_key_wr
            node = self.graph.nodes.get(reg_key)
            if not node:
                node = self.graph.nodes.get(f'{reg_key}_wr')
            if not node:
                # Try to find any node with this base name that has incoming assignments
                for nid, n in sorted(self.graph.nodes.items(), key=lambda x: x[0]):
                    if n.data.get('name') == reg_key and n.incoming_edges:
                        # Check if it's a write node (has incoming assignment)
                        has_assignment = any(e.data.get('type') == 'assignment' for e in n.incoming_edges)
                        if has_assignment or nid.endswith('_wr'):
                            node = n
                            break
            if not node:
                continue

            # Find what drives this register
            for edge in node.incoming_edges:
                edge_type = edge.data.get('type', '')
                if edge_type in ['assignment', 'data', 'operand']:
                    source = self._get_or_create_wire(edge.source)
                    # Register update in PyRTL
                    reg.next <<= source
                    break
        
        # NOTE: Memory writes are now handled by _generate_memory_write_port()
        # for memory_write_port nodes. The old ILA-style array_access write
        # handling has been removed because it was incorrectly creating writes
        # for read operations like rf[rs1] and rf[rs2], which corrupted the
        # register file by writing read values back to the source registers.
    
    def generate(self) -> pyrtl.Block:
        """
        Generate PyRTL hardware design from the resource graph.

        Returns:
            The PyRTL Block containing the generated design
        """
        # Reset and start fresh
        pyrtl.reset_working_block()
        
        # Analyze graph structure
        self._analyze_graph()
        
        # Generate constants
        self._generate_constants()
        
        # Generate combinational logic
        self._generate_operations()
        
        # Generate sequential logic
        self._generate_sequential_logic()
        
        # Return the working block
        return pyrtl.working_block()


def generate_pyrtl(graph: ResourceGraph, module_name: str = "processor") -> pyrtl.Block:
    """
    Convenience function to generate PyRTL design from a ResourceGraph.

    Args:
        graph: The ResourceGraph to convert
        module_name: Name for the module (documentation only)

    Returns:
        PyRTL Block containing the generated design
    """
    generator = PyRTLGenerator(graph, module_name)
    return generator.generate()
