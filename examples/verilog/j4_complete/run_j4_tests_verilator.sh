#!/bin/bash

# Test J4 (SuperH-4) processor using Verilator
# Based on run_riscv32if_tests_verilator.sh pattern

# Add verilator to PATH if installed locally
export PATH="/.local/bin:$PATH"

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../../.." && pwd)
cd "$SCRIPT_DIR"

VERILOG_DIR="."

# Generate J4 complete if not present
if [ ! -f "./j4_complete.v" ]; then
    echo "Generating J4 complete processor..."
    python3 ../../../isa/j4/generators/generate_j4_complete.py --subset full --backend verilog --output-dir .
fi

echo "Compiling J4 testbench with Verilator..."

# Check if we should use cvfpu
USE_CVFPU=0
if grep -q "cvfpu_simple" ${VERILOG_DIR}/j4_complete.v 2>/dev/null; then
    USE_CVFPU=1
    echo "Including CVFPU sources..."
fi

# Only recompile if needed
RECOMPILE=0
if [ ! -f "${VERILOG_DIR}/test_j4" ]; then
    RECOMPILE=1
elif [ "${VERILOG_DIR}/j4_complete.v" -nt "${VERILOG_DIR}/test_j4" ]; then
    RECOMPILE=1
elif [ "$PROJECT_ROOT/isa/j4/j4-tests/sim/simple_tb.sv" -nt "${VERILOG_DIR}/test_j4" ]; then
    RECOMPILE=1
fi

if [ $RECOMPILE -eq 1 ]; then
    # Copy simple_tb.sv to verilog dir
    cp "$PROJECT_ROOT/isa/j4/j4-tests/sim/simple_tb.sv" .

    if [ $USE_CVFPU -eq 1 ]; then
        verilator --timing --exe --binary \
            -Wno-fatal -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-TIMESCALEMOD -Wno-PINMISSING \
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
            -o test_j4 j4_complete.v simple_tb.sv
    else
        verilator --timing --exe --binary \
            -Wno-fatal -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-TIMESCALEMOD -Wno-PINMISSING \
            -o test_j4 j4_complete.v simple_tb.sv
    fi

    if [ $? -ne 0 ]; then
        echo "ERROR: Verilator compilation failed!"
        exit 1
    fi

    # Move binary from obj_dir
    if ! mv obj_dir/test_j4 . 2>/dev/null; then
        echo "ERROR: Failed to move Verilator sim binary from obj_dir/test_j4"
        exit 1
    fi
    rm -rf obj_dir
fi

VERILOG_ABS="$SCRIPT_DIR"
TEST_CMD="./test_j4"

# Test list - all tests that have been built
TESTS=""
for hex in "$PROJECT_ROOT/isa/j4/j4-tests/isa/j4-isacomp-"*.hex; do
    if [ -f "$hex" ]; then
        test_name=$(basename "$hex" .hex | sed 's/j4-isacomp-//')
        TESTS="$TESTS $test_name"
    fi
done

PASS=0
FAIL=0
SKIP=0

echo ""
echo "=== Running J4 Tests ==="
for test in $TESTS; do
    echo -n "  Testing $test... "

    TEST_BASE="$PROJECT_ROOT/isa/j4/j4-tests/isa/j4-isacomp-${test}"

    if [ ! -f "$TEST_BASE.hex" ]; then
        echo "SKIP (no hex file)"
        SKIP=$((SKIP + 1))
        continue
    fi

    if [ ! -f "$TEST_BASE.addrs" ]; then
        echo "SKIP (no addrs file)"
        SKIP=$((SKIP + 1))
        continue
    fi

    # Get pass/fail addresses from .addrs file
    read PASS_ADDR FAIL_ADDR < "$TEST_BASE.addrs"

    # Convert Intel HEX to unified memory format (umem.hex)
    python3 -c "
import sys
data = {}
with open('$TEST_BASE.hex', 'r') as f:
    for line in f:
        line = line.strip()
        if not line.startswith(':'):
            continue
        byte_count = int(line[1:3], 16)
        address = int(line[3:7], 16)
        record_type = int(line[7:9], 16)
        if record_type == 0:  # Data record
            for i in range(byte_count):
                byte_val = int(line[9+i*2:11+i*2], 16)
                data[address + i] = byte_val
        elif record_type == 1:  # EOF
            break

if not data:
    sys.exit(1)

# Unified memory: all code and data in one hex file
max_addr = max(data.keys())
max_word = (max_addr // 4) + 1

# Write umem (unified memory for code + data) - big endian for SH4
with open('${VERILOG_ABS}/umem.hex', 'w') as f:
    for word_idx in range(max(1024, max_word)):
        word = 0
        addr = word_idx * 4
        for byte_offset in range(4):
            byte_addr = addr + byte_offset
            if byte_addr in data:
                # Big endian: byte 0 is MSB
                word |= data[byte_addr] << ((3 - byte_offset) * 8)
        f.write(f'{word:08x}\n')
"

    if [ $? -ne 0 ]; then
        echo "FAIL (conversion error)"
        FAIL=$((FAIL + 1))
        continue
    fi

    # Run test from verilog directory
    OUTPUT=$(cd ${VERILOG_ABS} && timeout 30s $TEST_CMD +pass_addr=$PASS_ADDR +fail_addr=$FAIL_ADDR 2>&1)

    if echo "$OUTPUT" | grep -q "TEST PASSED"; then
        echo "PASS"
        PASS=$((PASS + 1))
    elif echo "$OUTPUT" | grep -q "TEST FAILED\|TIMEOUT"; then
        echo "FAIL"
        echo "$OUTPUT"
        FAIL=$((FAIL + 1))
    else
        echo "ERROR"
        FAIL=$((FAIL + 1))
    fi
done

rm -f ${VERILOG_ABS}/umem.hex

echo ""
echo "=============================="
echo "Results: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
echo "=============================="

if [ $FAIL -gt 0 ]; then
    exit 1
fi
exit 0
