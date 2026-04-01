#!/bin/bash
# Build OpenPOWER tests for ISAComp
# Based on the MIPS test build script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Find PowerPC cross-compiler
if command -v powerpc64le-linux-gnu-gcc &> /dev/null; then
    GCC=powerpc64le-linux-gnu-gcc
    AS=powerpc64le-linux-gnu-as
    LD=powerpc64le-linux-gnu-ld
    NM=powerpc64le-linux-gnu-nm
    OBJCOPY=powerpc64le-linux-gnu-objcopy
    OBJDUMP=powerpc64le-linux-gnu-objdump
elif command -v powerpc64-linux-gnu-gcc &> /dev/null; then
    GCC=powerpc64-linux-gnu-gcc
    AS=powerpc64-linux-gnu-as
    LD=powerpc64-linux-gnu-ld
    NM=powerpc64-linux-gnu-nm
    OBJCOPY=powerpc64-linux-gnu-objcopy
    OBJDUMP=powerpc64-linux-gnu-objdump
else
    echo "Error: PowerPC cross-compiler not found"
    echo "Install with: apt install gcc-powerpc64le-linux-gnu"
    exit 1
fi

TEST_DIR="isa"

# Create output directory
mkdir -p "$TEST_DIR"

PASS=0
FAIL=0

# Build each test (base + FP tests from f/ subdirectory)
for TEST_SRC in "$TEST_DIR"/*.S "$TEST_DIR"/f/*.S; do
    if [ ! -f "$TEST_SRC" ]; then
        continue
    fi

    TEST_NAME=$(basename "$TEST_SRC" .S)
    # Put output in same directory as source (handles f/ subdirectory)
    TEST_SUBDIR=$(dirname "$TEST_SRC")
    TEST_BASE="$TEST_SUBDIR/power-isacomp-$TEST_NAME"

    echo -n "Building $TEST_NAME... "

    # Compile with PowerPC64 flags
    # -mcpu=power8 for OpenPOWER compatible
    # -mabi=elfv2 for little-endian ELF v2 ABI
    # -static -no-pie to prevent dynamic linking issues
    if ! $GCC -mcpu=power8 -mabi=elfv2 -mlittle-endian \
         -nostdlib -nostartfiles -static -no-pie \
         -Wl,--build-id=none,-N,--no-dynamic-linker \
         -I"$TEST_DIR" \
         -T"$TEST_DIR/linker.ld" \
         "$TEST_SRC" -o "${TEST_BASE}.elf" 2>/dev/null; then
        echo "COMPILE FAILED"
        # Try to show the error
        $GCC -mcpu=power8 -mabi=elfv2 -mlittle-endian \
             -nostdlib -nostartfiles -static -no-pie \
             -Wl,--build-id=none,-N,--no-dynamic-linker \
             -I"$TEST_DIR" \
             -T"$TEST_DIR/linker.ld" \
             "$TEST_SRC" -o "${TEST_BASE}.elf" 2>&1 | head -20
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

    # Generate binary file for loading into simulation
    if ! $OBJCOPY -O binary "${TEST_BASE}.elf" "${TEST_BASE}.bin" 2>/dev/null; then
        echo "BIN FAILED"
        FAIL=$((FAIL + 1))
        continue
    fi

    # Generate hex dump for debugging
    $OBJDUMP -d "${TEST_BASE}.elf" > "${TEST_BASE}.dump" 2>/dev/null

    # Generate Verilog hex file for $readmemh
    python3 - <<PYTHON "${TEST_BASE}.bin" "${TEST_BASE}.imem.hex" "${TEST_BASE}.dmem.hex"
import sys

bin_file = sys.argv[1]
imem_file = sys.argv[2]
dmem_file = sys.argv[3]

with open(bin_file, 'rb') as f:
    data = f.read()

# Split into imem (code at 0x0, up to 16KB) and dmem (data at 0x10000)
# imem: 16KB at address 0x0 (4K x 32-bit words)
# dmem: 128KB at address 0x10000 (16K x 64-bit doublewords)

IMEM_SIZE = 16384  # 16KB imem (4K x 32-bit words)
DMEM_OFFSET = 0x10000  # Data starts at 0x10000
DMEM_ENTRIES = 16384  # 16K entries (128KB as 64-bit words)

# Write imem.hex - 32-bit words in hex, little-endian
with open(imem_file, 'w') as f:
    for i in range(0, IMEM_SIZE, 4):
        if i + 4 <= len(data):
            word = int.from_bytes(data[i:i+4], 'little')
        elif i < len(data):
            # Partial word at end
            word = int.from_bytes(data[i:] + bytes(4 - (len(data) - i)), 'little')
        else:
            word = 0
        f.write(f'{word:08x}\n')

# Write dmem.hex - 64-bit doublewords in hex, little-endian
# Data starts at address 0x10000 in the binary
# run_tests.sh places this at umem index 8192 (address 0x10000)
with open(dmem_file, 'w') as f:
    for i in range(DMEM_ENTRIES):
        byte_addr = DMEM_OFFSET + (i * 8)  # Start from DMEM_OFFSET
        if byte_addr + 8 <= len(data):
            dword = int.from_bytes(data[byte_addr:byte_addr+8], 'little')
        elif byte_addr < len(data):
            # Partial doubleword at end
            remaining = data[byte_addr:]
            dword = int.from_bytes(remaining + bytes(8 - len(remaining)), 'little')
        else:
            dword = 0
        f.write(f'{dword:016x}\n')
PYTHON

    echo "OK (pass=$PASS_ADDR, fail=$FAIL_ADDR)"
    PASS=$((PASS + 1))
done

echo ""
echo "Build complete: $PASS succeeded, $FAIL failed"
echo ""
echo "Output files in: $TEST_DIR/"
echo "  - power-isacomp-*.elf       (ELF binary)"
echo "  - power-isacomp-*.bin       (Raw binary)"
echo "  - power-isacomp-*.imem.hex  (Verilog hex for imem)"
echo "  - power-isacomp-*.dmem.hex  (Verilog hex for dmem)"
echo "  - power-isacomp-*.addrs     (pass/fail addresses)"
echo "  - power-isacomp-*.dump      (Disassembly)"
