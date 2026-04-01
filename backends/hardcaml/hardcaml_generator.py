"""
HardCaml Generator for ISAComp

Generates OCaml code using the HardCaml library from ResourceGraph representations.
The generated code, when compiled and run, produces synthesizable Verilog output
via HardCaml's Rtl module.

Uses a two-phase wire approach: all intermediate signals are forward-declared as
`wire N`, then connected with `<==`. This handles cyclic dataflow graphs naturally
(e.g., instruction fetch -> decode -> memory write -> instruction fetch).
"""

from typing import Dict, List, Set, Tuple, Optional
import re
from core.resource_graph import ResourceGraph, Node, Edge


class HardCamlGenerator:
    """Generate OCaml/HardCaml source code from a ResourceGraph."""

    def __init__(self, graph: ResourceGraph, module_name: str = "processor"):
        self.graph = graph
        self.module_name = module_name

        # Name tracking
        self.node_id_to_name: Dict[str, str] = {}
        self.declared_names: Set[str] = set()
        self.name_counter: Dict[str, int] = {}

        # Signal classification
        self.registers: Dict[str, dict] = {}       # base_name -> {width, rd_node, wr_node}
        self.memories: Dict[str, dict] = {}         # node_id -> {name, bit_width, addr_width, depth, node}
        self.constants: Dict[str, dict] = {}        # node_id -> {name, value, width}
        self.pipeline_registers: Dict[str, dict] = {}  # node_id -> {name, width, node, is_validity}

        # Code sections (OCaml source fragments)
        self.forward_wires: List[str] = []          # `let name = wire N in`
        self.reg_specs: List[str] = []              # register creation
        self.memory_specs: List[str] = []           # memory creation
        self.comb_lets: List[str] = []              # `let name = expr in` for constants/mem reads
        self.wire_connections: List[str] = []       # `name <== expr;`
        self.outputs: List[str] = []                # circuit outputs

        # Bit-width cache
        self._bit_width_cache: Dict[str, int] = {}

        # Track which nodes have been processed
        self._processed: Set[str] = set()
        # Track which nodes have forward-declared wires
        self._has_wire: Set[str] = set()

        # Infer default width from register file
        self.default_width = 32
        rf_node = self.graph.nodes.get('rf')
        if rf_node and rf_node.data.get('bit_width'):
            self.default_width = rf_node.data['bit_width']

    # ------------------------------------------------------------------ #
    #  Name management
    # ------------------------------------------------------------------ #

    def _sanitize_name(self, name: str) -> str:
        """Sanitize a name to be a valid OCaml identifier."""
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

        # OCaml value identifiers must start with lowercase letter or underscore
        sanitized = sanitized.lower()

        # Avoid OCaml keywords
        ocaml_keywords = {'and', 'as', 'assert', 'begin', 'class', 'constraint',
                          'do', 'done', 'downto', 'else', 'end', 'exception',
                          'external', 'false', 'for', 'fun', 'function', 'functor',
                          'if', 'in', 'include', 'inherit', 'initializer', 'lazy',
                          'let', 'match', 'method', 'module', 'mutable', 'new',
                          'nonrec', 'object', 'of', 'open', 'or', 'private',
                          'rec', 'sig', 'struct', 'then', 'to', 'true', 'try',
                          'type', 'val', 'virtual', 'when', 'while', 'with', 'mod'}
        if sanitized in ocaml_keywords:
            sanitized = sanitized + '_s'

        return sanitized

    def _unique_name(self, base: str) -> str:
        """Generate a unique OCaml name from a base string."""
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
        """Get (or create) the OCaml variable name for a node."""
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
            return 32
        _visited = _visited | {node.id}
        result = self._infer_bit_width_impl(node, _visited)
        self._bit_width_cache[node.id] = result
        return result

    def _infer_bit_width_impl(self, node: Node, _visited: set) -> int:
        ntype = node.data.get('type', '')

        # Pipeline register widths in the graph can be wrong (identifier
        # name mismatch in concatenation expressions).  Infer from the
        # pipeline_input edge source instead.
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
    #  OCaml expression helpers
    # ------------------------------------------------------------------ #

    def _ocaml_const(self, value: int, width: int) -> str:
        if value == 0:
            return f"(zero {width})"
        if width <= 62:
            return f"(of_int ~width:{width} {value})"
        hex_str = format(value, 'x')
        return f"(of_hex_string ~signedness:Unsigned ~width:{width} \"{hex_str}\")"

    def _ref(self, node: Node) -> str:
        """Return the OCaml variable name referencing a node's signal."""
        return self._get_name(node)

    def _find_instruction_enable(self, instr_name: str) -> Optional[str]:
        """Find the enable signal name for a given instruction.

        In pipelined designs the original enable (e.g. ``sw_enable``) lives
        in the Decode stage while the memory write port lives in the Memory
        stage.  We need the most-downstream (highest ``pipe_time``) version
        so that the byte-enable mask is aligned with the actual store.
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
        """Generate complete OCaml/HardCaml source."""
        self._classify_nodes()
        self._declare_all_wires()
        self._emit_all()
        return self._assemble()

    def _classify_nodes(self):
        """First pass: classify every node."""
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            ntype = node.data.get('type', '')
            if ntype in ['cast']:
                continue

            # Pipeline registers (before regular register classification)
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
        """Classify a pipeline register node (sequential element with stall/flush gating)."""
        name = self._get_name(node)
        width = self._infer_bit_width(node)
        is_validity = node.data.get('type') == 'validity_bit'
        # Detect double-pipelining: if the pipeline_input source already
        # depends on another pipeline register output, this register would
        # add an extra (incorrect) pipeline stage.  Treat it as a
        # passthrough wire instead.
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
        pipeline register output, which would cause double-pipelining.

        A pipeline register is double-pipelined when its pipe_time matches
        its pipeline_input source's pipe_time (the value is already in
        the correct stage and re-registering it would add latency).

        Stall-related delay registers are excluded since they are
        intentional register insertions to break combinational loops.
        """
        node_pt = getattr(node, 'pipe_time', None)
        if node_pt is None:
            return False
        # Never make stall/delay/valid registers into passthroughs.
        # These are pipeline control signals that must remain sequential
        # to break combinational loops through stall/validity logic.
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
    #  Phase 1: Forward-declare ALL wires
    # ------------------------------------------------------------------ #

    def _declare_all_wires(self):
        """Forward-declare wires for ALL intermediate signals.

        This eliminates ordering issues from cyclic dataflow graphs.
        Every signal is a `wire N` that gets connected later via `<==`.
        """
        # 1. Register write wires and register outputs
        for base, info in sorted(self.registers.items()):
            w = info['width']
            wr_name = f"{base}_wr"
            en_name = f"{base}_reg_en"
            self.forward_wires.append(f"  let {wr_name} = wire {w} in")
            self.forward_wires.append(f"  let {en_name} = wire 1 in")
            self.reg_specs.append(f"  let {base} = reg spec ~enable:{en_name} {wr_name} in")
            info['_en_name'] = en_name
            if info['rd_node']:
                self.node_id_to_name[info['rd_node'].id] = base
                self._processed.add(info['rd_node'].id)
            if info['wr_node']:
                self.node_id_to_name[info['wr_node'].id] = wr_name
                # Don't mark wr_node as processed - it needs _emit_variable
                # to connect its assignment source to the register write wire.
                # The wire is already declared above, so _declare_all_wires
                # won't create a duplicate.
                self._has_wire.add(info['wr_node'].id)

        # 2. Pipeline registers (sequential elements with stall/flush gating)
        for pid, pinfo in sorted(self.pipeline_registers.items()):
            name = pinfo['name']
            w = pinfo['width']
            if pinfo.get('is_passthrough'):
                # Double-pipelined: emit as a simple wire (no register)
                self.forward_wires.append(f"  let {name} = wire {w} in")
            else:
                # Forward-declare data input and enable wires
                self.forward_wires.append(f"  let {name}_data = wire {w} in")
                self.forward_wires.append(f"  let {name}_en = wire 1 in")
                # Create register: validity bits reset to 1, others to 0
                if pinfo['is_validity']:
                    self.reg_specs.append(
                        f"  let {name} = reg (Reg_spec.override spec ~clear_to:(ones {w})) "
                        f"~enable:{name}_en {name}_data in"
                    )
                else:
                    self.reg_specs.append(
                        f"  let {name} = reg spec ~enable:{name}_en {name}_data in"
                    )
            self.node_id_to_name[pid] = name
            self._has_wire.add(pid)

        # 3. Memory infrastructure
        for mid, minfo in sorted(self.memories.items()):
            self._declare_memory(mid, minfo)

        # 4. Constants as let-bindings (no wire needed, they're values)
        for nid, cinfo in sorted(self.constants.items()):
            self.comb_lets.append(
                f"  let {cinfo['name']} = {self._ocaml_const(cinfo['value'], cinfo['width'])} in"
            )
            self._processed.add(nid)

        # 5. Forward-declare wires for ALL remaining nodes
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            if node.id in self._processed or node.id in self._has_wire:
                continue
            ntype = node.data.get('type', '')
            if ntype in ['cast']:
                continue
            if ntype.startswith('isa_state') and node.data.get('is_memory', False):
                continue  # memories handled above

            name = self._get_name(node)
            w = self._infer_bit_width(node)
            self.forward_wires.append(f"  let {name} = wire {w} in")
            self._has_wire.add(node.id)

    def _declare_memory(self, mid: str, minfo: dict):
        """Declare memory infrastructure: write port wires, read ports."""
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

        # Forward-declare write port wires
        for i, wp in enumerate(write_ports):
            self.forward_wires.append(f"  let {name}_waddr_{i} = wire {aw} in")
            self.forward_wires.append(f"  let {name}_wdata_{i} = wire {bw} in")
            self.forward_wires.append(f"  let {name}_wen_{i} = wire 1 in")
            wp.data['_hc_mem_name'] = name
            wp.data['_hc_wp_index'] = i

        # Check for byte enables on write ports (sub-word stores need read-modify-write)
        rmw_wp_indices = []
        for i, wp in enumerate(write_ports):
            has_be = any(e.data.get('type') == 'byte_enable' for e in wp.incoming_edges)
            if has_be:
                rmw_wp_indices.append(i)
                self.forward_wires.append(f"  let {name}_rmw_raddr_{i} = wire {aw} in")
                wp.data['_hc_rmw_read_idx'] = len(read_addrs) + len(rmw_wp_indices) - 1
        minfo['_rmw_wp_indices'] = rmw_wp_indices

        # Forward-declare read address wires
        for i, ra in enumerate(read_addrs):
            self.forward_wires.append(f"  let {name}_raddr_{i} = wire {aw} in")

        # Build write_ports array
        if write_ports:
            wp_strs = []
            for i in range(len(write_ports)):
                wp_strs.append(
                    f"    {{ write_clock = clock; write_address = {name}_waddr_{i}; "
                    f"write_enable = {name}_wen_{i}; write_data = {name}_wdata_{i} }}"
                )
            wp_array = "  [|\n" + ";\n".join(wp_strs) + "\n  |]"
        else:
            wp_array = (f"  [| {{ write_clock = clock; write_address = (zero {aw}); "
                        f"write_enable = gnd; write_data = (zero {bw}) }} |]")

        # Build read_addresses array (including RMW read ports)
        ra_strs = [f"{name}_raddr_{i}" for i in range(len(read_addrs))]
        for i in rmw_wp_indices:
            ra_strs.append(f"{name}_rmw_raddr_{i}")
        if ra_strs:
            ra_array = f"  [| {'; '.join(ra_strs)} |]"
        else:
            ra_array = f"  [| (zero {aw}) |]"

        self.memory_specs.append(
            f"  let {name}_read_ports = multiport_memory {depth}\n"
            f"    ~write_ports:\n{wp_array}\n"
            f"    ~read_addresses:\n{ra_array}\n"
            f"  in"
        )

        # Check if write-read forwarding is enabled on this memory
        write_read_fwd = minfo['node'].data.get('write_read_fwd', False) and len(write_ports) > 0

        # Declare wires for read ports and connect them
        for i, ra in enumerate(read_addrs):
            ra_name = self._get_name(ra)
            w = self._infer_bit_width(ra)
            self.forward_wires.append(f"  let {ra_name} = wire {w} in")
            self.comb_lets.append(f"  let {ra_name}_mem = {name}_read_ports.({i}) in")
            if write_read_fwd:
                # Write-read forwarding: forward write data when reading
                # same address that is being written (write-first semantics).
                # Uses write port 0 (the shared write port).
                fwd_cond = f"({name}_wen_0 &: ({name}_waddr_0 ==: {name}_raddr_{i}))"
                self.comb_lets.append(
                    f"  let {ra_name}_fwd = mux2 {fwd_cond} {name}_wdata_0 {ra_name}_mem in"
                )
                self.wire_connections.append(f"  {ra_name} <== {ra_name}_fwd;")
            else:
                self.wire_connections.append(f"  {ra_name} <== {ra_name}_mem;")

            # Connect the read address wire from the array index edge
            raddr_name = f"{name}_raddr_{i}"
            idx_connected = False
            for e in ra.incoming_edges:
                if e.data.get('type') in ['array_index', 'index']:
                    idx_ref = self._get_name(e.source)
                    port_w = minfo['node'].data.get('port_width')
                    if port_w:
                        shift = 3 if port_w == 64 else 2
                        idx_expr = f"(select (log_shift srl {idx_ref} (of_int ~width:(width {idx_ref}) {shift})) {aw - 1} 0)"
                    else:
                        idx_expr = f"(select {idx_ref} {aw - 1} 0)" if aw > 0 else idx_ref
                    self.wire_connections.append(f"  {raddr_name} <== {idx_expr};")
                    idx_connected = True
                    break
            if not idx_connected:
                self.wire_connections.append(f"  {raddr_name} <== (zero {aw});")

            self._processed.add(ra.id)
            self._has_wire.add(ra.id)

        # Declare RMW read data signals (for sub-word store read-modify-write)
        for idx, i in enumerate(rmw_wp_indices):
            rmw_port_idx = len(read_addrs) + idx
            self.comb_lets.append(
                f"  let {name}_rmw_rdata_{i} = {name}_read_ports.({rmw_port_idx}) in"
            )

        # Declare memory node as a completion signal.
        # For single-cycle memory, this is always 1 (vdd).
        # Pipeline variable-latency code references the memory node directly
        # for completion/idle status.
        self.comb_lets.append(f"  let {name} = vdd in")

        self._processed.add(mid)

    # ------------------------------------------------------------------ #
    #  Phase 2: Emit wire connections for all nodes
    # ------------------------------------------------------------------ #

    def _emit_all(self):
        """Emit `<==` connections for all intermediate signals."""
        for node in sorted(self.graph.nodes.values(), key=lambda n: n.id):
            if node.id in self._processed:
                continue
            self._emit_node(node)

        # Connect ISA state register enable wires (stall gating)
        self._connect_register_enables()

        # Connect any remaining unconnected wires to zero.
        # This can happen when graph nodes are unused or when optional
        # signals (e.g. unused pipeline enables) have no driver.
        connected_wires = set()
        for line in self.wire_connections:
            m = re.match(r'\s+(\w+)\s*<==', line)
            if m:
                connected_wires.add(m.group(1))

        unconnected = []
        for line in self.forward_wires:
            m = re.match(r'\s+let\s+(\w+)\s*=\s*wire\s+(\d+)', line)
            if m:
                wire_name = m.group(1)
                wire_width = int(m.group(2))
                if wire_name not in connected_wires:
                    self.wire_connections.append(
                        f"  {wire_name} <== (zero {wire_width});"
                    )
                    unconnected.append(wire_name)
        if unconnected:
            import warnings
            warnings.warn(
                f"HardCaml: {len(unconnected)} unconnected wire(s) "
                f"auto-connected to zero: {', '.join(unconnected[:10])}"
                + (f" (and {len(unconnected) - 10} more)" if len(unconnected) > 10 else "")
            )

    def _connect_register_enables(self):
        """Connect stall signals to ISA state register enable wires.

        When a pipeline stall controller sends a 'stall' or 'stall_enable'
        edge to an ISA state read or write node, the register should hold
        its value (enable=0) while the stall is active.  If no stall edges
        exist, the enable defaults to vdd (always update).
        """
        for base, info in self.registers.items():
            en_name = info.get('_en_name')
            if not en_name:
                continue

            stall_signals = []
            for node in [info.get('rd_node'), info.get('wr_node')]:
                if node is None:
                    continue
                for e in node.incoming_edges:
                    et = e.data.get('type', '')
                    if et in ('stall', 'stall_enable'):
                        stall_signals.append(self._ref(e.source))

            if stall_signals:
                # Combine multiple stall sources with OR, then invert:
                # stall=1 → hold register (enable=0)
                if len(stall_signals) == 1:
                    stall_expr = stall_signals[0]
                else:
                    stall_expr = stall_signals[0]
                    for s in stall_signals[1:]:
                        stall_expr = f"({stall_expr} |: {s})"
                enable_expr = f"(~: (uresize {stall_expr} 1))"
            else:
                enable_expr = "vdd"

            self.wire_connections.append(f"  {en_name} <== {enable_expr};")

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
        """Emit `name <== expr;` for a forward-declared wire."""
        name = self._get_name(node)
        w = self._infer_bit_width(node)
        # Ensure the expression width matches the wire width
        self.wire_connections.append(f"  {name} <== (uresize {expr} {w});")

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

        # Determine max width for binary ops to ensure width matching
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

        # Resize all operands to max width for width-matching
        if len(all_widths) >= 2:
            max_w = max(all_widths)
            resized = []
            for op, w in zip(all_ops, all_widths):
                if w != max_w:
                    resized.append(f"(uresize {op} {max_w})")
                else:
                    resized.append(op)
            all_ops = resized

        l = all_ops[0] if all_ops else None
        r = all_ops[1] if len(all_ops) > 1 else None
        return l, r, all_ops

    # ------------------------------------------------------------------ #
    #  Individual emitters (all use _connect to write wire <== expr)
    # ------------------------------------------------------------------ #

    def _emit_constant_wire(self, node: Node):
        """Connect a wire for a constant that wasn't pre-classified."""
        value, width = self._parse_literal(node)
        self._connect(node, self._ocaml_const(value, width))

    def _emit_operation(self, node: Node):
        op = node.data.get('operator') or node.data.get('operation', '')
        left, right, ops = self._get_operands(node)
        is_unsigned = self._is_unsigned_context(node)

        if len(ops) < 2:
            if len(ops) == 1:
                if op in ['!', 'not', 'logical_not']:
                    self._connect(node, f"({ops[0]} ==: (zero (width {ops[0]})))")
                elif op in ['~', 'bitwise_not', 'invert']:
                    self._connect(node, f"(~: {ops[0]})")
                else:
                    self._connect(node, ops[0])
            return

        a, b = ops[0], ops[1]

        # For associative/chainable operators with >2 operands, chain them all
        chainable_ops = {
            '||': '|:', 'logical_or': '|:',
            '&&': '&:', 'logical_and': '&:',
            '|': '|:', 'or': '|:',
            '&': '&:', 'and': '&:',
            '^': '^:', 'xor': '^:',
            '+': '+:', 'add': '+:',
        }
        if op in chainable_ops and len(ops) > 2:
            hc_op = chainable_ops[op]
            w = self._infer_bit_width(node)
            # HardCaml binary ops require matching widths; uresize all operands
            expr = f"(uresize {ops[0]} {w})"
            for operand in ops[1:]:
                expr = f"({expr} {hc_op} (uresize {operand} {w}))"
            self._connect(node, expr)
            return

        op_map = {
            '+': '+:', 'add': '+:',
            '-': '-:', 'sub': '-:',
            '*': '*:', 'mul': '*:',
            '&': '&:', 'and': '&:',
            '|': '|:', 'or': '|:',
            '^': '^:', 'xor': '^:',
        }

        if op in op_map:
            self._connect(node, f"({a} {op_map[op]} {b})")
        elif op in ['<<', 'shl']:
            self._connect(node, f"(log_shift sll {a} {b})")
        elif op in ['>>', 'shr']:
            self._connect(node, f"(log_shift srl {a} {b})")
        elif op in ['>>>', 'ashr']:
            self._connect(node, f"(log_shift sra {a} {b})")
        elif op in ['==', 'eq']:
            self._connect(node, f"({a} ==: {b})")
        elif op in ['!=', 'ne']:
            self._connect(node, f"({a} <>: {b})")
        elif op in ['<', 'lt', '<s']:
            self._connect(node, f"({a} {'<:' if is_unsigned else '<+'} {b})")
        elif op in ['>', 'gt', '>s']:
            self._connect(node, f"({a} {'>:' if is_unsigned else '>+'} {b})")
        elif op in ['<=', 'le', '<=s']:
            self._connect(node, f"({a} {'<=:' if is_unsigned else '<=+'} {b})")
        elif op in ['>=', 'ge', '>=s']:
            self._connect(node, f"({a} {'>=:' if is_unsigned else '>=+'} {b})")
        elif op in ['<u', 'ult']:
            self._connect(node, f"({a} <: {b})")
        elif op in ['>u', 'ugt']:
            self._connect(node, f"({a} >: {b})")
        elif op in ['<=u', 'ule']:
            self._connect(node, f"({a} <=: {b})")
        elif op in ['>=u', 'uge']:
            self._connect(node, f"({a} >=: {b})")
        elif op in ['||', 'logical_or']:
            self._connect(node, f"({a} |: {b})")
        elif op in ['&&', 'logical_and']:
            self._connect(node, f"({a} &: {b})")
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
                        cst = self._ocaml_const(lit_val, sw)
                        self._connect(node, f"((select {ops[0]} {hi} {lo}) ==: {cst})")
                        return
                    # Non-bit-slice left side: compare operand directly with literal
                    op_w = self._infer_bit_width(node.incoming_edges.__iter__().__next__().source)
                    lit_w = right_expr.get('width', op_w)
                    cmp_w = max(op_w, lit_w)
                    cst = self._ocaml_const(lit_val, cmp_w)
                    cmp_op = '==:'
                    if op in ['!=', 'ne']:
                        cmp_op = '<>:'
                    elif op in ['<', 'lt']:
                        cmp_op = '<+' if not is_unsigned else '<:'
                    elif op in ['>', 'gt']:
                        cmp_op = '>+' if not is_unsigned else '>:'
                    self._connect(node, f"((uresize {ops[0]} {cmp_w}) {cmp_op} {cst})")
                    return
            # Also handle compare_value from node data (e.g., byte mux selects)
            compare_value = node.data.get('compare_value')
            if compare_value is not None and len(ops) == 1:
                op_w = self._infer_bit_width(node.incoming_edges.__iter__().__next__().source)
                cst = self._ocaml_const(int(compare_value), op_w)
                cmp_op = '==:'
                if op in ['!=', 'ne']:
                    cmp_op = '<>:'
                self._connect(node, f"((uresize {ops[0]} {op_w}) {cmp_op} {cst})")
                return
            if len(ops) == 1:
                self._connect(node, ops[0])
            else:
                self._connect(node, "gnd")
            return

        a, b = ops[0], ops[1]
        cmp_map_u = {'==': '==:', 'eq': '==:', '!=': '<>:', 'ne': '<>:',
                     '<': '<:', 'lt': '<:', '<u': '<:', 'ult': '<:',
                     '>': '>:', 'gt': '>:', '>u': '>:', 'ugt': '>:',
                     '<=': '<=:', 'le': '<=:', '<=u': '<=:', 'ule': '<=:',
                     '>=': '>=:', 'ge': '>=:', '>=u': '>=:', 'uge': '>=:'}
        cmp_map_s = {'<': '<+', 'lt': '<+', '<s': '<+',
                     '>': '>+', 'gt': '>+', '>s': '>+',
                     '<=': '<=+', 'le': '<=+', '<=s': '<=+',
                     '>=': '>=+', 'ge': '>=+', '>=s': '>=+'}

        if op in ['==', 'eq', '!=', 'ne']:
            self._connect(node, f"({a} {cmp_map_u[op]} {b})")
        elif is_unsigned or op in ['<u', '>u', '<=u', '>=u', 'ult', 'ugt', 'ule', 'uge']:
            self._connect(node, f"({a} {cmp_map_u.get(op, '==:')} {b})")
        else:
            hc_op = cmp_map_s.get(op, cmp_map_u.get(op, '==:'))
            self._connect(node, f"({a} {hc_op} {b})")

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
            self._connect(node, f"(select {self._ref(src_edge.source)} {hi} {lo})")
        else:
            self._connect(node, "gnd")

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
                f"(mux2 (bit {cond} 0) (uresize {true_val} {w}) (uresize {false_val} {w}))")
        else:
            self._connect(node, f"(zero {self._infer_bit_width(node)})")

    def _emit_array_access(self, node: Node):
        """Emit read address connection for memory reads."""
        if node.id in self._processed:
            return
        # Memory reads already handled in _declare_memory
        # This handles non-memory array accesses
        w = self._infer_bit_width(node)
        self._connect(node, f"(zero {w})")

    def _emit_concatenation(self, node: Node):
        parts = []
        for e in sorted(node.incoming_edges, key=lambda e: e.data.get('position', 0)):
            parts.append(self._ref(e.source))
        if len(parts) == 1:
            self._connect(node, parts[0])
        elif parts:
            self._connect(node, f"(concat_msb [{'; '.join(parts)}])")
        else:
            self._connect(node, "gnd")

    def _emit_repetition(self, node: Node):
        count = node.data.get('count', node.data.get('repetitions', 1))
        expr = node.data.get('expression', {})
        if expr.get('type') == 'repetition':
            count = expr.get('count', count)
        src_edge = next(iter(node.incoming_edges), None)
        if src_edge:
            src = self._ref(src_edge.source)
            parts = "; ".join([src] * count)
            self._connect(node, f"(concat_msb [{parts}])")
        else:
            self._connect(node, f"(zero {self._infer_bit_width(node)})")

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
                self.wire_connections.append(f"  {base}_wr <== (uresize {src} {w});")
            else:
                self._connect(node, src)
        else:
            self._connect(node, src)

    def _emit_enable(self, node: Node):
        w = self._infer_bit_width(node)
        conds = [self._ref(e.source) for e in sorted(node.incoming_edges, key=lambda e: e.source.id)]
        if not conds:
            self._connect(node, "vdd")
        elif len(conds) == 1:
            self._connect(node, conds[0])
        else:
            # HardCaml &: requires matching widths; uresize all operands
            resized = [f"(uresize {c} {w})" for c in conds]
            expr = resized[0]
            for c in resized[1:]:
                expr = f"({expr} &: {c})"
            self._connect(node, expr)

    def _emit_logical_or(self, node: Node):
        w = self._infer_bit_width(node)
        conds = [self._ref(e.source) for e in sorted(node.incoming_edges, key=lambda e: e.source.id)]
        if not conds:
            self._connect(node, "gnd")
        elif len(conds) == 1:
            self._connect(node, conds[0])
        else:
            # HardCaml |: requires matching widths; uresize all operands
            resized = [f"(uresize {c} {w})" for c in conds]
            expr = resized[0]
            for c in resized[1:]:
                expr = f"({expr} |: {c})"
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
            default_val = f"(zero {width})"

        current = f"(uresize {default_val} {width})"
        for idx in sorted(selects_by_idx.keys()):
            if idx in inputs_by_idx:
                sel = selects_by_idx[idx]
                val = inputs_by_idx[idx]
                current = (f"(mux2 (bit {sel} 0) "
                           f"(uresize {val} {width}) {current})")

        self._connect(node, current)

    def _emit_shared_write(self, node: Node):
        for e in node.incoming_edges:
            if e.data.get('type') in ['data', 'assignment', 'operand']:
                self._connect(node, self._ref(e.source))
                return
        self._connect(node, f"(zero {self._infer_bit_width(node)})")

    def _emit_zero_extend(self, node: Node):
        target_w = self._infer_bit_width(node)
        for e in node.incoming_edges:
            self._connect(node, f"(uresize {self._ref(e.source)} {target_w})")
            return
        self._connect(node, f"(zero {target_w})")

    def _emit_memory_write_port(self, node: Node):
        mem_name = node.data.get('_hc_mem_name')
        wp_idx = node.data.get('_hc_wp_index')

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

        # Compute address expression
        addr_expr = addr_wire
        if addr_wire:
            if port_width:
                shift = 3 if port_width == 64 else 2
                addr_expr = f"(log_shift srl {addr_wire} (of_int ~width:(width {addr_wire}) {shift}))"
            self.wire_connections.append(f"  {waddr} <== (select {addr_expr} {aw - 1} 0);")

        # Check for byte enables (sub-word stores need read-modify-write)
        byte_enable_edges = [e for e in node.incoming_edges if e.data.get('type') == 'byte_enable']
        rmw_read_idx = node.data.get('_hc_rmw_read_idx')

        if byte_enable_edges and rmw_read_idx is not None and data_wire and addr_wire:
            # Connect RMW read address = write address
            rmw_raddr = f"{mem_name}_rmw_raddr_{wp_idx}"
            self.wire_connections.append(f"  {rmw_raddr} <== (select {addr_expr} {aw - 1} 0);")

            rmw_rdata = f"{mem_name}_rmw_rdata_{wp_idx}"
            num_bytes = bw // 8

            # Build combined byte enable:
            # - For sub-word writers: gate byte_enable with instruction enable
            # - For full-word writers: gate all-ones with instruction enable
            be_terms = []

            # Sub-word writers (have byte_enable edges)
            for be_edge in byte_enable_edges:
                instr = be_edge.data.get('instruction', '')
                be_ref = self._ref(be_edge.source)
                enable_ref = self._find_instruction_enable(instr)
                if enable_ref:
                    be_terms.append(
                        f"(mux2 (bit {enable_ref} 0) (uresize {be_ref} {num_bytes}) (zero {num_bytes}))"
                    )
                else:
                    be_terms.append(f"(uresize {be_ref} {num_bytes})")

            # Full-word writers (no byte_enable, write all bytes)
            writers = node.data.get('writers', [])
            be_instrs = {e.data.get('instruction', '') for e in byte_enable_edges}
            for writer in writers:
                if writer not in be_instrs:
                    enable_ref = self._find_instruction_enable(writer)
                    if enable_ref:
                        be_terms.append(
                            f"(mux2 (bit {enable_ref} 0) (ones {num_bytes}) (zero {num_bytes}))"
                        )

            # Combine all byte enable terms with OR
            if not be_terms:
                combined_be = f"(ones {num_bytes})"
            elif len(be_terms) == 1:
                combined_be = be_terms[0]
            else:
                combined_be = be_terms[0]
                for term in be_terms[1:]:
                    combined_be = f"({combined_be} |: {term})"

            # Forward-declare combined byte enable and expanded mask wires
            cbe_name = f"{mem_name}_combined_be_{wp_idx}"
            mask_name = f"{mem_name}_be_mask_{wp_idx}"
            self.forward_wires.append(f"  let {cbe_name} = wire {num_bytes} in")
            self.forward_wires.append(f"  let {mask_name} = wire {bw} in")
            self.wire_connections.append(f"  {cbe_name} <== {combined_be};")

            # Expand byte enable to full-width mask (each bit -> 8 bits)
            expand_parts = []
            for b in range(num_bytes - 1, -1, -1):  # MSB first for concat_msb
                expand_parts.append(f"(repeat (bit {cbe_name} {b}) 8)")
            self.wire_connections.append(
                f"  {mask_name} <== (concat_msb [{'; '.join(expand_parts)}]);"
            )

            # RMW: final_data = (old_word & ~mask) | (new_data & mask)
            self.wire_connections.append(
                f"  {wdata} <== (({rmw_rdata} &: (~: {mask_name})) "
                f"|: ((uresize {data_wire} {bw}) &: {mask_name}));"
            )
        else:
            # No RMW needed - write data directly
            if data_wire:
                self.wire_connections.append(f"  {wdata} <== (uresize {data_wire} {bw});")

        if enable_wire:
            self.wire_connections.append(f"  {wen} <== (bit {enable_wire} 0);")
        else:
            self.wire_connections.append(f"  {wen} <== gnd;")

    def _emit_pipeline_register(self, node: Node):
        """Emit wire connections for a pipeline register.

        Pipeline registers are sequential elements gated by stall and validity
        signals. The register declaration (with enable) is done in
        _declare_all_wires; here we connect the data input and compute the
        enable signal from stall/valid_gate edges.

        Passthrough pipeline registers (double-pipelined signals) are emitted
        as simple wire connections, bypassing the register.
        """
        pinfo = self.pipeline_registers.get(node.id)
        if pinfo is None:
            # Fallback for unclassified pipeline registers
            self._emit_passthrough(node)
            return

        name = pinfo['name']
        w = pinfo['width']

        # Find incoming edges by type
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
                # stall_enable acts like stall (prevents update)
                stall_signal = self._ref(e.source)

        if pinfo.get('is_passthrough'):
            # Passthrough: connect the wire directly to the data source
            if data_source:
                self.wire_connections.append(f"  {name} <== (uresize {data_source} {w});")
            else:
                self.wire_connections.append(f"  {name} <== (zero {w});")
            return

        # Connect data input
        if data_source:
            self.wire_connections.append(f"  {name}_data <== (uresize {data_source} {w});")
        else:
            self.wire_connections.append(f"  {name}_data <== (zero {w});")

        # Compute enable: update when NOT stalled AND valid_gate is asserted
        if stall_signal and valid_gate_signal:
            enable_expr = f"((~: (bit {stall_signal} 0)) &: (bit {valid_gate_signal} 0))"
        elif stall_signal:
            enable_expr = f"(~: (bit {stall_signal} 0))"
        elif valid_gate_signal:
            enable_expr = f"(bit {valid_gate_signal} 0)"
        else:
            enable_expr = "vdd"

        self.wire_connections.append(f"  {name}_en <== {enable_expr};")

    def _emit_stall_controller(self, node: Node):
        conds = []
        for e in node.incoming_edges:
            if e.data.get('type') == 'control':
                conds.append(self._ref(e.source))
        if not conds:
            self._connect(node, "gnd")
        elif len(conds) == 1:
            self._connect(node, conds[0])
        else:
            expr = conds[0]
            for c in conds[1:]:
                expr = f"({expr} |: {c})"
            self._connect(node, expr)

    def _emit_passthrough(self, node: Node):
        for e in node.incoming_edges:
            if e.data.get('type') != 'stall':
                self._connect(node, self._ref(e.source))
                return
        self._connect(node, f"(zero {self._infer_bit_width(node)})")

    # ------------------------------------------------------------------ #
    #  Assembly
    # ------------------------------------------------------------------ #

    def _assemble(self) -> str:
        """Assemble the complete OCaml source file."""
        lines = []
        lines.append("(* Generated by ISAComp HardCaml backend *)")
        lines.append("(* Compile: dune build *)")
        lines.append("(* Run: dune exec ./FILENAME.exe to generate Verilog *)")
        lines.append("")
        lines.append("[@@@warning \"-26-27\"]")
        lines.append("")
        lines.append("open Hardcaml")
        lines.append("open Signal")
        lines.append("")
        lines.append("let () =")
        lines.append("  let clock = input \"clock\" 1 in")
        lines.append("  let clear = input \"clear\" 1 in")
        lines.append("  let spec = Reg_spec.create ~clock ~clear () in")
        lines.append("")

        if self.forward_wires:
            lines.append("  (* Forward-declared wires *)")
            lines.extend(self.forward_wires)
            lines.append("")

        if self.reg_specs:
            lines.append("  (* Registers *)")
            lines.extend(self.reg_specs)
            lines.append("")

        if self.memory_specs:
            lines.append("  (* Memories *)")
            lines.extend(self.memory_specs)
            lines.append("")

        if self.comb_lets:
            lines.append("  (* Constants and memory read aliases *)")
            lines.extend(self.comb_lets)
            lines.append("")

        if self.wire_connections:
            lines.append("  (* Wire connections *)")
            lines.extend(self.wire_connections)
            lines.append("")

        # Outputs
        output_signals = []
        for base, info in sorted(self.registers.items()):
            output_signals.append(f"    output \"{base}\" {base}")

        # Export pipeline registers as outputs (for testbench observability)
        for pid, pinfo in sorted(self.pipeline_registers.items()):
            output_signals.append(
                f"    output \"{pinfo['name']}\" {pinfo['name']}"
            )

        if not output_signals:
            output_signals.append("    output \"gnd\" gnd")

        lines.append("  (* Build circuit *)")
        lines.append(f"  let circuit = Circuit.create_exn ~name:\"{self.module_name}\" [")
        lines.append(";\n".join(output_signals))
        lines.append("  ] in")
        lines.append("")
        lines.append("  (* Output Verilog *)")
        lines.append("  Rtl.print Verilog circuit")
        lines.append("")

        return "\n".join(lines)


def generate_hardcaml(graph: ResourceGraph, module_name: str = "processor") -> str:
    """Generate OCaml/HardCaml source code from a ResourceGraph."""
    generator = HardCamlGenerator(graph, module_name)
    return generator.generate()
