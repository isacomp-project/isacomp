#!/bin/bash
# Run all RV32UI tests and collect statistics

set -e

SCRIPT_DIR=$(dirname "$0")
cd "$SCRIPT_DIR"

TESTS=(
    "add" "addi" "and" "andi" "auipc"
    "beq" "bge" "bgeu" "blt" "bltu" "bne"
    "jal" "jalr"
    "lb" "lbu" "lh" "lhu" "lui" "lw"
    "or" "ori"
    "sb" "sh" "sw"
    "sll" "slli" "slt" "slti" "sltiu" "sltu"
    "sra" "srai" "srl" "srli"
    "sub"
    "xor" "xori"
)

PASSED=0
FAILED=0
PASSED_TESTS=()
FAILED_TESTS=()

echo "=========================================="
echo "Running All RV32UI Tests"
echo "=========================================="
echo ""

for test in "${TESTS[@]}"; do
    echo -n "Testing $test... "

    if ./run_riscv_test.sh "$test" > /dev/null 2>&1; then
        echo "PASSED"
        PASSED=$((PASSED + 1))
        PASSED_TESTS+=("$test")
    else
        echo "FAILED"
        FAILED=$((FAILED + 1))
        FAILED_TESTS+=("$test")
    fi
done

TOTAL=$((PASSED + FAILED))

echo ""
echo "=========================================="
echo "Test Results Summary"
echo "=========================================="
echo "Total:  ${TOTAL}"
echo "Passed: ${PASSED}"
echo "Failed: ${FAILED}"
echo ""

if [ ${#PASSED_TESTS[@]} -gt 0 ]; then
    echo "Passed tests (${PASSED}):"
    for test in "${PASSED_TESTS[@]}"; do
        echo "  ✓ $test"
    done
    echo ""
fi

if [ ${#FAILED_TESTS[@]} -gt 0 ]; then
    echo "Failed tests (${FAILED}):"
    for test in "${FAILED_TESTS[@]}"; do
        echo "  ✗ $test"
    done
    echo ""
fi

if [ $FAILED -eq 0 ]; then
    echo "✓ All tests passed!"
    exit 0
else
    echo "✗ Some tests failed"
    exit 1
fi
