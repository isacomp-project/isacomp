# ISAComp OpenPOWER Linux Boot Platform Makefile
# Generates processor, builds Verilator simulation, and runs boot test

TOPDIR := $(shell pwd)/../..
PLATFORM_DIR := $(TOPDIR)/openpower/platform
VERILOG_DIR := $(TOPDIR)/examples/verilog/openpower_linux
GENERATOR := $(TOPDIR)/openpower/generators/generate_openpower_linux.py

# Tools
VERILATOR := verilator
DTC := dtc
PPC_PREFIX ?= powerpc64le-linux-gnu-
PPC_CC := $(PPC_PREFIX)gcc
PPC_OBJCOPY := $(PPC_PREFIX)objcopy
PPC_LD := $(PPC_PREFIX)ld

# Output directories
BUILD_DIR := $(PLATFORM_DIR)/build
SIM_DIR := $(BUILD_DIR)/sim

# Verilog source files
RTL_FILE := $(VERILOG_DIR)/openpower_lcs_extmem.v
TB_FILE := $(VERILOG_DIR)/linux_boot_tb.sv
UART_FILE := $(VERILOG_DIR)/uart16550.sv
INTC_FILE := $(VERILOG_DIR)/power_intc.sv
TIMER_FILE := $(VERILOG_DIR)/power_timer.sv

# Simulation binary
SIM_BINARY := $(SIM_DIR)/Vlinux_boot_tb

.PHONY: all clean generate dtb verilator sim test help

all: generate dtb verilator test

# Create build directories
$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(SIM_DIR):
	mkdir -p $(SIM_DIR)

# =========================================================================
# Step 1: Generate processor RTL from ISA specifications
# =========================================================================
generate: $(RTL_FILE)

$(RTL_FILE): $(GENERATOR) $(wildcard $(TOPDIR)/openpower/*.isa)
	cd $(TOPDIR) && python $(GENERATOR) -o $(VERILOG_DIR)
	@echo "Processor RTL generated: $@"

# =========================================================================
# Step 2: Compile device tree
# =========================================================================
dtb: $(BUILD_DIR)/openpower_isacomp.dtb

$(BUILD_DIR)/openpower_isacomp.dtb: $(PLATFORM_DIR)/openpower_isacomp.dts | $(BUILD_DIR)
	$(DTC) -I dts -O dtb -o $@ $<
	@echo "Device tree compiled: $@"

# =========================================================================
# Step 3: Build Verilator simulation
# =========================================================================
verilator: $(SIM_BINARY)

$(SIM_BINARY): $(RTL_FILE) $(TB_FILE) $(UART_FILE) $(INTC_FILE) $(TIMER_FILE) | $(SIM_DIR)
	$(VERILATOR) --binary --timing \
		-Wno-fatal \
		-fno-dfg \
		--top-module linux_boot_tb \
		-I$(VERILOG_DIR) \
		--Mdir $(SIM_DIR) \
		-o Vlinux_boot_tb \
		$(TB_FILE) \
		$(UART_FILE) \
		$(INTC_FILE) \
		$(TIMER_FILE) \
		$(RTL_FILE)
	@echo "Verilator simulation built: $@"

# =========================================================================
# Step 4: Build minimal test program (UART hello world)
# =========================================================================
test-program: $(BUILD_DIR)/test_boot.bin

$(BUILD_DIR)/test_boot.bin: $(PLATFORM_DIR)/tests/test_boot.S | $(BUILD_DIR)
	$(PPC_CC) -mbig-endian -mabi=elfv1 -nostdlib -nostartfiles \
		-Wl,-T,$(PLATFORM_DIR)/tests/boot.lds \
		-Wl,--oformat,elf64-powerpc \
		-o $(BUILD_DIR)/test_boot.elf $<
	$(PPC_OBJCOPY) -O binary $(BUILD_DIR)/test_boot.elf $@
	@echo "Test program built: $@"

# =========================================================================
# Step 5: Run simulation with test program
# =========================================================================
test: $(SIM_BINARY) $(BUILD_DIR)/test_boot.bin
	cd $(SIM_DIR) && $(SIM_BINARY) \
		+kernel=$(BUILD_DIR)/test_boot.bin \
		+max_cycles=10000 \
		+debug
	@echo "=== UART Output ==="
	@cat $(SIM_DIR)/uart_output.txt 2>/dev/null || true

# Run with a Linux kernel image
sim: $(SIM_BINARY) $(BUILD_DIR)/openpower_isacomp.dtb
	cd $(SIM_DIR) && $(SIM_BINARY) \
		+kernel=$(KERNEL) \
		+dtb=$(BUILD_DIR)/openpower_isacomp.dtb \
		+max_cycles=500000000
	@echo "=== UART Output ==="
	@cat $(SIM_DIR)/uart_output.txt 2>/dev/null || true

# =========================================================================
# Clean
# =========================================================================
clean:
	rm -rf $(BUILD_DIR)

clean-all: clean
	rm -f $(RTL_FILE) $(VERILOG_DIR)/umem_memory.v

# =========================================================================
# Help
# =========================================================================
help:
	@echo "ISAComp OpenPOWER Linux Boot Platform"
	@echo ""
	@echo "Targets:"
	@echo "  all          - Generate RTL, compile DTB, build simulator, run test"
	@echo "  generate     - Generate processor RTL from ISA specifications"
	@echo "  dtb          - Compile device tree"
	@echo "  verilator    - Build Verilator simulation binary"
	@echo "  test-program - Build minimal test program"
	@echo "  test         - Run simulation with test program"
	@echo "  sim          - Run simulation with Linux kernel (KERNEL=path)"
	@echo "  clean        - Clean build artifacts"
	@echo ""
	@echo "Variables:"
	@echo "  PPC_PREFIX   - PowerPC toolchain prefix (default: powerpc64le-linux-gnu-)"
	@echo "  KERNEL       - Path to Linux kernel binary (for 'sim' target)"
