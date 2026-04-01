"""
Clash HDL Backend for ISAComp

This module provides Clash (Haskell-based HDL) code generation from
ResourceGraph representations. Clash is a functional hardware description
language that compiles to Verilog, VHDL, or SystemVerilog.

Key features:
- Generates synthesizable Clash code
- Uses Mealy machine model for sequential logic
- Compiles to Verilog/VHDL via the Clash compiler

Reference: https://clash-lang.org/
"""

from .clash_generator import ClashGenerator, generate_clash
from .clash_graph_generator import ClashPipelineGenerator, generate_clash_pipeline
from .testbench_generator import (
    copy_test_infrastructure,
    generate_clash_testbench,
)

__all__ = [
    'ClashGenerator',
    'generate_clash',
    'ClashPipelineGenerator',
    'generate_clash_pipeline',
    'copy_test_infrastructure',
    'generate_clash_testbench',
]
