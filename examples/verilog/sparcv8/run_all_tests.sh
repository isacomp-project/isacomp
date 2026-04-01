#!/bin/bash

# Test all SPARCv8 instructions using simple_tb with hex files
# Supports both iverilog and verilator simulators
# Set SIMULATOR=verilator to use Verilator instead of Icarus Verilog

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

SIMULATOR=${SIMULATOR:-iverilog}

echo "Compiling simple testbench with $SIMULATOR..."

if [ "$SIMULATOR" = "verilator" ]; then
    # Verilator compilation with timing support (v5+) - only recompile if needed
    if [ ! -f "test_simple" ] || [ "sparcv8.v" -nt "test_simple" ] || [ "simple_tb.sv" -nt "test_simple" ]; then
        # Run verilator from vendor directory so paths in cvfpu_sources.f work
        (cd ../../../vendor && verilator --timing --exe --binary \
            --top-module simple_tb \
            -Wno-fatal -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-TIMESCALEMOD \
            -Wno-IMPLICIT -Wno-UNSIGNED -Wno-SELRANGE -Wno-ASCRANGE -Wno-WIDTHCONCAT \
            -f cvfpu_sources.f \
            -o test_simple ../examples/verilog/sparcv8/sparcv8.v ../examples/verilog/sparcv8/simple_tb.sv && \
            mv obj_dir/test_simple ../examples/verilog/sparcv8/)
        if [ $? -ne 0 ] || [ ! -x "./test_simple" ]; then
            echo "ERROR: Verilator compilation failed!"
            exit 1
        fi
    fi
    TEST_CMD="./test_simple"
else
    # Icarus Verilog compilation - only recompile if needed
    if [ ! -f "test_simple" ] || [ "sparcv8.v" -nt "test_simple" ] || [ "simple_tb.sv" -nt "test_simple" ]; then
        iverilog -g2012 -o test_simple sparcv8.v cvfpu_simple.v simple_tb.sv
        if [ $? -ne 0 ]; then
            echo "ERROR: Icarus Verilog compilation failed!"
            exit 1
        fi
    fi
    TEST_CMD="vvp test_simple"
fi

# Test list - matches test files we created
# Basic ALU
TESTS="add addcc sub subcc and or xor xnor andn orn sll srl sra"
# Multiply/Divide
TESTS="$TESTS smul smulcc umul umulcc sdiv sdivcc udiv udivcc mulscc"
# Tagged arithmetic
TESTS="$TESTS taddcc tsubcc taddcctv tsubcctv"
# Load/Store
TESTS="$TESTS ld st ldub lduh ldsb ldsh"
# Atomic operations
TESTS="$TESTS swap ldstub"
# Branches
TESTS="$TESTS ba be bne bg bge bl ble bgu bleu bcc bcs bpos bneg bvc bvs"
# Control transfer
TESTS="$TESTS jmpl call sethi nop"
# Register window
TESTS="$TESTS save restore window"
# Conditional traps (Ticc)
TESTS="$TESTS ta tn te tne tcc tcs tg tle tge tl tgu tleu tpos tneg tvc tvs"
# Privileged instructions
TESTS="$TESTS rdpsr wrpsr rdwim wrwim rdtbr wrtbr"
# FP load/store
TESTS="$TESTS ldf stf lddf stdf ldfsr stfsr"
# FP arithmetic
TESTS="$TESTS fadds fsubs fmuls fdivs fsqrts"
# FP move operations
TESTS="$TESTS fmovs fnegs fabss"
# FP conversions
TESTS="$TESTS fitos fstoi"
# FP branches (unconditional - don't need fcmps)
TESTS="$TESTS fba fbn"
# FP branches (conditional - require fcmps which needs fp_unordered intrinsic)
# TESTS="$TESTS fbe fbne fbl fbg fble fbge"

PASS=0
FAIL=0
SKIP=0

for test in $TESTS; do
    echo -n "Testing $test... "

    TEST_BASE="../../../isa/sparcv8/sparcv8-tests/isa/sparcv8-isacomp-$test"

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

    # SPARCv8 hex files are already in big-endian word format from build_tests.sh
    # Just copy directly - no conversion needed
    cp "$TEST_BASE.hex" umem.hex

    # Run test
    RESULT=$(timeout 10 $TEST_CMD +pass_addr=$PASS_ADDR +fail_addr=$FAIL_ADDR 2>&1)
    EXIT_CODE=$?

    if echo "$RESULT" | grep -q "TEST PASSED"; then
        echo "PASS"
        PASS=$((PASS + 1))
    elif echo "$RESULT" | grep -q "TEST FAILED"; then
        echo "FAIL"
        FAIL=$((FAIL + 1))
    elif [ $EXIT_CODE -eq 124 ]; then
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

# Exit with error if any tests failed or no tests passed
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
