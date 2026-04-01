#!/bin/bash
# Build MIPS32 FP tests for ISAComp

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

TEST_DIR="isa/f"

PASS=0
FAIL=0

# Build each FP test
for TEST_SRC in "$TEST_DIR"/*.S; do
    if [ ! -f "$TEST_SRC" ]; then
        continue
    fi

    TEST_NAME=$(basename "$TEST_SRC" .S)
    TEST_BASE="$TEST_DIR/mips32-isacomp-$TEST_NAME"

    echo -n "Building $TEST_NAME... "

    # Compile with minimal flags - no PIC, no GOT, bare metal
    if ! $GCC -march=mips32 -mabi=32 -EL \
         -mno-abicalls -fno-pic \
         -mhard-float \
         -nostdlib -nostartfiles \
         -Wl,--build-id=none \
         -I"isa" \
         -T"isa/linker.ld" \
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
echo "FP Build complete: $PASS succeeded, $FAIL failed"
