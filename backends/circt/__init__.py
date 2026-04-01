"""
CIRCT Backend for ISAComp

This package provides MLIR/CIRCT code generation from ISA specifications,
enabling hardware synthesis through the CIRCT toolchain.
"""

from .circt_generator import CIRCTGenerator
from .circt_testbench import CIRCTTestbenchGenerator, generate_circt_testbench

__all__ = ['CIRCTGenerator', 'CIRCTTestbenchGenerator', 'generate_circt_testbench']
