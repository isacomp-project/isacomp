# Minimal initramfs for OpenRISC OR1K Linux
#
# Builds a static /init binary and generates initramfs.cpio.
# Use CONFIG_INITRAMFS_SOURCE to embed in kernel.

CROSS_COMPILE ?= or1k-elf-
CC = $(CROSS_COMPILE)gcc
STRIP = $(CROSS_COMPILE)strip

CFLAGS = -nostdlib -static -Wl,-Ttext=0x100

.PHONY: all clean

all: initramfs.cpio

init: init.S
	$(CC) $(CFLAGS) -o $@ $<
	$(STRIP) $@

initramfs.cpio: init gen_initramfs.py
	python3 gen_initramfs.py init initramfs.cpio

clean:
	rm -f init initramfs.cpio
