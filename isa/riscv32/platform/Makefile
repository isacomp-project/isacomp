# ISAComp RISC-V 32 MMU Platform Makefile
# Builds OpenSBI and runs simulation

TOPDIR := $(shell pwd)/../../..
PLATFORM_DIR := $(TOPDIR)/isa/riscv32/platform
TEST_DIR := $(PLATFORM_DIR)/tests
VERILOG_DIR := $(TOPDIR)/examples/verilog/riscv32_mmu

# Tools
VERILATOR := verilator
DTC := dtc
RISCV_PREFIX ?= riscv32-unknown-elf-

# OpenSBI configuration
OPENSBI_DIR ?= $(TOPDIR)/isa/riscv32/platform/opensbi
OPENSBI_PLATFORM := generic
OPENSBI_FW_JUMP_ADDR := 0x80200000

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
dtb: $(BUILD_DIR)/riscv32_mmu.dtb

$(BUILD_DIR)/riscv32_mmu.dtb: $(PLATFORM_DIR)/riscv32_mmu.dts | $(BUILD_DIR)
	$(DTC) -I dts -O dtb -o $@ $<
	@echo "Device tree compiled: $@"

# Clone and build OpenSBI
$(OPENSBI_DIR):
	git clone https://github.com/riscv-software-src/opensbi.git $(OPENSBI_DIR)

opensbi: $(BUILD_DIR)/fw_payload.bin

$(BUILD_DIR)/fw_payload.bin: | $(OPENSBI_DIR) $(BUILD_DIR)
	cp $(OPENSBI_DIR)/build/platform/$(OPENSBI_PLATFORM)/firmware/fw_payload.bin $@
	@echo "OpenSBI firmware (with Linux) built: $@"

# Build Verilator simulation
verilator: $(SIM_DIR)/Vopensbi_boot_tb

$(SIM_DIR)/Vopensbi_boot_tb: $(VERILOG_DIR)/riscv32_mmu.v $(TEST_DIR)/clint.sv $(TEST_DIR)/fake_uart.sv $(TEST_DIR)/opensbi_boot_tb.sv | $(SIM_DIR)
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
		$(VERILOG_DIR)/riscv32_mmu.v \
		--trace
	@echo "Verilator simulation built: $@"

# Run simulation
sim: $(SIM_DIR)/Vopensbi_boot_tb $(BUILD_DIR)/fw_payload.bin $(BUILD_DIR)/riscv32_mmu.dtb
	cd $(SIM_DIR) && ./Vopensbi_boot_tb \
		+firmware=$(BUILD_DIR)/fw_payload.bin \
		+fdt_file=$(BUILD_DIR)/riscv32_mmu.dtb \
		+entry=0x80000000 \
		+fdt=0x82200000

# Clean
clean:
	rm -rf $(BUILD_DIR)
	rm -rf $(OPENSBI_DIR)/build

# Help
help:
	@echo "ISAComp RISC-V 32 MMU Platform"
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
	@echo "  RISCV_PREFIX - RISC-V toolchain prefix (default: riscv32-unknown-elf-)"
	@echo "  OPENSBI_DIR  - OpenSBI source directory"
