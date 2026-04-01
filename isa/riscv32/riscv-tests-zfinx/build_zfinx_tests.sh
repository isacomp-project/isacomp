#!/bin/bash
# Build script for Zfinx tests
# Uses rv32i_zicsr_zfinx architecture

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/isa"
INCLUDE_DIR="$SCRIPT_DIR/../riscv-tests-env/isacomp"
MACROS_DIR="$SCRIPT_DIR/../riscv-tests/isa/macros/scalar"

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Check for RISC-V toolchain (try multiple options)
if command -v riscv64-unknown-elf-gcc &> /dev/null; then
    GCC=riscv64-unknown-elf-gcc
    OBJCOPY=riscv64-unknown-elf-objcopy
    OBJDUMP=riscv64-unknown-elf-objdump
    NM=riscv64-unknown-elf-nm
elif command -v riscv64-linux-gnu-gcc &> /dev/null; then
    GCC=riscv64-linux-gnu-gcc
    OBJCOPY=riscv64-linux-gnu-objcopy
    OBJDUMP=riscv64-linux-gnu-objdump
    NM=riscv64-linux-gnu-nm
else
    echo "Error: No RISC-V toolchain found"
    echo "Please install riscv64-unknown-elf-gcc or riscv64-linux-gnu-gcc"
    exit 1
fi
echo "Using toolchain: $GCC"

# Linker script
LINKER_SCRIPT="$INCLUDE_DIR/link.ld"

# Common flags for Zfinx (uses integer registers for FP)
# -march=rv32i_zicsr_zfinx includes base integer, CSR access, and Zfinx extension
# -Wl,--build-id=none prevents .note.gnu.build-id section which would be placed at address 0
CFLAGS="-march=rv32i_zicsr_zfinx -mabi=ilp32 -static -mcmodel=medany -fvisibility=hidden -nostdlib -nostartfiles -Wl,--build-id=none"

# Include paths
INCLUDES="-I$INCLUDE_DIR -I$MACROS_DIR"

echo "Building Zfinx tests..."
echo "Output directory: $OUTPUT_DIR"
echo ""

# Build each test
for src in "$SCRIPT_DIR"/*.S; do
    if [ -f "$src" ]; then
        basename=$(basename "$src" .S)
        echo "Building: $basename"

        # Compile
        $GCC $CFLAGS $INCLUDES \
            -T "$LINKER_SCRIPT" \
            -o "$OUTPUT_DIR/rv32uzfinx-isacomp-$basename.elf" \
            "$src"

        # Create binary (only include text sections, strip note sections that would create gaps)
        $OBJCOPY -O binary \
            -j .text.init -j .text \
            "$OUTPUT_DIR/rv32uzfinx-isacomp-$basename.elf" \
            "$OUTPUT_DIR/rv32uzfinx-isacomp-$basename.bin"

        # Create hex file for Verilog $readmemh
        python3 -c "
import sys
with open('$OUTPUT_DIR/rv32uzfinx-isacomp-$basename.bin', 'rb') as f:
    data = f.read()
with open('$OUTPUT_DIR/rv32uzfinx-isacomp-$basename.hex', 'w') as f:
    f.write('@00000000\n')
    for i in range(0, len(data), 4):
        word = data[i:i+4]
        if len(word) < 4:
            word = word + b'\x00' * (4 - len(word))
        # Little-endian to big-endian for $readmemh
        f.write('{:02x}{:02x}{:02x}{:02x}\n'.format(word[3], word[2], word[1], word[0]))
"

        # Extract pass/fail addresses
        PASS_ADDR=$($NM "$OUTPUT_DIR/rv32uzfinx-isacomp-$basename.elf" 2>/dev/null | grep " pass$" | awk '{print $1}')
        FAIL_ADDR=$($NM "$OUTPUT_DIR/rv32uzfinx-isacomp-$basename.elf" 2>/dev/null | grep " fail$" | awk '{print $1}')

        if [ -n "$PASS_ADDR" ] && [ -n "$FAIL_ADDR" ]; then
            echo "$PASS_ADDR $FAIL_ADDR" > "$OUTPUT_DIR/rv32uzfinx-isacomp-$basename.addrs"
            echo "  Pass: 0x$PASS_ADDR, Fail: 0x$FAIL_ADDR"
        else
            echo "  Warning: Could not extract pass/fail addresses"
        fi

        # Create disassembly
        $OBJDUMP -d "$OUTPUT_DIR/rv32uzfinx-isacomp-$basename.elf" \
            > "$OUTPUT_DIR/rv32uzfinx-isacomp-$basename.dump"

        echo "  Created: $basename.{elf,bin,hex,dump,addrs}"
    fi
done

echo ""
echo "Build complete!"
echo "Test files in: $OUTPUT_DIR"
