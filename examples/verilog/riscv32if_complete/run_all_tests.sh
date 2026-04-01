#!/bin/bash

# Test all RV32I and RV32F instructions using simple_tb with hex files
# Supports both iverilog and verilator simulators
# Set SIMULATOR=verilator to use Verilator instead of Icarus Verilog

SIMULATOR=${SIMULATOR:-iverilog}

echo "Compiling simple testbench with $SIMULATOR..."

# CVFPU source files (using cvfpu's internal submodules)
VENDOR_DIR="../../../vendor"
CVFPU_DIR="$VENDOR_DIR/cvfpu"

# T-Head E906 FPU sources (required for TH32 div/sqrt) - pure Verilog, no dependencies
THEAD_FPU_DIR="$CVFPU_DIR/vendor/opene906/E906_RTL_FACTORY/gen_rtl"
THEAD_SOURCES="
    $THEAD_FPU_DIR/clk/rtl/gated_clk_cell.v
    $THEAD_FPU_DIR/fdsu/rtl/pa_fdsu_ctrl.v
    $THEAD_FPU_DIR/fdsu/rtl/pa_fdsu_ff1.v
    $THEAD_FPU_DIR/fdsu/rtl/pa_fdsu_pack_single.v
    $THEAD_FPU_DIR/fdsu/rtl/pa_fdsu_prepare.v
    $THEAD_FPU_DIR/fdsu/rtl/pa_fdsu_round_single.v
    $THEAD_FPU_DIR/fdsu/rtl/pa_fdsu_special.v
    $THEAD_FPU_DIR/fdsu/rtl/pa_fdsu_srt_single.v
    $THEAD_FPU_DIR/fdsu/rtl/pa_fdsu_top.v
    $THEAD_FPU_DIR/fpu/rtl/pa_fpu_dp.v
    $THEAD_FPU_DIR/fpu/rtl/pa_fpu_frbus.v
    $THEAD_FPU_DIR/fpu/rtl/pa_fpu_src_type.v
"

# CVFPU sources - fpnew_pkg.sv first, then modules that depend on it
CVFPU_SOURCES="
    $CVFPU_DIR/src/common_cells/src/cf_math_pkg.sv
    $CVFPU_DIR/src/common_cells/src/lzc.sv
    $CVFPU_DIR/src/common_cells/src/rr_arb_tree.sv
    $CVFPU_DIR/src/fpu_div_sqrt_mvp/hdl/defs_div_sqrt_mvp.sv
    $CVFPU_DIR/src/fpu_div_sqrt_mvp/hdl/preprocess_mvp.sv
    $CVFPU_DIR/src/fpu_div_sqrt_mvp/hdl/nrbd_nrsc_mvp.sv
    $CVFPU_DIR/src/fpu_div_sqrt_mvp/hdl/control_mvp.sv
    $CVFPU_DIR/src/fpu_div_sqrt_mvp/hdl/iteration_div_sqrt_mvp.sv
    $CVFPU_DIR/src/fpu_div_sqrt_mvp/hdl/norm_div_sqrt_mvp.sv
    $CVFPU_DIR/src/fpu_div_sqrt_mvp/hdl/div_sqrt_top_mvp.sv
    $CVFPU_DIR/src/fpu_div_sqrt_mvp/hdl/div_sqrt_mvp_wrapper.sv
    $CVFPU_DIR/src/fpnew_pkg.sv
    $CVFPU_DIR/src/fpnew_classifier.sv
    $CVFPU_DIR/src/fpnew_rounding.sv
    $CVFPU_DIR/src/fpnew_fma.sv
    $CVFPU_DIR/src/fpnew_fma_multi.sv
    $CVFPU_DIR/src/fpnew_cast_multi.sv
    $CVFPU_DIR/src/fpnew_noncomp.sv
    $CVFPU_DIR/src/fpnew_divsqrt_multi.sv
    $CVFPU_DIR/src/fpnew_divsqrt_th_32.sv
    $CVFPU_DIR/src/fpnew_opgroup_fmt_slice.sv
    $CVFPU_DIR/src/fpnew_opgroup_multifmt_slice.sv
    $CVFPU_DIR/src/fpnew_opgroup_block.sv
    $CVFPU_DIR/src/fpnew_top.sv
    $VENDOR_DIR/cvfpu_wrapper.sv
"

INCLUDE_DIRS="-I$CVFPU_DIR/src/common_cells/include -I$CVFPU_DIR/src/fpu_div_sqrt_mvp/hdl -I$CVFPU_DIR/src"

if [ "$SIMULATOR" = "verilator" ]; then
    # Verilator compilation with timing support (v5+) - only recompile if needed
    if [ ! -f "test_simple" ] || [ "riscv32if_complete.v" -nt "test_simple" ] || [ "simple_tb.sv" -nt "test_simple" ]; then
        verilator --timing --exe --binary \
            -Wno-fatal -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-TIMESCALEMOD -Wno-UNOPTFLAT \
            -Wno-UNUSEDSIGNAL -Wno-UNUSEDPARAM -Wno-PINMISSING -Wno-CASEINCOMPLETE \
            -Wno-BLKANDNBLK -Wno-WIDTHCONCAT -Wno-ASCRANGE -Wno-UNSIGNED -Wno-MULTITOP \
            --top-module run_test \
            $INCLUDE_DIRS \
            -o test_simple riscv32if_complete.v $THEAD_SOURCES $CVFPU_SOURCES simple_tb.sv
        if [ $? -ne 0 ]; then
            echo "ERROR: Verilator compilation failed!"
            exit 1
        fi
        # Move binary from obj_dir and ensure it exists
        if ! mv obj_dir/test_simple . 2>/dev/null; then
            echo "ERROR: Failed to move Verilator sim binary from obj_dir/test_simple"
            exit 1
        fi
        if [ ! -x "./test_simple" ]; then
            echo "ERROR: Verilator sim binary './test_simple' not found or not executable"
            exit 1
        fi
    fi
    TEST_CMD="./test_simple"
else
    # Icarus Verilog compilation - only recompile if needed
    if [ ! -f "test_simple" ] || [ "riscv32if_complete.v" -nt "test_simple" ] || [ "simple_tb.sv" -nt "test_simple" ]; then
        iverilog -g2012 $INCLUDE_DIRS -o test_simple riscv32if_complete.v $CVFPU_SOURCES simple_tb.sv
        if [ $? -ne 0 ]; then
            echo "ERROR: Icarus Verilog compilation failed!"
            exit 1
        fi
    fi
    TEST_CMD="vvp test_simple"
fi

# RV32I tests
I_TESTS="add addi sub lui auipc and andi or ori xor xori sll slli srl srli sra srai slt slti sltu sltiu beq bne blt bltu bge bgeu jal jalr lw lh lhu lb lbu sw sh sb"

# RV32F tests
F_TESTS="fadd fclass fcmp fcvt fcvt_w fdiv fmadd fmin ldst move recoding"

PASS=0
FAIL=0
SKIP=0

echo ""
echo "========================================"
echo "Running RV32I tests..."
echo "========================================"

for test in $I_TESTS; do
    echo -n "Testing $test... "

    TEST_BASE="../../../isa/riscv32/riscv-tests/isa/rv32ui-isacomp-$test"

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

    # Get pass/fail addresses first
    read PASS_ADDR FAIL_ADDR < "$TEST_BASE.addrs"

    # I tests use Intel HEX format, convert to simple hex for Verilog $readmemh
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
max_addr = max(data.keys())
max_word = (max_addr // 4) + 1
with open('umem.hex', 'w') as f:
    for word_idx in range(max(1024, max_word)):
        word = 0
        for byte_offset in range(4):
            addr = word_idx * 4 + byte_offset
            if addr in data:
                word |= data[addr] << (byte_offset * 8)
        f.write(f'{word:08x}\n')
"

    # Run test
    RESULT=$(timeout 5 $TEST_CMD +pass_addr=$PASS_ADDR +fail_addr=$FAIL_ADDR 2>&1)
    EXIT_CODE=$?

    if echo "$RESULT" | grep -q "TEST PASSED"; then
        echo "PASS"
        PASS=$((PASS + 1))
    elif echo "$RESULT" | grep -q "TEST FAILED"; then
        echo "FAIL"
        FAIL=$((FAIL + 1))
    elif [ $EXIT_CODE -eq 124 ]; then
        echo "TIMEOUT"
        FAIL=$((FAIL + 1))
    else
        echo "ERROR"
        FAIL=$((FAIL + 1))
    fi
done

echo ""
echo "========================================"
echo "Running RV32F tests..."
echo "========================================"

for test in $F_TESTS; do
    echo -n "Testing $test... "

    TEST_BASE="../../../isa/riscv32/riscv-tests/isa/rv32uf-isacomp-$test"

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

    # Get pass/fail addresses first
    read PASS_ADDR FAIL_ADDR < "$TEST_BASE.addrs"

    # Check if file is Intel HEX or simple hex format
    if head -1 "$TEST_BASE.hex" | grep -q "^:"; then
        # Convert Intel HEX to simple hex for Verilog $readmemh
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
max_addr = max(data.keys())
max_word = (max_addr // 4) + 1
with open('umem.hex', 'w') as f:
    for word_idx in range(max(1024, max_word)):
        word = 0
        for byte_offset in range(4):
            addr = word_idx * 4 + byte_offset
            if addr in data:
                word |= data[addr] << (byte_offset * 8)
        f.write(f'{word:08x}\n')
"
    else
        # Simple hex format - copy directly
        cp "$TEST_BASE.hex" umem.hex
    fi

    # Run test
    RESULT=$(timeout 10 $TEST_CMD +pass_addr=$PASS_ADDR +fail_addr=$FAIL_ADDR 2>&1)
    EXIT_CODE=$?

    if echo "$RESULT" | grep -q "TEST PASSED"; then
        echo "PASS"
        PASS=$((PASS + 1))
    elif echo "$RESULT" | grep -q "TEST FAILED"; then
        echo "FAIL"
        FAIL=$((FAIL + 1))
    elif [ $EXIT_CODE -eq 124 ]; then
        echo "TIMEOUT"
        FAIL=$((FAIL + 1))
    else
        echo "ERROR"
        FAIL=$((FAIL + 1))
    fi
done

echo ""
echo "========================================"
echo "Results: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
echo "========================================"

# Exit with error if any tests failed or no tests passed
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
