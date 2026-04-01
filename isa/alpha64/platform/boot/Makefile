# Alpha64 Boot Image Makefile
#
# Builds PALcode + boot ROM into a single binary image.
# Optionally includes a kernel binary.
#
# Usage:
#   make              - Build boot.bin (PALcode + boot ROM only)
#   make boot.bin     - Same as above
#   make boot_with_kernel.elf - Build with kernel included
#   make clean        - Remove build artifacts

CROSS = alpha-linux-gnu-
CC = $(CROSS)gcc
LD = $(CROSS)ld
OBJCOPY = $(CROSS)objcopy

all: boot.bin

palcode.o: palcode.S
	$(CC) -c -o $@ $<

bootrom.o: bootrom.S
	$(CC) -c -o $@ $<

boot.elf: palcode.o bootrom.o boot.ld
	$(LD) -T boot.ld -o $@ palcode.o bootrom.o

boot.bin: boot.elf
	$(OBJCOPY) -O binary $< $@

# Build with kernel: converts raw kernel binary to ELF object, then links
boot_with_kernel.elf: palcode.o bootrom.o kernel.bin boot.ld
	$(OBJCOPY) -I binary -O elf64-alpha -B alpha kernel.bin kernel.o
	$(LD) -T boot.ld -o $@ palcode.o bootrom.o kernel.o

clean:
	rm -f *.o *.elf *.bin

.PHONY: all clean
