--###############################################################################
--# rudi_post_egress_cosim_tb.vhd - Cosimulation testbench comparing Original vs Post-Egress
--# Both CPUs have integrated memory (loaded from imem.mem)
--###############################################################################

library IEEE;
use IEEE.std_logic_1164.all;
use IEEE.numeric_std.all;
use STD.textio.all;

entity rudi_post_egress_cosim_tb is
    generic (
        MEM_INIT_FILE : string := "imem.mem";
        TIMEOUT_CYCLES : integer := 1000;
        PASS_PC_INT : integer := 16#000004F0#;  -- Default: 0x4F0
        FAIL_PC_INT : integer := 16#000004E8#   -- Default: 0x4E8
    );
end entity rudi_post_egress_cosim_tb;

architecture testbench of rudi_post_egress_cosim_tb is

    -- Original Rudi CPU with memory wrapper
    component rudi_riscv_cpu_with_mem is
        port (
            clk : in std_logic;
            reset : in std_logic;
            debug_pc : out std_logic_vector(31 downto 0)
        );
    end component;

    -- Post-egress Rudi CPU (VHDL->ResourceGraph->VHDL) also with memory
    component rudi_post_egress is
        port (
            clk : in std_logic;
            reset : in std_logic;
            debug_pc : out std_logic_vector(31 downto 0);
            reset_pc : in std_logic_vector(31 downto 0);
            reset_cpu_core_i_program_counter_current_pc : in std_logic_vector(31 downto 0);
            -- Debug outputs for branch tracking
            debug_take_branch : out std_logic;
            debug_test_is_true : out std_logic;
            debug_branch_test_enable : out std_logic;
            debug_branch_test_mode : out std_logic_vector(2 downto 0);
            debug_reg_read_data_a : out std_logic_vector(31 downto 0);
            debug_reg_read_data_b : out std_logic_vector(31 downto 0);
            debug_instr_reg : out std_logic_vector(31 downto 0);
            debug_a_eq_b : out std_logic;
            -- Additional debug for register file
            debug_write_port_addr : out std_logic_vector(4 downto 0);
            debug_write_data : out std_logic_vector(31 downto 0);
            debug_read_port_1_addr : out std_logic_vector(4 downto 0);
            debug_read_port_2_addr : out std_logic_vector(4 downto 0)
        );
    end component;

    -- Clock and reset
    signal clk : std_logic := '0';
    signal reset : std_logic := '1';

    -- Original CPU outputs
    signal orig_debug_pc : std_logic_vector(31 downto 0);

    -- Post-egress CPU outputs
    signal pe_debug_pc : std_logic_vector(31 downto 0);
    signal pe_take_branch : std_logic;
    signal pe_test_is_true : std_logic;
    signal pe_branch_test_enable : std_logic;
    signal pe_branch_test_mode : std_logic_vector(2 downto 0);
    signal pe_reg_a : std_logic_vector(31 downto 0);
    signal pe_reg_b : std_logic_vector(31 downto 0);
    signal pe_instr : std_logic_vector(31 downto 0);
    signal pe_a_eq_b : std_logic;
    signal pe_write_port_addr : std_logic_vector(4 downto 0);
    signal pe_write_data : std_logic_vector(31 downto 0);
    signal pe_read_port_1_addr : std_logic_vector(4 downto 0);
    signal pe_read_port_2_addr : std_logic_vector(4 downto 0);

    -- Test control
    signal test_done : boolean := false;
    signal test_passed : boolean := false;
    signal cycle_count : integer := 0;
    signal mismatch_count : integer := 0;

    -- RISC-V test pass/fail PC addresses (from generics, can be overridden at runtime)
    constant PASS_PC : std_logic_vector(31 downto 0) := std_logic_vector(to_unsigned(PASS_PC_INT, 32));
    constant FAIL_PC : std_logic_vector(31 downto 0) := std_logic_vector(to_unsigned(FAIL_PC_INT, 32));

    -- Constants
    constant CLK_PERIOD : time := 10 ns;
    constant RESET_CYCLES : integer := 5;

begin

    -- Original Rudi CPU with memory (Device Under Test 1)
    dut_orig : rudi_riscv_cpu_with_mem
        port map (
            clk       => clk,
            reset     => reset,
            debug_pc  => orig_debug_pc
        );

    -- Post-egress CPU with memory (Device Under Test 2)
    dut_post_egress : rudi_post_egress
        port map (
            clk       => clk,
            reset     => reset,
            debug_pc  => pe_debug_pc,
            reset_pc  => x"00000000",  -- Reset PC to 0 (RESET_VECTOR)
            reset_cpu_core_i_program_counter_current_pc => x"00000000",  -- Reset to 0 (RESET_VECTOR)
            debug_take_branch => pe_take_branch,
            debug_test_is_true => pe_test_is_true,
            debug_branch_test_enable => pe_branch_test_enable,
            debug_branch_test_mode => pe_branch_test_mode,
            debug_reg_read_data_a => pe_reg_a,
            debug_reg_read_data_b => pe_reg_b,
            debug_instr_reg => pe_instr,
            debug_a_eq_b => pe_a_eq_b,
            debug_write_port_addr => pe_write_port_addr,
            debug_write_data => pe_write_data,
            debug_read_port_1_addr => pe_read_port_1_addr,
            debug_read_port_2_addr => pe_read_port_2_addr
        );

    -- Clock generation
    clk_proc : process
    begin
        while not test_done loop
            clk <= '0';
            wait for CLK_PERIOD / 2;
            clk <= '1';
            wait for CLK_PERIOD / 2;
        end loop;
        wait;
    end process;

    -- Main test process
    test_proc : process
    begin
        -- Initial reset
        reset <= '1';
        wait for CLK_PERIOD * RESET_CYCLES;
        reset <= '0';

        report "========================================" severity note;
        report "Starting cosimulation comparison" severity note;
        report "Original Rudi vs Post-Egress (VHDL->ResourceGraph->VHDL)" severity note;
        report "========================================" severity note;

        -- Run simulation
        while cycle_count < TIMEOUT_CYCLES and not test_done loop
            wait until rising_edge(clk);
            cycle_count <= cycle_count + 1;

            -- Check for metavalues (X, U, etc.) in PC which indicate problems
            if is_x(orig_debug_pc) then
                report "ERROR: Original CPU PC has metavalue at cycle " & integer'image(cycle_count) &
                       ": " & to_hstring(orig_debug_pc) severity error;
                test_done <= true;
                test_passed <= false;
            end if;

            if is_x(pe_debug_pc) then
                report "ERROR: Post-Egress CPU PC has metavalue at cycle " & integer'image(cycle_count) &
                       ": " & to_hstring(pe_debug_pc) severity error;
                test_done <= true;
                test_passed <= false;
            end if;

            -- Detailed logging - report every cycle for first 50 cycles and around cycle 129 to catch divergence
            if cycle_count <= 50 or (cycle_count >= 120 and cycle_count <= 135) then
                if orig_debug_pc = pe_debug_pc then
                    report "Cycle " & integer'image(cycle_count) &
                           ": PC = " & to_hstring(orig_debug_pc) & " [MATCH]" severity note;
                else
                    report "Cycle " & integer'image(cycle_count) &
                           ": Orig PC = " & to_hstring(orig_debug_pc) &
                           ", Post PC = " & to_hstring(pe_debug_pc) & " [MISMATCH]" severity note;
                end if;
            end if;

            -- Extra debug for cycles 1-15, around cycle 37, and around cycle 128
            if (cycle_count >= 1 and cycle_count <= 15) or (cycle_count >= 33 and cycle_count <= 45) or (cycle_count >= 125 and cycle_count <= 135) then
                report "Cycle " & integer'image(cycle_count) & " Debug:" &
                       " instr=" & to_hstring(pe_instr) &
                       " mode=" & to_string(pe_branch_test_mode) &
                       " reg_a=" & to_hstring(pe_reg_a) &
                       " reg_b=" & to_hstring(pe_reg_b) severity note;
                report "  RegFile: rd_a=" & to_string(pe_read_port_1_addr) &
                       " rd_b=" & to_string(pe_read_port_2_addr) &
                       " wr_addr=" & to_string(pe_write_port_addr) &
                       " wr_data=" & to_hstring(pe_write_data) &
                       " enable=" & std_logic'image(pe_branch_test_enable) &
                       " take=" & std_logic'image(pe_take_branch) severity note;
            end if;

            -- Compare PC values
            if orig_debug_pc /= pe_debug_pc then
                report "DIVERGENCE at cycle " & integer'image(cycle_count) &
                       ": Orig PC = " & to_hstring(orig_debug_pc) &
                       ", Post-Egress PC = " & to_hstring(pe_debug_pc) severity warning;
                report "  Post-Egress Debug:" severity note;
                report "    instr = " & to_hstring(pe_instr) severity note;
                report "    reg_a = " & to_hstring(pe_reg_a) severity note;
                report "    reg_b = " & to_hstring(pe_reg_b) severity note;
                report "    a_eq_b = " & std_logic'image(pe_a_eq_b) severity note;
                report "    branch_test_mode = " & to_string(pe_branch_test_mode) severity note;
                report "    branch_test_enable = " & std_logic'image(pe_branch_test_enable) severity note;
                report "    test_is_true = " & std_logic'image(pe_test_is_true) severity note;
                report "    take_branch = " & std_logic'image(pe_take_branch) severity note;
                mismatch_count <= mismatch_count + 1;

                -- Stop after first mismatch for detailed analysis
                if mismatch_count >= 1 then
                    report "Stopping after first divergence for analysis" severity note;
                    test_passed <= false;
                    test_done <= true;
                end if;
            else
                -- PCs match - report progress every 100 cycles
                if cycle_count mod 100 = 0 then
                    report "Cycle " & integer'image(cycle_count) &
                           ": PC = " & to_hstring(orig_debug_pc) & " [OK]" severity note;
                end if;
            end if;

            -- Check for PASS PC (both must match and be at PASS_PC)
            if orig_debug_pc = PASS_PC and pe_debug_pc = PASS_PC then
                report "Both CPUs reached PASS_PC at cycle " & integer'image(cycle_count) severity note;
                report "RESULT: PASS" severity note;
                test_done <= true;
                exit;
            end if;

            -- Check for FAIL PC
            if orig_debug_pc = FAIL_PC or pe_debug_pc = FAIL_PC then
                report "CPU reached FAIL_PC at cycle " & integer'image(cycle_count) severity error;
                report "RESULT: FAIL - Test program failed" severity error;
                test_done <= true;
                exit;
            end if;

        end loop;

        -- Report results
        report "========================================" severity note;
        if mismatch_count = 0 then
            report "RESULT: PASS - All cycles matched!" severity note;
            report "Total cycles: " & integer'image(cycle_count) severity note;
        else
            report "RESULT: FAIL - " & integer'image(mismatch_count) & " mismatches" severity error;
        end if;
        report "========================================" severity note;

        test_done <= true;
        wait;
    end process;

end architecture testbench;
