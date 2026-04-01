#!/usr/bin/env python3
"""
Extract individual instructions from ILA JSON exports.

This demonstrates that ILA models can be split instruction-by-instruction,
creating standalone JSON files for each instruction.
"""

import json
import sys
from pathlib import Path
from typing import Dict, Set, Any


def collect_referenced_expressions(ast_array: list, expr_id: int, visited: Set[int]) -> None:
    """Recursively collect all expressions referenced by expr_id."""
    if expr_id in visited:
        return
    visited.add(expr_id)

    # Find the expression in AST array
    expr = None
    for e in ast_array:
        if e.get('i') == expr_id:
            expr = e
            break

    if not expr:
        return

    # If it's an operation, recursively collect arguments
    if expr.get('u') == 3:  # EXPR_UID_OP
        for arg_id in expr.get('a', []):
            collect_referenced_expressions(ast_array, arg_id, visited)


def extract_instruction(ila_json_file: str, instruction_name: str, output_file: str = None) -> Dict[str, Any]:
    """
    Extract a single instruction from an ILA JSON file.

    Creates a minimal JSON containing:
    - Only the states needed by this instruction
    - Only the AST expressions used by this instruction
    - Just this one instruction

    Args:
        ila_json_file: Path to full ILA JSON export
        instruction_name: Name of instruction to extract (e.g., "ADD", "BEQ")
        output_file: Optional output file path

    Returns:
        Dictionary with extracted instruction data
    """
    # Load full ILA
    with open(ila_json_file, 'r') as f:
        full_ila = json.load(f)

    ast_array = full_ila.get('a', [])
    top_ila = full_ila.get('t', {})

    # Find the instruction
    instr_data = None
    for instr in top_ila.get('instr', []):
        if instr.get('n') == instruction_name:
            instr_data = instr
            break

    if not instr_data:
        available = [i.get('n') for i in top_ila.get('instr', [])]
        raise ValueError(f"Instruction '{instruction_name}' not found. Available: {available}")

    # Collect all expression IDs used by this instruction
    used_expr_ids = set()

    # Add decode expression
    decode_id = instr_data.get('d')
    if decode_id:
        collect_referenced_expressions(ast_array, decode_id, used_expr_ids)

    # Add all update expressions
    for state_name, update_id in instr_data.get('u', {}).items():
        collect_referenced_expressions(ast_array, update_id, used_expr_ids)

    # Add state expressions themselves
    for state_id in top_ila.get('s', []):
        used_expr_ids.add(state_id)

    # Filter AST array to only used expressions
    filtered_ast = [e for e in ast_array if e.get('i') in used_expr_ids]

    # Create minimal ILA with just this instruction
    minimal_ila = {
        'a': filtered_ast,
        'f': full_ila.get('f'),  # Keep function definitions
        't': {
            'n': f"{top_ila.get('n', 'ila')}_{instruction_name}",
            's': top_ila.get('s', []),  # Keep all states
            'i': top_ila.get('i', []),  # Keep inputs
            'v': top_ila.get('v'),      # Keep valid expression
            'init': top_ila.get('init', []),
            'instr': [instr_data],      # Just this instruction
            'c': []                      # No children
        }
    }

    # Write to output file if specified
    if output_file:
        with open(output_file, 'w') as f:
            json.dump(minimal_ila, f, indent=2)
        print(f"Extracted '{instruction_name}' to: {output_file}")
        print(f"  Original AST size: {len(ast_array)} expressions")
        print(f"  Filtered AST size: {len(filtered_ast)} expressions")
        print(f"  Reduction: {100*(1-len(filtered_ast)/len(ast_array)):.1f}%")

    return minimal_ila


def list_instructions(ila_json_file: str) -> None:
    """List all instructions in an ILA JSON file."""
    with open(ila_json_file, 'r') as f:
        ila = json.load(f)

    top_ila = ila.get('t', {})
    instructions = top_ila.get('instr', [])

    print(f"ILA Model: {top_ila.get('n', 'unknown')}")
    print(f"Total Instructions: {len(instructions)}\n")

    for i, instr in enumerate(instructions, 1):
        name = instr.get('n', 'unnamed')
        decode_id = instr.get('d', '?')
        num_updates = len(instr.get('u', {}))
        print(f"{i:2}. {name:10} (decode: {decode_id:4}, updates: {num_updates:2} states)")


def extract_all_instructions(ila_json_file: str, output_dir: str) -> None:
    """Extract all instructions to individual JSON files."""
    with open(ila_json_file, 'r') as f:
        ila = json.load(f)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    top_ila = ila.get('t', {})
    model_name = top_ila.get('n', 'ila')
    instructions = [i.get('n') for i in top_ila.get('instr', [])]

    print(f"Extracting {len(instructions)} instructions from {model_name}...")
    print()

    total_original = len(ila.get('a', []))
    total_extracted = 0

    for instr_name in instructions:
        output_file = output_path / f"{model_name}_{instr_name.lower()}.json"
        result = extract_instruction(ila_json_file, instr_name, str(output_file))
        total_extracted += len(result['a'])

    print(f"\nSummary:")
    print(f"  Extracted: {len(instructions)} instructions")
    print(f"  Output directory: {output_dir}")
    print(f"  Average AST size: {total_extracted // len(instructions)} expressions/instruction")
    print(f"  vs Original: {total_original} expressions total")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Extract individual instructions from ILA JSON')
    parser.add_argument('ila_file', help='ILA JSON file')
    parser.add_argument('--list', '-l', action='store_true', help='List all instructions')
    parser.add_argument('--instruction', '-i', help='Instruction name to extract')
    parser.add_argument('--output', '-o', help='Output file for extracted instruction')
    parser.add_argument('--all', '-a', help='Extract all instructions to directory')

    args = parser.parse_args()

    if args.list:
        list_instructions(args.ila_file)
    elif args.all:
        extract_all_instructions(args.ila_file, args.all)
    elif args.instruction:
        output = args.output or f"{args.instruction.lower()}.json"
        extract_instruction(args.ila_file, args.instruction, output)
    else:
        parser.print_help()
