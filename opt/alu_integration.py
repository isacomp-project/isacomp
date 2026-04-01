"""
ALU integration for ResourceGraphs.

Replaces user-specified operation nodes with a shared ALU module,
operand muxes, and an opcode mux.  The caller names the graph nodes
to integrate; this module validates them and performs the graph surgery.

New node types introduced:

* ``alu_module``       – the shared ALU (incoming: operands + opcode;
                         outgoing: result edges to original targets)
* ``alu_opcode_mux``   – priority mux selecting opcode from instruction
                         enables
* ``alu_operand_mux``  – priority mux selecting an operand from
                         instruction enables (one per operand position)
"""

import logging
from typing import Dict, List, Optional
from core.resource_graph import ResourceGraph, Node, Edge

logger = logging.getLogger(__name__)


class ALUSpec:
    """Specification for an ALU module."""

    def __init__(self, name: str, input_width: int = 32, output_width: int = 32):
        self.name = name
        self.input_width = input_width
        self.output_width = output_width
        self.operations = {}  # operator -> opcode mapping
        self.opcode_width = 0

    def add_operation(self, operator: str, opcode: int, description: str = ""):
        """Add an operation to this ALU."""
        self.operations[operator] = {
            'opcode': opcode,
            'description': description
        }
        max_opcode = max(op['opcode'] for op in self.operations.values())
        self.opcode_width = max_opcode.bit_length()

    def supports_operation(self, operator: str) -> bool:
        return operator in self.operations

    def get_opcode(self, operator: str) -> Optional[int]:
        return self.operations.get(operator, {}).get('opcode')

    def __str__(self):
        ops = [f"{op}: {info['opcode']}" for op, info in self.operations.items()]
        return f"ALU({self.name}, ops=[{', '.join(ops)}])"


# ====================================================================== #
#  Introspection helpers (public API for --list-operations etc.)           #
# ====================================================================== #

def get_operation_operator(node: Node) -> Optional[str]:
    """Extract operator from a binary operation or comparison-ternary.

    Recognises ``(cmp) ? 1 : 0`` ternaries — the common ISA pattern
    for slt / sltu — and returns the comparison operator so the ALU
    case body (which evaluates the full ``cmp ? 1 : 0``) is used.
    """
    expr = node.data.get('expression', {})

    if expr.get('type') == 'binary_op':
        return expr.get('operator')

    if node.data.get('type') == 'ternary_op':
        cond_edge = true_edge = false_edge = None
        for edge in node.incoming_edges:
            etype = edge.data.get('type')
            if etype == 'ternary_condition':
                cond_edge = edge
            elif etype == 'ternary_true':
                true_edge = edge
            elif etype == 'ternary_false':
                false_edge = edge

        if cond_edge and true_edge and false_edge:
            true_val = true_edge.source.data.get('value')
            false_val = false_edge.source.data.get('value')
            if true_val == 1 and false_val == 0:
                cond_expr = cond_edge.source.data.get('expression', {})
                if cond_expr.get('type') == 'binary_op':
                    return cond_expr.get('operator')

    return None


def get_enable_signal(node: Node) -> Optional[str]:
    """Return the Verilog enable expression for *node*.

    - Grouped nodes (with ``group_members``): OR of all member enables
    - Instruction-specific nodes: ``{instruction}_enable``
    """
    members = node.data.get('group_members')
    if members:
        return ' || '.join(f"{m}_enable" for m in sorted(members))

    instruction = node.data.get('instruction')
    if instruction is not None:
        return f"{instruction}_enable"

    return None


# ====================================================================== #
#  Validation                                                              #
# ====================================================================== #

def validate_node(graph: ResourceGraph, node_id: str,
                  alu_spec: ALUSpec) -> Optional[str]:
    """Check whether *node_id* can legally be integrated into *alu_spec*.

    Returns ``None`` if the node is valid, or an error message string
    explaining why it cannot be integrated.
    """
    node = graph.nodes.get(node_id)
    if node is None:
        return f"node '{node_id}' not found in graph"

    operator = get_operation_operator(node)
    if operator is None:
        return f"node '{node_id}' is not a binary operation or comparison-ternary"

    if not alu_spec.supports_operation(operator):
        return (f"ALU '{alu_spec.name}' does not support operator '{operator}' "
                f"(node '{node_id}')")

    enable = get_enable_signal(node)
    if enable is None:
        return (f"node '{node_id}' has no determinable enable signal "
                f"(needs instruction or group_members)")

    if not node.outgoing_edges:
        return f"node '{node_id}' has no outgoing edges"

    for edge in node.outgoing_edges:
        target_name = edge.target.data.get('name', edge.target.id)
        if edge.data.get('type') == 'assignment' and target_name in ('pc', 'pc_wr'):
            return f"node '{node_id}' writes to PC — keep as dedicated adder"

    return None


def _resolve_operands(op_node: Node, operand_node: Node):
    """Resolve left and right operand sources for *operand_node*.

    Raises ValueError if operands cannot be determined.
    """
    left_src = right_src = None
    for edge in operand_node.incoming_edges:
        pos = edge.data.get('position', edge.data.get('operand_position'))
        if pos == 'left':
            left_src = edge.source
        elif pos == 'right':
            right_src = edge.source

    if left_src is None or right_src is None:
        # Fallback: take first two edges sorted by source id.
        edges = sorted(operand_node.incoming_edges, key=lambda e: e.source.id)
        if len(edges) >= 2:
            if left_src is None:
                left_src = edges[0].source
            if right_src is None:
                right_src = edges[1].source

    if left_src is None or right_src is None:
        raise ValueError(
            f"cannot resolve both operands for node '{op_node.id}' "
            f"(operand node '{operand_node.id}' has "
            f"{len(list(operand_node.incoming_edges))} incoming edges)"
        )

    return left_src, right_src


# ====================================================================== #
#  Graph surgery                                                           #
# ====================================================================== #

def apply_alu_integration(graph: ResourceGraph, alu_spec: ALUSpec,
                          node_ids: List[str]) -> bool:
    """Replace the named *node_ids* with a shared ALU.

    Args:
        graph:    The ResourceGraph to transform (modified in place).
        alu_spec: ALU specification describing the shared module.
        node_ids: Graph node IDs to replace with the ALU.

    Returns:
        True if the ALU was created.
        False if fewer than 2 valid nodes were provided (no sharing possible).

    Raises:
        ValueError: if any node_id fails validation, if operands cannot
            be resolved, or if the ALU name would collide with existing
            graph nodes.
    """
    # ---- validate every node the caller asked for ----------------------
    nodes: List[Node] = []
    for nid in node_ids:
        err = validate_node(graph, nid, alu_spec)
        if err:
            raise ValueError(err)
        nodes.append(graph.nodes[nid])

    if len(nodes) < 2:
        logger.warning("Need at least 2 nodes to share an ALU, got %d", len(nodes))
        return False

    # ---- guard against duplicate ALU names -----------------------------
    alu_name = f"{alu_spec.name}_module"
    for existing_id in graph.nodes:
        if existing_id == alu_name or existing_id.startswith(f"{alu_name}_"):
            raise ValueError(
                f"ALU node ID '{existing_id}' already exists in graph "
                f"(alu_spec.name='{alu_spec.name}')"
            )

    # ---- collect per-operation info ------------------------------------
    data_width = alu_spec.input_width
    output_width = alu_spec.output_width
    opcode_width = alu_spec.opcode_width

    op_info_list = []
    for op_node in nodes:
        operator = get_operation_operator(op_node)
        enable = get_enable_signal(op_node)

        # For ternaries, pull operands from the condition comparison node.
        operand_node = op_node
        if op_node.data.get('type') == 'ternary_op':
            for edge in op_node.incoming_edges:
                if edge.data.get('type') == 'ternary_condition':
                    operand_node = edge.source
                    break

        left_src, right_src = _resolve_operands(op_node, operand_node)
        outgoing = list(op_node.outgoing_edges)

        op_info_list.append({
            'node': op_node,
            'operand_node': operand_node,
            'enable': enable,
            'operator': operator,
            'opcode': alu_spec.get_opcode(operator),
            'left_src': left_src,
            'right_src': right_src,
            'outgoing': outgoing,
        })

    logger.debug("Integrating %d nodes into %s", len(nodes), alu_spec.name)
    for info in op_info_list:
        logger.debug("  %s: %s [enable=%s]",
                      info['operator'], info['node'].id, info['enable'])

    # ---- create operand-A mux -----------------------------------------
    op_a_name = f"{alu_name}_op_a_mux"
    op_a_node = Node(op_a_name, {
        'type': 'alu_operand_mux',
        'name': op_a_name,
        'display_name': f"{alu_spec.name} operand A mux",
        'bit_width': data_width,
        'mux_entries': [],
    })
    graph.add_node(op_a_node)

    for info in op_info_list:
        entry = {'enable': info['enable'], 'source_id': info['left_src'].id}
        op_a_node.data['mux_entries'].append(entry)
        graph.add_edge(Edge(info['left_src'], op_a_node, data={
            'type': 'mux_input', 'enable_signal': info['enable'],
        }))

    # ---- create operand-B mux -----------------------------------------
    op_b_name = f"{alu_name}_op_b_mux"
    op_b_node = Node(op_b_name, {
        'type': 'alu_operand_mux',
        'name': op_b_name,
        'display_name': f"{alu_spec.name} operand B mux",
        'bit_width': data_width,
        'mux_entries': [],
    })
    graph.add_node(op_b_node)

    for info in op_info_list:
        entry = {'enable': info['enable'], 'source_id': info['right_src'].id}
        op_b_node.data['mux_entries'].append(entry)
        graph.add_edge(Edge(info['right_src'], op_b_node, data={
            'type': 'mux_input', 'enable_signal': info['enable'],
        }))

    # ---- create opcode mux --------------------------------------------
    opc_name = f"{alu_name}_opcode_mux"
    opc_node = Node(opc_name, {
        'type': 'alu_opcode_mux',
        'name': opc_name,
        'display_name': f"{alu_spec.name} opcode mux",
        'bit_width': opcode_width,
        'mux_entries': [
            {'enable': info['enable'], 'opcode': info['opcode']}
            for info in op_info_list
        ],
    })
    graph.add_node(opc_node)

    # ---- create ALU module node ----------------------------------------
    alu_node = Node(alu_name, {
        'type': 'alu_module',
        'name': alu_name,
        'display_name': alu_spec.name,
        'alu_spec': alu_spec,
        'input_width': data_width,
        'output_width': output_width,
        'opcode_width': opcode_width,
        'bit_width': output_width,
    }, is_uarch_state=True)
    graph.add_node(alu_node)

    graph.add_edge(Edge(op_a_node, alu_node, data={
        'type': 'alu_operand', 'signal_name': 'operand_a'}))
    graph.add_edge(Edge(op_b_node, alu_node, data={
        'type': 'alu_operand', 'signal_name': 'operand_b'}))
    graph.add_edge(Edge(opc_node, alu_node, data={
        'type': 'alu_opcode', 'signal_name': 'opcode'}))

    # ---- wire ALU result to all original consumers ---------------------
    for info in op_info_list:
        for edge in info['outgoing']:
            new_data = dict(edge.data)
            new_data['enable_signal'] = info['enable']
            new_data['original_operation'] = info['node'].id
            graph.add_edge(Edge(alu_node, edge.target, data=new_data))
            logger.debug("  result -> %s (%s)", edge.target.id, edge.data.get('type'))

    # ---- remove original nodes -----------------------------------------
    for info in op_info_list:
        _remove_node(graph, info['node'])
        # For comparison-ternaries, also remove the bare comparison
        # node if it has no other consumers.
        cond_node = info['operand_node']
        if cond_node is not info['node'] and cond_node.id in graph.nodes:
            remaining = [e for e in cond_node.outgoing_edges
                         if e.target.id in graph.nodes]
            if not remaining:
                _remove_node(graph, cond_node)

    logger.debug("Created ALU subgraph: %s (%d ops)", alu_spec.name, len(nodes))
    return True


def _remove_node(graph: ResourceGraph, node: Node):
    """Remove a node and all its edges from the graph."""
    for edge in list(node.incoming_edges) + list(node.outgoing_edges):
        edge.remove_from_nodes()
        graph.edges.pop(edge.id, None)
    graph.nodes.pop(node.id, None)


def create_standard_alu() -> ALUSpec:
    """Create a standard ALU specification."""
    alu = ALUSpec("StandardALU", input_width=32, output_width=32)
    alu.add_operation('+', 0b000, "Addition")
    alu.add_operation('-', 0b001, "Subtraction")
    alu.add_operation('|', 0b010, "Bitwise OR")
    alu.add_operation('&', 0b011, "Bitwise AND")
    alu.add_operation('^', 0b100, "Bitwise XOR")
    alu.add_operation('<<', 0b101, "Left shift")
    alu.add_operation('>>', 0b110, "Right shift")
    return alu
