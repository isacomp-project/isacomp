#!/bin/bash
# Create combined boot image for M68K Linux simulation
#
# The boot image is a flat memory image starting at address 0:
#   0x00000000 - 0x000003FF: Exception vectors (from bootrom)
#   0x00000400 - 0x000004FF: Boot ROM code (from bootrom)
#   0x00000500 - 0x000007FF: Bootinfo records (from bootrom)
#   0x00001000 - ...........: Linux kernel (from vmlinux.bin)
#
# Note: vmlinux.bin (from objcopy -O binary) starts at _stext (0x1000),
# meaning file offset 0 = address 0x1000. We need to prepend 0x1000 bytes
# of bootrom data to create the full memory image.
#
# Usage: create_boot_image.sh bootrom.bin vmlinux.bin dtb boot.bin

BOOTROM="$1"
KERNEL="$2"
DTB="$3"
OUTPUT="$4"

if [ -z "$OUTPUT" ]; then
    echo "Usage: $0 bootrom.bin vmlinux.bin dtb output.bin"
    exit 1
fi

# Kernel starts at address 0x1000
KERNEL_OFFSET=4096

BOOTROM_SIZE=$(stat -c%s "$BOOTROM" 2>/dev/null || stat -f%z "$BOOTROM")
echo "Boot ROM size: $BOOTROM_SIZE bytes"

if [ -f "$KERNEL" ]; then
    KERNEL_SIZE=$(stat -c%s "$KERNEL" 2>/dev/null || stat -f%z "$KERNEL")
    echo "Kernel size: $KERNEL_SIZE bytes (starts at address 0x1000)"

    # 1. Start with bootrom (vectors + boot code + bootinfo)
    cp "$BOOTROM" "$OUTPUT"

    # 2. Pad from bootrom end to kernel offset (0x1000)
    PADDING=$((KERNEL_OFFSET - BOOTROM_SIZE))
    if [ $PADDING -gt 0 ]; then
        dd if=/dev/zero bs=1 count=$PADDING 2>/dev/null >> "$OUTPUT"
        echo "Added $PADDING bytes of padding (to offset 0x1000)"
    fi

    # 3. Append kernel binary (vmlinux.bin starts at address 0x1000)
    cat "$KERNEL" >> "$OUTPUT"
    echo "Appended kernel at offset 0x1000"
else
    echo "Warning: Kernel not found at $KERNEL"
    echo "Creating bootrom-only image"
    cp "$BOOTROM" "$OUTPUT"
fi

FINAL_SIZE=$(stat -c%s "$OUTPUT" 2>/dev/null || stat -f%z "$OUTPUT")
echo "Final boot image: $FINAL_SIZE bytes ($((FINAL_SIZE / 1024)) KB)"
