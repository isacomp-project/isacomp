#!/bin/bash
# Build all MIPS32 tests for ISAComp (including Linux-compatible extensions)
# Builds tests for base MIPS32 + MIPS32R2 extended instructions
# Requires -march=mips32r2 for extended instructions (rotr, seb, seh, ext, ins, etc.)

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

PASS=0
FAIL=0

# Build each test (all .S files in the directory)
for TEST_SRC in "$TEST_DIR"/*.S; do
    if [ ! -f "$TEST_SRC" ]; then
        continue
    fi

    TEST_NAME=$(basename "$TEST_SRC" .S)
    TEST_BASE="$TEST_DIR/mips32-isacomp-$TEST_NAME"

    echo -n "Building $TEST_NAME... "

    # Compile with mips32r2 for extended instructions (rotr, seb, seh, wsbh, ext, ins, etc.)
    if ! $GCC -march=mips32r2 -mabi=32 -EL \
         -mno-abicalls -fno-pic \
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
echo "  - mips32-isacomp-*.elf   (ELF binary)"
echo "  - mips32-isacomp-*.hex   (Intel HEX)"
echo "  - mips32-isacomp-*.addrs (pass/fail addresses)"
