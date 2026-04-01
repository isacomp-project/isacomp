#!/bin/bash
# Run a single RISC-V test for post-egress cosimulation
# Usage: run_riscv_test.sh <test_name>
# Example: run_riscv_test.sh add

set -e

if [ $# -ne 1 ]; then
    echo "Usage: $0 <test_name>"
    echo "Example: $0 add"
    exit 1
fi

TEST_NAME="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RISCV_TESTS_DIR="$SCRIPT_DIR/../../../isa/riscv32/riscv-tests/isa"
TEST_BASE="${RISCV_TESTS_DIR}/rv32ui-isacomp-${TEST_NAME}"
TEST_HEX="${TEST_BASE}.hex"
TEST_ADDRS="${TEST_BASE}.addrs"

# Check test files exist
if [ ! -f "$TEST_HEX" ]; then
    echo "ERROR: Test hex file not found: $TEST_HEX"
    echo "Run build_riscv_tests.sh first"
    exit 1
fi

if [ ! -f "$TEST_ADDRS" ]; then
    echo "ERROR: Test addresses file not found: $TEST_ADDRS"
    echo "Run build_riscv_tests.sh first"
    exit 1
fi

# Read pass/fail addresses from .addrs file
read PASS_ADDR FAIL_ADDR < "$TEST_ADDRS"

# Convert hex to decimal for GHDL generics
PASS_PC=$((16#$PASS_ADDR))
FAIL_PC=$((16#$FAIL_ADDR))

# Convert Intel HEX to simple hex format for GHDL hread
python3 -c "
data = {}
with open('$TEST_HEX', 'r') as f:
    for line in f:
        line = line.strip()
        if not line.startswith(':'):
            continue
        byte_count = int(line[1:3], 16)
        address = int(line[3:7], 16)
        record_type = int(line[7:9], 16)
        if record_type == 0:  # Data record
            for i in range(byte_count):
                byte_val = int(line[9+i*2:11+i*2], 16)
                data[address + i] = byte_val
        elif record_type == 1:  # EOF
            break

if not data:
    exit(1)

# Write word-addressed hex file (one word per line for GHDL hread)
with open('imem.mem', 'w') as f:
    max_addr = max(data.keys())
    max_word = (max_addr // 4) + 1
    for word_idx in range(max(1024, max_word)):
        word = 0
        for byte_offset in range(4):
            addr = word_idx * 4 + byte_offset
            if addr in data:
                word |= data[addr] << (byte_offset * 8)
        f.write(f'{word:08x}\n')
"

# Run cosimulation with pass/fail PCs
OUTPUT=$(./run_post_egress_cosim.sh $PASS_PC $FAIL_PC 2>&1)

# Check for PASS/FAIL in output
if echo "$OUTPUT" | grep -q "RESULT: PASS"; then
    exit 0
elif echo "$OUTPUT" | grep -q "RESULT: FAIL"; then
    exit 1
elif echo "$OUTPUT" | grep -q "ghdl:error"; then
    echo "$OUTPUT" | head -50
    exit 1
else
    echo "$OUTPUT" | tail -30
    exit 1
fi
