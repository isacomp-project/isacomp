#!/usr/bin/env python3
"""
Simple SUBLEQ assembler.

SUBLEQ instruction format: a b c
Semantics: *b = *b - *a; if (*b <= 0) pc = c else pc = pc + 3

Supports:
- Labels (label:)
- Comments (# or ;)
- .word directive for data
- .halt pseudo-instruction (jumps to 0xFFFFFFFF)
"""

import sys
import re
from pathlib import Path


class SUBLEQAssembler:
    def __init__(self):
        self.memory = []
        self.labels = {}
        self.pc = 0
        self.fixups = []  # (address, label_name)

    def assemble_file(self, filename):
        """Assemble a SUBLEQ assembly file."""
        with open(filename, 'r') as f:
            lines = f.readlines()

        # First pass: collect labels
        self.pc = 0
        for line_num, line in enumerate(lines, 1):
            line = self._preprocess_line(line)
            if not line:
                continue

            # Check for label
            if ':' in line:
                label, rest = line.split(':', 1)
                label = label.strip()
                if label:
                    if label in self.labels:
                        raise ValueError(f"Line {line_num}: Duplicate label '{label}'")
                    self.labels[label] = self.pc
                line = rest.strip()
                if not line:
                    continue

            # Count instruction/data words
            if line.startswith('.word'):
                self.pc += 1
            elif line.startswith('.halt'):
                self.pc += 3  # Halt is actually a SUBLEQ instruction
            else:
                # Regular SUBLEQ instruction
                parts = line.split()
                if len(parts) == 3:
                    self.pc += 3
                else:
                    raise ValueError(f"Line {line_num}: Invalid instruction '{line}'")

        # Second pass: generate code
        self.pc = 0
        self.memory = []
        for line_num, line in enumerate(lines, 1):
            line = self._preprocess_line(line)
            if not line:
                continue

            # Skip label definition
            if ':' in line:
                _, line = line.split(':', 1)
                line = line.strip()
                if not line:
                    continue

            # Process directives and instructions
            if line.startswith('.word'):
                self._assemble_word(line, line_num)
            elif line.startswith('.halt'):
                self._assemble_halt()
            else:
                self._assemble_instruction(line, line_num)

        # Apply fixups
        for addr, label in self.fixups:
            if label not in self.labels:
                raise ValueError(f"Undefined label: {label}")
            self.memory[addr] = self.labels[label]

        return self.memory

    def _preprocess_line(self, line):
        """Remove comments and whitespace."""
        # Remove comments
        line = re.sub(r'[#;].*', '', line)
        # Strip whitespace
        line = line.strip()
        return line

    def _parse_operand(self, operand, line_num, addr=None):
        """Parse an operand (number or label)."""
        operand = operand.strip()

        # Try to parse as number
        if operand.startswith('0x'):
            return int(operand, 16)
        elif operand.startswith('0b'):
            return int(operand, 2)
        elif operand.isdigit() or (operand.startswith('-') and operand[1:].isdigit()):
            return int(operand)
        else:
            # It's a label - add fixup
            if addr is None:
                addr = len(self.memory)
            self.fixups.append((addr, operand))
            return 0  # Placeholder

    def _assemble_instruction(self, line, line_num):
        """Assemble a SUBLEQ instruction."""
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f"Line {line_num}: Expected 3 operands, got {len(parts)}")

        # Get current memory position for each operand
        addr_a = len(self.memory)
        a = self._parse_operand(parts[0], line_num, addr_a)
        addr_b = len(self.memory) + 1
        b = self._parse_operand(parts[1], line_num, addr_b)
        addr_c = len(self.memory) + 2
        c = self._parse_operand(parts[2], line_num, addr_c)

        self.memory.extend([a, b, c])
        self.pc += 3

    def _assemble_word(self, line, line_num):
        """Assemble a .word directive."""
        match = re.match(r'\.word\s+(.+)', line)
        if not match:
            raise ValueError(f"Line {line_num}: Invalid .word directive")

        addr = len(self.memory)
        value = self._parse_operand(match.group(1), line_num, addr)
        self.memory.append(value)
        self.pc += 1

    def _assemble_halt(self):
        """Assemble a .halt pseudo-instruction."""
        # Jump to 0xFFFFFFFF to halt
        self.memory.extend([0, 0, 0xFFFFFFFF])
        self.pc += 3

    def write_hex(self, filename):
        """Write memory to Verilog hex format."""
        with open(filename, 'w') as f:
            for i, word in enumerate(self.memory):
                # Handle negative numbers (two's complement)
                if word < 0:
                    word = (1 << 32) + word
                f.write(f"{word:08x}\n")


def main():
    if len(sys.argv) < 2:
        print("Usage: subleq_asm.py <input.s> [-o <output.mem>]")
        print("\nSUBLEQ Assembly Format:")
        print("  a b c         ; SUBLEQ instruction: *b = *b - *a; if (*b <= 0) pc = c")
        print("  label:        ; Define label at current address")
        print("  .word N       ; Place word in memory")
        print("  .halt         ; Halt execution")
        print("  # comment     ; Comment")
        sys.exit(1)

    input_file = sys.argv[1]

    # Determine output file
    if '-o' in sys.argv:
        output_file = sys.argv[sys.argv.index('-o') + 1]
    else:
        output_file = Path(input_file).with_suffix('.mem')

    try:
        assembler = SUBLEQAssembler()
        memory = assembler.assemble_file(input_file)

        print(f"Assembled {len(memory)} words")
        print(f"Labels: {assembler.labels}")

        assembler.write_hex(output_file)
        print(f"Written to {output_file}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
