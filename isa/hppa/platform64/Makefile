# HPPA 2.0 Linux Boot Platform Makefile
#
# Builds the HPPA 2.0 boot stub, DTB, Verilator simulation, and boots Linux.
#
# Prerequisites:
#   - hppa-linux-gnu-{as,ld,objcopy,objdump}  (apt: gcc-hppa-linux-gnu binutils-hppa-linux-gnu)
#   - verilator (apt: verilator)
#   - dtc (apt: device-tree-compiler)
#   - python3 (for generator)
#
# Usage:
#   make all          — build bootrom, DTB, and Verilator sim
#   make boot         — run simulation with boot_combined.bin
#   make kernel       — build Linux (requires LINUX_DIR)
#   make clean        — remove generated files
#
# Environment:
#   LINUX_DIR         — path to Linux shallow clone (default: ../../linux-hppa)
#   CROSS             — cross-compile prefix (default: hppa-linux-gnu-)

CROSS    ?= hppa-linux-gnu-
AS       := $(CROSS)as
LD       := $(CROSS)ld
OBJCOPY  := $(CROSS)objcopy
OBJDUMP  := $(CROSS)objdump

VERILATOR ?= verilator
DTC       ?= dtc
PYTHON3   ?= python3

# Repository root (two levels up from platform64/)
REPO_ROOT := ../..

# Generated Verilog (PA-RISC 2.0)
VERILOG_DIR := $(REPO_ROOT)/examples/verilog/hppa20
HPPA_V      := $(VERILOG_DIR)/hppa20.v

# Testbench
TB_DIR  := tests
TB_SRC  := $(TB_DIR)/hppa20_boot_tb.sv

# Boot files
BOOT_DIR    := boot
BOOTROM_S   := $(BOOT_DIR)/bootrom.S
BOOTROM_ELF := $(BOOT_DIR)/bootrom.elf
BOOTROM_BIN := $(BOOT_DIR)/bootrom.bin

# Firmware (PDC/IODC)
FIRMWARE_S   := $(BOOT_DIR)/firmware.S
FIRMWARE_ELF := $(BOOT_DIR)/firmware.elf
FIRMWARE_BIN := $(BOOT_DIR)/firmware.bin

# Device tree
DTS_SRC := hppa20_isacomp.dts
DTB_OUT := $(BOOT_DIR)/hppa20_isacomp.dtb

# Linux kernel (optional — set LINUX_DIR)
LINUX_DIR  ?= $(REPO_ROOT)/linux-hppa
VMLINUX    := $(LINUX_DIR)/vmlinux
VMLINUX_BIN := $(BOOT_DIR)/vmlinux.bin

# Combined boot image
BOOT_COMBINED := $(BOOT_DIR)/boot_combined.bin

# Verilator output
SIM_DIR := obj_dir
SIM     := $(SIM_DIR)/Vhppa20_boot_tb

# =========================================================================
# Default target
# =========================================================================
.PHONY: all
all: $(BOOTROM_BIN) $(DTB_OUT) $(SIM)

# =========================================================================
# Boot stub
# =========================================================================
$(BOOTROM_ELF): $(BOOTROM_S)
	$(AS) -o $(BOOT_DIR)/bootrom.o $(BOOTROM_S)
	$(LD) -Ttext=0x1000 -o $@ $(BOOT_DIR)/bootrom.o

$(BOOTROM_BIN): $(BOOTROM_ELF)
	$(OBJCOPY) -O binary $< $@
	@echo "Bootrom: $@ ($$(wc -c < $@) bytes)"

.PHONY: disasm
disasm: $(BOOTROM_ELF)
	$(OBJDUMP) -d $(BOOTROM_ELF)

# =========================================================================
# Firmware (PDC/IODC entry points at 0x0F000000 and 0x0F000400)
# =========================================================================
$(FIRMWARE_ELF): $(FIRMWARE_S)
	$(AS) -o $(BOOT_DIR)/firmware.o $(FIRMWARE_S)
	$(LD) -Ttext=0x0F000000 -o $@ $(BOOT_DIR)/firmware.o

$(FIRMWARE_BIN): $(FIRMWARE_ELF)
	$(OBJCOPY) -O binary $< $@
	@echo "Firmware: $@ ($$(wc -c < $@) bytes)"

# =========================================================================
# Device tree blob
# =========================================================================
$(DTB_OUT): $(DTS_SRC) | $(BOOT_DIR)
	$(DTC) -I dts -O dtb -o $@ $<
	@echo "DTB: $@"

boot_dir_stamp:
	mkdir -p $(BOOT_DIR)

# =========================================================================
# Verilog generation (regenerate if ISA files are newer)
# =========================================================================
$(HPPA_V): $(wildcard $(REPO_ROOT)/isa/hppa/20/*.isa \
                       $(REPO_ROOT)/isa/hppa/20/mmu/*.isa)
	mkdir -p $(VERILOG_DIR)
	cd $(REPO_ROOT) && $(PYTHON3) isa/hppa/20/generators/generate_hppa20.py -o examples/verilog/hppa20

# =========================================================================
# Verilator simulation build
# =========================================================================
VERILATOR_FLAGS := \
	--binary \
	--timing \
	--top-module hppa20_boot_tb \
	-Wno-WIDTHEXPAND \
	-Wno-WIDTHTRUNC \
	-Wno-MULTIDRIVEN \
	-Wno-UNOPTFLAT \
	-j 0

FPU_STUB    := cvfpu_simple_stub.sv

$(SIM): $(TB_SRC) $(HPPA_V) $(FPU_STUB)
	$(VERILATOR) $(VERILATOR_FLAGS) \
		$(TB_SRC) $(FPU_STUB) $(HPPA_V) \
		-o Vhppa20_boot_tb

# =========================================================================
# Combined boot image: bootrom at 0x1000, kernel at 0x100000
# =========================================================================
KERNEL_OFFSET := 0x100000

$(BOOT_COMBINED): $(BOOTROM_BIN) $(VMLINUX_BIN)
	@echo "Creating combined boot image..."
	@KERNEL_SIZE=$$(wc -c < $(VMLINUX_BIN)); \
	TOTAL=$$(( $(KERNEL_OFFSET) + $$KERNEL_SIZE )); \
	truncate -s $$TOTAL $@; \
	dd if=$(BOOTROM_BIN) bs=1 seek=4096 conv=notrunc of=$@ 2>/dev/null; \
	dd if=$(VMLINUX_BIN) bs=1 seek=$$(( $(KERNEL_OFFSET) )) conv=notrunc of=$@ 2>/dev/null; \
	echo "Combined image: $@ ($${TOTAL} bytes)"

# =========================================================================
# Linux kernel build (32-bit parisc on PA-RISC 2.0 CPU)
# =========================================================================
.PHONY: kernel
kernel: $(VMLINUX_BIN)

$(VMLINUX_BIN): $(VMLINUX)
	$(OBJCOPY) -O binary $< $@
	@echo "Kernel binary: $@ ($$(wc -c < $@ 2>/dev/null || echo '?') bytes)"

$(VMLINUX):
	@echo "Building Linux kernel in $(LINUX_DIR)..."
	$(MAKE) -C $(LINUX_DIR) ARCH=parisc CROSS_COMPILE=$(CROSS) generic-32bit_defconfig
	$(MAKE) -C $(LINUX_DIR) ARCH=parisc CROSS_COMPILE=$(CROSS) -j$$(nproc)

# =========================================================================
# Run simulation
# =========================================================================
.PHONY: boot
boot: $(SIM) $(BOOT_COMBINED) $(DTB_OUT) $(FIRMWARE_BIN)
	cd $(BOOT_DIR) && \
	../$(SIM) \
		+boot=boot_combined.bin \
		+fdt=hppa20_isacomp.dtb \
		+firmware=firmware.bin \
		+entry=0x1000

.PHONY: boot-trace
boot-trace: $(SIM) $(BOOT_COMBINED) $(DTB_OUT) $(FIRMWARE_BIN)
	cd $(BOOT_DIR) && \
	../$(SIM) \
		+boot=boot_combined.bin \
		+fdt=hppa20_isacomp.dtb \
		+firmware=firmware.bin \
		+entry=0x1000 \
		+trace

# =========================================================================
# Clean
# =========================================================================
.PHONY: clean
clean:
	rm -f $(BOOT_DIR)/bootrom.o $(BOOTROM_ELF) $(BOOTROM_BIN)
	rm -f $(BOOT_DIR)/firmware.o $(FIRMWARE_ELF) $(FIRMWARE_BIN)
	rm -f $(DTB_OUT) $(VMLINUX_BIN) $(BOOT_COMBINED)
	rm -rf $(SIM_DIR)
	rm -f uart_output.txt hppa20_boot.vcd

.PHONY: distclean
distclean: clean
	rm -f $(HPPA_V) $(REPO_ROOT)/examples/verilog/hppa20/hppa20_tb.sv \
	      $(REPO_ROOT)/examples/verilog/hppa20/hppa20.core
