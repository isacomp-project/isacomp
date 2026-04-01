# Minimal initramfs for Alpha64 Linux
#
# Builds a static /init binary. The kernel build system creates the
# cpio archive from initramfs_list (CONFIG_INITRAMFS_SOURCE).

CROSS_COMPILE ?= alpha-linux-gnu-
CC = $(CROSS_COMPILE)gcc
STRIP = $(CROSS_COMPILE)strip

CFLAGS = -nostdlib -static

.PHONY: all clean

all: init

init: init.S
	$(CC) $(CFLAGS) -I../../.. -o $@ $<
	$(STRIP) $@
	@echo "Built init: $$(stat -c%s $$@) bytes"

clean:
	rm -f init
