"""
Chisel Backend for ISAComp

This backend generates Scala source code using the Chisel hardware construction
language from ISA specifications and ResourceGraph intermediate representations.
"""

from .chisel_generator import ChiselGenerator, generate_chisel

__all__ = [
    'ChiselGenerator',
    'generate_chisel',
]
