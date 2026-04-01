"""
Memory initialization file generation for VHDL simulations.

Generates memory initialization files that can be loaded during VHDL simulation.
"""

from pathlib import Path
from typing import List, Optional


def generate_mem_file(program_data: List[int],
                      output_file: Path,
                      width: int = 32,
                      format: str = "hex") -> None:
    """
    Generate memory initialization file.

    Args:
        program_data: List of integer words to write to memory
        output_file: Path to output file
        width: Data width in bits
        format: "hex" or "bin" for hexadecimal or binary format

    Format:
        Each line contains one memory word in hexadecimal (without 0x prefix)
        Example for 32-bit words:
            00500093
            00300113
            002081b3
    """
    with open(output_file, 'w') as f:
        for word in program_data:
            if format == "hex":
                # Hexadecimal format (most common)
                hex_width = (width + 3) // 4  # Number of hex digits
                f.write(f"{word:0{hex_width}x}\n")
            elif format == "bin":
                # Binary format
                f.write(f"{word:0{width}b}\n")
            else:
                raise ValueError(f"Unknown format: {format}")


def generate_vhdl_memory_reader(mem_name: str,
                                 mem_size: int,
                                 data_width: int,
                                 init_file: Optional[str] = None) -> str:
    """
    Generate VHDL code for memory with optional file initialization.

    Args:
        mem_name: Name of the memory signal
        mem_size: Number of memory words
        data_width: Width of each memory word in bits
        init_file: Optional path to initialization file

    Returns:
        VHDL code string for memory initialization process
    """
    vhdl = []

    if init_file:
        vhdl.append(f"    -- Initialize {mem_name} from file\n")
        vhdl.append("    process\n")
        vhdl.append("        use std.textio.all;\n")
        vhdl.append("        file mem_file : text;\n")
        vhdl.append("        variable file_line : line;\n")
        vhdl.append("        variable hex_value : string(1 to 8);\n")
        vhdl.append("        variable addr : integer := 0;\n")
        vhdl.append("    begin\n")
        vhdl.append(f"        file_open(mem_file, \"{init_file}\", read_mode);\n")
        vhdl.append(f"        while not endfile(mem_file) and addr < {mem_size} loop\n")
        vhdl.append("            readline(mem_file, file_line);\n")
        vhdl.append("            read(file_line, hex_value);\n")
        vhdl.append(f"            {mem_name}(addr) <= std_logic_vector(to_unsigned(")
        vhdl.append(f"integer'value(\"16#\" & hex_value & \"#\"), {data_width}));\n")
        vhdl.append("            addr := addr + 1;\n")
        vhdl.append("        end loop;\n")
        vhdl.append("        file_close(mem_file);\n")
        vhdl.append("        wait;\n")
        vhdl.append("    end process;\n")
    else:
        vhdl.append(f"    -- {mem_name} starts uninitialized\n")

    return "".join(vhdl)


def add_memory_init_to_testbench(testbench_code: str,
                                  mem_name: str,
                                  init_file: str,
                                  data_width: int = 32,
                                  mem_size: int = 1024) -> str:
    """
    Add memory initialization code to existing testbench.

    Args:
        testbench_code: Existing VHDL testbench code
        mem_name: Name of memory to initialize
        init_file: Path to initialization file
        data_width: Memory word width
        mem_size: Memory size in words

    Returns:
        Updated testbench code with memory initialization
    """
    # Find where to insert the initialization code
    # Look for "architecture testbench of" and insert after "begin"

    init_code = generate_vhdl_memory_reader(
        f"dut.{mem_name}",  # This won't work in VHDL, but shows intent
        mem_size,
        data_width,
        init_file
    )

    # Note: Direct memory access via dut.mem doesn't work in VHDL
    # This is a placeholder showing the intent
    # Real implementation would need shared variables or memory ports

    return testbench_code  # Return unchanged for now
