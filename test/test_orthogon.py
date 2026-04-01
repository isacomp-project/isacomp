#!/usr/bin/env python3
"""Tests for orthogon parsing and merging."""

import os
import sys
import unittest

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.orthogon_parser import (
    OrthogonParser, OrthogonDefinition, parse_orthogon_file, is_orthogon_file,
)
from core.orthogon_merger import OrthogonMerger
from core.resource_graph import ResourceGraph, Node, Edge
from core.isa_parser import ISAParser


# ── Minimal test orthogon (inline text) ────────────────────────────────

MINIMAL_ORTHOGON = """
orthogon test_orth {
    selector sel[1:0];

    uses {
        isa_state dmem[7:0][7:0];
    }

    provides {
        result[7:0];
    }

    writes {
        isa_state pc[7:0];
    }

    variant a : sel == 2'd0 {
        result = dmem[pc];
        pc = pc + 1;
    }

    variant b : sel == 2'd1 {
        var lo[7:0];
        var hi[7:0];
        lo = dmem[pc];
        pc = pc + 1;
        hi = dmem[pc];
        pc = pc + 1;
        result = dmem[{hi, lo}];
    }
}
"""

TWO_PROVIDES_ORTHOGON = """
orthogon dual_out {
    selector s[0:0];

    provides {
        out_a[7:0];
        out_b[3:0];
    }

    variant lo : s == 1'b0 {
        out_a = 8'h00;
        out_b = 4'h0;
    }

    variant hi : s == 1'b1 {
        out_a = 8'hFF;
        out_b = 4'hF;
    }
}
"""


class TestOrthogonParser(unittest.TestCase):
    """Test orthogon file parsing."""

    def test_parse_minimal(self):
        parser = OrthogonParser()
        defn = parser.parse(MINIMAL_ORTHOGON)

        self.assertEqual(defn.name, 'test_orth')
        self.assertEqual(defn.selector_name, 'sel')
        self.assertEqual(defn.selector_high, 1)
        self.assertEqual(defn.selector_low, 0)
        self.assertEqual(defn.selector_width, 2)

    def test_parse_uses(self):
        parser = OrthogonParser()
        defn = parser.parse(MINIMAL_ORTHOGON)

        self.assertEqual(len(defn.uses), 1)
        self.assertEqual(defn.uses[0].name, 'dmem')
        self.assertEqual(defn.uses[0].bit_high, 7)
        self.assertEqual(defn.uses[0].bit_low, 0)
        self.assertTrue(defn.uses[0].is_memory)
        self.assertEqual(len(defn.uses[0].array_dims), 1)

    def test_parse_provides(self):
        parser = OrthogonParser()
        defn = parser.parse(MINIMAL_ORTHOGON)

        self.assertEqual(len(defn.provides), 1)
        self.assertEqual(defn.provides[0].name, 'result')
        self.assertEqual(defn.provides[0].bit_width, 8)

    def test_parse_writes(self):
        parser = OrthogonParser()
        defn = parser.parse(MINIMAL_ORTHOGON)

        self.assertEqual(len(defn.writes), 1)
        self.assertEqual(defn.writes[0].name, 'pc')
        self.assertEqual(defn.writes[0].bit_width, 8)

    def test_parse_variants(self):
        parser = OrthogonParser()
        defn = parser.parse(MINIMAL_ORTHOGON)

        self.assertEqual(len(defn.variants), 2)
        self.assertEqual(defn.variants[0].name, 'a')
        self.assertEqual(defn.variants[1].name, 'b')

        # Check conditions are parsed as AST dicts
        cond_a = defn.variants[0].condition
        self.assertEqual(cond_a['type'], 'binary_op')
        self.assertEqual(cond_a['operator'], '==')
        self.assertEqual(cond_a['right']['value'], 0)

        cond_b = defn.variants[1].condition
        self.assertEqual(cond_b['right']['value'], 1)

    def test_parse_body_tokens(self):
        parser = OrthogonParser()
        defn = parser.parse(MINIMAL_ORTHOGON)

        # Variant a has simple body: result = mem[pc]; pc = pc + 1;
        self.assertGreater(len(defn.variants[0].body_tokens), 0)
        # Variant b has more complex body
        self.assertGreater(len(defn.variants[1].body_tokens),
                          len(defn.variants[0].body_tokens))

    def test_parse_two_provides(self):
        parser = OrthogonParser()
        defn = parser.parse(TWO_PROVIDES_ORTHOGON)

        self.assertEqual(len(defn.provides), 2)
        names = {p.name for p in defn.provides}
        self.assertEqual(names, {'out_a', 'out_b'})

    def test_provides_by_name(self):
        parser = OrthogonParser()
        defn = parser.parse(TWO_PROVIDES_ORTHOGON)

        by_name = defn.provides_by_name()
        self.assertIn('out_a', by_name)
        self.assertEqual(by_name['out_a'].bit_width, 8)
        self.assertIn('out_b', by_name)
        self.assertEqual(by_name['out_b'].bit_width, 4)

    def test_parse_6502_addr_mode(self):
        """Parse the real 6502 addressing mode orthogon."""
        orth_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'isa', '6502', 'orthogons', 'addr_mode.isa',
        )
        if not os.path.exists(orth_file):
            self.skipTest(f"6502 addr_mode.isa not found at {orth_file}")

        parser = OrthogonParser()
        defn = parser.parse_file(orth_file, preprocess=False)

        self.assertEqual(defn.name, 'addr_mode')
        self.assertEqual(defn.selector_name, 'sel')
        self.assertEqual(defn.selector_width, 4)
        self.assertEqual(len(defn.uses), 3)  # mainmem, X, Y
        self.assertEqual(len(defn.provides), 2)  # data, eff_addr
        self.assertEqual(len(defn.writes), 1)  # pc
        self.assertEqual(len(defn.variants), 9)

        variant_names = [v.name for v in defn.variants]
        self.assertIn('imm', variant_names)
        self.assertIn('abs', variant_names)
        self.assertIn('ind_x', variant_names)
        self.assertIn('zp_ind', variant_names)


class TestOrthogonValidation(unittest.TestCase):
    """Test orthogon validation rules."""

    def test_no_variants_error(self):
        text = """
        orthogon empty {
            selector s[0:0];
            provides { x[7:0]; }
        }
        """
        parser = OrthogonParser()
        with self.assertRaises(ValueError) as ctx:
            parser.parse(text)
        self.assertIn('no variants', str(ctx.exception))

    def test_no_provides_error(self):
        text = """
        orthogon noprov {
            selector s[0:0];
            variant a : s == 1'b0 { }
        }
        """
        parser = OrthogonParser()
        with self.assertRaises(SyntaxError) as ctx:
            parser.parse(text)
        self.assertIn('provides', str(ctx.exception).lower())

    def test_duplicate_variant_names_error(self):
        text = """
        orthogon dupvar {
            selector s[0:0];
            provides { x[7:0]; }
            variant a : s == 1'b0 { x = 8'h00; }
            variant a : s == 1'b1 { x = 8'hFF; }
        }
        """
        parser = OrthogonParser()
        with self.assertRaises(ValueError) as ctx:
            parser.parse(text)
        self.assertIn('duplicate', str(ctx.exception).lower())

    def test_uses_writes_overlap_error(self):
        text = """
        orthogon overlap {
            selector s[0:0];
            uses { isa_state pc[7:0]; }
            provides { x[7:0]; }
            writes { isa_state pc[7:0]; }
            variant a : s == 1'b0 { x = 8'h00; pc = pc + 1; }
        }
        """
        parser = OrthogonParser()
        with self.assertRaises(ValueError) as ctx:
            parser.parse(text)
        self.assertIn('both', str(ctx.exception).lower())


class TestIsOrthogonFile(unittest.TestCase):
    """Test the is_orthogon_file heuristic."""

    def test_orthogon_file(self):
        orth_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'isa', '6502', 'orthogons', 'addr_mode.isa',
        )
        if os.path.exists(orth_file):
            self.assertTrue(is_orthogon_file(orth_file))

    def test_regular_isa_file(self):
        isa_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'isa', '6502', 'adc_imm.isa',
        )
        if os.path.exists(isa_file):
            self.assertFalse(is_orthogon_file(isa_file))


class TestUseStatementParsing(unittest.TestCase):
    """Test that the ISA parser recognizes `use` statements."""

    def test_use_token_recognized(self):
        """Verify the USE token is in the lexer."""
        from core.isa_parser import ISALexer
        lexer = ISALexer()
        tokens = lexer.tokenize("use foo(bar);")
        token_types = [t.type for t in tokens]
        self.assertIn('USE', token_types)

    def test_use_statement_parsed(self):
        """Parse a minimal instruction with a use statement and inline expansion."""
        import tempfile, os

        # Write the orthogon definition to a temp file so the inline
        # expansion can find it.
        tmpdir = tempfile.mkdtemp()
        orth_file = os.path.join(tmpdir, 'test_orth.isa')
        with open(orth_file, 'w') as f:
            f.write(MINIMAL_ORTHOGON)

        instr_file = os.path.join(tmpdir, 'test_instr.isa')
        with open(instr_file, 'w') as f:
            f.write("""
            isa_state pc[7:0];
            isa_state dmem[7:0][7:0];
            var instr[7:0];
            var sel[1:0];
            instr = dmem[pc];
            assume instr == 0x42;
            pc = pc + 1;
            sel = instr[3:2];
            use test_orth(sel);
            """)

        parser = ISAParser()
        graph = parser.parse_file(instr_file)

        # Verify the use declaration was recorded
        self.assertTrue(hasattr(graph, 'orthogon_uses'))
        self.assertEqual(len(graph.orthogon_uses), 1)
        use_decl = graph.orthogon_uses[0]
        self.assertEqual(use_decl['orthogon_name'], 'test_orth')
        self.assertIn('selector_expr', use_decl)
        self.assertIn('selector_node_id', use_decl)

        # Verify that orthogon expansion created nodes
        has_mux = any('result_mux' in nid for nid in graph.nodes)
        self.assertTrue(has_mux, "Expected orthogon mux nodes to be created")

        # Clean up
        import shutil
        shutil.rmtree(tmpdir)


class TestOrthogonImperativeWrites(unittest.TestCase):
    """Test that orthogon variants respect imperative ordering for writes."""

    def test_variant_multi_step_pc_increment(self):
        """
        When a variant body increments a 'writes' state multiple times
        (e.g., pc = pc + 1; pc = pc + 1), the ternary chain should
        select between the FINAL values, not the initial intermediate.
        """
        import tempfile, shutil

        tmpdir = tempfile.mkdtemp()
        orth_file = os.path.join(tmpdir, 'test_orth.isa')
        with open(orth_file, 'w') as f:
            f.write(MINIMAL_ORTHOGON)

        instr_file = os.path.join(tmpdir, 'test_instr.isa')
        with open(instr_file, 'w') as f:
            f.write("""
            isa_state pc[7:0];
            isa_state dmem[7:0][7:0];
            var instr[7:0];
            var sel[1:0];
            instr = dmem[pc];
            assume instr == 0x42;
            pc = pc + 1;
            sel = instr[3:2];
            use test_orth(sel);
            """)

        parser = ISAParser()
        graph = parser.parse_file(instr_file)

        # Find the PC writes ternary node (orthogon creates a ternary
        # chain instead of a mux for writes state).
        ternary_node = None
        for nid, n in graph.nodes.items():
            if (n.data and n.data.get('type') == 'ternary_op'
                    and n.data.get('from_orthogon') and 'pc' in nid):
                ternary_node = n
                break
        self.assertIsNotNone(ternary_node,
                             "PC ternary select not found in graph")

        # The ternary should have two different value sources
        # (true branch = one PC value, false branch = another)
        true_src = None
        false_src = None
        for e in ternary_node.incoming_edges:
            if e.data.get('type') == 'ternary_true':
                true_src = e.source
            elif e.data.get('type') == 'ternary_false':
                false_src = e.source

        self.assertIsNotNone(true_src, "Ternary missing true branch")
        self.assertIsNotNone(false_src, "Ternary missing false branch")
        self.assertNotEqual(
            true_src.id, false_src.id,
            f"Ternary true and false branches should differ "
            f"(multi-step imperative writes), but both got '{true_src.id}'"
        )

        shutil.rmtree(tmpdir)

    def test_6502_pc_advancement(self):
        """
        Verify that the real 6502 addr_mode orthogon correctly tracks
        per-variant PC advancement via a ternary select (pc+2 vs pc+3).
        """
        lda_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'isa', '6502', 'orthogonal', 'lda.isa',
        )
        if not os.path.exists(lda_file):
            self.skipTest("6502 lda.isa not found")

        from core.resource_graph import ResourceGraph
        graph = ResourceGraph.from_isa_file(lda_file)

        # Find the PC writes ternary node
        pc_ternary = None
        for nid, n in graph.nodes.items():
            if (n.data and n.data.get('type') == 'ternary_op'
                    and n.data.get('from_orthogon')
                    and 'pc' in nid):
                pc_ternary = n
                break
        self.assertIsNotNone(pc_ternary, "PC writes ternary not found in LDA graph")

        # The ternary selects between 2 PC values
        true_src = false_src = None
        for e in pc_ternary.incoming_edges:
            if e.data.get('type') == 'ternary_true':
                true_src = e.source.id
            elif e.data.get('type') == 'ternary_false':
                false_src = e.source.id

        self.assertIsNotNone(true_src, "Ternary missing true branch")
        self.assertIsNotNone(false_src, "Ternary missing false branch")
        self.assertNotEqual(true_src, false_src,
                           "pc+2 and pc+3 must be different values")


class TestOrthogonMergerSetup(unittest.TestCase):
    """Test OrthogonMerger registration and loading."""

    def test_register_orthogon(self):
        graph = ResourceGraph()
        merger = OrthogonMerger(graph)

        parser = OrthogonParser()
        defn = parser.parse(MINIMAL_ORTHOGON)

        merger.register_orthogon(defn)
        self.assertIn('test_orth', merger.orthogons)

    def test_register_duplicate_same_file(self):
        """Re-registering from the same file is OK."""
        graph = ResourceGraph()
        merger = OrthogonMerger(graph)

        parser = OrthogonParser()
        defn = parser.parse(MINIMAL_ORTHOGON)
        defn.source_file = '/fake/path.isa'

        merger.register_orthogon(defn)
        merger.register_orthogon(defn)  # Should not raise

    def test_register_duplicate_different_file(self):
        """Re-registering from a different file is an error."""
        graph = ResourceGraph()
        merger = OrthogonMerger(graph)

        parser = OrthogonParser()
        defn1 = parser.parse(MINIMAL_ORTHOGON)
        defn1.source_file = '/fake/path1.isa'

        defn2 = parser.parse(MINIMAL_ORTHOGON)
        defn2.source_file = '/fake/path2.isa'

        merger.register_orthogon(defn1)
        with self.assertRaises(ValueError):
            merger.register_orthogon(defn2)


if __name__ == '__main__':
    unittest.main()
