#!/bin/bash
# Build RISC-V VM tests using ISAComp's VM environment
# These tests set up Sv32 identity-mapped page tables and run in S-mode

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RISCV_PREFIX="riscv64-unknown-elf-"
GCC="${RISCV_PREFIX}gcc"
OBJCOPY="${RISCV_PREFIX}objcopy"
OBJDUMP="${RISCV_PREFIX}objdump"
NM="${RISCV_PREFIX}nm"

# Use ISAComp's VM environment (assembly-only, no C library needed)
VM_ENV="${SCRIPT_DIR}/../mmu/env"
TEST_SRC_DIR="${SCRIPT_DIR}/../riscv-tests/isa/rv32ui"
MACROS_DIR="${SCRIPT_DIR}/../riscv-tests/isa/macros/scalar"
OUTPUT_DIR="${SCRIPT_DIR}/../riscv-tests/isa"

# Tests to compile (RV32I instruction set)
TESTS="add addi sub lui auipc and andi or ori xor xori sll slli srl srli sra srai slt slti sltu sltiu beq bne blt bltu bge bgeu jal jalr lw lh lhu lb lbu sw sh sb"

echo "Building RISC-V VM tests using ISAComp VM environment..."
echo "========================================================="

# Create output directory
mkdir -p "$OUTPUT_DIR"

for test in $TESTS; do
    TEST_SRC="${TEST_SRC_DIR}/${test}.S"

    if [ ! -f "$TEST_SRC" ]; then
        echo "  Skipping $test: No source file"
        continue
    fi

    TEST_ELF="$OUTPUT_DIR/rv32ui-vm-${test}"
    TEST_BIN="$OUTPUT_DIR/rv32ui-vm-${test}.bin"
    TEST_HEX="$OUTPUT_DIR/rv32ui-vm-${test}.hex"
    TEST_DUMP="$OUTPUT_DIR/rv32ui-vm-${test}.dump"
    TEST_ADDRS="$OUTPUT_DIR/rv32ui-vm-${test}.addrs"

    printf "Building %-10s ... " "$test"

    # Compile with ISAComp VM environment (assembly-only)
    $GCC -march=rv32i_zicsr -mabi=ilp32 -static -mcmodel=medany \
         -fvisibility=hidden -nostdlib -nostartfiles \
         -I${VM_ENV} -I${MACROS_DIR} \
         -T${VM_ENV}/link.ld \
         ${TEST_SRC} -o ${TEST_ELF} 2>&1 | grep -v "warning:" || true

    if [ ! -f "$TEST_ELF" ]; then
        echo "FAILED (compilation)"
        continue
    fi

    # Extract pass/fail addresses
    PASS_ADDR=$($NM $TEST_ELF 2>/dev/null | grep " pass$" | awk '{print $1}' || echo "")
    FAIL_ADDR=$($NM $TEST_ELF 2>/dev/null | grep " fail$" | awk '{print $1}' || echo "")

    if [ -z "$PASS_ADDR" ] || [ -z "$FAIL_ADDR" ]; then
        echo "FAILED (no pass/fail symbols)"
        rm -f "$TEST_ELF"
        continue
    fi

    # Create binary
    $OBJCOPY -O binary $TEST_ELF $TEST_BIN

    # Convert to hex format for $readmemh (32-bit words, little-endian)
    python3 -c "
import sys
with open('$TEST_BIN', 'rb') as f:
    data = f.read()
# Pad to multiple of 4
while len(data) % 4:
    data += b'\\x00'
with open('$TEST_HEX', 'w') as f:
    for i in range(0, len(data), 4):
        word = data[i] | (data[i+1] << 8) | (data[i+2] << 16) | (data[i+3] << 24)
        f.write('%08x\n' % word)
"

    # Create disassembly
    $OBJDUMP -d $TEST_ELF > $TEST_DUMP 2>/dev/null || true

    # Save addresses
    echo "$PASS_ADDR $FAIL_ADDR" > $TEST_ADDRS

    echo "OK (pass=0x$PASS_ADDR, fail=0x$FAIL_ADDR)"
done

echo ""
echo "================================================="
echo "Build complete! Tests in: $OUTPUT_DIR/rv32ui-v-*"
