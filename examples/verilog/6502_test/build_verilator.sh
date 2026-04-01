#!/bin/bash
# Build script for 6502 co-simulation testbench using Verilator

set -e

echo "Building 6502 co-simulation testbench..."

verilator --cc --exe --build --timing \
    --top-module cpu_6502_test_tb \
    -Wall -Wno-fatal \
    6502_test.v \
    cpu_6502_test_tb_verilator.sv \
    6502_dpi.c \
    fake6502_wrapper.c \
    main.cpp \
    -CFLAGS "-I."

echo ""
echo "Build complete! Run with: ./obj_dir/Vcpu_6502_test_tb"
