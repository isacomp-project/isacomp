# Alpha64 Boot Simulation Makefile
#
# Builds and runs the Verilator simulation of Alpha64 Linux boot.
#
# Usage:
#   make              - Build simulation binary
#   make run          - Build and run with boot.bin
#   make run_trace    - Build and run with VCD waveform output
#   make clean        - Remove build artifacts

VERILATOR = verilator
VFLAGS = --exe --cc --build --timing --trace \
         -Wno-WIDTHEXPAND -Wno-WIDTHTRUNC -Wno-CASEINCOMPLETE \
         -Wno-UNOPTFLAT -Wno-BLKSEQ -Wno-fatal
TOP = alpha64_boot_tb
PLATFORM_DIR = ..
VERILOG_DIR = ../../../../examples/verilog/alpha64
VENDOR_DIR = ../../../../vendor

# Source files
SV_SRCS = alpha64_boot_tb.sv \
          $(PLATFORM_DIR)/alpha_intc.sv \
          $(PLATFORM_DIR)/alpha_timer.sv \
          $(PLATFORM_DIR)/uart16550_alpha.sv

# ISAComp-generated CPU RTL
CPU_SRC = $(VERILOG_DIR)/alpha64_linux.v

# FPU stub (for initial boot testing - no FP operations in PALcode/bootrom)
FPU_SRC = ../../../../isa/j4/j4-tests/sim/cvfpu_simple.v

# Custom C++ main that drives clk/rst_n (--binary generates a broken main
# that never toggles the clock for modules with external clk/rst_n ports)
SIM_MAIN = ../../../../sim_main.cpp

all: obj_dir/V$(TOP)

obj_dir/V$(TOP): $(SV_SRCS) $(CPU_SRC) $(FPU_SRC) $(SIM_MAIN)
	$(VERILATOR) $(VFLAGS) --top-module $(TOP) $(SV_SRCS) $(CPU_SRC) $(FPU_SRC) $(SIM_MAIN)

run: obj_dir/V$(TOP)
	./obj_dir/V$(TOP) +boot=../boot/boot.bin

run_with_kernel: obj_dir/V$(TOP)
	./obj_dir/V$(TOP) +boot=../boot/boot.bin +kernel=../../../../linux/vmlinux.bin

run_trace: obj_dir/V$(TOP)
	./obj_dir/V$(TOP) +boot=../boot/boot.bin +trace

clean:
	rm -rf obj_dir *.vcd uart_output.txt

.PHONY: all run run_trace clean
