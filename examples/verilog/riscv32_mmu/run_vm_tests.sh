#!/bin/bash
# Run RISC-V VM tests on the MMU processor
# Tests use Sv32 two-level page tables and run in S-mode

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Compile testbench if needed
if [ ! -f "sim_simple" ] || [ "riscv32_mmu.v" -nt "sim_simple" ] || [ "riscv32_mmu_tb_simple.sv" -nt "sim_simple" ]; then
    echo "Compiling testbench..."
    iverilog -g2012 -o sim_simple riscv32_mmu.v riscv32_mmu_tb_simple.sv
fi

TEST_DIR="../../../isa/riscv32/riscv-tests/isa"
PASS=0
FAIL=0
TIMEOUT=0
SKIP=0

echo ""
echo "========================================"
echo "Running RISC-V VM Tests on MMU Processor"
echo "(Sv32 two-level page tables, S-mode)"
echo "========================================"
echo ""

for test_hex in $TEST_DIR/rv32ui-vm-*.hex; do
    # Get test name
    base=$(basename "$test_hex" .hex)
    test_name=$(echo "$base" | sed 's/rv32ui-vm-//')
    addrs_file="${test_hex%.hex}.addrs"

    if [ ! -f "$addrs_file" ]; then
        echo "  $test_name: SKIP (no .addrs file)"
        SKIP=$((SKIP + 1))
        continue
    fi

    # Read pass/fail addresses
    read pass_addr fail_addr < "$addrs_file"

    # Run test with timeout
    printf "%-12s ... " "$test_name"
    set +e
    output=$(timeout 10 vvp -n sim_simple +hex="$test_hex" +pass_addr="$pass_addr" +fail_addr="$fail_addr" 2>&1)
    exit_code=$?
    set -e

    if [ $exit_code -eq 124 ]; then
        echo "TIMEOUT"
        TIMEOUT=$((TIMEOUT + 1))
    elif echo "$output" | grep -q "TEST PASSED"; then
        cycles=$(echo "$output" | grep "TEST PASSED" | grep -oP 'cycle \K[0-9]+' || echo "?")
        echo "PASS (${cycles} cycles)"
        PASS=$((PASS + 1))
    elif echo "$output" | grep -q "TEST FAILED"; then
        testnum=$(echo "$output" | grep "TESTNUM" | grep -oP '= \K[0-9]+' || echo "?")
        echo "FAIL (test $testnum)"
        FAIL=$((FAIL + 1))
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
    echo "SUCCESS: All tests passed!"
    exit 0
else
    echo "FAILURE: Some tests failed"
    exit 1
fi
