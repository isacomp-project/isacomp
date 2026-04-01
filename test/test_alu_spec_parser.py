#!/usr/bin/env python3
"""Tests for ALU spec parsing and graph integration."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alu_spec_parser import (
    ALUSpecParser,
    EnhancedALUSpec,
    OPERATOR_MAPPING,
    parse_alu_spec,
    parse_alu_spec_file,
)
from opt.alu_integration import ALUSpec


def _spec_path(*parts):
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo_root, *parts)


class TestParseCompleteSpec(unittest.TestCase):
    """Parse examples/complete_alu.spec and verify the result."""

    def setUp(self):
        specs = parse_alu_spec_file(_spec_path('examples', 'complete_alu.spec'))
        self.assertEqual(len(specs), 1)
        self.alu = specs[0]

    def test_module_name_and_width(self):
        self.assertEqual(self.alu.name, 'ProcessorALU')
        self.assertEqual(self.alu.input_width, 32)
        self.assertEqual(self.alu.output_width, 32)

    def test_operation_count(self):
        self.assertEqual(len(self.alu.operation_definitions), 14)

    def test_opcode_width(self):
        self.assertEqual(self.alu.opcode_width, 4)

    def test_operator_mapping(self):
        self.assertEqual(self.alu.get_opcode('+'), 0)
        self.assertEqual(self.alu.get_opcode('-'), 1)
        self.assertEqual(self.alu.get_opcode('<<'), 5)
        self.assertEqual(self.alu.get_opcode('>>>'), 7)
        self.assertEqual(self.alu.get_opcode('<s'), 8)
        self.assertEqual(self.alu.get_opcode('<'), 9)
        self.assertEqual(self.alu.get_opcode('=='), 10)
        self.assertEqual(self.alu.get_opcode('>=s'), 12)

    def test_function_body_preserved(self):
        add = self.alu.operation_definitions['add']
        self.assertEqual(add.function, 'result = operand_a + operand_b;')

    def test_description_preserved(self):
        slt = self.alu.operation_definitions['slt']
        self.assertEqual(slt.description, 'Set less than (signed)')

    def test_complex_function_body(self):
        slt = self.alu.operation_definitions['slt']
        self.assertIn('$signed', slt.function)
        self.assertIn("32'h1", slt.function)

    def test_isinstance(self):
        self.assertIsInstance(self.alu, ALUSpec)
        self.assertIsInstance(self.alu, EnhancedALUSpec)


class TestParseMIPS32Spec(unittest.TestCase):
    """Parse isa/mips32/mips32_alu.spec and verify the result."""

    def test_mips32_alu_spec(self):
        specs = parse_alu_spec_file(_spec_path('isa', 'mips32', 'mips32_alu.spec'))
        self.assertEqual(len(specs), 1)
        alu = specs[0]
        self.assertEqual(alu.name, 'MIPS32_ALU')
        self.assertEqual(alu.input_width, 32)
        self.assertEqual(len(alu.operation_definitions), 11)
        self.assertEqual(alu.opcode_width, 4)


class TestParserErrors(unittest.TestCase):
    """Parser should give clear errors on malformed input."""

    def test_operation_outside_module(self):
        with self.assertRaises(ValueError) as ctx:
            parse_alu_spec('operation add { opcode = 0; function = "x"; }')
        self.assertIn('outside', str(ctx.exception).lower())

    def test_missing_brace(self):
        with self.assertRaises(ValueError):
            parse_alu_spec('alu_module A[31:0];\noperation add = 0;')

    def test_missing_closing_brace(self):
        with self.assertRaises(ValueError):
            parse_alu_spec('alu_module A[31:0];\noperation add {\nopcode = 0;\n')

    def test_missing_module_name(self):
        with self.assertRaises(ValueError):
            parse_alu_spec('alu_module ;')


class TestOperatorMapping(unittest.TestCase):
    """OPERATOR_MAPPING must match the operators ISAParser produces."""

    def test_signed_comparisons(self):
        self.assertEqual(OPERATOR_MAPPING['slt'], '<s')
        self.assertEqual(OPERATOR_MAPPING['sge'], '>=s')

    def test_unsigned_comparisons(self):
        self.assertEqual(OPERATOR_MAPPING['sltu'], '<')
        self.assertEqual(OPERATOR_MAPPING['sgeu'], '>=')

    def test_shifts(self):
        self.assertEqual(OPERATOR_MAPPING['sll'], '<<')
        self.assertEqual(OPERATOR_MAPPING['srl'], '>>')
        self.assertEqual(OPERATOR_MAPPING['sra'], '>>>')


class TestALUIntegrationWithRV32I(unittest.TestCase):
    """End-to-end: parse ALU spec, merge RV32I, integrate named nodes."""

    def test_graph_transform(self):
        from core.graph_merger import merge_instructions
        from opt.alu_integration import apply_alu_integration, validate_node

        instructions = ['add', 'sub', 'and', 'or', 'xor', 'sll', 'beq']
        isa_files = {
            instr: _spec_path('isa', 'riscv32', f'{instr}.isa')
            for instr in instructions
        }
        graph = merge_instructions(isa_files)
        alu_specs = parse_alu_spec_file(_spec_path('examples', 'complete_alu.spec'))
        alu_spec = alu_specs[0]

        node_ids = [
            '(r1 + r2)', '(r1 - r2)', '(r1 & r2)',
            '(r1 | r2)', '(r1 ^ r2)', '(r1 << r2[4:0])',
            '(r1 == r2)',
        ]
        # All should pass validation
        for nid in node_ids:
            self.assertIsNone(validate_node(graph, nid, alu_spec), nid)

        self.assertTrue(apply_alu_integration(graph, alu_spec, node_ids))

        # One ALU module node created
        alu_nodes = [n for n in graph.nodes.values()
                     if n.data.get('type') == 'alu_module']
        self.assertEqual(len(alu_nodes), 1)
        self.assertEqual(alu_nodes[0].data['alu_spec'].name, 'ProcessorALU')

        # Original nodes should be gone
        for nid in node_ids:
            self.assertNotIn(nid, graph.nodes)

        # ALU routes results to downstream targets
        self.assertGreater(len(alu_nodes[0].outgoing_edges), 0)

    def test_validation_rejects_bad_nodes(self):
        from core.graph_merger import merge_instructions
        from opt.alu_integration import validate_node

        graph = merge_instructions({
            instr: _spec_path('isa', 'riscv32', f'{instr}.isa')
            for instr in ['add', 'beq']
        })
        alu_specs = parse_alu_spec_file(_spec_path('examples', 'complete_alu.spec'))
        alu_spec = alu_specs[0]

        # Non-existent node
        self.assertIsNotNone(validate_node(graph, 'bogus', alu_spec))

        # PC adder — no enable signal (shared, no group_members)
        err = validate_node(graph, '(pc + 4)', alu_spec)
        self.assertIsNotNone(err)

    def test_raises_on_invalid_node(self):
        from core.graph_merger import merge_instructions
        from opt.alu_integration import apply_alu_integration

        graph = merge_instructions({
            'add': _spec_path('isa', 'riscv32', 'add.isa'),
        })
        alu_specs = parse_alu_spec_file(_spec_path('examples', 'complete_alu.spec'))

        with self.assertRaises(ValueError):
            apply_alu_integration(graph, alu_specs[0], ['bogus_node'])


if __name__ == '__main__':
    unittest.main()
