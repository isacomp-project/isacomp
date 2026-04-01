#!/bin/bash

# Test all RV32I instructions using the dual-issue pipelined processor
# Supports both iverilog and verilator simulators
# Set SIMULATOR=verilator to use Verilator instead of Icarus Verilog

SIMULATOR=${SIMULATOR:-iverilog}

echo "Compiling dual-issue pipelined testbench with $SIMULATOR..."

# Derive verilog filename from directory name (directory name matches module name)
DIR_NAME=$(basename "$PWD")
VERILOG_FILE="${DIR_NAME}.v"

if [ ! -f "$VERILOG_FILE" ]; then
    echo "ERROR: Expected Verilog file '$VERILOG_FILE' not found!"
    exit 1
fi

# Find testbench file (may be simple_tb.sv or simple_tb_new.sv)
if [ -f "simple_tb.sv" ]; then
    TB_FILE="simple_tb.sv"
elif [ -f "simple_tb_new.sv" ]; then
    TB_FILE="simple_tb_new.sv"
else
    echo "ERROR: No testbench file found (expected simple_tb.sv or simple_tb_new.sv)!"
    exit 1
fi

if [ "$SIMULATOR" = "verilator" ]; then
    # Verilator compilation with timing support (v5+) - only recompile if needed
    if [ ! -f "test_sim" ] || [ "$VERILOG_FILE" -nt "test_sim" ] || [ "$TB_FILE" -nt "test_sim" ]; then
        verilator --timing --exe --binary \
            -Wno-fatal -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-TIMESCALEMOD \
            -o test_sim "$VERILOG_FILE" "$TB_FILE"
        if [ $? -ne 0 ]; then
            echo "ERROR: Verilator compilation failed!"
            exit 1
        fi
        # Move binary from obj_dir and ensure it exists
        if ! mv obj_dir/test_sim . 2>/dev/null; then
            echo "ERROR: Failed to move Verilator sim binary from obj_dir/test_sim"
            exit 1
        fi
        if [ ! -x "./test_sim" ]; then
            echo "ERROR: Verilator sim binary './test_sim' not found or not executable"
            exit 1
        fi
    fi
    TEST_CMD="./test_sim"
else
    # Icarus Verilog compilation - only recompile if needed
    if [ ! -f "test_sim" ] || [ "$VERILOG_FILE" -nt "test_sim" ] || [ "$TB_FILE" -nt "test_sim" ]; then
        iverilog -g2012 -o test_sim "$VERILOG_FILE" "$TB_FILE"
        if [ $? -ne 0 ]; then
            echo "ERROR: Icarus Verilog compilation failed!"
            exit 1
        fi
    fi
    TEST_CMD="vvp test_sim"
fi

TESTS="add addi sub lui auipc and andi or ori xor xori sll slli srl srli sra srai slt slti sltu sltiu beq bne blt bltu bge bgeu jal jalr lw lh lhu lb lbu sw sh sb"

PASS=0
FAIL=0
SKIP=0
FAILED_TESTS=""

for test in $TESTS; do
    echo -n "Testing $test... "

    TEST_BASE="../../../isa/riscv32/riscv-tests/isa/rv32ui-isacomp-$test"

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

    # Convert Intel HEX to unified memory format (umem.hex)
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
        if record_type == 0:  # Data record
            for i in range(byte_count):
                byte_val = int(line[9+i*2:11+i*2], 16)
                data[address + i] = byte_val
        elif record_type == 1:  # EOF
            break

if not data:
    sys.exit(1)

# Unified memory: all code and data in one hex file
max_addr = max(data.keys())
max_word = (max_addr // 4) + 1

# Write umem (unified memory for code + data)
with open('umem.hex', 'w') as f:
    for word_idx in range(max(8192, max_word)):
        word = 0
        addr = word_idx * 4
        for byte_offset in range(4):
            byte_addr = addr + byte_offset
            if byte_addr in data:
                word |= data[byte_addr] << (byte_offset * 8)
        f.write(f'{word:08x}\n')
"

    # Run test
    RESULT=$(timeout 5 $TEST_CMD +pass_addr=$PASS_ADDR +fail_addr=$FAIL_ADDR 2>&1)
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
