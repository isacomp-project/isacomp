"""
Orthogon merger for ISA specifications.

Expands `use` statements in instruction graphs by:
1. Parsing each variant's body into a subgraph
2. Creating mux nodes for `provides` outputs (selector-based)
3. Creating mux nodes for `writes` state side effects (selector-based)
4. Injecting the muxed values into the host instruction's scope

The key difference from aspect_merger.py is the selection mechanism:
- Aspects use priority-based override (if-else chain with conditions)
- Orthogons use data-select mux (one-hot or encoded, exactly one variant active)

This means the orthogon's muxes directly use the selector signal as the
select input, making them efficient and recognizable for structural sharing
during instruction merging.
"""

import os
from typing import Dict, List, Optional, Set, Tuple
from .resource_graph import ResourceGraph, Node, Edge
from .orthogon_parser import (
    OrthogonDefinition, VariantDef, ProvidesDef, StateRef,
    parse_orthogon_file, is_orthogon_file,
)


class OrthogonMerger:
    """
    Expands orthogon `use` statements into mux trees within an instruction graph.

    Usage:
        merger = OrthogonMerger(graph, instruction_file_path)
        merger.register_orthogon(orthogon_def)
        merger.expand_use(use_decl)
    """

    def __init__(self, graph: ResourceGraph, base_file_path: Optional[str] = None):
        self.graph = graph
        self.base_file_path = base_file_path
        # Registry of loaded orthogon definitions by name
        self.orthogons: Dict[str, OrthogonDefinition] = {}

    def register_orthogon(self, defn: OrthogonDefinition):
        """Register an orthogon definition for later use."""
        if defn.name in self.orthogons:
            existing = self.orthogons[defn.name]
            if existing.source_file != defn.source_file:
                raise ValueError(
                    f"Orthogon '{defn.name}' already registered from "
                    f"'{existing.source_file}', cannot re-register from "
                    f"'{defn.source_file}'"
                )
            return  # Same file, already registered
        self.orthogons[defn.name] = defn

    def load_orthogon(self, name: str, search_dirs: Optional[List[str]] = None) -> OrthogonDefinition:
        """
        Load an orthogon definition by name, searching for the file.

        Searches for files named '{name}.isa' in:
        1. The directory of the base instruction file
        2. Any provided search directories
        3. A sibling 'orthogons/' directory
        """
        if name in self.orthogons:
            return self.orthogons[name]

        candidates = []
        if self.base_file_path:
            base_dir = os.path.dirname(os.path.abspath(self.base_file_path))
            candidates.append(os.path.join(base_dir, f"{name}.isa"))
            candidates.append(os.path.join(base_dir, "orthogons", f"{name}.isa"))
            # Also check parent directory
            parent_dir = os.path.dirname(base_dir)
            candidates.append(os.path.join(parent_dir, f"{name}.isa"))
            candidates.append(os.path.join(parent_dir, "orthogons", f"{name}.isa"))

        if search_dirs:
            for d in search_dirs:
                candidates.append(os.path.join(d, f"{name}.isa"))

        for path in candidates:
            if os.path.exists(path) and is_orthogon_file(path):
                defn = parse_orthogon_file(path)
                self.register_orthogon(defn)
                return defn

        raise FileNotFoundError(
            f"Orthogon '{name}' not found. Searched: {candidates}"
        )

    def expand_use(self, use_decl: dict, intermediate_values: Optional[Dict] = None):
        """
        Expand a `use` statement into the instruction graph.

        Args:
            use_decl: Dictionary with:
                - 'orthogon_name': str
                - 'selector_expr': parsed AST expression dict
                - 'selector_node_id': node ID for the selector expression in the graph
            intermediate_values: Current intermediate value map from the parser
                (so the orthogon sees in-cycle assignments preceding the `use`)
        """
        orth_name = use_decl['orthogon_name']
        selector_expr = use_decl['selector_expr']
        selector_node_id = use_decl['selector_node_id']

        defn = self.orthogons.get(orth_name)
        if defn is None:
            defn = self.load_orthogon(orth_name)

        # Validate interface: check that uses/writes states exist in the graph
        self._validate_interface(defn)

        # Get or create the selector node in the graph
        selector_node = self.graph.nodes.get(selector_node_id)
        if selector_node is None:
            raise ValueError(
                f"Selector node '{selector_node_id}' not found in graph "
                f"for orthogon '{orth_name}'"
            )

        # Derive an instruction-specific tag for mux and output nodes.
        # Variant subgraph internals use orthogon-only prefixes so the
        # merger can share them across instructions.
        instr_tag = use_decl.get('instruction_tag', '')
        if not instr_tag and self.base_file_path:
            import os
            instr_tag = os.path.splitext(os.path.basename(self.base_file_path))[0]

        # Phase 1: Parse each variant's body into the graph.
        # Variant internals use orthogon-only prefix (shared across instructions).
        # Mux/output nodes use instruction-specific prefix (per-instruction).
        variant_subgraphs = {}
        for variant in defn.variants:
            prefix = f"{orth_name}_{variant.name}"
            variant_info = self._expand_variant(
                defn, variant, prefix, intermediate_values
            )
            variant_subgraphs[variant.name] = variant_info

        # Phase 2: Create mux nodes for provides outputs
        for prov in defn.provides:
            self._create_provides_mux(
                defn, prov, selector_node, variant_subgraphs,
                intermediate_values, instr_tag,
            )

        # Phase 3: Create mux nodes for writes state
        for wr in defn.writes:
            self._create_writes_mux(
                defn, wr, selector_node, variant_subgraphs,
                intermediate_values, instr_tag,
            )

    def _validate_interface(self, defn: OrthogonDefinition):
        """Validate that all uses/writes states exist in the host graph."""
        graph_state_names = {
            node.data.get('name')
            for node in self.graph.nodes.values()
            if node.data and node.data.get('type', '').startswith('isa_state')
        }

        for ref in defn.uses:
            if ref.name not in graph_state_names:
                raise ValueError(
                    f"Orthogon '{defn.name}' uses state '{ref.name}' which "
                    f"does not exist in the host instruction. "
                    f"Available states: {graph_state_names}"
                )

        for ref in defn.writes:
            if ref.name not in graph_state_names:
                raise ValueError(
                    f"Orthogon '{defn.name}' writes state '{ref.name}' which "
                    f"does not exist in the host instruction. "
                    f"Available states: {graph_state_names}"
                )

    def _expand_variant(
        self,
        defn: OrthogonDefinition,
        variant: VariantDef,
        prefix: str,
        intermediate_values: Optional[Dict],
    ) -> dict:
        """
        Parse a variant's body tokens into the graph with prefixed node names.

        Returns a dict mapping provides/writes names to their output node IDs.
        """
        from .isa_parser import ISAParser

        # Build the variant body text with declarations for interface state.
        # The variant body needs to know about:
        # 1. uses states (read-only, already in graph)
        # 2. writes states (read-write, already in graph)
        # 3. provides outputs (new vars, will be created with prefix)
        #
        # We parse the variant body as a mini-instruction into the existing graph,
        # but with a node-name prefix to avoid collisions.

        parser = ISAParser()

        # Reconstruct the variant body text from tokens
        body_text = self._tokens_to_text(variant.body_tokens)

        # Build preamble: declare provides as vars so the body can assign to them
        preamble_lines = []
        for prov in defn.provides:
            preamble_lines.append(f"var {prefix}_{prov.name}[{prov.bit_high}:{prov.bit_low}];")

        # Declare writes states as vars for intermediate tracking.
        # The variant body references them by their original names, but we need
        # prefixed copies to avoid clobbering the host instruction's state.
        for wr in defn.writes:
            dims = f"[{wr.bit_high}:{wr.bit_low}]"
            for d in wr.array_dims:
                dims += f"[{d[0]}:{d[1]}]"
            preamble_lines.append(f"var {prefix}_{wr.name}{dims};")

        # Rewrite the body to use prefixed names for provides, writes,
        # AND all local var declarations.  This prevents name collisions
        # when multiple instructions expand the same orthogon variant.
        rewritten_body = body_text

        # Collect local var names from the body tokens so we can prefix them.
        local_var_names = self._extract_var_names(variant.body_tokens)

        # Rewrite local var declarations and references
        for var_name in local_var_names:
            rewritten_body = self._rewrite_identifier(
                rewritten_body, var_name, f"{prefix}_{var_name}"
            )

        # Rewrite provides names
        for prov in defn.provides:
            rewritten_body = self._rewrite_identifier(
                rewritten_body, prov.name, f"{prefix}_{prov.name}"
            )

        # Rewrite writes names — both reads and writes within the variant
        for wr in defn.writes:
            rewritten_body = self._rewrite_identifier(
                rewritten_body, wr.name, f"{prefix}_{wr.name}"
            )

        # Build the full text to parse
        full_text = '\n'.join(preamble_lines) + '\n' + rewritten_body

        # Parse into the existing graph.
        # We set up intermediate values so reads of uses/writes states resolve
        # to the current instruction-scope values.
        if intermediate_values:
            self.graph._intermediate_values = dict(intermediate_values)

            # For writes states, the variant should start reading from the
            # current intermediate value (e.g., the host's current pc).
            # Copy the intermediate to the prefixed name.
            for wr in defn.writes:
                if wr.name in intermediate_values:
                    self.graph._intermediate_values[f"{prefix}_{wr.name}"] = (
                        intermediate_values[wr.name]
                    )

        parser.parse(full_text, existing_graph=self.graph, skip_aspect_merge=True)

        # Sync the parser's updated intermediate values back to the graph.
        # The parser made a copy of _intermediate_values at the start, then
        # updated its own copy as it processed imperative assignments (e.g.,
        # `pc = pc + 1; pc = pc + 1` updates the intermediate twice).  We
        # need these updates reflected in graph._intermediate_values so that
        # _find_latest_assignment_target sees the final value, not the initial.
        if hasattr(parser, 'intermediate_values'):
            for key, val in parser.intermediate_values.items():
                if key.startswith(prefix):
                    self.graph._intermediate_values[key] = val

        # Fix up assignment edge data for writes nodes.
        # The text rewriting turns `pc = pc + 1` into
        # `addr_mode_imm_pc = addr_mode_imm_pc + 1`, creating a spurious
        # self-reference in the edge's expression AST.  The actual graph
        # edges are wired correctly (source is the computation, not a
        # feedback loop), so we just clear the misleading AST data to
        # prevent the Verilog backend from treating these as registers.
        for wr in defn.writes:
            prefixed_name = f"{prefix}_{wr.name}"
            wr_node = self.graph.nodes.get(prefixed_name)
            if wr_node:
                for edge in wr_node.incoming_edges:
                    if edge.data and edge.data.get('type') == 'assignment':
                        # Remove the right-hand side AST to prevent
                        # self-reference detection
                        edge.data.pop('right', None)
                        edge.data.pop('left', None)

        # Collect output node IDs for provides and writes
        result = {
            'provides': {},
            'writes': {},
            'prefix': prefix,
            'condition': variant.condition,
        }

        for prov in defn.provides:
            prefixed_name = f"{prefix}_{prov.name}"
            # Find the node that was last assigned to this provides var
            node = self._find_latest_assignment_target(prefixed_name)
            if node is not None:
                result['provides'][prov.name] = node.id
            else:
                raise ValueError(
                    f"Variant '{variant.name}' in orthogon '{defn.name}' "
                    f"does not assign to provides value '{prov.name}'"
                )

        for wr in defn.writes:
            prefixed_name = f"{prefix}_{wr.name}"
            node = self._find_latest_assignment_target(prefixed_name)
            if node is not None:
                result['writes'][wr.name] = node.id
            else:
                raise ValueError(
                    f"Variant '{variant.name}' in orthogon '{defn.name}' "
                    f"does not assign to writes state '{wr.name}'"
                )

        return result

    def _create_provides_mux(
        self,
        defn: OrthogonDefinition,
        prov: ProvidesDef,
        selector_node: Node,
        variant_subgraphs: Dict[str, dict],
        intermediate_values: Optional[Dict] = None,
        instr_tag: str = '',
    ):
        """
        Create a mux node for one provides output.

        The mux selects between variant outputs based on the selector signal.
        The mux output becomes a var in the host instruction's scope.
        """
        # Mux nodes use orthogon-only prefix so the merger can share them
        # across instructions using the same orthogon.
        mux_id = f"{defn.name}_{prov.name}_mux"
        mux_node = Node(
            node_id=mux_id,
            data={
                'type': 'multiplexer',
                'name': mux_id,
                'display_name': f"{defn.name}.{prov.name}",
                'select_type': 'orthogon',
                'orthogon_name': defn.name,
                'provides_name': prov.name,
                'num_inputs': len(defn.variants),
                'bit_width': prov.bit_width,
                'orthogon_mux': True,
                'from_orthogon': defn.name,
            }
        )
        self.graph.add_node(mux_node)

        # The mux node IS the provides value. We register it as the
        # intermediate value for this name so the host instruction's
        # subsequent references resolve to the mux output.
        # We also create a var node with the provides name so the host
        # parser can find it, but give it a unique ID.
        output_id = f"{mux_id}_out"
        output_node = Node(
            node_id=output_id,
            data={
                'type': 'var',
                'name': prov.name,
                'display_name': prov.name,
                'bit_width': prov.bit_width,
                'bit_range': [prov.bit_high, prov.bit_low],
                'from_orthogon': defn.name,
            },
            from_isa_spec=True,
        )
        self.graph.add_node(output_node)

        # Edge: mux output -> provides var
        output_edge = Edge(
            source=mux_node,
            target=output_node,
            data={'type': 'assignment', 'from_orthogon': defn.name},
        )
        self.graph.add_edge(output_edge)

        # Register the output node as the intermediate value for this name
        # so subsequent host references to prov.name find it.
        if intermediate_values is not None:
            intermediate_values[prov.name] = output_id
        if hasattr(self.graph, '_intermediate_values'):
            self.graph._intermediate_values[prov.name] = output_id

        # Edge: global selector -> mux (for Verilog case statement generation).
        # Tagged as 'orthogon_selector' so the merger doesn't treat it as
        # a per-variant condition.
        select_edge = Edge(
            source=selector_node,
            target=mux_node,
            data={
                'type': 'mux_select',
                'orthogon_selector': True,
                'from_orthogon': defn.name,
            },
        )
        self.graph.add_edge(select_edge)

        # Edges: variant outputs -> mux inputs with per-variant conditions.
        # Group variants by their value source node so that variants
        # producing the same value share one mux_input with an OR'd
        # condition.  This is critical for correct merging: without
        # grouping, the merger may discard mux_input edges for
        # duplicate values, losing their associated select conditions.
        self._add_grouped_mux_inputs(
            defn, mux_node, selector_node, variant_subgraphs,
            lambda vinfo: vinfo['provides'].get(prov.name),
            prov.name, 'provides', instr_tag,
        )

    def _create_writes_mux(
        self,
        defn: OrthogonDefinition,
        wr: StateRef,
        selector_node: Node,
        variant_subgraphs: Dict[str, dict],
        intermediate_values: Optional[Dict],
        instr_tag: str = '',
    ):
        """
        Create a mux node for one writes state side effect.

        The mux selects between variant write values based on the selector.
        The mux output becomes the new intermediate value for this state.
        """
        # Group variants by their write-value node and create a ternary
        # chain instead of a case-style mux.  The merger handles ternaries
        # natively, avoiding cross-instruction condition leakage.
        ternary_output = self._create_writes_ternary(
            defn, selector_node, variant_subgraphs, wr, instr_tag,
        )

        # Wire the ternary output directly to the state target.
        target_state = self._find_state_node(wr.name)
        if target_state:
            # Remove existing assignment edges from the instruction body.
            edges_to_remove = [
                e for e in list(target_state.incoming_edges)
                if e.data and e.data.get('type') == 'assignment'
                and not e.data.get('from_orthogon')
            ]
            for e in edges_to_remove:
                self.graph.remove_edge(e.id)

            assign_edge = Edge(
                source=ternary_output,
                target=target_state,
                data={
                    'type': 'assignment',
                    'from_orthogon': defn.name,
                    'orthogon_writes': True,
                },
            )
            self.graph.add_edge(assign_edge)

            # Update intermediate values so subsequent reads see the output
            if intermediate_values is not None:
                intermediate_values[wr.name] = ternary_output.id

    def _create_variant_condition_node(
        self,
        defn: OrthogonDefinition,
        variant: VariantDef,
        selector_node: Node,
        variant_index: int,
        instr_tag: str = '',
    ) -> Optional[Node]:
        """Create (or find) a node representing the variant's selector match condition."""
        cond = variant.condition
        # Use orthogon-only prefix (no instr_tag) so the merger can share
        # identical condition nodes across instructions.
        cond_id = f"{defn.name}_{variant.name}_sel_match"

        # Reuse if already created (shared across provides/writes muxes)
        if cond_id in self.graph.nodes:
            return self.graph.nodes[cond_id]

        if cond.get('type') == 'binary_op' and cond.get('operator') == '==':
            cond_node = Node(
                node_id=cond_id,
                data={
                    'type': 'operation',
                    'name': cond_id,
                    'display_name': f"{variant.name}?",
                    'operator': '==',
                    'bit_width': 1,
                    'from_orthogon': defn.name,
                    'variant_name': variant.name,
                    'variant_index': variant_index,
                },
            )
            self.graph.add_node(cond_node)

            right = cond.get('right', {})
            literal_id = f"{cond_id}_val"
            literal_node = Node(
                node_id=literal_id,
                data={
                    'type': right.get('type', 'literal'),
                    'name': literal_id,
                    'value': right.get('value'),
                    'width': right.get('width'),
                    'format': right.get('format'),
                    'from_orthogon': defn.name,
                },
            )
            self.graph.add_node(literal_node)

            Edge(
                source=selector_node,
                target=cond_node,
                data={'type': 'operand', 'operand_position': 'left'},
            )
            Edge(
                source=literal_node,
                target=cond_node,
                data={'type': 'operand', 'operand_position': 'right'},
            )
            return cond_node

        # Fallback for complex conditions
        cond_node = Node(
            node_id=cond_id,
            data={
                'type': 'orthogon_condition',
                'name': cond_id,
                'condition_ast': cond,
                'from_orthogon': defn.name,
                'variant_name': variant.name,
                'variant_index': variant_index,
            },
        )
        self.graph.add_node(cond_node)
        return cond_node

    def _create_writes_ternary(
        self,
        defn: OrthogonDefinition,
        selector_node: Node,
        variant_subgraphs: Dict[str, dict],
        wr,
        instr_tag: str,
    ) -> Node:
        """Create a ternary chain for a writes state output.

        Groups variants by their write-value node, creates an OR of the
        variant conditions for each group, then builds a ternary_op chain.
        Returns the output node.
        """
        from collections import OrderedDict

        groups: Dict[str, list] = OrderedDict()
        for i, variant in enumerate(defn.variants):
            vinfo = variant_subgraphs[variant.name]
            src_id = vinfo['writes'].get(wr.name)
            if src_id is None:
                raise ValueError(
                    f"Variant '{variant.name}' missing writes '{wr.name}'"
                )
            src_node = self.graph.nodes.get(src_id)
            if src_node is None:
                raise ValueError(
                    f"Node '{src_id}' not found for variant "
                    f"'{variant.name}' writes '{wr.name}'"
                )
            cond_node = self._create_variant_condition_node(
                defn, variant, selector_node, i, instr_tag
            )
            groups.setdefault(src_id, []).append((src_node, variant, cond_node))

        group_list = list(groups.items())
        if len(group_list) < 2:
            return group_list[0][1][0][0]

        # Build ternary chain: if (group0_cond) value0 else ... else valueN
        prev_node = group_list[-1][1][0][0]  # default = last group

        for g_idx in range(len(group_list) - 2, -1, -1):
            src_id, members = group_list[g_idx]
            value_node = members[0][0]

            if len(members) == 1:
                cond = members[0][2]
            else:
                or_id = f"{defn.name}_{wr.name}_wr_g{g_idx}_or"
                or_node = Node(
                    node_id=or_id,
                    data={
                        'type': 'operation',
                        'operator': '||',
                        'bit_width': 1,
                        'from_orthogon': defn.name,
                    },
                )
                self.graph.add_node(or_node)
                for op_i, (_, _, cn) in enumerate(members):
                    if cn:
                        Edge(source=cn, target=or_node,
                             data={'type': 'operand', 'operand_index': op_i})
                cond = or_node

            tern_id = f"{defn.name}_{wr.name}_wr_tern{g_idx}"
            tern_node = Node(
                node_id=tern_id,
                data={
                    'type': 'ternary_op',
                    'display_name': f"{defn.name}.{wr.name} select {g_idx}",
                    'bit_width': wr.bit_width,
                    'from_orthogon': defn.name,
                },
            )
            self.graph.add_node(tern_node)

            Edge(source=cond, target=tern_node,
                 data={'type': 'ternary_condition', 'operand_index': 0})
            Edge(source=value_node, target=tern_node,
                 data={'type': 'ternary_true', 'operand_index': 1})
            Edge(source=prev_node, target=tern_node,
                 data={'type': 'ternary_false', 'operand_index': 2})

            prev_node = tern_node

        return prev_node

    def _add_grouped_mux_inputs(
        self,
        defn: OrthogonDefinition,
        mux_node: Node,
        selector_node: Node,
        variant_subgraphs: Dict[str, dict],
        get_source_id,
        output_name: str,
        kind: str,
        instr_tag: str = '',
    ):
        """Add mux inputs grouped by value node.

        Variants producing the same value share one mux_input edge with
        an OR'd select condition.  This ensures that the merger/dedup
        never discards conditions for duplicate values.
        """
        from collections import OrderedDict

        # Collect (source_node_id, variant_index, variant, cond_node) for each variant
        variant_info = []
        for i, variant in enumerate(defn.variants):
            vinfo = variant_subgraphs[variant.name]
            source_node_id = get_source_id(vinfo)
            if source_node_id is None:
                raise ValueError(
                    f"Variant '{variant.name}' missing {kind} '{output_name}'"
                )
            source_node = self.graph.nodes.get(source_node_id)
            if source_node is None:
                raise ValueError(
                    f"Node '{source_node_id}' not found for variant "
                    f"'{variant.name}' {kind} '{output_name}'"
                )
            cond_node = self._create_variant_condition_node(
                defn, variant, selector_node, i, instr_tag
            )
            variant_info.append((source_node_id, source_node, i, variant, cond_node))

        # Group by source node id (preserving first-seen order)
        groups: Dict[str, list] = OrderedDict()
        for src_id, src_node, idx, variant, cond_node in variant_info:
            groups.setdefault(src_id, []).append((src_node, idx, variant, cond_node))

        # Create one mux_input + one select per group
        mux_input_idx = 0
        for src_id, members in groups.items():
            src_node = members[0][0]

            # Build condition: OR of all variant conditions in this group
            if len(members) == 1:
                _, idx, variant, cond_node = members[0]
                combined_cond = cond_node
            else:
                # Create OR node combining all variant conditions.
                # Use orthogon-only prefix so the merger can share these.
                or_id = f"{defn.name}_{output_name}_group{mux_input_idx}_or"
                or_node = Node(
                    node_id=or_id,
                    data={
                        'type': 'operation',
                        'operator': '||',
                        'display_name': f"{defn.name}.{output_name} group {mux_input_idx}",
                        'bit_width': 1,
                        'from_orthogon': defn.name,
                    },
                )
                self.graph.add_node(or_node)
                for op_i, (_, _, variant, cond_node) in enumerate(members):
                    if cond_node:
                        Edge(
                            source=cond_node,
                            target=or_node,
                            data={'type': 'operand', 'operand_index': op_i},
                        )
                combined_cond = or_node

            # Add mux_input edge
            input_edge = Edge(
                source=src_node,
                target=mux_node,
                data={
                    'type': 'mux_input',
                    'input_index': mux_input_idx,
                    'variant_name': members[0][2].name,
                    'from_orthogon': defn.name,
                },
            )
            self.graph.add_edge(input_edge)

            # Add mux_select edge
            if combined_cond:
                cond_edge = Edge(
                    source=combined_cond,
                    target=mux_node,
                    data={
                        'type': 'mux_select',
                        'select_index': mux_input_idx,
                        'from_orthogon': defn.name,
                    },
                )
                self.graph.add_edge(cond_edge)

            mux_input_idx += 1

    # ── Helpers ───────────────────────────────────────────────────────

    def _find_state_node(self, name: str) -> Optional[Node]:
        """Find an isa_state node by name."""
        for node in self.graph.nodes.values():
            if (node.data and
                node.data.get('name') == name and
                node.data.get('type', '').startswith('isa_state')):
                return node
        return None

    def _find_latest_assignment_target(self, name: str) -> Optional[Node]:
        """Find the node that was last assigned to a variable by name."""
        # Check intermediate values first (includes parser-synced values)
        if hasattr(self.graph, '_intermediate_values'):
            iv = self.graph._intermediate_values.get(name)
            if iv is not None:
                # iv can be a Node object (from parser) or a string node ID
                if hasattr(iv, 'id'):
                    return iv
                if isinstance(iv, str) and iv in self.graph.nodes:
                    return self.graph.nodes[iv]

        # Fall back to finding the node by name
        for node_id, node in self.graph.nodes.items():
            if node.data and node.data.get('name') == name:
                return node
        return None

    @staticmethod
    def _extract_var_names(tokens: List) -> List[str]:
        """Extract local var names from a token list (var NAME[...]; declarations)."""
        names = []
        i = 0
        while i < len(tokens):
            if tokens[i].type == 'VAR' and i + 1 < len(tokens):
                # Next token should be the var name (IDENTIFIER)
                if tokens[i + 1].type == 'IDENTIFIER':
                    names.append(tokens[i + 1].value)
            i += 1
        return names

    @staticmethod
    def _tokens_to_text(tokens: List) -> str:
        """Reconstruct source text from a token list."""
        if not tokens:
            return ''
        parts = []
        prev_line = tokens[0].line if tokens else 0
        for tok in tokens:
            # Add newlines for line breaks
            if tok.line > prev_line:
                parts.append('\n' * (tok.line - prev_line))
                prev_line = tok.line
            parts.append(tok.value)
            parts.append(' ')
        return ''.join(parts)

    @staticmethod
    def _rewrite_identifier(text: str, old_name: str, new_name: str) -> str:
        """
        Replace standalone identifier occurrences in text.

        Uses word-boundary matching to avoid replacing substrings.
        """
        import re
        pattern = r'(?<![a-zA-Z0-9_])' + re.escape(old_name) + r'(?![a-zA-Z0-9_])'
        return re.sub(pattern, new_name, text)


def expand_orthogon_uses(graph: ResourceGraph, base_file_path: Optional[str] = None):
    """
    Process all orthogon `use` declarations in a graph.

    Called after initial parsing, before aspect merging.
    """
    if not hasattr(graph, 'orthogon_uses') or not graph.orthogon_uses:
        return

    merger = OrthogonMerger(graph, base_file_path)

    for use_decl in graph.orthogon_uses:
        merger.expand_use(use_decl)
