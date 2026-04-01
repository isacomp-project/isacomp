"""
Verilog/SystemVerilog frontend for isacomp.

This package provides support for parsing Verilog and SystemVerilog files
into isacomp's ResourceGraph intermediate representation using pyslang.
"""

from .verilog_parser import VerilogParser, parse_verilog_file, parse_verilog_text

__all__ = ['VerilogParser', 'parse_verilog_file', 'parse_verilog_text']
