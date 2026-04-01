#!/bin/bash
# Run J4 tests using Verilator simulation (required for FPU tests)
# FPU tests require Verilator because cvfpu has complex SystemVerilog not supported by Icarus

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_DIR="$SCRIPT_DIR/../isa"
J4_VERILOG=""

# Check for Verilator
if ! command -v verilator &> /dev/null; then
    echo "ERROR: Verilator not found. Please install Verilator to run FPU tests."
    echo "  On Ubuntu/Debian: sudo apt install verilator"
    echo "  On macOS: brew install verilator"
    exit 1
fi

# Find or generate J4 Verilog (full version with FPU)
find_verilog() {
    if [ -f "$SCRIPT_DIR/j4_complete.v" ]; then
        J4_VERILOG="$SCRIPT_DIR/j4_complete.v"
    else
        echo "Generating J4 processor (full with FPU)..."
        python3 "$SCRIPT_DIR/../../generators/generate_j4_complete.py" --subset full --backend verilog --output-dir "$SCRIPT_DIR" 2>/dev/null
        if [ -f "$SCRIPT_DIR/j4_complete.v" ]; then
            J4_VERILOG="$SCRIPT_DIR/j4_complete.v"
        else
            echo "ERROR: Cannot generate j4_complete.v"
            exit 1
        fi
    fi
}

# Convert Intel HEX to $readmemh format (word-addressed, 32-bit for J4/SH4 unified memory)
intel_hex_to_memh() {
    local hex_file="$1"
    local memh_file="$2"

    python3 - "$hex_file" "$memh_file" << 'PYEOF'
import sys

def convert_ihex_to_memh(ihex_path, memh_path):
    # First pass: collect all bytes
    bytes_mem = {}
    extended_addr = 0

    with open(ihex_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line[0] != ':':
                continue

            byte_count = int(line[1:3], 16)
            address = int(line[3:7], 16)
            record_type = int(line[7:9], 16)

            if record_type == 0x00:  # Data record
                full_addr = extended_addr + address
                data = line[9:9 + byte_count * 2]
                for i in range(0, len(data), 2):
                    byte_addr = full_addr + i // 2
                    bytes_mem[byte_addr] = data[i:i+2]
            elif record_type == 0x02:  # Extended segment address
                extended_addr = int(line[9:13], 16) << 4
            elif record_type == 0x04:  # Extended linear address
                extended_addr = int(line[9:13], 16) << 16
            elif record_type == 0x01:  # EOF
                break

    # Second pass: combine into 32-bit words
    # SH4 is big-endian: byte at addr 0 is MSB of word at addr 0
    mem32 = {}
    if bytes_mem:
        max_byte_addr = max(bytes_mem.keys())
        max_word_addr = max_byte_addr // 4

        for word_addr in range(max_word_addr + 1):
            byte0 = bytes_mem.get(word_addr * 4, '00')
            byte1 = bytes_mem.get(word_addr * 4 + 1, '00')
            byte2 = bytes_mem.get(word_addr * 4 + 2, '00')
            byte3 = bytes_mem.get(word_addr * 4 + 3, '00')
            # Big-endian: MSB first (byte0 at highest bits)
            mem32[word_addr] = byte0 + byte1 + byte2 + byte3

    # Write in $readmemh format
    with open(memh_path, 'w') as f:
        if mem32:
            max_addr = max(mem32.keys())
            for addr in range(max_addr + 1):
                if addr in mem32:
                    f.write(f"{mem32[addr]}\n")
                else:
                    f.write("00000000\n")

if __name__ == "__main__":
    convert_ihex_to_memh(sys.argv[1], sys.argv[2])
PYEOF
}

# Compile simulator with Verilator (includes CVFPU for FPU tests)
compile_sim() {
    echo "Compiling J4 simulator with Verilator..."
    cd "$SCRIPT_DIR"
    # Remove old simulator to ensure we detect compilation failures
    rm -f j4_verilator_sim

    # Use CVFPU sources from vendor directory
    VENDOR_DIR="$SCRIPT_DIR/../../../../vendor"

    verilator --timing --exe --binary \
        -Wno-fatal -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-TIMESCALEMOD \
        -I${VENDOR_DIR}/common_cells/include \
        -I${VENDOR_DIR}/cvfpu/src \
        -I${VENDOR_DIR}/fpu_div_sqrt_mvp/hdl \
        ${VENDOR_DIR}/common_cells/src/cf_math_pkg.sv \
        ${VENDOR_DIR}/common_cells/src/lzc.sv \
        ${VENDOR_DIR}/common_cells/src/rr_arb_tree.sv \
        ${VENDOR_DIR}/fpu_div_sqrt_mvp/hdl/defs_div_sqrt_mvp.sv \
        ${VENDOR_DIR}/fpu_div_sqrt_mvp/hdl/preprocess_mvp.sv \
        ${VENDOR_DIR}/fpu_div_sqrt_mvp/hdl/nrbd_nrsc_mvp.sv \
        ${VENDOR_DIR}/fpu_div_sqrt_mvp/hdl/control_mvp.sv \
        ${VENDOR_DIR}/fpu_div_sqrt_mvp/hdl/iteration_div_sqrt_mvp.sv \
        ${VENDOR_DIR}/fpu_div_sqrt_mvp/hdl/norm_div_sqrt_mvp.sv \
        ${VENDOR_DIR}/fpu_div_sqrt_mvp/hdl/div_sqrt_top_mvp.sv \
        ${VENDOR_DIR}/fpu_div_sqrt_mvp/hdl/div_sqrt_mvp_wrapper.sv \
        ${VENDOR_DIR}/cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/clk/rtl/gated_clk_cell.v \
        ${VENDOR_DIR}/cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_ctrl.v \
        ${VENDOR_DIR}/cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_ff1.v \
        ${VENDOR_DIR}/cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_pack_single.v \
        ${VENDOR_DIR}/cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_prepare.v \
        ${VENDOR_DIR}/cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_round_single.v \
        ${VENDOR_DIR}/cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_special.v \
        ${VENDOR_DIR}/cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_srt_single.v \
        ${VENDOR_DIR}/cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_top.v \
        ${VENDOR_DIR}/cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fpu/rtl/pa_fpu_dp.v \
        ${VENDOR_DIR}/cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fpu/rtl/pa_fpu_frbus.v \
        ${VENDOR_DIR}/cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fpu/rtl/pa_fpu_src_type.v \
        ${VENDOR_DIR}/cvfpu/src/fpnew_pkg.sv \
        ${VENDOR_DIR}/cvfpu/src/fpnew_classifier.sv \
        ${VENDOR_DIR}/cvfpu/src/fpnew_rounding.sv \
        ${VENDOR_DIR}/cvfpu/src/fpnew_fma.sv \
        ${VENDOR_DIR}/cvfpu/src/fpnew_fma_multi.sv \
        ${VENDOR_DIR}/cvfpu/src/fpnew_cast_multi.sv \
        ${VENDOR_DIR}/cvfpu/src/fpnew_noncomp.sv \
        ${VENDOR_DIR}/cvfpu/src/fpnew_divsqrt_th_32.sv \
        ${VENDOR_DIR}/cvfpu/src/fpnew_divsqrt_multi.sv \
        ${VENDOR_DIR}/cvfpu/src/fpnew_opgroup_fmt_slice.sv \
        ${VENDOR_DIR}/cvfpu/src/fpnew_opgroup_multifmt_slice.sv \
        ${VENDOR_DIR}/cvfpu/src/fpnew_opgroup_block.sv \
        ${VENDOR_DIR}/cvfpu/src/fpnew_top.sv \
        ${VENDOR_DIR}/cvfpu_wrapper.sv \
        -o j4_verilator_sim j4_complete.v j4_complete_tb.sv 2>&1

    if [ $? -ne 0 ]; then
        echo "ERROR: Verilator compilation failed"
        exit 1
    fi

    # Move binary from obj_dir
    if ! mv obj_dir/j4_verilator_sim . 2>/dev/null; then
        echo "ERROR: Failed to move Verilator sim binary from obj_dir/j4_verilator_sim"
        exit 1
    fi
    rm -rf obj_dir

    if [ ! -f j4_verilator_sim ]; then
        echo "ERROR: Compilation failed - no output file"
        exit 1
    fi
}

# Run a single test
run_test() {
    local test_name="$1"
    local hex_file="$TEST_DIR/j4-isacomp-${test_name}.hex"
    local addr_file="$TEST_DIR/j4-isacomp-${test_name}.addrs"

    if [ ! -f "$hex_file" ]; then
        echo "SKIP: $test_name (no hex file)"
        return 2
    fi

    if [ ! -f "$addr_file" ]; then
        echo "SKIP: $test_name (no addr file)"
        return 2
    fi

    # Convert hex to memh format (unified memory)
    intel_hex_to_memh "$hex_file" "$SCRIPT_DIR/umem.hex"

    # Read pass/fail addresses (format: "pass_addr fail_addr")
    local pass_addr=$(awk '{print $1}' "$addr_file")
    local fail_addr=$(awk '{print $2}' "$addr_file")

    # Run simulation
    cd "$SCRIPT_DIR"
    local output=$(timeout 30 ./j4_verilator_sim +pass_addr="$pass_addr" +fail_addr="$fail_addr" 2>&1)

    if echo "$output" | grep -q "TEST PASSED"; then
        echo "PASS: $test_name"
        return 0
    elif echo "$output" | grep -q "TEST FAILED"; then
        echo "FAIL: $test_name"
        return 1
    else
        echo "TIMEOUT: $test_name"
        return 1
    fi
}

# Main
main() {
    find_verilog
    compile_sim

    local passed=0 failed=0 skipped=0

    if [ $# -gt 0 ]; then
        # Run specified tests
        for test in "$@"; do
            run_test "$test"
            case $? in
                0) ((passed++)) ;;
                1) ((failed++)) ;;
                2) ((skipped++)) ;;
            esac
        done
    else
        # Run all tests
        for hex_file in "$TEST_DIR"/j4-isacomp-*.hex; do
            if [ -f "$hex_file" ]; then
                test_name=$(basename "$hex_file" .hex | sed 's/j4-isacomp-//')
                run_test "$test_name"
                case $? in
                    0) ((passed++)) ;;
                    1) ((failed++)) ;;
                    2) ((skipped++)) ;;
                esac
            fi
        done
    fi

    echo ""
    echo "================================"
    echo "Results: $passed PASS, $failed FAIL, $skipped SKIP"
    echo "================================"

    [ $failed -eq 0 ]
}

main "$@"
