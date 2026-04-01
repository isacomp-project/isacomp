# Minimal initramfs for RISC-V 64 Linux
#
# Builds a static /init binary. The kernel build system creates the
# cpio archive from initramfs_list (CONFIG_INITRAMFS_SOURCE).

CROSS_COMPILE ?= riscv64-linux-gnu-
CC = $(CROSS_COMPILE)gcc
STRIP = $(CROSS_COMPILE)strip

MARCH = rv64ima
MABI = lp64
CFLAGS = -march=$(MARCH) -mabi=$(MABI) -nostdlib -static

.PHONY: all clean

all: init

init: init.S
	$(CC) $(CFLAGS) -o $@ $<
	$(STRIP) $@
	@echo "Built init: $$(stat -c%s $$@) bytes"

clean:
	rm -f init
