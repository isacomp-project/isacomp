#!/bin/bash
# Run J2 ISA tests against the pipelined processor

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VERILOG_DIR="../../examples/verilog/j2_pipelined_5stage"
TEST_DIR="isa"

# Check if simulator exists
if [ ! -f "$VERILOG_DIR/test_sim" ]; then
    echo "Error: Simulator not found. Please compile the Verilog first."
    exit 1
fi

PASS=0
FAIL=0
FAILED_TESTS=""

# Run each test
for ADDR_FILE in "$TEST_DIR"/j2-isacomp-*.addrs; do
    if [ ! -f "$ADDR_FILE" ]; then
        continue
    fi

    TEST_NAME=$(basename "$ADDR_FILE" .addrs | sed 's/j2-isacomp-//')
    HEX_FILE="${ADDR_FILE%.addrs}.hex"

    if [ ! -f "$HEX_FILE" ]; then
        echo "  SKIP: $TEST_NAME (no hex file)"
        continue
    fi

    # Read pass/fail addresses
    read PASS_ADDR FAIL_ADDR < "$ADDR_FILE"

    # Validate that addresses are hex values (mitigate command injection)
    if ! [[ "$PASS_ADDR" =~ ^[0-9A-Fa-f]+$ ]] || ! [[ "$FAIL_ADDR" =~ ^[0-9A-Fa-f]+$ ]]; then
        printf "%-20s" "$TEST_NAME..."
        echo -e "\033[31mINVALID ADDR\033[0m"
        FAIL=$((FAIL + 1))
        FAILED_TESTS="$FAILED_TESTS $TEST_NAME(invalid_addrs)"
        continue
    fi

    # Copy hex file to umem.hex in Verilog directory
    cp "$HEX_FILE" "$VERILOG_DIR/umem.hex"

    # Run simulation with timeout
    printf "%-20s" "$TEST_NAME..."
    RESULT=$(timeout 5 "$VERILOG_DIR/test_sim" "+pass_addr=$PASS_ADDR" "+fail_addr=$FAIL_ADDR" 2>&1)

    if echo "$RESULT" | grep -q "TEST PASSED"; then
        echo -e "\033[32mPASS\033[0m"
        PASS=$((PASS + 1))
    elif echo "$RESULT" | grep -q "TEST FAILED"; then
        echo -e "\033[31mFAIL\033[0m"
        FAIL=$((FAIL + 1))
        FAILED_TESTS="$FAILED_TESTS $TEST_NAME"
    else
        echo -e "\033[33mTIMEOUT\033[0m"
        FAIL=$((FAIL + 1))
        FAILED_TESTS="$FAILED_TESTS $TEST_NAME(timeout)"
    fi
done

echo ""
echo "========================================"
echo "Results: $PASS passed, $FAIL failed"
if [ -n "$FAILED_TESTS" ]; then
    echo "Failed tests:$FAILED_TESTS"
fi
echo "========================================"

exit $FAIL
