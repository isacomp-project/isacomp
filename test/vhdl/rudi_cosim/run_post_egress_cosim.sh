#!/bin/bash
# Cosimulation runner: Original Rudi vs Post-Egress (VHDL->ResourceGraph->VHDL)
# Usage: run_post_egress_cosim.sh [PASS_PC] [FAIL_PC]
# PCs are in decimal (e.g., 1264 for 0x4F0)

set -e

GHDL="${GHDL:-ghdl}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUDI_SRC="$SCRIPT_DIR/../../../frontends/vhdl/rudi-rv32i/src/cpu"
POST_EGRESS_SRC="$SCRIPT_DIR/../rudi_generated"

# Default pass/fail PCs (can be overridden via arguments)
PASS_PC=${1:-1264}    # 0x4F0 = 1264
FAIL_PC=${2:-1256}    # 0x4E8 = 1256

echo "========================================"
echo "Rudi Post-Egress Cosimulation"
echo "Original VHDL vs VHDL->ResourceGraph->VHDL"
echo "========================================"

cd "$SCRIPT_DIR"

# Clean old work library
rm -f work-obj08.cf

# Step 1: Compile original Rudi components
echo ""
echo "Step 1: Compiling Original Rudi VHDL..."
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
echo "  Original Rudi compiled!"

# Step 2: Compile original wrapper with memory
echo ""
echo "Step 2: Compiling Original Memory Wrapper..."
$GHDL -a --std=08 $POST_EGRESS_SRC/rudi_riscv_cpu_with_mem.vhd
echo "  Original memory wrapper compiled!"

# Step 3: Compile post-egress version (also has integrated memory)
echo ""
echo "Step 3: Compiling Post-Egress VHDL..."
$GHDL -a --std=08 $POST_EGRESS_SRC/rudi_post_egress.vhd
echo "  Post-egress version compiled!"

# Step 4: Compile cosimulation testbench
echo ""
echo "Step 4: Compiling cosimulation testbench..."
$GHDL -a --std=08 rudi_post_egress_cosim_tb.vhd
echo "  Testbench compiled!"

# Step 5: Elaborate
echo ""
echo "Step 5: Elaborating..."
$GHDL -e --std=08 rudi_post_egress_cosim_tb
echo "  Elaboration complete!"

# Step 6: Run simulation
echo ""
echo "Step 6: Running cosimulation..."
if [ -f "imem.mem" ]; then
    echo "  Using memory file: imem.mem"
    echo ""
    $GHDL -r --std=08 rudi_post_egress_cosim_tb -gPASS_PC_INT=$PASS_PC -gFAIL_PC_INT=$FAIL_PC --stop-delta=10000 2>&1
else
    echo "  ERROR: imem.mem not found!"
    echo "  Please generate memory file from riscv-test binary first."
    exit 1
fi

echo ""
echo "========================================"
echo "Cosimulation complete!"
echo "========================================"
