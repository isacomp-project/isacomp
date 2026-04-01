#!/usr/bin/env python3
"""Convert RISC-V ELF file to Verilog hex format for $readmemh"""
import subprocess
import sys
import struct

def elf_to_hex(elf_file, hex_file, word_size=4):
    """Convert ELF to hex format suitable for $readmemh with 32-bit words."""
    # Convert ELF to binary
    bin_file = hex_file + '.bin'
    try:
        subprocess.run(
            ['objcopy', '-O', 'binary', elf_file, bin_file],
            check=True,
            capture_output=True
        )
    except subprocess.CalledProcessError:
        return False
   
    # Read binary and convert to hex words
    try:
        with open(bin_file, 'rb') as f:
            data = f.read()
        
        with open(hex_file, 'w') as f:
            # Write in 32-bit word format
            for i in range(0, len(data), word_size):
                if i + word_size <= len(data):
                    # Read 4 bytes as little-endian 32-bit word
                    word = struct.unpack('<I', data[i:i+word_size])[0]
                    f.write(f'{word:08x}\n')
                else:
                    # Pad last word with zeros if needed
                    remaining = data[i:]
                    padded = remaining + b'\x00' * (word_size - len(remaining))
                    word = struct.unpack('<I', padded)[0]
                    f.write(f'{word:08x}\n')
        
        # Clean up binary file
        subprocess.run(['rm', bin_file], check=True, capture_output=True)
        return True
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return False

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: elf_to_verilog_hex.py <elf_file> <hex_file>")
        sys.exit(1)
    
    success = elf_to_hex(sys.argv[1], sys.argv[2])
    sys.exit(0 if success else 1)
