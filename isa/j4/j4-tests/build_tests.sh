#!/bin/bash
# Build j4 (SuperH-4) tests for ISAComp
# Based on J2 test build script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Find SH-4 cross-compiler
# Try different possible compiler names (SH-4 compatible compilers)
if command -v sh4-elf-gcc &> /dev/null; then
    GCC=sh4-elf-gcc
    NM=sh4-elf-nm
    OBJCOPY=sh4-elf-objcopy
elif command -v sh-elf-gcc &> /dev/null; then
    GCC=sh-elf-gcc
    NM=sh-elf-nm
    OBJCOPY=sh-elf-objcopy
elif command -v sh4-linux-gnu-gcc &> /dev/null; then
    GCC=sh4-linux-gnu-gcc
    NM=sh4-linux-gnu-nm
    OBJCOPY=sh4-linux-gnu-objcopy
elif command -v sh-linux-gnu-gcc &> /dev/null; then
    GCC=sh-linux-gnu-gcc
    NM=sh-linux-gnu-nm
    OBJCOPY=sh-linux-gnu-objcopy
else
    echo "Error: SH-4 cross-compiler not found"
    echo "Tried: sh4-elf-gcc, sh-elf-gcc, sh4-linux-gnu-gcc, sh-linux-gnu-gcc"
    echo "Install with: apt install gcc-sh-elf or build from source"
    exit 1
fi

echo "Using compiler: $GCC"

TEST_DIR="isa"

# Create output directory if it doesn't exist
mkdir -p "$TEST_DIR"

PASS=0
FAIL=0

# Build each test
for TEST_SRC in "$TEST_DIR"/*.S; do
    if [ ! -f "$TEST_SRC" ]; then
        continue
    fi

    TEST_NAME=$(basename "$TEST_SRC" .S)
    TEST_BASE="$TEST_DIR/j4-isacomp-$TEST_NAME"

    echo -n "Building $TEST_NAME... "

    # Compile with minimal flags for j4/SH-4
    # -m4: SH-4 instruction set
    # -mb: big-endian (J4/SH4 native mode)
    # -nostdlib: no standard library
    # -nostartfiles: no startup files
    if ! $GCC -m4 -mb \
         -nostdlib -nostartfiles \
         -Wl,--build-id=none \
         -I"$TEST_DIR" \
         -T"$TEST_DIR/linker.ld" \
         "$TEST_SRC" -o "${TEST_BASE}.elf" 2>/dev/null; then
        echo "COMPILE FAILED"
        FAIL=$((FAIL + 1))
        continue
    fi

    # Extract pass/fail addresses
    PASS_ADDR=$($NM "${TEST_BASE}.elf" 2>/dev/null | grep " pass$" | awk '{print $1}' | head -1)
    FAIL_ADDR=$($NM "${TEST_BASE}.elf" 2>/dev/null | grep " fail$" | awk '{print $1}' | head -1)

    if [ -z "$PASS_ADDR" ] || [ -z "$FAIL_ADDR" ]; then
        echo "MISSING SYMBOLS"
        FAIL=$((FAIL + 1))
        continue
    fi

    echo "$PASS_ADDR $FAIL_ADDR" > "${TEST_BASE}.addrs"

    # Generate Intel HEX file
    if ! $OBJCOPY -O ihex "${TEST_BASE}.elf" "${TEST_BASE}.hex" 2>/dev/null; then
        echo "HEX FAILED"
        FAIL=$((FAIL + 1))
        continue
    fi

    echo "OK (pass=$PASS_ADDR, fail=$FAIL_ADDR)"
    PASS=$((PASS + 1))
done

echo ""
echo "Build complete: $PASS succeeded, $FAIL failed"
echo ""
echo "Output files in: $TEST_DIR/"
echo "  - j4-isacomp-*.elf   (ELF binary)"
echo "  - j4-isacomp-*.hex   (Intel HEX)"
echo "  - j4-isacomp-*.addrs (pass/fail addresses)"
