#!/bin/bash
# Run all PDP-11 tests
# Usage: ./run_all_tests.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERILOG_DIR="$SCRIPT_DIR/../../../examples/verilog/pdp11_complete"
TEST_DIR="$SCRIPT_DIR/isa"

# Create work directory
WORK_DIR=$(mktemp -d)
trap "rm -rf $WORK_DIR" EXIT

# Compile once
echo "=== Compiling PDP-11 processor ==="
iverilog -g2012 -o $WORK_DIR/sim.vvp \
    "$VERILOG_DIR/pdp11_complete.v" \
    "$SCRIPT_DIR/simple_tb.sv"
touch $WORK_DIR/rf.hex
echo "Compilation successful"
echo ""

# Test configurations: test_name:pass_addr:fail_addr
# Addresses derived from assembled hex files (BR self-loop locations)
TESTS=(
    # Basic data movement and arithmetic
    "mov:0042:0044"
    "add:006e:0070"
    "sub:0062:0064"
    "inc_dec:0068:006a"
    "neg:0050:0052"

    # Logical operations
    "logical:006e:0070"
    "xor:005a:005c"
    "bit:0056:0058"
    "clr_com:0056:0058"
    "com:0052:0054"

    # Shift and rotate
    "shift:005c:005e"
    "rotate:0068:006a"

    # Branches
    "branch:0076:0078"

    # EIS instructions
    "mul:007a:007c"
    "div:0082:0084"
    "ash:005a:005c"

    # Byte instructions
    "movb:0054:0056"
    "incb_decb:0058:005a"

    # Miscellaneous
    "swab:004c:004e"
    "sxt:0050:0052"
    "tst:0044:0046"
    "adc_sbc:006a:006c"
    "cond_codes:004a:004c"
    "sob:0042:0044"

    # Subroutines
    "jsr_rts:006e:0070"

    # Benchmark-derived tests (from vanheusden.com PDP-11 benchmark)
    "addr_modes:00d2:00d4"
    "carry_chain:00ce:00d0"
    "ashc:00b0:00b2"
    "byte_ops:00d2:00d4"
    "jmp:0054:0056"
    "benchmark_seq:00e6:00e8"
    "mem_ops:00c8:00ca"
)

PASSED=0
FAILED=0

echo "=== Running PDP-11 Test Suite ==="
echo ""

for test_config in "${TESTS[@]}"; do
    IFS=':' read -r test_name pass_addr fail_addr <<< "$test_config"

    printf "%-20s " "$test_name..."

    if [ ! -f "$TEST_DIR/${test_name}.hex" ]; then
        echo "SKIP (no test file)"
        continue
    fi

    cp "$TEST_DIR/${test_name}.hex" "$WORK_DIR/umem.hex"

    # Run test and capture output
    OUTPUT=$(cd $WORK_DIR && vvp sim.vvp +pass_addr=$pass_addr +fail_addr=$fail_addr 2>&1)

    if echo "$OUTPUT" | grep -q "PASSED"; then
        echo "PASS"
        PASSED=$((PASSED + 1))
    elif echo "$OUTPUT" | grep -q "FAILED\|TIMEOUT"; then
        echo "FAIL"
        FAILED=$((FAILED + 1))
        if [ "$VERBOSE" = "1" ]; then
            echo "  Output: $OUTPUT"
        fi
    else
        echo "ERROR"
        FAILED=$((FAILED + 1))
    fi
done

echo ""
echo "=== Test Summary ==="
echo "Passed: $PASSED"
echo "Failed: $FAILED"
echo "Total:  $((PASSED + FAILED))"

if [ $FAILED -eq 0 ]; then
    echo ""
    echo "All tests PASSED!"
    exit 0
else
    echo ""
    echo "Some tests FAILED!"
    exit 1
fi
