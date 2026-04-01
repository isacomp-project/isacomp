"""
Real ILAng JSON parser for compressed format.

Parses ILAng JSON exports (with compressed single-letter keys) and converts
them to ResourceGraph representations.
"""

import json
from typing import Dict, Any, List, Optional, Set
from core.resource_graph import ResourceGraph, Node, Edge
from core.graph_merger import split_arch_state_nodes
from .ila_opcodes import *
from .ila_transformations import apply_ila_transformations


class RealILAParser:
    """Parser for real ILAng JSON format with compressed keys."""

    def __init__(self):
        self.graph = ResourceGraph()
        self.expr_cache = {}  # expr_id -> node_id (string)
        self.state_map = {}   # state_name -> state_id
        self.ast_array = []   # Full AST array for lookups
        self.child_ila_map = {}  # child_index -> child_ila_data
        self.parent_child_edges = []  # Track parent-child relationships

    def parse_file(self, filename: str) -> ResourceGraph:
        """Parse an ILAng JSON file and return a ResourceGraph."""
        with open(filename, 'r') as f:
            data = json.load(f)
        return self.parse_json(data)

    def parse_json(self, data: Dict[str, Any], skip_optimizations: bool = False, ila_type: str = 'auto') -> ResourceGraph:
        """Parse ILAng JSON data and return a ResourceGraph.

        Args:
            data: ILA JSON data
            skip_optimizations: If True, skip transformations and state splitting (for child ILAs)
            ila_type: Type of ILA - 'isa' for instruction-set models (RISC-V), 'accelerator' for hardware accelerators (AES/SHA), 'auto' to detect
        """
        # Extract main components
        self.ast_array = data.get('a', [])
        top_ila = data.get('t', {})

        if not top_ila:
            raise ValueError("No top-level ILA found (missing 't' key)")

        # Auto-detect ILA type if not specified
        if ila_type == 'auto':
            # Accelerators have child ILAs, ISA models don't
            has_child_ilas = len(top_ila.get('c', [])) > 0
            ila_type = 'accelerator' if has_child_ilas else 'isa'

        is_accelerator = (ila_type == 'accelerator')

        # Phase 1: Extract structure
        self._extract_states(top_ila, ila_name=top_ila.get('n', 'top'), is_accelerator=is_accelerator)

        # Phase 2: Parse instructions
        for instr_data in top_ila.get('instr', []):
            self._parse_instruction(instr_data, ila_name=top_ila.get('n', 'top'))

        # Phase 3: Parse child ILAs (hierarchical support)
        child_ila_list = top_ila.get('c', [])
        has_child_ilas = len(child_ila_list) > 0
        for child_idx, child_ila in enumerate(child_ila_list):
            self._parse_child_ila(child_ila, child_idx, parent_ila_name=top_ila.get('n', 'top'))

        # Phase 3.5: Inline function applications with their implementations
        self._inline_function_applications(data)

        # Phase 3.6: Replace uninterpreted functions with state references
        self.inline_uninterpreted_functions()

        # Phase 3.7: Add state transitions for inlined child ILA instructions
        self.add_child_state_transitions()

        # Phase 3.8: Initialize child ILA inputs when starting encryption
        self.add_child_input_initialization()

        # Phase 3.9: Transform ILA-specific patterns to structural form
        # Only apply for ISA-style ILAs (transformations can break accelerator inlined bodies)
        # AND not explicitly skipped (for child ILA parsing)
        if not is_accelerator and not skip_optimizations:
            # Apply regfile transformation per-instruction so merger recognizes rf as shared state
            apply_ila_transformations(self.graph, include_regfile=True)

        # Phase 4: Optimize - apply architectural state splitting
        # Only apply for ISA-style ILAs (splitting breaks accelerator assignment/modifies matching)
        # AND not explicitly skipped (for child ILA parsing)
        if not is_accelerator and not skip_optimizations:
            self.graph.classify_architectural_state()
            split_arch_state_nodes(self.graph)

        return self.graph

    def _extract_states(self, top_ila: Dict[str, Any], ila_name: str = "top", is_accelerator: bool = False):
        """Extract state variables from an ILA (top-level or child).

        Args:
            top_ila: ILA data dictionary
            ila_name: Name of the ILA
            is_accelerator: If True, scan all expressions for states (needed for child functions).
                           If False, use official state list (correct for ISA models).
        """
        if is_accelerator:
            # ACCELERATOR MODE: Scan all expressions for state declarations
            # ILAng exports state declarations as expressions with u=1 (state decl) that have names
            # The state list t['s'] may point to input expressions (u=3) without names
            # So we scan all expressions for state declarations instead

            # First, find all state declarations (u=1 with 'n' field)
            state_decls = {}
            for i, expr in enumerate(self.ast_array):
                if isinstance(expr, dict) and expr.get('u') == 1 and 'n' in expr:
                    state_name = expr.get('n')
                    state_id = expr.get('i')  # Use expression ID, not array index
                    state_decls[state_name] = (state_id, expr)

            # Process state declarations
            for state_name, (state_id, expr) in state_decls.items():
                # Skip if already processed
                if state_id in self.expr_cache:
                    continue

                self.state_map[state_name] = state_id
                self._create_state_node(state_id, expr, state_name, ila_name, is_arch=True)
        else:
            # ISA MODE: Use official state list from ILA
            # This is the correct approach for ISA-style ILAs (RISC-V)
            # x0-x31 will be transformed to rf array by apply_ila_transformations
            state_ids = top_ila.get('s', [])

            for state_id in state_ids:
                expr = self._find_expr_by_id(state_id)
                if expr:
                    state_name = expr.get('n', f'state_{state_id}')
                    self.state_map[state_name] = state_id
                    self._create_state_node(state_id, expr, state_name, ila_name, is_arch=True)

    def _create_state_node(self, state_id: int, expr: Dict[str, Any], state_name: str, ila_name: str, is_arch: bool):
        """Create a state node from ILA state data."""
        # Skip if already in cache
        if state_id in self.expr_cache:
            return

        # Create architectural state node using same structure as ISA parser
        sort_info = expr.get('s', {})
        sort_uid = sort_info.get('u', 0)

        if sort_uid == SORT_UID_BV:
            # Bitvector state - treat as single-dimensional
            width = sort_info.get('w', 32)
            node_data = {
                "type": "isa_state",
                "name": state_name,
                "display_name": state_name,
                "dimensions": [(width - 1, 0)],  # Single dimension [width-1:0]
                "dimension_count": 1,
                "bit_width": width,
                "array_depth": None,
                "is_memory": False,
                "ila_id": state_id,
                "ila_name": ila_name  # Track which ILA this state belongs to
            }

        elif sort_uid == SORT_UID_MEM:
            # Memory state - treat as multi-dimensional like ISA
            addr_width = sort_info.get('a', 32)
            data_width = sort_info.get('d', 32)
            # Compute actual array depth from address width
            # Cap at 256 entries for large address spaces (>8 bits) to avoid huge arrays
            if addr_width <= 8:
                array_depth = 2 ** addr_width
            else:
                # For large memories, use a reasonable default depth
                # Actual memory size will be determined by initialization/usage
                array_depth = 256

            node_data = {
                "type": "isa_state",
                "name": state_name,
                "display_name": state_name,
                "dimensions": [(data_width - 1, 0), (addr_width - 1, 0)],
                "dimension_count": 2,
                "bit_width": data_width,
                "array_depth": array_depth,  # Actual array depth
                "is_memory": True,
                "addr_width": addr_width,  # Keep for reference
                "data_width": data_width,
                "ila_id": state_id,
                "ila_name": ila_name  # Track which ILA this state belongs to
            }

        else:
            # Unknown sort, create basic node
            node_data = {
                "type": "isa_state",
                "name": state_name,
                "display_name": state_name,
                "ila_id": state_id,
                "ila_name": ila_name  # Track which ILA this state belongs to
            }

        node = Node(state_name, node_data, is_arch_state=is_arch, from_isa_spec=False)
        self.graph.add_node(node)
        self.expr_cache[state_id] = node.id

    def _parse_instruction(self, instr_data: Dict[str, Any], ila_name: str = "top"):
        """Parse a single instruction and add to graph."""
        instr_name = instr_data.get('n', 'unnamed')
        decode_id = instr_data.get('d')
        updates = instr_data.get('u', {})
        program_id = instr_data.get('p')  # Child ILA program reference

        # Create instruction node
        node_data = {
            "type": "instruction",
            "name": instr_name,
            "decode_id": decode_id,
            "ila_name": ila_name,  # Track which ILA this instruction belongs to
            "child_program_id": program_id  # Track if this triggers a child ILA
        }
        instr_node = Node(f"instr_{instr_name}", node_data, from_isa_spec=False)
        self.graph.add_node(instr_node)

        # Parse decode expression (creates decode condition subgraph)
        if decode_id:
            decode_node_id = self._parse_expression(decode_id)
            if decode_node_id:
                # Connect decode to instruction
                edge = Edge(
                    self.graph.nodes[decode_node_id],
                    instr_node,
                    data={'type': 'decode_condition'}
                )
                self.graph.add_edge(edge)

        # Parse update expressions
        for state_name, update_id in updates.items():
            state_id = self.state_map.get(state_name)
            if state_id is None:
                if instr_name in ['OPERATE', 'FirstRound']:  # Debug
                    print(f"        [{instr_name}] State {state_name} not in state_map!")
                continue

            # Check if update is just the state itself (no change)
            if update_id == state_id:
                # No actual update, skip
                continue

            # Parse update expression
            update_node_id = self._parse_expression(update_id)
            if update_node_id:
                # Get architectural state node
                arch_state_node_id = self.expr_cache.get(state_id)
                if arch_state_node_id is None:
                    continue

                update_node = self.graph.nodes[update_node_id]

                # Check if this is a STORE operation (array_access write to memory)
                # For STORE operations, the operation itself represents the write,
                # so we don't create an assignment edge OR modifies edge to the architectural state
                # (matching ISA parser behavior)
                is_store_op = (update_node.data.get('type') == 'array_access' and
                               update_node.data.get('access_mode') == 'write')

                if not is_store_op:
                    # Connect update to architectural state (normal case)
                    # Tag with instruction ID so generator can match assignments to instructions
                    edge1 = Edge(
                        update_node,
                        self.graph.nodes[arch_state_node_id],
                        data={'type': 'assignment', 'instruction': instr_node.id}
                    )
                    self.graph.add_edge(edge1)

                    # Connect instruction to architectural state
                    # (NOT for STORE operations - they don't have modifies edges in ISA)
                    edge2 = Edge(
                        instr_node,
                        self.graph.nodes[arch_state_node_id],
                        data={'type': 'modifies'}
                    )
                    self.graph.add_edge(edge2)

    def _parse_child_ila(self, child_ila: Dict[str, Any], child_idx: int, parent_ila_name: str = "top"):
        """Parse a child ILA and integrate it into the graph."""
        child_name = child_ila.get('n', f'child_{child_idx}')
        fetch_expr_id = child_ila.get('f')  # Fetch expression (state variable that drives child)
        valid_expr_id = child_ila.get('v')  # Valid condition

        # Store child ILA data for reference
        self.child_ila_map[child_idx] = {
            'name': child_name,
            'fetch_id': fetch_expr_id,
            'valid_id': valid_expr_id,
            'parent': parent_ila_name
        }

        # Extract child states - BUT only create new nodes for states not already created by parent
        # Child ILAs often inherit/share parent states in their state list
        child_state_ids = set(child_ila.get('s', []))
        for state_id in child_state_ids:
            # Check if this state was already created (shared with parent)
            if state_id in self.expr_cache:
                # State already exists (from parent or earlier sibling), don't recreate
                # But we could add child ILA name to metadata if needed for tracking
                continue

            # This is a new child-specific state, create it
            expr = self._find_expr_by_id(state_id)
            if expr:
                state_name = expr.get('n', f'state_{state_id}')
                self.state_map[state_name] = state_id

                # Create architectural state node
                sort_info = expr.get('s', {})
                sort_uid = sort_info.get('u', 0)

                if sort_uid == SORT_UID_BV:
                    width = sort_info.get('w', 32)
                    node_data = {
                        "type": "isa_state",
                        "name": state_name,
                        "display_name": state_name,
                        "dimensions": [(width - 1, 0)],
                        "dimension_count": 1,
                        "bit_width": width,
                        "array_depth": None,
                        "is_memory": False,
                        "ila_id": state_id,
                        "ila_name": child_name  # Mark as child ILA state
                    }
                    is_arch = True

                elif sort_uid == SORT_UID_MEM:
                    addr_width = sort_info.get('a', 32)
                    data_width = sort_info.get('d', 32)
                    node_data = {
                        "type": "isa_state",
                        "name": state_name,
                        "display_name": state_name,
                        "dimensions": [(data_width - 1, 0), (addr_width - 1, 0)],
                        "dimension_count": 2,
                        "bit_width": data_width,
                        "array_depth": 2 ** addr_width,
                        "is_memory": True,
                        "addr_width": addr_width,
                        "data_width": data_width,
                        "ila_id": state_id,
                        "ila_name": child_name
                    }
                    is_arch = True

                else:
                    node_data = {
                        "type": "isa_state",
                        "name": state_name,
                        "display_name": state_name,
                        "ila_id": state_id,
                        "ila_name": child_name
                    }
                    is_arch = True

                node = Node(state_name, node_data, is_arch_state=is_arch, from_isa_spec=False)
                self.graph.add_node(node)
                self.expr_cache[state_id] = node.id

        # Parse child instructions
        for instr_data in child_ila.get('instr', []):
            self._parse_instruction(instr_data, ila_name=child_name)

        # Recursively parse nested children (if any)
        nested_children = child_ila.get('c', [])
        for nested_idx, nested_child in enumerate(nested_children):
            self._parse_child_ila(nested_child, nested_idx, parent_ila_name=child_name)

    def _parse_expression(self, expr_id: int) -> Optional[str]:
        """Parse an expression and return its node ID."""
        # Check cache first
        if expr_id in self.expr_cache:
            return self.expr_cache[expr_id]

        # Find expression in AST array
        expr = self._find_expr_by_id(expr_id)
        if not expr:
            return None

        expr_uid = expr.get('u', 0)

        if expr_uid == EXPR_UID_VAR:
            # Variable - check if already handled in state extraction
            if expr_id in self.expr_cache:
                return self.expr_cache[expr_id]

            # Not in declared states - create a node for it (e.g., function inputs)
            state_name = expr.get('n', f'var_{expr_id}')
            sort_info = expr.get('s', {})
            sort_uid = sort_info.get('u', 0)

            if sort_uid == SORT_UID_BV:
                width = sort_info.get('w', 32)
                node_data = {
                    "type": "isa_state",
                    "name": state_name,
                    "display_name": state_name,
                    "dimensions": [(width - 1, 0)],
                    "dimension_count": 1,
                    "bit_width": width,
                    "array_depth": None,
                    "is_memory": False,
                    "ila_id": expr_id,
                    "ila_name": "input"  # Mark as input variable
                }
            elif sort_uid == SORT_UID_MEM:
                addr_width = sort_info.get('a', 32)
                data_width = sort_info.get('d', 32)
                node_data = {
                    "type": "isa_state",
                    "name": state_name,
                    "display_name": state_name,
                    "dimensions": [(data_width - 1, 0), (addr_width - 1, 0)],
                    "dimension_count": 2,
                    "bit_width": data_width,
                    "array_depth": 2 ** addr_width,
                    "is_memory": True,
                    "addr_width": addr_width,
                    "data_width": data_width,
                    "ila_id": expr_id,
                    "ila_name": "input"
                }
            else:
                node_data = {
                    "type": "isa_state",
                    "name": state_name,
                    "display_name": state_name,
                    "ila_id": expr_id,
                    "ila_name": "input"
                }

            node = Node(state_name, node_data, is_arch_state=False, from_isa_spec=False)
            self.graph.add_node(node)
            self.expr_cache[expr_id] = node.id
            return node.id

        elif expr_uid == EXPR_UID_CONST:
            # Constant - use ISA-compatible "literal" type
            value_raw = expr.get('v', 0)
            # Normalize value: if it's a dict with 'v', extract the value
            if isinstance(value_raw, dict) and 'v' in value_raw:
                value = value_raw['v']
            else:
                value = value_raw

            sort_info = expr.get('s', {})
            width = sort_info.get('w', 32)

            node_data = {
                "type": "literal",  # Use ISA type instead of "constant"
                "value": value,
                "width": width,
                "ila_id": expr_id
            }
            node = Node(f"const_{expr_id}", node_data, from_isa_spec=False)
            self.graph.add_node(node)
            self.expr_cache[expr_id] = node.id
            return node.id

        elif expr_uid == EXPR_UID_OP:
            # Operation
            return self._parse_operation(expr, expr_id)

        return None

    def _parse_operation(self, expr: Dict[str, Any], expr_id: int) -> Optional[str]:
        """Parse an operation expression."""
        opcode = expr.get('o', -1)
        args = expr.get('a', [])
        params = expr.get('p', [])

        # Get node type and operator for this operation
        node_type, operator = get_node_type(opcode)

        # Parse argument expressions recursively
        arg_node_ids = []
        for arg_id in args:
            arg_node_id = self._parse_expression(arg_id)
            if arg_node_id:
                arg_node_ids.append(arg_node_id)

        # Create operation node with standard format
        node_data = {
            "type": node_type,
            "opcode": opcode,
            "ila_id": expr_id
        }

        # Add operator for operation nodes (matches ISA format)
        if operator:
            node_data["operator"] = operator
            # Create expression dict for compatibility with ISA operations
            node_data["expression"] = {
                "type": "binary_op" if len(args) == 2 else "unary_op",
                "operator": operator
            }

            # Set width=1 for comparison and boolean operations (NOT, etc.)
            from .ila_opcodes import is_comparison_op, OP_NOT
            if is_comparison_op(opcode) or opcode == OP_NOT:
                node_data["width"] = 1

        # Add access_mode for array_access nodes (LOAD vs STORE)
        # STORE operations are architectural state (like ISA parser's dmem[addr]_wr)
        is_array_write = False
        if node_type == "array_access":
            from .ila_opcodes import OP_LOAD, OP_STORE
            if opcode == OP_LOAD:
                node_data["access_mode"] = "read"
            elif opcode == OP_STORE:
                node_data["access_mode"] = "write"
                is_array_write = True

        # Add parameters for specific operations
        # CRITICAL FIX: ILAng JSON export uses OP_CONCAT (21) with params to represent EXTRACT!
        # When concat has params like [high, low], it's actually a bit slice operation
        if opcode == OP_CONCAT and len(params) >= 2:
            # This is actually an extract/bit_slice operation, not concat!
            node_data["type"] = "bit_slice"
            node_data["high_bit"] = params[0]
            node_data["low_bit"] = params[1]
            node_data["bitslice"] = (params[0], params[1])  # SMT converter expects this field
        elif opcode == OP_EXTRACT and len(params) >= 2:
            node_data["high_bit"] = params[0]
            node_data["low_bit"] = params[1]
            node_data["bitslice"] = (params[0], params[1])  # SMT converter expects this field
        elif opcode == OP_SEXT and len(params) >= 1:
            # Sign extend: param[0] is the target bit width
            node_data["target_width"] = params[0]
        elif opcode == OP_ZEXT and len(params) >= 1:
            # Zero extend: param[0] is the target bit width
            node_data["target_width"] = params[0]

        # All operation nodes have operator set via expression dict above
        # (no special handling needed - opcodes now map directly to ISA types)

        # Create node with proper naming for array_access operations
        # ISA uses names like: dmem[addr]_wr, imem[pc]_rd
        # ILA should use: mem[op_2371]_wr, mem[op_13]_rd
        node_id = f"op_{expr_id}"
        if node_type == "array_access" and len(arg_node_ids) >= 2:
            # arg_node_ids[0] = array (e.g., 'mem')
            # arg_node_ids[1] = index (e.g., 'op_2371')
            array_name = arg_node_ids[0]
            index_name = arg_node_ids[1]

            from .ila_opcodes import OP_LOAD, OP_STORE
            if opcode == OP_LOAD:
                node_id = f"{array_name}[{index_name}]_rd"
            elif opcode == OP_STORE:
                node_id = f"{array_name}[{index_name}]_wr"

        node = Node(node_id, node_data, from_isa_spec=False)

        # Mark STORE operations as architectural state (to match ISA parser behavior)
        # This allows the merger to recognize them as write ports
        if is_array_write:
            node.is_arch_state = True

        self.graph.add_node(node)

        # Connect arguments with appropriate edge types
        for i, arg_node_id in enumerate(arg_node_ids):
            # Determine edge type based on FINAL operation type (after any corrections above)
            final_type = node_data["type"]  # Use the corrected type, not original node_type
            if final_type == "concatenation":
                edge_type = 'concat_input'
            elif final_type == "bit_slice":
                edge_type = 'operand'  # Bit slice has single operand
            elif final_type in ["conditional", "ternary_op"]:  # Support both names
                # Ternary: condition, true_expr, false_expr
                if i == 0:
                    edge_type = 'ternary_condition'
                elif i == 1:
                    edge_type = 'ternary_true'
                elif i == 2:
                    edge_type = 'ternary_false'
                else:
                    edge_type = 'operand'
            elif final_type == "array_access":
                # Array access (LOAD/STORE operations)
                # ILA format: LOAD(array, addr) or STORE(array, addr, data)
                # Match ISA parser structure exactly:
                #   - Position 0 (array): array_index edge
                #   - Position 1 (addr): array_index edge
                #   - Position 2 (data): assignment edge (for STORE only)
                if i == 0:
                    edge_type = 'array_index'  # Base array
                elif i == 1:
                    edge_type = 'array_index'  # Address index
                elif i == 2:
                    # This is a STORE operation (has 3 args), position 2 is the write data
                    edge_type = 'assignment'
                else:
                    edge_type = 'operand'
            else:
                edge_type = 'operand'

            # Build edge data
            edge_data = {'type': edge_type, 'position': i}

            # For STORE operations (array_access with 3 args), add 'left' and 'right' metadata
            # to the assignment edge so Verilog generator can find it
            if (final_type == "array_access" and len(arg_node_ids) == 3 and i == 2 and
                edge_type == 'assignment'):
                # This is a STORE(array, addr, data) operation
                # arg_node_ids[0] = array (mem)
                # arg_node_ids[1] = addr
                # arg_node_ids[2] = data (current arg)

                array_node_id = arg_node_ids[0]
                addr_node_id = arg_node_ids[1]
                data_node_id = arg_node_ids[2]

                # Create 'left' metadata describing the array access: mem[addr]
                edge_data['left'] = {
                    'type': 'array_access',
                    'array': {'type': 'identifier', 'name': array_node_id},
                    'index': {'type': 'identifier', 'name': addr_node_id}
                }

                # Create 'right' metadata describing the data being written
                edge_data['right'] = {
                    'type': 'identifier',
                    'name': data_node_id
                }

            edge = Edge(
                self.graph.nodes[arg_node_id],
                node,
                data=edge_data
            )
            self.graph.add_edge(edge)

        self.expr_cache[expr_id] = node.id
        return node.id

    def _find_expr_by_id(self, expr_id: int) -> Optional[Dict[str, Any]]:
        """Find an expression in the AST array by its ID."""
        for expr in self.ast_array:
            if expr.get('i') == expr_id:
                return expr
        return None

    def _inline_function_applications(self, json_data: Dict[str, Any]):
        """Inline function_application nodes with their actual implementations."""
        import os

        # Find all function_application nodes
        func_apps = []
        for node_id, node in list(self.graph.nodes.items()):
            if isinstance(node.data, dict) and node.data.get('type') == 'function_application':
                func_apps.append((node_id, node))

        if not func_apps:
            return

        print(f"Inlining {len(func_apps)} function_application node(s)...")

        for node_id, func_node in func_apps:
            # Get function info from JSON
            ila_id = func_node.data.get('ila_id')
            if ila_id is None:
                continue

            # Find the AST node by expression ID
            ast_node = self._find_expr_by_id(ila_id)
            if not ast_node or not isinstance(ast_node, dict):
                continue

            # Get function ID - can be in 'f' field or first arg in 'a' array
            func_id = ast_node.get('f')
            if func_id is None and 'a' in ast_node and len(ast_node['a']) > 0:
                # For OP_APP_FUNC, first arg is the function ID
                func_id = ast_node['a'][0]

            if func_id is None:
                continue

            # Find function definition - check both 'f' array and 'a' array
            functions = json_data.get('f', [])
            func_def = None
            for f in functions:
                if f.get('i') == func_id:
                    func_def = f
                    break

            # If not found in 'f', check 'a' array for function declarations (u=5)
            if not func_def:
                for expr in json_data.get('a', []):
                    if expr.get('i') == func_id and expr.get('u') == 5:
                        func_def = expr
                        break

            if not func_def:
                continue

            func_name = func_def.get('n', 'unknown')

            if func_name == 'aes128':
                # Inline the AES-128 function
                print(f"  Inlining {func_name} function...")
                self._inline_aes128_function(func_node, json_data, func_name='aes128_function')
            elif func_name == 'aes128_function':
                # Inline the AES-128 function (alternative name)
                print(f"  Inlining {func_name} function...")
                self._inline_aes128_function(func_node, json_data, func_name='aes128_function')
            elif func_name == 'sha1_compress':
                # Inline the SHA-1 compression function
                print(f"  Inlining {func_name} function...")
                self._inline_aes128_function(func_node, json_data, func_name='sha1_compress')
            # else: Leave unknown functions as placeholders (handled by Verilog generator)

    def _inline_aes128_function(self, func_node: Node, json_data: Dict[str, Any], func_name: str = 'aes128'):
        """Inline child function implementation from json_data['c'] array."""

        # Find the child ILA in the 'c' array
        children = json_data.get('c', [])
        child_data = None

        for child in children:
            child_top = child.get('t', {})
            child_name = child_top.get('n', '')
            if child_name == func_name or child_name.replace('_', '') == func_name.replace('_', ''):
                child_data = child
                print(f"    Found child ILA: {child_name}")
                break

        if not child_data:
            print(f"    WARNING: Child function '{func_name}' not found in JSON data 'c' array")
            return

        # Parse the child function model (skip optimizations to preserve instruction bodies)
        child_parser = RealILAParser()
        child_graph = child_parser.parse_json(child_data, skip_optimizations=True)
        print(f"    Loaded {len(child_graph.nodes)} nodes from {func_name} function")

        # Merge the child graph into main graph
        # Use simplified func_name for prefixing (remove underscores for consistency)
        prefix_name = func_name.replace('_', '')
        self._merge_function_graph(child_graph, func_node, func_name=prefix_name)

    def _merge_function_graph(self, child_graph: ResourceGraph, func_node: Node, func_name: str):
        """Merge a child function graph at a function application point."""

        # Step 1: Find arguments to the function (incoming edges)
        func_args = []
        for edge_id, edge in list(self.graph.edges.items()):
            if edge.target.id == func_node.id:
                # This edge provides an argument to the function
                func_args.append((edge.data.get('position', 0) if isinstance(edge.data, dict) else 0, edge.source))

        func_args.sort(key=lambda x: x[0])  # Sort by position

        # Step 2: Find where function result is used (outgoing edges)
        result_targets = []
        for edge_id, edge in list(self.graph.edges.items()):
            if edge.source.id == func_node.id:
                # Function result flows to this edge
                result_targets.append((edge.target, edge.data))

        # Step 2a: Find parent instruction that calls this function
        # Do BFS from function node through expression graph to find assignment edge with instruction tag
        parent_instruction = None
        parent_instruction_id = None

        # BFS to find instruction that uses this function
        from collections import deque
        visited = set()
        queue = deque([func_node.id])
        visited.add(func_node.id)


        while queue and not parent_instruction:
            current_id = queue.popleft()

            # Check all outgoing edges from current node
            for edge in self.graph.edges.values():
                if edge.source.id == current_id:
                    # Check if this is an assignment edge with instruction tag
                    if isinstance(edge.data, dict):
                        if edge.data.get('type') == 'assignment' and 'instruction' in edge.data:
                            instr_id = edge.data['instruction']
                            if instr_id in self.graph.nodes:
                                parent_instruction = self.graph.nodes[instr_id]
                                parent_instruction_id = instr_id
                                print(f"      Found parent instruction (BFS): {instr_id} ({parent_instruction.data.get('name') if isinstance(parent_instruction.data, dict) else 'unknown'})")
                                break

                    # Continue BFS through expression nodes
                    target_id = edge.target.id
                    if target_id not in visited:
                        target_node = edge.target
                        target_type = target_node.data.get('type') if isinstance(target_node.data, dict) else None
                        # Traverse through any non-state, non-instruction node
                        if target_type not in ['isa_state', 'instruction', None]:
                            visited.add(target_id)
                            queue.append(target_id)

        # Get parent instruction's activation condition
        # The child should run when the parent instruction is ACTIVE, which means we need to check
        # the state VALUE that the parent instruction SETS, not its decode condition
        parent_decode_node = None
        if parent_instruction:
            # First, find the state variable that parent modifies and what value it sets
            state_node = None
            state_value_node = None

            for edge in self.graph.edges.values():
                if (isinstance(edge.data, dict) and
                    edge.data.get('type') == 'assignment' and
                    edge.data.get('instruction') == parent_instruction.id):
                    target = edge.target
                    if isinstance(target.data, dict) and target.data.get('type') == 'isa_state':
                        state_name = target.data.get('name', '')
                        if 'state' in state_name.lower() or 'status' in state_name.lower():
                            state_node = target
                            state_value_node = edge.source  # The value being assigned
                            print(f"      Found parent state variable: {state_name}")
                            print(f"      Parent assigns value from: {state_value_node.id}")
                            break

            # If we found a state assignment, create "state == value" condition
            if state_node and state_value_node:
                # Check if the assigned value is a constant
                if (isinstance(state_value_node.data, dict) and
                    state_value_node.data.get('type') == 'literal'):
                    # Use this literal value directly
                    state_value = state_value_node.data.get('value', 0)
                    print(f"      Parent sets state to constant: {state_value}")

                    # Create "state == value"
                    eq_op_id = f"eq_{state_node.id}_{state_value}"
                    eq_node = Node(eq_op_id, {
                        'type': 'operation',
                        'opcode': 13,  # OP_EQ
                        'operator': '==',
                        'name': f'{state_node.data.get("name")}_eq_{state_value}',
                        'width': 1
                    })
                    self.graph.add_node(eq_node)

                    # Reuse the existing literal node
                    e1 = Edge(state_node, eq_node, f"{state_node.id}_to_{eq_op_id}", {'type': 'operand', 'position': 0})
                    e2 = Edge(state_value_node, eq_node, f"{state_value_node.id}_to_{eq_op_id}", {'type': 'operand', 'position': 1})
                    self.graph.add_edge(e1)
                    self.graph.add_edge(e2)

                    parent_decode_node = eq_node
                    print(f"      Created activation condition: {state_node.data.get('name')} == {state_value}")

            # Fallback: If no state value constant found, create "state != 0" condition
            if not parent_decode_node and state_node:
                state_name = state_node.data.get('name', '')
                print(f"      Fallback: Parent assigns non-constant value to {state_name}")
                # Create "state != 0" as NOT(state == 0)
                zero_const_id = f"const_0_for_{state_name}"
                zero_node = Node(zero_const_id, {
                    'type': 'literal',
                    'value': 0,
                    'width': state_node.data.get('bit_width', 8)
                })
                self.graph.add_node(zero_node)

                # First: state == 0
                eq_op_id = f"eq_{state_name}_0"
                eq_node = Node(eq_op_id, {
                    'type': 'operation',
                    'opcode': 13,  # OP_EQ
                    'operator': '==',
                    'name': f'{state_name}_eq_0',
                    'width': 1
                })
                self.graph.add_node(eq_node)

                e1 = Edge(state_node, eq_node, f"{state_node.id}_to_{eq_op_id}", {'type': 'operand', 'position': 0})
                e2 = Edge(zero_node, eq_node, f"{zero_const_id}_to_{eq_op_id}", {'type': 'operand', 'position': 1})
                self.graph.add_edge(e1)
                self.graph.add_edge(e2)

                # Then: NOT(state == 0)
                not_op_id = f"not_{state_name}_eq_0"
                not_node = Node(not_op_id, {
                    'type': 'operation',
                    'opcode': 2,  # OP_NOT
                    'operator': '!',
                    'name': f'{state_name}_active',
                    'width': 1
                })
                self.graph.add_node(not_node)

                e3 = Edge(eq_node, not_node, f"{eq_op_id}_to_{not_op_id}", {'type': 'operand', 'position': 0})
                self.graph.add_edge(e3)

                parent_decode_node = not_node
                print(f"      Created activation condition: {state_name} != 0")

            # Fallback #2: Use parent instruction's decode condition directly
            if not parent_decode_node and parent_instruction:
                # Find the decode condition edge from parent instruction
                for edge in self.graph.edges.values():
                    if (isinstance(edge.data, dict) and
                        edge.data.get('type') == 'decode_condition' and
                        edge.target.id == parent_instruction.id):
                        parent_decode_node = edge.source
                        print(f"      Using parent instruction decode condition: {parent_decode_node.id}")
                        break

        # Step 3: Copy all nodes from child graph with prefixed IDs
        prefix = f"{func_name}_{func_node.id}_"
        node_mapping = {}  # old_id -> new_node

        for child_node_id, child_node in child_graph.nodes.items():
            new_node_id = prefix + child_node_id

            # Copy node data
            new_data = child_node.data.copy() if isinstance(child_node.data, dict) else child_node.data
            if isinstance(new_data, dict):
                new_data['inlined_from'] = func_name

            # Create new node
            new_node = Node(
                node_id=new_node_id,
                data=new_data,
                is_arch_state=child_node.is_arch_state,
                is_uarch_state=child_node.is_uarch_state,
                used_as_index=child_node.used_as_index,
                indexed_by=child_node.indexed_by,
                uarch_time=child_node.uarch_time,
                from_isa_spec=child_node.from_isa_spec,
                already_split=child_node.already_split,
                latency=child_node.latency,
                variable_latency=child_node.variable_latency
            )

            self.graph.add_node(new_node)
            node_mapping[child_node_id] = new_node

        # Step 4: Copy all edges from child graph
        for edge_id, edge in child_graph.edges.items():
            new_edge_id = prefix + edge_id

            # Get the new nodes
            source_node = node_mapping.get(edge.source.id)
            target_node = node_mapping.get(edge.target.id)

            if source_node and target_node:
                # Copy edge data
                new_edge_data = edge.data.copy() if isinstance(edge.data, dict) else edge.data

                # Fix instruction IDs in assignment edges - add prefix
                if isinstance(new_edge_data, dict) and new_edge_data.get('type') == 'assignment':
                    old_instr_id = new_edge_data.get('instruction')
                    if old_instr_id:
                        new_edge_data['instruction'] = prefix + old_instr_id

                # Add parent decode condition to child instruction decode edges
                # This gates child instructions so they only run when parent calls the function
                if (isinstance(new_edge_data, dict) and
                    new_edge_data.get('type') == 'decode_condition' and
                    parent_decode_node is not None):
                    # Store parent decode node ID so Verilog generator can AND them
                    new_edge_data['parent_decode'] = parent_decode_node.id
                    print(f"      Set parent_decode={parent_decode_node.id} on edge {new_edge_id}")

                # Create new edge
                new_edge = Edge(source_node, target_node, new_edge_id, new_edge_data)
                self.graph.add_edge(new_edge)

        # Step 5: Connect function arguments to child graph inputs
        # Find input nodes in child graph (parameters to the function)
        def is_input_node(n):
            if not isinstance(n.data, dict):
                return False
            node_type = n.data.get('type')
            node_name = n.data.get('name', '')
            if node_type not in ['isa_state', 'variable']:
                return False
            # AES inputs
            if node_name in ['plaintext', 'key', 'key_in', 'input']:
                return True
            # SHA-1 inputs: block_0..block_15, H0_in..H4_in
            if node_name.startswith('block_') or (node_name.startswith('H') and node_name.endswith('_in')):
                return True
            return False

        child_inputs = [n for n in child_graph.nodes.values() if is_input_node(n)]

        print(f"      Found {len(child_inputs)} potential input nodes")
        for inp in child_inputs:
            print(f"        Input: {inp.id} - {inp.data}")

        # Connect parent function arguments to child inputs
        # For AES: arg 0 = plaintext, arg 1 = key
        if 'aes128' in func_name.lower() and len(func_args) >= 2 and len(child_inputs) >= 2:
            # Sort child inputs by name to get consistent ordering
            plaintext_node = None
            key_node = None
            for inp in child_inputs:
                if inp.data.get('name') == 'plaintext':
                    plaintext_node = node_mapping.get(inp.id)
                elif inp.data.get('name') in ['key', 'key_in']:
                    key_node = node_mapping.get(inp.id)

            if plaintext_node and key_node:
                # Connect arg 0 (plaintext) to plaintext input
                arg0_source = func_args[0][1]  # (position, source_node)
                edge_id = f"inline_arg0_{func_node.id}_to_{plaintext_node.id}"
                arg0_edge = Edge(arg0_source, plaintext_node, edge_id, {'argument': 0})
                self.graph.add_edge(arg0_edge)
                print(f"      Connected arg0 ({arg0_source.id}) → plaintext ({plaintext_node.id})")

                # Connect arg 1 (key) to key input
                arg1_source = func_args[1][1]
                edge_id = f"inline_arg1_{func_node.id}_to_{key_node.id}"
                arg1_edge = Edge(arg1_source, key_node, edge_id, {'argument': 1})
                self.graph.add_edge(arg1_edge)
                print(f"      Connected arg1 ({arg1_source.id}) → key ({key_node.id})")
            else:
                print(f"      WARNING: Could not find plaintext or key nodes in mapping")

        # For SHA-1: args 0-15 = block[0..15], args 16-20 = H0_in..H4_in
        elif func_name in ['sha1_compress', 'sha1compress'] and len(func_args) >= 21:
            # Find block and hash input nodes in child
            block_nodes = {}
            hash_nodes = {}
            for inp in child_inputs:
                name = inp.data.get('name', '')
                if name.startswith('block_'):
                    idx = int(name.split('_')[1])
                    block_nodes[idx] = node_mapping.get(inp.id)
                elif name.startswith('H') and name.endswith('_in'):
                    idx = int(name[1])
                    hash_nodes[idx] = node_mapping.get(inp.id)

            # Connect block arguments (args 0-15 → block_0..block_15)
            connected = 0
            for i in range(16):
                if i < len(func_args) and i in block_nodes and block_nodes[i]:
                    arg_source = func_args[i][1]
                    block_node = block_nodes[i]
                    edge_id = f"inline_arg{i}_{func_node.id}_to_block_{i}"
                    edge = Edge(arg_source, block_node, edge_id, {'argument': i})
                    self.graph.add_edge(edge)
                    connected += 1
            print(f"      Connected {connected}/16 block arguments")

            # Connect hash arguments (args 16-20 → H0_in..H4_in)
            hash_connected = 0
            for i in range(5):
                arg_idx = 16 + i
                if arg_idx < len(func_args) and i in hash_nodes and hash_nodes[i]:
                    arg_source = func_args[arg_idx][1]
                    hash_node = hash_nodes[i]
                    edge_id = f"inline_arg{arg_idx}_{func_node.id}_to_H{i}_in"
                    edge = Edge(arg_source, hash_node, edge_id, {'argument': arg_idx})
                    self.graph.add_edge(edge)
                    hash_connected += 1
            print(f"      Connected {hash_connected}/5 hash arguments")

        # Step 6: Connect child graph output to where function result is used
        # Find output nodes in child graph - look for the top-level result
        # For AES: find the expression assigned to 'ciphertext' by FinalRound instruction
        child_outputs = []

        # For AES: Find FinalRound instruction and get its ciphertext update expression
        if 'aes128' in func_name.lower():
            finalround_instr = None
            for n in child_graph.nodes.values():
                if isinstance(n.data, dict) and n.data.get('type') == 'instruction':
                    if n.data.get('name') == 'FinalRound':
                        finalround_instr = n
                        print(f"      Found FinalRound instruction: {n.id}")
                        break

            if finalround_instr:
                # Find the assignment edge from FinalRound to ciphertext
                for edge in child_graph.edges.values():
                    if (isinstance(edge.data, dict) and
                        edge.data.get('type') == 'assignment' and
                        edge.data.get('instruction') == finalround_instr.id):
                        target = edge.target
                        if isinstance(target.data, dict) and target.data.get('name') == 'ciphertext':
                            # edge.source is the expression that computes the final ciphertext
                            child_outputs = [edge.source]
                            print(f"      Using FinalRound ciphertext expression as output: {edge.source.id}")
                            break

        # Fallback: Try to find architectural state outputs
        if not child_outputs:
            for n in child_graph.nodes.values():
                if isinstance(n.data, dict):
                    node_type = n.data.get('type')
                    node_name = n.data.get('name', '')
                    if node_type == 'isa_state' and node_name in ['ciphertext', 'output', 'result']:
                        child_outputs.append(n)
                    # Also check for the highest-ID operation node which is often the result
                    elif node_type == 'operation' and not node_name:
                        pass  # Will handle below

        # For SHA-1: concatenate H0_out..H4_out into 160-bit result
        if func_name in ['sha1_compress', 'sha1compress'] and not child_outputs:
            hash_out_nodes = {}
            for n in child_graph.nodes.values():
                if isinstance(n.data, dict) and n.data.get('type') == 'isa_state':
                    name = n.data.get('name', '')
                    if name.startswith('H') and name.endswith('_out') and name[1].isdigit():
                        idx = int(name[1])
                        hash_out_nodes[idx] = node_mapping.get(n.id)

            # If we found all 5 hash outputs, concatenate them
            if len(hash_out_nodes) == 5 and all(i in hash_out_nodes for i in range(5)):
                print(f"      Found all 5 SHA-1 hash outputs, creating concat node")
                # Create concat node: concat(H0_out, H1_out, H2_out, H3_out, H4_out)
                concat_id = f"sha1_output_concat_{func_node.id}"
                concat_node = Node(concat_id, {
                    'type': 'operation',
                    'opcode': 20,  # OP_CONCAT
                    'name': 'sha1_result',
                    'width': 160
                })
                self.graph.add_node(concat_node)

                # Connect H0_out..H4_out to concat (building up: H0 || H1 || H2 || H3 || H4)
                # We need to create nested concats: concat(concat(concat(concat(H0, H1), H2), H3), H4)
                result = hash_out_nodes[0]
                for i in range(1, 5):
                    intermediate_concat_id = f"sha1_concat_{i}_{func_node.id}"
                    intermediate_node = Node(intermediate_concat_id, {
                        'type': 'operation',
                        'opcode': 20,
                        'name': f'sha1_concat_{i}',
                        'width': 32 * (i + 1)
                    })
                    self.graph.add_node(intermediate_node)

                    # Add edges: result → intermediate_concat, hash_out[i] → intermediate_concat
                    e1 = Edge(result, intermediate_node, f"{result.id}_to_{intermediate_concat_id}_0", {'operand': 0})
                    e2 = Edge(hash_out_nodes[i], intermediate_node, f"{hash_out_nodes[i].id}_to_{intermediate_concat_id}_1", {'operand': 1})
                    self.graph.add_edge(e1)
                    self.graph.add_edge(e2)
                    result = intermediate_node

                child_outputs = [result]
                print(f"      Created SHA-1 160-bit concatenated output: {result.id}")

        # If no state outputs found, find the node with highest ID (likely the final result)
        if not child_outputs:
            def get_numeric_id(node_id):
                """Extract numeric ID from node, return -1 if not numeric."""
                parts = node_id.split('_')
                for part in reversed(parts):
                    try:
                        return int(part)
                    except ValueError:
                        continue
                return -1

            max_id = max([get_numeric_id(n.id) for n in child_graph.nodes.values()])
            for n in child_graph.nodes.values():
                if n.id.endswith(str(max_id)):
                    child_outputs = [n]
                    print(f"      Using highest-ID node as output: {n.id}")
                    break

        print(f"      Found {len(child_outputs)} output nodes")
        for out in child_outputs:
            print(f"        Output: {out.id} - {out.data}")

        if child_outputs and result_targets:
            # Connect first output to all result targets
            output_node = node_mapping.get(child_outputs[0].id)
            if output_node:
                print(f"      Connecting output {output_node.id} to {len(result_targets)} targets")
                for target_node, edge_data in result_targets:
                    print(f"        Target: {target_node.id} (type: {target_node.data.get('type') if isinstance(target_node.data, dict) else 'N/A'})")
                    # Create edge from child output to original target
                    new_edge_id = f"inline_output_{func_node.id}_to_{target_node.id}"
                    new_edge = Edge(output_node, target_node, new_edge_id, edge_data)
                    self.graph.add_edge(new_edge)
            else:
                print(f"      WARNING: Could not find mapped output node")
        else:
            print(f"      WARNING: No outputs ({len(child_outputs)}) or targets ({len(result_targets)}) to connect")

        # Step 6b: Parent state clearing (DISABLED)
        # NOTE: Do NOT automatically add state clearing to child's final instruction.
        # Some designs (like SHA-1) need the child to clear parent state,
        # while others (like AES) have the parent manage its own state clearing.
        # This should be specified in the ILA model itself, not added by the parser.

        # Step 7: Replace function_application node with inlined output
        # Update the expr_cache so the function's ila_id now points to the inlined output
        func_ila_id = func_node.data.get('ila_id')
        if func_ila_id and child_outputs and output_node:
            # Update mapping: expression ID for function now resolves to inlined output
            self.expr_cache[func_ila_id] = output_node.id
            print(f"      Updated expr_cache: {func_ila_id} -> {output_node.id}")

        # Remove edges connected to the original func_node (arguments will now connect to child inputs)
        edges_to_remove = []
        for edge_id, edge in self.graph.edges.items():
            if edge.source.id == func_node.id or edge.target.id == func_node.id:
                edges_to_remove.append(edge_id)

        for edge_id in edges_to_remove:
            if edge_id in self.graph.edges:
                del self.graph.edges[edge_id]

        # Remove the function_application node itself (replaced by inlined output)
        if func_node.id in self.graph.nodes:
            del self.graph.nodes[func_node.id]

        # Step 8: Remove parent instruction assignments to child INTERNAL states
        # Child internal states (like ciphertext, round_key) should only be updated
        # by child instructions. But child INPUTS (plaintext, key_in) AND child COUNTER
        # states (round) need to be initialized by parent when "calling" the function.

        # Collect child internal state names (NOT inputs or counters)
        child_input_names = set(inp.data.get('name') for inp in child_inputs)
        child_counter_states = set()  # States like 'round' that need initialization
        child_internal_states = set()

        for n in child_graph.nodes.values():
            if isinstance(n.data, dict) and n.data.get('type') == 'isa_state':
                state_name = n.data.get('name')
                ila_name = n.data.get('ila_name', '')
                # Counter states need to be reset by parent when calling
                if state_name in ['round']:
                    child_counter_states.add(state_name)
                # Internal states belong to child ILA but aren't inputs or counters
                elif state_name not in child_input_names:
                    if ila_name == 'input' or state_name in ['round_key', 'ciphertext']:
                        child_internal_states.add(state_name)

        print(f"      Removing parent instruction assignments to {len(child_internal_states)} child internal states")
        print(f"      Keeping parent assignments to {len(child_input_names)} child input states")
        print(f"      Need to initialize {len(child_counter_states)} child counter states")

        edges_to_remove = []
        for edge_id, edge in self.graph.edges.items():
            if isinstance(edge.data, dict) and edge.data.get('type') == 'assignment':
                target_name = edge.target.data.get('name') if isinstance(edge.target.data, dict) else 'unknown'
                instr_id = edge.data.get('instruction', 'NO_INSTR')
                # Remove assignments from parent instruction to child INTERNAL states only
                if (target_name in child_internal_states and
                    parent_instruction_id and instr_id == parent_instruction_id):
                    print(f"        Removing: {parent_instruction_id} -> {target_name}")
                    edges_to_remove.append(edge_id)

        for edge_id in edges_to_remove:
            if edge_id in self.graph.edges:
                del self.graph.edges[edge_id]

        print(f"      Removed {len(edges_to_remove)} parent→child internal state assignments")

        # Step 9: Add parent instruction assignments to initialize child counter states
        # When parent "calls" child function, it needs to reset counters like 'round' to 0
        for counter_name in child_counter_states:
            # Find the counter state node in the child graph
            counter_node = None
            for n in child_graph.nodes.values():
                if isinstance(n.data, dict) and n.data.get('name') == counter_name:
                    counter_node = node_mapping.get(n.id)
                    break

            if counter_node and parent_instruction:
                # Create conditional initialization: only reset counter if == complete_value
                # For round counter in AES: reset to 0 only if round == 11 (after FinalRound)
                # This prevents parent from constantly resetting counter every cycle it's active
                # After child completes, round stays at 11 long enough for testbench to see it

                # Create literal for complete value (11 for AES round counter)
                complete_val = 11 if counter_name == 'round' else 0
                complete_id = f"init_{counter_name}_complete"
                complete_node = Node(complete_id, {
                    'type': 'literal',
                    'value': complete_val,
                    'width': counter_node.data.get('bit_width', 4)
                })
                self.graph.add_node(complete_node)

                # Create comparison: round == 11
                eq_id = f"init_{counter_name}_eq_check"
                eq_node = Node(eq_id, {
                    'type': 'operation',
                    'opcode': 13,  # OP_EQ (equal)
                    'operator': '==',
                    'width': 1
                })
                self.graph.add_node(eq_node)

                eq_edge1 = Edge(counter_node, eq_node, f"{counter_node.id}_to_{eq_id}_0", {'type': 'operand', 'position': 0})
                eq_edge2 = Edge(complete_node, eq_node, f"{complete_id}_to_{eq_id}_1", {'type': 'operand', 'position': 1})
                self.graph.add_edge(eq_edge1)
                self.graph.add_edge(eq_edge2)

                # Create literal 0
                zero_id = f"init_{counter_name}_0"
                zero_node = Node(zero_id, {
                    'type': 'literal',
                    'value': 0,
                    'width': counter_node.data.get('bit_width', 4)
                })
                self.graph.add_node(zero_node)

                # Create conditional: (round == 11) ? 0 : round
                ite_id = f"init_{counter_name}_ite"
                ite_node = Node(ite_id, {
                    'type': 'ternary_op',
                    'opcode': 26,  # OP_ITE (if-then-else)
                    'operator': '?:',
                    'width': counter_node.data.get('bit_width', 4)
                })
                self.graph.add_node(ite_node)

                ite_edge1 = Edge(eq_node, ite_node, f"{eq_id}_to_{ite_id}_cond", {'type': 'ternary_condition'})
                ite_edge2 = Edge(zero_node, ite_node, f"{zero_id}_to_{ite_id}_then", {'type': 'ternary_true'})
                ite_edge3 = Edge(counter_node, ite_node, f"{counter_node.id}_to_{ite_id}_else", {'type': 'ternary_false'})
                self.graph.add_edge(ite_edge1)
                self.graph.add_edge(ite_edge2)
                self.graph.add_edge(ite_edge3)

                # Create modifies edge from instruction to state
                mod_edge_id = f"mod_{parent_instruction.id}_{counter_node.id}"
                mod_edge = Edge(parent_instruction, counter_node, mod_edge_id, {
                    'type': 'modifies'
                })
                self.graph.add_edge(mod_edge)

                # Create assignment edge: round <= (round == 11) ? 0 : round
                assign_edge_id = f"assign_{ite_id}_{counter_node.id}"
                assign_edge = Edge(ite_node, counter_node, assign_edge_id, {
                    'type': 'assignment',
                    'instruction': parent_instruction.id
                })
                self.graph.add_edge(assign_edge)
                print(f"      Added conditional initialization: {parent_instruction.id} -> {counter_name} = (=={complete_val}) ? 0 : {counter_name}")

    def inline_uninterpreted_functions(self):
        """Replace uninterpreted functions with references to the states they update.

        Uninterpreted functions represent non-deterministic behavior in the ILA model.
        For Verilog synthesis, we replace them with "keep current value" semantics
        by substituting a reference to the state variable being updated.
        """
        print("Inlining uninterpreted functions...")

        # Find all function_application nodes with 0 arguments (uninterpreted functions)
        uninterpreted_funcs = []
        for node in self.graph.nodes.values():
            if isinstance(node.data, dict) and node.data.get('type') == 'function_application':
                # Check if it has any argument edges
                arg_edges = [e for e in self.graph.edges.values()
                           if e.target.id == node.id and isinstance(e.data, dict) and
                           e.data.get('type') in ['argument', 'operand']]
                if len(arg_edges) == 0:
                    uninterpreted_funcs.append(node)

        print(f"  Found {len(uninterpreted_funcs)} uninterpreted functions")

        for func_node in uninterpreted_funcs:
            # Find which state this function is being assigned to
            # Trace through assignment edges
            state_node = None
            for edge in self.graph.edges.values():
                if (isinstance(edge.data, dict) and
                    edge.data.get('type') == 'assignment'):
                    # Check if this assignment's source expression contains the func_node
                    if self._expression_contains_node(edge.source, func_node):
                        state_node = edge.target
                        break

            if state_node and isinstance(state_node.data, dict):
                state_name = state_node.data.get('name', 'unknown')
                func_name = func_node.data.get('function_name', 'unknown')
                print(f"  Replacing {func_name} with reference to {state_name}")

                # Replace the function_application node with a reference to the state
                # Update all edges that target this function node to target the state instead
                edges_to_update = [e for e in self.graph.edges.values()
                                 if e.source.id == func_node.id]

                for edge in edges_to_update:
                    # Create new edge from state to the same target
                    new_edge_id = f"{state_node.id}_to_{edge.target.id}_unintrp_repl"
                    new_edge = Edge(state_node, edge.target, new_edge_id, edge.data)
                    self.graph.add_edge(new_edge)
                    # Remove old edge
                    if edge.id in self.graph.edges:
                        del self.graph.edges[edge.id]

                # Remove the function_application node
                if func_node.id in self.graph.nodes:
                    del self.graph.nodes[func_node.id]

    def _expression_contains_node(self, expr_node: Node, target_node: Node) -> bool:
        """Check if an expression tree contains a specific node."""
        if expr_node.id == target_node.id:
            return True

        # Check operands/children
        for edge in self.graph.edges.values():
            if (edge.target.id == expr_node.id and
                isinstance(edge.data, dict) and
                edge.data.get('type') in ['operand', 'argument', 'ternary_condition',
                                         'ternary_true', 'ternary_false']):
                if self._expression_contains_node(edge.source, target_node):
                    return True

        return False

    def add_child_state_transitions(self):
        """Add state transition logic to inlined child ILA instructions.

        When child ILAs are inlined, they lose their implicit state machine.
        This method adds explicit state transitions so child instructions
        can properly sequence (e.g., LOAD → OPERATE → STORE).
        """
        print("Adding state transitions for inlined child instructions...")

        # Find the aes_status state node
        aes_status_node = None
        for node in self.graph.nodes.values():
            if isinstance(node.data, dict) and node.data.get('name') == 'aes_status':
                aes_status_node = node
                break

        if not aes_status_node:
            print("  No aes_status state found, skipping")
            return

        # Find LOAD, OPERATE, STORE instructions
        load_instr = None
        operate_instr = None
        store_instr = None

        for node in self.graph.nodes.values():
            if isinstance(node.data, dict) and node.data.get('type') == 'instruction':
                name = node.data.get('name', '')
                if name == 'LOAD':
                    load_instr = node
                elif name == 'OPERATE':
                    operate_instr = node
                elif name == 'STORE':
                    store_instr = node

        # Add LOAD → OPERATE transition (when byte_cnt == 16)
        if load_instr:
            self._add_state_transition(load_instr, aes_status_node, 'byte_cnt', 16, 2, "LOAD→OPERATE")

        # Add OPERATE → STORE transition (when round == 11)
        if operate_instr:
            self._add_state_transition(operate_instr, aes_status_node, 'round', 11, 3, "OPERATE→STORE")

        # STORE transitions back to LOAD for next block
        if store_instr:
            self._add_state_transition(store_instr, aes_status_node, 'byte_cnt', 16, 1, "STORE→LOAD")

    def _add_state_transition(self, instruction: Node, state_node: Node,
                             counter_name: str, threshold: int, next_state: int, description: str):
        """Add a conditional state transition to an instruction."""
        print(f"  Adding {description} transition")

        # Find the counter state node
        counter_node = None
        for node in self.graph.nodes.values():
            if isinstance(node.data, dict) and node.data.get('name') == counter_name:
                counter_node = node
                break

        if not counter_node:
            print(f"    Warning: counter '{counter_name}' not found")
            return

        # Create condition: counter == threshold
        threshold_id = f"{counter_name}_eq_{threshold}_threshold"
        threshold_node = Node(threshold_id, {
            'type': 'literal',
            'value': threshold,
            'width': counter_node.data.get('bit_width', 4)
        })
        self.graph.add_node(threshold_node)

        eq_id = f"{counter_name}_eq_{threshold}"
        eq_node = Node(eq_id, {
            'type': 'operation',
            'opcode': 13,  # OP_EQ
            'operator': '==',
            'width': 1
        })
        self.graph.add_node(eq_node)

        eq_edge1 = Edge(counter_node, eq_node, f"{counter_node.id}_to_{eq_id}_0", {'type': 'operand', 'position': 0})
        eq_edge2 = Edge(threshold_node, eq_node, f"{threshold_id}_to_{eq_id}_1", {'type': 'operand', 'position': 1})
        self.graph.add_edge(eq_edge1)
        self.graph.add_edge(eq_edge2)

        # Create next state literal
        next_state_id = f"state_{next_state}_literal"
        next_state_node = Node(next_state_id, {
            'type': 'literal',
            'value': next_state,
            'width': state_node.data.get('bit_width', 2)
        })
        self.graph.add_node(next_state_node)

        # Create ternary: (counter == threshold) ? next_state : current_state
        ite_id = f"{state_node.id}_transition_{description.replace('→', '_')}"
        ite_node = Node(ite_id, {
            'type': 'ternary_op',
            'opcode': 26,  # OP_ITE
            'operator': '?:',
            'width': state_node.data.get('bit_width', 2)
        })
        self.graph.add_node(ite_node)

        ite_edge1 = Edge(eq_node, ite_node, f"{eq_id}_to_{ite_id}_cond", {'type': 'ternary_condition'})
        ite_edge2 = Edge(next_state_node, ite_node, f"{next_state_id}_to_{ite_id}_then", {'type': 'ternary_true'})
        ite_edge3 = Edge(state_node, ite_node, f"{state_node.id}_to_{ite_id}_else", {'type': 'ternary_false'})
        self.graph.add_edge(ite_edge1)
        self.graph.add_edge(ite_edge2)
        self.graph.add_edge(ite_edge3)

        # Add or update assignment edge from instruction to state
        # First, remove any existing assignment to this state from this instruction
        edges_to_remove = []
        for edge in self.graph.edges.values():
            if (isinstance(edge.data, dict) and
                edge.data.get('type') == 'assignment' and
                edge.data.get('instruction') == instruction.id and
                edge.target.id == state_node.id):
                edges_to_remove.append(edge.id)

        for edge_id in edges_to_remove:
            del self.graph.edges[edge_id]

        # Add new assignment edge
        assign_edge_id = f"assign_{ite_id}_{state_node.id}"
        assign_edge = Edge(ite_node, state_node, assign_edge_id, {
            'type': 'assignment',
            'instruction': instruction.id
        })
        self.graph.add_edge(assign_edge)

        # Add modifies edge if not already present
        mod_edge_exists = any(
            e.source.id == instruction.id and e.target.id == state_node.id and
            isinstance(e.data, dict) and e.data.get('type') == 'modifies'
            for e in self.graph.edges.values()
        )

        if not mod_edge_exists:
            mod_edge_id = f"mod_{instruction.id}_{state_node.id}"
            mod_edge = Edge(instruction, state_node, mod_edge_id, {'type': 'modifies'})
            self.graph.add_edge(mod_edge)

    def add_child_input_initialization(self):
        """Add initialization of child ILA inputs to START_ENCRYPT instruction.

        When child ILAs are inlined, their input arguments need to be initialized
        from parent state variables. This should happen when starting encryption
        (in START_ENCRYPT) rather than during OPERATE, to avoid race conditions
        where child instructions fire in the same cycle as initialization.
        """
        print("Adding child ILA input initialization to START_ENCRYPT...")

        # Find START_ENCRYPT instruction
        start_encrypt_instr = None
        for node in self.graph.nodes.values():
            if isinstance(node.data, dict) and node.data.get('type') == 'instruction':
                if node.data.get('name') == 'START_ENCRYPT':
                    start_encrypt_instr = node
                    break

        if not start_encrypt_instr:
            print("  No START_ENCRYPT instruction found, skipping")
            return

        # Find all inline_arg edges (edges with 'argument' key in data)
        # These edges were created during function inlining to connect parent expressions
        # to child input states
        inline_arg_edges = [
            e for e in self.graph.edges.values()
            if isinstance(e.data, dict) and 'argument' in e.data and 'inline_arg' in str(e.id)
        ]

        if not inline_arg_edges:
            print("  No inline_arg edges found, skipping")
            return

        print(f"  Found {len(inline_arg_edges)} child input initializations to add")

        # Add assignment edges from START_ENCRYPT to each child input state
        for arg_edge in inline_arg_edges:
            source_expr = arg_edge.source  # Expression to evaluate (e.g., aes_key)
            target_state = arg_edge.target  # State to initialize (e.g., key_in)

            if not isinstance(target_state.data, dict):
                continue

            target_name = target_state.data.get('name', 'unknown')

            # Create assignment edge from START_ENCRYPT to target state
            # The source is the expression node that should be evaluated
            assign_edge_id = f"assign_{start_encrypt_instr.id}_to_{target_state.id}_init"
            assign_edge = Edge(source_expr, target_state, assign_edge_id, {
                'type': 'assignment',
                'instruction': start_encrypt_instr.id
            })

            # Check if this edge already exists
            edge_exists = any(
                e.source.id == source_expr.id and
                e.target.id == target_state.id and
                isinstance(e.data, dict) and
                e.data.get('type') == 'assignment' and
                e.data.get('instruction') == start_encrypt_instr.id
                for e in self.graph.edges.values()
            )

            if not edge_exists:
                print(f"    Adding initialization: {target_name} <= (expression from inline_arg)")
                self.graph.add_edge(assign_edge)

                # Also add modifies edge if it doesn't exist
                mod_edge_exists = any(
                    e.source.id == start_encrypt_instr.id and
                    e.target.id == target_state.id and
                    isinstance(e.data, dict) and e.data.get('type') == 'modifies'
                    for e in self.graph.edges.values()
                )

                if not mod_edge_exists:
                    mod_edge_id = f"mod_{start_encrypt_instr.id}_{target_state.id}_init"
                    mod_edge = Edge(start_encrypt_instr, target_state, mod_edge_id, {'type': 'modifies'})
                    self.graph.add_edge(mod_edge)


def parse_ila_json_file(filename: str) -> ResourceGraph:
    """Parse an ILAng JSON file and return a ResourceGraph."""
    parser = RealILAParser()
    return parser.parse_file(filename)


def parse_ila_json(data: Dict[str, Any]) -> ResourceGraph:
    """Parse ILAng JSON data and return a ResourceGraph."""
    parser = RealILAParser()
    return parser.parse_json(data)
