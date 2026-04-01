#!/bin/bash
# Build ISAComp RISC-V tests
# ISAComp tests start at address 0x0 instead of 0x80000000

RISCV_PREFIX="riscv64-unknown-elf-"
GCC="${RISCV_PREFIX}gcc"
OBJCOPY="${RISCV_PREFIX}objcopy"
OBJDUMP="${RISCV_PREFIX}objdump"
NM="${RISCV_PREFIX}nm"

TEST_DIR="isa/riscv32/riscv-tests/isa"
OUTPUT_DIR="isa/riscv32/riscv-tests/isa"
ISACOMP_ENV="isa/riscv32/riscv-tests-env/isacomp"

# Tests to compile (must have matching .isa files)
# Complete RV32I instruction set (37 instructions)
I_TESTS="add addi sub lui auipc and andi or ori xor xori sll slli srl srli sra srai slt slti sltu sltiu beq bne blt bltu bge bgeu jal jalr lw lh lhu lb lbu sw sh sb"

# RV32M integer multiply/divide tests
M_TESTS="mul mulh mulhsu mulhu div divu rem remu"

# RV32F single-precision floating-point tests
F_TESTS="fadd fcmp fcvt fcvt_w fdiv fmadd fmin fmv fsgnj ldst recoding"

# Option to build only specific extensions
BUILD_I=true
BUILD_M=false
BUILD_F=true

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --i-only)
            BUILD_M=false
            BUILD_F=false
            shift
            ;;
        --m-only)
            BUILD_I=false
            BUILD_M=true
            BUILD_F=false
            shift
            ;;
        --im)
            BUILD_M=true
            BUILD_F=false
            shift
            ;;
        --f-only)
            BUILD_I=false
            BUILD_M=false
            shift
            ;;
        --all)
            BUILD_M=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--i-only] [--m-only] [--im] [--f-only] [--all]"
            exit 1
            ;;
    esac
done

PASS=0
FAIL=0
SKIP=0
FAILED_TESTS=""

echo "Building ISAComp RISC-V tests..."
echo "=============================="

# Create output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"

# Build RV32I tests
if $BUILD_I; then
    echo ""
    echo "=== Building RV32I Tests ==="
    echo ""

    for test in $I_TESTS; do
        if [ ! -f "isa/riscv32/${test}.isa" ]; then
            echo "  Skipping $test: No ISA definition"
            SKIP=$((SKIP + 1))
            continue
        fi

        if [ ! -f "$TEST_DIR/rv32ui/${test}.S" ]; then
            echo "  Skipping $test: No test source"
            SKIP=$((SKIP + 1))
            continue
        fi

        TEST_SRC="$TEST_DIR/rv32ui/${test}.S"
        TEST_ELF="$OUTPUT_DIR/rv32ui-isacomp-${test}"
        TEST_BIN="$OUTPUT_DIR/rv32ui-isacomp-${test}.bin"
        TEST_HEX="$OUTPUT_DIR/rv32ui-isacomp-${test}.hex"

        echo "Building ${test}..."

        # Compile with ISAComp link address (0x0)
        $GCC -march=rv32i_zicsr -mabi=ilp32 -static -mcmodel=medany -fvisibility=hidden \
             -nostdlib -nostartfiles \
             -I${ISACOMP_ENV} -I${TEST_DIR}/macros/scalar \
             -T${ISACOMP_ENV}/link.ld \
             -Wl,--defsym,__stack_top=0x10000 \
             $TEST_SRC -o $TEST_ELF 2>&1 | grep -v "warning: cannot find entry symbol _start" || true

        # Check if compilation succeeded
        if [ ! -f "$TEST_ELF" ]; then
            echo "    Compilation failed for $test"
            FAIL=$((FAIL + 1))
            FAILED_TESTS="$FAILED_TESTS $test"
            continue
        fi

        # Extract pass/fail addresses
        PASS_ADDR=$($NM $TEST_ELF | grep " pass" | awk '{print $1}')
        FAIL_ADDR=$($NM $TEST_ELF | grep " fail" | awk '{print $1}')

        if [ -z "$PASS_ADDR" ] || [ -z "$FAIL_ADDR" ]; then
            echo "    Warning: Could not find pass/fail symbols"
            PASS_ADDR="4ec"
            FAIL_ADDR="4e4"
        fi

        echo "    Compiled: $TEST_ELF"
        echo "    Pass: 0x$PASS_ADDR, Fail: 0x$FAIL_ADDR"

        # Create binary and hex files
        if ! $OBJCOPY -O binary $TEST_ELF $TEST_BIN 2>/dev/null; then
            echo "    Failed to create binary for $test"
            FAIL=$((FAIL + 1))
            FAILED_TESTS="$FAILED_TESTS $test"
            continue
        fi

        if ! $OBJCOPY -O ihex $TEST_ELF $TEST_HEX 2>/dev/null; then
            echo "    Failed to create hex for $test"
            FAIL=$((FAIL + 1))
            FAILED_TESTS="$FAILED_TESTS $test"
            continue
        fi

        # Store addresses in a separate file for easy lookup
        echo "$PASS_ADDR $FAIL_ADDR" > ${TEST_ELF}.addrs

        PASS=$((PASS + 1))
    done
fi

# Build RV32M tests
if $BUILD_M; then
    echo ""
    echo "=== Building RV32M Tests ==="
    echo ""

    for test in $M_TESTS; do
        if [ ! -f "$TEST_DIR/rv32um/${test}.S" ]; then
            echo "  Skipping $test: No test source at $TEST_DIR/rv32um/${test}.S"
            SKIP=$((SKIP + 1))
            continue
        fi

        TEST_SRC="$TEST_DIR/rv32um/${test}.S"
        TEST_ELF="$OUTPUT_DIR/rv32um-isacomp-${test}"
        TEST_BIN="$OUTPUT_DIR/rv32um-isacomp-${test}.bin"
        TEST_HEX="$OUTPUT_DIR/rv32um-isacomp-${test}.hex"

        echo "Building ${test}..."

        # Compile with ISAComp link address (0x0)
        # Use rv32im to enable M extension
        $GCC -march=rv32im_zicsr -mabi=ilp32 -static -mcmodel=medany -fvisibility=hidden \
             -nostdlib -nostartfiles \
             -I${ISACOMP_ENV} -I${TEST_DIR}/macros/scalar \
             -T${ISACOMP_ENV}/link.ld \
             -Wl,--defsym,__stack_top=0x10000 \
             $TEST_SRC -o $TEST_ELF 2>&1 | grep -v "warning: cannot find entry symbol _start" || true

        # Check if compilation succeeded
        if [ ! -f "$TEST_ELF" ]; then
            echo "    Compilation failed for $test"
            FAIL=$((FAIL + 1))
            FAILED_TESTS="$FAILED_TESTS $test"
            continue
        fi

        # Extract pass/fail addresses
        PASS_ADDR=$($NM $TEST_ELF | grep " pass" | awk '{print $1}')
        FAIL_ADDR=$($NM $TEST_ELF | grep " fail" | awk '{print $1}')

        if [ -z "$PASS_ADDR" ] || [ -z "$FAIL_ADDR" ]; then
            echo "    Warning: Could not find pass/fail symbols"
            PASS_ADDR="4ec"
            FAIL_ADDR="4e4"
        fi

        echo "    Compiled: $TEST_ELF"
        echo "    Pass: 0x$PASS_ADDR, Fail: 0x$FAIL_ADDR"

        # Create binary and hex files
        if ! $OBJCOPY -O binary $TEST_ELF $TEST_BIN 2>/dev/null; then
            echo "    Failed to create binary for $test"
            FAIL=$((FAIL + 1))
            FAILED_TESTS="$FAILED_TESTS $test"
            continue
        fi

        if ! $OBJCOPY -O ihex $TEST_ELF $TEST_HEX 2>/dev/null; then
            echo "    Failed to create hex for $test"
            FAIL=$((FAIL + 1))
            FAILED_TESTS="$FAILED_TESTS $test"
            continue
        fi

        # Store addresses in a separate file for easy lookup
        echo "$PASS_ADDR $FAIL_ADDR" > ${TEST_ELF}.addrs

        PASS=$((PASS + 1))
    done
fi

# Build RV32F tests
if $BUILD_F; then
    echo ""
    echo "=== Building RV32F Tests ==="
    echo ""

    for test in $F_TESTS; do
        # Check if we have at least one F ISA file (for basic validation)
        if [ ! -d "isa/riscv32/f" ]; then
            echo "  Skipping F tests: No isa/riscv32/f directory"
            break
        fi

        if [ ! -f "$TEST_DIR/rv32uf/${test}.S" ]; then
            echo "  Skipping $test: No test source at $TEST_DIR/rv32uf/${test}.S"
            SKIP=$((SKIP + 1))
            continue
        fi

        TEST_SRC="$TEST_DIR/rv32uf/${test}.S"
        TEST_ELF="$OUTPUT_DIR/rv32uf-isacomp-${test}"
        TEST_BIN="$OUTPUT_DIR/rv32uf-isacomp-${test}.bin"
        TEST_HEX="$OUTPUT_DIR/rv32uf-isacomp-${test}.hex"

        echo "Building ${test}..."

        # Compile with ISAComp link address (0x0)
        # Use rv32if to enable F extension
        $GCC -march=rv32if_zicsr -mabi=ilp32f -static -mcmodel=medany -fvisibility=hidden \
             -nostdlib -nostartfiles \
             -I${ISACOMP_ENV} -I${TEST_DIR}/macros/scalar \
             -T${ISACOMP_ENV}/link.ld \
             -Wl,--defsym,__stack_top=0x10000 \
             $TEST_SRC -o $TEST_ELF 2>&1 | grep -v "warning: cannot find entry symbol _start" || true

        # Check if compilation succeeded
        if [ ! -f "$TEST_ELF" ]; then
            echo "    Compilation failed for $test"
            FAIL=$((FAIL + 1))
            FAILED_TESTS="$FAILED_TESTS $test"
            continue
        fi

        # Extract pass/fail addresses
        PASS_ADDR=$($NM $TEST_ELF | grep " pass" | awk '{print $1}')
        FAIL_ADDR=$($NM $TEST_ELF | grep " fail" | awk '{print $1}')

        if [ -z "$PASS_ADDR" ] || [ -z "$FAIL_ADDR" ]; then
            echo "    Warning: Could not find pass/fail symbols"
            PASS_ADDR="4ec"
            FAIL_ADDR="4e4"
        fi

        echo "    Compiled: $TEST_ELF"
        echo "    Pass: 0x$PASS_ADDR, Fail: 0x$FAIL_ADDR"

        # Create binary and hex files
        if ! $OBJCOPY -O binary $TEST_ELF $TEST_BIN 2>/dev/null; then
            echo "    Failed to create binary for $test"
            FAIL=$((FAIL + 1))
            FAILED_TESTS="$FAILED_TESTS $test"
            continue
        fi

        if ! $OBJCOPY -O ihex $TEST_ELF $TEST_HEX 2>/dev/null; then
            echo "    Failed to create hex for $test"
            FAIL=$((FAIL + 1))
            FAILED_TESTS="$FAILED_TESTS $test"
            continue
        fi

        # Store addresses in a separate file for easy lookup
        echo "$PASS_ADDR $FAIL_ADDR" > ${TEST_ELF}.addrs

        PASS=$((PASS + 1))
    done
fi

echo ""
echo "=============================="
echo "Results: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
if [ -n "$FAILED_TESTS" ]; then
    echo "Failed tests:$FAILED_TESTS"
fi
echo "=============================="

# Exit with error if any tests failed or no tests passed
if [ $FAIL -gt 0 ]; then
    echo "FAILED: $FAIL test(s) failed to build"
    exit 1
fi

if [ $PASS -eq 0 ]; then
    echo "FAILED: No tests built successfully (all skipped)"
    exit 1
fi

echo "SUCCESS: All $PASS tests built successfully"
echo "Tests are in: $OUTPUT_DIR/"
exit 0
