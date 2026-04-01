#!/usr/bin/env python3
"""
Resolve parameter expressions in resource graphs to concrete values.

Since pyslang elaborates parameters during compilation, we have access to
concrete parameter values. This pass evaluates any symbolic parameter
expressions in the graph (like bit slices, array bounds) to their numeric values.
"""

import re
from .resource_graph import ResourceGraph

def resolve_parameter_expressions(graph: ResourceGraph) -> None:
    """
    Resolve parameter expressions in graph to concrete values.

    Args:
        graph: ResourceGraph with potential parameter expressions
    """
    # Build parameter value map
    params = {}
    for node_id, node in graph.nodes.items():
        if node.data.get('node_type') == 'parameter':
            param_name = node_id
            param_value = node.data.get('value', node_id)
            params[param_name] = param_value
            print(f"[PARAM_RESOLVE] {param_name} = {param_value}")

    # Resolve expressions in node data
    for node_id, node in graph.nodes.items():
        _resolve_in_node_data(node.data, params)

def _resolve_in_node_data(data: dict, params: dict) -> None:
    """Recursively resolve parameter expressions in node data."""

    # Resolve bit slices
    if 'bit_slice' in data and isinstance(data['bit_slice'], dict):
        slice_info = data['bit_slice']
        if 'high' in slice_info:
            slice_info['high'] = _eval_param_expr(slice_info['high'], params)
        if 'low' in slice_info:
            slice_info['low'] = _eval_param_expr(slice_info['low'], params)

    # Resolve array dimensions
    for key in ['array_left', 'array_right', 'bit_width']:
        if key in data and isinstance(data[key], str):
            data[key] = _eval_param_expr(data[key], params)

def _eval_param_expr(expr, params: dict):
    """
    Evaluate a parameter expression to a concrete value.

    Handles expressions like:
    - "($signed(width) Subtract $signed(1))"
    - "width"
    - "32"
    """
    if not isinstance(expr, str):
        return expr

    # If it's already a number, return it
    try:
        return int(expr)
    except ValueError:
        pass

    # Simple parameter reference
    if expr in params:
        val = params[expr]
        try:
            return int(val)
        except:
            return val

    # Parameter expression - need to evaluate
    # Replace parameter names with their values
    expr_eval = expr
    for param_name, param_value in params.items():
        # Handle $signed(param) wrappers
        expr_eval = expr_eval.replace(f'$signed({param_name})', str(param_value))
        expr_eval = expr_eval.replace(param_name, str(param_value))

    # Replace operations
    expr_eval = expr_eval.replace('Subtract', '-')
    expr_eval = expr_eval.replace('Add', '+')
    expr_eval = expr_eval.replace('Multiply', '*')
    expr_eval = expr_eval.replace('Divide', '/')

    # Remove extra parentheses and whitespace
    expr_eval = expr_eval.replace('(', '').replace(')', '').strip()

    # Try to evaluate as Python expression
    try:
        result = eval(expr_eval, {"__builtins__": {}}, {})
        return int(result)
    except:
        # If evaluation fails, return original
        print(f"[PARAM_RESOLVE] Warning: Could not evaluate '{expr}' -> '{expr_eval}'")
        return expr

if __name__ == "__main__":
    # Test with SERV
    from frontends.verilog import parse_verilog_file

    print("Parsing SERV...")
    graph = parse_verilog_file('examples/verilog/serv/serv_simple.v', top_module='serv_simple')

    print(f"\nBefore parameter resolution:")
    print(f"  Total nodes: {len(graph.nodes)}")

    # Find a node with parameter expressions
    for node_id, node in list(graph.nodes.items())[:100]:
        if 'bit_slice' in node.data and isinstance(node.data['bit_slice'], dict):
            high = node.data['bit_slice'].get('high', '')
            if 'Subtract' in str(high) or 'signed' in str(high):
                print(f"  Example node: {node_id[:50]}")
                print(f"    Before: high={high}")

    print(f"\nResolving parameters...")
    resolve_parameter_expressions(graph)

    print(f"\nAfter parameter resolution:")
    # Check the same nodes
    for node_id, node in list(graph.nodes.items())[:100]:
        if 'bit_slice' in node.data and isinstance(node.data['bit_slice'], dict):
            high = node.data['bit_slice'].get('high', '')
            if isinstance(high, int):
                print(f"  Example node: {node_id[:50]}")
                print(f"    After: high={high} (resolved!)")
                break
