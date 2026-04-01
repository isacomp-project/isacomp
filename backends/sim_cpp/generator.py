"""
C++ Simulation Generator for ISAComp

This module generates C++ simulation code from ResourceGraph representations.
The generated code is a cycle-accurate simulation that can be compiled and run
as a standalone executable or integrated into a larger simulation framework.
"""

import re
from typing import Dict, List, Set, Tuple
from core.resource_graph import ResourceGraph, Node


class CppSimGenerator:
    """Generate C++ simulation code from a ResourceGraph."""

    def __init__(self, graph: ResourceGraph, module_name: str = "processor"):
        """
        Initialize the C++ simulation generator.

        Args:
            graph: The ResourceGraph to generate from
            module_name: Name of the generated C++ class
        """
        self.graph = graph
        self.module_name = module_name

        # Track node categorization
        self.registers: Dict[str, Dict] = {}  # name -> {width, initial_value}
        self.memories: Dict[str, Dict] = {}   # name -> {width, depth, addr_width}
        self.wires: Dict[str, int] = {}       # name -> width
        self.constants: Dict[str, Tuple[int, int]] = {}  # name -> (value, width)

        # Track signal widths
        self.signal_widths: Dict[str, int] = {}

        # Node ID to C++ variable name mapping
        self.node_id_to_name: Dict[str, str] = {}
        self.used_names: Set[str] = set()

        # Track nodes that have been processed
        self.processed_nodes: Set[str] = set()

        # Output buffer
        self.lines: List[str] = []
        self.indent_level = 0

        # Default width (inferred from register file if present)
        self.default_width = 32
        rf_node = self.graph.nodes.get('rf')
        if rf_node and rf_node.data.get('bit_width'):
            self.default_width = rf_node.data['bit_width']

    def _indent(self) -> str:
        """Return current indentation string."""
        return "    " * self.indent_level

    def _emit(self, line: str = ""):
        """Emit a line with current indentation."""
        if line:
            self.lines.append(self._indent() + line)
        else:
            self.lines.append("")

    def _get_width(self, node: Node) -> int:
        """
        Determine the bit width of a node's output.

        Args:
            node: The node to analyze

        Returns:
            The bit width (defaults to self.default_width if not specified)
        """
        if node.id in self.signal_widths:
            return self.signal_widths[node.id]

        node_type = node.data.get('type', '')

        # Check explicit width fields
        if 'bit_width' in node.data and node.data['bit_width'] is not None:
            width = node.data['bit_width']
            self.signal_widths[node.id] = width
            return width

        if 'output_width' in node.data:
            width = node.data['output_width']
            self.signal_widths[node.id] = width
            return width

        if 'width' in node.data:
            width = node.data['width']
            self.signal_widths[node.id] = width
            return width

        # For bit slices, compute from range
        if node_type == 'bit_slice':
            if 'expression' in node.data and 'range' in node.data['expression']:
                high_bit, low_bit = node.data['expression']['range']
                width = high_bit - low_bit + 1
                self.signal_widths[node.id] = width
                return width
            # Try to parse from node ID
            match = re.search(r'\[(\d+):(\d+)\]', node.id)
            if match:
                high_bit = int(match.group(1))
                low_bit = int(match.group(2))
                width = high_bit - low_bit + 1
                self.signal_widths[node.id] = width
                return width

        # For literals, infer from value or width specification
        if node_type in ['literal', 'binary_literal', 'hex_literal',
                         'verilog_hex_literal', 'verilog_binary_literal', 'sized_literal', 'constant']:
            # Try to parse width from node ID (e.g., "32'hFFFFFFFE")
            match = re.match(r"(\d+)'([hbodHBOD])([0-9a-fA-F_]+)", node.id)
            if match:
                width = int(match.group(1))
                self.signal_widths[node.id] = width
                return width
            value = node.data.get('value', 0)
            if isinstance(value, int):
                width = max(1, value.bit_length()) if value >= 0 else self.default_width
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

        # For array accesses, get width from the array
        if node_type == 'array_access':
            for edge in node.incoming_edges:
                if edge.data.get('type') in ['array', 'array_base']:
                    array_width = edge.source.data.get('bit_width')
                    if array_width:
                        self.signal_widths[node.id] = array_width
                        return array_width

        # For comparisons, result is always 1 bit
        if node_type in ['comparison']:
            self.signal_widths[node.id] = 1
            return 1

        # For operations, check operator
        if node_type == 'operation':
            operator = node.data.get('operator', '')
            comparison_ops = ['==', '!=', '<', '>', '<=', '>=', '<s', '>s', '<=s', '>=s',
                              '<u', '>u', '<=u', '>=u']
            if operator in comparison_ops:
                self.signal_widths[node.id] = 1
                return 1
            # For arithmetic operations, get max width from operands
            max_width = 0
            for edge in node.incoming_edges:
                w = self._get_width(edge.source)
                if w > max_width:
                    max_width = w
            if max_width > 0:
                self.signal_widths[node.id] = max_width
                return max_width

        # For multiplexers, use data input widths
        if node_type == 'multiplexer':
            widths = []
            for edge in node.incoming_edges:
                edge_type = edge.data.get('type', '')
                if edge_type in ['mux_input', 'mux_default_input']:
                    w = self._get_width(edge.source)
                    if w:
                        widths.append(w)
            if widths:
                width = max(widths)
                self.signal_widths[node.id] = width
                return width

        # For ternary ops, get width from true/false branches
        if node_type in ['ternary', 'ternary_op']:
            widths = []
            for edge in node.incoming_edges:
                edge_type = edge.data.get('type', '')
                if edge_type in ['ternary_true', 'ternary_false', 'true_value', 'false_value']:
                    src = edge.source
                    if src.data.get('type') != 'literal':
                        w = self._get_width(src)
                        if w:
                            widths.append(w)
            if widths:
                width = max(widths)
                self.signal_widths[node.id] = width
                return width

        # Default width
        self.signal_widths[node.id] = self.default_width
        return self.default_width

    def _cpp_type(self, width: int) -> str:
        """Return appropriate C++ integer type for given bit width.

        Note: For widths > 64 bits, uses GCC/Clang extension __uint128_t.
        This requires compilation with GCC or Clang (not MSVC).
        """
        if width <= 8:
            return "uint8_t"
        elif width <= 16:
            return "uint16_t"
        elif width <= 32:
            return "uint32_t"
        elif width <= 64:
            return "uint64_t"
        else:
            # Use GCC/Clang __uint128_t for 65+ bit values
            # Wider signals are represented in 128 bits to preserve integer-like semantics
            return "__uint128_t"

    def _signed_cpp_type(self, width: int) -> str:
        """Return appropriate signed C++ integer type for given bit width."""
        if width <= 8:
            return "int8_t"
        elif width <= 16:
            return "int16_t"
        elif width <= 32:
            return "int32_t"
        elif width <= 64:
            return "int64_t"
        else:
            # Use GCC/Clang __int128_t for 65+ bit signed values
            return "__int128_t"

    def _mask(self, width: int) -> str:
        """Return a mask expression for the given bit width."""
        if width >= 128:
            # Full 128-bit mask
            return "((__uint128_t)-1)"
        elif width > 64:
            # Partial 128-bit mask
            return f"(((__uint128_t)1 << {width}) - 1)"
        elif width == 64:
            return "0xFFFFFFFFFFFFFFFFULL"
        else:
            # Use 1ULL to ensure 64-bit shift context for widths >= 32
            return f"0x{(1 << width) - 1:X}ULL"

    def _sanitize_name(self, name: str, ensure_unique: bool = True) -> str:
        """Sanitize a name to be a valid C++ identifier.

        Args:
            name: The name to sanitize
            ensure_unique: If True, append counter suffix if name already exists
        """
        # Replace operators with descriptive text
        replacements = [
            ('>>>', '_ashr_'), ('>>', '_shr_'), ('<<', '_shl_'),
            ('>=', '_gte_'), ('<=', '_lte_'), ('!=', '_neq_'), ('==', '_eq_'),
            ('>', '_gt_'), ('<s', '_lts_'), ('<', '_lt_'),
            ('+', '_add_'), ('-', '_sub_'), ('*', '_mul_'),
            ('&', '_and_'), ('|', '_or_'), ('^', '_xor_'), ('~', '_not_'),
            ('?', '_sel_'), (':', '_'), ('[', '_'), (']', '_'),
            ('/', '_div_'), ('%', '_mod_'), ("'", '_')
        ]
        result = name
        for old, new in replacements:
            result = result.replace(old, new)

        # Replace invalid characters with underscore
        result = re.sub(r'[^a-zA-Z0-9_]', '_', result)
        # Remove consecutive underscores
        result = re.sub(r'_+', '_', result)
        # Strip leading/trailing underscores
        result = result.strip('_')

        # Prefix with underscore if starts with digit
        if result and result[0].isdigit():
            result = '_' + result

        if not result:
            result = 'sig'

        if ensure_unique:
            # Ensure uniqueness
            base_name = result
            counter = 0
            while result in self.used_names:
                counter += 1
                result = f"{base_name}_{counter}"

            self.used_names.add(result)

        return result

    def _get_base_register_name(self, name: str) -> str:
        """Extract base register name, stripping _rd/_wr suffixes."""
        if name.endswith('_rd') or name.endswith('_wr'):
            return name[:-3]
        return name

    def _get_node_name(self, node: Node) -> str:
        """Get the C++ variable name for a node."""
        if node.id in self.node_id_to_name:
            return self.node_id_to_name[node.id]

        # Use name from node data if available, then node.id
        # Note: prefer 'name' over 'display_name' since display_name may have
        # formatting that creates naming mismatches (e.g., 0b prefix in literals)
        raw_name = node.data.get('name') or node.id

        # For _rd/_wr nodes, use the base register name
        base_name = self._get_base_register_name(raw_name)

        # Check if this base name is already registered
        # This ensures pc, pc_rd, and pc_wr all map to the same 'pc'
        sanitized_base = self._sanitize_name(base_name, ensure_unique=False)

        if sanitized_base in self.used_names:
            # Already registered, reuse the same name
            self.node_id_to_name[node.id] = sanitized_base
            return sanitized_base

        # Register the name
        self.used_names.add(sanitized_base)
        self.node_id_to_name[node.id] = sanitized_base
        return sanitized_base

    def _parse_literal_value(self, node: Node) -> Tuple[int, int]:
        """Parse a literal node to get its value and width."""
        value = node.data.get('value', 0)
        width = self._get_width(node)

        # Parse from node ID if needed
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

        if isinstance(value, str):
            if value.startswith('0x'):
                value = int(value, 16)
            elif value.startswith('0b'):
                value = int(value, 2)
            else:
                try:
                    value = int(value)
                except ValueError:
                    value = 0

        return value, width

    def _pre_register_arch_state_names(self):
        """Pre-register all architectural state base names to ensure consistency."""
        for node_id, node in sorted(self.graph.nodes.items()):
            if node.is_arch_state or node.data.get('type', '').startswith('isa_state'):
                if not node.data.get('is_memory', False) and 'array_depth' not in node.data:
                    # Get the base name (stripping _rd/_wr)
                    raw_name = node.data.get('display_name') or node.data.get('name') or node_id
                    base_name = self._get_base_register_name(raw_name)
                    sanitized = self._sanitize_name(base_name, ensure_unique=False)

                    # Register the name if not already registered
                    if sanitized not in self.used_names:
                        self.used_names.add(sanitized)

                    # Map all variants to the same name
                    self.node_id_to_name[node_id] = sanitized

    def _analyze_graph(self):
        """Analyze the graph to categorize nodes."""
        # Pre-register architectural state names first
        self._pre_register_arch_state_names()

        for node_id, node in sorted(self.graph.nodes.items()):
            node_type = node.data.get('type', '')
            width = self._get_width(node)

            # Categorize based on node properties
            if node.is_arch_state or node_type.startswith('isa_state'):
                if node.data.get('is_memory', False) or 'array_depth' in node.data:
                    # Memory array
                    if 'array_depth' in node.data and node.data['array_depth'] is not None:
                        addr_width = node.data['array_depth']
                        depth = 2 ** addr_width
                        # Check if this is byte-addressed memory
                        # Byte-addressed memories have 'endianness' or 'addr_bits' fields
                        is_byte_addressed = (
                            'endianness' in node.data or
                            'addr_bits' in node.data
                        )
                        self.memories[node_id] = {
                            'width': width,
                            'depth': depth,
                            'addr_width': addr_width,
                            'is_byte_addressed': is_byte_addressed
                        }
                elif not node_id.endswith('_rd') and not node_id.endswith('_wr'):
                    # Simple register - use pre-registered name
                    initial_value = node.data.get('initial_value', 0)
                    cpp_name = self._get_node_name(node)
                    self.registers[cpp_name] = {
                        'width': width,
                        'initial_value': initial_value
                    }
                else:
                    # Handle split _rd/_wr nodes - register the base name if not already
                    base_name = self._get_base_register_name(node_id)
                    cpp_name = self._sanitize_name(base_name, ensure_unique=False)
                    if cpp_name not in self.registers:
                        initial_value = node.data.get('initial_value', 0)
                        self.registers[cpp_name] = {
                            'width': width,
                            'initial_value': initial_value
                        }

            elif node.is_uarch_state or node_type == 'pipeline_register':
                # Pipeline registers
                initial_value = node.data.get('initial_value', 0)
                cpp_name = self._get_node_name(node)
                self.registers[cpp_name] = {
                    'width': width,
                    'initial_value': initial_value
                }

            elif node_type in ['literal', 'binary_literal', 'hex_literal',
                               'verilog_hex_literal', 'sized_literal', 'constant']:
                # Constants
                value, w = self._parse_literal_value(node)
                self.constants[node_id] = (value, w)

            else:
                # Wires (intermediate signals)
                self.wires[node_id] = width

    def _generate_header(self):
        """Generate C++ header with includes and class declaration."""
        self._emit("#pragma once")
        self._emit()
        self._emit("#include <cstdint>")
        self._emit("#include <cstring>")
        self._emit("#include <array>")
        self._emit("#include <bitset>")
        self._emit("#include <iostream>")
        self._emit("#include <fstream>")
        self._emit("#include <iomanip>")
        self._emit("#include <functional>")
        self._emit()
        self._emit(f"class {self.module_name} {{")
        self._emit("public:")
        self.indent_level += 1

    def _generate_state_members(self):
        """Generate state member declarations."""
        self._emit("// Architectural state")

        # Use the registers dict populated during _analyze_graph
        # Filter out pipeline registers (they'll be declared separately)
        arch_regs = {}
        pipeline_regs = {}

        for cpp_name, info in self.registers.items():
            # Check if this is a pipeline register by looking at the original node
            is_pipeline = False
            for node_id, node in self.graph.nodes.items():
                if self.node_id_to_name.get(node_id) == cpp_name:
                    if node.is_uarch_state or node.data.get('type') == 'pipeline_register':
                        is_pipeline = True
                        break

            if is_pipeline:
                pipeline_regs[cpp_name] = info
            else:
                arch_regs[cpp_name] = info

        # Generate architectural register declarations
        for cpp_name, info in sorted(arch_regs.items()):
            cpp_type = self._cpp_type(info['width'])
            initial_value = info.get('initial_value', 0)
            self._emit(f"{cpp_type} {cpp_name} = {initial_value};")

        self._emit()
        self._emit("// Memory arrays")

        # Generate memory declarations
        for mem_name, mem_info in sorted(self.memories.items()):
            cpp_name = self._sanitize_name(mem_name, ensure_unique=False)
            if cpp_name not in self.used_names:
                self.used_names.add(cpp_name)
            elem_type = self._cpp_type(mem_info['width'])
            depth = mem_info['depth']
            self._emit(f"std::array<{elem_type}, {depth}> {cpp_name} = {{}};")

        # Generate pipeline registers
        if pipeline_regs:
            self._emit()
            self._emit("// Pipeline registers")
            for cpp_name, info in sorted(pipeline_regs.items()):
                cpp_type = self._cpp_type(info['width'])
                self._emit(f"{cpp_type} {cpp_name} = 0;")

        self._emit()
        self._emit("// Simulation state")
        self._emit("uint64_t cycle_count = 0;")
        self._emit("bool halted = false;")

    def _generate_wire_declarations(self):
        """Generate intermediate wire declarations."""
        self._emit()
        self._emit("// Intermediate signals (computed each cycle)")

        declared_wires = set()
        for node_id, width in sorted(self.wires.items()):
            node = self.graph.nodes.get(node_id)
            if node:
                cpp_type = self._cpp_type(width)
                cpp_name = self._get_node_name(node)
                # Skip if already declared as state or already declared as wire
                if cpp_name not in self.registers and cpp_name not in declared_wires:
                    self._emit(f"{cpp_type} {cpp_name} = 0;")
                    declared_wires.add(cpp_name)

    def _get_operand_expr(self, node: Node) -> str:
        """Get the C++ expression for reading a node's value."""
        node_type = node.data.get('type', '')

        # For literals, return the value directly
        if node_type in ['literal', 'binary_literal', 'hex_literal',
                         'verilog_hex_literal', 'sized_literal', 'constant']:
            value, width = self._parse_literal_value(node)
            if width > 32:
                return f"{value}ULL"
            return str(value)

        # For architectural state with _rd suffix, return the base register
        if node.id.endswith('_rd'):
            base_name = node.id[:-3]
            return self._sanitize_name(base_name, ensure_unique=False)

        # For everything else, return the node name
        return self._get_node_name(node)

    def _generate_expression(self, node: Node) -> str:
        """Generate C++ expression for a node's computation."""
        node_type = node.data.get('type', '')

        # Literals
        if node_type in ['literal', 'binary_literal', 'hex_literal',
                         'verilog_hex_literal', 'sized_literal', 'constant']:
            value, width = self._parse_literal_value(node)
            if width > 32:
                return f"{value}ULL"
            return str(value)

        # Array access (must be before generic _rd check)
        if node_type == 'array_access':
            return self._generate_array_access(node)

        # Architectural state read (simple registers, not array accesses)
        if node.id.endswith('_rd') and '[' not in node.id:
            base_name = node.id[:-3]
            return self._sanitize_name(base_name, ensure_unique=False)

        # Operations (including logical_and, logical_or which are operation-like)
        if node_type in ['operation', 'logical_and', 'logical_or']:
            return self._generate_operation(node)

        # Comparisons
        if node_type in ['comparison', 'equality', 'relational']:
            return self._generate_comparison(node)

        # Bit slice
        if node_type == 'bit_slice':
            return self._generate_bit_slice(node)

        # Concatenation
        if node_type in ['concatenation', 'concat']:
            return self._generate_concatenation(node)

        # Repetition
        if node_type == 'repetition':
            return self._generate_repetition(node)

        # Ternary
        if node_type in ['ternary', 'ternary_op']:
            return self._generate_ternary(node)

        # Zero/sign extend
        if node_type == 'zero_extend':
            return self._generate_zero_extend(node)
        if node_type == 'sign_extend':
            return self._generate_sign_extend(node)

        # Multiplexer
        if node_type == 'multiplexer':
            return self._generate_multiplexer(node)

        # Variable (alias)
        if node_type in ['var', 'temp_var']:
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'assignment':
                    return self._get_operand_expr(edge.source)
            # If no assignment, just return the node name
            return self._get_node_name(node)

        # Instruction enable - pass through from single input
        if node_type == 'instruction_enable':
            for edge in node.incoming_edges:
                # Return the decode enable source
                return self._get_operand_expr(edge.source)
            # Fallback if no edges
            return "0"

        # Pipeline stall controller - pass through from single input
        if node_type == 'pipeline_stall_controller':
            for edge in node.incoming_edges:
                return self._get_operand_expr(edge.source)
            # Fallback if no edges
            return "0"

        # Default: return node name
        return self._get_node_name(node)

    def _generate_operation(self, node: Node) -> str:
        """Generate C++ expression for an arithmetic/logic operation."""
        operator = node.data.get('operator', node.data.get('operation', ''))
        width = self._get_width(node)
        mask = self._mask(width)

        # Get operands and their widths
        left_op = None
        right_op = None
        left_width = self.default_width
        right_width = self.default_width
        operands = []
        operand_widths = []

        for edge in node.incoming_edges:
            edge_type = edge.data.get('type', '')
            position = edge.data.get('position')

            if edge_type == 'left_operand' or position == 'left':
                left_op = self._get_operand_expr(edge.source)
                left_width = self._get_width(edge.source)
            elif edge_type == 'right_operand' or position == 'right':
                right_op = self._get_operand_expr(edge.source)
                right_width = self._get_width(edge.source)
            elif edge_type == 'operand':
                operands.append(self._get_operand_expr(edge.source))
                operand_widths.append(self._get_width(edge.source))

        # Build operands list
        if left_op is not None:
            operands = [left_op]
            operand_widths = [left_width]
            if right_op is not None:
                operands.append(right_op)
                operand_widths.append(right_width)
        elif not operands:
            # Sort by position
            def get_pos(e):
                pos = e.data.get('position', 999)
                return int(pos) if isinstance(pos, (int, str)) and str(pos).isdigit() else 999
            sorted_edges = sorted(node.incoming_edges, key=get_pos)
            operands = [self._get_operand_expr(e.source) for e in sorted_edges]
            operand_widths = [self._get_width(e.source) for e in sorted_edges]

        if len(operands) < 1:
            return "0"

        # Handle unary operators
        if len(operands) == 1:
            if operator in ['!', 'not', 'logical_not']:
                return f"(!({operands[0]}) ? 1 : 0)"
            elif operator in ['~', 'bitwise_not', 'invert']:
                return f"((~{operands[0]}) & {mask})"
            return operands[0]

        # Binary operators
        left = operands[0]
        right = operands[1]
        # Get the max operand width for signed casts
        operand_width = max(operand_widths[0], operand_widths[1]) if len(operand_widths) >= 2 else self.default_width
        signed_type = self._signed_cpp_type(operand_width)

        op_map = {
            '+': f"(({left} + {right}) & {mask})",
            '-': f"(({left} - {right}) & {mask})",
            '*': f"(({left} * {right}) & {mask})",
            '&': f"({left} & {right})",
            'and': f"({left} & {right})",
            '|': f"({left} | {right})",
            'or': f"({left} | {right})",
            '^': f"({left} ^ {right})",
            'xor': f"({left} ^ {right})",
            '<<': f"(({left} << {right}) & {mask})",
            'shl': f"(({left} << {right}) & {mask})",
            '>>': f"({left} >> {right})",
            'shr': f"({left} >> {right})",
            '>>>': f"(({signed_type}){left} >> {right})",  # Arithmetic shift
            'ashr': f"(({signed_type}){left} >> {right})",
        }

        if operator in op_map:
            return op_map[operator]

        # Comparison operators (use operand width for signed casts, not result width)
        comparison_ops = {
            '==': f"(({left} == {right}) ? 1 : 0)",
            'eq': f"(({left} == {right}) ? 1 : 0)",
            '!=': f"(({left} != {right}) ? 1 : 0)",
            'ne': f"(({left} != {right}) ? 1 : 0)",
            '<': f"(({left} < {right}) ? 1 : 0)",
            'lt': f"(({left} < {right}) ? 1 : 0)",
            '<=': f"(({left} <= {right}) ? 1 : 0)",
            'le': f"(({left} <= {right}) ? 1 : 0)",
            '>': f"(({left} > {right}) ? 1 : 0)",
            'gt': f"(({left} > {right}) ? 1 : 0)",
            '>=': f"(({left} >= {right}) ? 1 : 0)",
            'ge': f"(({left} >= {right}) ? 1 : 0)",
            '<s': f"((({signed_type}){left} < ({signed_type}){right}) ? 1 : 0)",
            '>s': f"((({signed_type}){left} > ({signed_type}){right}) ? 1 : 0)",
            '<=s': f"((({signed_type}){left} <= ({signed_type}){right}) ? 1 : 0)",
            '>=s': f"((({signed_type}){left} >= ({signed_type}){right}) ? 1 : 0)",
        }

        if operator in comparison_ops:
            return comparison_ops[operator]

        # Logical operators - handle multiple operands
        if operator in ['&&', 'logical_and']:
            if len(operands) == 2:
                return f"(({left} != 0 && {right} != 0) ? 1 : 0)"
            else:
                # Multiple operands: AND them all
                conditions = [f"({op} != 0)" for op in operands]
                return f"(({' && '.join(conditions)}) ? 1 : 0)"
        if operator in ['||', 'logical_or']:
            if len(operands) == 2:
                return f"(({left} != 0 || {right} != 0) ? 1 : 0)"
            else:
                # Multiple operands: OR them all
                conditions = [f"({op} != 0)" for op in operands]
                return f"(({' || '.join(conditions)}) ? 1 : 0)"

        # Default to left operand
        return left

    def _generate_comparison(self, node: Node) -> str:
        """Generate C++ expression for a comparison."""
        operator = node.data.get('operation', node.data.get('operator', '=='))
        left_width = self.default_width
        right_width = self.default_width

        # Get operands
        left_op = None
        right_op = None

        # First check if expression data contains the comparison structure
        expr_data = node.data.get('expression', {})
        if isinstance(expr_data, dict) and expr_data.get('type') in ['binary_op', 'comparison']:
            left_expr = expr_data.get('left', {})
            right_expr = expr_data.get('right', {})
            operator = expr_data.get('operator', expr_data.get('operation', operator))

            # Generate C++ for left operand (usually a bit slice)
            left_op = self._generate_expression_from_dict(left_expr, node)
            right_op = self._generate_expression_from_dict(right_expr, node)

            # Get widths
            if left_expr.get('type') == 'bit_slice':
                high = left_expr.get('high', {}).get('value', 31)
                low = left_expr.get('low', {}).get('value', 0)
                left_width = high - low + 1
            if right_expr.get('type') == 'bit_slice':
                high = right_expr.get('high', {}).get('value', 31)
                low = right_expr.get('low', {}).get('value', 0)
                right_width = high - low + 1

        if not left_op or not right_op:
            # Try from incoming edges
            for edge in node.incoming_edges:
                edge_type = edge.data.get('type', '')
                position = edge.data.get('position')

                if edge_type == 'left_operand' or position == 'left':
                    left_op = self._get_operand_expr(edge.source)
                    left_width = self._get_width(edge.source)
                elif edge_type == 'right_operand' or position == 'right':
                    right_op = self._get_operand_expr(edge.source)
                    right_width = self._get_width(edge.source)

        if not left_op or not right_op:
            # Try to get from sorted edges
            sorted_edges = sorted(node.incoming_edges,
                                  key=lambda e: e.data.get('position', 999))
            if len(sorted_edges) >= 2:
                left_op = self._get_operand_expr(sorted_edges[0].source)
                right_op = self._get_operand_expr(sorted_edges[1].source)
                left_width = self._get_width(sorted_edges[0].source)
                right_width = self._get_width(sorted_edges[1].source)

        if not left_op:
            left_op = "0"
        if not right_op:
            right_op = "0"

        # Use max operand width for signed casts
        operand_width = max(left_width, right_width)
        signed_type = self._signed_cpp_type(operand_width)

        comparison_ops = {
            '==': f"(({left_op} == {right_op}) ? 1 : 0)",
            '!=': f"(({left_op} != {right_op}) ? 1 : 0)",
            '<': f"(({left_op} < {right_op}) ? 1 : 0)",
            '<=': f"(({left_op} <= {right_op}) ? 1 : 0)",
            '>': f"(({left_op} > {right_op}) ? 1 : 0)",
            '>=': f"(({left_op} >= {right_op}) ? 1 : 0)",
            '<s': f"((({signed_type}){left_op} < ({signed_type}){right_op}) ? 1 : 0)",
            '>s': f"((({signed_type}){left_op} > ({signed_type}){right_op}) ? 1 : 0)",
        }

        return comparison_ops.get(operator, f"(({left_op} == {right_op}) ? 1 : 0)")

    def _generate_expression_from_dict(self, expr_dict: dict, context_node: Node) -> str:
        """Generate C++ expression from an expression dictionary."""
        if not isinstance(expr_dict, dict):
            return str(expr_dict)

        expr_type = expr_dict.get('type', '')

        # Literal value
        if expr_type == 'literal':
            value = expr_dict.get('value')
            if isinstance(value, str):
                # Parse binary/hex literals
                if value.startswith('0b'):
                    return str(int(value, 2))
                elif value.startswith('0x'):
                    return str(int(value, 16))
                return value
            return str(value) if value is not None else "0"

        # Identifier - look up the variable
        if expr_type == 'identifier':
            name = expr_dict.get('name', '')
            return self._sanitize_name(name, ensure_unique=False)

        # Bit slice
        if expr_type == 'bit_slice':
            array_expr = expr_dict.get('array', {})
            high = expr_dict.get('high', {}).get('value', 31)
            low = expr_dict.get('low', {}).get('value', 0)
            source = self._generate_expression_from_dict(array_expr, context_node)
            width = high - low + 1
            mask = self._mask(width)
            return f"(({source} >> {low}) & {mask})"

        return "0"

    def _generate_bit_slice(self, node: Node) -> str:
        """Generate C++ expression for bit slice extraction."""
        high_bit = 31
        low_bit = 0

        if 'expression' in node.data and 'range' in node.data['expression']:
            high_bit, low_bit = node.data['expression']['range']
        else:
            match = re.search(r'\[(\d+):(\d+)\]', node.id)
            if match:
                high_bit = int(match.group(1))
                low_bit = int(match.group(2))

        width = high_bit - low_bit + 1
        mask = self._mask(width)

        # Get source
        source_expr = "0"
        for edge in node.incoming_edges:
            if edge.data.get('type') in ['operand', 'bit_access', 'data']:
                source_expr = self._get_operand_expr(edge.source)
                break

        return f"(({source_expr} >> {low_bit}) & {mask})"

    def _generate_array_access(self, node: Node) -> str:
        """Generate C++ expression for array/memory read."""
        array_name = None
        index_expr = "0"

        for edge in node.incoming_edges:
            source = edge.source
            edge_type = edge.data.get('type', '')

            if source.data.get('is_memory') or edge_type in ['array', 'array_base']:
                array_name = self._sanitize_name(source.id, ensure_unique=False)
            elif edge_type in ['index', 'array_index']:
                index_expr = self._get_operand_expr(source)
            # Also check for edges without proper type
            elif not array_name and source.id in [mem_id for mem_id in self.memories]:
                array_name = self._sanitize_name(source.id, ensure_unique=False)
            elif index_expr == "0" and source.id.endswith('_rd'):
                index_expr = self._get_operand_expr(source)

        if not array_name:
            # Try to find from the node ID pattern like "rf[rs1]_rd"
            match = re.match(r'([a-zA-Z_]\w*)\[', node.id)
            if match:
                array_name = self._sanitize_name(match.group(1), ensure_unique=False)

        if array_name:
            # Get memory info for address masking
            mem_info = None
            for mem_id, info in self.memories.items():
                if self._sanitize_name(mem_id, ensure_unique=False) == array_name:
                    mem_info = info
                    break

            if mem_info:
                addr_mask = self._mask(mem_info['addr_width'])
                data_width = mem_info.get('width', 32)
                is_byte_addressed = mem_info.get('is_byte_addressed', False)

                # Convert byte address to word address only for byte-addressed memories
                byte_shift = 0
                if is_byte_addressed:
                    if data_width == 32:
                        byte_shift = 2
                    elif data_width == 16:
                        byte_shift = 1
                    elif data_width == 64:
                        byte_shift = 3

                if byte_shift > 0:
                    return f"{array_name}[({index_expr} >> {byte_shift}) & {addr_mask}]"
                else:
                    return f"{array_name}[{index_expr} & {addr_mask}]"
            return f"{array_name}[{index_expr}]"

        return "0"

    def _generate_concatenation(self, node: Node) -> str:
        """Generate C++ expression for bit concatenation."""
        parts = []
        for edge in sorted(node.incoming_edges,
                           key=lambda e: e.data.get('position', 0)):
            parts.append((self._get_operand_expr(edge.source),
                          self._get_width(edge.source)))

        if not parts:
            return "0"

        # Build concatenation expression
        result = parts[0][0]
        total_width = parts[0][1]

        for i in range(1, len(parts)):
            expr, width = parts[i]
            result = f"(({result} << {width}) | ({expr} & {self._mask(width)}))"
            total_width += width

        return result

    def _generate_repetition(self, node: Node) -> str:
        """Generate C++ expression for bit repetition."""
        count = node.data.get('count', node.data.get('repetitions', 1))

        source_expr = "0"
        source_width = 1

        for edge in node.incoming_edges:
            source_expr = self._get_operand_expr(edge.source)
            source_width = self._get_width(edge.source)
            break

        if count == 1:
            return source_expr

        # Generate repeated bits
        result_width = count * source_width
        mask = self._mask(source_width)

        # For single-bit repetition (common for sign extension)
        if source_width == 1:
            return f"(({source_expr} & 1) ? {self._mask(result_width)} : 0)"

        # For multi-bit repetition
        result = source_expr
        for _ in range(count - 1):
            result = f"(({result} << {source_width}) | ({source_expr} & {mask}))"

        return result

    def _generate_ternary(self, node: Node) -> str:
        """Generate C++ expression for ternary operation."""
        cond = "0"
        true_val = "0"
        false_val = "0"

        for edge in node.incoming_edges:
            edge_type = edge.data.get('type', edge.data.get('edge_type', ''))
            if edge_type in ['condition', 'ternary_condition']:
                cond = self._get_operand_expr(edge.source)
            elif edge_type in ['true_value', 'ternary_true']:
                true_val = self._get_operand_expr(edge.source)
            elif edge_type in ['false_value', 'ternary_false']:
                false_val = self._get_operand_expr(edge.source)

        return f"(({cond}) ? ({true_val}) : ({false_val}))"

    def _generate_zero_extend(self, node: Node) -> str:
        """Generate C++ expression for zero extension."""
        for edge in node.incoming_edges:
            source_expr = self._get_operand_expr(edge.source)
            source_width = self._get_width(edge.source)
            mask = self._mask(source_width)
            return f"({source_expr} & {mask})"
        return "0"

    def _generate_sign_extend(self, node: Node) -> str:
        """Generate C++ expression for sign extension."""
        target_width = self._get_width(node)

        for edge in node.incoming_edges:
            source_expr = self._get_operand_expr(edge.source)
            source_width = self._get_width(edge.source)

            if source_width >= target_width:
                return source_expr

            # Sign extension
            sign_bit = source_width - 1
            source_mask = self._mask(source_width)
            extension_bits = f"({self._mask(target_width - source_width)} << {source_width})"

            return f"((({source_expr} >> {sign_bit}) & 1) ? (({source_expr} & {source_mask}) | {extension_bits}) : ({source_expr} & {source_mask}))"

        return "0"

    def _generate_multiplexer(self, node: Node) -> str:
        """Generate C++ expression for multiplexer."""
        default_val = "0"

        for edge in node.incoming_edges:
            edge_type = edge.data.get('type', edge.data.get('edge_type', ''))
            if edge_type in ['mux_default', 'mux_default_input']:
                default_val = self._get_operand_expr(edge.source)

        # Collect select/value pairs
        selects = {}  # index -> select_expr
        values = {}   # index -> value_expr

        for edge in node.incoming_edges:
            edge_type = edge.data.get('type', edge.data.get('edge_type', ''))
            # Try multiple key names for index
            idx = edge.data.get('input_index')
            if idx is None:
                idx = edge.data.get('select_index')
            if idx is None:
                idx = edge.data.get('index')
            if idx is None:
                idx = edge.data.get('mux_index')

            if edge_type in ['mux_input', 'mux_value']:
                if idx is not None:
                    values[idx] = self._get_operand_expr(edge.source)
            elif edge_type in ['mux_select', 'mux_condition']:
                if idx is not None:
                    selects[idx] = self._get_operand_expr(edge.source)

        # Build cascaded ternary expression
        result = default_val
        for idx in sorted(selects.keys(), reverse=True):
            if idx in values:
                sel = selects[idx]
                val = values[idx]
                result = f"(({sel}) ? ({val}) : ({result}))"

        return result

    def _generate_combinational_logic(self):
        """Generate the combinational logic computation method."""
        self._emit()
        self._emit("void compute_combinational() {")
        self.indent_level += 1

        # Topologically sort nodes to ensure dependencies are computed first
        visited = set()
        order = []

        def extract_expr_dependencies(expr_dict: dict) -> set:
            """Extract variable references from expression dictionaries.

            Some nodes store their dependencies in expression dicts rather than
            as graph edges. This function extracts those embedded dependencies
            so the topological sort can properly order them.
            """
            deps = set()
            if not isinstance(expr_dict, dict):
                return deps

            expr_type = expr_dict.get('type', '')

            # Identifier - this is a variable reference
            if expr_type == 'identifier':
                name = expr_dict.get('name', '')
                if name:
                    deps.add(name)

            # Bit slice - recurse into array/target expression
            if expr_type == 'bit_slice':
                # Try both 'array' and 'target' as the source field
                array_expr = expr_dict.get('array', expr_dict.get('target', {}))
                deps.update(extract_expr_dependencies(array_expr))

            # Binary operations - recurse into both sides
            if expr_type in ['binary_op', 'comparison']:
                left_expr = expr_dict.get('left', {})
                right_expr = expr_dict.get('right', {})
                deps.update(extract_expr_dependencies(left_expr))
                deps.update(extract_expr_dependencies(right_expr))

            return deps

        def visit(node_id):
            if node_id in visited:
                return
            visited.add(node_id)

            node = self.graph.nodes.get(node_id)
            if not node:
                return

            # Visit dependencies first
            # Skip certain edge types to break cycles:
            # - memory_write: memory writes affect the next cycle, not current combinational logic
            # - pipeline_input edges on pipeline_register nodes: pipeline registers hold OLD values
            #   from the previous cycle; their new values (from pipeline_input) are computed but
            #   not used until the next cycle, so we don't need to order based on pipeline_input
            node_type = node.data.get('type', '')
            for edge in node.incoming_edges:
                edge_type = edge.data.get('type', '')
                if edge_type == 'memory_write':
                    continue
                # For pipeline registers, skip pipeline_input edges - we use their stored value
                if node_type == 'pipeline_register' and edge_type == 'pipeline_input':
                    continue
                visit(edge.source.id)

            # Also visit dependencies embedded in expression dictionaries
            # These are variable references stored as {'type': 'identifier', 'name': 'varname'}
            # inside comparison/slice expressions
            expr_data = node.data.get('expression', {})
            if isinstance(expr_data, dict):
                embedded_deps = extract_expr_dependencies(expr_data)
                for dep_name in embedded_deps:
                    # Try to find a matching node
                    if dep_name in self.graph.nodes:
                        visit(dep_name)
                    # Also try with common suffixes/prefixes
                    elif f"PIPE_Decode_{dep_name}_PIPE" in self.graph.nodes:
                        visit(f"PIPE_Decode_{dep_name}_PIPE")

            order.append(node_id)

        for node_id in self.graph.nodes:
            visit(node_id)

        # Generate assignments for each wire
        # Track emitted C++ variable names to avoid duplicate assignments
        # (can happen when same node exists under multiple dict keys after renaming)
        emitted_cpp_names = set()

        for node_id in order:
            node = self.graph.nodes.get(node_id)
            if not node:
                continue

            node_type = node.data.get('type', '')

            # Skip state nodes and literals
            if node.is_arch_state or node.is_uarch_state:
                continue
            if node_type in ['literal', 'binary_literal', 'hex_literal',
                             'verilog_hex_literal', 'sized_literal', 'constant']:
                continue
            if node_type.startswith('isa_state'):
                continue
            if node_type == 'pipeline_register':
                continue

            # Skip simple register _rd nodes (handled as register reads)
            # But process array access _rd nodes (like umem[pc]_rd)
            if node_id.endswith('_rd'):
                # Check if this is an array access (contains '[')
                if '[' not in node_id:
                    continue
                # For array reads, we need to generate the memory access

            # Skip _wr nodes (handled in sequential logic)
            if node_id.endswith('_wr'):
                continue

            # Generate the assignment
            cpp_name = self._get_node_name(node)

            # Skip if we've already emitted this C++ variable (duplicate node)
            if cpp_name in emitted_cpp_names:
                continue

            expr = self._generate_expression(node)

            # Don't emit self-assignments or zero assignments (except for array reads)
            is_array_read = '[' in node_id and node_id.endswith('_rd')

            if expr != cpp_name:
                if expr != "0" or is_array_read:
                    width = self._get_width(node)
                    mask = self._mask(width)
                    self._emit(f"{cpp_name} = ({expr}) & {mask};")
                    emitted_cpp_names.add(cpp_name)

        self.indent_level -= 1
        self._emit("}")

    def _generate_sequential_logic(self):
        """Generate the sequential logic update method."""
        self._emit()
        self._emit("void update_sequential() {")
        self.indent_level += 1

        # Collect all pipeline register updates - need to handle these specially
        # to avoid read-after-write hazards (when one pipeline register's new value
        # depends on another pipeline register's old value)
        pipeline_reg_updates = []  # List of (cpp_name, source_expr, width, mask, stall_conds)
        pipeline_reg_names = set()  # Names of pipeline registers for detecting dependencies

        # Collect regular register updates
        regular_reg_updates = []  # List of (cpp_name, source_expr, width, mask, stall_cond)
        memory_write_nodes = []   # Nodes that do memory writes

        # First pass: identify all pipeline registers
        for node_id, node in self.graph.nodes.items():
            if node.data.get('type') == 'pipeline_register':
                cpp_name = self._get_node_name(node)
                pipeline_reg_names.add(cpp_name)

        # Second pass: collect all updates (but don't emit yet)
        for node_id, node in sorted(self.graph.nodes.items()):
            # Handle _wr nodes (register writes)
            if node_id.endswith('_wr'):
                base_name = node_id[:-3]
                cpp_name = self._sanitize_name(base_name, ensure_unique=False)

                # Check if corresponding _rd node has a stall edge
                rd_node_id = base_name + '_rd'
                rd_node = self.graph.nodes.get(rd_node_id)
                stall_cond = None
                if rd_node:
                    for edge in rd_node.incoming_edges:
                        if edge.data.get('type') == 'stall':
                            stall_cond = self._get_operand_expr(edge.source)
                            break

                # Find the source value
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'assignment':
                        source_expr = self._get_operand_expr(edge.source)
                        width = self._get_width(node)
                        mask = self._mask(width)
                        regular_reg_updates.append((cpp_name, source_expr, width, mask, stall_cond))
                        break

            # Handle memory writes - collect for later
            if node.data.get('type') == 'memory_write_port':
                memory_write_nodes.append(node)

            # Handle pipeline registers - collect for later
            if node.data.get('type') == 'pipeline_register':
                cpp_name = self._get_node_name(node)
                # Collect any stall edges
                stall_conds = []
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'stall':
                        stall_conds.append(self._get_operand_expr(edge.source))
                for edge in node.incoming_edges:
                    if edge.data.get('type') == 'pipeline_input':
                        source_expr = self._get_operand_expr(edge.source)
                        width = self._get_width(node)
                        mask = self._mask(width)
                        pipeline_reg_updates.append((cpp_name, source_expr, width, mask, stall_conds))
                        break

        # CRITICAL: Capture ALL temporaries FIRST, before ANY register updates
        # This ensures pipeline registers see consistent old values for both
        # architectural registers (like pc) AND combinational signals (like umem_pc)
        # that depend on them.
        #
        # Without this, the following bug occurs:
        # 1. pc gets updated from pc_wr
        # 2. _new_1 = pc captures NEW pc value
        # 3. _new_2 = umem_pc captures OLD umem_pc (computed from OLD pc)
        # Result: D_pc and D_instr are misaligned!

        if pipeline_reg_updates:
            self._emit("// Capture pipeline register inputs BEFORE any state updates")
            self._emit("// This ensures consistent snapshot of current cycle state")
            for i, (cpp_name, source_expr, width, mask, stall_conds) in enumerate(pipeline_reg_updates):
                cpp_type = self._cpp_type(width)
                self._emit(f"{cpp_type} _new_{i} = ({source_expr}) & {mask};")
            self._emit()

        # Now emit regular register updates
        for cpp_name, source_expr, width, mask, stall_cond in regular_reg_updates:
            if stall_cond:
                # Gate the write when stalled - don't update if stall is active
                self._emit(f"if (!{stall_cond}) {{")
                self.indent_level += 1
                self._emit(f"{cpp_name} = ({source_expr}) & {mask};")
                self.indent_level -= 1
                self._emit("}")
            else:
                self._emit(f"{cpp_name} = ({source_expr}) & {mask};")

        # Now emit memory writes
        for node in memory_write_nodes:
            self._generate_memory_write(node)

        # Finally, update pipeline registers using the pre-captured temporaries
        if pipeline_reg_updates:
            self._emit()
            self._emit("// Update pipeline registers with pre-captured values")
            for i, (cpp_name, source_expr, width, mask, stall_conds) in enumerate(pipeline_reg_updates):
                if stall_conds:
                    # Don't update if any stall condition is active
                    stall_check = " || ".join(stall_conds)
                    self._emit(f"if (!({stall_check})) {cpp_name} = _new_{i};")
                else:
                    self._emit(f"{cpp_name} = _new_{i};")

        self._emit("cycle_count++;")
        self.indent_level -= 1
        self._emit("}")

    def _generate_memory_write(self, node: Node):
        """Generate memory write code."""
        mem_name = None
        addr_expr = None
        data_expr = None
        enable_expr = "1"
        byte_enable_info = []  # List of (byte_enable_expr, instr_name)

        # Get the store_byte_enables mapping to gate byte enables by instruction enable
        store_byte_enables = node.data.get('store_byte_enables', {})

        for edge in node.incoming_edges:
            edge_type = edge.data.get('type', '')
            if edge_type == 'write_address':
                addr_expr = self._get_operand_expr(edge.source)
            elif edge_type == 'write_data':
                data_expr = self._get_operand_expr(edge.source)
            elif edge_type == 'write_enable':
                enable_expr = self._get_operand_expr(edge.source)
            elif edge_type == 'byte_enable':
                be_name = self._get_operand_expr(edge.source)
                # Find which instruction this byte enable belongs to
                instr_name = None
                for instr, be_node_name in store_byte_enables.items():
                    if be_node_name == edge.source.id:
                        instr_name = instr
                        break
                byte_enable_info.append((be_name, instr_name))

        for edge in node.outgoing_edges:
            if edge.data.get('type') == 'memory_write':
                mem_name = self._sanitize_name(edge.target.id, ensure_unique=False)
                break

        if mem_name and addr_expr and data_expr:
            # Get memory info for address masking
            mem_info = None
            for mem_id, info in self.memories.items():
                if self._sanitize_name(mem_id, ensure_unique=False) == mem_name:
                    mem_info = info
                    break

            if mem_info:
                addr_mask = self._mask(mem_info['addr_width'])
                data_mask = self._mask(mem_info['width'])
                data_width = mem_info.get('width', 32)
                is_byte_addressed = mem_info.get('is_byte_addressed', False)

                # Convert byte address to word address for byte-addressed memories
                byte_shift = 0
                if is_byte_addressed:
                    if data_width == 32:
                        byte_shift = 2
                    elif data_width == 16:
                        byte_shift = 1
                    elif data_width == 64:
                        byte_shift = 3

                self._emit(f"if ({enable_expr}) {{")
                self.indent_level += 1

                # Generate address expression
                if byte_shift > 0:
                    addr_calc = f"({addr_expr} >> {byte_shift}) & {addr_mask}"
                else:
                    addr_calc = f"{addr_expr} & {addr_mask}"

                # Build byte enable expressions with proper pipeline stage detection
                # For pipelined processors, we need to use the pipelined version of
                # instruction enables that matches the stage where memory writes occur
                byte_enable_exprs = []
                if byte_enable_info:
                    # Detect pipeline stage from expressions that reference PIPE registers
                    # Try: 1) address expr, 2) enable expr, 3) search for pipelined instr enables
                    # Pattern like PIPE_Memory_... or PIPE_ExecuteMemoryWriteback_... indicates stage
                    pipeline_stage = None
                    for expr_to_check in [addr_expr, enable_expr]:
                        stage_match = re.match(r'PIPE_([A-Z][A-Za-z]+)_', expr_to_check)
                        if stage_match:
                            pipeline_stage = stage_match.group(1)
                            break

                    for be_name, instr_name in byte_enable_info:
                        if instr_name:
                            base_enable = f"{instr_name}_enable"
                            # Look for pipelined version of the enable signal
                            pipelined_enable = None

                            # Search for a pipelined enable matching the stage
                            # Pattern varies by pipeline depth:
                            # - 5-stage: PIPE_Memory_PIPE_Execute_sh_enable_PIPE_PIPE
                            # - 3-stage: PIPE_ExecuteMemoryWriteback_sh_enable_PIPE
                            instr_enable_suffix = f"{instr_name}_enable"

                            if pipeline_stage:
                                stage_prefix = f"PIPE_{pipeline_stage}_"
                                for reg_name in self.registers:
                                    if reg_name.startswith(stage_prefix) and instr_enable_suffix in reg_name:
                                        pipelined_enable = reg_name
                                        break

                            # If no stage detected or no match found, search all registers for
                            # any pipelined version of this instruction's enable
                            if not pipelined_enable:
                                for reg_name in self.registers:
                                    if reg_name.startswith('PIPE_') and instr_enable_suffix in reg_name:
                                        # Prefer the deepest pipeline stage (most _PIPE suffixes)
                                        if pipelined_enable is None or reg_name.count('_PIPE') > pipelined_enable.count('_PIPE'):
                                            pipelined_enable = reg_name

                            enable_to_use = pipelined_enable if pipelined_enable else base_enable
                            byte_enable_exprs.append(f"({enable_to_use} ? {be_name} : 0)")
                        else:
                            byte_enable_exprs.append(be_name)

                # Check if we need byte-lane handling (for subword stores)
                if byte_enable_exprs:
                    # Combine byte enables with OR (only one store type active at a time)
                    byte_en_combined = " | ".join(byte_enable_exprs)
                    # Generate byte mask from byte enable (each bit enables one byte)
                    # For 64-bit memory, byte_enable is 8-bit; for 32-bit, it's 4-bit
                    if data_width == 64:
                        # 64-bit memory: byte_en is 8-bit, mask is 64-bit
                        self._emit(f"uint64_t _byte_en = {byte_en_combined};")
                        self._emit(f"if (_byte_en == 0) _byte_en = 0xFF;  // Full doubleword store")
                        self._emit(f"uint64_t _byte_mask = ((_byte_en & 1) ? 0x00000000000000FFULL : 0) | "
                                  f"((_byte_en & 2) ? 0x000000000000FF00ULL : 0) | "
                                  f"((_byte_en & 4) ? 0x0000000000FF0000ULL : 0) | "
                                  f"((_byte_en & 8) ? 0x00000000FF000000ULL : 0) | "
                                  f"((_byte_en & 16) ? 0x000000FF00000000ULL : 0) | "
                                  f"((_byte_en & 32) ? 0x0000FF0000000000ULL : 0) | "
                                  f"((_byte_en & 64) ? 0x00FF000000000000ULL : 0) | "
                                  f"((_byte_en & 128) ? 0xFF00000000000000ULL : 0);")
                        self._emit(f"uint64_t _old_val = {mem_name}[{addr_calc}];")
                        self._emit(f"{mem_name}[{addr_calc}] = (_old_val & ~_byte_mask) | (({data_expr}) & _byte_mask);")
                    else:
                        # 32-bit memory: byte_en is 4-bit, mask is 32-bit
                        self._emit(f"uint32_t _byte_en = {byte_en_combined};")
                        self._emit(f"if (_byte_en == 0) _byte_en = 0xF;  // Full word store")
                        self._emit(f"uint32_t _byte_mask = ((_byte_en & 1) ? 0x000000FF : 0) | "
                                  f"((_byte_en & 2) ? 0x0000FF00 : 0) | "
                                  f"((_byte_en & 4) ? 0x00FF0000 : 0) | "
                                  f"((_byte_en & 8) ? 0xFF000000 : 0);")
                        self._emit(f"uint32_t _old_val = {mem_name}[{addr_calc}];")
                        self._emit(f"{mem_name}[{addr_calc}] = (_old_val & ~_byte_mask) | (({data_expr}) & _byte_mask);")
                else:
                    self._emit(f"{mem_name}[{addr_calc}] = ({data_expr}) & {data_mask};")

                self.indent_level -= 1
                self._emit("}")

    def _generate_cycle_method(self):
        """Generate the main cycle execution method."""
        self._emit()
        self._emit("void cycle() {")
        self.indent_level += 1
        self._emit("if (halted) return;")
        self._emit("compute_combinational();")
        self._emit("update_sequential();")
        self._emit("// Recompute combinational logic so derived values reflect new register state")
        self._emit("compute_combinational();")
        self.indent_level -= 1
        self._emit("}")

    def _generate_reset_method(self):
        """Generate reset method."""
        self._emit()
        self._emit("void reset() {")
        self.indent_level += 1
        self._emit("cycle_count = 0;")
        self._emit("halted = false;")

        # Reset registers to initial values (use the registers dict)
        for cpp_name, info in sorted(self.registers.items()):
            initial = info.get('initial_value', 0)
            self._emit(f"{cpp_name} = {initial};")

        # Reset memories
        for mem_name in self.memories:
            cpp_name = self._sanitize_name(mem_name, ensure_unique=False)
            self._emit(f"{cpp_name}.fill(0);")

        # Initialize memory latency signals for C++ sim backend
        # In C++ sim, memory is always single-cycle (operations happen inline)
        # So complete=1 and idle=1 regardless of ISA-specified latency
        for node_id, node in self.graph.nodes.items():
            mem_name_prefix = None
            # Check if this is a memory node with complete/idle signals
            if node.data.get('is_memory') or 'mem' in node.data.get('type', ''):
                mem_name_prefix = node_id
                # For C++ sim backend, always set complete=1 and idle=1
                # (the ISA may specify variable latency, but we model as single-cycle)
                complete_name = f"{mem_name_prefix}_complete"
                idle_name = f"{mem_name_prefix}_idle"
                if complete_name in self.wires:
                    cpp_name = self._sanitize_name(complete_name, ensure_unique=False)
                    self._emit(f"{cpp_name} = 1;  // Single-cycle memory: always complete")
                if idle_name in self.wires:
                    cpp_name = self._sanitize_name(idle_name, ensure_unique=False)
                    self._emit(f"{cpp_name} = 1;  // Single-cycle memory: always idle")

        self.indent_level -= 1
        self._emit("}")

    def _generate_memory_load_methods(self):
        """Generate methods to load memory from files."""
        self._emit()
        self._emit("// Load memory from binary file")
        self._emit("bool load_memory(const std::string& filename, const std::string& mem_name, uint64_t offset = 0) {")
        self.indent_level += 1
        self._emit("std::ifstream file(filename, std::ios::binary);")
        self._emit("if (!file) return false;")
        self._emit()

        for mem_name, mem_info in sorted(self.memories.items()):
            cpp_name = self._sanitize_name(mem_name, ensure_unique=False)
            elem_size = mem_info['width'] // 8
            self._emit(f'if (mem_name == "{mem_name}") {{')
            self.indent_level += 1
            self._emit(f"file.read(reinterpret_cast<char*>({cpp_name}.data() + offset), "
                       f"{cpp_name}.size() * {elem_size});")
            self._emit("return true;")
            self.indent_level -= 1
            self._emit("}")

        self._emit("return false;")
        self.indent_level -= 1
        self._emit("}")

        self._emit()
        self._emit("// Load memory from hex file")
        self._emit("bool load_memory_hex(const std::string& filename, const std::string& mem_name) {")
        self.indent_level += 1
        self._emit("std::ifstream file(filename);")
        self._emit("if (!file) return false;")
        self._emit()

        for mem_name, mem_info in sorted(self.memories.items()):
            cpp_name = self._sanitize_name(mem_name, ensure_unique=False)
            self._emit(f'if (mem_name == "{mem_name}") {{')
            self.indent_level += 1
            self._emit("std::string line;")
            self._emit("size_t addr = 0;")
            self._emit("while (std::getline(file, line) && addr < " + cpp_name + ".size()) {")
            self.indent_level += 1
            self._emit("if (line.empty() || line[0] == '/' || line[0] == '#') continue;")
            self._emit(f"{cpp_name}[addr++] = std::stoull(line, nullptr, 16);")
            self.indent_level -= 1
            self._emit("}")
            self._emit("return true;")
            self.indent_level -= 1
            self._emit("}")

        self._emit("return false;")
        self.indent_level -= 1
        self._emit("}")

    def _generate_accessors(self):
        """Generate accessor methods for state inspection."""
        self._emit()
        self._emit("// State accessors")

        # Register accessors (use self.registers dict)
        for cpp_name, info in sorted(self.registers.items()):
            width = info['width']
            cpp_type = self._cpp_type(width)
            self._emit(f"{cpp_type} get_{cpp_name}() const {{ return {cpp_name}; }}")
            self._emit(f"void set_{cpp_name}({cpp_type} val) {{ {cpp_name} = val; }}")

        # Memory accessors
        for mem_name, mem_info in sorted(self.memories.items()):
            cpp_name = self._sanitize_name(mem_name, ensure_unique=False)
            elem_type = self._cpp_type(mem_info['width'])
            self._emit(f"{elem_type} read_{cpp_name}(size_t addr) const {{ return {cpp_name}[addr]; }}")
            self._emit(f"void write_{cpp_name}(size_t addr, {elem_type} val) {{ {cpp_name}[addr] = val; }}")

        self._emit()
        self._emit("uint64_t get_cycle_count() const { return cycle_count; }")
        self._emit("bool is_halted() const { return halted; }")
        self._emit("void halt() { halted = true; }")

    def _generate_dump_method(self):
        """Generate state dump method for debugging."""
        self._emit()
        self._emit("void dump_state(std::ostream& os = std::cout) const {")
        self.indent_level += 1
        self._emit('os << "=== Processor State (cycle " << cycle_count << ") ===" << std::endl;')

        # Dump registers (use self.registers dict)
        for cpp_name, info in sorted(self.registers.items()):
            width = info['width']
            if width <= 64:
                # Adjust setw based on width
                hex_chars = (width + 3) // 4
                self._emit(f'os << "{cpp_name}: 0x" << std::hex << std::setw({hex_chars}) << std::setfill(\'0\') << {cpp_name} << std::dec << std::endl;')
            else:
                # Wide registers (e.g., __uint128_t) don't have ostream support
                # Print a placeholder instead
                self._emit(f'os << "{cpp_name}: <{width}-bit value>" << std::endl;')

        self.indent_level -= 1
        self._emit("}")

    def _generate_footer(self):
        """Generate class closing."""
        self.indent_level -= 1
        self._emit("};")

    def generate(self) -> str:
        """
        Generate complete C++ simulation code.

        Returns:
            C++ source code as a string
        """
        self.lines = []
        self.indent_level = 0

        # Analyze graph
        self._analyze_graph()

        # Generate code sections
        self._generate_header()
        self._generate_state_members()
        self._generate_wire_declarations()
        self._generate_combinational_logic()
        self._generate_sequential_logic()
        self._generate_cycle_method()
        self._generate_reset_method()
        self._generate_memory_load_methods()
        self._generate_accessors()
        self._generate_dump_method()
        self._generate_footer()

        return '\n'.join(self.lines)


def generate_cpp_sim(graph: ResourceGraph, module_name: str = "processor") -> str:
    """
    Convenience function to generate C++ simulation code from a ResourceGraph.

    Args:
        graph: The ResourceGraph to convert
        module_name: Name for the generated C++ class

    Returns:
        C++ source code as a string
    """
    generator = CppSimGenerator(graph, module_name)
    return generator.generate()
