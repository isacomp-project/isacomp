# OpenRISC OR1K Linux Platform Makefile
#
# Builds the platform components for ISAComp OR1K Linux boot
#
# Targets:
#   all            - Build DTB, bootrom, and generate processor
#   generate       - Generate processor Verilog (default: with FP, no ext memory)
#   generate-ext   - Generate processor with externalized memory (for Linux boot)
#   dtb            - Compile device tree
#   bootrom        - Build boot ROM
#   sim-iverilog   - Build Icarus Verilog simulation (linux_boot_tb)
#   sim-verilator  - Build Verilator simulation (linux_boot_tb)
#   run            - Run Linux boot simulation
#   clean          - Remove build artifacts
#
# Requirements:
#   - or1k-elf-gcc (OpenRISC cross compiler) - for bootrom
#   - dtc (device tree compiler)
#   - python3 (for ISAComp generator)
#   - iverilog or verilator (for simulation)

CROSS_COMPILE ?= or1k-elf-
CC = $(CROSS_COMPILE)gcc
AS = $(CROSS_COMPILE)as
LD = $(CROSS_COMPILE)ld
OBJCOPY = $(CROSS_COMPILE)objcopy
DTC ?= dtc

# Directories
BOOT_DIR = boot
BUILD_DIR = build
TEST_DIR = tests

# ISAComp root
ISACOMP_ROOT = ../../..

# Generated Verilog directories
VERILOG_DIR = $(ISACOMP_ROOT)/examples/verilog/or1k_mmu
VERILOG_EXT_DIR = $(ISACOMP_ROOT)/examples/verilog/or1k_mmu_ext

# Simulation parameters
FIRMWARE ?= vmlinux.bin
FDT_FILE ?= $(BUILD_DIR)/or1k_isacomp.dtb
ENTRY_POINT ?= 0x00000100
FDT_ADDR ?= 0x03F00000
MAX_CYCLES ?= 1500000000

.PHONY: all clean dtb bootrom generate generate-ext generate-nofp \
        sim-iverilog sim-verilator run help

all: dtb bootrom generate

help:
	@echo "OR1K Linux Platform Build System"
	@echo "================================"
	@echo ""
	@echo "Build targets:"
	@echo "  all              - Build DTB, bootrom, and generate processor"
	@echo "  generate         - Generate OR1K+MMU+FP Verilog (embedded memory)"
	@echo "  generate-ext     - Generate OR1K+MMU+FP Verilog (externalized memory)"
	@echo "  generate-nofp    - Generate without FP instructions"
	@echo "  dtb              - Compile device tree blob"
	@echo "  bootrom          - Build boot ROM hex file"
	@echo ""
	@echo "Simulation targets:"
	@echo "  sim-iverilog     - Build simulation with Icarus Verilog"
	@echo "  sim-verilator    - Build simulation with Verilator"
	@echo "  run              - Run Linux boot simulation"
	@echo ""
	@echo "Simulation parameters (override with make VAR=value):"
	@echo "  FIRMWARE         - Firmware binary (default: vmlinux.bin)"
	@echo "  FDT_FILE         - Device tree blob (default: build/or1k_isacomp.dtb)"
	@echo "  ENTRY_POINT      - CPU entry point (default: 0x00000000)"
	@echo "  FDT_ADDR         - FDT load address (default: 0x03F00000)"
	@echo "  MAX_CYCLES       - Simulation timeout (default: 1500000000)"

# =========================================================================
# Device Tree
# =========================================================================
dtb: $(BUILD_DIR)/or1k_isacomp.dtb

$(BUILD_DIR)/or1k_isacomp.dtb: or1k_isacomp.dts | $(BUILD_DIR)
	$(DTC) -I dts -O dtb -o $@ $<
	@echo "Device tree compiled: $@"

# =========================================================================
# Boot ROM
# =========================================================================
bootrom: $(BUILD_DIR)/bootrom.hex

$(BUILD_DIR)/bootrom.o: $(BOOT_DIR)/bootrom.S | $(BUILD_DIR)
	$(AS) -o $@ $<

$(BUILD_DIR)/bootrom.elf: $(BUILD_DIR)/bootrom.o
	$(LD) -Ttext 0x00000000 -o $@ $<

$(BUILD_DIR)/bootrom.bin: $(BUILD_DIR)/bootrom.elf
	$(OBJCOPY) -O binary $< $@

$(BUILD_DIR)/bootrom.hex: $(BUILD_DIR)/bootrom.bin
	od -An -tx4 -w4 $< | sed 's/^ *//' > $@
	@echo "Boot ROM compiled: $@"

# =========================================================================
# Processor Generation
# =========================================================================

# Default: generate with FP, embedded memory
generate:
	cd $(ISACOMP_ROOT) && python3 isa/or1k/generators/generate_or1k_mmu.py
	@echo "Generated OR1K+MMU+FP processor to $(VERILOG_DIR)/"

# Generate with externalized memory (for Linux boot testbench)
generate-ext:
	cd $(ISACOMP_ROOT) && python3 isa/or1k/generators/generate_or1k_mmu.py --externalize-memory
	@echo "Generated OR1K+MMU+FP processor with ext memory to $(VERILOG_EXT_DIR)/"

# Generate without FP
generate-nofp:
	cd $(ISACOMP_ROOT) && python3 isa/or1k/generators/generate_or1k_mmu.py --no-fp

# =========================================================================
# Simulation Build
# =========================================================================

# Icarus Verilog simulation build
sim-iverilog: generate-ext dtb | $(BUILD_DIR)
	iverilog -g2012 -o $(BUILD_DIR)/or1k_sim \
		$(VERILOG_EXT_DIR)/or1k_mmu.v \
		$(TEST_DIR)/linux_boot_tb.sv \
		$(TEST_DIR)/fake_uart.sv \
		$(TEST_DIR)/or1k_tick_timer.sv \
		$(TEST_DIR)/or1k_pic.sv \
		-s linux_boot_tb \
		-DSIMULATION
	@echo "Icarus Verilog simulation built: $(BUILD_DIR)/or1k_sim"

# Verilator simulation build
sim-verilator: generate-ext dtb | $(BUILD_DIR)
	verilator --cc --exe --build \
		-DSIMULATION \
		--top-module linux_boot_tb \
		-Wno-fatal \
		--timing \
		-o $(BUILD_DIR)/or1k_sim_verilator \
		$(VERILOG_EXT_DIR)/or1k_mmu.v \
		$(TEST_DIR)/linux_boot_tb.sv \
		$(TEST_DIR)/fake_uart.sv \
		$(TEST_DIR)/or1k_tick_timer.sv \
		$(TEST_DIR)/or1k_pic.sv
	@echo "Verilator simulation built: $(BUILD_DIR)/or1k_sim_verilator"

# Run simulation
run: $(BUILD_DIR)/or1k_sim
	cd $(BUILD_DIR) && ./or1k_sim \
		+firmware=$(abspath $(FIRMWARE)) \
		+fdt_file=$(abspath $(FDT_FILE)) \
		+entry=$(ENTRY_POINT) \
		+fdt=$(FDT_ADDR) \
		+max_cycles=$(MAX_CYCLES)

# =========================================================================
# Utilities
# =========================================================================
$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

clean:
	rm -rf $(BUILD_DIR)
	@echo "Build directory cleaned"
