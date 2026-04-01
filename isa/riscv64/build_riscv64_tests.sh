#!/bin/bash
# Build ISAComp RISC-V RV64IMC tests (I, M, and C extensions)
# ISAComp tests start at address 0x0 instead of 0x80000000

RISCV_PREFIX="riscv64-unknown-elf-"
GCC="${RISCV_PREFIX}gcc"
OBJCOPY="${RISCV_PREFIX}objcopy"
OBJDUMP="${RISCV_PREFIX}objdump"
NM="${RISCV_PREFIX}nm"

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_DIR="$SCRIPT_DIR/riscv-tests/isa"
OUTPUT_DIR="$TEST_DIR"

# Tests to compile (must have matching .isa files)
# Complete RV64I instruction set (49 instructions)
# Base RV64I (adapted from RV32I)
TESTS_BASE="add addi sub lui auipc and andi or ori xor xori sll slli srl srli srai sra slt slti sltu sltiu beq bne blt bltu bge bgeu jal jalr"

# Loads and stores
TESTS_MEM="lw lh lhu lb lbu lwu ld sw sh sb sd"

# RV64I-specific word operations
TESTS_WORD="addiw slliw srliw sraiw addw subw sllw srlw sraw"

# M extension instructions (13 instructions for RV64)
TESTS_M="mul mulh mulhsu mulhu div divu rem remu mulw divw divuw remw remuw"

PASS=0
FAIL=0
SKIP=0
FAILED_TESTS=""

build_test() {
    local test=$1
    local test_dir=$2
    local prefix=$3
    local arch=$4
    local isa_dir=$5

    local ISA_FILE="$isa_dir/${test}.isa"
    local TEST_SRC="$TEST_DIR/${test_dir}/${test}.S"
    local TEST_ELF="$OUTPUT_DIR/${prefix}-isacomp-${test}"
    local TEST_BIN="${TEST_ELF}.bin"
    local TEST_HEX="${TEST_ELF}.hex"

    if [ ! -f "$ISA_FILE" ]; then
        echo "  Skipping $test: No ISA definition ($ISA_FILE)"
        SKIP=$((SKIP + 1))
        return
    fi

    if [ ! -f "$TEST_SRC" ]; then
        echo "  Skipping $test: No test source ($TEST_SRC)"
        SKIP=$((SKIP + 1))
        return
    fi

    printf "  %-12s ... " "$test"

    # Compile with ISAComp link address (0x0)
    if ! $GCC -march=${arch}_zicsr -mabi=lp64 -static -mcmodel=medany -fvisibility=hidden \
         -nostdlib -nostartfiles \
         -I${SCRIPT_DIR}/riscv-tests-env/isacomp -I${TEST_DIR}/macros/scalar \
         -T${SCRIPT_DIR}/riscv-tests-env/isacomp/link.ld \
         -Wl,--defsym,__stack_top=0x10000 \
         $TEST_SRC -o $TEST_ELF 2>/dev/null; then
        echo "FAILED (compile)"
        FAIL=$((FAIL + 1))
        FAILED_TESTS="$FAILED_TESTS $test"
        return
    fi

    # Extract pass/fail addresses
    PASS_ADDR=$($NM $TEST_ELF 2>/dev/null | grep " pass$" | awk '{print $1}')
    FAIL_ADDR=$($NM $TEST_ELF 2>/dev/null | grep " fail$" | awk '{print $1}')

    if [ -z "$PASS_ADDR" ] || [ -z "$FAIL_ADDR" ]; then
        echo "FAILED (no symbols)"
        FAIL=$((FAIL + 1))
        FAILED_TESTS="$FAILED_TESTS $test"
        return
    fi

    # Create binary and hex files
    if ! $OBJCOPY -O binary $TEST_ELF $TEST_BIN 2>/dev/null; then
        echo "FAILED (binary)"
        FAIL=$((FAIL + 1))
        FAILED_TESTS="$FAILED_TESTS $test"
        return
    fi

    if ! $OBJCOPY -O ihex $TEST_ELF $TEST_HEX 2>/dev/null; then
        echo "FAILED (hex)"
        FAIL=$((FAIL + 1))
        FAILED_TESTS="$FAILED_TESTS $test"
        return
    fi

    # Store addresses in a separate file for easy lookup
    echo "$PASS_ADDR $FAIL_ADDR" > ${TEST_ELF}.addrs

    echo "OK (pass=0x$PASS_ADDR)"
    PASS=$((PASS + 1))
}

echo "Building ISAComp RISC-V RV64IMC tests..."
echo "======================================"
echo ""
echo "Instruction count:"
echo "  RV64I base: 49 instructions"
echo "  M extension: 13 instructions"
echo "  C extension: rvc test suite"
echo ""

# Build RV64I base tests
echo "Building RV64I base instruction tests..."
echo "----------------------------------------"
for test in $TESTS_BASE $TESTS_MEM $TESTS_WORD; do
    build_test "$test" "rv64ui" "rv64ui" "rv64i" "$SCRIPT_DIR"
done

# Build RV64M multiply/divide tests
echo ""
echo "Building RV64M multiply/divide tests..."
echo "----------------------------------------"
for test in $TESTS_M; do
    build_test "$test" "rv64um" "rv64um" "rv64im" "$SCRIPT_DIR/m"
done

# Build RV64C compressed tests
echo ""
echo "Building RV64C compressed instruction tests..."
echo "-----------------------------------------------"
TEST_SRC="$TEST_DIR/rv64uc/rvc.S"
if [ -f "$TEST_SRC" ] && [ -d "$SCRIPT_DIR/c" ]; then
    TEST_ELF="$OUTPUT_DIR/rv64uc-isacomp-rvc"
    TEST_BIN="${TEST_ELF}.bin"
    TEST_HEX="${TEST_ELF}.hex"

    printf "  %-12s ... " "rvc"

    if $GCC -march=rv64ic_zicsr -mabi=lp64 -static -mcmodel=medany -fvisibility=hidden \
         -nostdlib -nostartfiles \
         -I${SCRIPT_DIR}/riscv-tests-env/isacomp -I${TEST_DIR}/macros/scalar \
         -T${SCRIPT_DIR}/riscv-tests-env/isacomp/link.ld \
         -Wl,--defsym,__stack_top=0x10000 \
         $TEST_SRC -o $TEST_ELF 2>/dev/null; then

        PASS_ADDR=$($NM $TEST_ELF 2>/dev/null | grep " pass$" | awk '{print $1}')
        FAIL_ADDR=$($NM $TEST_ELF 2>/dev/null | grep " fail$" | awk '{print $1}')

        if [ -n "$PASS_ADDR" ] && [ -n "$FAIL_ADDR" ]; then
            $OBJCOPY -O binary $TEST_ELF $TEST_BIN 2>/dev/null
            $OBJCOPY -O ihex $TEST_ELF $TEST_HEX 2>/dev/null
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
else
    echo "  Skipping rvc: No test source or C extension ISA definitions"
    SKIP=$((SKIP + 1))
fi

echo ""
echo "======================================"
echo "Results: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
if [ -n "$FAILED_TESTS" ]; then
    echo "Failed tests:$FAILED_TESTS"
fi
echo "======================================"

# Exit with error if any tests failed or no tests passed
if [ $FAIL -gt 0 ]; then
    echo "FAILED: $FAIL test(s) failed to build"
    exit 1
fi

if [ $PASS -eq 0 ]; then
    echo "FAILED: No tests built successfully (all skipped)"
    echo ""
    echo "Note: To get RISC-V test sources, initialize the riscv-tests submodule:"
    echo "  git submodule update --init --recursive"
    exit 1
fi

echo "SUCCESS: All $PASS tests built successfully"
echo "Tests are in: $OUTPUT_DIR/rv64ui-isacomp-*, rv64um-isacomp-*, rv64uc-isacomp-*"
exit 0
