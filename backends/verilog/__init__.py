"""
Verilog Backend for ISAComp

This backend generates synthesizable Verilog code from ISA specifications
and ResourceGraph intermediate representations.
"""

from .verilog_generator import VerilogGenerator, generate_verilog, generate_verilog_with_testbench
from .verilog_module_generators import (
    MuxGenerator,
    CounterGenerator,
    LatencyCounterGenerator,
    HazardDetectorGenerator,
    ReadOnlyCacheGenerator,
    ReadWriteCacheGenerator,
    TLBModuleGenerator,
    generate_module_library,
    create_module_generator_from_node,
)

__all__ = [
    'VerilogGenerator',
    'generate_verilog',
    'generate_verilog_with_testbench',
    'MuxGenerator',
    'CounterGenerator',
    'LatencyCounterGenerator',
    'HazardDetectorGenerator',
    'ReadOnlyCacheGenerator',
    'ReadWriteCacheGenerator',
    'TLBModuleGenerator',
    'generate_module_library',
    'create_module_generator_from_node',
]
