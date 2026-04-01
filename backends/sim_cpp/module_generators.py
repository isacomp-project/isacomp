"""
C++ Simulation Module Generators for ISAComp

This module provides helper generators for complex hardware components
such as ALUs, multiplexers, and counters in C++ simulation code.

Unlike the Verilog/VHDL backends which generate separate modules,
the C++ simulation backend typically inlines these operations.
These generators provide standardized code patterns and can be used
for generating standalone C++ classes when needed.
"""

from typing import List, Tuple


class CppMuxGenerator:
    """Generate C++ multiplexer implementation."""

    def __init__(self, width: int = 32, name: str = "Mux"):
        """
        Initialize the multiplexer generator.

        Args:
            width: Data width in bits
            name: Class/function name
        """
        self.width = width
        self.name = name
        self.cpp_type = self._get_cpp_type(width)

    def _get_cpp_type(self, width: int) -> str:
        if width <= 8:
            return "uint8_t"
        elif width <= 16:
            return "uint16_t"
        elif width <= 32:
            return "uint32_t"
        else:
            return "uint64_t"

    def generate_binary_mux(self, sel: str, a: str, b: str) -> str:
        """Generate inline binary mux expression."""
        return f"(({sel}) ? ({a}) : ({b}))"

    def generate_priority_mux(self, cases: List[Tuple[str, str]], default: str) -> str:
        """
        Generate cascaded priority mux expression.

        Args:
            cases: List of (select, value) tuples in priority order
            default: Default value expression
        """
        result = default
        for sel, val in reversed(cases):
            result = f"(({sel}) ? ({val}) : ({result}))"
        return result

    def generate_one_hot_mux(self, cases: List[Tuple[str, str]], default: str = "0") -> str:
        """
        Generate one-hot mux expression (OR of AND-gated inputs).

        Args:
            cases: List of (select, value) tuples
            default: Default value (typically 0)
        """
        if not cases:
            return default

        terms = []
        for sel, val in cases:
            terms.append(f"(({sel}) ? ({val}) : 0)")

        return " | ".join(terms) if terms else default


class CppCounterGenerator:
    """Generate C++ counter implementation."""

    def __init__(self, width: int = 32, name: str = "Counter"):
        """
        Initialize the counter generator.

        Args:
            width: Counter width in bits
            name: Class/function name
        """
        self.width = width
        self.name = name
        self.cpp_type = self._get_cpp_type(width)

    def _get_cpp_type(self, width: int) -> str:
        if width <= 8:
            return "uint8_t"
        elif width <= 16:
            return "uint16_t"
        elif width <= 32:
            return "uint32_t"
        else:
            return "uint64_t"

    def generate_class(self, wrap: bool = True) -> str:
        """Generate a standalone counter class."""
        max_val = (1 << self.width) - 1
        mask = f"0x{max_val:X}"

        wrap_logic = f"return (count + 1) & {mask};" if wrap else \
                     f"return (count < {mask}) ? count + 1 : {mask};"

        return f'''
class {self.name} {{
public:
    {self.cpp_type} count = 0;

    void reset() {{ count = 0; }}

    void increment() {{
        count = next_value(count);
    }}

    void decrement() {{
        count = prev_value(count);
    }}

    static {self.cpp_type} next_value({self.cpp_type} count) {{
        {wrap_logic}
    }}

    static {self.cpp_type} prev_value({self.cpp_type} count) {{
        return (count - 1) & {mask};
    }}
}};
'''

    def generate_inline_increment(self, var: str) -> str:
        """Generate inline increment expression."""
        mask = f"0x{(1 << self.width) - 1:X}"
        return f"(({var} + 1) & {mask})"

    def generate_inline_decrement(self, var: str) -> str:
        """Generate inline decrement expression."""
        mask = f"0x{(1 << self.width) - 1:X}"
        return f"(({var} - 1) & {mask})"


class CppShifterGenerator:
    """Generate C++ barrel shifter implementation."""

    def __init__(self, width: int = 32):
        """
        Initialize the shifter generator.

        Args:
            width: Data width in bits
        """
        self.width = width
        self.cpp_type = self._get_cpp_type(width)
        self.signed_type = self._get_signed_type(width)

    def _get_cpp_type(self, width: int) -> str:
        if width <= 8:
            return "uint8_t"
        elif width <= 16:
            return "uint16_t"
        elif width <= 32:
            return "uint32_t"
        else:
            return "uint64_t"

    def _get_signed_type(self, width: int) -> str:
        if width <= 8:
            return "int8_t"
        elif width <= 16:
            return "int16_t"
        elif width <= 32:
            return "int32_t"
        else:
            return "int64_t"

    def generate_sll(self, val: str, amt: str) -> str:
        """Generate logical left shift."""
        mask = f"0x{(1 << self.width) - 1:X}ULL"
        shift_mask = self.width - 1
        return f"(({val} << ({amt} & {shift_mask})) & {mask})"

    def generate_srl(self, val: str, amt: str) -> str:
        """Generate logical right shift."""
        shift_mask = self.width - 1
        return f"({val} >> ({amt} & {shift_mask}))"

    def generate_sra(self, val: str, amt: str) -> str:
        """Generate arithmetic right shift."""
        shift_mask = self.width - 1
        return f"(({self.signed_type}){val} >> ({amt} & {shift_mask}))"


class CppMemoryGenerator:
    """Generate C++ memory array implementation."""

    def __init__(self, data_width: int = 32, addr_width: int = 10,
                 name: str = "Memory"):
        """
        Initialize the memory generator.

        Args:
            data_width: Data width in bits
            addr_width: Address width in bits
            name: Class/function name
        """
        self.data_width = data_width
        self.addr_width = addr_width
        self.name = name
        self.depth = 1 << addr_width
        self.data_type = self._get_cpp_type(data_width)
        self.addr_type = self._get_cpp_type(addr_width)

    def _get_cpp_type(self, width: int) -> str:
        if width <= 8:
            return "uint8_t"
        elif width <= 16:
            return "uint16_t"
        elif width <= 32:
            return "uint32_t"
        else:
            return "uint64_t"

    def generate_class(self) -> str:
        """Generate a standalone memory class."""
        addr_mask = f"0x{(1 << self.addr_width) - 1:X}"

        return f'''
class {self.name} {{
public:
    std::array<{self.data_type}, {self.depth}> data = {{}};

    {self.data_type} read({self.addr_type} addr) const {{
        return data[addr & {addr_mask}];
    }}

    void write({self.addr_type} addr, {self.data_type} val) {{
        data[addr & {addr_mask}] = val;
    }}

    void clear() {{
        data.fill(0);
    }}

    bool load_hex(const std::string& filename) {{
        std::ifstream file(filename);
        if (!file) return false;
        std::string line;
        size_t idx = 0;
        while (std::getline(file, line) && idx < {self.depth}) {{
            if (line.empty() || line[0] == '/' || line[0] == '#') continue;
            data[idx++] = std::stoull(line, nullptr, 16);
        }}
        return true;
    }}
}};
'''


def create_mux_generator(width: int = 32) -> CppMuxGenerator:
    """Factory function for Mux generator."""
    return CppMuxGenerator(width)


def create_counter_generator(width: int = 32) -> CppCounterGenerator:
    """Factory function for Counter generator."""
    return CppCounterGenerator(width)


def create_shifter_generator(width: int = 32) -> CppShifterGenerator:
    """Factory function for Shifter generator."""
    return CppShifterGenerator(width)


def create_memory_generator(data_width: int = 32,
                            addr_width: int = 10) -> CppMemoryGenerator:
    """Factory function for Memory generator."""
    return CppMemoryGenerator(data_width, addr_width)
