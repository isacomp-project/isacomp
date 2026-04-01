#!/bin/bash
# Run RISC-V tests on RV64IF processor using iverilog

cd "$(dirname "$0")"

VERILOG_DIR="."
TEST_DIR="../../../isa/riscv64/riscv-tests/isa"
OBJCOPY="riscv64-unknown-elf-objcopy"

# Check if we need to generate the processor first
if [ ! -f "${VERILOG_DIR}/riscv64if_complete.v" ]; then
    echo "Generating RV64IF processor..."
    python3 ../../../isa/riscv64/generators/generate_riscv64if_complete.py --backend verilog
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to generate processor"
        exit 1
    fi
fi

# Check if run_test.sv exists
if [ ! -f "${VERILOG_DIR}/run_test.sv" ]; then
    echo "ERROR: Missing run_test.sv in ${VERILOG_DIR}"
    exit 1
fi

# Compile testbench once
echo "Compiling RV64IF testbench..."
iverilog -g2012 -o /tmp/rv64if_sim \
    ${VERILOG_DIR}/riscv64if_complete.v \
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
# RV64I tests (49 instructions)
I_TESTS="add addi sub lui auipc and andi or ori xor xori sll slli srl srli sra srai slt slti sltu sltiu beq bne blt bltu bge bgeu jal jalr lw lh lhu lb lbu lwu ld sw sh sb sd addw addiw subw sllw slliw srlw srliw sraw sraiw"

# RV64F tests (single-precision floating-point)
F_TESTS="fadd fclass fcmp fcvt fcvt_w fdiv fmadd fmin ldst move recoding"

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

    # Convert to hex (64-bit word format for $readmemh)
    local hex_file="/tmp/${test_name}.hex"
    local bin_file="/tmp/${test_name}.bin"

    # Create binary first
    $OBJCOPY -O binary "$test_elf" "$bin_file" 2>/dev/null

    if [ ! -f "$bin_file" ]; then
        echo "  FAIL: $test_name (objcopy failed)"
        FAIL=$((FAIL + 1))
        return
    fi

    # Convert binary to 64-bit word-addressed hex
    python3 -c "
import sys
with open('$bin_file', 'rb') as f:
    data = f.read()
# Pad to 64-bit word boundary
while len(data) % 8 != 0:
    data += b'\\x00'
with open('$hex_file', 'w') as f:
    f.write('@00000000\\n')
    for i in range(0, len(data), 8):
        # Little-endian: bytes are in order d[0]..d[7]
        word = (data[i] | (data[i+1] << 8) | (data[i+2] << 16) | (data[i+3] << 24) |
                (data[i+4] << 32) | (data[i+5] << 40) | (data[i+6] << 48) | (data[i+7] << 56))
        f.write('%016x\\n' % word)
" 2>/dev/null

    rm -f "$bin_file"

    if [ ! -f "$hex_file" ]; then
        echo "  FAIL: $test_name (hex conversion failed)"
        FAIL=$((FAIL + 1))
        return
    fi

    # Run simulation
    echo -n "  Testing $test_name..."
    timeout 60s vvp /tmp/rv64if_sim +hex="$hex_file" +pass=$PASS_ADDR +fail=$FAIL_ADDR > /tmp/test_output.txt 2>&1
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
echo "=== Running RV64I Tests ==="
for test in $I_TESTS; do
    run_test "$test" "${TEST_DIR}/rv64ui-isacomp-${test}"
done

echo ""
echo "=== Running RV64F Tests ==="
for test in $F_TESTS; do
    run_test "$test" "${TEST_DIR}/rv64uf-isacomp-${test}"
done

echo ""
echo "=============================="
echo "Results: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
echo "=============================="

if [ $FAIL -gt 0 ]; then
    exit 1
fi
exit 0
