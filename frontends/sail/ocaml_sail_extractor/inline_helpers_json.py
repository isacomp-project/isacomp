#!/usr/bin/env python3
"""
Post-process SAIL JSON to inline helper functions.

This simulates what the OCaml extractor does with function inlining,
but operates on already-extracted JSON files.
"""

import json
import sys
from copy import deepcopy

def inline_function_in_json(graph_data, helpers):
    """Inline helper function calls in a graph."""

    nodes = graph_data['nodes']
    edges = graph_data['edges']

    # Find nodes that call wX_bits
    nodes_to_inline = []
    for node in nodes:
        node_data = node.get('data', {})
        if node_data.get('type') == 'operation' and node_data.get('operator') == 'wX_bits':
            nodes_to_inline.append(node)

    if not nodes_to_inline:
        print("  No wX_bits operations found to inline")
        return graph_data

    print(f"  Found {len(nodes_to_inline)} wX_bits operations to inline")

    # Get the _wX helper (wX_bits just calls wX)
    wX_helper = helpers.get('_wX')
    if not wX_helper:
        print("  ERROR: _wX helper not found!")
        return graph_data

    print(f"  _wX helper has {len(wX_helper['nodes'])} nodes")

    # For each wX_bits operation, inline the _wX helper
    node_id_counter = max([int(n['id'][1:]) for n in nodes]) + 1
    edge_id_counter = max([int(e['id'][1:]) for e in edges]) + 1

    new_nodes = []
    new_edges = []
    nodes_to_remove = []

    for wX_node in nodes_to_inline:
        print(f"\n  Inlining wX_bits at node {wX_node['id']}")

        # Find the arguments to wX_bits
        # wX_bits has operand edges from: register index and value
        operand_edges = [e for e in edges if e['target'] == wX_node['id'] and
                        e['data'].get('type') == 'operand']

        if len(operand_edges) != 2:
            print(f"    WARNING: Expected 2 operands, found {len(operand_edges)}")
            continue

        # Clone the _wX helper graph
        id_mapping = {}
        for helper_node in wX_helper['nodes']:
            new_id = f"n{node_id_counter}"
            node_id_counter += 1
            id_mapping[helper_node['id']] = new_id

            cloned_node = deepcopy(helper_node)
            cloned_node['id'] = new_id
            new_nodes.append(cloned_node)

        for helper_edge in wX_helper['edges']:
            new_edge = deepcopy(helper_edge)
            new_edge['id'] = f"e{edge_id_counter}"
            edge_id_counter += 1
            new_edge['source'] = id_mapping[helper_edge['source']]
            new_edge['target'] = id_mapping[helper_edge['target']]
            new_edges.append(new_edge)

        # Find parameter nodes in the inlined graph (r and v)
        param_nodes = {}
        for helper_node in wX_helper['nodes']:
            node_data = helper_node.get('data', {})
            display_name = node_data.get('display_name')
            if display_name in ['r', 'v'] and node_data.get('type') == 'var':
                new_id = id_mapping[helper_node['id']]
                param_nodes[display_name] = new_id

        print(f"    Found parameters: {list(param_nodes.keys())}")

        # Redirect edges from parameters to actual arguments
        for param_name, param_id in param_nodes.items():
            # Find the corresponding argument
            # r = index (first operand), v = value (second operand)
            arg_edges = sorted(operand_edges, key=lambda e: e['id'])
            arg_node_id = arg_edges[0]['source'] if param_name == 'r' else arg_edges[1]['source']

            # Redirect all edges FROM parameter TO arg_node
            for edge in new_edges:
                if edge['source'] == param_id:
                    edge['source'] = arg_node_id

        # Mark the wX_bits node for removal
        nodes_to_remove.append(wX_node['id'])

        print(f"    Inlined {len(id_mapping)} nodes")

    # Remove old wX_bits nodes and their edges
    nodes = [n for n in nodes if n['id'] not in nodes_to_remove]
    edges = [e for e in edges if e['source'] not in nodes_to_remove and
             e['target'] not in nodes_to_remove]

    # Add inlined nodes and edges
    nodes.extend(new_nodes)
    edges.extend(new_edges)

    return {'nodes': nodes, 'edges': edges}

def process_json_file(input_path, output_path):
    """Process a SAIL JSON file to inline helpers."""

    print(f"Loading {input_path}...")
    with open(input_path, 'r') as f:
        data = json.load(f)

    # Extract helpers
    helpers = {k: v for k, v in data.items() if k.startswith('_')}
    print(f"Found {len(helpers)} helper functions: {list(helpers.keys())}")

    # Process each instruction pattern
    for key, value in data.items():
        if key.startswith('_'):
            continue  # Skip helpers

        print(f"\nProcessing {key}...")
        data[key] = inline_function_in_json(value, helpers)

    # Write output
    print(f"\nWriting {output_path}...")
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)

    print("Done!")

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: inline_helpers_json.py <input.json> <output.json>")
        sys.exit(1)

    process_json_file(sys.argv[1], sys.argv[2])
