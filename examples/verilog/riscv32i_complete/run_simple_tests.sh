#!/bin/bash
# Simple test runner without VPI dependencies

TESTS="add addi sub lui auipc and andi or ori xor xori sll slli srl srli sra srai slt slti sltu sltiu beq bne blt bltu bge bgeu jal jalr lw lh lhu lb lbu sw sh sb"
PASS=0
FAIL=0

for test in $TESTS; do
    iverilog -g2012 -o sim_test riscv32i_complete.v test_${test}_tb.sv 2>/dev/null
    result=$(timeout 120 vvp sim_test 2>&1 | grep -E "PASSED|FAILED" | head -1)
    if echo "$result" | grep -q "PASSED"; then
        echo "$test: PASS"
        PASS=$((PASS + 1))
    elif echo "$result" | grep -q "FAILED"; then
        echo "$test: FAIL"
        FAIL=$((FAIL + 1))
    else
        echo "$test: TIMEOUT/ERROR"
        FAIL=$((FAIL + 1))
    fi
done

echo "============================="
echo "PASS: $PASS, FAIL: $FAIL"
