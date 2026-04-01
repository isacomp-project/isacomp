--------------------------------------------------------------------------------
-- rudi_riscv_cpu_with_mem.vhd
--
-- Memory wrapper for Rudi RV32I CPU
-- Adds integrated memory to make it compatible with
-- ISAComp test infrastructure (similar to ISA-generated processors)
--
-- This wrapper:
-- - Instantiates the Rudi CPU core
-- - Implements simple memory controller for bus interface
-- - Provides unified memory (single address space for instructions and data)
-- - Loads memory from imem.mem file (hex format, one word per line)
-- - Clean interface: only clk, reset, and debug_pc ports
--------------------------------------------------------------------------------

library IEEE;
use IEEE.std_logic_1164.all;
use IEEE.numeric_std.all;
use IEEE.std_logic_textio.all;
use STD.textio.all;

entity rudi_riscv_cpu_with_mem is
    port (
        clk : in std_logic;
        reset : in std_logic;
        -- TEMPORARY: debug_pc for testbench access (until GHDL external names work)
        -- This port won't survive VHDL->ISAComp->VHDL round-trip, will need external names
        debug_pc : out std_logic_vector(31 downto 0)
    );
end entity rudi_riscv_cpu_with_mem;

architecture rtl of rudi_riscv_cpu_with_mem is

    -- Unified memory (1024 words = 4KB)
    -- Used for both instructions and data (unified address space)
    type mem_array_type is array (0 to 1023) of std_logic_vector(31 downto 0);

    -- Memory initialization function
    impure function load_mem_from_file(filename : string) return mem_array_type is
        file mem_file : text;
        variable line_v : line;
        variable mem_word : std_logic_vector(31 downto 0);
        variable mem_data : mem_array_type := (others => (others => '0'));
        variable addr : integer := 0;
        variable good : boolean;
        variable status : file_open_status;
    begin
        file_open(status, mem_file, filename, read_mode);
        if status /= open_ok then
            report "WARNING: Could not open " & filename & " for reading, using zeros" severity warning;
            return mem_data;  -- Return zeros
        end if;

        report "Loading " & filename & "..." severity note;

        while not endfile(mem_file) and addr < 1024 loop
            readline(mem_file, line_v);
            -- Skip empty lines
            if line_v'length > 0 then
                hread(line_v, mem_word, good);
                if good then
                    mem_data(addr) := mem_word;
                    addr := addr + 1;
                end if;
            end if;
        end loop;
        file_close(mem_file);

        report "Loaded " & integer'image(addr) & " words from " & filename severity note;
        return mem_data;
    end function;

    signal mem : mem_array_type := load_mem_from_file("imem.mem");

    -- Generated Rudi CPU component declaration (matches entity name in riscv_cpu.vhd)
    component riscv_cpu is
        port (
            clk : in std_logic;
            reset : in std_logic;
            bus_addr : out std_logic_vector(31 downto 0);
            bus_busy : in std_logic;
            bus_din : in std_logic_vector(31 downto 0);
            bus_dout : out std_logic_vector(31 downto 0);
            bus_enable : out std_logic;
            bus_width : out std_logic_vector(1 downto 0);  -- Original uses 2-bit width
            bus_write : out std_logic;
            instr_reg : in std_logic_vector(31 downto 0);
            pc_next : out std_logic_vector(31 downto 0);
            minimize_size : in std_logic;
            debug_sel : in std_logic_vector(4 downto 0);
            debug_pc : out std_logic_vector(31 downto 0);
            debug_data : out std_logic_vector(31 downto 0)
        );
    end component;

    -- CPU signals
    signal pc_next : std_logic_vector(31 downto 0);
    signal instr_reg : std_logic_vector(31 downto 0);
    signal bus_busy : std_logic;
    signal bus_addr : std_logic_vector(31 downto 0);
    signal bus_width : std_logic_vector(1 downto 0);  -- Original uses 2-bit
    signal bus_dout : std_logic_vector(31 downto 0);
    signal bus_write : std_logic;
    signal bus_enable : std_logic;
    signal bus_din : std_logic_vector(31 downto 0);
    signal orig_debug_pc : std_logic_vector(31 downto 0);  -- CPU's internal debug PC
    signal debug_data : std_logic_vector(31 downto 0);  -- Not used

    -- Current PC for instruction fetch
    signal pc : std_logic_vector(31 downto 0);

    -- Memory control signals
    signal mem_addr_word : unsigned(31 downto 0);
    signal mem_addr_masked : unsigned(9 downto 0);  -- 1024 words = 10-bit address
    signal mem_read_data : std_logic_vector(31 downto 0);

begin

    -- Export PC for testbench (pass through to let testbench mask if needed)
    debug_pc <= pc;

    -- Instantiate generated Rudi CPU core
    cpu_core: riscv_cpu
        port map (
            clk => clk,
            reset => reset,
            bus_addr => bus_addr,
            bus_busy => bus_busy,
            bus_din => bus_din,
            bus_dout => bus_dout,
            bus_enable => bus_enable,
            bus_width => bus_width,
            bus_write => bus_write,
            instr_reg => instr_reg,
            pc_next => pc_next,
            minimize_size => '0',
            debug_sel => "00000",
            debug_pc => orig_debug_pc,
            debug_data => debug_data
        );

    -- PC register (for instruction fetch)
    process(clk)
    begin
        if rising_edge(clk) then
            if reset = '1' then
                pc <= (others => '0');
            else
                pc <= pc_next;
            end if;
        end if;
    end process;

    -- Instruction fetch from unified memory
    -- Address is in bytes, convert to word address
    instr_fetch: process(pc, mem)
        variable word_addr : unsigned(9 downto 0);
    begin
        -- Convert byte address to word address (divide by 4)
        word_addr := unsigned(pc(11 downto 2));  -- Take bits [11:2] for word address
        instr_reg <= mem(to_integer(word_addr));
    end process;

    -- Memory controller for stores (synchronous)
    mem_write: process(clk)
        variable word_addr : unsigned(9 downto 0);
        variable byte_offset : unsigned(1 downto 0);
    begin
        if rising_edge(clk) then
            if reset = '0' and bus_enable = '1' and bus_write = '1' then
                -- Convert byte address to word address
                word_addr := unsigned(bus_addr(11 downto 2));
                byte_offset := unsigned(bus_addr(1 downto 0));

                -- Store operation (use lower 2 bits of bus_width)
                case bus_width(1 downto 0) is
                    when "00" =>  -- Byte store
                        case byte_offset is
                            when "00" =>
                                mem(to_integer(word_addr))(7 downto 0) <= bus_dout(7 downto 0);
                            when "01" =>
                                mem(to_integer(word_addr))(15 downto 8) <= bus_dout(7 downto 0);
                            when "10" =>
                                mem(to_integer(word_addr))(23 downto 16) <= bus_dout(7 downto 0);
                            when "11" =>
                                mem(to_integer(word_addr))(31 downto 24) <= bus_dout(7 downto 0);
                            when others =>
                                null;
                        end case;

                    when "01" =>  -- Half-word store
                        if byte_offset(1) = '0' then
                            mem(to_integer(word_addr))(15 downto 0) <= bus_dout(15 downto 0);
                        else
                            mem(to_integer(word_addr))(31 downto 16) <= bus_dout(15 downto 0);
                        end if;

                    when "10" =>  -- Word store
                        mem(to_integer(word_addr)) <= bus_dout;

                    when others =>
                        null;
                end case;
            end if;
        end if;
    end process;

    -- Memory controller for loads (combinational)
    mem_read: process(bus_enable, bus_write, bus_addr, bus_width, mem)
        variable word_addr : unsigned(9 downto 0);
        variable byte_offset : unsigned(1 downto 0);
        variable read_data : std_logic_vector(31 downto 0);
    begin
        bus_din <= (others => '0');  -- Default

        if bus_enable = '1' and bus_write = '0' then
            -- Convert byte address to word address
            word_addr := unsigned(bus_addr(11 downto 2));
            byte_offset := unsigned(bus_addr(1 downto 0));

            -- Load operation (use lower 2 bits of bus_width)
            read_data := mem(to_integer(word_addr));

            case bus_width(1 downto 0) is
                when "00" =>  -- Byte load
                    case byte_offset is
                        when "00" =>
                            bus_din <= x"000000" & read_data(7 downto 0);
                        when "01" =>
                            bus_din <= x"000000" & read_data(15 downto 8);
                        when "10" =>
                            bus_din <= x"000000" & read_data(23 downto 16);
                        when "11" =>
                            bus_din <= x"000000" & read_data(31 downto 24);
                        when others =>
                            bus_din <= (others => '0');
                    end case;

                when "01" =>  -- Half-word load
                    if byte_offset(1) = '0' then
                        bus_din <= x"0000" & read_data(15 downto 0);
                    else
                        bus_din <= x"0000" & read_data(31 downto 16);
                    end if;

                when "10" =>  -- Word load
                    bus_din <= read_data;

                when others =>
                    bus_din <= (others => '0');
            end case;
        end if;
    end process;

    -- Memory is always ready (no wait states)
    bus_busy <= '0';

end architecture rtl;
