#!/bin/bash

# Test all 30 instructions in RV32I processor

# Check if processor exists
if [ ! -f "riscv32i_complete.v" ]; then
    echo "ERROR: riscv32i_complete.v not found. Generate processor first with:"
    echo "  python3 isa/riscv32/generators/generate_riscv32i_complete.py"
    exit 1
fi

# Compile if needed
if [ ! -f "sim" ] || [ "riscv32i_complete.v" -nt "sim" ] || [ "riscv32i_complete_tb.sv" -nt "sim" ]; then
    echo "Compiling RISC-V32I complete processor..."
    COMPILE_OUTPUT=$(iverilog -g2012 -o sim riscv32i_complete.v riscv32i_complete_tb.sv 2>&1)
    COMPILE_EXIT=$?

    # Only show errors, not warnings
    echo "$COMPILE_OUTPUT" | grep -i error

    if [ $COMPILE_EXIT -ne 0 ]; then
        echo "ERROR: Compilation failed"
        echo "$COMPILE_OUTPUT"
        exit 1
    fi
    echo ""
fi

TESTS="add addi sub lui auipc and andi or ori xor xori sll slli srl srli sra srai slt slti sltu sltiu beq bne blt bltu bge bgeu jal jalr lw lh lhu lb lbu sw sh sb"

PASS=0
FAIL=0
SKIP=0

for test in $TESTS; do
    echo -n "Testing $test... "

    # Check if test file exists
    TEST_FILE="../../../isa/riscv32/riscv-tests/isa/rv32ui-isacomp-$test"
    if [ ! -f "$TEST_FILE" ]; then
        echo "SKIP (file not found)"
        SKIP=$((SKIP + 1))
        continue
    fi

    # Extract pass/fail addresses using nm
    PASS_ADDR=$(riscv64-unknown-elf-nm "$TEST_FILE" | grep ' pass$' | awk '{print $1}')
    FAIL_ADDR=$(riscv64-unknown-elf-nm "$TEST_FILE" | grep ' fail$' | awk '{print $1}')

    if [ -z "$PASS_ADDR" ] || [ -z "$FAIL_ADDR" ]; then
        echo "SKIP (no pass/fail symbols)"
        SKIP=$((SKIP + 1))
        continue
    fi

    # Run the test with timeout
    OUTPUT=$(timeout 5 vvp -M. -melf_loader_vpi sim +elf_load="$TEST_FILE" +pass_addr="$PASS_ADDR" +fail_addr="$FAIL_ADDR" 2>&1)

    if echo "$OUTPUT" | grep -q "TEST PASSED"; then
        echo "PASS"
        PASS=$((PASS + 1))
    elif echo "$OUTPUT" | grep -q "TEST FAILED"; then
        echo "FAIL"
        FAIL=$((FAIL + 1))
    elif echo "$OUTPUT" | grep -q "Timeout"; then
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
