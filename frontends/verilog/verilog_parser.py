#!/usr/bin/env python3
"""
SystemVerilog parser using pyslang to extract resource graphs.

This module parses SystemVerilog code and converts it into ResourceGraph format,
looking for custom pragmas to identify architectural state.

Supported pragmas:
- (* arch_state *) - marks a signal/register as architectural state
"""

import sys
import os
from typing import Dict, List, Set, Optional, Any, Tuple
from core.resource_graph import ResourceGraph, Node, Edge

# Use pyslang from venv
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(_project_root, 'venv', 'lib', 'python3.12', 'site-packages'))
import pyslang


class VerilogParser:
    """Parser for SystemVerilog code using pyslang."""

    def __init__(self):
        self.arch_state_signals: Set[str] = set()
        self.module_name: Optional[str] = None
        self._is_top_level = False  # Track if processing top-level module
        self._instance_prefix_stack = []  # Stack of instance names for proper signal namespacing

    def _get_signal_prefix(self, signal_name: str) -> str:
        """
        Get the fully prefixed signal name based on current instance hierarchy.
        Top-level signals are not prefixed. Nested instance signals are prefixed with instance_name__.
        """
        if not self._instance_prefix_stack or self._is_top_level:
            return signal_name
        # Use double underscore to separate instance prefix from signal name
        return f"{'__'.join(self._instance_prefix_stack)}__{signal_name}"

    def parse_file(self, filename: str, top_module: Optional[str] = None) -> ResourceGraph:
        """
        Parse a SystemVerilog file and create a ResourceGraph.

        Args:
            filename: Path to the SystemVerilog file
            top_module: Optional name of the top module to use (if None, auto-detect)

        Returns:
            ResourceGraph representing the module
        """
        # Create compilation with optional top module specification
        tree = pyslang.SyntaxTree.fromFile(filename)
        if top_module:
            # Use CompilationOptions to specify the top module
            bag = pyslang.Bag()
            options = pyslang.CompilationOptions()
            options.topModules = {top_module}  # Must be a set
            bag.compilationOptions = options
            compilation = pyslang.Compilation(bag)
        else:
            compilation = pyslang.Compilation()
        compilation.addSyntaxTree(tree)

        # Check for compilation diagnostics
        diags = compilation.getAllDiagnostics()
        errors = [d for d in diags if d.isError()]
        if errors:
            print(f"[PARSER] WARNING: {len(errors)} compilation errors found")
            # TODO: Print error details properly
            # for err in errors[:5]:  # Show first 5
            #     print(f"  {err}")

        # Get the top-level module
        top_modules = list(compilation.getRoot().topInstances)
        if not top_modules:
            raise ValueError("No top-level modules found in file")

        top = top_modules[0]
        self.module_name = top.name

        # Create resource graph
        graph = ResourceGraph()

        # Track signal replacements for port conflicts
        # Maps external signal name to internal signal name
        self._signal_replacements = {}

        # First pass: identify architectural state from pragmas
        self._identify_arch_state_from_symbols(top.body)

        # Second pass: build the resource graph
        self._is_top_level = True  # Mark that we're processing the top-level module
        self._build_graph_from_module(top, graph, compilation)
        self._is_top_level = False  # Reset flag after top-level processing

        # Third pass: apply signal replacements from port conflicts
        self._apply_signal_replacements(graph)

        # Global cleanup: Remove intermediate mux assignments across all targets
        self._global_cleanup_intermediate_mux_assignments(graph)

        return graph

    def parse_text(self, verilog_text: str, module_name: str = "top") -> ResourceGraph:
        """
        Parse SystemVerilog text and create a ResourceGraph.

        Args:
            verilog_text: SystemVerilog source code
            module_name: Name for the module (used if not specified in code)

        Returns:
            ResourceGraph representing the module
        """
        # Create compilation from text
        tree = pyslang.SyntaxTree.fromText(verilog_text)
        compilation = pyslang.Compilation()
        compilation.addSyntaxTree(tree)

        # Get the top-level module
        top_modules = list(compilation.getRoot().topInstances)
        if not top_modules:
            raise ValueError("No top-level modules found in code")

        top = top_modules[0]
        self.module_name = top.name

        # Create resource graph
        graph = ResourceGraph()

        # Track signal replacements for port conflicts
        # Maps external signal name to internal signal name
        self._signal_replacements = {}

        # First pass: identify architectural state from pragmas
        self._identify_arch_state_from_symbols(top.body)

        # Second pass: build the resource graph
        self._is_top_level = True  # Mark that we're processing the top-level module
        self._build_graph_from_module(top, graph, compilation)
        self._is_top_level = False  # Reset flag after top-level processing

        # Third pass: apply signal replacements from port conflicts
        self._apply_signal_replacements(graph)

        # Global cleanup: Remove intermediate mux assignments across all targets
        self._global_cleanup_intermediate_mux_assignments(graph)

        return graph

    def _identify_arch_state_from_symbols(self, module_body) -> None:
        """
        Identify signals marked with (* arch_state *) pragma by examining symbols.

        Args:
            module_body: Module body instance to search
        """
        for member in module_body:
            # Check if this member has syntax with attributes
            if hasattr(member, 'syntax') and member.syntax:
                syntax = member.syntax

                # Attributes are on the parent DataDeclaration node
                if hasattr(syntax, 'parent'):
                    parent = syntax.parent
                    if hasattr(parent, 'attributes'):
                        attrs = list(parent.attributes)
                        for attr_instance in attrs:
                            # Each attribute instance has specs
                            if hasattr(attr_instance, 'specs'):
                                specs = list(attr_instance.specs)
                                for spec in specs:
                                    # Check the attribute name
                                    if hasattr(spec, 'name') and spec.name:
                                        attr_name = spec.name.valueText.strip()
                                        if attr_name == 'arch_state':
                                            # Mark this signal as architectural state
                                            self.arch_state_signals.add(member.name)

    def _build_graph_from_module(self, module_instance, graph: ResourceGraph, compilation) -> None:
        """
        Build the resource graph from a module instance.

        Args:
            module_instance: The module instance to process
            graph: ResourceGraph to populate
            compilation: Slang compilation object
        """
        # Get module definition
        module_def = module_instance.body

        # Process all members - module_def is iterable
        for member in module_def:
            member_kind = member.kind

            # Handle different member types
            if member_kind == pyslang.SymbolKind.Port:
                self._process_port(member, graph)
            elif member_kind == pyslang.SymbolKind.Variable:
                self._process_variable(member, graph)
            elif member_kind == pyslang.SymbolKind.Net:
                self._process_net(member, graph)
            elif member_kind == pyslang.SymbolKind.Parameter:
                self._process_parameter(member, graph)
            elif member_kind == pyslang.SymbolKind.Instance:
                # Recursively process instantiated modules
                self._process_instance(member, graph, compilation)
            elif member_kind == pyslang.SymbolKind.ContinuousAssign:
                self._process_continuous_assign(member, graph)
            elif member_kind == pyslang.SymbolKind.ProceduralBlock:
                print(f"    [DEBUG_PROC] Processing procedural block")
                self._process_procedural_block(member, graph)
            elif member_kind == pyslang.SymbolKind.GenerateBlock:
                # Process generate block members (slang has already elaborated to the active branch)
                print(f"  [PARSER] Processing generate block '{member.name if hasattr(member, 'name') else '<unnamed>'}' in top module")
                self._process_generate_block(member, graph, compilation)

    def _process_port(self, port_symbol, graph: ResourceGraph) -> None:
        """
        Process a port declaration.

        Args:
            port_symbol: Port symbol from slang
            graph: ResourceGraph to add/update nodes
        """
        # Only mark ports for the top-level module
        # When inlining instances, their ports become internal wires
        if not self._is_top_level:
            return

        port_name = port_symbol.name

        # Get port direction
        direction_map = {
            'In': 'input',
            'Out': 'output',
            'InOut': 'inout'
        }
        direction_str = str(port_symbol.direction).split('.')[-1]  # Get 'In', 'Out', or 'InOut'
        port_direction = direction_map.get(direction_str, 'input')

        # Check if node already exists (from Net/Variable processing)
        if port_name in graph.nodes:
            # Update existing node to mark it as a port
            node = graph.nodes[port_name]
            node.data['is_port'] = True
            node.data['port_direction'] = port_direction
            print(f"    - SymbolKind.Port: {port_name} ({port_direction}) - updated existing node")
        else:
            # Port not yet processed - it will be handled when we process its Net/Variable
            # Store port info for later
            if not hasattr(self, '_port_info'):
                self._port_info = {}
            self._port_info[port_name] = {
                'is_port': True,
                'port_direction': port_direction
            }
            print(f"    - SymbolKind.Port: {port_name} ({port_direction}) - stored for later")

    def _process_parameter(self, param_symbol, graph: ResourceGraph) -> None:
        """
        Process a parameter declaration.

        Args:
            param_symbol: Parameter symbol from slang
            graph: ResourceGraph to add nodes to
        """
        param_name = param_symbol.name

        # Check if parameter already exists in graph
        if param_name in graph.nodes:
            return

        # Create parameter node
        param_data = {
            'type': 'parameter',
            'name': param_name,
            'display_name': param_name
        }

        # Get the parameter's width from pyslang's type information
        try:
            if hasattr(param_symbol, 'type') and param_symbol.type is not None:
                if hasattr(param_symbol.type, 'bitWidth'):
                    param_data['width'] = param_symbol.type.bitWidth
        except Exception as e:
            print(f"[PARAM] {param_name}: error getting width: {e}")

        # Try to get the parameter's value
        try:
            if hasattr(param_symbol, 'value') and param_symbol.value is not None:
                # value is a ConstantValue
                if hasattr(param_symbol.value, 'convertToInt'):
                    int_val = param_symbol.value.convertToInt()
                    param_data['value'] = str(int_val)
                    param_data['verilog_value'] = str(int_val)
                else:
                    param_data['value'] = str(param_symbol.value)
                    param_data['verilog_value'] = str(param_symbol.value)
        except Exception as e:
            print(f"[PARAM] {param_name}: error getting value: {e}")

        param_node = Node(param_name, param_data)
        graph.add_node(param_node)
        print(f"[PARAM] Created parameter node: {param_name} = {param_data.get('value', 'unknown')} (width={param_data.get('width', 'unknown')})")

    def _process_variable(self, var_symbol, graph: ResourceGraph) -> None:
        """
        Process a variable declaration.

        Args:
            var_symbol: Variable symbol from slang
            graph: ResourceGraph to add nodes to
        """
        var_name = var_symbol.name
        # Get prefixed name for proper signal namespacing across instances
        prefixed_name = self._get_signal_prefix(var_name)

        # Get the type - use declaredType property
        var_type = var_symbol.declaredType

        # Get bit range (width, msb, lsb)
        bit_width, msb, lsb = self._get_bit_range(var_type)

        # Debug output for specific variables
        if var_name in ('o_cnt', 'rdata0', 'rdata1', 'data', 'o_rd'):
            print(f"[PARSE_VAR_DEBUG] {var_name} → {prefixed_name}: width={bit_width}, msb={msb}, lsb={lsb}, type={var_type}")

        # Check if this is architectural state
        is_arch = var_name in self.arch_state_signals

        # Create node with prefixed name as ID, but keep original name in data
        node_data = {
            'type': 'isa_state' if is_arch else 'var',
            'name': prefixed_name,  # Use prefixed name
            'original_name': var_name,  # Keep original for debugging
            'display_name': var_name,
            'bit_width': bit_width,
            'verilog_type': str(var_type)
        }

        # Store MSB/LSB for non-zero-based ranges
        if msb is not None and lsb is not None:
            node_data['bit_msb'] = msb
            node_data['bit_lsb'] = lsb
            print(f"[PARSE_VAR_DEBUG] Stored MSB/LSB for {var_name}: [{msb}:{lsb}]")

        # Check if this is an unpacked array (e.g., reg [31:0] regfile [0:31])
        # Check if var_type has array dimensions using pyslang API
        import re

        # Check if the declared type is an unpacked array
        # Access the actual type through var_type.type
        actual_type = var_type.type if hasattr(var_type, 'type') else var_type

        # Check if it's an unpacked array
        if hasattr(actual_type, 'isUnpackedArray') and actual_type.isUnpackedArray:
            # Use pyslang's elaborated range values instead of parsing string representation
            # This ensures we get the actual elaborated parameter values (e.g., WITH_CSR=0, RF_WIDTH=32)
            # rather than the default symbolic expressions
            if hasattr(actual_type, 'range'):
                r = actual_type.range
                node_data['is_array'] = True
                node_data['array_left'] = r.left
                node_data['array_right'] = r.right
                node_data['array_depth'] = abs(r.left - r.right) + 1

        # CRITICAL FIX: Don't replace existing nodes - this breaks edges!
        # When inlining modules, ports may already exist as wires/variables in parent module
        if prefixed_name in graph.nodes:
            existing_node = graph.nodes[prefixed_name]
            existing_width = existing_node.data.get('bit_width', 1)

            # Update if variable declaration has more accurate width info than net declaration
            # This happens when pyslang creates a net with type 'logic' (width=1) but the
            # actual reg declaration has the correct parametrized width
            if bit_width > existing_width:
                existing_node.data['bit_width'] = bit_width
                if msb is not None and lsb is not None:
                    existing_node.data['bit_msb'] = msb
                    existing_node.data['bit_lsb'] = lsb
                print(f"[NODE_UPDATE] Updated {prefixed_name} (original: {var_name}) width from {existing_width} to {bit_width}, msb={msb}, lsb={lsb}")
            elif var_name in ('rdata0', 'rdata1', 'o_rdata0', 'o_cnt', 'data', 'o_rd'):
                print(f"[NODE_EXISTS_DEBUG] {prefixed_name} (original: {var_name}) already exists with bit_width={existing_width}, type={existing_node.data.get('type')}, not updating (new width={bit_width})")
            return

        # Apply stored port info if available (using original name for lookup)
        # Port info describes the signal's role in its defining module context
        # This is needed for proper handling in expressions, not just declarations
        if hasattr(self, '_port_info') and var_name in self._port_info:
            node_data.update(self._port_info[var_name])
            print(f"    - Variable {var_name}: applied port info ({self._port_info[var_name].get('port_direction')})")

        # Create new variable node with prefixed name
        node = Node(prefixed_name, node_data, is_arch_state=is_arch, from_isa_spec=True)
        graph.add_node(node)

    def _process_net(self, net_symbol, graph: ResourceGraph) -> None:
        """
        Process a net (wire) declaration.

        Handles inline assignments like: wire [31:0] rs1_value = !insn_rs1 ? 0 : regfile[insn_rs1];
        These are split into a wire declaration and a separate assign statement.

        Args:
            net_symbol: Net symbol from slang
            graph: ResourceGraph to add nodes to
        """
        net_name = net_symbol.name
        # Get prefixed name for proper signal namespacing across instances
        prefixed_name = self._get_signal_prefix(net_name)

        # Get the type - NetSymbol is a ValueSymbol, so use .type
        net_type = net_symbol.type

        # Get bit range (width, msb, lsb)
        bit_width, msb, lsb = self._get_bit_range(net_type)

        # Debug output for specific nets
        if net_name in ('o_cnt', 'rdata0', 'rdata1', 'o_rdata0', 'o_rd'):
            print(f"[PARSE_NET_DEBUG] {net_name} → {prefixed_name}: width={bit_width}, msb={msb}, lsb={lsb}, type={net_type}")

        # Check if this is architectural state
        is_arch = net_name in self.arch_state_signals

        # Create node with prefixed name as ID, but keep original name in data
        node_data = {
            'type': 'isa_state' if is_arch else 'var',
            'name': prefixed_name,  # Use prefixed name
            'original_name': net_name,  # Keep original for debugging
            'display_name': net_name,
            'bit_width': bit_width,
            'verilog_type': str(net_type)
        }

        # Store MSB/LSB for non-zero-based ranges
        if msb is not None and lsb is not None:
            node_data['bit_msb'] = msb
            node_data['bit_lsb'] = lsb
            print(f"[PARSE_NET_DEBUG] Stored MSB/LSB for {prefixed_name}: [{msb}:{lsb}]")

        # Apply stored port info if available (using original name for lookup)
        # Port info describes the signal's role in its defining module context
        # This is needed for proper handling in expressions, not just declarations
        if hasattr(self, '_port_info') and net_name in self._port_info:
            node_data.update(self._port_info[net_name])
            print(f"    - Net {net_name}: applied port info ({self._port_info[net_name].get('port_direction')})")

        # CRITICAL FIX: Don't replace existing nodes - this breaks edges!
        # When inlining modules, ports may already exist as variables in parent module
        if prefixed_name in graph.nodes:
            # Node already exists - use it instead of creating a new one
            node = graph.nodes[prefixed_name]
        else:
            # Create new wire node with prefixed name
            node = Node(prefixed_name, node_data, is_arch_state=is_arch, from_isa_spec=True)
            graph.add_node(node)

        # Check for inline initializer (e.g., wire [31:0] x = expr;)
        # NetSymbol has an 'initializer' property that holds the semantic expression
        if hasattr(net_symbol, 'initializer') and net_symbol.initializer is not None:
            print(f"  [PARSER] Found inline initializer for wire {net_name}, creating assignment edge")

            # Parse using semantic expression parser
            source_node = self._expression_to_node(net_symbol.initializer, graph)

            if source_node:
                # Create a continuous assignment edge (like an assign statement)
                edge_data = {
                    'type': 'assignment',
                    'assign_type': 'continuous',  # Inline wire init is continuous assignment
                }
                edge = Edge(source_node, node, data=edge_data)
                graph.add_edge(edge)
                print(f"  [PARSER] Created continuous assignment edge: {source_node.id[:60]} -> {prefixed_name}")
            else:
                print(f"  [PARSER] WARNING: Failed to parse initializer for {net_name}")

    def _parse_syntax_tree_expression(self, expr_syntax, graph: ResourceGraph, context_symbol) -> Optional[Node]:
        """
        Parse a syntax tree expression and create graph nodes.

        Args:
            expr_syntax: Syntax expression node from pyslang
            graph: ResourceGraph to add nodes to
            context_symbol: The symbol providing context (for looking up names in scope)

        Returns:
            Node representing the expression, or None if parsing failed
        """
        from pyslang import SyntaxKind

        syntax_kind = expr_syntax.kind

        # Identifier reference (e.g., insn_rs1, regfile)
        if syntax_kind == SyntaxKind.IdentifierName:
            ident_name = expr_syntax.identifier.valueText
            # Use prefixed name to find the actual node
            prefixed_name = self._get_signal_prefix(ident_name)
            if prefixed_name in graph.nodes:
                return graph.nodes[prefixed_name]
            else:
                # Create a reference node with prefixed name
                ref_node = Node(prefixed_name, data={'type': 'var', 'name': prefixed_name, 'original_name': ident_name, 'display_name': ident_name})
                graph.add_node(ref_node)
                return ref_node

        # Literal value (e.g., 0, 32'h0)
        elif syntax_kind == SyntaxKind.IntegerLiteralExpression:
            lit_text = expr_syntax.literal.valueText
            # Skip don't-care literals ('hx, 'bx, 'bz, 'hz, 'b1x0z, etc.)
            # These are simulation-only values and should not create nodes
            if lit_text and ("x" in lit_text.lower() or "z" in lit_text.lower()):
                print(f"    [PARSER] Skipping don't-care literal: {lit_text}")
                return None
            node_id = f"const_{lit_text}"
            if node_id in graph.nodes:
                return graph.nodes[node_id]
            lit_node = Node(node_id, data={'type': 'literal', 'value': lit_text})
            graph.add_node(lit_node)
            return lit_node

        # Integer vector expression (e.g., 'hx, 'bz)
        elif syntax_kind == SyntaxKind.IntegerVectorExpression:
            # Get the text representation
            lit_text = expr_syntax.toString() if hasattr(expr_syntax, 'toString') else str(expr_syntax)
            lit_text = lit_text.strip()
            # Skip don't-care literals ('hx, 'bx, 'bz, 'hz, 32'hxxxxxxxx, etc.)
            if lit_text and lit_text.startswith("'") and ("x" in lit_text.lower() or "z" in lit_text.lower()):
                print(f"    [PARSER] Skipping don't-care vector literal: {lit_text}")
                return None
            # If it's a real vector literal (no x or z), create a node
            node_id = f"const_{lit_text}"
            if node_id in graph.nodes:
                return graph.nodes[node_id]
            lit_node = Node(node_id, data={'type': 'literal', 'value': lit_text})
            graph.add_node(lit_node)
            return lit_node

        # Conditional expression (ternary operator): cond ? true_val : false_val
        elif syntax_kind == SyntaxKind.ConditionalExpression:
            # Parse components
            # In syntax tree, the condition is in 'predicate.conditions'
            if hasattr(expr_syntax, 'predicate') and expr_syntax.predicate:
                # The predicate is a ConditionalPredicateSyntax with a 'conditions' list
                predicates = expr_syntax.predicate.conditions
                if predicates and len(predicates) > 0:
                    # Each condition has an 'expr' property
                    cond_node = self._parse_syntax_tree_expression(predicates[0].expr, graph, context_symbol)
                else:
                    cond_node = None
            else:
                cond_node = None

            true_node = self._parse_syntax_tree_expression(expr_syntax.left, graph, context_symbol)
            false_node = self._parse_syntax_tree_expression(expr_syntax.right, graph, context_symbol)

            # Create a mux node
            from core.mux_utils import MuxBuilder, MuxType
            cond_name = cond_node.id if cond_node else "?"
            true_name = true_node.id if true_node else "?"
            false_name = false_node.id if false_node else "?"
            mux_id = f"ternary_mux_{cond_name}_{true_name}_{false_name}"[:200]  # Limit length

            if mux_id in graph.nodes:
                return graph.nodes[mux_id]

            builder = MuxBuilder(graph, mux_id, MuxType.PRIORITY)
            builder.create_or_get_mux(display_name=f"{cond_name} ? {true_name} : {false_name}")

            # Add inputs with the condition node as selector
            # For ternary: cond ? true_val : false_val
            # true_val is selected when cond is true (non-zero)
            # false_val is selected when cond is false (zero)
            if true_node and cond_node:
                builder.add_input(true_node, cond_node)  # Selected when cond != 0
            if false_node:
                # For false case, use string selector since there's no "!cond" node
                builder.add_input(false_node, "default")  # Default/fallback case

            return graph.nodes.get(mux_id)

        # Element select (array indexing): array[index]
        elif syntax_kind == SyntaxKind.ElementSelectExpression:
            array_node = self._parse_syntax_tree_expression(expr_syntax.left, graph, context_symbol)
            index_node = self._parse_syntax_tree_expression(expr_syntax.selector.selectors[0].expr, graph, context_symbol)

            array_name = array_node.id if array_node else "?"
            index_name = index_node.id if index_node else "?"
            node_id = f"{array_name}[{index_name}]"

            if node_id in graph.nodes:
                return graph.nodes[node_id]

            access_node = Node(node_id, data={
                'type': 'array_access',
                'display_name': node_id,
                'array': array_name,
                'index': index_name
            })
            graph.add_node(access_node)

            if array_node:
                edge = Edge(array_node, access_node, data={'type': 'array_base'})
                graph.add_edge(edge)
            if index_node:
                edge = Edge(index_node, access_node, data={'type': 'array_index'})
                graph.add_edge(edge)

            return access_node

        # Unary expressions (e.g., !insn_rs1, ~x, -y)
        elif 'Unary' in str(syntax_kind):
            # Try to get operator token
            if hasattr(expr_syntax, 'operatorToken'):
                op_text = expr_syntax.operatorToken.valueText
            else:
                # Extract operator from syntax kind name
                kind_name = str(syntax_kind).split('.')[-1]
                op_text = kind_name.replace('Unary', '').replace('Expression', '')

            # Get operand
            if hasattr(expr_syntax, 'operand'):
                operand_node = self._parse_syntax_tree_expression(expr_syntax.operand, graph, context_symbol)
            else:
                operand_node = None

            operand_name = operand_node.id if operand_node else "?"
            node_id = f"({op_text} {operand_name})"

            if node_id in graph.nodes:
                return graph.nodes[node_id]

            # Create unary operation node with width info from pyslang if available
            op_data = {
                'type': 'operation',
                'operator': op_text,
                'unary': True,
                'display_name': node_id
            }

            # Try to get bit width from expression type
            if hasattr(expr_syntax, 'type') and expr_syntax.type is not None:
                try:
                    if hasattr(expr_syntax.type, 'bitWidth'):
                        width = expr_syntax.type.bitWidth
                        # Don't trust pyslang width for bitwise ops - let generator infer
                        if op_text not in ['BinaryOr', 'BinaryAnd', 'BinaryXor', 'BitwiseOr', 'BitwiseAnd', 'BitwiseXor']:
                            op_data['bit_width'] = width
                    elif hasattr(expr_syntax.type, 'width'):
                        op_data['bit_width'] = expr_syntax.type.width
                except Exception as e:
                    pass  # Width not available, will infer later

            op_node = Node(node_id, data=op_data)
            graph.add_node(op_node)

            if operand_node:
                edge = Edge(operand_node, op_node, data={'type': 'operand'})
                graph.add_edge(edge)

            return op_node

        # Cast expression (e.g., $signed(imm_i))
        elif syntax_kind == SyntaxKind.CastExpression:
            # For $signed() casts, create a separate node to preserve signedness
            # This is important because signed and unsigned operations produce different results
            if hasattr(expr_syntax, 'right'):
                operand_node = self._parse_syntax_tree_expression(expr_syntax.right, graph, context_symbol)
                if operand_node:
                    # Check if this is a $signed() cast
                    is_signed_cast = False
                    if hasattr(expr_syntax, 'left'):
                        cast_text = expr_syntax.left.toString() if hasattr(expr_syntax.left, 'toString') else str(expr_syntax.left)
                        is_signed_cast = 'signed' in cast_text.lower()

                    # If it's a $signed() cast, create a new node to mark it as signed
                    if is_signed_cast:
                        signed_node_id = f"$signed({operand_node.id})"
                        if signed_node_id in graph.nodes:
                            return graph.nodes[signed_node_id]

                        signed_node = Node(signed_node_id, data={
                            'type': 'cast',
                            'cast_type': 'signed',
                            'display_name': signed_node_id
                        })
                        graph.add_node(signed_node)
                        edge = Edge(operand_node, signed_node, data={'type': 'operand'})
                        graph.add_edge(edge)
                        return signed_node
                    else:
                        # For other casts, just follow through to the operand
                        return operand_node
                return operand_node
            return None

        # Binary expressions (e.g., pc + 4, rs1_value & mask)
        elif hasattr(expr_syntax, 'left') and hasattr(expr_syntax, 'right'):
            # Parse left and right operands
            left_node = self._parse_syntax_tree_expression(expr_syntax.left, graph, context_symbol)
            right_node = self._parse_syntax_tree_expression(expr_syntax.right, graph, context_symbol)

            # Get operator
            if hasattr(expr_syntax, 'operatorToken'):
                op_text = expr_syntax.operatorToken.valueText
            else:
                # Extract from syntax kind
                kind_name = str(syntax_kind).split('.')[-1].replace('Expression', '')
                op_text = '+'  # fallback

            # Create operation node
            left_name = left_node.id if left_node else "?"
            right_name = right_node.id if right_node else "?"
            node_id = f"{left_name} {op_text} {right_name}"

            if node_id in graph.nodes:
                return graph.nodes[node_id]

            # Create operation node with width info from pyslang if available
            op_data = {
                'type': 'operation',
                'operator': op_text,
                'display_name': node_id
            }

            # Try to get bit width from expression type
            if hasattr(expr_syntax, 'type') and expr_syntax.type is not None:
                try:
                    if hasattr(expr_syntax.type, 'bitWidth'):
                        width = expr_syntax.type.bitWidth
                        # Don't trust pyslang width for bitwise ops - let generator infer
                        if op_text not in ['BinaryOr', 'BinaryAnd', 'BinaryXor', 'BitwiseOr', 'BitwiseAnd', 'BitwiseXor']:
                            op_data['bit_width'] = width
                    elif hasattr(expr_syntax.type, 'width'):
                        op_data['bit_width'] = expr_syntax.type.width
                except Exception as e:
                    pass  # Width not available, will infer later

            op_node = Node(node_id, data=op_data)
            graph.add_node(op_node)

            # Create edges from operands to operation
            if left_node:
                edge = Edge(left_node, op_node, data={'type': 'left_operand', 'position': 'left'})
                graph.add_edge(edge)
            if right_node:
                edge = Edge(right_node, op_node, data={'type': 'right_operand', 'position': 'right'})
                graph.add_edge(edge)

            return op_node

        else:
            # Unsupported syntax kind - try to convert to text and create expression node
            expr_text = expr_syntax.toString() if hasattr(expr_syntax, 'toString') else str(expr_syntax)
            # Skip don't-care literals ('hx, 'bx, 'bz, etc.)
            if expr_text and expr_text.startswith("'") and ("x" in expr_text.lower() or "z" in expr_text.lower()):
                print(f"    [PARSER] Skipping don't-care literal (fallthrough): {expr_text}")
                return None
            node_id = expr_text[:100]
            if node_id in graph.nodes:
                return graph.nodes[node_id]
            expr_node = Node(node_id, data={'type': 'expression', 'expr': expr_text})
            graph.add_node(expr_node)
            return expr_node

    def _parse_syntax_tree_expression_with_versioning(self, expr_syntax, graph: ResourceGraph, context_symbol, target_node, assignment_context):
        """
        Parse a syntax tree expression, replacing references to target_node with versioned intermediate nodes if needed.

        This handles cases like:
            npc = pc + imm_j_sext;
            npc = npc & ~32'b11;  // Second assignment reads from npc - use npc_v0 instead

        Args:
            expr_syntax: Syntax expression node from pyslang
            graph: ResourceGraph to add nodes to
            context_symbol: The symbol providing context
            target_node: The target node being assigned (e.g., npc)
            assignment_context: Dict tracking previous assignments

        Returns:
            Node representing the expression
        """
        # First, parse the expression normally
        result_node = self._parse_syntax_tree_expression(expr_syntax, graph, context_symbol)

        if not result_node or not target_node:
            return result_node

        # Check if this expression references the target node
        # If so, and if there have been previous assignments to target, we need to create
        # an intermediate versioned node
        if target_node.id in assignment_context and len(assignment_context[target_node.id]) > 0:
            # Check if result_node or any of its dependencies reference target_node
            if self._expression_references_node(result_node, target_node):
                # Create a versioned intermediate node representing the value of target after the last assignment
                version = len(assignment_context[target_node.id]) - 1
                intermediate_id = f"{target_node.id}_v{version}"

                print(f"      [PARSER] Expression references {target_node.id}, creating intermediate node {intermediate_id}")

                # Check if we already created this intermediate node
                if intermediate_id not in graph.nodes:
                    # Get the source node from the last assignment
                    last_version, last_source = assignment_context[target_node.id][-1]

                    # Create intermediate node
                    intermediate_node = Node(intermediate_id, data={
                        'type': target_node.data.get('type', 'var'),
                        'name': intermediate_id,
                        'display_name': intermediate_id,
                        'bit_width': target_node.data.get('bit_width', 32),
                        'is_intermediate_version': True,
                        'original_node': target_node.id,
                        'version': version
                    })
                    graph.add_node(intermediate_node)

                    # Create edge from last source to intermediate node
                    edge_data = {'type': 'assignment', 'assign_type': 'blocking'}
                    edge = Edge(last_source, intermediate_node, data=edge_data)
                    graph.add_edge(edge)

                    print(f"      [PARSER] Created versioned intermediate: {last_source.id[:30]} -> {intermediate_id}")

                # Now replace references to target_node in result_node's dependency tree with intermediate_node
                intermediate_node = graph.nodes[intermediate_id]
                self._replace_node_references(result_node, target_node, intermediate_node, graph, visited=set())

        return result_node

    def _expression_references_node(self, expr_node: Node, target_node: Node, visited=None) -> bool:
        """
        Check if expr_node or any of its dependencies reference target_node.

        Args:
            expr_node: The expression node to check
            target_node: The target node we're looking for
            visited: Set of visited nodes to avoid cycles

        Returns:
            True if expr_node references target_node
        """
        if visited is None:
            visited = set()

        if expr_node.id in visited:
            return False
        visited.add(expr_node.id)

        # Direct reference
        if expr_node.id == target_node.id:
            return True

        # Check if the node ID/expression contains the target name
        # This catches cases like bit-slices or concatenations: {mem_wr_addr[31:2], 2'b00}
        if target_node.id in expr_node.id:
            # Make sure it's a word boundary match (not a substring of another identifier)
            import re
            pattern = rf'\b{re.escape(target_node.id)}\b'
            if re.search(pattern, expr_node.id):
                return True

        # Check incoming edges (operands, etc.)
        for edge in expr_node.incoming_edges:
            if edge.source.id == target_node.id:
                return True
            # Recursively check source dependencies
            if self._expression_references_node(edge.source, target_node, visited):
                return True

        return False

    def _replace_node_references(self, root_node: Node, old_node: Node, new_node: Node, graph: ResourceGraph, visited=None):
        """
        Replace all references to old_node with new_node in the dependency tree of root_node.

        Args:
            root_node: Root of the tree to process
            old_node: Node to replace
            new_node: Replacement node
            graph: ResourceGraph
            visited: Set of visited nodes to avoid cycles
        """
        if visited is None:
            visited = set()

        if root_node.id in visited:
            return
        visited.add(root_node.id)

        # Replace edges that reference old_node
        edges_to_update = []
        for edge in list(root_node.incoming_edges):
            if edge.source.id == old_node.id:
                edges_to_update.append(edge)
            else:
                # Recursively process source
                self._replace_node_references(edge.source, old_node, new_node, graph, visited)

        # Update edges
        for edge in edges_to_update:
            # Remove old edge
            old_node.outgoing_edges.discard(edge)
            root_node.incoming_edges.discard(edge)

            # Create new edge from new_node
            new_edge = Edge(new_node, edge.target, data=edge.data.copy())
            graph.add_edge(new_edge)
            print(f"      [PARSER] Replaced edge: {old_node.id[:30]} -> {new_node.id[:30]} in {root_node.id[:30]}")

    def _process_instance(self, instance_symbol, graph: ResourceGraph, compilation) -> None:
        """
        Process a module instance by recursively inlining its logic.

        Args:
            instance_symbol: Instance symbol from slang
            graph: ResourceGraph to add nodes/edges to
            compilation: Slang compilation object
        """
        instance_name = instance_symbol.name
        module_name = instance_symbol.definition.name
        print(f"  [PARSER] Inlining instance '{instance_name}' of module '{module_name}'")

        # Push instance name onto the prefix stack to namespace all internal signals
        self._instance_prefix_stack.append(instance_name)
        was_top_level = self._is_top_level
        self._is_top_level = False  # We're now inside an instance, not at top level

        # First, identify arch_state signals within this instance
        self._identify_arch_state_from_symbols(instance_symbol.body)

        # Recursively process all members of the instantiated module
        # This effectively "flattens" the hierarchy by inlining the instance's logic

        # Debug: Print all member kinds for serv_synth_wrapper and serv_top
        if 'serv_synth_wrapper' in module_name or 'serv_top' in module_name:
            print(f"  [DEBUG] Members of {module_name} instance '{instance_name}':")
            for member in instance_symbol.body:
                member_name = member.name if hasattr(member, 'name') else '<unnamed>'
                print(f"    - {member.kind}: {member_name}")

        for member in instance_symbol.body:
            member_kind = member.kind

            # Debug: Check if this member is inside a generate block
            if hasattr(member, 'getParentScope') and member.getParentScope():
                parent_scope = member.getParentScope()
                if hasattr(parent_scope, 'name') and ('gen_' in parent_scope.name or 'generate' in parent_scope.name.lower()):
                    print(f"    [GENERATE_DEBUG] Processing member {member.name if hasattr(member, 'name') else member_kind} from generate block '{parent_scope.name}'")

            if member_kind == pyslang.SymbolKind.Variable:
                self._process_variable(member, graph)
            elif member_kind == pyslang.SymbolKind.Net:
                self._process_net(member, graph)
            elif member_kind == pyslang.SymbolKind.Instance:
                # Recursively process nested instances
                self._process_instance(member, graph, compilation)
            elif member_kind == pyslang.SymbolKind.ContinuousAssign:
                self._process_continuous_assign(member, graph)
            elif member_kind == pyslang.SymbolKind.ProceduralBlock:
                print(f"    [DEBUG_PROC] Processing procedural block")
                self._process_procedural_block(member, graph)
            elif member_kind == pyslang.SymbolKind.GenerateBlock:
                # Process generate block members (slang has already elaborated to the active branch)
                print(f"  [PARSER] Processing generate block '{member.name if hasattr(member, 'name') else '<unnamed>'}'")
                self._process_generate_block(member, graph, compilation)

        # After inlining the module body, create assignments for port connections
        # This connects the module's internal signals to the instance's external wires
        self._process_port_connections(instance_symbol, graph)

        # Pop instance name from the prefix stack and restore top_level flag
        self._instance_prefix_stack.pop()
        self._is_top_level = was_top_level

    def _process_generate_block(self, generate_block, graph: ResourceGraph, compilation) -> None:
        """
        Process a generate block by recursively processing its members.

        Slang elaborates all generate blocks, but marks inactive branches with isUninstantiated.
        We need to check this flag and skip uninstantiated (inactive) branches.

        Args:
            generate_block: GenerateBlock symbol from slang
            graph: ResourceGraph to add nodes/edges to
            compilation: Slang compilation object
        """
        # Skip uninstantiated (inactive) generate blocks
        # Slang provides all branches but marks inactive ones with isUninstantiated=True
        if hasattr(generate_block, 'isUninstantiated') and generate_block.isUninstantiated:
            block_name = generate_block.name if hasattr(generate_block, 'name') else '<unnamed>'
            print(f"  [PARSER] Skipping uninstantiated generate block '{block_name}'")
            return

        # Recursively process all members of the generate block
        # Try iterating over the generate block directly
        # (GenerateBlockSymbol might be iterable)
        try:
            members = list(generate_block)
        except TypeError:
            print(f"  [PARSER] WARNING: Cannot iterate over GenerateBlock '{generate_block.name if hasattr(generate_block, 'name') else '<unnamed>'}'")
            print(f"  [PARSER] Available attributes: {[a for a in dir(generate_block) if not a.startswith('_')]}")
            return

        for member in members:
            member_kind = member.kind

            if member_kind == pyslang.SymbolKind.Variable:
                self._process_variable(member, graph)
            elif member_kind == pyslang.SymbolKind.Net:
                self._process_net(member, graph)
            elif member_kind == pyslang.SymbolKind.Instance:
                self._process_instance(member, graph, compilation)
            elif member_kind == pyslang.SymbolKind.ContinuousAssign:
                self._process_continuous_assign(member, graph)
            elif member_kind == pyslang.SymbolKind.ProceduralBlock:
                print(f"    [DEBUG_PROC] Processing procedural block")
                self._process_procedural_block(member, graph)
            elif member_kind == pyslang.SymbolKind.GenerateBlock:
                # Nested generate block - process recursively
                self._process_generate_block(member, graph, compilation)

    def _process_port_connections(self, instance_symbol, graph: ResourceGraph) -> None:
        """
        Create assignment edges for module instance port connections.

        When a module is inlined, we need to connect the module's internal port signals
        to the external wires at the instance site.

        For example, given:
            module_inst inst(.o_bus(ibus_cyc), .i_clk(clk));

        After inlining, we need:
            assign ibus_cyc = inst__o_bus;  // output port (prefixed)
            assign inst__i_clk = clk;        // input port (prefixed)

        Args:
            instance_symbol: Instance symbol with portConnections
            graph: ResourceGraph to add assignment edges to
        """
        instance_name = instance_symbol.name
        print(f"  [PORT_CONNECTIONS] Processing {len(instance_symbol.portConnections)} port connections for instance {instance_name}")

        for port_conn in instance_symbol.portConnections:
            port = port_conn.port
            expr = port_conn.expression

            # Get the internal port signal name for debug
            port_name_debug = port.internalSymbol.name if port.internalSymbol else port.name
            if 'wb_rdt' in port_name_debug or 'ctrl_misalign' in port_name_debug or 'alu_rd_sel' in port_name_debug:
                print(f"    [PORT_CONN_DEBUG] Found port connection: {port_name_debug}, expr.kind={expr.kind if expr else None}")

            # Skip unconnected ports
            if expr is None:
                continue

            # Get the internal port signal name (inside the module)
            internal_signal_orig = port.internalSymbol.name if port.internalSymbol else port.name
            # Use the full prefix from the stack for the internal signal
            # The internal signal was created with the full prefix during member processing
            internal_signal = self._get_signal_prefix(internal_signal_orig)

            # Create or get the internal signal node
            if internal_signal not in graph.nodes:
                # Create a node for the internal signal if it doesn't exist
                # Extract bit range from the port's type
                node_data = {'type': 'net', 'name': internal_signal, 'original_name': internal_signal_orig}
                if port.internalSymbol and hasattr(port.internalSymbol, 'type'):
                    port_type = port.internalSymbol.type
                    bit_width, msb, lsb = self._get_bit_range(port_type)
                    node_data['bit_width'] = bit_width
                    if msb is not None and lsb is not None:
                        node_data['bit_msb'] = msb
                        node_data['bit_lsb'] = lsb
                        print(f"    [PORT_NODE] Created {internal_signal} with bit range [{msb}:{lsb}]")
                internal_node = Node(internal_signal, data=node_data)
                graph.add_node(internal_node)
            else:
                internal_node = graph.nodes[internal_signal]

            # Handle different port directions
            if port.direction == pyslang.ArgumentDirection.Out:
                # Output port: module drives external wire
                # Expression is an Assignment with left=external wire, right=internal signal
                if expr.kind == pyslang.ExpressionKind.Assignment:
                    # Get external wire from left side of assignment
                    if hasattr(expr.left, 'symbol') and expr.left.symbol:
                        external_signal_orig = expr.left.symbol.name

                        # External signal is from parent module's scope
                        # Need to use parent's prefix (all instances except current one)
                        if self._instance_prefix_stack and len(self._instance_prefix_stack) > 1:
                            # Parent is also an instance - use parent prefix
                            parent_prefix = '__'.join(self._instance_prefix_stack[:-1])
                            external_signal = f"{parent_prefix}__{external_signal_orig}"
                        else:
                            # Parent is top-level (stack has 0 or 1 elements) - no prefix
                            external_signal = external_signal_orig

                        # Skip self-assignments (when port name matches external wire name)
                        if external_signal == internal_signal:
                            continue

                        # Create or get external wire node
                        if external_signal not in graph.nodes:
                            external_node = Node(external_signal, data={'type': 'net', 'name': external_signal})
                            graph.add_node(external_node)
                        else:
                            external_node = graph.nodes[external_signal]

                        # Check if this edge already exists
                        edge_exists = any(
                            e.source.id == internal_node.id and e.target.id == external_node.id
                            for e in graph.edges.values()
                        )

                        # Check if reverse edge exists (would create a cycle)
                        reverse_edge_exists = any(
                            e.source.id == external_node.id and e.target.id == internal_node.id
                            for e in graph.edges.values()
                        )

                        # Check if external signal already has a driver (is a register)
                        # This happens when the external wire has the same name as an internal register
                        external_has_driver = any(
                            e.target.id == external_node.id and
                            ('conditional_mux' in e.source.id or 'ternary_mux' in e.source.id)
                            for e in graph.edges.values()
                        )

                        if reverse_edge_exists:
                            print(f"    [PORT] Skipping output port connection {internal_signal} → {external_signal} (would create cycle with existing edge {external_signal} → {internal_signal})")
                        elif external_has_driver:
                            print(f"    [PORT] Skipping output port connection {internal_signal} → {external_signal} (external signal is already a register)")
                            # Record that references to external_signal should be replaced with internal_signal
                            self._signal_replacements[external_signal] = internal_signal
                            print(f"    [PORT] Recording signal replacement: {external_signal} → {internal_signal}")

                            # Propagate bit_width and range info from external to internal
                            if external_signal in graph.nodes and internal_signal in graph.nodes:
                                external_node = graph.nodes[external_signal]
                                internal_node = graph.nodes[internal_signal]
                                if external_signal == 'rdata0' or internal_signal == 'rdata0':
                                    print(f"    [PORT_DEBUG_RDATA0] external={external_signal}, internal={internal_signal}")
                                    print(f"    [PORT_DEBUG_RDATA0] external.bit_width={external_node.data.get('bit_width')}, internal.bit_width={internal_node.data.get('bit_width')}")
                                # Always overwrite internal bit_width with external (external is the source of truth)
                                if 'bit_width' in external_node.data:
                                    internal_node.data['bit_width'] = external_node.data['bit_width']
                                    print(f"    [PORT] Propagated bit_width={external_node.data['bit_width']} from {external_signal} to {internal_signal}")
                                if 'bit_msb' in external_node.data and 'bit_lsb' in external_node.data:
                                    internal_node.data['bit_msb'] = external_node.data['bit_msb']
                                    internal_node.data['bit_lsb'] = external_node.data['bit_lsb']
                                    print(f"    [PORT] Propagated bit range [{external_node.data['bit_msb']}:{external_node.data['bit_lsb']}] from {external_signal} to {internal_signal}")
                        elif not edge_exists:
                            # Create assignment: assign external = internal
                            edge_data = {'type': 'assignment', 'assign_type': 'continuous'}
                            edge = Edge(internal_node, external_node, data=edge_data)
                            graph.add_edge(edge)
                            print(f"    [PORT] Output: assign {external_signal} = {internal_signal};")
                            if 'ibus_ack' in external_signal or 'ibus_ack' in internal_signal:
                                print(f"    [PORT_DEBUG_IBUS_ACK] Output port connection: {internal_signal} → {external_signal} (instance: {instance_name})")

            elif port.direction == pyslang.ArgumentDirection.In or port.direction == pyslang.ArgumentDirection.InOut:
                # Input port: external wire drives module signal
                if 'ext_ready' in internal_signal or 'timer_irq' in internal_signal:
                    print(f"    [PORT_DEBUG] Processing input port {internal_signal}, expr.kind={expr.kind}")
                if expr.kind == pyslang.ExpressionKind.NamedValue:
                    if hasattr(expr, 'symbol') and expr.symbol:
                        external_signal_orig = expr.symbol.name

                        # External signal is from parent module's scope
                        # Need to use parent's prefix (all instances except current one)
                        if self._instance_prefix_stack and len(self._instance_prefix_stack) > 1:
                            # Parent is also an instance - use parent prefix
                            parent_prefix = '__'.join(self._instance_prefix_stack[:-1])
                            external_signal = f"{parent_prefix}__{external_signal_orig}"
                        else:
                            # Parent is top-level (stack has 0 or 1 elements) - no prefix
                            external_signal = external_signal_orig

                        # Skip self-assignments (when port name matches external wire name)
                        if external_signal == internal_signal:
                            continue

                        # Create or get external wire node
                        if external_signal not in graph.nodes:
                            external_node = Node(external_signal, data={'type': 'net', 'name': external_signal})
                            graph.add_node(external_node)
                        else:
                            external_node = graph.nodes[external_signal]

                        # Check if this edge already exists
                        edge_exists = any(
                            e.source.id == external_node.id and e.target.id == internal_node.id
                            for e in graph.edges.values()
                        )

                        # Check if reverse edge exists (would create a cycle)
                        reverse_edge_exists = any(
                            e.source.id == internal_node.id and e.target.id == external_node.id
                            for e in graph.edges.values()
                        )

                        if reverse_edge_exists:
                            print(f"    [PORT] Skipping input port connection {external_signal} → {internal_signal} (would create cycle with existing edge {internal_signal} → {external_signal})")
                        elif not edge_exists:
                            # Create assignment: assign internal = external
                            edge_data = {'type': 'assignment', 'assign_type': 'continuous'}
                            edge = Edge(external_node, internal_node, data=edge_data)
                            graph.add_edge(edge)
                            print(f"    [PORT] Input: assign {internal_signal} = {external_signal};")
                            if 'ibus_ack' in external_signal or 'ibus_ack' in internal_signal:
                                print(f"    [PORT_DEBUG_IBUS_ACK] Input port connection: {external_signal} → {internal_signal} (instance: {instance_name})")

                elif expr.kind in [pyslang.ExpressionKind.IntegerLiteral, pyslang.ExpressionKind.UnbasedUnsizedIntegerLiteral, pyslang.ExpressionKind.Conversion]:
                    # Input port connected to a constant literal or conversion (e.g., .i_ext_ready(1'b0))
                    # Conversion expressions wrap constants when type conversion is needed
                    # Create a constant node and connect it to the internal signal
                    const_value = self._expression_to_node(expr, graph)
                    if const_value:
                        # Check if edge already exists
                        edge_exists = any(
                            e.source.id == const_value.id and e.target.id == internal_node.id
                            for e in graph.edges.values()
                        )
                        if not edge_exists:
                            edge_data = {'type': 'assignment', 'assign_type': 'continuous'}
                            edge = Edge(const_value, internal_node, data=edge_data)
                            graph.add_edge(edge)
                            print(f"    [PORT] Input (constant): assign {internal_signal} = {const_value.id};")

                elif expr.kind in [pyslang.ExpressionKind.RangeSelect, pyslang.ExpressionKind.ElementSelect]:
                    # Input port connected to a bit selection or range (e.g., .i_wb_rdt(signal[31:2]) or .i_bit(signal[5]))
                    # Need to handle scope carefully - the base signal is from parent scope
                    # Temporarily pop the current instance from stack to parse parent scope expression
                    current_instance = self._instance_prefix_stack.pop() if self._instance_prefix_stack else None
                    try:
                        selection_node = self._expression_to_node(expr, graph)
                        if selection_node:
                            # Check if edge already exists
                            edge_exists = any(
                                e.source.id == selection_node.id and e.target.id == internal_node.id
                                for e in graph.edges.values()
                            )
                            if not edge_exists:
                                edge_data = {'type': 'assignment', 'assign_type': 'continuous'}
                                edge = Edge(selection_node, internal_node, data=edge_data)
                                graph.add_edge(edge)
                                print(f"    [PORT] Input (selection): assign {internal_signal} = {selection_node.id};")
                    finally:
                        # Restore the instance prefix stack
                        if current_instance:
                            self._instance_prefix_stack.append(current_instance)

                else:
                    # Unknown expression kind for input port
                    if 'ext_ready' in internal_signal or 'timer_irq' in internal_signal or 'wb_rdt' in internal_signal or 'misalign' in internal_signal:
                        print(f"    [PORT_DEBUG] Unhandled input port expression kind for {internal_signal}: {expr.kind}")

    def _parse_syntax_tree_expression(self, expr_syntax, graph: ResourceGraph, context_symbol) -> Optional[Node]:
        """
        Parse a syntax tree expression and create graph nodes.

        Args:
            expr_syntax: Syntax expression node from pyslang
            graph: ResourceGraph to add nodes to
            context_symbol: The symbol providing context (for looking up names in scope)

        Returns:
            Node representing the expression, or None if parsing failed
        """
        from pyslang import SyntaxKind

        syntax_kind = expr_syntax.kind

        # Identifier reference (e.g., insn_rs1, regfile)
        if syntax_kind == SyntaxKind.IdentifierName:
            ident_name = expr_syntax.identifier.valueText
            # Use prefixed name to find the actual node
            prefixed_name = self._get_signal_prefix(ident_name)
            if prefixed_name in graph.nodes:
                return graph.nodes[prefixed_name]
            else:
                # Create a reference node with prefixed name
                ref_node = Node(prefixed_name, data={'type': 'var', 'name': prefixed_name, 'original_name': ident_name, 'display_name': ident_name})
                graph.add_node(ref_node)
                return ref_node

        # Literal value (e.g., 0, 32'h0)
        elif syntax_kind == SyntaxKind.IntegerLiteralExpression:
            lit_text = expr_syntax.literal.valueText
            # Skip don't-care literals ('hx, 'bx, 'bz, 'hz, 'b1x0z, etc.)
            # These are simulation-only values and should not create nodes
            if lit_text and ("x" in lit_text.lower() or "z" in lit_text.lower()):
                print(f"    [PARSER] Skipping don't-care literal: {lit_text}")
                return None
            node_id = f"const_{lit_text}"
            if node_id in graph.nodes:
                return graph.nodes[node_id]
            lit_node = Node(node_id, data={'type': 'literal', 'value': lit_text})
            graph.add_node(lit_node)
            return lit_node

        # Integer vector expression (e.g., 'hx, 'bz)
        elif syntax_kind == SyntaxKind.IntegerVectorExpression:
            # Get the text representation
            lit_text = expr_syntax.toString() if hasattr(expr_syntax, 'toString') else str(expr_syntax)
            lit_text = lit_text.strip()
            # Skip don't-care literals ('hx, 'bx, 'bz, 'hz, 32'hxxxxxxxx, etc.)
            if lit_text and lit_text.startswith("'") and ("x" in lit_text.lower() or "z" in lit_text.lower()):
                print(f"    [PARSER] Skipping don't-care vector literal: {lit_text}")
                return None
            # If it's a real vector literal (no x or z), create a node
            node_id = f"const_{lit_text}"
            if node_id in graph.nodes:
                return graph.nodes[node_id]
            lit_node = Node(node_id, data={'type': 'literal', 'value': lit_text})
            graph.add_node(lit_node)
            return lit_node

        # Conditional expression (ternary operator): cond ? true_val : false_val
        elif syntax_kind == SyntaxKind.ConditionalExpression:
            # Parse components
            # In syntax tree, the condition is in 'predicate.conditions'
            if hasattr(expr_syntax, 'predicate') and expr_syntax.predicate:
                # The predicate is a ConditionalPredicateSyntax with a 'conditions' list
                predicates = expr_syntax.predicate.conditions
                if predicates and len(predicates) > 0:
                    # Each condition has an 'expr' property
                    cond_node = self._parse_syntax_tree_expression(predicates[0].expr, graph, context_symbol)
                else:
                    cond_node = None
            else:
                cond_node = None

            true_node = self._parse_syntax_tree_expression(expr_syntax.left, graph, context_symbol)
            false_node = self._parse_syntax_tree_expression(expr_syntax.right, graph, context_symbol)

            # Create a mux node
            from core.mux_utils import MuxBuilder, MuxType
            cond_name = cond_node.id if cond_node else "?"
            true_name = true_node.id if true_node else "?"
            false_name = false_node.id if false_node else "?"
            mux_id = f"ternary_mux_{cond_name}_{true_name}_{false_name}"[:200]  # Limit length

            if mux_id in graph.nodes:
                return graph.nodes[mux_id]

            builder = MuxBuilder(graph, mux_id, MuxType.PRIORITY)
            builder.create_or_get_mux(display_name=f"{cond_name} ? {true_name} : {false_name}")

            # Add inputs with the condition node as selector
            # For ternary: cond ? true_val : false_val
            # true_val is selected when cond is true (non-zero)
            # false_val is selected when cond is false (zero)
            if true_node and cond_node:
                builder.add_input(true_node, cond_node)  # Selected when cond != 0
            if false_node:
                # For false case, use string selector since there's no "!cond" node
                builder.add_input(false_node, "default")  # Default/fallback case

            return graph.nodes.get(mux_id)

        # Element select (array indexing): array[index]
        elif syntax_kind == SyntaxKind.ElementSelectExpression:
            array_node = self._parse_syntax_tree_expression(expr_syntax.left, graph, context_symbol)
            index_node = self._parse_syntax_tree_expression(expr_syntax.selector.selectors[0].expr, graph, context_symbol)

            array_name = array_node.id if array_node else "?"
            index_name = index_node.id if index_node else "?"
            node_id = f"{array_name}[{index_name}]"

            if node_id in graph.nodes:
                return graph.nodes[node_id]

            access_node = Node(node_id, data={
                'type': 'array_access',
                'display_name': node_id,
                'array': array_name,
                'index': index_name
            })
            graph.add_node(access_node)

            if array_node:
                edge = Edge(array_node, access_node, data={'type': 'array_base'})
                graph.add_edge(edge)
            if index_node:
                edge = Edge(index_node, access_node, data={'type': 'array_index'})
                graph.add_edge(edge)

            return access_node

        # Unary expressions (e.g., !insn_rs1, ~x, -y)
        elif 'Unary' in str(syntax_kind):
            # Try to get operator token
            if hasattr(expr_syntax, 'operatorToken'):
                op_text = expr_syntax.operatorToken.valueText
            else:
                # Extract operator from syntax kind name
                kind_name = str(syntax_kind).split('.')[-1]
                op_text = kind_name.replace('Unary', '').replace('Expression', '')

            # Get operand
            if hasattr(expr_syntax, 'operand'):
                operand_node = self._parse_syntax_tree_expression(expr_syntax.operand, graph, context_symbol)
            else:
                operand_node = None

            operand_name = operand_node.id if operand_node else "?"
            node_id = f"({op_text} {operand_name})"

            if node_id in graph.nodes:
                return graph.nodes[node_id]

            # Create unary operation node with width info from pyslang if available
            op_data = {
                'type': 'operation',
                'operator': op_text,
                'unary': True,
                'display_name': node_id
            }

            # Try to get bit width from expression type
            if hasattr(expr_syntax, 'type') and expr_syntax.type is not None:
                try:
                    if hasattr(expr_syntax.type, 'bitWidth'):
                        width = expr_syntax.type.bitWidth
                        # Don't trust pyslang width for bitwise ops - let generator infer
                        if op_text not in ['BinaryOr', 'BinaryAnd', 'BinaryXor', 'BitwiseOr', 'BitwiseAnd', 'BitwiseXor']:
                            op_data['bit_width'] = width
                    elif hasattr(expr_syntax.type, 'width'):
                        op_data['bit_width'] = expr_syntax.type.width
                except Exception as e:
                    pass  # Width not available, will infer later

            op_node = Node(node_id, data=op_data)
            graph.add_node(op_node)

            if operand_node:
                edge = Edge(operand_node, op_node, data={'type': 'operand'})
                graph.add_edge(edge)

            return op_node

        # Cast expression (e.g., $signed(imm_i))
        elif syntax_kind == SyntaxKind.CastExpression:
            # For $signed() casts, create a separate node to preserve signedness
            # This is important because signed and unsigned operations produce different results
            if hasattr(expr_syntax, 'right'):
                operand_node = self._parse_syntax_tree_expression(expr_syntax.right, graph, context_symbol)
                if operand_node:
                    # Check if this is a $signed() cast
                    is_signed_cast = False
                    if hasattr(expr_syntax, 'left'):
                        cast_text = expr_syntax.left.toString() if hasattr(expr_syntax.left, 'toString') else str(expr_syntax.left)
                        is_signed_cast = 'signed' in cast_text.lower()

                    # If it's a $signed() cast, create a new node to mark it as signed
                    if is_signed_cast:
                        signed_node_id = f"$signed({operand_node.id})"
                        if signed_node_id in graph.nodes:
                            return graph.nodes[signed_node_id]

                        signed_node = Node(signed_node_id, data={
                            'type': 'cast',
                            'cast_type': 'signed',
                            'display_name': signed_node_id
                        })
                        graph.add_node(signed_node)
                        edge = Edge(operand_node, signed_node, data={'type': 'operand'})
                        graph.add_edge(edge)
                        return signed_node
                    else:
                        # For other casts, just follow through to the operand
                        return operand_node
                return operand_node
            return None

        # Binary expressions (e.g., pc + 4, rs1_value & mask)
        elif hasattr(expr_syntax, 'left') and hasattr(expr_syntax, 'right'):
            # Parse left and right operands
            left_node = self._parse_syntax_tree_expression(expr_syntax.left, graph, context_symbol)
            right_node = self._parse_syntax_tree_expression(expr_syntax.right, graph, context_symbol)

            # Get operator
            if hasattr(expr_syntax, 'operatorToken'):
                op_text = expr_syntax.operatorToken.valueText
            else:
                # Extract from syntax kind
                kind_name = str(syntax_kind).split('.')[-1].replace('Expression', '')
                op_text = '+'  # fallback

            # Create operation node
            left_name = left_node.id if left_node else "?"
            right_name = right_node.id if right_node else "?"
            node_id = f"{left_name} {op_text} {right_name}"

            if node_id in graph.nodes:
                return graph.nodes[node_id]

            # Create operation node with width info from pyslang if available
            op_data = {
                'type': 'operation',
                'operator': op_text,
                'display_name': node_id
            }

            # Try to get bit width from expression type
            if hasattr(expr_syntax, 'type') and expr_syntax.type is not None:
                try:
                    if hasattr(expr_syntax.type, 'bitWidth'):
                        width = expr_syntax.type.bitWidth
                        # Don't trust pyslang width for bitwise ops - let generator infer
                        if op_text not in ['BinaryOr', 'BinaryAnd', 'BinaryXor', 'BitwiseOr', 'BitwiseAnd', 'BitwiseXor']:
                            op_data['bit_width'] = width
                    elif hasattr(expr_syntax.type, 'width'):
                        op_data['bit_width'] = expr_syntax.type.width
                except Exception as e:
                    pass  # Width not available, will infer later

            op_node = Node(node_id, data=op_data)
            graph.add_node(op_node)

            # Create edges from operands to operation
            if left_node:
                edge = Edge(left_node, op_node, data={'type': 'left_operand', 'position': 'left'})
                graph.add_edge(edge)
            if right_node:
                edge = Edge(right_node, op_node, data={'type': 'right_operand', 'position': 'right'})
                graph.add_edge(edge)

            return op_node

        else:
            # Unsupported syntax kind - try to convert to text and create expression node
            expr_text = expr_syntax.toString() if hasattr(expr_syntax, 'toString') else str(expr_syntax)
            # Skip don't-care literals ('hx, 'bx, 'bz, etc.)
            if expr_text and expr_text.startswith("'") and ("x" in expr_text.lower() or "z" in expr_text.lower()):
                print(f"    [PARSER] Skipping don't-care literal (fallthrough): {expr_text}")
                return None
            node_id = expr_text[:100]
            if node_id in graph.nodes:
                return graph.nodes[node_id]
            expr_node = Node(node_id, data={'type': 'expression', 'expr': expr_text})
            graph.add_node(expr_node)
            return expr_node

    def _parse_syntax_tree_expression_with_versioning(self, expr_syntax, graph: ResourceGraph, context_symbol, target_node, assignment_context):
        """
        Parse a syntax tree expression, replacing references to target_node with versioned intermediate nodes if needed.

        This handles cases like:
            npc = pc + imm_j_sext;
            npc = npc & ~32'b11;  // Second assignment reads from npc - use npc_v0 instead

        Args:
            expr_syntax: Syntax expression node from pyslang
            graph: ResourceGraph to add nodes to
            context_symbol: The symbol providing context
            target_node: The target node being assigned (e.g., npc)
            assignment_context: Dict tracking previous assignments

        Returns:
            Node representing the expression
        """
        # First, parse the expression normally
        result_node = self._parse_syntax_tree_expression(expr_syntax, graph, context_symbol)

        if not result_node or not target_node:
            return result_node

        # Check if this expression references the target node
        # If so, and if there have been previous assignments to target, we need to create
        # an intermediate versioned node
        if target_node.id in assignment_context and len(assignment_context[target_node.id]) > 0:
            # Check if result_node or any of its dependencies reference target_node
            if self._expression_references_node(result_node, target_node):
                # Create a versioned intermediate node representing the value of target after the last assignment
                version = len(assignment_context[target_node.id]) - 1
                intermediate_id = f"{target_node.id}_v{version}"

                print(f"      [PARSER] Expression references {target_node.id}, creating intermediate node {intermediate_id}")

                # Check if we already created this intermediate node
                if intermediate_id not in graph.nodes:
                    # Get the source node from the last assignment
                    last_version, last_source = assignment_context[target_node.id][-1]

                    # Create intermediate node
                    intermediate_node = Node(intermediate_id, data={
                        'type': target_node.data.get('type', 'var'),
                        'name': intermediate_id,
                        'display_name': intermediate_id,
                        'bit_width': target_node.data.get('bit_width', 32),
                        'is_intermediate_version': True,
                        'original_node': target_node.id,
                        'version': version
                    })
                    graph.add_node(intermediate_node)

                    # Create edge from last source to intermediate node
                    edge_data = {'type': 'assignment', 'assign_type': 'blocking'}
                    edge = Edge(last_source, intermediate_node, data=edge_data)
                    graph.add_edge(edge)

                    print(f"      [PARSER] Created versioned intermediate: {last_source.id[:30]} -> {intermediate_id}")

                # Now replace references to target_node in result_node's dependency tree with intermediate_node
                intermediate_node = graph.nodes[intermediate_id]
                self._replace_node_references(result_node, target_node, intermediate_node, graph, visited=set())

        return result_node

    def _expression_references_node(self, expr_node: Node, target_node: Node, visited=None) -> bool:
        """
        Check if expr_node or any of its dependencies reference target_node.

        Args:
            expr_node: The expression node to check
            target_node: The target node we're looking for
            visited: Set of visited nodes to avoid cycles

        Returns:
            True if expr_node references target_node
        """
        if visited is None:
            visited = set()

        if expr_node.id in visited:
            return False
        visited.add(expr_node.id)

        # Direct reference
        if expr_node.id == target_node.id:
            return True

        # Check if the node ID/expression contains the target name
        # This catches cases like bit-slices or concatenations: {mem_wr_addr[31:2], 2'b00}
        if target_node.id in expr_node.id:
            # Make sure it's a word boundary match (not a substring of another identifier)
            import re
            pattern = rf'\b{re.escape(target_node.id)}\b'
            if re.search(pattern, expr_node.id):
                return True

        # Check incoming edges (operands, etc.)
        for edge in expr_node.incoming_edges:
            if edge.source.id == target_node.id:
                return True
            # Recursively check source dependencies
            if self._expression_references_node(edge.source, target_node, visited):
                return True

        return False

    def _replace_node_references(self, root_node: Node, old_node: Node, new_node: Node, graph: ResourceGraph, visited=None):
        """
        Replace all references to old_node with new_node in the dependency tree of root_node.

        Args:
            root_node: Root of the tree to process
            old_node: Node to replace
            new_node: Replacement node
            graph: ResourceGraph
            visited: Set of visited nodes to avoid cycles
        """
        if visited is None:
            visited = set()

        if root_node.id in visited:
            return
        visited.add(root_node.id)

        # Replace edges that reference old_node
        edges_to_update = []
        for edge in list(root_node.incoming_edges):
            if edge.source.id == old_node.id:
                edges_to_update.append(edge)
            else:
                # Recursively process source
                self._replace_node_references(edge.source, old_node, new_node, graph, visited)

        # Update edges
        for edge in edges_to_update:
            # Remove old edge
            old_node.outgoing_edges.discard(edge)
            root_node.incoming_edges.discard(edge)

            # Create new edge from new_node
            new_edge = Edge(new_node, edge.target, data=edge.data.copy())
            graph.add_edge(new_edge)
            print(f"      [PARSER] Replaced edge: {old_node.id[:30]} -> {new_node.id[:30]} in {root_node.id[:30]}")

    def _process_continuous_assign(self, assign_symbol, graph: ResourceGraph) -> None:
        """
        Process a continuous assignment (assign statement).

        Args:
            assign_symbol: Assignment symbol from slang
            graph: ResourceGraph to add edges to
        """
        # Get assignment expression - use .assignment property
        assignment = assign_symbol.assignment

        # Check if assignment is valid
        if not hasattr(assignment, 'left') or not hasattr(assignment, 'right'):
            print(f"  [PARSER] WARNING: Skipping invalid assignment (type={type(assignment)})")
            return

        # Parse left side (target) and right side (source)
        target_node = self._expression_to_node(assignment.left, graph)
        source_node = self._expression_to_node(assignment.right, graph)

        # Debug for co_two_stage_op
        if target_node and 'co_two_stage_op' in target_node.id:
            print(f"  [DEBUG_ASSIGN] Processing continuous assign to {target_node.id}, source={source_node.id if source_node else 'None'}")

        # Debug output for ibus_ack and wb_ibus signals
        if target_node and source_node:
            if 'ibus_ack' in target_node.id or 'ibus_ack' in source_node.id or 'wb_ibus' in target_node.id or 'wb_ibus' in source_node.id:
                print(f"    [ASSIGN_DEBUG] assign {target_node.id} = {source_node.id};")
            if 'pc_plus_offset_aligned' in target_node.id or 'pc_plus_offset_aligned' in source_node.id:
                print(f"    [ASSIGN_DEBUG_PC] assign {target_node.id} = {source_node.id};")

        # Debug for assignments that fail to create an edge
        if target_node is None or source_node is None:
            # Get target name for logging
            try:
                left_str = str(assignment.left)
            except:
                left_str = "unknown"
            # Only log first 20 failures to avoid spam
            if not hasattr(self, '_assign_fail_count'):
                self._assign_fail_count = 0
            if self._assign_fail_count < 20:
                print(f"    [ASSIGN_SKIP] target={left_str[:60]}, target_node={'None' if target_node is None else 'OK'}, source_node={'None' if source_node is None else 'OK'}")
                self._assign_fail_count += 1

        # Create edge from source to target
        if target_node and source_node:
            edge_data = {'type': 'assignment', 'assign_type': 'continuous'}
            edge = Edge(source_node, target_node, data=edge_data)
            graph.add_edge(edge)

    def _detect_byte_enable_pattern(self, stmt_list, graph: ResourceGraph, depth=0) -> set:
        """
        Detect byte enable patterns in a statement list and mark the arrays with metadata.

        Pattern: Multiple consecutive conditionals that write to byte slices of an arch_state array.
        Example:
            if (wstrb[0]) mem[addr][7:0] <= data[7:0];
            if (wstrb[1]) mem[addr][15:8] <= data[15:8];
            ...

        Returns:
            Set of indices in stmt_list that are part of byte enable patterns
        """
        indent = "  " * depth
        processed_indices = set()

        # Group consecutive conditionals
        i = 0
        while i < len(stmt_list):
            stmt = stmt_list[i]

            # Check if this is a conditional statement
            if stmt.kind != pyslang.StatementKind.Conditional:
                i += 1
                continue

            # Start collecting a group of conditionals
            conditional_group = []
            j = i
            while j < len(stmt_list) and stmt_list[j].kind == pyslang.StatementKind.Conditional:
                conditional_group.append((j, stmt_list[j]))
                j += 1

            # If we have multiple consecutive conditionals, check for byte enable pattern
            if len(conditional_group) >= 2:
                print(f"{indent}[BYTE_ENABLE] Found {len(conditional_group)} consecutive conditionals, checking pattern...")
                if self._process_byte_enable_group(conditional_group, graph, depth):
                    # Mark these indices as processed
                    for idx, _ in conditional_group:
                        processed_indices.add(idx)
                    print(f"{indent}[BYTE_ENABLE] Detected and processed byte enable pattern covering indices {[idx for idx, _ in conditional_group]}")

            i = j

        return processed_indices

    def _process_byte_enable_group(self, conditional_group, graph: ResourceGraph, depth=0) -> bool:
        """
        Check if a group of conditionals represents a byte enable pattern and process it.

        Returns:
            True if this is a valid byte enable pattern that was processed
        """
        indent = "  " * depth

        # Extract pattern information from each conditional
        byte_lane_info = []
        for idx, cond_stmt in conditional_group:
            info = self._extract_byte_lane_info(cond_stmt, graph)
            if info:
                byte_lane_info.append((idx, info))

        if not byte_lane_info:
            return False

        # Check if all write to the same array with same address
        if len(byte_lane_info) < 2:
            return False

        # Get the first entry as reference
        _, first_info = byte_lane_info[0]
        array_name = first_info.get('array')
        address_expr = first_info.get('address')

        # Check if array is marked arch_state
        if array_name not in graph.nodes:
            return False

        array_node = graph.nodes[array_name]
        if not array_node.is_arch_state:
            print(f"{indent}[BYTE_ENABLE] Array {array_name} is not arch_state, skipping")
            return False

        # Verify all lanes write to same array and address
        for _, info in byte_lane_info:
            if info.get('array') != array_name or info.get('address') != address_expr:
                return False

        # Extract byte lane information
        lanes = []
        for _, info in byte_lane_info:
            lane_low = info.get('bit_slice_low')
            lane_high = info.get('bit_slice_high')
            if lane_low is not None and lane_high is not None:
                lanes.append({
                    'low': lane_low,
                    'high': lane_high,
                    'width': lane_high - lane_low + 1,
                    'enable': info.get('enable_signal'),
                    'data': info.get('data_expr')
                })

        # Check if lanes are byte-aligned and consecutive
        lanes.sort(key=lambda x: x['low'])
        for lane in lanes:
            if lane['low'] % 8 != 0 or lane['width'] != 8:
                print(f"{indent}[BYTE_ENABLE] Lane {lane['low']}:{lane['high']} is not byte-aligned, skipping")
                return False

        # Verify consecutive
        for i in range(len(lanes) - 1):
            if lanes[i]['high'] + 1 != lanes[i+1]['low']:
                print(f"{indent}[BYTE_ENABLE] Lanes are not consecutive, skipping")
                return False

        # This is a valid byte enable pattern!
        print(f"{indent}[BYTE_ENABLE] Valid pattern: {len(lanes)} byte lanes for array {array_name}")
        print(f"{indent}[BYTE_ENABLE]   Lanes: {[(l['low'], l['high']) for l in lanes]}")

        # Mark the array node with byte enable metadata
        if 'byte_enables' not in array_node.data:
            array_node.data['byte_enables'] = []

        # Create the pattern dict
        pattern = {
            'num_lanes': len(lanes),
            'lane_width': 8,
            'total_width': lanes[-1]['high'] + 1,
            'address': address_expr,
            'lanes': lanes
        }

        # Check if this exact pattern already exists (avoid duplicates from nested conditionals)
        for existing_pattern in array_node.data['byte_enables']:
            if (existing_pattern['address'] == pattern['address'] and
                existing_pattern['num_lanes'] == pattern['num_lanes'] and
                existing_pattern['total_width'] == pattern['total_width']):
                print(f"{indent}[BYTE_ENABLE] Pattern already exists for {array_name}, skipping duplicate")
                return True

        array_node.data['byte_enables'].append(pattern)

        return True

    def _extract_byte_lane_info(self, cond_stmt, graph: ResourceGraph) -> Optional[dict]:
        """
        Extract byte lane information from a conditional statement.

        Pattern: if (enable[N]) array[addr][high:low] <= data[high:low];

        Returns:
            Dict with array, address, bit_slice_low, bit_slice_high, enable_signal, data_expr
            or None if pattern doesn't match
        """
        # Get condition expression (should be element select like wstrb[0])
        if not hasattr(cond_stmt, 'conditions') or not cond_stmt.conditions:
            return None

        condition_expr = cond_stmt.conditions[0].expr

        # Get the if-true statement (should be assignment to array bit slice)
        if not hasattr(cond_stmt, 'ifTrue'):
            return None

        true_stmt = cond_stmt.ifTrue

        # Handle block statement wrapping
        if true_stmt.kind == pyslang.StatementKind.Block:
            true_stmt = true_stmt.body

        # Should be an expression statement with assignment
        if true_stmt.kind != pyslang.StatementKind.ExpressionStatement:
            return None

        if not hasattr(true_stmt, 'expr') or true_stmt.expr.kind != pyslang.ExpressionKind.Assignment:
            return None

        assign_expr = true_stmt.expr

        # Left side: should be RangeSelect of ElementSelect (array[addr][high:low])
        # Right side: data expression
        left_expr = assign_expr.left
        right_expr = assign_expr.right

        # Check if left is a RangeSelect
        if left_expr.kind != pyslang.ExpressionKind.RangeSelect:
            return None

        # Get the value being selected from (should be ElementSelect - array[addr])
        if not hasattr(left_expr, 'value'):
            return None

        elem_select = left_expr.value
        if elem_select.kind != pyslang.ExpressionKind.ElementSelect:
            return None

        # Get array and address
        if not hasattr(elem_select, 'value') or not hasattr(elem_select, 'selector'):
            return None

        array_expr = elem_select.value
        addr_expr = elem_select.selector

        # Array should be a simple name reference
        if array_expr.kind != pyslang.ExpressionKind.NamedValue:
            return None

        if not hasattr(array_expr, 'symbol') or not hasattr(array_expr.symbol, 'name'):
            return None

        array_name = array_expr.symbol.name

        # Get bit slice range
        if not hasattr(left_expr, 'left') or not hasattr(left_expr, 'right'):
            return None

        # Extract constant values for bit range
        left_val = self._extract_constant_value(left_expr.left)
        right_val = self._extract_constant_value(left_expr.right)

        if left_val is None or right_val is None:
            return None

        bit_slice_high = max(left_val, right_val)
        bit_slice_low = min(left_val, right_val)

        # Convert address expression to string representation for matching
        addr_str = self._expr_to_string(addr_expr)

        return {
            'array': array_name,
            'address': addr_str,
            'bit_slice_low': bit_slice_low,
            'bit_slice_high': bit_slice_high,
            'enable_signal': self._expr_to_string(condition_expr),
            'data_expr': self._expr_to_string(right_expr)
        }

    def _extract_constant_value(self, expr) -> Optional[int]:
        """Extract a constant integer value from an expression."""
        if expr.kind == pyslang.ExpressionKind.IntegerLiteral:
            if hasattr(expr, 'value'):
                return int(expr.value)
        return None

    def _expr_to_string(self, expr) -> str:
        """Convert an expression to a string representation."""
        # This is a simplified version - may need to be extended
        if expr.kind == pyslang.ExpressionKind.NamedValue:
            if hasattr(expr, 'symbol') and hasattr(expr.symbol, 'name'):
                return expr.symbol.name
        elif expr.kind == pyslang.ExpressionKind.ElementSelect:
            if hasattr(expr, 'value') and hasattr(expr, 'selector'):
                base = self._expr_to_string(expr.value)
                index = self._expr_to_string(expr.selector)
                return f"{base}[{index}]"
        elif expr.kind == pyslang.ExpressionKind.RangeSelect:
            if hasattr(expr, 'value') and hasattr(expr, 'left') and hasattr(expr, 'right'):
                base = self._expr_to_string(expr.value)
                left = self._extract_constant_value(expr.left)
                right = self._extract_constant_value(expr.right)
                if left is not None and right is not None:
                    return f"{base}[{left}:{right}]"
        elif expr.kind == pyslang.ExpressionKind.IntegerLiteral:
            if hasattr(expr, 'value'):
                return str(expr.value)

        # Fallback: try to get string representation
        return str(expr)[:50]

    def _process_procedural_block(self, block_symbol, graph: ResourceGraph) -> None:
        """
        Process a procedural block (always, always_ff, always_comb).

        Args:
            block_symbol: Procedural block symbol from slang
            graph: ResourceGraph to add nodes/edges to
        """
        # Create a context to track assignments within this block
        # This is needed to handle sequential assignments like:
        #   npc = pc + 4;
        #   npc = npc & ~32'b11;  // Second assignment reads from first
        assignment_context = {}  # target_id -> list of (version, node)

        # Walk the statement tree with assignment tracking
        self._walk_statement(block_symbol.body, graph, depth=0, assignment_context=assignment_context)

        # Clean up intermediate mux assignments
        # For each target with multiple muxes, only the last mux should have an assignment edge
        for target_id, mux_list in assignment_context.items():
            if len(mux_list) <= 1:
                continue  # Single assignment, nothing to clean up

            target_node = graph.nodes.get(target_id)
            if not target_node:
                continue

            # Get all mux nodes for this target
            mux_nodes = [node for (version, node) in mux_list if node.data.get('type') == 'multiplexer']
            if len(mux_nodes) <= 1:
                continue  # Only one mux, nothing to clean up

            # The last mux is the final one - keep its assignment edge
            final_mux = mux_nodes[-1]

            # Remove assignment edges from all intermediate muxes
            for mux_node in mux_nodes[:-1]:
                edges_to_remove = [e for e in mux_node.outgoing_edges
                                 if e.target.id == target_id and
                                 e.data.get('type') == 'assignment']
                for edge in edges_to_remove:
                    graph.remove_edge(edge.id)

    def _apply_signal_replacements(self, graph: ResourceGraph) -> None:
        """
        Apply signal replacements recorded during port connection processing.

        When a wrapper wire conflicts with an internal register (same name),
        we replace all references to the wrapper wire with the correct internal signal.

        For example, if wrapper has 'wire ibus_cyc' connected to 'serv_inst.o_ibus_cyc',
        but the inlined module has 'reg ibus_cyc', we replace all wrapper references
        to 'ibus_cyc' with 'o_ibus_cyc'.
        """
        if not self._signal_replacements:
            return

        print(f"\n  [SIGNAL_REPLACEMENT] Applying {len(self._signal_replacements)} signal replacements")

        for old_signal, new_signal in self._signal_replacements.items():
            print(f"    Replacing '{old_signal}' with '{new_signal}'")

            # Find all edges that reference the old signal
            edges_to_update = []
            for edge in graph.edges.values():
                # Check if source or target node ID contains the old signal name
                if old_signal in edge.source.id or old_signal in edge.target.id:
                    edges_to_update.append(edge)

            # For each edge, replace the old signal reference
            for edge in edges_to_update:
                # Get the new source and target nodes
                old_source_id = edge.source.id
                old_target_id = edge.target.id

                new_source_id = old_source_id.replace(f'({old_signal} ', f'({new_signal} ').replace(f' {old_signal})', f' {new_signal})')
                new_target_id = old_target_id.replace(f'({old_signal} ', f'({new_signal} ').replace(f' {old_signal})', f' {new_signal})')

                # Also replace exact matches
                if old_source_id == old_signal:
                    new_source_id = new_signal
                if old_target_id == old_signal:
                    new_target_id = new_signal

                # If the IDs changed, we need to update the edge
                if new_source_id != old_source_id or new_target_id != old_target_id:
                    # Get or create the new nodes
                    if new_source_id not in graph.nodes:
                        if new_signal in graph.nodes:
                            new_source_node = graph.nodes[new_signal]
                        else:
                            # Keep old node data
                            new_source_node = Node(new_source_id, data=edge.source.data.copy())
                            graph.add_node(new_source_node)
                    else:
                        new_source_node = graph.nodes[new_source_id]

                    if new_target_id not in graph.nodes:
                        if new_signal in graph.nodes:
                            new_target_node = graph.nodes[new_signal]
                        else:
                            new_target_node = Node(new_target_id, data=edge.target.data.copy())
                            graph.add_node(new_target_node)
                    else:
                        new_target_node = graph.nodes[new_target_id]

                    # Create new edge with updated nodes
                    new_edge = Edge(new_source_node, new_target_node, data=edge.data.copy())

                    # Remove old edge and add new one
                    graph.remove_edge(edge.id)
                    graph.add_edge(new_edge)

                    print(f"      Updated edge: {old_source_id} → {old_target_id} becomes {new_source_id} → {new_target_id}")

    def _global_cleanup_intermediate_mux_assignments(self, graph: ResourceGraph) -> None:
        """
        Global cleanup pass to remove intermediate mux assignments.
        For each target that has multiple mux nodes assigning to it,
        keep only the final mux assignment (the one with reset logic or highest in the chain).

        This catches muxes created outside of procedural block tracking (e.g., from case statements
        or other constructs) that create duplicate assignment edges.
        """
        # For each node in the graph, find all muxes assigning to it
        for target_id, target_node in graph.nodes.items():
            # Get all mux nodes that assign to this target
            mux_assignments = []
            for edge in target_node.incoming_edges:
                if edge.data.get('type') == 'assignment':
                    source = edge.source
                    if source.data.get('type') == 'multiplexer':
                        mux_assignments.append((source, edge))

            if len(mux_assignments) <= 1:
                continue  # Nothing to clean up

            # Find the "final" mux - prefer one with 'reset' in the ID
            final_mux = None
            for mux, edge in mux_assignments:
                if 'reset' in mux.id.lower():
                    final_mux = mux
                    break

            # If no reset mux found, use the last one (arbitrary choice)
            if not final_mux:
                final_mux = mux_assignments[-1][0]

            # Remove all intermediate mux assignments
            for mux, edge in mux_assignments:
                if mux.id != final_mux.id:
                    graph.remove_edge(edge.id)

    def _walk_statement(self, stmt, graph: ResourceGraph, depth=0, assignment_context=None) -> None:
        """
        Recursively walk a statement tree and extract assignments.

        Args:
            stmt: Statement from slang
            graph: ResourceGraph to add edges to
            depth: Recursion depth for debug
            assignment_context: Dict tracking assignments in procedural blocks for versioning
        """
        if assignment_context is None:
            assignment_context = {}

        stmt_kind = stmt.kind
        indent = "  " * depth

        # Timed statement (e.g., @(posedge clk)) - follow through
        if stmt_kind == pyslang.StatementKind.Timed:
            print(f"{indent}[WALK] Timed statement, following through")
            self._walk_statement(stmt.stmt, graph, depth+1, assignment_context)

        # Block statement (begin...end) - follow to body
        elif stmt_kind == pyslang.StatementKind.Block:
            print(f"{indent}[WALK] Block statement, following to body")
            # Check if the body is a statement list - if so, detect byte enable patterns first
            if stmt.body.kind == pyslang.StatementKind.List:
                print(f"{indent}[WALK] Block has {len(stmt.body.list)} statements: {[s.kind for s in stmt.body.list]}")
                byte_enable_indices = self._detect_byte_enable_pattern(stmt.body.list, graph, depth+1)
                # Now process the remaining statements
                for i, substmt in enumerate(stmt.body.list):
                    if i in byte_enable_indices:
                        print(f"{indent}  [WALK] Block item {i}: {substmt.kind} (BYTE ENABLE - already processed)")
                        continue
                    print(f"{indent}  [WALK] Block item {i}: {substmt.kind}")
                    self._walk_statement(substmt, graph, depth+2, assignment_context)
            else:
                self._walk_statement(stmt.body, graph, depth+1, assignment_context)

        # Statement list - iterate
        elif stmt_kind == pyslang.StatementKind.List:
            print(f"{indent}[WALK] Statement list with {len(stmt.list)} items")

            # First, check for byte enable patterns before processing individual statements
            byte_enable_indices = self._detect_byte_enable_pattern(stmt.list, graph, depth)

            for i, substmt in enumerate(stmt.list):
                # Skip statements that are part of a byte enable pattern (already processed)
                if i in byte_enable_indices:
                    print(f"{indent}[WALK] Processing list item {i}: {substmt.kind} (BYTE ENABLE - already processed)")
                    continue

                print(f"{indent}[WALK] Processing list item {i}: {substmt.kind}")
                self._walk_statement(substmt, graph, depth+1, assignment_context)

        # Expression statement - check for assignments
        elif stmt_kind == pyslang.StatementKind.ExpressionStatement:
            if hasattr(stmt, 'expr'):
                expr = stmt.expr
                # Check if it's an assignment
                if expr.kind == pyslang.ExpressionKind.Assignment:
                    print(f"{indent}[WALK] Found assignment expression")
                    self._process_assignment_expr(expr, graph, assignment_context)
                else:
                    print(f"{indent}[WALK] Expression statement (not assignment): {expr.kind}")

        # Conditional statement (if/else)
        elif stmt_kind == pyslang.StatementKind.Conditional:
            print(f"{indent}[WALK] Conditional statement - processing semantically")
            # DEBUG: Check what's being assigned in this conditional
            test_assignments = {}
            if hasattr(stmt, 'ifTrue') and stmt.ifTrue:
                self._collect_conditional_assignments(stmt.ifTrue, test_assignments, graph)
                if test_assignments:
                    print(f"{indent}[WALK]   Conditional assigns to: {list(test_assignments.keys())[:5]}")
            self._process_conditional_statement(stmt, graph, assignment_context, depth)

        # Case statement
        elif stmt_kind == pyslang.StatementKind.Case:
            print(f"{indent}[WALK] Case statement")
            self._process_case_statement(stmt, graph, assignment_context)

        # Invalid statement - this can happen for constructs inside generate blocks
        # Try to parse via syntax instead
        elif stmt_kind == pyslang.StatementKind.Invalid:
            print(f"{indent}[WALK] Invalid statement - attempting syntax-based parsing")
            if hasattr(stmt, 'syntax') and stmt.syntax:
                print(f"{indent}[WALK]   Syntax kind: {stmt.syntax.kind}")
                # Use syntax-based parsing as fallback
                self._parse_invalid_via_syntax(stmt.syntax, graph, depth, assignment_context)
            else:
                print(f"{indent}[WALK] WARNING: Invalid statement with no syntax - skipping")

        # For other statement types, we can add support later
        else:
            print(f"{indent}[WALK] Unhandled statement kind: {stmt_kind}")

    def _process_conditional_statement(self, stmt, graph: ResourceGraph, assignment_context=None, depth=0) -> None:
        """
        Process a conditional (if/else) statement by creating ternary mux nodes.

        This creates semantic mux nodes for conditional assignments, similar to how
        case statements create case_mux nodes.
        """
        from core.mux_utils import MuxBuilder, MuxType
        indent = "  " * depth

        # Counter to make mux IDs unique
        if not hasattr(self, '_conditional_mux_counter'):
            self._conditional_mux_counter = 0
        self._conditional_mux_counter += 1
        mux_counter = self._conditional_mux_counter

        # Check if the ifTrue branch contains a byte enable pattern
        if hasattr(stmt, 'ifTrue') and stmt.ifTrue:
            true_body = stmt.ifTrue
            # Unwrap block statements
            if true_body.kind == pyslang.StatementKind.Block:
                true_body = true_body.body
            # Check for byte enable pattern in statement list
            if true_body.kind == pyslang.StatementKind.List:
                byte_enable_indices = self._detect_byte_enable_pattern(true_body.list, graph, depth)
                if byte_enable_indices:
                    # This conditional contains a byte enable pattern - process and return
                    print(f"{indent}[CONDITIONAL] Contains byte enable pattern, skipping normal processing")
                    return

        # Extract condition expression
        condition_node = None
        if hasattr(stmt, 'conditions') and stmt.conditions:
            # If we have assignment_context, substitute variables in the condition
            # with their most recent assigned values to avoid circular dependencies
            if assignment_context:
                assigned_vars = set(assignment_context.keys())
                condition_node = self._substitute_inbranch_values_in_expr(
                    stmt.conditions[0].expr, assigned_vars, assignment_context, graph)
            else:
                condition_node = self._expression_to_node(stmt.conditions[0].expr, graph)

            if condition_node:
                print(f"{indent}[CONDITIONAL] Condition: {condition_node.id}")

                # Check if condition is a compile-time constant
                if condition_node.data.get('type') == 'constant':
                    const_val = condition_node.data.get('value', 0)
                    take_if_branch = (const_val != 0)
                    print(f"{indent}[CONDITIONAL] Condition is constant: {const_val} -> taking {'if' if take_if_branch else 'else'} branch, eliminating other branch")

                    # Only process the taken branch
                    if take_if_branch:
                        if hasattr(stmt, 'ifTrue'):
                            self._walk_statement(stmt.ifTrue, graph, depth+1, assignment_context)
                    else:
                        if hasattr(stmt, 'ifFalse') and stmt.ifFalse:
                            self._walk_statement(stmt.ifFalse, graph, depth+1, assignment_context)
                    return  # Done - don't create muxes

        if not condition_node:
            print(f"{indent}[CONDITIONAL] No condition found, falling back to walking")
            # Fall back to regular walking
            if hasattr(stmt, 'ifTrue'):
                self._walk_statement(stmt.ifTrue, graph, depth+1, assignment_context)
            if hasattr(stmt, 'ifFalse') and stmt.ifFalse:
                self._walk_statement(stmt.ifFalse, graph, depth+1, assignment_context)
            return

        # Process nested conditionals in else clause FIRST (before collecting assignments)
        # This ensures that else-if creates its mux, which can be used as false_value
        if hasattr(stmt, 'ifFalse') and stmt.ifFalse:
            if stmt.ifFalse.kind == pyslang.StatementKind.Conditional:
                print(f"{indent}[CONDITIONAL] Else clause contains nested conditional - processing recursively")
                self._process_conditional_statement(stmt.ifFalse, graph, assignment_context, depth+1)
            elif stmt.ifFalse.kind == pyslang.StatementKind.Block and hasattr(stmt.ifFalse, 'body'):
                # Check if block contains a single conditional (else if pattern)
                body = stmt.ifFalse.body
                if body.kind == pyslang.StatementKind.Conditional:
                    print(f"{indent}[CONDITIONAL] Else block contains conditional - processing recursively")
                    self._process_conditional_statement(body, graph, assignment_context, depth+1)

        # Collect assignments in if-true branch
        true_assignments = {}  # target_id -> source_node
        if hasattr(stmt, 'ifTrue'):
            self._collect_conditional_assignments(stmt.ifTrue, true_assignments, graph, assignment_context)
            print(f"{indent}[CONDITIONAL] If-true assigns to: {list(true_assignments.keys())}")

        # Collect assignments in if-false branch
        false_assignments = {}  # target_id -> source_node
        if hasattr(stmt, 'ifFalse') and stmt.ifFalse:
            self._collect_conditional_assignments(stmt.ifFalse, false_assignments, graph, assignment_context)
            print(f"{indent}[CONDITIONAL] If-false assigns to: {list(false_assignments.keys())}")

        # Find all variables assigned in either branch
        all_targets = set(true_assignments.keys()) | set(false_assignments.keys())

        # Create ternary mux for each assigned variable
        for target_id in all_targets:
            target_node = graph.nodes.get(target_id)
            if not target_node:
                print(f"{indent}[CONDITIONAL] Skipping {target_id}: target_node not found in graph.nodes")
                print(f"{indent}[CONDITIONAL]   Keys matching pattern: {[k for k in graph.nodes.keys() if target_id[:20] in k][:3]}")
                continue

            # Get value from if-true branch
            true_assignment = true_assignments.get(target_id)
            true_value = true_assignment['source'] if true_assignment and isinstance(true_assignment, dict) else true_assignment
            true_partial = true_assignment['partial'] if true_assignment and isinstance(true_assignment, dict) else None
            if target_id in ['pc', 'trapped']:
                print(f"{indent}[CONDITIONAL] DEBUG {target_id}: true_value={true_value}, partial={true_partial}")

            # Get value from if-false branch or previous assignment
            false_assignment = false_assignments.get(target_id)
            false_value = false_assignment['source'] if false_assignment and isinstance(false_assignment, dict) else false_assignment
            false_partial = false_assignment['partial'] if false_assignment and isinstance(false_assignment, dict) else None
            if target_id in ['pc', 'trapped']:
                print(f"{indent}[CONDITIONAL] DEBUG {target_id}: false_value initial={false_value}")
                print(f"{indent}[CONDITIONAL] DEBUG {target_id}: in assignment_context={target_id in assignment_context if assignment_context else False}")
            if not false_value and assignment_context and target_id in assignment_context:
                # No explicit else - use previous assignment as default
                pre_if_assignments = assignment_context[target_id]
                if pre_if_assignments:
                    _, false_value = pre_if_assignments[-1]
                    print(f"{indent}[CONDITIONAL] {target_id}: using pre-if assignment as else: {false_value.id}")

            # Check if a nested conditional already created a mux for this target
            # (from else-if processing). If so, use that mux as the false_value.
            if not false_value:
                # Look for conditional_mux nodes that target this variable
                nested_mux_candidates = [node for node in graph.nodes.values()
                                        if node.id.startswith(f'conditional_mux_{target_id}_')
                                        and node.data.get('type') == 'multiplexer']
                # Use the most recently created mux (highest index or last in list)
                if nested_mux_candidates:
                    false_value = nested_mux_candidates[-1]
                    print(f"{indent}[CONDITIONAL] {target_id}: using nested conditional mux as else: {false_value.id}")

            # For registers/array elements in clocked blocks with no else clause, use the target itself as the else value
            # This represents "keep old value if condition is false"
            is_stateful = (target_node.is_arch_state or
                          target_node.data.get('type') == 'array_access' or
                          target_node.data.get('type') == 'var')
            if not false_value and is_stateful:
                false_value = target_node
                if target_node.data.get('type') == 'array_access':
                    node_type = "array element"
                elif target_node.data.get('type') == 'var':
                    node_type = "variable/register"
                else:
                    node_type = "register"
                print(f"{indent}[CONDITIONAL] {target_id}: {node_type} with no else - holds old value")

            if not true_value or not false_value:
                print(f"{indent}[CONDITIONAL] Skipping {target_id}: missing true or false value")
                continue

            # Handle partial register assignments by constructing full-width values
            # For partial assignment like data[31:2] <= new_val, create: {data[31:2_updated], data[1:0]}
            if true_partial:
                high = true_partial['high']
                low = true_partial['low']
                width = target_node.data.get('bit_width', 32)
                print(f"{indent}[CONDITIONAL] Constructing full-width value for partial assignment [{high}:{low}] of {width}-bit register")

                # Create bit slice nodes for unchanged portions
                # Build from MSB to LSB: [upper_unchanged, new_value, lower_unchanged]
                parts = []

                # Upper unchanged bits (if any): data[width-1:high+1]
                if high + 1 < width:
                    upper_slice_id = f"{target_id}[{width-1}:{high+1}]"
                    if upper_slice_id not in graph.nodes:
                        from core.resource_graph import Node, Edge
                        upper_node = Node(upper_slice_id, {'type': 'bit_slice', 'value': target_id,
                                                           'high': width-1, 'low': high+1, 'bit_width': width-high-1})
                        graph.add_node(upper_node)
                        edge = Edge(target_node, upper_node, data={'type': 'bit_slice'})
                        graph.add_edge(edge)
                    parts.append(graph.nodes[upper_slice_id])

                # New value for assigned bits [high:low]
                parts.append(true_value)

                # Lower unchanged bits (if any): data[low-1:0]
                if low > 0:
                    lower_slice_id = f"{target_id}[{low-1}:0]"
                    if lower_slice_id not in graph.nodes:
                        from core.resource_graph import Node, Edge
                        lower_node = Node(lower_slice_id, {'type': 'bit_slice', 'value': target_id,
                                                           'high': low-1, 'low': 0, 'bit_width': low})
                        graph.add_node(lower_node)
                        edge = Edge(target_node, lower_node, data={'type': 'bit_slice'})
                        graph.add_edge(edge)
                    parts.append(graph.nodes[lower_slice_id])

                # Create concatenation of all parts
                if len(parts) > 1:
                    from core.resource_graph import Node, Edge
                    concat_id = f"concat_partial_{target_id}_{high}_{low}_{mux_counter}"
                    concat_node = Node(concat_id, {'type': 'concatenation', 'bit_width': width})
                    graph.add_node(concat_node)
                    for i, part in enumerate(parts):
                        edge = Edge(part, concat_node, data={'type': 'concat', 'position': i})
                        graph.add_edge(edge)
                    true_value = concat_node
                    print(f"{indent}[CONDITIONAL] Created partial assignment concat: {[p.id[:30] for p in parts]}")

            # Create ternary mux (priority-encoded: condition has priority over default)
            # Make the mux ID unique by including a counter to distinguish identical conditions
            # with different contexts (e.g., alignment checks in JAL vs JALR vs BRANCH)
            mux_id = f"conditional_mux_{target_id}_{condition_node.id[:20]}_{mux_counter}"
            builder = MuxBuilder(graph, mux_id, MuxType.PRIORITY)
            builder.create_or_get_mux(display_name=f"if({condition_node.id[:20]})")

            # Add inputs: condition selects between true_value and false_value
            builder.add_input(true_value, condition_node)  # Selected when condition is true
            builder.add_default_input(false_value)          # Selected when condition is false

            # Connect to target with non-blocking assignment (we're in a procedural block)
            builder.connect_output(target_node, 'assignment', metadata={'assign_type': 'non_blocking'})

            print(f"{indent}[CONDITIONAL] Created conditional_mux for {target_id}: {condition_node.id[:30]} ? {true_value.id[:30]} : {false_value.id[:30]}")

            # Track this mux in assignment_context so next if statement can use it
            mux_node = builder.mux_node
            if assignment_context is not None:
                if target_id not in assignment_context:
                    assignment_context[target_id] = []
                assignment_context[target_id].append((len(assignment_context[target_id]), mux_node))
                print(f"{indent}[CONDITIONAL] Tracked conditional_mux as assignment #{len(assignment_context[target_id])} to {target_id}")

            # Remove pre-if assignment edge if we used it as false branch
            if not false_assignments.get(target_id) and assignment_context and target_id in assignment_context:
                edges_to_remove = [e for e in target_node.incoming_edges
                                 if e.source.id == false_value.id and
                                 e.data.get('assign_type') == 'blocking']
                for edge in edges_to_remove:
                    print(f"{indent}[CONDITIONAL] Removing redundant pre-if edge from {false_value.id[:40]}")
                    graph.remove_edge(edge.id)

    def _collect_conditional_assignments(self, stmt, assignments: dict, graph: ResourceGraph, assignment_context: dict = None) -> None:
        """
        Collect all assignments in a conditional branch.

        Args:
            stmt: Statement to collect assignments from
            assignments: Dict to store collected assignments (target_id -> source_node)
            graph: ResourceGraph
            assignment_context: Optional dict mapping var IDs to their most recent assignments,
                              used for in-branch value substitution
        """
        if stmt.kind == pyslang.StatementKind.Block:
            if hasattr(stmt, 'body'):
                self._collect_conditional_assignments(stmt.body, assignments, graph, assignment_context)
        elif stmt.kind == pyslang.StatementKind.List:
            for substmt in stmt.list:
                self._collect_conditional_assignments(substmt, assignments, graph, assignment_context)
        elif stmt.kind == pyslang.StatementKind.Conditional:
            # Nested conditional - process it normally to create its mux
            # This handles cases like: if (outer) { if (inner) reg <= val; }
            print(f"      [CONDITIONAL] Found nested conditional, processing recursively")
            self._process_conditional_statement(stmt, graph, assignment_context=assignment_context)
            # Don't add to assignments dict - the nested conditional creates its own mux
        elif stmt.kind == pyslang.StatementKind.ExpressionStatement:
            if hasattr(stmt, 'expr') and stmt.expr.kind == pyslang.ExpressionKind.Assignment:
                target_node = self._expression_to_node(stmt.expr.left, graph)

                # Use in-branch substitution for RHS if we have assignment context
                # This prevents circular dependencies like: npc = npc & ~3 becoming
                # npc = case_mux_npc & ~3 instead of npc = (pc + imm) & ~3
                if assignment_context:
                    assigned_vars = set(assignment_context.keys())
                    source_node = self._substitute_inbranch_values_in_expr(
                        stmt.expr.right, assigned_vars, assignment_context, graph)
                else:
                    source_node = self._expression_to_node(stmt.expr.right, graph)

                # CRITICAL FIX: Handle partial register assignments (bit slices)
                # If target is a bit_slice like data[31:2], redirect to parent register
                partial_info = None
                if target_node and target_node.data.get('type') == 'bit_slice':
                    parent_name = target_node.data.get('value')
                    parent_node = graph.nodes.get(parent_name)
                    if parent_node:
                        high_bit = target_node.data.get('high')
                        low_bit = target_node.data.get('low')
                        print(f"      [CONDITIONAL] Detected partial assignment: {parent_name}[{high_bit}:{low_bit}]")
                        print(f"      [CONDITIONAL] Redirecting to parent register: {parent_name}")
                        partial_info = {'high': high_bit, 'low': low_bit, 'bit_slice_node': target_node.id}
                        target_node = parent_node

                if target_node and source_node:
                    # Store both source node and partial assignment info (if any)
                    assignments[target_node.id] = {'source': source_node, 'partial': partial_info}
                elif not target_node:
                    print(f"      [CONDITIONAL] Skipping assignment - no target node")
                elif not source_node:
                    print(f"      [CONDITIONAL] Skipping assignment to {target_node.id} - no source node")
                    print(f"      [CONDITIONAL] RHS expression kind: {stmt.expr.right.kind}")
                    if hasattr(stmt.expr.right, 'symbol'):
                        print(f"      [CONDITIONAL] RHS symbol name: {stmt.expr.right.symbol.name}")

    def _scan_case_for_assigned_vars(self, stmt, graph: ResourceGraph) -> set:
        """
        Scan a case statement to find all variables that are assigned in any branch.

        Args:
            stmt: Case statement from slang
            graph: ResourceGraph

        Returns:
            Set of variable IDs that are assigned in the case
        """
        assigned_vars = set()

        # Scan each case item
        for item in stmt.items:
            branch_vars = {}
            self._collect_all_assignments(item.stmt, branch_vars, graph)
            assigned_vars.update(branch_vars.keys())

        # Scan default case if present
        if stmt.defaultCase:
            default_vars = {}
            self._collect_all_assignments(stmt.defaultCase, default_vars, graph)
            assigned_vars.update(default_vars.keys())

        return assigned_vars

    def _substitute_inbranch_values_in_expr(self, expr, assigned_vars: set, assignment_context: dict, graph: ResourceGraph):
        """
        Substitute variable references in an expression with their most recent assigned values
        within the same branch. This is used for conditionals within case branches where the
        condition references a variable that was just assigned.

        Example:
            npc = pc + imm_j_sext;
            if (npc & 32'b11) begin  // npc should refer to (pc + imm_j_sext), not the case input
                npc = npc & ~32'b11;
            end

        Args:
            expr: Expression from slang
            assigned_vars: Set of variable IDs assigned in this branch so far
            assignment_context: Dict mapping var IDs to list of (assignment_num, source_node)
            graph: ResourceGraph

        Returns:
            Modified expression node
        """
        from pyslang import ExpressionKind

        # If assigned_vars is empty, no substitution needed
        if not assigned_vars or not assignment_context:
            return self._expression_to_node(expr, graph)

        # If expression is a literal/constant, no substitution needed
        if hasattr(expr, 'kind') and expr.kind in [ExpressionKind.IntegerLiteral,
                                                     ExpressionKind.UnbasedUnsizedIntegerLiteral,
                                                     ExpressionKind.StringLiteral]:
            return self._expression_to_node(expr, graph)

        # Handle different expression kinds
        if hasattr(expr, 'kind'):
            if expr.kind == ExpressionKind.NamedValue:
                # Variable reference - check if it's in our assigned set
                var_id = str(expr.symbol.name)
                if var_id in assigned_vars and var_id in assignment_context:
                    # Use the most recent assignment
                    assignments = assignment_context[var_id]
                    if assignments:
                        _, most_recent_value = assignments[-1]
                        print(f"[INBRANCH_SUB] Substituting {var_id} with most recent assignment: {most_recent_value.id[:60]}")
                        return most_recent_value
                # Not assigned or not in context - use as-is
                return self._expression_to_node(expr, graph)

            elif expr.kind == ExpressionKind.BinaryOp:
                # Recursively substitute in both operands
                left_node = self._substitute_inbranch_values_in_expr(expr.left, assigned_vars, assignment_context, graph)
                right_node = self._substitute_inbranch_values_in_expr(expr.right, assigned_vars, assignment_context, graph)

                if not left_node or not right_node:
                    return self._expression_to_node(expr, graph)

                # Rebuild the binary operation
                op = expr.op
                op_str = str(op).split('.')[-1]

                # Create combined node ID
                combined_id = f"({left_node.id} {op_str} {right_node.id})"
                if combined_id in graph.nodes:
                    return graph.nodes[combined_id]

                # Create new node for the operation
                op_data = {
                    'type': 'operator',
                    'operator': op_str,
                    'display_name': combined_id,
                    '_reachable': True  # Mark as reachable so generator processes it
                }
                op_node = Node(combined_id, op_data)
                graph.add_node(op_node)

                # Add edges with correct metadata for generator
                edge_left = Edge(left_node, op_node, data={'type': 'operand', 'position': 'left'})
                edge_right = Edge(right_node, op_node, data={'type': 'operand', 'position': 'right'})
                graph.add_edge(edge_left)
                graph.add_edge(edge_right)

                return op_node

            elif expr.kind == ExpressionKind.RangeSelect:
                # For bit slices, substitute the base variable
                value_node = self._substitute_inbranch_values_in_expr(expr.value, assigned_vars, assignment_context, graph)
                if not value_node:
                    return self._expression_to_node(expr, graph)
                # Create slice node
                left_val = self._extract_constant_value(expr.left) if hasattr(expr, 'left') else None
                right_val = self._extract_constant_value(expr.right) if hasattr(expr, 'right') else None
                if left_val is not None and right_val is not None:
                    slice_id = f"{value_node.id}[{left_val}:{right_val}]"
                    if slice_id in graph.nodes:
                        return graph.nodes[slice_id]
                    slice_node = Node(slice_id, {'type': 'bit_slice', '_reachable': True})
                    graph.add_node(slice_node)
                    edge = Edge(value_node, slice_node, data={'type': 'operand'})
                    graph.add_edge(edge)
                    return slice_node
                return self._expression_to_node(expr, graph)

        # Default: convert normally
        return self._expression_to_node(expr, graph)

    def _substitute_precase_values_in_expr(self, expr, assigned_vars: set, assignment_context: dict, graph: ResourceGraph):
        """
        Recursively substitute variable references in an expression with their pre-case values.

        If a variable is both referenced in this expression AND assigned in the case body,
        replace it with its pre-case value from assignment_context to avoid combinational loops.

        Args:
            expr: Expression from slang
            assigned_vars: Set of variable IDs assigned in the case
            assignment_context: Dict mapping var IDs to list of (source_node, assignment_num)
            graph: ResourceGraph

        Returns:
            Modified expression node
        """
        from pyslang import ExpressionKind

        # If assigned_vars is empty, no substitution needed
        if not assigned_vars:
            return self._expression_to_node(expr, graph)

        # If expression is a literal/constant, no substitution needed
        if hasattr(expr, 'kind') and expr.kind in [ExpressionKind.IntegerLiteral,
                                                     ExpressionKind.UnbasedUnsizedIntegerLiteral,
                                                     ExpressionKind.StringLiteral]:
            return self._expression_to_node(expr, graph)

        # For concatenations like {insn_funct3, mem_rd_addr[1:0]}, we need to rebuild it
        # with substituted sub-expressions
        if hasattr(expr, 'kind'):
            if expr.kind == ExpressionKind.Concatenation:
                # Recursively process operands
                operands = []
                for operand in expr.operands:
                    operands.append(self._substitute_precase_values_in_expr(operand, assigned_vars, assignment_context, graph))
                # Rebuild concatenation with substituted operands
                concat_parts = [op.id for op in operands if op]
                concat_id = "{" + ", ".join(concat_parts) + "}"
                if concat_id in graph.nodes:
                    return graph.nodes[concat_id]
                # Create new concatenation node
                concat_data = {'type': 'concatenation', 'display_name': concat_id, '_reachable': True}
                concat_node = Node(concat_id, concat_data)
                graph.add_node(concat_node)
                # Add edges from operands
                for i, op in enumerate(operands):
                    if op:
                        edge = Edge(op, concat_node, data={'type': 'operand', 'position': i})
                        graph.add_edge(edge)
                return concat_node

            elif expr.kind == ExpressionKind.RangeSelect:
                # For bit slices like mem_rd_addr[1:0], substitute the base variable
                value_node = self._substitute_precase_values_in_expr(expr.value, assigned_vars, assignment_context, graph)
                if not value_node:
                    return self._expression_to_node(expr, graph)
                # Rebuild the slice with substituted base
                left_val = expr.left.constant if hasattr(expr.left, 'constant') else None
                right_val = expr.right.constant if hasattr(expr.right, 'constant') else None
                if left_val is not None and right_val is not None:
                    # Convert ConstantValue to int
                    high_int = int(str(left_val))
                    low_int = int(str(right_val))
                    slice_id = f"{value_node.id}[{high_int}:{low_int}]"
                    if slice_id in graph.nodes:
                        return graph.nodes[slice_id]
                    slice_data = {
                        'type': 'bit_slice',
                        'high': high_int,
                        'low': low_int,
                        'display_name': slice_id,
                        '_reachable': True
                    }
                    slice_node = Node(slice_id, slice_data)
                    graph.add_node(slice_node)
                    edge = Edge(value_node, slice_node, data={'type': 'bit_access'})
                    graph.add_edge(edge)
                    return slice_node
                return self._expression_to_node(expr, graph)

            elif expr.kind == ExpressionKind.NamedValue:
                # Check if this variable is assigned in the case
                if hasattr(expr, 'symbol'):
                    var_id = expr.symbol.name
                    # Debug for mem_rd_addr
                    if var_id == 'mem_rd_addr':
                        print(f"[PRECASE_DEBUG] Found mem_rd_addr reference")
                        print(f"  in assigned_vars: {var_id in assigned_vars}")
                        print(f"  in assignment_context: {var_id in (assignment_context or {})}")
                        if assignment_context and var_id in assignment_context:
                            print(f"  context has {len(assignment_context[var_id])} assignments")
                    if var_id in assigned_vars and assignment_context and var_id in assignment_context:
                        # Use pre-case value
                        pre_case_assignments = assignment_context[var_id]
                        if pre_case_assignments:
                            # assignment_context stores tuples as (assignment_num, source_node)
                            _, pre_case_value = pre_case_assignments[-1]
                            print(f"[PRECASE_SUB] Substituting {var_id} with pre-case value {pre_case_value.id[:60]}")
                            return pre_case_value

            elif expr.kind == ExpressionKind.BinaryOp:
                # For binary operations, recursively substitute operands
                left_node = self._substitute_precase_values_in_expr(expr.left, assigned_vars, assignment_context, graph)
                right_node = self._substitute_precase_values_in_expr(expr.right, assigned_vars, assignment_context, graph)

                if not left_node or not right_node:
                    return self._expression_to_node(expr, graph)

                # Create binary op node with substituted operands
                op_str = str(expr.op).split('.')[-1]  # Get operator name
                op_id = f"({left_node.id} {op_str} {right_node.id})"

                if op_id in graph.nodes:
                    return graph.nodes[op_id]

                op_data = {
                    'type': 'operation',  # Use 'operation' type to match _expression_to_node
                    'operator': op_str,
                    'display_name': op_id
                }
                op_node = Node(op_id, op_data)
                graph.add_node(op_node)

                # Add edges from operands (use same edge types as _expression_to_node)
                left_edge = Edge(left_node, op_node, data={'type': 'operand', 'position': 'left'})
                graph.add_edge(left_edge)
                right_edge = Edge(right_node, op_node, data={'type': 'operand', 'position': 'right'})
                graph.add_edge(right_edge)

                return op_node

        # Default: use standard expression processing
        return self._expression_to_node(expr, graph)

    def _process_case_statement(self, stmt, graph: ResourceGraph, assignment_context=None, parent_case_context=None, parent_selector_id=None) -> None:
        """
        Process a case statement by analyzing assignments and creating muxes.

        Case statements in Verilog are essentially multiplexers that select
        between different values based on a selector expression.

        Args:
            stmt: Case statement from slang
            graph: ResourceGraph to add nodes/edges to
            assignment_context: Context for tracking assignments
            parent_case_context: Parent case value for nested cases (makes mux ID unique)
            parent_selector_id: Parent case selector ID (e.g., "insn_opcode") for nested cases
        """
        from core.mux_utils import MuxBuilder, MuxType

        # First, scan the case body to find all variables that will be assigned
        assigned_vars = self._scan_case_for_assigned_vars(stmt, graph)

        # Get the selector expression, substituting pre-case values for any variables
        # that are assigned within the case to avoid combinational loops
        selector_node = self._substitute_precase_values_in_expr(stmt.expr, assigned_vars, assignment_context, graph)
        if not selector_node:
            return

        # Track assignments in each case branch to detect muxes
        # Map: target_id -> [(case_value, source_node), ...]
        assignments_by_target = {}

        # IMPORTANT: Save default values for all variables that might be assigned in this case
        # We need to do this BEFORE processing any case branches, because nested cases
        # will update assignment_context and we'll lose track of the true pre-case values
        case_defaults = {}  # Map: target_id -> default_source_node
        for var_id in assigned_vars:
            if assignment_context and var_id in assignment_context:
                pre_case_assignments = assignment_context[var_id]
                if pre_case_assignments:
                    # Find the original non-mux assignment
                    default_source = None
                    for _, source in reversed(pre_case_assignments):
                        is_mux = (source.data.get('type') == 'multiplexer' and
                                ('case_mux' in source.id or 'conditional_mux' in source.id))
                        if not is_mux:
                            default_source = source
                            break
                    # If all are muxes, use the most recent
                    if default_source is None:
                        _, default_source = pre_case_assignments[-1]
                    case_defaults[var_id] = default_source
                    print(f"[CASE_PRE] Saved default for {var_id}: {default_source.id[:60]}")

        # Process each case item
        for item_idx, item in enumerate(stmt.items):
            # Get the case match values (can be multiple for one branch)
            case_values = []
            for match_expr in item.expressions:
                # Debug: print the expression details for funct case
                if selector_node and 'funct7' in selector_node.id and 'funct3' in selector_node.id:
                    print(f"[CASE_EXPR_DEBUG] item {item_idx}: kind={match_expr.kind if hasattr(match_expr, 'kind') else 'no kind'}")
                    print(f"  has constant: {hasattr(match_expr, 'constant')}, value={match_expr.constant if hasattr(match_expr, 'constant') else 'N/A'}")
                    print(f"  str: {str(match_expr)[:100]}")
                    if hasattr(match_expr, 'syntax'):
                        print(f"  syntax: {str(match_expr.syntax)[:100]}")
                    if hasattr(match_expr, 'sourceRange'):
                        # Get the source text
                        try:
                            src = match_expr.sourceRange
                            print(f"  source range available")
                        except:
                            pass

                # Try to extract case value
                # For parameters (like OPCODE_LUI), use the parameter name
                # For literals (like 3'b100), use the constant value
                if hasattr(match_expr, 'symbol') and match_expr.symbol and match_expr.symbol.kind == pyslang.SymbolKind.Parameter:
                    # This is a parameter reference - use the parameter name
                    param_name = match_expr.symbol.name
                    case_values.append(param_name)
                    if param_name in ['OPCODE_LOAD', 'OPCODE_STORE']:
                        print(f"[CASE_DEBUG] Processing case for {param_name}, stmt kind: {item.stmt.kind}")

                    # Create or update parameter node in graph with its constant value
                    if param_name not in graph.nodes:
                        param_data = {
                            'type': 'parameter',
                            'name': param_name,
                            'display_name': param_name
                        }
                        # Get the constant value from the parameter symbol's .value attribute
                        try:
                            param_sym = match_expr.symbol
                            if hasattr(param_sym, 'value'):
                                const_val = param_sym.value
                                if const_val is not None:
                                    param_data['value'] = str(const_val)
                        except Exception as e:
                            print(f"[PARAM] {param_name}: error getting value: {e}")
                        param_node = Node(param_name, param_data)
                        graph.add_node(param_node)

                elif hasattr(match_expr, 'constant') and match_expr.constant is not None:
                    # This is a literal constant - use the actual value
                    const = match_expr.constant
                    case_val = str(const)
                    case_values.append(case_val)
                elif hasattr(match_expr, 'constant') and match_expr.constant is None:
                    # This might be a casez pattern with 'z' bits
                    # Try to extract the pattern from the syntax
                    if hasattr(match_expr, 'syntax') and match_expr.syntax:
                        pattern_str = str(match_expr.syntax).strip()
                        # Parse pattern like "10'b zzzzzzz_000"
                        import re
                        match = re.match(r"(\d+)'([bBhHdD])\s*([0-9a-fA-FxXzZ_]+)", pattern_str)
                        if match:
                            width = int(match.group(1))
                            base = match.group(2).lower()
                            value = match.group(3).replace('_', '')

                            if 'z' in value.lower() or 'x' in value.lower():
                                # This is a casez/casex pattern with don't-cares
                                # Store the pattern for special handling
                                case_values.append(pattern_str)
                                print(f"[CASEZ] Extracted pattern: {pattern_str}")
                                continue
                        # Fallback to placeholder
                        case_values.append(f"case_{item_idx}")
                    else:
                        # No syntax available, use placeholder
                        case_values.append(f"case_{item_idx}")
                elif hasattr(match_expr, 'kind') and match_expr.kind == pyslang.ExpressionKind.EmptyArgument:
                    # This is the default case
                    case_values.append("default")
                elif hasattr(match_expr, 'type') and hasattr(match_expr.type, 'isSigned'):
                    # Try to get the evaluated constant value from the expression
                    try:
                        # For integer literals and bit patterns, try to get the value
                        if hasattr(match_expr, 'eval'):
                            const_val = match_expr.eval()
                            if const_val is not None:
                                case_values.append(str(const_val))
                                continue
                    except:
                        pass
                    # For non-constant, use a placeholder
                    case_values.append(f"case_{item_idx}")
                else:
                    # For non-constant, use a placeholder
                    case_values.append(f"case_{item_idx}")

            # Process the statement for this case
            # We need to track assignments made in this branch
            # IMPORTANT: Create a copy of assignment_context for each branch!
            # Each case branch should see the same pre-case state, not be affected by
            # conditional_muxes created in other branches (which would cause chaining bugs)
            branch_context = None
            if assignment_context:
                import copy
                # Deep copy the assignment_context so each branch is isolated
                branch_context = {}
                for var_id, assignments_list in assignment_context.items():
                    # Copy the list of assignments for this variable
                    branch_context[var_id] = list(assignments_list)

            # Handle both single statements and blocks
            if item.stmt.kind == pyslang.StatementKind.Block:
                # Process all statements in the block
                self._extract_case_assignments(item.stmt, case_values, selector_node, assignments_by_target, graph, assigned_vars, branch_context)
            elif item.stmt.kind == pyslang.StatementKind.ExpressionStatement:
                if hasattr(item.stmt, 'expr'):
                    expr = item.stmt.expr
                    if expr.kind == pyslang.ExpressionKind.Assignment:
                        # This is an assignment in a case branch
                        target_node = self._expression_to_node(expr.left, graph)
                        # Use pre-case substitution for RHS to avoid combinational loops
                        # Use branch_context (or assignment_context if branch_context is None)
                        source_node = self._substitute_precase_values_in_expr(expr.right, assigned_vars, branch_context if branch_context is not None else assignment_context, graph)

                        if target_node and source_node:
                            target_id = target_node.id
                            if target_id not in assignments_by_target:
                                assignments_by_target[target_id] = []

                            # Store assignment with case values
                            # Create a comparison node for each case value
                            for case_val in case_values:
                                if case_val == "default":
                                    # For default case, use None as condition (means "else")
                                    condition_node = None
                                else:
                                    # Create comparison node: selector == case_val
                                    condition_node = self._create_case_condition_node(selector_node, case_val, graph)
                                assignments_by_target[target_id].append(
                                    (condition_node, source_node, case_val)
                                )

        # Process default case if it exists
        if stmt.defaultCase:
            # Create isolated context for default case too
            default_context = None
            if assignment_context:
                import copy
                default_context = {}
                for var_id, assignments_list in assignment_context.items():
                    default_context[var_id] = list(assignments_list)

            if stmt.defaultCase.kind == pyslang.StatementKind.Block:
                # Process all statements in the default block
                self._extract_case_assignments(stmt.defaultCase, ["default"], selector_node, assignments_by_target, graph, assigned_vars, default_context)
            elif stmt.defaultCase.kind == pyslang.StatementKind.ExpressionStatement:
                if hasattr(stmt.defaultCase, 'expr'):
                    expr = stmt.defaultCase.expr
                    if expr.kind == pyslang.ExpressionKind.Assignment:
                        target_node = self._expression_to_node(expr.left, graph)
                        # Use pre-case substitution for RHS to avoid combinational loops
                        source_node = self._substitute_precase_values_in_expr(expr.right, assigned_vars, default_context if default_context is not None else assignment_context, graph)

                        if target_node and source_node:
                            target_id = target_node.id
                            if target_id not in assignments_by_target:
                                assignments_by_target[target_id] = []

                            # Default case - use None as condition (means "else")
                            condition_node = None
                            assignments_by_target[target_id].append(
                                (condition_node, source_node, "default")
                            )

        # Now create muxes for each target that has assignments
        # All case assignments should go through a case_mux, even single assignments,
        # because the case_mux is responsible for implementing case selection logic
        for target_id, assignments in assignments_by_target.items():
            # Deduplicate: if same case_val appears multiple times (due to multiple
            # assignments in same case branch), keep only the LAST one
            deduplicated = {}
            for condition_node, source_node, case_val in assignments:
                # Store by case_val - later assignments overwrite earlier ones
                deduplicated[case_val] = (condition_node, source_node, case_val)

            # Convert back to list
            assignments = list(deduplicated.values())

            # Check if there's an explicit default case
            has_explicit_default = any(case_val == "default" for _, _, case_val in assignments)

            # If no explicit default, use the saved case default
            if not has_explicit_default and target_id in case_defaults:
                pre_case_source = case_defaults[target_id]
                print(f"[CASE_DEFAULT] {target_id}: using saved case default {pre_case_source.id[:60]}")
                # Add the pre-case assignment as the default
                assignments.append((None, pre_case_source, "default"))

                # Remove the pre-case assignment edge from the graph to avoid redundant syntax_mux
                # The case_mux will have this as its default_in, so we don't need the direct edge
                target_node = graph.nodes[target_id]
                # Debug: check all incoming edges
                print(f"[CASE_DEFAULT] {target_id}: checking {len(target_node.incoming_edges)} incoming edges")
                for e in target_node.incoming_edges:
                    print(f"  [CASE_DEFAULT]   edge from {e.source.id[:40]}: assign_type={e.data.get('assign_type')}")

                print(f"[CASE_DEFAULT] {target_id}: looking for edges from pre_case_source.id={pre_case_source.id[:60]}")
                # Check if pre_case_source is a mux (case_mux or conditional_mux)
                is_pre_case_mux = (pre_case_source.data.get('type') == 'multiplexer' and
                                  ('case_mux' in pre_case_source.id or 'conditional_mux' in pre_case_source.id))

                edges_to_remove = []
                if is_pre_case_mux:
                    # The pre-case source is a mux (from a nested case or earlier case).
                    # We should remove:
                    # 1. The edge from this mux
                    # 2. ALL earlier blocking edges (since they're now handled by the case_mux chain)
                    for e in target_node.incoming_edges:
                        if e.source.id == pre_case_source.id:
                            edges_to_remove.append(e)
                        elif (e.data.get('assign_type') == 'blocking' and
                              e.source.data.get('type') != 'multiplexer'):
                            # This is a direct blocking assignment (not from a mux)
                            # Remove it since the case_mux chain now handles it
                            edges_to_remove.append(e)
                else:
                    # For non-mux sources, require assign_type='blocking'
                    edges_to_remove = [e for e in target_node.incoming_edges
                                     if e.source.id == pre_case_source.id and
                                     e.data.get('assign_type') == 'blocking']
                # Debug: why didn't we find the edge?
                if len(edges_to_remove) == 0:
                    for e in target_node.incoming_edges:
                        match_id = (e.source.id == pre_case_source.id)
                        match_type = (e.data.get('assign_type') == 'blocking')
                        print(f"  [CASE_DEFAULT]   edge {e.source.id[:40]}: id_match={match_id}, type_match={match_type}")
                print(f"[CASE_DEFAULT] {target_id}: found {len(edges_to_remove)} edges to remove")
                for edge in edges_to_remove:
                    print(f"[CASE_DEFAULT] {target_id}: removing redundant pre-case edge from {pre_case_source.id} (edge_id={edge.id[:40]})")
                    graph.remove_edge(edge.id)
                print(f"[CASE_DEFAULT] {target_id}: after removal, {len(target_node.incoming_edges)} incoming edges remain")


            # Create a case_mux for this target
            target_node = graph.nodes[target_id]
            # Include parent case context to make nested case muxes unique
            if parent_case_context:
                mux_id = f"case_mux_{target_id}_{selector_node.id}_{parent_case_context}"
            else:
                mux_id = f"case_mux_{target_id}_{selector_node.id}"

            # Use priority mux since case statements are priority-encoded
            builder = MuxBuilder(graph, mux_id, MuxType.PRIORITY)
            builder.create_or_get_mux(display_name=f"case({selector_node.id})")

            # Add each case branch as a mux input
            for condition_node, source_node, case_val in assignments:
                if condition_node is None:
                    # This is a default case (either explicit or from pre-case assignment)
                    builder.add_default_input(source_node)
                else:
                    # Normal case with condition node as select signal
                    builder.add_input(source_node, condition_node)

            # Connect mux output to target
            builder.connect_output(target_node, 'assignment')

            # Remove bypassing edges from inputs to target (now that mux handles them)
            source_nodes = [source for _, source, _ in assignments]
            builder.remove_bypassing_edges(source_nodes, target_node)

            # Track this case_mux in assignment_context so subsequent if statements can use it
            mux_node = builder.mux_node

            # Store parent_case_context as metadata for nested case_muxes
            # This will be used by the generator to create proper selector conditions
            if parent_case_context and parent_selector_id:
                mux_node.data['parent_case_context'] = parent_case_context
                mux_node.data['parent_selector'] = parent_selector_id  # e.g., "insn_opcode"
                print(f"[CASE] Stored activation condition for {mux_id}: parent_selector={parent_selector_id}, parent_case_context={parent_case_context}")

            if assignment_context is not None:
                if target_id not in assignment_context:
                    assignment_context[target_id] = []
                assignment_context[target_id].append((len(assignment_context[target_id]), mux_node))
                print(f"[CASE] Tracked case_mux as assignment #{len(assignment_context[target_id])} to {target_id}: mux_id={mux_node.id[:80]}")

    def _create_case_condition_node(self, selector_node: Node, case_value: str, graph: ResourceGraph) -> Node:
        """
        Create a comparison node for a case condition (selector == case_value).

        Handles casez patterns with don't-care bits (z/x) by generating comparison
        logic that only checks the fixed bits.

        Args:
            selector_node: The case selector expression (e.g., opcode)
            case_value: The case match value (e.g., "7'b0110111", "OPCODE_LUI", or "10'b zzzzzzz_000")
            graph: ResourceGraph to add node to

        Returns:
            Node representing the comparison
        """
        import re

        # Check if this is a casez/casex pattern with don't-care bits
        match = re.match(r"(\d+)'([bBhHdD])\s*([0-9a-fA-FxXzZ_]+)", case_value.strip())
        if match:
            print(f"[CASEZ_DEBUG] Matched pattern: {case_value}, groups: width={match.group(1)}, base={match.group(2)}, pattern={match.group(3)}")
        if match and ('z' in match.group(3).lower() or 'x' in match.group(3).lower()):
            print(f"[CASEZ_DEBUG] Found don't-care bits in {case_value}")
            # Handle casez pattern
            width = int(match.group(1))
            base = match.group(2).lower()
            pattern = match.group(3).replace('_', '')

            if base == 'b':
                # Binary pattern - identify fixed bits
                fixed_bits = []
                for i, bit in enumerate(reversed(pattern)):  # LSB first
                    if bit in '01':
                        fixed_bits.append((i, bit))

                if not fixed_bits:
                    # All don't-cares - always matches
                    print(f"[CASEZ] Pattern {case_value} has all don't-cares - creating constant true")
                    # Return a constant 1 node
                    const_node_id = "const_1"
                    if const_node_id not in graph.nodes:
                        const_data = {'type': 'literal', 'value': '1', 'display_name': '1'}
                        const_node = Node(const_node_id, const_data)
                        graph.add_node(const_node)
                    return graph.nodes[const_node_id]

                # Generate comparison for fixed bits only
                # For "10'b zzzzzzz_000", fixed_bits = [(0,'0'), (1,'0'), (2,'0')]
                # Generate: selector[2:0] == 3'b000

                # Find contiguous ranges of fixed bits
                # For simplicity, we'll just check each range
                if len(fixed_bits) == 1:
                    # Single bit check: selector[i] == bit
                    bit_idx, bit_val = fixed_bits[0]
                    # Create bit slice node
                    slice_id = f"{selector_node.id}[{bit_idx}]"
                    if slice_id not in graph.nodes:
                        slice_data = {
                            'type': 'bit_slice',
                            'high': bit_idx,
                            'low': bit_idx,
                            'display_name': slice_id
                        }
                        slice_node = Node(slice_id, slice_data)
                        graph.add_node(slice_node)
                        # Add edge from selector to slice
                        slice_edge = Edge(selector_node, slice_node, data={'type': 'bit_access'})
                        graph.add_edge(slice_edge)
                    else:
                        slice_node = graph.nodes[slice_id]

                    # Create value node
                    val_id = f"1'b{bit_val}"
                    if val_id not in graph.nodes:
                        val_data = {'type': 'literal', 'value': val_id, 'display_name': val_id}
                        val_node = Node(val_id, val_data)
                        graph.add_node(val_node)
                    else:
                        val_node = graph.nodes[val_id]

                    # Create comparison
                    sanitized_case = case_value.replace("'", "_").replace(" ", "_").replace("{", "").replace("}", "").replace(",", "_")
                    comp_id = f"{selector_node.id}_matches_{sanitized_case}"
                    if comp_id in graph.nodes:
                        return graph.nodes[comp_id]

                    comp_data = {
                        'type': 'comparison',
                        'operator': '==',
                        'display_name': f"{slice_id} == {val_id}"
                    }
                    comp_node = Node(comp_id, comp_data)
                    graph.add_node(comp_node)

                    # Add edges
                    Edge(slice_node, comp_node, data={'type': 'operand', 'position': 0})
                    Edge(val_node, comp_node, data={'type': 'operand', 'position': 1})

                    print(f"[CASEZ] Generated comparison for {case_value}: {slice_id} == {val_id}")
                    return comp_node
                else:
                    # Multiple bits - check if contiguous
                    indices = [idx for idx, _ in fixed_bits]
                    if max(indices) - min(indices) + 1 == len(indices):
                        # Contiguous range
                        low = min(indices)
                        high = max(indices)
                        slice_width = high - low + 1

                        # Create bit slice
                        if low == high:
                            slice_id = f"{selector_node.id}[{low}]"
                        else:
                            slice_id = f"{selector_node.id}[{high}:{low}]"

                        if slice_id not in graph.nodes:
                            slice_data = {
                                'type': 'bit_slice',
                                'high': high,
                                'low': low,
                                'display_name': slice_id
                            }
                            slice_node = Node(slice_id, slice_data)
                            graph.add_node(slice_node)
                            # Add edge from selector to slice
                            slice_edge = Edge(selector_node, slice_node, data={'type': 'bit_access'})
                            graph.add_edge(slice_edge)
                        else:
                            slice_node = graph.nodes[slice_id]

                        # Build the value for fixed bits
                        value_str = ''.join([bit_val for _, bit_val in sorted(fixed_bits, reverse=True)])
                        val_id = f"{slice_width}'b{value_str}"

                        if val_id not in graph.nodes:
                            val_data = {'type': 'literal', 'value': val_id, 'display_name': val_id}
                            val_node = Node(val_id, val_data)
                            graph.add_node(val_node)
                        else:
                            val_node = graph.nodes[val_id]

                        # Create comparison
                        sanitized_case = case_value.replace("'", "_").replace(" ", "_").replace("{", "").replace("}", "").replace(",", "_")
                        comp_id = f"{selector_node.id}_matches_{sanitized_case}"
                        if comp_id in graph.nodes:
                            return graph.nodes[comp_id]

                        comp_data = {
                            'type': 'comparison',
                            'operator': '==',
                            'display_name': f"{slice_id} == {val_id}"
                        }
                        comp_node = Node(comp_id, comp_data)
                        graph.add_node(comp_node)

                        # Add edges
                        Edge(slice_node, comp_node, data={'type': 'operand', 'position': 0})
                        Edge(val_node, comp_node, data={'type': 'operand', 'position': 1})

                        print(f"[CASEZ] Generated comparison for {case_value}: {slice_id} == {val_id}")
                        return comp_node
                    else:
                        # Non-contiguous - use mask-and-compare approach
                        # Generate: (selector & mask) == value
                        # Where mask has 1s at fixed bit positions, value has the fixed bit values
                        print(f"[CASEZ] Handling non-contiguous fixed bits in {case_value}")

                        # Build mask and value
                        mask_bits = ['0'] * width
                        value_bits = ['0'] * width
                        for bit_idx, bit_val in fixed_bits:
                            mask_bits[width - 1 - bit_idx] = '1'  # MSB first for string
                            value_bits[width - 1 - bit_idx] = bit_val

                        mask_str = ''.join(mask_bits)
                        value_str = ''.join(value_bits)
                        mask_literal = f"{width}'b{mask_str}"
                        value_literal = f"{width}'b{value_str}"

                        # Create mask node
                        if mask_literal not in graph.nodes:
                            mask_data = {'type': 'literal', 'value': mask_literal, 'display_name': mask_literal}
                            mask_node = Node(mask_literal, mask_data)
                            graph.add_node(mask_node)
                        else:
                            mask_node = graph.nodes[mask_literal]

                        # Create masked selector: selector & mask
                        masked_id = f"({selector_node.id} BitwiseAnd {mask_literal})"
                        if masked_id not in graph.nodes:
                            masked_data = {
                                'type': 'operation',
                                'operator': 'BitwiseAnd',
                                'display_name': masked_id
                            }
                            masked_node = Node(masked_id, masked_data)
                            graph.add_node(masked_node)
                            # Add edges
                            Edge(selector_node, masked_node, data={'type': 'operand', 'position': 0})
                            Edge(mask_node, masked_node, data={'type': 'operand', 'position': 1})
                        else:
                            masked_node = graph.nodes[masked_id]

                        # Create value node
                        if value_literal not in graph.nodes:
                            value_data = {'type': 'literal', 'value': value_literal, 'display_name': value_literal}
                            value_node = Node(value_literal, value_data)
                            graph.add_node(value_node)
                        else:
                            value_node = graph.nodes[value_literal]

                        # Create comparison: masked_selector == value
                        sanitized_case = case_value.replace("'", "_").replace(" ", "_").replace("{", "").replace("}", "").replace(",", "_")
                        comp_id = f"{selector_node.id}_matches_{sanitized_case}"
                        if comp_id in graph.nodes:
                            return graph.nodes[comp_id]

                        comp_data = {
                            'type': 'comparison',
                            'operator': '==',
                            'display_name': f"({selector_node.id} & {mask_literal}) == {value_literal}"
                        }
                        comp_node = Node(comp_id, comp_data)
                        graph.add_node(comp_node)

                        # Add edges
                        Edge(masked_node, comp_node, data={'type': 'operand', 'position': 0})
                        Edge(value_node, comp_node, data={'type': 'operand', 'position': 1})

                        print(f"[CASEZ] Generated mask-and-compare for {case_value}: ({selector_node.id} & {mask_literal}) == {value_literal}")
                        return comp_node


        # Regular case (no don't-cares) or fallback
        # Create or get a node for the case value
        if case_value in graph.nodes:
            value_node = graph.nodes[case_value]
        else:
            # Create a literal or parameter node for the case value
            value_data = {
                'type': 'literal',
                'value': case_value,
                'display_name': case_value
            }
            value_node = Node(case_value, value_data)
            graph.add_node(value_node)

        # Create comparison node: selector == case_value
        # Sanitize case_value for use in node ID (remove Verilog syntax like ')
        sanitized_case = case_value.replace("'", "_").replace(" ", "_").replace("{", "").replace("}", "").replace(",", "_")
        node_id = f"{selector_node.id}_eq_{sanitized_case}"
        if node_id in graph.nodes:
            return graph.nodes[node_id]

        comparison_data = {
            'type': 'comparison',
            'operator': '==',
            'display_name': f"{selector_node.id} == {case_value}"
        }
        comparison_node = Node(node_id, comparison_data)
        graph.add_node(comparison_node)

        # Create edges from operands to comparison
        left_edge = Edge(selector_node, comparison_node, data={'type': 'left_operand', 'position': 'left'})
        graph.add_edge(left_edge)

        right_edge = Edge(value_node, comparison_node, data={'type': 'right_operand', 'position': 'right'})
        graph.add_edge(right_edge)

        return comparison_node

    def _extract_case_assignments(self, stmt, case_values, selector_node, assignments_by_target, graph, assigned_vars=None, assignment_context=None):
        """
        Helper to extract assignments from a case statement branch.

        Args:
            stmt: Statement to extract from (Block or List)
            case_values: List of case match values for this branch
            selector_node: The case selector expression
            assignments_by_target: Dict to accumulate assignments
            graph: ResourceGraph
            assigned_vars: Set of variable IDs assigned in the case (for pre-case substitution)
            assignment_context: Dict mapping var IDs to pre-case values (for pre-case substitution)
        """
        if assigned_vars is None:
            assigned_vars = set()
        if assignment_context is None:
            assignment_context = {}
        if any(cv in ['OPCODE_LOAD', 'OPCODE_STORE'] for cv in case_values):
            print(f"[EXTRACT_DEBUG] case_values={case_values}, stmt kind: {stmt.kind}")

        # Handle block statements
        if stmt.kind == pyslang.StatementKind.Block:
            self._extract_case_assignments(stmt.body, case_values, selector_node, assignments_by_target, graph, assigned_vars, assignment_context)
            return

        # Handle statement lists
        if stmt.kind == pyslang.StatementKind.List:
            if any(cv in ['OPCODE_LOAD', 'OPCODE_STORE'] for cv in case_values):
                print(f"[EXTRACT_DEBUG] List has {len(stmt.list)} statements")

            # IMPORTANT: For nested casez, we need to track assignments that happen BEFORE the nested case
            # Example: mem_rd_addr = rs1_value + imm_i_sext; casez ({insn_funct3, mem_rd_addr[1:0]})
            # The nested casez should use the value just assigned, not the pre-case default
            # Create a mutable copy of assignment_context for tracking in-case assignments
            current_context = {}
            if assignment_context:
                import copy
                for var_id, assignments_list in assignment_context.items():
                    current_context[var_id] = list(assignments_list)

            for i, substmt in enumerate(stmt.list):
                if any(cv in ['OPCODE_LOAD', 'OPCODE_STORE'] for cv in case_values):
                    print(f"[EXTRACT_DEBUG]   Statement {i}: {substmt.kind}")

                # Check if this statement is an assignment
                is_assignment = False
                if substmt.kind == pyslang.StatementKind.ExpressionStatement:
                    if hasattr(substmt, 'expr') and hasattr(substmt.expr, 'kind'):
                        if substmt.expr.kind == pyslang.ExpressionKind.Assignment:
                            is_assignment = True
                            # This is an assignment - extract the target and value
                            if hasattr(substmt.expr, 'left') and hasattr(substmt.expr.left, 'symbol'):
                                target_var = substmt.expr.left.symbol.name
                                # IMPORTANT: Use pre-case substitution for self-referencing assignments!
                                # Example: mem_rd_addr = {mem_rd_addr[31:2], 2'b 00}
                                # The RHS references mem_rd_addr, which should use the value BEFORE this assignment
                                value_node = self._substitute_precase_values_in_expr(
                                    substmt.expr.right, assigned_vars, current_context, graph)
                                if value_node:
                                    # Update context with this new assignment
                                    # This is used for subsequent statements in the list that might reference this variable
                                    if target_var not in current_context:
                                        current_context[target_var] = []
                                    # Track this as assignment #0 for in-case context (num doesn't matter, just use latest)
                                    current_context[target_var] = [(0, value_node)]
                                    if any(cv in ['OPCODE_LOAD', 'OPCODE_STORE'] for cv in case_values):
                                        print(f"[INCASE_ASSIGN] {target_var} = {value_node.id[:50]}")

                                    # Add this assignment directly to assignments_by_target using the value_node we just created
                                    # This avoids re-parsing and creating duplicate shift operations
                                    target_node = self._expression_to_node(substmt.expr.left, graph)
                                    if target_node:
                                        target_id = target_node.id
                                        if target_id not in assignments_by_target:
                                            assignments_by_target[target_id] = []
                                        for case_val in case_values:
                                            if case_val == "default":
                                                condition_node = None
                                            else:
                                                condition_node = self._create_case_condition_node(selector_node, case_val, graph)
                                            assignments_by_target[target_id].append(
                                                (condition_node, value_node, case_val)
                                            )

                # Only recursively process non-assignment statements
                # Assignments were already handled above to avoid double-parsing
                if not is_assignment:
                    self._extract_case_assignments(substmt, case_values, selector_node, assignments_by_target, graph, assigned_vars, current_context)
            return

        # Handle nested case statements
        if stmt.kind == pyslang.StatementKind.Case:
            if any(cv in ['OPCODE_LOAD', 'OPCODE_STORE'] for cv in case_values):
                print(f"[EXTRACT_DEBUG] case_values={case_values}, stmt kind: StatementKind.Case")

            # IMPORTANT: Get the nested selector BEFORE processing the nested case
            # Because _process_case_statement will update assignment_context with case_mux nodes,
            # and we need the original in-case values for the selector, not the case_mux nodes.
            nested_assigned_vars = self._scan_case_for_assigned_vars(stmt, graph)
            nested_selector_node = self._substitute_precase_values_in_expr(stmt.expr, nested_assigned_vars, assignment_context, graph)
            if not nested_selector_node:
                return

            # Process the nested case statement as a full case_mux (not just common assignments)
            # This creates case_mux nodes for assignments that differ between branches
            # Pass the parent case values and selector to make the mux ID unique and enable activation conditions
            # IMPORTANT: If multiple case values share the same body, use ALL of them as context
            # so the nested case_mux is shared, not duplicated
            parent_context = '_'.join(case_values) if case_values else None
            self._process_case_statement(stmt, graph, assignment_context=assignment_context, parent_case_context=parent_context, parent_selector_id=selector_node.id)

            # After processing, the nested case has created its case_mux nodes.
            # Now extract which variables were assigned (to know what the outer case needs to track)
            # We collect ALL assignments from the nested case (not just common ones)
            nested_targets = set()
            for item in stmt.items:
                branch_assign = {}
                self._collect_all_assignments(item.stmt, branch_assign, graph)
                nested_targets.update(branch_assign.keys())

            # For each variable assigned in the nested case, find its case_mux and use it
            for target_id in nested_targets:
                # Look for the case_mux created by the nested case
                # It will have the form case_mux_{target}_{nested_selector}_{parent_context}
                # First try to find with parent context
                mux_id_pattern = f'case_mux_{target_id}_'
                if parent_context:
                    # Look for mux with this specific parent context
                    mux_id_with_context = f'{mux_id_pattern}{nested_selector_node.id}_{parent_context}'
                    print(f"[NESTED_LOOKUP] Looking for {target_id}: {mux_id_with_context[:80]}")
                    if mux_id_with_context in graph.nodes:
                        case_mux_node = graph.nodes[mux_id_with_context]
                        print(f"[NESTED_CASE] Variable {target_id}: using nested case_mux {case_mux_node.id[:60]}")

                        # Add the case_mux as the assignment for this outer case branch
                        if target_id not in assignments_by_target:
                            assignments_by_target[target_id] = []
                        for case_val in case_values:
                            if case_val == "default":
                                condition_node = None
                            else:
                                condition_node = self._create_case_condition_node(selector_node, case_val, graph)
                            print(f"[NESTED_CASE] Adding {case_mux_node.id[:60]} to outer case for {target_id} at case_val={case_val}")
                            assignments_by_target[target_id].append(
                                (condition_node, case_mux_node, case_val)
                            )
                    else:
                        # No matching case_mux found - this variable is not assigned by the nested case itself,
                        # but by other statements (e.g., assignments after the nested case).
                        # Skip it - those assignments will be extracted when processing the branch statements.
                        print(f"[NESTED_CASE] Variable {target_id}: no case_mux for parent_context={parent_context[:50]}, skipping")
                        continue
                else:
                    mux_candidates = [node for node in graph.nodes.values()
                                     if node.id.startswith(mux_id_pattern)
                                     and node.data.get('type') == 'multiplexer']

                    if not mux_candidates:
                        continue
                    # Use the most recently created case_mux
                    case_mux_node = mux_candidates[-1]
                    print(f"[NESTED_CASE] Variable {target_id}: using nested case_mux {case_mux_node.id[:60]}")

                    if target_id not in assignments_by_target:
                        assignments_by_target[target_id] = []

                    # Add the case_mux as the assignment for this outer case branch
                    for case_val in case_values:
                        if case_val == "default":
                            condition_node = None
                        else:
                            condition_node = self._create_case_condition_node(selector_node, case_val, graph)
                        print(f"[NESTED_CASE] Adding {case_mux_node.id[:60]} to outer case for {target_id} at case_val={case_val}")
                        assignments_by_target[target_id].append(
                            (condition_node, case_mux_node, case_val)
                        )
            # Don't return - continue processing other statements in the same block

        # Handle conditional statements (if statements within case branches)
        # Example: case (funct3) 3'b000: begin if (rs1 == rs2) npc = target; end endcase
        if stmt.kind == pyslang.StatementKind.Conditional:
            print(f"[EXTRACT_CONDITIONAL] Found conditional statement in case branch (case_values={case_values})")

            # Track what was in assignment_context before processing
            pre_conditional_context = {}
            if assignment_context:
                for var_id, assignments in assignment_context.items():
                    pre_conditional_context[var_id] = len(assignments)

            # Process the conditional statement to create conditional_mux nodes
            # This will update assignment_context with the newly created muxes
            self._process_conditional_statement(stmt, graph, assignment_context, depth=0)

            # After processing, find which variables were assigned by checking what changed in assignment_context
            if assignment_context:
                for var_id, assignments in assignment_context.items():
                    prev_len = pre_conditional_context.get(var_id, 0)
                    if len(assignments) > prev_len:
                        # This variable got a new assignment from the conditional
                        # The new assignment is the conditional_mux that was just created
                        _, conditional_mux = assignments[-1]
                        print(f"[EXTRACT_CONDITIONAL] Variable {var_id} got conditional_mux: {conditional_mux.id[:60]}")

                        # Add this conditional_mux to assignments_by_target
                        if var_id not in assignments_by_target:
                            assignments_by_target[var_id] = []

                        for case_val in case_values:
                            if case_val == "default":
                                condition_node = None
                            else:
                                condition_node = self._create_case_condition_node(selector_node, case_val, graph)
                            print(f"[EXTRACT_CONDITIONAL] Adding {conditional_mux.id[:60]} to outer case for {var_id} at case_val={case_val}")
                            assignments_by_target[var_id].append(
                                (condition_node, conditional_mux, case_val)
                            )
            return

        # Handle expression statements
        if stmt.kind == pyslang.StatementKind.ExpressionStatement:
            if hasattr(stmt, 'expr'):
                expr = stmt.expr
                if expr.kind == pyslang.ExpressionKind.Assignment:
                    target_node = self._expression_to_node(expr.left, graph)

                    # Debug: check assignment_context before substitution
                    if target_node and target_node.id in ['mem_wr_strb', 'mem_wr_data']:
                        if assignment_context and target_node.id in assignment_context:
                            assignments = assignment_context[target_node.id]
                            print(f"[PRE_SUBST] {target_node.id} has {len(assignments)} assignments in context:")
                            for i, (num, node) in enumerate(assignments):
                                print(f"  [{i}] #{num}: {node.id[:50]}")

                    # Use pre-case substitution for RHS to avoid combinational loops
                    source_node = self._substitute_precase_values_in_expr(expr.right, assigned_vars, assignment_context, graph)

                    if target_node and source_node:
                        target_id = target_node.id
                        if any(cv in ['OPCODE_LOAD', 'OPCODE_STORE'] for cv in case_values):
                            print(f"[EXTRACT_DEBUG] Found assignment: {target_id} = {source_node.id}")
                        # Debug nested case assignments
                        if target_id in ['mem_wr_strb', 'mem_wr_data']:
                            print(f"[EXTRACT_NESTED] {target_id} = {source_node.id[:60]} (case_values={case_values})")
                        if target_id not in assignments_by_target:
                            assignments_by_target[target_id] = []

                        # Store assignment with case values
                        # Create a comparison node for each case value
                        for case_val in case_values:
                            if case_val == "default":
                                # For default case, use None as condition (means "else")
                                condition_node = None
                            else:
                                # Create comparison node: selector == case_val
                                condition_node = self._create_case_condition_node(selector_node, case_val, graph)
                            assignments_by_target[target_id].append(
                                (condition_node, source_node, case_val)
                            )

    def _extract_common_case_assignments(self, case_stmt, graph: ResourceGraph) -> dict:
        """
        Extract assignments that are common to all non-default branches of a nested case statement.

        For example, if all branches of a nested case set next_wr = 1, we return {'next_wr': <node for 1>}

        Args:
            case_stmt: The nested case statement
            graph: ResourceGraph

        Returns:
            Dict mapping target_id -> source_node for common assignments
        """
        # Collect assignments from each non-default branch
        branch_assignments = []  # List of {target_id: source_node} dicts, one per branch

        for item in case_stmt.items:
            # Skip default case (we only care about non-default branches)
            is_default = False
            for match_expr in item.expressions:
                if hasattr(match_expr, 'kind') and match_expr.kind == pyslang.ExpressionKind.EmptyArgument:
                    is_default = True
                    break

            if is_default:
                continue

            # Extract all assignments in this branch
            branch_assign = {}
            self._collect_all_assignments(item.stmt, branch_assign, graph)
            if branch_assign:
                branch_assignments.append(branch_assign)

        if not branch_assignments:
            return {}

        # Find assignments that appear in all branches with the same source value
        common = {}
        first_branch = branch_assignments[0]

        for target_id, source_node in first_branch.items():
            # Check if this assignment appears in all other branches with same source
            appears_in_all = True
            for branch in branch_assignments[1:]:
                if target_id not in branch:
                    appears_in_all = False
                    break
                # Check if source is the same (by node ID)
                if branch[target_id].id != source_node.id:
                    appears_in_all = False
                    break

            if appears_in_all:
                common[target_id] = source_node
                print(f"[NESTED_CASE] Found common assignment: {target_id} = {source_node.id} (in all {len(branch_assignments)} non-default branches)")

        return common

    def _collect_all_assignments(self, stmt, assignments: dict, graph: ResourceGraph):
        """
        Recursively collect all assignments in a statement into a dict.

        Args:
            stmt: Statement to scan
            assignments: Dict to populate with target_id -> source_node
            graph: ResourceGraph
        """
        if stmt.kind == pyslang.StatementKind.Block:
            self._collect_all_assignments(stmt.body, assignments, graph)
            return

        if stmt.kind == pyslang.StatementKind.List:
            for substmt in stmt.list:
                self._collect_all_assignments(substmt, assignments, graph)
            return

        if stmt.kind == pyslang.StatementKind.Conditional:
            # Collect assignments from both branches of the conditional
            if hasattr(stmt, 'ifTrue'):
                self._collect_all_assignments(stmt.ifTrue, assignments, graph)
            if hasattr(stmt, 'ifFalse') and stmt.ifFalse:
                self._collect_all_assignments(stmt.ifFalse, assignments, graph)
            return

        if stmt.kind == pyslang.StatementKind.ExpressionStatement:
            if hasattr(stmt, 'expr'):
                expr = stmt.expr
                if expr.kind == pyslang.ExpressionKind.Assignment:
                    target_node = self._expression_to_node(expr.left, graph)
                    source_node = self._expression_to_node(expr.right, graph)
                    if target_node and source_node:
                        assignments[target_node.id] = source_node

    def _parse_invalid_via_syntax(self, syntax, graph: ResourceGraph, depth: int = 0, assignment_context=None) -> None:
        """
        DEPRECATED: This method is no longer used.

        Previously attempted to parse statements from syntax tree when semantic tree was Invalid.
        This was a source of bugs and technical debt. The parser now fails with a clear error
        message instead of falling back to syntactic parsing.

        Kept for reference only. Will be removed in a future cleanup.

        Args:
            syntax: Syntax node from slang
            graph: ResourceGraph to add nodes/edges to
            depth: Recursion depth for debugging
            assignment_context: Dict tracking assignments in procedural blocks for versioning
        """
        if assignment_context is None:
            assignment_context = {}
        indent = "  " * depth

        # Get the syntax kind
        syntax_kind = syntax.kind
        print(f"{indent}[SYNTAX] Processing syntax kind: {syntax_kind}")

        # Handle timing control statement (always @*)
        if syntax_kind == pyslang.SyntaxKind.TimingControlStatement:
            print(f"{indent}[SYNTAX]   TimingControlStatement - getting inner statement")
            if hasattr(syntax, 'statement') and syntax.statement:
                self._parse_invalid_via_syntax(syntax.statement, graph, depth+1, assignment_context)
            return

        # Handle sequential block statement (begin...end)
        if syntax_kind == pyslang.SyntaxKind.SequentialBlockStatement:
            print(f"{indent}[SYNTAX]   SequentialBlockStatement with {len(syntax.items)} items")
            for idx, item in enumerate(syntax.items):
                print(f"{indent}[SYNTAX]     Item {idx}: {item.kind}")
                self._parse_invalid_via_syntax(item, graph, depth+1, assignment_context)
            return

        # Handle expression statement (most assignments)
        if syntax_kind == pyslang.SyntaxKind.ExpressionStatement:
            print(f"{indent}[SYNTAX]   ExpressionStatement")
            if hasattr(syntax, 'expr') and syntax.expr:
                # Try to convert syntax expression to semantic expression
                self._parse_syntax_expression_as_assignment(syntax.expr, graph, depth, assignment_context)
            return

        # Handle conditional statement (if/else)
        if syntax_kind == pyslang.SyntaxKind.ConditionalStatement:
            print(f"{indent}[SYNTAX]   ConditionalStatement")

            # Check if condition is compile-time constant (e.g., parameter-based)
            # If so, only process the taken branch
            condition_is_constant = False
            take_if_branch = True  # default if we can't determine

            # Try to get the condition and check if it's been evaluated to a constant
            # Note: syntax tree doesn't have .constant, need to check the condition value differently
            if hasattr(syntax, 'predicate') and syntax.predicate:
                # Try to convert syntax predicate to string and check for parameter values
                pred_str = str(syntax.predicate) if hasattr(syntax.predicate, '__str__') else None
                print(f"{indent}[SYNTAX]     Predicate: {pred_str[:100] if pred_str else 'unknown'}")

                # Special case: RESET_STRATEGY comparisons
                # RESET_STRATEGY is "MINI" (0x4d494e49), so:
                # - RESET_STRATEGY == "NONE" is always false
                # - RESET_STRATEGY != "NONE" is always true
                if pred_str and 'RESET_STRATEGY' in pred_str:
                    if 'RESET_STRATEGY == "NONE"' in pred_str or "RESET_STRATEGY == 'NONE'" in pred_str:
                        condition_is_constant = True
                        take_if_branch = False  # MINI != NONE
                        print(f"{indent}[SYNTAX]     RESET_STRATEGY == NONE is always false -> taking else branch")
                    elif '!=' in pred_str and 'NONE' in pred_str:
                        condition_is_constant = True
                        take_if_branch = True  # MINI != NONE
                        print(f"{indent}[SYNTAX]     RESET_STRATEGY != NONE is always true -> taking if branch")

            if condition_is_constant:
                # Only process the taken branch
                if take_if_branch:
                    if hasattr(syntax, 'statement') and syntax.statement:
                        print(f"{indent}[SYNTAX]     Processing if branch (else eliminated)")
                        self._parse_invalid_via_syntax(syntax.statement, graph, depth+1, assignment_context)
                else:
                    if hasattr(syntax, 'elseClause') and syntax.elseClause:
                        print(f"{indent}[SYNTAX]     Processing else branch (if eliminated)")
                        if hasattr(syntax.elseClause, 'clause') and syntax.elseClause.clause:
                            self._parse_invalid_via_syntax(syntax.elseClause.clause, graph, depth+1, assignment_context)
            else:
                # Condition is not constant - process both branches (runtime mux)
                print(f"{indent}[SYNTAX]     Condition is not constant - processing both branches")
                if hasattr(syntax, 'statement') and syntax.statement:
                    print(f"{indent}[SYNTAX]     Processing if branch")
                    self._parse_invalid_via_syntax(syntax.statement, graph, depth+1, assignment_context)
                if hasattr(syntax, 'elseClause') and syntax.elseClause:
                    print(f"{indent}[SYNTAX]     Processing else branch")
                    if hasattr(syntax.elseClause, 'clause') and syntax.elseClause.clause:
                        self._parse_invalid_via_syntax(syntax.elseClause.clause, graph, depth+1, assignment_context)
            return

        # Handle case statement
        if syntax_kind == pyslang.SyntaxKind.CaseStatement:
            print(f"{indent}[SYNTAX]   CaseStatement")
            # Process case items
            if hasattr(syntax, 'items') and syntax.items:
                for item in syntax.items:
                    if hasattr(item, 'clause') and item.clause:
                        self._parse_invalid_via_syntax(item.clause, graph, depth+1, assignment_context)
            return

        # Unknown syntax kind
        print(f"{indent}[SYNTAX]   Unhandled syntax kind: {syntax_kind}")

    def _parse_syntax_expression_as_assignment(self, expr_syntax, graph: ResourceGraph, depth: int, assignment_context=None) -> None:
        """
        Parse a syntax-level expression and try to process it as an assignment.

        Args:
            expr_syntax: Expression syntax node
            graph: ResourceGraph to add edges to
            depth: Recursion depth for debugging
            assignment_context: Dict tracking assignments in procedural blocks for versioning
        """
        if assignment_context is None:
            assignment_context = {}

        indent = "  " * depth

        # Check if this looks like an assignment
        # In SystemVerilog syntax, assignments are BinaryExpression with = operator
        if expr_syntax.kind == pyslang.SyntaxKind.AssignmentExpression:
            print(f"{indent}[SYNTAX]     AssignmentExpression found")

            # Extract left and right sides as strings
            if hasattr(expr_syntax, 'left') and hasattr(expr_syntax, 'right'):
                # Get the text representation and clean it
                left_text = self._extract_clean_text(expr_syntax.left)
                right_text = self._extract_clean_text(expr_syntax.right)

                print(f"{indent}[SYNTAX]       Assignment: {left_text} = {right_text}")

                # Try to find or create nodes for left and right
                # The left side is the target (should exist in graph already)
                target_node = None
                if left_text in graph.nodes:
                    target_node = graph.nodes[left_text]
                else:
                    print(f"{indent}[SYNTAX]       Warning: Target '{left_text}' not in graph")

                # For the right side, parse the syntax tree to create proper edges
                # Use _parse_syntax_tree_expression to handle binary ops, etc.
                # IMPORTANT: Before parsing the source, check if it references the target
                # If so, we need to use a versioned intermediate node
                source_node = self._parse_syntax_tree_expression_with_versioning(
                    expr_syntax.right, graph, None, target_node, assignment_context
                )

                # Create assignment edge if we have both nodes
                if target_node and source_node:
                    edge_data = {'type': 'assignment', 'assign_type': 'blocking'}
                    edge = Edge(source_node, target_node, data=edge_data)
                    graph.add_edge(edge)
                    print(f"{indent}[SYNTAX]       Created assignment edge: {source_node.id[:40]} -> {target_node.id[:40]}")

                    # Track this assignment for future references
                    # If target is assigned again, we'll create a versioned node
                    if target_node.id not in assignment_context:
                        assignment_context[target_node.id] = []
                    assignment_context[target_node.id].append((len(assignment_context[target_node.id]), source_node))
                    print(f"{indent}[SYNTAX]       Tracked assignment #{len(assignment_context[target_node.id])} to {target_node.id}")

                else:
                    if not target_node:
                        print(f"{indent}[SYNTAX]       Skipping - no target node")
                    if not source_node:
                        print(f"{indent}[SYNTAX]       Skipping - no source node")
        else:
            print(f"{indent}[SYNTAX]     Not an assignment (kind={expr_syntax.kind})")

    def _extract_clean_text(self, syntax_node) -> str:
        """
        Extract clean text from a syntax node, removing comments and extra whitespace.

        Args:
            syntax_node: Syntax node to extract text from

        Returns:
            Cleaned text string
        """
        # Convert to string
        text = str(syntax_node)

        # Remove single-line comments (// ...)
        import re
        text = re.sub(r'//[^\n]*', '', text)

        # Remove multi-line comments (/* ... */)
        text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)

        # Collapse whitespace
        text = ' '.join(text.split())

        return text.strip()

    def _parse_syntax_expr_to_node(self, expr_text: str, graph: ResourceGraph) -> Optional[Node]:
        """
        Parse a syntax expression string and create/find a node for it.

        Args:
            expr_text: String representation of the expression
            graph: ResourceGraph to search/add to

        Returns:
            Node representing the expression, or None if parsing failed
        """
        # First check if it's a simple reference to an existing node
        if expr_text in graph.nodes:
            return graph.nodes[expr_text]

        # Check for simple literals
        if expr_text.isdigit() or (expr_text.startswith("'") or expr_text.startswith("32'")):
            # Constant literal
            node_id = f"const_{expr_text}"
            if node_id in graph.nodes:
                return graph.nodes[node_id]
            else:
                # Create constant node
                node = Node(node_id, data={'type': 'constant', 'value': expr_text})
                graph.add_node(node)
                return node

        # For complex expressions, create an expression node
        # This is a simplified approach - ideally we'd parse the expression tree
        node_id = expr_text[:100]  # Limit length
        if node_id in graph.nodes:
            return graph.nodes[node_id]
        else:
            # Create expression node
            node = Node(node_id, data={'type': 'expression', 'expr': expr_text})
            graph.add_node(node)
            return node

    def _process_assignment_expr(self, expr, graph: ResourceGraph, assignment_context=None) -> None:
        """
        Process an assignment expression and create edges.

        Args:
            expr: Assignment expression from slang
            graph: ResourceGraph to add edges to
            assignment_context: Dict tracking assignments in procedural blocks for versioning
        """
        if assignment_context is None:
            assignment_context = {}

        # Get target node (may be a bit_slice for partial assignments like data[31:2] <= ...)
        target_node = self._expression_to_node(expr.left, graph)

        # DEBUG: Track what's being processed
        if target_node:
            target_name = target_node.id[:50]
        else:
            target_name = str(expr.left)[:50] if hasattr(expr, 'left') else "unknown"

        if not target_node:
            print(f"  [PARSER] Skipping assignment - no target node for: {target_name}")
            return

        # CRITICAL FIX: Check if target is a bit slice (partial register assignment)
        # For assignments like `data[31:2] <= expr`, we need to create the assignment
        # to the parent register `data`, not to the bit_slice node `data[31:2]`
        partial_assignment_info = None
        if target_node.data.get('type') == 'bit_slice':
            # This is a partial assignment - extract parent register info
            parent_name = target_node.data.get('value')
            high_bit = target_node.data.get('high')
            low_bit = target_node.data.get('low')

            print(f"  [PARSER] Detected partial assignment: {parent_name}[{high_bit}:{low_bit}] <= ...")

            # Find or create the parent register node
            parent_node = graph.nodes.get(parent_name)
            if not parent_node:
                print(f"  [PARSER] ERROR: Parent register {parent_name} not found for partial assignment!")
                return

            # Store partial assignment metadata for the edge
            partial_assignment_info = {
                'partial_assignment': True,
                'bit_slice': target_node.id,
                'high': high_bit,
                'low': low_bit
            }

            # Redirect target to parent register
            target_node = parent_node
            target_name = parent_name
            print(f"  [PARSER] Redirected assignment target to parent register: {target_name}")

        # TODO: For semantic tree assignments, we don't have the syntax tree readily available
        # So we can't easily implement versioning for these. For now, just parse normally.
        # Most assignments go through the Invalid/syntax path anyway.
        source_node = self._expression_to_node(expr.right, graph)

        if not source_node:
            print(f"  [PARSER] Skipping assignment - no source node for target: {target_name}")
            return

        # Create edge or conditional mux
        assign_type = 'non_blocking' if expr.isNonBlocking else 'blocking'

        # Check if this assignment is inside an if statement
        if '__current_condition__' in assignment_context and assignment_context['__current_condition__']:
            condition_node = assignment_context['__current_condition__']
            print(f"  [PARSER] Conditional assignment to {target_name} on: {condition_node.id[:40]}")

            # Create conditional mux: condition ? new_value : target_itself
            # Using target_itself as the "else" creates a self-loop representing "keep previous value"
            # State splitting will properly handle this by creating _rd and _wr variants
            from core.mux_utils import MuxBuilder, MuxType

            mux_id = f"conditional_mux_{target_node.id}_{condition_node.id[:30]}"
            builder = MuxBuilder(graph, mux_id, MuxType.PRIORITY)
            builder.create_or_get_mux(display_name=f"if({condition_node.id[:20]})")

            # Add inputs: if_true=source_node, if_false=target (self-loop for "keep value")
            builder.add_input(source_node, condition_node)  # if true, use new value
            builder.add_default_input(target_node)  # if false, keep current value (self-loop)

            # Connect mux output to target with metadata
            edge_metadata = {'assign_type': assign_type}
            if partial_assignment_info:
                edge_metadata.update(partial_assignment_info)

            builder.connect_output(target_node, 'assignment', metadata=edge_metadata)

            if partial_assignment_info:
                print(f"  [PARSER] Created conditional mux with partial assignment: {condition_node.id[:30]} ? {source_node.id[:30]} : {target_node.id}")
            else:
                print(f"  [PARSER] Created conditional mux: {condition_node.id[:30]} ? {source_node.id[:30]} : {target_node.id}")

            # Track the mux output as the new assignment
            if target_node.id not in assignment_context:
                assignment_context[target_node.id] = []
            assignment_context[target_node.id].append((len(assignment_context[target_node.id]), builder.mux_node))
        else:
            # Unconditional assignment - create normal edge
            edge_data = {'type': 'assignment', 'assign_type': assign_type}

            # Add partial assignment metadata if this is a bit slice assignment
            if partial_assignment_info:
                edge_data.update(partial_assignment_info)

            edge = Edge(source_node, target_node, data=edge_data)
            graph.add_edge(edge)

            if partial_assignment_info:
                print(f"  [PARSER] Added {assign_type} partial assignment: {source_node.id[:40]} -> {target_name}[{partial_assignment_info['high']}:{partial_assignment_info['low']}]")
            else:
                print(f"  [PARSER] Added {assign_type} assignment: {source_node.id[:40]} -> {target_name}")

            # Track assignment
            if target_node.id not in assignment_context:
                assignment_context[target_node.id] = []
            assignment_context[target_node.id].append((len(assignment_context[target_node.id]), source_node))
            print(f"  [PARSER] Tracked assignment #{len(assignment_context[target_node.id])} to {target_node.id}")

    def _expression_to_node(self, expr, graph: ResourceGraph) -> Optional[Node]:
        """
        Convert a pyslang expression to a ResourceGraph node.

        Args:
            expr: Expression from slang
            graph: ResourceGraph to add nodes to

        Returns:
            Node representing the expression, or None if unsupported
        """
        # CRITICAL: Check if this expression has been elaborated to a constant by pyslang
        # This handles ALL parameter-based expressions (comparisons, arithmetic, ternary, etc.)
        # Pyslang evaluates these at elaboration time, so we should use the constant value
        # instead of creating operation nodes
        if hasattr(expr, 'constant') and expr.constant is not None:
            try:
                # Debug: check what kind of constant we have
                # print(f"  [CONSTANT-DEBUG] Expression has constant attribute: {type(expr.constant)}")
                # print(f"  [CONSTANT-DEBUG] Constant attributes: {[a for a in dir(expr.constant) if not a.startswith('_')]}")

                # Get the elaborated constant value
                const_val = expr.constant.integer if hasattr(expr.constant, 'integer') else None
                if const_val is not None:
                    # Create a constant node instead of an operation node
                    const_id = f"const_{const_val.value}_{id(expr)}"
                    if const_id not in graph.nodes:
                        const_node = Node(
                            const_id,
                            data={
                                'type': 'constant',
                                'value': const_val.value,
                                'bit_width': const_val.getBitWidth() if hasattr(const_val, 'getBitWidth') else 32,
                                'display_name': str(const_val.value)
                            }
                        )
                        graph.add_node(const_node)
                        print(f"  [CONSTANT] Folded expression to constant: {const_val.value} (width={const_val.getBitWidth() if hasattr(const_val, 'getBitWidth') else 32})")
                    return graph.nodes[const_id]
            except Exception as e:
                # If we can't extract the constant, fall through to regular processing
                print(f"  [CONSTANT] Warning: Failed to extract constant value: {e}")

        expr_kind = expr.kind

        # Named value (variable reference or parameter)
        if expr_kind == pyslang.ExpressionKind.NamedValue:
            if hasattr(expr, 'symbol'):
                symbol_name = expr.symbol.name

                # Check if this is a parameter that hasn't been added yet
                # Parameters are NOT prefixed because they're module-level constants
                if expr.symbol.kind == pyslang.SymbolKind.Parameter:
                    if symbol_name in graph.nodes:
                        return graph.nodes[symbol_name]

                    param_data = {
                        'type': 'parameter',
                        'name': symbol_name,
                        'display_name': symbol_name
                    }
                    # Try to get the parameter's default value
                    try:
                        if hasattr(expr.symbol, 'value') and expr.symbol.value is not None:
                            param_data['value'] = str(expr.symbol.value)
                            param_data['verilog_value'] = str(expr.symbol.value)
                    except Exception as e:
                        print(f"[PARAM] {symbol_name}: error getting value: {e}")

                    param_node = Node(symbol_name, param_data)
                    graph.add_node(param_node)
                    print(f"[PARAM] Created parameter node: {symbol_name} = {param_data.get('value', 'unknown')}")
                    return param_node

                # For regular variables (nets, vars, logic), use prefixed name
                # This ensures expressions reference the correct prefixed signal
                prefixed_name = self._get_signal_prefix(symbol_name)
                if prefixed_name in graph.nodes:
                    return graph.nodes[prefixed_name]

                # Node doesn't exist yet - create it with prefixed name
                # This handles cases like: if (!stall) mem_rd_enable_q <= mem_rd_enable;
                # where mem_rd_enable is a variable that might not have a node yet
                var_data = {
                    'type': 'variable',
                    'name': prefixed_name,
                    'original_name': symbol_name,
                    'display_name': symbol_name
                }
                var_node = Node(prefixed_name, var_data)
                graph.add_node(var_node)
                print(f"[VAR] Created variable node for reference: {symbol_name} → {prefixed_name}")
                return var_node
            return None

        # Binary operation (e.g., a + b)
        elif expr_kind == pyslang.ExpressionKind.BinaryOp:
            # Get operator
            op = str(expr.op).split('.')[-1]  # Extract operator name from enum

            # Check if operands are signed (for signed comparisons/operations)
            # In Verilog, $signed(a) < $signed(b) means the comparison operates on signed values
            # pyslang represents this by having signed types on the operands
            left_is_signed = False
            right_is_signed = False
            if hasattr(expr.left, 'type') and hasattr(expr.left.type, 'isSigned'):
                left_is_signed = expr.left.type.isSigned
            if hasattr(expr.right, 'type') and hasattr(expr.right.type, 'isSigned'):
                right_is_signed = expr.right.type.isSigned

            # Process operands
            left_node = self._expression_to_node(expr.left, graph)
            right_node = self._expression_to_node(expr.right, graph)

            # If operands are signed but the nodes don't reflect this, wrap them
            # This handles cases where $signed() cast is implicit in the type system
            if left_is_signed and left_node and not left_node.id.startswith('$signed('):
                # Don't wrap if it's already a cast node (avoid double-wrapping cast outputs)
                if left_node.data.get('type') != 'cast':
                    cast_id = f"$signed({left_node.id})"
                    if cast_id not in graph.nodes:
                        cast_node = Node(cast_id, data={'type': 'cast', 'cast_type': 'signed', 'display_name': cast_id})
                        graph.add_node(cast_node)
                        Edge(left_node, cast_node, data={'type': 'operand'})
                        graph.add_edge(Edge(left_node, cast_node, data={'type': 'operand'}))
                    left_node = graph.nodes[cast_id]
                    print(f"[BINARYOP] Created signed cast for left operand: {left_node.id[:60]}")

            if right_is_signed and right_node and not right_node.id.startswith('$signed('):
                # Don't wrap if it's already a cast node (avoid double-wrapping cast outputs)
                if right_node.data.get('type') != 'cast':
                    cast_id = f"$signed({right_node.id})"
                    if cast_id not in graph.nodes:
                        cast_node = Node(cast_id, data={'type': 'cast', 'cast_type': 'signed', 'display_name': cast_id})
                        graph.add_node(cast_node)
                        graph.add_edge(Edge(right_node, cast_node, data={'type': 'operand'}))
                    right_node = graph.nodes[cast_id]
                    print(f"[BINARYOP] Created signed cast for right operand: {right_node.id[:60]}")

            # Create operation node
            node_id = f"({left_node.id if left_node else '?'} {op} {right_node.id if right_node else '?'})"
            if node_id in graph.nodes:
                return graph.nodes[node_id]

            node_data = {
                'type': 'operation',
                'operator': op,
                'display_name': node_id
            }
            op_node = Node(node_id, node_data)
            graph.add_node(op_node)

            # Create edges from operands to operation
            if left_node:
                edge = Edge(left_node, op_node, data={'type': 'operand', 'position': 'left'})
                graph.add_edge(edge)
            if right_node:
                edge = Edge(right_node, op_node, data={'type': 'operand', 'position': 'right'})
                graph.add_edge(edge)

            return op_node

        # Integer literal
        elif expr_kind == pyslang.ExpressionKind.IntegerLiteral:
            # Get the value - pyslang provides it as a formatted string
            # Note: Don't use "if expr.value" because value might be 0 (falsy)
            if hasattr(expr, 'value') and expr.value is not None:
                node_id = str(expr.value)
            else:
                node_id = "literal"

            if node_id in graph.nodes:
                return graph.nodes[node_id]

            node_data = {
                'type': 'literal',
                'display_name': node_id,
                'value': node_id  # Store the literal value
            }
            lit_node = Node(node_id, node_data)
            graph.add_node(lit_node)
            return lit_node

        # Conversion/cast
        elif expr_kind == pyslang.ExpressionKind.Conversion:
            # Check if this is a signed conversion - if so, create a cast node
            if hasattr(expr, 'operand'):
                operand_kind = str(expr.operand.kind).split('.')[-1] if hasattr(expr.operand, 'kind') else 'unknown'
                operand_node = self._expression_to_node(expr.operand, graph)
                if operand_node is None:
                    print(f"[CONVERSION] Warning: conversion operand returned None")
                    print(f"  Conversion type: {expr.type if hasattr(expr, 'type') else 'unknown'}")
                    print(f"  Operand kind: {operand_kind}")
                    print(f"  Operand: {expr.operand}")
                    return None

                # Check if this is a signed conversion (e.g., $signed())
                is_signed_conversion = False
                if hasattr(expr, 'type') and hasattr(expr.type, 'isSigned'):
                    # Check if the result type is signed
                    is_signed_conversion = expr.type.isSigned
                    # Also check if the operand type is different signedness (actual conversion)
                    if hasattr(expr.operand, 'type') and hasattr(expr.operand.type, 'isSigned'):
                        operand_signed = expr.operand.type.isSigned
                        # Try multiple ways to get bit width from pyslang
                        operand_width = None
                        if hasattr(expr.operand.type, 'width'):
                            operand_width = expr.operand.type.width
                        elif hasattr(expr.operand.type, 'bitWidth'):
                            operand_width = expr.operand.type.bitWidth
                        elif hasattr(expr.operand.type, 'getBitWidth'):
                            operand_width = expr.operand.type.getBitWidth()

                        result_width = None
                        if hasattr(expr.type, 'width'):
                            result_width = expr.type.width
                        elif hasattr(expr.type, 'bitWidth'):
                            result_width = expr.type.bitWidth
                        elif hasattr(expr.type, 'getBitWidth'):
                            result_width = expr.type.getBitWidth()

                        print(f"[CONVERSION] operand={operand_node.id[:40]}, operand_signed={operand_signed}, result_signed={expr.type.isSigned}, operand_width={operand_width}, result_width={result_width}")
                        if operand_signed == is_signed_conversion and operand_width == result_width:
                            # Not actually converting signedness OR width, just a no-op cast
                            is_signed_conversion = False
                        elif result_width and operand_width and result_width > operand_width and expr.type.isSigned:
                            # This is a sign extension (e.g., $signed(8-bit) to 32-bit)
                            # Always create the cast node for sign extension
                            print(f"[CONVERSION] Sign extension detected: {operand_width} -> {result_width}")
                            is_signed_conversion = True

                # If this is a signed conversion, create a cast node
                if is_signed_conversion:
                    cast_node_id = f"$signed({operand_node.id})"
                    if cast_node_id in graph.nodes:
                        return graph.nodes[cast_node_id]

                    cast_node = Node(cast_node_id, data={
                        'type': 'cast',
                        'cast_type': 'signed',
                        'display_name': cast_node_id
                    })
                    graph.add_node(cast_node)
                    edge = Edge(operand_node, cast_node, data={'type': 'operand'})
                    graph.add_edge(edge)
                    return cast_node
                else:
                    # Not a signed conversion, just follow through
                    return operand_node
            print(f"[CONVERSION] Warning: conversion has no operand attribute")
            return None

        # Unary operation
        elif expr_kind == pyslang.ExpressionKind.UnaryOp:
            op = str(expr.op).split('.')[-1]
            operand_node = self._expression_to_node(expr.operand, graph)

            node_id = f"({op} {operand_node.id if operand_node else '?'})"
            if node_id in graph.nodes:
                return graph.nodes[node_id]

            node_data = {
                'type': 'operation',
                'operator': op,
                'unary': True,
                'display_name': node_id
            }
            op_node = Node(node_id, node_data)
            graph.add_node(op_node)

            if operand_node:
                edge = Edge(operand_node, op_node, data={'type': 'operand'})
                graph.add_edge(edge)

            return op_node

        # Element select (array indexing) - e.g., regfile[5] or mem[addr]
        elif expr_kind == pyslang.ExpressionKind.ElementSelect:
            # Get the array and index
            array_node = self._expression_to_node(expr.value, graph)
            index_node = self._expression_to_node(expr.selector, graph)

            # Create a node for the array access
            array_name = array_node.id if array_node else "?"
            index_name = index_node.id if index_node else "?"
            node_id = f"{array_name}[{index_name}]"

            if node_id in graph.nodes:
                return graph.nodes[node_id]

            node_data = {
                'type': 'array_access',
                'display_name': node_id,
                'array': array_name,
                'index': index_name
            }
            access_node = Node(node_id, node_data)
            graph.add_node(access_node)

            # Create edges
            if array_node:
                edge = Edge(array_node, access_node, data={'type': 'array_base'})
                graph.add_edge(edge)
            if index_node:
                edge = Edge(index_node, access_node, data={'type': 'array_index'})
                graph.add_edge(edge)

            return access_node

        # Range select (bit slicing) - e.g., x[15:8]
        elif expr_kind == pyslang.ExpressionKind.RangeSelect:
            # Get the value being sliced
            value_node = self._expression_to_node(expr.value, graph)

            # Get the range bounds - use pyslang's elaborated constant values if available
            # This avoids storing symbolic expressions like "($signed(width) Subtract $signed(1))"
            if hasattr(expr.left, 'constant') and expr.left.constant:
                # Use elaborated constant value (pyslang ConstantValue)
                left_val = expr.left.constant.convertToInt()
                left_name = str(left_val)
                left_node = None  # No need for a node
            else:
                # Non-constant expression - create a node
                left_node = self._expression_to_node(expr.left, graph)
                left_name = left_node.id if left_node else "?"

            if hasattr(expr.right, 'constant') and expr.right.constant:
                # Use elaborated constant value (pyslang ConstantValue)
                right_val = expr.right.constant.convertToInt()
                right_name = str(right_val)
                right_node = None  # No need for a node
            else:
                # Non-constant expression - create a node
                right_node = self._expression_to_node(expr.right, graph)
                right_name = right_node.id if right_node else "?"

            # Create a node for the slice
            value_name = value_node.id if value_node else "?"
            node_id = f"{value_name}[{left_name}:{right_name}]"

            if node_id in graph.nodes:
                return graph.nodes[node_id]

            node_data = {
                'type': 'bit_slice',
                'display_name': node_id,
                'value': value_name,
                'high': int(left_name) if left_name.isdigit() else left_name,
                'low': int(right_name) if right_name.isdigit() else right_name
            }
            slice_node = Node(node_id, node_data)
            graph.add_node(slice_node)

            # Create edge from source value
            if value_node:
                edge = Edge(value_node, slice_node, data={'type': 'bit_slice_source'})
                graph.add_edge(edge)

            # Optionally create edges from the range expressions if they're not literals
            # (for variable-width slices, though uncommon)
            if left_node and left_node.data.get('type') != 'literal':
                edge = Edge(left_node, slice_node, data={'type': 'slice_high'})
                graph.add_edge(edge)
            if right_node and right_node.data.get('type') != 'literal':
                edge = Edge(right_node, slice_node, data={'type': 'slice_low'})
                graph.add_edge(edge)

            return slice_node

        # Ternary operator (conditional operator) - e.g., sel ? a : b
        elif expr_kind == pyslang.ExpressionKind.ConditionalOp:
            from core.mux_utils import MuxBuilder, MuxType

            # Get condition, true value, and false value
            conds = list(expr.conditions)
            if not conds:
                return None

            condition_node = self._expression_to_node(conds[0].expr, graph)
            true_node = self._expression_to_node(expr.left, graph)
            false_node = self._expression_to_node(expr.right, graph)

            # Create a unique mux ID
            cond_name = condition_node.id if condition_node else "?"
            true_name = true_node.id if true_node else "?"
            false_name = false_node.id if false_node else "?"
            mux_id = f"ternary_mux_{cond_name}_{true_name}_{false_name}"

            # Check if mux already exists
            if mux_id in graph.nodes:
                return graph.nodes[mux_id]

            # Create mux using MuxBuilder
            builder = MuxBuilder(graph, mux_id, MuxType.PRIORITY)
            builder.create_or_get_mux(display_name=f"{cond_name} ? {true_name} : {false_name}")

            # Add inputs: true value (when condition is true), false value (when condition is false)
            if true_node and condition_node:
                builder.add_input(true_node, condition_node)  # Selected when condition is true
            if false_node:
                builder.add_default_input(false_node)  # Default/fallback case

            # Return the mux node
            mux_node = graph.nodes.get(mux_id)
            return mux_node

        # Concatenation - e.g., {a, b, c}
        elif expr_kind == pyslang.ExpressionKind.Concatenation:
            # Get all operands
            operands = list(expr.operands)
            operand_nodes = []
            operand_names = []

            for op in operands:
                op_node = self._expression_to_node(op, graph)
                if op_node:
                    operand_nodes.append(op_node)
                    operand_names.append(op_node.id)

            # Create concatenation node
            node_id = "{" + ", ".join(operand_names) + "}"

            if node_id in graph.nodes:
                return graph.nodes[node_id]

            node_data = {
                'type': 'concatenation',
                'display_name': node_id,
                'num_operands': len(operand_nodes)
            }
            concat_node = Node(node_id, node_data)
            graph.add_node(concat_node)

            # Create edges from operands
            for idx, op_node in enumerate(operand_nodes):
                edge = Edge(op_node, concat_node, data={'type': 'concat_input', 'index': idx})
                graph.add_edge(edge)

            return concat_node

        # Replication - e.g., {4{byte}}
        elif expr_kind == pyslang.ExpressionKind.Replication:
            # Get count and concatenation expression
            count_node = self._expression_to_node(expr.count, graph)
            concat_node = self._expression_to_node(expr.concat, graph)

            count_name = count_node.id if count_node else "?"
            concat_name = concat_node.id if concat_node else "?"

            # Create replication node
            node_id = "{" + count_name + concat_name + "}"

            if node_id in graph.nodes:
                return graph.nodes[node_id]

            node_data = {
                'type': 'replication',
                'display_name': node_id,
                'count': count_name
            }
            repl_node = Node(node_id, node_data)
            graph.add_node(repl_node)

            # Create edges
            if count_node:
                edge = Edge(count_node, repl_node, data={'type': 'repl_count'})
                graph.add_edge(edge)
            if concat_node:
                edge = Edge(concat_node, repl_node, data={'type': 'repl_value'})
                graph.add_edge(edge)

            return repl_node

        # Function call - handle system functions like $signed, $unsigned
        elif expr_kind == pyslang.ExpressionKind.Call:
            # Try different ways to get the function name
            func_name = None
            if hasattr(expr, 'subroutine'):
                if hasattr(expr.subroutine, 'name'):
                    func_name = str(expr.subroutine.name)
                elif hasattr(expr.subroutine, '__str__'):
                    func_name = str(expr.subroutine)

            # Also try checking if it's a system call conversion
            if hasattr(expr, 'isSystemCall') and expr.isSystemCall:
                # For system calls like $signed/$unsigned, check arguments
                if hasattr(expr, 'arguments') and len(expr.arguments) > 0:
                    # Just pass through the first argument for $signed/$unsigned
                    arg = expr.arguments[0]
                    return self._expression_to_node(arg, graph)

            if func_name:
                # For $signed and $unsigned, just pass through the argument
                if func_name in ['$signed', '$unsigned']:
                    if hasattr(expr, 'arguments') and len(expr.arguments) > 0:
                        # Get the first argument
                        arg = expr.arguments[0]
                        return self._expression_to_node(arg, graph)
                    else:
                        print(f"[CALL] Warning: {func_name} has no arguments")
                        return None
                else:
                    print(f"[CALL] Unsupported function call: {func_name}")
                    return None
            else:
                # Unknown call - try to pass through if it has arguments
                if hasattr(expr, 'arguments') and len(expr.arguments) == 1:
                    return self._expression_to_node(expr.arguments[0], graph)
                return None

        # For other expression types, return None for now
        else:
            # Could log unsupported expression types here
            return None

    def _get_bit_range(self, type_obj) -> tuple:
        """
        Get the bit range of a type.

        Args:
            type_obj: Type object from slang

        Returns:
            Tuple of (width, msb, lsb) where msb/lsb are None for zero-based ranges
        """
        import re

        try:
            # For unpacked arrays, skip to the element type to get the bit range
            # e.g., for "reg [31:0] memory [0:31]", we want [31:0], not [0:31]
            if hasattr(type_obj, 'isUnpackedArray') and type_obj.isUnpackedArray:
                if hasattr(type_obj, 'elementType'):
                    return self._get_bit_range(type_obj.elementType)

            # Try to get range from pyslang type directly (for packed types)
            if hasattr(type_obj, 'range'):
                r = type_obj.range
                msb = r.left
                lsb = r.right
                width = abs(msb - lsb) + 1
                # Only preserve non-zero-based ranges
                if lsb != 0:
                    return (width, msb, lsb)
                else:
                    return (width, None, None)

            # Try getBitWidth() first
            if hasattr(type_obj, 'getBitWidth'):
                return (type_obj.getBitWidth(), None, None)
            elif hasattr(type_obj, 'width'):
                return (type_obj.width, None, None)

            # For DeclaredType, try to access the underlying type
            if hasattr(type_obj, 'type'):
                underlying_type = type_obj.type
                # Recursively get bit range from underlying type
                return self._get_bit_range(underlying_type)

            # Parse bit width from string representation
            # Examples: "logic[31:0]" -> 32, "logic[4:0]" -> 5, "logic" -> 1
            type_str = str(type_obj)

            # Match pattern like [high:low]
            match = re.search(r'\[(\d+):(\d+)\]', type_str)
            if match:
                high = int(match.group(1))
                low = int(match.group(2))
                width = high - low + 1
                # Only preserve non-zero-based ranges
                if low != 0:
                    return (width, high, low)
                else:
                    return (width, None, None)

            # No bit range means scalar (1-bit) for logic/reg/wire types
            if 'logic' in type_str or 'reg' in type_str or 'wire' in type_str:
                return (1, None, None)

            # Default to 32 for unknown types
            return (32, None, None)
        except Exception as e:
            # On any error, default to 32
            return (32, None, None)

    def _get_bit_width(self, type_obj) -> int:
        """
        Get the bit width of a type.

        Args:
            type_obj: Type object from slang

        Returns:
            Bit width as integer
        """
        width, _, _ = self._get_bit_range(type_obj)
        return width


def parse_verilog_file(filename: str, top_module: Optional[str] = None) -> ResourceGraph:
    """
    Parse a Verilog/SystemVerilog file and return a ResourceGraph.

    Args:
        filename: Path to the Verilog file
        top_module: Optional name of the top module to use (if None, auto-detect)

    Returns:
        ResourceGraph representing the module
    """
    parser = VerilogParser()
    return parser.parse_file(filename, top_module=top_module)


def parse_verilog_text(verilog_text: str, module_name: str = "top") -> ResourceGraph:
    """
    Parse Verilog/SystemVerilog text and return a ResourceGraph.

    Args:
        verilog_text: SystemVerilog source code
        module_name: Name for the module

    Returns:
        ResourceGraph representing the module
    """
    parser = VerilogParser()
    return parser.parse_text(verilog_text, module_name)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m frontends.verilog.verilog_parser <verilog_file> [module_name]")
        sys.exit(1)

    filename = sys.argv[1]
    module_name = sys.argv[2] if len(sys.argv) > 2 else None
    graph = parse_verilog_file(filename, module_name)
    print(f"Parsed {filename}: {graph}")
    print(f"Found {len(graph.nodes)} nodes and {len(graph.edges)} edges")

    # Generate Verilog output
    if module_name:
        from backends.verilog import generate_verilog
        output_filename = f"{module_name}_exported.v"
        verilog_code = generate_verilog(graph, module_name)
        with open(output_filename, 'w') as f:
            f.write(verilog_code)
        print(f"Generated {output_filename}")
