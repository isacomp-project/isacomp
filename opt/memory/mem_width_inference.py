"""Width inference for mem-declared memories."""

from core.resource_graph import ResourceGraph, Node
from typing import Dict, Optional, List, Tuple


def infer_mem_widths(graph: ResourceGraph) -> Dict[str, int]:
    """Infer data widths for all mem declarations.

    Strategy:
    1. Find all mem base nodes (type='mem', width_inferred=True)
    2. Find all access nodes for each memory
    3. Determine width from:
       - Explicit width specifiers: dmem[addr]<7:0> (future feature)
       - Assignment context: byte_var = dmem[addr] (infer from byte_var)
       - Default to 32 bits if ambiguous
    4. Return mapping of mem_name -> inferred_width

    Args:
        graph: The ResourceGraph to analyze

    Returns:
        Dictionary mapping memory name to inferred width
    """
    mem_widths = {}

    # Find all mem declarations (type is 'isa_state mem')
    mem_nodes = [n for n in graph.nodes.values()
                 if n.data.get('type') == 'isa_state mem' and n.data.get('width_inferred')]

    for mem_node in mem_nodes:
        mem_name = mem_node.data['name']
        access_widths = []

        # Find all access nodes for this memory
        access_nodes = _find_memory_access_nodes(graph, mem_name)

        # Validate that vars used with this mem have explicit widths
        _validate_mem_access_vars(graph, mem_name, access_nodes)

        for access_node in access_nodes:
            width = _infer_access_width(graph, access_node)
            if width:
                access_widths.append(width)
                # Track on memory node for later merger use
                if 'access_widths' not in mem_node.data:
                    mem_node.data['access_widths'] = []
                mem_node.data['access_widths'].append(width)

        # Use maximum observed width, or default to 32
        inferred_width = max(access_widths) if access_widths else 32
        mem_node.data['bit_width'] = inferred_width
        mem_widths[mem_name] = inferred_width

    return mem_widths


def _validate_mem_access_vars(graph: ResourceGraph, mem_name: str,
                              access_nodes: List[Node]) -> None:
    """Validate that vars used with mem accesses have explicit widths.

    Args:
        graph: The ResourceGraph
        mem_name: Name of the memory being accessed
        access_nodes: List of array_access nodes for this memory

    Raises:
        ValueError: If a var without explicit width is used with mem
    """
    errors = []

    for access_node in access_nodes:
        access_mode = access_node.data.get('access_mode', 'read')

        if access_mode == 'read':
            # Check vars that receive data from memory
            for edge in access_node.outgoing_edges:
                if edge.data.get('type') == 'assignment':
                    target = edge.target
                    var_name = _get_var_name_from_node(target)
                    if var_name:
                        base_var = graph.nodes.get(var_name)
                        if base_var and base_var.data.get('type') == 'var':
                            if not base_var.data.get('width_explicit'):
                                errors.append(
                                    f"Variable '{var_name}' is used to read from memory '{mem_name}' "
                                    f"but has no explicit width. Use: var[N:0] {var_name}; "
                                    f"to specify the access width."
                                )
        else:  # write
            # Check vars that provide data to memory
            for edge in access_node.incoming_edges:
                if edge.data.get('type') == 'assignment':
                    source = edge.source
                    var_name = _get_var_name_from_node(source)
                    if var_name:
                        base_var = graph.nodes.get(var_name)
                        if base_var and base_var.data.get('type') == 'var':
                            if not base_var.data.get('width_explicit'):
                                errors.append(
                                    f"Variable '{var_name}' is used to write to memory '{mem_name}' "
                                    f"but has no explicit width. Use: var[N:0] {var_name}; "
                                    f"to specify the access width."
                                )

    if errors:
        error_msg = "\n".join(errors)
        raise ValueError(f"Memory access width validation failed:\n{error_msg}")


def _get_var_name_from_node(node: Node) -> Optional[str]:
    """Extract var name from a node, handling identifiers and bit slices.

    Args:
        node: The node to extract var name from

    Returns:
        The var name if found, None otherwise
    """
    node_type = node.data.get('type')

    if node_type == 'identifier' or node_type == 'var':
        return node.data.get('name')

    if node_type == 'bit_slice':
        # For bit slices, get the target's name
        expr = node.data.get('expression', {})
        target_expr = expr.get('target', {})
        if target_expr.get('type') == 'identifier':
            return target_expr.get('name')

    # For other node types, check if there's a name field
    return node.data.get('name')


def _find_memory_access_nodes(graph: ResourceGraph, mem_name: str) -> list:
    """Find all array_access nodes that access the given memory.

    Args:
        graph: The ResourceGraph to search
        mem_name: Name of the memory to find accesses for

    Returns:
        List of array_access nodes
    """
    access_nodes = []

    for node in graph.nodes.values():
        if node.data.get('type') == 'array_access':
            # Check if this accesses our memory by examining the expression
            expr = node.data.get('expression', {})
            array_expr = expr.get('target', {})

            # The array expression should be an identifier with the memory name
            if array_expr.get('type') == 'identifier' and array_expr.get('name') == mem_name:
                access_nodes.append(node)

    return access_nodes


def _infer_access_width(graph: ResourceGraph, access_node: Node) -> Optional[int]:
    """Infer width of a single memory access from context.

    For loads (reads):
        Look at outgoing assignment edges to see what the data is assigned to

    For stores (writes):
        Look at incoming assignment edges to see what data is being written

    Args:
        graph: The ResourceGraph
        access_node: The array_access node

    Returns:
        Inferred width in bits, or None if cannot be determined
    """
    # Check for explicit width annotation (future feature)
    if access_node.data.get('access_width'):
        return access_node.data['access_width']

    access_mode = access_node.data.get('access_mode', 'read')
    widths = []

    if access_mode == 'read':
        # For reads, look at what the data is assigned to
        # Collect ALL assignment widths and return maximum
        for edge in access_node.outgoing_edges:
            if edge.data.get('type') == 'assignment':
                target = edge.target
                width = _get_node_width(graph, target)
                if width:
                    widths.append(width)
    else:
        # For writes, look at what data is being assigned from
        # Collect ALL assignment widths and return maximum
        for edge in access_node.incoming_edges:
            if edge.data.get('type') == 'assignment':
                source = edge.source
                width = _get_node_width(graph, source)
                if width:
                    widths.append(width)

    # Return maximum width found, or None if no widths found
    return max(widths) if widths else None


def _get_node_width(graph: ResourceGraph, node: Node) -> Optional[int]:
    """Get the bit width of a node if it can be determined.

    Args:
        graph: The ResourceGraph
        node: The node to get width for

    Returns:
        Width in bits, or None if cannot be determined
    """
    # Check if node already has width metadata
    if node.data.get('bit_width'):
        return node.data['bit_width']

    if node.data.get('width'):
        return node.data['width']

    # Check based on node type
    node_type = node.data.get('type')

    # For var nodes with explicit width declaration
    if node_type == 'var':
        if node.data.get('width_explicit'):
            return node.data.get('bit_width')
        # If var width not explicit, try to look it up from base node
        var_name = node.data.get('name')
        if var_name and var_name in graph.nodes:
            base_node = graph.nodes[var_name]
            if base_node.data.get('width_explicit'):
                return base_node.data.get('bit_width')
        return None

    if node_type == 'sized_literal':
        return node.data.get('width')

    if node_type == 'bit_slice':
        # Calculate width from bit range
        bit_range = node.data.get('expression', {}).get('range')
        if bit_range:
            high, low = bit_range
            if isinstance(high, int) and isinstance(low, int):
                return high - low + 1

    if node_type == 'concatenation':
        # Sum widths of all concatenated expressions
        expr = node.data.get('expression', {})
        expressions = expr.get('parts', [])
        total_width = 0
        for sub_expr in expressions:
            # Would need to recursively get width - simplified for now
            pass

    if node_type == 'repetition':
        # Count * width of repeated expression
        count = node.data.get('count')
        expr = node.data.get('expression', {}).get('expression')
        # Would need to get width of inner expression - simplified for now
        pass

    # For isa_state nodes
    if node_type == 'isa_state':
        return node.data.get('bit_width')

    # Cannot determine width
    return None
