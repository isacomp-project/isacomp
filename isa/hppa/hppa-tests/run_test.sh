#!/bin/bash
# Run HPPA ISA tests with iverilog simulation

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ISA_DIR="$SCRIPT_DIR/isa"
VERILOG_DIR="$SCRIPT_DIR/../../../examples/verilog/hppa"
TESTBENCH="$SCRIPT_DIR/hppa_tb_simple.sv"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Convert ELF to hex format suitable for $readmemh
# Format: one 32-bit word per line in hex, word-addressed
elf_to_hex() {
    local elf_file=$1
    local hex_file=$2

    # Use objcopy to get binary, then convert to hex words
    local bin_file=$(mktemp)
    hppa-linux-gnu-objcopy -O binary "$elf_file" "$bin_file"

    # Convert binary to hex words (big-endian, 32-bit)
    xxd -g 4 -c 4 "$bin_file" | awk '{print $2}' > "$hex_file"

    rm -f "$bin_file"
}

# Get symbol address from ELF
get_symbol_addr() {
    local elf_file=$1
    local symbol=$2
    hppa-linux-gnu-nm "$elf_file" | grep " $symbol$" | awk '{print $1}'
}

# Compile a test
compile_test() {
    local test_name=$1
    local test_file="$ISA_DIR/${test_name}.S"
    local elf_file="$ISA_DIR/${test_name}.elf"
    local intermediate_file="$ISA_DIR/${test_name}.i"
    local obj_file="$ISA_DIR/${test_name}.o"

    if [[ ! -f "$test_file" ]]; then
        echo -e "${RED}Test file not found: $test_file${NC}"
        return 1
    fi

    echo "Compiling $test_name..."

    # Preprocess
    hppa-linux-gnu-gcc -E -I "$ISA_DIR" "$test_file" -o "$intermediate_file" 2>/dev/null

    # Convert semicolons to newlines (HPPA assembler doesn't support ; as separator)
    sed -i 's/;/\n/g' "$intermediate_file"

    # Assemble
    hppa-linux-gnu-as -o "$obj_file" "$intermediate_file" 2>/dev/null

    # Link
    hppa-linux-gnu-ld -T "$ISA_DIR/link.ld" -o "$elf_file" "$obj_file" 2>/dev/null

    # Cleanup intermediate files
    rm -f "$intermediate_file" "$obj_file"

    return 0
}

# Run a test
run_test() {
    local test_name=$1
    local elf_file="$ISA_DIR/${test_name}.elf"
    local hex_file="program.hex"

    if [[ ! -f "$elf_file" ]]; then
        echo -e "${RED}ELF file not found: $elf_file${NC}"
        return 1
    fi

    # Convert ELF to hex
    elf_to_hex "$elf_file" "$hex_file"

    # Also create umem.hex for generated Verilog's $readmemh
    cp "$hex_file" "umem.hex"

    # Get pass/fail addresses
    local pass_addr=$(get_symbol_addr "$elf_file" "pass")
    local fail_addr=$(get_symbol_addr "$elf_file" "fail")

    if [[ -z "$pass_addr" ]] || [[ -z "$fail_addr" ]]; then
        echo -e "${YELLOW}Warning: Could not find pass/fail symbols, using defaults${NC}"
        pass_addr="00000024"
        fail_addr="0000002c"
    fi

    echo "  Pass addr: 0x$pass_addr"
    echo "  Fail addr: 0x$fail_addr"

    # Run simulation
    echo "Running simulation for $test_name..."
    local sim_output=$(vvp -n hppa_sim +pass_addr=$pass_addr +fail_addr=$fail_addr 2>&1)

    if echo "$sim_output" | grep -q "TEST PASSED"; then
        echo -e "${GREEN}  PASSED${NC}"
        return 0
    else
        echo -e "${RED}  FAILED${NC}"
        echo "$sim_output"
        return 1
    fi
}

# Compile the Verilog design
compile_verilog() {
    echo "Compiling Verilog design..."
    # Include FPU stub for testing (full FPU not needed for integer tests)
    iverilog -g2012 -o hppa_sim \
        "$SCRIPT_DIR/../../../vendor/cvfpu_stub.sv" \
        "$VERILOG_DIR/hppa.v" \
        "$TESTBENCH"
}

# Main
main() {
    local tests=("$@")

    if [[ ${#tests[@]} -eq 0 ]]; then
        tests=(simple_test)
    fi

    # Compile Verilog first
    compile_verilog

    local passed=0
    local failed=0

    for test in "${tests[@]}"; do
        echo ""
        echo "========================================"
        echo "Test: $test"
        echo "========================================"

        if compile_test "$test"; then
            if run_test "$test"; then
                ((passed++))
            else
                ((failed++))
            fi
        else
            ((failed++))
        fi
    done

    echo ""
    echo "========================================"
    echo "Summary: $passed passed, $failed failed"
    echo "========================================"

    if [[ $failed -gt 0 ]]; then
        exit 1
    fi
}

cd "$SCRIPT_DIR"
main "$@"
