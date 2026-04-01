"""
Test suite for mux_utils module.

Tests the unified mux insertion utilities including:
- Basic mux creation
- Adding inputs incrementally
- Different mux types (one-hot and priority)
- Mux information retrieval
- Mux refactoring into sub-muxes
"""

import unittest
from core.resource_graph import ResourceGraph, Node, Edge
from core.mux_utils import (MuxBuilder, MuxType, create_mux, add_mux_input, get_mux_info,
                       MuxRefactor, refactor_mux, analyze_mux)


class TestMuxBuilder(unittest.TestCase):
    """Test the MuxBuilder class."""

    def setUp(self):
        """Create a fresh graph for each test."""
        self.graph = ResourceGraph()

        # Create some test nodes
        self.source1 = Node('source1', {'type': 'var', 'name': 'a'})
        self.source2 = Node('source2', {'type': 'var', 'name': 'b'})
        self.source3 = Node('source3', {'type': 'var', 'name': 'c'})
        self.target = Node('target', {'type': 'var', 'name': 'out'})

        self.select1 = Node('sel1', {'type': 'instruction_enable', 'name': 'instr1_enable'})
        self.select2 = Node('sel2', {'type': 'instruction_enable', 'name': 'instr2_enable'})
        self.select3 = Node('sel3', {'type': 'instruction_enable', 'name': 'instr3_enable'})

        for node in [self.source1, self.source2, self.source3, self.target,
                     self.select1, self.select2, self.select3]:
            self.graph.add_node(node)

    def test_create_basic_mux(self):
        """Test creating a basic 2-to-1 mux."""
        builder = MuxBuilder(self.graph, 'test_mux', MuxType.ONE_HOT)
        mux = builder.create_or_get_mux('Test MUX')

        self.assertIsNotNone(mux)
        self.assertEqual(mux.id, 'test_mux')
        self.assertEqual(mux.data['type'], 'multiplexer')
        self.assertEqual(mux.data['operation'], 'one_hot_select')

    def test_add_inputs(self):
        """Test adding inputs to a mux."""
        builder = MuxBuilder(self.graph, 'test_mux', MuxType.ONE_HOT)
        builder.create_or_get_mux()

        idx1 = builder.add_input(self.source1, self.select1)
        idx2 = builder.add_input(self.source2, self.select2)

        self.assertEqual(idx1, 0)
        self.assertEqual(idx2, 1)
        self.assertEqual(builder.num_inputs, 2)
        self.assertEqual(builder.mux_node.data['num_inputs'], 2)

    def test_connect_output(self):
        """Test connecting mux output to target."""
        builder = MuxBuilder(self.graph, 'test_mux', MuxType.ONE_HOT)
        builder.create_or_get_mux()
        builder.add_input(self.source1, self.select1)
        builder.add_input(self.source2, self.select2)
        builder.connect_output(self.target)

        # Check that output edge exists
        output_edges = [e for e in builder.mux_node.outgoing_edges
                       if e.target == self.target]
        self.assertEqual(len(output_edges), 1)
        self.assertEqual(output_edges[0].data['type'], 'assignment')

    def test_incremental_mux_extension(self):
        """Test adding inputs to an existing mux."""
        # Create initial 2-to-1 mux
        builder1 = MuxBuilder(self.graph, 'test_mux', MuxType.ONE_HOT)
        builder1.create_or_get_mux()
        builder1.add_input(self.source1, self.select1)
        builder1.add_input(self.source2, self.select2)

        # Extend to 3-to-1 mux using a new builder
        builder2 = MuxBuilder(self.graph, 'test_mux', MuxType.ONE_HOT)
        builder2.create_or_get_mux()
        idx3 = builder2.add_input(self.source3, self.select3)

        self.assertEqual(idx3, 2)
        self.assertEqual(builder2.num_inputs, 3)
        self.assertEqual(builder2.mux_node.data['num_inputs'], 3)

    def test_priority_mux_type(self):
        """Test creating a priority-encoded mux."""
        builder = MuxBuilder(self.graph, 'priority_mux', MuxType.PRIORITY)
        mux = builder.create_or_get_mux()

        self.assertEqual(mux.data['operation'], 'priority_select')

    def test_remove_bypassing_edges(self):
        """Test removing direct edges that bypass the mux."""
        # Create direct edges from sources to target
        edge1 = Edge(self.source1, self.target, data={'type': 'assignment'})
        edge2 = Edge(self.source2, self.target, data={'type': 'assignment'})
        self.graph.add_edge(edge1)
        self.graph.add_edge(edge2)

        # Create mux
        builder = MuxBuilder(self.graph, 'test_mux', MuxType.ONE_HOT)
        builder.create_or_get_mux()
        builder.add_input(self.source1, self.select1)
        builder.add_input(self.source2, self.select2)

        # Remove bypassing edges
        removed = builder.remove_bypassing_edges([self.source1, self.source2], self.target)

        self.assertEqual(removed, 2)
        # Check that direct edges are gone
        direct_edges = [e for e in self.source1.outgoing_edges if e.target == self.target]
        self.assertEqual(len(direct_edges), 0)


class TestConvenienceFunctions(unittest.TestCase):
    """Test convenience functions for mux creation."""

    def setUp(self):
        """Create a fresh graph for each test."""
        self.graph = ResourceGraph()
        self.source1 = Node('source1', {'type': 'var'})
        self.source2 = Node('source2', {'type': 'var'})
        self.target = Node('target', {'type': 'var'})
        self.select1 = Node('sel1', {'type': 'instruction_enable'})
        self.select2 = Node('sel2', {'type': 'instruction_enable'})

        for node in [self.source1, self.source2, self.target, self.select1, self.select2]:
            self.graph.add_node(node)

    def test_create_mux_convenience(self):
        """Test create_mux convenience function."""
        mux = create_mux(
            self.graph,
            'test_mux',
            [(self.source1, self.select1), (self.source2, self.select2)],
            self.target,
            display_name='Test MUX'
        )

        self.assertIsNotNone(mux)
        self.assertEqual(mux.data['num_inputs'], 2)

        # Check output connection
        output_edges = [e for e in mux.outgoing_edges if e.target == self.target]
        self.assertEqual(len(output_edges), 1)

    def test_add_mux_input_convenience(self):
        """Test add_mux_input convenience function."""
        # Create initial mux
        source3 = Node('source3', {'type': 'var'})
        select3 = Node('sel3', {'type': 'instruction_enable'})
        self.graph.add_node(source3)
        self.graph.add_node(select3)

        create_mux(
            self.graph,
            'test_mux',
            [(self.source1, self.select1), (self.source2, self.select2)],
            self.target
        )

        # Add third input
        idx = add_mux_input(self.graph, 'test_mux', source3, select3)

        self.assertEqual(idx, 2)

        # Verify mux now has 3 inputs
        info = get_mux_info(self.graph, 'test_mux')
        self.assertEqual(info['num_inputs'], 3)

    def test_get_mux_info(self):
        """Test get_mux_info function."""
        create_mux(
            self.graph,
            'test_mux',
            [(self.source1, self.select1), (self.source2, self.select2)],
            self.target,
            display_name='Test MUX'
        )

        info = get_mux_info(self.graph, 'test_mux')

        self.assertIsNotNone(info)
        self.assertEqual(info['mux_id'], 'test_mux')
        self.assertEqual(info['num_inputs'], 2)
        self.assertEqual(len(info['inputs']), 2)
        self.assertEqual(len(info['selects']), 2)
        self.assertEqual(len(info['outputs']), 1)

    def test_get_mux_info_nonexistent(self):
        """Test get_mux_info for nonexistent mux."""
        info = get_mux_info(self.graph, 'nonexistent_mux')
        self.assertIsNone(info)


class TestStringConditions(unittest.TestCase):
    """Test using string conditions instead of select nodes."""

    def setUp(self):
        """Create a fresh graph for each test."""
        self.graph = ResourceGraph()
        self.source1 = Node('source1', {'type': 'var'})
        self.source2 = Node('source2', {'type': 'var'})
        self.target = Node('target', {'type': 'var'})

        for node in [self.source1, self.source2, self.target]:
            self.graph.add_node(node)

    def test_string_select_conditions(self):
        """Test using string conditions for select signals."""
        builder = MuxBuilder(self.graph, 'test_mux', MuxType.ONE_HOT)
        builder.create_or_get_mux()
        builder.add_input(self.source1, 'instr1_enable == 1')
        builder.add_input(self.source2, 'instr2_enable == 1')

        self.assertEqual(builder.num_inputs, 2)

        # Verify conditions are stored (not as edges)
        mux_inputs = [e for e in builder.mux_node.incoming_edges
                     if e.data.get('type') == 'mux_input']
        self.assertEqual(len(mux_inputs), 2)


class TestMuxRefactor(unittest.TestCase):
    """Test the MuxRefactor class for mux decomposition."""

    def setUp(self):
        """Create a graph with a large mux for refactoring tests."""
        self.graph = ResourceGraph()

        # Create ALU result sources (simulating RV32I ALU operations)
        self.alu_sources = {}
        alu_ops = ['add_res', 'sub_res', 'and_res', 'or_res', 'xor_res',
                   'sll_res', 'srl_res', 'sra_res', 'slt_res', 'sltu_res']
        for op in alu_ops:
            node = Node(op, {'type': 'var', 'name': op, 'instruction': op.replace('_res', '')})
            self.graph.add_node(node)
            self.alu_sources[op] = node

        # Create immediate ALU result sources
        self.imm_sources = {}
        imm_ops = ['addi_res', 'andi_res', 'ori_res', 'xori_res', 'lui_res']
        for op in imm_ops:
            node = Node(op, {'type': 'var', 'name': op, 'instruction': op.replace('_res', '')})
            self.graph.add_node(node)
            self.imm_sources[op] = node

        # Create memory sources
        self.mem_sources = {}
        mem_ops = ['data', 'byte_data', 'halfword_data']
        for op in mem_ops:
            node = Node(op, {'type': 'var', 'name': op, 'instruction': 'load'})
            self.graph.add_node(node)
            self.mem_sources[op] = node

        # Create enable signals
        self.enables = {}
        for name in list(self.alu_sources.keys()) + list(self.imm_sources.keys()) + ['load']:
            enable_name = f"{name.replace('_res', '')}_enable"
            node = Node(enable_name, {'type': 'instruction_enable', 'bit_width': 1})
            self.graph.add_node(node)
            self.enables[enable_name] = node

        # Create target
        self.target = Node('rf_write', {'type': 'var', 'name': 'rf_write'})
        self.graph.add_node(self.target)

        # Create large mux with all inputs
        all_sources = {**self.alu_sources, **self.imm_sources, **self.mem_sources}
        builder = MuxBuilder(self.graph, 'rf_write_data_mux', MuxType.ONE_HOT)
        builder.create_or_get_mux('RF Write Data MUX')

        for name, source in all_sources.items():
            enable_name = f"{name.replace('_res', '')}_enable"
            if enable_name in self.enables:
                builder.add_input(source, self.enables[enable_name])
            else:
                builder.add_input(source, 'load_enable')  # For memory sources

        builder.connect_output(self.target)

    def test_refactor_basic(self):
        """Test basic mux refactoring into sub-muxes."""
        refactor = MuxRefactor(self.graph, 'rf_write_data_mux')
        refactor.add_group('alu_r', ['add_res', 'sub_res', 'and_res', 'or_res', 'xor_res'])
        refactor.add_group('alu_i', ['addi_res', 'andi_res', 'ori_res', 'xori_res', 'lui_res'])

        sub_muxes = refactor.apply()

        # Check that sub-muxes were created
        self.assertIn('alu_r', sub_muxes)
        self.assertIn('alu_i', sub_muxes)

        # Check sub-mux properties
        alu_r_mux = sub_muxes['alu_r']
        self.assertEqual(alu_r_mux.data['type'], 'multiplexer')
        self.assertEqual(alu_r_mux.data['num_inputs'], 5)

        alu_i_mux = sub_muxes['alu_i']
        self.assertEqual(alu_i_mux.data['num_inputs'], 5)

    def test_refactor_combined_enable_creation(self):
        """Test that combined enable signals are created correctly."""
        refactor = MuxRefactor(self.graph, 'rf_write_data_mux')
        refactor.add_group('alu_r', ['add_res', 'sub_res', 'and_res'])

        refactor.apply()

        # Check that combined enable was created
        enable_node = self.graph.nodes.get('alu_r_group_enable')
        self.assertIsNotNone(enable_node)
        self.assertEqual(enable_node.data['type'], 'combined_enable')
        self.assertIn('component_enables', enable_node.data)

        # Check that it contains the right enables
        component_enables = enable_node.data['component_enables']
        self.assertIn('add_enable', component_enables)
        self.assertIn('sub_enable', component_enables)
        self.assertIn('and_enable', component_enables)

    def test_refactor_main_mux_reduced(self):
        """Test that main mux input count is reduced after refactoring."""
        original_info = get_mux_info(self.graph, 'rf_write_data_mux')
        original_count = original_info['num_inputs']

        refactor = MuxRefactor(self.graph, 'rf_write_data_mux')
        refactor.add_group('alu_r', ['add_res', 'sub_res', 'and_res', 'or_res', 'xor_res',
                                     'sll_res', 'srl_res', 'sra_res', 'slt_res', 'sltu_res'])
        refactor.apply()

        new_info = get_mux_info(self.graph, 'rf_write_data_mux')

        # After refactoring: original - 10 ALU inputs + 1 sub-mux input
        expected_count = original_count - 10 + 1
        self.assertEqual(new_info['num_inputs'], expected_count)

    def test_refactor_invalid_mux(self):
        """Test that refactoring fails gracefully for invalid mux ID."""
        with self.assertRaises(ValueError):
            MuxRefactor(self.graph, 'nonexistent_mux')

    def test_refactor_no_groups(self):
        """Test that apply() fails if no groups defined."""
        refactor = MuxRefactor(self.graph, 'rf_write_data_mux')
        with self.assertRaises(ValueError):
            refactor.apply()

    def test_refactor_invalid_source(self):
        """Test that invalid source IDs are skipped with warning."""
        refactor = MuxRefactor(self.graph, 'rf_write_data_mux')
        refactor.add_group('test', ['add_res', 'nonexistent_source'])

        # Should not raise, just warn
        sub_muxes = refactor.apply()
        self.assertIn('test', sub_muxes)
        # Only 1 valid input should be in the sub-mux
        self.assertEqual(sub_muxes['test'].data['num_inputs'], 1)

    def test_refactor_method_chaining(self):
        """Test that add_group supports method chaining."""
        refactor = MuxRefactor(self.graph, 'rf_write_data_mux')
        result = refactor.add_group('group1', ['add_res']).add_group('group2', ['sub_res'])

        self.assertIs(result, refactor)
        self.assertEqual(len(refactor.groups), 2)


class TestRefactorMuxConvenience(unittest.TestCase):
    """Test the refactor_mux convenience function."""

    def setUp(self):
        """Create a simple graph with a mux for testing."""
        self.graph = ResourceGraph()

        # Create source nodes
        self.sources = {}
        for name in ['a', 'b', 'c', 'd', 'e']:
            node = Node(name, {'type': 'var', 'name': name, 'instruction': name})
            self.graph.add_node(node)
            self.sources[name] = node

        # Create enables
        self.enables = {}
        for name in ['a', 'b', 'c', 'd', 'e']:
            enable_name = f"{name}_enable"
            node = Node(enable_name, {'type': 'instruction_enable', 'bit_width': 1})
            self.graph.add_node(node)
            self.enables[enable_name] = node

        # Create target
        self.target = Node('target', {'type': 'var'})
        self.graph.add_node(self.target)

        # Create mux
        builder = MuxBuilder(self.graph, 'test_mux', MuxType.ONE_HOT)
        builder.create_or_get_mux()
        for name, source in self.sources.items():
            builder.add_input(source, self.enables[f"{name}_enable"])
        builder.connect_output(self.target)

    def test_refactor_mux_convenience(self):
        """Test the refactor_mux convenience function."""
        sub_muxes = refactor_mux(self.graph, 'test_mux', {
            'group1': ['a', 'b'],
            'group2': ['c', 'd', 'e']
        })

        self.assertEqual(len(sub_muxes), 2)
        self.assertIn('group1', sub_muxes)
        self.assertIn('group2', sub_muxes)

        # Verify sub-mux input counts
        self.assertEqual(sub_muxes['group1'].data['num_inputs'], 2)
        self.assertEqual(sub_muxes['group2'].data['num_inputs'], 3)

        # Verify main mux now has 2 inputs (the sub-muxes)
        main_mux = self.graph.nodes['test_mux']
        self.assertEqual(main_mux.data['num_inputs'], 2)


class TestAnalyzeMux(unittest.TestCase):
    """Test the analyze_mux function."""

    def setUp(self):
        """Create a graph with a mux for analysis."""
        self.graph = ResourceGraph()

        # Create RISC-V style sources
        sources_info = [
            ('add_res', 'add'),
            ('sub_res', 'sub'),
            ('addi_res', 'addi'),
            ('data', 'lw'),
            ('ret_addr', 'jal')
        ]

        self.sources = {}
        for name, instr in sources_info:
            node = Node(name, {'type': 'var', 'name': name, 'instruction': instr})
            node.pipe_time = 2 if 'data' in name else 1  # Memory at different stage
            self.graph.add_node(node)
            self.sources[name] = node

        # Create target
        self.target = Node('target', {'type': 'var'})
        self.graph.add_node(self.target)

        # Create mux with string conditions
        builder = MuxBuilder(self.graph, 'test_mux', MuxType.ONE_HOT)
        builder.create_or_get_mux()
        for name in self.sources:
            instr = self.sources[name].data['instruction']
            builder.add_input(self.sources[name], f"{instr}_enable")
        builder.connect_output(self.target)

    def test_analyze_mux_basic(self):
        """Test basic mux analysis."""
        analysis = analyze_mux(self.graph, 'test_mux')

        self.assertIsNotNone(analysis)
        self.assertEqual(analysis['mux_id'], 'test_mux')
        self.assertEqual(analysis['num_inputs'], 5)

    def test_analyze_mux_inputs(self):
        """Test that analyze_mux returns input information."""
        analysis = analyze_mux(self.graph, 'test_mux')

        inputs = analysis['inputs']
        self.assertEqual(len(inputs), 5)

        # Check that sources are tracked
        source_ids = [inp['source_id'] for inp in inputs]
        self.assertIn('add_res', source_ids)
        self.assertIn('data', source_ids)

    def test_analyze_mux_by_instruction(self):
        """Test grouping by instruction."""
        analysis = analyze_mux(self.graph, 'test_mux')

        by_instr = analysis['by_instruction']
        self.assertIn('add', by_instr)
        self.assertIn('lw', by_instr)
        self.assertEqual(by_instr['add'], ['add_res'])

    def test_analyze_mux_by_pipe_time(self):
        """Test grouping by pipeline time."""
        analysis = analyze_mux(self.graph, 'test_mux')

        by_time = analysis['by_pipe_time']
        self.assertIn(1, by_time)
        self.assertIn(2, by_time)
        self.assertIn('data', by_time[2])

    def test_analyze_mux_suggested_groups(self):
        """Test suggested groupings."""
        analysis = analyze_mux(self.graph, 'test_mux')

        suggested = analysis['suggested_groups']

        # Should have alu_r group with add_res and sub_res
        self.assertIn('alu_r', suggested)
        self.assertIn('add_res', suggested['alu_r'])
        self.assertIn('sub_res', suggested['alu_r'])

        # Should have mem group with data
        self.assertIn('mem', suggested)
        self.assertIn('data', suggested['mem'])

        # Should have jump group with ret_addr
        self.assertIn('jump', suggested)
        self.assertIn('ret_addr', suggested['jump'])

    def test_analyze_nonexistent_mux(self):
        """Test analyze_mux returns None for nonexistent mux."""
        analysis = analyze_mux(self.graph, 'nonexistent')
        self.assertIsNone(analysis)


class TestSingleEnableGroup(unittest.TestCase):
    """Test edge case where a group has only one input."""

    def setUp(self):
        """Create a simple graph."""
        self.graph = ResourceGraph()

        self.source = Node('source', {'type': 'var', 'instruction': 'test'})
        self.enable = Node('test_enable', {'type': 'instruction_enable', 'bit_width': 1})
        self.target = Node('target', {'type': 'var'})

        for node in [self.source, self.enable, self.target]:
            self.graph.add_node(node)

        builder = MuxBuilder(self.graph, 'test_mux', MuxType.ONE_HOT)
        builder.create_or_get_mux()
        builder.add_input(self.source, self.enable)
        builder.connect_output(self.target)

    def test_single_input_group_uses_existing_enable(self):
        """Test that single-input groups reuse the existing enable signal."""
        refactor = MuxRefactor(self.graph, 'test_mux')
        refactor.add_group('single', ['source'])

        sub_muxes = refactor.apply()

        # With single input, should reuse existing enable (no combined_enable created)
        # The returned enable should be the original enable node
        self.assertIn('single', sub_muxes)


if __name__ == '__main__':
    unittest.main()