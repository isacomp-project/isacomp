"""
Shared VHDL test runner generation utilities.

This module provides common functions for generating VHDL test runner testbenches
and test scripts across different processor architectures (RV32I, RV64I, MIPS32).
"""

import os
import re


def generate_vhdl_test_runner_tb(
    vhdl_file: str,
    entity_name: str,
    output_dir: str,
    pc_width: int = 32,
    is_pipelined: bool = False
) -> str:
    """
    Generate a test runner testbench for processor tests.

    Args:
        vhdl_file: Path to the generated VHDL RTL file
        entity_name: Name of the DUT entity
        output_dir: Directory to write the testbench file
        pc_width: Width of program counter (32 or 64)
        is_pipelined: Whether this is a pipelined processor (affects PC checking logic)

    Returns:
        Path to the generated testbench file
    """
    # Parse ports from the generated VHDL file
    with open(vhdl_file, 'r') as f:
        vhdl_content = f.read()

    # Find entity ports
    pattern = rf'entity\s+{entity_name}\s+is\s+port\s*\((.*?)\);\s*end\s+entity'
    match = re.search(pattern, vhdl_content, re.DOTALL | re.IGNORECASE)
    if not match:
        raise ValueError(f"Could not parse ports for entity {entity_name}")

    port_block = match.group(1)
    ports = []
    port_text = port_block.replace('\n', ' ')
    for part in port_text.split(';'):
        part = part.strip()
        if not part:
            continue
        port_match = re.match(r'(\w+)\s*:\s*(in|out)\s+(.+)', part, re.IGNORECASE)
        if port_match:
            ports.append({
                'name': port_match.group(1),
                'direction': port_match.group(2).lower(),
                'type': port_match.group(3).strip()
            })

    # Determine hex string length based on PC width
    hex_len = pc_width // 4

    # Generate hex conversion function based on PC width
    if pc_width == 64:
        hex_func_name = "hex_to_slv64"
        hex_func = f"""
    function hex_to_slv64(hex : string) return std_logic_vector is
        variable result : std_logic_vector(63 downto 0) := (others => '0');
        variable nibble : integer;
    begin
        for i in hex'range loop
            nibble := hex_char_to_int(hex(i));
            result := result(59 downto 0) & std_logic_vector(to_unsigned(nibble, 4));
        end loop;
        return result;
    end function;
"""
    else:
        hex_func_name = "hex_to_slv"
        hex_func = f"""
    function hex_to_slv(hex : string) return std_logic_vector is
        variable result : std_logic_vector(31 downto 0) := (others => '0');
        variable nibble : integer;
    begin
        for i in hex'range loop
            nibble := hex_char_to_int(hex(i));
            result := result(27 downto 0) & std_logic_vector(to_unsigned(nibble, 4));
        end loop;
        return result;
    end function;
"""

    # Generate testbench header
    processor_type = "pipelined" if is_pipelined else "single-cycle"
    tb = f"""-- Test runner testbench for {processor_type} processor (auto-generated)
library IEEE;
use IEEE.std_logic_1164.all;
use IEEE.numeric_std.all;
use STD.textio.all;

entity test_runner_tb is
end entity test_runner_tb;

architecture testbench of test_runner_tb is
    signal PASS_ADDR : std_logic_vector({pc_width-1} downto 0) := (others => '0');
    signal FAIL_ADDR : std_logic_vector({pc_width-1} downto 0) := (others => '0');
    signal addrs_loaded : boolean := false;

    function hex_char_to_int(c : character) return integer is
    begin
        case c is
            when '0' => return 0; when '1' => return 1; when '2' => return 2; when '3' => return 3;
            when '4' => return 4; when '5' => return 5; when '6' => return 6; when '7' => return 7;
            when '8' => return 8; when '9' => return 9;
            when 'a' | 'A' => return 10; when 'b' | 'B' => return 11; when 'c' | 'C' => return 12;
            when 'd' | 'D' => return 13; when 'e' | 'E' => return 14; when 'f' | 'F' => return 15;
            when others => return 0;
        end case;
    end function;
{hex_func}
    component {entity_name} is
        port (
"""
    # Add component ports
    for i, port in enumerate(ports):
        tb += f"            {port['name']} : {port['direction']} {port['type']}"
        tb += ";\n" if i < len(ports) - 1 else "\n"

    tb += f"""        );
    end component {entity_name};

    -- DUT signals
"""
    # Declare signals
    for port in ports:
        if port['direction'] == 'in':
            if 'std_logic_vector' in port['type']:
                tb += f"    signal {port['name']} : {port['type']} := (others => '0');\n"
            else:
                default = "'1'" if port['name'] == 'reset' else "'0'"
                tb += f"    signal {port['name']} : {port['type']} := {default};\n"
        else:
            tb += f"    signal {port['name']} : {port['type']};\n"

    tb += """
    constant CLK_PERIOD : time := 10 ns;
    signal cycle_count : integer := 0;

begin
    clk_gen : process
    begin
        clk <= '0';
        wait for CLK_PERIOD / 2;
        clk <= '1';
        wait for CLK_PERIOD / 2;
    end process;

    dut : """ + entity_name + """
        port map (
"""
    # Add port mappings
    for i, port in enumerate(ports):
        tb += f"            {port['name']} => {port['name']}"
        tb += ",\n" if i < len(ports) - 1 else "\n"

    tb += f"""        );

    load_addrs_proc : process
        file addr_file : text;
        variable l : line;
        variable hex_str : string(1 to {hex_len});
        variable good : boolean;
    begin
        file_open(addr_file, "test_addrs.txt", read_mode);
        readline(addr_file, l);
        read(l, hex_str, good);
        if good then PASS_ADDR <= {hex_func_name}(hex_str); end if;
        readline(addr_file, l);
        read(l, hex_str, good);
        if good then FAIL_ADDR <= {hex_func_name}(hex_str); end if;
        file_close(addr_file);
        addrs_loaded <= true;
        wait;
    end process;

    test_proc : process
        variable l : line;
    begin
        wait until addrs_loaded = true;
        wait for 1 ns;
        write(l, string'("Loaded PASS_ADDR=0x")); hwrite(l, PASS_ADDR);
        write(l, string'(" FAIL_ADDR=0x")); hwrite(l, FAIL_ADDR);
        writeline(output, l);
        reset <= '1';
        wait for CLK_PERIOD * 5;
        reset <= '0';
        for i in 0 to 100000 loop
            wait for CLK_PERIOD;
            cycle_count <= cycle_count + 1;
"""

    # PC check logic differs between single-cycle and pipelined
    if is_pipelined:
        tb += """            -- Pipelined: check PC after pipeline settles
            if cycle_count > 10 then
                if debug_pc_rd = PASS_ADDR then
                    write(l, string'("TEST PASSED at cycle ")); write(l, cycle_count);
                    writeline(output, l);
                    std.env.finish;
                end if;
                if debug_pc_rd = FAIL_ADDR then
                    write(l, string'("TEST FAILED at cycle ")); write(l, cycle_count);
                    writeline(output, l);
                    std.env.finish;
                end if;
            end if;
"""
    else:
        tb += """            -- Single-cycle: check PC directly each cycle
            if debug_pc_rd = PASS_ADDR then
                write(l, string'("TEST PASSED at cycle ")); write(l, cycle_count);
                writeline(output, l);
                std.env.finish;
            end if;
            if debug_pc_rd = FAIL_ADDR then
                write(l, string'("TEST FAILED at cycle ")); write(l, cycle_count);
                writeline(output, l);
                std.env.finish;
            end if;
"""

    tb += """        end loop;
        write(l, string'("TIMEOUT after 100000 cycles"));
        writeline(output, l);
        std.env.finish;
    end process;

end architecture testbench;
"""
    # Write testbench file
    tb_file = os.path.join(output_dir, "test_runner_tb.vhd")
    with open(tb_file, 'w') as f:
        f.write(tb)

    return tb_file


def generate_vhdl_test_script(
    entity_name: str,
    output_dir: str,
    arch: str,
    tests: list,
    test_base_path: str,
    data_width: int = 32,
    is_pipelined: bool = False
) -> str:
    """
    Generate run_all_tests.sh for GHDL.

    Args:
        entity_name: Name of the DUT entity
        output_dir: Directory to write the script
        arch: Architecture name for display (e.g., "RISC-V 32-bit", "MIPS32")
        tests: List of test names to run
        test_base_path: Base path to test files (e.g., "../../riscv32/riscv-tests/isa/rv32ui-isacomp-")
        data_width: Width of data memory entries (32 or 64)
        is_pipelined: Whether this is a pipelined processor

    Returns:
        Path to the generated script file
    """
    tests_str = " ".join(tests)
    processor_type = "pipelined" if is_pipelined else "single-cycle"

    # Address format depends on data width
    addr_format = f"%0{data_width // 4}X"

    # Memory generation code depends on data width
    if data_width == 64:
        dmem_gen = f"""with open('dmem.mem', 'w') as f:
    for dword_idx in range(2048):
        dword = 0
        addr = dword_idx * 8
        for byte_offset in range(8):
            byte_addr = addr + byte_offset
            if byte_addr in data: dword |= data[byte_addr] << (byte_offset * 8)
        f.write(f'{{dword:016X}}\\n')"""
    else:
        dmem_gen = f"""with open('dmem.mem', 'w') as f:
    for word_idx in range(4096):
        word = 0
        addr = word_idx * 4
        for byte_offset in range(4):
            byte_addr = addr + byte_offset
            if byte_addr in data: word |= data[byte_addr] << (byte_offset * 8)
        f.write(f'{{word:08X}}\\n')"""

    script = f'''#!/bin/bash
# Run {arch} VHDL tests for {processor_type} processor
set -e
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
cd "$SCRIPT_DIR"
ENTITY_NAME="{entity_name}"
RTL_FILE="${{ENTITY_NAME}}.vhd"
TB_FILE="test_runner_tb.vhd"

if [ ! -f "$TB_FILE" ]; then echo "Error: $TB_FILE not found"; exit 1; fi

echo "Compiling VHDL files..."
rm -f work-obj08.cf
ghdl -a --std=08 "$RTL_FILE" 2>/dev/null || {{ echo "Error compiling RTL"; exit 1; }}
ghdl -a --std=08 "$TB_FILE" 2>/dev/null || {{ echo "Error compiling testbench"; exit 1; }}

echo "Running {arch} tests..."
TESTS="{tests_str}"
PASS=0; FAIL=0; SKIP=0; FAILED_TESTS=""

for test in $TESTS; do
    echo -n "Testing $test... "
    TEST_BASE="{test_base_path}$test"
    if [ ! -f "$TEST_BASE.hex" ]; then echo "SKIP (no hex file)"; SKIP=$((SKIP + 1)); continue; fi
    if [ ! -f "$TEST_BASE.addrs" ]; then echo "SKIP (no addrs file)"; SKIP=$((SKIP + 1)); continue; fi
    read PASS_ADDR FAIL_ADDR < "$TEST_BASE.addrs"
    printf "{addr_format}\\n{addr_format}\\n" 0x$PASS_ADDR 0x$FAIL_ADDR > test_addrs.txt
    python3 << PYEOF
data = {{}}
with open('$TEST_BASE.hex', 'r') as f:
    for line in f:
        line = line.strip()
        if not line.startswith(':'): continue
        byte_count = int(line[1:3], 16)
        address = int(line[3:7], 16)
        record_type = int(line[7:9], 16)
        if record_type == 0:
            for i in range(byte_count):
                data[address + i] = int(line[9+i*2:11+i*2], 16)
        elif record_type == 1: break
with open('imem.mem', 'w') as f:
    for word_idx in range(4096):
        word = 0
        addr = word_idx * 4
        for byte_offset in range(4):
            byte_addr = addr + byte_offset
            if byte_addr in data: word |= data[byte_addr] << (byte_offset * 8)
        f.write(f'{{word:08X}}\\n')
{dmem_gen}
PYEOF
    ghdl -e --std=08 test_runner_tb 2>/dev/null
    RESULT=$(timeout 60 ghdl -r --std=08 test_runner_tb --stop-time=5ms 2>&1 || true)
    if echo "$RESULT" | grep -q "TEST PASSED"; then echo "PASS"; PASS=$((PASS + 1))
    elif echo "$RESULT" | grep -q "TEST FAILED"; then echo "FAIL"; FAIL=$((FAIL + 1)); FAILED_TESTS="$FAILED_TESTS $test"
    elif echo "$RESULT" | grep -q "TIMEOUT"; then echo "TIMEOUT"; FAIL=$((FAIL + 1)); FAILED_TESTS="$FAILED_TESTS $test"
    elif echo "$RESULT" | grep -qi "error"; then echo "ERROR"; FAIL=$((FAIL + 1)); FAILED_TESTS="$FAILED_TESTS $test"
    else echo "UNKNOWN"; FAIL=$((FAIL + 1)); FAILED_TESTS="$FAILED_TESTS $test"; fi
done
echo ""
echo "================================"
echo "Results: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
if [ -n "$FAILED_TESTS" ]; then echo "Failed tests:$FAILED_TESTS"; fi
echo "================================"
if [ $FAIL -gt 0 ]; then exit 1; fi
'''
    script_file = os.path.join(output_dir, "run_all_tests.sh")
    with open(script_file, 'w') as f:
        f.write(script)
    os.chmod(script_file, 0o755)

    return script_file
