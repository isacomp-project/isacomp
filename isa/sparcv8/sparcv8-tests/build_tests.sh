#!/bin/bash
# Build SPARCv8 tests for ISAComp
# Based on J2 and MIPS32 test build scripts

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Find SPARC cross-compiler
# Try different possible compiler names
if command -v sparc-elf-gcc &> /dev/null; then
    GCC=sparc-elf-gcc
    NM=sparc-elf-nm
    OBJCOPY=sparc-elf-objcopy
elif command -v sparc-linux-gnu-gcc &> /dev/null; then
    GCC=sparc-linux-gnu-gcc
    NM=sparc-linux-gnu-nm
    OBJCOPY=sparc-linux-gnu-objcopy
elif command -v sparc64-linux-gnu-gcc &> /dev/null; then
    # SPARC64 toolchain can target 32-bit with -m32
    GCC="sparc64-linux-gnu-gcc -m32"
    NM=sparc64-linux-gnu-nm
    OBJCOPY=sparc64-linux-gnu-objcopy
elif command -v sparc-unknown-elf-gcc &> /dev/null; then
    GCC=sparc-unknown-elf-gcc
    NM=sparc-unknown-elf-nm
    OBJCOPY=sparc-unknown-elf-objcopy
else
    echo "Error: SPARC cross-compiler not found"
    echo "Tried: sparc-elf-gcc, sparc-linux-gnu-gcc, sparc64-linux-gnu-gcc"
    echo "Install with: apt install gcc-sparc64-linux-gnu"
    echo "Or build a SPARC cross-compiler from source"
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
    TEST_BASE="$TEST_DIR/sparcv8-isacomp-$TEST_NAME"

    echo -n "Building $TEST_NAME... "

    # Preprocess the assembly file (needed for test macros)
    if ! cpp -I"$TEST_DIR" "$TEST_SRC" 2>/dev/null | grep -v '^#' > "${TEST_BASE}.s"; then
        echo "PREPROCESS FAILED"
        FAIL=$((FAIL + 1))
        continue
    fi

    # Compile and link
    # Use -nostdlib to avoid standard library, -static for static linking
    if ! $GCC -nostdlib -static -T"$TEST_DIR/linker.ld" -o "${TEST_BASE}.elf" "${TEST_BASE}.s" 2>/dev/null; then
        # Try without linker script
        if ! $GCC -nostdlib -static -Wl,-Ttext=0 -o "${TEST_BASE}.elf" "${TEST_BASE}.s" 2>/dev/null; then
            echo "COMPILE FAILED"
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

    # Convert to hex format for Verilog $readmemh (32-bit words, big-endian for SPARC)
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
echo "  - sparcv8-isacomp-*.elf   (ELF binary)"
echo "  - sparcv8-isacomp-*.hex   (Verilog hex)"
echo "  - sparcv8-isacomp-*.addrs (pass/fail addresses)"
