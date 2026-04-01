#!/usr/bin/env python3
"""Parse objcopy verilog format and convert to word-addressed hex for $readmemh"""
import sys

def parse_verilog_hex(input_file, output_file):
    """Convert byte-addressed verilog hex to word-addressed hex."""
    memory = {}
    current_addr = 0
    
    with open(input_file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            if line.startswith('@'):
                # Address marker
                current_addr = int(line[1:], 16)
            else:
                # Data bytes
                bytes_data = line.split()
                for byte_str in bytes_data:
                    memory[current_addr] = int(byte_str, 16)
                    current_addr += 1
    
    # Convert to 32-bit words
    words = {}
    for addr in sorted(memory.keys()):
        word_addr = addr // 4
        byte_offset = addr % 4
        
        if word_addr not in words:
            words[word_addr] = [0, 0, 0, 0]
        
        words[word_addr][byte_offset] = memory[addr]
    
    # Write output
    with open(output_file, 'w') as f:
        for addr in sorted(words.keys()):
            # Combine bytes into 32-bit little-endian word
            word_val = (words[addr][3] << 24) | (words[addr][2] << 16) | \
                       (words[addr][1] << 8) | words[addr][0]
            f.write(f'@{addr:08x}\n')
            f.write(f'{word_val:08x}\n')

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: parse_verilog_hex.py <input.hex> <output.hex>")
        sys.exit(1)
    
    parse_verilog_hex(sys.argv[1], sys.argv[2])
