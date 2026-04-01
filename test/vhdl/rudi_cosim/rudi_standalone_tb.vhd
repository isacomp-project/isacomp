--###############################################################################
--# rudi_standalone_tb.vhd - Cosimulation testbench for Rudi RV32I
--# Provides memory model and test infrastructure for riscv-tests
--###############################################################################

library IEEE;
use IEEE.std_logic_1164.all;
use IEEE.numeric_std.all;
use STD.textio.all;

entity rudi_standalone_tb is
    generic (
        MEM_INIT_FILE : string := "imem.mem";
        TIMEOUT_CYCLES : integer := 100000
    );
end entity rudi_standalone_tb;

architecture testbench of rudi_standalone_tb is

    component riscv_cpu is
        port (
            clk           : in  std_logic;
            pc_next       : out std_logic_vector(31 downto 0);
            instr_reg     : in  std_logic_vector(31 downto 0);
            reset         : in  std_logic;
            minimize_size : in  std_logic;
            bus_busy      : in  std_logic;
            bus_addr      : out std_logic_vector(31 downto 0);
            bus_width     : out std_logic_vector(1 downto 0);
            bus_dout      : out std_logic_vector(31 downto 0);
            bus_write     : out std_logic;
            bus_enable    : out std_logic;
            bus_din       : in  std_logic_vector(31 downto 0);
            debug_pc      : out std_logic_vector(31 downto 0);
            debug_sel     : in  std_logic_vector(4 downto 0);
            debug_data    : out std_logic_vector(31 downto 0)
        );
    end component;

    -- Clock and reset
    signal clk : std_logic := '0';
    signal reset : std_logic := '1';

    -- CPU interface signals
    signal pc_next : std_logic_vector(31 downto 0);
    signal instr_reg : std_logic_vector(31 downto 0) := (others => '0');
    signal bus_busy : std_logic := '0';
    signal bus_addr : std_logic_vector(31 downto 0);
    signal bus_width : std_logic_vector(1 downto 0);
    signal bus_dout : std_logic_vector(31 downto 0);
    signal bus_write : std_logic;
    signal bus_enable : std_logic;
    signal bus_din : std_logic_vector(31 downto 0) := (others => '0');
    signal debug_pc : std_logic_vector(31 downto 0);
    signal debug_data : std_logic_vector(31 downto 0);

    -- Test control
    signal test_done : boolean := false;
    signal test_passed : boolean := false;
    signal cycle_count : integer := 0;

    -- Memory (4KB each for instructions and data)
    type mem_type is array (0 to 1023) of std_logic_vector(31 downto 0);
    signal imem : mem_type := (others => (others => '0'));
    signal dmem : mem_type := (others => (others => '0'));

    -- Data memory initialization signal
    signal dmem_init : mem_type := (others => (others => '0'));
    signal dmem_loaded : boolean := false;

    -- Constants
    constant CLK_PERIOD : time := 10 ns;
    constant RESET_CYCLES : integer := 5;

    -- Test result detection (riscv-tests write to tohost at 0x80001000)
    constant TOHOST_ADDR : std_logic_vector(31 downto 0) := x"80001000";
    signal tohost_value : std_logic_vector(31 downto 0) := (others => '0');

begin

    -- Device Under Test
    dut : riscv_cpu
        port map (
            clk           => clk,
            pc_next       => pc_next,
            instr_reg     => instr_reg,
            reset         => reset,
            minimize_size => '0',
            bus_busy      => bus_busy,
            bus_addr      => bus_addr,
            bus_width     => bus_width,
            bus_dout      => bus_dout,
            bus_write     => bus_write,
            bus_enable    => bus_enable,
            bus_din       => bus_din,
            debug_pc      => debug_pc,
            debug_sel     => "00000",
            debug_data    => debug_data
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

    -- Instruction memory (simple ROM) at 0xF0000000 - registered output
    imem_process : process(clk)
        variable addr_idx : integer;
    begin
        if rising_edge(clk) then
            if not is_x(pc_next) then
                if pc_next(31 downto 28) = x"F" then
                    addr_idx := to_integer(unsigned(pc_next(11 downto 2)));
                    if addr_idx >= 0 and addr_idx < 1024 then
                        instr_reg <= imem(addr_idx);
                    else
                        instr_reg <= x"00000013"; -- NOP
                    end if;
                else
                    instr_reg <= x"00000013"; -- NOP
                end if;
            else
                instr_reg <= x"00000013"; -- NOP
            end if;
        end if;
    end process;

    -- Data memory WRITE (registered) with initialization
    dmem_write : process(clk, dmem_loaded)
        variable addr_idx : integer;
        variable initialized : boolean := false;
    begin
        -- Copy initial values when loaded
        if dmem_loaded and not initialized then
            dmem <= dmem_init;
            initialized := true;
        end if;

        if rising_edge(clk) then
            if bus_enable = '1' and bus_write = '1' then
                addr_idx := to_integer(unsigned(bus_addr(11 downto 2)));
                report "BUS WRITE: addr=0x" & to_hstring(bus_addr) &
                       " data=0x" & to_hstring(bus_dout) &
                       " width=" & to_string(to_integer(unsigned(bus_width))) severity note;

                if addr_idx >= 0 and addr_idx < 1024 then
                    case bus_width is
                        when "00" => -- Byte
                            case bus_addr(1 downto 0) is
                                when "00" => dmem(addr_idx)(7 downto 0) <= bus_dout(7 downto 0);
                                when "01" => dmem(addr_idx)(15 downto 8) <= bus_dout(7 downto 0);
                                when "10" => dmem(addr_idx)(23 downto 16) <= bus_dout(7 downto 0);
                                when "11" => dmem(addr_idx)(31 downto 24) <= bus_dout(7 downto 0);
                                when others => null;
                            end case;
                        when "01" => -- Halfword
                            if bus_addr(1) = '0' then
                                dmem(addr_idx)(15 downto 0) <= bus_dout(15 downto 0);
                            else
                                dmem(addr_idx)(31 downto 16) <= bus_dout(15 downto 0);
                            end if;
                        when "10" => -- Word
                            dmem(addr_idx) <= bus_dout;
                        when others => null;
                    end case;
                end if;

                -- Check for tohost write
                if bus_addr = TOHOST_ADDR then
                    tohost_value <= bus_dout;
                end if;
            end if;
        end if;
    end process;

    -- Data memory READ (combinational)
    dmem_read : process(bus_enable, bus_write, bus_addr, bus_width, dmem)
        variable addr_idx : integer;
        variable word_data : std_logic_vector(31 downto 0);
    begin
        bus_din <= (others => '0');

        if bus_enable = '1' and bus_write = '0' then
            addr_idx := to_integer(unsigned(bus_addr(11 downto 2)));

            if addr_idx >= 0 and addr_idx < 1024 then
                word_data := dmem(addr_idx);

                case bus_width is
                    when "00" => -- Byte
                        case bus_addr(1 downto 0) is
                            when "00" => bus_din <= x"000000" & word_data(7 downto 0);
                            when "01" => bus_din <= x"000000" & word_data(15 downto 8);
                            when "10" => bus_din <= x"000000" & word_data(23 downto 16);
                            when "11" => bus_din <= x"000000" & word_data(31 downto 24);
                            when others => bus_din <= (others => '0');
                        end case;
                    when "01" => -- Halfword
                        if bus_addr(1) = '0' then
                            bus_din <= x"0000" & word_data(15 downto 0);
                        else
                            bus_din <= x"0000" & word_data(31 downto 16);
                        end if;
                    when "10" => -- Word
                        bus_din <= word_data;
                    when others =>
                        bus_din <= (others => '0');
                end case;
            end if;
        end if;
    end process;

    -- Test stimulus and memory initialization
    stimulus : process
        file mem_file : text;
        variable line_buf : line;
        variable word : std_logic_vector(31 downto 0);
        variable idx : integer := 0;
        variable status : file_open_status;
    begin
        -- Load instruction memory
        report "Loading instruction memory from " & MEM_INIT_FILE severity note;
        file_open(mem_file, MEM_INIT_FILE, read_mode);

        while not endfile(mem_file) and idx < 1024 loop
            readline(mem_file, line_buf);
            hread(line_buf, word);
            imem(idx) <= word;
            idx := idx + 1;
        end loop;

        file_close(mem_file);
        report "Loaded " & integer'image(idx) & " instructions" severity note;

        -- Try to load data memory
        file_open(status, mem_file, "dmem.mem", read_mode);
        if status = open_ok then
            idx := 0;
            while not endfile(mem_file) and idx < 1024 loop
                readline(mem_file, line_buf);
                hread(line_buf, word);
                dmem_init(idx) <= word;
                idx := idx + 1;
            end loop;
            file_close(mem_file);
            report "Loaded " & integer'image(idx) & " data words" severity note;
        else
            report "No dmem.mem file (data section empty)" severity note;
        end if;
        dmem_loaded <= true;
        wait for 0 ns;  -- Allow signal to update

        -- Reset sequence
        reset <= '1';
        wait for CLK_PERIOD * RESET_CYCLES;
        reset <= '0';
        report "Reset released, starting execution..." severity note;

        wait;
    end process;

    -- Test completion detection
    completion : process(clk)
    begin
        if rising_edge(clk) then
            if reset = '0' then
                cycle_count <= cycle_count + 1;

                if (cycle_count mod 1000) = 0 then
                    report "Cycle " & integer'image(cycle_count) &
                           ": PC = 0x" & to_hstring(debug_pc) severity note;
                end if;

                -- Trace bus reads
                if bus_enable = '1' and bus_write = '0' then
                    report "BUS READ: addr=0x" & to_hstring(bus_addr) &
                           " data=0x" & to_hstring(bus_din) &
                           " width=" & to_string(to_integer(unsigned(bus_width))) severity note;
                end if;

                if tohost_value /= x"00000000" then
                    if tohost_value = x"00000001" then
                        report "TEST PASSED! (tohost = 1)" severity note;
                        test_passed <= true;
                    else
                        report "TEST FAILED! (tohost = 0x" & to_hstring(tohost_value) & ")" severity error;
                        test_passed <= false;
                    end if;
                    test_done <= true;
                end if;

                if cycle_count >= TIMEOUT_CYCLES then
                    report "TIMEOUT after " & integer'image(TIMEOUT_CYCLES) & " cycles" severity warning;
                    test_passed <= false;
                    test_done <= true;
                end if;
            end if;
        end if;
    end process;

end architecture testbench;
