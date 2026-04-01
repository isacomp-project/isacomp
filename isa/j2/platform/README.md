# J2 NOMMU Linux Platform

This directory contains the simulation platform for running NOMMU Linux on the
J2 processor generated from ISAComp specifications.

## Overview

The J2 is a clean-room reimplementation of the SH2 instruction set, designed
for running Linux without an MMU. This platform provides:

- Verilator-based simulation testbench
- Boot ROM that initializes the processor and jumps to Linux
- Device tree for hardware description
- UART output for console

## Prerequisites

### Toolchain

You need an SH cross-compiler. The `sh-elf` toolchain works:

```bash
# Check if available
which sh-elf-as sh-elf-ld sh-elf-objcopy

# Version used for testing
sh-elf-as --version  # GNU assembler 2.40+
```

For building the Linux kernel, you need an SH Linux toolchain:

```bash
# Options (in order of preference):
# 1. sh2eb-linux-muslfdpic-gcc (for FDPIC/NOMMU)
# 2. sh4-linux-gnu-gcc (works for kernel, not userspace)
```

### Other Tools

```bash
# Device tree compiler
apt install device-tree-compiler  # provides 'dtc'

# Verilator (for simulation)
apt install verilator  # version 5.x recommended

# Python 3 (for RTL generation)
python3 --version  # 3.8+
```

## Linux Kernel

### Getting the Source

```bash
# Clone Linux (or use existing tree)
git clone https://github.com/torvalds/linux.git
cd linux
git checkout v6.6  # or later
```

### Kernel Configuration

Use the J2 defconfig as a starting point:

```bash
make ARCH=sh j2_defconfig
```

Key configuration options for this platform:

```
CONFIG_CPU_SUBTYPE_J2=y      # J2 processor
CONFIG_CPU_BIG_ENDIAN=y      # Big-endian
CONFIG_SH_DEVICE_TREE=y      # Device tree support
CONFIG_MEMORY_START=0x00000000  # RAM at 0 (modified from default)
CONFIG_MEMORY_SIZE=0x03F00000   # 63MB (1MB reserved for peripherals)

# Console
CONFIG_SERIAL_EARLYCON=y
CONFIG_SERIAL_UARTLITE=y
CONFIG_SERIAL_UARTLITE_CONSOLE=y

# Interrupts/Timer
CONFIG_CLKSRC_JCORE_PIT=y
CONFIG_JCORE_AIC=y
```

### Building the Kernel

```bash
# Set cross compiler
export CROSS_COMPILE=sh2eb-linux-muslfdpic-
# Or if using sh4 toolchain:
export CROSS_COMPILE=sh4-linux-gnu-

# Build
make ARCH=sh -j$(nproc)

# Create raw binary for simulation
# The kernel ELF is arch/sh/boot/vmlinux
# Extract raw binary starting at load address
objcopy -O binary vmlinux vmlinux.bin
```

## Memory Map

```
Address Range          Description
--------------------- ------------------------------------------
0x00000000-0x00000FFF  VBR / Exception vectors (filled by kernel)
0x00001000-0x00001FFF  Kernel zero page
0x00002000-0x004XXXXX  Linux kernel (_stext entry point at 0x2000)
0x03F00000-0x03FFFFFF  Peripheral I/O region (1MB)
  0x03F00100           UART base (UARTLite)
  0x03F00104           UART TX data register
  0x03F00200           AIC/PIT base
```

## Device Tree

The device tree (`j2_isacomp.dts`) describes:

- CPU: jcore,j2 at 50MHz
- Memory: 63MB RAM at 0x00000000
- UART: xlnx,xps-uartlite-1.00.a at 0x03F00100
- Timer: jcore,pit at 0x03F00200
- Interrupt controller: jcore,aic1 at 0x03F00200

### Compiling the Device Tree

```bash
cd j2/platform
dtc -I dts -O dtb -o j2_isacomp.dtb j2_isacomp.dts
```

## Boot ROM

The boot ROM (`boot/bootrom.S`) performs minimal initialization:

1. Sets VBR to kernel's vector base (0x51e0)
2. Loads R4 with FDT pointer (required by Linux boot protocol)
3. Jumps to kernel entry point at 0x00002000

### Building the Boot Image

```bash
cd j2/platform/boot

# Build with sh-elf toolchain
make CROSS_COMPILE=sh-elf-

# This creates boot.bin containing:
# - Padding (0x0000-0x0FFF)
# - Kernel binary (0x1000+)
# - Device tree blob (after kernel)
# - Boot ROM code (after FDT)
```

The Makefile combines:
- `vmlinux.bin` - Raw kernel binary
- `j2_isacomp.dtb` - Compiled device tree
- `bootrom.S` - Boot ROM assembly

## RTL Generation

Generate the J2 processor RTL from ISA specifications:

```bash
cd /path/to/isacomp
python3 j2/generators/generate_j2_complete.py

# Copy to platform
cp j2/generated/j2_complete.v j2/platform/rtl/
```

**Note**: After regeneration, you may need to comment out the umem
initialization loop in `j2_complete.v` for faster simulation:

```verilog
// Skip umem initialization (too slow - 16M words)
// for (i = 0; i < 16777216; i = i + 1) begin
//     umem[i] = 0;
// end
```

## Simulation

### Building the Testbench

```bash
cd j2/platform/tests
make clean
make all
```

### Running Linux Boot

```bash
# Run simulation
./obj_dir/Vlinux_boot_tb +boot=../boot/boot.bin

# The testbench will:
# 1. Load boot.bin into memory
# 2. Start CPU at boot ROM entry point
# 3. Boot ROM jumps to kernel
# 4. UART output appears on stdout
```

### Testing UART

A simple UART test ROM is provided:

```bash
# Build test ROM
cd j2/platform/boot
sh-elf-as -big --isa=sh2 -o test_uart.o test_uart.S
sh-elf-ld -T test_uart.ld -nostdlib -o test_uart.elf test_uart.o
sh-elf-objcopy -O binary test_uart.elf test_uart.bin

# Update testbench ENTRY_POINT to 0x00000000, rebuild, then:
./obj_dir/Vlinux_boot_tb +boot=../boot/test_uart.bin
# Should print: Hello UART!
```

## Troubleshooting

### No UART Output

1. Check that UART address matches between:
   - Device tree (`j2_isacomp.dts`: soc base + 0x100)
   - Testbench (`linux_boot_tb.sv`: UART_TX parameter)
   - Kernel earlycon (`bootargs` in device tree)

2. The UART must be within the 64MB internal memory range
   (0x00000000 - 0x03FFFFFF) for the testbench to detect writes.

### Kernel Hangs

1. Check boot ROM entry point matches `_start` symbol:
   ```bash
   sh-elf-nm boot/bootrom.elf | grep _start
   ```
   Update `ENTRY_POINT` in testbench to match.

2. Verify VBR is set correctly (should be ~0x5000 after kernel init)

3. Timer interrupts should be visible as exceptions in simulation output

### CAS.L Issues

The CAS.L (Compare-and-Swap) instruction semantics:
- Rn = compare value (expected old value), receives original @R0 as output
- Rm = new value (to swap in if match, read-only)
- If @R0 == Rn: @R0 = Rm, T = 1
- Else: Rn = @R0, T = 0

## Files

```
j2/platform/
├── README.md              # This file
├── j2_isacomp.dts         # Device tree source
├── j2_isacomp.dtb         # Compiled device tree
├── boot/
│   ├── Makefile           # Build boot image
│   ├── bootrom.S          # Boot ROM assembly
│   ├── boot.ld            # Linker script for boot image
│   ├── boot.bin           # Combined boot image
│   ├── test_uart.S        # UART test ROM
│   └── test_uart.ld       # UART test linker script
├── rtl/
│   └── j2_complete.v      # Generated J2 processor RTL
└── tests/
    ├── Makefile           # Build simulation
    ├── linux_boot_tb.sv   # Verilator testbench
    └── sim_main.cpp       # Verilator C++ main
```

## References

- J2 Core: https://j-core.org/
- Linux/SH: https://www.kernel.org/ (arch/sh/)
- Verilator: https://verilator.org/
