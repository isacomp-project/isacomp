#!/bin/bash
# Build MIPS32 base tests for ISAComp (38 instructions + delay_slot)
# Only builds tests for the base MIPS32 instruction set
# Use build_tests_linux.sh to build extended instruction tests
#
# Builds two variants:
#   mips32-isacomp-<test>         - without delay slots (default)
#   mips32-isacomp-ds-<test>      - with delay slots (-DDELAY_SLOT)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Find MIPS cross-compiler
if command -v mipsel-linux-gnu-gcc &> /dev/null; then
    GCC=mipsel-linux-gnu-gcc
    NM=mipsel-linux-gnu-nm
    OBJCOPY=mipsel-linux-gnu-objcopy
elif command -v mips-linux-gnu-gcc &> /dev/null; then
    GCC=mips-linux-gnu-gcc
    NM=mips-linux-gnu-nm
    OBJCOPY=mips-linux-gnu-objcopy
else
    echo "Error: MIPS cross-compiler not found"
    echo "Install with: apt install gcc-mipsel-linux-gnu"
    exit 1
fi

TEST_DIR="isa"

# Create output directory
mkdir -p "$TEST_DIR"

# Base MIPS32 instruction tests (39 instructions)
# These match MIPS32_INSTRUCTIONS in create_mips32_pipeline.py
# plus the delay_slot validation test
BASE_TESTS=(
    # R-type arithmetic
    add addu sub subu slt sltu
    # R-type logical
    and or xor nor
    # R-type shifts - immediate
    sll srl sra
    # R-type shifts - variable
    sllv srlv srav
    # I-type arithmetic/logical
    addi addiu andi ori xori slti sltiu lui
    # Loads
    lw lh lhu lb lbu
    # Stores
    sw sh sb
    # Branches
    beq bne
    # Jumps
    j jal jr jalr
    # Delay slot validation
    delay_slot
)

# build_one_test TEST_NAME EXTRA_CFLAGS OUTPUT_PREFIX
# Compiles a single test with the given flags and output naming.
build_one_test() {
    local TEST_NAME="$1"
    local EXTRA_CFLAGS="$2"
    local OUTPUT_PREFIX="$3"

    local TEST_SRC="$TEST_DIR/${TEST_NAME}.S"
    if [ ! -f "$TEST_SRC" ]; then
        echo "Skipping ${OUTPUT_PREFIX}${TEST_NAME} (no test file)"
        return 2
    fi

    local TEST_BASE="$TEST_DIR/${OUTPUT_PREFIX}${TEST_NAME}"

    echo -n "Building ${OUTPUT_PREFIX}${TEST_NAME}... "

    # Compile with minimal flags - no PIC, no GOT, bare metal
    if ! $GCC -march=mips32 -mabi=32 -EL \
         -mno-abicalls -fno-pic \
         -nostdlib -nostartfiles \
         -Wl,--build-id=none \
         -I"$TEST_DIR" \
         -T"$TEST_DIR/linker.ld" \
         $EXTRA_CFLAGS \
         "$TEST_SRC" -o "${TEST_BASE}.elf" 2>/dev/null; then
        echo "COMPILE FAILED"
        return 1
    fi

    # Extract pass/fail addresses
    local PASS_ADDR=$($NM "${TEST_BASE}.elf" 2>/dev/null | grep " pass$" | awk '{print $1}' | head -1)
    local FAIL_ADDR=$($NM "${TEST_BASE}.elf" 2>/dev/null | grep " fail$" | awk '{print $1}' | head -1)

    if [ -z "$PASS_ADDR" ] || [ -z "$FAIL_ADDR" ]; then
        echo "MISSING SYMBOLS"
        return 1
    fi

    echo "$PASS_ADDR $FAIL_ADDR" > "${TEST_BASE}.addrs"

    # Generate Intel HEX file
    if ! $OBJCOPY -O ihex "${TEST_BASE}.elf" "${TEST_BASE}.hex" 2>/dev/null; then
        echo "HEX FAILED"
        return 1
    fi

    echo "OK (pass=$PASS_ADDR, fail=$FAIL_ADDR)"
    return 0
}

PASS=0
FAIL=0

echo "=== Building non-delay-slot tests ==="
for TEST_NAME in "${BASE_TESTS[@]}"; do
    build_one_test "$TEST_NAME" "" "mips32-isacomp-"
    case $? in
        0) PASS=$((PASS + 1)) ;;
        1) FAIL=$((FAIL + 1)) ;;
    esac
done
echo "  Non-delay-slot: $PASS succeeded, $FAIL failed"

PASS_DS=0
FAIL_DS=0

echo ""
echo "=== Building delay-slot tests ==="
for TEST_NAME in "${BASE_TESTS[@]}"; do
    build_one_test "$TEST_NAME" "-DDELAY_SLOT" "mips32-isacomp-ds-"
    case $? in
        0) PASS_DS=$((PASS_DS + 1)) ;;
        1) FAIL_DS=$((FAIL_DS + 1)) ;;
    esac
done
echo "  Delay-slot: $PASS_DS succeeded, $FAIL_DS failed"

echo ""
echo "Build complete: $((PASS + PASS_DS)) succeeded, $((FAIL + FAIL_DS)) failed"
echo ""
echo "Output files in: $TEST_DIR/"
echo "  - mips32-isacomp-*.{elf,hex,addrs}     (non-delay-slot)"
echo "  - mips32-isacomp-ds-*.{elf,hex,addrs}   (delay-slot)"
