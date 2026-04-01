#!/bin/bash
# Build 6502 tests for ISAComp pipelined processor
#
# This script assembles all 6502 test programs using ACME assembler
# and generates hex files suitable for loading into ISAComp simulation.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

ISA_DIR="isa"
OUTPUT_DIR="bin"

# List of tests to build
TESTS="lda sta adc sbc cmp and shift incdec branch jmp transfer stack flags ldxy hazard bit memory edge pipeline jsrts stxy ora eor nop decimal brk"

echo "========================================"
echo "Building 6502 ISAComp Tests"
echo "========================================"
echo ""

# Check for ACME assembler
if ! command -v acme &> /dev/null; then
    echo "ERROR: ACME assembler not found."
    echo "Install with: apt install acme"
    exit 1
fi

# Create output directory
mkdir -p "$OUTPUT_DIR"

PASS=0
FAIL=0
FAILED_TESTS=""

for test in $TESTS; do
    TEST_SRC="$ISA_DIR/${test}.s"
    TEST_BIN="$OUTPUT_DIR/${test}.bin"
    TEST_SYM="$OUTPUT_DIR/${test}.sym"
    TEST_HEX="$OUTPUT_DIR/${test}.hex"
    TEST_ADDRS="$OUTPUT_DIR/${test}.addrs"

    if [ ! -f "$TEST_SRC" ]; then
        echo "  SKIP: $test (no source file)"
        continue
    fi

    echo "Building ${test}..."

    # Assemble with ACME
    if acme --cpu 6502 -o "$TEST_BIN" -l "$TEST_SYM" "$TEST_SRC" 2>&1; then
        # Convert binary to hex format for $readmemh
        # Programs start at $0400, so we prefix with the address
        python3 -c "
import sys
with open('$TEST_BIN', 'rb') as f:
    data = f.read()
with open('$TEST_HEX', 'w') as f:
    f.write('@0400\n')  # Start address
    for b in data:
        f.write(f'{b:02X}\n')
"

        # Extract pass/fail addresses from symbol file
        # ACME symbol format: <tab>label<tab>= $addr<tab>; ...
        PASS_ADDR=$(grep -E $'^\tpass\t' "$TEST_SYM" | sed -E 's/.*= \$([0-9A-Fa-f]+).*/\1/' | tr 'a-f' 'A-F')
        FAIL_ADDR=$(grep -E $'^\tfail\t' "$TEST_SYM" | sed -E 's/.*= \$([0-9A-Fa-f]+).*/\1/' | tr 'a-f' 'A-F')

        # Default addresses if not found
        [ -z "$PASS_ADDR" ] && PASS_ADDR="FF00"
        [ -z "$FAIL_ADDR" ] && FAIL_ADDR="FF10"

        echo "  Assembled: $TEST_HEX ($(wc -l < "$TEST_HEX") bytes)"
        echo "  Pass: 0x$PASS_ADDR, Fail: 0x$FAIL_ADDR"

        # Store addresses
        echo "$PASS_ADDR $FAIL_ADDR" > "$TEST_ADDRS"

        PASS=$((PASS + 1))
    else
        echo "  FAIL: Assembly failed for $test"
        FAIL=$((FAIL + 1))
        FAILED_TESTS="$FAILED_TESTS $test"
    fi
done

echo ""
echo "========================================"
echo "Build Results: $PASS PASS, $FAIL FAIL"
if [ -n "$FAILED_TESTS" ]; then
    echo "Failed tests:$FAILED_TESTS"
fi
echo "========================================"

if [ $FAIL -gt 0 ]; then
    exit 1
fi

if [ $PASS -eq 0 ]; then
    echo "ERROR: No tests built"
    exit 1
fi

echo ""
echo "Tests built successfully in: $OUTPUT_DIR/"
exit 0
