#!/bin/bash
# Run MIPS32 tests on both non-delay-slot and delay-slot designs.
# Assumes designs are already generated (via generate_mips32_complete.py)
# and test binaries are already built (via build_tests.sh or build_tests_binutils.sh).
# Compiles the Verilog testbenches and runs all tests.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

TESTS="add addi addiu addu and andi beq bne j jal jalr jr lb lbu lh lhu lui lw nor or ori sb sh sll sllv slt slti sltiu sltu sra srav srl srlv sub subu sw xor xori delay_slot"

TEST_SRC_DIR="isa/mips32/mips-tests/isa"

# Helper: convert Intel HEX to umem.hex
convert_hex() {
    local HEX_FILE="$1"
    python3 -c "
import sys
data = {}
with open('$HEX_FILE', 'r') as f:
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
with open('umem.hex', 'w') as f:
    for word_idx in range(8192):
        word = 0
        addr = word_idx * 4
        word = data.get(addr, 0) | (data.get(addr+1, 0) << 8) | (data.get(addr+2, 0) << 16) | (data.get(addr+3, 0) << 24)
        f.write(f'{word:08x}\n')
"
}

# Create rf.hex (all zeros)
create_rf() {
    python3 -c "
with open('rf.hex', 'w') as f:
    for i in range(32):
        f.write('00000000\n')
"
}

# run_test_suite DESIGN_DIR TEST_PREFIX SUITE_NAME
run_test_suite() {
    local DESIGN_DIR="$1"
    local TEST_PREFIX="$2"
    local SUITE_NAME="$3"

    echo ""
    echo "========================================"
    echo " $SUITE_NAME"
    echo "========================================"

    cd "$REPO_ROOT/$DESIGN_DIR"

    # Compile testbench
    echo "Compiling $DESIGN_DIR..."
    iverilog -g2012 -o test_simple mips32_complete.v simple_tb.sv
    create_rf

    local PASS=0 FAIL=0 SKIP=0
    local FAILED_TESTS=""

    for test in $TESTS; do
        printf "  %-20s" "$test"

        TEST_BASE="$REPO_ROOT/$TEST_SRC_DIR/${TEST_PREFIX}${test}"

        if [ ! -f "$TEST_BASE.hex" ] || [ ! -f "$TEST_BASE.addrs" ]; then
            echo "SKIP"
            SKIP=$((SKIP + 1))
            continue
        fi

        read PASS_ADDR FAIL_ADDR < "$TEST_BASE.addrs"
        convert_hex "$TEST_BASE.hex"

        RESULT=$(timeout 5 vvp test_simple +pass_addr=$PASS_ADDR +fail_addr=$FAIL_ADDR 2>&1 || true)
        EXIT_CODE=${PIPESTATUS[0]:-$?}

        if echo "$RESULT" | grep -q "TEST PASSED"; then
            echo "PASS"
            PASS=$((PASS + 1))
        elif echo "$RESULT" | grep -q "TEST FAILED"; then
            TESTNUM=$(echo "$RESULT" | grep "TEST FAILED" | sed 's/.*testnum=\([0-9]*\).*/\1/')
            echo "FAIL (test $TESTNUM)"
            FAIL=$((FAIL + 1))
            FAILED_TESTS="$FAILED_TESTS $test"
        elif echo "$RESULT" | grep -q "TIMEOUT"; then
            echo "TIMEOUT"
            FAIL=$((FAIL + 1))
            FAILED_TESTS="$FAILED_TESTS $test"
        else
            echo "ERROR"
            FAIL=$((FAIL + 1))
            FAILED_TESTS="$FAILED_TESTS $test"
        fi
    done

    echo "  ----------------------------------------"
    echo "  Results: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
    if [ -n "$FAILED_TESTS" ]; then
        echo "  Failed:$FAILED_TESTS"
    fi

    cd "$REPO_ROOT"
    return $FAIL
}

echo "========================================"
echo " MIPS32 Delay Slot Test Suite"
echo "========================================"

# Run non-delay-slot tests on non-delay-slot design
FAIL1=0
run_test_suite "examples/verilog/mips32_complete" "mips32-isacomp-" \
    "Non-delay-slot design + non-delay-slot tests" || FAIL1=$?

# Run delay-slot tests on delay-slot design
FAIL2=0
run_test_suite "examples/verilog/mips32_complete_ds" "mips32-isacomp-ds-" \
    "Delay-slot design + delay-slot tests" || FAIL2=$?

# Summary
echo ""
echo "========================================"
echo " OVERALL SUMMARY"
echo "========================================"
if [ $FAIL1 -eq 0 ] && [ $FAIL2 -eq 0 ]; then
    echo " ALL TESTS PASSED"
else
    echo " FAILURES DETECTED"
    [ $FAIL1 -gt 0 ] && echo "   Non-delay-slot: $FAIL1 failures"
    [ $FAIL2 -gt 0 ] && echo "   Delay-slot: $FAIL2 failures"
fi
echo "========================================"

exit $((FAIL1 + FAIL2))
