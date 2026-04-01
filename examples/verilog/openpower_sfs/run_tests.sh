#!/bin/bash

# Test OpenPOWER SFS processor
# Supports both iverilog and verilator simulators
# Set SIMULATOR=verilator to use Verilator instead of Icarus Verilog

SIMULATOR=${SIMULATOR:-iverilog}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if processor exists
if [ ! -f "openpower_sfs.v" ]; then
    echo "ERROR: openpower_sfs.v not found. Generate processor first with:"
    echo "  python3 isa/openpower/generators/generate_openpower_sfs.py"
    exit 1
fi

# Compile based on simulator choice
echo "Compiling OpenPOWER SFS processor with $SIMULATOR..."

if [ "$SIMULATOR" = "verilator" ]; then
    # Verilator compilation with timing support (v5+) - only recompile if needed
    if [ ! -f "sim" ] || [ "openpower_sfs.v" -nt "sim" ] || [ "simple_tb.sv" -nt "sim" ]; then
        verilator --timing --exe --binary \
            -Wno-fatal -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-TIMESCALEMOD \
            -o sim openpower_sfs.v simple_tb.sv
        if [ $? -ne 0 ]; then
            echo "ERROR: Verilator compilation failed!"
            exit 1
        fi
        # Move binary from obj_dir and ensure it exists
        if ! mv obj_dir/sim . 2>/dev/null; then
            echo "ERROR: Failed to move Verilator sim binary from obj_dir/sim"
            exit 1
        fi
        if [ ! -x "./sim" ]; then
            echo "ERROR: Verilator sim binary './sim' not found or not executable"
            exit 1
        fi
    fi
    TEST_CMD="./sim"
else
    # Icarus Verilog compilation - recompile if source newer than binary
    if [ ! -f "sim" ] || [ "openpower_sfs.v" -nt "sim" ] || [ "simple_tb.sv" -nt "sim" ]; then
        COMPILE_OUTPUT=$(iverilog -g2012 -o sim openpower_sfs.v simple_tb.sv 2>&1)
        COMPILE_EXIT=$?

        # Only show errors, not warnings
        echo "$COMPILE_OUTPUT" | grep -i error

        if [ $COMPILE_EXIT -ne 0 ]; then
            echo "ERROR: Compilation failed"
            echo "$COMPILE_OUTPUT"
            exit 1
        fi
        echo ""
    fi
    TEST_CMD="vvp sim"
fi

TEST_DIR="../../../isa/openpower/power-tests/isa"

# Check if tests are built
if [ ! -f "$TEST_DIR/power-isacomp-simple.imem.hex" ]; then
    echo "Tests not built. Building..."
    (cd "$TEST_DIR/.." && ./build_tests.sh)
    echo ""
fi

# Create empty rf.hex (register file starts at zero)
python3 -c "
with open('rf.hex', 'w') as f:
    for i in range(32):
        f.write('0000000000000000\n')
"

PASS=0
FAIL=0
SKIP=0

# SFS-supported tests only (matches INSTRUCTIONS list in generate_openpower_sfs.py)
SFS_TESTS="add addi addis subf subfic neg mullw mulld mulli divw divwu divd divdu \
and andi andis or ori oris xor xori xoris nand nor eqv andc orc \
extsb extsh extsw slw srw sraw srawi sld srd srad sradi \
rldicl rldicr rlwinm \
lbz lbzx lhz lhzx lha lwz lwzx lwa ld ldx \
stb stbx sth sthx stw stwx std stdx \
b ba bl bla bc bcl bclr bclrl bcctr bcctrl \
cmpw cmplw cmpwi cmplwi cmpd cmpld cmpdi cmpldi \
crand cror crxor crnand crnor mcrf \
mfcr mtcrf mfspr mtspr simple sub"

# Get list of tests - filter to only SFS-supported instructions
TESTS=""
for test in $(ls "$TEST_DIR"/*.S 2>/dev/null | xargs -n1 basename | sed 's/\.S$//' | grep -v test_macros); do
    if echo " $SFS_TESTS " | grep -q " $test "; then
        TESTS="$TESTS $test"
    fi
done

for test in $TESTS; do
    echo -n "Testing $test... "

    # Check if test files exist
    IMEM_FILE="$TEST_DIR/power-isacomp-$test.imem.hex"
    DMEM_FILE="$TEST_DIR/power-isacomp-$test.dmem.hex"
    ADDR_FILE="$TEST_DIR/power-isacomp-$test.addrs"

    if [ ! -f "$IMEM_FILE" ] || [ ! -f "$DMEM_FILE" ]; then
        echo "SKIP (files not found)"
        SKIP=$((SKIP + 1))
        continue
    fi

    # Get pass/fail addresses
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
    python3 -c "
import sys
umem = {}
# Read imem (instructions at low addresses, 32-bit -> 64-bit)
# PC[2]=0 selects bits[31:0], PC[2]=1 selects bits[63:32]
# So first instruction (even index) goes to low bits, second (odd) to high bits
with open('$IMEM_FILE', 'r') as f:
    for i, line in enumerate(f):
        line = line.strip()
        if line:
            word_addr = i // 2
            if word_addr not in umem:
                umem[word_addr] = ['00000000', '00000000']  # [high, low]
            if i % 2 == 0:
                umem[word_addr][1] = line.zfill(8)  # First instr -> low bits
            else:
                umem[word_addr][0] = line.zfill(8)  # Second instr -> high bits
# Read dmem (data, already 64-bit, at address 0x10000)
with open('$DMEM_FILE', 'r') as f:
    for i, line in enumerate(f):
        line = line.strip()
        if line:
            # dmem starts at address 0x10000 (word 8192 for 64-bit)
            word_addr = 8192 + i
            umem[word_addr] = [line.zfill(16)[:8], line.zfill(16)[8:]]
# Write unified memory (high bits first, then low bits)
max_addr = max(umem.keys()) if umem else 0
with open('umem.hex', 'w') as f:
    for addr in range(max_addr + 1):
        if addr in umem:
            f.write(umem[addr][0] + umem[addr][1] + '\n')
        else:
            f.write('0000000000000000\n')
"

    # Run the test with timeout
    OUTPUT=$(timeout 10 $TEST_CMD +pass_addr="$PASS_ADDR" +fail_addr="$FAIL_ADDR" 2>&1)

    if echo "$OUTPUT" | grep -q "TEST PASSED"; then
        echo "PASS"
        PASS=$((PASS + 1))
    elif echo "$OUTPUT" | grep -q "TEST FAILED"; then
        TESTNUM=$(echo "$OUTPUT" | grep -oP 'testnum=\K\d+' || echo "?")
        echo "FAIL (test $TESTNUM)"
        FAIL=$((FAIL + 1))
    elif echo "$OUTPUT" | grep -q "TIMEOUT"; then
        PC=$(echo "$OUTPUT" | grep -oP 'pc=\K[0-9a-fA-F]+' || echo "?")
        echo "TIMEOUT (pc=$PC)"
        FAIL=$((FAIL + 1))
    else
        echo "ERROR"
        echo "$OUTPUT"
        FAIL=$((FAIL + 1))
    fi
done

# Cleanup
rm -f umem.hex

echo ""
echo "================================"
echo "Results: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
echo "================================"

if [ $FAIL -gt 0 ]; then
    exit 1
fi
exit 0
