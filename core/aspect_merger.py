"""
Aspect-Oriented Programming support for ISA specifications.

This module handles loading, validating, and merging aspect files with base ISA graphs.
"""

import os
from typing import Dict, List, Set, Optional
from .resource_graph import ResourceGraph, Node, Edge


class AspectMerger:
    """Handles merging aspect files with base ISA specifications."""

    def __init__(self, base_graph: ResourceGraph, base_file_path: Optional[str] = None):
        """
        Initialize the aspect merger.

        Args:
            base_graph: The base ISA resource graph
            base_file_path: Path to the base .isa file (used to resolve relative aspect paths)
        """
        self.base_graph = base_graph
        self.base_file_path = base_file_path
        self.aspect_graphs: List[Dict] = []  # List of {graph, gated_states, order}

    def load_and_merge_aspects(self):
        """
        Load all declared aspects and merge them with the base graph.

        This is the main entry point for aspect processing.
        """
        if not self.base_graph.aspect_declarations:
            return  # No aspects to merge

        # Load all aspect files
        for aspect_decl in self.base_graph.aspect_declarations:
            self._load_aspect(aspect_decl)

        # Validate priority consistency before merging
        # If multiple aspects gate the same state, all must have priorities
        self._validate_priority_consistency()

        # Merge aspects in order (for proper precedence)
        for aspect_info in self.aspect_graphs:
            self._merge_aspect(aspect_info)

        # NOTE: We do NOT create multiplexers here because:
        # 1. Individual instruction graphs will be merged together by graph_merger.py
        # 2. PC gets split into pc_rd and pc_wr during merging
        # 3. Muxes created here would be lost or misconnected during that process
        # Instead, graph_merger.py will create gated write muxes after merging is complete

        # Store gated states metadata for graph_merger to use later
        all_gated_states = set()
        for aspect_info in self.aspect_graphs:
            all_gated_states.update(aspect_info['gated_states'])
            all_gated_states.update(aspect_info.get('prioritized_states', {}).keys())
        if all_gated_states:
            self.base_graph.gated_states = all_gated_states

        # After all aspects are merged, create multiplexers for gated writes
        self._create_gated_write_multiplexers()

        # Merge prioritized writes from multiple aspects
        # This handles variables like exc_taken (OR) and exc_vector (priority mux)
        self._merge_prioritized_writes()

    def _load_aspect(self, aspect_decl: Dict):
        """
        Load and parse an aspect file.

        Args:
            aspect_decl: Dictionary with 'file', 'gated_states', 'prioritized_states', 'order'
        """
        aspect_file = aspect_decl['file']

        # Resolve relative path - try file's directory, then parent directory
        if self.base_file_path and not os.path.isabs(aspect_file):
            base_dir = os.path.dirname(self.base_file_path)
            resolved = os.path.join(base_dir, aspect_file)
            if not os.path.exists(resolved):
                # Try parent directory (for files in subdirectories)
                parent_dir = os.path.dirname(base_dir)
                resolved = os.path.join(parent_dir, aspect_file)
            aspect_file = resolved

        if not os.path.exists(aspect_file):
            raise FileNotFoundError(f"Aspect file not found: {aspect_file}")

        # Parse the aspect file directly into the base graph
        # This allows the aspect to access all instruction variables
        from .isa_parser import ISAParser
        parser = ISAParser()

        # Pass intermediate values snapshot from the instruction parser so the
        # aspect can see in-cycle assignments that preceded this aspect declaration.
        # For example, if the instruction has `eval_reg = decoded_value;` before
        # including cont_pop.isa, then cont_pop's references to eval_reg should
        # resolve to decoded_value (the just-assigned value), not eval_reg_rd (stale).
        aspect_intermediates = aspect_decl.get('intermediate_values', {})
        if aspect_intermediates:
            self.base_graph._intermediate_values = dict(aspect_intermediates)
        elif hasattr(self.base_graph, '_intermediate_values'):
            del self.base_graph._intermediate_values

        # Count nodes and edges before parsing to identify aspect-added ones
        nodes_before = set(self.base_graph.nodes.keys())
        edges_before = set()
        for node in self.base_graph.nodes.values():
            edges_before.update(id(e) for e in node.outgoing_edges)

        # Parse aspect into base graph (shares namespace with instruction)
        parser.parse_file(aspect_file, existing_graph=self.base_graph)

        # Mark new nodes/edges as from_aspect
        nodes_after = set(self.base_graph.nodes.keys())
        aspect_nodes = nodes_after - nodes_before

        # Collect edges added by this aspect (by identity)
        edges_after = set()
        for node in self.base_graph.nodes.values():
            edges_after.update(id(e) for e in node.outgoing_edges)
        new_edge_ids = edges_after - edges_before

        aspect_edges = []
        for node in self.base_graph.nodes.values():
            for e in node.outgoing_edges:
                if id(e) in new_edge_ids:
                    aspect_edges.append(e)

        for node_id in aspect_nodes:
            node = self.base_graph.nodes[node_id]
            if node.data is None:
                node.data = {}
            node.data['from_aspect'] = aspect_file

        # Mark new edges with from_aspect at load time
        for e in aspect_edges:
            if e.data is None:
                e.data = {}
            e.data['from_aspect'] = aspect_file

        # Store metadata for later processing
        # Include both gated_states (exclusive access) and prioritized_states (merged access)
        self.aspect_graphs.append({
            'graph': self.base_graph,  # Reference to the shared graph
            'gated_states': set(aspect_decl['gated_states']),
            'prioritized_states': dict(aspect_decl.get('prioritized_states', {})),
            'order': aspect_decl['order'],
            'file': aspect_file,
            'aspect_nodes': aspect_nodes,
            'aspect_edges': aspect_edges
        })

    def _validate_gated_states(self, gated_states: List[str], aspect_graph: ResourceGraph):
        """
        Validate that all gated states exist in the base graph.

        We can't validate writes yet because the aspect nodes haven't been
        mapped to base nodes. That validation happens in _merge_aspect.

        Args:
            gated_states: List of state names that can be affected
            aspect_graph: The aspect resource graph
        """
        # Check that gated states exist in base
        base_state_names = {
            node.data.get('name') for node in self.base_graph.nodes.values()
            if node.data and node.data.get('type', '').startswith('isa_state')
        }

        for state_name in gated_states:
            if state_name not in base_state_names:
                raise ValueError(
                    f"Gated state '{state_name}' not found in base ISA. "
                    f"Available states: {base_state_names}"
                )

    def _get_state_name_from_node(self, node: Node, graph: ResourceGraph) -> Optional[str]:
        """
        Extract the base state name from a node (handling array access, etc.).

        Args:
            node: The node to extract state name from
            graph: The graph containing the node

        Returns:
            The base state name, or None if not a state access
        """
        if node.data and node.data.get('type') == 'isa_state':
            return node.data.get('name')

        # For array access nodes, trace back to the array
        if node.data and node.data.get('type') == 'array_access':
            # Find the array node (follow edges backward)
            for edge in node.incoming_edges:
                if edge.data and edge.data.get('type') == 'array_index':
                    array_name = self._get_state_name_from_node(edge.source, graph)
                    if array_name:
                        return array_name

        return None

    def _merge_aspect(self, aspect_info: Dict):
        """
        Process aspect metadata now that aspect is parsed into base graph.

        This involves:
        1. Marking assignment edges from aspect with precedence
        2. Validating that aspect only writes to gated states

        Args:
            aspect_info: Dictionary with graph, gated_states, order, file, aspect_nodes
        """
        gated_states = aspect_info['gated_states']
        prioritized_states = aspect_info.get('prioritized_states', {})
        all_valid_states = gated_states | set(prioritized_states.keys())
        aspect_file = aspect_info['file']
        aspect_edges = aspect_info.get('aspect_edges', [])
        precedence = aspect_info['order'] + 1  # Higher order = higher precedence

        # Process only edges that were actually created by this aspect
        # (tracked during _load_aspect by comparing edges before/after parsing)
        for edge in aspect_edges:
            # For assignment edges, add precedence and validate gating
            if edge.data and edge.data.get('type') == 'assignment':
                edge.data['precedence'] = precedence

                # Validate that assignment targets a gated state
                target_state = self._get_state_name_from_node(edge.target, self.base_graph)
                if target_state and target_state not in all_valid_states:
                    # Check if this is a conditional assignment (allowed to write to gated states)
                    if edge.data.get('enable'):
                        raise ValueError(
                            f"Aspect {aspect_file} uses conditional assignment to '{target_state}' "
                            f"but this state is not in the gates list. "
                            f"Conditional assignments must target gated states: {gated_states}"
                        )

    def _validate_assignment_gating(self, aspect_edge: Edge, node_mapping: Dict[str, str],
                                     gated_states: Set[str], aspect_file: str):
        """
        Validate that an assignment edge only writes to gated states.

        Args:
            aspect_edge: The assignment edge from the aspect graph
            node_mapping: Mapping from aspect node IDs to base node IDs
            gated_states: Set of state names that can be affected
            aspect_file: Path to aspect file (for error messages)
        """
        # Get the target node in the base graph
        target_id = node_mapping.get(aspect_edge.target.id)
        if not target_id:
            return  # Node not yet mapped

        target_node = self.base_graph.nodes.get(target_id)
        if not target_node:
            return  # Node not in base graph

        # Extract the base state name being written to
        target_state_name = self._get_target_state_name(target_node)

        # Check if this is a base ISA state that's not gated
        if target_state_name:
            # Check if it's a base ISA state (not from the aspect itself)
            is_base_state = any(
                node.data and node.data.get('name') == target_state_name
                and node.data.get('type', '').startswith('isa_state')
                and not node.data.get('from_aspect')
                for node in self.base_graph.nodes.values()
            )

            if is_base_state and target_state_name not in gated_states:
                raise ValueError(
                    f"Aspect '{aspect_file}' writes to non-gated state '{target_state_name}'. "
                    f"Add '{target_state_name}' to the gates clause or remove the assignment. "
                    f"Gated states: {gated_states}"
                )

    def _get_target_state_name(self, node: Node) -> Optional[str]:
        """
        Extract the base state name from a write target node.

        Args:
            node: The target node of an assignment

        Returns:
            The base state name, or None if not a state write
        """
        if not node.data:
            return None

        node_type = node.data.get('type', '')

        # Direct state write
        if node_type == 'isa_state':
            return node.data.get('name')

        # Array access (e.g., rf[rd] = ...)
        if node_type == 'array_access':
            # Find the base array by looking at incoming edges
            for edge in node.incoming_edges:
                if edge.data and edge.data.get('type') == 'array_index':
                    # Check if this edge connects to the array (not the index)
                    source_name = edge.source.data.get('name') if edge.source.data else None
                    if source_name:
                        return source_name

        # Temp var might have been mapped to a base state
        if node_type == 'temp_var':
            return node.data.get('name')

        return None

    def _find_or_create_node(self, aspect_node: Node, aspect_file: str) -> Node:
        """
        Find an existing node in base graph or create a new one.

        Args:
            aspect_node: Node from aspect graph
            aspect_file: Path to aspect file (for metadata)

        Returns:
            The node in the base graph (existing or newly created)
        """
        node_name = aspect_node.data.get('name') if aspect_node.data else None

        if node_name:
            # Try to find existing node with same name (sorted for deterministic order)
            for node_id, base_node in sorted(self.base_graph.nodes.items()):
                if base_node.data and base_node.data.get('name') == node_name:
                    # Found existing node - merge metadata
                    if aspect_node.data.get('is_external'):
                        base_node.data['is_external'] = True
                    if aspect_node.data.get('is_sensitive'):
                        base_node.data['is_sensitive'] = True
                    return base_node

        # No existing node found - create new one
        new_node_data = aspect_node.data.copy() if aspect_node.data else {}
        new_node_data['from_aspect'] = aspect_file

        new_node = Node(
            node_id=aspect_node.id,
            data=new_node_data,
            is_arch_state=aspect_node.is_arch_state,
            is_uarch_state=aspect_node.is_uarch_state,
            from_isa_spec=aspect_node.from_isa_spec
        )
        self.base_graph.add_node(new_node)
        return new_node

    def _merge_edge(self, aspect_edge: Edge, node_mapping: Dict[str, str],
                    aspect_file: str, precedence: int):
        """
        Merge an edge from aspect into base graph with precedence handling.

        For assignment edges to the same target, we need to create a multiplexer
        structure that respects precedence.

        Args:
            aspect_edge: Edge from aspect graph
            node_mapping: Mapping from aspect node IDs to base node IDs
            aspect_file: Path to aspect file (for metadata)
            precedence: Precedence level (higher = higher priority)
        """
        # Map source and target to base graph nodes
        source_id = node_mapping.get(aspect_edge.source.id, aspect_edge.source.id)
        target_id = node_mapping.get(aspect_edge.target.id, aspect_edge.target.id)

        source_node = self.base_graph.nodes.get(source_id)
        target_node = self.base_graph.nodes.get(target_id)

        if not source_node or not target_node:
            raise ValueError(f"Cannot map edge: source={source_id}, target={target_id}")

        # Create new edge with precedence metadata
        edge_data = aspect_edge.data.copy() if aspect_edge.data else {}
        edge_data['from_aspect'] = aspect_file
        edge_data['precedence'] = precedence

        new_edge = Edge(source_node, target_node, data=edge_data)
        self.base_graph.add_edge(new_edge)

    def _create_gated_write_multiplexers(self):
        """
        Create multiplexer nodes for gated writes.

        When multiple assignments target the same state (base + aspects with 'when' conditions),
        create a priority multiplexer that combines them properly:
        - Aspects with higher precedence become earlier mux inputs
        - Conditional writes use their 'enable' condition as the mux select
        - Base writes become the default case
        """
        # Collect all gated states from all aspects (both exclusive and prioritized).
        # Both types need mux creation here since this handles the base-vs-aspect
        # write conflict (base write becomes default, aspect writes are conditional).
        all_gated_states = set()
        for aspect_info in self.aspect_graphs:
            all_gated_states.update(aspect_info['gated_states'])
            all_gated_states.update(aspect_info.get('prioritized_states', {}).keys())

        if not all_gated_states:
            return  # No gated writes to process

        # Build explicit priority map: (state_name, aspect_file) -> priority_number
        # Used for states declared with priority syntax (e.g., "gates pc:1, sr:1")
        # so that mux ordering respects declared priorities, not merge order.
        explicit_priority_map = {}
        for aspect_info in self.aspect_graphs:
            for state_name, priority in aspect_info.get('prioritized_states', {}).items():
                explicit_priority_map[(state_name, aspect_info['file'])] = priority

        print(f"\nCreating multiplexers for {len(all_gated_states)} gated states: {all_gated_states}")

        # For each gated state, find all assignment edges and create a mux
        # Sort gated states for deterministic iteration order
        for state_name in sorted(all_gated_states):
            # Find the target node for this state (sorted for deterministic selection)
            target_nodes = [
                node for node_id, node in sorted(self.base_graph.nodes.items())
                if node.data and node.data.get('name') == state_name
                and node.data.get('type', '').startswith('isa_state')
            ]

            if not target_nodes:
                print(f"  Warning: Gated state '{state_name}' not found in graph")
                continue

            target_node = target_nodes[0]

            # Collect all assignment edges to this target (sorted for deterministic order)
            # Skip intermediate (dead) writes — the parser tags non-final sequential
            # assignments to isa_state with 'intermediate': True.  Including them
            # would create extra unconditional mux inputs and the wrong one could
            # be selected as the default (e.g., an intermediate pc+2 instead of
            # the final branch target).
            assignments = []  # List of (source_node, edge, precedence, condition)
            for edge in sorted(target_node.incoming_edges, key=lambda e: (e.source.id, e.data.get('type', '') if e.data else '')):
                if edge.data and edge.data.get('type') == 'assignment':
                    if edge.data.get('intermediate'):
                        continue
                    precedence = edge.data.get('precedence', 0)  # Base = 0, aspects = 1+
                    condition = edge.data.get('enable')  # Conditional write condition (e.g., "exception_taken")
                    from_aspect = edge.data.get('from_aspect')
                    assignments.append((edge.source, edge, precedence, condition, from_aspect))

            # NOTE: Do NOT remove intermediate edges from the graph here.
            # They are excluded from the gated mux inputs (filtered above), but
            # they must remain on the target node so that after arch-state splitting
            # they end up on pc_wr where the instruction length analyzer can sum them
            # to determine the total instruction length.  The graph_merger removes
            # them later (after analysis) in merge_instructions().

            if len(assignments) <= 1:
                # Only one assignment, no mux needed
                continue

            print(f"\n  State '{state_name}' has {len(assignments)} assignments:")
            for src, edge, prec, cond, aspect in assignments:
                cond_str = f"when ({cond})" if cond else "unconditional"
                aspect_str = f"from {aspect}" if aspect else "from base"
                print(f"    - {src.id} [{cond_str}, precedence={prec}, {aspect_str}]")

            # Check if this state has explicit priorities from any aspect
            has_explicit_priorities = any(
                (state_name, aspect_info['file']) in explicit_priority_map
                for aspect_info in self.aspect_graphs
            )

            if has_explicit_priorities:
                # Use explicit priority numbers: lower number = higher priority = sorted first.
                # Base instruction writes (no aspect) get a high default priority (sorted last)
                # so they become the mux default case.
                def priority_sort_key(x):
                    src, edge, prec, cond, aspect = x
                    pri = explicit_priority_map.get((state_name, aspect), 9999)
                    return (pri, src.id)
                assignments.sort(key=priority_sort_key)
            else:
                # Use merge-order precedence: higher first (original behavior)
                assignments.sort(key=lambda x: (-x[2], x[0].id))

            # Create multiplexer node
            mux_id = f"{state_name}_gated_mux"
            mux_node = Node(
                node_id=mux_id,
                data={
                    'type': 'multiplexer',
                    'name': mux_id,
                    'display_name': mux_id,
                    'select_type': 'priority',  # Use priority mux (if-else chain)
                    'num_inputs': len(assignments),
                    'gated_write_mux': True,  # Mark this as a gated write mux
                }
            )
            self.base_graph.add_node(mux_node)
            print(f"    Created mux node: {mux_id}")

            # Remove original assignment edges to the target
            for src, edge, prec, cond, aspect in assignments:
                self.base_graph.remove_edge(edge.id)

            # Add mux inputs from source nodes
            for i, (src, edge, prec, cond, aspect) in enumerate(assignments):
                # Determine edge type: conditional inputs are 'mux_input', unconditional is 'mux_default_input'
                edge_type = 'mux_input' if cond else 'mux_default_input'

                # Create edge from source to mux input
                # Preserve original_enable so that the graph_merger can compute
                # consistent structure keys even when muxes are created early
                input_edge = Edge(
                    source=src,
                    target=mux_node,
                    data={
                        'type': edge_type,
                        'input_index': i,  # Use input_index for verilog_generator
                        'original_precedence': prec,
                        'from_aspect': aspect,
                        'original_enable': cond,  # Preserve for structure key computation
                        'explicit_priority': explicit_priority_map.get((state_name, aspect)),
                    }
                )
                self.base_graph.add_edge(input_edge)

                # Create edge for mux select (the condition)
                if cond:
                    # Handle condition - either find existing node or create one for compound expressions
                    cond_node = self._get_or_create_condition_node(cond, i, src.id)
                    if cond_node:
                        select_edge = Edge(
                            source=cond_node,
                            target=mux_node,
                            data={
                                'type': 'mux_select',
                                'select_index': i,  # Use select_index for verilog_generator
                            }
                        )
                        self.base_graph.add_edge(select_edge)
                        print(f"      Input {i}: {src.id} when ({cond_node.id})")
                    else:
                        print(f"      Warning: Could not create condition node for input {i}: {src.id}")
                else:
                    # Unconditional assignment (default case)
                    print(f"      Input {i}: {src.id} (default)")

            # Add edge from mux output to target
            output_edge = Edge(
                source=mux_node,
                target=target_node,
                data={'type': 'assignment'}
            )
            self.base_graph.add_edge(output_edge)
            print(f"    Mux output -> {state_name}")

    def _get_or_create_condition_node(self, cond, input_index: int, src_id: str) -> Optional[Node]:
        """
        Get or create a node for a condition expression.

        For simple identifier conditions, finds the existing node.
        For compound expressions (binary_op, etc.), creates a new node.

        Args:
            cond: The condition expression (dict or string)
            input_index: The mux input index (for generating unique node IDs)
            src_id: The source node ID (for generating unique node IDs)

        Returns:
            The condition node, or None if it couldn't be found/created.
        """
        if not isinstance(cond, dict):
            # String condition - find existing node (sorted for deterministic order)
            cond_name = str(cond)
            for node_id, node in sorted(self.base_graph.nodes.items()):
                if node.id == cond_name or (node.data and node.data.get('name') == cond_name):
                    return node
            return None

        cond_type = cond.get('type')

        if cond_type == 'identifier':
            # Simple identifier - find existing node (sorted for deterministic order)
            cond_name = cond.get('name')
            for node_id, node in sorted(self.base_graph.nodes.items()):
                if node.id == cond_name or (node.data and node.data.get('name') == cond_name):
                    return node
            return None

        elif cond_type == 'binary_op':
            # Compound expression - create a new node for it
            # Generate a unique ID for this condition node (same format as ISA parser)
            left_id = self._expression_to_id(cond.get('left', {}))
            right_id = self._expression_to_id(cond.get('right', {}))
            operator = cond.get('operator', '&')
            cond_id = f"({left_id} {operator} {right_id})"

            # Check if we already created a node for this expression
            if cond_id in self.base_graph.nodes:
                return self.base_graph.nodes[cond_id]

            # Get operand nodes first (to access their bit_widths)
            left_node = self._get_or_create_condition_node(cond.get('left'), input_index, src_id)
            right_node = self._get_or_create_condition_node(cond.get('right'), input_index, src_id)

            # Calculate result width - comparison operators always produce 1-bit
            if operator in ('==', '!=', '<', '>', '<=', '>=', '&', '|', '&&', '||'):
                result_width = 1
            else:
                result_width = 32  # Default for arithmetic

            # Create node matching ISA parser format (type='operation')
            cond_node = Node(
                node_id=cond_id,
                data={
                    'type': 'operation',  # Match ISA parser
                    'operator': operator,
                    'expression': cond,
                    'display_name': cond_id,
                    'bit_width': result_width,
                }
            )
            self.base_graph.add_node(cond_node)

            # Create edges from operand nodes to this condition node
            if left_node:
                left_edge = Edge(
                    source=left_node,
                    target=cond_node,
                    data={'type': 'operand', 'position': 'left'}
                )
                self.base_graph.add_edge(left_edge)

            if right_node:
                right_edge = Edge(
                    source=right_node,
                    target=cond_node,
                    data={'type': 'operand', 'position': 'right'}
                )
                self.base_graph.add_edge(right_edge)

            return cond_node

        elif cond_type == 'unary_op':
            # Unary expression (e.g., ~int_should_take) - create or find node
            operator = cond.get('operator', '~')
            operand_id = self._expression_to_id(cond.get('operand', {}))
            cond_id = f"{operator}{operand_id}"

            # Check if we already have this node
            if cond_id in self.base_graph.nodes:
                return self.base_graph.nodes[cond_id]

            # Get operand node
            operand_node = self._get_or_create_condition_node(cond.get('operand'), input_index, src_id)

            # Create unary operation node
            cond_node = Node(
                node_id=cond_id,
                data={
                    'type': 'operation',
                    'operator': operator,
                    'expression': cond,
                    'display_name': cond_id,
                    'bit_width': 1,
                }
            )
            self.base_graph.add_node(cond_node)

            # Create edge from operand to this node
            if operand_node:
                operand_edge = Edge(
                    source=operand_node,
                    target=cond_node,
                    data={'type': 'operand', 'position': 'unary'}
                )
                self.base_graph.add_edge(operand_edge)

            return cond_node

        elif cond_type in ('literal', 'binary_literal', 'decimal_literal'):
            # Literal value - create or find literal node
            value = cond.get('value', 0)
            width = cond.get('width', None)
            bits = cond.get('bits', None)
            if cond_type == 'binary_literal' and bits:
                literal_id = f"{width}'b{bits}"
            else:
                literal_id = str(value)
            if literal_id in self.base_graph.nodes:
                return self.base_graph.nodes[literal_id]

            node_data = {
                'type': cond_type if cond_type != 'literal' else 'literal',
                'value': value,
                'display_name': literal_id,
            }
            if width is not None:
                node_data['width'] = width
            if bits is not None:
                node_data['bits'] = bits

            literal_node = Node(
                node_id=literal_id,
                data=node_data,
            )
            self.base_graph.add_node(literal_node)
            return literal_node

        elif cond_type == 'array_access':
            # Handle bit access like instr[1] - treat as a bit slice node
            # Build the node ID using the same format as ISA parser (target[high:low])
            target_id = self._expression_to_id(cond.get('target', {}))
            index = cond.get('index', {})
            if isinstance(index, dict) and index.get('type') == 'literal':
                idx_val = index.get('value', 0)
                # Check for existing bit_slice node with high:low format
                slice_id = f"{target_id}[{idx_val}:{idx_val}]"
                if slice_id in self.base_graph.nodes:
                    return self.base_graph.nodes[slice_id]
                # Also check without the _rd suffix
                slice_id_rd = f"{slice_id}_rd"
                if slice_id_rd in self.base_graph.nodes:
                    return self.base_graph.nodes[slice_id_rd]
                # Check for simple instr[N] access
                simple_id = f"{target_id}[{idx_val}]"
                if simple_id in self.base_graph.nodes:
                    return self.base_graph.nodes[simple_id]
                # Node doesn't exist yet — create it as a bit_slice node
                # This happens when a bit is only referenced in 'when' conditions
                # (e.g., instr[1] for the nullification n-bit) and was never used
                # in the base instruction's data path expressions.
                target_node = self._get_or_create_condition_node(
                    cond.get('target', {}), input_index, src_id)
                slice_node = Node(
                    node_id=slice_id,
                    data={
                        'type': 'bit_slice',
                        'display_name': slice_id,
                        'bit_width': 1,
                    }
                )
                self.base_graph.add_node(slice_node)
                # Create bit_access edge from target to slice
                if target_node:
                    bit_edge = Edge(
                        source=target_node,
                        target=slice_node,
                        data={'type': 'bit_access'}
                    )
                    self.base_graph.add_edge(bit_edge)
                return slice_node
            # Non-literal index: try to find by expression ID
            expr_id = self._expression_to_id(cond)
            if expr_id in self.base_graph.nodes:
                return self.base_graph.nodes[expr_id]
            return None

        else:
            print(f"      Warning: Unhandled condition type '{cond_type}' in condition: {cond}")
            return None

    def _expression_to_id(self, expr) -> str:
        """Convert an expression AST to a unique ID string (matching ISA parser format)."""
        if not isinstance(expr, dict):
            return str(expr)

        expr_type = expr.get('type')

        if expr_type == 'identifier':
            return expr.get('name', 'unknown')
        elif expr_type == 'literal':
            return str(expr.get('value', 0))
        elif expr_type == 'binary_op':
            left_id = self._expression_to_id(expr.get('left', {}))
            right_id = self._expression_to_id(expr.get('right', {}))
            operator = expr.get('operator', '&')
            # Match ISA parser format: (left_id operator right_id)
            return f"({left_id} {operator} {right_id})"
        elif expr_type == 'unary_op':
            operator = expr.get('operator', '~')
            operand_id = self._expression_to_id(expr.get('operand', {}))
            return f"{operator}{operand_id}"
        elif expr_type == 'array_access':
            # Handle bit/element access like instr[1], rf[r1], etc.
            # This matches the ISA parser's node naming convention for bit slices
            target_id = self._expression_to_id(expr.get('target', {}))
            index = expr.get('index', {})
            if isinstance(index, dict) and index.get('type') == 'literal':
                idx_val = index.get('value', 0)
                # Single-bit access: use high:low bit_slice format to match ISA parser nodes
                return f"{target_id}[{idx_val}:{idx_val}]"
            else:
                index_id = self._expression_to_id(index)
                return f"{target_id}[{index_id}]"
        elif expr_type == 'bit_slice':
            target_id = self._expression_to_id(expr.get('target') or expr.get('array', {}))
            if 'range' in expr:
                high, low = expr['range']
            else:
                high = expr.get('high', 0)
                low = expr.get('low', 0)
            return f"{target_id}[{high}:{low}]"
        else:
            return f"expr_{hash(str(expr)) % 10000}"

    def _validate_priority_consistency(self):
        """
        Validate that if multiple aspects ASSIGN to the same prioritized state,
        ALL of them must specify a priority.

        This only checks prioritized_states (states with :priority syntax),
        not regular gated_states, because:
        - Regular gates just restrict what an aspect CAN write to
        - Prioritized states indicate the aspect WILL write and needs merging

        Raises ValueError if there are conflicts.
        """
        # Collect all prioritized states across aspects
        # state_name -> list of (aspect_file, priority)
        prioritized_by_aspect = {}

        for aspect_info in self.aspect_graphs:
            aspect_file = aspect_info['file']

            # Only check prioritized states (those with explicit :priority)
            for state, priority in aspect_info.get('prioritized_states', {}).items():
                if state not in prioritized_by_aspect:
                    prioritized_by_aspect[state] = []
                prioritized_by_aspect[state].append((aspect_file, priority))

        # Check for conflicts in prioritized states
        errors = []
        for state, aspects in prioritized_by_aspect.items():
            if len(aspects) <= 1:
                continue  # Only one aspect writes to this state - OK

            # Multiple aspects write to this state - all should have priorities
            # (they do, since we only collected prioritized_states)
            # Just verify no None priorities slipped through
            no_priority = [(f, p) for f, p in aspects if p is None]
            if no_priority:
                errors.append(
                    f"State '{state}' has inconsistent priorities:\n"
                    f"  Without priority: {', '.join(f for f, _ in no_priority)}\n"
                    f"  All aspects writing to the same state must specify a priority."
                )

        if errors:
            raise ValueError("Aspect priority conflicts:\n\n" + "\n\n".join(errors))

    def _merge_prioritized_writes(self):
        """
        Merge writes from multiple aspects to prioritized variables.

        For each variable that has priority annotations from multiple aspects:
        - 1-bit variables: OR all sources together
        - Multi-bit variables: Create priority-ordered conditional chain
        """
        # Step 1: Collect all prioritized writes across aspects
        # Structure: { var_name: [(priority, aspect_file, source_node, edge)] }
        prioritized_vars = {}

        for aspect_info in self.aspect_graphs:
            aspect_file = aspect_info['file']
            prioritized_states = aspect_info.get('prioritized_states', {})
            aspect_nodes = aspect_info['aspect_nodes']

            for var_name, priority in prioritized_states.items():
                if var_name not in prioritized_vars:
                    prioritized_vars[var_name] = []

                # Find the assignment to this variable from this aspect
                for node_id in aspect_nodes:
                    node = self.base_graph.nodes.get(node_id)
                    if not node:
                        continue

                    # Look for assignment edges TO the target variable
                    for edge in node.outgoing_edges:
                        if edge.data and edge.data.get('type') == 'assignment':
                            target = edge.target
                            target_name = target.data.get('name') if target.data else None
                            if target_name == var_name:
                                prioritized_vars[var_name].append({
                                    'priority': priority,
                                    'aspect': aspect_file,
                                    'source': node,
                                    'edge': edge
                                })

        # Step 2: Pre-compute conditions for multi-bit variables BEFORE any merging
        # This is critical because merging 1-bit vars removes the edges we need to find conditions
        conditions_map = {}  # (aspect_file, priority) -> condition_node
        for var_name, writes in prioritized_vars.items():
            if len(writes) < 2:
                continue

            # Find target node to check width
            target_node = None
            for node in self.base_graph.nodes.values():
                if node.data and node.data.get('name') == var_name:
                    target_node = node
                    break

            if not target_node:
                continue

            var_width = target_node.data.get('bit_width', target_node.data.get('width', 1))

            # For 1-bit variables, the source IS the condition
            if var_width == 1:
                for w in writes:
                    key = (w['aspect'], w['priority'])
                    conditions_map[key] = w['source']

        # Step 3: Process each variable with multiple prioritized writes
        for var_name, writes in prioritized_vars.items():
            if len(writes) < 2:
                continue  # No merge needed

            # Sort by priority (lower number = higher priority = checked first)
            writes.sort(key=lambda w: w['priority'])

            # Find the target node
            target_node = None
            for node in self.base_graph.nodes.values():
                if node.data and node.data.get('name') == var_name:
                    target_node = node
                    break

            if not target_node:
                print(f"  Warning: Prioritized variable '{var_name}' not found")
                continue

            var_width = target_node.data.get('bit_width', target_node.data.get('width', 1))

            # Validate: for multi-bit variables, no duplicate priorities
            if var_width > 1:
                priorities = [w['priority'] for w in writes]
                duplicates = [p for p in set(priorities) if priorities.count(p) > 1]
                if duplicates:
                    dup_details = []
                    for p in duplicates:
                        aspects = [w['aspect'] for w in writes if w['priority'] == p]
                        dup_details.append(f"  Priority {p}: {', '.join(aspects)}")
                    raise ValueError(
                        f"Multiple aspects assign to multi-bit variable '{var_name}' "
                        f"with the same priority:\n" + "\n".join(dup_details) + "\n"
                        f"Each aspect must use a unique priority for multi-bit variables."
                    )

            print(f"\nMerging {len(writes)} writes to '{var_name}' (width={var_width}):")
            for w in writes:
                print(f"  Priority {w['priority']}: {w['source'].id} from {os.path.basename(w['aspect'])}")

            if var_width == 1:
                self._create_or_merge(target_node, writes, var_name)
            else:
                self._create_priority_chain_merge(target_node, writes, var_name, conditions_map)

    def _create_or_merge(self, target_node: Node, writes: List[Dict], var_name: str):
        """
        Merge multiple 1-bit writes using OR.

        Creates: target = source1 | source2 | source3 | ...
        """
        # Remove original assignment edges
        for w in writes:
            if w['edge'].id in [e.id for e in self.base_graph.edges.values()]:
                self.base_graph.remove_edge(w['edge'].id)

        # Build OR chain: ((source1 | source2) | source3) | ...
        sources = [w['source'] for w in writes]

        if len(sources) == 2:
            # Simple OR of two sources
            or_node = self._create_or_node(sources[0], sources[1], f"{var_name}_merged")
        else:
            # Chain of ORs
            or_node = self._create_or_node(sources[0], sources[1], f"{var_name}_or_0_1")
            for i, source in enumerate(sources[2:], start=2):
                or_node = self._create_or_node(or_node, source, f"{var_name}_or_{i}")

        # Create new assignment edge from OR result to target
        new_edge = Edge(or_node, target_node, data={'type': 'assignment'})
        self.base_graph.add_edge(new_edge)

        print(f"  Created OR merge: {var_name} = {' | '.join(s.id for s in sources)}")

    def _create_or_node(self, left, right, node_id: str) -> Node:
        """Create an OR operation node."""
        # Handle case where left/right are already nodes vs node IDs
        left_node = left if isinstance(left, Node) else self.base_graph.nodes.get(left, left)
        right_node = right if isinstance(right, Node) else self.base_graph.nodes.get(right, right)

        left_id = left_node.id if isinstance(left_node, Node) else str(left_node)
        right_id = right_node.id if isinstance(right_node, Node) else str(right_node)

        or_node = Node(
            node_id=node_id,
            data={
                'type': 'operation',
                'operator': '|',
                'display_name': f"({left_id} | {right_id})",
                'bit_width': 1
            }
        )
        self.base_graph.add_node(or_node)

        # Create edges from operands to OR node
        left_edge = Edge(left_node, or_node, data={'type': 'operand', 'position': 'left'})
        right_edge = Edge(right_node, or_node, data={'type': 'operand', 'position': 'right'})
        self.base_graph.add_edge(left_edge)
        self.base_graph.add_edge(right_edge)

        return or_node

    def _create_priority_chain_merge(self, target_node: Node, writes: List[Dict], var_name: str, conditions_map: Dict):
        """
        Merge multiple multi-bit writes using priority-ordered conditionals.

        Creates: target = cond1 ? val1 : (cond2 ? val2 : (cond3 ? val3 : default))

        The condition for each value comes from the conditions_map, which maps
        (aspect_file, priority) to the condition node (source of the 1-bit var
        assignment with the same priority from the same aspect).
        """
        var_width = target_node.data.get('bit_width', target_node.data.get('width', 32))

        # Remove original assignment edges
        for w in writes:
            if w['edge'].id in [e.id for e in self.base_graph.edges.values()]:
                self.base_graph.remove_edge(w['edge'].id)

        # Find the condition for each write from the pre-computed map
        writes_with_conditions = []
        for w in writes:
            key = (w['aspect'], w['priority'])
            condition = conditions_map.get(key)
            if condition:
                writes_with_conditions.append({
                    'priority': w['priority'],
                    'value': w['source'],
                    'condition': condition,
                    'aspect': w['aspect']
                })
            else:
                print(f"  Warning: No condition found for priority {w['priority']} from {os.path.basename(w['aspect'])}")

        if len(writes_with_conditions) == 0:
            print(f"  Error: No conditions found for any writes to {var_name}")
            return

        # Build ternary chain from lowest to highest priority (inside-out)
        # Start with default value (0)
        default_val = self._get_or_create_literal_node(0, var_width, f"{var_name}_default")

        # Build from the end: cond_n ? val_n : default
        # Then: cond_{n-1} ? val_{n-1} : (cond_n ? val_n : default)
        # etc.
        result_node = default_val

        # Process in reverse order (lowest priority first, becomes innermost)
        for w in reversed(writes_with_conditions):
            ternary_id = f"{var_name}_priority_{w['priority']}"

            ternary_node = Node(
                node_id=ternary_id,
                data={
                    'type': 'ternary_op',
                    'display_name': f"{w['condition'].id} ? {w['value'].id} : ...",
                    'bit_width': var_width
                }
            )
            self.base_graph.add_node(ternary_node)

            # Connect condition, true value, and false value (previous result)
            cond_edge = Edge(w['condition'], ternary_node,
                            data={'type': 'ternary_condition'})
            true_edge = Edge(w['value'], ternary_node,
                            data={'type': 'ternary_true'})
            false_edge = Edge(result_node, ternary_node,
                             data={'type': 'ternary_false'})

            self.base_graph.add_edge(cond_edge)
            self.base_graph.add_edge(true_edge)
            self.base_graph.add_edge(false_edge)

            result_node = ternary_node

        # Create assignment from final ternary to target
        new_edge = Edge(result_node, target_node, data={'type': 'assignment'})
        self.base_graph.add_edge(new_edge)

        print(f"  Created priority chain for {var_name}:")
        for w in writes_with_conditions:
            print(f"    Priority {w['priority']}: {w['condition'].id} ? {w['value'].id}")

    def _find_condition_for_write(self, write: Dict) -> Optional[Node]:
        """
        Find the condition variable for a multi-bit write.

        Strategy: Look for a 1-bit variable assignment from the same aspect
        with the same priority. The SOURCE of that assignment is the condition.

        For example:
        - interrupt.isa assigns exc_taken:1 = int_should_take
        - interrupt.isa assigns exc_vector:1 = irq_vector
        - The condition for irq_vector is int_should_take
        """
        priority = write['priority']
        aspect = write['aspect']

        # Look through all prioritized variables for this aspect
        for aspect_info in self.aspect_graphs:
            if aspect_info['file'] != aspect:
                continue

            prioritized_states = aspect_info.get('prioritized_states', {})
            aspect_nodes = aspect_info['aspect_nodes']

            # Find 1-bit variables with same priority
            for other_var_name, var_priority in prioritized_states.items():
                if var_priority != priority:
                    continue

                # Check if this is a 1-bit variable
                other_target_node = None
                for node in self.base_graph.nodes.values():
                    if node.data and node.data.get('name') == other_var_name:
                        other_target_node = node
                        break

                if not other_target_node:
                    continue

                var_width = other_target_node.data.get('bit_width', other_target_node.data.get('width', 1))
                if var_width != 1:
                    continue

                # Find the assignment to this 1-bit variable from this aspect
                for node_id in aspect_nodes:
                    node = self.base_graph.nodes.get(node_id)
                    if not node:
                        continue

                    for edge in node.outgoing_edges:
                        if edge.data and edge.data.get('type') == 'assignment':
                            if edge.target.id == other_target_node.id:
                                # Found it! The source of this assignment is the condition
                                return node

        return None

    def _get_or_create_literal_node(self, value: int, width: int, node_id: str) -> Node:
        """Get or create a literal node with the given value and width."""
        # Check if node already exists
        if node_id in self.base_graph.nodes:
            return self.base_graph.nodes[node_id]

        node = Node(
            node_id=node_id,
            data={
                'type': 'literal',
                'value': value,
                'bit_width': width,
                'display_name': str(value)
            }
        )
        self.base_graph.add_node(node)
        return node


def merge_aspects(graph: ResourceGraph, base_file_path: Optional[str] = None):
    """
    Convenience function to merge all aspects in a graph.

    Args:
        graph: The base ISA resource graph with aspect declarations
        base_file_path: Optional path to the base .isa file
    """
    merger = AspectMerger(graph, base_file_path)
    merger.load_and_merge_aspects()
