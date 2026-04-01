#!/bin/bash
# Build ISAComp RISC-V tests with virtual memory (v environment)
# These tests use the riscv-tests v environment with Sv32 page tables

set -e

RISCV_PREFIX="riscv64-unknown-elf-"
GCC="${RISCV_PREFIX}gcc"
OBJCOPY="${RISCV_PREFIX}objcopy"
OBJDUMP="${RISCV_PREFIX}objdump"
NM="${RISCV_PREFIX}nm"

TEST_DIR="isa/riscv32/riscv-tests/isa"
ENV_DIR="isa/riscv32/riscv-tests/env/v"
LOCAL_ENV_DIR="isa/riscv32/mmu/v_env"  # Local freestanding copies
OUTPUT_DIR="isa/riscv32/riscv-tests/isa"

# Tests to compile
TESTS="add addi sub lui auipc and andi or ori xor xori sll slli srl srli sra srai slt slti sltu sltiu beq bne blt bltu bge bgeu jal jalr lw lh lhu lb lbu sw sh sb"

PASS=0
FAIL=0
SKIP=0

echo "Building ISAComp RISC-V VM tests (v environment)..."
echo "===================================================="

# Create output directory
mkdir -p "$OUTPUT_DIR"

for test in $TESTS; do
    TEST_SRC="$TEST_DIR/rv32ui/${test}.S"

    if [ ! -f "$TEST_SRC" ]; then
        echo "⚠  Skipping $test: No test source"
        SKIP=$((SKIP + 1))
        continue
    fi

    TEST_ELF="$OUTPUT_DIR/rv32ui-v-${test}"
    TEST_BIN="$OUTPUT_DIR/rv32ui-v-${test}.bin"
    TEST_HEX="$OUTPUT_DIR/rv32ui-v-${test}.hex"

    printf "Building %-10s ... " "$test"

    # Generate entropy from test name
    ENTROPY=$(echo "$test" | md5sum | cut -c 1-7)

    # Compile with v environment (includes VM setup code)
    # Use local freestanding source files but include paths from riscv-tests
    # Set ISACOMP_DRAM_BASE=0x0 for isacomp address space (vm.c uses this)
    $GCC -march=rv32g -mabi=ilp32 -static -mcmodel=medany -fvisibility=hidden \
         -nostdlib -nostartfiles -ffreestanding \
         -DENTROPY=0x${ENTROPY} -DISACOMP_DRAM_BASE=0x0 -std=gnu99 -O2 \
         -I${ENV_DIR} -I${TEST_DIR}/macros/scalar \
         -T${LOCAL_ENV_DIR}/link_isacomp.ld \
         ${LOCAL_ENV_DIR}/entry.S ${LOCAL_ENV_DIR}/vm.c ${LOCAL_ENV_DIR}/string.c \
         $TEST_SRC -o $TEST_ELF 2>&1

    if [ ! -f "$TEST_ELF" ]; then
        echo "FAILED (compilation)"
        FAIL=$((FAIL + 1))
        continue
    fi

    # Extract pass/fail addresses (v tests use ecall)
    # The userstart label is where test code begins
    USERSTART=$($NM $TEST_ELF 2>/dev/null | grep " userstart" | awk '{print $1}' || echo "")

    echo "OK (userstart=0x$USERSTART)"

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
    $OBJDUMP -d $TEST_ELF > ${TEST_ELF}.dump 2>/dev/null || true

    PASS=$((PASS + 1))
done

echo ""
echo "===================================================="
echo "Results: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
echo "===================================================="
echo "Tests are in: $OUTPUT_DIR/rv32ui-v-*"
