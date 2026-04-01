#!/bin/bash
# Run test for 6502 3-stage pipelined processor

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "==================================="
echo "6502 3-Stage Pipelined Processor Test"
echo "==================================="

# Check if processor exists
if [ ! -f "cpu_6502_pipelined_3stage.v" ]; then
    echo "ERROR: cpu_6502_pipelined_3stage.v not found."
    echo "Run: python3 isa/6502/generators/create_6502_pipeline.py"
    exit 1
fi

# Check if testbench exists
if [ ! -f "simple_tb.sv" ]; then
    echo "ERROR: simple_tb.sv not found."
    exit 1
fi

# Create a simple test program if imem.hex doesn't exist
if [ ! -f "imem.hex" ]; then
    echo "Creating simple test program..."
    python3 - << 'PYTHON'
# Create a simple 6502 test program
# Test: LDA #$42, STA $10, LDA $10, CMP #$42, BEQ pass, JMP fail
# Pass: JMP pass (infinite loop at pass address)
# Fail: JMP fail (infinite loop at fail address)

import struct

# Memory image (64KB)
mem = bytearray(65536)

# Start address
start = 0x0400

# Pass and fail addresses
pass_addr = 0x0420
fail_addr = 0x0430

# Simple test program at 0x0400
prog = [
    0xA9, 0x42,       # 0400: LDA #$42
    0x85, 0x10,       # 0402: STA $10
    0xA5, 0x10,       # 0404: LDA $10
    0xC9, 0x42,       # 0406: CMP #$42
    0xF0, 0x16,       # 0408: BEQ pass ($0420)
    0x4C, 0x30, 0x04, # 040A: JMP fail ($0430)
    # ... padding to pass address
]

# Write program
for i, b in enumerate(prog):
    mem[start + i] = b

# Pass: JMP pass (infinite loop)
mem[pass_addr] = 0x4C
mem[pass_addr + 1] = pass_addr & 0xFF
mem[pass_addr + 2] = (pass_addr >> 8) & 0xFF

# Fail: JMP fail (infinite loop)
mem[fail_addr] = 0x4C
mem[fail_addr + 1] = fail_addr & 0xFF
mem[fail_addr + 2] = (fail_addr >> 8) & 0xFF

# Write as hex file
with open('imem.hex', 'w') as f:
    for i in range(0, 65536, 16):
        f.write(f"@{i:04X} ")
        for j in range(16):
            f.write(f"{mem[i+j]:02X} ")
        f.write("\n")

print(f"Created imem.hex with simple test program")
print(f"Start: 0x{start:04X}")
print(f"Pass:  0x{pass_addr:04X}")
print(f"Fail:  0x{fail_addr:04X}")
PYTHON
fi

# Compile with Icarus Verilog
echo ""
echo "Compiling with Icarus Verilog..."
if ! COMPILE_OUTPUT=$(iverilog -g2012 -o sim cpu_6502_pipelined_3stage.v simple_tb.sv 2>&1); then
    echo "ERROR: Compilation failed"
    echo "$COMPILE_OUTPUT"
    exit 1
fi

# Show only errors from compile output
echo "$COMPILE_OUTPUT" | grep -i "error" || true

echo "Compilation successful!"

# Run simulation
echo ""
echo "Running simulation..."
timeout 30 vvp sim 2>&1 | tee sim_output.log

# Check result
if grep -q "TEST PASSED" sim_output.log; then
    echo ""
    echo "==================================="
    echo "TEST PASSED"
    echo "==================================="
    exit 0
elif grep -q "TEST FAILED" sim_output.log; then
    echo ""
    echo "==================================="
    echo "TEST FAILED"
    echo "==================================="
    exit 1
else
    echo ""
    echo "==================================="
    echo "TEST RESULT UNKNOWN"
    echo "==================================="
    tail -20 sim_output.log
    exit 1
fi
