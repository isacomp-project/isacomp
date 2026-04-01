"""
C++ Simulation Testbench Generator for ISAComp

This module generates C++ testbench code that can drive simulations,
load programs, and verify execution results.
"""

from typing import Dict, List


class CppTestbenchGenerator:
    """Generate C++ testbench code for simulation."""

    def __init__(self, module_name: str = "processor", header_name: str = None):
        """
        Initialize the testbench generator.

        Args:
            module_name: Name of the processor class
            header_name: Name of the header file to include
        """
        self.module_name = module_name
        self.header_name = header_name or f"{module_name}.hpp"
        self.lines: List[str] = []
        self.indent_level = 0

    def _indent(self) -> str:
        """Return current indentation string."""
        return "    " * self.indent_level

    def _emit(self, line: str = ""):
        """Emit a line with current indentation."""
        if line:
            self.lines.append(self._indent() + line)
        else:
            self.lines.append("")

    def generate(self,
                 max_cycles: int = 10000,
                 trace_enabled: bool = True,
                 memory_files: Dict[str, str] = None) -> str:
        """
        Generate complete testbench code.

        Args:
            max_cycles: Maximum number of cycles to run
            trace_enabled: Whether to enable cycle tracing
            memory_files: Dict of memory_name -> filename for initialization

        Returns:
            C++ testbench source code
        """
        self.lines = []
        memory_files = memory_files or {}

        self._emit("#include <iostream>")
        self._emit("#include <fstream>")
        self._emit("#include <string>")
        self._emit("#include <cstdlib>")
        self._emit("#include <getopt.h>")
        self._emit(f'#include "{self.header_name}"')
        self._emit()

        self._generate_elf_loader()
        self._generate_main(max_cycles, trace_enabled, memory_files)

        return '\n'.join(self.lines)

    def _generate_elf_loader(self):
        """Generate a simple ELF loader function."""
        self._emit("// Simple binary program loader")
        self._emit(f"bool load_program({self.module_name}& cpu, const std::string& filename) {{")
        self.indent_level += 1
        self._emit("std::ifstream file(filename, std::ios::binary);")
        self._emit("if (!file) {")
        self.indent_level += 1
        self._emit('std::cerr << "Error: Cannot open file " << filename << std::endl;')
        self._emit("return false;")
        self.indent_level -= 1
        self._emit("}")
        self._emit()
        self._emit("// Read file into buffer")
        self._emit("file.seekg(0, std::ios::end);")
        self._emit("size_t size = file.tellg();")
        self._emit("file.seekg(0, std::ios::beg);")
        self._emit()
        self._emit("std::vector<uint8_t> buffer(size);")
        self._emit("file.read(reinterpret_cast<char*>(buffer.data()), size);")
        self._emit()
        self._emit("// Load into instruction memory (assuming word-aligned)")
        self._emit("for (size_t i = 0; i + 3 < size; i += 4) {")
        self.indent_level += 1
        self._emit("uint32_t word = buffer[i] | (buffer[i+1] << 8) | ")
        self._emit("               (buffer[i+2] << 16) | (buffer[i+3] << 24);")
        self._emit('cpu.write_imem(i / 4, word);  // Assuming imem exists')
        self.indent_level -= 1
        self._emit("}")
        self._emit()
        self._emit("return true;")
        self.indent_level -= 1
        self._emit("}")
        self._emit()

    def _generate_main(self, max_cycles: int, trace_enabled: bool,
                       memory_files: Dict[str, str]):
        """Generate the main function."""
        self._emit("int main(int argc, char* argv[]) {")
        self.indent_level += 1

        # Command line parsing
        self._emit("// Command line options")
        self._emit("std::string program_file;")
        self._emit(f"uint64_t max_cycles = {max_cycles};")
        self._emit(f"bool trace = {'true' if trace_enabled else 'false'};")
        self._emit("bool quiet = false;")
        self._emit()

        self._emit("int opt;")
        self._emit('while ((opt = getopt(argc, argv, "p:c:tqh")) != -1) {')
        self.indent_level += 1
        self._emit("switch (opt) {")
        self.indent_level += 1
        self._emit("case 'p': program_file = optarg; break;")
        self._emit("case 'c': max_cycles = std::stoull(optarg); break;")
        self._emit("case 't': trace = true; break;")
        self._emit("case 'q': quiet = true; break;")
        self._emit("case 'h':")
        self.indent_level += 1
        self._emit('std::cout << "Usage: " << argv[0] << " [options]" << std::endl;')
        self._emit('std::cout << "  -p FILE  Load program from FILE" << std::endl;')
        self._emit('std::cout << "  -c N     Run for N cycles (default: ' + str(max_cycles) + ')" << std::endl;')
        self._emit('std::cout << "  -t       Enable trace output" << std::endl;')
        self._emit('std::cout << "  -q       Quiet mode (no output)" << std::endl;')
        self._emit("return 0;")
        self.indent_level -= 1
        self._emit("default:")
        self.indent_level += 1
        self._emit("return 1;")
        self.indent_level -= 1
        self.indent_level -= 1
        self._emit("}")
        self.indent_level -= 1
        self._emit("}")
        self._emit()

        # Create processor instance
        self._emit(f"{self.module_name} cpu;")
        self._emit("cpu.reset();")
        self._emit()

        # Load memory files if specified
        if memory_files:
            self._emit("// Load memory initialization files")
            for mem_name, filename in memory_files.items():
                self._emit(f'if (!cpu.load_memory_hex("{filename}", "{mem_name}")) {{')
                self.indent_level += 1
                self._emit(f'std::cerr << "Warning: Failed to load {filename}" << std::endl;')
                self.indent_level -= 1
                self._emit("}")
            self._emit()

        # Load program if specified
        self._emit("// Load program if specified")
        self._emit("if (!program_file.empty()) {")
        self.indent_level += 1
        self._emit("if (!load_program(cpu, program_file)) {")
        self.indent_level += 1
        self._emit("return 1;")
        self.indent_level -= 1
        self._emit("}")
        self.indent_level -= 1
        self._emit("}")
        self._emit()

        # Main simulation loop
        self._emit("// Run simulation")
        self._emit("if (!quiet) {")
        self.indent_level += 1
        self._emit('std::cout << "Starting simulation..." << std::endl;')
        self.indent_level -= 1
        self._emit("}")
        self._emit()

        self._emit("while (!cpu.is_halted() && cpu.get_cycle_count() < max_cycles) {")
        self.indent_level += 1
        self._emit("if (trace) {")
        self.indent_level += 1
        self._emit("cpu.dump_state();")
        self.indent_level -= 1
        self._emit("}")
        self._emit("cpu.cycle();")
        self.indent_level -= 1
        self._emit("}")
        self._emit()

        # Final output
        self._emit("if (!quiet) {")
        self.indent_level += 1
        self._emit('std::cout << "Simulation complete after " << cpu.get_cycle_count() << " cycles" << std::endl;')
        self._emit("if (cpu.is_halted()) {")
        self.indent_level += 1
        self._emit('std::cout << "Processor halted" << std::endl;')
        self.indent_level -= 1
        self._emit("} else {")
        self.indent_level += 1
        self._emit('std::cout << "Max cycles reached" << std::endl;')
        self.indent_level -= 1
        self._emit("}")
        self._emit("cpu.dump_state();")
        self.indent_level -= 1
        self._emit("}")
        self._emit()

        self._emit("return 0;")
        self.indent_level -= 1
        self._emit("}")

        return '\n'.join(self.lines)


class CppMakefileGenerator:
    """Generate Makefile for building C++ simulation."""

    def __init__(self, module_name: str = "processor"):
        """
        Initialize the Makefile generator.

        Args:
            module_name: Name of the processor module
        """
        self.module_name = module_name

    def generate(self,
                 header_file: str = None,
                 testbench_file: str = None,
                 output_name: str = None) -> str:
        """
        Generate a Makefile for building the simulation.

        Args:
            header_file: Processor header file name
            testbench_file: Testbench source file name
            output_name: Output executable name

        Returns:
            Makefile content as a string
        """
        header_file = header_file or f"{self.module_name}.hpp"
        testbench_file = testbench_file or f"{self.module_name}_tb.cpp"
        output_name = output_name or f"{self.module_name}_sim"

        lines = [
            f"# Makefile for {self.module_name} simulation",
            "",
            "CXX = g++",
            "CXXFLAGS = -std=c++17 -O3 -Wall -Wextra",
            "LDFLAGS = ",
            "",
            f"TARGET = {output_name}",
            f"HEADER = {header_file}",
            f"TESTBENCH = {testbench_file}",
            "",
            "all: $(TARGET)",
            "",
            "$(TARGET): $(TESTBENCH) $(HEADER)",
            "\t$(CXX) $(CXXFLAGS) -o $@ $(TESTBENCH) $(LDFLAGS)",
            "",
            "debug: CXXFLAGS += -g -O0 -DDEBUG",
            "debug: $(TARGET)",
            "",
            "clean:",
            "\trm -f $(TARGET)",
            "",
            "run: $(TARGET)",
            "\t./$(TARGET)",
            "",
            ".PHONY: all clean debug run",
        ]

        return '\n'.join(lines)


def generate_cpp_testbench(module_name: str = "processor",
                            max_cycles: int = 10000,
                            trace_enabled: bool = True,
                            memory_files: Dict[str, str] = None) -> str:
    """
    Convenience function to generate C++ testbench code.

    Args:
        module_name: Name of the processor class
        max_cycles: Maximum simulation cycles
        trace_enabled: Enable cycle tracing
        memory_files: Memory initialization files

    Returns:
        C++ testbench source code
    """
    generator = CppTestbenchGenerator(module_name)
    return generator.generate(max_cycles, trace_enabled, memory_files)


def generate_makefile(module_name: str = "processor") -> str:
    """
    Convenience function to generate a Makefile.

    Args:
        module_name: Name of the processor module

    Returns:
        Makefile content
    """
    generator = CppMakefileGenerator(module_name)
    return generator.generate()
