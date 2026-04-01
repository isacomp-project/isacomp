#!/bin/bash

# Test all RV64I instructions using the dual-issue processor

echo "Compiling dual-issue pipelined testbench with iverilog..."

DIR_NAME=$(basename "$PWD")
VERILOG_FILE="${DIR_NAME}.v"

if [ ! -f "$VERILOG_FILE" ]; then
    echo "ERROR: Expected Verilog file '$VERILOG_FILE' not found!"
    exit 1
fi

if [ -f "simple_tb.sv" ]; then
    TB_FILE="simple_tb.sv"
else
    echo "ERROR: No testbench file found!"
    exit 1
fi

if [ ! -f "test_sim" ] || [ "$VERILOG_FILE" -nt "test_sim" ] || [ "$TB_FILE" -nt "test_sim" ]; then
    iverilog -g2012 -o test_sim "$VERILOG_FILE" "$TB_FILE"
    if [ $? -ne 0 ]; then
        echo "ERROR: Icarus Verilog compilation failed!"
        exit 1
    fi
fi

# Base RV64I instructions
TESTS_BASE="add addi sub lui auipc and andi or ori xor xori sll slli srl srli sra srai slt slti sltu sltiu beq bne blt bltu bge bgeu jal jalr"

# Loads and stores
TESTS_MEM="lw lh lhu lb lbu lwu ld sw sh sb sd"

# RV64I-specific word operations
TESTS_WORD="addiw slliw srliw sraiw addw subw sllw srlw sraw"

TESTS="$TESTS_BASE $TESTS_MEM $TESTS_WORD"

PASS=0
FAIL=0
SKIP=0
FAILED_TESTS=""

for test in $TESTS; do
    echo -n "Testing $test... "

    TEST_BASE="../../../isa/riscv32/riscv-tests/isa/rv64ui-isacomp-$test"

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

    read PASS_ADDR FAIL_ADDR < "$TEST_BASE.addrs"

    # Convert Intel HEX to umem.hex (unified memory, 64-bit doublewords)
    python3 -c "
import sys
data = {}
with open('$TEST_BASE.hex', 'r') as f:
    for line in f:
        line = line.strip()
        if not line.startswith(':'):
            continue
        byte_count = int(line[1:3], 16)
        address = int(line[3:7], 16)
        record_type = int(line[7:9], 16)
        if record_type == 0:
            for i in range(byte_count):
                byte_val = int(line[9+i*2:11+i*2], 16)
                data[address + i] = byte_val
        elif record_type == 1:
            break

if not data:
    sys.exit(1)

# Write umem - 8192 doublewords (64-bit each, 8 bytes per entry)
with open('umem.hex', 'w') as f:
    for word_idx in range(8192):
        word = 0
        addr = word_idx * 8  # 8 bytes per doubleword
        for byte_offset in range(8):
            byte_addr = addr + byte_offset
            if byte_addr in data:
                word |= data[byte_addr] << (byte_offset * 8)
        f.write(f'{word:016x}\n')
"

    RESULT=$(timeout 5 vvp test_sim +pass_addr=$PASS_ADDR +fail_addr=$FAIL_ADDR 2>&1)
    EXIT_CODE=$?

    if echo "$RESULT" | grep -q "TEST PASSED"; then
        CYCLES=$(echo "$RESULT" | grep "TEST PASSED" | sed 's/.*in \([0-9]*\) cycles.*/\1/')
        if [ -n "$CYCLES" ]; then
            echo "PASS ($CYCLES cycles)"
        else
            echo "PASS"
        fi
        PASS=$((PASS + 1))
    elif echo "$RESULT" | grep -q "TEST FAILED"; then
        echo "FAIL"
        FAIL=$((FAIL + 1))
        FAILED_TESTS="$FAILED_TESTS $test"
    elif [ $EXIT_CODE -eq 124 ]; then
        echo "TIMEOUT"
        FAIL=$((FAIL + 1))
        FAILED_TESTS="$FAILED_TESTS $test"
    else
        echo "ERROR"
        FAIL=$((FAIL + 1))
        FAILED_TESTS="$FAILED_TESTS $test"
    fi
done

echo ""
echo "================================"
echo "Results: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
if [ -n "$FAILED_TESTS" ]; then
    echo "Failed tests:$FAILED_TESTS"
fi
echo "================================"

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
