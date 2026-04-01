#!/bin/bash
# Run a PDP-11 test
# Usage: ./run_test.sh <test_name> [pass_addr] [fail_addr]

set -e

TEST_NAME=${1:-mov}
PASS_ADDR=${2:-0020}
FAIL_ADDR=${3:-0022}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERILOG_DIR="$SCRIPT_DIR/../../../examples/verilog/pdp11_complete"
TEST_DIR="$SCRIPT_DIR/isa"

echo "=== Running PDP-11 test: $TEST_NAME ==="
echo "Pass address: 0x$PASS_ADDR"
echo "Fail address: 0x$FAIL_ADDR"

# Create work directory
WORK_DIR=$(mktemp -d)
trap "rm -rf $WORK_DIR" EXIT

cd $WORK_DIR

# Copy test hex file as umem.hex
cp "$TEST_DIR/${TEST_NAME}.hex" umem.hex

# Compile with iverilog
echo "Compiling..."
iverilog -g2012 -o sim.vvp \
    "$VERILOG_DIR/pdp11_complete.v" \
    "$SCRIPT_DIR/simple_tb.sv"

# Run simulation
echo "Running simulation..."
vvp sim.vvp +pass_addr=$PASS_ADDR +fail_addr=$FAIL_ADDR

echo "=== Test complete ==="
