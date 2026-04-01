#!/bin/bash
# Simple test runner for RISC-V MMU processor

if [ $# -lt 1 ]; then
    echo "Usage: $0 <test.hex> [pass_addr] [fail_addr]"
    exit 1
fi

HEX_FILE="$1"
PASS_ADDR="${2:-00000014}"  # Default from simple test
FAIL_ADDR="${3:-00000018}"

if [ ! -f "$HEX_FILE" ]; then
    echo "ERROR: Hex file not found: $HEX_FILE"
    exit 1
fi

# Compile if needed
if [ ! -f "sim_simple" ] || [ "riscv32_mmu.v" -nt "sim_simple" ]; then
    echo "Compiling testbench..."
    iverilog -g2012 -o sim_simple riscv32_mmu.v riscv32_mmu_tb_simple.sv
    if [ $# -ne 0 ]; then
        echo "Compilation failed"
        exit 1
    fi
fi

# Run test
vvp sim_simple +hex="$HEX_FILE" +pass_addr="$PASS_ADDR" +fail_addr="$FAIL_ADDR" 2>&1 | grep -v "Unable to open"
