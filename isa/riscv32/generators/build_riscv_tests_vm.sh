#!/bin/bash
# Build ISACompV RISC-V tests (with virtual memory)
# ISACompV tests use virtual memory and start with page tables

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RISCV_PREFIX="riscv64-unknown-elf-"
GCC="${RISCV_PREFIX}gcc"
OBJCOPY="${RISCV_PREFIX}objcopy"
OBJDUMP="${RISCV_PREFIX}objdump"
NM="${RISCV_PREFIX}nm"

# Use ISACompV's own VM-enabled test environment
ISACOMPV_ENV="${SCRIPT_DIR}/../mmu/env"
TEST_DIR="${SCRIPT_DIR}/../riscv-tests/isa"
OUTPUT_DIR="${SCRIPT_DIR}/../riscv-tests/isa"

# Tests to compile (must have matching .isa files)
# Complete RV32I instruction set (37 instructions)
TESTS="add addi sub lui auipc and andi or ori xor xori sll slli srl srli sra srai slt slti sltu sltiu beq bne blt bltu bge bgeu jal jalr lw lh lhu lb lbu sw sh sb"

echo "Building ISACompV RISC-V tests (with virtual memory)..."
echo "=============================="

# Create output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"

for test in $TESTS; do
    if [ ! -f "$TEST_DIR/rv32ui/${test}.S" ]; then
        echo "⚠  Skipping $test: No test source"
        continue
    fi

    TEST_SRC="$TEST_DIR/rv32ui/${test}.S"
    TEST_ELF="$OUTPUT_DIR/rv32ui-isacompv-${test}"
    TEST_BIN="$OUTPUT_DIR/rv32ui-isacompv-${test}.bin"
    TEST_HEX="$OUTPUT_DIR/rv32ui-isacompv-${test}.hex"

    echo "Building ${test}..."

    # Compile with ISACompV link address (with virtual memory)
    # Uses our own isacompv environment that sets up Sv32 page tables
    $GCC -march=rv32i_zicsr -mabi=ilp32 -static -mcmodel=medany -fvisibility=hidden \
         -nostdlib -nostartfiles \
         -I${ISACOMPV_ENV} -I${TEST_DIR}/macros/scalar \
         -T${ISACOMPV_ENV}/link.ld \
         -Wl,--defsym,__stack_top=0x10000 \
         $TEST_SRC -o $TEST_ELF 2>&1 | grep -v "warning: cannot find entry symbol _start" || true

    # Check if compilation succeeded
    if [ ! -f "$TEST_ELF" ]; then
        echo "  ✗ Compilation failed for $test"
        continue
    fi

    # Extract pass/fail addresses
    PASS_ADDR=$($NM $TEST_ELF | grep " pass" | awk '{print $1}')
    FAIL_ADDR=$($NM $TEST_ELF | grep " fail" | awk '{print $1}')

    if [ -z "$PASS_ADDR" ] || [ -z "$FAIL_ADDR" ]; then
        echo "  ⚠  Warning: Could not find pass/fail symbols"
        PASS_ADDR="4ec"
        FAIL_ADDR="4e4"
    fi

    echo "  ✓ Compiled: $TEST_ELF"
    echo "    Pass address: 0x$PASS_ADDR"
    echo "    Fail address: 0x$FAIL_ADDR"

    # Create binary file
    $OBJCOPY -O binary $TEST_ELF $TEST_BIN

    # Convert binary to 32-bit word hex format for $readmemh
    # Each word is 4 bytes in little-endian format
    python3 -c "
import sys
with open('$TEST_BIN', 'rb') as f:
    data = f.read()
# Pad to multiple of 4
while len(data) % 4:
    data += b'\\x00'
with open('$TEST_HEX', 'w') as f:
    for i in range(0, len(data), 4):
        # Little-endian: bytes 0,1,2,3 -> word as bytes[3]bytes[2]bytes[1]bytes[0]
        word = data[i] | (data[i+1] << 8) | (data[i+2] << 16) | (data[i+3] << 24)
        f.write('%08x\n' % word)
"

    # Create disassembly for debugging
    $OBJDUMP -d $TEST_ELF > ${TEST_ELF}.dump 2>/dev/null || true

    # Store addresses in a separate file for easy lookup
    echo "$PASS_ADDR $FAIL_ADDR" > ${TEST_ELF}.addrs
done

echo ""
echo "=============================="
echo "Build complete!"
echo "Tests are in: $OUTPUT_DIR/rv32ui-isacompv-*"
