#!/usr/bin/env python3
"""
Fix the AES IntermediateRound decode condition in the JSON.
Changes: round == 1  ->  (round > 0) && (round <= 9)
"""

import json
import sys

def find_node_by_id(nodes, node_id):
    """Find a node by its id in the nodes list."""
    for node in nodes:
        if isinstance(node, dict) and node.get('i') == node_id:
            return node
    return None

def create_comparison_node(node_id, op_uid, var_ref, const_val, bit_width=4):
    """Create a comparison node."""
    return {
        'u': 3,  # Expression
        'i': node_id,
        'o': op_uid,  # operation
        'a': [var_ref, const_val],
        'p': []
    }

def create_const_node(node_id, value, bit_width=4):
    """Create a constant node."""
    return {
        'u': 2,  # Constant
        'i': node_id,
        's': {'u': 2, 'w': bit_width},
        'v': {'v': value}
    }

def create_and_node(node_id, left_ref, right_ref):
    """Create an AND node."""
    return {
        'u': 3,  # Expression
        'i': node_id,
        'o': 4,  # AND operation (OP_AND = 4)
        'a': [left_ref, right_ref],
        'p': []
    }

def fix_decode_condition(input_file, output_file):
    """Fix the decode condition for IntermediateRound."""

    with open(input_file, 'r') as f:
        ila = json.load(f)

    # Find the round state variable ID
    round_id = None
    for state_id in ila['t']['s']:
        node = find_node_by_id(ila['a'], state_id)
        if node and node.get('n') == 'round':
            round_id = state_id
            break

    if not round_id:
        print("Error: Could not find 'round' state variable")
        return False

    print(f"Found round state ID: {round_id}")

    # Find IntermediateRound instruction
    intermediate_instr = None
    for instr in ila['t']['instr']:
        if instr['n'] == 'IntermediateRound':
            intermediate_instr = instr
            break

    if not intermediate_instr:
        print("Error: Could not find IntermediateRound instruction")
        return False

    old_decode_id = intermediate_instr['d']
    print(f"Old decode node ID: {old_decode_id}")

    # Find the maximum node ID to generate new unique IDs
    max_id = max(node.get('i', 0) for node in ila['a'] if isinstance(node, dict))
    print(f"Max existing node ID: {max_id}")

    # Create new nodes for the corrected decode: (round > 0) && (round <= 9)
    # We need: Ugt(round, 0) & Ule(round, 9)
    # Note: Ule(round, 9) = (round == 9) | (round < 9)

    # Node IDs
    const_0_id = max_id + 1
    const_9_id = max_id + 2
    ugt_id = max_id + 3           # round > 0
    eq_9_id = max_id + 4          # round == 9
    ult_9_id = max_id + 5         # round < 9
    ule_9_id = max_id + 6         # (round == 9) | (round < 9)
    and_id = max_id + 7           # (round > 0) && (round <= 9)

    # Create constant 0
    const_0 = create_const_node(const_0_id, 0, 4)

    # Create constant 9
    const_9 = create_const_node(const_9_id, 9, 4)

    # Create: round > 0 (Ugt is op 17)
    ugt_node = create_comparison_node(ugt_id, 17, round_id, const_0_id)

    # Create: round == 9 (EQ is op 13)
    eq_9_node = create_comparison_node(eq_9_id, 13, round_id, const_9_id)

    # Create: round < 9 (ULT is op 16)
    ult_9_node = create_comparison_node(ult_9_id, 16, round_id, const_9_id)

    # Create: (round == 9) | (round < 9) - this is Ule(round, 9) (OR is op 5)
    ule_9_node = {
        'u': 3,  # Expression
        'i': ule_9_id,
        'o': 5,  # OR operation
        'a': [eq_9_id, ult_9_id],
        'p': []
    }

    # Create: (round > 0) && ((round == 9) | (round < 9))
    and_node = create_and_node(and_id, ugt_id, ule_9_id)

    # Add new nodes to the array
    ila['a'].extend([const_0, const_9, ugt_node, eq_9_node, ult_9_node, ule_9_node, and_node])

    # Update the decode reference
    intermediate_instr['d'] = and_id

    print(f"New decode node ID: {and_id}")
    print("Decode condition changed from: round == 1")
    print("                           to: (round > 0) && (round <= 9)")

    # Save the corrected JSON
    with open(output_file, 'w') as f:
        json.dump(ila, f, separators=(',', ':'))

    print(f"\nCorrected ILA saved to: {output_file}")
    return True

if __name__ == '__main__':
    input_file = 'test_data/aes128_function_lut.json'
    output_file = 'test_data/aes128_function_lut_fixed.json'

    if fix_decode_condition(input_file, output_file):
        print("\n✓ Successfully fixed decode condition")
        sys.exit(0)
    else:
        print("\n✗ Failed to fix decode condition")
        sys.exit(1)
