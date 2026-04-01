"""
VHDL Backend for ISAComp

This backend generates synthesizable VHDL code from ISA specifications.
"""

from .generator import VHDLGenerator, generate_vhdl, generate_vhdl_with_testbench
from .testbench_generator import VHDLTestbenchGenerator, VHDLTestbenchConfig
from .elf_loader import ELFLoader, load_elf_for_testbench
from .sim_utils import compile_vhdl, run_vhdl_simulation

__all__ = [
    'VHDLGenerator',
    'generate_vhdl',
    'generate_vhdl_with_testbench',
    'VHDLTestbenchGenerator',
    'VHDLTestbenchConfig',
    'ELFLoader',
    'load_elf_for_testbench',
    'compile_vhdl',
    'run_vhdl_simulation',
]
