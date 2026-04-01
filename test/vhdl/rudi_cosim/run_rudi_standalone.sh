#!/bin/bash
# Cosimulation runner for Rudi RV32I with riscv-tests

set -e

GHDL=${GHDL:-ghdl}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUDI_SRC="$SCRIPT_DIR/../../../frontends/vhdl/rudi-rv32i/src/cpu"

echo "========================================"
echo "Rudi RV32I Cosimulation"
echo "========================================"

# Step 1: Compile all Rudi components
echo ""
echo "Step 1: Compiling Rudi VHDL components..."
cd "$SCRIPT_DIR"

# Clean old work library
rm -f work-obj08.cf

# Compile in dependency order
$GHDL -a --std=08 $RUDI_SRC/data_bus_mux_a.vhd
$GHDL -a --std=08 $RUDI_SRC/data_bus_mux_b.vhd
$GHDL -a --std=08 $RUDI_SRC/sign_extender.vhd
$GHDL -a --std=08 $RUDI_SRC/result_bus_mux.vhd
$GHDL -a --std=08 $RUDI_SRC/alu.vhd
$GHDL -a --std=08 $RUDI_SRC/shifter.vhd
$GHDL -a --std=08 $RUDI_SRC/branch_test.vhd
$GHDL -a --std=08 $RUDI_SRC/program_counter.vhd
$GHDL -a --std=08 $RUDI_SRC/register_file.vhd
$GHDL -a --std=08 $RUDI_SRC/decode.vhd
$GHDL -a --std=08 $RUDI_SRC/riscv_cpu.vhd

echo "  Rudi components compiled successfully!"

# Step 2: Compile testbench
echo ""
echo "Step 2: Compiling testbench..."
$GHDL -a --std=08 rudi_standalone_tb.vhd
echo "  Testbench compiled!"

# Step 3: Elaborate
echo ""
echo "Step 3: Elaborating..."
$GHDL -e --std=08 rudi_standalone_tb
echo "  Elaboration complete!"

# Step 4: Run simulation
echo ""
echo "Step 4: Running simulation..."
if [ -f "imem.mem" ]; then
    echo "  Using memory file: imem.mem"
    $GHDL -r --std=08 rudi_standalone_tb --stop-time=10ms --stop-delta=10000 2>&1
else
    echo "  ERROR: imem.mem not found!"
    echo "  Please generate memory file from riscv-test binary first."
    exit 1
fi

echo ""
echo "========================================"
echo "Cosimulation complete!"
echo "========================================"
