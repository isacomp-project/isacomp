# Minimal initramfs for J2 Linux
#
# Creates a tiny cpio archive containing only:
#   - /init (statically linked, no libc)
#   - /dev/console
#   - /dev/null

# Cross compiler (SH2 big-endian)
# Toolchain executables are wrapped to use qemu-i386-static
TOOLCHAIN = /opt/cross/sh2eb-linux-muslfdpic-cross
CROSS_COMPILE = $(TOOLCHAIN)/bin/sh2eb-linux-muslfdpic-

CC = $(CROSS_COMPILE)gcc
STRIP = $(CROSS_COMPILE)strip
OBJDUMP = $(CROSS_COMPILE)objdump

# Compile flags - static, no libc, freestanding
CFLAGS = -Os -nostdlib -nostartfiles -ffreestanding
LDFLAGS = -static -nostdlib

# Output
INITRAMFS = initramfs.cpio

.PHONY: all clean

all: $(INITRAMFS)

# Build init binary (statically linked, no libc)
init: init.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	$(STRIP) $@
	@echo "Built init: $$(stat -c%s $@) bytes"

# Create minimal cpio archive
$(INITRAMFS): init
	@echo "Creating minimal initramfs..."
	@rm -rf _root
	@mkdir -p _root/dev
	@# Copy init
	@cp init _root/init
	@chmod 755 _root/init
	@# Create device nodes
	@mknod _root/dev/console c 5 1
	@mknod _root/dev/null c 1 3
	@# Create the cpio archive
	@cd _root && find . | cpio -o -H newc > ../$(INITRAMFS)
	@rm -rf _root
	@echo "Created $(INITRAMFS): $$(stat -c%s $(INITRAMFS)) bytes"

# Debug: show init disassembly
disasm: init
	$(OBJDUMP) -d $<

# Debug: list initramfs contents
list: $(INITRAMFS)
	cpio -tv < $(INITRAMFS)

clean:
	rm -f init $(INITRAMFS)
	rm -rf _root
