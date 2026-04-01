#!/bin/bash
# Script to run RISC-V tests on ILA-generated processor
# Requires: verilator (v5+), riscv toolchain

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RISCV_TESTS_DIR="$SCRIPT_DIR/../../../isa/riscv32/riscv-tests"
BUILD_DIR="${SCRIPT_DIR}/test_build"
RESULTS_DIR="${SCRIPT_DIR}/test_results"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=========================================="
echo "RISC-V Tests on ILA Processor"
echo "=========================================="

# Check for verilator
if ! command -v verilator &> /dev/null; then
    echo -e "${RED}Error: verilator not found${NC}"
    exit 1
fi

# Check for RISC-V toolchain
if command -v riscv32-unknown-elf-gcc &> /dev/null; then
    TOOLCHAIN_PREFIX="riscv32-unknown-elf"
elif command -v riscv64-unknown-elf-gcc &> /dev/null; then
    TOOLCHAIN_PREFIX="riscv64-unknown-elf"
else
    echo -e "${RED}Error: RISC-V toolchain not found${NC}"
    echo "Install with: sudo apt-get install gcc-riscv64-unknown-elf"
    exit 1
fi

echo "Using toolchain: ${TOOLCHAIN_PREFIX}-gcc"

# Create directories
mkdir -p "${BUILD_DIR}"
mkdir -p "${RESULTS_DIR}"

# Check if riscv-tests exist
if [ ! -d "${RISCV_TESTS_DIR}" ]; then
    echo -e "${YELLOW}Warning: riscv-tests not found at ${RISCV_TESTS_DIR}${NC}"
    echo "Cloning riscv-tests..."
    mkdir -p "${SCRIPT_DIR}"
    cd "${SCRIPT_DIR}"
    git clone -b isacomp https://github.com/Jbalkind/riscv-tests.git
    cd riscv-tests
    git submodule update --init --recursive
    cd "${SCRIPT_DIR}"
fi

# Compile testbench
echo ""
echo "1. Compiling testbench with Verilator..."
verilator --binary \
    --timing \
    --top-module riscv32i_ila_testbench \
    -Wno-fatal -Wno-UNOPTFLAT -Wno-WIDTH -Wno-CASEINCOMPLETE \
    -Wno-WIDTHEXPAND -Wno-WIDTHTRUNC -Wno-CMPCONST \
    --converge-limit 10000 \
    riscv32i_ila.v \
    testbench_debug.v \
    --exe --build \
    -o ila_sim

# Move binary
mv obj_dir/ila_sim "${BUILD_DIR}/ila_sim"
echo "   ✓ Testbench compiled"

# Function to run a single test
run_test() {
    local test_name=$1
    local test_elf="${BUILD_DIR}/${test_name}.elf"
    local test_hex="${BUILD_DIR}/${test_name}.hex"
    local test_log="${RESULTS_DIR}/${test_name}.log"

    echo -n "  Testing ${test_name}... "

    # Compile test
    if ! ${TOOLCHAIN_PREFIX}-gcc -march=rv32i -mabi=ilp32 \
        -static -mcmodel=medany -fvisibility=hidden -nostdlib -nostartfiles \
        -I"${RISCV_TESTS_DIR}/isa/macros/scalar" \
        -I"${RISCV_TESTS_DIR}/env/isacomp" \
        -I"${RISCV_TESTS_DIR}/env" \
        -T "${RISCV_TESTS_DIR}/env/isacomp/link.ld" \
        "${RISCV_TESTS_DIR}/isa/rv32ui/${test_name}.S" \
        -o "${test_elf}" 2>&1 > "${test_log}.compile"; then
        echo -e "${RED}COMPILE FAILED${NC}"
        return 1
    fi

    # Convert to hex
    ${TOOLCHAIN_PREFIX}-objcopy -O verilog --verilog-data-width=4 "${test_elf}" "${test_hex}"

    # Extract pass/fail addresses (ILA uses address 0x0 base)
    local pass_addr=$(${TOOLCHAIN_PREFIX}-nm "${test_elf}" | grep " pass$" | awk '{print "0x" $1}')
    local fail_addr=$(${TOOLCHAIN_PREFIX}-nm "${test_elf}" | grep " fail$" | awk '{print "0x" $1}')

    if [ -z "$pass_addr" ] || [ -z "$fail_addr" ]; then
        echo -e "${RED}NO PASS/FAIL SYMBOLS${NC}"
        return 1
    fi

    # Run simulation
    cd "${BUILD_DIR}"
    timeout 30 ./ila_sim "+load=${test_hex}" "+pass_pc=${pass_addr}" "+fail_pc=${fail_addr}" 2>&1 > "${test_log}"
    local sim_result=$?
    cd "${SCRIPT_DIR}"

    # Check results
    if [ $sim_result -eq 124 ]; then
        echo -e "${RED}TIMEOUT${NC}"
        return 1
    elif grep -q "TEST PASSED" "${test_log}"; then
        echo -e "${GREEN}PASSED${NC}"
        return 0
    elif grep -q "TEST FAILED" "${test_log}"; then
        echo -e "${RED}FAILED${NC}"
        tail -20 "${test_log}"
        return 1
    else
        echo -e "${YELLOW}UNKNOWN${NC}"
        return 1
    fi
}

# List of tests matching available instructions
# ILA currently has: ADD, ADDI, AND, ANDI, AUIPC, BEQ, BGE
TESTS=(
    "add" "addi" "and" "andi" "auipc"
    "beq" "bge" "bgeu" "blt" "bltu" "bne"
    "jal" "jalr"
    "lb" "lbu" "lh" "lhu" "lui" "lw"
    "or" "ori"
    "sb" "sh" "sw"
    "sll" "slli" "slt" "slti" "sltiu" "sltu"
    "sra" "srai" "srl" "srli"
    "sub"
    "xor" "xori"
)

# Allow user to specify tests
if [ $# -gt 0 ]; then
    TESTS=("$@")
fi

# Run tests
echo ""
echo "2. Running RISC-V ISA tests..."
echo ""

PASSED=0
FAILED=0
TOTAL=${#TESTS[@]}

for test in "${TESTS[@]}"; do
    if run_test "$test"; then
        ((PASSED++)) || true
    else
        ((FAILED++)) || true
    fi
done

# Summary
echo ""
echo "=========================================="
echo "Test Results Summary"
echo "=========================================="
echo -e "Total:  ${TOTAL}"
echo -e "Passed: ${GREEN}${PASSED}${NC}"
echo -e "Failed: ${RED}${FAILED}${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}✗ Some tests failed${NC}"
    echo "Check logs in: ${RESULTS_DIR}/"
    exit 1
fi
