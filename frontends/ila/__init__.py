"""
ILA (Instruction-Level Abstraction) frontend for isacomp.

This package provides support for parsing ILA models exported from ILAng
into isacomp's ResourceGraph intermediate representation.
"""

from .ila_parser_real import RealILAParser, parse_ila_json_file, parse_ila_json

__all__ = ['RealILAParser', 'parse_ila_json_file', 'parse_ila_json']
