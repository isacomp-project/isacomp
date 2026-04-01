#!/bin/bash
# Run RISC-V tests on RV32IF processor using iverilog

cd "$(dirname "$0")"

VERILOG_DIR="."
TEST_DIR="../../../isa/riscv32/riscv-tests/isa"
OBJCOPY="riscv64-unknown-elf-objcopy"

# Compile testbench once
echo "Compiling RV32IF testbench..."
iverilog -g2012 -o /tmp/rv32if_sim \
    ${VERILOG_DIR}/riscv32if_complete.v \
    ${VERILOG_DIR}/run_test.sv 2>&1

if [ $? -ne 0 ]; then
    echo "ERROR: Failed to compile testbench"
    exit 1
fi
echo "Testbench compiled successfully"

PASS=0
FAIL=0
SKIP=0

# Test lists
I_TESTS="add addi sub lui auipc and andi or ori xor xori sll slli srl srli sra srai slt slti sltu sltiu beq bne blt bltu bge bgeu jal jalr lw lh lhu lb lbu sw sh sb"
F_TESTS="fadd fcmp fcvt fcvt_w fdiv fmadd fmin ldst recoding"

run_test() {
    local test_name=$1
    local test_elf=$2

    if [ ! -f "$test_elf" ]; then
        echo "  SKIP: $test_name (no ELF file)"
        SKIP=$((SKIP + 1))
        return
    fi

    # Get pass/fail addresses
    if [ -f "${test_elf}.addrs" ]; then
        read PASS_ADDR FAIL_ADDR < "${test_elf}.addrs"
    else
        # Default addresses
        PASS_ADDR="0"
        FAIL_ADDR="0"
    fi

    # Convert to hex (word format for $readmemh)
    local hex_file="/tmp/${test_name}.hex"
    local bin_file="/tmp/${test_name}.bin"

    # Create binary first
    $OBJCOPY -O binary "$test_elf" "$bin_file" 2>/dev/null

    if [ ! -f "$bin_file" ]; then
        echo "  FAIL: $test_name (objcopy failed)"
        FAIL=$((FAIL + 1))
        return
    fi

    # Convert binary to word-addressed hex
    python3 -c "
import sys
with open('$bin_file', 'rb') as f:
    data = f.read()
# Pad to word boundary
while len(data) % 4 != 0:
    data += b'\\x00'
with open('$hex_file', 'w') as f:
    f.write('@00000000\\n')
    for i in range(0, len(data), 4):
        # Little-endian: bytes are in order d[0], d[1], d[2], d[3]
        word = data[i] | (data[i+1] << 8) | (data[i+2] << 16) | (data[i+3] << 24)
        f.write('%08x\\n' % word)
" 2>/dev/null

    rm -f "$bin_file"

    if [ ! -f "$hex_file" ]; then
        echo "  FAIL: $test_name (hex conversion failed)"
        FAIL=$((FAIL + 1))
        return
    fi

    # Run simulation
    echo -n "  Testing $test_name..."
    timeout 30s vvp /tmp/rv32if_sim +hex="$hex_file" +pass=$PASS_ADDR +fail=$FAIL_ADDR > /tmp/test_output.txt 2>&1
    local result=$?

    if grep -q "^PASS" /tmp/test_output.txt; then
        echo " PASS"
        PASS=$((PASS + 1))
    elif grep -q "^FAIL" /tmp/test_output.txt || grep -q "TIMEOUT" /tmp/test_output.txt; then
        echo " FAIL"
        cat /tmp/test_output.txt | tail -5
        FAIL=$((FAIL + 1))
    else
        echo " ERROR (unknown result)"
        cat /tmp/test_output.txt | tail -10
        FAIL=$((FAIL + 1))
    fi

    rm -f "$hex_file"
}

echo ""
echo "=== Running RV32I Tests ==="
for test in $I_TESTS; do
    run_test "$test" "${TEST_DIR}/rv32ui-isacomp-${test}"
done

echo ""
echo "=== Running RV32F Tests ==="
for test in $F_TESTS; do
    run_test "$test" "${TEST_DIR}/rv32uf-isacomp-${test}"
done

echo ""
echo "=============================="
echo "Results: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
echo "=============================="

if [ $FAIL -gt 0 ]; then
    exit 1
fi
exit 0
