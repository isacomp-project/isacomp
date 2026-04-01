#!/usr/bin/env python3
"""
Convert HSQ compiler output to hex format for our SUBLEQ processor.

HSQ outputs space-separated decimal SUBLEQ code.
We need to convert it to hex format (one word per line).
"""

import sys
import re

def convert_hsq_to_hex(input_text):
    """Convert HSQ output to hex format."""
    # Split on whitespace and filter out empty strings
    numbers = []
    for line in input_text.strip().split('\n'):
        # Remove any comments or extra whitespace
        line = line.strip()
        if not line:
            continue
        # Split on whitespace and convert to integers
        parts = line.split()
        for part in parts:
            part = part.strip()
            if part:
                try:
                    num = int(part)
                    # Handle negative numbers (two's complement)
                    if num < 0:
                        num = (1 << 32) + num
                    numbers.append(num)
                except ValueError:
                    print(f"Warning: Skipping non-numeric value: {part}", file=sys.stderr)

    return numbers

def main():
    if len(sys.argv) < 2:
        print("Usage: hsq_to_hex.py <input.sq> [-o <output.mem>]")
        print("\nConverts HSQ compiler output (SUBLEQ code) to hex format")
        sys.exit(1)

    input_file = sys.argv[1]

    # Determine output file
    if '-o' in sys.argv:
        output_file = sys.argv[sys.argv.index('-o') + 1]
    else:
        output_file = input_file.replace('.sq', '.mem')

    # Read input
    with open(input_file, 'r') as f:
        input_text = f.read()

    # Convert
    numbers = convert_hsq_to_hex(input_text)

    # Write output
    with open(output_file, 'w') as f:
        for num in numbers:
            f.write(f"{num:08x}\n")

    print(f"Converted {len(numbers)} words to {output_file}")

if __name__ == '__main__':
    main()
