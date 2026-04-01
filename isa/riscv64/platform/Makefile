# ISAComp RISC-V 64 MMU Platform Makefile
# Builds OpenSBI and runs simulation

TOPDIR := $(shell pwd)/../..
PLATFORM_DIR := $(TOPDIR)/isa/riscv64/platform
TEST_DIR := $(PLATFORM_DIR)/tests
VERILOG_DIR := $(TOPDIR)/examples/verilog/riscv64_mmu

# Tools
VERILATOR := verilator
DTC := dtc
RISCV_PREFIX ?= riscv64-unknown-elf-

# OpenSBI configuration
OPENSBI_DIR ?= $(TOPDIR)/opensbi
OPENSBI_PLATFORM := generic
OPENSBI_FW_PAYLOAD_OFFSET := 0x200000
OPENSBI_CROSS_COMPILE ?= riscv64-linux-gnu-
# ISAComp RV64 implements IMA only (no C extension)
OPENSBI_ISA := rv64ima_zicsr_zifencei
OPENSBI_ABI := lp64

# Linux kernel configuration
LINUX_DIR ?= $(TOPDIR)/linux
LINUX_IMAGE := $(LINUX_DIR)/arch/riscv/boot/Image

# Output directories
BUILD_DIR := $(PLATFORM_DIR)/build
SIM_DIR := $(BUILD_DIR)/sim

.PHONY: all clean dtb opensbi verilator sim

all: dtb opensbi verilator

# Create build directories
$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(SIM_DIR):
	mkdir -p $(SIM_DIR)

# Compile device tree
dtb: $(BUILD_DIR)/riscv64_mmu.dtb

$(BUILD_DIR)/riscv64_mmu.dtb: $(PLATFORM_DIR)/riscv64_mmu.dts | $(BUILD_DIR)
	$(DTC) -I dts -O dtb -o $@ $<
	@echo "Device tree compiled: $@"

# Clone OpenSBI if not present
$(OPENSBI_DIR):
	git clone https://github.com/riscv-software-src/opensbi.git $(OPENSBI_DIR)

opensbi: $(BUILD_DIR)/fw_payload.bin

$(BUILD_DIR)/fw_payload.bin: $(LINUX_IMAGE) | $(OPENSBI_DIR) $(BUILD_DIR)
	@if [ ! -f $(LINUX_IMAGE) ]; then \
		echo "Error: Linux kernel Image not found at $(LINUX_IMAGE)"; \
		echo "Build the kernel first: cd $(LINUX_DIR) && make ARCH=riscv CROSS_COMPILE=$(OPENSBI_CROSS_COMPILE) Image"; \
		exit 1; \
	fi
	cd $(OPENSBI_DIR) && $(MAKE) CROSS_COMPILE=$(OPENSBI_CROSS_COMPILE) \
		PLATFORM=$(OPENSBI_PLATFORM) \
		FW_PAYLOAD_PATH=$(LINUX_IMAGE) \
		FW_PAYLOAD_OFFSET=$(OPENSBI_FW_PAYLOAD_OFFSET) \
		PLATFORM_RISCV_ISA=$(OPENSBI_ISA) \
		PLATFORM_RISCV_ABI=$(OPENSBI_ABI)
	cp $(OPENSBI_DIR)/build/platform/$(OPENSBI_PLATFORM)/firmware/fw_payload.bin $@
	@echo "OpenSBI firmware (with Linux) built: $@"

# Build Verilator simulation
verilator: $(SIM_DIR)/Vopensbi_boot_tb

$(SIM_DIR)/Vopensbi_boot_tb: $(VERILOG_DIR)/riscv64_mmu.v $(TEST_DIR)/clint.sv $(TEST_DIR)/fake_uart.sv $(TEST_DIR)/opensbi_boot_tb.sv | $(SIM_DIR)
	$(VERILATOR) --binary --timing \
		-Wno-fatal \
		--top-module opensbi_boot_tb \
		-I$(VERILOG_DIR) \
		-I$(TEST_DIR) \
		--Mdir $(SIM_DIR) \
		-o Vopensbi_boot_tb \
		$(TEST_DIR)/opensbi_boot_tb.sv \
		$(TEST_DIR)/clint.sv \
		$(TEST_DIR)/fake_uart.sv \
		$(VERILOG_DIR)/riscv64_mmu.v \
		--trace
	@echo "Verilator simulation built: $@"

# Run simulation
sim: $(SIM_DIR)/Vopensbi_boot_tb $(BUILD_DIR)/fw_payload.bin $(BUILD_DIR)/riscv64_mmu.dtb
	cd $(SIM_DIR) && ./Vopensbi_boot_tb \
		+firmware=$(BUILD_DIR)/fw_payload.bin \
		+fdt_file=$(BUILD_DIR)/riscv64_mmu.dtb \
		+entry=0x80000000 \
		+fdt=0x82200000

# Clean
clean:
	rm -rf $(BUILD_DIR)
	rm -rf $(OPENSBI_DIR)/build

# Help
help:
	@echo "ISAComp RISC-V 64 MMU Platform"
	@echo ""
	@echo "Targets:"
	@echo "  all       - Build everything (dtb, opensbi, verilator)"
	@echo "  dtb       - Compile device tree"
	@echo "  opensbi   - Build OpenSBI firmware"
	@echo "  verilator - Build Verilator simulation"
	@echo "  sim       - Run simulation"
	@echo "  clean     - Clean build artifacts"
	@echo ""
	@echo "Variables:"
	@echo "  RISCV_PREFIX - RISC-V toolchain prefix (default: riscv64-unknown-elf-)"
	@echo "  OPENSBI_DIR  - OpenSBI source directory"
