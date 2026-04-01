#!/bin/bash
# Run J4 tests using Icarus Verilog simulation

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_DIR="$SCRIPT_DIR/../isa"
J4_VERILOG=""

# Find or generate J4 Verilog
find_verilog() {
    if [ -f "$SCRIPT_DIR/j4_complete.v" ]; then
        J4_VERILOG="$SCRIPT_DIR/j4_complete.v"
    else
        echo "Generating J4 processor (full subset)..."
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

# Compile simulator
compile_sim() {
    echo "Compiling J4 simulator..."
    cd "$SCRIPT_DIR"
    # Remove old simulator to ensure we detect compilation failures
    rm -f j4_sim
    if ! iverilog -g2012 -o j4_sim cvfpu_simple.v j4_complete.v simple_tb.sv 2>&1; then
        echo "ERROR: Verilog compilation failed"
        exit 1
    fi
    if [ ! -f j4_sim ]; then
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

    # Create empty rf.hex (register file initialization)
    : > "$SCRIPT_DIR/rf.hex"

    # Read pass/fail addresses (format: "pass_addr fail_addr")
    local pass_addr=$(awk '{print $1}' "$addr_file")
    local fail_addr=$(awk '{print $2}' "$addr_file")

    # Run simulation
    cd "$SCRIPT_DIR"
    local output=$(timeout 10 vvp j4_sim +pass_addr="$pass_addr" +fail_addr="$fail_addr" 2>&1)

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
