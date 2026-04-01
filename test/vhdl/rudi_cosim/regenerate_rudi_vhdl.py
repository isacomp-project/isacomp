#!/usr/bin/env python3
"""
Regenerate Rudi post-egress VHDL with interface ports exposed.
This allows the testbench to drive inputs and observe outputs.
"""

import sys
import os

# Add project root to path (3 levels up from test/vhdl/rudi_cosim/)
project_root = os.path.join(os.path.dirname(__file__), '..', '..', '..')
sys.path.insert(0, project_root)

# Add ghdl-src for pyGHDL (only if not using venv pyGHDL)
# ghdl_src = os.path.join(project_root, 'ghdl-src')
# if os.path.exists(ghdl_src):
#     sys.path.insert(0, ghdl_src)

from frontends.vhdl.vhdl_multifile_parser import MultiFileVHDLParser
from backends.vhdl.generator import generate_vhdl

def main():
    # VHDL source files for Rudi CPU with memory wrapper
    vhdl_dir = os.path.join(project_root, 'frontends', 'vhdl', 'rudi-rv32i', 'src', 'cpu')

    # Memory wrapper file (includes integrated memory)
    mem_wrapper_file = os.path.join(os.path.dirname(__file__), '..', 'rudi_generated',
                                    'rudi_riscv_cpu_with_mem.vhd')

    vhdl_files = [
        # First parse all CPU components
        os.path.join(vhdl_dir, 'riscv_cpu.vhd'),
        os.path.join(vhdl_dir, 'program_counter.vhd'),
        os.path.join(vhdl_dir, 'register_file.vhd'),
        os.path.join(vhdl_dir, 'branch_test.vhd'),
        os.path.join(vhdl_dir, 'data_bus_mux_a.vhd'),
        os.path.join(vhdl_dir, 'data_bus_mux_b.vhd'),
        os.path.join(vhdl_dir, 'result_bus_mux.vhd'),
        os.path.join(vhdl_dir, 'decode.vhd'),
        os.path.join(vhdl_dir, 'alu.vhd'),
        os.path.join(vhdl_dir, 'shifter.vhd'),
        os.path.join(vhdl_dir, 'sign_extender.vhd'),
        # Then parse the memory wrapper as top-level
        mem_wrapper_file,
    ]

    print("Parsing VHDL files (including memory wrapper)...")

    # Parse all files to build hierarchical graph
    parser = MultiFileVHDLParser()
    parser.parse_files(vhdl_files)

    # Build unified graph from memory-wrapped CPU (not bare CPU core)
    graph = parser.build_hierarchical_graph("rudi_riscv_cpu_with_mem")
    print(f"Graph has {len(graph.nodes)} nodes and {len(graph.edges)} edges")

    # Define interface ports for the memory-wrapped entity
    # Includes debug outputs for cosimulation comparison
    # Format: 'name': ('direction', bit_width) or 'name': 'direction' for inferred width
    # Port names must match internal signal name suffixes (after stripping debug_ prefix)
    interface_ports = {
        # Inputs (1-bit unless specified)
        'clk': ('in', 1),
        'reset': ('in', 1),
        # Outputs - PC and data are 32-bit
        'debug_pc': ('out', 32),
        # Debug outputs for branch tracking (match internal signal suffixes)
        'debug_take_branch': ('out', 1),           # matches *_take_branch
        'debug_test_is_true': ('out', 1),          # matches *_test_is_true
        'debug_branch_test_enable': ('out', 1),    # matches *_branch_test_enable
        'debug_branch_test_mode': ('out', 3),      # matches *_branch_test_mode
        'debug_reg_read_data_a': ('out', 32),      # matches *_reg_read_data_a (32-bit data)
        'debug_reg_read_data_b': ('out', 32),      # matches *_reg_read_data_b (32-bit data)
        'debug_instr_reg': ('out', 32),            # matches *_instr_reg (32-bit instruction)
        'debug_a_eq_b': ('out', 1),                # matches *_a_eq_b
        # Register file debug (match internal signal suffixes)
        'debug_write_port_addr': ('out', 5),       # matches *_write_port_addr (5-bit)
        'debug_write_data': ('out', 32),           # matches *_write_data (32-bit)
        'debug_read_port_1_addr': ('out', 5),      # matches *_read_port_1_addr (5-bit)
        'debug_read_port_2_addr': ('out', 5),      # matches *_read_port_2_addr (5-bit)
    }

    print("Generating VHDL with interface ports...")
    vhdl_code = generate_vhdl(graph, "rudi_post_egress", interface_ports=interface_ports)

    # Write to output file
    output_file = os.path.join(os.path.dirname(__file__), '..', 'rudi_generated',
                               'rudi_post_egress.vhd')

    with open(output_file, 'w') as f:
        f.write(vhdl_code)

    print(f"Generated {len(vhdl_code)} characters of VHDL")
    print(f"Written to {output_file}")

if __name__ == "__main__":
    main()
