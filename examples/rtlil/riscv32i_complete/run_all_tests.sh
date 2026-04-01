#!/bin/bash
# Run all riscv-tests through CXXRTL simulation
# Mirrors the Verilog backend's run_all_tests.sh

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

MODULE_NAME=${MODULE_NAME:-riscv32i_complete}

# Step 1: Compile CXXRTL simulation binary
echo "Compiling CXXRTL simulation..."
bash compile_${MODULE_NAME}.sh
if [ $? -ne 0 ]; then
    echo "ERROR: CXXRTL compilation failed!"
    exit 1
fi

TEST_CMD="./${MODULE_NAME}_sim"

# Function to convert Intel HEX to word-addressed hex
convert_ihex() {
    local input=$1
    local output=$2
    python3 -c "
import sys
data = {}
with open('$input', 'r') as f:
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
    sys.exit(1)
max_addr = max(data.keys())
max_word = (max_addr // 4) + 1

with open('$output', 'w') as f:
    for word_idx in range(max(1024, max_word)):
        word = 0
        addr = word_idx * 4
        for byte_offset in range(4):
            byte_addr = addr + byte_offset
            if byte_addr in data:
                word |= data[byte_addr] << (byte_offset * 8)
        f.write(f'{word:08x}\n')
"
}

TESTS="add addi sub lui auipc and andi or ori xor xori sll slli srl srli sra srai slt slti sltu sltiu beq bne blt bltu bge bgeu jal jalr lw lh lhu lb lbu sw sh sb"

PASS=0
FAIL=0
SKIP=0

for test in $TESTS; do
    echo -n "Testing $test... "

    TEST_BASE="../../../../isa/riscv32/riscv-tests/isa/rv32ui-isacomp-$test"

    if [ ! -f "$TEST_BASE.hex" ]; then
        echo "SKIP (no hex file)"
        SKIP=$((SKIP + 1))
        continue
    fi

    if [ ! -f "$TEST_BASE.addrs" ]; then
        echo "SKIP (no addrs file)"
        SKIP=$((SKIP + 1))
        continue
    fi

    # Get pass/fail addresses
    read PASS_ADDR FAIL_ADDR < "$TEST_BASE.addrs"

    # Convert Intel HEX to word-addressed format
    convert_ihex "$TEST_BASE.hex" "umem.hex"

    # Run test
    RESULT=$(timeout 10 $TEST_CMD +pass_addr=$PASS_ADDR +fail_addr=$FAIL_ADDR +hex=umem.hex 2>&1)
    EXIT_CODE=$?

    if echo "$RESULT" | grep -q "TEST PASSED"; then
        echo "PASS"
        PASS=$((PASS + 1))
    elif echo "$RESULT" | grep -q "TEST FAILED"; then
        echo "FAIL"
        FAIL=$((FAIL + 1))
    elif [ $EXIT_CODE -eq 124 ]; then
        echo "TIMEOUT"
        FAIL=$((FAIL + 1))
    else
        echo "ERROR"
        FAIL=$((FAIL + 1))
    fi
done

echo ""
echo "================================"
echo "Results: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
echo "================================"

# Exit with error if any tests failed or no tests passed
if [ $FAIL -gt 0 ]; then
    echo "FAILED: $FAIL test(s) failed"
    exit 1
fi

if [ $PASS -eq 0 ]; then
    echo "FAILED: No tests passed (all skipped)"
    exit 1
fi

echo "SUCCESS: All $PASS tests passed"
exit 0
