#!/usr/bin/env python3
"""
Complete test runner for M68000 JSON tests from SingleStepTests.
Generates Verilog, creates testbench, and validates execution.
"""

import json
import sys
import os
import subprocess
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from core.isa_parser import ISAParser
from backends.verilog import VerilogGenerator


def extract_ccr_flags(sr):
    """Extract CCR flags from status register."""
    return {
        'C': (sr >> 0) & 1,
        'V': (sr >> 1) & 1,
        'Z': (sr >> 2) & 1,
        'N': (sr >> 3) & 1,
        'X': (sr >> 4) & 1,
    }


def generate_testbench(test, module_name, generator, output_file):
    """Generate a SystemVerilog testbench for a single M68000 test."""

    # Extract initial and final state
    init_state = test['initial']
    final_state = test['final']

    # Extract initial flag values from SR
    init_sr = init_state.get('sr', 0)
    init_ccr = extract_ccr_flags(init_sr)

    # Extract final expected values
    final_sr = final_state.get('sr', 0)
    final_ccr = extract_ccr_flags(final_sr)

    # Check which registers and memories exist in the module
    reg_names = [r['name'] for r in generator.reg_declarations]
    mem_names = list(generator.memory_declarations.keys())

    has_dregs = 'dregs' in mem_names
    has_aregs = 'aregs' in mem_names
    has_dmem = 'dmem' in mem_names
    has_imem = 'imem' in mem_names

    # Check for flags
    has_flag_X = 'flag_X' in reg_names
    has_flag_N = 'flag_N' in reg_names
    has_flag_Z = 'flag_Z' in reg_names
    has_flag_V = 'flag_V' in reg_names
    has_flag_C = 'flag_C' in reg_names

    # Reset value declarations
    reset_decls_list = ["    reg [31:0] reset_pc;"]
    if has_flag_X: reset_decls_list.append("    reg reset_flag_X;")
    if has_flag_N: reset_decls_list.append("    reg reset_flag_N;")
    if has_flag_Z: reset_decls_list.append("    reg reset_flag_Z;")
    if has_flag_V: reset_decls_list.append("    reg reset_flag_V;")
    if has_flag_C: reset_decls_list.append("    reg reset_flag_C;")
    reset_decls = "\n".join(reset_decls_list)

    # Build DUT port connections
    dut_ports_list = [
        "        .clk(clk)",
        "        .reset(reset)",
        "        .reset_pc(reset_pc)"
    ]
    if has_flag_X: dut_ports_list.append("        .reset_flag_X(reset_flag_X)")
    if has_flag_N: dut_ports_list.append("        .reset_flag_N(reset_flag_N)")
    if has_flag_Z: dut_ports_list.append("        .reset_flag_Z(reset_flag_Z)")
    if has_flag_V: dut_ports_list.append("        .reset_flag_V(reset_flag_V)")
    if has_flag_C: dut_ports_list.append("        .reset_flag_C(reset_flag_C)")
    dut_ports = ",\n".join(dut_ports_list)

    # Build instruction and data memory loading from RAM
    # RAM is byte-addressed in the test format
    mem_loads = ""

    # IMPORTANT: M68000 uses prefetch - the instruction to execute is in the prefetch buffer.
    # The prefetch contains words that were fetched BEFORE the current PC.
    # prefetch[0] is at (PC - 2*len(prefetch)), prefetch[1] at (PC - 2*(len(prefetch)-1)), etc.
    # This way, when the ISA starts executing at PC, it reads the opcode from prefetch position.
    pc = init_state.get('pc', 0)
    prefetch = init_state.get('prefetch', [])

    if has_imem and prefetch:
        # Load prefetch words BEFORE PC
        # The instruction being executed starts at PC - 2*len(prefetch)
        instr_start = pc - 2 * len(prefetch)
        for i, word in enumerate(prefetch):
            byte_addr = instr_start + i * 2
            word_addr = byte_addr >> 1  # Convert byte address to word address
            mem_loads += f"        dut.imem[24'h{word_addr:06X}] = 16'h{word:04X};\n"

    if 'ram' in init_state:
        # Group bytes into 16-bit words for imem (M68K has 16-bit instruction bus)
        ram_bytes = {addr: val for addr, val in init_state['ram']}

        # Load imem: 16-bit words at word addresses (pc[31:1])
        # Calculate where prefetch data was loaded
        instr_start = pc - 2 * len(prefetch) if prefetch else pc

        for addr, val in init_state['ram']:
            # For imem, we need 16-bit words at even addresses
            # Skip addresses covered by prefetch (they may differ from RAM due to prefetch timing)
            # The generated Verilog uses word addresses (pc[31:1]), so we divide byte addr by 2
            if has_imem and addr % 2 == 0:
                # Skip if this address is covered by prefetch
                skip = False
                for i in range(len(prefetch)):
                    prefetch_addr = instr_start + i * 2
                    if addr == prefetch_addr or addr == prefetch_addr + 1:
                        skip = True
                        break
                if not skip:
                    hi_byte = ram_bytes.get(addr, 0)
                    lo_byte = ram_bytes.get(addr + 1, 0)
                    word = (hi_byte << 8) | lo_byte
                    word_addr = addr >> 1  # Convert byte address to word address
                    mem_loads += f"        dut.imem[24'h{word_addr:06X}] = 16'h{word:04X};\n"

        # Load dmem: byte-addressed (no word packing since port_width not set)
        # Note: M68000 has 24-bit address space
        if has_dmem:
            for addr, val in init_state['ram']:
                wrapped_addr = addr & 0xFFFFFF  # 24-bit address
                mem_loads += f"        dut.dmem[24'h{wrapped_addr:06X}] = 8'h{val:02X};\n"

    # Build data register initialization
    dreg_init_code = ""
    if has_dregs:
        for i in range(8):
            val = init_state.get(f'd{i}', 0)
            dreg_init_code += f"        dut.dregs[{i}] = 32'h{val:08X};\n"

    # Build address register initialization
    areg_init_code = ""
    if has_aregs:
        for i in range(7):
            val = init_state.get(f'a{i}', 0)
            areg_init_code += f"        dut.aregs[{i}] = 32'h{val:08X};\n"
        # A7 is the stack pointer - use SSP for supervisor mode, USP for user mode
        sr = init_state.get('sr', 0)
        is_supervisor = (sr >> 13) & 1
        if is_supervisor:
            a7_val = init_state.get('ssp', 0)
            areg_init_code += f"        dut.aregs[7] = 32'h{a7_val:08X};  // A7/SSP (supervisor)\n"
        else:
            a7_val = init_state.get('usp', 0)
            areg_init_code += f"        dut.aregs[7] = 32'h{a7_val:08X};  // A7/USP (user)\n"

    # Build flag reset assignments
    flag_reset_assignments = []
    if has_flag_X: flag_reset_assignments.append(f"reset_flag_X = 1'b{init_ccr['X']};")
    if has_flag_N: flag_reset_assignments.append(f"reset_flag_N = 1'b{init_ccr['N']};")
    if has_flag_Z: flag_reset_assignments.append(f"reset_flag_Z = 1'b{init_ccr['Z']};")
    if has_flag_V: flag_reset_assignments.append(f"reset_flag_V = 1'b{init_ccr['V']};")
    if has_flag_C: flag_reset_assignments.append(f"reset_flag_C = 1'b{init_ccr['C']};")
    flag_reset_code = "\n        ".join(flag_reset_assignments) if flag_reset_assignments else "// No flags to reset"

    # Calculate instruction start PC (opcode is in prefetch, which was fetched before current PC)
    prefetch = init_state.get('prefetch', [])
    instr_start_pc = init_state['pc'] - 2 * len(prefetch)

    # Expected final PC, adjusted for the offset
    # The final PC from test is also offset by the same amount
    test_final_pc = final_state.get('pc', 0)
    expected_pc = test_final_pc - 2 * len(prefetch)

    # Build validation code for data registers
    dreg_check_code = ""
    if has_dregs:
        for i in range(8):
            expected = final_state.get(f'd{i}', init_state.get(f'd{i}', 0))
            dreg_check_code += f'''
        if (dut.dregs[{i}] !== 32'h{expected:08X}) begin
            $display("ERROR: D{i} mismatch! Got %08X, expected %08X", dut.dregs[{i}], 32'h{expected:08X});
            errors = errors + 1;
        end'''

    # Build validation code for flags
    flag_check_code = ""
    if has_flag_X:
        flag_check_code += f'''
        if (dut.flag_X !== 1'b{final_ccr['X']}) begin
            $display("ERROR: X flag mismatch! Got %b, expected %b", dut.flag_X, 1'b{final_ccr['X']});
            errors = errors + 1;
        end'''
    if has_flag_N:
        flag_check_code += f'''
        if (dut.flag_N !== 1'b{final_ccr['N']}) begin
            $display("ERROR: N flag mismatch! Got %b, expected %b", dut.flag_N, 1'b{final_ccr['N']});
            errors = errors + 1;
        end'''
    if has_flag_Z:
        flag_check_code += f'''
        if (dut.flag_Z !== 1'b{final_ccr['Z']}) begin
            $display("ERROR: Z flag mismatch! Got %b, expected %b", dut.flag_Z, 1'b{final_ccr['Z']});
            errors = errors + 1;
        end'''
    if has_flag_V:
        flag_check_code += f'''
        if (dut.flag_V !== 1'b{final_ccr['V']}) begin
            $display("ERROR: V flag mismatch! Got %b, expected %b", dut.flag_V, 1'b{final_ccr['V']});
            errors = errors + 1;
        end'''
    if has_flag_C:
        flag_check_code += f'''
        if (dut.flag_C !== 1'b{final_ccr['C']}) begin
            $display("ERROR: C flag mismatch! Got %b, expected %b", dut.flag_C, 1'b{final_ccr['C']});
            errors = errors + 1;
        end'''

    # Display initial/final state for data registers
    dreg_display_init = ""
    dreg_display_final = ""
    if has_dregs:
        dreg_display_init = '''$display("  D0-D3: %08X %08X %08X %08X", dut.dregs[0], dut.dregs[1], dut.dregs[2], dut.dregs[3]);
        $display("  D4-D7: %08X %08X %08X %08X", dut.dregs[4], dut.dregs[5], dut.dregs[6], dut.dregs[7]);'''
        dreg_display_final = f'''$display("  D0-D3: %08X %08X %08X %08X", dut.dregs[0], dut.dregs[1], dut.dregs[2], dut.dregs[3]);
        $display("  D4-D7: %08X %08X %08X %08X", dut.dregs[4], dut.dregs[5], dut.dregs[6], dut.dregs[7]);'''

    testbench = f'''`timescale 1ns/1ps
module {module_name}_tb;

    // VCD dump for waveform viewing
    initial begin
        $dumpfile("{module_name}_tb.vcd");
        $dumpvars(0, {module_name}_tb);
    end

    // Clock and reset
    reg clk;
    reg reset;

    // Reset values
{reset_decls}

    // Device Under Test
    {module_name} dut (
{dut_ports}
    );

    // Clock generation
    initial clk = 0;
    always #5 clk = ~clk;

    // Test execution
    initial begin
        // Variables
        integer cycle_count;
        integer errors;
        reg [31:0] initial_pc;

        errors = 0;

        $display("========================================");
        $display("Test: {test['name']}");
        $display("========================================");

        // Wait for DUT's initial block to finish
        #1;

        // Set up reset values
        // PC points to instruction start (before prefetch words)
        reset_pc = 32'h{instr_start_pc:08X};
        {flag_reset_code}

        // Load memory
{mem_loads}
        // Initialize data registers
{dreg_init_code}
        // Initialize address registers
{areg_init_code}
        $display("Initial State:");
        $display("  PC: %08Xh", reset_pc);
        {dreg_display_init}

        // Apply reset
        $display("\\nApplying reset...");
        reset = 1;
        @(posedge clk);
        @(posedge clk);
        #1;

        reset = 0;

        // Execute instruction
        initial_pc = dut.pc;
        for (cycle_count = 0; cycle_count < 100; cycle_count = cycle_count + 1) begin
            @(posedge clk);
            #1;

            // Check if instruction completed (PC changed)
            if (dut.pc !== initial_pc) begin
                $display("  Instruction completed after %0d cycle(s)", cycle_count + 1);
                cycle_count = 100;  // Break
            end
        end

        $display("\\nFinal State:");
        $display("  PC: %08Xh (expected %08Xh)", dut.pc, 32'h{expected_pc:08X});
        {dreg_display_final}

        // Validate PC
        if (dut.pc !== 32'h{expected_pc:08X}) begin
            $display("ERROR: PC mismatch!");
            errors = errors + 1;
        end

        // Validate registers
{dreg_check_code}

        // Validate flags
{flag_check_code}

        $display("\\n========================================");
        if (errors == 0) begin
            $display("TEST PASSED");
            $finish(0);
        end else begin
            $display("TEST FAILED (%0d errors)", errors);
            $finish(1);
        end
        $display("========================================");
    end

    // Timeout
    initial begin
        #10000;
        $display("ERROR: Test timeout!");
        $finish(1);
    end

endmodule
'''

    with open(output_file, 'w') as f:
        f.write(testbench)


def load_tests(test_file):
    """Load tests from JSON file (decoded from .json.bin)."""
    with open(test_file, 'r') as f:
        return json.load(f)


def find_matching_test(tests, constraints):
    """Find a test that matches the ISA constraints."""
    # For now, just return the first test
    # TODO: Add constraint matching based on ISA assumes
    return 0, tests[0]


def main():
    print("M68000 JSON Test Runner")
    print("=" * 60)

    if len(sys.argv) < 3:
        print("Usage: python3 run_m68k_json_test.py <isa_file> <test_file.json> [test_index]")
        print("Example: python3 run_m68k_json_test.py isa/m68k/add_l_dn_dn.isa isa/m68k/tests/v1/ADD.l.json")
        sys.exit(1)

    isa_file = sys.argv[1]
    test_file = sys.argv[2]

    # Extract module name from ISA file
    module_name = "cpu_" + os.path.splitext(os.path.basename(isa_file))[0]
    verilog_file = f"examples/verilog/m68k_test/{module_name}.v"
    testbench_file = f"examples/verilog/m68k_test/{module_name}_tb.sv"

    # Load tests
    tests = load_tests(test_file)
    if isinstance(tests, dict):
        tests = [tests]

    # Select test
    test_index = int(sys.argv[3]) if len(sys.argv) >= 4 else 0
    test = tests[test_index]

    print(f"Test: {test['name']} (test #{test_index})")

    print(f"\n1. Parsing ISA file: {isa_file}")
    parser = ISAParser()
    graph = parser.parse_file(isa_file)
    print(f"   → {len(graph.nodes)} nodes, {len(graph.edges)} edges")

    # Set memory port widths for proper addressing (like RISC-V and 6502 scripts)
    # imem: 16-bit words, byte-addressed via PC - generator handles pc[31:1] conversion
    imem_node = graph.nodes.get('imem')
    if imem_node:
        imem_node.data['port_width'] = 16
        imem_node.data['element_width'] = 16
        print(f"   → Set imem port_width=16 for word-addressed instruction memory")

    # dmem: Keep byte-addressed (no port_width change) to avoid double byte extraction bug
    # The Verilog generator has a bug where setting port_width causes double bit_slice
    dmem_node = graph.nodes.get('dmem')
    if dmem_node:
        # Don't set port_width - keep dmem as byte-addressed
        print(f"   → dmem remains byte-addressed")

    print(f"\n2. Generating Verilog: {verilog_file}")
    gen = VerilogGenerator(graph, module_name)
    verilog = gen.generate()

    # Ensure output directory exists
    Path(verilog_file).parent.mkdir(parents=True, exist_ok=True)

    with open(verilog_file, 'w') as f:
        f.write(verilog)
    print(f"   → Generated {len(verilog)} bytes")

    print(f"\n3. Generating testbench: {testbench_file}")
    generate_testbench(test, module_name, gen, testbench_file)
    print(f"   → Testbench created")

    print(f"\n4. Compiling with iverilog...")
    sim_file = f"examples/verilog/m68k_test/sim_{module_name}"
    result = subprocess.run([
        'iverilog',
        '-g2012',  # SystemVerilog 2012
        '-o', sim_file,
        verilog_file,
        testbench_file
    ], capture_output=True, text=True)

    if result.returncode != 0:
        print("   ERROR: Compilation failed!")
        print(result.stderr)
        sys.exit(1)
    print(f"   → Compiled to {sim_file}")

    print(f"\n5. Running simulation...")
    result = subprocess.run([sim_file], capture_output=True, text=True)

    print(result.stdout)
    if result.stderr:
        print(result.stderr)

    # Check for errors
    has_error = ('ERROR' in result.stdout or 'FAILED' in result.stdout)
    if result.returncode != 0 or has_error:
        print("\n   ❌ TEST FAILED")
        sys.exit(1)
    else:
        print("   ✅ TEST PASSED")


if __name__ == '__main__':
    main()
