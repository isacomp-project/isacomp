#!/bin/bash

# Test all 49 instructions in RV64I processor

# Check if processor exists
if [ ! -f "riscv64i_complete.v" ]; then
    echo "ERROR: riscv64i_complete.v not found. Generate processor first with:"
    echo "  python3 isa/riscv64/generators/generate_riscv64i_complete.py"
    exit 1
fi

# Compile if needed
if [ ! -f "sim" ] || [ "riscv64i_complete.v" -nt "sim" ] || [ "simple_tb.sv" -nt "sim" ]; then
    echo "Compiling RISC-V64I complete processor..."
    COMPILE_OUTPUT=$(iverilog -g2012 -o sim riscv64i_complete.v simple_tb.sv 2>&1)
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

# Base RV64I instructions (adapted from RV32I)
TESTS_BASE="add addi sub lui auipc and andi or ori xor xori sll slli srl srli sra srai slt slti sltu sltiu beq bne blt bltu bge bgeu jal jalr"

# Loads and stores (base)
TESTS_MEM="lw lh lhu lb lbu sw sh sb"

# RV64I-specific instructions
TESTS_RV64="ld lwu sd addiw slliw srliw sraiw addw subw sllw srlw sraw"

# Combine all tests
TESTS="$TESTS_BASE $TESTS_MEM $TESTS_RV64"

PASS=0
FAIL=0
SKIP=0

echo "======================================"
echo "RV64I PROCESSOR TEST SUITE"
echo "======================================"
echo ""

for test in $TESTS; do
    printf "%-10s... " "$test"

    # Check if test file exists
    TEST_FILE="../../../isa/riscv64/riscv-tests/isa/rv64ui-isacomp-$test"
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
        echo "✓ PASS"
        PASS=$((PASS + 1))
    elif echo "$OUTPUT" | grep -q "TEST FAILED"; then
        echo "✗ FAIL"
        FAIL=$((FAIL + 1))
    elif echo "$OUTPUT" | grep -q "Timeout"; then
        echo "✗ TIMEOUT"
        FAIL=$((FAIL + 1))
    else
        echo "✗ ERROR"
        FAIL=$((FAIL + 1))
    fi
done

echo ""
echo "======================================"
echo "RESULTS"
echo "======================================"
echo "PASS:  $PASS / $(echo $TESTS | wc -w)"
echo "FAIL:  $FAIL / $(echo $TESTS | wc -w)"
echo "SKIP:  $SKIP / $(echo $TESTS | wc -w)"
echo ""

if [ $FAIL -eq 0 ] && [ $PASS -gt 0 ]; then
    echo "✓ ALL TESTS PASSED!"
    exit 0
else
    echo "✗ SOME TESTS FAILED"
    exit 1
fi
