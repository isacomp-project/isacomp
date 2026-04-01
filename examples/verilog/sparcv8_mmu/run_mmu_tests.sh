#!/bin/bash
# Run SPARCv8 MMU tests using simple_tb with hex files
# Supports both iverilog and verilator simulators

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

SIMULATOR=${SIMULATOR:-iverilog}

# Build tests first
echo "Building MMU tests..."
(cd ../../../isa/sparcv8/sparcv8-tests && ./build_mmu_tests.sh)
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to build MMU tests"
    exit 1
fi

echo "Compiling simple testbench with $SIMULATOR..."

if [ "$SIMULATOR" = "verilator" ]; then
    # Verilator compilation
    if [ ! -f "test_simple" ] || [ "sparcv8_mmu.v" -nt "test_simple" ] || [ "simple_tb.sv" -nt "test_simple" ]; then
        (cd ../../../vendor && verilator --timing --exe --binary \
            --top-module simple_tb \
            -Wno-fatal -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-TIMESCALEMOD \
            -Wno-IMPLICIT -Wno-UNSIGNED -Wno-SELRANGE -Wno-ASCRANGE -Wno-WIDTHCONCAT \
            -f cvfpu_sources.f \
            -o test_simple ../examples/verilog/sparcv8_mmu/sparcv8_mmu.v ../examples/verilog/sparcv8_mmu/simple_tb.sv && \
            mv obj_dir/test_simple ../examples/verilog/sparcv8_mmu/)
        if [ $? -ne 0 ] || [ ! -x "./test_simple" ]; then
            echo "ERROR: Verilator compilation failed!"
            exit 1
        fi
    fi
    TEST_CMD="./test_simple"
else
    # Icarus Verilog compilation
    if [ ! -f "test_simple" ] || [ "sparcv8_mmu.v" -nt "test_simple" ] || [ "simple_tb.sv" -nt "test_simple" ]; then
        iverilog -g2012 -o test_simple sparcv8_mmu.v cvfpu_simple.v simple_tb.sv
        if [ $? -ne 0 ]; then
            echo "ERROR: Icarus Verilog compilation failed!"
            exit 1
        fi
    fi
    TEST_CMD="vvp test_simple"
fi

# MMU test list
TESTS="mmu_basic mmu_multi mmu_miss mmu_prot mmu_context"

PASS=0
FAIL=0
SKIP=0

for test in $TESTS; do
    echo -n "Testing $test... "

    TEST_BASE="../../../isa/sparcv8/sparcv8-tests/mmu/sparcv8-mmu-$test"

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

    # Copy hex file
    cp "$TEST_BASE.hex" umem.hex

    # Run test
    RESULT=$(timeout 10 $TEST_CMD +pass_addr=$PASS_ADDR +fail_addr=$FAIL_ADDR 2>&1)
    EXIT_CODE=$?

    if echo "$RESULT" | grep -q "TEST PASSED"; then
        echo "PASS"
        PASS=$((PASS + 1))
    elif echo "$RESULT" | grep -q "TEST FAILED"; then
        echo "FAIL"
        echo "  Output: $(echo "$RESULT" | grep -E 'TEST FAILED|testnum')"
        FAIL=$((FAIL + 1))
    elif [ $EXIT_CODE -eq 124 ]; then
        echo "TIMEOUT"
        FAIL=$((FAIL + 1))
    else
        echo "ERROR"
        echo "  Output: $RESULT"
        FAIL=$((FAIL + 1))
    fi
done

echo ""
echo "================================"
echo "Results: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
echo "================================"

if [ $FAIL -gt 0 ]; then
    echo "FAILED: $FAIL test(s) failed"
    exit 1
fi

if [ $PASS -eq 0 ]; then
    echo "FAILED: No tests passed"
    exit 1
fi

echo "SUCCESS: All $PASS tests passed"
exit 0
