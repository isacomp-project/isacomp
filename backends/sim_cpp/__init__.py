"""
C++ Simulation Backend for ISAComp

This package provides a backend that generates C++ simulation code
from ResourceGraph representations. The generated code can be compiled
and run as a software simulation of the hardware design.

Example usage:
    from core.resource_graph import ResourceGraph
    from backends.sim_cpp import generate_cpp_sim, generate_cpp_testbench, generate_makefile

    # Load ISA specification
    graph = ResourceGraph.from_isa_file("my_processor.isa")

    # Generate C++ simulation code
    cpp_code = generate_cpp_sim(graph, "MyProcessor")

    # Generate testbench
    tb_code = generate_cpp_testbench("MyProcessor")

    # Generate Makefile
    makefile = generate_makefile("MyProcessor")

    # Write files
    with open("MyProcessor.hpp", "w") as f:
        f.write(cpp_code)
    with open("MyProcessor_tb.cpp", "w") as f:
        f.write(tb_code)
    with open("Makefile", "w") as f:
        f.write(makefile)
"""

from .generator import CppSimGenerator, generate_cpp_sim
from .testbench_generator import (
    CppTestbenchGenerator,
    CppMakefileGenerator,
    generate_cpp_testbench,
    generate_makefile
)
from .module_generators import (
    CppMuxGenerator,
    CppCounterGenerator,
    CppShifterGenerator,
    CppMemoryGenerator,
    create_mux_generator,
    create_counter_generator,
    create_shifter_generator,
    create_memory_generator
)

__all__ = [
    # Main generator
    'CppSimGenerator',
    'generate_cpp_sim',
    # Testbench generator
    'CppTestbenchGenerator',
    'CppMakefileGenerator',
    'generate_cpp_testbench',
    'generate_makefile',
    # Module generators
    'CppMuxGenerator',
    'CppCounterGenerator',
    'CppShifterGenerator',
    'CppMemoryGenerator',
    'create_mux_generator',
    'create_counter_generator',
    'create_shifter_generator',
    'create_memory_generator'
]
