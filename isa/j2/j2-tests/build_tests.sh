#!/bin/bash
# Build j2 (SuperH-2) tests for ISAComp
# Based on MIPS32 and Alpha test build scripts

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Find SH-2 cross-compiler
# Try different possible compiler names
if command -v sh2-elf-gcc &> /dev/null; then
    GCC=sh2-elf-gcc
    NM=sh2-elf-nm
    OBJCOPY=sh2-elf-objcopy
elif command -v sh-elf-gcc &> /dev/null; then
    GCC=sh-elf-gcc
    NM=sh-elf-nm
    OBJCOPY=sh-elf-objcopy
elif command -v sh4-linux-gnu-gcc &> /dev/null; then
    # SH4 toolchain; script uses assembler/linker directly with big-endian flags
    GCC=sh4-linux-gnu-gcc
    NM=sh4-linux-gnu-nm
    OBJCOPY=sh4-linux-gnu-objcopy
elif command -v sh2-linux-gnu-gcc &> /dev/null; then
    GCC=sh2-linux-gnu-gcc
    NM=sh2-linux-gnu-nm
    OBJCOPY=sh2-linux-gnu-objcopy
elif command -v sh-linux-gnu-gcc &> /dev/null; then
    GCC=sh-linux-gnu-gcc
    NM=sh-linux-gnu-nm
    OBJCOPY=sh-linux-gnu-objcopy
else
    echo "Error: SH-2 cross-compiler not found"
    echo "Tried: sh2-elf-gcc, sh-elf-gcc, sh4-linux-gnu-gcc, sh2-linux-gnu-gcc, sh-linux-gnu-gcc"
    echo "Install with: apt install gcc-10-sh4-linux-gnu or build from source"
    echo "See: https://j-core.org/ for j2 toolchain information"
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
    TEST_BASE="$TEST_DIR/j2-isacomp-$TEST_NAME"

    echo -n "Building $TEST_NAME... "

    # Compile with minimal flags for j2/SH-2
    # For SH4 cross-toolchain: use assembler with --big flag and linker with -EB
    # This avoids the -m2 flag which isn't supported by sh4-linux-gnu-gcc

    # Get base tools name (remove gcc suffix)
    AS="${GCC%gcc}as"
    LD="${GCC%gcc}ld"

    # Preprocess the assembly file (needed for test macros)
    if ! cpp -I"$TEST_DIR" "$TEST_SRC" 2>/dev/null | grep -v '^#' > "${TEST_BASE}.s"; then
        echo "PREPROCESS FAILED"
        FAIL=$((FAIL + 1))
        continue
    fi

    # Assemble with big-endian flag
    if ! $AS --big -o "${TEST_BASE}.o" "${TEST_BASE}.s" 2>/dev/null; then
        echo "ASSEMBLE FAILED"
        FAIL=$((FAIL + 1))
        continue
    fi

    # Then link with big-endian flag
    if ! $LD -EB -T"$TEST_DIR/linker.ld" -o "${TEST_BASE}.elf" "${TEST_BASE}.o" 2>/dev/null; then
        # Try without linker script
        if ! $LD -EB -Ttext=0 -o "${TEST_BASE}.elf" "${TEST_BASE}.o" 2>/dev/null; then
            echo "LINK FAILED"
            FAIL=$((FAIL + 1))
            continue
        fi
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

    # Generate binary file and convert to Verilog $readmemh format
    if ! $OBJCOPY -O binary "${TEST_BASE}.elf" "${TEST_BASE}.bin" 2>/dev/null; then
        echo "BIN FAILED"
        FAIL=$((FAIL + 1))
        continue
    fi

    # Convert to hex format for Verilog $readmemh (32-bit words, big-endian)
    python3 -c "
import struct
with open('${TEST_BASE}.bin', 'rb') as f:
    data = f.read()
# Pad to 4-byte boundary
while len(data) % 4 != 0:
    data += b'\\x00'
with open('${TEST_BASE}.hex', 'w') as f:
    for i in range(0, len(data), 4):
        word = struct.unpack('>I', data[i:i+4])[0]
        f.write(f'{word:08X}\\n')
" 2>/dev/null
    if [ ! -f "${TEST_BASE}.hex" ]; then
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
echo "  - j2-isacomp-*.elf   (ELF binary)"
echo "  - j2-isacomp-*.hex   (Intel HEX)"
echo "  - j2-isacomp-*.addrs (pass/fail addresses)"
