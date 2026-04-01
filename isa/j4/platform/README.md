# J4 (SH-4) NOMMU Linux Platform

This directory contains the simulation platform for running NOMMU Linux on the
J4 (SH-4) processor generated from ISAComp specifications.

## Status

- **ISA Tests**: 117/117 passing
- **UART Output**: Verified working
- **Platform Ready**: Yes (awaiting Linux kernel)

## Overview

The J4 is a SuperH-4 compatible processor with:
- 213 instructions (including FPU and MMU support)
- Full SH-4 ISA compatibility
- CAM-based TLB (4 ITLB + 64 UTLB entries)
- NOMMU mode for running without virtual memory

This platform provides:
- Verilator-based simulation testbench
- Boot ROM that initializes the processor and jumps to Linux
- Device tree for hardware description
- UART output for console
- Timer (PIT) and interrupt controller (AIC)

## Directory Structure

```
j4/platform/
├── README.md               # This file
├── j4_isacomp.dts         # Device tree source
├── j4_isacomp.dtb         # Compiled device tree
├── jcore_aic.sv           # Interrupt controller
├── jcore_pit.sv           # Programmable interval timer
├── uartlite.sv            # UART peripheral
├── boot/
│   ├── Makefile           # Build boot image
│   ├── bootrom.S          # Boot ROM assembly (SH-4)
│   ├── boot.ld            # Linker script
│   ├── test.ld            # Simple test linker script
│   └── test_uart.S        # UART test program
├── rtl/
│   ├── j4_complete.v      # Generated J4 processor (667KB)
│   └── cvfpu_simple.v     # Simple FPU stub
└── tests/
    ├── Makefile           # Build simulation
    └── linux_boot_tb.sv   # Linux boot testbench
```

## Memory Map (NOMMU Mode)

```
0x00000000 - 0x03EFFFFF: Main RAM (63MB)
0x03F00100: UARTLite (TX at +0x04)
0x03F00200: AIC + PIT (shared base)
```

## Quick Test

Run the UART test to verify the platform works:

```bash
# Build the test
cd boot
sh-elf-as -big --isa=sh4 -o test_uart.o test_uart.S
sh-elf-ld -T test.ld -nostdlib -o test_uart.elf test_uart.o
sh-elf-objcopy -O binary test_uart.elf test_uart.bin

# Convert to hex format
cd ../tests
python3 << 'EOF'
import sys
data = open('../boot/test_uart.bin', 'rb').read()
with open('umem.hex', 'w') as f:
    for i in range(4096):
        if i*4 + 4 <= len(data):
            word = (data[i*4] << 24) | (data[i*4+1] << 16) | (data[i*4+2] << 8) | data[i*4+3]
        else:
            word = 0
        f.write(f'{word:08x}\n')
EOF

# Create empty hex files for other arrays
for f in rf.hex rf_bank.hex fpr.hex fr.hex itlb_v.hex; do
    echo "00000000" > $f
done
for f in utlb_asid.hex utlb_c.hex utlb_d.hex utlb_ppn.hex utlb_pr.hex utlb_sh.hex utlb_sz.hex utlb_v.hex utlb_vpn.hex utlb_wt.hex; do
    echo "00000000" > $f
done

# Build and run
make
./obj_dir/Vlinux_boot_tb +boot=../boot/test_uart.bin +entry=00000000
```

Expected output:
```
=== J4 Linux Boot Started ===
J4 UART OK
```

## Building for Linux Boot

### Prerequisites

```bash
# SH cross-compilers
apt install binutils-sh-elf gcc-sh-elf gcc-sh4-linux-gnu

# Device tree compiler
apt install device-tree-compiler

# Verilator
apt install verilator
```

### Linux Kernel Configuration

Use the J2 defconfig as a starting point, with modifications for J4:

```bash
cd linux
make ARCH=sh j2_defconfig
```

Key configuration:
```
CONFIG_CPU_SUBTYPE_J2=y      # J2 compatible (for NOMMU)
CONFIG_CPU_BIG_ENDIAN=y      # Big-endian
CONFIG_SH_DEVICE_TREE=y      # Device tree support
CONFIG_MEMORY_START=0x00000000
CONFIG_MEMORY_SIZE=0x03F00000   # 63MB

# Console
CONFIG_SERIAL_EARLYCON=y
CONFIG_SERIAL_UARTLITE=y
CONFIG_SERIAL_UARTLITE_CONSOLE=y

# Interrupts/Timer
CONFIG_CLKSRC_JCORE_PIT=y
CONFIG_JCORE_AIC=y
```

### Building the Boot Image

```bash
cd boot
make KERNEL=path/to/vmlinux.bin DTB=../j4_isacomp.dtb
```

### Running the Simulation

```bash
cd tests
make sim
```

## NOMMU vs MMU Boot

This platform currently supports NOMMU boot, which is simpler and doesn't
require TLB management. For MMU boot:

1. Set MMUCR.AT=1 in boot ROM
2. Pre-populate TLB entries for kernel space
3. Use a kernel configured with CONFIG_MMU=y

The J4 processor includes full MMU support with CAM-based TLB, but MMU
boot requires additional testing of TLB miss exception handling.

## See Also

- `../J4_SOC_IMPLEMENTATION_PLAN.md` - Detailed implementation plan
- `../../j2/platform/` - J2 platform (reference implementation)
