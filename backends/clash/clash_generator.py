"""
Clash HDL Backend Generator for ISAComp

This module generates Clash (Haskell-based HDL) code from a ResourceGraph.
Clash is a functional hardware description language that compiles to
Verilog, VHDL, or SystemVerilog.

The generated code uses:
- Clash.Prelude for hardware primitives (Signal, BitVector, etc.)
- Signal types for sequential logic
- Pure functions for combinational logic
- Mealy machines for state machines

Reference: https://clash-lang.org/
"""

from typing import Dict, Set, List, Tuple, Optional
from core.resource_graph import ResourceGraph, Node, Edge
import re


class ClashGenerator:
    """Generates Clash HDL code from a ResourceGraph."""

    def __init__(self, graph: ResourceGraph, module_name: str = "Processor"):
        """
        Initialize the Clash generator.

        Args:
            graph: The ResourceGraph to generate Clash from
            module_name: Name of the top-level module (capitalized for Haskell)
        """
        self.graph = graph
        # Capitalize module name for Haskell conventions
        self.module_name = module_name[0].upper() + module_name[1:] if module_name else "Processor"
        self.lines: List[str] = []

        # Track node types for generation
        self.registers: Set[str] = set()
        self.wires: Set[str] = set()
        self.memories: Dict[str, Tuple[int, int]] = {}  # name -> (width, depth)
        self.pipeline_registers: Set[str] = set()  # Pipeline register node IDs
        self.validity_bits: Set[str] = set()  # Validity bit node IDs
        self.stall_controllers: Set[str] = set()  # Stall controller node IDs

        # Track signal widths
        self.signal_widths: Dict[str, int] = {}

        # Track generated expressions to avoid duplicates
        self.generated_nodes: Set[str] = set()

        # Map node IDs to Clash variable names
        self.node_to_var: Dict[str, str] = {}
        self.var_counter = 0

        # Infer default width from register file
        self.default_width = 32
        rf_node = self.graph.nodes.get('rf')
        if rf_node and rf_node.data.get('bit_width'):
            self.default_width = rf_node.data['bit_width']

        # Detect if this is a pipelined processor
        self.is_pipelined = self._detect_pipeline()

    def _detect_pipeline(self) -> bool:
        """Detect if the graph represents a pipelined processor."""
        for node in self.graph.nodes.values():
            if node.data.get('type') == 'pipeline_register':
                return True
        return False

    def _emit(self, line: str = ""):
        """Emit a line of Clash code."""
        self.lines.append(line)

    def _sanitize_name(self, name: str) -> str:
        """
        Sanitize a name to be a valid Haskell identifier.
        Haskell identifiers must start with lowercase letter.
        """
        # Replace operators with descriptive text
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
        name = name.replace('[', '_')
        name = name.replace(']', '_')
        name = name.replace('\'', '_')
        name = name.replace('.', '_')

        # Replace invalid characters with underscore
        sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', name)

        # Must start with lowercase letter
        if sanitized and sanitized[0].isdigit():
            sanitized = 'v_' + sanitized
        elif sanitized and sanitized[0].isupper():
            sanitized = sanitized[0].lower() + sanitized[1:]

        # Remove consecutive underscores
        sanitized = re.sub(r'_+', '_', sanitized)
        sanitized = sanitized.strip('_')

        if not sanitized:
            sanitized = 'sig'

        return sanitized

    def _get_var_name(self, node_id: str) -> str:
        """Get or create a Clash variable name for a node."""
        if node_id in self.node_to_var:
            return self.node_to_var[node_id]

        var_name = self._sanitize_name(node_id)

        # Ensure uniqueness
        base_name = var_name
        counter = 0
        while var_name in self.node_to_var.values():
            counter += 1
            var_name = f"{base_name}_{counter}"

        self.node_to_var[node_id] = var_name
        return var_name

    def _get_width(self, node: Node) -> int:
        """Determine the bit width of a node's output."""
        if node.id in self.signal_widths:
            return self.signal_widths[node.id]

        node_type = node.data.get('type', '')

        # Check node data for width information
        if 'bit_width' in node.data and node.data['bit_width'] is not None:
            width = node.data['bit_width']
            self.signal_widths[node.id] = width
            return width

        # For bit slices, compute width from range
        if node_type == 'bit_slice':
            if 'expression' in node.data and 'range' in node.data['expression']:
                high_bit, low_bit = node.data['expression']['range']
                width = high_bit - low_bit + 1
                self.signal_widths[node.id] = width
                return width
            # Try parsing from node ID
            match = re.search(r'\[(\d+):(\d+)\]', node.id)
            if match:
                high_bit = int(match.group(1))
                low_bit = int(match.group(2))
                width = high_bit - low_bit + 1
                self.signal_widths[node.id] = width
                return width

        # For literals, infer from value
        if node_type in ['literal', 'binary_literal', 'hex_literal', 'verilog_hex_literal']:
            match = re.match(r"(\d+)'([hbodHBOD])([0-9a-fA-F_]+)", node.id)
            if match:
                width = int(match.group(1))
                self.signal_widths[node.id] = width
                return width
            value = node.data.get('value', 0)
            if isinstance(value, int):
                width = 32  # Default for integer literals
                self.signal_widths[node.id] = width
                return width

        # For concatenations, sum of all part widths
        if node_type in ['concatenation', 'concat']:
            total = 0
            for edge in node.incoming_edges:
                w = self._get_width(edge.source)
                if w is not None:
                    total += w
            if total > 0:
                self.signal_widths[node.id] = total
                return total

        # For repetitions, count * source width
        if node_type == 'repetition':
            count = node.data.get('count', node.data.get('repetitions', 1))
            if node.incoming_edges:
                source_width = self._get_width(next(iter(node.incoming_edges)).source)
                width = count * source_width
                self.signal_widths[node.id] = width
                return width

        # For comparison operations, result is always 1 bit
        if node_type in ['operation', 'comparison']:
            operator = node.data.get('operator', '')
            comparison_ops = ['==', '!=', '<', '>', '<=', '>=', 'eq', 'ne', 'lt', 'gt', 'le', 'ge',
                              '<s', '>s', '<=s', '>=s', '<u', '>u', '<=u', '>=u']
            if operator in comparison_ops:
                self.signal_widths[node.id] = 1
                return 1

        # For logical AND/OR, result is 1 bit
        if node_type in ['logical_and', 'logical_or', 'logical_not']:
            self.signal_widths[node.id] = 1
            return 1

        # For validity bits, always 1 bit
        if node_type == 'validity_bit':
            self.signal_widths[node.id] = 1
            return 1

        # For pipeline registers, infer from input
        if node_type == 'pipeline_register':
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'pipeline_input':
                    width = self._get_width(edge.source)
                    self.signal_widths[node.id] = width
                    return width

        # For variables, follow the source
        if node_type in ['var', 'temp_var']:
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'assignment':
                    width = self._get_width(edge.source)
                    self.signal_widths[node.id] = width
                    return width

        # For array accesses, get width from array
        if node_type == 'array_access':
            for edge in node.incoming_edges:
                if edge.data.get('type') in ['array', 'array_base']:
                    array_node = edge.source
                    array_width = array_node.data.get('bit_width')
                    if array_width:
                        self.signal_widths[node.id] = array_width
                        return array_width

        # Default width
        self.signal_widths[node.id] = self.default_width
        return self.default_width

    def _clash_type(self, width: int) -> str:
        """Convert bit width to Clash type string."""
        if width == 1:
            return "Bit"
        else:
            return f"BitVector {width}"

    def _clash_signal_type(self, width: int) -> str:
        """Convert bit width to Clash Signal type string."""
        if width == 1:
            return "Signal dom Bit"
        else:
            return f"Signal dom (BitVector {width})"

    def _analyze_graph(self):
        """Analyze the graph to categorize nodes and determine signal properties."""
        for node_id, node in self.graph.nodes.items():
            node_type = node.data.get('type', '')

            # Track pipeline-specific nodes
            if node_type == 'pipeline_register':
                self.pipeline_registers.add(node_id)
                self.registers.add(node_id)
            elif node_type == 'validity_bit':
                self.validity_bits.add(node_id)
                self.registers.add(node_id)
            elif node_type == 'pipeline_stall_controller':
                self.stall_controllers.add(node_id)
                self.wires.add(node_id)

            # Determine if this is a register or wire
            elif node.is_arch_state or node.is_uarch_state:
                self.registers.add(node_id)
            elif node_type in ['operation', 'var', 'literal', 'multiplexer',
                              'ternary_op', 'comparison', 'bit_slice']:
                self.wires.add(node_id)

            # Track memory arrays
            if node_type in ['isa_state', 'isa_state mem']:
                if 'array_size' in node.data:
                    width = self._get_width(node)
                    depth = node.data['array_size']
                    self.memories[node_id] = (width, depth)
                    self.registers.add(node_id)
                elif 'array_depth' in node.data and node.data['array_depth'] is not None:
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

    def _generate_header(self):
        """Generate Clash module header and imports."""
        self._emit("{-# LANGUAGE DataKinds #-}")
        self._emit("{-# LANGUAGE TypeApplications #-}")
        self._emit("{-# LANGUAGE TypeFamilies #-}")
        self._emit("{-# LANGUAGE FlexibleContexts #-}")
        self._emit("{-# LANGUAGE NoImplicitPrelude #-}")
        self._emit("{-# LANGUAGE NumericUnderscores #-}")
        self._emit("{-# LANGUAGE ScopedTypeVariables #-}")
        self._emit("{-# LANGUAGE TypeOperators #-}")
        self._emit("{-# LANGUAGE DeriveGeneric #-}")
        self._emit("{-# LANGUAGE DeriveAnyClass #-}")
        self._emit("{-# LANGUAGE BinaryLiterals #-}")
        self._emit("")
        self._emit(f"module {self.module_name} where")
        self._emit("")
        self._emit("import Clash.Prelude")
        self._emit("import Clash.Explicit.Prelude (register)")
        self._emit("import qualified Data.List as L")
        self._emit("")

    def _generate_type_aliases(self):
        """Generate type aliases for the processor."""
        self._emit("-- Type aliases (using Word32 to avoid conflict with Clash.Prelude.Word)")
        self._emit(f"type Word32 = BitVector {self.default_width}")
        self._emit(f"type Addr = BitVector {self.default_width}")

        # Register file type
        rf_node = self.graph.nodes.get('rf')
        if rf_node:
            rf_depth = rf_node.data.get('array_depth', 5)
            rf_size = 2 ** rf_depth
            self._emit(f"type RegFile = Vec {rf_size} Word32")

        self._emit("")

    def _get_literal_value(self, node: Node) -> Tuple[int, int]:
        """Get the value and width from a literal node."""
        node_type = node.data.get('type', '')
        value = node.data.get('value', 0)
        width = self._get_width(node)

        # Parse Verilog-style literal from node ID
        match = re.match(r"(\d+)'([hbodHBOD])([0-9a-fA-F_]+)", node.id)
        if match:
            width = int(match.group(1))
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
        elif isinstance(value, str):
            if value.startswith('0x') or value.startswith('0X'):
                value = int(value, 16)
            elif value.startswith('0b') or value.startswith('0B'):
                value = int(value, 2)
            else:
                try:
                    value = int(value)
                except ValueError:
                    value = 0

        return value, width

    def _generate_expression(self, node: Node, visited: Optional[Set[str]] = None) -> str:
        """
        Generate a Clash expression for a node (recursive).

        Returns the Clash expression string for this node.
        """
        if visited is None:
            visited = set()

        if node.id in visited:
            # Cycle detected - return variable reference
            return self._get_var_name(node.id)

        visited.add(node.id)
        node_type = node.data.get('type', '')

        # Literal values
        if node_type in ['literal', 'binary_literal', 'hex_literal', 'verilog_hex_literal', 'verilog_binary_literal', 'constant']:
            value, width = self._get_literal_value(node)
            if width == 1:
                return str(value)
            else:
                return f"({value} :: BitVector {width})"

        # Variable/alias
        if node_type in ['var', 'temp_var']:
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'assignment':
                    return self._generate_expression(edge.source, visited)
            # No assignment found
            if node.incoming_edges:
                return self._generate_expression(list(node.incoming_edges)[0].source, visited)
            return self._get_var_name(node.id)

        # ISA state read (register read)
        if node_type.startswith('isa_state') and not node.data.get('is_memory', False):
            return self._get_var_name(node.id)

        # Array access (memory read)
        if node_type == 'array_access':
            return self._generate_array_access_expr(node, visited)

        # Bit slice
        if node_type == 'bit_slice':
            return self._generate_bit_slice_expr(node, visited)

        # Operations
        if node_type == 'operation':
            return self._generate_operation_expr(node, visited)

        # Comparison
        if node_type == 'comparison':
            return self._generate_comparison_expr(node, visited)

        # Ternary (mux)
        if node_type in ['ternary', 'ternary_op']:
            return self._generate_ternary_expr(node, visited)

        # Multiplexer
        if node_type in ['mux', 'multiplexer']:
            return self._generate_mux_expr(node, visited)

        # Concatenation
        if node_type in ['concatenation', 'concat']:
            return self._generate_concat_expr(node, visited)

        # Repetition (for sign extension)
        if node_type == 'repetition':
            return self._generate_repetition_expr(node, visited)

        # Logical operations
        if node_type == 'logical_and':
            return self._generate_logical_and_expr(node, visited)
        if node_type == 'logical_or':
            return self._generate_logical_or_expr(node, visited)
        if node_type == 'logical_not':
            return self._generate_logical_not_expr(node, visited)

        # Enable (AND of decode conditions)
        if node_type in ['enable', 'instruction_enable']:
            return self._generate_enable_expr(node, visited)

        # Zero extend
        if node_type == 'zero_extend':
            return self._generate_zero_extend_expr(node, visited)

        # Sign extend
        if node_type == 'sign_extend':
            return self._generate_sign_extend_expr(node, visited)

        # Pipeline register - return the registered value
        if node_type == 'pipeline_register':
            return self._get_var_name(node.id)

        # Validity bit
        if node_type == 'validity_bit':
            return self._get_var_name(node.id)

        # Pipeline stall controller
        if node_type == 'pipeline_stall_controller':
            return self._generate_stall_controller_expr(node, visited)

        # Memory write port - no expression, handled in state update
        if node_type == 'memory_write_port':
            return "()"

        # Byte enable computation
        if node_type == 'byte_enable_computation':
            for edge in node.incoming_edges:
                return self._generate_expression(edge.source, visited)
            return "0xF"

        # Control signal
        if node_type == 'control_signal':
            return self._get_var_name(node.id)

        # Default: return variable name
        return self._get_var_name(node.id)

    def _generate_array_access_expr(self, node: Node, visited: Set[str]) -> str:
        """Generate expression for array access (memory read)."""
        array_node = None
        index_node = None

        for edge in node.incoming_edges:
            edge_type = edge.data.get('type', '')
            if edge_type in ['array', 'array_base'] or edge.source.data.get('is_memory'):
                array_node = edge.source
            elif edge_type == 'array_index' or (edge_type != 'array' and edge_type != 'array_base'):
                if index_node is None:
                    index_node = edge.source

        if not array_node or not index_node:
            return self._get_var_name(node.id)

        array_name = self._get_var_name(array_node.id)
        index_expr = self._generate_expression(index_node, visited)

        # Use Clash's array indexing: array !! index
        # For memories with address width transformation, shift index
        port_width = array_node.data.get('port_width')
        if port_width:
            shift_amount = 3 if port_width == 64 else 2
            return f"({array_name} !! (unpack (shiftR {index_expr} {shift_amount})))"

        return f"({array_name} !! (unpack {index_expr}))"

    def _generate_bit_slice_expr(self, node: Node, visited: Set[str]) -> str:
        """Generate expression for bit slice."""
        if 'expression' in node.data and 'range' in node.data['expression']:
            high_bit, low_bit = node.data['expression']['range']
        else:
            match = re.search(r'\[(\d+):(\d+)\]', node.id)
            if match:
                high_bit = int(match.group(1))
                low_bit = int(match.group(2))
            else:
                return self._get_var_name(node.id)

        source_edge = next((e for e in node.incoming_edges
                           if e.data.get('type') in ['operand', 'bit_access', 'source']), None)
        if not source_edge:
            if node.incoming_edges:
                source_edge = list(node.incoming_edges)[0]
            else:
                return self._get_var_name(node.id)

        source_expr = self._generate_expression(source_edge.source, visited)
        source_width = self._get_width(source_edge.source)
        width = high_bit - low_bit + 1

        # Use Clash's slice function or bit extraction
        # slice @n @m = extract bits [n-1:m] (0-indexed from LSB)
        return f"(slice @{high_bit} @{low_bit} {source_expr})"

    def _generate_operation_expr(self, node: Node, visited: Set[str]) -> str:
        """Generate expression for arithmetic/logic operation."""
        operator = node.data.get('operator', '') or node.data.get('operation', '')

        # Get operands
        operands = []
        left_operand = None
        right_operand = None

        for edge in node.incoming_edges:
            edge_type = edge.data.get('type', '')
            pos = edge.data.get('position')
            if edge_type == 'left_operand' or pos == 'left':
                left_operand = self._generate_expression(edge.source, visited)
            elif edge_type == 'right_operand' or pos == 'right':
                right_operand = self._generate_expression(edge.source, visited)
            elif edge_type == 'operand':
                operands.append(self._generate_expression(edge.source, visited))

        if left_operand is not None:
            operands = [left_operand]
            if right_operand is not None:
                operands.append(right_operand)
        elif not operands:
            # Sort by position
            sorted_edges = sorted(node.incoming_edges,
                                 key=lambda e: e.data.get('position', 999) if isinstance(e.data.get('position'), int) else 999)
            for edge in sorted_edges:
                operands.append(self._generate_expression(edge.source, visited))

        if len(operands) == 0:
            return self._get_var_name(node.id)

        if len(operands) == 1:
            # Unary operation
            if operator in ['!', 'not', 'logical_not']:
                return f"(complement {operands[0]})"
            elif operator in ['~', 'bitwise_not', 'invert']:
                return f"(complement {operands[0]})"
            else:
                return operands[0]

        # Binary operations
        op_a, op_b = operands[0], operands[1]

        # Map operators to Clash
        op_map = {
            '+': '+',
            'add': '+',
            '-': '-',
            'sub': '-',
            '*': '*',
            'mul': '*',
            '&': '.&.',
            'and': '.&.',
            '|': '.|.',
            'or': '.|.',
            '^': 'xor',
            'xor': 'xor',
            '<<': 'shiftL',
            'shl': 'shiftL',
            '>>': 'shiftR',
            'shr': 'shiftR',
            '>>>': 'shiftRA',
            'ashr': 'shiftRA',
        }

        if operator in op_map:
            clash_op = op_map[operator]
            if clash_op in ['+', '-', '*', '.&.', '.|.']:
                return f"({op_a} {clash_op} {op_b})"
            elif clash_op == 'xor':
                return f"(xor {op_a} {op_b})"
            elif clash_op in ['shiftL', 'shiftR', 'shiftRA']:
                return f"({clash_op} {op_a} (unpack {op_b}))"

        # Comparison operators - generate comparison expression
        if operator in ['==', 'eq']:
            return f"(boolToBit ({op_a} == {op_b}))"
        elif operator in ['!=', 'ne']:
            return f"(boolToBit ({op_a} /= {op_b}))"
        elif operator in ['<', 'lt', '<u', 'ult']:
            return f"(boolToBit ({op_a} < {op_b}))"
        elif operator in ['<=', 'le', '<=u', 'ule']:
            return f"(boolToBit ({op_a} <= {op_b}))"
        elif operator in ['>', 'gt', '>u', 'ugt']:
            return f"(boolToBit ({op_a} > {op_b}))"
        elif operator in ['>=', 'ge', '>=u', 'uge']:
            return f"(boolToBit ({op_a} >= {op_b}))"
        # Signed comparisons - use signed conversion
        elif operator in ['<s', 'slt']:
            return f"(boolToBit (unpack @(Signed {self.default_width}) {op_a} < unpack @(Signed {self.default_width}) {op_b}))"
        elif operator in ['<=s', 'sle']:
            return f"(boolToBit (unpack @(Signed {self.default_width}) {op_a} <= unpack @(Signed {self.default_width}) {op_b}))"
        elif operator in ['>s', 'sgt']:
            return f"(boolToBit (unpack @(Signed {self.default_width}) {op_a} > unpack @(Signed {self.default_width}) {op_b}))"
        elif operator in ['>=s', 'sge']:
            return f"(boolToBit (unpack @(Signed {self.default_width}) {op_a} >= unpack @(Signed {self.default_width}) {op_b}))"

        # Logical operators
        elif operator in ['&&', 'logical_and']:
            return f"({op_a} .&. {op_b})"
        elif operator in ['||', 'logical_or']:
            return f"({op_a} .|. {op_b})"

        return self._get_var_name(node.id)

    def _generate_comparison_expr(self, node: Node, visited: Set[str]) -> str:
        """Generate expression for comparison operation."""
        operator = node.data.get('operator', '') or node.data.get('operation', '') or '=='

        operands = []
        for edge in sorted(node.incoming_edges,
                          key=lambda e: (0 if e.data.get('position') == 'left' or e.data.get('type') == 'left_operand' else 1)):
            edge_type = edge.data.get('type', '')
            if edge_type in ['operand', 'left_operand', 'right_operand']:
                operands.append(self._generate_expression(edge.source, visited))

        if len(operands) < 2:
            # Try to get compare value from node data
            compare_value = node.data.get('compare_value')
            if compare_value is not None and len(operands) == 1:
                width = self._get_width(node)
                operands.append(f"({compare_value} :: BitVector {width})")

        if len(operands) < 2:
            return self._get_var_name(node.id)

        op_a, op_b = operands[0], operands[1]

        # Map comparison operators
        if operator in ['==', 'eq']:
            return f"(boolToBit ({op_a} == {op_b}))"
        elif operator in ['!=', 'ne']:
            return f"(boolToBit ({op_a} /= {op_b}))"
        elif operator in ['<', 'lt', '<u', 'ult']:
            return f"(boolToBit ({op_a} < {op_b}))"
        elif operator in ['<=', 'le', '<=u', 'ule']:
            return f"(boolToBit ({op_a} <= {op_b}))"
        elif operator in ['>', 'gt', '>u', 'ugt']:
            return f"(boolToBit ({op_a} > {op_b}))"
        elif operator in ['>=', 'ge', '>=u', 'uge']:
            return f"(boolToBit ({op_a} >= {op_b}))"

        return f"(boolToBit ({op_a} == {op_b}))"

    def _generate_ternary_expr(self, node: Node, visited: Set[str]) -> str:
        """Generate expression for ternary (conditional) operation."""
        cond = None
        true_val = None
        false_val = None

        for edge in node.incoming_edges:
            edge_type = edge.data.get('edge_type') or edge.data.get('type', '')
            if edge_type in ['condition', 'ternary_condition']:
                cond = self._generate_expression(edge.source, visited)
            elif edge_type in ['true_value', 'ternary_true']:
                true_val = self._generate_expression(edge.source, visited)
            elif edge_type in ['false_value', 'ternary_false']:
                false_val = self._generate_expression(edge.source, visited)

        if cond is not None and true_val is not None and false_val is not None:
            # Use Clash's mux: mux condition falseCase trueCase
            # Note: mux takes false case first!
            return f"(mux (bitToBool {cond}) {false_val} {true_val})"

        return self._get_var_name(node.id)

    def _generate_mux_expr(self, node: Node, visited: Set[str]) -> str:
        """Generate expression for multiplexer."""
        default_value = None
        mux_inputs = []

        for edge in node.incoming_edges:
            edge_type = edge.data.get('edge_type') or edge.data.get('type', '')
            if edge_type in ['mux_default', 'mux_default_input']:
                default_value = self._generate_expression(edge.source, visited)
            elif edge_type in ['mux_input', 'mux_value']:
                input_idx = edge.data.get('input_index', len(mux_inputs))
                select_idx = edge.data.get('select_index', input_idx)
                mux_inputs.append((select_idx, edge))

        # Get select signals
        selects = []
        for edge in node.incoming_edges:
            edge_type = edge.data.get('edge_type') or edge.data.get('type', '')
            if edge_type in ['mux_select', 'mux_condition']:
                select_idx = edge.data.get('select_index', len(selects))
                selects.append((select_idx, self._generate_expression(edge.source, visited)))

        if not mux_inputs:
            if default_value:
                return default_value
            return self._get_var_name(node.id)

        # Sort by index
        mux_inputs.sort(key=lambda x: x[0])
        selects.sort(key=lambda x: x[0])

        # Build cascaded mux
        width = self._get_width(node)
        if default_value is None:
            default_value = f"(0 :: BitVector {width})"

        result = default_value
        for i, (idx, edge) in enumerate(mux_inputs):
            if i < len(selects):
                sel = selects[i][1]
            else:
                continue
            value = self._generate_expression(edge.source, visited)
            result = f"(mux (bitToBool {sel}) {result} {value})"

        return result

    def _generate_concat_expr(self, node: Node, visited: Set[str]) -> str:
        """Generate expression for concatenation."""
        parts = []
        for edge in sorted(node.incoming_edges, key=lambda e: e.data.get('position', 0)):
            parts.append(self._generate_expression(edge.source, visited))

        if not parts:
            return self._get_var_name(node.id)

        if len(parts) == 1:
            return parts[0]

        # Clash concatenation: use ++#
        result = parts[0]
        for part in parts[1:]:
            result = f"({result} ++# {part})"

        return result

    def _generate_repetition_expr(self, node: Node, visited: Set[str]) -> str:
        """Generate expression for bit repetition."""
        count = node.data.get('count', node.data.get('repetitions', 1))

        source_edge = next((e for e in node.incoming_edges), None)
        if not source_edge:
            return self._get_var_name(node.id)

        source_expr = self._generate_expression(source_edge.source, visited)

        # Use Clash's replicate for bit repetition
        return f"(pack (repeat @{count} (unpack {source_expr})))"

    def _generate_logical_and_expr(self, node: Node, visited: Set[str]) -> str:
        """Generate expression for logical AND."""
        inputs = []
        for edge in node.incoming_edges:
            edge_type = edge.data.get('type', '')
            if edge_type in ['logic_input', 'operand', 'left_operand', 'right_operand']:
                inputs.append(self._generate_expression(edge.source, visited))

        if not inputs:
            return "1"
        if len(inputs) == 1:
            return inputs[0]

        result = inputs[0]
        for inp in inputs[1:]:
            result = f"({result} .&. {inp})"
        return result

    def _generate_logical_or_expr(self, node: Node, visited: Set[str]) -> str:
        """Generate expression for logical OR."""
        inputs = []
        for edge in node.incoming_edges:
            edge_type = edge.data.get('type', '')
            if edge_type in ['logic_input', 'operand', 'left_operand', 'right_operand']:
                inputs.append(self._generate_expression(edge.source, visited))

        if not inputs:
            return "0"
        if len(inputs) == 1:
            return inputs[0]

        result = inputs[0]
        for inp in inputs[1:]:
            result = f"({result} .|. {inp})"
        return result

    def _generate_logical_not_expr(self, node: Node, visited: Set[str]) -> str:
        """Generate expression for logical NOT."""
        for edge in node.incoming_edges:
            edge_type = edge.data.get('type', '')
            if edge_type in ['logic_input', 'operand']:
                inp = self._generate_expression(edge.source, visited)
                return f"(complement {inp})"
        return self._get_var_name(node.id)

    def _generate_enable_expr(self, node: Node, visited: Set[str]) -> str:
        """Generate expression for instruction enable signal."""
        inputs = []
        for edge in node.incoming_edges:
            inputs.append(self._generate_expression(edge.source, visited))

        if not inputs:
            return "1"
        if len(inputs) == 1:
            return inputs[0]

        result = inputs[0]
        for inp in inputs[1:]:
            result = f"({result} .&. {inp})"
        return result

    def _generate_zero_extend_expr(self, node: Node, visited: Set[str]) -> str:
        """Generate expression for zero extension."""
        target_width = self._get_width(node)

        for edge in node.incoming_edges:
            source_expr = self._generate_expression(edge.source, visited)
            source_width = self._get_width(edge.source)

            if source_width < target_width:
                # Zero extend
                return f"(zeroExtend {source_expr} :: BitVector {target_width})"
            else:
                return source_expr

        return self._get_var_name(node.id)

    def _generate_sign_extend_expr(self, node: Node, visited: Set[str]) -> str:
        """Generate expression for sign extension."""
        target_width = self._get_width(node)

        for edge in node.incoming_edges:
            source_expr = self._generate_expression(edge.source, visited)
            source_width = self._get_width(edge.source)

            if source_width < target_width:
                # Sign extend via conversion to Signed and back
                return f"(pack (resize (unpack @(Signed {source_width}) {source_expr}) :: Signed {target_width}))"
            else:
                return source_expr

        return self._get_var_name(node.id)

    def _generate_stall_controller_expr(self, node: Node, visited: Set[str]) -> str:
        """Generate expression for stall controller."""
        inputs = []
        for edge in node.incoming_edges:
            edge_type = edge.data.get('type', '')
            if edge_type in ['control', 'stall_input', 'hazard_input', 'operand']:
                inputs.append(self._generate_expression(edge.source, visited))

        if not inputs:
            return "0"
        if len(inputs) == 1:
            return inputs[0]

        # OR all inputs together
        result = inputs[0]
        for inp in inputs[1:]:
            result = f"({result} .|. {inp})"
        return result

    def _find_write_node(self, base_name: str) -> Optional[Node]:
        """Find the write node for a register."""
        # Try different naming patterns
        candidates = [
            f"{base_name}_wr",
            base_name,
        ]

        for name in candidates:
            node = self.graph.nodes.get(name)
            if node:
                # Check if it has incoming assignment
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'assignment':
                        return node

        return None

    def _find_write_source(self, node: Node) -> Optional[Node]:
        """Find the source of a write (what value is being written)."""
        for edge in node.incoming_edges:
            if edge.data.get('type') == 'assignment':
                return edge.source
        return None

    def _generate_state_record(self):
        """Generate the processor state record type."""
        self._emit("-- Processor state record")
        self._emit("data ProcessorState = ProcessorState")
        self._emit("  { stPc :: Word32")

        # Register file
        if 'rf' in self.memories:
            rf_width, rf_depth = self.memories['rf']
            self._emit(f"  , stRf :: Vec {rf_depth} Word32")

        # Data memory
        for mem_name in ['dmem', 'umem']:
            if mem_name in self.memories:
                mem_width, mem_depth = self.memories[mem_name]
                self._emit(f"  , st{mem_name.capitalize()} :: Vec {mem_depth} (BitVector {mem_width})")
                break

        # Instruction memory
        if 'imem' in self.memories:
            imem_width, imem_depth = self.memories['imem']
            self._emit(f"  , stImem :: Vec {imem_depth} (BitVector {imem_width})")

        # Pipeline registers (only if pipelined)
        if self.is_pipelined:
            for pipe_reg in sorted(self.pipeline_registers):
                var_name = self._get_var_name(pipe_reg)
                width = self._get_width(self.graph.nodes[pipe_reg])
                self._emit(f"  , stPipe{var_name} :: BitVector {width}")

            # Validity bits
            for valid_bit in sorted(self.validity_bits):
                var_name = self._get_var_name(valid_bit)
                self._emit(f"  , stValid{var_name} :: Bit")

        self._emit("  } deriving (Generic, NFDataX)")
        self._emit("")

    def _generate_initial_state(self):
        """Generate initial state function."""
        self._emit("-- Initial processor state")
        self._emit("initialState :: ProcessorState")
        self._emit("initialState = ProcessorState")
        self._emit("  { stPc = 0")

        if 'rf' in self.memories:
            _, rf_depth = self.memories['rf']
            self._emit(f"  , stRf = repeat 0")

        for mem_name in ['dmem', 'umem']:
            if mem_name in self.memories:
                self._emit(f"  , st{mem_name.capitalize()} = repeat 0")
                break

        if 'imem' in self.memories:
            self._emit(f"  , stImem = repeat 0")

        # Pipeline registers (initialize to 0)
        if self.is_pipelined:
            for pipe_reg in sorted(self.pipeline_registers):
                var_name = self._get_var_name(pipe_reg)
                self._emit(f"  , stPipe{var_name} = 0")

            # Validity bits (initialize to 1 = valid)
            for valid_bit in sorted(self.validity_bits):
                var_name = self._get_var_name(valid_bit)
                self._emit(f"  , stValid{var_name} = 1")

        self._emit("  }")
        self._emit("")

    def _generate_transition_function(self):
        """Generate the processor transition function (Mealy machine)."""
        self._emit("-- Processor transition function")
        self._emit("processorT :: ProcessorState -> () -> (ProcessorState, Word32)")
        self._emit("processorT state _ = (state', pc)")
        self._emit("  where")

        # Extract current state
        self._emit("    -- Current state")
        self._emit("    pc = stPc state")

        if 'rf' in self.memories:
            self._emit("    rf = stRf state")

        for mem_name in ['dmem', 'umem']:
            if mem_name in self.memories:
                self._emit(f"    {mem_name} = st{mem_name.capitalize()} state")
                break

        if 'imem' in self.memories:
            self._emit("    imem = stImem state")

        self._emit("")

        # Generate instruction fetch
        self._emit("    -- Instruction fetch")
        imem_name = 'umem' if 'umem' in self.memories else 'imem' if 'imem' in self.memories else 'dmem'
        self._emit(f"    pc_word_addr = resize (shiftR pc 2) :: BitVector 13")
        self._emit(f"    instr = {imem_name} !! (fromIntegral pc_word_addr)")
        self._emit("")

        # Generate decode logic using Clash's slice with SNat indices (d prefix)
        self._emit("    -- Decode fields")
        self._emit("    opcode = slice d6 d0 instr")
        self._emit("    rd = slice d11 d7 instr")
        self._emit("    funct3 = slice d14 d12 instr")
        self._emit("    rs1 = slice d19 d15 instr")
        self._emit("    rs2 = slice d24 d20 instr")
        self._emit("    funct7 = slice d31 d25 instr")
        self._emit("")

        # Generate intermediate computations
        self._emit("    -- Register reads")
        self._emit("    rs1_data = rf !! (fromIntegral rs1)")
        self._emit("    rs2_data = rf !! (fromIntegral rs2)")
        self._emit("")

        # Generate immediate decoding
        self._emit("    -- Immediate extraction (using specialized sext functions)")
        self._emit("    imm_i = sext12to32 (slice d31 d20 instr)")
        self._emit("    imm_s = sext12to32 ((slice d31 d25 instr) ++# (slice d11 d7 instr))")
        self._emit("    imm_b = sext13to32 ((slice d31 d31 instr) ++# (slice d7 d7 instr) ++# (slice d30 d25 instr) ++# (slice d11 d8 instr) ++# (0 :: BitVector 1))")
        self._emit("    imm_u = (slice d31 d12 instr) ++# (0 :: BitVector 12)")
        self._emit("    imm_j = sext21to32 ((slice d31 d31 instr) ++# (slice d19 d12 instr) ++# (slice d20 d20 instr) ++# (slice d30 d21 instr) ++# (0 :: BitVector 1))")
        self._emit("")

        # Generate ALU operations
        self._emit("    -- ALU operations (R-type)")
        self._emit("    alu_add = rs1_data + rs2_data")
        self._emit("    alu_sub = rs1_data - rs2_data")
        self._emit("    alu_and = rs1_data .&. rs2_data")
        self._emit("    alu_or = rs1_data .|. rs2_data")
        self._emit("    alu_xor = xor rs1_data rs2_data")
        self._emit("    alu_sll = shiftL rs1_data (fromIntegral (resize rs2_data :: BitVector 5))")
        self._emit("    alu_srl = shiftR rs1_data (fromIntegral (resize rs2_data :: BitVector 5))")
        self._emit("    -- Arithmetic right shift: replicate sign bit for the shifted positions")
        self._emit("    alu_sra_shamt = fromIntegral (resize rs2_data :: BitVector 5)")
        self._emit("    alu_sra = shiftR rs1_data alu_sra_shamt .|. (if testBit rs1_data 31 then complement (shiftR (complement 0) alu_sra_shamt) else 0)")
        self._emit("    -- Signed comparison: XOR the sign bits to handle different sign cases")
        self._emit("    alu_slt_diff_signs = testBit rs1_data 31 && not (testBit rs2_data 31)  -- rs1 negative, rs2 positive")
        self._emit("    alu_slt_same_signs = testBit rs1_data 31 == testBit rs2_data 31 && rs1_data < rs2_data")
        self._emit("    alu_slt = if alu_slt_diff_signs || alu_slt_same_signs then 1 else 0")
        self._emit("    alu_sltu = if rs1_data < rs2_data then 1 else 0")
        self._emit("")

        self._emit("    -- ALU operations (I-type)")
        self._emit("    shamt = resize (slice d24 d20 instr) :: BitVector 5")
        self._emit("    alu_addi = rs1_data + imm_i")
        self._emit("    alu_andi = rs1_data .&. imm_i")
        self._emit("    alu_ori = rs1_data .|. imm_i")
        self._emit("    alu_xori = xor rs1_data imm_i")
        self._emit("    -- Signed comparison immediate")
        self._emit("    alu_slti_diff_signs = testBit rs1_data 31 && not (testBit imm_i 31)")
        self._emit("    alu_slti_same_signs = testBit rs1_data 31 == testBit imm_i 31 && rs1_data < imm_i")
        self._emit("    alu_slti = if alu_slti_diff_signs || alu_slti_same_signs then 1 else 0")
        self._emit("    alu_sltiu = if rs1_data < imm_i then 1 else 0")
        self._emit("    alu_slli = shiftL rs1_data (fromIntegral shamt)")
        self._emit("    alu_srli = shiftR rs1_data (fromIntegral shamt)")
        self._emit("    -- Arithmetic right shift immediate")
        self._emit("    alu_srai_shamt = fromIntegral shamt")
        self._emit("    alu_srai = shiftR rs1_data alu_srai_shamt .|. (if testBit rs1_data 31 then complement (shiftR (complement 0) alu_srai_shamt) else 0)")
        self._emit("")

        # Opcode decode
        self._emit("    -- Opcode decode")
        self._emit("    is_rtype = opcode == 0b0110011")
        self._emit("    is_itype = opcode == 0b0010011")
        self._emit("    is_load = opcode == 0b0000011")
        self._emit("    is_store = opcode == 0b0100011")
        self._emit("    is_branch = opcode == 0b1100011")
        self._emit("    is_jal = opcode == 0b1101111")
        self._emit("    is_jalr = opcode == 0b1100111")
        self._emit("    is_lui = opcode == 0b0110111")
        self._emit("    is_auipc = opcode == 0b0010111")
        self._emit("")

        # Generate ALU result selection (using if-then-else for synthesizable patterns)
        self._emit("    -- R-type ALU result")
        self._emit("    rtype_result")
        self._emit("      | funct3 == 0 && funct7 == 0 = alu_add")
        self._emit("      | funct3 == 0 && funct7 == 32 = alu_sub")
        self._emit("      | funct3 == 7 && funct7 == 0 = alu_and")
        self._emit("      | funct3 == 6 && funct7 == 0 = alu_or")
        self._emit("      | funct3 == 4 && funct7 == 0 = alu_xor")
        self._emit("      | funct3 == 1 && funct7 == 0 = alu_sll")
        self._emit("      | funct3 == 5 && funct7 == 0 = alu_srl")
        self._emit("      | funct3 == 5 && funct7 == 32 = alu_sra")
        self._emit("      | funct3 == 2 && funct7 == 0 = alu_slt")
        self._emit("      | funct3 == 3 && funct7 == 0 = alu_sltu")
        self._emit("      | otherwise = 0")
        self._emit("")

        self._emit("    -- I-type ALU result")
        self._emit("    itype_result")
        self._emit("      | funct3 == 0 = alu_addi")
        self._emit("      | funct3 == 7 = alu_andi")
        self._emit("      | funct3 == 6 = alu_ori")
        self._emit("      | funct3 == 4 = alu_xori")
        self._emit("      | funct3 == 2 = alu_slti")
        self._emit("      | funct3 == 3 = alu_sltiu")
        self._emit("      | funct3 == 1 = alu_slli")
        self._emit("      | funct3 == 5 = if testBit funct7 5 then alu_srai else alu_srli")
        self._emit("      | otherwise = 0")
        self._emit("")

        # Memory access
        self._emit("    -- Memory address calculation")
        self._emit("    mem_addr = rs1_data + imm_i")
        self._emit("    store_addr = rs1_data + imm_s")
        self._emit("    mem_word_idx = shiftR mem_addr 2")
        self._emit("    store_word_idx = shiftR store_addr 2")
        self._emit("")

        self._emit("    -- Memory read (for loads)")
        self._emit("    mem_word_addr = resize (shiftR mem_addr 2) :: BitVector 13")
        self._emit("    mem_data = umem !! (fromIntegral mem_word_addr)")
        self._emit("")

        self._emit("    -- Byte/halfword extraction based on address alignment (using BitVector comparisons)")
        self._emit("    byte_offset_bits = slice d1 d0 mem_addr")
        self._emit("    lb_byte = if byte_offset_bits == 0b00 then slice d7 d0 mem_data")
        self._emit("              else if byte_offset_bits == 0b01 then slice d15 d8 mem_data")
        self._emit("              else if byte_offset_bits == 0b10 then slice d23 d16 mem_data")
        self._emit("              else slice d31 d24 mem_data")
        self._emit("    lb_data = sext8to32 lb_byte")
        self._emit("    lbu_data = zeroExtend lb_byte")
        self._emit("    half_offset_bit = slice d1 d1 mem_addr")
        self._emit("    lh_half = if half_offset_bit == 0")
        self._emit("              then slice d15 d0 mem_data")
        self._emit("              else slice d31 d16 mem_data")
        self._emit("    lh_data = sext16to32 lh_half")
        self._emit("    lhu_data = zeroExtend lh_half")
        self._emit("")

        self._emit("    -- Load result selection")
        self._emit("    load_result")
        self._emit("      | funct3 == 0 = lb_data    -- LB")
        self._emit("      | funct3 == 1 = lh_data    -- LH")
        self._emit("      | funct3 == 2 = mem_data   -- LW")
        self._emit("      | funct3 == 4 = lbu_data   -- LBU")
        self._emit("      | funct3 == 5 = lhu_data   -- LHU")
        self._emit("      | otherwise = 0")
        self._emit("")

        # Branch conditions
        self._emit("    -- Branch condition evaluation")
        self._emit("    branch_eq = rs1_data == rs2_data")
        self._emit("    -- Signed comparison for branch: use same logic as alu_slt")
        self._emit("    branch_lt_diff_signs = testBit rs1_data 31 && not (testBit rs2_data 31)")
        self._emit("    branch_lt_same_signs = testBit rs1_data 31 == testBit rs2_data 31 && rs1_data < rs2_data")
        self._emit("    branch_lt = branch_lt_diff_signs || branch_lt_same_signs")
        self._emit("    branch_ltu = rs1_data < rs2_data")
        self._emit("")

        self._emit("    -- Branch taken")
        self._emit("    branch_taken")
        self._emit("      | funct3 == 0 = branch_eq       -- BEQ")
        self._emit("      | funct3 == 1 = not branch_eq   -- BNE")
        self._emit("      | funct3 == 4 = branch_lt       -- BLT")
        self._emit("      | funct3 == 5 = not branch_lt   -- BGE")
        self._emit("      | funct3 == 6 = branch_ltu      -- BLTU")
        self._emit("      | funct3 == 7 = not branch_ltu  -- BGEU")
        self._emit("      | otherwise = False")
        self._emit("")

        # Generate PC update logic
        self._emit("    -- PC calculation")
        self._emit("    pc_plus_4 = pc + 4")
        self._emit("    branch_target = pc + imm_b")
        self._emit("    jal_target = pc + imm_j")
        self._emit("    jalr_target = (rs1_data + imm_i) .&. complement 1  -- Clear LSB")
        self._emit("")

        self._emit("    -- PC update")
        self._emit("    pc_next")
        self._emit("      | is_jal = jal_target")
        self._emit("      | is_jalr = jalr_target")
        self._emit("      | is_branch && branch_taken = branch_target")
        self._emit("      | otherwise = pc_plus_4")
        self._emit("")

        # Register write data
        self._emit("    -- Register write data selection")
        self._emit("    rd_data")
        self._emit("      | is_lui = imm_u")
        self._emit("      | is_auipc = pc + imm_u")
        self._emit("      | is_jal || is_jalr = pc_plus_4  -- Return address")
        self._emit("      | is_load = load_result")
        self._emit("      | is_itype = itype_result")
        self._emit("      | is_rtype = rtype_result")
        self._emit("      | otherwise = 0")
        self._emit("")

        self._emit("    -- Register write enable (don't write to x0)")
        self._emit("    rd_idx = fromIntegral rd")
        self._emit("    rd_wen = rd /= 0 && (is_rtype || is_itype || is_load || is_lui || is_auipc || is_jal || is_jalr)")
        self._emit("")

        # Generate memory write logic
        self._emit("    -- Store data preparation")
        self._emit("    store_byte_offset_bits = slice d1 d0 store_addr")
        self._emit("    store_word_addr = resize (shiftR store_addr 2) :: BitVector 13")
        self._emit("    store_word = umem !! (fromIntegral store_word_addr)")
        self._emit("")
        self._emit("    -- Byte store data (SB)")
        self._emit("    sb_data = if store_byte_offset_bits == 0b00 then (slice d31 d8 store_word) ++# (resize rs2_data)")
        self._emit("              else if store_byte_offset_bits == 0b01 then (slice d31 d16 store_word) ++# (resize rs2_data) ++# (slice d7 d0 store_word)")
        self._emit("              else if store_byte_offset_bits == 0b10 then (slice d31 d24 store_word) ++# (resize rs2_data) ++# (slice d15 d0 store_word)")
        self._emit("              else (resize rs2_data) ++# (slice d23 d0 store_word)")
        self._emit("")
        self._emit("    -- Halfword store data (SH)")
        self._emit("    sh_data = if slice d1 d1 store_addr == 0")
        self._emit("              then (slice d31 d16 store_word) ++# (resize rs2_data)")
        self._emit("              else (resize rs2_data) ++# (slice d15 d0 store_word)")
        self._emit("")
        self._emit("    -- Byte/halfword/word store data selection")
        self._emit("    store_data = if funct3 == 0b000 then sb_data      -- SB")
        self._emit("                 else if funct3 == 0b001 then sh_data -- SH")
        self._emit("                 else if funct3 == 0b010 then rs2_data -- SW")
        self._emit("                 else store_word")
        self._emit("")

        # Generate next state
        self._emit("    -- Store enable")
        self._emit("    store_en = is_store")
        self._emit("")
        self._emit("    -- Next register file state")
        self._emit("    rf' = if rd_wen then replace rd_idx rd_data rf else rf")
        self._emit("")
        self._emit("    -- Next memory state")
        self._emit("    umem' = if store_en then replace (fromIntegral store_word_addr) store_data umem else umem")
        self._emit("")
        self._emit("    -- Next state")
        self._emit("    state' = ProcessorState")
        self._emit("      { stPc = pc_next")
        self._emit("      , stRf = rf'")
        self._emit("      , stUmem = umem'")

        # Pipeline register updates (if pipelined)
        if self.is_pipelined:
            for pipe_reg in sorted(self.pipeline_registers):
                var_name = self._get_var_name(pipe_reg)
                self._emit(f"      , stPipe{var_name} = {var_name}_next")
            for valid_bit in sorted(self.validity_bits):
                var_name = self._get_var_name(valid_bit)
                self._emit(f"      , stValid{var_name} = {var_name}_next")

        self._emit("      }")
        self._emit("")

    def _generate_top_entity(self):
        """Generate the top-level entity."""
        self._emit("-- Top entity using mealy machine")
        self._emit("{-# ANN topEntity")
        self._emit("  (Synthesize")
        self._emit(f'    {{ t_name   = "{self.module_name}"')
        self._emit('    , t_inputs = [PortName "clk", PortName "rst", PortName "en"]')
        self._emit('    , t_output = PortName "pc"')
        self._emit("    }) #-}")
        self._emit("topEntity")
        self._emit("  :: Clock System")
        self._emit("  -> Reset System")
        self._emit("  -> Enable System")
        self._emit("  -> Signal System Word32")
        self._emit("topEntity = exposeClockResetEnable processorMachine")
        self._emit("")
        self._emit("-- Mealy machine wrapper")
        self._emit("processorMachine")
        self._emit("  :: HiddenClockResetEnable dom")
        self._emit("  => Signal dom Word32")
        self._emit("processorMachine = mealy processorT initialState (pure ())")
        self._emit("")

    def _generate_helpers(self):
        """Generate helper functions."""
        self._emit("-- Helper functions")
        self._emit("-- Note: boolToBit is already provided by Clash.Prelude")
        self._emit("")
        self._emit("-- Sign extend a narrow BitVector to a wider one")
        self._emit("-- This implementation avoids pack/unpack which lack BlackBox definitions")
        self._emit("sext12to32 :: BitVector 12 -> BitVector 32")
        self._emit("sext12to32 x = if testBit x 11")
        self._emit("               then (0xFFFFF :: BitVector 20) ++# x")
        self._emit("               else (0x00000 :: BitVector 20) ++# x")
        self._emit("")
        self._emit("sext13to32 :: BitVector 13 -> BitVector 32")
        self._emit("sext13to32 x = if testBit x 12")
        self._emit("               then (0x7FFFF :: BitVector 19) ++# x")
        self._emit("               else (0x00000 :: BitVector 19) ++# x")
        self._emit("")
        self._emit("sext20to32 :: BitVector 20 -> BitVector 32")
        self._emit("sext20to32 x = if testBit x 19")
        self._emit("               then (0xFFF :: BitVector 12) ++# x")
        self._emit("               else (0x000 :: BitVector 12) ++# x")
        self._emit("")
        self._emit("sext21to32 :: BitVector 21 -> BitVector 32")
        self._emit("sext21to32 x = if testBit x 20")
        self._emit("               then (0x7FF :: BitVector 11) ++# x")
        self._emit("               else (0x000 :: BitVector 11) ++# x")
        self._emit("")
        self._emit("sext8to32 :: BitVector 8 -> BitVector 32")
        self._emit("sext8to32 x = if testBit x 7")
        self._emit("              then (0xFFFFFF :: BitVector 24) ++# x")
        self._emit("              else (0x000000 :: BitVector 24) ++# x")
        self._emit("")
        self._emit("sext16to32 :: BitVector 16 -> BitVector 32")
        self._emit("sext16to32 x = if testBit x 15")
        self._emit("               then (0xFFFF :: BitVector 16) ++# x")
        self._emit("               else (0x0000 :: BitVector 16) ++# x")
        self._emit("")

    def generate(self) -> str:
        """
        Generate Clash HDL code from the resource graph.

        Returns:
            String containing the complete Clash module
        """
        # Analyze the graph
        self._analyze_graph()

        # Generate code
        self._generate_header()
        self._generate_type_aliases()
        self._generate_helpers()
        self._generate_state_record()
        self._generate_initial_state()
        self._generate_transition_function()
        self._generate_top_entity()

        return '\n'.join(self.lines)


def generate_clash(graph: ResourceGraph, module_name: str = "Processor") -> str:
    """
    Convenience function to generate Clash HDL from a ResourceGraph.

    Args:
        graph: The ResourceGraph to convert
        module_name: Name for the module

    Returns:
        String containing Clash HDL code
    """
    generator = ClashGenerator(graph, module_name)
    return generator.generate()
