#!/usr/bin/env python3
"""Run riscv-tests against SAIL-generated Verilog designs.

Usage:
    python run_sail_tests.py sail_rv32i.v          # run RV32I tests
    python run_sail_tests.py sail_rv32if.v         # run RV32I tests (F tests need FPU)
    python run_sail_tests.py sail_rv32if.v --all   # run RV32I + RV32F tests
"""

import os
import subprocess
import sys
import argparse
import tempfile

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
TEST_DIR = os.path.join(REPO_ROOT, 'isa/riscv32/riscv-tests/isa')

RV32I_TESTS = [
    'add', 'addi', 'sub', 'lui', 'auipc',
    'and', 'andi', 'or', 'ori', 'xor', 'xori',
    'sll', 'slli', 'srl', 'srli', 'sra', 'srai',
    'slt', 'slti', 'sltu', 'sltiu',
    'beq', 'bne', 'blt', 'bltu', 'bge', 'bgeu',
    'jal', 'jalr',
    'lw', 'lh', 'lhu', 'lb', 'lbu',
    'sw', 'sh', 'sb',
]

RV32F_TESTS = [
    'fadd', 'fclass', 'fcmp', 'fcvt', 'fcvt_w', 'fdiv', 'fmadd', 'fmin',
    'fmv', 'fsgnj', 'fsqrt', 'fsub', 'ldst', 'recoding',
]


def convert_ihex_to_mem(hex_path, imem_path, dmem_path):
    """Convert Intel HEX to word-addressed imem.hex and dmem.hex."""
    data = {}
    with open(hex_path) as f:
        for line in f:
            line = line.strip()
            if not line.startswith(':'):
                continue
            byte_count = int(line[1:3], 16)
            address = int(line[3:7], 16)
            record_type = int(line[7:9], 16)
            if record_type == 0:
                for i in range(byte_count):
                    byte_val = int(line[9 + i * 2:11 + i * 2], 16)
                    data[address + i] = byte_val
            elif record_type == 1:
                break

    if not data:
        return

    max_addr = max(data.keys())
    max_word = (max_addr // 4) + 1

    for path, size in [(imem_path, max(8192, max_word)), (dmem_path, max(1024, max_word))]:
        with open(path, 'w') as f:
            for word_idx in range(size):
                word = 0
                addr = word_idx * 4
                for byte_offset in range(4):
                    byte_addr = addr + byte_offset
                    if byte_addr in data:
                        word |= data[byte_addr] << (byte_offset * 8)
                f.write(f'{word:08x}\n')


def create_testbench(verilog_path, work_dir):
    """Create a testbench matching the processor's reset ports."""
    # Read until end of module port list to find reset ports
    with open(verilog_path) as f:
        header = ''
        for line in f:
            header += line
            if line.strip().startswith(');'):
                break

    reset_ports = []
    for line in header.splitlines():
        stripped = line.strip()
        if 'input' in stripped and 'reset_' in stripped:
            # Extract port name from "input wire [31:0] reset_foo"
            parts = stripped.rstrip(',').rstrip(')').split()
            port_name = parts[-1]
            reset_ports.append(port_name)

    port_connections = ".clk(clk),\n        .reset(reset)"
    for port in reset_ports:
        port_connections += f",\n        .{port}(zero32)"

    tb = f"""module sim_tb;
    reg clk, reset;
    wire [31:0] zero32 = 32'd0;

    processor dut (
        {port_connections}
    );

    always #5 clk = ~clk;

    reg [31:0] pass_addr, fail_addr;
    integer cycle_count;

    initial begin
        if (!$value$plusargs("pass_addr=%h", pass_addr)) pass_addr = 32'hFFFF_FFFF;
        if (!$value$plusargs("fail_addr=%h", fail_addr)) fail_addr = 32'hFFFF_FFFE;

        clk = 0; reset = 1;
        cycle_count = 0;

        $readmemh("imem.hex", dut.imem);
        $readmemh("dmem.hex", dut.dmem);

        repeat(3) @(posedge clk);
        reset = 0;

        while (cycle_count < 20000) begin
            @(posedge clk);
            cycle_count = cycle_count + 1;

            if (dut.pc_rd == pass_addr) begin
                $display("TEST PASSED");
                $finish;
            end
            if (dut.pc_rd == fail_addr) begin
                $display("TEST FAILED at pc=%h", dut.pc_rd);
                $finish;
            end
        end

        $display("TIMEOUT");
        $finish;
    end
endmodule
"""
    tb_path = os.path.join(work_dir, 'sim_tb.sv')
    with open(tb_path, 'w') as f:
        f.write(tb)
    return tb_path


def find_fpu_stub():
    """Find the cvfpu_simple stub for compilation."""
    candidates = [
        os.path.join(REPO_ROOT, 'isa/j4/j4-tests/sim/cvfpu_simple.v'),
        os.path.join(REPO_ROOT, 'isa/j4/platform/rtl/cvfpu_simple.v'),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def compile_sim(verilog_path, tb_path, sim_path, work_dir):
    """Compile Verilog design + testbench with iverilog."""
    sources = [verilog_path, tb_path]

    # Include FPU stub if design uses cvfpu_simple
    with open(verilog_path) as f:
        if 'cvfpu_simple' in f.read(10000):
            fpu_stub = find_fpu_stub()
            if fpu_stub:
                sources.append(fpu_stub)
                print(f"Including FPU stub: {fpu_stub}")
            else:
                print("Warning: design uses cvfpu_simple but stub not found")

    result = subprocess.run(
        ['iverilog', '-g2012', '-o', sim_path] + sources,
        capture_output=True, text=True, cwd=work_dir
    )
    if result.returncode != 0:
        print(f"Compilation failed:\n{result.stderr}")
        sys.exit(1)
    print(f"Compiled simulation binary: {sim_path}")


def run_tests(sim_path, work_dir, tests, test_prefix='rv32ui'):
    """Run tests and return (passed, failed, failures)."""
    passed = 0
    failed = 0
    failures = []

    for test in tests:
        hex_file = os.path.join(TEST_DIR, f'{test_prefix}-isacomp-{test}.hex')
        addrs_file = os.path.join(TEST_DIR, f'{test_prefix}-isacomp-{test}.addrs')
        if not os.path.exists(hex_file) or not os.path.exists(addrs_file):
            print(f'  {test}: SKIP (no test binary)')
            continue

        with open(addrs_file) as f:
            parts = f.read().strip().split()
            pass_addr = parts[0]
            fail_addr = parts[1]

        convert_ihex_to_mem(hex_file,
                            os.path.join(work_dir, 'imem.hex'),
                            os.path.join(work_dir, 'dmem.hex'))

        # Create init files for csr and rf (all zeros)
        for init_file, count in [('csr.hex', 4096), ('rf.hex', 32)]:
            path = os.path.join(work_dir, init_file)
            if not os.path.exists(path):
                with open(path, 'w') as f:
                    for _ in range(count):
                        f.write('00000000\n')

        try:
            result = subprocess.run(
                ['vvp', sim_path, f'+pass_addr={pass_addr}', f'+fail_addr={fail_addr}'],
                capture_output=True, text=True, timeout=10, cwd=work_dir
            )
            output = result.stdout + result.stderr

            if 'TEST PASSED' in output:
                passed += 1
                print(f'  {test}: PASS')
            elif 'TEST FAILED' in output:
                failed += 1
                failures.append(test)
                print(f'  {test}: FAIL')
            else:
                failed += 1
                failures.append(test)
                print(f'  {test}: TIMEOUT')
        except subprocess.TimeoutExpired:
            failed += 1
            failures.append(test)
            print(f'  {test}: TIMEOUT')

    return passed, failed, failures


def main():
    parser = argparse.ArgumentParser(description='Run riscv-tests against SAIL-generated Verilog')
    parser.add_argument('verilog', help='Path to generated Verilog file')
    parser.add_argument('--all', action='store_true',
                        help='Run F extension tests too (requires FPU support)')
    parser.add_argument('--work-dir', default=None,
                        help='Working directory for simulation (default: temp dir)')
    args = parser.parse_args()

    if not os.path.exists(args.verilog):
        print(f"Error: {args.verilog} not found")
        sys.exit(1)

    work_dir = args.work_dir or tempfile.mkdtemp(prefix='sail_sim_')
    os.makedirs(work_dir, exist_ok=True)

    verilog_path = os.path.abspath(args.verilog)
    sim_path = os.path.join(work_dir, 'sail_sim')

    print(f"Work directory: {work_dir}")
    tb_path = create_testbench(verilog_path, work_dir)
    compile_sim(verilog_path, tb_path, sim_path, work_dir)

    print(f"\nRunning RV32I tests ({len(RV32I_TESTS)} tests)...")
    i_pass, i_fail, i_failures = run_tests(sim_path, work_dir, RV32I_TESTS, 'rv32ui')

    total_pass = i_pass
    total_fail = i_fail
    all_failures = i_failures

    if args.all:
        print(f"\nRunning RV32F tests ({len(RV32F_TESTS)} tests)...")
        f_pass, f_fail, f_failures = run_tests(sim_path, work_dir, RV32F_TESTS, 'rv32uf')
        total_pass += f_pass
        total_fail += f_fail
        all_failures += f_failures

    print(f'\nResults: {total_pass} PASS, {total_fail} FAIL out of {total_pass + total_fail}')
    if all_failures:
        print(f'Failures: {all_failures}')
        sys.exit(1)


if __name__ == '__main__':
    main()
