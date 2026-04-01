# M68K Linux Boot Image Build System
#
# Prerequisites:
#   - m68k-linux-gnu toolchain (or m68k-elf)
#   - Device tree compiler (dtc)
#   - Linux kernel source (for vmlinux)
#
# Targets:
#   make all       - Build boot ROM and combined image
#   make clean     - Clean build artifacts
#   make dtb       - Compile device tree
#   make bootrom   - Build boot ROM only

# Toolchain
CROSS_COMPILE ?= m68k-linux-gnu-
AS = $(CROSS_COMPILE)as
LD = $(CROSS_COMPILE)ld
OBJCOPY = $(CROSS_COMPILE)objcopy
OBJDUMP = $(CROSS_COMPILE)objdump

# Device tree compiler
DTC ?= dtc

# Kernel paths (override these)
KERNEL_DIR ?= /path/to/linux
KERNEL_BIN ?= $(KERNEL_DIR)/vmlinux.bin

# Output files
BOOTROM_ELF = bootrom.elf
BOOTROM_BIN = bootrom.bin
DTB = ../m68k_linux.dtb
DTS = ../m68k_linux.dts
BOOT_IMAGE = boot.bin

# Assembler flags
ASFLAGS = -m68030

# Linker flags
LDFLAGS = -T boot.ld -nostdlib

.PHONY: all clean dtb bootrom

all: $(BOOT_IMAGE)

# Compile device tree
dtb: $(DTB)

$(DTB): $(DTS)
	$(DTC) -I dts -O dtb -o $@ $<

# Build boot ROM
bootrom: $(BOOTROM_BIN)

$(BOOTROM_ELF): bootrom.S boot.ld
	$(AS) $(ASFLAGS) -o bootrom.o bootrom.S
	$(LD) $(LDFLAGS) -o $@ bootrom.o

$(BOOTROM_BIN): $(BOOTROM_ELF)
	$(OBJCOPY) -O binary $< $@
	$(OBJDUMP) -d $< > bootrom.dis

# Create combined boot image
# For simulation, we just need the boot ROM vectors and kernel
# The testbench loads this directly into memory

$(BOOT_IMAGE): $(BOOTROM_BIN) $(DTB)
	@echo "Creating boot image..."
	@if [ ! -f "$(KERNEL_BIN)" ]; then \
		echo "Note: Kernel binary not found at $(KERNEL_BIN)"; \
		echo "Creating minimal boot image with boot ROM only"; \
		cp $(BOOTROM_BIN) $@; \
	else \
		echo "Combining bootrom + kernel + dtb..."; \
		./create_boot_image.sh $(BOOTROM_BIN) $(KERNEL_BIN) $(DTB) $@; \
	fi
	@echo "Boot image created: $@ ($$(stat -c%s $@ 2>/dev/null || stat -f%z $@) bytes)"

clean:
	rm -f *.o *.elf *.bin *.dis $(DTB)

# Help target
help:
	@echo "M68K Linux Boot Image Build System"
	@echo ""
	@echo "Targets:"
	@echo "  all       - Build complete boot image"
	@echo "  bootrom   - Build boot ROM only"
	@echo "  dtb       - Compile device tree"
	@echo "  clean     - Remove build artifacts"
	@echo ""
	@echo "Configuration:"
	@echo "  CROSS_COMPILE - Toolchain prefix (default: m68k-linux-gnu-)"
	@echo "  KERNEL_DIR    - Path to Linux kernel source"
	@echo "  KERNEL_BIN    - Path to kernel binary (vmlinux.bin)"
