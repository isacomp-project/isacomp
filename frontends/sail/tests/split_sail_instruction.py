#!/usr/bin/env python3
"""
Script to extract a single instruction from SAIL per-instruction JSON.
Usage: python split_sail_instruction.py <pattern_name> [json_file]
"""

import json
import sys

def extract_instruction(pattern_name, json_file='sail/ocaml_sail_extractor/rtype_multiplexer.json'):
    """Extract a single instruction pattern from the per-instruction JSON."""
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    if pattern_name not in data:
        print(f"Error: Pattern '{pattern_name}' not found in {json_file}")
        print(f"\nAvailable patterns ({len(data)} total):")
        for i, key in enumerate(sorted(data.keys())[:30]):
            print(f"  {key}")
        if len(data) > 30:
            print(f"  ... and {len(data) - 30} more")
        sys.exit(1)
    
    pattern = data[pattern_name]
    print(f"Extracted pattern '{pattern_name}':")
    print(f"  Nodes: {len(pattern.get('nodes', []))}")
    print(f"  Edges: {len(pattern.get('edges', []))}")
    
    return pattern

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python split_sail_instruction.py <pattern_name> [json_file]")
        print("\nExample: python split_sail_instruction.py C_ADD")
        sys.exit(1)
    
    pattern_name = sys.argv[1]
    json_file = sys.argv[2] if len(sys.argv) > 2 else 'sail/ocaml_sail_extractor/rtype_multiplexer.json'
    
    pattern = extract_instruction(pattern_name, json_file)
    
    # Optionally save to a file
    output_file = f"{pattern_name.lower()}_sail.json"
    output_data = {pattern_name: pattern}
    with open(output_file, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"  Saved to: {output_file}")
