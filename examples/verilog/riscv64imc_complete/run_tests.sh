#!/bin/bash
# Run RV64IMC tests on the ISAComp-generated processor
# Requires tests to be built first with build_imc_tests.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Simulator selection
SIMULATOR=${SIMULATOR:-iverilog}

# Check if processor exists
if [ ! -f "riscv64imc_complete.v" ]; then
    echo "ERROR: riscv64imc_complete.v not found. Generate processor first with:"
    echo "  python3 isa/riscv64/generators/generate_riscv64imc_complete.py"
    exit 1
fi

# Check if tests exist, if not try to build them
if [ ! -d "tests" ] || [ -z "$(ls tests/*.hex 2>/dev/null)" ]; then
    echo "Tests not found. Building tests..."
    bash ./build_imc_tests.sh || {
        echo "Failed to build tests"
        exit 1
    }
fi

# Create empty rf.hex (register file starts at zero)
python3 -c "
with open('rf.hex', 'w') as f:
    for i in range(32):
        f.write('0000000000000000\n')
"

# Compile simulator if needed
if [ "$SIMULATOR" = "verilator" ]; then
    if [ ! -f "sim" ] || [ "riscv64imc_complete.v" -nt "sim" ] || [ "simple_tb.sv" -nt "sim" ]; then
        echo "Compiling RV64IMC processor simulator with Verilator..."
        verilator --timing --exe --binary \
            -Wno-fatal -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-TIMESCALEMOD \
            -o sim riscv64imc_complete.v simple_tb.sv
        if [ $? -ne 0 ]; then
            echo "ERROR: Verilator compilation failed!"
            exit 1
        fi
        if ! mv obj_dir/sim . 2>/dev/null; then
            echo "ERROR: Failed to move Verilator sim binary"
            exit 1
        fi
    fi
    TEST_CMD="./sim"
else
    if [ ! -f "sim" ] || [ "riscv64imc_complete.v" -nt "sim" ] || [ "simple_tb.sv" -nt "sim" ]; then
        echo "Compiling RV64IMC processor simulator with Icarus Verilog..."
        COMPILE_OUTPUT=$(iverilog -g2012 -o sim riscv64imc_complete.v simple_tb.sv 2>&1)
        COMPILE_EXIT=$?

        # Only show errors, not warnings
        ERRORS=$(echo "$COMPILE_OUTPUT" | grep -i "error" || true)
        if [ -n "$ERRORS" ]; then
            echo "$ERRORS"
        fi

        if [ $COMPILE_EXIT -ne 0 ]; then
            echo "ERROR: Compilation failed"
            echo "$COMPILE_OUTPUT"
            exit 1
        fi
        echo "Compilation successful"
        echo ""
    fi
    TEST_CMD="vvp sim"
fi

PASS=0
FAIL=0
SKIP=0

run_test() {
    local TEST_NAME="$1"
    local TEST_FILE="$2"

    printf "  %-20s ... " "$TEST_NAME"

    if [ ! -f "$TEST_FILE" ]; then
        echo "SKIP (not found)"
        SKIP=$((SKIP + 1))
        return
    fi

    # Get addresses file
    ADDRS_FILE="${TEST_FILE%.hex}"
    ADDRS_FILE="${ADDRS_FILE}.addrs"

    if [ ! -f "$ADDRS_FILE" ]; then
        echo "SKIP (no addresses)"
        SKIP=$((SKIP + 1))
        return
    fi

    PASS_ADDR=$(awk '{print $1}' "$ADDRS_FILE")
    FAIL_ADDR=$(awk '{print $2}' "$ADDRS_FILE")

    # Copy test to umem.hex (unified memory model - code and data share same space)
    cp "$TEST_FILE" umem.hex

    # Run test with timeout
    OUTPUT=$(timeout 10 $TEST_CMD +pass_addr="$PASS_ADDR" +fail_addr="$FAIL_ADDR" 2>&1)

    if echo "$OUTPUT" | grep -q "TEST PASSED"; then
        echo "PASS"
        PASS=$((PASS + 1))
    elif echo "$OUTPUT" | grep -q "TEST FAILED"; then
        echo "FAIL"
        FAIL=$((FAIL + 1))
    elif echo "$OUTPUT" | grep -q "TIMEOUT"; then
        echo "TIMEOUT"
        FAIL=$((FAIL + 1))
    else
        echo "ERROR"
        FAIL=$((FAIL + 1))
    fi

    # Cleanup
    rm -f umem.hex
}

echo "======================================================================"
echo "Running RV64IMC Tests"
echo "======================================================================"
echo ""

# RV64I base tests
echo "RV64I Base Instruction Tests"
echo "----------------------------"

TESTS_I="add addi sub lui auipc and andi or ori xor xori sll slli srl srli sra srai slt slti sltu sltiu beq bne blt bltu bge bgeu jal jalr lw lh lhu lb lbu sw sh sb ld lwu sd"

for test in $TESTS_I; do
    run_test "$test" "tests/rv64ui-isacomp-${test}.hex"
done

# RV64I word operations
echo ""
echo "RV64I Word Operation Tests"
echo "--------------------------"

TESTS_I_WORD="addw addiw subw sllw slliw srlw srliw sraw sraiw"

for test in $TESTS_I_WORD; do
    run_test "$test" "tests/rv64ui-isacomp-${test}.hex"
done

# RV64M multiply/divide tests
echo ""
echo "RV64M Multiply/Divide Tests"
echo "---------------------------"

TESTS_M="mul mulh mulhsu mulhu div divu rem remu mulw divw divuw remw remuw"

for test in $TESTS_M; do
    run_test "$test" "tests/rv64um-isacomp-${test}.hex"
done

# RV64C compressed tests
echo ""
echo "RV64C Compressed Instruction Tests"
echo "-----------------------------------"

run_test "rvc (compressed)" "tests/rv64uc-isacomp-rvc.hex"

echo ""
echo "======================================================================"
echo "Test Summary: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
echo "======================================================================"

if [ $FAIL -gt 0 ]; then
    echo "Some tests FAILED!"
    exit 1
fi

if [ $PASS -eq 0 ]; then
    echo "No tests passed!"
    exit 1
fi

echo "All tests PASSED!"
exit 0
