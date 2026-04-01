#!/bin/bash
# Run all riscv-tests on the MMU processor

set -e

# Compile testbench if needed
if [ ! -f "sim_simple" ] || [ "riscv32_mmu.v" -nt "sim_simple" ]; then
    echo "Compiling testbench..."
    iverilog -g2012 -o sim_simple riscv32_mmu.v riscv32_mmu_tb_simple.sv
fi

TEST_DIR="../../../isa/riscv32/riscv-tests/isa"
PASS=0
FAIL=0
TIMEOUT=0

echo ""
echo "========================================"
echo "Running RISC-V Tests on MMU Processor"
echo "========================================"
echo ""

for hex_file in $TEST_DIR/rv32ui-isacomp-*.hex; do
    test_name=$(basename "$hex_file" .hex | sed 's/rv32ui-isacomp-//')
    addrs_file="${hex_file%.hex}.addrs"

    if [ ! -f "$addrs_file" ]; then
        echo "⚠  $test_name: No address file"
        continue
    fi

    # Read pass/fail addresses
    read pass_addr fail_addr < "$addrs_file"

    # Run test with 2 second timeout
    printf "%-10s ... " "$test_name"
    output=$(timeout 2 vvp sim_simple +hex="$hex_file" +pass_addr="$pass_addr" +fail_addr="$fail_addr" 2>&1 | grep -v "Unable to open")

    if echo "$output" | grep -q "TEST PASSED"; then
        cycles=$(echo "$output" | grep "TEST PASSED" | grep -oP 'cycle \K[0-9]+')
        echo "PASS (${cycles} cycles)"
        PASS=$((PASS + 1))
    elif echo "$output" | grep -q "TEST FAILED"; then
        echo "FAIL"
        FAIL=$((FAIL + 1))
    elif echo "$output" | grep -q "TIMEOUT"; then
        echo "TIMEOUT"
        TIMEOUT=$((TIMEOUT + 1))
    else
        echo "ERROR"
        FAIL=$((FAIL + 1))
    fi
done

echo ""
echo "========================================"
echo "Results: $PASS PASS, $FAIL FAIL, $TIMEOUT TIMEOUT"
echo "========================================"
echo ""

if [ $FAIL -eq 0 ] && [ $TIMEOUT -eq 0 ]; then
    exit 0
else
    exit 1
fi
