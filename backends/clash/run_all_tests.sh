#!/bin/bash

# Test all RV32I instructions using Clash-generated Verilog
# Usage: ./run_all_tests.sh [design_dir]
#
# Uses gen_tb.py to generate testbench from Clash's flat state register layout.
# gen_tb.py handles both non-pipelined and pipelined designs, detecting
# execute-stage PC and validity signals for pipelined pass/fail checking.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -n "$1" ]; then
    DESIGN_DIR="$(cd "$1" && pwd)"
else
    DESIGN_DIR="$SCRIPT_DIR"
fi

cd "$DESIGN_DIR"

VERILOG_FILE=$(ls *.v 2>/dev/null | head -1)

# If no Verilog file is found in the design directory, try common Clash output locations.
if [ -z "$VERILOG_FILE" ] && [ -d "verilog" ]; then
    VERILOG_FILE=$(find verilog -maxdepth 2 -type f -name '*.v' 2>/dev/null | head -1)
fi

if [ -z "$VERILOG_FILE" ]; then
    echo "ERROR: No Verilog file found in $DESIGN_DIR (or in common Clash output subdirectories)"
    exit 1
fi

GEN_TB="$DESIGN_DIR/gen_tb.py"
if [ ! -f "$GEN_TB" ]; then
    GEN_TB="$SCRIPT_DIR/gen_tb.py"
fi
if [ ! -f "$GEN_TB" ]; then
    echo "ERROR: gen_tb.py not found"
    exit 1
fi

echo "Design directory: $DESIGN_DIR"
echo "Verilog file: $VERILOG_FILE"

echo "Generating testbench from Clash Verilog..."
python3 "$GEN_TB" "$VERILOG_FILE" simple_tb.sv
if [ $? -ne 0 ]; then
    echo "ERROR: Testbench generation failed"
    exit 1
fi

rm -f test_simple

echo "Compiling with iverilog..."
iverilog -g2012 -o test_simple "$VERILOG_FILE" simple_tb.sv
if [ $? -ne 0 ]; then
    echo "ERROR: Icarus Verilog compilation failed!"
    exit 1
fi

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
        if record_type == 0:
            for i in range(byte_count):
                byte_val = int(line[9+i*2:11+i*2], 16)
                data[address + i] = byte_val
        elif record_type == 1:
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
TEST_DIR="../../../isa/riscv32/riscv-tests/isa"

MAX_JOBS=${MAX_JOBS:-6}
TMPBASE=$(mktemp -d)

run_test() {
    trap - EXIT
    local test=$1
    local tmpdir="$TMPBASE/$test"
    mkdir -p "$tmpdir"
    local TEST_BASE="$TEST_DIR/rv32ui-isacomp-$test"
    if [ ! -f "$TEST_BASE.hex" ]; then
        echo "SKIP" > "$tmpdir/status"
        return 0
    fi
    if [ ! -f "$TEST_BASE.addrs" ]; then
        echo "SKIP" > "$tmpdir/status"
        return 0
    fi
    local PASS_ADDR FAIL_ADDR
    read PASS_ADDR FAIL_ADDR < "$TEST_BASE.addrs"
    convert_ihex "$TEST_BASE.hex" "$tmpdir/umem.hex"
    local RESULT
    RESULT=$(cd "$tmpdir" && timeout 120 vvp "$DESIGN_DIR/test_simple" +pass_addr=$PASS_ADDR +fail_addr=$FAIL_ADDR 2>&1) || true
    if echo "$RESULT" | grep -q "TEST PASSED"; then
        echo "PASS" > "$tmpdir/status"
    elif echo "$RESULT" | grep -q "TEST FAILED"; then
        echo "FAIL" > "$tmpdir/status"
        echo "$RESULT" | grep -o "testnum=[0-9]*" | cut -d= -f2 > "$tmpdir/reason"
    else
        echo "ERROR" > "$tmpdir/status"
        echo "$RESULT" > "$tmpdir/reason"
    fi
    return 0
}

echo "Running tests (max $MAX_JOBS parallel)..."
RUNNING=0
for test in $TESTS; do
    run_test "$test" &
    RUNNING=$((RUNNING + 1))
    if [ $RUNNING -ge $MAX_JOBS ]; then
        wait -n 2>/dev/null || true
        RUNNING=$((RUNNING - 1))
    fi
done
wait

PASS=0
FAIL=0
SKIP=0
for test in $TESTS; do
    STATUS=$(cat "$TMPBASE/$test/status" 2>/dev/null || echo "ERROR")
    REASON=$(cat "$TMPBASE/$test/reason" 2>/dev/null || echo "")
    case "$STATUS" in
        PASS)  echo "  $test: PASS"; PASS=$((PASS + 1));;
        FAIL)  echo "  $test: FAIL (test $REASON)"; FAIL=$((FAIL + 1));;
        SKIP)  echo "  $test: SKIP"; SKIP=$((SKIP + 1));;
        *)     echo "  $test: ERROR"; FAIL=$((FAIL + 1));;
    esac
done

rm -rf "$TMPBASE"

echo ""
echo "================================"
echo "Results: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
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
