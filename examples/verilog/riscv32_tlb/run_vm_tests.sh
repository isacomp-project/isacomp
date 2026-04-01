#!/bin/bash
# Run RISC-V v environment tests on the TLB processor
# Tests use Sv32 two-level page tables and run in S-mode with virtual memory enabled
#
# This uses the riscv-tests v environment which properly sets up page tables,
# switches to S-mode, and enables virtual memory via satp CSR.

# Get the directory containing this script (works from any working directory)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

SIMULATOR=${SIMULATOR:-iverilog}
# Use RISCV_TESTS_DIR if set, otherwise use relative path from this script
TEST_DIR="${RISCV_TESTS_DIR:-$SCRIPT_DIR/../../../isa/riscv32/riscv-tests/isa}"
PASS=0
FAIL=0
TIMEOUT=0
SKIP=0

echo "Compiling testbench with $SIMULATOR..."

if [ "$SIMULATOR" = "verilator" ]; then
    if [ ! -f "sim_vm_tests" ] || [ "riscv32_tlb.v" -nt "sim_vm_tests" ] || [ "riscv32_tlb_tb_v.sv" -nt "sim_vm_tests" ]; then
        verilator --timing --exe --binary \
            -Wno-fatal -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-TIMESCALEMOD -Wno-UNOPTFLAT \
            -DMEM_BASE="32'h00000000" \
            -o sim_vm_tests riscv32_tlb.v riscv32_tlb_tb_v.sv
        if [ $? -ne 0 ]; then
            echo "ERROR: Verilator compilation failed!"
            exit 1
        fi
        mv obj_dir/sim_vm_tests . 2>/dev/null
    fi
    TEST_CMD="./sim_vm_tests"
else
    if [ ! -f "sim_vm_tests" ] || [ "riscv32_tlb.v" -nt "sim_vm_tests" ] || [ "riscv32_tlb_tb_v.sv" -nt "sim_vm_tests" ]; then
        iverilog -g2012 -DMEM_BASE="32'h00000000" -o sim_vm_tests riscv32_tlb.v riscv32_tlb_tb_v.sv
        if [ $? -ne 0 ]; then
            echo "ERROR: Icarus Verilog compilation failed!"
            exit 1
        fi
    fi
    TEST_CMD="vvp -n sim_vm_tests"
fi

echo ""
echo "========================================"
echo "Running RISC-V v Environment Tests"
echo "(Sv32 two-level page tables with TLB, S-mode)"
echo "========================================"
echo ""

for hex_file in "$TEST_DIR"/rv32ui-v-*.hex; do
    test_name=$(basename "$hex_file" .hex)
    elf_file="${hex_file%.hex}"

    # Extract pass/fail addresses from ELF
    PASS_ADDR=$(riscv64-unknown-elf-nm "$elf_file" 2>/dev/null | grep " pass$" | awk '{print $1}')
    FAIL_ADDR=$(riscv64-unknown-elf-nm "$elf_file" 2>/dev/null | grep " fail$" | awk '{print $1}')

    if [ -z "$PASS_ADDR" ] || [ -z "$FAIL_ADDR" ]; then
        printf "%-20s ... SKIP (no symbols)\n" "$test_name"
        SKIP=$((SKIP + 1))
        continue
    fi

    printf "%-20s ... " "$test_name"
    set +e
    output=$(timeout 60 $TEST_CMD +hex="$hex_file" +pass_addr=$PASS_ADDR +fail_addr=$FAIL_ADDR 2>&1)
    exit_code=$?
    set -e

    if [ $exit_code -eq 124 ]; then
        echo "TIMEOUT"
        TIMEOUT=$((TIMEOUT + 1))
    elif echo "$output" | grep -q "TEST PASSED"; then
        cycles=$(echo "$output" | grep "TEST PASSED" | grep -oP 'cycle \K[0-9]+' || echo "?")
        printf "PASS (%s cycles)\n" "$cycles"
        PASS=$((PASS + 1))
    elif echo "$output" | grep -q "TEST FAILED"; then
        gp=$(echo "$output" | grep "gp=" | grep -oP 'gp=\K[0-9]+' || echo "?")
        printf "FAIL (gp=%s)\n" "$gp"
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
