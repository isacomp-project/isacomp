# M68K Linux Boot Platform

This directory contains the platform support files for booting Linux on the
ISAComp-generated M68K processor (MC68030 compatible with MMU support).

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    M68K SoC Platform                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   M68K CPU Core (303 instructions, MC68030 compatible)      │
│       ├─ Full 32-bit address/data                           │
│       ├─ Supervisor/User mode                               │
│       ├─ 22-entry ATC (MMU TLB)                             │
│       └─ Exception/Interrupt handling                       │
│                         │                                    │
│              ┌──────────┼──────────┐                        │
│              │          │          │                        │
│         ┌────▼───┐ ┌───▼───┐ ┌───▼────┐                   │
│         │ Memory │ │ Periph│ │  IRQ   │                   │
│         │  Bus   │ │  Bus  │ │ Encode │                   │
│         └────┬───┘ └───┬───┘ └───┬────┘                   │
│              │         │         │                         │
│    ┌─────────▼─────────▼─────────▼──────────────────┐     │
│    │        64MB RAM (0x00000000 - 0x03FFFFFF)      │     │
│    │    Exception Vectors: 0x000 - 0x3FF (1KB)      │     │
│    │    Kernel Entry: 0x00001000                     │     │
│    └────────────────────────────────────────────────┘     │
│                                                            │
│    ┌────────────────────────────────────────────────┐     │
│    │    Peripherals (0x10000000 - 0x10FFFFFF)       │     │
│    ├────────────────────────────────────────────────┤     │
│    │ • UARTLite @ 0x10000100                        │     │
│    │ • Interrupt Controller @ 0x10000200            │     │
│    │ • Timer @ 0x10000300                           │     │
│    └────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

## Memory Map

| Address Range | Size | Description |
|---------------|------|-------------|
| 0x00000000 - 0x000003FF | 1KB | Exception Vector Table |
| 0x00000400 - 0x00000FFF | 3KB | Boot ROM |
| 0x00001000 - 0x03EFFFFF | ~62MB | Linux Kernel + Applications |
| 0x03F00000 - 0x03FFFFFF | 1MB | Reserved |
| 0x10000000 - 0x10FFFFFF | 16MB | I/O Peripherals |

## Peripheral Register Maps

### UARTLite (0x10000100)

| Offset | Register | Description |
|--------|----------|-------------|
| 0x00 | RX_FIFO | Receive data FIFO |
| 0x04 | TX_FIFO | Transmit data FIFO |
| 0x08 | STATUS | Status register |
| 0x0C | CONTROL | Control register |

### Interrupt Controller (0x10000200)

| Offset | Register | Description |
|--------|----------|-------------|
| 0x00 | ISR | Interrupt Status (R) |
| 0x04 | IER | Interrupt Enable (R/W) |
| 0x08 | IPR | Interrupt Priority (R/W) |
| 0x0C | IMR | Interrupt Mask (R/W) |
| 0x10 | IVR | Vector Base (R/W) |
| 0x14 | IAR | Acknowledge (R) |

### Timer (0x10000300)

| Offset | Register | Description |
|--------|----------|-------------|
| 0x00 | CTRL | Control (enable, IRQ, auto-reload) |
| 0x04 | LOAD | Reload value |
| 0x08 | COUNT | Current count (R) |
| 0x0C | STATUS | Status (R) |
| 0x10 | PRESCALE | Prescaler value |
| 0x14 | SEC_LO | Seconds low (R) |
| 0x18 | SEC_HI | Seconds high (R) |
| 0x1C | NSEC | Nanoseconds (R) |

## M68K Reset Sequence

1. Processor reads SSP from address 0x00000000
2. Processor reads PC from address 0x00000004
3. Processor enters supervisor mode with SR = 0x2700
4. Execution begins at loaded PC value

## Linux Boot Protocol

The boot ROM performs the following:

1. Set VBR (Vector Base Register) to exception table
2. Initialize stack pointer (SSP)
3. Load A0 with FDT (Device Tree) pointer
4. Jump to kernel entry point at 0x00001000

## Building

### Prerequisites

- m68k-linux-gnu toolchain (or m68k-elf)
- Device tree compiler (dtc)
- Verilator 5.x
- Linux kernel source configured for m68k

### Generate RTL

```bash
# From isacomp root
python3 isa/m68k/generators/generate_m68k_linux.py
```

### Build Boot Image

```bash
cd isa/m68k/platform/boot
make KERNEL_DIR=/path/to/linux
```

### Run Simulation

```bash
cd isa/m68k/platform/tests
make sim BOOT_IMAGE=../boot/boot.bin
```

### Trace Simulation

```bash
make trace
gtkwave m68k_linux_boot.vcd
```

## Linux Kernel Configuration

### ISAComp Machine Type

The ISAComp platform has its own machine type in the Linux kernel, enabling
the use of standard peripherals (UARTLite, simple timer, simple INTC) instead
of QEMU's Goldfish devices used by the VIRT machine.

The kernel patches are in `linux-kernel-isacomp.patch`. To apply:

```bash
cd /path/to/linux
git apply /path/to/linux-kernel-isacomp.patch
make ARCH=m68k CROSS_COMPILE=m68k-linux-gnu- isacomp_defconfig
make ARCH=m68k CROSS_COMPILE=m68k-linux-gnu- vmlinux
```

### Key Configuration Options

Use `isacomp_defconfig` which sets:

```
CONFIG_ISACOMP=y              # ISAComp platform
CONFIG_M68030=y               # MC68030 CPU (matches ISA's PMOVE-based MMU)
CONFIG_MMU_MOTOROLA=y         # Motorola MMU
CONFIG_M68KFPU_EMU=y          # Software FPU emulation
CONFIG_M68KFPU_EMU_ONLY=y     # No hardware FPU
CONFIG_LEGACY_TIMER_TICK=y    # Simple timer support
CONFIG_SERIAL_UARTLITE=y      # UARTLite serial driver
CONFIG_SERIAL_UARTLITE_CONSOLE=y  # UARTLite as console
```

### Machine Type Details

The ISAComp kernel patches add:
- `MACH_ISACOMP = 15` in bootinfo.h
- `MACH_IS_ISACOMP` macros in setup.h
- `config_isacomp()` and `isacomp_parse_bootinfo()` functions
- `isacomp/config.c` - Timer, interrupt controller, platform init
- `isacomp/platform.c` - UARTLite platform device registration
- `NR_IRQS = 200` for ISACOMP builds

## Directory Structure

```
platform/
├── README.md               # This file
├── m68k_linux.dts         # Device tree source
├── m68k_soc.sv            # Top-level SoC module
├── m68k_intc.sv           # Interrupt controller
├── m68k_timer.sv          # Programmable timer
├── boot/
│   ├── bootrom.S          # Boot ROM assembly
│   ├── boot.ld            # Linker script
│   └── Makefile           # Boot image build
├── tests/
│   ├── m68k_linux_boot_tb.sv  # Linux boot testbench
│   └── Makefile           # Simulation build
├── initramfs/
│   └── init.c             # Minimal init program
└── rtl/
    └── m68k_complete.core # FuseSoC core file
```

## Exception Vectors

| Vector | Address | Exception |
|--------|---------|-----------|
| 0 | 0x000 | Initial SSP |
| 1 | 0x004 | Initial PC (Reset) |
| 2 | 0x008 | Bus Error |
| 3 | 0x00C | Address Error |
| 4 | 0x010 | Illegal Instruction |
| 5 | 0x014 | Zero Divide |
| 6 | 0x018 | CHK Instruction |
| 7 | 0x01C | TRAPV Instruction |
| 8 | 0x020 | Privilege Violation |
| 9 | 0x024 | Trace |
| 10 | 0x028 | Line 1010 Emulator |
| 11 | 0x02C | Line 1111 Emulator |
| 24 | 0x060 | Spurious Interrupt |
| 25-31 | 0x064-0x07C | Autovector (Level 1-7) |
| 32-47 | 0x080-0x0BC | TRAP #0-15 |
| 64-255 | 0x100-0x3FC | User Interrupts |

## Debugging

### UART Output

Console output is written to stdout during simulation. The testbench intercepts
writes to the UART TX register and prints characters directly.

### VCD Traces

Enable waveform tracing with:

```bash
make trace
```

View with GTKWave:

```bash
gtkwave m68k_linux_boot.vcd
```

### Progress Monitoring

The testbench prints PC and SR every 1M cycles to show boot progress.

## Known Limitations

1. MMU support is present but not fully integrated with the memory subsystem
2. Cache is not implemented (CACR writes are ignored)
3. FPU instructions are not implemented
4. Coprocessor interface is not implemented

## Future Work

- [ ] Full MMU integration with page table walks
- [ ] Cache simulation
- [ ] FPU support (MC68881/82 compatible)
- [ ] DMA controller
- [ ] Network interface (for NFS root)
