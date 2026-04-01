#!/bin/bash

# Test MIPS32 Linux instructions using the single-cycle processor
# Supports both iverilog and verilator simulators

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

SIMULATOR=${SIMULATOR:-iverilog}

echo "Compiling MIPS32 Linux testbench with $SIMULATOR..."

if [ "$SIMULATOR" = "verilator" ]; then
    if [ ! -f "test_simple" ] || [ "mips32_linux.v" -nt "test_simple" ] || [ "simple_tb.sv" -nt "test_simple" ]; then
        verilator --timing --exe --binary \
            -Wno-fatal -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-TIMESCALEMOD \
            -o test_simple mips32_linux.v simple_tb.sv
        if [ $? -ne 0 ]; then
            echo "ERROR: Verilator compilation failed!"
            exit 1
        fi
        mv obj_dir/test_simple . 2>/dev/null || true
    fi
    TEST_CMD="./test_simple"
else
    if [ ! -f "test_simple" ] || [ "mips32_linux.v" -nt "test_simple" ] || [ "simple_tb.sv" -nt "test_simple" ]; then
        iverilog -g2012 -o test_simple mips32_linux.v simple_tb.sv
        if [ $? -ne 0 ]; then
            echo "ERROR: Icarus Verilog compilation failed!"
            exit 1
        fi
    fi
    TEST_CMD="vvp test_simple"
fi

# Create empty rf.hex (register file starts at zero)
python3 -c "
with open('rf.hex', 'w') as f:
    for i in range(32):
        f.write('00000000\n')
"

# All tests supported by the MIPS32 Linux processor
TESTS="add addi addiu addu and andi beq bne j jal jalr jr lb lbu lh lhu lui lw nor or ori sb sh sll sllv slt slti sltiu sltu sra srav srl srlv sub subu sw xor xori"
TESTS="$TESTS bgez bgtz blez bltz bgezal bltzal"
TESTS="$TESTS mul mult multu div divu madd maddu msub msubu"
TESTS="$TESTS clz clo ext ins seb seh wsbh rotr rotrv"
TESTS="$TESTS movz movn ll sc"

PASS=0
FAIL=0
SKIP=0
FAILED_TESTS=""

for test in $TESTS; do
    echo -n "Testing $test... "

    TEST_BASE="../../../isa/mips32/mips-tests/isa/mips32-isacomp-$test"

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

    # Convert Intel HEX to umem.hex (unified memory)
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

# Write umem (unified memory) - 8192 words (little-endian)
with open('umem.hex', 'w') as f:
    for word_idx in range(8192):
        word = 0
        addr = word_idx * 4
        word = data.get(addr, 0) | (data.get(addr+1, 0) << 8) | (data.get(addr+2, 0) << 16) | (data.get(addr+3, 0) << 24)
        f.write(f'{word:08x}\n')
"

    # Run test
    RESULT=$(timeout 5 $TEST_CMD +pass_addr=$PASS_ADDR +fail_addr=$FAIL_ADDR 2>&1)
    EXIT_CODE=$?

    if echo "$RESULT" | grep -q "TEST PASSED"; then
        echo "PASS"
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
