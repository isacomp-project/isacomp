"""
Helper function to create gated write multiplexers.

This is extracted from aspect_merger.py and adapted to work with merged graphs
where architectural state has been split into _rd and _wr nodes.
"""

from .resource_graph import ResourceGraph, Node, Edge


def create_gated_write_multiplexers(merged_graph: ResourceGraph, instruction_graphs: dict):
    """
    Create multiplexer nodes for gated writes in a merged graph.

    When multiple assignments target the same state (base + aspects with 'when' conditions),
    create a priority multiplexer that combines them properly:
    - Aspects with higher precedence become earlier mux inputs
    - Conditional writes use their 'enable' condition as the mux select
    - Base writes become the default case

    Args:
        merged_graph: The merged graph (after arch state splitting)
        instruction_graphs: Dict of instruction graphs (to get gated_states metadata)
    """
    # Collect all gated states from all instruction graphs
    all_gated_states = set()
    for instr_name, graph in instruction_graphs.items():
        if hasattr(graph, 'gated_states'):
            all_gated_states.update(graph.gated_states)

    if not all_gated_states:
        return  # No gated writes to process


    # For each gated state, find all assignment edges and create a mux
    for state_name in all_gated_states:
        # In merged graph, architectural state is split into _rd and _wr nodes
        # We need to find the _wr node for assignment targets
        target_node_id = f"{state_name}_wr"
        if target_node_id not in merged_graph.nodes:
            # Fallback: maybe it wasn't split (e.g., write-only state)
            target_node_id = state_name
            if target_node_id not in merged_graph.nodes:
                print(f"  Warning: Gated state '{state_name}' (or {state_name}_wr) not found in merged graph")
                continue

        target_node = merged_graph.nodes[target_node_id]

        # Collect all assignment edges to this target
        assignments = []  # List of (source_node, edge, precedence, condition, from_aspect)

        for edge in list(target_node.incoming_edges):
            if edge.data and edge.data.get('type') == 'assignment':
                precedence = edge.data.get('precedence', 0)  # Base = 0, aspects = 1+
                condition = edge.data.get('enable')  # Conditional write condition (e.g., "exception_taken")
                from_aspect = edge.data.get('from_aspect')
                assignments.append((edge.source, edge, precedence, condition, from_aspect))

        if len(assignments) <= 1:
            # Only one assignment, no mux needed
            continue

        # Check if we have multiple unconditional assignments at the same precedence
        # This happens when multiple instructions write to the same state
        unconditional_assignments = [a for a in assignments if not a[3]]  # a[3] is condition
        conditional_assignments = [a for a in assignments if a[3]]  # Has condition

        if len(unconditional_assignments) > 1 and len(conditional_assignments) == 0:
            # All unconditional at same precedence - let instruction decode handle it
            continue

        # Save all original assignments before filtering (needed to remove all edges later)
        all_original_assignments = assignments.copy()

        # If we have conditional assignments (from aspects) and multiple unconditional ones,
        # keep conditional assignments as priority mux inputs and ONE unconditional as default
        # The unconditional one should be the previously-created instruction mux if it exists
        if len(unconditional_assignments) > 1 and len(conditional_assignments) > 0:
            # Prefer keeping an unconditional assignment from a mux (e.g., pc_wr_mux) over direct assignments
            default_assignment = None
            for a in unconditional_assignments:
                if '_mux' in a[0].id:  # a[0] is source node
                    default_assignment = a
                    break
            if not default_assignment:
                # No mux found, just keep the first unconditional assignment
                default_assignment = unconditional_assignments[0]
            assignments = conditional_assignments + [default_assignment]

        # Sort by precedence (higher first) to build priority mux
        assignments.sort(key=lambda x: x[2], reverse=True)

        # Create multiplexer node
        mux_id = f"{state_name}_gated_mux"
        mux_node = Node(
            node_id=mux_id,
            data={
                'type': 'multiplexer',
                'name': mux_id,
                'display_name': mux_id,
                'operation': 'priority_select',  # Use priority mux (if-else chain)
                'num_inputs': len(assignments),
                'gated_write_mux': True,  # Mark this as a gated write mux
            }
        )
        merged_graph.add_node(mux_node)

        # Remove ALL original assignment edges to the target (not just the ones we're keeping)
        for src, edge, prec, cond, aspect in all_original_assignments:
            merged_graph.remove_edge(edge.id)

        # Add mux inputs from source nodes
        for i, (src, edge, prec, cond, aspect) in enumerate(assignments):
            # Determine edge type: conditional inputs are 'mux_input', unconditional is 'mux_default_input'
            edge_type = 'mux_input' if cond else 'mux_default_input'

            # Create edge from source to mux input
            input_edge = Edge(
                source=src,
                target=mux_node,
                data={
                    'type': edge_type,
                    'input_index': i,  # Use input_index for verilog_generator
                    'original_precedence': prec,
                    'from_aspect': aspect,
                }
            )
            merged_graph.add_edge(input_edge)

            # Create edge for mux select (the condition)
            if cond:
                # Extract condition name from dict if needed
                if isinstance(cond, dict):
                    cond_name = cond.get('name', str(cond))
                else:
                    cond_name = str(cond)

                # Find the node that represents the condition
                # Try both the original name and with instruction prefixes
                cond_nodes = [
                    node for node in merged_graph.nodes.values()
                    if node.id == cond_name or
                       (node.data and node.data.get('name') == cond_name) or
                       node.id.endswith(f"_{cond_name}")  # Handle prefixed names
                ]
                if cond_nodes:
                    select_edge = Edge(
                        source=cond_nodes[0],
                        target=mux_node,
                        data={
                            'type': 'mux_select',
                            'select_index': i,  # Use select_index for verilog_generator
                        }
                    )
                    merged_graph.add_edge(select_edge)
                else:
                    print(f"      Warning: Condition node '{cond_name}' not found in merged graph")
        # Add edge from mux output to target
        output_edge = Edge(
            source=mux_node,
            target=target_node,
            data={'type': 'assignment'}
        )
        merged_graph.add_edge(output_edge)
