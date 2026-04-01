# M68K Linux Boot Simulation Makefile
#
# Targets:
#   make all       - Build simulator
#   make sim       - Run simulation with boot image
#   make trace     - Run simulation with VCD trace
#   make clean     - Clean build artifacts

# Verilator settings
VERILATOR ?= verilator
VERILATOR_WARNS = -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-CASEINCOMPLETE \
    -Wno-UNOPTFLAT -Wno-TIMESCALEMOD -Wno-LATCH -Wno-INITIALDLY \
    -Wno-PINMISSING -Wno-SELRANGE -Wno-fatal
VERILATOR_FLAGS = --cc --exe --timing --main --public \
    -CFLAGS "-fcoroutines" $(VERILATOR_WARNS)

# Source files
RTL_DIR = ../rtl
PLATFORM_DIR = ..

# RTL sources
RTL_SRCS = \
    $(RTL_DIR)/cpu_m68k_linux.v \
    $(PLATFORM_DIR)/goldfish_pic.sv \
    $(PLATFORM_DIR)/goldfish_timer.sv

# Testbench
TB_SRC = m68k_linux_boot_tb.sv

# Simulation binary
SIM_BIN = obj_dir/Vm68k_linux_boot_tb

.PHONY: all sim trace clean

all: $(SIM_BIN)

$(SIM_BIN): $(TB_SRC) $(RTL_SRCS)
	$(VERILATOR) $(VERILATOR_FLAGS) \
		-I$(RTL_DIR) -I$(PLATFORM_DIR) \
		--top-module m68k_linux_boot_tb \
		--build-jobs $$(nproc) \
		$(TB_SRC) $(RTL_SRCS)
	$(MAKE) -C obj_dir -f Vm68k_linux_boot_tb.mk -j$$(nproc)

# Run simulation (line-buffered for real-time output)
sim: $(SIM_BIN)
	stdbuf -oL ./$(SIM_BIN)

# Run simulation with VCD trace (add --trace to VERILATOR_FLAGS and rebuild first)
trace: $(TB_SRC) $(RTL_SRCS)
	$(VERILATOR) $(VERILATOR_FLAGS) --trace \
		-I$(RTL_DIR) -I$(PLATFORM_DIR) \
		--top-module m68k_linux_boot_tb \
		--build-jobs $$(nproc) \
		$(TB_SRC) $(RTL_SRCS)
	$(MAKE) -C obj_dir -f Vm68k_linux_boot_tb.mk -j$$(nproc)
	stdbuf -oL ./$(SIM_BIN)

clean:
	rm -rf obj_dir *.vcd

help:
	@echo "M68K Linux Boot Simulation"
	@echo ""
	@echo "Targets:"
	@echo "  all     - Build Verilator simulator (no trace, ~2x faster)"
	@echo "  sim     - Build and run simulation"
	@echo "  trace   - Build with VCD trace and run"
	@echo "  clean   - Remove build artifacts"
