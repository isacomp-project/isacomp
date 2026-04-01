#!/usr/bin/env python3
"""
Tests for UnrollSharedOperationsTransform

Tests the functionality to reverse resource sharing optimizations by
unrolling shared operations back into parallel operations.

Author: Claude
Date: 2025-10-20
"""

import unittest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.resource_graph import ResourceGraph, Node, Edge
from opt.sharing.unroll_shared_operations import UnrollSharedOperationsTransform, unroll_shared_operations


class TestUnrollSharedOperations(unittest.TestCase):
    """Test cases for unrolling shared operations."""

    def setUp(self):
        """Set up common test fixtures."""
        self.graph = ResourceGraph()

    def test_identify_shared_resources(self):
        """Test identification of shared resources."""
        # Create a shared operation
        shared_op = Node(
            node_id='shared_add',
            data={'operator': '+', 'shared_resource': True, 'time_slot': 0},
            is_arch_state=False
        )
        self.graph.add_node(shared_op)

        # Create a pipeline register
        pipeline_reg = Node(
            node_id='input_t0_reg',
            data={'type': 'pipeline_register'},
            is_uarch_state=True
        )
        self.graph.add_node(pipeline_reg)

        # Create a counter
        counter = Node(
            node_id='uarch_counter',
            data={'type': 'counter'},
            is_uarch_state=True
        )
        self.graph.add_node(counter)

        # Add control edge from counter to shared op
        control_edge = Edge(counter, shared_op, data={'type': 'resource_control'})
        self.graph.add_edge(control_edge)

        # Run identification
        transform = UnrollSharedOperationsTransform(self.graph)
        transform._identify_shared_resources()

        # Verify
        self.assertEqual(len(transform.shared_operations), 1)
        self.assertIn(shared_op, transform.shared_operations)
        self.assertIn(pipeline_reg, transform.pipeline_registers)
        self.assertIn(counter, transform.counter_nodes)

    def test_extract_time_slot(self):
        """Test extracting time slot from node IDs."""
        transform = UnrollSharedOperationsTransform(self.graph)

        self.assertEqual(transform._extract_time_slot('input_t0_reg'), 0)
        self.assertEqual(transform._extract_time_slot('input_t1_reg'), 1)
        self.assertEqual(transform._extract_time_slot('result_t2_reg'), 2)
        self.assertEqual(transform._extract_time_slot('add_t5'), 5)
        self.assertIsNone(transform._extract_time_slot('no_slot'))

    def test_unroll_simple_shared_operation(self):
        """Test unrolling a simple shared operation without time slots."""
        # Create a shared operation
        shared_op = Node(
            node_id='shared_mul',
            data={
                'operator': '*',
                'shared_resource': True,
                'display_name': 'Shared mul'
            },
            is_arch_state=False
        )
        self.graph.add_node(shared_op)

        # Create inputs and outputs
        input1 = Node(node_id='r1', data={}, is_arch_state=True)
        input2 = Node(node_id='r2', data={}, is_arch_state=True)
        output = Node(node_id='r3', data={}, is_arch_state=True)

        self.graph.add_node(input1)
        self.graph.add_node(input2)
        self.graph.add_node(output)

        # Connect
        self.graph.add_edge(Edge(input1, shared_op, data={'operand': 0}))
        self.graph.add_edge(Edge(input2, shared_op, data={'operand': 1}))
        self.graph.add_edge(Edge(shared_op, output, data={'type': 'assignment'}))

        # Unroll
        result = unroll_shared_operations(self.graph)

        self.assertTrue(result)

        # The original shared operation should be removed or unshared
        # Check if there's still a node with the same ID
        if 'shared_mul' in self.graph.nodes:
            # If it's still there, it should no longer be marked as shared
            node = self.graph.nodes['shared_mul']
            self.assertFalse(node.data.get('shared_resource', False))
            self.assertEqual(node.data.get('display_name'), 'mul')
        else:
            # If it's been removed, check that there's a mul operation
            mul_ops = [n for n in self.graph.nodes.values()
                      if n.data.get('operator') == '*' and not n.data.get('shared_resource', False)]
            self.assertGreater(len(mul_ops), 0)

    def test_unroll_with_time_slots(self):
        """Test unrolling shared operations with time slots."""
        # Create shared addition operation
        shared_add = Node(
            node_id='shared_add',
            data={
                'operator': '+',
                'shared_resource': True,
                'display_name': 'Shared add [slot 0]'
            },
            is_arch_state=False
        )
        self.graph.add_node(shared_add)

        # Create two sets of inputs for two time slots
        # Time slot 0
        r1 = Node(node_id='r1', data={'value': 5}, is_arch_state=True)
        r2 = Node(node_id='r2', data={'value': 3}, is_arch_state=True)
        r1_t0_reg = Node(node_id='r1_t0_reg', data={'type': 'pipeline_register'}, is_uarch_state=True)
        r2_t0_reg = Node(node_id='r2_t0_reg', data={'type': 'pipeline_register'}, is_uarch_state=True)
        result_t0_reg = Node(node_id='add_result_t0_reg', data={'type': 'pipeline_register'}, is_uarch_state=True)
        dest0 = Node(node_id='r4', data={}, is_arch_state=True)

        # Time slot 1
        r3 = Node(node_id='r3', data={'value': 7}, is_arch_state=True)
        imm = Node(node_id='imm_10', data={'value': 10, 'type': 'literal'}, is_arch_state=False)
        r3_t1_reg = Node(node_id='r3_t1_reg', data={'type': 'pipeline_register'}, is_uarch_state=True)
        imm_t1_reg = Node(node_id='imm_t1_reg', data={'type': 'pipeline_register'}, is_uarch_state=True)
        result_t1_reg = Node(node_id='add_result_t1_reg', data={'type': 'pipeline_register'}, is_uarch_state=True)
        dest1 = Node(node_id='r5', data={}, is_arch_state=True)

        # Counter
        counter = Node(node_id='uarch_counter', data={'type': 'counter'}, is_uarch_state=True)

        # Add all nodes
        for node in [r1, r2, r3, imm, r1_t0_reg, r2_t0_reg, r3_t1_reg, imm_t1_reg,
                     result_t0_reg, result_t1_reg, dest0, dest1, counter]:
            self.graph.add_node(node)

        # Build time slot 0 dataflow
        self.graph.add_edge(Edge(r1, r1_t0_reg, data={'type': 'pipeline_stage'}))
        self.graph.add_edge(Edge(r2, r2_t0_reg, data={'type': 'pipeline_stage'}))
        self.graph.add_edge(Edge(r1_t0_reg, shared_add, data={'operand': 0}))
        self.graph.add_edge(Edge(r2_t0_reg, shared_add, data={'operand': 1}))
        self.graph.add_edge(Edge(shared_add, result_t0_reg, data={'type': 'result_capture'}))
        self.graph.add_edge(Edge(result_t0_reg, dest0, data={'type': 'assignment'}))

        # Build time slot 1 dataflow
        self.graph.add_edge(Edge(r3, r3_t1_reg, data={'type': 'pipeline_stage'}))
        self.graph.add_edge(Edge(imm, imm_t1_reg, data={'type': 'pipeline_stage'}))
        self.graph.add_edge(Edge(r3_t1_reg, shared_add, data={'operand': 0}))
        self.graph.add_edge(Edge(imm_t1_reg, shared_add, data={'operand': 1}))
        self.graph.add_edge(Edge(shared_add, result_t1_reg, data={'type': 'result_capture'}))
        self.graph.add_edge(Edge(result_t1_reg, dest1, data={'type': 'assignment'}))

        # Add counter control
        self.graph.add_edge(Edge(counter, shared_add, data={'type': 'resource_control', 'time_slot': 0}))

        # Store original node count
        original_node_count = len(self.graph.nodes)

        # Unroll
        result = unroll_shared_operations(self.graph)

        self.assertTrue(result)

        # Verify shared operation is removed
        self.assertNotIn('shared_add', self.graph.nodes)

        # Verify two new operations were created
        unrolled_ops = [n for n in self.graph.nodes.values()
                        if 'shared_add_unrolled' in n.id]
        self.assertEqual(len(unrolled_ops), 2)

        # Verify operations connect to original sources
        # Find the unrolled operation for time slot 0
        t0_op = next((n for n in unrolled_ops if '_t0' in n.id), None)
        self.assertIsNotNone(t0_op)

        # Check that r1 and r2 connect to t0_op
        t0_sources = [e.source.id for e in t0_op.incoming_edges]
        self.assertIn('r1', t0_sources)
        self.assertIn('r2', t0_sources)

        # Check that t0_op connects to dest0
        t0_targets = [e.target.id for e in t0_op.outgoing_edges]
        self.assertIn('r4', t0_targets)

        # Verify pipeline registers are removed
        pipeline_regs = [n for n in self.graph.nodes.values()
                        if '_t0_reg' in n.id or '_t1_reg' in n.id]
        self.assertEqual(len(pipeline_regs), 0)

        # Verify counter is removed
        self.assertNotIn('uarch_counter', self.graph.nodes)

    def test_remove_isa_state_gating(self):
        """Test removal of ISA state gating conditions."""
        # Create ISA state node
        isa_reg = Node(node_id='r1', data={}, is_arch_state=True)
        self.graph.add_node(isa_reg)

        # Create source node
        source = Node(node_id='add_result', data={'operator': '+'}, is_arch_state=False)
        self.graph.add_node(source)

        # Create gated assignment
        gated_edge = Edge(
            source, isa_reg,
            data={
                'type': 'assignment',
                'gated_by': 'counter_max',
                'condition': 'counter == 1'
            }
        )
        self.graph.add_edge(gated_edge)

        # Run transform
        transform = UnrollSharedOperationsTransform(self.graph)
        transform._remove_isa_state_gating()

        # Verify gating is removed
        edge = list(isa_reg.incoming_edges)[0]
        self.assertNotIn('gated_by', edge.data)
        self.assertNotIn('condition', edge.data)

    def test_round_trip_resource_sharing(self):
        """Test that manually creating shared operations and then unrolling preserves correctness."""
        # Create a manually-shared graph (simulating what resource sharing would do)
        r1 = Node(node_id='r1', data={}, is_arch_state=True)
        r2 = Node(node_id='r2', data={}, is_arch_state=True)
        r3 = Node(node_id='r3', data={}, is_arch_state=True)
        imm = Node(node_id='imm_5', data={'type': 'literal', 'value': 5}, is_arch_state=False)

        # Create a shared operation
        shared_add = Node(
            node_id='shared_add',
            data={'operator': '+', 'shared_resource': True, 'display_name': 'Shared add'},
            is_arch_state=False
        )

        # Pipeline registers for time slot 0
        r1_t0 = Node(node_id='r1_t0_reg', data={'type': 'pipeline_register'}, is_uarch_state=True)
        r2_t0 = Node(node_id='r2_t0_reg', data={'type': 'pipeline_register'}, is_uarch_state=True)
        res_t0 = Node(node_id='res_t0_reg', data={'type': 'pipeline_register'}, is_uarch_state=True)

        # Pipeline registers for time slot 1
        r3_t1 = Node(node_id='r3_t1_reg', data={'type': 'pipeline_register'}, is_uarch_state=True)
        imm_t1 = Node(node_id='imm_t1_reg', data={'type': 'pipeline_register'}, is_uarch_state=True)
        res_t1 = Node(node_id='res_t1_reg', data={'type': 'pipeline_register'}, is_uarch_state=True)

        dest1 = Node(node_id='r4', data={}, is_arch_state=True)
        dest2 = Node(node_id='r5', data={}, is_arch_state=True)

        counter = Node(node_id='uarch_counter', data={'type': 'counter'}, is_uarch_state=True)

        for node in [r1, r2, r3, imm, shared_add, r1_t0, r2_t0, r3_t1, imm_t1,
                     res_t0, res_t1, dest1, dest2, counter]:
            self.graph.add_node(node)

        # Build time slot 0
        self.graph.add_edge(Edge(r1, r1_t0, data={'type': 'pipeline_stage'}))
        self.graph.add_edge(Edge(r2, r2_t0, data={'type': 'pipeline_stage'}))
        self.graph.add_edge(Edge(r1_t0, shared_add, data={'operand': 0}))
        self.graph.add_edge(Edge(r2_t0, shared_add, data={'operand': 1}))
        self.graph.add_edge(Edge(shared_add, res_t0, data={'type': 'result_capture'}))
        self.graph.add_edge(Edge(res_t0, dest1, data={'type': 'assignment'}))

        # Build time slot 1
        self.graph.add_edge(Edge(r3, r3_t1, data={'type': 'pipeline_stage'}))
        self.graph.add_edge(Edge(imm, imm_t1, data={'type': 'pipeline_stage'}))
        self.graph.add_edge(Edge(r3_t1, shared_add, data={'operand': 0}))
        self.graph.add_edge(Edge(imm_t1, shared_add, data={'operand': 1}))
        self.graph.add_edge(Edge(shared_add, res_t1, data={'type': 'result_capture'}))
        self.graph.add_edge(Edge(res_t1, dest2, data={'type': 'assignment'}))

        # Counter control
        self.graph.add_edge(Edge(counter, shared_add, data={'type': 'resource_control', 'time_slot': 0}))

        # Now unroll
        unroll_result = unroll_shared_operations(self.graph)
        self.assertTrue(unroll_result)

        # Verify shared operation is removed
        self.assertNotIn('shared_add', self.graph.nodes)

        # Verify we have separate operations
        unrolled_ops = [n for n in self.graph.nodes.values()
                       if n.data.get('operator') == '+' and not n.data.get('shared_resource', False)]
        self.assertEqual(len(unrolled_ops), 2)

        # Verify dataflow is preserved - dest1 should connect to r1 and r2
        dest1_node = self.graph.nodes['r4']
        add_to_dest1 = [e.source for e in dest1_node.incoming_edges
                       if e.source.data.get('operator') == '+']
        self.assertEqual(len(add_to_dest1), 1)

        # That add should have inputs from r1 and r2
        add_op = add_to_dest1[0]
        sources = [e.source.id for e in add_op.incoming_edges]
        self.assertIn('r1', sources)
        self.assertIn('r2', sources)

        # Verify pipeline registers are removed
        regs = [n for n in self.graph.nodes.values() if '_t0_reg' in n.id or '_t1_reg' in n.id]
        self.assertEqual(len(regs), 0)

        # Verify counter is removed
        self.assertNotIn('uarch_counter', self.graph.nodes)

    def test_no_shared_operations(self):
        """Test that unroll returns False when no shared operations exist."""
        # Create a simple graph without sharing
        r1 = Node(node_id='r1', data={}, is_arch_state=True)
        add = Node(node_id='add1', data={'operator': '+'}, is_arch_state=False)
        r2 = Node(node_id='r2', data={}, is_arch_state=True)

        self.graph.add_node(r1)
        self.graph.add_node(add)
        self.graph.add_node(r2)

        self.graph.add_edge(Edge(r1, add, data={'operand': 0}))
        self.graph.add_edge(Edge(add, r2, data={'type': 'assignment'}))

        # Unroll should return False
        result = unroll_shared_operations(self.graph)
        self.assertFalse(result)

    def test_cleanup_removes_all_infrastructure(self):
        """Test that counter, registers, and control edges are fully removed."""
        # Build a minimal shared resource setup
        counter = Node(node_id='uarch_counter', data={'type': 'counter'}, is_uarch_state=True)
        counter_inc = Node(node_id='counter_increment', data={'operator': '+'}, is_uarch_state=True)
        one = Node(node_id='counter_one', data={'type': 'literal', 'value': 1}, is_arch_state=False)

        shared_op = Node(node_id='shared_add', data={'operator': '+', 'shared_resource': True}, is_arch_state=False)
        r1_t0 = Node(node_id='r1_t0_reg', data={'type': 'pipeline_register'}, is_uarch_state=True)
        r2_t0 = Node(node_id='r2_t0_reg', data={'type': 'pipeline_register'}, is_uarch_state=True)

        r1 = Node(node_id='r1', data={}, is_arch_state=True)
        r2 = Node(node_id='r2', data={}, is_arch_state=True)
        r3 = Node(node_id='r3', data={}, is_arch_state=True)

        for node in [counter, counter_inc, one, shared_op, r1_t0, r2_t0, r1, r2, r3]:
            self.graph.add_node(node)

        # Build counter logic
        self.graph.add_edge(Edge(one, counter_inc, data={'operand': 1}))
        self.graph.add_edge(Edge(counter, counter_inc, data={'operand': 0}))
        self.graph.add_edge(Edge(counter_inc, counter, data={'type': 'assignment'}))

        # Build resource control
        self.graph.add_edge(Edge(counter, shared_op, data={'type': 'resource_control', 'time_slot': 0}))

        # Build dataflow
        self.graph.add_edge(Edge(r1, r1_t0, data={'type': 'pipeline_stage'}))
        self.graph.add_edge(Edge(r2, r2_t0, data={'type': 'pipeline_stage'}))
        self.graph.add_edge(Edge(r1_t0, shared_op, data={'operand': 0}))
        self.graph.add_edge(Edge(r2_t0, shared_op, data={'operand': 1}))
        self.graph.add_edge(Edge(shared_op, r3, data={'type': 'assignment'}))

        # Count infrastructure before
        counters_before = len([n for n in self.graph.nodes.values() if 'counter' in n.id])
        regs_before = len([n for n in self.graph.nodes.values() if '_t0_reg' in n.id])

        self.assertGreater(counters_before, 0)
        self.assertGreater(regs_before, 0)

        # Unroll
        result = unroll_shared_operations(self.graph)
        self.assertTrue(result)

        # Verify all infrastructure is removed
        counters_after = len([n for n in self.graph.nodes.values() if 'counter' in n.id])
        regs_after = len([n for n in self.graph.nodes.values() if '_t0_reg' in n.id])

        self.assertEqual(counters_after, 0)
        self.assertEqual(regs_after, 0)

        # Verify no resource_control edges remain
        control_edges = [e for e in self.graph.edges.values()
                        if e.data.get('type') == 'resource_control']
        self.assertEqual(len(control_edges), 0)


if __name__ == '__main__':
    unittest.main()
