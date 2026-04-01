# J4 Linux Boot Simulation Makefile
# Uses Verilator for simulation

VERILATOR = verilator
VERILATOR_FLAGS = --binary --timing --build -j 4 --trace \
                  -Wno-WIDTHEXPAND -Wno-WIDTHTRUNC -Wno-CASEINCOMPLETE \
                  -Wno-UNOPTFLAT -Wno-BLKSEQ -Wno-PINCONNECTEMPTY \
                  -Wno-UNUSEDSIGNAL -Wno-UNUSEDPARAM

# Source files - internal memory version
TB = linux_boot_tb.sv
CPU = ../rtl/j4_complete.v
FPU = ../rtl/cvfpu_simple.v
PERIPHERALS = ../jcore_aic.sv ../jcore_pit.sv ../uartlite.sv

# Outputs
SIM = obj_dir/Vlinux_boot_tb

# Boot image
BOOT_IMAGE = ../boot/boot.bin

.PHONY: all sim clean generate trace

all: $(SIM)

# Internal memory version
$(SIM): $(TB) $(CPU) $(FPU) $(PERIPHERALS)
	$(VERILATOR) $(VERILATOR_FLAGS) --top-module linux_boot_tb \
		$(TB) $(CPU) $(FPU) $(PERIPHERALS)

# Get entry point from boot ROM symbols
ENTRY_POINT = $(shell sh-elf-nm ../boot/bootrom.elf 2>/dev/null | grep ' T _start' | cut -d' ' -f1)

# Run simulation with boot image
sim: $(SIM) $(BOOT_IMAGE)
	./$(SIM) +boot=$(BOOT_IMAGE) +entry=$(ENTRY_POINT)

# Run with trace enabled
trace: $(SIM) $(BOOT_IMAGE)
	./$(SIM) +boot=$(BOOT_IMAGE) +entry=$(ENTRY_POINT) +trace

# Build boot image
$(BOOT_IMAGE):
	$(MAKE) -C ../boot

# Compile device tree
../j4_isacomp.dtb: ../j4_isacomp.dts
	dtc -I dts -O dtb -o $@ $<

# Generate J4 processor RTL
generate:
	cd ../../../.. && python3 isa/j4/generators/generate_j4_complete.py \
		--backend verilog --output-dir isa/j4/platform/rtl

clean:
	rm -rf obj_dir *.vcd

# Quick test - just compile, no simulation
test: $(SIM)
	@echo "Build successful!"
