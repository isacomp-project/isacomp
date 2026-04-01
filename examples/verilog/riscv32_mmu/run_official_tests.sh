#!/bin/bash
# Run official riscv-tests on MMU processor

set -e

# Compile testbench if needed
if [ ! -f "sim_simple" ] || [ "riscv32_mmu.v" -nt "sim_simple" ]; then
    echo "Compiling testbench..."
    iverilog -g2012 -o sim_simple riscv32_mmu.v riscv32_mmu_tb_simple.sv
fi

TEST_DIR="/tmp/riscv-tests/isa"
PASS=0
FAIL=0
TIMEOUT=0
SKIP=0

echo ""
echo "========================================"
echo "Running Official RISC-V Tests"
echo "========================================"
echo ""

for hex_file in $TEST_DIR/rv32ui-isacomp-*.hex.words; do
    test_name=$(basename "$hex_file" .hex.words | sed 's/rv32ui-isacomp-//')
    addrs_file="${hex_file%.hex.words}.addrs"

    if [ ! -f "$addrs_file" ]; then
        echo "⚠  $test_name: No address file"
        SKIP=$((SKIP + 1))
        continue
    fi

    # Read pass/fail addresses
    read pass_addr fail_addr < "$addrs_file"
    
    # Skip if no addresses
    if [ -z "$pass_addr" ] || [ -z "$fail_addr" ]; then
        printf "%-15s ... SKIP (no addresses)\n" "$test_name"
        SKIP=$((SKIP + 1))
        continue
    fi

    # Run test with 5 second timeout
    printf "%-15s ... " "$test_name"
    output=$(timeout 5 vvp sim_simple +hex="$hex_file" +pass_addr="$pass_addr" +fail_addr="$fail_addr" 2>&1 | grep -v "Unable to open")

    if echo "$output" | grep -q "TEST PASSED"; then
        cycles=$(echo "$output" | grep "TEST PASSED" | grep -oP 'cycle \K[0-9]+')
        printf "PASS (%4s cycles)\n" "${cycles}"
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
echo "Results: $PASS PASS, $FAIL FAIL, $TIMEOUT TIMEOUT, $SKIP SKIP"
echo "========================================"
echo ""

if [ $FAIL -eq 0 ] && [ $TIMEOUT -eq 0 ]; then
    exit 0
else
    exit 1
fi
