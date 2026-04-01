#!/bin/bash
# Build Verilator simulation binary for fast TDMI testing
#
# Prerequisites:
#   apt install verilator  # (or build from source)
#   python3 isa/tdmi/generators/generate_tdmi.py  # Generate Verilog first
#
# Usage:
#   cd /path/to/isacomp
#   ./isa/tdmi/tests/build_verilator_sim.sh
#
# Then run tests with:
#   python3 isa/tdmi/tests/run_singlestep_tests.py --verilator-fast --category ldm_stm

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
VERILOG_DIR="$PROJECT_ROOT/examples/verilog/tdmi"
OUTPUT_DIR="$SCRIPT_DIR"

# Check prerequisites
if ! command -v verilator &> /dev/null; then
    echo "Error: verilator not found. Install with: apt install verilator"
    exit 1
fi

if [ ! -f "$VERILOG_DIR/tdmi.v" ]; then
    echo "Error: $VERILOG_DIR/tdmi.v not found"
    echo "Generate it with: python3 isa/tdmi/generators/generate_tdmi.py"
    exit 1
fi

echo "Building Verilator simulation binary..."
echo "  Verilog: $VERILOG_DIR/tdmi.v"
echo "  Testbench: $SCRIPT_DIR/tb_generic.v"
echo "  Output: $OUTPUT_DIR/sim_generic"

cd "$OUTPUT_DIR"

verilator --binary --timing \
    -Wno-fatal -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-UNUSEDSIGNAL \
    -Wno-UNDRIVEN -Wno-LATCH -Wno-TIMESCALEMOD -Wno-DECLFILENAME \
    -Wno-UNUSEDPARAM -Wno-WIDTHCONCAT -Wno-UNSIGNED -Wno-MULTIDRIVEN \
    -Wno-UNOPTFLAT -Wno-CASEINCOMPLETE \
    --top-module tb_generic \
    -o sim_generic \
    "$VERILOG_DIR/tdmi.v" \
    "$SCRIPT_DIR/tb_generic.v"

# Move binary to expected location
mv obj_dir/sim_generic "$OUTPUT_DIR/sim_generic"

echo ""
echo "Build complete: $OUTPUT_DIR/sim_generic"
echo ""
echo "Run tests with:"
echo "  python3 isa/tdmi/tests/run_singlestep_tests.py --verilator-fast --max-tests 50"
