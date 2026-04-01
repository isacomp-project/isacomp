#!/bin/bash
# Build RISC-V RV32IMC tests (I, M, and C extension tests)
# Tests start at address 0x0 (ISAComp convention)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}/../../.."

RISCV_PREFIX="riscv64-unknown-elf-"
GCC="${RISCV_PREFIX}gcc"
OBJCOPY="${RISCV_PREFIX}objcopy"
OBJDUMP="${RISCV_PREFIX}objdump"
NM="${RISCV_PREFIX}nm"

# Check for toolchain
if ! command -v $GCC &> /dev/null; then
    echo "ERROR: RISC-V toolchain not found. Install with: apt install gcc-riscv64-unknown-elf"
    exit 1
fi

# Test locations
ISA_TESTS="${PROJECT_ROOT}/riscv-tests/isa"
ISACOMP_ENV="${ISA_TESTS}/../env/isacomp"
MACROS_DIR="${ISA_TESTS}/macros/scalar"
OUTPUT_DIR="${SCRIPT_DIR}/tests"

# Create output directory
mkdir -p "$OUTPUT_DIR"

PASS=0
FAIL=0
SKIP=0

echo "======================================================================"
echo "Building RV32IMC Tests for ISAComp"
echo "======================================================================"
echo ""

# Build RV32I tests
echo "Building RV32I base instruction tests..."
echo "----------------------------------------"

TESTS_I="add addi sub lui auipc and andi or ori xor xori sll slli srl srli sra srai slt slti sltu sltiu beq bne blt bltu bge bgeu jal jalr lw lh lhu lb lbu sw sh sb"

for test in $TESTS_I; do
    TEST_SRC="${ISA_TESTS}/rv32ui/${test}.S"

    if [ ! -f "$TEST_SRC" ]; then
        echo "  SKIP $test (no source)"
        SKIP=$((SKIP + 1))
        continue
    fi

    TEST_ELF="$OUTPUT_DIR/rv32ui-isacomp-${test}"
    TEST_BIN="${TEST_ELF}.bin"
    TEST_HEX="${TEST_ELF}.hex"

    printf "  Building %-12s ... " "$test"

    # Compile with ISAComp link address (0x0)
    if $GCC -march=rv32i -mabi=ilp32 -static -mcmodel=medany \
         -fvisibility=hidden -nostdlib -nostartfiles \
         -I${ISACOMP_ENV} -I${MACROS_DIR} \
         -T${ISACOMP_ENV}/link.ld \
         ${TEST_SRC} -o ${TEST_ELF} 2>/dev/null; then

        # Extract pass/fail addresses
        PASS_ADDR=$($NM $TEST_ELF 2>/dev/null | grep " pass$" | awk '{print $1}' || echo "")
        FAIL_ADDR=$($NM $TEST_ELF 2>/dev/null | grep " fail$" | awk '{print $1}' || echo "")

        if [ -n "$PASS_ADDR" ] && [ -n "$FAIL_ADDR" ]; then
            # Create binary
            $OBJCOPY -O binary $TEST_ELF $TEST_BIN

            # Convert to hex for $readmemh
            python3 -c "
with open('$TEST_BIN', 'rb') as f:
    data = f.read()
while len(data) % 4:
    data += b'\\x00'
with open('$TEST_HEX', 'w') as f:
    for i in range(0, len(data), 4):
        word = data[i] | (data[i+1] << 8) | (data[i+2] << 16) | (data[i+3] << 24)
        f.write('%08x\n' % word)
"
            # Save addresses
            echo "$PASS_ADDR $FAIL_ADDR" > ${TEST_ELF}.addrs

            echo "OK (pass=0x$PASS_ADDR)"
            PASS=$((PASS + 1))
        else
            echo "FAILED (no symbols)"
            FAIL=$((FAIL + 1))
        fi
    else
        echo "FAILED (compile)"
        FAIL=$((FAIL + 1))
    fi
done

# Build RV32M tests
echo ""
echo "Building RV32M multiply/divide tests..."
echo "----------------------------------------"

TESTS_M="mul mulh mulhsu mulhu div divu rem remu"

for test in $TESTS_M; do
    TEST_SRC="${ISA_TESTS}/rv32um/${test}.S"

    if [ ! -f "$TEST_SRC" ]; then
        echo "  SKIP $test (no source)"
        SKIP=$((SKIP + 1))
        continue
    fi

    TEST_ELF="$OUTPUT_DIR/rv32um-isacomp-${test}"
    TEST_BIN="${TEST_ELF}.bin"
    TEST_HEX="${TEST_ELF}.hex"

    printf "  Building %-12s ... " "$test"

    # Compile with M extension
    if $GCC -march=rv32im -mabi=ilp32 -static -mcmodel=medany \
         -fvisibility=hidden -nostdlib -nostartfiles \
         -I${ISACOMP_ENV} -I${MACROS_DIR} \
         -T${ISACOMP_ENV}/link.ld \
         ${TEST_SRC} -o ${TEST_ELF} 2>/dev/null; then

        PASS_ADDR=$($NM $TEST_ELF 2>/dev/null | grep " pass$" | awk '{print $1}' || echo "")
        FAIL_ADDR=$($NM $TEST_ELF 2>/dev/null | grep " fail$" | awk '{print $1}' || echo "")

        if [ -n "$PASS_ADDR" ] && [ -n "$FAIL_ADDR" ]; then
            $OBJCOPY -O binary $TEST_ELF $TEST_BIN
            python3 -c "
with open('$TEST_BIN', 'rb') as f:
    data = f.read()
while len(data) % 4:
    data += b'\\x00'
with open('$TEST_HEX', 'w') as f:
    for i in range(0, len(data), 4):
        word = data[i] | (data[i+1] << 8) | (data[i+2] << 16) | (data[i+3] << 24)
        f.write('%08x\n' % word)
"
            echo "$PASS_ADDR $FAIL_ADDR" > ${TEST_ELF}.addrs
            echo "OK (pass=0x$PASS_ADDR)"
            PASS=$((PASS + 1))
        else
            echo "FAILED (no symbols)"
            FAIL=$((FAIL + 1))
        fi
    else
        echo "FAILED (compile)"
        FAIL=$((FAIL + 1))
    fi
done

# Build RV32C compressed tests
echo ""
echo "Building RV32C compressed instruction tests..."
echo "------------------------------------------------"

# The RV32UC test suite has a single rvc.S test that covers all compressed instructions
TEST_SRC="${ISA_TESTS}/rv32uc/rvc.S"

if [ -f "$TEST_SRC" ]; then
    TEST_ELF="$OUTPUT_DIR/rv32uc-isacomp-rvc"
    TEST_BIN="${TEST_ELF}.bin"
    TEST_HEX="${TEST_ELF}.hex"
    TEST_DIS="${TEST_ELF}.dis"

    printf "  Building rvc           ... "

    # Compile with C extension enabled
    if $GCC -march=rv32ic -mabi=ilp32 -static -mcmodel=medany \
         -fvisibility=hidden -nostdlib -nostartfiles \
         -I${ISACOMP_ENV} -I${MACROS_DIR} \
         -T${ISACOMP_ENV}/link.ld \
         ${TEST_SRC} -o ${TEST_ELF} 2>/dev/null; then

        PASS_ADDR=$($NM $TEST_ELF 2>/dev/null | grep " pass$" | awk '{print $1}' || echo "")
        FAIL_ADDR=$($NM $TEST_ELF 2>/dev/null | grep " fail$" | awk '{print $1}' || echo "")

        if [ -n "$PASS_ADDR" ] && [ -n "$FAIL_ADDR" ]; then
            $OBJCOPY -O binary $TEST_ELF $TEST_BIN

            # Create hex file for simulation
            python3 -c "
with open('$TEST_BIN', 'rb') as f:
    data = f.read()
while len(data) % 4:
    data += b'\\x00'
with open('$TEST_HEX', 'w') as f:
    for i in range(0, len(data), 4):
        word = data[i] | (data[i+1] << 8) | (data[i+2] << 16) | (data[i+3] << 24)
        f.write('%08x\n' % word)
"
            echo "$PASS_ADDR $FAIL_ADDR" > ${TEST_ELF}.addrs

            # Create disassembly to show compressed instructions
            $OBJDUMP -d $TEST_ELF > $TEST_DIS 2>/dev/null || true

            echo "OK (pass=0x$PASS_ADDR)"
            PASS=$((PASS + 1))
        else
            echo "FAILED (no symbols)"
            FAIL=$((FAIL + 1))
        fi
    else
        echo "FAILED (compile)"
        FAIL=$((FAIL + 1))
    fi
else
    echo "  SKIP rvc (no source)"
    SKIP=$((SKIP + 1))
fi

echo ""
echo "======================================================================"
echo "Build Summary: $PASS built, $FAIL failed, $SKIP skipped"
echo "======================================================================"
echo "Tests are in: $OUTPUT_DIR/"
echo ""

if [ $FAIL -gt 0 ]; then
    exit 1
fi

exit 0
