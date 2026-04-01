"""
ELF loader utility for VHDL testbenches.

This module extracts program code and data from ELF files and converts them
to formats usable by VHDL testbenches (hex arrays, memory initialization).
"""

from typing import List, Optional, Tuple, Dict
from pathlib import Path
import struct


class ELFLoader:
    """Load and parse ELF files for VHDL testbench generation."""

    def __init__(self, elf_path: Path):
        """Initialize ELF loader with path to ELF file."""
        self.elf_path = Path(elf_path)
        self.memory_data: Dict[int, int] = {}  # address -> 32-bit word
        self.symbols: Dict[str, int] = {}  # symbol name -> address
        self._load_elf()

    def _load_elf(self):
        """Load ELF file using Python's struct module or pyelftools if available."""
        try:
            from elftools.elf.elffile import ELFFile
            from elftools.elf.sections import SymbolTableSection
            self._load_with_pyelftools()
        except ImportError:
            # Fallback to simple binary reading
            print("Warning: pyelftools not available, using simple binary loader")
            self._load_simple()

    def _load_with_pyelftools(self):
        """Load ELF using pyelftools library."""
        try:
            from elftools.elf.elffile import ELFFile
            from elftools.elf.sections import SymbolTableSection

            with open(self.elf_path, 'rb') as f:
                elf = ELFFile(f)

                # Load program sections
                for segment in elf.iter_segments():
                    if segment['p_type'] == 'PT_LOAD':
                        vaddr = segment['p_vaddr']
                        data = segment.data()

                        # Store as 32-bit words
                        for i in range(0, len(data), 4):
                            if i + 4 <= len(data):
                                word = struct.unpack('<I', data[i:i+4])[0]
                                self.memory_data[vaddr + i] = word

                # Load symbols
                for section in elf.iter_sections():
                    if isinstance(section, SymbolTableSection):
                        for symbol in section.iter_symbols():
                            if symbol.name:
                                self.symbols[symbol.name] = symbol['st_value']

        except Exception as e:
            print(f"Error loading ELF with pyelftools: {e}")
            self._load_simple()

    def _load_simple(self):
        """Simple ELF loader for basic cases."""
        # This is a simplified loader that assumes the ELF is small and
        # we can just read the raw binary data
        with open(self.elf_path, 'rb') as f:
            # Read ELF header
            magic = f.read(4)
            if magic != b'\x7fELF':
                raise ValueError("Not a valid ELF file")

            # For simplicity, just read all data starting from a known offset
            # This is a very simplified approach
            f.seek(0)
            data = f.read()

            # Try to find .text section (this is very simplified)
            # In a real implementation, we'd parse the section headers
            # For now, just load everything from address 0
            for i in range(0, len(data) - 4, 4):
                word = struct.unpack('<I', data[i:i+4])[0]
                if word != 0:  # Only store non-zero words
                    self.memory_data[i] = word

    def get_memory_array(self, base_addr: int = 0, size: int = 1024) -> List[int]:
        """
        Get memory array for testbench initialization.

        Args:
            base_addr: Base address to start from
            size: Number of 32-bit words in the array

        Returns:
            List of 32-bit words (zero-filled if no data at that address)
        """
        array = []
        for i in range(size):
            addr = base_addr + (i * 4)
            word = self.memory_data.get(addr, 0)
            array.append(word)
        return array

    def get_symbol_address(self, symbol_name: str) -> Optional[int]:
        """Get address of a symbol (e.g., 'pass', 'fail')."""
        return self.symbols.get(symbol_name)

    def generate_hex_file(self, output_path: Path, base_addr: int = 0, size: int = 1024):
        """
        Generate hex file for VHDL memory initialization.

        Format: One 32-bit hex word per line (8 hex digits)
        """
        array = self.get_memory_array(base_addr, size)
        with open(output_path, 'w') as f:
            for word in array:
                f.write(f"{word:08x}\n")

    def generate_vhdl_array(self, array_name: str = "program_data",
                           base_addr: int = 0, size: int = 1024) -> str:
        """
        Generate VHDL constant array declaration with program data.

        Returns:
            VHDL code for constant array
        """
        array = self.get_memory_array(base_addr, size)

        vhdl = []
        vhdl.append(f"    type memory_array_type is array (0 to {size-1}) of std_logic_vector(31 downto 0);\n")
        vhdl.append(f"    constant {array_name} : memory_array_type := (\n")

        for i, word in enumerate(array):
            if i < len(array) - 1:
                vhdl.append(f"        {i} => x\"{word:08x}\",\n")
            else:
                vhdl.append(f"        {i} => x\"{word:08x}\"\n")

        vhdl.append("    );\n")

        return "".join(vhdl)


def load_elf_for_testbench(elf_path: Path,
                           imem_size: int = 1024,
                           dmem_size: int = 1024,
                           find_pass_fail: bool = True) -> Tuple[List[int], List[int], Optional[int], Optional[int]]:
    """
    Load ELF file and extract data for VHDL testbench.

    Args:
        elf_path: Path to ELF file
        imem_size: Size of instruction memory in words
        dmem_size: Size of data memory in words
        find_pass_fail: Whether to look for 'pass' and 'fail' symbols

    Returns:
        Tuple of (imem_data, dmem_data, pass_addr, fail_addr)
    """
    loader = ELFLoader(elf_path)

    # Get full memory map
    full_memory = loader.memory_data

    # Both imem and dmem get the full memory map (unified address space)
    # In hardware they would be separate ports to the same memory
    imem_data = []
    dmem_data = []

    # Build both arrays from address 0
    for i in range(max(imem_size, dmem_size)):
        addr = i * 4
        word = full_memory.get(addr, 0)
        if i < imem_size:
            imem_data.append(word)
        if i < dmem_size:
            dmem_data.append(word)

    # Get pass/fail addresses if requested
    pass_addr = None
    fail_addr = None
    if find_pass_fail:
        pass_addr = loader.get_symbol_address('pass')
        fail_addr = loader.get_symbol_address('fail')

        # Also try alternative symbol names
        if pass_addr is None:
            pass_addr = loader.get_symbol_address('_pass')
        if fail_addr is None:
            fail_addr = loader.get_symbol_address('_fail')

    return imem_data, dmem_data, pass_addr, fail_addr


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python vhdl_elf_loader.py <elf_file> [output.hex]")
        sys.exit(1)

    elf_file = Path(sys.argv[1])
    output_file = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("program.hex")

    loader = ELFLoader(elf_file)

    # Generate hex file
    loader.generate_hex_file(output_file)
    print(f"Generated {output_file}")

    # Print symbols
    if loader.symbols:
        print("\nSymbols found:")
        for name, addr in sorted(loader.symbols.items(), key=lambda x: x[1]):
            print(f"  {name:20s} = 0x{addr:08x}")

    # Print some statistics
    if loader.memory_data:
        min_addr = min(loader.memory_data.keys())
        max_addr = max(loader.memory_data.keys())
        print(f"\nMemory range: 0x{min_addr:08x} - 0x{max_addr:08x}")
        print(f"Total words: {len(loader.memory_data)}")
