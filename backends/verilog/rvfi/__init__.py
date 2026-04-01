"""
RVFI (RISC-V Formal Interface) support for the Verilog backend.

Provides RVFI signal generation, testbench generation, and integration
with the Verilog code generator.
"""

from .rvfi_generator import RVFIConfig, RVFISignalGenerator, generate_rvfi_wrapper
from .rvfi_testbench_generator import (
    RVFITestbenchConfig,
    RVFITestbenchGenerator,
    generate_rvfi_testbench_files,
)
from .verilog_rvfi_integration import generate_verilog_with_rvfi

__all__ = [
    'RVFIConfig',
    'RVFISignalGenerator',
    'generate_rvfi_wrapper',
    'RVFITestbenchConfig',
    'RVFITestbenchGenerator',
    'generate_rvfi_testbench_files',
    'generate_verilog_with_rvfi',
]
