"""
HardCaml Backend for ISAComp

This backend generates OCaml code using the HardCaml library from ISA specifications
and ResourceGraph intermediate representations. The generated OCaml code, when compiled
and executed, produces synthesizable Verilog via HardCaml's RTL output.
"""

from .hardcaml_generator import HardCamlGenerator, generate_hardcaml

__all__ = [
    'HardCamlGenerator',
    'generate_hardcaml',
]
