# J2 Linux Boot Simulation Makefile
# Uses Verilator for simulation

VERILATOR = verilator
VERILATOR_FLAGS = --binary --timing --build -j 4 --trace \
                  -Wno-WIDTHEXPAND -Wno-WIDTHTRUNC -Wno-CASEINCOMPLETE \
                  -Wno-UNOPTFLAT -Wno-BLKSEQ

# Source files - internal memory version
TB = linux_boot_tb.sv
CPU = ../rtl/j2_complete.v
PERIPHERALS = ../jcore_aic.sv ../jcore_pit.sv ../uartlite.sv

# Source files - external memory version (legacy, with memory mirroring)
TB_EXTMEM = linux_boot_extmem_tb.sv
CPU_EXTMEM = ../rtl_extmem/j2_complete_extmem.v
MEM_WRAPPER = ../rtl_extmem/umem_memory.v

# Source files - SoC model (proper bus architecture, no memory mirroring)
# Uses valid-ready handshake protocol for external memory
TB_SOC = linux_boot_soc_tb.sv
CPU_SOC = ../../../examples/verilog/j2_extmem/j2_complete_extmem.v
SOC_WRAPPER = ../j2_soc_extmem.sv

# Outputs
SIM = obj_dir/Vlinux_boot_tb
SIM_EXTMEM = obj_dir_extmem/Vlinux_boot_extmem_tb
SIM_SOC = obj_dir_soc/Vlinux_boot_soc_tb

# Boot image
BOOT_IMAGE = ../boot/boot.bin

.PHONY: all sim clean extmem sim_extmem soc sim_soc generate

all: $(SIM)

# Internal memory version
$(SIM): $(TB) $(CPU) $(PERIPHERALS)
	$(VERILATOR) $(VERILATOR_FLAGS) --top-module linux_boot_tb \
		$(TB) $(CPU) $(PERIPHERALS)

# External memory version
extmem: $(SIM_EXTMEM)

$(SIM_EXTMEM): $(TB_EXTMEM) $(CPU_EXTMEM) $(MEM_WRAPPER)
	$(VERILATOR) $(VERILATOR_FLAGS) --top-module linux_boot_extmem_tb \
		-Mdir obj_dir_extmem \
		$(TB_EXTMEM) $(CPU_EXTMEM) $(MEM_WRAPPER)

# Get entry point from boot ROM symbols
ENTRY_POINT = $(shell sh-elf-nm ../boot/bootrom.elf 2>/dev/null | grep ' T _start' | cut -d' ' -f1)

# Run simulation with boot image (internal memory)
sim: $(SIM) $(BOOT_IMAGE)
	./$(SIM) +boot=$(BOOT_IMAGE) +entry=$(ENTRY_POINT)

# Run simulation with boot image (external memory)
sim_extmem: $(SIM_EXTMEM) $(BOOT_IMAGE)
	./$(SIM_EXTMEM) +boot=$(BOOT_IMAGE) +entry=$(ENTRY_POINT)

# Run with trace enabled
trace: $(SIM) $(BOOT_IMAGE)
	./$(SIM) +boot=$(BOOT_IMAGE) +entry=$(ENTRY_POINT) +trace

trace_extmem: $(SIM_EXTMEM) $(BOOT_IMAGE)
	./$(SIM_EXTMEM) +boot=$(BOOT_IMAGE) +entry=$(ENTRY_POINT) +trace

# =========================================================================
# SoC Model (proper bus architecture with valid-ready handshake)
# =========================================================================

# Generate J2 core with externalized memory (valid-ready protocol)
# The generator creates multiple write ports for exception handling which
# pushes both PC and SR to the stack simultaneously.
GENERATOR = ../../generators/generate_j2_complete.py
VERILOG_GEN = ../../../backends/verilog/verilog_generator.py

$(CPU_SOC): $(GENERATOR) $(VERILOG_GEN)
	cd ../../.. && python3 j2/generators/generate_j2_complete.py \
		--externalize-memory -o examples/verilog/j2_extmem

generate: $(CPU_SOC)

# Build SoC simulation
soc: $(SIM_SOC)

$(SIM_SOC): $(TB_SOC) $(CPU_SOC) $(PERIPHERALS)
	$(VERILATOR) $(VERILATOR_FLAGS) --top-module linux_boot_soc_tb \
		-Mdir obj_dir_soc \
		$(TB_SOC) $(CPU_SOC) $(PERIPHERALS)

# Run SoC simulation with boot image
sim_soc: $(SIM_SOC) $(BOOT_IMAGE)
	./$(SIM_SOC) +boot_image=$(BOOT_IMAGE)

# Run SoC simulation with trace
trace_soc: $(SIM_SOC) $(BOOT_IMAGE)
	./$(SIM_SOC) +boot_image=$(BOOT_IMAGE) +trace

clean:
	rm -rf obj_dir obj_dir_extmem obj_dir_soc *.vcd
