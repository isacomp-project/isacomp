--------------------------------------------------------------------------------
-- rudi_mem_standalone_tb.vhd
--
-- Test runner for Rudi RV32I CPU with integrated memory
-- Compatible with riscv-tests infrastructure
--
-- Detects test completion by monitoring PC for pass/fail addresses
--------------------------------------------------------------------------------

library IEEE;
use IEEE.std_logic_1164.all;
use IEEE.numeric_std.all;
use STD.textio.all;

entity rudi_mem_standalone_tb is
    generic (
        TEST_NAME : string := "add";
        PASS_ADDR : std_logic_vector(31 downto 0) := x"000004ec";
        FAIL_ADDR : std_logic_vector(31 downto 0) := x"000004e4"
    );
end entity rudi_mem_standalone_tb;

architecture testbench of rudi_mem_standalone_tb is
    component rudi_riscv_cpu_with_mem is
        port (
            clk : in std_logic;
            reset : in std_logic;
            debug_pc : out std_logic_vector(31 downto 0)
        );
    end component rudi_riscv_cpu_with_mem;

    -- Clock and reset
    signal clk : std_logic := '0';
    signal reset : std_logic := '1';

    -- Test control
    signal test_done : boolean := false;
    signal test_passed : boolean := false;
    signal cycle_count : integer := 0;

    -- PC monitoring (from debug port - masked and clean)
    signal pc : std_logic_vector(31 downto 0);
    signal prev_pc : std_logic_vector(31 downto 0) := (others => '0');

    -- Timing constants
    constant CLK_PERIOD : time := 10 ns;
    constant RESET_CYCLES : integer := 5;
    constant TIMEOUT_CYCLES : integer := 100000;

begin

    -- Device Under Test
    dut : rudi_riscv_cpu_with_mem
        port map (
            clk => clk,
            reset => reset,
            debug_pc => pc
        );

    -- Clock generation
    clk_process : process
    begin
        while not test_done loop
            clk <= '0';
            wait for CLK_PERIOD / 2;
            clk <= '1';
            wait for CLK_PERIOD / 2;
        end loop;
        wait;
    end process;

    -- Test stimulus
    stimulus : process
    begin
        -- Initialize
        reset <= '1';

        report "========================================";
        report "Running RISC-V test: " & TEST_NAME;
        report "Pass address: 0x" & to_hstring(PASS_ADDR);
        report "Fail address: 0x" & to_hstring(FAIL_ADDR);
        report "========================================";

        -- Reset sequence
        wait for CLK_PERIOD * 2;

        for i in 0 to RESET_CYCLES-1 loop
            wait until rising_edge(clk);
        end loop;

        reset <= '0';
        report "Reset released, starting test execution...";

        wait;
    end process;

    -- Completion detection
    completion : process(clk)
    begin
        if rising_edge(clk) then
            if reset = '0' then
                cycle_count <= cycle_count + 1;
                prev_pc <= pc;

                -- Debug: Print PC for first 50 cycles and then periodically
                if cycle_count < 50 or (cycle_count mod 100) = 0 then
                    report "Cycle " & integer'image(cycle_count) & ": PC = 0x" & to_hstring(pc);
                end if;

                -- Check for test pass (PC is already masked by wrapper)
                if pc = PASS_ADDR then
                    report "========================================" severity note;
                    report "TEST PASSED at cycle " & integer'image(cycle_count) severity note;
                    report "PC reached pass address: 0x" & to_hstring(PASS_ADDR) severity note;
                    report "========================================" severity note;
                    test_passed <= true;
                    test_done <= true;
                end if;

                -- Check for test fail (PC is already masked by wrapper)
                if pc = FAIL_ADDR then
                    report "========================================" severity error;
                    report "TEST FAILED at cycle " & integer'image(cycle_count) severity error;
                    report "PC reached fail address: 0x" & to_hstring(FAIL_ADDR) severity error;
                    report "========================================" severity error;
                    test_passed <= false;
                    test_done <= true;
                end if;

                -- Timeout check
                if cycle_count >= TIMEOUT_CYCLES then
                    report "========================================" severity error;
                    report "TEST TIMEOUT after " & integer'image(TIMEOUT_CYCLES) & " cycles" severity error;
                    report "Final PC: 0x" & to_hstring(pc) severity error;
                    report "========================================" severity error;
                    test_passed <= false;
                    test_done <= true;
                end if;
            end if;
        end if;
    end process;

end architecture testbench;
