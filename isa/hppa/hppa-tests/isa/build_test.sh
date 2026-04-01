#!/bin/bash
# Build HPPA test and run simulation
# Usage: ./build_test.sh <test_name>

set -e

TEST=$1
if [ -z "$TEST" ]; then
    echo "Usage: $0 <test_name>"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERILOG_DIR="$SCRIPT_DIR/../../../../examples/verilog/hppa"
TESTS_DIR="$SCRIPT_DIR/.."

# Preprocess
echo "Preprocessing ${TEST}.S..."
hppa-linux-gnu-gcc -E -I"$SCRIPT_DIR" "${TEST}.S" -o "${TEST}.i"

# Convert semicolons to newlines for HPPA assembler
echo "Converting statement separators..."
sed -i 's/;/\n/g' "${TEST}.i"

# Assemble
echo "Assembling..."
hppa-linux-gnu-as -o "${TEST}.o" "${TEST}.i"

# Link
echo "Linking..."
hppa-linux-gnu-ld -T link.ld -o "${TEST}.elf" "${TEST}.o"

# Convert to binary
echo "Creating binary..."
hppa-linux-gnu-objcopy -O binary "${TEST}.elf" "${TEST}.bin"

# Convert to hex (big-endian to match HPPA)
# HPPA is big-endian, so we need to swap bytes when reading on little-endian host
echo "Creating hex file..."
xxd -p -c 4 "${TEST}.bin" | while read line; do
    # xxd outputs big-endian (correct byte order for HPPA)
    # Just reformat: AB CD EF 01 -> ABCDEF01
    echo "$line"
done > "${TEST}.hex"

# Show disassembly
echo ""
echo "=== Disassembly (first 50 lines) ==="
hppa-linux-gnu-objdump -d "${TEST}.elf" | head -50

# Get pass/fail addresses
PASS_ADDR=$(hppa-linux-gnu-nm "${TEST}.elf" | grep ' pass$' | awk '{print $1}')
FAIL_ADDR=$(hppa-linux-gnu-nm "${TEST}.elf" | grep ' fail$' | awk '{print $1}')

echo ""
echo "Pass address: 0x${PASS_ADDR}"
echo "Fail address: 0x${FAIL_ADDR}"

# Copy hex file to test directory and run simulation
cp "${TEST}.hex" "$TESTS_DIR/program.hex"

echo ""
echo "=== Running simulation ==="
cd "$TESTS_DIR"
iverilog -g2012 -o hppa_sim "${VERILOG_DIR}/hppa.v" hppa_tb_simple.sv
vvp -n hppa_sim +pass_addr=${PASS_ADDR} +fail_addr=${FAIL_ADDR}
