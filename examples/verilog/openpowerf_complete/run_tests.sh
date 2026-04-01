#!/bin/bash

# Test OpenPOWER + FPU processor using Verilator

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Compiling OpenPOWER+FPU testbench with Verilator..."

# Verilator compilation with CVFPU sources
if [ ! -f "test_simple" ] || [ "openpowerf_complete.v" -nt "test_simple" ] || [ "simple_tb.sv" -nt "test_simple" ]; then
    verilator --timing --exe --binary \
        -Wno-fatal -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-TIMESCALEMOD -Wno-UNOPTFLAT -Wno-PINMISSING \
        -I../../../vendor/common_cells/include \
        -I../../../vendor/cvfpu/src \
        -I../../../vendor/fpu_div_sqrt_mvp/hdl \
        ../../../vendor/common_cells/src/cf_math_pkg.sv \
        ../../../vendor/common_cells/src/lzc.sv \
        ../../../vendor/common_cells/src/rr_arb_tree.sv \
        ../../../vendor/fpu_div_sqrt_mvp/hdl/defs_div_sqrt_mvp.sv \
        ../../../vendor/fpu_div_sqrt_mvp/hdl/preprocess_mvp.sv \
        ../../../vendor/fpu_div_sqrt_mvp/hdl/nrbd_nrsc_mvp.sv \
        ../../../vendor/fpu_div_sqrt_mvp/hdl/control_mvp.sv \
        ../../../vendor/fpu_div_sqrt_mvp/hdl/iteration_div_sqrt_mvp.sv \
        ../../../vendor/fpu_div_sqrt_mvp/hdl/norm_div_sqrt_mvp.sv \
        ../../../vendor/fpu_div_sqrt_mvp/hdl/div_sqrt_top_mvp.sv \
        ../../../vendor/fpu_div_sqrt_mvp/hdl/div_sqrt_mvp_wrapper.sv \
        ../../../vendor/cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/clk/rtl/gated_clk_cell.v \
        ../../../vendor/cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_ctrl.v \
        ../../../vendor/cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_ff1.v \
        ../../../vendor/cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_pack_single.v \
        ../../../vendor/cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_prepare.v \
        ../../../vendor/cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_round_single.v \
        ../../../vendor/cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_special.v \
        ../../../vendor/cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_srt_single.v \
        ../../../vendor/cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_top.v \
        ../../../vendor/cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fpu/rtl/pa_fpu_dp.v \
        ../../../vendor/cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fpu/rtl/pa_fpu_frbus.v \
        ../../../vendor/cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fpu/rtl/pa_fpu_src_type.v \
        ../../../vendor/cvfpu/src/fpnew_pkg.sv \
        ../../../vendor/cvfpu/src/fpnew_classifier.sv \
        ../../../vendor/cvfpu/src/fpnew_rounding.sv \
        ../../../vendor/cvfpu/src/fpnew_fma.sv \
        ../../../vendor/cvfpu/src/fpnew_fma_multi.sv \
        ../../../vendor/cvfpu/src/fpnew_cast_multi.sv \
        ../../../vendor/cvfpu/src/fpnew_noncomp.sv \
        ../../../vendor/cvfpu/src/fpnew_divsqrt_th_32.sv \
        ../../../vendor/cvfpu/src/fpnew_divsqrt_multi.sv \
        ../../../vendor/cvfpu/src/fpnew_opgroup_fmt_slice.sv \
        ../../../vendor/cvfpu/src/fpnew_opgroup_multifmt_slice.sv \
        ../../../vendor/cvfpu/src/fpnew_opgroup_block.sv \
        ../../../vendor/cvfpu/src/fpnew_top.sv \
        ../../../vendor/cvfpu_wrapper.sv \
        -o test_simple openpowerf_complete.v simple_tb.sv
    if [ $? -ne 0 ]; then
        echo "ERROR: Verilator compilation failed!"
        exit 1
    fi
    if ! mv obj_dir/test_simple . 2>/dev/null; then
        echo "ERROR: Failed to move Verilator sim binary"
        exit 1
    fi
    rm -rf obj_dir
fi
TEST_CMD="./test_simple"

TEST_DIR="../../../isa/openpower/power-tests/isa"

# Create empty register files (64-bit)
python3 -c "
with open('rf.hex', 'w') as f:
    for i in range(32):
        f.write('0000000000000000\n')
with open('frf.hex', 'w') as f:
    for i in range(32):
        f.write('0000000000000000\n')
"

PASS=0
FAIL=0
SKIP=0
FAILED_TESTS=""

# Get list of tests (base + FP)
BASE_TESTS=$(ls "$TEST_DIR"/*.S 2>/dev/null | xargs -n1 basename | sed 's/\.S$//' | grep -v test_macros)
FP_TESTS=$(ls "$TEST_DIR"/f/*.S 2>/dev/null | xargs -n1 basename | sed 's/\.S$//')
TESTS="$BASE_TESTS $FP_TESTS"

for test in $TESTS; do
    echo -n "Testing $test... "

    # Check if it's an FP test (in f/ subdirectory)
    if [ -f "$TEST_DIR/f/$test.S" ]; then
        IMEM_FILE="$TEST_DIR/f/power-isacomp-$test.imem.hex"
        DMEM_FILE="$TEST_DIR/f/power-isacomp-$test.dmem.hex"
        ADDR_FILE="$TEST_DIR/f/power-isacomp-$test.addrs"
    else
        IMEM_FILE="$TEST_DIR/power-isacomp-$test.imem.hex"
        DMEM_FILE="$TEST_DIR/power-isacomp-$test.dmem.hex"
        ADDR_FILE="$TEST_DIR/power-isacomp-$test.addrs"
    fi

    if [ ! -f "$IMEM_FILE" ] || [ ! -f "$DMEM_FILE" ]; then
        echo "SKIP (files not found)"
        SKIP=$((SKIP + 1))
        continue
    fi

    if [ ! -f "$ADDR_FILE" ]; then
        echo "SKIP (no addr file)"
        SKIP=$((SKIP + 1))
        continue
    fi

    PASS_ADDR=$(cat "$ADDR_FILE" | awk '{print $1}')
    FAIL_ADDR=$(cat "$ADDR_FILE" | awk '{print $2}')

    if [ -z "$PASS_ADDR" ] || [ -z "$FAIL_ADDR" ]; then
        echo "SKIP (no pass/fail symbols)"
        SKIP=$((SKIP + 1))
        continue
    fi

    # Merge imem and dmem into unified umem.hex (64-bit words)
    # Note: dmem files may be large but mostly zeros, only include non-zero entries
    python3 -c "
import sys
umem = {}
# Load instruction memory (32-bit instructions packed into 64-bit words)
with open('$IMEM_FILE', 'r') as f:
    for i, line in enumerate(f):
        line = line.strip()
        if line:
            word_addr = i // 2
            if word_addr not in umem:
                umem[word_addr] = ['00000000', '00000000']
            if i % 2 == 0:
                umem[word_addr][1] = line.zfill(8)
            else:
                umem[word_addr][0] = line.zfill(8)
# Load data memory (only non-zero entries, offset at word 8192)
with open('$DMEM_FILE', 'r') as f:
    for i, line in enumerate(f):
        line = line.strip()
        if line and line != '0000000000000000':
            word_addr = 8192 + i
            if word_addr < 16384:  # Stay within memory bounds
                umem[word_addr] = [line.zfill(16)[:8], line.zfill(16)[8:]]
max_addr = max(umem.keys()) if umem else 0
with open('umem.hex', 'w') as f:
    for addr in range(max_addr + 1):
        if addr in umem:
            f.write(umem[addr][0] + umem[addr][1] + '\n')
        else:
            f.write('0000000000000000\n')
"

    OUTPUT=$(timeout 10 $TEST_CMD +pass_addr="$PASS_ADDR" +fail_addr="$FAIL_ADDR" 2>&1)

    if echo "$OUTPUT" | grep -q "TEST PASSED"; then
        echo "PASS"
        PASS=$((PASS + 1))
    elif echo "$OUTPUT" | grep -q "TEST FAILED"; then
        TESTNUM=$(echo "$OUTPUT" | grep -oP 'testnum=\K\d+' || echo "?")
        echo "FAIL (test $TESTNUM)"
        FAIL=$((FAIL + 1))
        FAILED_TESTS="$FAILED_TESTS $test"
    elif echo "$OUTPUT" | grep -q "TIMEOUT"; then
        echo "TIMEOUT"
        FAIL=$((FAIL + 1))
        FAILED_TESTS="$FAILED_TESTS $test"
    else
        echo "ERROR"
        FAIL=$((FAIL + 1))
        FAILED_TESTS="$FAILED_TESTS $test"
    fi
done

rm -f umem.hex

echo ""
echo "================================"
echo "Results: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
if [ -n "$FAILED_TESTS" ]; then
    echo "Failed tests:$FAILED_TESTS"
fi
echo "================================"

if [ $FAIL -gt 0 ]; then
    exit 1
fi

if [ $PASS -eq 0 ]; then
    echo "FAILED: No tests passed"
    exit 1
fi

echo "SUCCESS: All $PASS tests passed"
exit 0
