"""
CIRCT Testbench Generator

Generates testbenches and test runner scripts for CIRCT-generated processors.
Parses the generated SystemVerilog to extract actual signal names (which have
numeric suffixes from MLIR SSA generation).
"""

import re
from pathlib import Path
from typing import Dict


class CIRCTTestbenchGenerator:
    """Generate testbenches for CIRCT-generated processors."""

    def __init__(self, sv_file: str, module_name: str, arch: str):
        """
        Initialize testbench generator.

        Args:
            sv_file: Path to the generated SystemVerilog file
            module_name: Name of the processor module
            arch: Architecture type ('mips32', 'riscv32', 'riscv64')
        """
        self.sv_file = Path(sv_file)
        self.module_name = module_name
        self.arch = arch.lower()
        self.output_dir = self.sv_file.parent

        # Architecture-specific settings
        self.arch_config = self._get_arch_config()

        # Parse signal names from SystemVerilog
        self.signal_names = self._parse_signal_names()

    def _get_arch_config(self) -> Dict:
        """Get architecture-specific configuration."""
        configs = {
            'mips32': {
                'data_width': 32,
                'testnum_reg': 2,      # $2 ($v0) holds test number
                'test_dir': 'isa/mips32/mips-tests/isa',
                'test_prefix': 'mips32-isacomp-',
                'imem_width': 32,
                'dmem_width': 32,
                'imem_depth': 2048,
                'dmem_depth': 8192,
                'timeout_cycles': 50000,
            },
            'riscv32': {
                'data_width': 32,
                'testnum_reg': 28,     # x28 holds test number
                'test_dir': 'isa/riscv32/riscv-tests/isa',
                'test_prefix': 'rv32ui-isacomp-',
                'imem_width': 32,
                'dmem_width': 32,
                'imem_depth': 2048,
                'dmem_depth': 2048,
                'timeout_cycles': 100000,
            },
            'riscv64': {
                'data_width': 64,
                'testnum_reg': 28,     # x28 holds test number
                'test_dir': 'isa/riscv64/riscv-tests/isa',
                'test_prefix': 'rv64ui-isacomp-',
                'imem_width': 32,
                'dmem_width': 64,
                'imem_depth': 2048,
                'dmem_depth': 2048,
                'timeout_cycles': 100000,
            },
        }
        return configs.get(self.arch, configs['riscv32'])

    def _parse_signal_names(self) -> Dict[str, str]:
        """
        Parse the generated SystemVerilog to find actual signal names.

        CIRCT generates names with numeric suffixes (e.g., pc_rd_55, rf_reg_28_49).
        We need to find these actual names.

        For pipelined designs, also finds Execute stage PC and validity signals.
        """
        signals = {}

        if not self.sv_file.exists():
            return signals

        content = self.sv_file.read_text()

        # Find PC read signal: pc_rd_N
        pc_match = re.search(r'\breg\s+\[\d+:0\]\s+(pc_rd_\d+)\s*;', content)
        if pc_match:
            signals['pc'] = pc_match.group(1)

        # Find register file signals: rf_reg_N_M
        # We want the testnum register (reg 2 for MIPS, reg 28 for RISC-V)
        testnum_reg = self.arch_config['testnum_reg']
        rf_pattern = rf'\breg\s+\[\d+:0\]\s+(rf_reg_{testnum_reg}_\d+)\s*;'
        rf_match = re.search(rf_pattern, content)
        if rf_match:
            signals['testnum'] = rf_match.group(1)

        # Check for pipelined design signals
        # Execute stage PC: PIPE_Execute_PIPE_Decode_pc_rd_PIPE_PIPE_N or similar
        # Also handles combined stages like PIPE_ExecuteMemoryWriteback for 3-stage
        exec_pc_match = re.search(r'\breg\s+\[\d+:0\]\s+(PIPE_Execute[A-Za-z]*[_A-Za-z]*pc_rd[_A-Za-z]*_\d+)\s*;', content)
        if exec_pc_match:
            signals['exec_pc'] = exec_pc_match.group(1)
            signals['is_pipelined'] = True

        # Execute stage validity: PIPE_Execute_valid_PIPE_N or PIPE_ExecuteMemoryWriteback_valid_PIPE_N
        exec_valid_match = re.search(r'\breg\s+(PIPE_Execute[A-Za-z]*_valid_PIPE_\d+)\s*;', content)
        if exec_valid_match:
            signals['exec_valid'] = exec_valid_match.group(1)

        return signals

    def generate_testbench(self) -> str:
        """Generate SystemVerilog testbench content."""
        cfg = self.arch_config
        width = cfg['data_width']

        # Get signal names (with fallbacks if not found)
        pc_signal = self.signal_names.get('pc', 'pc_rd')
        testnum_signal = self.signal_names.get('testnum', f"rf_reg_{cfg['testnum_reg']}")

        # Check if this is a pipelined design
        is_pipelined = self.signal_names.get('is_pipelined', False)
        exec_pc_signal = self.signal_names.get('exec_pc')
        exec_valid_signal = self.signal_names.get('exec_valid')

        if is_pipelined and exec_pc_signal and exec_valid_signal:
            # Pipelined design: check Execute PC with validity
            testbench = f"""`timescale 1ns/1ps
module simple_tb;
    reg clk, reset;

    {self.module_name} dut (
        .clk_0(clk),
        .reset_1(reset)
    );

    reg [{width-1}:0] pass_addr, fail_addr;
    integer i;
    always #5 clk = ~clk;

    // For pipelined designs: check Execute PC with validity, not Fetch PC
    wire [{width-1}:0] exec_pc = dut.{exec_pc_signal};
    wire exec_valid = dut.{exec_valid_signal};
    wire [{width-1}:0] testnum = dut.{testnum_signal};

    initial begin
        clk = 0; reset = 1;
        if (!$value$plusargs("pass_addr=%h", pass_addr)) pass_addr = {width}'h{"F" * (width // 4)};
        if (!$value$plusargs("fail_addr=%h", fail_addr)) fail_addr = {width}'h{"F" * (width // 4 - 1)}E;
        $readmemh("umem.hex", dut.umem);
        repeat(3) @(posedge clk);
        reset = 0;
        for (i = 0; i < {cfg['timeout_cycles']}; i = i + 1) begin
            @(posedge clk);
            // Pipelined: check Execute PC with validity for correct behavior
            if (exec_valid && exec_pc == pass_addr) begin $display("TEST PASSED"); $finish; end
            if (exec_valid && exec_pc == fail_addr) begin $display("TEST FAILED at pc=%h testnum=%d", exec_pc, testnum); $finish; end
        end
        $display("TIMEOUT");
        $finish;
    end
endmodule
"""
        else:
            # Single-cycle design: check PC directly
            testbench = f"""`timescale 1ns/1ps
module simple_tb;
    reg clk, reset;

    {self.module_name} dut (
        .clk_0(clk),
        .reset_1(reset)
    );

    reg [{width-1}:0] pass_addr, fail_addr;
    integer i;
    always #5 clk = ~clk;

    // Get the PC value using hierarchical access
    // The actual signal name is generated by CIRCT
    wire [{width-1}:0] pc_value = dut.{pc_signal};
    wire [{width-1}:0] testnum = dut.{testnum_signal};

    initial begin
        clk = 0; reset = 1;
        if (!$value$plusargs("pass_addr=%h", pass_addr)) pass_addr = {width}'h{"F" * (width // 4)};
        if (!$value$plusargs("fail_addr=%h", fail_addr)) fail_addr = {width}'h{"F" * (width // 4 - 1)}E;
        $readmemh("umem.hex", dut.umem);
        repeat(3) @(posedge clk);
        reset = 0;
        for (i = 0; i < {cfg['timeout_cycles']}; i = i + 1) begin
            @(posedge clk);
            // Single-cycle: PC updates every cycle, check directly
            if (pc_value == pass_addr) begin $display("TEST PASSED"); $finish; end
            if (pc_value == fail_addr) begin $display("TEST FAILED at pc=%h testnum=%d", pc_value, testnum); $finish; end
        end
        $display("TIMEOUT");
        $finish;
    end
endmodule
"""
        return testbench

    def generate_test_runner(self, instructions: list) -> str:
        """Generate bash test runner script."""
        cfg = self.arch_config
        tests_str = ' '.join(instructions)

        # Python hex converter code - architecture-specific
        if cfg['dmem_width'] == 64:
            # RV64I: imem is 32-bit, dmem is 64-bit
            hex_converter = self._generate_hex_converter_64bit()
        else:
            # MIPS32, RV32I: both are 32-bit
            hex_converter = self._generate_hex_converter_32bit()

        script = f"""#!/bin/bash

# Test all {self.arch.upper()} instructions using simple_tb with hex files
# This uses the CIRCT-generated processor

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/../.."
TEST_DIR="$REPO_ROOT/{cfg['test_dir']}"

# Check if processor exists
if [ ! -f "$SCRIPT_DIR/{self.module_name}.sv" ]; then
    echo "ERROR: Processor not found at $SCRIPT_DIR/{self.module_name}.sv"
    echo "Run the appropriate generator with --backend circt"
    exit 1
fi

echo "Compiling simple testbench with Verilator..."
cd "$SCRIPT_DIR"
verilator --binary -j 0 -o test_simple --top-module simple_tb \\
    -Wno-WIDTHEXPAND -Wno-WIDTHTRUNC -Wno-UNOPTFLAT -Wno-CASEINCOMPLETE -Wno-TIMESCALEMOD \\
    --timing {self.module_name}.sv simple_tb.sv 2>&1
if [ $? -ne 0 ]; then
    echo "ERROR: Compilation failed!"
    exit 1
fi
# Verilator outputs to obj_dir by default
TEST_BINARY="obj_dir/test_simple"

TESTS="{tests_str}"

PASS=0
FAIL=0
SKIP=0

for test in $TESTS; do
    echo -n "Testing $test... "

    HEX_FILE="$TEST_DIR/{cfg['test_prefix']}$test.hex"
    ADDR_FILE="$TEST_DIR/{cfg['test_prefix']}$test.addrs"

    if [ ! -f "$HEX_FILE" ]; then
        echo "SKIP (no hex file)"
        SKIP=$((SKIP + 1))
        continue
    fi

    if [ ! -f "$ADDR_FILE" ]; then
        echo "SKIP (no addr file)"
        SKIP=$((SKIP + 1))
        continue
    fi

    # Read pass/fail addresses from the .addrs file
    read PASS_ADDR FAIL_ADDR < "$ADDR_FILE"

    if [ -z "$PASS_ADDR" ] || [ -z "$FAIL_ADDR" ]; then
        echo "SKIP (no pass/fail symbols)"
        SKIP=$((SKIP + 1))
        continue
    fi

    # Convert Intel HEX file to one-word-per-line format for $readmemh
{hex_converter}

    # Run test
    RESULT=$(timeout 10 $TEST_BINARY +pass_addr=$PASS_ADDR +fail_addr=$FAIL_ADDR 2>&1)
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
echo "================================"
echo "Results: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
echo "================================"

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
"""
        return script

    def _generate_hex_converter_32bit(self) -> str:
        """Generate Python code to convert Intel HEX to 32-bit word format."""
        cfg = self.arch_config
        return f"""    python3 -c "
import sys

# Parse Intel HEX format
mem = {{}}

with open('$HEX_FILE', 'r') as f:
    for line in f:
        line = line.strip()
        if not line.startswith(':'):
            continue
        byte_count = int(line[1:3], 16)
        address = int(line[3:7], 16)
        record_type = int(line[7:9], 16)

        if record_type == 0:  # Data record
            data = line[9:9+byte_count*2]
            for i in range(0, len(data), 2):
                byte_addr = address + i // 2
                mem[byte_addr] = int(data[i:i+2], 16)
        elif record_type == 1:  # EOF
            break

if not mem:
    sys.exit(0)

# Write hex files - one 32-bit word per line (little-endian)
for fname, size in [('imem.hex', {cfg['imem_depth']}), ('dmem.hex', {cfg['dmem_depth']})]:
    with open(fname, 'w') as f:
        for word_addr in range(size):
            byte0 = mem.get(word_addr * 4 + 0, 0)
            byte1 = mem.get(word_addr * 4 + 1, 0)
            byte2 = mem.get(word_addr * 4 + 2, 0)
            byte3 = mem.get(word_addr * 4 + 3, 0)
            word = byte0 | (byte1 << 8) | (byte2 << 16) | (byte3 << 24)
            f.write(f'{{word:08X}}\\n')
" """

    def _generate_hex_converter_64bit(self) -> str:
        """Generate Python code to convert Intel HEX to 32-bit imem and 64-bit dmem."""
        cfg = self.arch_config
        return f"""    python3 -c "
import sys

# Parse Intel HEX format
mem = {{}}

with open('$HEX_FILE', 'r') as f:
    for line in f:
        line = line.strip()
        if not line.startswith(':'):
            continue
        byte_count = int(line[1:3], 16)
        address = int(line[3:7], 16)
        record_type = int(line[7:9], 16)

        if record_type == 0:  # Data record
            data = line[9:9+byte_count*2]
            for i in range(0, len(data), 2):
                byte_addr = address + i // 2
                mem[byte_addr] = int(data[i:i+2], 16)
        elif record_type == 1:  # EOF
            break

if not mem:
    sys.exit(0)

# Write imem.hex - 32-bit words (little-endian)
with open('imem.hex', 'w') as f:
    for word_addr in range({cfg['imem_depth']}):
        byte0 = mem.get(word_addr * 4 + 0, 0)
        byte1 = mem.get(word_addr * 4 + 1, 0)
        byte2 = mem.get(word_addr * 4 + 2, 0)
        byte3 = mem.get(word_addr * 4 + 3, 0)
        word = byte0 | (byte1 << 8) | (byte2 << 16) | (byte3 << 24)
        f.write(f'{{word:08X}}\\n')

# Write dmem.hex - 64-bit words (little-endian)
with open('dmem.hex', 'w') as f:
    for dword_addr in range({cfg['dmem_depth']}):
        byte0 = mem.get(dword_addr * 8 + 0, 0)
        byte1 = mem.get(dword_addr * 8 + 1, 0)
        byte2 = mem.get(dword_addr * 8 + 2, 0)
        byte3 = mem.get(dword_addr * 8 + 3, 0)
        byte4 = mem.get(dword_addr * 8 + 4, 0)
        byte5 = mem.get(dword_addr * 8 + 5, 0)
        byte6 = mem.get(dword_addr * 8 + 6, 0)
        byte7 = mem.get(dword_addr * 8 + 7, 0)
        dword = byte0 | (byte1 << 8) | (byte2 << 16) | (byte3 << 24) | \\
                (byte4 << 32) | (byte5 << 40) | (byte6 << 48) | (byte7 << 56)
        f.write(f'{{dword:016X}}\\n')
" """

    def write_files(self, instructions: list) -> Dict[str, str]:
        """
        Write testbench and test runner files.

        Args:
            instructions: List of instruction names for the test runner

        Returns:
            Dictionary of generated file paths
        """
        files = {}

        # Write testbench
        tb_file = self.output_dir / 'simple_tb.sv'
        tb_content = self.generate_testbench()
        tb_file.write_text(tb_content)
        files['testbench'] = str(tb_file)

        # Write test runner
        runner_file = self.output_dir / 'run_all_tests.sh'
        runner_content = self.generate_test_runner(instructions)
        runner_file.write_text(runner_content)
        runner_file.chmod(0o755)
        files['test_runner'] = str(runner_file)

        return files


def generate_circt_testbench(
    sv_file: str,
    module_name: str,
    arch: str,
    instructions: list
) -> Dict[str, str]:
    """
    Generate CIRCT testbench and test runner.

    Args:
        sv_file: Path to the generated SystemVerilog file
        module_name: Name of the processor module
        arch: Architecture type ('mips32', 'riscv32', 'riscv64')
        instructions: List of instruction names

    Returns:
        Dictionary of generated file paths
    """
    generator = CIRCTTestbenchGenerator(sv_file, module_name, arch)
    return generator.write_files(instructions)
