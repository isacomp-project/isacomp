#!/bin/bash
# Test runner for RV32I_Zfinx processor using Verilator
#
# Uses the actual OpenHW Group cvfpu for IEEE 754 FP operations

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEST_DIR="$SCRIPT_DIR/../../../isa/riscv32/riscv-tests-zfinx/isa"
VENDOR_DIR="$SCRIPT_DIR/../../../vendor"

echo "=================================================="
echo "RV32I_Zfinx Test Runner (Verilator + cvfpu)"
echo "=================================================="

# Check for required files
if [ ! -f "$SCRIPT_DIR/riscv32i_zfinx_complete.v" ]; then
    echo "Error: riscv32i_zfinx_complete.v not found"
    echo "Run generate_riscv32i_zfinx_complete.py first"
    exit 1
fi

if [ ! -f "$VENDOR_DIR/cvfpu/src/fpnew_pkg.sv" ]; then
    echo "Error: cvfpu not found. Run: git submodule update --init vendor/cvfpu vendor/common_cells vendor/fpu_div_sqrt_mvp"
    exit 1
fi

# Build simulation if not already built or if sources changed
BUILD_DIR="$SCRIPT_DIR/obj_dir"
SIM_EXE="$BUILD_DIR/Vsimple_tb"

rebuild_needed=0
if [ ! -f "$SIM_EXE" ]; then
    rebuild_needed=1
elif [ "$SCRIPT_DIR/riscv32i_zfinx_complete.v" -nt "$SIM_EXE" ]; then
    rebuild_needed=1
elif [ "$SCRIPT_DIR/simple_tb.sv" -nt "$SIM_EXE" ]; then
    rebuild_needed=1
fi

if [ $rebuild_needed -eq 1 ]; then
    echo "Compiling design with Verilator..."

    cd "$VENDOR_DIR"

    verilator --cc --build -j 0 -Wno-fatal --timing --binary \
        -Wno-WIDTHEXPAND -Wno-WIDTHTRUNC -Wno-UNUSEDSIGNAL -Wno-UNUSEDPARAM \
        -Wno-PINMISSING -Wno-TIMESCALEMOD -Wno-ENUMVALUE -Wno-UNOPTFLAT \
        -Wno-ASCRANGE -Wno-WIDTHCONCAT -Wno-CASEINCOMPLETE -Wno-LATCH \
        -Wno-UNSIGNED -Wno-CMPCONST -Wno-SELRANGE -Wno-MULTIDRIVEN \
        -Wno-SPLITVAR -Wno-BLKANDNBLK \
        +incdir+common_cells/include \
        +incdir+fpu_div_sqrt_mvp/hdl \
        +incdir+cvfpu/src \
        common_cells/src/cf_math_pkg.sv \
        common_cells/src/lzc.sv \
        common_cells/src/rr_arb_tree.sv \
        fpu_div_sqrt_mvp/hdl/defs_div_sqrt_mvp.sv \
        fpu_div_sqrt_mvp/hdl/preprocess_mvp.sv \
        fpu_div_sqrt_mvp/hdl/nrbd_nrsc_mvp.sv \
        fpu_div_sqrt_mvp/hdl/control_mvp.sv \
        fpu_div_sqrt_mvp/hdl/iteration_div_sqrt_mvp.sv \
        fpu_div_sqrt_mvp/hdl/norm_div_sqrt_mvp.sv \
        fpu_div_sqrt_mvp/hdl/div_sqrt_top_mvp.sv \
        fpu_div_sqrt_mvp/hdl/div_sqrt_mvp_wrapper.sv \
        cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/clk/rtl/gated_clk_cell.v \
        cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_ctrl.v \
        cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_ff1.v \
        cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_pack_single.v \
        cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_prepare.v \
        cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_round_single.v \
        cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_special.v \
        cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_srt_single.v \
        cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_top.v \
        cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fpu/rtl/pa_fpu_dp.v \
        cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fpu/rtl/pa_fpu_frbus.v \
        cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fpu/rtl/pa_fpu_src_type.v \
        cvfpu/src/fpnew_pkg.sv \
        cvfpu/src/fpnew_classifier.sv \
        cvfpu/src/fpnew_rounding.sv \
        cvfpu/src/fpnew_fma.sv \
        cvfpu/src/fpnew_fma_multi.sv \
        cvfpu/src/fpnew_cast_multi.sv \
        cvfpu/src/fpnew_noncomp.sv \
        cvfpu/src/fpnew_divsqrt_multi.sv \
        cvfpu/src/fpnew_opgroup_fmt_slice.sv \
        cvfpu/src/fpnew_opgroup_multifmt_slice.sv \
        cvfpu/src/fpnew_opgroup_block.sv \
        cvfpu/src/fpnew_top.sv \
        cvfpu_wrapper.sv \
        "$SCRIPT_DIR/riscv32i_zfinx_complete.v" \
        "$SCRIPT_DIR/simple_tb.sv" \
        --Mdir "$BUILD_DIR" \
        --top-module simple_tb \
        2>&1 || true  # Verilator may have spurious exit errors even when build succeeds

    cd "$SCRIPT_DIR"

    if [ ! -f "$SIM_EXE" ]; then
        echo "Verilator compilation failed - binary not created"
        exit 1
    fi
    echo "Compilation successful"
else
    echo "Using cached simulation binary"
fi
echo ""

# Run tests
PASSED=0
FAILED=0
TOTAL=0

for test_hex in "$TEST_DIR"/*.hex; do
    if [ -f "$test_hex" ]; then
        test_name=$(basename "$test_hex" .hex)
        addrs_file="$TEST_DIR/${test_name}.addrs"

        if [ -f "$addrs_file" ]; then
            read PASS_ADDR FAIL_ADDR < "$addrs_file"
        else
            echo "Warning: No .addrs file for $test_name, using defaults"
            PASS_ADDR="FFFFFFFF"
            FAIL_ADDR="FFFFFFFE"
        fi

        TOTAL=$((TOTAL + 1))
        printf "Testing %-40s " "$test_name..."

        # Copy hex file to umem.hex for testbench
        cp "$test_hex" "$SCRIPT_DIR/umem.hex"

        # Run simulation with timeout
        cd "$SCRIPT_DIR"
        OUTPUT=$(timeout 30s "$SIM_EXE" \
            +pass_addr=0x$PASS_ADDR \
            +fail_addr=0x$FAIL_ADDR \
            2>&1) || true

        if echo "$OUTPUT" | grep -q "TEST PASSED"; then
            echo "PASSED"
            PASSED=$((PASSED + 1))
        elif echo "$OUTPUT" | grep -q "TEST FAILED"; then
            echo "FAILED"
            FAILED=$((FAILED + 1))
            echo "  Test number that failed: $(echo "$OUTPUT" | grep -o 'TESTNUM.*' | head -1)"
        elif echo "$OUTPUT" | grep -q "TIMEOUT"; then
            echo "TIMEOUT"
            FAILED=$((FAILED + 1))
        else
            echo "ERROR"
            FAILED=$((FAILED + 1))
            echo "  Output: $(echo "$OUTPUT" | tail -5)"
        fi
    fi
done

# Cleanup
rm -f "$SCRIPT_DIR/umem.hex"

echo ""
echo "=================================================="
echo "Results: $PASSED/$TOTAL passed, $FAILED failed"
echo "=================================================="

if [ $FAILED -eq 0 ] && [ $TOTAL -gt 0 ]; then
    echo "All tests passed!"
    exit 0
else
    exit 1
fi
