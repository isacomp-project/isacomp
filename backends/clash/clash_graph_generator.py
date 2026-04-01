"""
Clash HDL Pipeline Generator for ISAComp

Graph-traversing generator that produces Clash (Haskell) code from a
ResourceGraph, supporting pipelined processor designs.  Follows the same
architecture as the HardCaml and Chisel backends: classify every graph node,
then emit Haskell let-bindings in a Mealy-machine transition function.

Haskell's lazy evaluation in ``where`` clauses naturally handles forward
references, so no explicit two-phase wire declaration is needed.

Generated code structure:
  * State record with all sequential elements (ISA regs, memories,
    pipeline registers, validity bits)
  * Pure transition function ``processorT`` computing next state
  * Mealy machine wrapper ``topEntity`` for Clash synthesis
"""

from typing import Dict, List, Set, Tuple, Optional
import re
from core.resource_graph import ResourceGraph, Node, Edge


class ClashPipelineGenerator:
    """Graph-traversing Clash code generator for pipelined processors."""

    def __init__(self, graph: ResourceGraph, module_name: str = "Processor"):
        self.graph = graph
        self.module_name = (
            module_name[0].upper() + module_name[1:] if module_name else "Processor"
        )

        # ── Name management ────────────────────────────────────────────
        self.node_id_to_name: Dict[str, str] = {}
        self.declared_names: Set[str] = set()
        self.name_counter: Dict[str, int] = {}

        # ── Signal classification ──────────────────────────────────────
        self.registers: Dict[str, dict] = {}           # base -> {width, rd_node, wr_node}
        self.memories: Dict[str, dict] = {}             # node_id -> {name, bit_width, addr_width, depth, node}
        self.constants: Dict[str, dict] = {}            # node_id -> {name, value, width}
        self.pipeline_registers: Dict[str, dict] = {}   # node_id -> {name, width, node, is_validity, is_passthrough}

        # ── Code sections ──────────────────────────────────────────────
        self.state_extract_lines: List[str] = []    # extract current state
        self.let_bindings: List[str] = []           # combinational let bindings
        self.next_state_lines: List[str] = []       # next state record fields

        # ── Tracking ───────────────────────────────────────────────────
        self._bit_width_cache: Dict[str, int] = {}
        self._processed: Set[str] = set()

        # Default width from register file
        self.default_width = 32
        rf_node = self.graph.nodes.get('rf')
        if rf_node and rf_node.data.get('bit_width'):
            self.default_width = rf_node.data['bit_width']

    # ================================================================ #
    #  Name management
    # ================================================================ #

    _REPLACEMENTS = [
        ('>>>', '_ashr_'), ('>>', '_shr_'), ('<<', '_shl_'),
        ('>=', '_gte_'), ('<=', '_lte_'), ('!=', '_neq_'),
        ('==', '_eq_'), ('>', '_gt_'), ('<s', '_lts_'),
        ('<', '_lt_'), ('+', '_add_'), ('-', '_sub_'),
        ('*', '_mul_'), ('&', '_and_'), ('|', '_or_'),
        ('^', '_xor_'), ('~', '_not_'), ('?', '_sel_'),
        (':', '_'), ('[', '_'), (']', '_'), ('{', '_'), ('}', '_'),
        (' ', '_'), ("'", '_'), ('.', '_'), ('/', '_'),
        ('(', '_'), (')', '_'), (',', '_'), (';', '_'),
        ('#', '_'), ('@', '_'), ('!', '_'), ('$', '_'),
        ('%', '_'), ('\\', '_'),
    ]

    _HASKELL_KEYWORDS = frozenset({
        'case', 'class', 'data', 'default', 'deriving', 'do', 'else',
        'forall', 'foreign', 'hiding', 'if', 'import', 'in', 'infix',
        'infixl', 'infixr', 'instance', 'let', 'module', 'newtype',
        'of', 'qualified', 'then', 'type', 'where', 'as', 'not',
        'mod', 'div', 'True', 'False',
    })

    def _sanitize_name(self, name: str) -> str:
        for old, new in self._REPLACEMENTS:
            name = name.replace(old, new)
        name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
        name = re.sub(r'_+', '_', name)
        name = name.strip('_')
        if not name:
            name = 'sig'
        if name[0].isdigit():
            name = 'v_' + name
        # Haskell value identifiers must start lowercase
        name = name[0].lower() + name[1:]
        if name in self._HASKELL_KEYWORDS:
            name = name + '_s'
        return name

    def _unique_name(self, base: str) -> str:
        name = self._sanitize_name(base)
        if name not in self.declared_names:
            self.declared_names.add(name)
            return name
        if name not in self.name_counter:
            self.name_counter[name] = 0
        self.name_counter[name] += 1
        unique = f"{name}_{self.name_counter[name]}"
        self.declared_names.add(unique)
        return unique

    def _get_name(self, node: Node) -> str:
        if node.id in self.node_id_to_name:
            return self.node_id_to_name[node.id]
        base = node.data.get('name', node.id)
        name = self._unique_name(base)
        self.node_id_to_name[node.id] = name
        return name

    def _ref(self, node: Node) -> str:
        return self._get_name(node)

    # ================================================================ #
    #  Bit-width inference  (mirrors HardCaml)
    # ================================================================ #

    def _infer_bit_width(self, node: Node, _visited: set = None) -> int:
        if node.id in self._bit_width_cache:
            return self._bit_width_cache[node.id]
        if _visited is None:
            _visited = set()
        if node.id in _visited:
            return self.default_width
        _visited = _visited | {node.id}
        result = self._infer_bit_width_impl(node, _visited)
        self._bit_width_cache[node.id] = result
        return result

    def _infer_bit_width_impl(self, node: Node, _visited: set) -> int:
        ntype = node.data.get('type', '')

        if ntype in ('pipeline_register', 'validity_bit'):
            for e in node.incoming_edges:
                if e.data.get('type') == 'pipeline_input':
                    return self._infer_bit_width(e.source, _visited)

        if ntype != 'array_access':
            if node.data.get('port_width') is not None:
                return node.data['port_width']
            if node.data.get('bit_width') is not None:
                return node.data['bit_width']

        if self._produces_boolean_result(node):
            return 1

        if ntype == 'literal' and 'width' in node.data:
            return node.data['width']

        if ntype == 'bit_slice':
            for pair in [('high_bit', 'low_bit'), ('high', 'low')]:
                if pair[0] in node.data and pair[1] in node.data:
                    return node.data[pair[0]] - node.data[pair[1]] + 1
            if 'bitslice' in node.data:
                h, l = node.data['bitslice']
                return h - l + 1
            expr = node.data.get('expression', {})
            if expr.get('type') == 'bit_slice' and 'range' in expr:
                h, l = expr['range']
                return h - l + 1

        if ntype == 'binary_literal':
            expr = node.data.get('expression', {})
            if expr.get('type') == 'binary_literal':
                return expr.get('width', 1)
            return node.data.get('width', 1)

        if ntype in ['verilog_hex_literal', 'verilog_dec_literal']:
            return node.data.get('width', 32)

        if ntype == 'repetition':
            expr = node.data.get('expression', {})
            if expr.get('type') == 'repetition':
                count = expr.get('count', 1)
                if node.incoming_edges:
                    src = next(iter(node.incoming_edges)).source
                    return count * self._infer_bit_width(src, _visited)
                return count

        if ntype == 'concatenation':
            if node.incoming_edges:
                return sum(self._infer_bit_width(e.source, _visited)
                           for e in node.incoming_edges)

        if ntype == 'multiplexer':
            widths = []
            for e in node.incoming_edges:
                if e.data.get('type') in ['mux_input', 'mux_default_input']:
                    widths.append(self._infer_bit_width(e.source, _visited))
            return max(widths) if widths else self.default_width

        if ntype in ['ternary', 'ternary_op']:
            widths = []
            for e in node.incoming_edges:
                if e.data.get('type') in ['ternary_true', 'ternary_false']:
                    widths.append(self._infer_bit_width(e.source, _visited))
            if widths:
                return max(widths)

        if ntype == 'pipeline_register':
            for e in node.incoming_edges:
                if e.data.get('type') not in ['stall', 'valid_gate']:
                    return self._infer_bit_width(e.source, _visited)

        if ntype in ['var', 'temp_var']:
            for e in node.incoming_edges:
                if e.data.get('type') == 'validity_check':
                    continue
                return self._infer_bit_width(e.source, _visited)

        if ntype == 'array_access':
            for e in node.incoming_edges:
                if e.data.get('type') in ['array', 'array_base']:
                    aw = e.source.data.get('port_width') or e.source.data.get('bit_width')
                    if aw:
                        return aw

        return self.default_width

    def _produces_boolean_result(self, node: Node) -> bool:
        ntype = node.data.get('type', '')
        if ntype in ['comparison', 'enable', 'logical_and', 'logical_or',
                      'validity_bit']:
            return True
        if ntype == 'operation':
            op = node.data.get('operator') or node.data.get('operation', '')
            cmp_ops = ['==', '!=', '<', '>', '<=', '>=', 'eq', 'ne',
                        'lt', 'gt', 'le', 'ge', '<s', '>s', '<=s', '>=s',
                        '<u', '>u', '<=u', '>=u']
            if op in cmp_ops:
                return True
        return False

    # ================================================================ #
    #  Literal / constant helpers
    # ================================================================ #

    def _parse_literal(self, node: Node) -> Tuple[int, int]:
        width = self._infer_bit_width(node)
        value = node.data.get('value', 0)

        m = re.match(r"(\d+)'([hbodHBOD])([0-9a-fA-F_]+)", node.id)
        if m:
            width = int(m.group(1))
            base_ch = m.group(2).lower()
            val_str = m.group(3).replace('_', '')
            bases = {'h': 16, 'b': 2, 'o': 8, 'd': 10}
            value = int(val_str, bases.get(base_ch, 10))
            return value, width

        if isinstance(value, int):
            return value, width
        if isinstance(value, str):
            try:
                if value.startswith('0x'):
                    return int(value, 16), width
                elif value.startswith('0b'):
                    return int(value, 2), width
                return int(value), width
            except ValueError:
                return 0, width
        return 0, width

    def _clash_const(self, value: int, width: int) -> str:
        if value == 0:
            return f"(0 :: BitVector {width})"
        return f"({value} :: BitVector {width})"

    def _resize_expr(self, expr: str, target_width: int) -> str:
        """Resize expression to target width."""
        return f"(resize {expr} :: BitVector {target_width})"

    # ================================================================ #
    #  Unsigned context detection
    # ================================================================ #

    def _is_unsigned_context(self, node: Node) -> bool:
        nid = node.id.lower()
        gid = (node.data.get('group_id') or '').lower()
        instr_name = (node.data.get('instruction') or '').lower()
        members = [m.lower() for m in node.data.get('group_members', [])]
        unsigned_kw = ['bltu', 'bgeu', 'sltu', 'sltiu']
        if any(kw in nid for kw in unsigned_kw):
            return True
        if any(kw in gid for kw in unsigned_kw):
            return True
        if any(kw == instr_name for kw in unsigned_kw):
            return True
        if any(kw in members for kw in unsigned_kw):
            return True
        return False

    # ================================================================ #
    #  Instruction enable lookup
    # ================================================================ #

    def _find_instruction_enable(self, instr_name: str) -> Optional[str]:
        target = f"{instr_name}_enable"
        best_node = None
        best_pt = -1
        for n in self.graph.nodes.values():
            node_name = n.data.get('name', n.id)
            if node_name == target or n.id == target or \
               (n.id.endswith('_PIPE') and target in n.id):
                pt = getattr(n, 'pipe_time', 0) or 0
                if pt > best_pt:
                    best_pt = pt
                    best_node = n
        if best_node:
            return self._ref(best_node)
        return None

    # ================================================================ #
    #  Classification
    # ================================================================ #

    def _classify_nodes(self):
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            ntype = node.data.get('type', '')
            if ntype in ['cast']:
                continue

            if ntype in ['pipeline_register', 'validity_bit']:
                self._classify_pipeline_register(node)
                continue

            is_mem = node.data.get('is_memory', False)
            is_arch = node.is_arch_state or ntype.startswith('isa_state')

            if is_mem and is_arch:
                self._classify_memory(node)
            elif is_arch and not is_mem:
                self._classify_register(node)
            elif ntype in ['literal', 'binary_literal', 'hex_literal',
                           'verilog_hex_literal', 'verilog_binary_literal',
                           'verilog_dec_literal', 'constant']:
                self._classify_constant(node)

    def _classify_memory(self, node: Node):
        name = self._get_name(node)
        width = node.data.get('port_width') or node.data.get('bit_width') or self.default_width
        raw_depth = node.data.get('array_depth', 5)
        if node.data.get('is_cam', False):
            depth = raw_depth
            addr_width = max(1, (raw_depth - 1).bit_length())
        else:
            addr_width = raw_depth
            depth = min(2 ** addr_width, 67108864)
        self.memories[node.id] = {
            'name': name, 'bit_width': width,
            'addr_width': addr_width, 'depth': depth,
            'node': node,
        }

    def _classify_register(self, node: Node):
        name = self._get_name(node)
        width = self._infer_bit_width(node)

        base = name
        if base.endswith('_rd'):
            base = base[:-3]
        elif base.endswith('_wr'):
            base = base[:-3]

        if base not in self.registers:
            self.registers[base] = {'width': width, 'rd_node': None, 'wr_node': None}
        if node.id.endswith('_rd'):
            self.registers[base]['rd_node'] = node
        elif node.id.endswith('_wr'):
            self.registers[base]['wr_node'] = node
        else:
            if self.registers[base]['rd_node'] is None:
                self.registers[base]['rd_node'] = node
            if self.registers[base]['wr_node'] is None:
                self.registers[base]['wr_node'] = node

        if width and width != self.default_width:
            self.registers[base]['width'] = width

    def _classify_constant(self, node: Node):
        value, width = self._parse_literal(node)
        name = self._get_name(node)
        self.constants[node.id] = {'name': name, 'value': value, 'width': width}

    def _classify_pipeline_register(self, node: Node):
        name = self._get_name(node)
        width = self._infer_bit_width(node)
        is_validity = node.data.get('type') == 'validity_bit'
        is_passthrough = False
        if not is_validity:
            is_passthrough = self._is_double_pipelined(node)
        self.pipeline_registers[node.id] = {
            'name': name,
            'width': width,
            'node': node,
            'is_validity': is_validity,
            'is_passthrough': is_passthrough,
        }

    def _is_double_pipelined(self, node: Node) -> bool:
        node_pt = getattr(node, 'pipe_time', None)
        if node_pt is None:
            return False
        node_name = node.data.get('name', node.id).lower()
        if 'stall' in node_name or 'delay' in node_name or 'valid' in node_name:
            return False
        for e in node.incoming_edges:
            if e.data.get('type') == 'pipeline_input':
                src_pt = getattr(e.source, 'pipe_time', None)
                if src_pt is not None and src_pt == node_pt:
                    return True
        return False

    # ================================================================ #
    #  get_operands (matches HardCaml pattern)
    # ================================================================ #

    def _get_operands(self, node: Node) -> Tuple[Optional[str], Optional[str], List[str]]:
        left = right = None
        positional = []
        left_w = right_w = None
        pos_widths = []
        for edge in sorted(node.incoming_edges, key=lambda e: e.source.id):
            etype = edge.data.get('type', '')
            pos = edge.data.get('position', '')
            if etype == 'left_operand' or pos == 'left':
                left = self._ref(edge.source)
                left_w = self._infer_bit_width(edge.source)
            elif etype == 'right_operand' or pos == 'right':
                right = self._ref(edge.source)
                right_w = self._infer_bit_width(edge.source)
            elif etype == 'operand':
                positional.append(self._ref(edge.source))
                pos_widths.append(self._infer_bit_width(edge.source))

        all_widths: List[int] = []
        all_ops: List[str] = []
        if left is not None:
            all_ops.append(left)
            all_widths.append(left_w)
            if right is not None:
                all_ops.append(right)
                all_widths.append(right_w)
        elif positional:
            all_ops = positional
            all_widths = pos_widths
        else:
            sorted_edges = sorted(
                node.incoming_edges,
                key=lambda e: (int(e.data.get('position', 999))
                               if str(e.data.get('position', '')).isdigit()
                               else 999))
            all_ops = [self._ref(e.source) for e in sorted_edges]
            all_widths = [self._infer_bit_width(e.source) for e in sorted_edges]

        # Resize operands to consistent width.
        # For bitwise ops combining 1-bit enable signals, keep width 1.
        # Otherwise use the max operand width.
        if len(all_widths) >= 2:
            target_w = max(all_widths)
            nop = node.data.get('operator') or node.data.get('operation', '')
            if nop in ['|', '||', '&', '&&', 'or', 'and',
                        'logical_or', 'logical_and']:
                # If ANY operand is 1-bit (enable), keep everything at 1
                if min(all_widths) == 1:
                    target_w = 1
            resized = []
            for op_expr, w in zip(all_ops, all_widths):
                if w != target_w:
                    resized.append(f"(resize {op_expr} :: BitVector {target_w})")
                else:
                    resized.append(op_expr)
            all_ops = resized

        l = all_ops[0] if all_ops else None
        r = all_ops[1] if len(all_ops) > 1 else None
        return l, r, all_ops

    # ================================================================ #
    #  Expression emission  (let binding per node)
    # ================================================================ #

    def _emit_binding(self, name: str, expr: str):
        """Emit a ``let name = expr`` line for the where clause."""
        self.let_bindings.append(f"    {name} = {expr}")

    def _emit_node(self, node: Node):
        if node.id in self._processed:
            return
        self._processed.add(node.id)

        ntype = node.data.get('type', '')
        if ntype in ['cast']:
            return
        # Memories handled during classification / state extraction
        if ntype.startswith('isa_state') and node.data.get('is_memory', False):
            return

        if ntype == 'operation':
            self._emit_operation(node)
        elif ntype == 'comparison':
            self._emit_comparison(node)
        elif ntype == 'bit_slice':
            self._emit_bit_slice(node)
        elif ntype in ['ternary', 'ternary_op']:
            self._emit_ternary(node)
        elif ntype == 'array_access':
            self._emit_array_access(node)
        elif ntype == 'concatenation':
            self._emit_concatenation(node)
        elif ntype == 'repetition':
            self._emit_repetition(node)
        elif ntype in ['var', 'temp_var']:
            self._emit_variable(node)
        elif ntype in ['enable', 'logical_and']:
            self._emit_enable(node)
        elif ntype == 'logical_or':
            self._emit_logical_or(node)
        elif ntype in ['mux', 'multiplexer']:
            self._emit_mux(node)
        elif ntype in ['shared_write', 'shared_wr']:
            self._emit_shared_write(node)
        elif ntype == 'zero_extend':
            self._emit_zero_extend(node)
        elif ntype == 'sign_extend':
            self._emit_sign_extend(node)
        elif ntype == 'memory_write_port':
            self._emit_memory_write_port(node)
        elif ntype in ['literal', 'binary_literal', 'hex_literal',
                        'verilog_hex_literal', 'verilog_binary_literal',
                        'verilog_dec_literal', 'constant']:
            self._emit_constant_binding(node)
        elif ntype in ['pipeline_register', 'validity_bit']:
            self._emit_pipeline_register(node)
        elif ntype == 'pipeline_stall_controller':
            self._emit_stall_controller(node)
        elif ntype.startswith('isa_state'):
            pass  # handled in classify
        elif node.incoming_edges:
            self._emit_passthrough(node)

    # ================================================================ #
    #  Individual node emitters
    # ================================================================ #

    def _connect(self, node: Node, expr: str):
        """Emit a let binding for this node."""
        name = self._get_name(node)
        self._emit_binding(name, expr)

    def _emit_constant_binding(self, node: Node):
        value, width = self._parse_literal(node)
        self._connect(node, self._clash_const(value, width))

    def _emit_operation(self, node: Node):
        op = node.data.get('operator') or node.data.get('operation', '')
        left, right, ops = self._get_operands(node)
        is_unsigned = self._is_unsigned_context(node)
        w = self._infer_bit_width(node)
        # For comparisons embedded in operations, we need the operand width
        # (not the output width which is 1 for boolean results)
        operand_w = self.default_width
        src_widths = [self._infer_bit_width(e.source) for e in node.incoming_edges
                      if e.data.get('type') in ['operand', 'left_operand', 'right_operand']]
        if src_widths:
            operand_w = max(src_widths)

        if len(ops) < 2:
            if len(ops) == 1:
                if op in ['!', 'not', 'logical_not']:
                    self._connect(node, f"(complement {ops[0]})")
                elif op in ['~', 'bitwise_not', 'invert']:
                    self._connect(node, f"(complement {ops[0]})")
                else:
                    self._connect(node, ops[0])
            else:
                self._connect(node, self._clash_const(0, w))
            return

        a, b = ops[0], ops[1]

        # Chainable ops with >2 operands
        chainable = {
            '||': '.|.', 'logical_or': '.|.',
            '&&': '.&.', 'logical_and': '.&.',
            '|': '.|.', 'or': '.|.',
            '&': '.&.', 'and': '.&.',
            '^': '`xor`', 'xor': '`xor`',
            '+': '+', 'add': '+',
        }
        if op in chainable and len(ops) > 2:
            hc_op = chainable[op]
            expr = ops[0]
            for operand in ops[1:]:
                expr = f"({expr} {hc_op} {operand})"
            self._connect(node, expr)
            return

        arith_map = {
            '+': '+', 'add': '+',
            '-': '-', 'sub': '-',
            '*': '*', 'mul': '*',
            '&': '.&.', 'and': '.&.',
            '|': '.|.', 'or': '.|.',
        }
        if op in arith_map:
            self._connect(node, f"({a} {arith_map[op]} {b})")
        elif op in ['^', 'xor']:
            self._connect(node, f"(xor {a} {b})")
        elif op in ['<<', 'shl']:
            self._connect(node, f"(shiftL {a} (fromIntegral (resize {b} :: BitVector 5)))")
        elif op in ['>>', 'shr']:
            self._connect(node, f"(shiftR {a} (fromIntegral (resize {b} :: BitVector 5)))")
        elif op in ['>>>', 'ashr']:
            # Arithmetic right shift via sign bit replication
            # Use a let-in expression (valid inside where clauses in Haskell)
            self._connect(node,
                f"(let {{ sh = fromIntegral (resize {b} :: BitVector 5) }} "
                f"in shiftR {a} sh .|. "
                f"(if testBit {a} ({w} - 1) then complement (shiftR (complement (0 :: BitVector {w})) sh) "
                f"else (0 :: BitVector {w})))")
        elif op in ['==', 'eq']:
            self._connect(node, f"(bv1 ({a} == {b}))")
        elif op in ['!=', 'ne']:
            self._connect(node, f"(bv1 ({a} /= {b}))")
        elif op in ['<', 'lt']:
            if is_unsigned:
                self._connect(node, f"(bv1 ({a} < {b}))")
            else:
                self._connect(node,
                    f"(bv1 (unpack @(Signed {operand_w}) (resize {a} :: BitVector {operand_w}) "
                    f"< unpack @(Signed {operand_w}) (resize {b} :: BitVector {operand_w})))")
        elif op in ['>', 'gt']:
            if is_unsigned:
                self._connect(node, f"(bv1 ({a} > {b}))")
            else:
                self._connect(node,
                    f"(bv1 (unpack @(Signed {operand_w}) (resize {a} :: BitVector {operand_w}) "
                    f"> unpack @(Signed {operand_w}) (resize {b} :: BitVector {operand_w})))")
        elif op in ['<=', 'le']:
            if is_unsigned:
                self._connect(node, f"(bv1 ({a} <= {b}))")
            else:
                self._connect(node,
                    f"(bv1 (unpack @(Signed {operand_w}) (resize {a} :: BitVector {operand_w}) "
                    f"<= unpack @(Signed {operand_w}) (resize {b} :: BitVector {operand_w})))")
        elif op in ['>=', 'ge']:
            if is_unsigned:
                self._connect(node, f"(bv1 ({a} >= {b}))")
            else:
                self._connect(node,
                    f"(bv1 (unpack @(Signed {operand_w}) (resize {a} :: BitVector {operand_w}) "
                    f">= unpack @(Signed {operand_w}) (resize {b} :: BitVector {operand_w})))")
        elif op in ['<s', 'slt']:
            self._connect(node,
                f"(bv1 (unpack @(Signed {operand_w}) (resize {a} :: BitVector {operand_w}) "
                f"< unpack @(Signed {operand_w}) (resize {b} :: BitVector {operand_w})))")
        elif op in ['>s', 'sgt']:
            self._connect(node,
                f"(bv1 (unpack @(Signed {operand_w}) (resize {a} :: BitVector {operand_w}) "
                f"> unpack @(Signed {operand_w}) (resize {b} :: BitVector {operand_w})))")
        elif op in ['<=s', 'sle']:
            self._connect(node,
                f"(bv1 (unpack @(Signed {operand_w}) (resize {a} :: BitVector {operand_w}) "
                f"<= unpack @(Signed {operand_w}) (resize {b} :: BitVector {operand_w})))")
        elif op in ['>=s', 'sge']:
            self._connect(node,
                f"(bv1 (unpack @(Signed {operand_w}) (resize {a} :: BitVector {operand_w}) "
                f">= unpack @(Signed {operand_w}) (resize {b} :: BitVector {operand_w})))")
        elif op in ['<u', 'ult']:
            self._connect(node, f"(bv1 ({a} < {b}))")
        elif op in ['>u', 'ugt']:
            self._connect(node, f"(bv1 ({a} > {b}))")
        elif op in ['<=u', 'ule']:
            self._connect(node, f"(bv1 ({a} <= {b}))")
        elif op in ['>=u', 'uge']:
            self._connect(node, f"(bv1 ({a} >= {b}))")
        elif op in ['||', 'logical_or']:
            self._connect(node, f"({a} .|. {b})")
        elif op in ['&&', 'logical_and']:
            self._connect(node, f"({a} .&. {b})")
        else:
            self._connect(node, a if a else self._clash_const(0, w))

    def _emit_comparison(self, node: Node):
        op = node.data.get('operation') or node.data.get('operator', '')
        left, right, ops = self._get_operands(node)
        is_unsigned = self._is_unsigned_context(node)
        w = self._infer_bit_width(node)
        # w for comparisons is 1, but operand width matters for signed
        operand_w = self.default_width

        if len(ops) < 2:
            compare_value = node.data.get('compare_value')
            if compare_value is not None and len(ops) == 1:
                op_w = self._infer_bit_width(
                    next(iter(node.incoming_edges)).source)
                cst = self._clash_const(int(compare_value), op_w)
                cmp_op = '==' if op in ['==', 'eq', ''] else '/='
                self._connect(node,
                    f"(bv1 ((resize {ops[0]} :: BitVector {op_w}) {cmp_op} {cst}))")
                return

            # Try expression-embedded literal
            expr = node.data.get('expression', {})
            if expr.get('type') in ('binary_op', 'comparison') and 'right' in expr:
                right_expr = expr['right']
                if right_expr.get('type') == 'literal' and len(ops) == 1:
                    lit_val = right_expr.get('value', 0)
                    if isinstance(lit_val, str):
                        if lit_val.startswith('0b'):
                            lit_val = int(lit_val, 2)
                        elif lit_val.startswith('0x'):
                            lit_val = int(lit_val, 16)
                        else:
                            lit_val = int(lit_val)
                    left_expr = expr.get('left', {})
                    if left_expr.get('type') == 'bit_slice':
                        hi = left_expr.get('high', {}).get('value', 31)
                        lo = left_expr.get('low', {}).get('value', 0)
                        sw = hi - lo + 1
                        cst = self._clash_const(lit_val, sw)
                        self._connect(node,
                            f"(bv1 ((slice d{hi} d{lo} {ops[0]} :: BitVector {sw}) == {cst}))")
                        return
                    op_w = self._infer_bit_width(
                        next(iter(node.incoming_edges)).source)
                    cst = self._clash_const(lit_val, op_w)
                    cmp_op = '==' if op in ['==', 'eq', ''] else '/='
                    self._connect(node,
                        f"(bv1 ((resize {ops[0]} :: BitVector {op_w}) {cmp_op} {cst}))")
                    return

            if len(ops) == 1:
                self._connect(node, ops[0])
            else:
                self._connect(node, self._clash_const(0, 1))
            return

        a, b = ops[0], ops[1]
        # Determine operand width for signed comparisons
        if node.incoming_edges:
            src_widths = [self._infer_bit_width(e.source) for e in node.incoming_edges
                          if e.data.get('type') in ['operand', 'left_operand', 'right_operand']]
            if src_widths:
                operand_w = max(src_widths)

        if op in ['==', 'eq']:
            self._connect(node, f"(bv1 ({a} == {b}))")
        elif op in ['!=', 'ne']:
            self._connect(node, f"(bv1 ({a} /= {b}))")
        elif is_unsigned or op in ['<u', '>u', '<=u', '>=u', 'ult', 'ugt', 'ule', 'uge']:
            cmp_map = {'<': '<', 'lt': '<', '<u': '<', 'ult': '<',
                        '>': '>', 'gt': '>', '>u': '>', 'ugt': '>',
                        '<=': '<=', 'le': '<=', '<=u': '<=', 'ule': '<=',
                        '>=': '>=', 'ge': '>=', '>=u': '>=', 'uge': '>='}
            hc_op = cmp_map.get(op, '==')
            self._connect(node, f"(bv1 ({a} {hc_op} {b}))")
        else:
            # Signed comparison
            signed_map = {'<': '<', 'lt': '<', '<s': '<',
                          '>': '>', 'gt': '>', '>s': '>',
                          '<=': '<=', 'le': '<=', '<=s': '<=',
                          '>=': '>=', 'ge': '>=', '>=s': '>='}
            hc_op = signed_map.get(op, '<')
            self._connect(node,
                f"(bv1 (unpack @(Signed {operand_w}) "
                f"(resize {a} :: BitVector {operand_w}) {hc_op} "
                f"unpack @(Signed {operand_w}) "
                f"(resize {b} :: BitVector {operand_w})))")

    def _emit_bit_slice(self, node: Node):
        hi, lo = None, None
        expr = node.data.get('expression', {})
        if expr.get('type') == 'bit_slice' and 'range' in expr:
            hi, lo = expr['range']
        for pair in [('high_bit', 'low_bit'), ('high', 'low')]:
            if pair[0] in node.data:
                hi, lo = node.data[pair[0]], node.data[pair[1]]
        if 'bitslice' in node.data:
            hi, lo = node.data['bitslice']
        if hi is None:
            m = re.search(r'\[(\d+):(\d+)\]', node.id)
            if m:
                hi, lo = int(m.group(1)), int(m.group(2))

        src_edge = next((e for e in node.incoming_edges
                         if e.data.get('type') in ['operand', 'bit_access']), None)
        if src_edge is None:
            src_edge = next(iter(node.incoming_edges), None)

        if src_edge and hi is not None:
            w = hi - lo + 1
            self._connect(node, f"(slice d{hi} d{lo} {self._ref(src_edge.source)} :: BitVector {w})")
        else:
            self._connect(node, self._clash_const(0, self._infer_bit_width(node)))

    def _emit_ternary(self, node: Node):
        cond = true_val = false_val = None
        for e in node.incoming_edges:
            et = e.data.get('edge_type') or e.data.get('type', '')
            if et in ['condition', 'ternary_condition']:
                cond = self._ref(e.source)
            elif et in ['true_value', 'ternary_true']:
                true_val = self._ref(e.source)
            elif et in ['false_value', 'ternary_false']:
                false_val = self._ref(e.source)

        w = self._infer_bit_width(node)
        if cond and true_val and false_val:
            # Clash mux: mux cond falseCase trueCase (when cond is Bool)
            # We use if-then-else with bv1ToBool for 1-bit conditions
            self._connect(node,
                f"(if bv1ToBool {cond} "
                f"then (resize {true_val} :: BitVector {w}) "
                f"else (resize {false_val} :: BitVector {w}))")
        else:
            self._connect(node, self._clash_const(0, w))

    def _emit_array_access(self, node: Node):
        """Memory read expressions handled here for non-memory arrays."""
        array_node = None
        index_node = None

        for edge in node.incoming_edges:
            edge_type = edge.data.get('type', '')
            if edge_type in ['array', 'array_base'] or edge.source.data.get('is_memory'):
                array_node = edge.source
            elif edge_type == 'array_index':
                index_node = edge.source
            elif index_node is None and edge_type not in ['array', 'array_base']:
                index_node = edge.source

        if array_node and index_node:
            array_name = self._ref(array_node)
            index_expr = self._ref(index_node)
            port_width = array_node.data.get('port_width')
            if port_width:
                shift = 3 if port_width == 64 else 2
                self._connect(node,
                    f"({array_name} !! fromIntegral (shiftR {index_expr} {shift}))")
            else:
                self._connect(node, f"({array_name} !! fromIntegral {index_expr})")
        else:
            w = self._infer_bit_width(node)
            self._connect(node, self._clash_const(0, w))

    def _emit_concatenation(self, node: Node):
        edges = sorted(node.incoming_edges, key=lambda e: e.data.get('position', 0))
        parts = []
        part_widths = []
        for e in edges:
            parts.append(self._ref(e.source))
            part_widths.append(self._infer_bit_width(e.source))
        if len(parts) == 1:
            self._connect(node, parts[0])
        elif parts:
            total_w = self._infer_bit_width(node)
            # For long chains, batch into groups to reduce type-level nesting
            result = parts[0]
            running_w = part_widths[0]
            for i, p in enumerate(parts[1:], 1):
                result = f"({result} ++# {p})"
                running_w += part_widths[i]
                # Add intermediate type annotation every 4 parts to help GHC
                if i % 4 == 0 and i < len(parts) - 1:
                    result = f"({result} :: BitVector {running_w})"
            # Always annotate the final result
            result = f"({result} :: BitVector {total_w})"
            self._connect(node, result)
        else:
            self._connect(node, self._clash_const(0, self._infer_bit_width(node)))

    def _emit_repetition(self, node: Node):
        count = node.data.get('count', node.data.get('repetitions', 1))
        expr = node.data.get('expression', {})
        if expr.get('type') == 'repetition':
            count = expr.get('count', count)
        src_edge = next(iter(node.incoming_edges), None)
        if src_edge:
            src = self._ref(src_edge.source)
            src_w = self._infer_bit_width(src_edge.source)
            total_w = self._infer_bit_width(node)
            # Build concatenation with intermediate annotations
            result = src
            running_w = src_w
            for i in range(1, count):
                result = f"({result} ++# {src})"
                running_w += src_w
                if i % 4 == 0 and i < count - 1:
                    result = f"({result} :: BitVector {running_w})"
            result = f"({result} :: BitVector {total_w})"
            self._connect(node, result)
        else:
            self._connect(node, self._clash_const(0, self._infer_bit_width(node)))

    def _emit_variable(self, node: Node):
        name = self._get_name(node)
        is_wr = node.id.endswith('_wr')
        is_arch = node.is_arch_state

        src = None
        for e in node.incoming_edges:
            if e.data.get('type') == 'assignment':
                src = self._ref(e.source)
                break

        if src is None:
            return

        # Emit as let binding
        self._emit_binding(name, src)

    def _emit_enable(self, node: Node):
        conds = [self._ref(e.source) for e in sorted(node.incoming_edges, key=lambda e: e.source.id)]
        if not conds:
            self._connect(node, "(1 :: BitVector 1)")
        elif len(conds) == 1:
            self._connect(node, conds[0])
        else:
            expr = conds[0]
            for c in conds[1:]:
                expr = f"({expr} .&. {c})"
            self._connect(node, expr)

    def _emit_logical_or(self, node: Node):
        conds = [self._ref(e.source) for e in sorted(node.incoming_edges, key=lambda e: e.source.id)]
        if not conds:
            self._connect(node, "(0 :: BitVector 1)")
        elif len(conds) == 1:
            self._connect(node, conds[0])
        else:
            expr = conds[0]
            for c in conds[1:]:
                expr = f"({expr} .|. {c})"
            self._connect(node, expr)

    def _emit_mux(self, node: Node):
        width = self._infer_bit_width(node)
        default_val = None
        inputs_by_idx = {}
        selects_by_idx = {}

        for e in node.incoming_edges:
            et = e.data.get('edge_type') or e.data.get('type', '')
            if et in ['mux_default', 'mux_default_input']:
                default_val = self._ref(e.source)
            elif et in ['mux_input', 'mux_value']:
                idx = e.data.get('input_index', 999)
                inputs_by_idx[idx] = self._ref(e.source)
            elif et in ['mux_select', 'mux_condition']:
                idx = e.data.get('select_index', 999)
                selects_by_idx[idx] = self._ref(e.source)

        if default_val is None:
            default_val = f"(0 :: BitVector {width})"
        else:
            default_val = f"(resize {default_val} :: BitVector {width})"

        current = default_val
        for idx in sorted(selects_by_idx.keys()):
            if idx in inputs_by_idx:
                sel = selects_by_idx[idx]
                val = inputs_by_idx[idx]
                current = (f"(if bv1ToBool {sel} "
                           f"then (resize {val} :: BitVector {width}) "
                           f"else {current})")

        self._connect(node, current)

    def _emit_shared_write(self, node: Node):
        for e in node.incoming_edges:
            if e.data.get('type') in ['data', 'assignment', 'operand']:
                self._connect(node, self._ref(e.source))
                return
        self._connect(node, self._clash_const(0, self._infer_bit_width(node)))

    def _emit_zero_extend(self, node: Node):
        target_w = self._infer_bit_width(node)
        for e in node.incoming_edges:
            self._connect(node, f"(zeroExtend {self._ref(e.source)} :: BitVector {target_w})")
            return
        self._connect(node, self._clash_const(0, target_w))

    def _emit_sign_extend(self, node: Node):
        target_w = self._infer_bit_width(node)
        for e in node.incoming_edges:
            src = self._ref(e.source)
            src_w = self._infer_bit_width(e.source)
            if src_w < target_w:
                self._connect(node,
                    f"(pack (resize (unpack {src} :: Signed {src_w}) :: Signed {target_w}))")
            else:
                self._connect(node, src)
            return
        self._connect(node, self._clash_const(0, target_w))

    def _emit_memory_write_port(self, node: Node):
        """Emit memory write port bindings.

        Memory writes in Clash are handled as next-state computation:
        the transition function produces updated memory vectors via
        ``replace``.  We emit let-bindings for the write address, data,
        and enable, and accumulate next-state memory update logic.
        """
        # Find which memory this write port targets
        mem_id = None
        for e in node.outgoing_edges:
            if e.data.get('type') == 'memory_write' and e.target.id in self.memories:
                mem_id = e.target.id
                break
        if mem_id is None:
            return

        minfo = self.memories[mem_id]
        mem_name = minfo['name']
        aw = minfo['addr_width']
        bw = minfo['bit_width']
        port_width = minfo['node'].data.get('port_width')

        addr_ref = data_ref = enable_ref = None
        for e in node.incoming_edges:
            et = e.data.get('type', '')
            if et in ['write_address', 'array_index']:
                addr_ref = self._ref(e.source)
            elif et == 'write_data':
                data_ref = self._ref(e.source)
            elif et == 'write_enable':
                enable_ref = self._ref(e.source)

        # Compute address with optional word-alignment shift
        wp_name = self._get_name(node)
        if addr_ref:
            if port_width:
                shift = 3 if port_width == 64 else 2
                addr_expr = f"(fromIntegral (resize (shiftR {addr_ref} {shift}) :: BitVector {aw}))"
            else:
                addr_expr = f"(fromIntegral (resize {addr_ref} :: BitVector {aw}))"
        else:
            addr_expr = "0"

        self._emit_binding(f"{wp_name}_addr", addr_expr)

        # Check for byte enables (sub-word stores need read-modify-write)
        byte_enable_edges = [e for e in node.incoming_edges if e.data.get('type') == 'byte_enable']

        if byte_enable_edges and data_ref:
            num_bytes = bw // 8
            # Build combined byte enable from instruction-gated terms
            be_terms = []
            for be_edge in byte_enable_edges:
                instr = be_edge.data.get('instruction', '')
                be_ref = self._ref(be_edge.source)
                enable_name = self._find_instruction_enable(instr)
                if enable_name:
                    be_terms.append(
                        f"(if bv1ToBool {enable_name} then (resize {be_ref} :: BitVector {num_bytes}) "
                        f"else (0 :: BitVector {num_bytes}))")
                else:
                    be_terms.append(f"(resize {be_ref} :: BitVector {num_bytes})")

            # Full-word writers contribute all-ones when active
            writers = node.data.get('writers', [])
            be_instrs = {e.data.get('instruction', '') for e in byte_enable_edges}
            for writer in writers:
                if writer not in be_instrs:
                    enable_name = self._find_instruction_enable(writer)
                    if enable_name:
                        be_terms.append(
                            f"(if bv1ToBool {enable_name} "
                            f"then ({(1 << num_bytes) - 1} :: BitVector {num_bytes}) "
                            f"else (0 :: BitVector {num_bytes}))")

            if not be_terms:
                combined_be = f"({(1 << num_bytes) - 1} :: BitVector {num_bytes})"
            elif len(be_terms) == 1:
                combined_be = be_terms[0]
            else:
                combined_be = be_terms[0]
                for t in be_terms[1:]:
                    combined_be = f"({combined_be} .|. {t})"

            self._emit_binding(f"{wp_name}_be", combined_be)

            # Expand byte enable to bit mask
            # Each byte enable bit -> 8 bits of mask
            mask_parts = []
            for b in range(num_bytes - 1, -1, -1):
                mask_parts.append(
                    f"(if testBit {wp_name}_be {b} "
                    f"then (0xFF :: BitVector 8) else (0 :: BitVector 8))")
            mask_expr = mask_parts[0]
            for p in mask_parts[1:]:
                mask_expr = f"({mask_expr} ++# {p})"
            mask_expr = f"({mask_expr} :: BitVector {bw})"
            self._emit_binding(f"{wp_name}_mask", mask_expr)

            # Read-modify-write: (old & ~mask) | (new & mask)
            self._emit_binding(f"{wp_name}_old",
                f"({mem_name} !! {wp_name}_addr)")
            self._emit_binding(f"{wp_name}_data",
                f"(({wp_name}_old .&. complement {wp_name}_mask) .|. "
                f"((resize {data_ref} :: BitVector {bw}) .&. {wp_name}_mask))")
        else:
            if data_ref:
                self._emit_binding(f"{wp_name}_data",
                    f"(resize {data_ref} :: BitVector {bw})")
            else:
                self._emit_binding(f"{wp_name}_data",
                    self._clash_const(0, bw))

        if enable_ref:
            self._emit_binding(f"{wp_name}_en",
                f"(bv1ToBool {enable_ref})")
        else:
            self._emit_binding(f"{wp_name}_en", "False")

        # Store info for next-state memory update
        if '_write_ports' not in minfo:
            minfo['_write_ports'] = []
        minfo['_write_ports'].append(wp_name)

    def _emit_pipeline_register(self, node: Node):
        pinfo = self.pipeline_registers.get(node.id)
        if pinfo is None:
            self._emit_passthrough(node)
            return

        name = pinfo['name']
        w = pinfo['width']

        data_source = None
        stall_signal = None
        valid_gate_signal = None

        for e in node.incoming_edges:
            et = e.data.get('type', '')
            if et == 'pipeline_input':
                data_source = self._ref(e.source)
            elif et == 'stall':
                stall_signal = self._ref(e.source)
            elif et == 'valid_gate':
                valid_gate_signal = self._ref(e.source)
            elif et == 'stall_enable':
                stall_signal = self._ref(e.source)

        if pinfo.get('is_passthrough'):
            if data_source:
                self._emit_binding(name, f"(resize {data_source} :: BitVector {w})")
            else:
                self._emit_binding(name, self._clash_const(0, w))
            # No state update needed for passthrough
            return

        # For sequenced pipeline registers, the current value comes from state
        # (already extracted in state_extract_lines).
        # Compute the next value with stall/validity gating.
        if stall_signal and valid_gate_signal:
            enable_expr = f"(not (bv1ToBool {stall_signal}) && bv1ToBool {valid_gate_signal})"
        elif stall_signal:
            enable_expr = f"(not (bv1ToBool {stall_signal}))"
        elif valid_gate_signal:
            enable_expr = f"(bv1ToBool {valid_gate_signal})"
        else:
            enable_expr = "True"

        data_expr = f"(resize {data_source} :: BitVector {w})" if data_source else self._clash_const(0, w)
        self._emit_binding(f"{name}_next",
            f"(if {enable_expr} then {data_expr} else {name})")

    def _emit_stall_controller(self, node: Node):
        conds = []
        for e in node.incoming_edges:
            if e.data.get('type') == 'control':
                conds.append(self._ref(e.source))
        if not conds:
            self._connect(node, "(0 :: BitVector 1)")
        elif len(conds) == 1:
            self._connect(node, conds[0])
        else:
            expr = conds[0]
            for c in conds[1:]:
                expr = f"({expr} .|. {c})"
            self._connect(node, expr)

    def _emit_passthrough(self, node: Node):
        for e in node.incoming_edges:
            if e.data.get('type') == 'stall':
                continue
            # If the source is a memory node, this is likely a memory status
            # signal (idle, complete, etc.).  In synchronous single-cycle memory
            # models the memory is always ready, so emit a constant.
            if e.source.id in self.memories or e.source.data.get('is_memory'):
                name = self._get_name(node)
                # "complete" and "idle" → always 1 (ready)
                # Everything else (start, etc.) → always 0
                if any(k in node.id for k in ['complete', 'idle']):
                    self._emit_binding(name, "(1 :: BitVector 1)")
                else:
                    self._emit_binding(name, "(0 :: BitVector 1)")
                return
            self._connect(node, self._ref(e.source))
            return
        self._connect(node, self._clash_const(0, self._infer_bit_width(node)))

    # ================================================================ #
    #  Main generation
    # ================================================================ #

    def generate(self) -> str:
        self._classify_nodes()
        self._emit_all_bindings()
        return self._assemble()

    def _emit_all_bindings(self):
        """Emit let-bindings for all graph nodes."""
        # Emit all intermediate nodes
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            self._emit_node(node)

    def _collect_stall_signals_for_register(self, base: str) -> List[str]:
        """Collect stall signals targeting an ISA state register."""
        info = self.registers[base]
        stall_signals = []
        for node in [info.get('rd_node'), info.get('wr_node')]:
            if node is None:
                continue
            for e in node.incoming_edges:
                et = e.data.get('type', '')
                if et in ('stall', 'stall_enable'):
                    stall_signals.append(self._ref(e.source))
        return stall_signals

    def _assemble(self) -> str:
        """Assemble the complete Clash module."""
        lines: List[str] = []

        # ── Header ─────────────────────────────────────────────────────
        lines.append("{-# LANGUAGE DataKinds #-}")
        lines.append("{-# LANGUAGE TypeApplications #-}")
        lines.append("{-# LANGUAGE TypeFamilies #-}")
        lines.append("{-# LANGUAGE FlexibleContexts #-}")
        lines.append("{-# LANGUAGE NoImplicitPrelude #-}")
        lines.append("{-# LANGUAGE NumericUnderscores #-}")
        lines.append("{-# LANGUAGE ScopedTypeVariables #-}")
        lines.append("{-# LANGUAGE TypeOperators #-}")
        lines.append("{-# LANGUAGE DeriveGeneric #-}")
        lines.append("{-# LANGUAGE DeriveAnyClass #-}")
        lines.append("{-# LANGUAGE BinaryLiterals #-}")
        lines.append("")
        lines.append(f"module {self.module_name} where")
        lines.append("")
        lines.append("import Clash.Prelude")
        lines.append("")
        # Helper: Bool → BitVector 1 (avoids Bit/BitVector mismatch)
        lines.append("-- | Convert Bool to BitVector 1 (uniform type for all enable signals)")
        lines.append("bv1 :: Bool -> BitVector 1")
        lines.append("bv1 True  = 1")
        lines.append("bv1 False = 0")
        lines.append("")
        lines.append("-- | Convert BitVector 1 to Bool")
        lines.append("bv1ToBool :: BitVector 1 -> Bool")
        lines.append("bv1ToBool x = x /= 0")
        lines.append("")

        # ── Type aliases ───────────────────────────────────────────────
        lines.append(f"type Word{self.default_width} = BitVector {self.default_width}")
        lines.append(f"type Addr = BitVector {self.default_width}")
        rf_node = self.graph.nodes.get('rf')
        if rf_node:
            rf_depth = rf_node.data.get('array_depth', 5)
            rf_size = 2 ** rf_depth
            lines.append(f"type RegFile = Vec {rf_size} Word{self.default_width}")
        lines.append("")

        # ── State record ───────────────────────────────────────────────
        lines.append("-- Processor state record")
        lines.append("data ProcessorState = ProcessorState")

        state_fields = []

        # PC register
        if 'pc' in self.registers:
            w = self.registers['pc']['width']
            state_fields.append(f"stPc :: BitVector {w}")

        # Register file
        if 'rf' in self.memories:
            rf_w, rf_d = self.memories['rf']['bit_width'], self.memories['rf']['depth']
            state_fields.append(f"stRf :: Vec {rf_d} (BitVector {rf_w})")

        # Data/unified memory
        for mem_id, minfo in sorted(self.memories.items()):
            mname = minfo['name']
            if mname in ['rf']:
                continue
            state_fields.append(
                f"st{mname[0].upper()}{mname[1:]} :: Vec {minfo['depth']} (BitVector {minfo['bit_width']})")

        # Pipeline registers (non-passthrough only)
        for pid in sorted(self.pipeline_registers.keys()):
            pinfo = self.pipeline_registers[pid]
            if pinfo.get('is_passthrough'):
                continue
            name = pinfo['name']
            w = pinfo['width']
            if pinfo.get('is_validity'):
                state_fields.append(f"st_{name} :: BitVector 1")
            else:
                state_fields.append(f"st_{name} :: BitVector {w}")

        if not state_fields:
            state_fields.append(f"stDummy :: BitVector 1")

        for i, field in enumerate(state_fields):
            prefix = "  { " if i == 0 else "  , "
            lines.append(f"{prefix}{field}")
        lines.append("  } deriving (Generic, NFDataX)")
        lines.append("")

        # ── Initial state ──────────────────────────────────────────────
        lines.append("-- Initial processor state")
        lines.append("initialState :: ProcessorState")
        lines.append("initialState = ProcessorState")

        init_vals = []
        if 'pc' in self.registers:
            init_vals.append("stPc = 0")
        if 'rf' in self.memories:
            init_vals.append("stRf = repeat 0")
        for mem_id, minfo in sorted(self.memories.items()):
            mname = minfo['name']
            if mname == 'rf':
                continue
            init_vals.append(f"st{mname[0].upper()}{mname[1:]} = repeat 0")

        for pid in sorted(self.pipeline_registers.keys()):
            pinfo = self.pipeline_registers[pid]
            if pinfo.get('is_passthrough'):
                continue
            name = pinfo['name']
            if pinfo.get('is_validity'):
                init_vals.append(f"st_{name} = 1")
            else:
                init_vals.append(f"st_{name} = 0")

        if not init_vals:
            init_vals.append("stDummy = 0")

        for i, val in enumerate(init_vals):
            prefix = "  { " if i == 0 else "  , "
            lines.append(f"{prefix}{val}")
        lines.append("  }")
        lines.append("")

        # ── Transition function ────────────────────────────────────────
        lines.append("-- Processor transition function (Mealy machine)")
        lines.append(f"processorT :: ProcessorState -> () -> (ProcessorState, BitVector {self.default_width})")
        lines.append("processorT state _ = (state', pcOut)")
        lines.append("  where")
        lines.append("")

        # Extract current state
        lines.append("    -- Current state extraction")
        if 'pc' in self.registers:
            pc_name = self.registers['pc'].get('rd_node')
            if pc_name:
                pc_var = self._get_name(pc_name)
                lines.append(f"    {pc_var} = stPc state")
            else:
                lines.append("    pc = stPc state")

        if 'rf' in self.memories:
            rf_var = self.memories['rf']['name']
            lines.append(f"    {rf_var} = stRf state")

        for mem_id, minfo in sorted(self.memories.items()):
            mname = minfo['name']
            if mname == 'rf':
                continue
            lines.append(f"    {mname} = st{mname[0].upper()}{mname[1:]} state")

        # Extract pipeline register state
        for pid in sorted(self.pipeline_registers.keys()):
            pinfo = self.pipeline_registers[pid]
            if pinfo.get('is_passthrough'):
                continue
            name = pinfo['name']
            lines.append(f"    {name} = st_{name} state")

        lines.append("")

        # Emit all let-bindings (combinational logic from graph traversal)
        lines.append("    -- Combinational logic (graph-traversed)")
        lines.extend(self.let_bindings)
        lines.append("")

        # ── Next state computation ─────────────────────────────────────
        lines.append("    -- Next state")

        next_state_fields = []

        # PC next value
        if 'pc' in self.registers:
            wr_node = self.registers['pc'].get('wr_node')
            stall_sigs = self._collect_stall_signals_for_register('pc')
            if wr_node:
                wr_name = self._get_name(wr_node)
                if stall_sigs:
                    stall_expr = stall_sigs[0]
                    for s in stall_sigs[1:]:
                        stall_expr = f"({stall_expr} .|. {s})"
                    next_state_fields.append(
                        f"stPc = if bv1ToBool {stall_expr} then stPc state else {wr_name}")
                else:
                    next_state_fields.append(f"stPc = {wr_name}")
            else:
                next_state_fields.append("stPc = stPc state")

        # Register file next value
        if 'rf' in self.memories:
            rf_name = self.memories['rf']['name']
            wp_list = self.memories['rf'].get('_write_ports', [])
            if wp_list:
                # Chain replace operations for each write port
                expr = rf_name
                for wp in wp_list:
                    expr = f"(if {wp}_en then replace {wp}_addr {wp}_data {expr} else {expr})"
                next_state_fields.append(f"stRf = {expr}")
            else:
                next_state_fields.append(f"stRf = {rf_name}")

        # Other memories
        for mem_id, minfo in sorted(self.memories.items()):
            mname = minfo['name']
            if mname == 'rf':
                continue
            field_name = f"st{mname[0].upper()}{mname[1:]}"
            wp_list = minfo.get('_write_ports', [])
            if wp_list:
                expr = mname
                for wp in wp_list:
                    expr = f"(if {wp}_en then replace {wp}_addr {wp}_data {expr} else {expr})"
                next_state_fields.append(f"{field_name} = {expr}")
            else:
                next_state_fields.append(f"{field_name} = {mname}")

        # Pipeline registers next values
        for pid in sorted(self.pipeline_registers.keys()):
            pinfo = self.pipeline_registers[pid]
            if pinfo.get('is_passthrough'):
                continue
            name = pinfo['name']
            next_state_fields.append(f"st_{name} = {name}_next")

        if not next_state_fields:
            next_state_fields.append("stDummy = 0")

        lines.append("    state' = ProcessorState")
        for i, field in enumerate(next_state_fields):
            prefix = "      { " if i == 0 else "      , "
            lines.append(f"{prefix}{field}")
        lines.append("      }")
        lines.append("")

        # Output
        lines.append("    pcOut = stPc state")
        lines.append("")

        # ── Top entity ─────────────────────────────────────────────────
        lines.append("-- Top entity using mealy machine")
        lines.append("{-# ANN topEntity")
        lines.append("  (Synthesize")
        lines.append(f'    {{ t_name   = "{self.module_name}"')
        lines.append('    , t_inputs = [PortName "clk", PortName "rst", PortName "en"]')
        lines.append('    , t_output = PortName "pc"')
        lines.append("    }) #-}")
        lines.append("topEntity")
        lines.append(f"  :: Clock System")
        lines.append(f"  -> Reset System")
        lines.append(f"  -> Enable System")
        lines.append(f"  -> Signal System (BitVector {self.default_width})")
        lines.append("topEntity = exposeClockResetEnable processorMachine")
        lines.append("")
        lines.append("-- Mealy machine wrapper")
        lines.append("processorMachine")
        lines.append("  :: HiddenClockResetEnable dom")
        lines.append(f"  => Signal dom (BitVector {self.default_width})")
        lines.append("processorMachine = mealy processorT initialState (pure ())")
        lines.append("")

        return '\n'.join(lines)


def generate_clash_pipeline(graph: ResourceGraph, module_name: str = "Processor") -> str:
    """Generate Clash HDL code for a pipelined processor from a ResourceGraph.

    This is the graph-traversing generator that handles pipelined designs
    with pipeline registers, stall controllers, and validity bits.
    """
    generator = ClashPipelineGenerator(graph, module_name)
    return generator.generate()
