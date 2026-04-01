"""
VHDL Parser using pyGHDL for isacomp
=====================================

This parser uses pyGHDL (Python bindings to GHDL) to parse VHDL files and
generate ResourceGraph IR for isacomp.

Key features:
- Full VHDL parser (no regex!)
- Detects arch_state attributes on signals
- Handles expressions, processes, and control flow
- Generates ResourceGraph with nodes and edges
"""

from pathlib import Path
from typing import Set, Dict, Optional
from pyGHDL.dom.NonStandard import Design, Document
import pyGHDL.libghdl.vhdl.nodes as nodes
from pyGHDL.libghdl import name_table
import pyGHDL.libghdl.vhdl.nodes_meta as nodes_meta

from core.resource_graph import ResourceGraph, Node, Edge


class VHDLParserPyGHDL:
    """VHDL parser using pyGHDL for isacomp"""

    def __init__(self):
        self.arch_state_signals: Set[str] = set()
        self.entity_name: Optional[str] = None
        self.graph: Optional[ResourceGraph] = None
        self.signal_nodes: Dict[str, Node] = {}
        self.variable_nodes: Dict[str, Node] = {}  # Track process variables
        self.constants: Dict[str, str] = {}  # Constant name -> value (as string)
        self._temp_var_counter = 0
        self._design: Optional[Design] = None
        # Hierarchical parsing support
        self.components: Dict[str, Dict] = {}  # component_name -> {ports: {}, ...}
        self.instances: Dict[str, Dict] = {}   # instance_name -> {component: str, port_map: {}}
        # Control flow tracking
        self._condition_stack: list = []  # Stack of condition nodes for nested if/case
        # Clock edge detection
        self._in_clocked_process: bool = False  # True when inside rising_edge(clk) block
        # Combinational default tracking (per process)
        self._process_defaults: Dict[str, Node] = {}  # Signal name -> default value node
        # Process tracking for variable scoping
        self._current_process_name: Optional[str] = None
        self._process_counter = 0  # For unnamed processes

    def parse_file(self, filename: str) -> ResourceGraph:
        """
        Parse a VHDL file and return a ResourceGraph.

        Args:
            filename: Path to the VHDL file

        Returns:
            ResourceGraph containing the parsed design
        """
        # Initialize pyGHDL (Design object handles this)
        self._design = Design()

        # Parse the VHDL file
        document = Document(Path(filename))

        # Create graph
        self.graph = ResourceGraph()

        # Extract entity name and ports
        if document.Entities:
            self.entity_name = list(document.Entities.keys())[0]
            entity = document.Entities[self.entity_name]
            self._extract_entity_ports(entity)

        # Process architectures
        for entity_name, arch_dict in document.Architectures.items():
            for arch_name, architecture in arch_dict.items():
                self._process_architecture(architecture)

        return self.graph

    def _process_architecture(self, architecture):
        """Process an architecture and extract signals, attributes, and logic"""

        # Phase 1: Extract arch_state attributes
        # This is CRITICAL for isacomp - we must identify ISA state signals
        self._extract_arch_state_attributes(architecture)

        # Phase 2: Extract component declarations
        self._extract_component_declarations(architecture)

        # Phase 2.5: Extract constant declarations
        self._extract_constant_declarations(architecture)

        # Phase 3: Create signal nodes
        self._create_signal_nodes(architecture)

        # Phase 4: Process statements to create edges
        self._process_statements(architecture)

        # Phase 4.5: Process low-level statements (catches what DOM drops)
        self._process_lowlevel_statements(architecture)

        # Phase 5: Extract component instantiations and build hierarchy
        self._extract_component_instantiations(architecture)

    def _extract_entity_ports(self, entity):
        """Extract and create nodes for entity ports (inputs/outputs)"""
        if not hasattr(entity, 'PortItems') or not entity.PortItems:
            return

        for port in entity.PortItems:
            if hasattr(port, 'Identifiers'):
                for ident in port.Identifiers:
                    port_name = str(ident)

                    # Determine port direction
                    port_mode = "unknown"
                    if hasattr(port, 'Mode'):
                        port_mode = str(port.Mode).lower()

                    # Extract bit width from type
                    width = None
                    if hasattr(port, 'Subtype'):
                        width = self._extract_bit_width_from_type(port.Subtype)

                    # Create standardized variable node for this port
                    # Ports are variables with direction metadata
                    node = self._create_variable_node(port_name, width=width, is_arch_state=False)

                    # Add port-specific metadata
                    node.data['direction'] = port_mode
                    node.data['is_port'] = True

                    self.graph.add_node(node)
                    # Use lowercase for case-insensitive lookups (VHDL is case-insensitive)
                    self.signal_nodes[port_name.lower()] = node

    def _extract_arch_state_attributes(self, architecture):
        """
        Extract arch_state attribute specifications from the architecture.

        CRITICAL: This identifies which signals are architectural state (ISA state).
        """
        for decl in architecture.DeclaredItems:
            # Look for AttributeSpecification objects
            if type(decl).__name__ == 'AttributeSpecification':
                # Check if this is an arch_state attribute
                if hasattr(decl, 'Attribute') and str(decl.Attribute) == 'arch_state':
                    # Get the signal names this attribute applies to
                    if hasattr(decl, 'Identifiers'):
                        for ident in decl.Identifiers:
                            signal_name = str(ident)
                            self.arch_state_signals.add(signal_name)
                            print(f"✓ Detected arch_state signal: {signal_name}")

    def _extract_component_declarations(self, architecture):
        """Extract component declarations to understand component interfaces"""
        for decl in architecture.DeclaredItems:
            decl_type = type(decl).__name__

            # Process component declarations
            if decl_type == 'Component':
                component_name = str(decl.Identifier) if hasattr(decl, 'Identifier') else None
                if not component_name:
                    continue

                # Extract port information from component declaration
                ports = {}
                if hasattr(decl, 'PortItems') and decl.PortItems:
                    for port in decl.PortItems:
                        if hasattr(port, 'Identifiers'):
                            for ident in port.Identifiers:
                                port_name = str(ident)
                                port_mode = str(port.Mode).lower() if hasattr(port, 'Mode') else "unknown"
                                ports[port_name] = {
                                    "direction": port_mode,
                                    "type": str(port.Subtype) if hasattr(port, 'Subtype') else "unknown"
                                }

                self.components[component_name] = {"ports": ports}
                print(f"  ✓ Found component: {component_name} ({len(ports)} ports)")

    def _convert_vhdl_literal_to_int(self, literal_str: str) -> int:
        """
        Convert VHDL literal strings to their decimal integer values.

        Args:
            literal_str: VHDL literal like "11" (binary), x"FF" (hex), '1' (bit)

        Returns:
            Integer value of the literal
        """
        literal_str = str(literal_str).strip()

        # Binary string literal: "101", "11", etc.
        if literal_str.startswith('"') and literal_str.endswith('"'):
            inner = literal_str[1:-1]
            # Check if all characters are binary digits
            if all(c in '01' for c in inner):
                return int(inner, 2)  # Convert binary to decimal
            # Otherwise might be other string literal, return 0
            return 0

        # Hex string literal: x"FF", x"DEADBEEF", etc.
        elif literal_str.lower().startswith('x"') and literal_str.endswith('"'):
            hex_part = literal_str[2:-1]
            return int(hex_part, 16)

        # Octal string literal: o"77", etc.
        elif literal_str.lower().startswith('o"') and literal_str.endswith('"'):
            oct_part = literal_str[2:-1]
            return int(oct_part, 8)

        # Character literal: '1', '0'
        elif literal_str.startswith("'") and literal_str.endswith("'"):
            char = literal_str[1:-1]
            if char in '01':
                return int(char)
            return 0

        # Already a number
        else:
            try:
                return int(literal_str)
            except ValueError:
                # Can't parse, return 0
                return 0

    def _extract_constant_declarations(self, architecture):
        """Extract constant declarations to preserve their values for code generation"""
        for decl in architecture.DeclaredItems:
            decl_type = type(decl).__name__

            # Process constant declarations
            if decl_type == 'Constant':
                # Constants can declare multiple identifiers with the same value
                if hasattr(decl, 'Identifiers') and hasattr(decl, 'DefaultExpression'):
                    const_value = None

                    # Try to extract the constant's value
                    expr = decl.DefaultExpression
                    expr_type = type(expr).__name__

                    if expr_type == 'StringLiteral':
                        # Bit string literal like "10", x"FFFFFFFF", etc.
                        # Get the raw string representation which includes quotes
                        const_value_str = str(expr)
                        # Convert binary/hex literals to decimal integer
                        const_value = self._convert_vhdl_literal_to_int(const_value_str)
                    elif expr_type == 'IntegerLiteral':
                        const_value = int(str(expr))
                    elif expr_type == 'CharacterLiteral':
                        const_value = self._convert_vhdl_literal_to_int(str(expr))
                    else:
                        # For other types, try to convert or use 0
                        try:
                            const_value = int(str(expr))
                        except:
                            const_value = 0

                    # Store the constant value for all identifiers
                    if const_value is not None:
                        for ident in decl.Identifiers:
                            const_name = str(ident)
                            self.constants[const_name] = const_value
                            print(f"  ✓ Found constant: {const_name} = {const_value}")

    def _create_signal_nodes(self, architecture):
        """Create nodes for all signals in the architecture"""
        for decl in architecture.DeclaredItems:
            decl_type = type(decl).__name__

            # Process signal declarations
            if decl_type == 'Signal':
                if hasattr(decl, 'Identifiers'):
                    for ident in decl.Identifiers:
                        signal_name = str(ident)

                        # Check if this signal is arch_state
                        is_arch_state = signal_name in self.arch_state_signals

                        # Extract bit width from type
                        width = None
                        if hasattr(decl, 'Subtype'):
                            width = self._extract_bit_width_from_type(decl.Subtype)

                        # Extract initial/default value if present
                        initial_value = None
                        if hasattr(decl, 'DefaultExpression') and decl.DefaultExpression is not None:
                            initial_value = self._extract_initial_value(decl.DefaultExpression)

                        # Create standardized variable or isa_state node
                        node = self._create_variable_node(signal_name, width=width, is_arch_state=is_arch_state,
                                                          initial_value=initial_value)

                        self.graph.add_node(node)
                        # Use lowercase for case-insensitive lookups (VHDL is case-insensitive)
                        self.signal_nodes[signal_name.lower()] = node

    def _process_statements(self, architecture):
        """Process concurrent statements in the architecture"""
        for stmt in architecture.Statements:
            stmt_type = type(stmt).__name__

            if stmt_type == 'ProcessStatement':
                self._process_process_statement(stmt)
            elif stmt_type == 'ConcurrentSimpleSignalAssignment':
                self._process_concurrent_assignment(stmt)
            elif stmt_type == 'ConcurrentConditionalSignalAssignment':
                self._process_concurrent_conditional(stmt)
            elif stmt_type == 'ConcurrentSelectedSignalAssignment':
                self._process_concurrent_selected(stmt)

    def _process_lowlevel_statements(self, architecture):
        """
        Process statements using low-level libghdl API.

        This catches concurrent conditional/selected statements that DOM drops.
        """
        # Access the raw IIR node from the architecture
        if not hasattr(architecture, '_iirNode'):
            return

        arch_node = architecture._iirNode
        if arch_node == nodes.Null_Iir:
            return

        # Get the concurrent statement chain
        stmt_chain = nodes.Get_Concurrent_Statement_Chain(arch_node)
        if stmt_chain == nodes.Null_Iir:
            return

        # Walk the chain
        stmt = stmt_chain
        while stmt != nodes.Null_Iir:
            kind = nodes.Get_Kind(stmt)

            if kind == nodes.Iir_Kind.Concurrent_Conditional_Signal_Assignment:
                self._process_lowlevel_conditional(stmt)
            elif kind == nodes.Iir_Kind.Concurrent_Selected_Signal_Assignment:
                self._process_lowlevel_selected(stmt)

            stmt = nodes.Get_Chain(stmt)

    def _extract_component_instantiations(self, architecture):
        """Extract component instantiations and build hierarchical connections"""
        for stmt in architecture.Statements:
            stmt_type = type(stmt).__name__

            # Look for component instantiations
            if stmt_type == 'ComponentInstantiation':
                self._process_component_instantiation(stmt)

    def _process_component_instantiation(self, inst):
        """Process a single component instantiation"""
        # Get instance label (e.g., i_alu)
        instance_name = str(inst.Label) if hasattr(inst, 'Label') else None
        if not instance_name:
            return

        # Get component name (e.g., alu)
        component_name = str(inst.Component) if hasattr(inst, 'Component') else None
        if not component_name:
            return

        # Clean up component name (remove '?' suffix from pyGHDL)
        component_name = component_name.rstrip('?')

        # Extract port map
        port_map = {}
        if hasattr(inst, 'PortAssociations') and inst.PortAssociations:
            for assoc in inst.PortAssociations:
                # Get formal (component port) and actual (signal) names
                formal = str(assoc.Formal) if hasattr(assoc, 'Formal') else None
                actual = str(assoc.Actual) if hasattr(assoc, 'Actual') else None

                if formal and actual:
                    # Clean up names (remove '?' suffix from pyGHDL)
                    formal = formal.rstrip('?')
                    actual = actual.rstrip('?')
                    port_map[formal] = actual

        # Store instance information
        self.instances[instance_name] = {
            "component": component_name,
            "port_map": port_map
        }

        # Create edges for hierarchical connections
        self._create_hierarchical_edges(instance_name, component_name, port_map)

        print(f"  ✓ Found instance: {instance_name} ({component_name}) with {len(port_map)} connections")

    def _create_hierarchical_edges(self, instance_name: str, component_name: str, port_map: Dict[str, str]):
        """Create edges representing hierarchical connections through component instances"""
        for formal_port, actual_signal in port_map.items():
            # Check if actual signal exists in our signal nodes (case-insensitive)
            if actual_signal.lower() in self.signal_nodes:
                actual_node = self.signal_nodes[actual_signal.lower()]

                # Create a hierarchical connection node
                conn_id = f"{instance_name}.{formal_port}"
                conn_node = Node(
                    node_id=conn_id,
                    data={
                        "type": "component_port",
                        "instance": instance_name,
                        "component": component_name,
                        "port": formal_port
                    }
                )
                self.graph.add_node(conn_node)

                # Determine edge direction based on port direction
                component_info = self.components.get(component_name)
                if component_info:
                    ports = component_info.get("ports", {})
                    port_info = ports.get(formal_port)
                    if port_info:
                        direction = port_info.get("direction", "unknown")

                        if direction == "in":
                            # Input port: signal -> component_port
                            edge = Edge(actual_node, conn_node, data={"type": "component_input"})
                            self.graph.add_edge(edge)
                        elif direction == "out":
                            # Output port: component_port -> signal
                            edge = Edge(conn_node, actual_node, data={"type": "component_output"})
                            self.graph.add_edge(edge)
                        elif direction == "inout":
                            # Bidirectional port: both directions
                            edge_in = Edge(actual_node, conn_node, data={"type": "component_inout"})
                            edge_out = Edge(conn_node, actual_node, data={"type": "component_inout"})
                            self.graph.add_edge(edge_in)
                            self.graph.add_edge(edge_out)

    def _process_process_statement(self, process):
        """Process a process statement"""
        if not hasattr(process, 'Statements') or not process.Statements:
            return

        # Get process label/name for variable scoping
        process_label = str(process.Label) if hasattr(process, 'Label') and process.Label else None
        if not process_label:
            # Generate a unique name for unnamed processes
            process_label = f"proc_{self._process_counter}"
            self._process_counter += 1

        # Save current process name for variable scoping
        prev_process_name = self._current_process_name
        self._current_process_name = process_label

        # Track combinational defaults (first unconditional assignment to each signal)
        # These represent the default values before any if/case branches
        self._process_defaults = {}  # Maps signal name -> default value node

        # Process statements inside the process
        for seq_stmt in process.Statements:
            self._process_sequential_statement(seq_stmt)

        # Clear process-specific tracking
        self._process_defaults = {}
        self._current_process_name = prev_process_name

    def _process_sequential_statement(self, stmt):
        """Process a sequential statement (inside a process)"""
        stmt_type = type(stmt).__name__

        if stmt_type == 'IfStatement':
            self._process_if_statement(stmt)
        elif stmt_type == 'CaseStatement':
            self._process_case_statement(stmt)
        elif stmt_type in ['SequentialSimpleSignalAssignment', 'SequentialSignalAssignment']:
            self._process_sequential_assignment(stmt)
        elif stmt_type in ['SequentialSimpleVariableAssignment', 'SimpleVariableAssignment', 'VariableAssignment']:
            self._process_variable_assignment(stmt)
        elif stmt_type == 'ForLoopStatement':
            self._process_for_loop(stmt)
        else:
            # Debug output for unrecognized statement types
            print(f"DEBUG: Unrecognized sequential statement type: {stmt_type}")

    def _process_if_statement(self, stmt):
        """Process an if statement - recursively process branches with condition tracking"""
        if not hasattr(stmt, 'IfBranch'):
            return

        # Process then branch with condition
        if_branch = stmt.IfBranch
        was_in_clocked = self._in_clocked_process  # Save state for nested ifs
        pushed_condition = False  # Track if we pushed a condition
        saved_condition_node = None  # Save the condition node for reuse in else branch

        if hasattr(if_branch, 'Condition'):
            # Check if this is a clock edge condition (rising_edge or falling_edge)
            condition_str = str(if_branch.Condition)
            if 'rising_edge' in condition_str.lower() or 'falling_edge' in condition_str.lower():
                self._in_clocked_process = True

            # Check if this is an always-true condition (like "1 = 1")
            # These are used to reserve structure and contain default assignments
            is_always_true = False
            if '1 = 1' in condition_str or '1=1' in condition_str:
                is_always_true = True

            # Parse condition expression and create condition node
            condition_node = self._parse_expression(if_branch.Condition)
            if condition_node:
                # Mark this node as a condition
                if condition_node.data is None:
                    condition_node.data = {}
                condition_node.data["is_condition"] = True

                # Save the condition node for potential reuse in else branch
                saved_condition_node = condition_node

                # Don't push always-true conditions onto stack (treat as unconditional)
                if not is_always_true:
                    # Push condition onto stack
                    self._condition_stack.append({
                        "node": condition_node,
                        "branch": "then",
                        "inverted": False
                    })
                    pushed_condition = True

        # Process then branch statements
        if hasattr(if_branch, 'Statements') and if_branch.Statements:
            for s in if_branch.Statements:
                self._process_sequential_statement(s)

        # Pop then condition (only if we pushed it)
        if pushed_condition and self._condition_stack:
            self._condition_stack.pop()

        # Process elsif branches (NOTE: attribute is ElsIfBranches, not ElsifBranches!)
        if hasattr(stmt, 'ElsIfBranches') and stmt.ElsIfBranches:
            for elsif in stmt.ElsIfBranches:
                if hasattr(elsif, 'Condition'):
                    condition_node = self._parse_expression(elsif.Condition)
                    if condition_node:
                        if condition_node.data is None:
                            condition_node.data = {}
                        condition_node.data["is_condition"] = True
                        self._condition_stack.append({
                            "node": condition_node,
                            "branch": "elsif",
                            "inverted": False
                        })

                if hasattr(elsif, 'Statements') and elsif.Statements:
                    for s in elsif.Statements:
                        self._process_sequential_statement(s)

                if self._condition_stack:
                    self._condition_stack.pop()

        # Process else branch (implicitly when all previous conditions are false)
        if hasattr(stmt, 'ElseBranch') and stmt.ElseBranch:
            # Else branch: all previous conditions were false
            # IMPORTANT: Reuse the saved condition node instead of parsing again
            # This prevents creating duplicate comparison nodes for the same condition
            if saved_condition_node:
                self._condition_stack.append({
                    "node": saved_condition_node,
                    "branch": "else",
                    "inverted": True  # else = NOT(condition)
                })

            if hasattr(stmt.ElseBranch, 'Statements') and stmt.ElseBranch.Statements:
                for s in stmt.ElseBranch.Statements:
                    self._process_sequential_statement(s)

            if self._condition_stack:
                self._condition_stack.pop()

        # Restore clocked process state (handle nested ifs)
        self._in_clocked_process = was_in_clocked

    def _process_case_statement(self, stmt):
        """Process a case statement - process all branches with choice tracking"""
        if not hasattr(stmt, 'Cases'):
            return

        # Get the case expression (what we're switching on)
        # Note: pyGHDL uses SelectExpression, not Expression
        case_expr_node = None
        if hasattr(stmt, 'SelectExpression'):
            case_expr_node = self._parse_expression(stmt.SelectExpression)
            if case_expr_node:
                if case_expr_node.data is None:
                    case_expr_node.data = {}
                case_expr_node.data["is_case_selector"] = True
        elif hasattr(stmt, 'Expression'):
            case_expr_node = self._parse_expression(stmt.Expression)
            if case_expr_node:
                if case_expr_node.data is None:
                    case_expr_node.data = {}
                case_expr_node.data["is_case_selector"] = True

        for case_idx, case in enumerate(stmt.Cases):
            # Get the choice values for this case branch
            choice_str = "unknown"
            case_type = type(case).__name__

            # Handle OthersCase specially - it doesn't have Choices attribute
            if case_type == 'OthersCase':
                choice_str = "others"
            elif hasattr(case, 'Choices') and case.Choices:
                # Convert choices to string representation
                choices = []
                for choice in case.Choices:
                    choice_type = type(choice).__name__
                    choice_value = str(choice)
                    # Check if this is an "others" choice
                    if choice_type == 'OthersChoice':
                        choice_value = "others"
                    choices.append(choice_value)
                choice_str = ", ".join(choices)


            # DEBUG: Log case processing in result_bus_mux
            if self.entity_name and 'result_bus_mux' in self.entity_name.lower():
                stmt_count = len(case.Statements) if hasattr(case, 'Statements') else 0
                print(f"DEBUG CASE_ITER: Case #{case_idx} choice={choice_str} statements={stmt_count}")
                if hasattr(case, 'Statements') and case.Statements:
                    for s_idx, s in enumerate(case.Statements):
                        stmt_type = type(s).__name__
                        target = str(s.Target) if hasattr(s, 'Target') else "NO_TARGET"
                        expr = str(s.Waveform[0].Expression) if hasattr(s, 'Waveform') and s.Waveform and len(s.Waveform) > 0 and hasattr(s.Waveform[0], 'Expression') else "NO_EXPR"
                        print(f"  Statement #{s_idx}: {target} <= {expr}")

            # Push case choice as condition
            if case_expr_node:
                self._condition_stack.append({
                    "node": case_expr_node,
                    "branch": "case",
                    "inverted": False,
                    "case_choice": choice_str
                })

            # Process statements in this case branch
            if hasattr(case, 'Statements') and case.Statements:
                for s in case.Statements:
                    self._process_sequential_statement(s)
            elif case_type == 'OthersCase':
                # pyGHDL DOM bug: OthersCase.Statements is empty even when statements exist
                # Use low-level GHDL API to get statements
                if hasattr(case, '_iirNode') and case._iirNode != nodes.Null_Iir:
                    from pyGHDL.libghdl import utils
                    iir_node = case._iirNode
                    # Get the associated statement chain for this case alternative
                    stmt_chain = nodes.Get_Associated_Chain(iir_node)
                    if stmt_chain != nodes.Null_Iir:
                        # Parse the statement chain
                        for stmt_node in utils.chain_iter(stmt_chain):
                            # Create DOM statement from low-level node
                            # We need to use the Sequential statement parser
                            from pyGHDL.dom.Sequential import (
                                SequentialSimpleSignalAssignment,
                                SequentialSimpleVariableAssignment
                            )
                            stmt_kind = nodes.Get_Kind(stmt_node)
                            if stmt_kind == nodes.Iir_Kind.Simple_Signal_Assignment_Statement:
                                stmt_obj = SequentialSimpleSignalAssignment.parse(stmt_node)
                                self._process_sequential_statement(stmt_obj)
                            elif stmt_kind == nodes.Iir_Kind.Variable_Assignment_Statement:
                                stmt_obj = SequentialSimpleVariableAssignment.parse(stmt_node)
                                self._process_sequential_statement(stmt_obj)

            # Pop case condition
            if case_expr_node and self._condition_stack:
                self._condition_stack.pop()

    def _process_sequential_assignment(self, stmt):
        """Process a sequential signal assignment"""
        if not hasattr(stmt, 'Target') or not hasattr(stmt, 'Waveform'):
            return

        # Get target signal
        target_name = str(stmt.Target)

        # DEBUG: Log all assignments in result_bus_mux
        if self.entity_name and 'result_bus_mux' in self.entity_name.lower():
            if 'res_bus' in target_name:
                waveform_str = str(stmt.Waveform[0].Expression) if stmt.Waveform and len(stmt.Waveform) > 0 and hasattr(stmt.Waveform[0], 'Expression') else "NO_EXPR"
                case_choice = self._condition_stack[-1].get('case_choice', 'N/A') if self._condition_stack else 'N/A'
                stmt_id = id(stmt)
                expr_id = id(stmt.Waveform[0].Expression) if stmt.Waveform and len(stmt.Waveform) > 0 and hasattr(stmt.Waveform[0], 'Expression') else "NO_EXPR"
                print(f"DEBUG ASSIGN: {target_name} <= {waveform_str} [case_choice: {case_choice}] stmt_id={stmt_id} expr_id={expr_id}")

        # Debug for pc_mode and branch_test_mode assignments
        if 'pc_mode' in target_name.lower() or 'branch_test_mode' in target_name.lower():
            print(f"DEBUG: Assignment to {target_name}, condition_stack={len(self._condition_stack)}, clocked={self._in_clocked_process}")

        # Handle indexed access (e.g., registers(rd?)) - extract base signal name and index
        import re
        indexed_match = re.match(r'^([a-zA-Z_]\w*)\s*\(', target_name)
        array_index_node = None
        if indexed_match:
            base_signal = indexed_match.group(1)
            target_node = self.signal_nodes.get(base_signal)

            # Try to extract index expression from pyGHDL AST
            # For ParenthesisName (array access), the index is in Associations
            if hasattr(stmt, 'Target') and hasattr(stmt.Target, 'Associations'):
                associations = stmt.Target.Associations
                if associations and len(associations) > 0:
                    # First association is the index expression
                    index_expr = associations[0]
                    # Parse the index expression as a node
                    array_index_node = self._parse_expression(index_expr)
        else:
            target_node = self.signal_nodes.get(target_name)

        if not target_node:
            return

        # Mark as register if inside a clocked process (rising_edge/falling_edge)
        if self._in_clocked_process:
            if target_node.data is None:
                target_node.data = {}
            target_node.data["is_register"] = True
            # Also mark as ISA state for architectural registers
            if target_name in ['current_pc', 'pc', 'registers', 'reg_file']:
                target_node.data["type"] = "isa_state"
                self.arch_state_signals.add(target_name)

        # Get expression from waveform
        source_node = None

        # CRITICAL FIX: Use low-level API for case statements to avoid pyGHDL DOM bug
        # pyGHDL DOM incorrectly reuses expressions in case statements
        if self._condition_stack and self._condition_stack[-1].get('branch') == 'case':
            # Inside case statement - use low-level API to avoid DOM bug
            if hasattr(stmt, '_iirNode') and stmt._iirNode != nodes.Null_Iir:
                iir_node = stmt._iirNode
                waveform_chain = nodes.Get_Waveform_Chain(iir_node)
                if waveform_chain != nodes.Null_Iir:
                    expr_node = nodes.Get_We_Value(waveform_chain)
                    if expr_node != nodes.Null_Iir:
                        source_node = self._parse_lowlevel_node(expr_node)
                        # DEBUG: Log low-level API result
                        if self.entity_name and 'result_bus_mux' in self.entity_name.lower() and 'res_bus' in target_name:
                            print(f"DEBUG LOW-LEVEL: Parsed {target_name} <= {source_node.id if source_node else 'NONE'} [case_choice: {self._condition_stack[-1].get('case_choice')}]")
            if not source_node:
                return
        elif not stmt.Waveform or len(stmt.Waveform) == 0:
            # Fallback: access low-level GHDL node when DOM drops the expression
            # This handles complex expressions like AND operations or hex literals
            if hasattr(stmt, '_iirNode') and stmt._iirNode != nodes.Null_Iir:
                iir_node = stmt._iirNode
                waveform_chain = nodes.Get_Waveform_Chain(iir_node)
                if waveform_chain != nodes.Null_Iir:
                    expr_node = nodes.Get_We_Value(waveform_chain)
                    if expr_node != nodes.Null_Iir:
                        source_node = self._parse_lowlevel_node(expr_node)
            if not source_node:
                return
        else:
            waveform_element = stmt.Waveform[0]
            if not hasattr(waveform_element, 'Expression'):
                return

            expr = waveform_element.Expression

            # Parse the expression and create edges
            source_node = self._parse_expression(expr)

        if source_node:
            edge_data = {"type": "assignment"}

            # Store array index if this is an indexed assignment (e.g., registers(addr) <= value)
            if array_index_node:
                edge_data["array_index"] = array_index_node.id
                edge_data["is_array_write"] = True

            # Mark as register write if inside clocked process
            if self._in_clocked_process:
                edge_data["is_register_write"] = True

            # Track combinational defaults (first unconditional assignment to signal)
            # OR assignments in "when others" clauses of case statements
            is_unconditional = not self._condition_stack and not self._in_clocked_process
            is_case_others = False

            # Check if this assignment is in a "when others" clause
            if self._condition_stack and not self._in_clocked_process:
                # Check if the last condition (innermost) is a case with "others" choice
                for cond_info in reversed(self._condition_stack):
                    if cond_info.get("branch") == "case" and cond_info.get("case_choice"):
                        case_choice = cond_info.get("case_choice", "").lower().strip()
                        if "others" in case_choice:
                            is_case_others = True
                            break

            if (is_unconditional or is_case_others) and target_name not in self._process_defaults:
                # First assignment - this is the default value
                self._process_defaults[target_name] = source_node
                # Mark this edge as a default assignment
                edge_data["is_default"] = True
                # Store default value in target node for generator to access
                if target_node.data is None:
                    target_node.data = {}
                target_node.data["default_value"] = source_node.id
                # Debug output for important signals
                if 'pc_mode' in target_name or 'out_pc_mode' in target_name:
                    print(f"DEBUG: Tracking default for {target_name} = {source_node.id} (is_case_others={is_case_others})")

            # Add condition information if we're inside a conditional block
            if self._condition_stack:
                condition_info = self._condition_stack[-1]  # Get most recent condition
                edge_data["condition"] = condition_info["node"].id
                edge_data["condition_branch"] = condition_info["branch"]
                edge_data["condition_inverted"] = condition_info["inverted"]
                # Include case_choice if this is inside a case statement
                # Search ALL conditions in the stack for case_choice (for nested if-inside-case)
                if "case_choice" in condition_info:
                    edge_data["case_choice"] = condition_info["case_choice"]
                    # DEBUG: Log case statement assignments for result_bus_mux
                    if 'res_bus' in target_name and self.entity_name and 'result_bus_mux' in self.entity_name.lower():
                        print(f"DEBUG CASE: {target_name} <= {source_node.id} [case_choice: {condition_info['case_choice']}]")
                else:
                    # Check parent conditions for case_choice
                    for cond_info in reversed(self._condition_stack):
                        if "case_choice" in cond_info:
                            edge_data["case_choice"] = cond_info["case_choice"]
                            # DEBUG: Log case statement assignments for result_bus_mux
                            if 'res_bus' in target_name and self.entity_name and 'result_bus_mux' in self.entity_name.lower():
                                print(f"DEBUG CASE: {target_name} <= {source_node.id} [case_choice: {cond_info['case_choice']}]")
                            break

                # Track ALL conditions in the stack for nested conditionals
                # This is critical for case-inside-if or if-inside-case structures
                if len(self._condition_stack) > 1:
                    all_conditions = []
                    for cond_info in self._condition_stack:
                        cond_data = {
                            "node_id": cond_info["node"].id,
                            "branch": cond_info["branch"],
                            "inverted": cond_info["inverted"]
                        }
                        if "case_choice" in cond_info:
                            cond_data["case_choice"] = cond_info["case_choice"]
                        all_conditions.append(cond_data)
                    edge_data["all_conditions"] = all_conditions

                # Create edge from condition to source (control flow dependency)
                cond_node = condition_info["node"]
                cond_edge = Edge(cond_node, source_node, data={"type": "control_flow"})
                self.graph.add_edge(cond_edge)

            edge = Edge(source_node, target_node, data=edge_data)
            self.graph.add_edge(edge)

    def _process_variable_assignment(self, stmt):
        """Process a variable assignment (:= operator)"""
        if not hasattr(stmt, 'Target') or not hasattr(stmt, 'Expression'):
            return

        # Get target variable name
        target_name = str(stmt.Target)

        # Create scoped variable name if inside a process
        # Use lowercase for case-insensitive lookups (VHDL is case-insensitive)
        if self._current_process_name:
            scoped_name = f"{self._current_process_name}_{target_name}".lower()
            node_id = f"var_{scoped_name}"
        else:
            scoped_name = target_name.lower()
            node_id = f"var_{target_name}"

        # Get or create variable node with scoped name
        if scoped_name not in self.variable_nodes:
            # Detect if this is an indexed assignment (e.g., a_dash(31) := value)
            # For single-bit indexed assignments, set bit_width to 1
            bit_width = None
            if '(' in target_name:
                # Check for single-bit index or 'high/'low attribute (both are 1-bit)
                if "'high" in target_name.lower() or "'low" in target_name.lower():
                    bit_width = 1
                # Check for single integer index like a_dash(31)
                elif target_name.count('(') == 1 and 'downto' not in target_name.lower() and 'to' not in target_name.lower():
                    bit_width = 1

            # Create a new node for this variable
            var_node = Node(
                node_id=node_id,
                data={
                    "name": target_name,  # Keep original name for VHDL generation
                    "scoped_name": scoped_name,  # Track scoped name
                    "process_name": self._current_process_name,  # Track which process
                    "type": "variable",
                    "is_variable": True,
                    "bit_width": bit_width  # Set width for indexed assignments
                }
            )
            self.graph.add_node(var_node)
            self.variable_nodes[scoped_name] = var_node
        else:
            var_node = self.variable_nodes[scoped_name]

        # Parse the expression
        source_node = self._parse_expression(stmt.Expression)

        if source_node:
            # Infer bit width from source expression if variable doesn't have one yet
            if var_node.data.get('bit_width') is None and source_node.data:
                source_width = source_node.data.get('bit_width')
                if source_width:
                    var_node.data['bit_width'] = source_width

            edge_data = {"type": "variable_assignment"}

            # Add condition information if we're inside a conditional block
            if self._condition_stack:
                condition_info = self._condition_stack[-1]
                edge_data["condition"] = condition_info["node"].id
                edge_data["condition_branch"] = condition_info["branch"]
                edge_data["condition_inverted"] = condition_info["inverted"]
                if "case_choice" in condition_info:
                    edge_data["case_choice"] = condition_info["case_choice"]

            edge = Edge(source_node, var_node, data=edge_data)
            self.graph.add_edge(edge)

            print(f"DEBUG: Variable assignment: {scoped_name} := {source_node.id}")

    def _process_for_loop(self, stmt):
        """Process a for loop statement"""
        if not hasattr(stmt, 'Statements') or not stmt.Statements:
            return

        # Process statements inside the loop
        for s in stmt.Statements:
            self._process_sequential_statement(s)

    def _process_concurrent_assignment(self, stmt):
        """Process a concurrent signal assignment"""
        if not hasattr(stmt, 'Target') or not hasattr(stmt, 'Waveform'):
            return

        # Get target signal (use lowercase for case-insensitive lookup)
        target_name = str(stmt.Target)
        target_node = self.signal_nodes.get(target_name.lower())

        if not target_node:
            return

        # Get expression from waveform
        if not stmt.Waveform or len(stmt.Waveform) == 0:
            return

        waveform_element = stmt.Waveform[0]
        if not hasattr(waveform_element, 'Expression'):
            return

        expr = waveform_element.Expression

        # Get target's bit width for context
        target_width = target_node.data.get('bit_width') if target_node.data else None

        # Parse the expression and create edges (pass target width for context)
        source_node = self._parse_expression(expr, target_width=target_width)

        # DEBUG: Log assignment creation
        if target_name in ['rs1', 'rs2', 'rd', 'func3', 'func7', 'opcode']:
            print(f"DEBUG ASSIGNMENT: {target_name} <= {source_node.id if source_node else 'None'} (source type: {source_node.data.get('type') if source_node else 'N/A'})")

        if source_node:
            edge = Edge(source_node, target_node, data={"type": "assignment"})
            self.graph.add_edge(edge)

    def _process_concurrent_conditional(self, stmt):
        """
        Process a concurrent conditional signal assignment (when/else).

        Example: target <= value1 when condition else value2

        Creates a mux/select operation node.
        """
        if not hasattr(stmt, 'Target'):
            return

        # Get target signal (use lowercase for case-insensitive lookup)
        target_name = str(stmt.Target)
        target_node = self.signal_nodes.get(target_name.lower())

        if not target_node:
            return

        # ConcurrentConditionalSignalAssignment has ConditionalWaveforms
        if not hasattr(stmt, 'ConditionalWaveforms') or not stmt.ConditionalWaveforms:
            return

        # Create mux operation node
        mux_id = f"mux_{target_name}_{self._temp_var_counter}"
        self._temp_var_counter += 1

        mux_node = self._create_operation_node(
            node_id=mux_id,
            operator="mux"
        )
        # Add style metadata for when/else mux
        mux_node.data["style"] = "when_else"
        self.graph.add_node(mux_node)

        # Process each conditional waveform (when clauses)
        for idx, cond_waveform in enumerate(stmt.ConditionalWaveforms):
            # Get the waveform (value) for this condition
            if hasattr(cond_waveform, 'Waveform') and cond_waveform.Waveform:
                waveform_elem = cond_waveform.Waveform[0]
                if hasattr(waveform_elem, 'Expression'):
                    value_node = self._parse_expression(waveform_elem.Expression)

                    if value_node:
                        # Add edge from value to mux
                        edge_data = {"type": "mux_input", "index": idx}

                        # Check if this has a condition
                        if hasattr(cond_waveform, 'Condition'):
                            # Parse the condition
                            condition_node = self._parse_expression(cond_waveform.Condition)
                            if condition_node:
                                # Add condition as selector input
                                cond_edge = Edge(condition_node, mux_node,
                                               data={"type": "mux_selector", "index": idx})
                                self.graph.add_edge(cond_edge)
                                edge_data["condition"] = condition_node.id
                        else:
                            # No condition = else clause (default)
                            edge_data["is_default"] = True

                        # Add value input to mux
                        value_edge = Edge(value_node, mux_node, data=edge_data)
                        self.graph.add_edge(value_edge)

        # Add edge from mux to target
        output_edge = Edge(mux_node, target_node, data={"type": "assignment"})
        self.graph.add_edge(output_edge)

    def _process_concurrent_selected(self, stmt):
        """
        Process a concurrent selected signal assignment (with/select).

        Example: with selector select target <= value1 when choice1, value2 when choice2;

        Creates a mux/select operation node.
        """
        if not hasattr(stmt, 'Target'):
            return

        # Get target signal (use lowercase for case-insensitive lookup)
        target_name = str(stmt.Target)
        target_node = self.signal_nodes.get(target_name.lower())

        if not target_node:
            return

        # Get selector expression
        selector_node = None
        if hasattr(stmt, 'Expression'):
            selector_node = self._parse_expression(stmt.Expression)

        # Create mux operation node
        mux_id = f"mux_{target_name}_{self._temp_var_counter}"
        self._temp_var_counter += 1

        mux_node = self._create_operation_node(
            node_id=mux_id,
            operator="mux"
        )
        # Add style metadata for with/select mux
        mux_node.data["style"] = "with_select"
        self.graph.add_node(mux_node)

        # Add selector as input
        if selector_node:
            selector_edge = Edge(selector_node, mux_node, data={"type": "mux_selector"})
            self.graph.add_edge(selector_edge)

        # Process selected waveforms (choices)
        if hasattr(stmt, 'SelectedWaveforms') and stmt.SelectedWaveforms:
            for idx, selected_waveform in enumerate(stmt.SelectedWaveforms):
                # Get choice value(s)
                choice_str = "unknown"
                if hasattr(selected_waveform, 'Choices') and selected_waveform.Choices:
                    choices = []
                    for choice in selected_waveform.Choices:
                        choices.append(str(choice))
                    choice_str = ", ".join(choices)

                # Get waveform value
                if hasattr(selected_waveform, 'Waveform') and selected_waveform.Waveform:
                    waveform_elem = selected_waveform.Waveform[0]
                    if hasattr(waveform_elem, 'Expression'):
                        value_node = self._parse_expression(waveform_elem.Expression)

                        if value_node:
                            # Add value input to mux
                            edge_data = {
                                "type": "mux_input",
                                "index": idx,
                                "choice": choice_str
                            }
                            value_edge = Edge(value_node, mux_node, data=edge_data)
                            self.graph.add_edge(value_edge)

        # Add edge from mux to target
        output_edge = Edge(mux_node, target_node, data={"type": "assignment"})
        self.graph.add_edge(output_edge)

    def _process_lowlevel_conditional(self, stmt):
        """
        Process concurrent conditional signal assignment using low-level API.

        Example: target <= value1 when condition else value2
        """
        # Get target
        target_node = self._get_lowlevel_target(stmt)
        if not target_node:
            return

        # Create mux operation node
        mux_id = f"mux_{target_node.id}_{self._temp_var_counter}"
        self._temp_var_counter += 1

        mux_node = self._create_operation_node(
            node_id=mux_id,
            operator="mux"
        )
        # Add style metadata for when/else mux
        mux_node.data["style"] = "when_else"
        self.graph.add_node(mux_node)

        # Get conditional waveform chain
        cond_waveform = nodes.Get_Conditional_Waveform_Chain(stmt)

        idx = 0
        while cond_waveform != nodes.Null_Iir:
            # Get condition (None for else clause)
            condition = nodes.Get_Condition(cond_waveform)

            # Get waveform
            waveform = nodes.Get_Waveform_Chain(cond_waveform)
            if waveform != nodes.Null_Iir:
                # Parse the value expression from waveform
                value_expr = nodes.Get_We_Value(waveform)
                value_node = self._parse_lowlevel_node(value_expr)

                if value_node:
                    edge_data = {"type": "mux_input", "index": idx}

                    if condition != nodes.Null_Iir:
                        # Parse condition
                        condition_node = self._parse_lowlevel_node(condition)
                        if condition_node:
                            # Add selector edge
                            cond_edge = Edge(condition_node, mux_node,
                                           data={"type": "mux_selector", "index": idx})
                            self.graph.add_edge(cond_edge)
                            edge_data["condition"] = condition_node.id
                    else:
                        # Else clause (default)
                        edge_data["is_default"] = True

                    # Add value input
                    value_edge = Edge(value_node, mux_node, data=edge_data)
                    self.graph.add_edge(value_edge)

            idx += 1
            cond_waveform = nodes.Get_Chain(cond_waveform)

        # Add mux output to target
        output_edge = Edge(mux_node, target_node, data={"type": "assignment"})
        self.graph.add_edge(output_edge)

    def _process_lowlevel_selected(self, stmt):
        """
        Process concurrent selected signal assignment using low-level API.

        Example: with selector select target <= value1 when choice1, value2 when choice2;
        """
        # Get target
        target_node = self._get_lowlevel_target(stmt)
        if not target_node:
            return

        # Create mux operation node
        mux_id = f"mux_{target_node.id}_{self._temp_var_counter}"
        self._temp_var_counter += 1

        mux_node = self._create_operation_node(
            node_id=mux_id,
            operator="mux"
        )
        # Add style metadata for with/select mux
        mux_node.data["style"] = "with_select"
        self.graph.add_node(mux_node)

        # Get selector expression
        selector_expr = nodes.Get_Expression(stmt)
        if selector_expr != nodes.Null_Iir:
            selector_node = self._parse_lowlevel_node(selector_expr)
            if selector_node:
                selector_edge = Edge(selector_node, mux_node, data={"type": "mux_selector"})
                self.graph.add_edge(selector_edge)

        # Get selected waveform chain
        selected_waveform = nodes.Get_Selected_Waveform_Chain(stmt)

        idx = 0
        while selected_waveform != nodes.Null_Iir:
            swf_kind = nodes.Get_Kind(selected_waveform)
            print(f"DEBUG SELECTED: Waveform {idx} kind={swf_kind}")

            # Get choice from the selected waveform
            # For simple choices like '1' or others
            choice_str = "others"  # Default to others
            try:
                # Check if it's Choice_By_Others
                if swf_kind == nodes.Iir_Kind.Choice_By_Others:
                    choice_str = "others"
                    print(f"DEBUG SELECTED: Choice is 'others'")
                else:
                    # Try to get choice expression for Choice_By_Expression
                    choice_expr = nodes.Get_Choice_Expression(selected_waveform)
                    if choice_expr != nodes.Null_Iir:
                        choice_kind = nodes.Get_Kind(choice_expr)
                        print(f"DEBUG SELECTED: Choice expr kind={choice_kind}")
                        if choice_kind == nodes.Iir_Kind.Character_Literal:
                            char_id = nodes.Get_Identifier(choice_expr)
                            char_name = name_table.Get_Name_Ptr(char_id)
                            # Handle both str and bytes
                            if isinstance(char_name, bytes):
                                char_name = char_name.decode()
                            choice_str = char_name  # e.g., '1' or '0'
                            print(f"DEBUG SELECTED: Choice char: {choice_str}")
            except Exception as e:
                print(f"DEBUG SELECTED: Choice parsing error: {e}")

            # Get the value from the waveform chain
            value_node = None
            try:
                # Get associated chain - for selected waveforms, this links to the waveform
                assoc_chain = nodes.Get_Associated_Chain(selected_waveform)
                if assoc_chain != nodes.Null_Iir:
                    print(f"DEBUG SELECTED: assoc_chain kind={nodes.Get_Kind(assoc_chain)}")
                    # For waveform elements, get the value
                    we_value = nodes.Get_We_Value(assoc_chain)
                    if we_value != nodes.Null_Iir:
                        print(f"DEBUG SELECTED: we_value kind={nodes.Get_Kind(we_value)}")
                        value_node = self._parse_lowlevel_node(we_value)
            except Exception as e:
                print(f"DEBUG SELECTED: Associated chain error: {e}")

            # Try alternative: Get_Associated_Expr
            if not value_node:
                try:
                    assoc_expr = nodes.Get_Associated_Expr(selected_waveform)
                    if assoc_expr != nodes.Null_Iir:
                        print(f"DEBUG SELECTED: assoc_expr kind={nodes.Get_Kind(assoc_expr)}")
                        value_node = self._parse_lowlevel_node(assoc_expr)
                except Exception as e:
                    print(f"DEBUG SELECTED: Associated expr error: {e}")

            if value_node:
                print(f"DEBUG SELECTED: Adding mux_input edge choice={choice_str} value={value_node.id}")
                edge_data = {
                    "type": "mux_input",
                    "index": idx,
                    "choice": choice_str
                }
                value_edge = Edge(value_node, mux_node, data=edge_data)
                self.graph.add_edge(value_edge)
            else:
                print(f"DEBUG SELECTED: No value node for waveform {idx}")

            idx += 1
            selected_waveform = nodes.Get_Chain(selected_waveform)

        # Add mux output to target
        output_edge = Edge(mux_node, target_node, data={"type": "assignment"})
        self.graph.add_edge(output_edge)

    def _get_lowlevel_target(self, stmt) -> Optional[Node]:
        """Get the target signal node from a low-level statement"""
        target = nodes.Get_Target(stmt)
        if target == nodes.Null_Iir:
            return None

        # Get target name
        target_name = self._get_lowlevel_name(target)
        if not target_name:
            return None

        # Look up in signal nodes
        return self.signal_nodes.get(target_name)

    def _get_lowlevel_name(self, node) -> Optional[str]:
        """Get the name/identifier from a low-level node"""
        try:
            kind = nodes.Get_Kind(node)

            if kind == nodes.Iir_Kind.Simple_Name:
                ident = nodes.Get_Identifier(node)
                return name_table.Get_Name_Ptr(ident)
            elif kind == nodes.Iir_Kind.Character_Literal:
                # Character literal like '1', '0'
                ident = nodes.Get_Identifier(node)
                return f"'{name_table.Get_Name_Ptr(ident)}'"
            elif kind == nodes.Iir_Kind.Integer_Literal:
                # Integer literal
                value = nodes.Get_Value(node)
                return str(value)
            elif kind == nodes.Iir_Kind.String_Literal8:
                # String literal like "others"
                return "others"
            else:
                # Try to convert to string
                return str(node)
        except:
            return None

    def _parse_expression(self, expr, target_width: Optional[int] = None) -> Optional[Node]:
        """
        Parse an expression and return the node representing it.

        Args:
            expr: Expression object from pyGHDL
            target_width: Optional target width (for literals assigned to signals)

        This handles:
        - Simple signal references (SimpleObjectOrFunctionCallSymbol)
        - Binary operations (AdditionExpression, etc.)
        - Function calls / indexed access (IndexedObjectOrFunctionCallSymbol)
        - Literals

        Returns:
            Node representing the expression, or None if unsupported
        """
        # Store target width for use in literal creation
        self._current_target_width = target_width

        expr_type = type(expr).__name__

        # Handle simple signal references
        if expr_type in ['SimpleObjectOrFunctionCallSymbol', 'SimpleName']:
            signal_name = str(expr)
            # Remove '?' suffix used by pyGHDL for unresolved types
            signal_name = signal_name.rstrip('?')

            # Normalize signal name to lowercase for case-insensitive lookups
            signal_name_lower = signal_name.lower()

            # DEBUG: Log signal lookups in result_bus_mux
            if self.entity_name and 'result_bus_mux' in self.entity_name.lower():
                if signal_name_lower in ['res_alu', 'res_shifter', 'res_memory', 'res_pc_plus_four', 'res_bus']:
                    node_found = self.signal_nodes.get(signal_name_lower)
                    if node_found:
                        print(f"DEBUG EXPR: Parsing '{signal_name}' -> node '{node_found.id}'")
                    else:
                        print(f"DEBUG EXPR: Parsing '{signal_name}' -> NOT FOUND")

            if signal_name_lower in self.signal_nodes:
                return self.signal_nodes[signal_name_lower]
            # Check if it's a variable reference (try scoped name first if in a process)
            if self._current_process_name:
                scoped_name = f"{self._current_process_name}_{signal_name}"
                scoped_name_lower = scoped_name.lower()
                if scoped_name_lower in self.variable_nodes:
                    return self.variable_nodes[scoped_name_lower]
            if signal_name_lower in self.variable_nodes:
                return self.variable_nodes[signal_name_lower]
            # Check if it's a constant reference - create literal with constant's value
            # Constants are stored with uppercase names but pyGHDL may return lowercase
            signal_name_upper = signal_name.upper()
            if signal_name in self.constants:
                const_value = self.constants[signal_name]
                return self._create_literal_node(const_value, bit_width=None)
            elif signal_name_upper in self.constants:
                const_value = self.constants[signal_name_upper]
                return self._create_literal_node(const_value, bit_width=None)
            # Unknown signal/variable, create temp var
            return self._create_temp_var()

        # Handle unary operations
        if expr_type == 'InverseExpression':
            return self._parse_unary_expression(expr, 'not')

        # Handle parenthesized expressions (just unwrap)
        if expr_type == 'ParenthesisExpression':
            if hasattr(expr, 'Operand'):
                return self._parse_expression(expr.Operand)
            return self._create_temp_var()

        # Handle binary operations
        if expr_type in ['AdditionExpression', 'SubtractionExpression',
                         'MultiplicationExpression', 'MultiplyExpression',  # Alternate name
                         'DivisionExpression',
                         'AndExpression', 'OrExpression', 'XorExpression',
                         'NandExpression', 'NorExpression', 'XnorExpression',
                         'EqualityExpression', 'InequalityExpression',
                         'EqualExpression',  # Also = comparison
                         'UnequalExpression',  # Alternate name for /=
                         'LessThanExpression', 'LessThanOrEqualExpression',
                         'GreaterThanExpression', 'GreaterThanOrEqualExpression',
                         'ShiftLeftExpression', 'ShiftRightExpression',
                         'ConcatenationExpression']:
            return self._parse_binary_expression(expr, expr_type)

        # Handle function calls and indexed access
        if expr_type == 'IndexedObjectOrFunctionCallSymbol':
            # DEBUG
            expr_str = str(expr)
            debug_this = 'instr' in expr_str.lower() or 'pc' in expr_str.lower() or 'word_addr' in expr_str.lower()
            if debug_this:
                print(f"DEBUG EXPR: IndexedObjectOrFunctionCallSymbol: {expr_str}, has _iirNode: {hasattr(expr, '_iirNode')}")

            # Try low-level API first (can detect operations inside type conversions!)
            result = self._parse_lowlevel_expression(expr)
            if result:
                if debug_this:
                    print(f"  -> lowlevel returned: {result.id} (type: {result.data.get('type')})")
                return result
            # Fallback to DOM-based parsing
            if debug_this:
                print(f"  -> lowlevel returned None, falling back to DOM parsing")
            dom_result = self._parse_indexed_or_call(expr)
            if debug_this and dom_result:
                print(f"  -> DOM returned: {dom_result.id} (type: {dom_result.data.get('type')})")
            return dom_result

        # Handle literals
        if expr_type in ['IntegerLiteral', 'StringLiteral', 'BitStringLiteral', 'CharacterLiteral']:
            # Literals don't create nodes, return a constant node
            return self._create_constant_node(expr)

        # Handle aggregate expressions (e.g., (others => '0'))
        if expr_type == 'Aggregate':
            # Aggregates are constant initializers
            return self._create_constant_node(expr)

        # Handle range expressions (e.g., 11 downto 2 in pc(11 downto 2))
        # These typically appear inside indexed access expressions
        if expr_type in ['DescendingRangeExpression', 'AscendingRangeExpression']:
            # Range expressions don't create nodes by themselves
            # They should be handled in the context of bit slicing
            # If we reach here, the parent context should have handled it
            # Just return None to indicate this needs context-aware handling
            return None

        # Unsupported expression type, create temp var
        print(f"  Warning: Unsupported expression type: {expr_type}")
        return self._create_temp_var()

    def _parse_unary_expression(self, expr, op: str) -> Node:
        """Parse a unary expression (e.g., NOT x)"""
        if not hasattr(expr, 'Operand'):
            return self._create_temp_var()

        operand = self._parse_expression(expr.Operand)

        if not operand:
            return self._create_temp_var()

        # Create standardized operation node
        op_node = self._create_operation_node(
            node_id=f"{op}_{operand.id}",
            operator=op,
            left_name=str(operand.id)
        )
        self.graph.add_node(op_node)

        # Add edge from operand to operation
        self.graph.add_edge(Edge(operand, op_node, data={"operand": "unary"}))

        return op_node

    def _is_signed_dom_operand(self, operand) -> bool:
        """Check if a DOM operand is a signed() type conversion."""
        # Try to use the low-level IIR node if available
        if hasattr(operand, '_iirNode'):
            return self._is_signed_type_conversion(operand._iirNode)
        # Fallback: check the string representation
        try:
            operand_str = str(operand)
            if operand_str.lower().startswith('signed('):
                return True
        except:
            pass
        return False

    def _parse_binary_expression(self, expr, expr_type: str) -> Node:
        """Parse a binary expression (e.g., pc + 4)"""
        if not hasattr(expr, 'LeftOperand') or not hasattr(expr, 'RightOperand'):
            return self._create_temp_var()

        # Check if operands are wrapped in signed() type conversions
        # This is critical for signed comparisons (BGE, BLT, SLT, etc.)
        left_is_signed = self._is_signed_dom_operand(expr.LeftOperand)
        right_is_signed = self._is_signed_dom_operand(expr.RightOperand)
        is_signed_comparison = left_is_signed and right_is_signed

        left = self._parse_expression(expr.LeftOperand)
        right = self._parse_expression(expr.RightOperand)

        if not left or not right:
            return self._create_temp_var()

        # Propagate bit widths between operands for comparisons
        # If one operand is a literal without a width and the other has a width, propagate it
        # But only if the literal value can fit in that width
        left_width = left.data.get('bit_width')
        right_width = right.data.get('bit_width')
        left_is_literal = left.data.get('type') == 'literal'
        right_is_literal = right.data.get('type') == 'literal'

        def can_fit_in_width(value, width):
            """Check if a literal value can fit in the given bit width."""
            if width is None:
                return False
            try:
                int_val = int(value)
                max_val = (1 << width) - 1  # 2^width - 1
                return 0 <= int_val <= max_val
            except (ValueError, TypeError):
                # String literals - check if it's a valid binary string
                if isinstance(value, str):
                    if value.startswith('"') and value.endswith('"'):
                        inner = value[1:-1]
                        return len(inner) == width and all(c in '01' for c in inner)
                return False

        # For comparison and logical operations, match widths
        if expr_type in ['EqualityExpression', 'EqualExpression', 'InequalityExpression',
                        'LessThanExpression', 'LessThanOrEqualExpression',
                        'GreaterThanExpression', 'GreaterThanOrEqualExpression',
                        'AndExpression', 'OrExpression', 'XorExpression']:
            if left_is_literal and not left_width and right_width:
                # Left is literal without width, right has width - propagate if it fits
                left_value = left.data.get('value')
                if can_fit_in_width(left_value, right_width):
                    left.data['bit_width'] = right_width
            elif right_is_literal and not right_width and left_width:
                # Right is literal without width, left has width - propagate if it fits
                right_value = right.data.get('value')
                if can_fit_in_width(right_value, left_width):
                    right.data['bit_width'] = left_width

        # Map expression type to operator
        op_map = {
            # Arithmetic
            'AdditionExpression': '+',
            'SubtractionExpression': '-',
            'MultiplicationExpression': '*',
            'DivisionExpression': '/',
            'ModuloExpression': 'mod',
            'RemainderExpression': 'rem',
            # Logical
            'AndExpression': 'and',
            'OrExpression': 'or',
            'XorExpression': 'xor',
            'NandExpression': 'nand',
            'NorExpression': 'nor',
            'XnorExpression': 'xnor',
            # Comparison
            'EqualityExpression': '=',
            'EqualExpression': '=',  # Also = comparison
            'InequalityExpression': '/=',
            'UnequalExpression': '/=',  # Alternate name for /=
            'LessThanExpression': '<',
            'LessThanOrEqualExpression': '<=',
            'GreaterThanExpression': '>',
            'GreaterThanOrEqualExpression': '>=',
            # Shift
            'ShiftLeftExpression': 'sll',
            'ShiftRightExpression': 'srl',
            # Concatenation
            'ConcatenationExpression': 'concat',  # VHDL concatenation (& operator), not logical AND
        }
        op = op_map.get(expr_type, 'op')

        # For signed comparisons, use signed comparison operators
        signed_comparison_ops = ['<', '>', '<=', '>=']
        if is_signed_comparison and op in signed_comparison_ops:
            op = op + 's'  # '<' -> '<s', '>' -> '>s', etc.

        # Create standardized operation node
        op_node = self._create_operation_node(
            node_id=f"{left.id}_{op}_{right.id}",
            operator=op,
            left_name=str(left.id),
            right_name=str(right.id)
        )

        # Mark as signed if applicable
        if is_signed_comparison:
            op_node.data['is_signed'] = True

        # Propagate bit width to result
        left_width = left.data.get('bit_width') if left.data else None
        right_width = right.data.get('bit_width') if right.data else None

        # Comparison operators always produce 1-bit boolean result
        comparison_ops = ['=', '/=', '<', '>', '<=', '>=', '==', '!=', '<s', '>s', '<=s', '>=s']
        if op in comparison_ops:
            op_node.data['bit_width'] = 1
        elif op == 'concat':
            # For concatenation, result width is the SUM of operand widths
            # For literals without explicit width (like "0" in VHDL), default to 1 bit
            effective_left_width = left_width if left_width else 1
            effective_right_width = right_width if right_width else 1
            op_node.data['bit_width'] = effective_left_width + effective_right_width
        else:
            # For most operations, result width is the max of operand widths
            if left_width and right_width:
                op_node.data['bit_width'] = max(left_width, right_width)
            elif left_width:
                op_node.data['bit_width'] = left_width
            elif right_width:
                op_node.data['bit_width'] = right_width

        self.graph.add_node(op_node)

        # Add edges from operands to operation
        self.graph.add_edge(Edge(left, op_node, data={"operand": "left"}))
        self.graph.add_edge(Edge(right, op_node, data={"operand": "right"}))

        return op_node

    def _parse_indexed_or_call(self, expr) -> Node:
        """
        Parse indexed access or function call.

        Examples:
        - pc (simple reference within function call)
        - registers(rs1) (array access)
        - std_logic_vector(pc) (type cast)
        - instruction(6 downto 0) (bit slice)
        - to_integer(unsigned(instruction(11 downto 7))) (nested calls)
        """
        # Try to extract the base object from the Name string
        if hasattr(expr, 'Name'):
            name_str = str(expr.Name)

            # Direct signal reference (e.g., "pc", "instruction")
            # Use lowercase for case-insensitive lookups
            name_str_lower = name_str.lower()
            if name_str_lower in self.signal_nodes:
                return self.signal_nodes[name_str_lower]

            # Check if it's a process variable (try scoped name if in a process)
            # Extract base name if this is an indexed access like "a_dash(a_dash'high?)"
            base_name = name_str.split('(')[0] if '(' in name_str else name_str
            if self._current_process_name:
                scoped_name = f"{self._current_process_name}_{base_name}".lower()
                if scoped_name in self.variable_nodes:
                    base_var_node = self.variable_nodes[scoped_name]

                    # If this is an indexed/sliced access (has parentheses), create bit access node
                    if '(' in name_str:
                        # Check for attribute access like "a_dash(a_dash'high?)"
                        if "'high" in name_str.lower():
                            # For 32-bit vectors, 'high attribute is 31
                            # Create a bit_slice node for the high bit
                            slice_id = f"{base_var_node.id}_31"
                            slice_node = Node(
                                node_id=slice_id,
                                data={
                                    'type': 'bit_slice',
                                    'expression': {
                                        'type': 'bit_slice',
                                        'target': base_var_node.id,
                                        'range': (31, 31)  # Single bit
                                    },
                                    'bit_width': 1,
                                }
                            )
                            self.graph.add_node(slice_node)
                            self.graph.add_edge(Edge(base_var_node, slice_node, data={"type": "bit_access"}))
                            return slice_node

                        # Check for slice pattern: var(N downto M) or var(N to M)
                        import re
                        var_slice_pattern = r'(\w+)\s*\(\s*(\d+)\s+(downto|to)\s+(\d+)\s*\)\??'
                        var_match = re.match(var_slice_pattern, name_str)
                        if var_match:
                            high_str = var_match.group(2)
                            direction = var_match.group(3)
                            low_str = var_match.group(4)

                            left_val = int(high_str)
                            right_val = int(low_str)

                            # Determine high and low based on direction
                            if direction == 'downto':
                                high = left_val
                                low = right_val
                            else:  # 'to'
                                high = right_val
                                low = left_val

                            # Calculate bit width
                            bit_width = abs(high - low) + 1

                            # Create bit_slice node for process variable slice
                            slice_id = f"{base_var_node.id}_{high}_downto_{low}"
                            slice_node = Node(
                                node_id=slice_id,
                                data={
                                    'type': 'bit_slice',
                                    'expression': {
                                        'type': 'bit_slice',
                                        'target': base_var_node.id,
                                        'range': (high, low)
                                    },
                                    'bit_width': bit_width,
                                }
                            )
                            self.graph.add_node(slice_node)
                            self.graph.add_edge(Edge(base_var_node, slice_node, data={"type": "bit_access"}))
                            return slice_node

                    return base_var_node

            # Check if this is a bit slice: signal(N downto M) or signal(N to M)
            # Pattern: signal_name(number downto/to number)?
            import re
            slice_pattern = r'(\w+)\s*\(\s*(\d+)\s+(downto|to)\s+(\d+)\s*\)\??'
            match = re.match(slice_pattern, name_str)
            if match:
                signal_name = match.group(1)
                high_str = match.group(2)
                direction = match.group(3)  # 'downto' or 'to'
                low_str = match.group(4)

                # Check both signals and process variables (case-insensitive)
                prefix_node = None
                signal_name_lower = signal_name.lower()
                if signal_name_lower in self.signal_nodes:
                    prefix_node = self.signal_nodes[signal_name_lower]
                elif self._current_process_name:
                    scoped_name = f"{self._current_process_name}_{signal_name}".lower()
                    if scoped_name in self.variable_nodes:
                        prefix_node = self.variable_nodes[scoped_name]

                if prefix_node:
                    # Parse the range values
                    left_val = int(high_str)
                    right_val = int(low_str)

                    # Determine high and low based on direction
                    if direction == 'downto':
                        high = left_val
                        low = right_val
                    else:  # 'to'
                        high = right_val
                        low = left_val

                    # Calculate bit width
                    bit_width = abs(high - low) + 1

                    # Create bit_slice node
                    slice_id = f"{prefix_node.id}_{high}_downto_{low}"

                    # DEBUG
                    if 'instr' in signal_name.lower():
                        print(f"DEBUG DOM: Creating bit_slice for {signal_name}[{high}:{low}] (width={bit_width})")

                    slice_node = Node(
                        node_id=slice_id,
                        data={
                            'type': 'bit_slice',
                            'expression': {
                                'type': 'bit_slice',
                                'target': prefix_node.id,
                                'range': (high, low)
                            },
                            'bit_width': bit_width,
                        }
                    )
                    self.graph.add_node(slice_node)

                    # Add edge from prefix to slice
                    self.graph.add_edge(Edge(prefix_node, slice_node, data={"type": "bit_access"}))

                    return slice_node

            # Check if this is a type conversion function with parameter
            # Pattern: type_func(inner_expression)
            type_funcs = ['std_logic_vector', 'unsigned', 'signed', 'to_integer',
                          'to_unsigned', 'to_signed', 'resize', 'conv_integer']

            import re
            func_pattern = r'(\w+)\s*\('
            match = re.match(func_pattern, name_str)
            if match:
                func_name = match.group(1)
                if func_name in type_funcs:
                    # It's a type conversion - parse the inner expression recursively
                    # Extract the parameter expression
                    start = name_str.index('(')
                    depth = 0
                    end = start
                    for i in range(start, len(name_str)):
                        if name_str[i] == '(':
                            depth += 1
                        elif name_str[i] == ')':
                            depth -= 1
                            if depth == 0:
                                end = i
                                break

                    if end > start:
                        inner_expr_str = name_str[start+1:end].replace('?', '')

                        # Check if inner expression is a bit slice pattern: signal(N downto M)
                        slice_pattern = r'(\w+)\s*\(\s*(\d+)\s+(downto|to)\s+(\d+)\s*\)'
                        slice_match = re.match(slice_pattern, inner_expr_str)
                        if slice_match:
                            signal_name = slice_match.group(1)
                            high_str = slice_match.group(2)
                            direction = slice_match.group(3)
                            low_str = slice_match.group(4)

                            # Check if signal exists (case-insensitive)
                            prefix_node = None
                            signal_name_lower = signal_name.lower()
                            if signal_name_lower in self.signal_nodes:
                                prefix_node = self.signal_nodes[signal_name_lower]
                            elif self._current_process_name:
                                scoped_name = f"{self._current_process_name}_{signal_name}".lower()
                                if scoped_name in self.variable_nodes:
                                    prefix_node = self.variable_nodes[scoped_name]

                            if prefix_node:
                                # Parse the range values
                                left_val = int(high_str)
                                right_val = int(low_str)

                                # Determine high and low based on direction
                                if direction == 'downto':
                                    high = left_val
                                    low = right_val
                                else:  # 'to'
                                    high = right_val
                                    low = left_val

                                # Calculate bit width
                                bit_width = abs(high - low) + 1

                                # Create bit_slice node
                                slice_id = f"{prefix_node.id}_{high}_downto_{low}"
                                slice_node = Node(
                                    node_id=slice_id,
                                    data={
                                        'type': 'bit_slice',
                                        'expression': {
                                            'type': 'bit_slice',
                                            'target': prefix_node.id,
                                            'range': (high, low)
                                        },
                                        'bit_width': bit_width,
                                    }
                                )
                                self.graph.add_node(slice_node)
                                self.graph.add_edge(Edge(prefix_node, slice_node, data={"type": "bit_access"}))

                                # DEBUG
                                if 'pc' in signal_name.lower() or 'word_addr' in signal_name.lower():
                                    print(f"DEBUG DOM: Created bit_slice {signal_name}[{high}:{low}] from type conversion")

                                return slice_node

            # Try to extract signal from function calls and indexed access
            # Pattern: function_name(signal_name...) or signal_name(index...)
            signal_name = self._extract_signal_from_expression(name_str)

            if signal_name:
                # Use lowercase for case-insensitive lookups
                signal_name_lower = signal_name.lower()
                if signal_name_lower in self.signal_nodes:
                    return self.signal_nodes[signal_name_lower]
                elif self._current_process_name:
                    scoped_name = f"{self._current_process_name}_{signal_name}".lower()
                    if scoped_name in self.variable_nodes:
                        return self.variable_nodes[scoped_name]

        # If we can't determine the source, return temp var
        return self._create_temp_var()

    def _extract_signal_from_expression(self, expr_str: str) -> Optional[str]:
        """
        Extract the base signal name from an expression string.

        Examples:
            'std_logic_vector(pc?)' → 'pc'
            'instruction(6 downto 0)' → 'instruction'
            'registers(rs1)' → 'registers'
            'to_integer(unsigned(instruction(11 downto 7)?)?)'  → 'instruction'
        """
        # List of known type conversion functions to skip
        type_funcs = ['std_logic_vector', 'unsigned', 'signed', 'to_integer',
                      'to_unsigned', 'to_signed', 'resize', 'conv_integer',
                      'conv_std_logic_vector', 'shift_left', 'shift_right']

        # Remove '?' characters (used by pyGHDL for unknown types)
        expr_str = expr_str.replace('?', '')

        # Try to extract signal recursively
        import re

        # Pattern to match function_name(...)
        func_pattern = r'(\w+)\s*\('

        match = re.match(func_pattern, expr_str)
        if match:
            func_name = match.group(1)

            if func_name in type_funcs:
                # It's a type conversion - extract the argument
                # Find the content within the parentheses
                start = expr_str.index('(')
                # Find matching closing paren
                depth = 0
                end = start
                for i in range(start, len(expr_str)):
                    if expr_str[i] == '(':
                        depth += 1
                    elif expr_str[i] == ')':
                        depth -= 1
                        if depth == 0:
                            end = i
                            break

                if end > start:
                    inner = expr_str[start+1:end]
                    # Recursively extract from the inner expression
                    return self._extract_signal_from_expression(inner)
            else:
                # It's a signal with index/slice (e.g., instruction(7 downto 0))
                # The function name is actually the signal name
                if func_name in self.signal_nodes:
                    return func_name

        # If no function call, check if it's just a signal name
        # Extract identifier (letters, numbers, underscore)
        identifier_match = re.match(r'^([a-zA-Z_]\w*)', expr_str)
        if identifier_match:
            potential_signal = identifier_match.group(1)
            if potential_signal in self.signal_nodes:
                return potential_signal

        return None

    def _parse_lowlevel_expression(self, expr) -> Optional[Node]:
        """
        Parse expression using low-level pyGHDL API.

        This method can detect operations INSIDE type conversions!

        Example:
            std_logic_vector(unsigned(a) + unsigned(b))

        Returns operation node for the '+' operator with proper operands.
        """
        # Check if DOM object has low-level node
        if not hasattr(expr, '_iirNode'):
            return None

        try:
            return self._parse_lowlevel_node(expr._iirNode)
        except Exception as e:
            # If low-level parsing fails, return None to fall back to DOM parsing
            return None

    def _parse_lowlevel_node(self, node) -> Optional[Node]:
        """
        Recursively parse a low-level IIR node.

        This is the KEY method that solves the type conversion problem!
        """
        try:
            kind = nodes.Get_Kind(node)
        except:
            return None

        # Handle Slice_Name FIRST (before Parenthesis_Name)
        # Slice names like signal(high downto low) might come through as Slice_Name not Parenthesis_Name
        if kind == nodes.Iir_Kind.Slice_Name:
            return self._parse_slice_name_lowlevel(node)

        # Handle Parenthesis_Name (function calls / type conversions / indexed access)
        if kind == nodes.Iir_Kind.Parenthesis_Name:
            # First, check if this is actually indexed/sliced access by checking the prefix
            try:
                prefix = nodes.Get_Prefix(node)
                if prefix != nodes.Null_Iir:
                    prefix_kind = nodes.Get_Kind(prefix)

                    # DEBUG
                    prefix_kind_name = str(prefix_kind)
                    if hasattr(nodes, 'Get_Identifier') and prefix_kind == nodes.Iir_Kind.Simple_Name:
                        try:
                            prefix_ident = nodes.Get_Identifier(prefix)
                            prefix_name_str = name_table.Get_Name_Ptr(prefix_ident)
                            if 'instr' in prefix_name_str.lower():
                                print(f"DEBUG Parenthesis: prefix={prefix_name_str}, kind={prefix_kind_name}, in signal_nodes={prefix_name_str in self.signal_nodes}")
                        except:
                            pass

                    # Check if prefix is a signal or variable reference
                    if prefix_kind == nodes.Iir_Kind.Simple_Name:
                        prefix_ident = nodes.Get_Identifier(prefix)
                        prefix_name = name_table.Get_Name_Ptr(prefix_ident)

                        # Check if it's a process variable (need scoped name, case-insensitive)
                        prefix_node = None
                        prefix_name_lower = prefix_name.lower()
                        if prefix_name_lower in self.signal_nodes:
                            prefix_node = self.signal_nodes[prefix_name_lower]
                        elif self._current_process_name:
                            scoped_name = f"{self._current_process_name}_{prefix_name}".lower()
                            if scoped_name in self.variable_nodes:
                                prefix_node = self.variable_nodes[scoped_name]

                        # If prefix is a known signal or variable, this might be indexed access
                        if prefix_node:
                            # DEBUG
                            if 'instr' in prefix_name.lower():
                                print(f"DEBUG: Processing {prefix_name}, getting assoc_chain...")

                            assoc_chain = nodes.Get_Association_Chain(node)
                            if assoc_chain != nodes.Null_Iir:
                                assoc = assoc_chain
                                actual = nodes.Get_Actual(assoc)
                                # NULL CHECK: Avoid GHDL assertion if actual is Null_Iir
                                if actual == nodes.Null_Iir:
                                    if 'instr' in prefix_name.lower():
                                        print(f"  -> actual is Null_Iir, returning None")
                                    return None
                                actual_kind = nodes.Get_Kind(actual)

                                # DEBUG
                                if 'instr' in prefix_name.lower():
                                    print(f"  -> actual_kind: {actual_kind}")

                                # Check if it's a simple integer (index) or a range (slice)
                                if actual_kind == nodes.Iir_Kind.Integer_Literal:
                                    # This is indexed access: signal(index) or variable(index)
                                    index_val = nodes.Get_Value(actual)
                                    index_node = self._create_constant_node(str(index_val))

                                    # prefix_node already determined above
                                    access_id = f"{prefix_node.id}_{index_val}"
                                    access_node = Node(
                                        node_id=access_id,
                                        data={
                                            'type': 'array_access',
                                            'bit_width': 1,  # Single bit access
                                        }
                                    )
                                    self.graph.add_node(access_node)

                                    # Add edges: array -> access_node, index -> access_node
                                    self.graph.add_edge(Edge(prefix_node, access_node, data={"type": "array"}))
                                    self.graph.add_edge(Edge(index_node, access_node, data={"type": "index"}))

                                    return access_node

                                elif actual_kind == nodes.Iir_Kind.Range_Expression:
                                    # This is a slice: signal(high downto low)
                                    # Parse the range bounds (same as in _parse_slice_name_lowlevel)
                                    try:
                                        # Try to get the range constraint first
                                        # In some contexts, the range might be stored differently
                                        left_bound = nodes.Get_Left_Limit(actual)
                                        right_bound = nodes.Get_Right_Limit(actual)

                                        # NULL CHECK: Avoid GHDL assertion if bounds are Null_Iir
                                        # If bounds are Null, fall back to DOM parser
                                        if left_bound == nodes.Null_Iir or right_bound == nodes.Null_Iir:
                                            if 'instr' in prefix_name.lower() or 'pc' in prefix_name.lower() or 'word_addr' in prefix_name.lower():
                                                print(f"  -> Range_Expression with Null bounds, falling back to DOM parser")
                                            return None

                                        direction = nodes.Get_Direction(actual)

                                        # Parse bounds
                                        left_val = None
                                        right_val = None

                                        if nodes.Get_Kind(left_bound) == nodes.Iir_Kind.Integer_Literal:
                                            left_val = nodes.Get_Value(left_bound)
                                        if nodes.Get_Kind(right_bound) == nodes.Iir_Kind.Integer_Literal:
                                            right_val = nodes.Get_Value(right_bound)

                                        if left_val is None or right_val is None:
                                            # Can't determine static range, fall back to DOM
                                            if 'instr' in prefix_name.lower() or 'pc' in prefix_name.lower():
                                                print(f"  -> Range_Expression with non-static bounds: falling back to DOM parser")
                                            return None

                                        # Determine high and low based on direction
                                        # direction: 0 = to, 1 = downto
                                        if direction == 1:  # downto
                                            high = left_val
                                            low = right_val
                                        else:  # to
                                            high = right_val
                                            low = left_val

                                        # Calculate bit width
                                        bit_width = abs(high - low) + 1

                                        # DEBUG: Log bit slice creation
                                        if 'instr' in prefix_name.lower() or 'word_addr' in prefix_name.lower() or 'pc' in prefix_name.lower():
                                            print(f"DEBUG PARSER: Creating bit_slice for {prefix_name}[{high}:{low}] (width={bit_width})")

                                        # Create bit_slice node
                                        slice_id = f"{prefix_node.id}_{high}_downto_{low}"
                                        slice_node = Node(
                                            node_id=slice_id,
                                            data={
                                                'type': 'bit_slice',
                                                'expression': {
                                                    'type': 'bit_slice',
                                                    'target': prefix_node.id,
                                                    'range': (high, low)
                                                },
                                                'bit_width': bit_width,
                                            }
                                        )
                                        self.graph.add_node(slice_node)

                                        # Add edge from prefix to slice
                                        self.graph.add_edge(Edge(prefix_node, slice_node, data={"type": "bit_access"}))

                                        return slice_node
                                    except Exception as e:
                                        # If any error occurs, fall back to DOM parsing
                                        if 'instr' in prefix_name.lower() or 'pc' in prefix_name.lower():
                                            print(f"  -> Range_Expression parsing error: {e}, falling back to DOM parser")
                                        return None

                                else:
                                    # This is indexed access with a computed expression
                                    # e.g., registers_debug(to_integer(unsigned(debug_sel)))
                                    # Parse the index expression recursively
                                    index_node = self._parse_lowlevel_node(actual)
                                    if index_node:
                                        # prefix_node already determined above

                                        # Determine element width from array type
                                        array_width = prefix_node.data.get('bit_width')
                                        # For arrays like a_registers (array of 32-bit vectors),
                                        # the element width should be the element type width
                                        # Default to 32 for RISC-V register files
                                        element_width = 32

                                        access_id = f"{prefix_node.id}_indexed_{index_node.id}"
                                        access_node = Node(
                                            node_id=access_id,
                                            data={
                                                'type': 'array_access',
                                                'bit_width': element_width,
                                            }
                                        )
                                        self.graph.add_node(access_node)

                                        # Add edges: array -> access_node, index -> access_node
                                        self.graph.add_edge(Edge(prefix_node, access_node, data={"type": "array"}))
                                        self.graph.add_edge(Edge(index_node, access_node, data={"type": "index"}))

                                        return access_node
            except:
                # If prefix check fails, fall through to function call handling
                pass

            # Not indexed access, treat as function call/type conversion
            # Get parameters
            assoc_chain = nodes.Get_Association_Chain(node)
            if assoc_chain != nodes.Null_Iir:
                # Parse first parameter (where operations are)
                assoc = assoc_chain
                actual = nodes.Get_Actual(assoc)

                # RECURSIVELY parse the parameter - this is where we find operations!
                return self._parse_lowlevel_node(actual)

            # No parameters or couldn't parse
            return None

        # Handle Unary Operators
        elif kind == nodes.Iir_Kind.Not_Operator:
            return self._parse_lowlevel_unary_op(node, 'not')

        # Handle Binary Operators - THIS IS WHAT WE'RE LOOKING FOR!
        elif kind == nodes.Iir_Kind.Addition_Operator:
            return self._parse_lowlevel_binary_op(node, '+')
        elif kind == nodes.Iir_Kind.Substraction_Operator:
            return self._parse_lowlevel_binary_op(node, '-')
        elif kind == nodes.Iir_Kind.Multiplication_Operator:
            return self._parse_lowlevel_binary_op(node, '*')
        elif kind == nodes.Iir_Kind.Division_Operator:
            return self._parse_lowlevel_binary_op(node, '/')
        elif kind == nodes.Iir_Kind.And_Operator:
            return self._parse_lowlevel_binary_op(node, 'and')
        elif kind == nodes.Iir_Kind.Or_Operator:
            return self._parse_lowlevel_binary_op(node, 'or')
        elif kind == nodes.Iir_Kind.Xor_Operator:
            return self._parse_lowlevel_binary_op(node, 'xor')
        elif kind == nodes.Iir_Kind.Nand_Operator:
            return self._parse_lowlevel_binary_op(node, 'nand')
        elif kind == nodes.Iir_Kind.Nor_Operator:
            return self._parse_lowlevel_binary_op(node, 'nor')
        elif kind == nodes.Iir_Kind.Xnor_Operator:
            return self._parse_lowlevel_binary_op(node, 'xnor')

        # Comparison Operators
        elif kind == nodes.Iir_Kind.Equality_Operator:
            return self._parse_lowlevel_binary_op(node, '=')
        elif kind == nodes.Iir_Kind.Inequality_Operator:
            return self._parse_lowlevel_binary_op(node, '/=')
        elif kind == nodes.Iir_Kind.Less_Than_Operator:
            return self._parse_lowlevel_binary_op(node, '<')
        elif kind == nodes.Iir_Kind.Less_Than_Or_Equal_Operator:
            return self._parse_lowlevel_binary_op(node, '<=')
        elif kind == nodes.Iir_Kind.Greater_Than_Operator:
            return self._parse_lowlevel_binary_op(node, '>')
        elif kind == nodes.Iir_Kind.Greater_Than_Or_Equal_Operator:
            return self._parse_lowlevel_binary_op(node, '>=')

        # Shift Operators
        elif kind == nodes.Iir_Kind.Sll_Operator:
            return self._parse_lowlevel_binary_op(node, 'sll')
        elif kind == nodes.Iir_Kind.Srl_Operator:
            return self._parse_lowlevel_binary_op(node, 'srl')
        elif kind == nodes.Iir_Kind.Sla_Operator:
            return self._parse_lowlevel_binary_op(node, 'sla')
        elif kind == nodes.Iir_Kind.Sra_Operator:
            return self._parse_lowlevel_binary_op(node, 'sra')
        elif kind == nodes.Iir_Kind.Rol_Operator:
            return self._parse_lowlevel_binary_op(node, 'rol')
        elif kind == nodes.Iir_Kind.Ror_Operator:
            return self._parse_lowlevel_binary_op(node, 'ror')

        # Modulo and Remainder
        elif kind == nodes.Iir_Kind.Modulus_Operator:
            return self._parse_lowlevel_binary_op(node, 'mod')
        elif kind == nodes.Iir_Kind.Remainder_Operator:
            return self._parse_lowlevel_binary_op(node, 'rem')

        # Concatenation
        elif kind == nodes.Iir_Kind.Concatenation_Operator:
            return self._parse_lowlevel_binary_op(node, '&')

        # Handle Simple Names (signals/variables)
        elif kind == nodes.Iir_Kind.Simple_Name:
            try:
                ident = nodes.Get_Identifier(node)
                signal_name = name_table.Get_Name_Ptr(ident)
                # Use lowercase for case-insensitive lookups
                signal_name_lower = signal_name.lower()
                if signal_name_lower in self.signal_nodes:
                    return self.signal_nodes[signal_name_lower]
                # Also check process variables (try scoped name first if in a process)
                if self._current_process_name:
                    scoped_name = f"{self._current_process_name}_{signal_name}".lower()
                    if scoped_name in self.variable_nodes:
                        return self.variable_nodes[scoped_name]
                if signal_name_lower in self.variable_nodes:
                    return self.variable_nodes[signal_name_lower]
                # Check if it's a constant reference - create literal with constant's value
                # Constants are stored with uppercase names (e.g., PC_JMP_RELATIVE_CONDITIONAL)
                # but pyGHDL may return lowercase names
                signal_name_upper = signal_name.upper()
                if signal_name in self.constants:
                    const_value = self.constants[signal_name]
                    # Create a literal node with the constant's actual value
                    return self._create_literal_node(const_value, bit_width=None)
                elif signal_name_upper in self.constants:
                    const_value = self.constants[signal_name_upper]
                    # Create a literal node with the constant's actual value
                    return self._create_literal_node(const_value, bit_width=None)
                # If not found but looks like a valid identifier, create a variable node
                # This handles process-local variables that weren't explicitly tracked
                if signal_name and signal_name[0].isalpha():
                    # Create scoped variable node if in a process (use lowercase for case-insensitive)
                    if self._current_process_name:
                        scoped_name = f"{self._current_process_name}_{signal_name}".lower()
                        node_id = f"var_{scoped_name}"
                    else:
                        scoped_name = signal_name.lower()
                        node_id = signal_name
                    # Create variable node on-the-fly for untracked process variables
                    # Default to 32-bit for RISC-V unsigned/signed operations
                    var_node = Node(
                        node_id=node_id,
                        data={
                            'type': 'variable',
                            'name': signal_name,
                            'scoped_name': scoped_name,
                            'process_name': self._current_process_name,
                            'display_name': signal_name,
                            'bit_width': 32,  # Default to 32-bit for RISC-V
                            'is_variable': True
                        }
                    )
                    self.graph.add_node(var_node)
                    self.variable_nodes[scoped_name] = var_node
                    return var_node
            except:
                pass
            return None

        # Handle Integer Literals
        elif kind == nodes.Iir_Kind.Integer_Literal:
            value = nodes.Get_Value(node)
            return self._create_constant_node(str(value))

        # Handle Character Literals (e.g., '1', '0')
        elif kind == nodes.Iir_Kind.Character_Literal:
            # Character literal like '1', '0'
            ident = nodes.Get_Identifier(node)
            char_value = name_table.Get_Name_Ptr(ident)
            # Create a 1-bit constant node
            const_node = self._create_constant_node(char_value)
            const_node.data['is_char_literal'] = True
            const_node.data['bit_width'] = 1
            return const_node

        # Handle String Literals (e.g., x"FFFFFFFC", "00110011")
        elif kind == nodes.Iir_Kind.String_Literal8:
            # For hex/binary literals, we need to extract the string value
            # Create a constant node for the literal
            try:
                # Get the string ID and length
                str_id = nodes.Get_String8_Id(node)
                str_len = nodes.Get_String_Length(node)

                # Get the actual string value from GHDL's string table
                from pyGHDL.libghdl import str_table
                # Convert to int if needed (pyGHDL sometimes returns enums/wrappers)
                str_id_int = int(str_id) if not isinstance(str_id, int) else str_id
                str_len_int = int(str_len) if not isinstance(str_len, int) else str_len

                # Get_String8_Ptr returns a Python string directly (not a pointer)
                actual_str = str_table.Get_String8_Ptr(str_id_int, str_len_int)

                # Create constant with the actual binary/hex value
                # Wrap in quotes to preserve format (e.g., "1" not x_1)
                const_node = self._create_constant_node(f'"{actual_str}"')
                const_node.data['is_string_literal'] = True
                const_node.data['string_value'] = actual_str

                # Determine bit width based on the literal's base (hex, octal, binary)
                # Note: pyGHDL expands hex/octal to binary, so str_len_int is already in bits
                # We use Get_Bit_String_Base to detect original format for proper rendering
                try:
                    bit_base = nodes.Get_Bit_String_Base(node)
                    # pyGHDL has already expanded to binary, so bit_width = string length
                    const_node.data['bit_width'] = str_len_int
                    if bit_base == nodes.NumberBaseType.Base_16:
                        # Was originally a hex literal - mark for hex output formatting
                        const_node.data['is_hex_literal'] = True
                except Exception:
                    # Fallback: just use string length as bit width
                    const_node.data['bit_width'] = str_len_int

                return const_node
            except Exception as e:
                # Log the error but fallback to a default value
                # This should rarely happen now that string extraction is fixed
                import sys
                print(f"Warning: Failed to extract String_Literal8: {e}", file=sys.stderr)

                # Fallback: create a constant node with a default mask value
                # Most VHDL hex literals in PC calculations are word-alignment masks
                const_node = self._create_constant_node("x_FFFFFFFC")
                const_node.data['is_string_literal'] = True
                const_node.data['bit_width'] = 32
                const_node.data['string_value'] = "FFFFFFFC"
                return const_node

        # Handle Indexed Names (e.g., signal(5), array(index))
        elif kind == nodes.Iir_Kind.Indexed_Name:
            return self._parse_indexed_name_lowlevel(node)

        # Handle Slice Names (e.g., signal(7 downto 0))
        elif kind == nodes.Iir_Kind.Slice_Name:
            return self._parse_slice_name_lowlevel(node)

        # Handle Parenthesis Expressions (e.g., (a + b))
        elif kind == nodes.Iir_Kind.Parenthesis_Expression:
            # Unwrap the parentheses and parse the inner expression
            try:
                inner_expr = nodes.Get_Expression(node)
                if inner_expr != nodes.Null_Iir:
                    return self._parse_lowlevel_node(inner_expr)
            except:
                pass
            return None

        # Unsupported kind
        return None

    def _is_signed_type_conversion(self, node) -> bool:
        """Check if a low-level IIR node is a signed() type conversion"""
        try:
            kind = nodes.Get_Kind(node)
            if kind == nodes.Iir_Kind.Parenthesis_Name:
                prefix = nodes.Get_Prefix(node)
                if prefix != nodes.Null_Iir:
                    prefix_kind = nodes.Get_Kind(prefix)
                    if prefix_kind == nodes.Iir_Kind.Simple_Name:
                        prefix_ident = nodes.Get_Identifier(prefix)
                        prefix_name = name_table.Get_Name_Ptr(prefix_ident)
                        return prefix_name.lower() == 'signed'
        except:
            pass
        return False

    def _parse_lowlevel_binary_op(self, node, op: str) -> Optional[Node]:
        """Parse a binary operator node at low level"""
        try:
            left_node = nodes.Get_Left(node)
            right_node = nodes.Get_Right(node)

            # Check if operands are wrapped in signed() type conversions
            # This is critical for signed comparisons (BGE, BLT, SLT, etc.)
            left_is_signed = self._is_signed_type_conversion(left_node)
            right_is_signed = self._is_signed_type_conversion(right_node)
            is_signed_comparison = left_is_signed and right_is_signed

            left = self._parse_lowlevel_node(left_node)
            right = self._parse_lowlevel_node(right_node)

            if left and right:
                # For signed comparisons, use signed comparison operators
                actual_op = op
                signed_comparison_ops = ['<', '>', '<=', '>=']
                if is_signed_comparison and op in signed_comparison_ops:
                    actual_op = op + 's'  # '<' -> '<s', '>' -> '>s', etc.

                # Create standardized operation node
                op_id = f"{left.id}_{actual_op}_{right.id}"
                op_node = self._create_operation_node(
                    node_id=op_id,
                    operator=actual_op,
                    left_name=str(left.id),
                    right_name=str(right.id)
                )

                # Mark as signed if applicable
                if is_signed_comparison:
                    op_node.data['is_signed'] = True

                # Propagate bit width from operands to result
                left_width = left.data.get('bit_width') if left.data else None
                right_width = right.data.get('bit_width') if right.data else None

                # Comparison operators always produce 1-bit boolean result
                comparison_ops = ['=', '/=', '<', '>', '<=', '>=', '==', '!=', '<s', '>s', '<=s', '>=s']
                # For concatenation, result width is the SUM of operand widths
                if actual_op in comparison_ops:
                    op_node.data['bit_width'] = 1
                elif op == '&':
                    if left_width and right_width:
                        op_node.data['bit_width'] = left_width + right_width
                    elif left_width:
                        op_node.data['bit_width'] = left_width
                    elif right_width:
                        op_node.data['bit_width'] = right_width
                    else:
                        op_node.data['bit_width'] = 32
                else:
                    # For most operations, the result width is the max of operand widths
                    if left_width and right_width:
                        op_node.data['bit_width'] = max(left_width, right_width)
                    elif left_width:
                        op_node.data['bit_width'] = left_width
                    elif right_width:
                        op_node.data['bit_width'] = right_width
                    else:
                        # Default to 32-bit for RISC-V operations
                        op_node.data['bit_width'] = 32

                self.graph.add_node(op_node)

                # Create edges
                left_edge = Edge(left, op_node, data={"type": "unknown", "operand": "left"})
                right_edge = Edge(right, op_node, data={"type": "unknown", "operand": "right"})
                self.graph.add_edge(left_edge)
                self.graph.add_edge(right_edge)

                return op_node
        except Exception as e:
            pass

        return None

    def _parse_lowlevel_unary_op(self, node, op: str) -> Optional[Node]:
        """Parse a unary operator node at low level (e.g., NOT, negation)"""
        try:
            operand_node = nodes.Get_Operand(node)
            operand = self._parse_lowlevel_node(operand_node)

            if operand:
                # Create standardized operation node
                op_id = f"{op}_{operand.id}"
                op_node = self._create_operation_node(
                    node_id=op_id,
                    operator=op,
                    left_name=str(operand.id)
                )

                # Propagate bit width from operand to result
                operand_width = operand.data.get('bit_width') if operand.data else None
                if operand_width:
                    op_node.data['bit_width'] = operand_width
                else:
                    # Default to 1-bit for logical NOT
                    op_node.data['bit_width'] = 1

                self.graph.add_node(op_node)

                # Create edge
                edge = Edge(operand, op_node, data={"type": "unknown", "operand": "unary"})
                self.graph.add_edge(edge)

                return op_node
        except Exception as e:
            pass

        return None

    def _parse_indexed_name_lowlevel(self, node) -> Optional[Node]:
        """
        Parse indexed name (e.g., signal(5), array(index)).
        Creates an array_access node.
        """
        try:
            # Get the prefix (base signal)
            prefix = nodes.Get_Prefix(node)
            prefix_node = self._parse_lowlevel_node(prefix)

            if not prefix_node:
                return None

            # Get the index list
            index_list = nodes.Get_Index_List(node)
            if index_list == nodes.Null_Iir_List:
                return prefix_node  # No index, just return the prefix

            # For now, handle single index (most common case)
            # Get first index
            first_index = nodes.Get_Nth_Element(index_list, 0)
            if first_index == nodes.Null_Iir:
                return prefix_node

            index_node = self._parse_lowlevel_node(first_index)
            if not index_node:
                # If index is a simple integer, create a literal node
                if nodes.Get_Kind(first_index) == nodes.Iir_Kind.Integer_Literal:
                    index_val = nodes.Get_Value(first_index)
                    index_node = self._create_constant_node(str(index_val))
                else:
                    return prefix_node

            # Create array_access node
            access_id = f"{prefix_node.id}_{index_node.id}"
            access_node = Node(
                node_id=access_id,
                data={
                    'type': 'array_access',
                    'bit_width': 1,  # Single bit access
                }
            )
            self.graph.add_node(access_node)

            # Add edges: array -> access_node, index -> access_node
            self.graph.add_edge(Edge(prefix_node, access_node, data={"type": "array"}))
            self.graph.add_edge(Edge(index_node, access_node, data={"type": "index"}))

            return access_node

        except Exception as e:
            print(f"  Warning: Failed to parse indexed name: {e}")
            return None

    def _parse_slice_name_lowlevel(self, node) -> Optional[Node]:
        """
        Parse slice name (e.g., signal(7 downto 0), signal(high downto low)).
        Creates a bit_slice node.
        """
        try:
            # Get the prefix (base signal)
            prefix = nodes.Get_Prefix(node)
            prefix_node = self._parse_lowlevel_node(prefix)

            if not prefix_node:
                return None

            # Get the suffix (range)
            suffix = nodes.Get_Suffix(node)
            if suffix == nodes.Null_Iir:
                return prefix_node

            # Parse the range
            if nodes.Get_Kind(suffix) == nodes.Iir_Kind.Range_Expression:
                left_bound = nodes.Get_Left_Limit(suffix)
                right_bound = nodes.Get_Right_Limit(suffix)
                direction = nodes.Get_Direction(suffix)

                # Parse bounds
                left_val = None
                right_val = None

                if nodes.Get_Kind(left_bound) == nodes.Iir_Kind.Integer_Literal:
                    left_val = nodes.Get_Value(left_bound)
                if nodes.Get_Kind(right_bound) == nodes.Iir_Kind.Integer_Literal:
                    right_val = nodes.Get_Value(right_bound)

                if left_val is None or right_val is None:
                    # Can't determine static range, return prefix
                    return prefix_node

                # Determine high and low based on direction
                # direction: 0 = to, 1 = downto
                if direction == 1:  # downto
                    high = left_val
                    low = right_val
                else:  # to
                    high = right_val
                    low = left_val

                # Calculate bit width
                bit_width = abs(high - low) + 1

                # DEBUG: Log bit slice creation
                if 'instr' in str(prefix_node.id).lower():
                    print(f"DEBUG PARSER: Creating bit_slice for {prefix_node.id}[{high}:{low}] (width={bit_width})")

                # Create bit_slice node
                slice_id = f"{prefix_node.id}_{high}_downto_{low}"
                slice_node = Node(
                    node_id=slice_id,
                    data={
                        'type': 'bit_slice',
                        'expression': {
                            'type': 'bit_slice',
                            'target': prefix_node.id,
                            'range': (high, low)
                        },
                        'bit_width': bit_width,
                    }
                )
                self.graph.add_node(slice_node)

                # Add edge from prefix to slice
                self.graph.add_edge(Edge(prefix_node, slice_node, data={"type": "bit_access"}))

                return slice_node

            return prefix_node

        except Exception as e:
            print(f"  Warning: Failed to parse slice name: {e}")
            return None

    # =========================================================================
    # Standardized Node Creation Helpers (ISA-compatible format)
    # =========================================================================

    def _create_variable_node(self, name: str, width: Optional[int] = None,
                            is_arch_state: bool = False, initial_value=None) -> Node:
        """
        Create a standardized variable/signal node compatible with ISA parser format.

        Args:
            name: Variable identifier
            width: Bit width (None for inference)
            is_arch_state: True if this is architectural state (ISA state)
            initial_value: Initial/default value (hex string, int, or None)

        Returns:
            Node with ISA-compatible metadata
        """
        if is_arch_state:
            # Create ISA state node (architectural state)
            return Node(
                node_id=name,
                data={
                    'type': 'isa_state',
                    'name': name,
                    'display_name': name,
                    'bit_width': width,
                    'initial_value': initial_value,  # Store initial value
                    'array_depth': None,  # Will be inferred from usage
                    'is_memory': False,   # Will be inferred from usage
                    'dimensions': [],      # Will be populated for arrays
                    'dimension_count': 0   # Will be updated for arrays
                },
                is_arch_state=True,
                from_isa_spec=False  # Parsed from VHDL, not ISA file
            )
        else:
            # Create variable node
            return Node(
                node_id=name,
                data={
                    'type': 'var',
                    'name': name,
                    'display_name': name,
                    'width': width,
                    'bit_width': width,
                    'width_explicit': width is not None,
                    'initial_value': initial_value  # Store initial value
                },
                from_isa_spec=False
            )

    def _create_operation_node(self, node_id: str, operator: str,
                              left_name: str = "", right_name: str = "") -> Node:
        """
        Create a standardized operation node compatible with ISA parser format.

        Args:
            node_id: Unique node identifier
            operator: Operator symbol ('+', '-', '&', '|', etc.)
            left_name: Left operand name (for display)
            right_name: Right operand name (for display)

        Returns:
            Node with ISA-compatible metadata
        """
        display = f"({left_name} {operator} {right_name})" if left_name and right_name else node_id
        return Node(
            node_id=node_id,
            data={
                'type': 'operation',
                'operator': operator,  # Use 'operator' not 'op'
                'display_name': display
            }
        )

    def _create_literal_node(self, value, node_id: Optional[str] = None, bit_width: Optional[int] = None) -> Node:
        """
        Create a standardized literal/constant node compatible with ISA parser format.

        Args:
            value: Constant value
            node_id: Optional node ID (auto-generated if None)
            bit_width: Optional bit width (inferred if not provided)

        Returns:
            Node with ISA-compatible metadata
        """
        if node_id is None:
            node_id = f"const_{self._temp_var_counter}"
            self._temp_var_counter += 1

        # Try to infer bit_width if not provided
        if bit_width is None:
            value_str = str(value)
            # Check for binary literals: "101", "1010", etc.
            if value_str.startswith('"') and value_str.endswith('"'):
                # Binary string literal
                inner = value_str[1:-1]
                if all(c in '01' for c in inner):
                    bit_width = len(inner)
            # Check for single bit literals: '0', '1'
            elif value_str.startswith("'") and value_str.endswith("'"):
                bit_width = 1
            # Check for hex literals: x"DEAD", x"FF"
            elif value_str.startswith('x"') and value_str.endswith('"'):
                hex_digits = value_str[2:-1]
                bit_width = len(hex_digits) * 4

        return Node(
            node_id=node_id,
            data={
                'type': 'literal',  # Use 'literal' not 'constant'
                'value': value,
                'display_name': str(value),
                'bit_width': bit_width  # Add bit width to metadata
            }
        )

    def _extract_bit_width_from_type(self, type_obj) -> Optional[int]:
        """
        Extract bit width from a VHDL type/subtype object.

        Returns:
            Bit width as integer, or None if cannot be determined
        """
        # Note: pyGHDL objects may have custom __bool__ that returns False
        # Use explicit None check instead
        if type_obj is None:
            return None

        # Convert to string for pattern matching
        type_str = str(type_obj)

        # Remove trailing '?' (indicates default value present)
        type_str = type_str.rstrip('?').strip()

        # std_logic -> 1 bit
        if 'std_logic' == type_str.lower() or 'std_ulogic' == type_str.lower():
            return 1

        # Check for constrained array types (std_logic_vector, unsigned, signed)
        # These have Constraints attribute with DescendingRangeExpression or AscendingRangeExpression
        if hasattr(type_obj, 'Constraints'):
            constraints = type_obj.Constraints
            if constraints and len(constraints) > 0:
                constraint = constraints[0]
                constraint_type = type(constraint).__name__

                # Handle DescendingRangeExpression (N downto M)
                if constraint_type == 'DescendingRangeExpression':
                    if hasattr(constraint, 'LeftOperand') and hasattr(constraint, 'RightOperand'):
                        try:
                            # Extract numeric values from operands
                            high = self._extract_integer_from_expression(constraint.LeftOperand)
                            low = self._extract_integer_from_expression(constraint.RightOperand)
                            if high is not None and low is not None:
                                return high - low + 1
                        except Exception:
                            pass

                # Handle AscendingRangeExpression (M to N)
                elif constraint_type == 'AscendingRangeExpression':
                    if hasattr(constraint, 'LeftOperand') and hasattr(constraint, 'RightOperand'):
                        try:
                            low = self._extract_integer_from_expression(constraint.LeftOperand)
                            high = self._extract_integer_from_expression(constraint.RightOperand)
                            if high is not None and low is not None:
                                return high - low + 1
                        except Exception:
                            pass

        # Fallback: try string pattern matching
        import re

        # Pattern: vector_type(high downto low)
        pattern = r'\w+\s*\(\s*(\d+)\s+downto\s+(\d+)\s*\)'
        match = re.search(pattern, type_str)
        if match:
            high = int(match.group(1))
            low = int(match.group(2))
            return high - low + 1

        # Pattern: vector_type(low to high)
        pattern = r'\w+\s*\(\s*(\d+)\s+to\s+(\d+)\s*\)'
        match = re.search(pattern, type_str)
        if match:
            low = int(match.group(1))
            high = int(match.group(2))
            return high - low + 1

        # integer -> 32 bits (default)
        if 'integer' in type_str.lower():
            return 32

        # natural -> 31 bits (non-negative integer)
        if 'natural' in type_str.lower():
            return 31

        # boolean -> 1 bit
        if 'boolean' in type_str.lower():
            return 1

        # Could not determine width
        return None

    def _extract_initial_value(self, expr):
        """
        Extract initial/default value from a VHDL expression.

        Args:
            expr: pyGHDL expression object (DefaultExpression)

        Returns:
            Initial value as string (e.g., 'x"FFFFFFFC"'), int, or None
        """
        if expr is None:
            return None

        expr_type = type(expr).__name__

        # Handle StringLiteral (bit string literals like x"FFFFFFFC")
        # StringLiteral.__str__ wraps value in quotes, so access Value directly
        if expr_type == 'StringLiteral':
            if hasattr(expr, 'Value'):
                return expr.Value
            # Fallback to string representation
            return str(expr).strip('"')

        expr_str = str(expr)

        # Handle aggregates like (others => '0') - common for vector initialization
        if expr_type == 'Aggregate' or 'aggregate' in expr_str.lower():
            # Store as string representation to be interpreted by generator
            return expr_str

        # Handle based literals (hex, binary, octal)
        # e.g., x"FFFFFFFC", X"00000000", b"1010", o"77"
        if expr_type in ['BasedLiteral', 'CharacterLiteral']:
            # Return as-is, let generator interpret
            return expr_str

        # Handle simple character literal like '0' or '1'
        if expr_type == 'CharacterLiteral':
            return expr_str

        # Handle integer literals
        if expr_type == 'IntegerLiteral':
            if hasattr(expr, 'Value'):
                return int(expr.Value)
            # Try to extract from string
            try:
                return int(expr_str)
            except ValueError:
                return expr_str

        # Handle physical literals (with units)
        if expr_type == 'PhysicalLiteral':
            return expr_str

        # String representation - covers hex literals like x"..." and unsigned(x"...")
        # Clean up and return
        expr_str = expr_str.strip()
        if expr_str:
            return expr_str

        return None

    def _extract_integer_from_expression(self, expr) -> Optional[int]:
        """Extract integer value from a pyGHDL expression object."""
        if expr is None:
            return None

        expr_type = type(expr).__name__

        # Direct integer literal
        if expr_type == 'IntegerLiteral':
            return int(str(expr))

        # Try converting string representation to int
        try:
            return int(str(expr))
        except ValueError:
            pass

        return None

    # Legacy helper functions for backward compatibility during migration
    def _create_constant_node(self, expr) -> Node:
        """Create a node for a constant literal (legacy - use _create_literal_node)"""
        # Use target width if available from assignment context
        target_width = getattr(self, '_current_target_width', None)

        # Detect CharacterLiteral (like '0', '1') - these are always 1 bit
        expr_type = type(expr).__name__

        if expr_type == 'CharacterLiteral':
            # Character literals are always single bit
            node = self._create_literal_node(str(expr), bit_width=1)
        elif expr_type == 'StringLiteral':
            # StringLiteral.__str__ wraps value in quotes, so access Value directly
            # This preserves hex literals like x"FFFFFFFF" without extra quoting
            if hasattr(expr, 'Value'):
                value = expr.Value
            else:
                value = str(expr)
            node = self._create_literal_node(value, bit_width=target_width)
        else:
            node = self._create_literal_node(str(expr), bit_width=target_width)

        self.graph.add_node(node)
        return node

    def _create_temp_var(self) -> Node:
        """Create a temporary variable node (legacy)"""
        temp_id = f"temp_var_{self._temp_var_counter}"
        self._temp_var_counter += 1
        node = self._create_variable_node(temp_id, width=None, is_arch_state=False)
        self.graph.add_node(node)
        return node


# Convenience function to maintain API compatibility with regex parser
def parse_vhdl_file(filename: str) -> ResourceGraph:
    """Parse a VHDL file and return a ResourceGraph"""
    parser = VHDLParserPyGHDL()
    return parser.parse_file(filename)
