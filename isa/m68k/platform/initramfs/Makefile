CROSS = m68k-linux-gnu-
CC = $(CROSS)gcc
OBJCOPY = $(CROSS)objcopy

all: initramfs.cpio

init.o: init.c
	$(CC) -m68030 -nostdlib -nostartfiles -static -Os -c -o $@ $<

init: init.o init.ld
	$(CC) -m68030 -nostdlib -nostartfiles -static -T init.ld -o $@ $<
	$(CROSS)strip $@

initramfs.cpio: init gen_initramfs.py
	python3 gen_initramfs.py init initramfs.cpio

clean:
	rm -f init init.o initramfs.cpio
