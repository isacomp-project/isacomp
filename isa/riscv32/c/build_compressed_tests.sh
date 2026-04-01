#!/bin/bash
# Build ISAComp RISC-V Compressed (RV32C) tests
# ISAComp tests start at address 0x0 instead of 0x80000000

RISCV_PREFIX="riscv64-unknown-elf-"
GCC="${RISCV_PREFIX}gcc"
OBJCOPY="${RISCV_PREFIX}objcopy"
OBJDUMP="${RISCV_PREFIX}objdump"
NM="${RISCV_PREFIX}nm"

TEST_DIR="isa/riscv32/riscv-tests/isa"
OUTPUT_DIR="isa/riscv32/c/riscv-tests/isa/rv32uc-isacomp"

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Compressed instruction test
TEST="rvc"

PASS=0
FAIL=0
SKIP=0
FAILED_TESTS=""

echo "Building ISAComp RISC-V Compressed (RV32C) tests..."
echo "=============================="

# Check if ISA files exist (we need all compressed instruction files)
REQUIRED_ISA_FILES="c.add c.addi c.addi4spn c.addi16sp c.and c.andi c.beqz c.bnez c.j c.jal c.jalr c.jr c.li c.lui c.lw c.lwsp c.mv c.nop c.or c.slli c.srai c.srli c.sub c.sw c.swsp c.xor"

for isa_file in $REQUIRED_ISA_FILES; do
    if [ ! -f "isa/riscv32/c/${isa_file}.isa" ]; then
        echo "⚠  Missing ISA definition: isa/riscv32/c/${isa_file}.isa"
        SKIP=$((SKIP + 1))
    fi
done

if [ ! -f "$TEST_DIR/rv32uc/${TEST}.S" ]; then
    echo "⚠  Skipping $TEST: No test source"
    SKIP=$((SKIP + 1))
    echo ""
    echo "=============================="
    echo "Results: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
    echo "=============================="
    exit 0
fi

TEST_SRC="$TEST_DIR/rv32uc/${TEST}.S"
TEST_ELF="$OUTPUT_DIR/rv32uc-isacomp-${TEST}"
TEST_BIN="$OUTPUT_DIR/rv32uc-isacomp-${TEST}.bin"
TEST_HEX="$OUTPUT_DIR/rv32uc-isacomp-${TEST}.hex"

echo "Building ${TEST}..."

# Compile with ISAComp link address (0x0) and compressed instructions enabled
$GCC -march=rv32ic -mabi=ilp32 -static -mcmodel=medany -fvisibility=hidden \
     -nostdlib -nostartfiles \
     -I${TEST_DIR}/../env/isacomp -I${TEST_DIR}/macros/scalar \
     -T${TEST_DIR}/../env/isacomp/link.ld \
     -Wl,--defsym,__stack_top=0x10000 \
     $TEST_SRC -o $TEST_ELF 2>&1 | grep -v "warning: cannot find entry symbol _start" || true

# Check if compilation succeeded
if [ ! -f "$TEST_ELF" ]; then
    echo "  ✗ Compilation failed for $TEST"
    FAIL=$((FAIL + 1))
    FAILED_TESTS="$FAILED_TESTS $TEST"
else
    # Extract pass/fail addresses
    PASS_ADDR=$($NM $TEST_ELF | grep " pass" | awk '{print $1}')
    FAIL_ADDR=$($NM $TEST_ELF | grep " fail" | awk '{print $1}')

    if [ -z "$PASS_ADDR" ] || [ -z "$FAIL_ADDR" ]; then
        echo "  ✗ Could not find pass/fail symbols for $TEST"
        FAIL=$((FAIL + 1))
        FAILED_TESTS="$FAILED_TESTS $TEST"
    else
        echo "  ✓ Compiled: $TEST_ELF"
        echo "    Pass address: 0x$PASS_ADDR"
        echo "    Fail address: 0x$FAIL_ADDR"

        # Create binary and hex files
        if ! $OBJCOPY -O binary $TEST_ELF $TEST_BIN 2>/dev/null; then
            echo "  ✗ Failed to create binary for $TEST"
            FAIL=$((FAIL + 1))
            FAILED_TESTS="$FAILED_TESTS $TEST"
        elif ! $OBJCOPY -O ihex $TEST_ELF $TEST_HEX 2>/dev/null; then
            echo "  ✗ Failed to create hex for $TEST"
            FAIL=$((FAIL + 1))
            FAILED_TESTS="$FAILED_TESTS $TEST"
        else
            # Store addresses in a separate file for easy lookup
            echo "$PASS_ADDR $FAIL_ADDR" > ${TEST_ELF}.addrs

            # Disassemble to see the compressed instructions
            echo "  Creating disassembly..."
            $OBJDUMP -d $TEST_ELF > ${TEST_ELF}.dis

            PASS=$((PASS + 1))
        fi
    fi
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
echo "Tests are in: $OUTPUT_DIR/rv32uc-isacomp-*"
echo ""
echo "To examine the compressed instructions, check:"
echo "  ${TEST_ELF}.dis"
exit 0
