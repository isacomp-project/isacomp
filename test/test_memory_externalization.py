#!/usr/bin/env python3
"""
Test memory externalization with valid-ready handshake protocol.

This test verifies:
1. Memory externalization marking works correctly
2. External port generation with valid-ready handshake
3. Internal memory array is skipped for externalized memories
4. Read/write port connections are generated correctly
5. Multi-port support: memories with multiple access points (like umem[pc], umem[ea])
   generate separate external ports (umem_pc_..., umem_ea_...)
"""

import os
import sys
import unittest

# Add project root to path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from core.resource_graph import ResourceGraph, Node, Edge
from opt.memory.memory_externalization import (
    MemoryExternalizationSpec,
    apply_memory_externalization,
    get_externalized_memories,
    MemoryPortInfo
)
from backends.verilog import VerilogGenerator


class TestMemoryExternalization(unittest.TestCase):
    """Test memory externalization functionality."""

    def setUp(self):
        """Create a simple test graph with a memory node."""
        self.graph = ResourceGraph()

        # Create a simple memory node (umem = unified memory)
        umem = Node('umem', {
            'type': 'isa_state mem',
            'name': 'umem',
            'is_memory': True,
            'bit_width': 32,
            'array_depth': 24,  # 24-bit address width
        })
        self.graph.add_node(umem)

        # Create a simple register node
        pc = Node('pc', {
            'type': 'isa_state',
            'name': 'pc',
            'bit_width': 32,
        })
        pc.is_arch_state = True
        self.graph.add_node(pc)

    def test_apply_externalization_single_cycle(self):
        """Test marking a memory for externalization (single-cycle, no valid-ready)."""
        spec = MemoryExternalizationSpec(
            memory_name='umem',
            create_read_port=True,
            create_write_port=True,
            variable_latency=False  # Single cycle, no handshake
        )

        result = apply_memory_externalization(self.graph, spec)

        self.assertTrue(result)

        # Verify memory node is marked
        umem_node = self.graph.nodes['umem']
        self.assertTrue(umem_node.data.get('externalized'))
        self.assertTrue(umem_node.data.get('externalize_read'))
        self.assertTrue(umem_node.data.get('externalize_write'))
        self.assertFalse(umem_node.data.get('use_valid_ready'))

        # Check externalized list
        externalized = get_externalized_memories(self.graph)
        self.assertIn('umem', externalized)

    def test_apply_externalization_variable_latency(self):
        """Test marking a memory for externalization with variable latency."""
        spec = MemoryExternalizationSpec(
            memory_name='umem',
            create_read_port=True,
            create_write_port=True,
            variable_latency=True  # Variable latency, use valid-ready handshake
        )

        result = apply_memory_externalization(self.graph, spec)

        self.assertTrue(result)

        # Verify memory node is marked with valid-ready
        umem_node = self.graph.nodes['umem']
        self.assertTrue(umem_node.data.get('externalized'))
        self.assertTrue(umem_node.data.get('use_valid_ready'))
        self.assertTrue(umem_node.variable_latency)

    def test_externalization_not_found(self):
        """Test externalization of non-existent memory returns False."""
        spec = MemoryExternalizationSpec(
            memory_name='nonexistent',
            create_read_port=True,
            create_write_port=True
        )

        result = apply_memory_externalization(self.graph, spec)

        self.assertFalse(result)

    def test_memory_port_info_read(self):
        """Test MemoryPortInfo generates correct read port signals."""
        port_info = MemoryPortInfo(
            memory_name='umem',
            port_type='read',
            addr_width=24,
            data_width=32
        )

        # Test without valid-ready (single-cycle)
        signals = port_info.get_port_signals(variable_latency=False)

        self.assertIn('umem_read_req_addr', signals)
        self.assertEqual(signals['umem_read_req_addr']['direction'], 'output')
        self.assertEqual(signals['umem_read_req_addr']['width'], 24)

        self.assertIn('umem_read_req_valid', signals)
        self.assertEqual(signals['umem_read_req_valid']['direction'], 'output')

        self.assertIn('umem_read_resp_data', signals)
        self.assertEqual(signals['umem_read_resp_data']['direction'], 'input')
        self.assertEqual(signals['umem_read_resp_data']['width'], 32)

        # No resp_ready for single-cycle
        self.assertNotIn('umem_read_resp_ready', signals)

        # Test with valid-ready (variable latency)
        signals_vr = port_info.get_port_signals(variable_latency=True)
        self.assertIn('umem_read_resp_ready', signals_vr)
        self.assertEqual(signals_vr['umem_read_resp_ready']['direction'], 'input')

    def test_memory_port_info_write(self):
        """Test MemoryPortInfo generates correct write port signals."""
        port_info = MemoryPortInfo(
            memory_name='umem',
            port_type='write',
            addr_width=24,
            data_width=32
        )

        signals = port_info.get_port_signals(variable_latency=True)

        self.assertIn('umem_write_req_addr', signals)
        self.assertIn('umem_write_req_data', signals)
        self.assertIn('umem_write_req_we', signals)
        self.assertIn('umem_write_req_valid', signals)
        self.assertIn('umem_write_resp_ready', signals)

        self.assertEqual(signals['umem_write_req_we']['width'], 4)  # 32/8 = 4 bytes


class TestVerilogGeneratorExternalization(unittest.TestCase):
    """Test Verilog generation for externalized memories."""

    def setUp(self):
        """Create a graph with externalized memory."""
        self.graph = ResourceGraph()

        # Create externalized memory
        umem = Node('umem', {
            'type': 'isa_state mem',
            'name': 'umem',
            'is_memory': True,
            'bit_width': 32,
            'array_depth': 24,
            'externalized': True,
            'externalize_read': True,
            'externalize_write': True,
            'use_valid_ready': True,  # Variable latency
        })
        self.graph.add_node(umem)

        # Create internal memory (not externalized)
        rf = Node('rf', {
            'type': 'isa_state mem',
            'name': 'rf',
            'is_memory': True,
            'bit_width': 32,
            'array_depth': 5,  # 32 registers
        })
        self.graph.add_node(rf)

        # Create PC register
        pc = Node('pc', {
            'type': 'isa_state',
            'name': 'pc',
            'bit_width': 32,
        })
        pc.is_arch_state = True
        self.graph.add_node(pc)

    def test_external_memory_not_declared(self):
        """Test that externalized memory is not declared as internal array."""
        generator = VerilogGenerator(self.graph, "test_processor")
        verilog = generator.generate()

        # External memory should NOT have internal array declaration
        self.assertNotIn("reg [31:0] umem [0:", verilog)

        # But internal memory SHOULD have declaration
        self.assertIn("reg [31:0] rf [0:", verilog)

    def test_external_ports_generated(self):
        """Test that external memory ports are generated in module header."""
        generator = VerilogGenerator(self.graph, "test_processor")
        verilog = generator.generate()

        # Read ports
        self.assertIn("umem_read_req_addr", verilog)
        self.assertIn("umem_read_req_valid", verilog)
        self.assertIn("umem_read_resp_data", verilog)
        self.assertIn("umem_read_resp_ready", verilog)

        # Write ports
        self.assertIn("umem_write_req_addr", verilog)
        self.assertIn("umem_write_req_data", verilog)
        self.assertIn("umem_write_req_valid", verilog)
        self.assertIn("umem_write_resp_ready", verilog)

    def test_stall_signal_generated(self):
        """Test that stall signal is generated for variable-latency memory."""
        generator = VerilogGenerator(self.graph, "test_processor")
        verilog = generator.generate()

        # Combined stall signal should be generated
        self.assertIn("mem_ext_stall", verilog)


class TestMemoryWrapperGeneration(unittest.TestCase):
    """Test generation of memory wrapper module."""

    def test_generate_memory_wrapper(self):
        """Test that memory wrapper module is generated correctly."""
        graph = ResourceGraph()

        umem = Node('umem', {
            'type': 'isa_state mem',
            'name': 'umem',
            'is_memory': True,
            'bit_width': 32,
            'array_depth': 24,
            'externalized': True,
            'externalize_read': True,
            'externalize_write': True,
            'use_valid_ready': True,
        })
        graph.add_node(umem)

        generator = VerilogGenerator(graph, "test_processor")
        generator.generate()  # This populates externalized_memories

        wrapper = generator.generate_memory_wrapper('umem')

        # Verify wrapper contains expected ports
        self.assertIn("module umem_memory", wrapper)
        self.assertIn("read_req_addr", wrapper)
        self.assertIn("read_req_valid", wrapper)
        self.assertIn("read_resp_data", wrapper)
        self.assertIn("read_resp_ready", wrapper)
        self.assertIn("write_req_addr", wrapper)
        self.assertIn("write_req_data", wrapper)
        self.assertIn("write_resp_ready", wrapper)


class TestMultiPortMemoryExternalization(unittest.TestCase):
    """Test multi-port memory externalization (e.g., umem[pc], umem[ea])."""

    def setUp(self):
        """Create a graph with memory and multiple access points."""
        self.graph = ResourceGraph()

        # Create externalized memory
        umem = Node('umem', {
            'type': 'isa_state mem',
            'name': 'umem',
            'is_memory': True,
            'bit_width': 32,
            'array_depth': 24,
            'externalized': True,
            'externalize_read': True,
            'externalize_write': True,
            'use_valid_ready': True,
        })
        self.graph.add_node(umem)

        # Create PC register (used as instruction fetch address)
        pc = Node('pc', {
            'type': 'isa_state',
            'name': 'pc',
            'bit_width': 32,
        })
        pc.is_arch_state = True
        self.graph.add_node(pc)

        # Create EA register (used as data access address)
        ea = Node('ea', {
            'type': 'var',
            'name': 'ea',
            'bit_width': 32,
        })
        self.graph.add_node(ea)

        # Create instruction fetch access: umem[pc]_rd
        instr_fetch = Node('umem[pc]_rd', {
            'type': 'array_access',
            'name': 'umem[pc]_rd',
            'bit_width': 32,
        })
        self.graph.add_node(instr_fetch)

        # Create data read access: umem[ea]_rd
        data_read = Node('umem[ea]_rd', {
            'type': 'array_access',
            'name': 'umem[ea]_rd',
            'bit_width': 32,
        })
        self.graph.add_node(data_read)

        # Create edges for instruction fetch
        edge1 = Edge(umem, instr_fetch, data={'type': 'array_base', 'position': 0})
        self.graph.add_edge(edge1)
        edge2 = Edge(pc, instr_fetch, data={'type': 'array_index', 'position': 1})
        self.graph.add_edge(edge2)

        # Create edges for data read
        edge3 = Edge(umem, data_read, data={'type': 'array_base', 'position': 0})
        self.graph.add_edge(edge3)
        edge4 = Edge(ea, data_read, data={'type': 'array_index', 'position': 1})
        self.graph.add_edge(edge4)

    def test_extract_memory_port_name(self):
        """Test the _extract_memory_port_name helper function."""
        generator = VerilogGenerator(self.graph, "test_processor")

        # Test bracket notation
        self.assertEqual(generator._extract_memory_port_name('umem[pc]_rd', 'umem'), 'umem_pc')
        self.assertEqual(generator._extract_memory_port_name('umem[ea]_rd', 'umem'), 'umem_ea')
        self.assertEqual(generator._extract_memory_port_name('umem[ea]_wr', 'umem'), 'umem_ea')

        # Test underscore notation (after sanitization)
        self.assertEqual(generator._extract_memory_port_name('umem_pc__rd', 'umem'), 'umem_pc')
        self.assertEqual(generator._extract_memory_port_name('umem_ea__rd', 'umem'), 'umem_ea')

        # Test shared port (should return just memory name)
        self.assertEqual(generator._extract_memory_port_name('umem_shared_rd', 'umem'), 'umem')
        self.assertEqual(generator._extract_memory_port_name('umem_rd', 'umem'), 'umem')

    def test_multi_port_generates_separate_ports(self):
        """Test that multiple memory access points generate separate external ports."""
        generator = VerilogGenerator(self.graph, "test_processor")
        verilog = generator.generate()

        # Should have separate ports for pc and ea
        self.assertIn("umem_pc_read_req_addr", verilog)
        self.assertIn("umem_pc_read_resp_data", verilog)
        self.assertIn("umem_ea_read_req_addr", verilog)
        self.assertIn("umem_ea_read_resp_data", verilog)

    def test_multi_port_connections(self):
        """Test that multi-port connections are generated correctly."""
        generator = VerilogGenerator(self.graph, "test_processor")
        verilog = generator.generate()

        # PC port should connect to pc signal
        self.assertIn("umem_pc_read_req_addr", verilog)

        # EA port should connect to ea signal
        self.assertIn("umem_ea_read_req_addr", verilog)

    def test_multi_port_stall_signals(self):
        """Test that stall signals are generated for each port."""
        generator = VerilogGenerator(self.graph, "test_processor")
        verilog = generator.generate()

        # Should have stall signals for each port with valid-ready
        self.assertIn("mem_ext_stall", verilog)

        # The stall signal should OR together multiple conditions
        # (one for each port with valid-ready handshake)
        if "umem_pc_read_req_valid" in verilog:
            self.assertIn("umem_pc_read_resp_ready", verilog)


class TestPortNameExtraction(unittest.TestCase):
    """Test edge cases of port name extraction."""

    def test_complex_port_names(self):
        """Test extraction of port names from complex node IDs."""
        graph = ResourceGraph()
        umem = Node('umem', {
            'type': 'isa_state mem',
            'name': 'umem',
            'is_memory': True,
            'bit_width': 32,
            'array_depth': 24,
        })
        graph.add_node(umem)

        generator = VerilogGenerator(graph, "test")

        # Various port name formats
        test_cases = [
            ('umem[pc]_rd', 'umem', 'umem_pc'),
            ('umem[ea]_wr', 'umem', 'umem_ea'),
            ('dmem[addr]_rd', 'dmem', 'dmem_addr'),
            ('imem[fetch_addr]_rd', 'imem', 'imem_fetch_addr'),
            ('umem_shared_rd', 'umem', 'umem'),  # shared = generic
            ('rf[rd]_wr', 'rf', 'rf_rd'),
        ]

        for port_name, mem_name, expected in test_cases:
            result = generator._extract_memory_port_name(port_name, mem_name)
            self.assertEqual(result, expected,
                           f"Expected {expected} for {port_name}, got {result}")


if __name__ == '__main__':
    unittest.main()
