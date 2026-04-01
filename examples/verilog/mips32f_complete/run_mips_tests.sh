#!/bin/bash

# Test MIPS32 + FPU instructions using the single-cycle processor
# Uses Verilator for simulation

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Compiling MIPS32F testbench with Verilator..."

# Verilator compilation with timing support and CVFPU sources
if [ ! -f "test_simple" ] || [ "mips32f_complete.v" -nt "test_simple" ] || [ "simple_tb.sv" -nt "test_simple" ]; then
    verilator --timing --exe --binary \
        -Wno-fatal -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-TIMESCALEMOD -Wno-UNOPTFLAT \
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
        -o test_simple mips32f_complete.v simple_tb.sv
    if [ $? -ne 0 ]; then
        echo "ERROR: Verilator compilation failed!"
        exit 1
    fi
    # Move binary from obj_dir
    if ! mv obj_dir/test_simple . 2>/dev/null; then
        echo "ERROR: Failed to move Verilator sim binary from obj_dir/test_simple"
        exit 1
    fi
    rm -rf obj_dir
fi
TEST_CMD="./test_simple"

# Create empty register files (start at zero)
python3 -c "
with open('rf.hex', 'w') as f:
    for i in range(32):
        f.write('00000000\n')
with open('frf.hex', 'w') as f:
    for i in range(32):
        f.write('00000000\n')
"

# Base MIPS32 tests
BASE_TESTS="add addi addiu addu and andi beq bne j jal jalr jr lb lbu lh lhu lui lw nor or ori sb sh sll sllv slt slti sltiu sltu sra srav srl srlv sub subu sw xor xori"

# FP tests (in f/ subdirectory)
FP_TESTS="fadd_s fdiv_s fmove_s fmul_s fsqrt_s fsub_s"

PASS=0
FAIL=0
SKIP=0
FAILED_TESTS=""

run_test() {
    local test=$1
    local test_dir=$2

    echo -n "Testing $test... "

    TEST_BASE="$test_dir/mips32-isacomp-$test"

    if [ ! -f "$TEST_BASE.hex" ]; then
        echo "SKIP (no hex file)"
        SKIP=$((SKIP + 1))
        return
    fi

    if [ ! -f "$TEST_BASE.addrs" ]; then
        echo "SKIP (no addrs file)"
        SKIP=$((SKIP + 1))
        return
    fi

    # Get pass/fail addresses
    read PASS_ADDR FAIL_ADDR < "$TEST_BASE.addrs"

    # Convert Intel HEX to umem.hex (unified memory)
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

# Write umem (unified memory) - 8192 words (little-endian)
with open('umem.hex', 'w') as f:
    for word_idx in range(8192):
        word = 0
        addr = word_idx * 4
        word = data.get(addr, 0) | (data.get(addr+1, 0) << 8) | (data.get(addr+2, 0) << 16) | (data.get(addr+3, 0) << 24)
        f.write(f'{word:08x}\n')
"

    # Run test
    RESULT=$(timeout 10 $TEST_CMD +pass_addr=$PASS_ADDR +fail_addr=$FAIL_ADDR 2>&1)
    EXIT_CODE=$?

    if echo "$RESULT" | grep -q "TEST PASSED"; then
        echo "PASS"
        PASS=$((PASS + 1))
    elif echo "$RESULT" | grep -q "TEST FAILED"; then
        echo "FAIL"
        FAIL=$((FAIL + 1))
        FAILED_TESTS="$FAILED_TESTS $test"
    elif [ $EXIT_CODE -eq 124 ]; then
        echo "TIMEOUT"
        FAIL=$((FAIL + 1))
        FAILED_TESTS="$FAILED_TESTS $test"
    else
        echo "ERROR"
        FAIL=$((FAIL + 1))
        FAILED_TESTS="$FAILED_TESTS $test"
    fi
}

# Run base tests
for test in $BASE_TESTS; do
    run_test "$test" "../../../isa/mips32/mips-tests/isa"
done

# Run FP tests
for test in $FP_TESTS; do
    run_test "$test" "../../../isa/mips32/mips-tests/isa/f"
done

echo ""
echo "================================"
echo "Results: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
if [ -n "$FAILED_TESTS" ]; then
    echo "Failed tests:$FAILED_TESTS"
fi
echo "================================"

# Exit with error if any tests failed
if [ $FAIL -gt 0 ]; then
    echo "FAILED: $FAIL test(s) failed"
    exit 1
fi

if [ $PASS -eq 0 ]; then
    echo "FAILED: No tests passed (all skipped)"
    exit 1
fi

echo "SUCCESS: All $PASS tests passed"
exit 0
