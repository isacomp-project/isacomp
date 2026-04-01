"""
RTLIL Backend for ISAComp

This backend generates Yosys RTLIL (.il) from ISA specifications and
ResourceGraph intermediate representations. The RTLIL can then be
processed by Yosys for CXXRTL simulation, synthesis, or further
transformations.
"""

from .rtlil_generator import RTLILGenerator, generate_rtlil
from .cxxrtl import rtlil_to_cxxrtl, rtlil_to_verilog, find_cxxrtl_include, compile_cxxrtl
from .testbench_generator import (
    CXXRTLTestbenchConfig,
    generate_cxxrtl_testbench,
    copy_test_scripts,
)

__all__ = [
    'RTLILGenerator',
    'generate_rtlil',
    'rtlil_to_cxxrtl',
    'rtlil_to_verilog',
    'find_cxxrtl_include',
    'compile_cxxrtl',
    'CXXRTLTestbenchConfig',
    'generate_cxxrtl_testbench',
    'copy_test_scripts',
]
