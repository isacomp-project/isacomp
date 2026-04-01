#!/bin/bash
# Run riscv-tests p environment tests on MMU processor (M-mode, no VM)
# Uses PC-based pass/fail detection

cd "$(dirname "$0")"

SIMULATOR=${SIMULATOR:-iverilog}
TEST_DIR="../../../isa/riscv32/riscv-tests/isa"
PASS=0
FAIL=0
TIMEOUT=0

echo "Compiling testbench with $SIMULATOR..."

if [ "$SIMULATOR" = "verilator" ]; then
    if [ ! -f "sim_p_tests" ] || [ "riscv32_mmu.v" -nt "sim_p_tests" ] || [ "riscv32_mmu_tb_p.sv" -nt "sim_p_tests" ]; then
        verilator --timing --exe --binary \
            -Wno-fatal -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-TIMESCALEMOD -Wno-UNOPTFLAT \
            -DMEM_BASE="32'h80000000" \
            -o sim_p_tests riscv32_mmu.v riscv32_mmu_tb_p.sv
        if [ $? -ne 0 ]; then
            echo "ERROR: Verilator compilation failed!"
            exit 1
        fi
        mv obj_dir/sim_p_tests . 2>/dev/null
    fi
    TEST_CMD="./sim_p_tests"
else
    if [ ! -f "sim_p_tests" ] || [ "riscv32_mmu.v" -nt "sim_p_tests" ] || [ "riscv32_mmu_tb_p.sv" -nt "sim_p_tests" ]; then
        iverilog -g2012 -DMEM_BASE="32'h80000000" -o sim_p_tests riscv32_mmu.v riscv32_mmu_tb_p.sv
        if [ $? -ne 0 ]; then
            echo "ERROR: Icarus Verilog compilation failed!"
            exit 1
        fi
    fi
    TEST_CMD="vvp -n sim_p_tests"
fi

echo ""
echo "========================================"
echo "Running RISC-V p Environment Tests"
echo "(M-mode, no virtual memory)"
echo "========================================"
echo ""

for hex_file in "$TEST_DIR"/rv32ui-p-*.hex; do
    test_name=$(basename "$hex_file" .hex)
    elf_file="${hex_file%.hex}"

    # Extract pass/fail addresses from ELF
    PASS_ADDR=$(riscv64-unknown-elf-nm "$elf_file" 2>/dev/null | grep " pass$" | awk '{print $1}')
    FAIL_ADDR=$(riscv64-unknown-elf-nm "$elf_file" 2>/dev/null | grep " fail$" | awk '{print $1}')

    if [ -z "$PASS_ADDR" ] || [ -z "$FAIL_ADDR" ]; then
        printf "%-20s ... SKIP (no symbols)\n" "$test_name"
        continue
    fi

    printf "%-20s ... " "$test_name"
    output=$(timeout 30 $TEST_CMD +hex="$hex_file" +pass_addr=$PASS_ADDR +fail_addr=$FAIL_ADDR 2>&1)

    if echo "$output" | grep -q "TEST PASSED"; then
        cycles=$(echo "$output" | grep "TEST PASSED" | grep -oP 'cycle \K[0-9]+' || echo "?")
        printf "PASS (%s cycles)\n" "$cycles"
        PASS=$((PASS + 1))
    elif echo "$output" | grep -q "TEST FAILED"; then
        gp=$(echo "$output" | grep "gp=" | grep -oP 'gp=\K[0-9]+' || echo "?")
        printf "FAIL (gp=%s)\n" "$gp"
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
