"""
Chisel Backend for ISAComp

Generates Scala source code using the Chisel hardware construction language
from ResourceGraph representations. The generated code, when compiled and run
with sbt, produces synthesizable Verilog output via Chisel's FIRRTL compiler.

Uses a Wire/Reg approach: all intermediate signals are declared as Wire(UInt(N.W))
and connected with `:=`. Architectural state uses RegInit for registers and
SyncReadMem/Mem for memories.

This backend is ISA-agnostic and works with any ResourceGraph.
"""

from typing import Dict, List, Set, Tuple, Optional
import re
from core.resource_graph import ResourceGraph, Node


class ChiselGenerator:
    """Generate Scala/Chisel source code from a ResourceGraph."""

    def __init__(self, graph: ResourceGraph, module_name: str = "Processor"):
        self.graph = graph
        self.module_name = self._to_class_name(module_name)

        # Name tracking
        self.node_id_to_name: Dict[str, str] = {}
        self.declared_names: Set[str] = set()
        self.name_counter: Dict[str, int] = {}

        # Signal classification
        self.registers: Dict[str, dict] = {}       # base_name -> {width, rd_node, wr_node}
        self.memories: Dict[str, dict] = {}         # node_id -> {name, bit_width, addr_width, depth, node}
        self.constants: Dict[str, dict] = {}        # node_id -> {name, value, width}
        self.pipeline_registers: Dict[str, dict] = {}  # node_id -> {name, width, node, is_validity}

        # Code sections (Scala source fragments)
        self.io_signals: List[str] = []             # IO bundle fields
        self.wire_decls: List[str] = []             # val name = Wire(UInt(N.W))
        self.reg_decls: List[str] = []              # val name = RegInit(0.U(N.W))
        self.mem_decls: List[str] = []              # val name = SyncReadMem(...)
        self.const_decls: List[str] = []            # val name = N.U(W.W)
        self.connections: List[str] = []            # name := expr
        self.seq_logic: List[str] = []              # when/otherwise blocks

        # Bit-width cache
        self._bit_width_cache: Dict[str, int] = {}

        # Track which nodes have been processed
        self._processed: Set[str] = set()
        # Track which nodes have wire/reg declarations
        self._has_decl: Set[str] = set()

        # Infer default width from register file
        self.default_width = 32
        rf_node = self.graph.nodes.get('rf')
        if rf_node and rf_node.data.get('bit_width'):
            self.default_width = rf_node.data['bit_width']

    # ------------------------------------------------------------------ #
    #  Name management
    # ------------------------------------------------------------------ #

    def _to_class_name(self, name: str) -> str:
        """Convert a module name to a valid Scala class name (PascalCase)."""
        # Split on underscores and capitalize each part
        parts = name.replace('-', '_').split('_')
        return ''.join(p.capitalize() for p in parts if p)

    def _sanitize_name(self, name: str) -> str:
        """Sanitize a name to be a valid Scala identifier."""
        replacements = [
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
        for old, new in replacements:
            name = name.replace(old, new)

        sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', name)
        sanitized = re.sub(r'_+', '_', sanitized)
        sanitized = sanitized.strip('_')

        if not sanitized:
            sanitized = 'sig'

        if sanitized[0].isdigit():
            sanitized = 'n' + sanitized

        # Scala identifiers should start with lowercase for vals
        sanitized = sanitized[0].lower() + sanitized[1:] if sanitized else 'sig'

        # Avoid Scala/Chisel keywords
        scala_keywords = {
            'abstract', 'case', 'catch', 'class', 'def', 'do', 'else',
            'extends', 'false', 'final', 'finally', 'for', 'forSome',
            'if', 'implicit', 'import', 'lazy', 'match', 'new', 'null',
            'object', 'override', 'package', 'private', 'protected',
            'return', 'sealed', 'super', 'this', 'throw', 'trait',
            'true', 'try', 'type', 'val', 'var', 'while', 'with',
            'yield', 'reset', 'clock', 'io', 'module', 'when',
        }
        if sanitized in scala_keywords:
            sanitized = sanitized + '_s'

        return sanitized

    def _unique_name(self, base: str) -> str:
        """Generate a unique Scala name from a base string."""
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
        """Get (or create) the Scala variable name for a node."""
        if node.id in self.node_id_to_name:
            return self.node_id_to_name[node.id]
        base = node.data.get('name', node.id)
        name = self._unique_name(base)
        self.node_id_to_name[node.id] = name
        return name

    # ------------------------------------------------------------------ #
    #  Bit-width inference
    # ------------------------------------------------------------------ #

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

        # Pipeline register widths: infer from pipeline_input source
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
            return max(widths) if widths else 32

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
        if ntype in ['comparison', 'enable', 'logical_and', 'logical_or']:
            return True
        if ntype == 'operation':
            op = node.data.get('operator') or node.data.get('operation', '')
            cmp_ops = ['==', '!=', '<', '>', '<=', '>=', 'eq', 'ne', 'lt', 'gt', 'le', 'ge',
                        '<s', '>s', '<=s', '>=s', '<u', '>u', '<=u', '>=u']
            if op in cmp_ops:
                return True
        return False

    # ------------------------------------------------------------------ #
    #  Literal / constant parsing
    # ------------------------------------------------------------------ #

    def _parse_literal(self, node: Node) -> Tuple[int, int]:
        """Return (value, width) for a literal node."""
        width = self._infer_bit_width(node)
        value = node.data.get('value', 0)

        m = re.match(r"(\d+)'([hbodHBOD])([0-9a-fA-F_]+)", node.id)
        if m:
            width = int(m.group(1))
            base = m.group(2).lower()
            val_str = m.group(3).replace('_', '')
            bases = {'h': 16, 'b': 2, 'o': 8, 'd': 10}
            value = int(val_str, bases.get(base, 10))
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

    # ------------------------------------------------------------------ #
    #  Chisel expression helpers
    # ------------------------------------------------------------------ #

    def _chisel_const(self, value: int, width: int) -> str:
        """Generate a Chisel constant literal."""
        if value == 0:
            return f"0.U({width}.W)"
        # Scala Int literals max at 2^31-1; use hex string form for larger values
        if value <= 2147483647:
            return f"{value}.U({width}.W)"
        hex_str = format(value, 'x')
        return f"\"h{hex_str}\".U({width}.W)"

    def _ref(self, node: Node) -> str:
        """Return the Scala variable name referencing a node's signal."""
        return self._get_name(node)

    def _pad(self, expr: str, target_width: int) -> str:
        """Pad/resize an expression to a target width using bit extraction and zero-fill."""
        return f"({expr}).pad({target_width})({target_width - 1}, 0)"

    def _as_uint(self, expr: str, width: int) -> str:
        """Ensure expression is the right width UInt."""
        return f"({expr})({width - 1}, 0)"

    def _find_instruction_enable(self, instr_name: str) -> Optional[str]:
        """Find the enable signal name for a given instruction.

        In pipelined designs the original enable lives in Decode stage while
        the memory write port lives in the Memory stage. We need the most
        downstream (highest pipe_time) version.
        """
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

    def _is_unsigned_context(self, node: Node) -> bool:
        nid = node.id.lower()
        gid = (node.data.get('group_id') or '').lower()
        instr_name = (node.data.get('instruction') or '').lower()
        members = [m.lower() for m in node.data.get('group_members', [])]
        unsigned_kw = ['bltu', 'bgeu', 'sltu', 'sltiu']
        if any(kw in nid for kw in unsigned_kw):
            return True
        if any(kw == gid for kw in unsigned_kw):
            return True
        if any(kw == instr_name for kw in unsigned_kw):
            return True
        if any(kw in members for kw in unsigned_kw):
            return True
        return False

    # ------------------------------------------------------------------ #
    #  Main generation
    # ------------------------------------------------------------------ #

    def generate(self) -> str:
        """Generate complete Scala/Chisel source."""
        self._classify_nodes()
        self._declare_all()
        self._emit_all()
        return self._assemble()

    def _classify_nodes(self):
        """First pass: classify every node."""
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            ntype = node.data.get('type', '')
            if ntype in ['cast']:
                continue

            # Pipeline registers
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
        """Classify a pipeline register node."""
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
        """Check if a pipeline register's input already depends on another
        pipeline register output, which would cause double-pipelining."""
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

    # ------------------------------------------------------------------ #
    #  Phase 1: Declare all signals
    # ------------------------------------------------------------------ #

    def _declare_all(self):
        """Declare all signals: registers, memories, wires, constants."""
        # 1. ISA state registers
        for base, info in sorted(self.registers.items()):
            w = info['width']
            # Create register with initial value 0
            self.reg_decls.append(f"  val {base} = RegInit({self._chisel_const(0, w)})")
            # The write wire
            wr_name = f"{base}_wr"
            self.wire_decls.append(f"  val {wr_name} = WireDefault({base})")

            # IO outputs for observability
            self.io_signals.append(f"    val {base}_out = Output(UInt({w}.W))")

            if info['rd_node']:
                self.node_id_to_name[info['rd_node'].id] = base
                self._processed.add(info['rd_node'].id)
            if info['wr_node']:
                self.node_id_to_name[info['wr_node'].id] = wr_name
                self._has_decl.add(info['wr_node'].id)

        # 2. Pipeline registers
        for pid, pinfo in sorted(self.pipeline_registers.items()):
            name = pinfo['name']
            w = pinfo['width']
            if pinfo.get('is_passthrough'):
                self.wire_decls.append(f"  val {name} = Wire(UInt({w}.W))")
            else:
                if pinfo['is_validity']:
                    # Validity bits reset to 1
                    all_ones = (1 << w) - 1
                    self.reg_decls.append(f"  val {name} = RegInit({self._chisel_const(all_ones, w)})")
                else:
                    self.reg_decls.append(f"  val {name} = RegInit({self._chisel_const(0, w)})")
                # Data input wire for the pipeline register
                self.wire_decls.append(f"  val {name}_data = Wire(UInt({w}.W))")
                self.wire_decls.append(f"  val {name}_en = Wire(Bool())")
            self.node_id_to_name[pid] = name
            self._has_decl.add(pid)

        # 3. Memories
        for mid, minfo in sorted(self.memories.items()):
            self._declare_memory(mid, minfo)

        # 4. Constants
        for nid, cinfo in sorted(self.constants.items()):
            self.const_decls.append(
                f"  val {cinfo['name']} = {self._chisel_const(cinfo['value'], cinfo['width'])}"
            )
            self._processed.add(nid)

        # 5. All remaining nodes as wires
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            if node.id in self._processed or node.id in self._has_decl:
                continue
            ntype = node.data.get('type', '')
            if ntype in ['cast']:
                continue
            if ntype.startswith('isa_state') and node.data.get('is_memory', False):
                continue

            name = self._get_name(node)
            w = self._infer_bit_width(node)
            self.wire_decls.append(f"  val {name} = Wire(UInt({w}.W))")
            self._has_decl.add(node.id)

    def _declare_memory(self, mid: str, minfo: dict):
        """Declare memory infrastructure."""
        name = minfo['name']
        bw = minfo['bit_width']
        aw = minfo['addr_width']
        depth = minfo['depth']

        # Find write ports and read addresses
        write_ports = []
        read_addrs = []

        for n in sorted(self.graph.nodes.values(), key=lambda x: x.id):
            if n.data.get('type') == 'memory_write_port':
                for e in n.outgoing_edges:
                    if e.data.get('type') == 'memory_write' and e.target.id == mid:
                        write_ports.append(n)
            if n.data.get('type') == 'array_access':
                for e in n.incoming_edges:
                    if e.data.get('type') in ['array', 'array_base'] and e.source.id == mid:
                        read_addrs.append(n)

        # Declare the memory
        # Always use Mem (combinational read) — the pipeline framework adds
        # pipeline registers around memory reads, so the read itself should
        # be combinational.  SyncReadMem would add an extra cycle of latency
        # that the pipeline doesn't account for.
        self.mem_decls.append(f"  val {name} = Mem({depth}, UInt({bw}.W))")

        # Declare write port wires
        for i, wp in enumerate(write_ports):
            self.wire_decls.append(f"  val {name}_waddr_{i} = Wire(UInt({aw}.W))")
            self.wire_decls.append(f"  val {name}_wdata_{i} = Wire(UInt({bw}.W))")
            self.wire_decls.append(f"  val {name}_wen_{i} = Wire(Bool())")
            wp.data['_ch_mem_name'] = name
            wp.data['_ch_wp_index'] = i

        # Check for byte enables for read-modify-write
        rmw_wp_indices = []
        for i, wp in enumerate(write_ports):
            has_be = any(e.data.get('type') == 'byte_enable' for e in wp.incoming_edges)
            if has_be:
                rmw_wp_indices.append(i)
                self.wire_decls.append(f"  val {name}_rmw_raddr_{i} = Wire(UInt({aw}.W))")
                wp.data['_ch_rmw_read_idx'] = len(read_addrs) + len(rmw_wp_indices) - 1
        minfo['_rmw_wp_indices'] = rmw_wp_indices

        # Declare read address wires and read data wires
        for i, ra in enumerate(read_addrs):
            self.wire_decls.append(f"  val {name}_raddr_{i} = Wire(UInt({aw}.W))")

        # Write-read forwarding flag
        write_read_fwd = minfo['node'].data.get('write_read_fwd', False) and len(write_ports) > 0

        # Read port connections
        for i, ra in enumerate(read_addrs):
            ra_name = self._get_name(ra)
            w = self._infer_bit_width(ra)
            self.wire_decls.append(f"  val {ra_name} = Wire(UInt({w}.W))")
            # Memory read
            self.const_decls.append(
                f"  val {ra_name}_mem = {name}.read({name}_raddr_{i})"
            )
            if write_read_fwd:
                # Generate priority-mux forwarding from all write ports.
                # Higher-index write ports have higher priority.
                fwd_expr = f"{ra_name}_mem"
                for wp_idx in reversed(range(len(write_ports))):
                    cond = (
                        f"{name}_wen_{wp_idx} && "
                        f"({name}_waddr_{wp_idx} === {name}_raddr_{i})"
                    )
                    fwd_expr = f"Mux({cond}, {name}_wdata_{wp_idx}, {fwd_expr})"
                self.connections.append(f"  {ra_name} := {fwd_expr}")
            else:
                self.connections.append(f"  {ra_name} := {ra_name}_mem")

            # Connect read address from the array index edge
            raddr_name = f"{name}_raddr_{i}"
            idx_connected = False
            for e in ra.incoming_edges:
                if e.data.get('type') in ['array_index', 'index']:
                    idx_ref = self._get_name(e.source)
                    port_w = minfo['node'].data.get('port_width')
                    if port_w:
                        shift = 3 if port_w == 64 else 2
                        idx_expr = f"({idx_ref} >> {shift}.U)({aw - 1}, 0)"
                    else:
                        idx_expr = f"({idx_ref})({aw - 1}, 0)" if aw > 0 else idx_ref
                    self.connections.append(f"  {raddr_name} := {idx_expr}")
                    idx_connected = True
                    break
            if not idx_connected:
                self.connections.append(f"  {raddr_name} := 0.U")

            self._processed.add(ra.id)
            self._has_decl.add(ra.id)

        # RMW read data signals
        for idx, i in enumerate(rmw_wp_indices):
            self.const_decls.append(
                f"  val {name}_rmw_rdata_{i} = {name}.read({name}_rmw_raddr_{i})"
            )

        # Write port logic
        for i, wp in enumerate(write_ports):
            self.connections.append(
                f"  when({name}_wen_{i}) {{ {name}.write({name}_waddr_{i}, {name}_wdata_{i}) }}"
            )

        # Memory control signals (complete, idle)
        # For single-cycle and static-latency memories, these are constant true
        mem_node = minfo['node']
        is_variable = mem_node.data.get('variable_latency', False)
        min_lat = mem_node.data.get('min_latency', 1)
        max_lat = mem_node.data.get('max_latency', 1)
        is_single_cycle = (not is_variable) or (min_lat <= 1 and max_lat <= 1)

        if is_single_cycle:
            self.const_decls.append(f"  val {name}_complete = true.B")
            self.const_decls.append(f"  val {name}_idle = true.B")
        else:
            # Variable latency FSM: counter-based with optional LFSR randomness
            import math
            counter_width = max(2, math.ceil(math.log2(max_lat + 1)))

            # Find start signal for this memory
            start_signal_id = mem_node.data.get('start_signal')
            if start_signal_id and start_signal_id in self.graph.nodes:
                start_node = self.graph.nodes[start_signal_id]
                start_ref = f"{self._get_name(start_node)}.asBool"
            else:
                start_ref = "false.B"

            self.wire_decls.append(f"  val {name}_complete = Wire(Bool())")
            self.wire_decls.append(f"  val {name}_idle = Wire(Bool())")

            if min_lat == max_lat:
                # Static latency: fixed target
                self.reg_decls.append(
                    f"  val {name}_lat_cnt = RegInit(0.U({counter_width}.W))  "
                    f"// latency counter (0=idle, {min_lat}=complete)")
                self.connections.append(
                    f"  {name}_complete := ({name}_lat_cnt =/= 0.U) && "
                    f"({name}_lat_cnt === {counter_width}.U({counter_width}.W))"
                    if min_lat == counter_width else
                    f"  {name}_complete := ({name}_lat_cnt =/= 0.U) && "
                    f"({name}_lat_cnt === {min_lat}.U({counter_width}.W))")
                self.connections.append(
                    f"  {name}_idle := {name}_lat_cnt === 0.U")
                self.seq_logic.append(f"  // Latency counter FSM for {name} ({min_lat}-cycle stall)")
                self.seq_logic.append(f"  when({name}_lat_cnt === 0.U) {{")
                self.seq_logic.append(f"    when({start_ref}) {{")
                self.seq_logic.append(f"      {name}_lat_cnt := 1.U")
                self.seq_logic.append(f"    }}")
                self.seq_logic.append(f"  }} .elsewhen({name}_lat_cnt === {min_lat}.U({counter_width}.W)) {{")
                self.seq_logic.append(f"    {name}_lat_cnt := 0.U")
                self.seq_logic.append(f"  }} .otherwise {{")
                self.seq_logic.append(f"    {name}_lat_cnt := {name}_lat_cnt + 1.U")
                self.seq_logic.append(f"  }}")
            else:
                # Variable latency: LFSR-based random target
                latency_range = max_lat - min_lat
                self.reg_decls.append(
                    f"  val {name}_lat_cnt = RegInit(0.U({counter_width}.W))  "
                    f"// latency counter")
                self.reg_decls.append(
                    f"  val {name}_lat_tgt = RegInit({min_lat}.U({counter_width}.W))  "
                    f"// random target ({min_lat}-{max_lat})")
                self.reg_decls.append(
                    f"  val {name}_lfsr = RegInit(1.U(16.W))  "
                    f"// 16-bit LFSR for random latency")
                # LFSR update (x^16 + x^14 + x^13 + x^11 + 1)
                self.connections.append(
                    f"  {name}_lfsr := Cat({name}_lfsr(14, 0), "
                    f"{name}_lfsr(15) ^ {name}_lfsr(13) ^ {name}_lfsr(12) ^ {name}_lfsr(10))")
                self.connections.append(
                    f"  {name}_complete := ({name}_lat_cnt =/= 0.U) && "
                    f"({name}_lat_cnt === {name}_lat_tgt)")
                self.connections.append(
                    f"  {name}_idle := {name}_lat_cnt === 0.U")
                self.seq_logic.append(
                    f"  // Latency counter FSM for {name} "
                    f"(random {min_lat}-{max_lat} cycles)")
                self.seq_logic.append(f"  when({name}_lat_cnt === 0.U) {{")
                self.seq_logic.append(f"    when({start_ref}) {{")
                self.seq_logic.append(f"      {name}_lat_cnt := 1.U")
                self.seq_logic.append(
                    f"      {name}_lat_tgt := {min_lat}.U +& "
                    f"({name}_lfsr({counter_width - 1}, 0) % {latency_range + 1}.U)")
                self.seq_logic.append(f"    }}")
                self.seq_logic.append(f"  }} .elsewhen({name}_lat_cnt === {name}_lat_tgt) {{")
                self.seq_logic.append(f"    {name}_lat_cnt := 0.U")
                self.seq_logic.append(f"  }} .otherwise {{")
                self.seq_logic.append(f"    {name}_lat_cnt := {name}_lat_cnt + 1.U")
                self.seq_logic.append(f"  }}")

        # Mark control signal nodes as processed so they don't get re-declared
        for suffix in ['_complete', '_idle']:
            ctrl_node_id = f"{name}{suffix}"
            if ctrl_node_id in self.graph.nodes:
                self._processed.add(ctrl_node_id)
                self._has_decl.add(ctrl_node_id)
                self.node_id_to_name[ctrl_node_id] = f"{name}{suffix}"

        self._processed.add(mid)

    # ------------------------------------------------------------------ #
    #  Phase 2: Emit connections for all nodes
    # ------------------------------------------------------------------ #

    def _emit_all(self):
        """Emit := connections for all intermediate signals."""
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            if node.id in self._processed:
                continue
            self._emit_node(node)

        # Connect ISA state register enables (stall gating)
        self._connect_register_updates()

        # Connect pipeline register updates
        self._connect_pipeline_updates()

        # Connect any remaining unconnected wires to zero
        connected_wires = set()
        for line in self.connections:
            m = re.match(r'\s+(\w+)\s*:=', line)
            if m:
                connected_wires.add(m.group(1))

        unconnected = []
        for line in self.wire_decls:
            m = re.match(r'\s+val\s+(\w+)\s*=\s*Wire\(UInt\((\d+)\.W\)\)', line)
            if m:
                wire_name = m.group(1)
                wire_width = int(m.group(2))
                if wire_name not in connected_wires:
                    self.connections.append(f"  {wire_name} := 0.U({wire_width}.W)")
                    unconnected.append(wire_name)
            # Also check for WireDefault and Bool wires
            m2 = re.match(r'\s+val\s+(\w+)\s*=\s*Wire\(Bool\(\)\)', line)
            if m2:
                wire_name = m2.group(1)
                if wire_name not in connected_wires:
                    self.connections.append(f"  {wire_name} := false.B")
                    unconnected.append(wire_name)

        if unconnected:
            import warnings
            warnings.warn(
                f"Chisel: {len(unconnected)} unconnected wire(s) "
                f"auto-connected to zero: {', '.join(unconnected[:10])}"
                + (f" (and {len(unconnected) - 10} more)" if len(unconnected) > 10 else "")
            )

    def _connect_register_updates(self):
        """Connect stall signals to ISA state register updates.

        Generates the sequential logic: when not stalled, update register.
        """
        for base, info in sorted(self.registers.items()):
            stall_signals = []
            for node in [info.get('rd_node'), info.get('wr_node')]:
                if node is None:
                    continue
                for e in node.incoming_edges:
                    et = e.data.get('type', '')
                    if et in ('stall', 'stall_enable'):
                        stall_signals.append(self._ref(e.source))

            wr_name = f"{base}_wr"
            if stall_signals:
                if len(stall_signals) == 1:
                    stall_expr = stall_signals[0]
                else:
                    stall_expr = " | ".join(stall_signals)
                self.seq_logic.append(
                    f"  when(!(({stall_expr})(0))) {{ {base} := {wr_name} }}"
                )
            else:
                self.seq_logic.append(f"  {base} := {wr_name}")

            # IO output connection
            self.connections.append(f"  io.{base}_out := {base}")

    def _connect_pipeline_updates(self):
        """Connect pipeline register data and enable logic."""
        for pid, pinfo in sorted(self.pipeline_registers.items()):
            if pinfo.get('is_passthrough'):
                continue

            name = pinfo['name']
            w = pinfo['width']

            # Generate: when(enable) { reg := data }
            self.seq_logic.append(
                f"  when({name}_en) {{ {name} := {name}_data({w - 1}, 0) }}"
            )

    def _emit_node(self, node: Node):
        if node.id in self._processed:
            return
        self._processed.add(node.id)

        ntype = node.data.get('type', '')
        if ntype in ['cast']:
            return
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
        elif ntype == 'memory_write_port':
            self._emit_memory_write_port(node)
        elif ntype in ['literal', 'binary_literal', 'hex_literal',
                        'verilog_hex_literal', 'verilog_binary_literal',
                        'verilog_dec_literal', 'constant']:
            self._emit_constant_wire(node)
        elif ntype in ['pipeline_register', 'validity_bit']:
            self._emit_pipeline_register(node)
        elif ntype == 'pipeline_stall_controller':
            self._emit_stall_controller(node)
        elif ntype.startswith('isa_state'):
            pass  # registers handled in classify
        elif node.incoming_edges:
            self._emit_passthrough(node)

    # ------------------------------------------------------------------ #
    #  Wire connection helpers
    # ------------------------------------------------------------------ #

    def _connect(self, node: Node, expr: str):
        """Emit `name := expr` for a declared wire.

        Uses .pad(w) before bit extraction to handle expressions that may be
        narrower than the target wire width (e.g., 1-bit comparison result
        assigned to a 32-bit wire).
        """
        name = self._get_name(node)
        w = self._infer_bit_width(node)
        self.connections.append(f"  {name} := ({expr}).pad({w})({w - 1}, 0)")

    def _connect_raw(self, node: Node, expr: str):
        """Emit `name := expr` without bit extraction (for 1-bit signals, etc.)."""
        name = self._get_name(node)
        self.connections.append(f"  {name} := {expr}")

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

        all_widths = []
        all_ops = []
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
            sorted_edges = sorted(node.incoming_edges,
                                  key=lambda e: (int(e.data.get('position', 999))
                                                 if str(e.data.get('position', '')).isdigit()
                                                 else 999))
            all_ops = [self._ref(e.source) for e in sorted_edges]
            all_widths = [self._infer_bit_width(e.source) for e in sorted_edges]

        # Pad all operands to max width for binary operations
        if len(all_widths) >= 2:
            max_w = max(all_widths)
            resized = []
            for op, w in zip(all_ops, all_widths):
                if w != max_w:
                    resized.append(f"({op}).pad({max_w})")
                else:
                    resized.append(op)
            all_ops = resized

        l = all_ops[0] if all_ops else None
        r = all_ops[1] if len(all_ops) > 1 else None
        return l, r, all_ops

    # ------------------------------------------------------------------ #
    #  Individual emitters
    # ------------------------------------------------------------------ #

    def _emit_constant_wire(self, node: Node):
        """Connect a wire for a constant that wasn't pre-classified."""
        value, width = self._parse_literal(node)
        self._connect(node, self._chisel_const(value, width))

    def _emit_operation(self, node: Node):
        op = node.data.get('operator') or node.data.get('operation', '')
        left, right, ops = self._get_operands(node)
        w = self._infer_bit_width(node)
        is_unsigned = self._is_unsigned_context(node)

        if len(ops) < 2:
            if len(ops) == 1:
                if op in ['!', 'not', 'logical_not']:
                    self._connect(node, f"({ops[0]} === 0.U)")
                elif op in ['~', 'bitwise_not', 'invert']:
                    self._connect(node, f"(~{ops[0]})")
                else:
                    self._connect(node, ops[0])
            return

        a, b = ops[0], ops[1]

        # For chainable operators with >2 operands
        chainable_ops = {
            '||': '|', 'logical_or': '|',
            '&&': '&', 'logical_and': '&',
            '|': '|', 'or': '|',
            '&': '&', 'and': '&',
            '^': '^', 'xor': '^',
            '+': '+', 'add': '+',
        }
        if op in chainable_ops and len(ops) > 2:
            ch_op = chainable_ops[op]
            expr = f"({ops[0]}).pad({w})"
            for operand in ops[1:]:
                expr = f"({expr} {ch_op} ({operand}).pad({w}))"
            self._connect(node, expr)
            return

        op_map = {
            '+': '+', 'add': '+',
            '-': '-', 'sub': '-',
            '*': '*', 'mul': '*',
            '&': '&', 'and': '&',
            '|': '|', 'or': '|',
            '^': '^', 'xor': '^',
        }

        if op in op_map:
            self._connect(node, f"({a} {op_map[op]} {b})")
        elif op in ['<<', 'shl']:
            # Limit shift amount width to avoid firtool "shift amount too large" error
            sb = max(1, (w - 1).bit_length())  # e.g., 5 for 32-bit
            self._connect(node, f"({a} << ({b})({sb - 1}, 0))")
        elif op in ['>>', 'shr']:
            sb = max(1, (w - 1).bit_length())
            self._connect(node, f"({a} >> ({b})({sb - 1}, 0))")
        elif op in ['>>>', 'ashr']:
            sb = max(1, (w - 1).bit_length())
            self._connect(node, f"({a}.asSInt >> ({b})({sb - 1}, 0)).asUInt")
        elif op in ['==', 'eq']:
            self._connect(node, f"({a} === {b})")
        elif op in ['!=', 'ne']:
            self._connect(node, f"({a} =/= {b})")
        elif op in ['<', 'lt', '<s']:
            if is_unsigned:
                self._connect(node, f"({a} < {b})")
            else:
                self._connect(node, f"({a}.asSInt < {b}.asSInt)")
        elif op in ['>', 'gt', '>s']:
            if is_unsigned:
                self._connect(node, f"({a} > {b})")
            else:
                self._connect(node, f"({a}.asSInt > {b}.asSInt)")
        elif op in ['<=', 'le', '<=s']:
            if is_unsigned:
                self._connect(node, f"({a} <= {b})")
            else:
                self._connect(node, f"({a}.asSInt <= {b}.asSInt)")
        elif op in ['>=', 'ge', '>=s']:
            if is_unsigned:
                self._connect(node, f"({a} >= {b})")
            else:
                self._connect(node, f"({a}.asSInt >= {b}.asSInt)")
        elif op in ['<u', 'ult']:
            self._connect(node, f"({a} < {b})")
        elif op in ['>u', 'ugt']:
            self._connect(node, f"({a} > {b})")
        elif op in ['<=u', 'ule']:
            self._connect(node, f"({a} <= {b})")
        elif op in ['>=u', 'uge']:
            self._connect(node, f"({a} >= {b})")
        elif op in ['||', 'logical_or']:
            self._connect(node, f"({a} | {b})")
        elif op in ['&&', 'logical_and']:
            self._connect(node, f"({a} & {b})")
        else:
            self._connect(node, a)

    def _emit_comparison(self, node: Node):
        op = node.data.get('operation') or node.data.get('operator', '')
        left, right, ops = self._get_operands(node)
        is_unsigned = self._is_unsigned_context(node)

        if len(ops) < 2:
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
                        cst = self._chisel_const(lit_val, sw)
                        self._connect(node, f"({ops[0]}({hi}, {lo}) === {cst})")
                        return
                    op_w = self._infer_bit_width(next(iter(node.incoming_edges)).source)
                    lit_w = right_expr.get('width', op_w)
                    cmp_w = max(op_w, lit_w)
                    cst = self._chisel_const(lit_val, cmp_w)
                    cmp_op = '==='
                    if op in ['!=', 'ne']:
                        cmp_op = '=/='
                    elif op in ['<', 'lt']:
                        if is_unsigned:
                            cmp_op = '<'
                        else:
                            # For signed, we need to use .asSInt
                            self._connect(node, f"(({ops[0]}).pad({cmp_w}).asSInt < {cst}.asSInt)")
                            return
                    elif op in ['>', 'gt']:
                        if is_unsigned:
                            cmp_op = '>'
                        else:
                            self._connect(node, f"(({ops[0]}).pad({cmp_w}).asSInt > {cst}.asSInt)")
                            return
                    self._connect(node, f"(({ops[0]}).pad({cmp_w}) {cmp_op} {cst})")
                    return
            compare_value = node.data.get('compare_value')
            if compare_value is not None and len(ops) == 1:
                op_w = self._infer_bit_width(next(iter(node.incoming_edges)).source)
                cst = self._chisel_const(int(compare_value), op_w)
                cmp_op = '==='
                if op in ['!=', 'ne']:
                    cmp_op = '=/='
                self._connect(node, f"(({ops[0]}).pad({op_w}) {cmp_op} {cst})")
                return
            if len(ops) == 1:
                self._connect(node, ops[0])
            else:
                self._connect(node, "0.U")
            return

        a, b = ops[0], ops[1]

        if op in ['==', 'eq']:
            self._connect(node, f"({a} === {b})")
        elif op in ['!=', 'ne']:
            self._connect(node, f"({a} =/= {b})")
        elif op in ['<', 'lt', '<s']:
            if is_unsigned or op in ['<u', 'ult']:
                self._connect(node, f"({a} < {b})")
            else:
                self._connect(node, f"({a}.asSInt < {b}.asSInt)")
        elif op in ['>', 'gt', '>s']:
            if is_unsigned or op in ['>u', 'ugt']:
                self._connect(node, f"({a} > {b})")
            else:
                self._connect(node, f"({a}.asSInt > {b}.asSInt)")
        elif op in ['<=', 'le', '<=s']:
            if is_unsigned or op in ['<=u', 'ule']:
                self._connect(node, f"({a} <= {b})")
            else:
                self._connect(node, f"({a}.asSInt <= {b}.asSInt)")
        elif op in ['>=', 'ge', '>=s']:
            if is_unsigned or op in ['>=u', 'uge']:
                self._connect(node, f"({a} >= {b})")
            else:
                self._connect(node, f"({a}.asSInt >= {b}.asSInt)")
        elif op in ['<u', 'ult']:
            self._connect(node, f"({a} < {b})")
        elif op in ['>u', 'ugt']:
            self._connect(node, f"({a} > {b})")
        elif op in ['<=u', 'ule']:
            self._connect(node, f"({a} <= {b})")
        elif op in ['>=u', 'uge']:
            self._connect(node, f"({a} >= {b})")
        else:
            self._connect(node, f"({a} === {b})")

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
        if src_edge and hi is not None:
            self._connect(node, f"{self._ref(src_edge.source)}({hi}, {lo})")
        else:
            self._connect(node, "0.U")

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

        if cond and true_val and false_val:
            w = self._infer_bit_width(node)
            self._connect(node,
                f"Mux({cond}(0), ({true_val}).pad({w}), ({false_val}).pad({w}))")
        else:
            w = self._infer_bit_width(node)
            self._connect(node, f"0.U({w}.W)")

    def _emit_array_access(self, node: Node):
        """Emit read address connection for memory reads."""
        if node.id in self._processed:
            return
        # Memory reads already handled in _declare_memory
        w = self._infer_bit_width(node)
        self._connect(node, f"0.U({w}.W)")

    def _emit_concatenation(self, node: Node):
        parts = []
        for e in sorted(node.incoming_edges, key=lambda e: e.data.get('position', 0)):
            parts.append(self._ref(e.source))
        if len(parts) == 1:
            self._connect(node, parts[0])
        elif parts:
            # Chisel Cat concatenates MSB-first: Cat(msb, ..., lsb)
            cat_expr = f"Cat({', '.join(parts)})"
            self._connect(node, cat_expr)
        else:
            self._connect(node, "0.U")

    def _emit_repetition(self, node: Node):
        count = node.data.get('count', node.data.get('repetitions', 1))
        expr = node.data.get('expression', {})
        if expr.get('type') == 'repetition':
            count = expr.get('count', count)
        src_edge = next(iter(node.incoming_edges), None)
        if src_edge:
            src = self._ref(src_edge.source)
            # Fill(n, x) replicates x n times
            self._connect(node, f"Fill({count}, {src})")
        else:
            self._connect(node, f"0.U({self._infer_bit_width(node)}.W)")

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

        if is_arch and is_wr:
            base = name[:-3] if name.endswith('_wr') else name
            if base in self.registers:
                w = self.registers[base]['width']
                self.connections.append(f"  {base}_wr := ({src}).pad({w})({w - 1}, 0)")
            else:
                self._connect(node, src)
        else:
            self._connect(node, src)

    def _emit_enable(self, node: Node):
        conds = [self._ref(e.source) for e in sorted(node.incoming_edges, key=lambda e: e.source.id)]
        if not conds:
            self._connect(node, "1.U")
        elif len(conds) == 1:
            self._connect(node, conds[0])
        else:
            expr = conds[0]
            for c in conds[1:]:
                expr = f"({expr} & {c})"
            self._connect(node, expr)

    def _emit_logical_or(self, node: Node):
        conds = [self._ref(e.source) for e in sorted(node.incoming_edges, key=lambda e: e.source.id)]
        if not conds:
            self._connect(node, "0.U")
        elif len(conds) == 1:
            self._connect(node, conds[0])
        else:
            expr = conds[0]
            for c in conds[1:]:
                expr = f"({expr} | {c})"
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
            default_val = f"0.U({width}.W)"

        # Build nested Mux chain
        current = f"({default_val}).pad({width})"
        for idx in sorted(selects_by_idx.keys()):
            if idx in inputs_by_idx:
                sel = selects_by_idx[idx]
                val = inputs_by_idx[idx]
                current = (f"Mux({sel}(0), "
                           f"({val}).pad({width}), {current})")

        self._connect(node, current)

    def _emit_shared_write(self, node: Node):
        for e in node.incoming_edges:
            if e.data.get('type') in ['data', 'assignment', 'operand']:
                self._connect(node, self._ref(e.source))
                return
        w = self._infer_bit_width(node)
        self._connect(node, f"0.U({w}.W)")

    def _emit_zero_extend(self, node: Node):
        target_w = self._infer_bit_width(node)
        for e in node.incoming_edges:
            self._connect(node, f"({self._ref(e.source)}).pad({target_w})")
            return
        self._connect(node, f"0.U({target_w}.W)")

    def _emit_memory_write_port(self, node: Node):
        mem_name = node.data.get('_ch_mem_name')
        wp_idx = node.data.get('_ch_wp_index')

        if mem_name is None:
            for e in node.outgoing_edges:
                if e.data.get('type') == 'memory_write' and e.target.id in self.memories:
                    mem_name = self.memories[e.target.id]['name']
                    wp_idx = 0
                    break

        if mem_name is None:
            return

        if wp_idx is None:
            wp_idx = 0

        minfo = None
        for mi in self.memories.values():
            if mi['name'] == mem_name:
                minfo = mi
                break
        if minfo is None:
            return

        aw = minfo['addr_width']
        bw = minfo['bit_width']
        port_width = minfo['node'].data.get('port_width')

        addr_wire = data_wire = enable_wire = None
        for e in node.incoming_edges:
            et = e.data.get('type', '')
            if et in ['write_address', 'array_index']:
                addr_wire = self._ref(e.source)
            elif et == 'write_data':
                data_wire = self._ref(e.source)
            elif et == 'write_enable':
                enable_wire = self._ref(e.source)

        waddr = f"{mem_name}_waddr_{wp_idx}"
        wdata = f"{mem_name}_wdata_{wp_idx}"
        wen = f"{mem_name}_wen_{wp_idx}"

        # Address expression
        addr_expr = addr_wire
        if addr_wire:
            if port_width:
                shift = 3 if port_width == 64 else 2
                addr_expr = f"({addr_wire} >> {shift}.U)"
            self.connections.append(f"  {waddr} := ({addr_expr}).pad({aw})({aw - 1}, 0)")

        # Check for byte enables (sub-word stores need read-modify-write)
        byte_enable_edges = [e for e in node.incoming_edges if e.data.get('type') == 'byte_enable']
        rmw_read_idx = node.data.get('_ch_rmw_read_idx')

        if byte_enable_edges and rmw_read_idx is not None and data_wire and addr_wire:
            # Connect RMW read address = write address
            rmw_raddr = f"{mem_name}_rmw_raddr_{wp_idx}"
            self.connections.append(f"  {rmw_raddr} := ({addr_expr})({aw - 1}, 0)")

            rmw_rdata = f"{mem_name}_rmw_rdata_{wp_idx}"
            num_bytes = bw // 8

            # Build combined byte enable
            be_terms = []
            for be_edge in byte_enable_edges:
                instr = be_edge.data.get('instruction', '')
                be_ref = self._ref(be_edge.source)
                enable_ref = self._find_instruction_enable(instr)
                if enable_ref:
                    be_terms.append(
                        f"Mux({enable_ref}(0), ({be_ref}).pad({num_bytes}), 0.U({num_bytes}.W))"
                    )
                else:
                    be_terms.append(f"({be_ref}).pad({num_bytes})")

            # Full-word writers
            writers = node.data.get('writers', [])
            be_instrs = {e.data.get('instruction', '') for e in byte_enable_edges}
            for writer in writers:
                if writer not in be_instrs:
                    enable_ref = self._find_instruction_enable(writer)
                    if enable_ref:
                        all_ones = (1 << num_bytes) - 1
                        be_terms.append(
                            f"Mux({enable_ref}(0), {self._chisel_const(all_ones, num_bytes)}, 0.U({num_bytes}.W))"
                        )

            if not be_terms:
                all_ones = (1 << num_bytes) - 1
                combined_be = self._chisel_const(all_ones, num_bytes)
            elif len(be_terms) == 1:
                combined_be = be_terms[0]
            else:
                combined_be = be_terms[0]
                for term in be_terms[1:]:
                    combined_be = f"({combined_be} | {term})"

            # Expand byte enable to full-width bit mask
            # Each byte-enable bit -> 8 bits of mask
            mask_parts = []
            for b in range(num_bytes - 1, -1, -1):
                mask_parts.append(f"Fill(8, ({combined_be})({b}))")
            mask_expr = f"Cat({', '.join(mask_parts)})"

            # RMW: final_data = (old & ~mask) | (new & mask)
            self.connections.append(
                f"  {wdata} := ({rmw_rdata} & (~{mask_expr}).asUInt) | "
                f"(({data_wire}).pad({bw}) & {mask_expr})"
            )
        else:
            if data_wire:
                self.connections.append(f"  {wdata} := ({data_wire}).pad({bw})({bw - 1}, 0)")

        if enable_wire:
            self.connections.append(f"  {wen} := {enable_wire}(0)")
        else:
            self.connections.append(f"  {wen} := false.B")

    def _emit_pipeline_register(self, node: Node):
        """Emit connections for a pipeline register."""
        pinfo = self.pipeline_registers.get(node.id)
        if pinfo is None:
            self._emit_passthrough(node)
            return

        name = pinfo['name']
        w = pinfo['width']

        data_source = None
        stall_signal = None
        valid_gate_signal = None

        # Sort edges by source.id to match Verilog backend's alphabetical
        # selection of the first stall controller.  Each pipeline register
        # may have stall edges from multiple controllers (e.g. Decode AND
        # Memory), but only the stage-local one should be used.
        for e in sorted(node.incoming_edges, key=lambda e: e.source.id):
            et = e.data.get('type', '')
            if et == 'pipeline_input':
                data_source = self._ref(e.source)
            elif et in ('stall', 'stall_enable'):
                if stall_signal is None:
                    stall_signal = self._ref(e.source)
            elif et == 'valid_gate':
                valid_gate_signal = self._ref(e.source)

        if pinfo.get('is_passthrough'):
            if data_source:
                self.connections.append(f"  {name} := ({data_source}).pad({w})({w - 1}, 0)")
            else:
                self.connections.append(f"  {name} := 0.U({w}.W)")
            return

        # Connect data input
        if data_source:
            self.connections.append(f"  {name}_data := ({data_source}).pad({w})({w - 1}, 0)")
        else:
            self.connections.append(f"  {name}_data := 0.U({w}.W)")

        # Compute enable: update when NOT stalled AND valid_gate is asserted
        if stall_signal:
            if valid_gate_signal:
                enable_expr = f"(!{stall_signal}(0) && {valid_gate_signal}(0))"
            else:
                enable_expr = f"(!{stall_signal}(0))"
        elif valid_gate_signal:
            enable_expr = f"{valid_gate_signal}(0)"
        else:
            enable_expr = "true.B"

        self.connections.append(f"  {name}_en := {enable_expr}")

    def _emit_stall_controller(self, node: Node):
        conds = []
        for e in node.incoming_edges:
            if e.data.get('type') == 'control':
                conds.append(self._ref(e.source))
        if not conds:
            self._connect(node, "0.U")
        elif len(conds) == 1:
            self._connect(node, conds[0])
        else:
            expr = conds[0]
            for c in conds[1:]:
                expr = f"({expr} | {c})"
            self._connect(node, expr)

    def _emit_passthrough(self, node: Node):
        for e in node.incoming_edges:
            if e.data.get('type') != 'stall':
                self._connect(node, self._ref(e.source))
                return
        w = self._infer_bit_width(node)
        self._connect(node, f"0.U({w}.W)")

    # ------------------------------------------------------------------ #
    #  Assembly
    # ------------------------------------------------------------------ #

    def _assemble(self) -> str:
        """Assemble the complete Scala source file."""
        lines = []
        lines.append("// Generated by ISAComp Chisel backend")
        lines.append("// Compile: sbt run")
        lines.append("// This produces Verilog via Chisel's FIRRTL compiler")
        lines.append("")
        lines.append("import chisel3._")
        lines.append("import chisel3.util._")
        lines.append("")

        # Module class
        lines.append(f"class {self.module_name} extends Module {{")

        # IO bundle
        lines.append("  val io = IO(new Bundle {")
        if self.io_signals:
            for sig in self.io_signals:
                lines.append(sig)
        else:
            lines.append("    val dummy = Output(UInt(1.W))")
        lines.append("  })")
        lines.append("")

        # Register declarations
        if self.reg_decls:
            lines.append("  // Registers (architectural state)")
            lines.extend(self.reg_decls)
            lines.append("")

        # Memory declarations
        if self.mem_decls:
            lines.append("  // Memories")
            lines.extend(self.mem_decls)
            lines.append("")

        # Split const_decls into pure constants vs memory reads
        # Memory reads (e.g., rf.read(addr)) reference wires, so must come after wire decls
        pure_consts = []
        mem_reads = []
        for line in self.const_decls:
            if '.read(' in line:
                mem_reads.append(line)
            else:
                pure_consts.append(line)

        # Pure constants (no wire dependencies)
        if pure_consts:
            lines.append("  // Constants")
            lines.extend(pure_consts)
            lines.append("")

        # Wire declarations
        if self.wire_decls:
            lines.append("  // Wires")
            lines.extend(self.wire_decls)
            lines.append("")

        # Memory reads (depend on address wires being declared)
        if mem_reads:
            lines.append("  // Memory reads")
            lines.extend(mem_reads)
            lines.append("")

        # Connections (combinational logic)
        if self.connections:
            lines.append("  // Combinational logic")
            lines.extend(self.connections)
            lines.append("")

        # Sequential logic
        if self.seq_logic:
            lines.append("  // Sequential logic (register updates)")
            lines.extend(self.seq_logic)
            lines.append("")

        # IO connections for dummy if needed
        if not self.io_signals:
            lines.append("  io.dummy := 0.U")
            lines.append("")

        lines.append("}")
        lines.append("")

        # Object with main for FIRRTL emission (use firtool separately for Verilog)
        lines.append(f"object {self.module_name}Main {{")
        lines.append("  def main(args: Array[String]): Unit = {")
        lines.append(f"    val targetDir = if (args.nonEmpty) args(0) else \"generated\"")
        lines.append(f"    val chirrtl = _root_.circt.stage.ChiselStage.emitCHIRRTL(new {self.module_name})")
        lines.append(f"    new java.io.File(targetDir).mkdirs()")
        lines.append(f"    val pw = new java.io.PrintWriter(s\"$targetDir/{self.module_name}.fir\")")
        lines.append(f"    pw.write(chirrtl)")
        lines.append(f"    pw.close()")
        lines.append(f"    println(s\"FIRRTL emitted to $targetDir/{self.module_name}.fir (${{chirrtl.length}} bytes)\")")
        lines.append("  }")
        lines.append("}")
        lines.append("")

        return "\n".join(lines)


def generate_chisel(graph: ResourceGraph, module_name: str = "Processor") -> str:
    """Generate Scala/Chisel source code from a ResourceGraph."""
    generator = ChiselGenerator(graph, module_name)
    return generator.generate()
