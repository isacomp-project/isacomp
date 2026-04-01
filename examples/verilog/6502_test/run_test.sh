#!/bin/bash
# Run 6502 test using iverilog

echo "Running 6502 test..."

# Check if processor exists
if [ ! -f "6502_test.v" ]; then
    echo "ERROR: 6502_test.v not found. Generate processor first."
    exit 1
fi

# Check for test hex file
if [ ! -f "imem.hex" ]; then
    echo "ERROR: imem.hex not found. Run test_all_variants.py --setup-only first."
    exit 1
fi

# Compile with iverilog
echo "Compiling..."
iverilog -g2012 -o sim 6502_test.v cpu_6502_test_tb_verilator.sv 2>&1 | grep -i error || true

if [ ! -f "sim" ]; then
    echo "ERROR: Compilation failed"
    exit 1
fi

# Run simulation (timeout after 120 seconds)
echo "Running simulation..."
timeout 120 vvp sim 2>&1 | tee test_output.log

# Check results
if grep -q "TEST PASSED" test_output.log; then
    echo "✅ 6502 TEST PASSED"
    exit 0
elif grep -q "MISMATCH" test_output.log; then
    echo "❌ 6502 CO-SIMULATION MISMATCH"
    tail -20 test_output.log
    exit 1
else
    echo "❌ 6502 TEST INCOMPLETE"
    tail -20 test_output.log
    exit 1
fi
