# Minimal initramfs for J4 (SH4) Linux
#
# Creates a tiny cpio archive containing:
#   /init         - statically linked, no libc
#   /dev/console  - console device node
#   /dev/null     - null device node
#
# Uses sh-elf bare-metal toolchain for SH4 big-endian assembly

CROSS_COMPILE ?= sh-elf-

AS = $(CROSS_COMPILE)as
LD = $(CROSS_COMPILE)ld
OBJCOPY = $(CROSS_COMPILE)objcopy
OBJDUMP = $(CROSS_COMPILE)objdump
STRIP = $(CROSS_COMPILE)strip

# Assembly flags: SH4, big-endian
ASFLAGS = -big --isa=sh4

# Linker flags: big-endian SH ELF
LDFLAGS = -m shelf -T init.ld

# Output
INITRAMFS = initramfs.cpio

.PHONY: all clean

all: $(INITRAMFS)

# Assemble init
init.o: init.S
	$(AS) $(ASFLAGS) -o $@ $<

# Link init binary
init: init.o init.ld
	$(LD) $(LDFLAGS) -o $@ init.o
	$(STRIP) $@
	@echo "Built init: $$(stat -c%s $@) bytes"

# Create minimal cpio archive (no root needed)
$(INITRAMFS): init gen_initramfs.py
	python3 gen_initramfs.py init $(INITRAMFS)

# Debug: show init disassembly
disasm: init
	$(OBJDUMP) -d $<

# Debug: show ELF header
elfinfo: init
	$(CROSS_COMPILE)readelf -h $< 2>/dev/null || readelf -h $<

clean:
	rm -f init init.o $(INITRAMFS)
