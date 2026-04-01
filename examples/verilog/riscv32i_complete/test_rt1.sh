#!/bin/bash

# Quick test script for RT1 processor

TESTS="add addi sub lui and or xor slt beq bne jal lw sw"

echo "Testing RT1 (Roundtrip 1) processor..."
echo "======================================"

PASS=0
FAIL=0

for test in $TESTS; do
    echo -n "Testing $test... "

    # Check if test file exists
    TEST_FILE="../../../isa/riscv32/riscv-tests/isa/rv32ui-isacomp-$test"
    if [ ! -f "$TEST_FILE" ]; then
        echo "SKIP (file not found)"
        continue
    fi

    # Extract pass/fail addresses
    PASS_ADDR=$(riscv64-unknown-elf-nm "$TEST_FILE" | grep ' pass$' | awk '{print $1}')
    FAIL_ADDR=$(riscv64-unknown-elf-nm "$TEST_FILE" | grep ' fail$' | awk '{print $1}')

    # Run the test
    OUTPUT=$(timeout 5 vvp -M. -melf_loader_vpi sim_rt1 +elf_load="$TEST_FILE" +pass_addr="$PASS_ADDR" +fail_addr="$FAIL_ADDR" 2>&1)

    if echo "$OUTPUT" | grep -q "TEST PASSED"; then
        echo "PASS"
        PASS=$((PASS + 1))
    elif echo "$OUTPUT" | grep -q "TEST FAILED"; then
        echo "FAIL"
        FAIL=$((FAIL + 1))
    else
        echo "ERROR"
        FAIL=$((FAIL + 1))
    fi
done

echo ""
echo "Results: $PASS PASS, $FAIL FAIL"
echo "======================================"
