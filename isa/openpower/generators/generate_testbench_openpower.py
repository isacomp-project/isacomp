#!/usr/bin/env python3
"""
Generate a testbench for an OpenPOWER pipelined processor.

This script parses the Verilog module and generates a testbench that correctly
connects all reset ports to appropriate default values.
"""

import re
import sys
import os

# Add project root to path for imports
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def parse_module_ports(verilog_file):
    """
    Parse a Verilog file to extract module name and ports.

    Returns:
        dict with 'module_name' and 'ports' (list of dicts with name, direction, width)
    """
    with open(verilog_file, 'r') as f:
        content = f.read()

    # Find module name
    module_match = re.search(r'module\s+(\w+)\s*\(', content)
    if not module_match:
        raise ValueError(f"Could not find module in {verilog_file}")
    module_name = module_match.group(1)

    # Find all port declarations
    ports = []

    # Pattern: input [63:0] name,  or input name,
    port_pattern = re.compile(r'(input|output)\s+(wire\s+|reg\s+)?(\[(\d+):(\d+)\]\s+)?(\w+)')

    for match in port_pattern.finditer(content):
        direction = match.group(1)
        msb = int(match.group(4)) if match.group(4) else 0
        lsb = int(match.group(5)) if match.group(5) else 0
        name = match.group(6)
        width = msb - lsb + 1 if msb >= lsb else lsb - msb + 1

        ports.append({
            'name': name,
            'direction': direction,
            'width': width
        })

    return {
        'module_name': module_name,
        'ports': ports
    }


def generate_testbench_openpower(verilog_file, output_file=None):
    """
    Generate a testbench for the given OpenPOWER Verilog file.
    """
    module_info = parse_module_ports(verilog_file)
    module_name = module_info['module_name']
    ports = module_info['ports']

    # Find reset ports and their widths
    reset_ports = []
    clk_port = None
    reset_port = None
    other_inputs = []

    for port in ports:
        name = port['name']
        if name == 'clk':
            clk_port = port
        elif name == 'reset':
            reset_port = port
        elif port['direction'] == 'input' and name.startswith('reset_'):
            reset_ports.append(port)
        elif port['direction'] == 'input':
            other_inputs.append(port)

    # Read the verilog file to find internal signals
    with open(verilog_file, 'r') as f:
        verilog_content = f.read()

    # Generate testbench
    tb_lines = []
    tb_lines.append('`timescale 1ns/1ps')
    tb_lines.append('module simple_tb;')
    tb_lines.append('    reg clk, reset;')
    tb_lines.append('    wire [63:0] zero64 = 64\'d0;')
    tb_lines.append('    wire [31:0] zero32 = 32\'d0;')
    tb_lines.append('    wire zero1 = 1\'b0;')
    tb_lines.append('')

    # DUT instantiation
    tb_lines.append(f'    {module_name} dut (')
    tb_lines.append('        .clk(clk),')
    tb_lines.append('        .reset(reset),')

    # Connect reset ports
    port_connections = []
    for port in reset_ports:
        if port['width'] == 1:
            port_connections.append(f"        .{port['name']}(zero1)")
        elif port['width'] <= 32:
            port_connections.append(f"        .{port['name']}(zero32)")
        else:
            port_connections.append(f"        .{port['name']}(zero64)")

    if port_connections:
        tb_lines.append(',\n'.join(port_connections))

    tb_lines.append('    );')
    tb_lines.append('')

    # Find PC pipeline register for tracking execution
    # Look for the deepest PC pipeline register (most _PIPE suffixes)
    exec_pc_signal = None
    exec_valid_signal = None

    pc_pattern = re.compile(r'reg\s+\[\d+:\d+\]\s+(PIPE_\w*pc_rd\w*_PIPE\w*)')
    all_pc_signals = pc_pattern.findall(verilog_content)

    if all_pc_signals:
        def count_pipe_depth(signal):
            return signal.count('_PIPE')

        all_pc_signals.sort(key=count_pipe_depth, reverse=True)
        exec_pc_signal = all_pc_signals[0]
        print(f"  Found {len(all_pc_signals)} PC signals, using deepest: {exec_pc_signal} (depth={count_pipe_depth(exec_pc_signal)})")

    # Find validity signal
    valid_patterns = [
        r'reg\s+(PIPE_Execute_valid_PIPE)',
        r'reg\s+(PIPE_ExecuteMemoryWriteback_valid_PIPE)',
        r'reg\s+(PIPE_MemoryWriteback_valid_PIPE)',
        r'reg\s+(PIPE_Memory_valid_PIPE)',
        r'reg\s+(PIPE_Writeback_valid_PIPE)',
        r'reg\s+(PIPE_\w+_valid_PIPE)',
    ]

    for pattern in valid_patterns:
        match = re.search(pattern, verilog_content)
        if match:
            exec_valid_signal = match.group(1)
            break

    # Test logic - use 64-bit addresses for OpenPOWER
    tb_lines.append('    reg [63:0] pass_addr, fail_addr;')
    tb_lines.append('    integer i;')
    tb_lines.append('    always #5 clk = ~clk;')
    tb_lines.append('')

    if exec_pc_signal:
        tb_lines.append(f'    wire [63:0] exec_pc = dut.{exec_pc_signal};')
    else:
        tb_lines.append('    wire [63:0] exec_pc = dut.pc_rd;  // Fallback')

    if exec_valid_signal:
        tb_lines.append(f'    wire exec_valid = dut.{exec_valid_signal};')
    else:
        tb_lines.append('    wire exec_valid = 1\'b1;  // Fallback')

    # Check if control_hazard_flush exists
    if 'control_hazard_flush' in verilog_content:
        tb_lines.append('    wire flush = dut.control_hazard_flush;')
    else:
        tb_lines.append('    wire flush = 1\'b0;')

    tb_lines.append('    wire exec_at_pass = exec_valid && (exec_pc == pass_addr);')
    tb_lines.append('    wire exec_at_fail = exec_valid && (exec_pc == fail_addr);')
    tb_lines.append('')

    tb_lines.append('    initial begin')
    tb_lines.append('        clk = 0; reset = 1;')
    tb_lines.append('        if (!$value$plusargs("pass_addr=%h", pass_addr)) pass_addr = 64\'hFFFFFFFFFFFFFFFF;')
    tb_lines.append('        if (!$value$plusargs("fail_addr=%h", fail_addr)) fail_addr = 64\'hFFFFFFFFFFFFFFFE;')
    tb_lines.append('        $readmemh("umem.hex", dut.umem);')
    tb_lines.append('        repeat(3) @(posedge clk);')
    tb_lines.append('        reset = 0;')
    tb_lines.append('        for (i = 0; i < 5000; i = i + 1) begin')
    tb_lines.append('            @(posedge clk);')
    tb_lines.append('            if (exec_at_pass) begin $display("TEST PASSED in %0d cycles", i+3); $finish; end')
    tb_lines.append('            if (exec_at_fail) begin')
    tb_lines.append('                $display("TEST FAILED at pc=%h testnum=%d", exec_pc, dut.rf[2]);')
    tb_lines.append('                $display("  r8=%h r9=%h r10=%h r25=%h", dut.rf[8], dut.rf[9], dut.rf[10], dut.rf[25]);')
    tb_lines.append('                $finish;')
    tb_lines.append('            end')
    tb_lines.append('        end')
    tb_lines.append('        $display("TIMEOUT at pc=%h", exec_pc);')
    tb_lines.append('        $finish;')
    tb_lines.append('    end')
    tb_lines.append('endmodule')

    testbench = '\n'.join(tb_lines) + '\n'

    if output_file:
        with open(output_file, 'w') as f:
            f.write(testbench)
        print(f"Generated testbench: {output_file}")
        print(f"  Module: {module_name}")
        print(f"  Reset ports: {len(reset_ports)}")
        if exec_pc_signal:
            print(f"  PC tracking: {exec_pc_signal}")
        if exec_valid_signal:
            print(f"  Valid signal: {exec_valid_signal}")
    else:
        print(testbench)

    return testbench


def generate_run_script(output_dir, module_name):
    """Generate a run script for testing the OpenPOWER processor."""
    script_content = f'''#!/bin/bash

# Test OpenPOWER SFS pipelined processor
# Supports both iverilog and verilator simulators
# Set SIMULATOR=verilator to use Verilator instead of Icarus Verilog

SIMULATOR=${{SIMULATOR:-iverilog}}

SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if processor exists
if [ ! -f "{module_name}.v" ]; then
    echo "ERROR: {module_name}.v not found."
    exit 1
fi

# Compile based on simulator choice
echo "Compiling {module_name} with $SIMULATOR..."

if [ "$SIMULATOR" = "verilator" ]; then
    # Verilator compilation with timing support (v5+) - only recompile if needed
    if [ ! -f "sim" ] || [ "{module_name}.v" -nt "sim" ] || [ "simple_tb.sv" -nt "sim" ]; then
        verilator --timing --exe --binary \\
            -Wno-fatal -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-TIMESCALEMOD \\
            -o sim {module_name}.v simple_tb.sv
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
    if [ ! -f "sim" ] || [ "{module_name}.v" -nt "sim" ] || [ "simple_tb.sv" -nt "sim" ]; then
        COMPILE_OUTPUT=$(iverilog -g2012 -o sim {module_name}.v simple_tb.sv 2>&1)
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
        f.write('0000000000000000\\n')
"

PASS=0
FAIL=0
SKIP=0

# SFS-supported tests only (matches INSTRUCTIONS list in generate_openpower_sfs.py)
SFS_TESTS="add addi addis subf subfic neg mullw mulld mulli divw divwu divd divdu \\
and andi andis or ori oris xor xori xoris nand nor eqv andc orc \\
extsb extsh extsw slw srw sraw srawi sld srd srad sradi \\
rldicl rldicr rlwinm \\
lbz lbzx lhz lhzx lha lwz lwzx lwa ld ldx \\
stb stbx sth sthx stw stwx std stdx \\
b ba bl bla bc bcl bclr bclrl bcctr bcctrl \\
cmpw cmplw cmpwi cmplwi cmpd cmpld cmpdi cmpldi \\
crand cror crxor crnand crnor mcrf \\
mfcr mtcrf mfspr mtspr simple sub"

# Get list of tests - filter to only SFS-supported instructions
TESTS=""
for test in $(ls "$TEST_DIR"/*.S 2>/dev/null | xargs -n1 basename | sed 's/\\.S$//' | grep -v test_macros); do
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

    PASS_ADDR=$(cat "$ADDR_FILE" | awk '{{print $1}}')
    FAIL_ADDR=$(cat "$ADDR_FILE" | awk '{{print $2}}')

    if [ -z "$PASS_ADDR" ] || [ -z "$FAIL_ADDR" ]; then
        echo "SKIP (no pass/fail symbols)"
        SKIP=$((SKIP + 1))
        continue
    fi

    # Merge imem and dmem into unified umem.hex (64-bit words)
    python3 -c "
import sys
umem = {{}}
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
# Write unified memory
max_addr = max(umem.keys()) if umem else 0
with open('umem.hex', 'w') as f:
    for addr in range(max_addr + 1):
        if addr in umem:
            # Little-endian: low word first
            f.write(umem[addr][0] + umem[addr][1] + '\\n')
        else:
            f.write('0000000000000000\\n')
"

    # Run the test with timeout (5s is plenty for 5000 cycle limit)
    OUTPUT=$(timeout 5 $TEST_CMD +pass_addr="$PASS_ADDR" +fail_addr="$FAIL_ADDR" 2>&1)

    if echo "$OUTPUT" | grep -q "TEST PASSED"; then
        CYCLES=$(echo "$OUTPUT" | grep -oP 'in \\K\\d+' || echo "?")
        echo "PASS ($CYCLES cycles)"
        PASS=$((PASS + 1))
    elif echo "$OUTPUT" | grep -q "TEST FAILED"; then
        TESTNUM=$(echo "$OUTPUT" | grep -oP 'testnum=\\K\\d+' || echo "?")
        echo "FAIL (test $TESTNUM)"
        FAIL=$((FAIL + 1))
    elif echo "$OUTPUT" | grep -q "TIMEOUT"; then
        PC=$(echo "$OUTPUT" | grep -oP 'pc=\\K[0-9a-fA-F]+' || echo "?")
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
'''
    script_path = os.path.join(output_dir, "run_tests.sh")
    with open(script_path, 'w') as f:
        f.write(script_content)
    os.chmod(script_path, 0o755)
    print(f"Generated run script: {script_path}")
    return script_path


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python generate_testbench_openpower.py <verilog_file> [output_file]")
        sys.exit(1)

    verilog_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    generate_testbench_openpower(verilog_file, output_file)
