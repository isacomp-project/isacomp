#!/usr/bin/env python3
"""
Test runner for merged M68K CPU using SingleStepTests JSON format.
Uses a pre-generated merged Verilog design instead of per-instruction generation.
"""

import json
import sys
import os
import subprocess
import re
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def extract_ccr_flags(sr):
    """Extract CCR flags from status register."""
    return {
        'C': (sr >> 0) & 1,
        'V': (sr >> 1) & 1,
        'Z': (sr >> 2) & 1,
        'N': (sr >> 3) & 1,
        'X': (sr >> 4) & 1,
    }


def parse_module_interface(verilog_file):
    """Parse the module interface from Verilog file to understand port names."""
    ports = {}
    regs = {}

    with open(verilog_file, 'r') as f:
        content = f.read()

    # Find input ports
    for match in re.finditer(r'input\s+wire\s+(\[[\d:]+\])?\s*(\w+)', content):
        width = match.group(1) or ''
        name = match.group(2)
        ports[name] = {'type': 'input', 'width': width}

    # Find internal registers
    for match in re.finditer(r'reg\s+(\[[\d:]+\])?\s*(\w+)\s*(\[[\d:]+\])?', content):
        width = match.group(1) or ''
        name = match.group(2)
        array = match.group(3) or ''
        regs[name] = {'width': width, 'array': array}

    return ports, regs


def generate_testbench(test, module_name, verilog_file, output_file):
    """Generate a SystemVerilog testbench for a single M68000 test."""

    # Parse module interface to understand naming
    ports, regs = parse_module_interface(verilog_file)

    # Determine PC register name
    pc_reg = 'pc_rd' if 'pc_rd' in regs else 'pc'

    # Determine flag register names
    flag_X_reg = 'flag_X_rd' if 'flag_X_rd' in regs else 'flag_X'
    flag_N_reg = 'flag_N' if 'flag_N' in regs else 'flag_N_rd'
    flag_Z_reg = 'flag_Z' if 'flag_Z' in regs else 'flag_Z_rd'
    flag_V_reg = 'flag_V_rd' if 'flag_V_rd' in regs else 'flag_V'
    flag_C_reg = 'flag_C' if 'flag_C' in regs else 'flag_C_rd'

    # Determine reset port names
    reset_pc_port = 'reset_pc_rd' if 'reset_pc_rd' in ports else 'reset_pc'
    reset_X_port = 'reset_flag_X_rd' if 'reset_flag_X_rd' in ports else 'reset_flag_X'
    reset_N_port = 'reset_flag_N' if 'reset_flag_N' in ports else 'reset_flag_N_rd'
    reset_Z_port = 'reset_flag_Z' if 'reset_flag_Z' in ports else 'reset_flag_Z_rd'
    reset_V_port = 'reset_flag_V_rd' if 'reset_flag_V_rd' in ports else 'reset_flag_V'
    reset_C_port = 'reset_flag_C' if 'reset_flag_C' in ports else 'reset_flag_C_rd'

    # Check dmem width - support 16-bit word and 32-bit dword addressed
    dmem_info = regs.get('dmem', {})
    dmem_width_str = dmem_info.get('width', '')
    dmem_is_word = '[15:0]' in dmem_width_str
    dmem_is_dword = '[31:0]' in dmem_width_str

    # Extract initial and final state
    init_state = test['initial']
    final_state = test['final']

    # Extract initial flag values from SR
    init_sr = init_state.get('sr', 0)
    init_ccr = extract_ccr_flags(init_sr)

    # Extract final expected values
    final_sr = final_state.get('sr', 0)
    final_ccr = extract_ccr_flags(final_sr)

    # Reset value declarations
    reset_decls = f"""    reg [31:0] reset_pc;
    reg reset_flag_X;
    reg reset_flag_N;
    reg reset_flag_Z;
    reg reset_flag_V;
    reg reset_flag_C;"""

    # Build DUT port connections
    dut_ports = f"""        .clk(clk),
        .reset(reset),
        .{reset_pc_port}(reset_pc),
        .{reset_X_port}(reset_flag_X),
        .{reset_N_port}(reset_flag_N),
        .{reset_Z_port}(reset_flag_Z),
        .{reset_V_port}(reset_flag_V),
        .{reset_C_port}(reset_flag_C)"""

    # Build instruction and data memory loading from RAM
    mem_loads = ""

    # M68000 uses prefetch
    pc = init_state.get('pc', 0)
    prefetch = init_state.get('prefetch', [])

    if prefetch:
        instr_start = pc - 2 * len(prefetch)
        for i, word in enumerate(prefetch):
            # Generated Verilog uses byte address for imem (imem[pc_rd])
            byte_addr = (instr_start + i * 2) & 0xFFFFFF
            mem_loads += f"        dut.imem[24'h{byte_addr:06X}] = 16'h{word:04X};\n"

    # Load dmem
    if dmem_is_dword:
        # 32-bit dword-addressed dmem - group 4 bytes into dwords
        # For big-endian M68K with the byte mux transform:
        #   halfword_select = addr[1]
        #   sel_0 = (halfword_select == 0) selects slice_31_16 (upper half)
        #   sel_1 = (halfword_select == 1) selects slice_15_0 (lower half)
        # So for aligned address (addr[1]=0), we get upper half -> bytes 0-1
        # And for addr+2 (addr[1]=1), we get lower half -> bytes 2-3
        # Pack: bytes 0-1 in [31:16], bytes 2-3 in [15:0]
        byte_data = {}
        for addr, val in init_state.get('ram', []):
            byte_data[addr & 0xFFFFFF] = val

        dword_addrs = set(a >> 2 for a in byte_data.keys())
        for dword_addr in sorted(dword_addrs):
            byte0 = byte_data.get(dword_addr * 4, 0)
            byte1 = byte_data.get(dword_addr * 4 + 1, 0)
            byte2 = byte_data.get(dword_addr * 4 + 2, 0)
            byte3 = byte_data.get(dword_addr * 4 + 3, 0)
            # Big-endian: bytes 0-1 go in upper half, bytes 2-3 in lower half
            word0 = (byte0 << 8) | byte1  # bytes at offset 0-1 (high word)
            word1 = (byte2 << 8) | byte3  # bytes at offset 2-3 (low word)
            dword = (word0 << 16) | word1  # high word in [31:16], low word in [15:0]
            mem_loads += f"        dut.dmem[24'h{dword_addr:06X}] = 32'h{dword:08X};\n"
    elif dmem_is_word:
        # 16-bit word-addressed dmem - group bytes into words
        byte_data = {}
        for addr, val in init_state.get('ram', []):
            byte_data[addr & 0xFFFFFF] = val

        # Convert to words (big-endian)
        word_addrs = set(a >> 1 for a in byte_data.keys())
        for word_addr in sorted(word_addrs):
            byte0 = byte_data.get(word_addr * 2, 0)
            byte1 = byte_data.get(word_addr * 2 + 1, 0)
            word = (byte0 << 8) | byte1
            mem_loads += f"        dut.dmem[24'h{word_addr:06X}] = 16'h{word:04X};\n"
    else:
        # Byte-addressed dmem
        for addr, val in init_state.get('ram', []):
            wrapped_addr = addr & 0xFFFFFF
            mem_loads += f"        dut.dmem[24'h{wrapped_addr:06X}] = 8'h{val:02X};\n"

    # Build data register initialization
    dreg_init_code = ""
    for i in range(8):
        val = init_state.get(f'd{i}', 0)
        dreg_init_code += f"        dut.dregs[{i}] = 32'h{val:08X};\n"

    # Build address register initialization
    areg_init_code = ""
    for i in range(7):
        val = init_state.get(f'a{i}', 0)
        areg_init_code += f"        dut.aregs[{i}] = 32'h{val:08X};\n"

    # A7 - use USP/SSP based on supervisor mode
    sr = init_state.get('sr', 0)
    is_supervisor = (sr >> 13) & 1
    a7_val = init_state.get('ssp' if is_supervisor else 'usp', 0)
    areg_init_code += f"        dut.aregs[7] = 32'h{a7_val:08X};\n"

    # Build flag reset assignments
    flag_reset_code = f"""reset_flag_X = 1'b{init_ccr['X']};
        reset_flag_N = 1'b{init_ccr['N']};
        reset_flag_Z = 1'b{init_ccr['Z']};
        reset_flag_V = 1'b{init_ccr['V']};
        reset_flag_C = 1'b{init_ccr['C']};"""

    # Calculate instruction start PC
    instr_start_pc = pc - 2 * len(prefetch)

    # Expected final PC
    final_pc = final_state.get('pc', pc)
    expected_final_pc = final_pc - 2 * len(prefetch)

    # Build verification code
    verify_code = f"""
        // Verify PC
        if (dut.{pc_reg} !== 32'h{expected_final_pc:08X}) begin
            $display("ERROR: PC mismatch!");
            $display("  Got:      0x%08X", dut.{pc_reg});
            $display("  Expected: 0x{expected_final_pc:08X}");
            errors = errors + 1;
        end
"""

    # Verify data registers
    for i in range(8):
        expected = final_state.get(f'd{i}', init_state.get(f'd{i}', 0))
        verify_code += f"""
        if (dut.dregs[{i}] !== 32'h{expected:08X}) begin
            $display("ERROR: D{i} mismatch! Got %08X, expected {expected:08X}", dut.dregs[{i}]);
            errors = errors + 1;
        end
"""

    # Verify address registers (0-6)
    for i in range(7):
        expected = final_state.get(f'a{i}', init_state.get(f'a{i}', 0))
        verify_code += f"""
        if (dut.aregs[{i}] !== 32'h{expected:08X}) begin
            $display("ERROR: A{i} mismatch! Got %08X, expected {expected:08X}", dut.aregs[{i}]);
            errors = errors + 1;
        end
"""

    # Verify flags
    verify_code += f"""
        if (dut.{flag_X_reg} !== 1'b{final_ccr['X']}) begin
            $display("ERROR: X flag mismatch! Got %b, expected {final_ccr['X']}", dut.{flag_X_reg});
            errors = errors + 1;
        end
        if (dut.{flag_N_reg} !== 1'b{final_ccr['N']}) begin
            $display("ERROR: N flag mismatch! Got %b, expected {final_ccr['N']}", dut.{flag_N_reg});
            errors = errors + 1;
        end
        if (dut.{flag_Z_reg} !== 1'b{final_ccr['Z']}) begin
            $display("ERROR: Z flag mismatch! Got %b, expected {final_ccr['Z']}", dut.{flag_Z_reg});
            errors = errors + 1;
        end
        if (dut.{flag_V_reg} !== 1'b{final_ccr['V']}) begin
            $display("ERROR: V flag mismatch! Got %b, expected {final_ccr['V']}", dut.{flag_V_reg});
            errors = errors + 1;
        end
        if (dut.{flag_C_reg} !== 1'b{final_ccr['C']}) begin
            $display("ERROR: C flag mismatch! Got %b, expected {final_ccr['C']}", dut.{flag_C_reg});
            errors = errors + 1;
        end
"""

    # Build display code
    display_init = f"""
        $display("Initial State:");
        $display("  PC: %08Xh", dut.{pc_reg});
        $display("  D0-D3: %08X %08X %08X %08X", dut.dregs[0], dut.dregs[1], dut.dregs[2], dut.dregs[3]);
        $display("  D4-D7: %08X %08X %08X %08X", dut.dregs[4], dut.dregs[5], dut.dregs[6], dut.dregs[7]);
"""

    display_final = f"""
        $display("Final State:");
        $display("  PC: %08Xh (expected %08Xh)", dut.{pc_reg}, 32'h{expected_final_pc:08X});
        $display("  D0-D3: %08X %08X %08X %08X", dut.dregs[0], dut.dregs[1], dut.dregs[2], dut.dregs[3]);
        $display("  D4-D7: %08X %08X %08X %08X", dut.dregs[4], dut.dregs[5], dut.dregs[6], dut.dregs[7]);
"""

    # Generate testbench
    testbench = f'''`timescale 1ns/1ps

module {module_name}_tb;
    // Clock and reset
    reg clk;
    reg reset;

    // Reset value inputs
{reset_decls}

    // Error counter
    integer errors;
    integer cycles;

    // Instantiate DUT
    {module_name} dut (
{dut_ports}
    );

    // Clock generation
    initial clk = 0;
    always #5 clk = ~clk;

    // Main test sequence
    initial begin
        $dumpfile("{module_name}_tb.vcd");
        $dumpvars(0, {module_name}_tb);

        errors = 0;
        cycles = 0;

        $display("========================================");
        $display("Test: {test['name']}");
        $display("========================================");

        // Initialize memories BEFORE reset
{mem_loads}
        // Initialize data registers
{dreg_init_code}
        // Initialize address registers
{areg_init_code}
        // Set PC to instruction start
        reset_pc = 32'h{instr_start_pc:08X};

        // Set initial flags
        {flag_reset_code}

{display_init}

        // Apply reset
        $display("Applying reset...");
        reset = 1;
        @(posedge clk);
        @(posedge clk);
        reset = 0;

        // Debug: show instruction decode
        #1;
        $display("  DEBUG: PC=%08X, instr=%04X", dut.{pc_reg}, dut.instr);
        $display("  DEBUG: add_l_an_predec_dn_enable=%b", dut.add_l_an_predec_dn_enable);
        $display("  DEBUG: dregs_write_enable=%b, addr=%0d, data=%08X",
                 dut.dregs_write_enable, dut.dregs_write_addr_mux, dut.dregs_write_data_mux);
        $display("  DEBUG: aregs_write_enable=%b, addr=%0d, data=%08X",
                 dut.aregs_write_enable, dut.aregs_write_addr_mux, dut.aregs_write_data_mux);
        $display("  DEBUG: dmem_addr_rd_addr_mux=%08X", dut.dmem_addr_rd_addr_mux);

        // Wait for instruction to complete
        @(posedge clk);
        #1;  // Allow non-blocking assignments to resolve
        cycles = cycles + 1;

        $display("  Instruction completed after %0d cycle(s)", cycles);

{display_final}

        // Verify results
{verify_code}

        // Final status
        $display("");
        $display("========================================");
        if (errors == 0) begin
            $display("TEST PASSED");
            $finish(0);
        end else begin
            $display("TEST FAILED (%0d errors)", errors);
            $finish(1);
        end
    end

    // Timeout
    initial begin
        #10000;
        $display("TIMEOUT!");
        $finish(2);
    end

endmodule
'''

    with open(output_file, 'w') as f:
        f.write(testbench)


def load_tests(test_file):
    """Load tests from JSON file."""
    with open(test_file, 'r') as f:
        return json.load(f)


def main():
    print("M68000 Merged CPU Test Runner")
    print("=" * 60)

    if len(sys.argv) < 3:
        print("Usage: python3 run_merged_m68k_test.py <merged_verilog.v> <test_file.json> [test_index]")
        sys.exit(1)

    verilog_file = Path(sys.argv[1])
    test_file = Path(sys.argv[2])
    test_index = int(sys.argv[3]) if len(sys.argv) > 3 else 0

    # Load tests
    tests = load_tests(test_file)

    if test_index >= len(tests):
        print(f"Error: Test index {test_index} out of range (0-{len(tests)-1})")
        sys.exit(1)

    test = tests[test_index]
    print(f"Test: {test['name']} (test #{test_index})")

    # Check for exception tests
    init_pc = test['initial']['pc']
    final_pc = test['final']['pc']
    if abs(final_pc - init_pc) > 1000:
        print(f"SKIP: Exception test (PC: 0x{init_pc:08X} -> 0x{final_pc:08X})")
        sys.exit(0)

    # Extract module name from verilog file
    with open(verilog_file, 'r') as f:
        for line in f:
            if line.strip().startswith('module '):
                module_name = line.split()[1].rstrip('(').rstrip(';')
                break
        else:
            module_name = verilog_file.stem

    # Output paths
    output_dir = Path(__file__).parent
    tb_file = output_dir / f"{module_name}_tb.sv"
    sim_file = output_dir / f"sim_{module_name}"

    # Generate testbench
    print(f"\n1. Generating testbench: {tb_file}")
    generate_testbench(test, module_name, verilog_file, tb_file)
    print(f"   → Testbench created")

    # Compile with iverilog
    print(f"\n2. Compiling with iverilog...")
    compile_cmd = ["iverilog", "-g2012", "-o", str(sim_file), str(verilog_file), str(tb_file)]
    result = subprocess.run(compile_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Compilation failed:\n{result.stderr}")
        sys.exit(1)
    print(f"   → Compiled to {sim_file}")

    # Run simulation
    print(f"\n3. Running simulation...")
    os.chdir(output_dir)
    sim_result = subprocess.run([str(sim_file)], capture_output=True, text=True)

    # Print simulation output
    print(sim_result.stdout)
    if sim_result.stderr:
        print(sim_result.stderr)

    # Check result
    if sim_result.returncode == 0:
        print("\n   ✅ TEST PASSED")
        return 0
    else:
        print("\n   ❌ TEST FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
