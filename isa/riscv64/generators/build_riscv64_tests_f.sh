#!/bin/bash
# Build RISC-V RV64F extension tests using ISAComp's environment
# These tests verify single-precision floating-point instructions for RV64

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RISCV_PREFIX="riscv64-unknown-elf-"
GCC="${RISCV_PREFIX}gcc"
OBJCOPY="${RISCV_PREFIX}objcopy"
OBJDUMP="${RISCV_PREFIX}objdump"
NM="${RISCV_PREFIX}nm"

# Use ISAComp's test environment (with FP support) - separate from submodule
ISACOMP_ENV="${SCRIPT_DIR}/../riscv-tests-env/isacomp"
# encoding.h is in parent of isacomp env
ENCODING_DIR="${SCRIPT_DIR}/../riscv-tests-env"
# Test sources from riscv-tests submodule
TEST_SRC_DIR="${SCRIPT_DIR}/../riscv-tests/isa/rv64uf"
MACROS_DIR="${SCRIPT_DIR}/../riscv-tests/isa/macros/scalar"
OUTPUT_DIR="${SCRIPT_DIR}/../riscv-tests/isa"

# RV64F tests available (same as RV32F, some test 64-bit conversions)
# Note: move.S tests fmv.x.w/fmv.w.x, recoding tests NaN handling
# fcvt.S and fcvt_w.S test both 32-bit and 64-bit integer conversions
TESTS="fadd fclass fcmp fcvt fcvt_w fdiv fmadd fmin ldst move recoding"

echo "Building RISC-V RV64F extension tests..."
echo "========================================="
echo ""

# Create output directory
mkdir -p "$OUTPUT_DIR"

SUCCESS_COUNT=0
FAIL_COUNT=0

for test in $TESTS; do
    TEST_SRC="${TEST_SRC_DIR}/${test}.S"

    if [ ! -f "$TEST_SRC" ]; then
        echo "  Skipping $test: No source file"
        continue
    fi

    TEST_ELF="$OUTPUT_DIR/rv64uf-isacomp-${test}"
    TEST_BIN="$OUTPUT_DIR/rv64uf-isacomp-${test}.bin"
    TEST_HEX="$OUTPUT_DIR/rv64uf-isacomp-${test}.hex"
    TEST_DUMP="$OUTPUT_DIR/rv64uf-isacomp-${test}.dump"
    TEST_ADDRS="$OUTPUT_DIR/rv64uf-isacomp-${test}.addrs"

    printf "Building %-12s ... " "$test"

    # Compile with ISAComp environment
    # Use rv64imf_zicsr to enable I, M, F extensions and CSR instructions
    # M extension is needed for some test macros that use mul
    COMPILE_OUTPUT=$($GCC -march=rv64imf_zicsr -mabi=lp64f -static -mcmodel=medany \
         -fvisibility=hidden -nostdlib -nostartfiles \
         -I${ISACOMP_ENV} -I${MACROS_DIR} -I${ENCODING_DIR} \
         -T${ISACOMP_ENV}/link.ld \
         ${TEST_SRC} -o ${TEST_ELF} 2>&1) || true

    if [ ! -f "$TEST_ELF" ]; then
        echo "FAILED (compilation)"
        echo "  Error: $COMPILE_OUTPUT" | head -5
        FAIL_COUNT=$((FAIL_COUNT + 1))
        continue
    fi

    # Extract pass/fail addresses
    PASS_ADDR=$($NM $TEST_ELF 2>/dev/null | grep " pass$" | awk '{print $1}' || echo "")
    FAIL_ADDR=$($NM $TEST_ELF 2>/dev/null | grep " fail$" | awk '{print $1}' || echo "")

    if [ -z "$PASS_ADDR" ] || [ -z "$FAIL_ADDR" ]; then
        echo "FAILED (no pass/fail symbols)"
        rm -f "$TEST_ELF"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        continue
    fi

    # Create binary
    $OBJCOPY -O binary $TEST_ELF $TEST_BIN

    # Convert to hex format for $readmemh (64-bit words, little-endian)
    python3 -c "
import sys
with open('$TEST_BIN', 'rb') as f:
    data = f.read()
# Pad to multiple of 8 (64-bit words)
while len(data) % 8:
    data += b'\\x00'
with open('$TEST_HEX', 'w') as f:
    for i in range(0, len(data), 8):
        word = (data[i] | (data[i+1] << 8) | (data[i+2] << 16) | (data[i+3] << 24) |
                (data[i+4] << 32) | (data[i+5] << 40) | (data[i+6] << 48) | (data[i+7] << 56))
        f.write('%016x\n' % word)
"

    # Create disassembly
    $OBJDUMP -d $TEST_ELF > $TEST_DUMP 2>/dev/null || true

    # Save addresses
    echo "$PASS_ADDR $FAIL_ADDR" > $TEST_ADDRS

    echo "OK (pass=0x$PASS_ADDR, fail=0x$FAIL_ADDR)"
    SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
done

echo ""
echo "========================================="
echo "Build complete!"
echo "  Success: $SUCCESS_COUNT tests"
echo "  Failed:  $FAIL_COUNT tests"
echo "  Output:  $OUTPUT_DIR/rv64uf-isacomp-*"
echo ""
