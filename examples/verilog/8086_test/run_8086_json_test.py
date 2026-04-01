#!/usr/bin/env python3
"""
Complete test runner for 8086 JSON tests.
Generates Verilog, creates testbench, and validates execution.
"""

import json
import gzip
import sys
import os
import subprocess
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from core.isa_parser import ISAParser
from backends.verilog import VerilogGenerator

def generate_testbench(test, module_name, generator, output_file):
    """Generate a SystemVerilog testbench for a single test."""

    # Extract initial state
    init_regs = test['initial']['regs']
    final_regs = test['final']['regs']

    # Map JSON register names to expected final values
    # Note: Final only contains changed registers
    expected_ax = final_regs.get('ax', init_regs.get('ax', 0))
    expected_bx = final_regs.get('bx', init_regs.get('bx', 0))
    expected_cx = final_regs.get('cx', init_regs.get('cx', 0))
    expected_dx = final_regs.get('dx', init_regs.get('dx', 0))
    expected_ip = final_regs.get('ip', init_regs.get('ip', 0))
    expected_flags = final_regs.get('flags', init_regs.get('flags', 0))

    # Extract flag bits
    init_flags = init_regs.get('flags', 0)
    cf_init = (init_flags >> 0) & 1
    pf_init = (init_flags >> 2) & 1
    af_init = (init_flags >> 4) & 1
    zf_init = (init_flags >> 6) & 1
    sf_init = (init_flags >> 7) & 1
    of_init = (init_flags >> 11) & 1

    # Check which registers and memories exist in the module
    reg_names = [r['name'] for r in generator.reg_declarations]
    mem_names = list(generator.memory_declarations.keys())

    has_modrm = 'modrm' in reg_names
    has_xregs = 'xregs' in mem_names

    # Check for each flag individually
    has_flag_CF = 'flag_CF' in reg_names
    has_flag_PF = 'flag_PF' in reg_names
    has_flag_AF = 'flag_AF' in reg_names
    has_flag_ZF = 'flag_ZF' in reg_names
    has_flag_SF = 'flag_SF' in reg_names
    has_flag_OF = 'flag_OF' in reg_names
    has_any_flag = any([has_flag_CF, has_flag_PF, has_flag_AF, has_flag_ZF, has_flag_SF, has_flag_OF])

    # Check for individual ISA state registers (for instructions that don't use xregs array)
    has_AL = 'AL' in reg_names
    has_AH = 'AH' in reg_names
    has_AX = 'AX' in reg_names
    has_BL = 'BL' in reg_names
    has_BH = 'BH' in reg_names
    has_BX = 'BX' in reg_names
    has_CL = 'CL' in reg_names
    has_CH = 'CH' in reg_names
    has_CX = 'CX' in reg_names
    has_DL = 'DL' in reg_names
    has_DH = 'DH' in reg_names
    has_DX = 'DX' in reg_names
    has_SI = 'SI' in reg_names
    has_DI = 'DI' in reg_names
    has_SP = 'SP' in reg_names
    has_BP = 'BP' in reg_names
    has_flag_DF = 'flag_DF' in reg_names
    # Segment registers
    has_ES = 'ES' in reg_names
    has_DS = 'DS' in reg_names
    has_CS = 'CS' in reg_names
    has_SS = 'SS' in reg_names

    # Extract individual register values from JSON
    df_init = (init_flags >> 10) & 1  # Direction flag is bit 10

    # Reset value declarations - only for ports that exist
    reset_decls_list = ["    reg [15:0] reset_ip;"]
    if has_flag_CF: reset_decls_list.append("    reg reset_flag_CF;")
    if has_flag_OF: reset_decls_list.append("    reg reset_flag_OF;")
    if has_flag_SF: reset_decls_list.append("    reg reset_flag_SF;")
    if has_flag_ZF: reset_decls_list.append("    reg reset_flag_ZF;")
    if has_flag_AF: reset_decls_list.append("    reg reset_flag_AF;")
    if has_flag_PF: reset_decls_list.append("    reg reset_flag_PF;")
    if has_flag_DF: reset_decls_list.append("    reg reset_flag_DF;")
    # Individual registers
    if has_AX: reset_decls_list.append("    reg [15:0] reset_AX;")
    if has_BX: reset_decls_list.append("    reg [15:0] reset_BX;")
    if has_CX: reset_decls_list.append("    reg [15:0] reset_CX;")
    if has_DX: reset_decls_list.append("    reg [15:0] reset_DX;")
    if has_SI: reset_decls_list.append("    reg [15:0] reset_SI;")
    if has_DI: reset_decls_list.append("    reg [15:0] reset_DI;")
    if has_SP: reset_decls_list.append("    reg [15:0] reset_SP;")
    if has_BP: reset_decls_list.append("    reg [15:0] reset_BP;")
    # Segment registers
    if has_ES: reset_decls_list.append("    reg [15:0] reset_ES;")
    if has_DS: reset_decls_list.append("    reg [15:0] reset_DS;")
    if has_CS: reset_decls_list.append("    reg [15:0] reset_CS;")
    if has_SS: reset_decls_list.append("    reg [15:0] reset_SS;")
    reset_decls = "\n".join(reset_decls_list)

    # Build DUT port connections - only connect ports that exist
    dut_ports_list = [
        "        .clk(clk)",
        "        .reset(reset)",
        "        .reset_ip(reset_ip)"
    ]
    if has_flag_CF: dut_ports_list.append("        .reset_flag_CF(reset_flag_CF)")
    if has_flag_OF: dut_ports_list.append("        .reset_flag_OF(reset_flag_OF)")
    if has_flag_SF: dut_ports_list.append("        .reset_flag_SF(reset_flag_SF)")
    if has_flag_ZF: dut_ports_list.append("        .reset_flag_ZF(reset_flag_ZF)")
    if has_flag_AF: dut_ports_list.append("        .reset_flag_AF(reset_flag_AF)")
    if has_flag_PF: dut_ports_list.append("        .reset_flag_PF(reset_flag_PF)")
    if has_flag_DF: dut_ports_list.append("        .reset_flag_DF(reset_flag_DF)")
    # Individual registers
    if has_AX: dut_ports_list.append("        .reset_AX(reset_AX)")
    if has_BX: dut_ports_list.append("        .reset_BX(reset_BX)")
    if has_CX: dut_ports_list.append("        .reset_CX(reset_CX)")
    if has_DX: dut_ports_list.append("        .reset_DX(reset_DX)")
    if has_SI: dut_ports_list.append("        .reset_SI(reset_SI)")
    if has_DI: dut_ports_list.append("        .reset_DI(reset_DI)")
    if has_SP: dut_ports_list.append("        .reset_SP(reset_SP)")
    if has_BP: dut_ports_list.append("        .reset_BP(reset_BP)")
    # Segment registers
    if has_ES: dut_ports_list.append("        .reset_ES(reset_ES)")
    if has_DS: dut_ports_list.append("        .reset_DS(reset_DS)")
    if has_CS: dut_ports_list.append("        .reset_CS(reset_CS)")
    if has_SS: dut_ports_list.append("        .reset_SS(reset_SS)")
    dut_ports = ",\n".join(dut_ports_list)

    # Build instruction memory loading code
    imem_loads = ""
    for i, byte in enumerate(test['bytes']):
        imem_loads += f"        dut.imem[16'h{init_regs['ip']+i:04X}] = 8'h{byte:02X};\n"

    # Build data memory (RAM) initialization code from test data
    # RAM is initialized from test['initial']['ram'] which is a list of [address, value] pairs
    dmem_loads = ""
    has_dmem = 'dmem' in mem_names
    if has_dmem and 'ram' in test.get('initial', {}):
        initial_ram = test['initial']['ram']
        for addr, val in initial_ram:
            # Use 20-bit addressing for 1MB memory space
            dmem_loads += f"        dut.dmem[20'h{addr:05X}] = 8'h{val:02X};\n"

    # Build register initialization code
    xreg_init_code = ""
    if has_xregs:
        xreg_init_code = f'''dut.xregs[0] = 16'h{init_regs.get('ax', 0):04X};  // AX
        dut.xregs[1] = 16'h{init_regs.get('cx', 0):04X};  // CX
        dut.xregs[2] = 16'h{init_regs.get('dx', 0):04X};  // DX
        dut.xregs[3] = 16'h{init_regs.get('bx', 0):04X};  // BX
        dut.xregs[4] = 16'h{init_regs.get('sp', 0):04X};  // SP
        dut.xregs[5] = 16'h{init_regs.get('bp', 0):04X};  // BP
        dut.xregs[6] = 16'h{init_regs.get('si', 0):04X};  // SI
        dut.xregs[7] = 16'h{init_regs.get('di', 0):04X};  // DI'''

    xreg_display_init = ""
    if has_xregs:
        xreg_display_init = f'''$display("  AX: %04Xh", dut.xregs[0]);
        $display("  CX: %04Xh", dut.xregs[1]);'''

    xreg_display_final = ""
    if has_xregs:
        xreg_display_final = f'''$display("  AX: %04Xh (expected %04Xh)", dut.xregs[0], 16'h{expected_ax:04X});
        $display("  CX: %04Xh (expected %04Xh)", dut.xregs[1], 16'h{expected_cx:04X});'''

    cx_check_code = ""
    if has_xregs:
        cx_check_code = f'''if (dut.xregs[1] !== 16'h{expected_cx:04X}) begin
            $display("ERROR: CX mismatch!");
            $finish(1);
        end'''

    # Build byte display string
    bytes_display = ' '.join(f'{b:02X}h' for b in test['bytes'])

    # Build initialization strings - directly set internal registers
    # Note: ip is split to ip/_wr, flags are not split
    ip_init_str = f"dut.ip = 16'h{init_regs['ip']:04X};"

    modrm_init = ""
    if has_modrm and len(test['bytes']) > 1:
        modrm_init = f"dut.modrm_rd = 8'h{test['bytes'][1]:02X};  // ModR/M byte"
    else:
        modrm_init = "// No ModR/M byte"

    # Build flag initialization strings - flags are not split, use simple names
    cf_init_str = f"dut.flag_CF = 1'b{cf_init};" if has_flag_CF else ""
    pf_init_str = f"dut.flag_PF = 1'b{pf_init};" if has_flag_PF else ""
    af_init_str = f"dut.flag_AF = 1'b{af_init};" if has_flag_AF else ""
    zf_init_str = f"dut.flag_ZF = 1'b{zf_init};" if has_flag_ZF else ""
    sf_init_str = f"dut.flag_SF = 1'b{sf_init};" if has_flag_SF else ""
    of_init_str = f"dut.flag_OF = 1'b{of_init};" if has_flag_OF else ""
    df_init_str = f"dut.flag_DF = 1'b{df_init};" if has_flag_DF else ""

    # Build individual register initialization strings - use _rd_rd suffix
    al_init_str = f"dut.AL_rd_rd = 8'h{init_regs.get('ax', 0) & 0xFF:02X};" if has_AL else ""
    ah_init_str = f"dut.AH_rd_rd = 8'h{(init_regs.get('ax', 0) >> 8) & 0xFF:02X};" if has_AH else ""
    ax_init_str = f"dut.AX_rd_rd = 16'h{init_regs.get('ax', 0):04X};" if has_AX else ""
    bl_init_str = f"dut.BL_rd_rd = 8'h{init_regs.get('bx', 0) & 0xFF:02X};" if has_BL else ""
    bh_init_str = f"dut.BH_rd_rd = 8'h{(init_regs.get('bx', 0) >> 8) & 0xFF:02X};" if has_BH else ""
    bx_init_str = f"dut.BX_rd_rd = 16'h{init_regs.get('bx', 0):04X};" if has_BX else ""
    cl_init_str = f"dut.CL_rd_rd = 8'h{init_regs.get('cx', 0) & 0xFF:02X};" if has_CL else ""
    ch_init_str = f"dut.CH_rd_rd = 8'h{(init_regs.get('cx', 0) >> 8) & 0xFF:02X};" if has_CH else ""
    cx_init_str = f"dut.CX_rd_rd = 16'h{init_regs.get('cx', 0):04X};" if has_CX else ""
    dl_init_str = f"dut.DL_rd_rd = 8'h{init_regs.get('dx', 0) & 0xFF:02X};" if has_DL else ""
    dh_init_str = f"dut.DH_rd_rd = 8'h{(init_regs.get('dx', 0) >> 8) & 0xFF:02X};" if has_DH else ""
    dx_init_str = f"dut.DX_rd_rd = 16'h{init_regs.get('dx', 0):04X};" if has_DX else ""
    si_init_str = f"dut.SI_rd_rd = 16'h{init_regs.get('si', 0):04X};" if has_SI else ""
    di_init_str = f"dut.DI_rd_rd = 16'h{init_regs.get('di', 0):04X};" if has_DI else ""
    sp_init_str = f"dut.SP_rd_rd = 16'h{init_regs.get('sp', 0):04X};" if has_SP else ""
    bp_init_str = f"dut.BP_rd_rd = 16'h{init_regs.get('bp', 0):04X};" if has_BP else ""

    # Build register initialization comment
    xreg_comment = "// Initialize registers" if has_xregs else "// No xregs"

    # Build flag display
    flag_display = "$display(\"  Flags: CF=%b\", reset_flag_CF);" if (has_any_flag and has_flag_CF) else ""

    # Build conditional flag reset assignments
    flag_reset_assignments = []
    if has_flag_CF: flag_reset_assignments.append(f"reset_flag_CF = 1'b{cf_init};")
    if has_flag_PF: flag_reset_assignments.append(f"reset_flag_PF = 1'b{pf_init};")
    if has_flag_AF: flag_reset_assignments.append(f"reset_flag_AF = 1'b{af_init};")
    if has_flag_ZF: flag_reset_assignments.append(f"reset_flag_ZF = 1'b{zf_init};")
    if has_flag_SF: flag_reset_assignments.append(f"reset_flag_SF = 1'b{sf_init};")
    if has_flag_OF: flag_reset_assignments.append(f"reset_flag_OF = 1'b{of_init};")
    if has_flag_DF: flag_reset_assignments.append(f"reset_flag_DF = 1'b{df_init};")
    # Add individual register reset assignments
    if has_AX: flag_reset_assignments.append(f"reset_AX = 16'h{init_regs.get('ax', 0):04X};")
    if has_BX: flag_reset_assignments.append(f"reset_BX = 16'h{init_regs.get('bx', 0):04X};")
    if has_CX: flag_reset_assignments.append(f"reset_CX = 16'h{init_regs.get('cx', 0):04X};")
    if has_DX: flag_reset_assignments.append(f"reset_DX = 16'h{init_regs.get('dx', 0):04X};")
    if has_SI: flag_reset_assignments.append(f"reset_SI = 16'h{init_regs.get('si', 0):04X};")
    if has_DI: flag_reset_assignments.append(f"reset_DI = 16'h{init_regs.get('di', 0):04X};")
    if has_SP: flag_reset_assignments.append(f"reset_SP = 16'h{init_regs.get('sp', 0):04X};")
    if has_BP: flag_reset_assignments.append(f"reset_BP = 16'h{init_regs.get('bp', 0):04X};")
    # Segment registers
    if has_ES: flag_reset_assignments.append(f"reset_ES = 16'h{init_regs.get('es', 0):04X};")
    if has_DS: flag_reset_assignments.append(f"reset_DS = 16'h{init_regs.get('ds', 0):04X};")
    if has_CS: flag_reset_assignments.append(f"reset_CS = 16'h{init_regs.get('cs', 0):04X};")
    if has_SS: flag_reset_assignments.append(f"reset_SS = 16'h{init_regs.get('ss', 0):04X};")
    flag_reset_code = "\n        ".join(flag_reset_assignments) if flag_reset_assignments else "// No flags to reset"

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
        // Variables for multi-cycle execution
        integer cycle_count;
        reg [15:0] initial_ip;

        $display("========================================");
        $display("Test: {test['name']}");
        $display("Bytes: {bytes_display}");
        $display("========================================");

        // Wait for DUT's initial block to finish zeroing memories
        #1;

        // Set up reset values (these will be loaded into registers on reset)
        reset_ip = 16'h{init_regs['ip']:04X};
        {flag_reset_code}

        // Load instruction memory (directly via hierarchical reference)
{imem_loads}
        // Load data memory (RAM) for stack/memory operations
{dmem_loads}
        // {xreg_comment}
        {xreg_init_code}

        $display("Initial State:");
        $display("  IP reset value: %04Xh", reset_ip);
        {xreg_display_init}
        {flag_display}

        // Apply reset to load initial values into registers
        $display("\\nApplying reset...");
        reset = 1;
        @(posedge clk);  // Wait for reset to be registered
        @(posedge clk);  // Extra cycle for stability
        #1;

        reset = 0;

        // Multi-cycle execution for REP instructions
        // Run for up to 1000 cycles or until IP changes from initial value
        initial_ip = dut.ip;

        for (cycle_count = 0; cycle_count < 1000; cycle_count = cycle_count + 1) begin
            @(posedge clk);
            #1;  // Small delay to ensure signals have propagated

            // Check if instruction completed (IP changed from initial value)
            if (dut.ip !== initial_ip) begin
                $display("  Instruction completed after %0d cycle(s)", cycle_count + 1);
                cycle_count = 1000;  // Break out of loop
            end
        end

        $display("\\nFinal State:");
        $display("  IP: %04Xh (expected %04Xh)", dut.ip, 16'h{expected_ip:04X});
        {xreg_display_final}

        // Validate results
        if (dut.ip !== 16'h{expected_ip:04X}) begin
            $display("ERROR: IP mismatch!");
            $finish(1);
        end

        {cx_check_code}

        $display("\\n========================================");
        $display("TEST PASSED");
        $display("========================================");
        $finish(0);
    end

    // Timeout
    initial begin
        #1000;
        $display("ERROR: Test timeout!");
        $finish(1);
    end

endmodule
'''

    with open(output_file, 'w') as f:
        f.write(testbench)

def main():
    print("8086 JSON Test Runner")
    print("=" * 60)

    # Parse command-line arguments
    if len(sys.argv) < 3:
        print("Usage: python3 run_8086_json_test.py <isa_file> <test_file.json.gz> [test_index]")
        print("Example: python3 run_8086_json_test.py 8086/loopne.isa 8086/tests/v1/E0.json.gz")
        sys.exit(1)

    isa_file = sys.argv[1]
    test_file = sys.argv[2]

    # Extract module name from ISA file
    module_name = "cpu_" + os.path.splitext(os.path.basename(isa_file))[0]
    verilog_file = f"examples/verilog/8086_test/{module_name}.v"
    testbench_file = f"examples/verilog/8086_test/{module_name}_tb.sv"

    # Parse test file
    with gzip.open(test_file, 'rt') as f:
        data = json.load(f)
        # Handle both single test (dict) and multiple tests (list)
        if isinstance(data, dict):
            tests = [data]
        else:
            tests = data

    # Find a test without instruction prefixes (look for test where first byte matches expected opcode)
    # Common 8086 prefixes: 0x26 (ES:), 0x2E (CS:), 0x36 (SS:), 0x3E (DS:), 0xF0 (LOCK), 0xF2 (REPNE), 0xF3 (REP)
    SEGMENT_PREFIXES = [0x26, 0x2E, 0x36, 0x3E]  # ES, CS, SS, DS overrides
    REP_PREFIXES = [0xF2, 0xF3]  # REPNE, REP
    LOCK_PREFIX = [0xF0]

    # Check if ISA file is for a REP/REPNE instruction
    isa_basename = os.path.basename(isa_file).lower()
    wants_rep = 'rep_' in isa_basename or 'repe_' in isa_basename
    wants_repne = 'repne_' in isa_basename

    test_index = 0
    if len(sys.argv) >= 4:
        test_index = int(sys.argv[3])
    else:
        # Parse ISA file to extract assume constraints for smart test selection
        import re
        constraints = {'mod': None, 'reg_bit2': None, 'rm_bit2': None, 'valid_rm': None, 'modrm': None}
        try:
            with open(isa_file, 'r') as f:
                content = f.read()
                mod_match = re.search(r'assume\s+mod_bits\s*==\s*0b(\d+)', content)
                if mod_match:
                    constraints['mod'] = int(mod_match.group(1), 2)
                reg_match = re.search(r'assume\s+reg_idx\[2\]\s*==\s*(\d)', content)
                if reg_match:
                    constraints['reg_bit2'] = int(reg_match.group(1))
                rm_match = re.search(r'assume\s+rm_idx\[2\]\s*==\s*(\d)', content)
                if rm_match:
                    constraints['rm_bit2'] = int(rm_match.group(1))
                # Parse case statements on rm_bits to find valid rm values
                rm_case_match = re.search(r'case\s*\(\s*rm_bits\s*\)\s*\{([^}]+)\}', content)
                if rm_case_match:
                    case_content = rm_case_match.group(1)
                    rm_values = re.findall(r'0b(\d+)\s*:', case_content)
                    if rm_values:
                        constraints['valid_rm'] = set(int(v, 2) for v in rm_values)
                # Parse direct modrm constraints (e.g., assume modrm == 0x5C)
                modrm_match = re.search(r'assume\s+modrm\s*==\s*0x([0-9A-Fa-f]+)', content)
                if modrm_match:
                    constraints['modrm'] = int(modrm_match.group(1), 16)
        except:
            pass

        # Find tests matching ISA constraints
        matching = []
        for i, t in enumerate(tests):
            b = t['bytes']

            # Handle prefix matching based on ISA type
            if wants_repne:
                # For REPNE instructions, require F2 prefix and skip segment overrides
                if b[0] != 0xF2:
                    continue
                # Strip the F2 prefix for further processing
                effective_bytes = b[1:]
            elif wants_rep:
                # For REP/REPE instructions, require F3 prefix and skip segment overrides
                if b[0] != 0xF3:
                    continue
                # Strip the F3 prefix for further processing
                effective_bytes = b[1:]
            else:
                # For non-REP instructions, skip all prefixes
                if b[0] in SEGMENT_PREFIXES + REP_PREFIXES + LOCK_PREFIX:
                    continue
                effective_bytes = b

            # For single-byte instructions (no ModR/M), skip constraint matching
            if len(effective_bytes) < 2:
                matching.append((i, len(b)))
                continue
            modrm = effective_bytes[1]
            mod, reg, rm = (modrm >> 6) & 3, (modrm >> 3) & 7, modrm & 7
            if constraints['mod'] is not None and mod != constraints['mod']:
                continue
            if constraints['reg_bit2'] is not None and ((reg >> 2) & 1) != constraints['reg_bit2']:
                continue
            if constraints['rm_bit2'] is not None and ((rm >> 2) & 1) != constraints['rm_bit2']:
                continue
            # Check if rm value is handled by case statement
            if constraints['valid_rm'] is not None and rm not in constraints['valid_rm']:
                continue
            # Check exact modrm value if specified
            if constraints['modrm'] is not None and modrm != constraints['modrm']:
                continue
            matching.append((i, len(b)))

        if matching:
            matching.sort(key=lambda x: x[1])  # Prefer shorter tests
            test_index = matching[0][0]
        else:
            # Fallback: minimal bytes
            min_bytes = min(len(t['bytes']) for t in tests)
            for i, t in enumerate(tests):
                if len(t['bytes']) == min_bytes:
                    test_index = i
                    break

    test = tests[test_index]
    print(f"Test: {test['name']} (test #{test_index})")
    print(f"Bytes: {' '.join(f'{b:02X}' for b in test['bytes'])}")

    print(f"\n1. Parsing ISA file: {isa_file}")
    parser = ISAParser()
    graph = parser.parse_file(isa_file)
    print(f"   → {len(graph.nodes)} nodes, {len(graph.edges)} edges")

    print(f"\n2. Generating Verilog: {verilog_file}")
    gen = VerilogGenerator(graph, module_name)
    verilog = gen.generate()
    with open(verilog_file, 'w') as f:
        f.write(verilog)
    print(f"   → Generated {len(verilog)} bytes")

    print(f"\n3. Generating testbench: {testbench_file}")
    generate_testbench(test, module_name, gen, testbench_file)
    print(f"   → Testbench created")

    print(f"\n4. Compiling with iverilog...")
    sim_file = f"examples/verilog/8086_test/sim_{module_name}"
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
    result = subprocess.run([sim_file],
                          capture_output=True, text=True)

    print(result.stdout)
    # Check for failure - either non-zero return code OR error messages in output
    # Exclude benign $readmemh warnings (testbench loads values directly via hierarchical refs)
    stdout_filtered = '\n'.join(line for line in result.stdout.split('\n')
                                 if 'readmemh' not in line.lower())
    has_error = ('ERROR' in stdout_filtered or 'FAILED' in stdout_filtered or
                 'mismatch' in stdout_filtered.lower())
    if result.returncode != 0 or has_error:
        print("\n   ❌ TEST FAILED")
        if result.stderr:
            print(result.stderr)
        sys.exit(1)
    else:
        print("   ✅ TEST PASSED")

if __name__ == '__main__':
    main()
