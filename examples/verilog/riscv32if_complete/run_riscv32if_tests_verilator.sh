#!/bin/bash

# Test RV32IF processor using Verilator
# Based on the run_all_tests.sh pattern from riscv32i_complete

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../../.." && pwd)
cd "$SCRIPT_DIR"

VERILOG_DIR="."

echo "Compiling RV32IF testbench with Verilator..."

# Check if we should use cvfpu
USE_CVFPU=0
if grep -q "cvfpu_simple" ${VERILOG_DIR}/riscv32if_complete.v 2>/dev/null; then
    USE_CVFPU=1
    echo "Including CVFPU sources..."
fi

# Only recompile if needed
RECOMPILE=0
if [ ! -f "${VERILOG_DIR}/test_rv32if" ]; then
    RECOMPILE=1
elif [ "${VERILOG_DIR}/riscv32if_complete.v" -nt "${VERILOG_DIR}/test_rv32if" ]; then
    RECOMPILE=1
elif [ "${VERILOG_DIR}/simple_tb.sv" -nt "${VERILOG_DIR}/test_rv32if" ]; then
    RECOMPILE=1
fi

if [ $RECOMPILE -eq 1 ]; then
    if [ $USE_CVFPU -eq 1 ]; then
        verilator --timing --exe --binary \
            -Wno-fatal -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-TIMESCALEMOD \
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
            -o test_rv32if riscv32if_complete.v simple_tb.sv
    else
        verilator --timing --exe --binary \
            -Wno-fatal -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-TIMESCALEMOD \
            -o test_rv32if riscv32if_complete.v simple_tb.sv
    fi

    if [ $? -ne 0 ]; then
        echo "ERROR: Verilator compilation failed!"
        exit 1
    fi

    # Move binary from obj_dir
    if ! mv obj_dir/test_rv32if . 2>/dev/null; then
        echo "ERROR: Failed to move Verilator sim binary from obj_dir/test_rv32if"
        exit 1
    fi
    if [ ! -x "./test_rv32if" ]; then
        echo "ERROR: Verilator sim binary './test_rv32if' not found or not executable"
        exit 1
    fi
    rm -rf obj_dir
fi

VERILOG_ABS="$SCRIPT_DIR"
TEST_CMD="./test_rv32if"

I_TESTS="add addi sub lui auipc and andi or ori xor xori sll slli srl srli sra srai slt slti sltu sltiu beq bne blt bltu bge bgeu jal jalr lw lh lhu lb lbu sw sh sb"
F_TESTS="fadd fcmp fcvt fcvt_w fdiv fmadd fmin ldst recoding"

PASS=0
FAIL=0
SKIP=0

echo ""
echo "=== Running RV32I Tests ==="
for test in $I_TESTS; do
    echo -n "  Testing $test... "

    TEST_BASE="$PROJECT_ROOT/isa/riscv32/riscv-tests/isa/rv32ui-isacomp-${test}"

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

# Write umem (unified memory for code + data)
with open('${VERILOG_ABS}/umem.hex', 'w') as f:
    for word_idx in range(max(1024, max_word)):
        word = 0
        addr = word_idx * 4
        for byte_offset in range(4):
            byte_addr = addr + byte_offset
            if byte_addr in data:
                word |= data[byte_addr] << (byte_offset * 8)
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
        # Print debug output for failing tests
        echo "$OUTPUT"
        FAIL=$((FAIL + 1))
    else
        echo "ERROR"
        Fail=$((FAIL + 1))
    fi
done

echo ""
echo "=== Running RV32F Tests ==="
for test in $F_TESTS; do
    echo -n "  Testing $test... "

    TEST_BASE="$PROJECT_ROOT/isa/riscv32/riscv-tests/isa/rv32uf-isacomp-${test}"

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

# Write umem (unified memory for code + data)
with open('${VERILOG_ABS}/umem.hex', 'w') as f:
    for word_idx in range(max(1024, max_word)):
        word = 0
        addr = word_idx * 4
        for byte_offset in range(4):
            byte_addr = addr + byte_offset
            if byte_addr in data:
                word |= data[byte_addr] << (byte_offset * 8)
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
        # Print debug output for failing tests
        echo "$OUTPUT"
        Fail=$((FAIL + 1))
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
