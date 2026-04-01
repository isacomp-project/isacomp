#!/bin/bash
# Build RISC-V RV64IMC tests (I, M, and C extension tests)
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
echo "Building RV64IMC Tests for ISAComp"
echo "======================================================================"
echo ""

# Build RV64I tests
echo "Building RV64I base instruction tests..."
echo "----------------------------------------"

TESTS_I="add addi sub lui auipc and andi or ori xor xori sll slli srl srli sra srai slt slti sltu sltiu beq bne blt bltu bge bgeu jal jalr lw lh lhu lb lbu sw sh sb ld lwu sd addw addiw subw sllw slliw srlw srliw sraw sraiw"

for test in $TESTS_I; do
    TEST_SRC="${ISA_TESTS}/rv64ui/${test}.S"

    if [ ! -f "$TEST_SRC" ]; then
        echo "  SKIP $test (no source)"
        SKIP=$((SKIP + 1))
        continue
    fi

    TEST_ELF="$OUTPUT_DIR/rv64ui-isacomp-${test}"
    TEST_BIN="${TEST_ELF}.bin"
    TEST_HEX="${TEST_ELF}.hex"

    printf "  Building %-12s ... " "$test"

    # Compile with ISAComp link address (0x0)
    if $GCC -march=rv64i -mabi=lp64 -static -mcmodel=medany \
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

            # Convert to hex for $readmemh (64-bit doublewords)
            python3 -c "
with open('$TEST_BIN', 'rb') as f:
    data = f.read()
while len(data) % 8:
    data += b'\\x00'
with open('$TEST_HEX', 'w') as f:
    for i in range(0, len(data), 8):
        dword = 0
        for j in range(8):
            dword |= data[i+j] << (j*8)
        f.write('%016x\n' % dword)
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

# Build RV64M tests
echo ""
echo "Building RV64M multiply/divide tests..."
echo "----------------------------------------"

TESTS_M="mul mulh mulhsu mulhu div divu rem remu mulw divw divuw remw remuw"

for test in $TESTS_M; do
    TEST_SRC="${ISA_TESTS}/rv64um/${test}.S"

    if [ ! -f "$TEST_SRC" ]; then
        echo "  SKIP $test (no source)"
        SKIP=$((SKIP + 1))
        continue
    fi

    TEST_ELF="$OUTPUT_DIR/rv64um-isacomp-${test}"
    TEST_BIN="${TEST_ELF}.bin"
    TEST_HEX="${TEST_ELF}.hex"

    printf "  Building %-12s ... " "$test"

    # Compile with M extension
    if $GCC -march=rv64im -mabi=lp64 -static -mcmodel=medany \
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
while len(data) % 8:
    data += b'\\x00'
with open('$TEST_HEX', 'w') as f:
    for i in range(0, len(data), 8):
        dword = 0
        for j in range(8):
            dword |= data[i+j] << (j*8)
        f.write('%016x\n' % dword)
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

# Build RV64C compressed tests
echo ""
echo "Building RV64C compressed instruction tests..."
echo "------------------------------------------------"

# The RV64UC test suite has a single rvc.S test that covers all compressed instructions
TEST_SRC="${ISA_TESTS}/rv64uc/rvc.S"

if [ -f "$TEST_SRC" ]; then
    TEST_ELF="$OUTPUT_DIR/rv64uc-isacomp-rvc"
    TEST_BIN="${TEST_ELF}.bin"
    TEST_HEX="${TEST_ELF}.hex"
    TEST_DIS="${TEST_ELF}.dis"

    printf "  Building rvc           ... "

    # Compile with C extension enabled
    if $GCC -march=rv64ic -mabi=lp64 -static -mcmodel=medany \
         -fvisibility=hidden -nostdlib -nostartfiles \
         -I${ISACOMP_ENV} -I${MACROS_DIR} \
         -T${ISACOMP_ENV}/link.ld \
         ${TEST_SRC} -o ${TEST_ELF} 2>/dev/null; then

        PASS_ADDR=$($NM $TEST_ELF 2>/dev/null | grep " pass$" | awk '{print $1}' || echo "")
        FAIL_ADDR=$($NM $TEST_ELF 2>/dev/null | grep " fail$" | awk '{print $1}' || echo "")

        if [ -n "$PASS_ADDR" ] && [ -n "$FAIL_ADDR" ]; then
            $OBJCOPY -O binary $TEST_ELF $TEST_BIN

            # Create hex file for simulation (64-bit doublewords)
            python3 -c "
with open('$TEST_BIN', 'rb') as f:
    data = f.read()
while len(data) % 8:
    data += b'\\x00'
with open('$TEST_HEX', 'w') as f:
    for i in range(0, len(data), 8):
        dword = 0
        for j in range(8):
            dword |= data[i+j] << (j*8)
        f.write('%016x\n' % dword)
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
