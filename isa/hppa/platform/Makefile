# HPPA Linux Boot Platform Makefile
#
# Builds the HPPA boot stub, DTB, Verilator simulation, and boots Linux.
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
#   LINUX_DIR         — path to Linux shallow clone (default: ../../../linux-hppa)
#   CROSS             — cross-compile prefix (default: hppa-linux-gnu-)

CROSS    ?= hppa-linux-gnu-
AS       := $(CROSS)as
LD       := $(CROSS)ld
OBJCOPY  := $(CROSS)objcopy
OBJDUMP  := $(CROSS)objdump

VERILATOR ?= verilator
DTC       ?= dtc
PYTHON3   ?= python3

# Repository root (two levels up from platform/)
REPO_ROOT := ../..

# Generated Verilog
VERILOG_DIR := $(REPO_ROOT)/examples/verilog/hppa
HPPA_V      := $(VERILOG_DIR)/hppa.v

# Testbench
TB_DIR  := tests
TB_SRC  := $(TB_DIR)/hppa_boot_tb.sv

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
DTS_SRC := hppa_isacomp.dts
DTB_OUT := $(BOOT_DIR)/hppa_isacomp.dtb

# Linux kernel (optional — set LINUX_DIR)
LINUX_DIR  ?= $(REPO_ROOT)/linux-hppa
VMLINUX    := $(LINUX_DIR)/vmlinux
VMLINUX_BIN := $(BOOT_DIR)/vmlinux.bin

# Combined boot image
BOOT_COMBINED := $(BOOT_DIR)/boot_combined.bin

# Verilator output
SIM_DIR := obj_dir
SIM     := $(SIM_DIR)/Vhppa_boot_tb

# Vendor files (FPU)
VENDOR_DIR := $(REPO_ROOT)/vendor

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
	@echo "Bootrom: $@ ($(shell wc -c < $@) bytes)"

.PHONY: disasm
disasm: $(BOOTROM_ELF)
	$(OBJDUMP) -d $(BOOTROM_ELF)

# =========================================================================
# Firmware (PDC/IODC entry points at 0x0F000000 and 0x0F000400)
# Linked at ROM address outside 64MB RAM to avoid kernel memset
# Loaded separately by testbench (not in boot_combined.bin)
# =========================================================================
$(FIRMWARE_ELF): $(FIRMWARE_S)
	$(AS) -o $(BOOT_DIR)/firmware.o $(FIRMWARE_S)
	$(LD) -Ttext=0x0F000000 -o $@ $(BOOT_DIR)/firmware.o

$(FIRMWARE_BIN): $(FIRMWARE_ELF)
	$(OBJCOPY) -O binary $< $@
	@echo "Firmware: $@ ($(shell wc -c < $@) bytes)"

.PHONY: disasm-firmware
disasm-firmware: $(FIRMWARE_ELF)
	$(OBJDUMP) -d $(FIRMWARE_ELF)

# =========================================================================
# Device tree blob
# =========================================================================
$(DTB_OUT): $(DTS_SRC) | $(BOOT_DIR)
	$(DTC) -I dts -O dtb -o $@ $<
	@echo "DTB: $@"

$(BOOT_DIR):
	mkdir -p $(BOOT_DIR)

# =========================================================================
# Verilog generation (regenerate if ISA files are newer)
# =========================================================================
$(HPPA_V): $(wildcard $(REPO_ROOT)/isa/hppa/*.isa \
                       $(REPO_ROOT)/isa/hppa/mmu/*.isa)
	mkdir -p $(VERILOG_DIR)
	cd $(REPO_ROOT) && $(PYTHON3) isa/hppa/generators/generate_hppa.py -o examples/verilog/hppa

# =========================================================================
# Verilator simulation build
# =========================================================================
VERILATOR_FLAGS := \
	--binary \
	--timing \
	--top-module hppa_boot_tb \
	-Wno-WIDTHEXPAND \
	-Wno-WIDTHTRUNC \
	-Wno-MULTIDRIVEN \
	-Wno-UNOPTFLAT \
	-j 0

FPU_STUB    := cvfpu_simple_stub.sv

$(SIM): $(TB_SRC) $(HPPA_V) $(FPU_STUB)
	$(VERILATOR) $(VERILATOR_FLAGS) \
		$(TB_SRC) $(FPU_STUB) $(HPPA_V) \
		-o Vhppa_boot_tb

# =========================================================================
# Combined boot image: bootrom at 0x1000, kernel at 0x100000
# Firmware is loaded separately by testbench at ROM address 0x0F000000
# =========================================================================
BOOT_SIZE := $(shell test -f $(BOOTROM_BIN) && wc -c < $(BOOTROM_BIN) || echo 0)
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
# Linux kernel build
# =========================================================================
.PHONY: kernel
kernel: $(VMLINUX_BIN)

$(VMLINUX_BIN): $(VMLINUX)
	$(OBJCOPY) -O binary $< $@
	@echo "Kernel binary: $@ ($(shell wc -c < $@ 2>/dev/null || echo '?') bytes)"

$(VMLINUX):
	@echo "Building Linux kernel in $(LINUX_DIR)..."
	$(MAKE) -C $(LINUX_DIR) ARCH=parisc CROSS_COMPILE=$(CROSS) parisc_defconfig
	$(MAKE) -C $(LINUX_DIR) ARCH=parisc CROSS_COMPILE=$(CROSS) -j$$(nproc)

# =========================================================================
# Run simulation
# =========================================================================
.PHONY: boot
boot: $(SIM) $(BOOT_COMBINED) $(DTB_OUT) $(FIRMWARE_BIN)
	cd $(BOOT_DIR) && \
	../$(SIM) \
		+boot=boot_combined.bin \
		+fdt=hppa_isacomp.dtb \
		+entry=0x1000

.PHONY: boot-trace
boot-trace: $(SIM) $(BOOT_COMBINED) $(DTB_OUT)
	cd $(BOOT_DIR) && \
	../$(SIM) \
		+boot=boot_combined.bin \
		+fdt=hppa_isacomp.dtb \
		+entry=0x1000 \
		+trace

# =========================================================================
# Validate DTB
# =========================================================================
.PHONY: check-dtb
check-dtb: $(DTB_OUT)
	$(DTC) -I dtb -O dts $(DTB_OUT)

# =========================================================================
# Clean
# =========================================================================
.PHONY: clean
clean:
	rm -f $(BOOT_DIR)/bootrom.o $(BOOTROM_ELF) $(BOOTROM_BIN)
	rm -f $(BOOT_DIR)/firmware.o $(FIRMWARE_ELF) $(FIRMWARE_BIN)
	rm -f $(DTB_OUT) $(VMLINUX_BIN) $(BOOT_COMBINED)
	rm -rf $(SIM_DIR)
	rm -f uart_output.txt hppa_boot.vcd

.PHONY: distclean
distclean: clean
	rm -f $(HPPA_V) $(REPO_ROOT)/examples/verilog/hppa/hppa_tb.sv \
	      $(REPO_ROOT)/examples/verilog/hppa/hppa.core
