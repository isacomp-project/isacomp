"""
RTLIL Backend for ISAComp

Generates Yosys RTLIL (.il) text from ResourceGraph intermediate representations.
The output can be processed by Yosys for simulation (write_cxxrtl), synthesis,
or further transformations.

This generator parses ResourceGraph nodes/edges generically - it is not
specific to any ISA.
"""

from typing import Dict, List, Optional, Set, Tuple
from collections import deque
from core.resource_graph import ResourceGraph, Node, Edge
import re


class RTLILGenerator:
    """Generate RTLIL text from a ResourceGraph."""

    def __init__(self, graph: ResourceGraph, module_name: str = "processor"):
        self.graph = graph
        self.module_name = module_name

        # Signal tracking
        self.node_to_wire: Dict[str, str] = {}   # node.id -> RTLIL wire name
        self.wire_widths: Dict[str, int] = {}     # wire name -> width
        self.declared_wires: Set[str] = set()
        self.name_counter: Dict[str, int] = {}

        # Generation state
        self._port_index = 0
        self._cell_counter = 0
        self._lines: List[str] = []

        # Memory tracking
        self.memories: Dict[str, dict] = {}       # mem name -> {width, depth, ...}

        # Bit-width inference cache
        self._width_cache: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self) -> str:
        """Generate complete RTLIL module from the ResourceGraph."""
        self._analyze_graph()
        self._lines = []
        self._emit(f"autoidx 1")
        self._emit(f"module \\{self.module_name}")

        # Ports
        self._generate_ports()

        # Internal wires
        self._generate_wire_declarations()

        # Memories
        self._generate_memory_declarations()

        # Combinational logic cells
        self._generate_combinational_logic()

        # Sequential logic (process blocks with sync posedge clk)
        self._generate_sequential_logic()

        self._emit("end")
        return "\n".join(self._lines) + "\n"

    # ------------------------------------------------------------------
    # Identifier handling
    # ------------------------------------------------------------------

    def _sanitize(self, name: str) -> str:
        """Sanitize a node ID into a valid RTLIL identifier fragment."""
        s = name
        s = re.sub(r'0b([01]*)(\*+)', lambda m: f'0b{m.group(1)}{"x" * len(m.group(2))}', s)
        s = s.replace('.', '_')
        s = s.replace('@', '_at_')
        s = s.replace('[', '_').replace(']', '_').replace(':', '_')
        s = s.replace('(', '_').replace(')', '_').replace(' ', '_')
        s = s.replace("'", '_').replace('{', '_').replace('}', '_')
        s = s.replace(',', '_').replace('?', '_').replace('$', '_')
        s = s.replace('+', 'add').replace('-', 'sub')
        s = s.replace('*', 'mul').replace('/s', 'divs').replace('/', 'div')
        s = s.replace('%s', 'mods').replace('%', 'mod')
        s = s.replace('&', 'and').replace('|', 'or').replace('^', 'xor')
        s = s.replace('>>>', 'srlgt').replace('<<', 'sll').replace('>>', 'srl')
        s = s.replace('==', 'eq').replace('!=', 'ne')
        s = s.replace('<=', 'le').replace('>=', 'ge')
        s = s.replace('<', 'lt').replace('>', 'gt')
        s = s.replace('=', 'eq')
        s = s.replace('!', 'not').replace('~', 'inv')
        while '__' in s:
            s = s.replace('__', '_')
        s = s.strip('_')
        if s and s[0].isdigit():
            s = 'w_' + s
        return s

    def _wire_name(self, node_id: str) -> str:
        """Get the RTLIL wire reference for a node, with leading backslash."""
        if node_id in self.node_to_wire:
            return self.node_to_wire[node_id]
        name = self._sanitize(node_id)
        self.node_to_wire[node_id] = f"\\{name}"
        return f"\\{name}"

    def _unique_cell_id(self, prefix: str = "cell") -> str:
        self._cell_counter += 1
        return f"${prefix}${self._cell_counter}"

    # ------------------------------------------------------------------
    # Bit-width inference (mirrors Verilog backend logic)
    # ------------------------------------------------------------------

    def _infer_width(self, node: Node, depth: int = 0, visited: Optional[Set[str]] = None) -> int:
        if visited is None:
            visited = set()
        if node.id in self._width_cache:
            return self._width_cache[node.id]
        if node.id in visited or depth > 20:
            return 32
        visited.add(node.id)

        w = self._infer_width_impl(node, depth, visited)
        self._width_cache[node.id] = w
        return w

    def _infer_width_impl(self, node: Node, depth: int, visited: Set[str]) -> int:
        ntype = node.data.get('type', '')

        # Explicit widths
        if ntype != 'array_access':
            if 'port_width' in node.data and node.data['port_width'] is not None:
                return node.data['port_width']
            if 'bit_width' in node.data and node.data['bit_width'] is not None:
                return node.data['bit_width']

        # Boolean-producing operations
        if self._is_boolean(node):
            return 1

        if ntype == 'literal':
            return node.data.get('width', 32)

        if ntype == 'bit_slice':
            hi, lo = self._get_bit_range(node)
            if hi is not None and lo is not None:
                return hi - lo + 1

        if ntype == 'binary_literal':
            expr = node.data.get('expression', {})
            if expr.get('type') == 'binary_literal':
                return expr.get('width', 1)
            return node.data.get('width', 1)

        if ntype in ('verilog_hex_literal', 'verilog_dec_literal'):
            return node.data.get('width', 32)

        if ntype == 'repetition':
            count = node.data.get('count', 1)
            expr = node.data.get('expression', {})
            if expr.get('type') == 'repetition':
                count = expr.get('count', count)
            if node.incoming_edges:
                src = next(iter(node.incoming_edges)).source
                inner = self._infer_width(src, depth + 1, visited)
                return count * inner
            return count

        if ntype == 'concatenation':
            if node.incoming_edges:
                total = 0
                for edge in sorted(node.incoming_edges, key=lambda e: e.source.id):
                    total += self._infer_width(edge.source, depth + 1, visited)
                return total

        if ntype == 'multiplexer':
            widths = []
            for edge in node.incoming_edges:
                if edge.data.get('type') in ('mux_input', 'mux_default_input'):
                    widths.append(self._infer_width(edge.source, depth + 1, visited))
            if widths:
                return max(widths)

        if ntype in ('ternary', 'ternary_op'):
            widths = []
            for edge in node.incoming_edges:
                et = edge.data.get('type', '')
                if et in ('ternary_true', 'ternary_false'):
                    widths.append(self._infer_width(edge.source, depth + 1, visited))
            if widths:
                return max(widths)

        if ntype == 'zero_extend':
            return node.data.get('bit_width', 32)

        if ntype == 'sign_extend':
            return node.data.get('bit_width', 32)

        if ntype == 'array_access':
            # Width comes from the memory element width
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'array_base':
                    mem = edge.source
                    pw = mem.data.get('port_width')
                    if pw:
                        return pw
                    bw = mem.data.get('bit_width')
                    if bw:
                        return bw

        if ntype == 'var':
            if node.data.get('width') is not None:
                return node.data['width']
            if node.data.get('bit_width') is not None:
                return node.data['bit_width']
            for edge in node.incoming_edges:
                if edge.data.get('type') != 'validity_check':
                    return self._infer_width(edge.source, depth + 1, visited)

        if ntype == 'comparison':
            return 1

        if ntype in ('logical_and', 'logical_or', 'logical_not'):
            return 1

        if ntype == 'instruction_enable':
            return 1

        # Pipeline-specific: stall controllers and control signals are 1-bit
        if ntype in ('pipeline_stall_controller', 'control_signal', 'validity_bit'):
            return node.data.get('bit_width', 1)

        # Pipeline registers: trace width from data input (pipeline_input edge)
        if ntype == 'pipeline_register':
            if node.data.get('bit_width') is not None:
                return node.data['bit_width']
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'pipeline_input':
                    return self._infer_width(edge.source, depth + 1, visited)
            return 32

        # flush_target_placeholder is unused
        if ntype == 'flush_target_placeholder':
            return 1

        if ntype == 'operation':
            op = node.data.get('operator', '')
            # Comparison and logical ops produce 1-bit
            if op in ('==', '!=', '<', '>', '<=', '>=', '<s', '>s', '<=s', '>=s',
                       '&&', '||', '!'):
                return 1
            # For arithmetic/bitwise ops, infer from operands
            widths = []
            for edge in node.incoming_edges:
                widths.append(self._infer_width(edge.source, depth + 1, visited))
            if widths:
                return max(widths)

        # ISA state
        if ntype in ('isa_state', 'isa_state mem'):
            bw = node.data.get('bit_width')
            if bw:
                return bw

        return 32  # fallback

    def _is_boolean(self, node: Node) -> bool:
        ntype = node.data.get('type', '')
        if ntype in ('comparison', 'logical_and', 'logical_or', 'logical_not',
                      'instruction_enable'):
            return True
        if ntype == 'operation':
            op = node.data.get('operator', '')
            if op in ('==', '!=', '<', '>', '<=', '>=', '<s', '>s', '<=s', '>=s',
                       '&&', '||', '!'):
                return True
        return False

    def _get_bit_range(self, node: Node) -> Tuple[Optional[int], Optional[int]]:
        """Extract (high, low) bit range from a bit_slice node."""
        if 'high_bit' in node.data and 'low_bit' in node.data:
            return node.data['high_bit'], node.data['low_bit']
        if 'high' in node.data and 'low' in node.data:
            return node.data['high'], node.data['low']
        if 'bitslice' in node.data:
            return node.data['bitslice']
        expr = node.data.get('expression', {})
        if expr.get('type') == 'bit_slice' and 'range' in expr:
            return expr['range']
        return None, None

    # ------------------------------------------------------------------
    # Graph analysis
    # ------------------------------------------------------------------

    def _analyze_graph(self):
        """Pre-pass: map every node to a wire name and infer widths."""
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            name = self._wire_name(node.id)
            width = self._infer_width(node)
            self.wire_widths[name] = width

            ntype = node.data.get('type', '')
            # Track memories
            if node.data.get('is_memory', False) and ntype in ('isa_state', 'isa_state mem'):
                raw_depth = node.data.get('array_depth', 5)
                if node.data.get('is_cam', False):
                    array_depth = raw_depth
                else:
                    array_depth = min(2 ** raw_depth, 67108864)
                self.memories[node.id] = {
                    'width': width,
                    'depth': array_depth,
                    'addr_width': raw_depth,
                    'port_width': node.data.get('port_width', width),
                    'endianness': node.data.get('endianness', 'little'),
                    'write_read_fwd': node.data.get('write_read_fwd', False),
                }

        # Pre-scan write ports for write-read forwarding
        self.memory_write_info = {}  # mem_name -> {addr, data, enable}
        for node in self.graph.nodes.values():
            if node.data.get('type') == 'memory_write_port':
                base_mem = node.data.get('base_memory')
                if base_mem and self.memories.get(base_mem, {}).get('write_read_fwd'):
                    addr_node = data_node = enable_node = None
                    for edge in node.incoming_edges:
                        etype = edge.data.get('type')
                        if etype == 'write_address':
                            addr_node = edge.source
                        elif etype == 'write_data':
                            data_node = edge.source
                        elif etype == 'write_enable':
                            enable_node = edge.source
                    if addr_node and data_node and enable_node:
                        self.memory_write_info[base_mem] = {
                            'addr': addr_node, 'data': data_node, 'enable': enable_node,
                        }

    def _get_dependency_order(self) -> List[Node]:
        """Topological sort of nodes for combinational logic generation."""
        dep_types = {'operand', 'array_index', 'bit_access', 'logic_input',
                     'concatenation_input', 'repetition_input', 'mux_input',
                     'mux_default_input', 'ternary_condition', 'ternary_true',
                     'ternary_false', 'left_operand', 'right_operand',
                     'decode_enable', 'control', 'mux_select'}

        all_nodes = {}
        in_degree = {}
        dependents = {}

        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            all_nodes[node.id] = node
            in_degree[node.id] = 0
            dependents[node.id] = []

        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            for edge in node.incoming_edges:
                if edge.data.get('type') in dep_types and edge.source.id in all_nodes:
                    in_degree[node.id] += 1
                    dependents[edge.source.id].append(node.id)

        queue = deque()
        for nid, deg in sorted(in_degree.items()):
            if deg == 0:
                queue.append(nid)

        ordered = []
        while queue:
            nid = queue.popleft()
            ordered.append(all_nodes[nid])
            for dep in sorted(dependents[nid]):
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    queue.append(dep)

        for nid, node in sorted(all_nodes.items()):
            if node not in ordered:
                ordered.append(node)

        return ordered

    # ------------------------------------------------------------------
    # RTLIL emission helpers
    # ------------------------------------------------------------------

    def _emit(self, line: str):
        self._lines.append(line)

    def _next_port_index(self) -> int:
        self._port_index += 1
        return self._port_index

    def _const(self, value: int, width: int) -> str:
        """Format an integer constant as an RTLIL bit-string."""
        if width <= 0:
            width = 1
        if value < 0:
            # two's complement
            value = value & ((1 << width) - 1)
        bits = bin(value)[2:].zfill(width)[-width:]
        # RTLIL bit-strings are MSB first
        return f"{width}'{bits}"

    def _sigspec(self, node_id: str) -> str:
        """Get the sigspec (wire reference) for a node."""
        return self._wire_name(node_id)

    def _sig_width(self, node_id: str) -> int:
        node = self.graph.nodes.get(node_id)
        if node:
            return self._infer_width(node)
        wn = self._wire_name(node_id)
        return self.wire_widths.get(wn, 32)

    # ------------------------------------------------------------------
    # Port generation
    # ------------------------------------------------------------------

    def _generate_ports(self):
        # clk and reset
        clk_idx = self._next_port_index()
        self._emit(f"  wire width 1 input {clk_idx} \\clk")
        self.declared_wires.add("\\clk")

        rst_idx = self._next_port_index()
        self._emit(f"  wire width 1 input {rst_idx} \\reset")
        self.declared_wires.add("\\reset")

        # Find ISA state _rd nodes that have a corresponding reset input
        # e.g., pc_rd gets an input port reset_pc_rd
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            if not node.id.endswith('_rd'):
                continue
            if not node.is_arch_state:
                continue
            if node.data.get('is_memory', False):
                continue
            ntype = node.data.get('type', '')
            if ntype not in ('isa_state',):
                continue
            # Create a reset value input port
            wn = self._wire_name(node.id)
            w = self.wire_widths.get(wn, 32)
            reset_name = f"\\reset_{self._sanitize(node.id)}"
            if reset_name not in self.declared_wires:
                pidx = self._next_port_index()
                self._emit(f"  wire width {w} input {pidx} {reset_name}")
                self.declared_wires.add(reset_name)

        # External input/output ports
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            is_ext = node.data.get('is_external', False)
            is_push = node.data.get('is_push', False)
            is_sensitive = node.data.get('is_sensitive', False)
            if is_ext and not is_push:
                wn = self._wire_name(node.id)
                w = self.wire_widths.get(wn, 32)
                if wn not in self.declared_wires:
                    pidx = self._next_port_index()
                    self._emit(f"  wire width {w} input {pidx} {wn}")
                    self.declared_wires.add(wn)
            elif is_ext and is_push:
                wn = self._wire_name(node.id)
                w = self.wire_widths.get(wn, 32)
                if wn not in self.declared_wires:
                    pidx = self._next_port_index()
                    self._emit(f"  wire width {w} output {pidx} {wn}")
                    self.declared_wires.add(wn)

    # ------------------------------------------------------------------
    # Wire declarations
    # ------------------------------------------------------------------

    def _generate_wire_declarations(self):
        self._emit("")
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            wn = self._wire_name(node.id)
            if wn in self.declared_wires:
                continue
            ntype = node.data.get('type', '')

            # Skip memory nodes - they're declared separately
            if node.data.get('is_memory', False) and ntype in ('isa_state', 'isa_state mem'):
                continue
            # Skip memory_write_port and flush_target_placeholder nodes
            if ntype in ('memory_write_port', 'flush_target_placeholder'):
                continue

            w = self.wire_widths.get(wn, 32)

            # Mark ISA state wires with keep attribute so Yosys
            # doesn't optimize them away (needed for CXXRTL testbenches)
            if node.is_arch_state and ntype == 'isa_state':
                self._emit(f"  attribute \\keep 1")

            self._emit(f"  wire width {w} {wn}")
            self.declared_wires.add(wn)

    # ------------------------------------------------------------------
    # Memory declarations
    # ------------------------------------------------------------------

    def _generate_memory_declarations(self):
        if not self.memories:
            return
        self._emit("")
        for mem_name, info in sorted(self.memories.items()):
            rtlil_name = f"\\{self._sanitize(mem_name)}"
            # Mark memories with keep attribute so Yosys doesn't
            # optimize them away (needed for CXXRTL testbenches)
            self._emit(f"  attribute \\keep 1")
            self._emit(f"  memory width {info['width']} size {info['depth']} {rtlil_name}")

    # ------------------------------------------------------------------
    # Combinational logic
    # ------------------------------------------------------------------

    def _generate_combinational_logic(self):
        self._emit("")
        processed = set()
        assigned = set()

        for node in self._get_dependency_order():
            if node.id in processed:
                continue
            ntype = node.data.get('type', '')

            # Skip memory containers and write ports
            if ntype in ('isa_state', 'isa_state mem') and node.data.get('is_memory'):
                processed.add(node.id)
                continue
            if ntype == 'memory_write_port':
                processed.add(node.id)
                continue

            wn = self._wire_name(node.id)
            if wn in assigned:
                processed.add(node.id)
                continue

            generated = False

            if ntype in ('operation', 'binary_op'):
                generated = self._gen_operation(node, wn)
            elif ntype == 'bit_slice':
                generated = self._gen_bit_slice(node, wn)
            elif ntype == 'comparison':
                generated = self._gen_comparison(node, wn)
            elif ntype in ('logical_and', 'logical_or'):
                generated = self._gen_logical(node, wn)
            elif ntype == 'logical_not':
                generated = self._gen_logical_not(node, wn)
            elif ntype == 'instruction_enable':
                generated = self._gen_instruction_enable(node, wn)
            elif ntype == 'literal':
                generated = self._gen_literal(node, wn)
            elif ntype == 'binary_literal':
                generated = self._gen_binary_literal(node, wn)
            elif ntype in ('verilog_hex_literal', 'verilog_dec_literal'):
                generated = self._gen_hex_literal(node, wn)
            elif ntype == 'concatenation':
                generated = self._gen_concatenation(node, wn)
            elif ntype == 'repetition':
                generated = self._gen_repetition(node, wn)
            elif ntype in ('ternary', 'ternary_op'):
                generated = self._gen_ternary(node, wn)
            elif ntype == 'zero_extend':
                generated = self._gen_zero_extend(node, wn)
            elif ntype == 'sign_extend':
                generated = self._gen_sign_extend(node, wn)
            elif ntype == 'array_access':
                generated = self._gen_array_access(node, wn)
            elif ntype == 'multiplexer':
                generated = self._gen_multiplexer(node, wn)
            elif ntype == 'var':
                generated = self._gen_var_assignment(node, wn)
            elif ntype == 'isa_state' and not node.data.get('is_memory'):
                # _rd nodes may need connections
                generated = self._gen_isa_state_wire(node, wn)
            elif ntype == 'pipeline_stall_controller':
                generated = self._gen_stall_controller(node, wn)
            elif ntype == 'control_signal':
                generated = self._gen_control_signal(node, wn)
            elif ntype in ('pipeline_register', 'validity_bit'):
                # Sequential - handled in _generate_sequential_logic
                generated = True
            elif ntype == 'flush_target_placeholder':
                generated = True  # Skip

            if generated:
                assigned.add(wn)
            processed.add(node.id)

    # ------------------------------------------------------------------
    # Cell generators for each node type
    # ------------------------------------------------------------------

    def _gen_operation(self, node: Node, wn: str) -> bool:
        """Generate RTLIL cell for an operation node."""
        operator = node.data.get('operator', '+')
        yw = self._infer_width(node)

        # n-ary || / && => chain of $reduce_or / $reduce_and or pairwise cells
        if operator in ('||', '&&', '|', '&') and len(node.incoming_edges) > 2:
            return self._gen_nary_logic(node, wn, operator)

        # Unary operations
        if len(node.incoming_edges) == 1:
            return self._gen_unary_op(node, wn, operator)

        # Unary NOT from node id (e.g., !beq_res -> notbeq_res)
        if len(node.incoming_edges) == 0 and (operator == '!' or node.id.startswith('!')):
            return self._gen_not_from_id(node, wn)

        # Binary operations
        if len(node.incoming_edges) >= 2:
            return self._gen_binary_op(node, wn, operator)

        return False

    def _gen_binary_op(self, node: Node, wn: str, operator: str) -> bool:
        """Generate a binary RTLIL cell ($add, $sub, etc.)."""
        left, right = self._get_lr_operands(node)
        if left is None or right is None:
            return False

        lw = self._infer_width(left)
        rw = self._infer_width(right)
        yw = self._infer_width(node)

        a_needs_signed = operator in ('<s', '>s', '<=s', '>=s', '>>>', '/s', '%s')

        # Map operator to RTLIL cell type
        cell_map = {
            '+': '$add', '-': '$sub', '*': '$mul',
            '/': '$div', '%': '$mod', '/s': '$div', '%s': '$mod',
            '&': '$and', '|': '$or', '^': '$xor',
            '<<': '$shl', '>>': '$shr', '>>>': '$sshr',
            '==': '$eq', '!=': '$ne',
            '<': '$lt', '>': '$gt', '<=': '$le', '>=': '$ge',
            '<s': '$lt', '>s': '$gt', '<=s': '$le', '>=s': '$ge',
            '&&': '$logic_and', '||': '$logic_or',
        }
        cell_type = cell_map.get(operator)
        if not cell_type:
            return False

        a_signed = 1 if a_needs_signed else 0
        # Shift amounts are never signed; for signed comparisons/division, B is signed
        if operator in ('>>>', '<<', '>>', '$shl', '$shr', '$sshr'):
            b_signed = 0
        else:
            b_signed = 1 if a_needs_signed else 0

        cid = self._unique_cell_id(cell_type[1:])
        self._emit(f"  cell {cell_type} {cid}")
        self._emit(f"    parameter \\A_SIGNED {a_signed}")
        self._emit(f"    parameter \\B_SIGNED {b_signed}")
        self._emit(f"    parameter \\A_WIDTH {lw}")
        self._emit(f"    parameter \\B_WIDTH {rw}")
        self._emit(f"    parameter \\Y_WIDTH {yw}")
        self._emit(f"    connect \\A {self._sigspec(left.id)}")
        self._emit(f"    connect \\B {self._sigspec(right.id)}")
        self._emit(f"    connect \\Y {wn}")
        self._emit(f"  end")
        return True

    def _gen_unary_op(self, node: Node, wn: str, operator: str) -> bool:
        """Generate a unary RTLIL cell ($not, $logic_not, $neg)."""
        src_edge = next(iter(node.incoming_edges))
        src = src_edge.source
        aw = self._infer_width(src)
        yw = self._infer_width(node)

        expr = node.data.get('expression', {})
        # Check expression type for more context
        if expr.get('type') == 'reduction_op':
            operator = expr.get('operator', operator)

        cell_map = {
            '!': '$logic_not', '~': '$not', '-': '$neg',
            '|': '$reduce_or', '&': '$reduce_and', '^': '$reduce_xor',
            'reduce_|': '$reduce_or', 'reduce_&': '$reduce_and',
            'reduce_^': '$reduce_xor',
        }
        cell_type = cell_map.get(operator, '$logic_not')

        cid = self._unique_cell_id(cell_type[1:])
        self._emit(f"  cell {cell_type} {cid}")
        self._emit(f"    parameter \\A_SIGNED 0")
        self._emit(f"    parameter \\A_WIDTH {aw}")
        self._emit(f"    parameter \\Y_WIDTH {yw}")
        self._emit(f"    connect \\A {self._sigspec(src.id)}")
        self._emit(f"    connect \\Y {wn}")
        self._emit(f"  end")
        return True

    def _gen_not_from_id(self, node: Node, wn: str) -> bool:
        """Generate $logic_not for nodes like !beq_res with no incoming edges."""
        # Derive source from node id
        nid = node.id
        if nid.startswith('!'):
            orig = nid[1:]
        elif nid.startswith('not'):
            orig = nid[3:]
        else:
            return False

        if orig not in self.graph.nodes:
            return False

        src_w = self._sig_width(orig)
        yw = self._infer_width(node)

        cid = self._unique_cell_id("logic_not")
        self._emit(f"  cell $logic_not {cid}")
        self._emit(f"    parameter \\A_SIGNED 0")
        self._emit(f"    parameter \\A_WIDTH {src_w}")
        self._emit(f"    parameter \\Y_WIDTH {yw}")
        self._emit(f"    connect \\A {self._sigspec(orig)}")
        self._emit(f"    connect \\Y {wn}")
        self._emit(f"  end")
        return True

    def _gen_nary_logic(self, node: Node, wn: str, operator: str) -> bool:
        """Generate chained cells for n-ary OR/AND operations."""
        edges = sorted(node.incoming_edges,
                       key=lambda e: (e.data.get('operand_index', 0), e.source.id))
        if len(edges) < 2:
            return False

        cell_type = '$or' if operator in ('||', '|') else '$and'
        yw = self._infer_width(node)

        # Chain: acc = a[0] op a[1]; then acc = acc op a[2]; ...
        prev_sig = self._sigspec(edges[0].source.id)
        prev_w = self._infer_width(edges[0].source)

        for i, edge in enumerate(edges[1:], 1):
            bsig = self._sigspec(edge.source.id)
            bw = self._infer_width(edge.source)

            if i < len(edges) - 1:
                # Intermediate wire
                tmp = f"$nary_{self._sanitize(node.id)}_{i}"
                self._emit(f"  wire width {yw} {tmp}")
                out_sig = tmp
            else:
                out_sig = wn

            cid = self._unique_cell_id(cell_type[1:])
            self._emit(f"  cell {cell_type} {cid}")
            self._emit(f"    parameter \\A_SIGNED 0")
            self._emit(f"    parameter \\B_SIGNED 0")
            self._emit(f"    parameter \\A_WIDTH {prev_w}")
            self._emit(f"    parameter \\B_WIDTH {bw}")
            self._emit(f"    parameter \\Y_WIDTH {yw}")
            self._emit(f"    connect \\A {prev_sig}")
            self._emit(f"    connect \\B {bsig}")
            self._emit(f"    connect \\Y {out_sig}")
            self._emit(f"  end")

            prev_sig = out_sig
            prev_w = yw

        return True

    @staticmethod
    def _parse_literal_value(val) -> int:
        """Parse a literal value that may be int, string hex/bin/dec."""
        if isinstance(val, int):
            return val
        if isinstance(val, str):
            s = val.strip()
            if s.startswith('0x') or s.startswith('0X'):
                return int(s, 16)
            if s.startswith('0b') or s.startswith('0B'):
                return int(s, 2)
            return int(s, 0)
        return 0

    def _gen_comparison(self, node: Node, wn: str) -> bool:
        """Generate RTLIL cell for comparison nodes (decode logic)."""
        op = node.data.get('operation', '==')
        expr = node.data.get('expression', {})

        # Comparisons in the graph typically compare a bit_slice of instr
        # against a constant. Extract from expression.
        if expr.get('type') in ('binary_op', 'comparison'):
            left_expr = expr.get('left', {})
            right_expr = expr.get('right', {})
        else:
            left_expr = {}
            right_expr = {}

        # Find the source signal from incoming edges
        src_nodes = []
        for edge in sorted(node.incoming_edges, key=lambda e: e.source.id):
            src_nodes.append(edge.source)

        if not src_nodes:
            return False

        src = src_nodes[0]

        # Determine what bit range of the source to use and what constant to compare against
        # The expression tells us: e.g., instr[14:12] == 0x0
        slice_hi = None
        slice_lo = None
        cmp_value = 0
        cmp_width = 32

        if left_expr.get('type') == 'bit_slice':
            # Range may be stored as 'range' tuple or as 'high'/'low' sub-expressions
            if 'range' in left_expr:
                slice_hi, slice_lo = left_expr['range']
            elif 'high' in left_expr and 'low' in left_expr:
                hi_expr = left_expr['high']
                lo_expr = left_expr['low']
                slice_hi = hi_expr.get('value', 0) if isinstance(hi_expr, dict) else hi_expr
                slice_lo = lo_expr.get('value', 0) if isinstance(lo_expr, dict) else lo_expr
            if slice_hi is not None and slice_lo is not None:
                cmp_width = slice_hi - slice_lo + 1

        if right_expr.get('type') in ('hex_literal', 'literal'):
            cmp_value = self._parse_literal_value(right_expr.get('value', 0))
            if right_expr.get('width'):
                cmp_width = right_expr['width']
        elif right_expr.get('type') == 'binary_literal':
            cmp_value = self._parse_literal_value(right_expr.get('value', 0))
            if right_expr.get('width'):
                cmp_width = right_expr['width']

        # If we have a bit range, create a slice wire and compare
        if slice_hi is not None and slice_lo is not None:
            slice_wire = f"$cmp_slice_{self._sanitize(node.id)}"
            self._emit(f"  wire width {cmp_width} {slice_wire}")
            # Connect slice: slice_wire = src[hi:lo]
            src_sig = self._sigspec(src.id)
            self._emit(f"  connect {slice_wire} {src_sig} [{slice_hi}:{slice_lo}]")

            cid = self._unique_cell_id("eq")
            self._emit(f"  cell $eq {cid}")
            self._emit(f"    parameter \\A_SIGNED 0")
            self._emit(f"    parameter \\B_SIGNED 0")
            self._emit(f"    parameter \\A_WIDTH {cmp_width}")
            self._emit(f"    parameter \\B_WIDTH {cmp_width}")
            self._emit(f"    parameter \\Y_WIDTH 1")
            self._emit(f"    connect \\A {slice_wire}")
            self._emit(f"    connect \\B {self._const(cmp_value, cmp_width)}")
            self._emit(f"    connect \\Y {wn}")
            self._emit(f"  end")
            return True

        # Direct comparison (no bit slicing) - e.g., byte_mux_sel nodes
        # comparing a selector signal against a constant value
        if left_expr.get('type') == 'identifier' or node.data.get('compare_value') is not None:
            src_sig = self._sigspec(src.id)
            src_w = self._infer_width(src)
            if node.data.get('compare_value') is not None:
                cmp_value = self._parse_literal_value(node.data['compare_value'])
            cmp_width = max(cmp_width, src_w) if right_expr.get('width') else src_w

            cid = self._unique_cell_id("eq")
            self._emit(f"  cell $eq {cid}")
            self._emit(f"    parameter \\A_SIGNED 0")
            self._emit(f"    parameter \\B_SIGNED 0")
            self._emit(f"    parameter \\A_WIDTH {src_w}")
            self._emit(f"    parameter \\B_WIDTH {src_w}")
            self._emit(f"    parameter \\Y_WIDTH 1")
            self._emit(f"    connect \\A {src_sig}")
            self._emit(f"    connect \\B {self._const(cmp_value, src_w)}")
            self._emit(f"    connect \\Y {wn}")
            self._emit(f"  end")
            return True

        # Signal-vs-signal comparison: two incoming edges (left_operand, right_operand)
        # Used by forwarding comparison nodes in bypass pipelines
        left_node = None
        right_node = None
        for edge in node.incoming_edges:
            pos = edge.data.get('type', edge.data.get('position', ''))
            if pos == 'left_operand':
                left_node = edge.source
            elif pos == 'right_operand':
                right_node = edge.source
        if left_node and right_node:
            left_sig = self._sigspec(left_node.id)
            right_sig = self._sigspec(right_node.id)
            left_w = self._infer_width(left_node)
            right_w = self._infer_width(right_node)
            w = max(left_w, right_w)
            cid = self._unique_cell_id("eq")
            self._emit(f"  cell $eq {cid}")
            self._emit(f"    parameter \\A_SIGNED 0")
            self._emit(f"    parameter \\B_SIGNED 0")
            self._emit(f"    parameter \\A_WIDTH {w}")
            self._emit(f"    parameter \\B_WIDTH {w}")
            self._emit(f"    parameter \\Y_WIDTH 1")
            self._emit(f"    connect \\A {left_sig}")
            self._emit(f"    connect \\B {right_sig}")
            self._emit(f"    connect \\Y {wn}")
            self._emit(f"  end")
            return True

        return False

    def _gen_logical(self, node: Node, wn: str) -> bool:
        """Generate cells for logical_and / logical_or nodes."""
        ntype = node.data.get('type', '')
        default_op = '||' if ntype == 'logical_or' else '&&'
        op = node.data.get('operation', default_op)
        edges = sorted(node.incoming_edges,
                       key=lambda e: (e.data.get('operand_index', 0), e.source.id))

        if len(edges) == 0:
            return False

        if len(edges) == 1:
            # Single input - just connect
            self._emit(f"  connect {wn} {self._sigspec(edges[0].source.id)}")
            return True

        if len(edges) == 2:
            cell_type = '$logic_and' if op == '&&' else '$logic_or'
            a = edges[0].source
            b = edges[1].source
            cid = self._unique_cell_id(cell_type[1:])
            self._emit(f"  cell {cell_type} {cid}")
            self._emit(f"    parameter \\A_SIGNED 0")
            self._emit(f"    parameter \\B_SIGNED 0")
            self._emit(f"    parameter \\A_WIDTH {self._infer_width(a)}")
            self._emit(f"    parameter \\B_WIDTH {self._infer_width(b)}")
            self._emit(f"    parameter \\Y_WIDTH 1")
            self._emit(f"    connect \\A {self._sigspec(a.id)}")
            self._emit(f"    connect \\B {self._sigspec(b.id)}")
            self._emit(f"    connect \\Y {wn}")
            self._emit(f"  end")
            return True

        # n-ary: chain
        rtlil_op = '$or' if op in ('||', '|') else '$and'
        return self._gen_nary_logic(node, wn, op)

    def _gen_logical_not(self, node: Node, wn: str) -> bool:
        """Generate $logic_not for logical_not nodes."""
        if node.incoming_edges:
            src = next(iter(node.incoming_edges)).source
            aw = self._infer_width(src)
            cid = self._unique_cell_id("logic_not")
            self._emit(f"  cell $logic_not {cid}")
            self._emit(f"    parameter \\A_SIGNED 0")
            self._emit(f"    parameter \\A_WIDTH {aw}")
            self._emit(f"    parameter \\Y_WIDTH 1")
            self._emit(f"    connect \\A {self._sigspec(src.id)}")
            self._emit(f"    connect \\Y {wn}")
            self._emit(f"  end")
            return True
        return self._gen_not_from_id(node, wn)

    def _gen_instruction_enable(self, node: Node, wn: str) -> bool:
        """Generate connection for instruction_enable nodes (single decode input)."""
        if node.incoming_edges:
            src = next(iter(node.incoming_edges)).source
            self._emit(f"  connect {wn} {self._sigspec(src.id)}")
            return True
        return False

    def _gen_literal(self, node: Node, wn: str) -> bool:
        """Generate constant connection for literal nodes."""
        value = node.data.get('value', 0)
        w = self._infer_width(node)
        self._emit(f"  connect {wn} {self._const(value, w)}")
        return True

    def _gen_binary_literal(self, node: Node, wn: str) -> bool:
        """Generate constant for binary literal nodes."""
        value = node.data.get('value', 0)
        w = node.data.get('width', 1)
        expr = node.data.get('expression', {})
        if expr.get('type') == 'binary_literal':
            w = expr.get('width', w)
            value = expr.get('value', value)
        self._emit(f"  connect {wn} {self._const(value, w)}")
        return True

    def _gen_hex_literal(self, node: Node, wn: str) -> bool:
        """Generate constant for hex/dec literal nodes."""
        value = node.data.get('value', 0)
        w = node.data.get('width', 32)
        self._emit(f"  connect {wn} {self._const(value, w)}")
        return True

    def _gen_bit_slice(self, node: Node, wn: str) -> bool:
        """Generate bit slice: connect output = source[hi:lo]."""
        hi, lo = self._get_bit_range(node)
        if hi is None or lo is None:
            return False

        # Find source
        src = None
        for edge in node.incoming_edges:
            src = edge.source
            break

        if not src:
            return False

        src_sig = self._sigspec(src.id)
        if hi == lo:
            self._emit(f"  connect {wn} {src_sig} [{hi}]")
        else:
            self._emit(f"  connect {wn} {src_sig} [{hi}:{lo}]")
        return True

    def _gen_concatenation(self, node: Node, wn: str) -> bool:
        """Generate concatenation: connect output = { msb_parts ... lsb_parts }."""
        # Get the expression to determine ordering
        expr = node.data.get('expression', {})
        expressions = expr.get('expressions', []) if expr.get('type') == 'concatenation' else []

        # Build ordered part list from expression (MSB first in RTLIL { } syntax)
        if expressions:
            parts = self._resolve_concat_parts(node, expressions)
        else:
            # Fallback: use incoming edges sorted by concatenation order
            edges = sorted(node.incoming_edges,
                           key=lambda e: (e.data.get('position', 0), e.source.id))
            parts = [self._sigspec(e.source.id) for e in edges]

        if not parts:
            return False

        concat_spec = "{ " + " ".join(parts) + " }"
        self._emit(f"  connect {wn} {concat_spec}")
        return True

    def _resolve_concat_parts(self, node: Node, expressions: list) -> List[str]:
        """Resolve concatenation sub-expressions to RTLIL sigspecs."""
        parts = []
        for sub in expressions:
            stype = sub.get('type', '')
            if stype == 'identifier':
                name = sub.get('name', '')
                # Find the actual node for this identifier
                resolved = self._find_concat_input(node, name)
                if resolved:
                    parts.append(self._sigspec(resolved))
                else:
                    parts.append(self._sigspec(name))
            elif stype == 'bit_slice':
                target = sub.get('target', {}).get('name', '')
                hi, lo = sub.get('range', (0, 0))
                resolved = self._find_concat_input_by_slice(node, target, hi, lo)
                if resolved:
                    parts.append(self._sigspec(resolved))
                else:
                    # Direct slice reference
                    tsig = self._sigspec(target)
                    if hi == lo:
                        parts.append(f"{tsig} [{hi}]")
                    else:
                        parts.append(f"{tsig} [{hi}:{lo}]")
            elif stype == 'array_access':
                # Single-bit array access like instr[31]
                arr = sub.get('array', {}).get('name', '')
                idx = sub.get('index', {}).get('value', 0)
                # Find the corresponding bit_slice node
                resolved = self._find_concat_input_by_slice(node, arr, idx, idx)
                if resolved:
                    parts.append(self._sigspec(resolved))
                else:
                    parts.append(f"{self._sigspec(arr)} [{idx}]")
            elif stype == 'repetition':
                count = sub.get('count', 1)
                # Find the repetition node in inputs
                for edge in node.incoming_edges:
                    if edge.source.data.get('type') == 'repetition':
                        src_count = edge.source.data.get('count', 0)
                        src_expr = edge.source.data.get('expression', {})
                        if src_expr.get('type') == 'repetition':
                            src_count = src_expr.get('count', src_count)
                        if src_count == count:
                            parts.append(self._sigspec(edge.source.id))
                            break
            elif stype in ('literal', 'binary_literal'):
                value = sub.get('value', 0)
                w = sub.get('width', 1)
                parts.append(self._const(value, w))
            else:
                # Fallback
                for edge in node.incoming_edges:
                    sig = self._sigspec(edge.source.id)
                    if sig not in parts:
                        parts.append(sig)
                        break
        return parts

    def _find_concat_input(self, node: Node, name: str) -> Optional[str]:
        """Find the node id among concat inputs matching a given identifier name."""
        for edge in node.incoming_edges:
            src = edge.source
            src_name = src.data.get('name', src.data.get('original_id', src.id))
            # Check direct name match or original_id
            if src_name == name or src.id == name:
                return src.id
            # Check if source is a prefixed version (e.g., addi_imm for 'imm')
            if src.data.get('original_id') == name:
                return src.id
            # Check if the node's display_name ends with the name
            disp = src.data.get('display_name', '')
            if disp == name or disp.endswith(f'_{name}'):
                return src.id
        return None

    def _find_concat_input_by_slice(self, node: Node, target: str, hi: int, lo: int) -> Optional[str]:
        """Find a concat input node that is a bit_slice of target[hi:lo]."""
        for edge in node.incoming_edges:
            src = edge.source
            if src.data.get('type') == 'bit_slice':
                src_hi, src_lo = self._get_bit_range(src)
                if src_hi == hi and src_lo == lo:
                    # Check that the source of this slice matches target
                    expr = src.data.get('expression', {})
                    if expr.get('type') == 'bit_slice':
                        t = expr.get('target', {}).get('name', '')
                        if t == target:
                            return src.id
        return None

    def _gen_repetition(self, node: Node, wn: str) -> bool:
        """Generate bit repetition: { count { signal } }."""
        count = node.data.get('count', 1)
        expr = node.data.get('expression', {})
        if expr.get('type') == 'repetition':
            count = expr.get('count', count)

        if not node.incoming_edges:
            return False

        src = next(iter(node.incoming_edges)).source
        src_sig = self._sigspec(src.id)
        src_w = self._infer_width(src)

        # In RTLIL, repetition is just concatenation of the same signal N times
        parts = " ".join([src_sig] * count)
        self._emit(f"  connect {wn} {{ {parts} }}")
        return True

    def _gen_ternary(self, node: Node, wn: str) -> bool:
        """Generate $mux cell for ternary (condition ? true : false)."""
        cond = None
        true_val = None
        false_val = None

        for edge in node.incoming_edges:
            et = edge.data.get('type', '')
            if et == 'ternary_condition':
                cond = edge.source
            elif et == 'ternary_true':
                true_val = edge.source
            elif et == 'ternary_false':
                false_val = edge.source

        if not cond or not true_val or not false_val:
            return False

        yw = self._infer_width(node)
        tw = self._infer_width(true_val)
        fw = self._infer_width(false_val)
        mux_w = max(yw, tw, fw)

        cid = self._unique_cell_id("mux")
        self._emit(f"  cell $mux {cid}")
        self._emit(f"    parameter \\WIDTH {mux_w}")
        self._emit(f"    connect \\A {self._sigspec(false_val.id)}")
        self._emit(f"    connect \\B {self._sigspec(true_val.id)}")
        self._emit(f"    connect \\S {self._sigspec(cond.id)}")
        self._emit(f"    connect \\Y {wn}")
        self._emit(f"  end")
        return True

    def _gen_zero_extend(self, node: Node, wn: str) -> bool:
        """Generate zero-extension via concatenation with zero bits."""
        yw = self._infer_width(node)

        if not node.incoming_edges:
            return False

        src = next(iter(node.incoming_edges)).source
        src_w = self._infer_width(src)

        pad = yw - src_w
        if pad <= 0:
            # No actual extension needed (source already wide enough)
            self._emit(f"  connect {wn} {self._sigspec(src.id)}")
            return True

        # { zeros, source }
        self._emit(f"  connect {wn} {{ {self._const(0, pad)} {self._sigspec(src.id)} }}")
        return True

    def _gen_sign_extend(self, node: Node, wn: str) -> bool:
        """Generate sign extension."""
        yw = self._infer_width(node)
        if not node.incoming_edges:
            return False

        src = next(iter(node.incoming_edges)).source
        src_w = self._infer_width(src)

        # Use $pos with A_SIGNED=1 to get sign extension
        cid = self._unique_cell_id("pos")
        self._emit(f"  cell $pos {cid}")
        self._emit(f"    parameter \\A_SIGNED 1")
        self._emit(f"    parameter \\A_WIDTH {src_w}")
        self._emit(f"    parameter \\Y_WIDTH {yw}")
        self._emit(f"    connect \\A {self._sigspec(src.id)}")
        self._emit(f"    connect \\Y {wn}")
        self._emit(f"  end")
        return True

    def _gen_array_access(self, node: Node, wn: str) -> bool:
        """Generate memory read via $memrd_v2 cell."""
        mem_node = None
        idx_node = None

        for edge in node.incoming_edges:
            if edge.data.get('type') == 'array_base':
                mem_node = edge.source
            elif edge.data.get('type') == 'array_index':
                idx_node = edge.source

        if not mem_node or not idx_node:
            return False

        mem_name = mem_node.id
        mem_info = self.memories.get(mem_name)
        if not mem_info:
            return False

        data_w = mem_info['width']
        addr_w = mem_info['addr_width']
        # For isa_state mem type, we need word-address computation
        is_mem_type = mem_node.data.get('type') == 'isa_state mem'
        port_width = mem_info.get('port_width', data_w)

        # If this is a byte-addressed memory, we need to shift the address
        # For word-addressed: addr >> log2(bytes_per_word)
        if is_mem_type and port_width >= 8:
            shift_bits = (port_width // 8 - 1).bit_length()
            if shift_bits > 0:
                # Create shifted address wire
                shifted_addr = f"$memrd_addr_{self._sanitize(node.id)}"
                shifted_w = self._infer_width(idx_node)
                self._emit(f"  wire width {shifted_w} {shifted_addr}")
                cid = self._unique_cell_id("shr")
                self._emit(f"  cell $shr {cid}")
                self._emit(f"    parameter \\A_SIGNED 0")
                self._emit(f"    parameter \\B_SIGNED 0")
                self._emit(f"    parameter \\A_WIDTH {shifted_w}")
                self._emit(f"    parameter \\B_WIDTH {shifted_w}")
                self._emit(f"    parameter \\Y_WIDTH {shifted_w}")
                self._emit(f"    connect \\A {self._sigspec(idx_node.id)}")
                self._emit(f"    connect \\B {self._const(shift_bits, shifted_w)}")
                self._emit(f"    connect \\Y {shifted_addr}")
                self._emit(f"  end")
                addr_sig = shifted_addr
            else:
                addr_sig = self._sigspec(idx_node.id)
        else:
            addr_sig = self._sigspec(idx_node.id)

        idx_w = self._infer_width(idx_node)
        rtlil_mem = f"\\{self._sanitize(mem_name)}"

        # Asynchronous (combinational) read - use $memrd (v1, widely supported)
        # If write-read forwarding is enabled, read into a temp wire first
        wr_info = self.memory_write_info.get(mem_name)
        if wr_info:
            mem_rd_wire = f"$memrd_raw_{self._sanitize(node.id)}"
            self._emit(f"  wire width {data_w} {mem_rd_wire}")
        else:
            mem_rd_wire = wn

        cid = self._unique_cell_id("memrd")
        self._emit(f"  cell $memrd {cid}")
        self._emit(f"    parameter \\MEMID \"\\\\{self._sanitize(mem_name)}\"")
        self._emit(f"    parameter \\ABITS {idx_w}")
        self._emit(f"    parameter \\WIDTH {data_w}")
        self._emit(f"    parameter \\CLK_ENABLE 0")
        self._emit(f"    parameter \\CLK_POLARITY 0")
        self._emit(f"    parameter \\TRANSPARENT 0")
        self._emit(f"    connect \\CLK 1'x")
        self._emit(f"    connect \\EN 1'x")
        self._emit(f"    connect \\ADDR {addr_sig}")
        self._emit(f"    connect \\DATA {mem_rd_wire}")
        self._emit(f"  end")

        # Write-read forwarding: if write is active to same address, forward write data
        if wr_info:
            wr_addr = self._sigspec(wr_info['addr'].id)
            wr_data = self._sigspec(wr_info['data'].id)
            wr_en = self._sigspec(wr_info['enable'].id)
            san = self._sanitize(node.id)
            wr_addr_w = self._infer_width(wr_info['addr'])

            # Compare addresses (use the same addr_sig used for the memrd)
            cmp_wire = f"$wrf_cmp_{san}"
            self._emit(f"  wire width 1 {cmp_wire}")
            cid = self._unique_cell_id("eq")
            self._emit(f"  cell $eq {cid}")
            self._emit(f"    parameter \\A_SIGNED 0")
            self._emit(f"    parameter \\B_SIGNED 0")
            self._emit(f"    parameter \\A_WIDTH {idx_w}")
            self._emit(f"    parameter \\B_WIDTH {wr_addr_w}")
            self._emit(f"    parameter \\Y_WIDTH 1")
            self._emit(f"    connect \\A {addr_sig}")
            self._emit(f"    connect \\B {wr_addr}")
            self._emit(f"    connect \\Y {cmp_wire}")
            self._emit(f"  end")

            # AND with write enable
            fwd_sel = f"$wrf_sel_{san}"
            self._emit(f"  wire width 1 {fwd_sel}")
            cid = self._unique_cell_id("and")
            self._emit(f"  cell $and {cid}")
            self._emit(f"    parameter \\A_SIGNED 0")
            self._emit(f"    parameter \\B_SIGNED 0")
            self._emit(f"    parameter \\A_WIDTH 1")
            self._emit(f"    parameter \\B_WIDTH 1")
            self._emit(f"    parameter \\Y_WIDTH 1")
            self._emit(f"    connect \\A {cmp_wire}")
            self._emit(f"    connect \\B {wr_en}")
            self._emit(f"    connect \\Y {fwd_sel}")
            self._emit(f"  end")

            # Mux: forward write data or use memory read
            cid = self._unique_cell_id("mux")
            self._emit(f"  cell $mux {cid}")
            self._emit(f"    parameter \\WIDTH {data_w}")
            self._emit(f"    connect \\A {mem_rd_wire}")
            self._emit(f"    connect \\B {wr_data}")
            self._emit(f"    connect \\S {fwd_sel}")
            self._emit(f"    connect \\Y {wn}")
            self._emit(f"  end")

        return True

    def _gen_multiplexer(self, node: Node, wn: str) -> bool:
        """Generate $mux chain for multiplexer nodes."""
        mux_w = self._infer_width(node)

        # Collect data inputs indexed by input_index, selects by select_index,
        # and a possible default
        input_by_index = {}
        selects = []
        default_input = None

        for edge in node.incoming_edges:
            if edge.data.get('type') == 'mux_input':
                idx = edge.data.get('input_index', None)
                if idx is not None:
                    input_by_index[idx] = edge.source
                else:
                    # Fallback: use order of appearance
                    input_by_index[len(input_by_index)] = edge.source
            elif edge.data.get('type') == 'mux_default_input':
                default_input = edge.source
            elif edge.data.get('type') == 'mux_select':
                selects.append(edge)

        # Sort selects by select_index
        selects.sort(key=lambda e: e.data.get('select_index', 999))

        # Build inputs list ordered by input_index to match select_index pairing
        max_idx = max(input_by_index.keys()) if input_by_index else -1
        inputs = [input_by_index.get(i) for i in range(max_idx + 1)]

        op = node.data.get('operation', 'priority_select')

        if op == 'one_hot_or':
            return self._gen_one_hot_mux(node, wn, mux_w, inputs, selects)
        else:
            return self._gen_priority_mux(node, wn, mux_w, inputs, selects, default_input)

    def _gen_priority_mux(self, node: Node, wn: str, mux_w: int,
                          inputs: List[Node], selects: List[Edge],
                          default_input: Optional[Node]) -> bool:
        """Generate chained $mux cells for priority select."""
        if not inputs or not selects:
            return False

        # Default value: 0 or the default_input
        if default_input:
            current_sig = self._sigspec(default_input.id)
        else:
            current_sig = self._const(0, mux_w)

        # For the node's previous value (used as default in some patterns)
        prev_sig = current_sig

        # Build pairs: each select maps to one input by matching
        # select_index with input_index
        pairs = []
        for sel_edge in selects:
            sel_src = sel_edge.source
            sel_idx = sel_edge.data.get('select_index', 0)
            if sel_idx < len(inputs) and inputs[sel_idx] is not None:
                pairs.append((sel_src, inputs[sel_idx]))

        if not pairs:
            return False

        # Chain muxes from last to first (priority: first select wins)
        # Actually for priority: mux from bottom up
        # Result = sel[-1] ? in[-1] : (sel[-2] ? in[-2] : ... : default)
        for i, (sel, data) in enumerate(reversed(pairs)):
            if i < len(pairs) - 1:
                tmp = f"$pmux_{self._sanitize(node.id)}_{i}"
                self._emit(f"  wire width {mux_w} {tmp}")
                out = tmp
            else:
                out = wn

            cid = self._unique_cell_id("mux")
            self._emit(f"  cell $mux {cid}")
            self._emit(f"    parameter \\WIDTH {mux_w}")
            self._emit(f"    connect \\A {current_sig}")
            self._emit(f"    connect \\B {self._sigspec(data.id)}")
            self._emit(f"    connect \\S {self._sigspec(sel.id)}")
            self._emit(f"    connect \\Y {out}")
            self._emit(f"  end")

            current_sig = out

        return True

    def _gen_one_hot_mux(self, node: Node, wn: str, mux_w: int,
                         inputs: List[Node], selects: List[Edge]) -> bool:
        """Generate one-hot OR mux: output = (s0 & d0) | (s1 & d1) | ..."""
        if not inputs or not selects:
            return False

        # For each (select, data) pair, create: select ? data : 0
        # Then OR all together
        terms = []
        for i, sel_edge in enumerate(selects):
            sel_src = sel_edge.source
            sel_idx = sel_edge.data.get('select_index', i)
            data_src = inputs[sel_idx] if sel_idx < len(inputs) and inputs[sel_idx] is not None else None
            if data_src is None:
                continue

            term_wire = f"$ohmux_{self._sanitize(node.id)}_{i}"
            self._emit(f"  wire width {mux_w} {term_wire}")

            cid = self._unique_cell_id("mux")
            self._emit(f"  cell $mux {cid}")
            self._emit(f"    parameter \\WIDTH {mux_w}")
            self._emit(f"    connect \\A {self._const(0, mux_w)}")
            self._emit(f"    connect \\B {self._sigspec(data_src.id)}")
            self._emit(f"    connect \\S {self._sigspec(sel_src.id)}")
            self._emit(f"    connect \\Y {term_wire}")
            self._emit(f"  end")
            terms.append(term_wire)

        # OR chain
        if len(terms) == 1:
            self._emit(f"  connect {wn} {terms[0]}")
            return True

        prev = terms[0]
        for i, term in enumerate(terms[1:], 1):
            if i < len(terms) - 1:
                tmp = f"$ohmux_or_{self._sanitize(node.id)}_{i}"
                self._emit(f"  wire width {mux_w} {tmp}")
                out = tmp
            else:
                out = wn

            cid = self._unique_cell_id("or")
            self._emit(f"  cell $or {cid}")
            self._emit(f"    parameter \\A_SIGNED 0")
            self._emit(f"    parameter \\B_SIGNED 0")
            self._emit(f"    parameter \\A_WIDTH {mux_w}")
            self._emit(f"    parameter \\B_WIDTH {mux_w}")
            self._emit(f"    parameter \\Y_WIDTH {mux_w}")
            self._emit(f"    connect \\A {prev}")
            self._emit(f"    connect \\B {term}")
            self._emit(f"    connect \\Y {out}")
            self._emit(f"  end")
            prev = out

        return True

    def _gen_var_assignment(self, node: Node, wn: str) -> bool:
        """Generate connection for var nodes (driven by assignment edges)."""
        for edge in node.incoming_edges:
            if edge.data.get('type') == 'assignment':
                self._emit(f"  connect {wn} {self._sigspec(edge.source.id)}")
                return True
        return False

    def _gen_isa_state_wire(self, node: Node, wn: str) -> bool:
        """Handle ISA state scalar _rd nodes - nothing to connect here,
        they're driven by the sequential logic process."""
        # _rd nodes are driven by the sequential process
        # No combinational connection needed
        return False

    def _gen_stall_controller(self, node: Node, wn: str) -> bool:
        """Generate OR of hazard signals for pipeline stall controllers."""
        hazard_signals = []
        for edge in node.incoming_edges:
            if edge.data.get('type') == 'control':
                hazard_signals.append(self._sigspec(edge.source.id))

        if not hazard_signals:
            self._emit(f"  connect {wn} 1'0")
            return True

        if len(hazard_signals) == 1:
            self._emit(f"  connect {wn} {hazard_signals[0]}")
            return True

        # OR chain for multiple hazard signals
        current = hazard_signals[0]
        for i, sig in enumerate(hazard_signals[1:], 1):
            out = f"$stall_or_{self._sanitize(node.id)}_{i}"
            self._emit(f"  wire width 1 {out}")
            cid = self._unique_cell_id("or")
            self._emit(f"  cell $or {cid}")
            self._emit(f"    parameter \\A_SIGNED 0")
            self._emit(f"    parameter \\B_SIGNED 0")
            self._emit(f"    parameter \\A_WIDTH 1")
            self._emit(f"    parameter \\B_WIDTH 1")
            self._emit(f"    parameter \\Y_WIDTH 1")
            self._emit(f"    connect \\A {current}")
            self._emit(f"    connect \\B {sig}")
            self._emit(f"    connect \\Y {out}")
            self._emit(f"  end")
            current = out
        self._emit(f"  connect {wn} {current}")
        return True

    def _gen_control_signal(self, node: Node, wn: str) -> bool:
        """Generate wire connection for control_signal nodes.

        For memory idle/complete signals with single-cycle memory, these are
        constant 1. For start signals, pass through from source.
        """
        sig_type = node.data.get('signal_type', '')

        # Memory idle/complete: always ready for single-cycle memory
        if sig_type in ('idle', 'complete'):
            self._emit(f"  connect {wn} 1'1")
            return True

        # Start or other control signals: pass through from source
        for edge in node.incoming_edges:
            src = edge.source
            # Skip memory nodes (not wires)
            if src.data.get('is_memory', False) or src.data.get('type') in ('isa_state mem',):
                continue
            src_sig = self._sigspec(src.id)
            self._emit(f"  connect {wn} {src_sig}")
            return True

        # No valid source - default to 0
        w = self._infer_width(node)
        self._emit(f"  connect {wn} {self._const(0, w)}")
        return True

    # ------------------------------------------------------------------
    # Sequential logic (process blocks)
    # ------------------------------------------------------------------

    def _generate_sequential_logic(self):
        """Generate $dff cells and reset muxes for sequential state updates.

        Uses explicit $dff + $mux cells instead of process blocks to avoid
        combinational loop issues in CXXRTL where the proc pass can create
        both a combinational driver and a DFF for the same signal.
        """
        self._emit("")

        # Find register assignments (target is _wr node or arch_state scalar)
        reg_updates = []     # (target_node, source_node)
        mem_writes = []      # memory_write_port nodes

        for edge in sorted(self.graph.edges.values(), key=lambda e: (e.source.id, e.target.id)):
            if edge.data.get('type') == 'assignment':
                target = edge.target
                if target.id.endswith('_wr') and not target.data.get('is_memory', False):
                    # _wr node: update the corresponding _rd register
                    if '[' not in target.id:
                        reg_updates.append((target, edge.source))

        # Collect memory write port nodes
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            if node.data.get('type') == 'memory_write_port':
                mem_writes.append(node)

        if not reg_updates and not mem_writes:
            return

        # For each register: create a $mux for reset selection, then a $dff
        # For pipeline designs, check for stall edges on the _rd node
        for target, source in reg_updates:
            base_name = target.id.replace('_wr', '')
            rd_wire = self._wire_name(base_name + '_rd')
            wr_wire = self._wire_name(target.id)
            w = self.wire_widths.get(rd_wire, 32)

            # Check for stall edges on the corresponding _rd node
            rd_node = self.graph.nodes.get(base_name + '_rd')
            stall_signals = []
            if rd_node:
                for edge in rd_node.incoming_edges:
                    if edge.data.get('type') == 'stall':
                        stall_signals.append(edge.source)

            # If stall signals exist, add stall mux: hold current value
            data_sig = wr_wire
            if stall_signals:
                san = self._sanitize(base_name)
                if len(stall_signals) == 1:
                    stall_sig = self._sigspec(stall_signals[0].id)
                else:
                    # OR stall signals together
                    current = self._sigspec(stall_signals[0].id)
                    for i, sn in enumerate(stall_signals[1:], 1):
                        or_out = f"$isa_stall_or_{san}_{i}"
                        self._emit(f"  wire width 1 {or_out}")
                        cid = self._unique_cell_id("or")
                        self._emit(f"  cell $or {cid}")
                        self._emit(f"    parameter \\A_SIGNED 0")
                        self._emit(f"    parameter \\B_SIGNED 0")
                        self._emit(f"    parameter \\A_WIDTH 1")
                        self._emit(f"    parameter \\B_WIDTH 1")
                        self._emit(f"    parameter \\Y_WIDTH 1")
                        self._emit(f"    connect \\A {current}")
                        self._emit(f"    connect \\B {self._sigspec(sn.id)}")
                        self._emit(f"    connect \\Y {or_out}")
                        self._emit(f"  end")
                        current = or_out
                    stall_sig = current

                # Stall mux: S=stall → B=hold(Q=rd_wire), S=!stall → A=wr_wire
                stall_mux_out = f"$isa_stall_mux_{san}"
                self._emit(f"  wire width {w} {stall_mux_out}")
                cid = self._unique_cell_id("mux")
                self._emit(f"  cell $mux {cid}")
                self._emit(f"    parameter \\WIDTH {w}")
                self._emit(f"    connect \\A {wr_wire}")
                self._emit(f"    connect \\B {rd_wire}")
                self._emit(f"    connect \\S {stall_sig}")
                self._emit(f"    connect \\Y {stall_mux_out}")
                self._emit(f"  end")
                data_sig = stall_mux_out

            # Reset value
            reset_wire = f"\\reset_{self._sanitize(base_name + '_rd')}"
            if reset_wire in self.declared_wires:
                reset_sig = reset_wire
            else:
                reset_sig = self._const(0, w)

            # $mux: select between reset value and write value
            dff_d = f"$dff_d_{self._sanitize(base_name)}"
            self._emit(f"  wire width {w} {dff_d}")
            cid = self._unique_cell_id("mux")
            self._emit(f"  cell $mux {cid}")
            self._emit(f"    parameter \\WIDTH {w}")
            self._emit(f"    connect \\A {data_sig}")
            self._emit(f"    connect \\B {reset_sig}")
            self._emit(f"    connect \\S \\reset")
            self._emit(f"    connect \\Y {dff_d}")
            self._emit(f"  end")

            # $dff: register the value on posedge clk
            cid = self._unique_cell_id("dff")
            self._emit(f"  cell $dff {cid}")
            self._emit(f"    parameter \\WIDTH {w}")
            self._emit(f"    parameter \\CLK_POLARITY 1")
            self._emit(f"    connect \\CLK \\clk")
            self._emit(f"    connect \\D {dff_d}")
            self._emit(f"    connect \\Q {rd_wire}")
            self._emit(f"  end")

        # Pipeline registers and validity bits
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            ntype = node.data.get('type', '')
            if ntype in ('pipeline_register', 'validity_bit'):
                self._generate_pipeline_register(node, ntype)

        # Memory write processes
        for wr_node in mem_writes:
            self._generate_memory_write_process(wr_node)

    def _generate_pipeline_register(self, node: Node, ntype: str):
        """Generate $dff with stall gating for pipeline register / validity bit.

        Pattern:
          stall_mux: select between hold (Q) and new data based on stall
          reset_mux: select between stall_mux and reset value
          dff: register on posedge clk
        """
        wn = self._wire_name(node.id)
        w = self._infer_width(node)

        # Find data input and stall signals from incoming edges
        data_src = None
        stall_signals = []
        valid_gate = None

        for edge in node.incoming_edges:
            etype = edge.data.get('type', '')
            if etype == 'pipeline_input':
                data_src = edge.source
            elif etype == 'stall':
                stall_signals.append(edge.source)
            elif etype == 'valid_gate':
                valid_gate = edge.source

        if not data_src:
            # No data input - validity_bit nodes without data are constant 1
            # (stage-level validity bits that are always active)
            if ntype == 'validity_bit':
                self._emit(f"  connect {wn} 1'1")
            return

        # Check for redundant pipeline registers: if the data source is already
        # derived from a pipeline register in the SAME stage, this DFF would
        # add an unwanted extra clock delay. Emit a wire connection instead.
        # Example: PIPE_Memory_umem_addr_rd_byte_offset_PIPE captures
        # umem_addr_rd_byte_offset which is computed from PIPE_Memory_lb_addr_PIPE.
        # Both are in the Memory stage, so the DFF is redundant.
        if ntype == 'pipeline_register':
            parts = node.id.split('_')
            stage = parts[1] if len(parts) >= 2 and parts[0] == 'PIPE' else None
            if stage:
                for edge in data_src.incoming_edges:
                    if edge.data.get('from_pipeline_reg', False):
                        src_id = edge.source.id
                        if src_id.startswith(f'PIPE_{stage}_'):
                            # Source is derived from same-stage pipeline reg
                            self._emit(f"  connect {wn} {self._sigspec(data_src.id)}")
                            return

        data_sig = self._sigspec(data_src.id)
        san = self._sanitize(node.id)

        # Combine stall signals with OR
        if stall_signals:
            if len(stall_signals) == 1:
                stall_sig = self._sigspec(stall_signals[0].id)
            else:
                # OR stall signals together
                current = self._sigspec(stall_signals[0].id)
                for i, sn in enumerate(stall_signals[1:], 1):
                    or_out = f"$pipe_stall_or_{san}_{i}"
                    self._emit(f"  wire width 1 {or_out}")
                    cid = self._unique_cell_id("or")
                    self._emit(f"  cell $or {cid}")
                    self._emit(f"    parameter \\A_SIGNED 0")
                    self._emit(f"    parameter \\B_SIGNED 0")
                    self._emit(f"    parameter \\A_WIDTH 1")
                    self._emit(f"    parameter \\B_WIDTH 1")
                    self._emit(f"    parameter \\Y_WIDTH 1")
                    self._emit(f"    connect \\A {current}")
                    self._emit(f"    connect \\B {self._sigspec(sn.id)}")
                    self._emit(f"    connect \\Y {or_out}")
                    self._emit(f"  end")
                    current = or_out
                stall_sig = current

            # Stall mux: S=stall → B=hold(Q), S=!stall → A=new data
            stall_mux_out = f"$pipe_stall_mux_{san}"
            self._emit(f"  wire width {w} {stall_mux_out}")
            cid = self._unique_cell_id("mux")
            self._emit(f"  cell $mux {cid}")
            self._emit(f"    parameter \\WIDTH {w}")
            self._emit(f"    connect \\A {data_sig}")
            self._emit(f"    connect \\B {wn}")
            self._emit(f"    connect \\S {stall_sig}")
            self._emit(f"    connect \\Y {stall_mux_out}")
            self._emit(f"  end")
            data_sig = stall_mux_out

        # Reset value: 0 for pipeline_register, 1 for validity_bit
        if ntype == 'validity_bit':
            reset_val = self._const(1, w)
        else:
            reset_val = self._const(0, w)

        # Reset mux
        dff_d = f"$pipe_dff_d_{san}"
        self._emit(f"  wire width {w} {dff_d}")
        cid = self._unique_cell_id("mux")
        self._emit(f"  cell $mux {cid}")
        self._emit(f"    parameter \\WIDTH {w}")
        self._emit(f"    connect \\A {data_sig}")
        self._emit(f"    connect \\B {reset_val}")
        self._emit(f"    connect \\S \\reset")
        self._emit(f"    connect \\Y {dff_d}")
        self._emit(f"  end")

        # DFF
        cid = self._unique_cell_id("dff")
        self._emit(f"  cell $dff {cid}")
        self._emit(f"    parameter \\WIDTH {w}")
        self._emit(f"    parameter \\CLK_POLARITY 1")
        self._emit(f"    connect \\CLK \\clk")
        self._emit(f"    connect \\D {dff_d}")
        self._emit(f"    connect \\Q {wn}")
        self._emit(f"  end")

    def _generate_memory_write_process(self, wr_node: Node):
        """Generate $memwr_v2 cell for a memory write port."""
        base_mem = wr_node.data.get('base_memory')
        if not base_mem:
            return

        mem_info = self.memories.get(base_mem)
        if not mem_info:
            return

        # Find write address, data, and enable from incoming edges
        addr_node = None
        data_node = None
        enable_node = None
        byte_enables = []  # (instruction, be_node)

        for edge in sorted(wr_node.incoming_edges, key=lambda e: e.source.id):
            etype = edge.data.get('type')
            if etype == 'write_address':
                addr_node = edge.source
            elif etype == 'write_data':
                data_node = edge.source
            elif etype == 'write_enable':
                enable_node = edge.source
            elif etype == 'byte_enable':
                byte_enables.append((edge.data.get('instruction', ''), edge.source))

        if not addr_node or not data_node or not enable_node:
            return

        data_w = mem_info['width']
        addr_w = self._infer_width(addr_node)
        rtlil_mem = f"\\{self._sanitize(base_mem)}"

        # For byte-addressed memories, shift the address
        mem_node = self.graph.nodes.get(base_mem)
        is_mem_type = mem_node is not None and mem_node.data.get('type') == 'isa_state mem'
        port_width = mem_info.get('port_width', data_w)

        if is_mem_type and port_width >= 8:
            shift_bits = (port_width // 8 - 1).bit_length()
            if shift_bits > 0:
                shifted_addr = f"$memwr_addr_{self._sanitize(wr_node.id)}"
                self._emit(f"  wire width {addr_w} {shifted_addr}")
                cid = self._unique_cell_id("shr")
                self._emit(f"  cell $shr {cid}")
                self._emit(f"    parameter \\A_SIGNED 0")
                self._emit(f"    parameter \\B_SIGNED 0")
                self._emit(f"    parameter \\A_WIDTH {addr_w}")
                self._emit(f"    parameter \\B_WIDTH {addr_w}")
                self._emit(f"    parameter \\Y_WIDTH {addr_w}")
                self._emit(f"    connect \\A {self._sigspec(addr_node.id)}")
                self._emit(f"    connect \\B {self._const(shift_bits, addr_w)}")
                self._emit(f"    connect \\Y {shifted_addr}")
                self._emit(f"  end")
                addr_sig = shifted_addr
            else:
                addr_sig = self._sigspec(addr_node.id)
        else:
            addr_sig = self._sigspec(addr_node.id)

        # Generate enable signal: per-bit enable for $memwr_v2
        num_bytes = max(1, data_w // 8)
        en_sig = self._sigspec(enable_node.id)

        if byte_enables:
            # Build per-byte enable from instruction-gated byte enables.
            # For each sub-word store (SH, SB), gate byte_enable by instr enable.
            # For full-word store (SW), use all-1s gated by sw_enable.
            san = self._sanitize(wr_node.id)

            # Build mapping: instruction name -> piped enable signal.
            # In a pipeline, byte enables must use the same-stage instruction
            # enables, not Decode-stage signals. Search the graph for piped
            # versions of each instruction enable (works for any stage count).
            piped_instr_enables = {}
            candidates = ['sb', 'sh', 'sw'] + [i for i, _ in byte_enables]
            for node_check in self.graph.nodes.values():
                nid = node_check.id
                if (node_check.data.get('type') == 'pipeline_register'
                        and '_enable' in nid and nid.startswith('PIPE_')):
                    for candidate_instr in candidates:
                        if f'{candidate_instr}_enable' in nid:
                            piped_instr_enables[candidate_instr] = nid
                            break

            # Gate each sub-word byte enable by its instruction enable
            gated_parts = []
            for instr, be_node in byte_enables:
                if instr in piped_instr_enables:
                    instr_en = self._sigspec(piped_instr_enables[instr])
                else:
                    instr_en = f"\\{self._sanitize(instr)}_enable"
                gated_wire = f"$be_gated_{self._sanitize(instr)}_{san}"
                self._emit(f"  wire width {num_bytes} {gated_wire}")
                cid = self._unique_cell_id("mux")
                self._emit(f"  cell $mux {cid}")
                self._emit(f"    parameter \\WIDTH {num_bytes}")
                self._emit(f"    connect \\A {self._const(0, num_bytes)}")
                self._emit(f"    connect \\B {self._sigspec(be_node.id)}")
                self._emit(f"    connect \\S {instr_en}")
                self._emit(f"    connect \\Y {gated_wire}")
                self._emit(f"  end")
                gated_parts.append(gated_wire)

            # SW (full-word store) byte enable: all 1s gated by sw_enable
            writers = wr_node.data.get('writers', [])
            sw_instrs = [w for w in writers
                         if w not in [instr for instr, _ in byte_enables]]
            if sw_instrs:
                instr_name = sw_instrs[0]
                if instr_name in piped_instr_enables:
                    sw_en_sig = self._sigspec(piped_instr_enables[instr_name])
                elif 'sw' in piped_instr_enables:
                    sw_en_sig = self._sigspec(piped_instr_enables['sw'])
                else:
                    sw_en_sig = f"\\{self._sanitize(instr_name)}_enable"
                sw_gated = f"$be_gated_sw_{san}"
                self._emit(f"  wire width {num_bytes} {sw_gated}")
                cid = self._unique_cell_id("mux")
                self._emit(f"  cell $mux {cid}")
                self._emit(f"    parameter \\WIDTH {num_bytes}")
                self._emit(f"    connect \\A {self._const(0, num_bytes)}")
                self._emit(f"    connect \\B {self._const((1 << num_bytes) - 1, num_bytes)}")
                self._emit(f"    connect \\S {sw_en_sig}")
                self._emit(f"    connect \\Y {sw_gated}")
                self._emit(f"  end")
                gated_parts.append(sw_gated)

            # OR all gated byte enables together
            combined_be = gated_parts[0]
            for i in range(1, len(gated_parts)):
                or_wire = f"$be_or_{i}_{san}"
                self._emit(f"  wire width {num_bytes} {or_wire}")
                cid = self._unique_cell_id("or")
                self._emit(f"  cell $or {cid}")
                self._emit(f"    parameter \\A_SIGNED 0")
                self._emit(f"    parameter \\B_SIGNED 0")
                self._emit(f"    parameter \\A_WIDTH {num_bytes}")
                self._emit(f"    parameter \\B_WIDTH {num_bytes}")
                self._emit(f"    parameter \\Y_WIDTH {num_bytes}")
                self._emit(f"    connect \\A {combined_be}")
                self._emit(f"    connect \\B {gated_parts[i]}")
                self._emit(f"    connect \\Y {or_wire}")
                self._emit(f"  end")
                combined_be = or_wire

            # Expand num_bytes-bit byte enable to data_w-bit per-bit enable
            # Each byte enable bit controls 8 data bits
            en_wire = f"$memwr_en_{san}"
            self._emit(f"  wire width {data_w} {en_wire}")
            expand_parts = []
            for b in range(num_bytes - 1, -1, -1):
                bit_ref = f"{combined_be} [{b}]"
                expand_parts.extend([bit_ref] * 8)
            self._emit(f"  connect {en_wire} {{ {' '.join(expand_parts)} }}")
            en_out = en_wire
        else:
            # Simple: all bytes enabled when write_enable is active
            en_wire = f"$memwr_en_{self._sanitize(wr_node.id)}"
            self._emit(f"  wire width {data_w} {en_wire}")
            parts = " ".join([en_sig] * data_w)
            self._emit(f"  connect {en_wire} {{ {parts} }}")
            en_out = en_wire

        cid = self._unique_cell_id("memwr")
        self._emit(f"  cell $memwr_v2 {cid}")
        self._emit(f"    parameter \\MEMID \"\\\\{self._sanitize(base_mem)}\"")
        self._emit(f"    parameter \\ABITS {addr_w}")
        self._emit(f"    parameter \\WIDTH {data_w}")
        self._emit(f"    parameter \\CLK_ENABLE 1'1")
        self._emit(f"    parameter \\CLK_POLARITY 1'1")
        self._emit(f"    parameter \\PORTID 0")
        self._emit(f"    parameter \\PRIORITY_MASK 0'x")
        self._emit(f"    connect \\CLK \\clk")
        self._emit(f"    connect \\EN {en_out}")
        self._emit(f"    connect \\ADDR {addr_sig}")
        self._emit(f"    connect \\DATA {self._sigspec(data_node.id)}")
        self._emit(f"  end")

    # ------------------------------------------------------------------
    # Operand helpers
    # ------------------------------------------------------------------

    def _get_lr_operands(self, node: Node) -> Tuple[Optional[Node], Optional[Node]]:
        """Get left and right operands for a binary operation node."""
        left = None
        right = None

        for edge in node.incoming_edges:
            pos = edge.data.get('position')
            if pos == 'left' or edge.data.get('operand') == 'left' or edge.data.get('type') == 'left_operand':
                left = edge.source
            elif pos == 'right' or edge.data.get('operand') == 'right' or edge.data.get('type') == 'right_operand':
                right = edge.source

        if not left or not right:
            edges = sorted(node.incoming_edges, key=lambda e: (
                e.data.get('position', 999) if isinstance(e.data.get('position'), int) else 999,
                e.source.id
            ))
            if len(edges) >= 2:
                if not left:
                    left = edges[0].source
                if not right:
                    right = edges[1].source

        return left, right


def generate_rtlil(graph: ResourceGraph, module_name: str = "processor") -> str:
    """Generate RTLIL text from a ResourceGraph."""
    generator = RTLILGenerator(graph, module_name)
    return generator.generate()
