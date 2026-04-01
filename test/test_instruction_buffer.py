"""
Test suite for instruction_buffer_optimization module.

Tests the instruction buffer optimization including:
- InstructionBufferSpec validation and parameter calculation
- Buffer node creation and graph transformation
- Fetch interface wiring
- Instruction width (consume) interface wiring
- Output data redirection
- PC-based access detection (imem[pc], imem[pc+1], imem[pc+N])
- Flush + redirect interface for branch misprediction
- Multi-offset output ports
- Verilog generation for instruction buffer modules
"""

import unittest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.resource_graph import ResourceGraph, Node, Edge
from opt.fetch.instruction_buffer_optimization import (
    InstructionBufferSpec,
    InstructionBufferOptimization,
    apply_instruction_buffer,
    get_ibuf_nodes,
    get_ibuf_info,
)
from backends.verilog.verilog_module_generators import (
    InstructionBufferGenerator,
    create_module_generator_from_node,
)


class TestInstructionBufferSpec(unittest.TestCase):
    """Test the InstructionBufferSpec dataclass."""

    def test_basic_spec_creation(self):
        """Test creating a basic instruction buffer spec."""
        spec = InstructionBufferSpec(
            imem_node='imem',
            pc_node='pc',
            instr_width_node='instr_len',
            fetch_width=32,
            buffer_size=4,
            address_width=32
        )

        self.assertEqual(spec.imem_node, 'imem')
        self.assertEqual(spec.pc_node, 'pc')
        self.assertEqual(spec.instr_width_node, 'instr_len')
        self.assertEqual(spec.buffer_name, 'imem_ibuf')
        self.assertEqual(spec.fetch_width, 32)
        self.assertEqual(spec.buffer_size, 4)

    def test_spec_with_custom_name(self):
        """Test buffer spec with custom name."""
        spec = InstructionBufferSpec(
            imem_node='imem',
            pc_node='pc',
            instr_width_node='instr_len',
            buffer_name='my_ibuf'
        )
        self.assertEqual(spec.buffer_name, 'my_ibuf')

    def test_derived_parameters(self):
        """Test derived parameter calculations."""
        spec = InstructionBufferSpec(
            imem_node='imem',
            pc_node='pc',
            instr_width_node='instr_len',
            fetch_width=32,    # 4 bytes per fetch
            buffer_size=4,     # 4 entries
            address_width=32
        )

        self.assertEqual(spec.fetch_bytes, 4)
        self.assertEqual(spec.buffer_capacity_bits, 128)   # 4 * 32
        self.assertEqual(spec.buffer_capacity_bytes, 16)    # 4 * 4

    def test_ptr_width_calculation(self):
        """Test pointer width calculation for buffer indexing."""
        spec = InstructionBufferSpec(
            imem_node='imem',
            pc_node='pc',
            instr_width_node='instr_len',
            fetch_width=32,    # 4 bytes
            buffer_size=4      # 16 bytes total -> ptr_width = 4 (to index 0-15)
        )
        self.assertEqual(spec.ptr_width, 4)

        spec2 = InstructionBufferSpec(
            imem_node='imem',
            pc_node='pc',
            instr_width_node='instr_len',
            fetch_width=64,    # 8 bytes
            buffer_size=8      # 64 bytes total -> ptr_width = 6 (to index 0-63)
        )
        self.assertEqual(spec2.ptr_width, 6)

    def test_spec_validation_invalid_fetch_width(self):
        """Test that non-multiple-of-8 fetch_width raises error."""
        with self.assertRaises(ValueError):
            InstructionBufferSpec(
                imem_node='imem',
                pc_node='pc',
                instr_width_node='instr_len',
                fetch_width=33  # Not a multiple of 8
            )

    def test_spec_validation_zero_fetch_width(self):
        """Test that zero fetch_width raises error."""
        with self.assertRaises(ValueError):
            InstructionBufferSpec(
                imem_node='imem',
                pc_node='pc',
                instr_width_node='instr_len',
                fetch_width=0
            )

    def test_spec_validation_small_buffer(self):
        """Test that buffer_size < 2 raises error."""
        with self.assertRaises(ValueError):
            InstructionBufferSpec(
                imem_node='imem',
                pc_node='pc',
                instr_width_node='instr_len',
                buffer_size=1
            )

    def test_str_representation(self):
        """Test string representation."""
        spec = InstructionBufferSpec(
            imem_node='imem',
            pc_node='pc',
            instr_width_node='instr_len',
            fetch_width=32,
            buffer_size=4
        )
        s = str(spec)
        self.assertIn('imem', s)
        self.assertIn('pc', s)
        self.assertIn('32', s)
        self.assertIn('instr_len', s)

    def test_str_representation_with_flush(self):
        """Test string representation includes flush+redirect."""
        spec = InstructionBufferSpec(
            imem_node='imem',
            pc_node='pc',
            instr_width_node='instr_len',
            flush_node='flush_sig',
            redirect_node='branch_target'
        )
        s = str(spec)
        self.assertIn('flush=flush_sig', s)
        self.assertIn('redirect=branch_target', s)

    def test_has_flush_property(self):
        """Test the has_flush property."""
        spec_no_flush = InstructionBufferSpec(
            imem_node='imem', pc_node='pc', instr_width_node='instr_len')
        self.assertFalse(spec_no_flush.has_flush)

        spec_flush = InstructionBufferSpec(
            imem_node='imem', pc_node='pc', instr_width_node='instr_len',
            flush_node='flush_sig')
        self.assertTrue(spec_flush.has_flush)


class TestInstructionBufferOptimization(unittest.TestCase):
    """Test the InstructionBufferOptimization class."""

    def _create_basic_graph(self):
        """Create a test graph with a memory and a single imem[pc] read access."""
        graph = ResourceGraph()

        # Create memory node
        mem_node = Node(
            'imem',
            {
                'type': 'isa_state mem',
                'name': 'imem',
                'is_memory': True,
                'bit_width': 32,
                'array_depth': 10
            },
            is_arch_state=True
        )
        graph.add_node(mem_node)

        # Create PC node
        addr_node = Node('pc', {'type': 'isa_state', 'name': 'pc', 'bit_width': 32})
        graph.add_node(addr_node)

        # Create array_access node for read
        access_node = Node(
            'imem_pc_rd',
            {'type': 'array_access', 'name': 'imem[pc]', 'access_mode': 'read'}
        )
        graph.add_node(access_node)

        # Create target node (instruction)
        target_node = Node('instr', {'type': 'var', 'name': 'instr', 'bit_width': 32})
        graph.add_node(target_node)

        # Create instruction width node (from decode)
        instr_len_node = Node(
            'instr_len',
            {'type': 'var', 'name': 'instr_len', 'bit_width': 4}
        )
        graph.add_node(instr_len_node)

        # Wire up the read access:
        # imem --[array_base]--> access_node <--[array_index]-- pc
        # access_node --[assignment]--> instr
        graph.add_edge(Edge(mem_node, access_node, data={'type': 'array_base'}))
        graph.add_edge(Edge(addr_node, access_node, data={'type': 'array_index'}))
        graph.add_edge(Edge(access_node, target_node, data={'type': 'assignment'}))

        return graph

    def setUp(self):
        """Create a test graph with a memory and read accesses."""
        self.graph = self._create_basic_graph()

    def test_ibuf_optimization_creates_buffer_node(self):
        """Test that applying buffer optimization creates a buffer node."""
        spec = InstructionBufferSpec(
            imem_node='imem',
            pc_node='pc',
            instr_width_node='instr_len',
            fetch_width=32,
            buffer_size=4
        )

        success = apply_instruction_buffer(self.graph, spec)

        self.assertTrue(success)
        self.assertIn('imem_ibuf', self.graph.nodes)

        buf_node = self.graph.nodes['imem_ibuf']
        self.assertEqual(buf_node.data['type'], 'instruction_buffer')
        self.assertEqual(buf_node.data['fetch_width'], 32)
        self.assertEqual(buf_node.data['buffer_size'], 4)
        self.assertTrue(buf_node.variable_latency)

    def test_ibuf_optimization_creates_data_output_node(self):
        """Test that buffer optimization creates data output nodes."""
        spec = InstructionBufferSpec(
            imem_node='imem',
            pc_node='pc',
            instr_width_node='instr_len'
        )
        apply_instruction_buffer(self.graph, spec)

        # Should have data output node for port 0
        self.assertIn('imem_ibuf_data_0', self.graph.nodes)
        data_node = self.graph.nodes['imem_ibuf_data_0']
        self.assertEqual(data_node.data['type'], 'ibuf_read_data')

    def test_ibuf_optimization_creates_valid_output_node(self):
        """Test that buffer optimization creates valid output nodes."""
        spec = InstructionBufferSpec(
            imem_node='imem',
            pc_node='pc',
            instr_width_node='instr_len'
        )
        apply_instruction_buffer(self.graph, spec)

        # Should have valid output node for port 0
        self.assertIn('imem_ibuf_valid_0', self.graph.nodes)
        valid_node = self.graph.nodes['imem_ibuf_valid_0']
        self.assertEqual(valid_node.data['type'], 'ibuf_valid')

    def test_ibuf_optimization_creates_fetch_interface(self):
        """Test that buffer optimization creates fetch interface nodes."""
        spec = InstructionBufferSpec(
            imem_node='imem',
            pc_node='pc',
            instr_width_node='instr_len'
        )
        apply_instruction_buffer(self.graph, spec)

        # Should have fetch address and data nodes
        self.assertIn('imem_ibuf_fetch_addr', self.graph.nodes)
        self.assertIn('imem_ibuf_fetch_data', self.graph.nodes)
        self.assertIn('imem_ibuf_fetch_req', self.graph.nodes)
        self.assertIn('imem_ibuf_fetch_valid', self.graph.nodes)

        fetch_addr = self.graph.nodes['imem_ibuf_fetch_addr']
        self.assertEqual(fetch_addr.data['type'], 'ibuf_fetch_addr')

    def test_ibuf_optimization_creates_consume_interface(self):
        """Test that buffer optimization wires the instruction width input."""
        spec = InstructionBufferSpec(
            imem_node='imem',
            pc_node='pc',
            instr_width_node='instr_len'
        )
        apply_instruction_buffer(self.graph, spec)

        # Should have consume bytes node
        self.assertIn('imem_ibuf_consume_bytes', self.graph.nodes)
        consume_node = self.graph.nodes['imem_ibuf_consume_bytes']

        # consume_bytes should be connected to instr_len
        incoming_sources = [e.source.id for e in consume_node.incoming_edges]
        self.assertIn('instr_len', incoming_sources)

        # consume_bytes should be connected to the buffer
        outgoing_targets = [e.target.id for e in consume_node.outgoing_edges]
        self.assertIn('imem_ibuf', outgoing_targets)

    def test_ibuf_optimization_redirects_read_access(self):
        """Test that read access is redirected through buffer."""
        spec = InstructionBufferSpec(
            imem_node='imem',
            pc_node='pc',
            instr_width_node='instr_len'
        )
        apply_instruction_buffer(self.graph, spec)

        # The target (instr) should now get data from buffer, not memory
        target_node = self.graph.nodes['instr']
        incoming_sources = [e.source.id for e in target_node.incoming_edges]

        # Should be connected to buffer data output
        self.assertIn('imem_ibuf_data_0', incoming_sources)

    def test_ibuf_optimization_creates_control_signals(self):
        """Test that control signals are created."""
        spec = InstructionBufferSpec(
            imem_node='imem',
            pc_node='pc',
            instr_width_node='instr_len'
        )
        apply_instruction_buffer(self.graph, spec)

        self.assertIn('imem_ibuf_start', self.graph.nodes)
        self.assertIn('imem_ibuf_idle', self.graph.nodes)
        self.assertIn('imem_ibuf_complete', self.graph.nodes)

    def test_ibuf_optimization_with_nonexistent_memory(self):
        """Test that optimization fails gracefully for missing memory."""
        spec = InstructionBufferSpec(
            imem_node='nonexistent',
            pc_node='pc',
            instr_width_node='instr_len'
        )
        success = apply_instruction_buffer(self.graph, spec)

        self.assertFalse(success)

    def test_ibuf_optimization_with_nonexistent_width_node(self):
        """Test that optimization fails gracefully for missing width node."""
        spec = InstructionBufferSpec(
            imem_node='imem',
            pc_node='pc',
            instr_width_node='nonexistent'
        )
        success = apply_instruction_buffer(self.graph, spec)

        self.assertFalse(success)

    def test_ibuf_optimization_with_nonexistent_pc_node(self):
        """Test that optimization fails gracefully for missing PC node."""
        spec = InstructionBufferSpec(
            imem_node='imem',
            pc_node='nonexistent_pc',
            instr_width_node='instr_len'
        )
        success = apply_instruction_buffer(self.graph, spec)

        self.assertFalse(success)

    def test_ibuf_optimization_with_custom_parameters(self):
        """Test buffer creation with non-default parameters."""
        spec = InstructionBufferSpec(
            imem_node='imem',
            pc_node='pc',
            instr_width_node='instr_len',
            fetch_width=64,
            buffer_size=8,
            address_width=16,
            buffer_name='my_prefetch_buf'
        )
        success = apply_instruction_buffer(self.graph, spec)

        self.assertTrue(success)
        self.assertIn('my_prefetch_buf', self.graph.nodes)

        buf_node = self.graph.nodes['my_prefetch_buf']
        self.assertEqual(buf_node.data['fetch_width'], 64)
        self.assertEqual(buf_node.data['buffer_size'], 8)
        self.assertEqual(buf_node.data['address_width'], 16)

    def test_ibuf_memory_still_connected_for_fetch(self):
        """Test that the original memory is still connected via fetch interface."""
        spec = InstructionBufferSpec(
            imem_node='imem',
            pc_node='pc',
            instr_width_node='instr_len'
        )
        apply_instruction_buffer(self.graph, spec)

        # Memory should still be in the graph (used by fetch interface)
        self.assertIn('imem', self.graph.nodes)

        # The fetch interface creates a new array_access for memory
        fetch_access_name = "imem[imem_ibuf_fetch_addr]_rd"
        self.assertIn(fetch_access_name, self.graph.nodes)

    def test_ibuf_output_has_byte_offset_metadata(self):
        """Test that output data nodes have byte_offset metadata."""
        spec = InstructionBufferSpec(
            imem_node='imem',
            pc_node='pc',
            instr_width_node='instr_len'
        )
        apply_instruction_buffer(self.graph, spec)

        data_node = self.graph.nodes['imem_ibuf_data_0']
        self.assertEqual(data_node.data['byte_offset'], 0)
        self.assertEqual(data_node.data['port_index'], 0)

    def test_ibuf_buffer_node_stores_output_offsets(self):
        """Test that the buffer node stores output_offsets in its data."""
        spec = InstructionBufferSpec(
            imem_node='imem',
            pc_node='pc',
            instr_width_node='instr_len'
        )
        apply_instruction_buffer(self.graph, spec)

        buf_node = self.graph.nodes['imem_ibuf']
        self.assertIn('output_offsets', buf_node.data)
        self.assertEqual(buf_node.data['output_offsets'], [0])

    def test_ibuf_buffer_node_stores_pc_node_ref(self):
        """Test that the buffer node records pc_node reference."""
        spec = InstructionBufferSpec(
            imem_node='imem',
            pc_node='pc',
            instr_width_node='instr_len'
        )
        apply_instruction_buffer(self.graph, spec)

        buf_node = self.graph.nodes['imem_ibuf']
        self.assertEqual(buf_node.data['pc_node'], 'pc')


class TestPCOffsetDetection(unittest.TestCase):
    """Test automatic detection of imem[pc+N] accesses."""

    def _make_graph_with_pc_plus_n(self, offsets):
        """Create a graph with imem[pc], imem[pc+1], etc. for each offset in offsets."""
        graph = ResourceGraph()

        # Memory node
        mem_node = Node(
            'imem',
            {'type': 'isa_state mem', 'name': 'imem', 'is_memory': True,
             'bit_width': 8, 'array_depth': 16},
            is_arch_state=True
        )
        graph.add_node(mem_node)

        # PC node
        pc_node = Node('pc', {'type': 'isa_state', 'name': 'pc', 'bit_width': 16})
        graph.add_node(pc_node)

        # Instruction width node
        instr_len_node = Node(
            'instr_len', {'type': 'var', 'name': 'instr_len', 'bit_width': 4})
        graph.add_node(instr_len_node)

        for offset in offsets:
            if offset == 0:
                # imem[pc] - direct PC reference
                access_node = Node(
                    f'imem_pc_rd',
                    {'type': 'array_access', 'name': 'imem[pc]', 'access_mode': 'read'}
                )
                graph.add_node(access_node)

                target_node = Node(
                    f'byte_{offset}',
                    {'type': 'var', 'name': f'byte_{offset}', 'bit_width': 8}
                )
                graph.add_node(target_node)

                graph.add_edge(Edge(mem_node, access_node, data={'type': 'array_base'}))
                graph.add_edge(Edge(pc_node, access_node, data={'type': 'array_index'}))
                graph.add_edge(Edge(access_node, target_node, data={'type': 'assignment'}))
            else:
                # imem[pc+N] - PC plus literal
                literal_node = Node(
                    f'literal_{offset}',
                    {'type': 'literal', 'name': str(offset), 'value': offset, 'bit_width': 16}
                )
                graph.add_node(literal_node)

                add_node = Node(
                    f'pc_plus_{offset}',
                    {'type': 'operation', 'operator': '+', 'name': f'pc+{offset}', 'bit_width': 16}
                )
                graph.add_node(add_node)

                # pc + literal -> add_node
                graph.add_edge(Edge(pc_node, add_node,
                    data={'type': 'operand', 'operand_position': 0}))
                graph.add_edge(Edge(literal_node, add_node,
                    data={'type': 'operand', 'operand_position': 1}))

                access_node = Node(
                    f'imem_pc_plus_{offset}_rd',
                    {'type': 'array_access', 'name': f'imem[pc+{offset}]', 'access_mode': 'read'}
                )
                graph.add_node(access_node)

                target_node = Node(
                    f'byte_{offset}',
                    {'type': 'var', 'name': f'byte_{offset}', 'bit_width': 8}
                )
                graph.add_node(target_node)

                graph.add_edge(Edge(mem_node, access_node, data={'type': 'array_base'}))
                graph.add_edge(Edge(add_node, access_node, data={'type': 'array_index'}))
                graph.add_edge(Edge(access_node, target_node, data={'type': 'assignment'}))

        return graph

    def test_detect_single_pc_access(self):
        """Test detection of a single imem[pc] access."""
        graph = self._make_graph_with_pc_plus_n([0])
        spec = InstructionBufferSpec(
            imem_node='imem', pc_node='pc', instr_width_node='instr_len')
        success = apply_instruction_buffer(graph, spec)
        self.assertTrue(success)

        buf_node = graph.nodes['imem_ibuf']
        self.assertEqual(buf_node.data['output_offsets'], [0])
        self.assertEqual(buf_node.data['num_read_ports'], 1)

    def test_detect_pc_plus_1(self):
        """Test detection of imem[pc] and imem[pc+1] accesses."""
        graph = self._make_graph_with_pc_plus_n([0, 1])
        spec = InstructionBufferSpec(
            imem_node='imem', pc_node='pc', instr_width_node='instr_len',
            data_width=8)
        success = apply_instruction_buffer(graph, spec)
        self.assertTrue(success)

        buf_node = graph.nodes['imem_ibuf']
        self.assertEqual(buf_node.data['output_offsets'], [0, 1])
        self.assertEqual(buf_node.data['num_read_ports'], 2)

    def test_detect_multiple_offsets(self):
        """Test detection of imem[pc], imem[pc+1], imem[pc+2]."""
        graph = self._make_graph_with_pc_plus_n([0, 1, 2])
        spec = InstructionBufferSpec(
            imem_node='imem', pc_node='pc', instr_width_node='instr_len',
            data_width=8)
        success = apply_instruction_buffer(graph, spec)
        self.assertTrue(success)

        buf_node = graph.nodes['imem_ibuf']
        self.assertEqual(buf_node.data['output_offsets'], [0, 1, 2])
        self.assertEqual(buf_node.data['num_read_ports'], 3)

    def test_offset_ports_redirect_correctly(self):
        """Test that each PC+N access gets redirected to the correct buffer output port."""
        graph = self._make_graph_with_pc_plus_n([0, 1])
        spec = InstructionBufferSpec(
            imem_node='imem', pc_node='pc', instr_width_node='instr_len',
            data_width=8)
        apply_instruction_buffer(graph, spec)

        # byte_0 should be connected to ibuf_data_0 (offset 0)
        byte_0 = graph.nodes['byte_0']
        incoming_sources = [e.source.id for e in byte_0.incoming_edges]
        self.assertIn('imem_ibuf_data_0', incoming_sources)

        # byte_1 should be connected to ibuf_data_1 (offset 1)
        byte_1 = graph.nodes['byte_1']
        incoming_sources = [e.source.id for e in byte_1.incoming_edges]
        self.assertIn('imem_ibuf_data_1', incoming_sources)

    def test_output_port_byte_offsets(self):
        """Test that output port nodes have correct byte_offset metadata."""
        graph = self._make_graph_with_pc_plus_n([0, 1, 2])
        spec = InstructionBufferSpec(
            imem_node='imem', pc_node='pc', instr_width_node='instr_len',
            data_width=8)
        apply_instruction_buffer(graph, spec)

        for i, offset in enumerate([0, 1, 2]):
            data_node = graph.nodes[f'imem_ibuf_data_{i}']
            self.assertEqual(data_node.data['byte_offset'], offset)
            self.assertEqual(data_node.data['port_index'], i)

    def test_detect_commutative_literal_plus_pc(self):
        """Test detection of imem[N+pc] (literal before PC, commutative)."""
        graph = ResourceGraph()

        mem_node = Node('imem',
            {'type': 'isa_state mem', 'name': 'imem', 'is_memory': True,
             'bit_width': 8, 'array_depth': 16}, is_arch_state=True)
        graph.add_node(mem_node)

        pc_node = Node('pc', {'type': 'isa_state', 'name': 'pc', 'bit_width': 16})
        graph.add_node(pc_node)

        instr_len_node = Node('instr_len', {'type': 'var', 'name': 'instr_len', 'bit_width': 4})
        graph.add_node(instr_len_node)

        # Create literal + pc (reverse order)
        literal_node = Node('literal_2',
            {'type': 'literal', 'name': '2', 'value': 2, 'bit_width': 16})
        graph.add_node(literal_node)

        add_node = Node('two_plus_pc',
            {'type': 'operation', 'operator': '+', 'name': '2+pc', 'bit_width': 16})
        graph.add_node(add_node)

        # literal (pos 0) + pc (pos 1)
        graph.add_edge(Edge(literal_node, add_node,
            data={'type': 'operand', 'operand_position': 0}))
        graph.add_edge(Edge(pc_node, add_node,
            data={'type': 'operand', 'operand_position': 1}))

        access_node = Node('imem_2_plus_pc_rd',
            {'type': 'array_access', 'name': 'imem[2+pc]', 'access_mode': 'read'})
        graph.add_node(access_node)

        target_node = Node('byte_2', {'type': 'var', 'name': 'byte_2', 'bit_width': 8})
        graph.add_node(target_node)

        graph.add_edge(Edge(mem_node, access_node, data={'type': 'array_base'}))
        graph.add_edge(Edge(add_node, access_node, data={'type': 'array_index'}))
        graph.add_edge(Edge(access_node, target_node, data={'type': 'assignment'}))

        spec = InstructionBufferSpec(
            imem_node='imem', pc_node='pc', instr_width_node='instr_len',
            data_width=8)
        success = apply_instruction_buffer(graph, spec)
        self.assertTrue(success)

        buf_node = graph.nodes['imem_ibuf']
        self.assertEqual(buf_node.data['output_offsets'], [2])

    def test_trace_through_assignment_chain(self):
        """Test detection of PC offset through an assignment chain (6502 pattern)."""
        graph = ResourceGraph()

        mem_node = Node('imem',
            {'type': 'isa_state mem', 'name': 'imem', 'is_memory': True,
             'bit_width': 8, 'array_depth': 16}, is_arch_state=True)
        graph.add_node(mem_node)

        pc_node = Node('pc', {'type': 'isa_state', 'name': 'pc', 'bit_width': 16})
        graph.add_node(pc_node)

        instr_len_node = Node('instr_len', {'type': 'var', 'name': 'instr_len', 'bit_width': 4})
        graph.add_node(instr_len_node)

        # pc + 1 -> intermediate_val (assignment chain: pc_val = pc + 1)
        literal_1 = Node('literal_1',
            {'type': 'literal', 'name': '1', 'value': 1, 'bit_width': 16})
        graph.add_node(literal_1)

        pc_plus_1 = Node('pc_plus_1',
            {'type': 'operation', 'operator': '+', 'name': 'pc+1', 'bit_width': 16})
        graph.add_node(pc_plus_1)

        graph.add_edge(Edge(pc_node, pc_plus_1,
            data={'type': 'operand', 'operand_position': 0}))
        graph.add_edge(Edge(literal_1, pc_plus_1,
            data={'type': 'operand', 'operand_position': 1}))

        # intermediate_val = pc + 1 (assignment chain)
        intermediate_val = Node('pc_val',
            {'type': 'var', 'name': 'pc_val', 'bit_width': 16})
        graph.add_node(intermediate_val)
        graph.add_edge(Edge(pc_plus_1, intermediate_val, data={'type': 'assignment'}))

        # imem[pc_val] - address is the intermediate value
        access_node = Node('imem_pc_val_rd',
            {'type': 'array_access', 'name': 'imem[pc_val]', 'access_mode': 'read'})
        graph.add_node(access_node)

        target_node = Node('byte_1', {'type': 'var', 'name': 'byte_1', 'bit_width': 8})
        graph.add_node(target_node)

        graph.add_edge(Edge(mem_node, access_node, data={'type': 'array_base'}))
        graph.add_edge(Edge(intermediate_val, access_node, data={'type': 'array_index'}))
        graph.add_edge(Edge(access_node, target_node, data={'type': 'assignment'}))

        spec = InstructionBufferSpec(
            imem_node='imem', pc_node='pc', instr_width_node='instr_len',
            data_width=8)
        success = apply_instruction_buffer(graph, spec)
        self.assertTrue(success)

        buf_node = graph.nodes['imem_ibuf']
        self.assertEqual(buf_node.data['output_offsets'], [1])

    def test_trace_chained_addition(self):
        """Test detection of chained pc+1+1=pc+2 (JMP ABS pattern)."""
        graph = ResourceGraph()

        mem_node = Node('imem',
            {'type': 'isa_state mem', 'name': 'imem', 'is_memory': True,
             'bit_width': 8, 'array_depth': 16}, is_arch_state=True)
        graph.add_node(mem_node)

        pc_node = Node('pc', {'type': 'isa_state', 'name': 'pc', 'bit_width': 16})
        graph.add_node(pc_node)

        instr_len_node = Node('instr_len', {'type': 'var', 'name': 'instr_len', 'bit_width': 4})
        graph.add_node(instr_len_node)

        # pc_plus_1 = pc + 1
        literal_1a = Node('literal_1a',
            {'type': 'literal', 'name': '1', 'value': 1, 'bit_width': 16})
        graph.add_node(literal_1a)

        pc_plus_1_op = Node('pc_plus_1_op',
            {'type': 'operation', 'operator': '+', 'name': 'pc+1', 'bit_width': 16})
        graph.add_node(pc_plus_1_op)

        graph.add_edge(Edge(pc_node, pc_plus_1_op,
            data={'type': 'operand', 'operand_position': 0}))
        graph.add_edge(Edge(literal_1a, pc_plus_1_op,
            data={'type': 'operand', 'operand_position': 1}))

        pc_plus_1_var = Node('pc_plus_1',
            {'type': 'var', 'name': 'pc_plus_1', 'bit_width': 16})
        graph.add_node(pc_plus_1_var)
        graph.add_edge(Edge(pc_plus_1_op, pc_plus_1_var, data={'type': 'assignment'}))

        # pc_plus_2 = pc_plus_1 + 1 (chained addition)
        literal_1b = Node('literal_1b',
            {'type': 'literal', 'name': '1', 'value': 1, 'bit_width': 16})
        graph.add_node(literal_1b)

        pc_plus_2_op = Node('pc_plus_2_op',
            {'type': 'operation', 'operator': '+', 'name': 'pc_plus_1+1', 'bit_width': 16})
        graph.add_node(pc_plus_2_op)

        graph.add_edge(Edge(pc_plus_1_var, pc_plus_2_op,
            data={'type': 'operand', 'operand_position': 0}))
        graph.add_edge(Edge(literal_1b, pc_plus_2_op,
            data={'type': 'operand', 'operand_position': 1}))

        pc_plus_2_var = Node('pc_plus_2',
            {'type': 'var', 'name': 'pc_plus_2', 'bit_width': 16})
        graph.add_node(pc_plus_2_var)
        graph.add_edge(Edge(pc_plus_2_op, pc_plus_2_var, data={'type': 'assignment'}))

        # mainmem[pc_plus_1] -> addr_lo (offset 1)
        access_lo = Node('imem_pc_plus_1_rd',
            {'type': 'array_access', 'name': 'imem[pc_plus_1]', 'access_mode': 'read'})
        graph.add_node(access_lo)

        target_lo = Node('addr_lo', {'type': 'var', 'name': 'addr_lo', 'bit_width': 8})
        graph.add_node(target_lo)

        graph.add_edge(Edge(mem_node, access_lo, data={'type': 'array_base'}))
        graph.add_edge(Edge(pc_plus_1_var, access_lo, data={'type': 'array_index'}))
        graph.add_edge(Edge(access_lo, target_lo, data={'type': 'assignment'}))

        # mainmem[pc_plus_2] -> addr_hi (offset 2 via chained addition)
        access_hi = Node('imem_pc_plus_2_rd',
            {'type': 'array_access', 'name': 'imem[pc_plus_2]', 'access_mode': 'read'})
        graph.add_node(access_hi)

        target_hi = Node('addr_hi', {'type': 'var', 'name': 'addr_hi', 'bit_width': 8})
        graph.add_node(target_hi)

        graph.add_edge(Edge(mem_node, access_hi, data={'type': 'array_base'}))
        graph.add_edge(Edge(pc_plus_2_var, access_hi, data={'type': 'array_index'}))
        graph.add_edge(Edge(access_hi, target_hi, data={'type': 'assignment'}))

        spec = InstructionBufferSpec(
            imem_node='imem', pc_node='pc', instr_width_node='instr_len',
            data_width=8)
        success = apply_instruction_buffer(graph, spec)
        self.assertTrue(success)

        buf_node = graph.nodes['imem_ibuf']
        self.assertEqual(buf_node.data['output_offsets'], [1, 2])
        self.assertEqual(buf_node.data['num_read_ports'], 2)

        # Verify correct redirection
        addr_lo = graph.nodes['addr_lo']
        lo_sources = [e.source.id for e in addr_lo.incoming_edges]
        self.assertIn('imem_ibuf_data_0', lo_sources)

        addr_hi = graph.nodes['addr_hi']
        hi_sources = [e.source.id for e in addr_hi.incoming_edges]
        self.assertIn('imem_ibuf_data_1', hi_sources)


class TestFlushRedirectInterface(unittest.TestCase):
    """Test flush + redirect interface for branch misprediction."""

    def _create_graph_with_flush(self):
        """Create a graph with memory, PC, and flush/redirect nodes."""
        graph = ResourceGraph()

        mem_node = Node('imem',
            {'type': 'isa_state mem', 'name': 'imem', 'is_memory': True,
             'bit_width': 32, 'array_depth': 10}, is_arch_state=True)
        graph.add_node(mem_node)

        pc_node = Node('pc', {'type': 'isa_state', 'name': 'pc', 'bit_width': 32})
        graph.add_node(pc_node)

        access_node = Node('imem_pc_rd',
            {'type': 'array_access', 'name': 'imem[pc]', 'access_mode': 'read'})
        graph.add_node(access_node)

        target_node = Node('instr', {'type': 'var', 'name': 'instr', 'bit_width': 32})
        graph.add_node(target_node)

        instr_len_node = Node('instr_len',
            {'type': 'var', 'name': 'instr_len', 'bit_width': 4})
        graph.add_node(instr_len_node)

        graph.add_edge(Edge(mem_node, access_node, data={'type': 'array_base'}))
        graph.add_edge(Edge(pc_node, access_node, data={'type': 'array_index'}))
        graph.add_edge(Edge(access_node, target_node, data={'type': 'assignment'}))

        # Add flush signal node
        flush_node = Node('control_hazard_flush',
            {'type': 'var', 'name': 'control_hazard_flush', 'bit_width': 1})
        graph.add_node(flush_node)

        # Add redirect address node (branch target)
        redirect_node = Node('branch_target',
            {'type': 'var', 'name': 'branch_target', 'bit_width': 32})
        graph.add_node(redirect_node)

        return graph

    def test_flush_redirect_wiring(self):
        """Test that flush+redirect nodes are wired to the buffer."""
        graph = self._create_graph_with_flush()
        spec = InstructionBufferSpec(
            imem_node='imem', pc_node='pc', instr_width_node='instr_len',
            flush_node='control_hazard_flush',
            redirect_node='branch_target')
        success = apply_instruction_buffer(graph, spec)
        self.assertTrue(success)

        buf_node = graph.nodes['imem_ibuf']
        self.assertTrue(buf_node.data['has_flush_input'])

        # Check flush var node exists and is wired
        flush_var_name = 'imem_ibuf_flush'
        self.assertIn(flush_var_name, graph.nodes)
        flush_var = graph.nodes[flush_var_name]
        self.assertEqual(flush_var.data['buffer_interface'], 'flush')

        # Check flush_var is connected to buffer via ibuf_flush edge
        ibuf_flush_edges = [e for e in buf_node.incoming_edges
                           if e.data and e.data.get('type') == 'ibuf_flush']
        self.assertEqual(len(ibuf_flush_edges), 1)

        # Check redirect_addr var node exists and is wired
        redirect_var_name = 'imem_ibuf_redirect_addr'
        self.assertIn(redirect_var_name, graph.nodes)
        redirect_var = graph.nodes[redirect_var_name]
        self.assertEqual(redirect_var.data['buffer_interface'], 'redirect_addr')

        # Check redirect_var is connected to buffer via ibuf_redirect_addr edge
        ibuf_redirect_edges = [e for e in buf_node.incoming_edges
                               if e.data and e.data.get('type') == 'ibuf_redirect_addr']
        self.assertEqual(len(ibuf_redirect_edges), 1)

    def test_flush_signal_sourced_from_correct_node(self):
        """Test that the flush var is sourced from the specified flush node."""
        graph = self._create_graph_with_flush()
        spec = InstructionBufferSpec(
            imem_node='imem', pc_node='pc', instr_width_node='instr_len',
            flush_node='control_hazard_flush',
            redirect_node='branch_target')
        apply_instruction_buffer(graph, spec)

        flush_var = graph.nodes['imem_ibuf_flush']
        incoming_sources = [e.source.id for e in flush_var.incoming_edges]
        self.assertIn('control_hazard_flush', incoming_sources)

    def test_redirect_addr_sourced_from_correct_node(self):
        """Test that the redirect_addr var is sourced from the specified redirect node."""
        graph = self._create_graph_with_flush()
        spec = InstructionBufferSpec(
            imem_node='imem', pc_node='pc', instr_width_node='instr_len',
            flush_node='control_hazard_flush',
            redirect_node='branch_target')
        apply_instruction_buffer(graph, spec)

        redirect_var = graph.nodes['imem_ibuf_redirect_addr']
        incoming_sources = [e.source.id for e in redirect_var.incoming_edges]
        self.assertIn('branch_target', incoming_sources)

    def test_buffer_info_includes_flush_redirect(self):
        """Test that get_ibuf_info returns flush/redirect signal info."""
        graph = self._create_graph_with_flush()
        spec = InstructionBufferSpec(
            imem_node='imem', pc_node='pc', instr_width_node='instr_len',
            flush_node='control_hazard_flush',
            redirect_node='branch_target')
        apply_instruction_buffer(graph, spec)

        info = get_ibuf_info(graph, 'imem_ibuf')
        self.assertIsNotNone(info)
        self.assertEqual(info['flush_signal'], 'imem_ibuf_flush')
        self.assertEqual(info['redirect_addr_signal'], 'imem_ibuf_redirect_addr')

    def test_flush_without_redirect(self):
        """Test that flush works without redirect (graceful degradation)."""
        graph = self._create_graph_with_flush()
        spec = InstructionBufferSpec(
            imem_node='imem', pc_node='pc', instr_width_node='instr_len',
            flush_node='control_hazard_flush')
        success = apply_instruction_buffer(graph, spec)
        self.assertTrue(success)

        buf_node = graph.nodes['imem_ibuf']
        self.assertTrue(buf_node.data['has_flush_input'])
        self.assertIn('imem_ibuf_flush', graph.nodes)
        # redirect_addr should not exist
        self.assertNotIn('imem_ibuf_redirect_addr', graph.nodes)

    def test_missing_flush_node_warning(self):
        """Test that missing flush node disables flush (warning, not error)."""
        graph = self._create_graph_with_flush()
        spec = InstructionBufferSpec(
            imem_node='imem', pc_node='pc', instr_width_node='instr_len',
            flush_node='nonexistent_flush')
        success = apply_instruction_buffer(graph, spec)
        self.assertTrue(success)

        buf_node = graph.nodes['imem_ibuf']
        self.assertFalse(buf_node.data['has_flush_input'])


class TestGetIbufFunctions(unittest.TestCase):
    """Test instruction buffer information helper functions."""

    def setUp(self):
        """Create a test graph with a buffer."""
        self.graph = ResourceGraph()

        # Create memory node
        mem_node = Node(
            'imem',
            {'type': 'isa_state mem', 'name': 'imem', 'is_memory': True,
             'bit_width': 32, 'array_depth': 10},
            is_arch_state=True
        )
        self.graph.add_node(mem_node)

        # Create address and target nodes
        addr_node = Node('pc', {'type': 'isa_state', 'name': 'pc', 'bit_width': 32})
        self.graph.add_node(addr_node)

        access_node = Node(
            'imem_pc_rd',
            {'type': 'array_access', 'name': 'imem[pc]', 'access_mode': 'read'}
        )
        self.graph.add_node(access_node)

        target_node = Node('instr', {'type': 'var', 'name': 'instr', 'bit_width': 32})
        self.graph.add_node(target_node)

        instr_len_node = Node(
            'instr_len',
            {'type': 'var', 'name': 'instr_len', 'bit_width': 4}
        )
        self.graph.add_node(instr_len_node)

        # Wire
        self.graph.add_edge(Edge(mem_node, access_node, data={'type': 'array_base'}))
        self.graph.add_edge(Edge(addr_node, access_node, data={'type': 'array_index'}))
        self.graph.add_edge(Edge(access_node, target_node, data={'type': 'assignment'}))

        # Apply optimization
        spec = InstructionBufferSpec(
            imem_node='imem',
            pc_node='pc',
            instr_width_node='instr_len',
            fetch_width=32,
            buffer_size=4
        )
        apply_instruction_buffer(self.graph, spec)

    def test_get_ibuf_nodes(self):
        """Test finding all instruction buffer nodes."""
        ibuf_nodes = get_ibuf_nodes(self.graph)
        self.assertEqual(len(ibuf_nodes), 1)
        self.assertEqual(ibuf_nodes[0].data['type'], 'instruction_buffer')

    def test_get_ibuf_info(self):
        """Test getting instruction buffer information."""
        info = get_ibuf_info(self.graph, 'imem_ibuf')
        self.assertIsNotNone(info)
        self.assertEqual(info['name'], 'imem_ibuf')
        self.assertEqual(info['imem_node'], 'imem')
        self.assertEqual(info['pc_node'], 'pc')
        self.assertEqual(info['instr_width_node'], 'instr_len')
        self.assertEqual(info['fetch_width'], 32)
        self.assertEqual(info['buffer_size'], 4)

    def test_get_ibuf_info_nonexistent(self):
        """Test getting info for non-existent buffer returns None."""
        info = get_ibuf_info(self.graph, 'nonexistent')
        self.assertIsNone(info)

    def test_get_ibuf_info_includes_output_offsets(self):
        """Test that info includes output_offsets."""
        info = get_ibuf_info(self.graph, 'imem_ibuf')
        self.assertIsNotNone(info)
        self.assertEqual(info['output_offsets'], [0])


class TestInstructionBufferGenerator(unittest.TestCase):
    """Test the Verilog module generator for instruction buffers."""

    def test_generator_creation(self):
        """Test creating an InstructionBufferGenerator."""
        gen = InstructionBufferGenerator(
            name='test_ibuf',
            fetch_width=32,
            buffer_size=4,
            address_width=32,
            data_width=32
        )
        self.assertEqual(gen.name, 'test_ibuf')
        self.assertEqual(gen.fetch_bytes, 4)
        self.assertEqual(gen.buffer_capacity_bytes, 16)

    def test_generator_module_output(self):
        """Test that generate_module produces valid Verilog structure."""
        gen = InstructionBufferGenerator(
            name='test_ibuf',
            fetch_width=32,
            buffer_size=4,
            address_width=32,
            data_width=32
        )
        verilog = gen.generate_module()

        # Check module declaration
        self.assertIn('module test_ibuf', verilog)
        self.assertIn('endmodule', verilog)

        # Check ports
        self.assertIn('fetch_addr', verilog)
        self.assertIn('fetch_req', verilog)
        self.assertIn('fetch_data', verilog)
        self.assertIn('fetch_valid', verilog)
        self.assertIn('out_data_0', verilog)
        self.assertIn('out_valid_0', verilog)
        self.assertIn('consume_bytes', verilog)
        self.assertIn('consume_valid', verilog)

        # Check storage
        self.assertIn('buffer', verilog)
        self.assertIn('wr_ptr', verilog)
        self.assertIn('rd_ptr', verilog)

    def test_generator_with_flush(self):
        """Test that flush+redirect ports are generated when has_flush=True."""
        gen = InstructionBufferGenerator(
            name='test_ibuf',
            fetch_width=32,
            buffer_size=4,
            has_flush=True
        )
        verilog = gen.generate_module()

        self.assertIn('input  wire flush', verilog)
        self.assertIn('redirect_addr', verilog)
        self.assertIn('Flush', verilog)

    def test_generator_without_flush(self):
        """Test that flush port is not present when has_flush=False."""
        gen = InstructionBufferGenerator(
            name='test_ibuf',
            fetch_width=32,
            buffer_size=4,
            has_flush=False
        )
        verilog = gen.generate_module()

        self.assertNotIn('input  wire flush', verilog)
        self.assertNotIn('redirect_addr', verilog)

    def test_generator_flush_uses_redirect_addr(self):
        """Test that flush logic uses redirect_addr to set fetch_addr."""
        gen = InstructionBufferGenerator(
            name='test_ibuf',
            fetch_width=32,
            buffer_size=4,
            has_flush=True
        )
        verilog = gen.generate_module()

        self.assertIn('fetch_addr <= redirect_addr', verilog)
        # Flush should be gated by buf_has_data (only flush on valid decode)
        self.assertIn('flush && buf_has_data', verilog)

    def test_generator_multi_offset_output_ports(self):
        """Test that multiple output ports are generated for different offsets."""
        gen = InstructionBufferGenerator(
            name='test_ibuf',
            fetch_width=32,
            buffer_size=4,
            data_width=8,
            output_offsets=[0, 1, 2]
        )
        verilog = gen.generate_module()

        # Should have 3 output port pairs
        self.assertIn('out_data_0', verilog)
        self.assertIn('out_valid_0', verilog)
        self.assertIn('out_data_1', verilog)
        self.assertIn('out_valid_1', verilog)
        self.assertIn('out_data_2', verilog)
        self.assertIn('out_valid_2', verilog)

        # Should have byte offset comments
        self.assertIn('byte offset 0', verilog)
        self.assertIn('byte offset 1', verilog)
        self.assertIn('byte offset 2', verilog)

    def test_generator_port_connections_multi_port(self):
        """Test get_port_connections with multi-port outputs."""
        gen = InstructionBufferGenerator(
            name='test_ibuf',
            fetch_width=32,
            buffer_size=4,
            output_offsets=[0, 1]
        )
        inst = gen.get_port_connections(
            fetch_addr='ibuf_fetch_addr',
            fetch_req='ibuf_fetch_req',
            fetch_data='ibuf_fetch_data',
            fetch_valid='ibuf_fetch_valid',
            out_datas=['ibuf_data_0', 'ibuf_data_1'],
            out_valids=['ibuf_valid_0', 'ibuf_valid_1'],
            consume_bytes='ibuf_consume',
            consume_valid='ibuf_consume_valid'
        )

        self.assertIn('test_ibuf test_ibuf_inst', inst)
        self.assertIn('.fetch_addr(ibuf_fetch_addr)', inst)
        self.assertIn('.out_data_0(ibuf_data_0)', inst)
        self.assertIn('.out_data_1(ibuf_data_1)', inst)
        self.assertIn('.out_valid_0(ibuf_valid_0)', inst)
        self.assertIn('.out_valid_1(ibuf_valid_1)', inst)
        self.assertIn('.consume_bytes(ibuf_consume)', inst)

    def test_generator_port_connections_legacy_single_port(self):
        """Test get_port_connections with legacy single-port interface."""
        gen = InstructionBufferGenerator(
            name='test_ibuf',
            fetch_width=32,
            buffer_size=4
        )
        inst = gen.get_port_connections(
            fetch_addr='ibuf_fetch_addr',
            fetch_req='ibuf_fetch_req',
            fetch_data='ibuf_fetch_data',
            fetch_valid='ibuf_fetch_valid',
            out_data='ibuf_data_0',
            out_valid='ibuf_valid_0',
            consume_bytes='ibuf_consume',
            consume_valid='ibuf_consume_valid'
        )

        self.assertIn('.out_data_0(ibuf_data_0)', inst)
        self.assertIn('.out_valid_0(ibuf_valid_0)', inst)

    def test_generator_port_connections_with_flush_redirect(self):
        """Test get_port_connections includes flush and redirect_addr."""
        gen = InstructionBufferGenerator(
            name='test_ibuf',
            fetch_width=32,
            buffer_size=4,
            has_flush=True
        )
        inst = gen.get_port_connections(
            fetch_addr='ibuf_fetch_addr',
            fetch_req='ibuf_fetch_req',
            fetch_data='ibuf_fetch_data',
            fetch_valid='ibuf_fetch_valid',
            out_data='ibuf_data_0',
            out_valid='ibuf_valid_0',
            consume_bytes='ibuf_consume',
            consume_valid='ibuf_consume_valid',
            flush_signal='flush_sig',
            redirect_addr='branch_target'
        )

        self.assertIn('.flush(flush_sig)', inst)
        self.assertIn('.redirect_addr(branch_target)', inst)

    def test_factory_creates_ibuf_generator(self):
        """Test that create_module_generator_from_node handles instruction_buffer."""
        node_data = {
            'type': 'instruction_buffer',
            'name': 'my_ibuf',
            'fetch_width': 64,
            'buffer_size': 8,
            'address_width': 32,
            'data_width': 32,
        }
        gen = create_module_generator_from_node(node_data)
        self.assertIsInstance(gen, InstructionBufferGenerator)
        self.assertEqual(gen.name, 'my_ibuf')
        self.assertEqual(gen.fetch_width, 64)
        self.assertEqual(gen.buffer_size, 8)

    def test_factory_passes_output_offsets(self):
        """Test that factory passes output_offsets from node data."""
        node_data = {
            'type': 'instruction_buffer',
            'name': 'my_ibuf',
            'fetch_width': 32,
            'buffer_size': 4,
            'output_offsets': [0, 1, 2],
            'has_flush_input': True,
        }
        gen = create_module_generator_from_node(node_data)
        self.assertIsInstance(gen, InstructionBufferGenerator)
        self.assertEqual(gen.output_offsets, [0, 1, 2])
        self.assertTrue(gen.has_flush)

    def test_generator_derived_parameters(self):
        """Test that derived parameters are calculated correctly."""
        gen = InstructionBufferGenerator(
            name='test_ibuf',
            fetch_width=64,     # 8 bytes
            buffer_size=8,      # 64 bytes total
            address_width=32,
            data_width=32
        )
        self.assertEqual(gen.fetch_bytes, 8)
        self.assertEqual(gen.buffer_capacity_bytes, 64)
        self.assertEqual(gen.data_bytes, 4)


if __name__ == '__main__':
    unittest.main()
