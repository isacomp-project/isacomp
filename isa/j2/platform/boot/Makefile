# J2 Linux Boot Image Builder
#
# Combines:
#   - Boot ROM (sets R4=FDT, jumps to kernel)
#   - Device Tree Blob
#   - Linux kernel
#
# Usage:
#   make KERNEL=path/to/vmlinux.bin DTB=path/to/j2.dtb

# Cross compiler (SH2 big-endian)
# Use sh-elf tools for assembly/linking (supports elf32-sh target)
CROSS_COMPILE ?= sh-elf-

AS = $(CROSS_COMPILE)as
LD = $(CROSS_COMPILE)ld
OBJCOPY = $(CROSS_COMPILE)objcopy
NM = $(CROSS_COMPILE)nm

# Input files
# Note: Initramfs is embedded in kernel via CONFIG_INITRAMFS_SOURCE
KERNEL ?= ../../../linux/vmlinux.bin
DTB ?= ../j2_isacomp.dtb

# Output files
BOOTROM_ELF = bootrom.elf
BOOTROM_BIN = bootrom.bin
BOOT_IMAGE = boot.bin

# Assembly flags (SH2, big-endian)
ASFLAGS = -big --isa=sh2

# Linker flags
LDFLAGS = -T boot.ld -nostdlib

.PHONY: all clean

all: $(BOOT_IMAGE)

# Assemble boot ROM
bootrom.o: bootrom.S
	$(AS) $(ASFLAGS) -o $@ $<

# Create binary section for FDT
fdt.o: $(DTB)
	$(OBJCOPY) -I binary -O elf32-shbig-linux -B sh \
		--rename-section .data=.fdt \
		$< $@

# Create binary section for kernel
kernel.o: $(KERNEL)
	$(OBJCOPY) -I binary -O elf32-shbig-linux -B sh \
		--rename-section .data=.kernel \
		$< $@

# Note: Initramfs is embedded in the kernel via CONFIG_INITRAMFS_SOURCE
# No separate initramfs section needed

# Link everything together
$(BOOTROM_ELF): bootrom.o fdt.o kernel.o boot.ld
	$(LD) $(LDFLAGS) -o $@ bootrom.o fdt.o kernel.o
	@echo "Linked boot image:"
	@$(CROSS_COMPILE)size $@

# Create flat binary for simulation
$(BOOT_IMAGE): $(BOOTROM_ELF)
	$(OBJCOPY) -O binary $< $@
	@echo "Created boot image: $@ ($$(stat -c%s $@) bytes)"
	@echo ""
	@echo "Memory layout:"
	@echo "  0x00000000 - Boot ROM entry (_start)"
	@echo "  0x00000100 - FDT"
	@echo "  0x00001000 - Kernel binary start"
	@echo "  0x00002000 - Kernel entry (_stext)"
	@echo "  (Initramfs embedded in kernel)"

# Also create a raw binary without boot ROM (for direct kernel boot)
vmlinux.bin: $(KERNEL)
	cp $< $@

clean:
	rm -f *.o $(BOOTROM_ELF) $(BOOTROM_BIN) $(BOOT_IMAGE)

# Debug: show symbols
symbols: $(BOOTROM_ELF)
	$(NM) $< | sort

# Debug: disassemble
disasm: $(BOOTROM_ELF)
	$(CROSS_COMPILE)objdump -d $<
