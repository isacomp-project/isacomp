#!/usr/bin/env python3
"""
ILA-specific Verilog generator.

This generator understands the ILA node format from ila_parser_real.py
and generates synthesizable Verilog code.
"""

import sys
from pathlib import Path
from typing import Dict, Set, List, Tuple

# Add parent directory to path to import resource_graph
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.resource_graph import ResourceGraph, Node, Edge


class ILAVerilogGenerator:
    """Generate Verilog from ILA resource graph."""

    def __init__(self, graph: ResourceGraph, module_name: str = "aes_module"):
        self.graph = graph
        self.module_name = module_name
        self.indent_level = 0
        self.generated_expr = {}  # Map node_id -> verilog wire name
        self.wire_counter = 0

        # Build ILA ID to node ID mapping
        self.ila_id_to_node = {}
        for node in graph.nodes.values():
            if isinstance(node.data, dict) and 'ila_id' in node.data:
                self.ila_id_to_node[node.data['ila_id']] = node

    def _indent(self) -> str:
        return "  " * self.indent_level

    def _fresh_wire(self, prefix: str = "w") -> str:
        """Generate a unique wire name."""
        name = f"{prefix}_{self.wire_counter}"
        self.wire_counter += 1
        return name

    def _get_node_width(self, node: Node) -> int:
        """Get bit width of a node."""
        if not isinstance(node.data, dict):
            return 1

        node_type = node.data.get('type')

        if node_type == 'literal':
            return node.data.get('width', 32)
        elif node_type == 'isa_state':
            return node.data.get('bit_width', 32)
        elif node_type == 'bit_slice':
            high = node.data.get('high_bit', 0)
            low = node.data.get('low_bit', 0)
            return high - low + 1
        elif node_type == 'array_access':
            # Memory reads return element width
            # Need to find the memory node
            return 8  # Default for AES S-box
        elif node_type == 'function_application':
            # function_application nodes should be inlined before Verilog generation
            # If we encounter one, it's an error in the inlining process
            print(f"WARNING: Found un-inlined function_application node: {node.id}")
            return 32
        else:
            # Try to infer from expression or use default
            return 32

    def _get_operands(self, node: Node) -> List[Tuple[int, Node]]:
        """Get operands of a node, ordered by position."""
        operands = []
        for edge_id, edge in self.graph.edges.items():
            if edge.target.id == node.id:
                edge_data = edge.data if isinstance(edge.data, dict) else {}
                edge_type = edge_data.get('type')

                # Accept different edge types depending on node type
                node_type = node.data.get('type') if isinstance(node.data, dict) else None

                if edge_type == 'operand':
                    pos = edge_data.get('position', 0)
                    operands.append((pos, edge.source))
                elif edge_type == 'concat_input' and node_type == 'concatenation':
                    pos = edge_data.get('position', 0)
                    operands.append((pos, edge.source))
                elif edge_type == 'array_index' and node_type == 'array_access':
                    # ILA array_access uses array_index edges for memory and address
                    pos = edge_data.get('position', 0)
                    operands.append((pos, edge.source))
                elif edge_type in ['ternary_condition', 'ternary_true', 'ternary_false'] and node_type in ['ternary_op', 'conditional']:
                    # Map ternary edge types to positions
                    if edge_type == 'ternary_condition':
                        pos = 0
                    elif edge_type == 'ternary_true':
                        pos = 1
                    elif edge_type == 'ternary_false':
                        pos = 2
                    operands.append((pos, edge.source))

        # Sort by position
        operands.sort(key=lambda x: x[0])
        return operands

    def _generate_expression(self, node: Node) -> str:
        """Generate Verilog expression for a node."""

        # If already generated, return the wire name
        if node.id in self.generated_expr:
            return self.generated_expr[node.id]

        if not isinstance(node.data, dict):
            return "1'b0"

        node_type = node.data.get('type')

        # Literals
        if node_type == 'literal':
            value = node.data.get('value', 0)
            width = node.data.get('width', 32)

            # Check if this is a memory constant (LUT)
            if isinstance(value, dict):
                # This is a memory array - should be declared separately, not inlined
                # Generate a reference to the memory instead
                # For now, return a placeholder - these should be declared in the memory section
                mem_name = f"mem_{node.id}"
                return mem_name

            return f"{width}'d{value}"

        # ISA state reads
        if node_type == 'isa_state':
            return node.data.get('name', node.id)

        # Binary operations
        if node_type == 'operation':
            operator = node.data.get('operator')
            operands = self._get_operands(node)

            if len(operands) == 2:
                left_expr = self._generate_expression(operands[0][1])
                right_expr = self._generate_expression(operands[1][1])

                # Handle signed comparison operators specially
                if operator == '<s':
                    return f"($signed({left_expr}) < $signed({right_expr}))"
                elif operator == '>s':
                    return f"($signed({left_expr}) > $signed({right_expr}))"
                elif operator == '<=s':
                    return f"($signed({left_expr}) <= $signed({right_expr}))"
                elif operator == '>=s':
                    return f"($signed({left_expr}) >= $signed({right_expr}))"

                # Map operators
                op_map = {
                    '==': '==', '!=': '!=',
                    '<': '<', '>': '>', '<=': '<=', '>=': '>=',
                    '+': '+', '-': '-', '*': '*', '/': '/',
                    '&': '&', '|': '|', '^': '^',
                    '&&': '&&', '||': '||',
                    '<<': '<<', '>>': '>>',
                    'lshr': '>>', 'ashr': '>>>'
                }

                verilog_op = op_map.get(operator, operator)
                return f"({left_expr} {verilog_op} {right_expr})"

            elif len(operands) == 1:
                # Unary operators
                operand_expr = self._generate_expression(operands[0][1])

                if operator == '~':
                    return f"(~{operand_expr})"
                elif operator == '!':
                    return f"(!{operand_expr})"
                elif operator == '-':
                    return f"(-{operand_expr})"
                else:
                    return operand_expr

        # Ternary operations (condition ? true : false)
        if node_type == 'ternary_op':
            operands = self._get_operands(node)
            if len(operands) == 3:
                cond = self._generate_expression(operands[0][1])
                true_val = self._generate_expression(operands[1][1])
                false_val = self._generate_expression(operands[2][1])
                return f"({cond} ? {true_val} : {false_val})"

        # Bit slicing
        if node_type == 'bit_slice':
            operands = self._get_operands(node)
            if operands:
                source_expr = self._generate_expression(operands[0][1])
                high = node.data.get('high_bit', 0)
                low = node.data.get('low_bit', 0)
                if high == low:
                    return f"{source_expr}[{high}]"
                else:
                    return f"{source_expr}[{high}:{low}]"

        # Concatenation
        if node_type == 'concatenation':
            operands = self._get_operands(node)
            exprs = [self._generate_expression(op[1]) for op in operands]
            return "{" + ", ".join(exprs) + "}"

        # Array access (memory read - LUT lookup)
        if node_type == 'array_access':
            operands = self._get_operands(node)
            if len(operands) >= 2:
                # First operand is memory, second is address
                mem_expr = self._generate_expression(operands[0][1])
                addr_expr = self._generate_expression(operands[1][1])
                return f"{mem_expr}[{addr_expr}]"

        # Zero extend - pad with zeros to wider width
        if node_type == 'zero_extend':
            operands = self._get_operands(node)
            if operands:
                source_expr = self._generate_expression(operands[0][1])
                target_width = node.data.get('width', 32)
                source_width = self._get_node_width(operands[0][1])
                if target_width > source_width:
                    padding = target_width - source_width
                    return f"{{{padding}'d0, {source_expr}}}"
                else:
                    return source_expr

        # Memory write - generate as empty for now (side effects handled in testbench)
        if node_type == 'memory_write':
            # Memory writes are side effects, not values
            # Return empty string or comment
            return f"/* memory write */"

        # Function application (uninterpreted functions / child ILAs)
        if node_type == 'function_application':
            # These should have been inlined by the parser!
            width = self._get_node_width(node)
            func_name = node.data.get('function_name', 'unknown_func')
            ila_id = node.data.get('ila_id', '')
            print(f"WARNING: Uninterpreted function {func_name} (ID {ila_id}) not inlined by parser!")
            return f"{width}'d0 /* ERROR: uninterpreted function {ila_id}: {func_name} should have been inlined */"

        # Unknown node type
        return f"/* unknown: {node_type} */"

    def generate(self) -> str:
        """Generate complete Verilog module."""

        lines = []

        # Find ISA states (these become module ports and registers)
        # Deduplicate by name
        isa_states_dict = {}
        for n in self.graph.nodes.values():
            if isinstance(n.data, dict) and n.data.get('type') == 'isa_state':
                name = n.data.get('name')
                if name and name not in isa_states_dict:
                    isa_states_dict[name] = n
        isa_states = list(isa_states_dict.values())

        # Find instructions (prioritize inlined child instructions over originals)
        instructions = []
        seen_names = {}  # name -> (is_inlined, node)

        for n in self.graph.nodes.values():
            if isinstance(n.data, dict) and n.data.get('type') == 'instruction':
                name = n.data.get('name', 'unnamed')
                is_inlined = 'inlined_from' in n.data

                if name not in seen_names:
                    seen_names[name] = (is_inlined, n)
                elif is_inlined and not seen_names[name][0]:
                    # Replace non-inlined with inlined version
                    seen_names[name] = (is_inlined, n)

        instructions = [node for (is_inlined, node) in seen_names.values()]

        # Module header
        lines.append(f"module {self.module_name} (")
        lines.append("  input wire clk,")
        lines.append("  input wire rst")

        # Add state variables as ports (inputs for initial values, outputs for current values)
        for state in isa_states:
            name = state.data.get('name')
            width = state.data.get('bit_width', 32)
            lines.append(f"  // State: {name}")
            if width == 1:
                lines.append(f"  // input wire {name}_in,")
                lines.append(f"  // output reg {name}_out")
            else:
                lines.append(f"  // input wire [{width-1}:0] {name}_in,")
                lines.append(f"  // output reg [{width-1}:0] {name}_out")

        lines.append(");")
        lines.append("")

        # Declare state registers
        lines.append("// State registers")
        for state in isa_states:
            name = state.data.get('name')
            width = state.data.get('bit_width', 32)
            if width == 1:
                lines.append(f"reg {name};")
            else:
                lines.append(f"reg [{width-1}:0] {name};")
        lines.append("")

        # Memory declarations (for LUTs)
        lines.append("// Memory declarations (LUTs)")
        # Find memory constant nodes
        mem_nodes = [n for n in self.graph.nodes.values()
                     if isinstance(n.data, dict) and
                     n.data.get('type') == 'literal' and
                     isinstance(n.data.get('value'), dict)]

        if mem_nodes:
            for mem_node in mem_nodes:
                mem_name = f"mem_{mem_node.id}"
                value_struct = mem_node.data.get('value', {})

                # Extract memory mappings (ILAng format: {'d': default, 'm': {addr: val, ...}})
                if isinstance(value_struct, dict) and 'm' in value_struct:
                    memory_map = value_struct['m']
                    default_val = value_struct.get('d', 0)

                    # Infer dimensions from the data
                    if memory_map:
                        # Get max address and max value to determine widths
                        max_addr = max((int(k) for k in memory_map.keys()), default=255)
                        max_val = max((int(v) for v in memory_map.values()), default=255)
                        max_val = max(max_val, default_val)  # Consider default value too

                        # Determine bit widths
                        addr_width = (max_addr).bit_length()
                        if addr_width == 0:
                            addr_width = 8
                        data_width = (max_val).bit_length()
                        if data_width == 0:
                            data_width = 8

                        lines.append(f"// Memory constant: {mem_node.id}")
                        lines.append(f"reg [{data_width-1}:0] {mem_name} [0:{max_addr}];")

            lines.append("")

            # Initialize memories
            lines.append("initial begin")
            for mem_node in mem_nodes:
                mem_name = f"mem_{mem_node.id}"
                value_struct = mem_node.data.get('value', {})

                if isinstance(value_struct, dict) and 'm' in value_struct:
                    memory_map = value_struct['m']
                    default_val = value_struct.get('d', 0)

                    lines.append(f"  // Initialize {mem_name}")
                    # Group initializations for readability
                    for addr_str, val in sorted(memory_map.items(), key=lambda x: int(x[0])):
                        addr = int(addr_str)
                        lines.append(f"  {mem_name}[{addr}] = {val};")

            lines.append("end")
            lines.append("")
        else:
            lines.append("// No memory constants found")
            lines.append("")

        # FSM state encoding
        if instructions:
            lines.append("// Instruction FSM states")
            lines.append("localparam")
            for i, instr in enumerate(instructions):
                name = instr.data.get('name', f'STATE_{i}')
                comma = "," if i < len(instructions) - 1 else ";"
                lines.append(f"  {name.upper()} = {i}{comma}")
            lines.append("")

            # FSM state register
            state_bits = (len(instructions) - 1).bit_length()
            if state_bits == 0:
                state_bits = 1
            lines.append(f"reg [{state_bits-1}:0] fsm_state;")
            lines.append("")

        # Main FSM logic
        lines.append("// Main FSM and state updates")
        lines.append("always @(posedge clk) begin")
        lines.append("  if (rst) begin")

        # Reset logic
        for state in isa_states:
            name = state.data.get('name')
            lines.append(f"    {name} <= 0;")

        if instructions:
            lines.append("    fsm_state <= 0;")

        lines.append("  end else begin")

        # State transition logic
        lines.append("    // State transitions would go here")
        lines.append("    // Each instruction would check its decode condition")
        lines.append("    // and update the appropriate state variables")

        # Generate state updates from graph structure (no JSON)
        print(f"   Generating {len(instructions)} instructions...")
        for instr in instructions:
                name = instr.data.get('name', 'unknown')
                print(f"     Processing {name} (ID: {instr.id})")
                lines.append(f"    ")
                lines.append(f"    // Instruction: {name}")

                # Find decode condition
                decode_edges = [e for e_id, e in self.graph.edges.items()
                               if e.target.id == instr.id and
                               isinstance(e.data, dict) and
                               e.data.get('type') == 'decode_condition']
                print(f"       Found {len(decode_edges)} decode edges")
                for de in decode_edges:
                    print(f"         Edge {de.id}: has parent_decode = {'parent_decode' in de.data}")

                if decode_edges:
                    decode_edge = decode_edges[0]
                    decode_node = decode_edge.source
                    decode_expr = self._generate_expression(decode_node)

                    # Check if this is a child instruction that needs parent gating
                    if isinstance(decode_edge.data, dict) and 'parent_decode' in decode_edge.data:
                        parent_decode_id = decode_edge.data['parent_decode']
                        print(f"      Found parent_decode={parent_decode_id} on instruction {name}")
                        if parent_decode_id in self.graph.nodes:
                            parent_decode_node = self.graph.nodes[parent_decode_id]
                            parent_decode_expr = self._generate_expression(parent_decode_node)
                            # AND child and parent decode conditions
                            decode_expr = f"({decode_expr}) && ({parent_decode_expr})"
                            print(f"      AND-ed with parent: {decode_expr[:100]}...")
                        else:
                            print(f"      WARNING: parent_decode node {parent_decode_id} not found in graph")

                    lines.append(f"    if ({decode_expr}) begin")

                    # Find states modified by this instruction
                    mod_edges = [e for e_id, e in self.graph.edges.items()
                                if e.source.id == instr.id and
                                isinstance(e.data, dict) and
                                e.data.get('type') == 'modifies']

                    # Generate child ILA input assignments (inline_arg edges)
                    # These connect parent function arguments to child ILA input states
                    # Only generate these if this is a parent instruction that calls a child ILA
                    inline_arg_edges = [e for e_id, e in self.graph.edges.items()
                                       if e_id.startswith('inline_arg')]

                    # Check if there's a 'round' counter being initialized by this instruction
                    # Define this before the is_parent check so it's in scope for later use
                    round_assign_edge = None
                    for e in self.graph.edges.values():
                        if (isinstance(e.data, dict) and
                            e.data.get('type') == 'assignment' and
                            e.data.get('instruction') == instr.id and
                            isinstance(e.target.data, dict) and
                            e.target.data.get('name') == 'round'):
                            round_assign_edge = e
                            break

                    if inline_arg_edges:
                        # Check if any child instruction has this instruction as parent
                        is_parent = any(
                            isinstance(e.data, dict) and
                            e.data.get('type') == 'decode_condition' and
                            e.data.get('parent_decode') == decode_node.id
                            for e in self.graph.edges.values()
                        )

                        if is_parent:
                            # Input initialization has been moved to START_ENCRYPT by the parser
                            # to avoid race conditions. No longer generate it here.
                            pass

                    # Get list of child input state names that are handled by inline_arg
                    child_input_names = set()
                    skip_round = False
                    if inline_arg_edges and is_parent:
                        child_input_names = {arg_edge.target.data.get('name') for arg_edge in inline_arg_edges
                                            if isinstance(arg_edge.target.data, dict)}
                        # Also skip round if it was handled conditionally above
                        if round_assign_edge:
                            skip_round = True

                    for mod_edge in mod_edges:
                        state_node = mod_edge.target
                        state_name = state_node.data.get('name', 'unknown')

                        # Skip child input states - they're handled by inline_arg assignments
                        if state_name in child_input_names:
                            continue

                        # Skip round counter if it was handled conditionally above
                        if skip_round and state_name == 'round':
                            continue

                        # Find the assignment edge for THIS instruction
                        # Assignment edges are tagged with 'instruction' field
                        assign_edges = [e for e_id, e in self.graph.edges.items()
                                       if e.target.id == state_node.id and
                                       isinstance(e.data, dict) and
                                       e.data.get('type') == 'assignment' and
                                       e.data.get('instruction') == instr.id]

                        if assign_edges:
                            update_node = assign_edges[0].source
                            # Skip memory writes - they're side effects, not state updates
                            if isinstance(update_node.data, dict) and update_node.data.get('type') == 'memory_write':
                                lines.append(f"      // {state_name} <= memory_write (skipped)")
                                continue
                            update_expr = self._generate_expression(update_node)
                            lines.append(f"      {state_name} <= {update_expr};")

                    lines.append("    end")

        lines.append("  end")
        lines.append("end")
        lines.append("")

        lines.append("endmodule")
        lines.append("")

        return "\n".join(lines)


def main():
    """Test the generator."""
    import sys
    import json
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from frontends.ila.ila_parser_real import RealILAParser

    # Get command line arguments
    if len(sys.argv) < 2:
        print("Usage: python ila_verilog_generator.py <input.json> [output.v] [module_name]")
        sys.exit(1)

    json_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else 'output.v'
    module_name = sys.argv[3] if len(sys.argv) > 3 else 'aes_module'

    # Parse JSON to resource graph
    parser = RealILAParser()
    with open(json_file) as f:
        data = json.load(f)

    graph = parser.parse_json(data)
    print(f"Parsed: {len(graph.nodes)} nodes, {len(graph.edges)} edges")

    # Generate Verilog from resource graph only (no JSON)
    generator = ILAVerilogGenerator(graph, module_name=module_name)
    verilog = generator.generate()

    # Write to file
    with open(output_file, 'w') as f:
        f.write(verilog)

    print(f"Generated Verilog: {output_file}")
    print(f"Lines: {verilog.count(chr(10))}")

    # Show preview
    print("\n" + "=" * 70)
    print(verilog[:1500])
    print("=" * 70)


if __name__ == '__main__':
    main()
