# Minimal initramfs for HPPA Linux
#
# Creates a tiny cpio archive containing:
#   /init         - statically linked, no libc
#   /dev/console  - console device node
#   /dev/null     - null device node
#   /dev/kmsg     - kernel message device

CROSS_COMPILE ?= hppa-linux-gnu-
CC = $(CROSS_COMPILE)gcc
STRIP = $(CROSS_COMPILE)strip
OBJDUMP = $(CROSS_COMPILE)objdump

CFLAGS = -nostdlib -nostartfiles -ffreestanding -static -Os

INITRAMFS = initramfs.cpio

.PHONY: all clean disasm

all: $(INITRAMFS)

init: init.S
	$(CC) $(CFLAGS) -o $@ $<
	$(STRIP) $@
	@echo "Built init: $$(stat -c%s $$@) bytes"

$(INITRAMFS): init gen_initramfs.py
	python3 gen_initramfs.py init $(INITRAMFS)

disasm: init
	$(OBJDUMP) -d $<

clean:
	rm -f init $(INITRAMFS)
