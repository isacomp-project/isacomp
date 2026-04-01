"""
Test suite for cache_optimization module.

Tests the read-only cache optimization including:
- ReadOnlyCacheSpec validation and parameter calculation
- Cache node creation and graph transformation
- Multi-port cache support
- Verilog generation for cache modules
"""

import unittest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.resource_graph import ResourceGraph, Node, Edge
from opt.memory.cache_optimization import (
    ReadOnlyCacheSpec,
    ReadOnlyCacheOptimization,
    apply_read_only_cache,
    get_cache_nodes,
    get_cache_info,
    wire_cache_start_signal,
    add_cache_latency_stalls
)
from backends.verilog.verilog_module_generators import ReadOnlyCacheGenerator


class TestReadOnlyCacheSpec(unittest.TestCase):
    """Test the ReadOnlyCacheSpec dataclass."""

    def test_basic_spec_creation(self):
        """Test creating a basic cache spec."""
        spec = ReadOnlyCacheSpec(
            memory_name='imem',
            block_size=32,
            associativity=1,
            num_rows=64,
            address_width=32
        )

        self.assertEqual(spec.memory_name, 'imem')
        self.assertEqual(spec.cache_name, 'imem_cache')
        self.assertEqual(spec.block_size, 32)
        self.assertEqual(spec.associativity, 1)
        self.assertEqual(spec.num_rows, 64)

    def test_spec_with_custom_name(self):
        """Test cache spec with custom cache name."""
        spec = ReadOnlyCacheSpec(
            memory_name='imem',
            cache_name='icache',
            block_size=32,
            associativity=2,
            num_rows=128
        )

        self.assertEqual(spec.cache_name, 'icache')

    def test_address_field_calculations(self):
        """Test offset, index, and tag width calculations."""
        spec = ReadOnlyCacheSpec(
            memory_name='imem',
            block_size=32,     # 32 bytes -> 5 bits offset
            num_rows=64,       # 64 rows -> 6 bits index
            address_width=32   # 32 - 5 - 6 = 21 bits tag
        )

        self.assertEqual(spec.offset_width, 5)  # log2(32) = 5
        self.assertEqual(spec.index_width, 6)   # log2(64) = 6
        self.assertEqual(spec.tag_width, 21)    # 32 - 5 - 6 = 21

    def test_spec_validation_invalid_associativity(self):
        """Test that non-power-of-2 associativity raises error."""
        with self.assertRaises(ValueError):
            ReadOnlyCacheSpec(
                memory_name='imem',
                associativity=3  # Not power of 2
            )

    def test_spec_validation_invalid_num_rows(self):
        """Test that non-power-of-2 num_rows raises error."""
        with self.assertRaises(ValueError):
            ReadOnlyCacheSpec(
                memory_name='imem',
                num_rows=100  # Not power of 2
            )

    def test_spec_validation_invalid_block_size(self):
        """Test that non-power-of-2 block_size raises error."""
        with self.assertRaises(ValueError):
            ReadOnlyCacheSpec(
                memory_name='imem',
                block_size=48  # Not power of 2
            )


class TestReadOnlyCacheOptimization(unittest.TestCase):
    """Test the ReadOnlyCacheOptimization class."""

    def setUp(self):
        """Create a test graph with a memory and read accesses."""
        self.graph = ResourceGraph()

        # Create memory node
        self.mem_node = Node(
            'imem',
            {
                'type': 'isa_state mem',
                'name': 'imem',
                'is_memory': True,
                'bit_width': 32,
                'array_depth': 10  # Address width
            },
            is_arch_state=True
        )
        self.graph.add_node(self.mem_node)

        # Create address node (e.g., PC)
        self.addr_node = Node('pc', {'type': 'isa_state', 'name': 'pc', 'bit_width': 32})
        self.graph.add_node(self.addr_node)

        # Create array_access node for read
        self.access_node = Node(
            'imem_pc_rd',
            {'type': 'array_access', 'name': 'imem[pc]'}
        )
        self.graph.add_node(self.access_node)

        # Create target node (instruction)
        self.target_node = Node('instr', {'type': 'var', 'name': 'instr', 'bit_width': 32})
        self.graph.add_node(self.target_node)

        # Wire up the read access:
        # imem --[array_index]--> access_node <--[array_index]-- pc
        # access_node --[assignment]--> instr
        mem_edge = Edge(self.mem_node, self.access_node, data={'type': 'array_index'})
        addr_edge = Edge(self.addr_node, self.access_node, data={'type': 'array_index'})
        assign_edge = Edge(self.access_node, self.target_node, data={'type': 'assignment'})

        self.graph.add_edge(mem_edge)
        self.graph.add_edge(addr_edge)
        self.graph.add_edge(assign_edge)

    def test_cache_optimization_creates_cache_node(self):
        """Test that applying cache optimization creates a cache node."""
        spec = ReadOnlyCacheSpec(
            memory_name='imem',
            block_size=32,
            associativity=1,
            num_rows=64
        )

        success = apply_read_only_cache(self.graph, spec)

        self.assertTrue(success)
        self.assertIn('imem_cache', self.graph.nodes)

        cache_node = self.graph.nodes['imem_cache']
        self.assertEqual(cache_node.data['type'], 'read_only_cache')
        self.assertEqual(cache_node.data['num_read_ports'], 1)
        self.assertTrue(cache_node.variable_latency)

    def test_cache_optimization_creates_data_output_node(self):
        """Test that cache optimization creates data output nodes."""
        spec = ReadOnlyCacheSpec(memory_name='imem')
        apply_read_only_cache(self.graph, spec)

        # Should have data output node for port 0
        self.assertIn('imem_cache_data_0', self.graph.nodes)
        data_node = self.graph.nodes['imem_cache_data_0']
        self.assertEqual(data_node.data['type'], 'cache_read_data')

    def test_cache_optimization_creates_valid_output_node(self):
        """Test that cache optimization creates valid output nodes."""
        spec = ReadOnlyCacheSpec(memory_name='imem')
        apply_read_only_cache(self.graph, spec)

        # Should have valid output node for port 0
        self.assertIn('imem_cache_valid_0', self.graph.nodes)
        valid_node = self.graph.nodes['imem_cache_valid_0']
        self.assertEqual(valid_node.data['type'], 'cache_valid')

    def test_cache_optimization_creates_refill_interface(self):
        """Test that cache optimization creates refill interface nodes."""
        spec = ReadOnlyCacheSpec(memory_name='imem')
        apply_read_only_cache(self.graph, spec)

        # Should have refill address and data nodes
        self.assertIn('imem_cache_refill_addr', self.graph.nodes)
        self.assertIn('imem_cache_refill_data', self.graph.nodes)

        refill_addr = self.graph.nodes['imem_cache_refill_addr']
        self.assertEqual(refill_addr.data['type'], 'cache_refill_addr')

    def test_cache_optimization_redirects_read_access(self):
        """Test that read access is redirected through cache."""
        spec = ReadOnlyCacheSpec(memory_name='imem')
        apply_read_only_cache(self.graph, spec)

        # The array_access node should now get data from cache, not memory
        access_node = self.graph.nodes['imem_pc_rd']
        incoming_sources = [e.source.id for e in access_node.incoming_edges]

        # Should be connected to cache data output
        self.assertIn('imem_cache_data_0', incoming_sources)
        # Memory should not be directly connected to access anymore
        self.assertNotIn('imem', incoming_sources)

    def test_cache_optimization_with_nonexistent_memory(self):
        """Test that optimization fails gracefully for missing memory."""
        spec = ReadOnlyCacheSpec(memory_name='nonexistent')
        success = apply_read_only_cache(self.graph, spec)

        self.assertFalse(success)


class TestMultiPortCache(unittest.TestCase):
    """Test cache optimization with multiple read ports."""

    def setUp(self):
        """Create a test graph with multiple read accesses to same memory."""
        self.graph = ResourceGraph()

        # Create memory node
        self.mem_node = Node(
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
        self.graph.add_node(self.mem_node)

        # Create two different address nodes
        self.addr1 = Node('pc', {'type': 'isa_state', 'name': 'pc', 'bit_width': 32})
        self.addr2 = Node('npc', {'type': 'isa_state', 'name': 'npc', 'bit_width': 32})
        self.graph.add_node(self.addr1)
        self.graph.add_node(self.addr2)

        # Create two array_access nodes
        self.access1 = Node('imem_pc_rd', {'type': 'array_access', 'name': 'imem[pc]'})
        self.access2 = Node('imem_npc_rd', {'type': 'array_access', 'name': 'imem[npc]'})
        self.graph.add_node(self.access1)
        self.graph.add_node(self.access2)

        # Create target nodes
        self.target1 = Node('instr1', {'type': 'var', 'name': 'instr1', 'bit_width': 32})
        self.target2 = Node('instr2', {'type': 'var', 'name': 'instr2', 'bit_width': 32})
        self.graph.add_node(self.target1)
        self.graph.add_node(self.target2)

        # Wire up first read access
        self.graph.add_edge(Edge(self.mem_node, self.access1, data={'type': 'array_index'}))
        self.graph.add_edge(Edge(self.addr1, self.access1, data={'type': 'array_index'}))
        self.graph.add_edge(Edge(self.access1, self.target1, data={'type': 'assignment'}))

        # Wire up second read access
        self.graph.add_edge(Edge(self.mem_node, self.access2, data={'type': 'array_index'}))
        self.graph.add_edge(Edge(self.addr2, self.access2, data={'type': 'array_index'}))
        self.graph.add_edge(Edge(self.access2, self.target2, data={'type': 'assignment'}))

    def test_multi_port_cache_creation(self):
        """Test that cache is created with correct number of ports."""
        spec = ReadOnlyCacheSpec(memory_name='imem')
        success = apply_read_only_cache(self.graph, spec)

        self.assertTrue(success)

        cache_node = self.graph.nodes['imem_cache']
        self.assertEqual(cache_node.data['num_read_ports'], 2)

    def test_multi_port_data_outputs(self):
        """Test that each port has its own data output."""
        spec = ReadOnlyCacheSpec(memory_name='imem')
        apply_read_only_cache(self.graph, spec)

        self.assertIn('imem_cache_data_0', self.graph.nodes)
        self.assertIn('imem_cache_data_1', self.graph.nodes)

    def test_multi_port_valid_outputs(self):
        """Test that each port has its own valid output."""
        spec = ReadOnlyCacheSpec(memory_name='imem')
        apply_read_only_cache(self.graph, spec)

        self.assertIn('imem_cache_valid_0', self.graph.nodes)
        self.assertIn('imem_cache_valid_1', self.graph.nodes)


class TestCacheInfoFunctions(unittest.TestCase):
    """Test cache information helper functions."""

    def setUp(self):
        """Create a graph with a cache."""
        self.graph = ResourceGraph()

        # Create minimal memory setup
        self.mem_node = Node(
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
        self.graph.add_node(self.mem_node)

        self.addr_node = Node('pc', {'type': 'isa_state', 'name': 'pc', 'bit_width': 32})
        self.graph.add_node(self.addr_node)

        self.access_node = Node('imem_pc_rd', {'type': 'array_access', 'name': 'imem[pc]'})
        self.graph.add_node(self.access_node)

        self.target_node = Node('instr', {'type': 'var', 'name': 'instr', 'bit_width': 32})
        self.graph.add_node(self.target_node)

        self.graph.add_edge(Edge(self.mem_node, self.access_node, data={'type': 'array_index'}))
        self.graph.add_edge(Edge(self.addr_node, self.access_node, data={'type': 'array_index'}))
        self.graph.add_edge(Edge(self.access_node, self.target_node, data={'type': 'assignment'}))

    def test_get_cache_nodes_empty(self):
        """Test get_cache_nodes on graph without caches."""
        caches = get_cache_nodes(self.graph)
        self.assertEqual(len(caches), 0)

    def test_get_cache_nodes_with_cache(self):
        """Test get_cache_nodes returns cache after optimization."""
        spec = ReadOnlyCacheSpec(memory_name='imem')
        apply_read_only_cache(self.graph, spec)

        caches = get_cache_nodes(self.graph)
        self.assertEqual(len(caches), 1)
        self.assertEqual(caches[0].id, 'imem_cache')

    def test_get_cache_info(self):
        """Test get_cache_info returns correct information."""
        spec = ReadOnlyCacheSpec(
            memory_name='imem',
            block_size=64,
            associativity=2,
            num_rows=128,
            replacement_policy='lru'
        )
        apply_read_only_cache(self.graph, spec)

        info = get_cache_info(self.graph, 'imem_cache')

        self.assertIsNotNone(info)
        self.assertEqual(info['name'], 'imem_cache')
        self.assertEqual(info['memory_name'], 'imem')
        self.assertEqual(info['block_size'], 64)
        self.assertEqual(info['associativity'], 2)
        self.assertEqual(info['num_rows'], 128)
        self.assertEqual(info['replacement_policy'], 'lru')

    def test_get_cache_info_nonexistent(self):
        """Test get_cache_info returns None for nonexistent cache."""
        info = get_cache_info(self.graph, 'nonexistent_cache')
        self.assertIsNone(info)


class TestReadOnlyCacheGenerator(unittest.TestCase):
    """Test the Verilog cache generator."""

    def test_direct_mapped_cache_generation(self):
        """Test generating a direct-mapped cache."""
        generator = ReadOnlyCacheGenerator(
            name='imem_cache',
            num_read_ports=1,
            block_size=32,
            associativity=1,
            num_rows=64,
            address_width=32,
            data_width=32
        )

        verilog = generator.generate_module()

        # Check module declaration
        self.assertIn('module imem_cache', verilog)
        self.assertIn('parameter BLOCK_SIZE = 32', verilog)
        self.assertIn('parameter ASSOCIATIVITY = 1', verilog)
        self.assertIn('parameter NUM_ROWS = 64', verilog)

        # Check ports
        self.assertIn('read_addr_0', verilog)
        self.assertIn('read_data_0', verilog)
        self.assertIn('read_valid_0', verilog)
        self.assertIn('refill_addr', verilog)
        self.assertIn('refill_data', verilog)

        # Check storage arrays
        self.assertIn('tag_array', verilog)
        self.assertIn('valid_array', verilog)
        self.assertIn('data_array', verilog)

        # Check hit logic
        self.assertIn('hit_0', verilog)

    def test_set_associative_cache_generation(self):
        """Test generating a set-associative cache."""
        generator = ReadOnlyCacheGenerator(
            name='icache',
            num_read_ports=1,
            block_size=32,
            associativity=4,
            num_rows=64,
            address_width=32,
            data_width=32,
            replacement_policy='lru'
        )

        verilog = generator.generate_module()

        # Check associative structures
        self.assertIn('way_hit_0', verilog)
        self.assertIn('hit_way_0', verilog)
        self.assertIn('lru_array', verilog)

    def test_multi_port_cache_generation(self):
        """Test generating a multi-port cache."""
        generator = ReadOnlyCacheGenerator(
            name='imem_cache',
            num_read_ports=2,
            block_size=32,
            associativity=1,
            num_rows=64
        )

        verilog = generator.generate_module()

        # Check both ports present
        self.assertIn('read_addr_0', verilog)
        self.assertIn('read_addr_1', verilog)
        self.assertIn('read_data_0', verilog)
        self.assertIn('read_data_1', verilog)
        self.assertIn('read_valid_0', verilog)
        self.assertIn('read_valid_1', verilog)

    def test_refill_fsm_generation(self):
        """Test that refill FSM is generated."""
        generator = ReadOnlyCacheGenerator(
            name='imem_cache',
            num_read_ports=1,
            block_size=32,
            associativity=1,
            num_rows=64
        )

        verilog = generator.generate_module()

        # Check FSM states
        self.assertIn('IDLE', verilog)
        self.assertIn('REFILL', verilog)
        self.assertIn('UPDATE', verilog)

        # Check miss detection
        self.assertIn('miss', verilog)

    def test_random_replacement_policy(self):
        """Test cache with random replacement policy."""
        generator = ReadOnlyCacheGenerator(
            name='icache',
            num_read_ports=1,
            associativity=2,
            replacement_policy='random'
        )

        verilog = generator.generate_module()

        # Check LFSR is present for random replacement
        self.assertIn('lfsr', verilog)

    def test_fifo_replacement_policy(self):
        """Test cache with FIFO replacement policy."""
        generator = ReadOnlyCacheGenerator(
            name='icache',
            num_read_ports=1,
            associativity=2,
            replacement_policy='fifo'
        )

        verilog = generator.generate_module()

        # Check FIFO pointer is present
        self.assertIn('fifo_ptr', verilog)

    def test_get_port_connections(self):
        """Test generating port connections for instantiation."""
        generator = ReadOnlyCacheGenerator(
            name='imem_cache',
            num_read_ports=2
        )

        connections = generator.get_port_connections(
            read_addrs=['pc', 'npc'],
            read_reqs=['1\'b1', '1\'b1'],
            read_datas=['instr1', 'instr2'],
            read_valids=['valid1', 'valid2'],
            refill_addr='mem_addr',
            refill_req='mem_req',
            refill_data='mem_data',
            refill_valid='mem_valid'
        )

        self.assertIn('.read_addr_0(pc)', connections)
        self.assertIn('.read_addr_1(npc)', connections)
        self.assertIn('.refill_addr(mem_addr)', connections)
        self.assertIn('.clk(clk)', connections)


class TestCacheLatencyIntegration(unittest.TestCase):
    """Test integration with memory latency infrastructure."""

    def setUp(self):
        """Create a test graph with a memory and cache."""
        self.graph = ResourceGraph()

        # Create memory node
        self.mem_node = Node(
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
        self.graph.add_node(self.mem_node)

        # Create address node (e.g., PC)
        self.addr_node = Node('pc', {'type': 'isa_state', 'name': 'pc', 'bit_width': 32})
        self.graph.add_node(self.addr_node)

        # Create array_access node for read
        self.access_node = Node(
            'imem_pc_rd',
            {'type': 'array_access', 'name': 'imem[pc]'}
        )
        self.graph.add_node(self.access_node)

        # Create target node
        self.target_node = Node('instr', {'type': 'var', 'name': 'instr', 'bit_width': 32})
        self.graph.add_node(self.target_node)

        # Wire up the read access
        mem_edge = Edge(self.mem_node, self.access_node, data={'type': 'array_index'})
        addr_edge = Edge(self.addr_node, self.access_node, data={'type': 'array_index'})
        assign_edge = Edge(self.access_node, self.target_node, data={'type': 'assignment'})

        self.graph.add_edge(mem_edge)
        self.graph.add_edge(addr_edge)
        self.graph.add_edge(assign_edge)

    def test_cache_has_control_signals(self):
        """Test that cache creates control signals (start, idle, complete)."""
        spec = ReadOnlyCacheSpec(
            memory_name='imem',
            block_size=32,
            associativity=1,
            num_rows=64
        )

        success = apply_read_only_cache(self.graph, spec)
        self.assertTrue(success)

        cache_node = self.graph.nodes['imem_cache']

        # Check control signal metadata
        self.assertIn('start_signal', cache_node.data)
        self.assertIn('idle_signal', cache_node.data)
        self.assertIn('complete_signal', cache_node.data)

        # Check signal nodes exist
        self.assertIn(cache_node.data['start_signal'], self.graph.nodes)
        self.assertIn(cache_node.data['idle_signal'], self.graph.nodes)
        self.assertIn(cache_node.data['complete_signal'], self.graph.nodes)

    def test_cache_control_signal_types(self):
        """Test that control signals have correct types."""
        spec = ReadOnlyCacheSpec(
            memory_name='imem',
            block_size=32,
            associativity=1,
            num_rows=64
        )

        success = apply_read_only_cache(self.graph, spec)
        self.assertTrue(success)

        cache_node = self.graph.nodes['imem_cache']

        # Check signal node types
        start_node = self.graph.nodes[cache_node.data['start_signal']]
        idle_node = self.graph.nodes[cache_node.data['idle_signal']]
        complete_node = self.graph.nodes[cache_node.data['complete_signal']]

        self.assertEqual(start_node.data['type'], 'control_signal')
        self.assertEqual(start_node.data['signal_type'], 'start')

        self.assertEqual(idle_node.data['type'], 'control_signal')
        self.assertEqual(idle_node.data['signal_type'], 'idle')

        self.assertEqual(complete_node.data['type'], 'control_signal')
        self.assertEqual(complete_node.data['signal_type'], 'complete')

    def test_get_cache_info_includes_control_signals(self):
        """Test that get_cache_info returns control signal info."""
        spec = ReadOnlyCacheSpec(
            memory_name='imem',
            block_size=32,
            associativity=1,
            num_rows=64
        )

        success = apply_read_only_cache(self.graph, spec)
        self.assertTrue(success)

        info = get_cache_info(self.graph, 'imem_cache')

        self.assertIsNotNone(info)
        self.assertIn('start_signal', info)
        self.assertIn('idle_signal', info)
        self.assertIn('complete_signal', info)
        self.assertEqual(info['start_signal'], 'imem_cache_start')
        self.assertEqual(info['idle_signal'], 'imem_cache_idle')
        self.assertEqual(info['complete_signal'], 'imem_cache_complete')


if __name__ == '__main__':
    unittest.main()
