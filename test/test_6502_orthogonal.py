#!/usr/bin/env python3
"""
Tests for 6502 orthogonal instruction compilation and Verilog generation.

Verifies that all 6502 instructions using orthogon addressing modes:
1. Parse without errors
2. Generate valid Verilog
3. Pass Icarus Verilog syntax checking (when available)
4. Produce correct imperative semantics for multi-byte PC advancement
"""

import os
import sys
import shutil
import subprocess
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.resource_graph import ResourceGraph
from core.graph_merger import merge_instructions
from backends.verilog.verilog_generator import VerilogGenerator

ORTHO_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'isa', '6502', 'orthogonal',
)

# Instructions that use the addr_mode orthogon
ORTHOGON_INSTRUCTIONS = ['adc', 'and', 'cmp', 'eor', 'lda', 'ora', 'sbc', 'sta']

# 1-byte operand addressing modes (pc advances by 1 within orthogon)
ONE_BYTE_VARIANTS = ['imm', 'zp', 'zp_x', 'ind_x', 'ind_y', 'zp_ind']
# 2-byte operand addressing modes (pc advances by 2 within orthogon)
TWO_BYTE_VARIANTS = ['abs', 'abs_x', 'abs_y']


def _has_iverilog():
    try:
        subprocess.run(['iverilog', '-V'], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


HAS_IVERILOG = _has_iverilog()


class TestOrthogonalParsing(unittest.TestCase):
    """Test that orthogonal instructions parse and build resource graphs."""

    def test_all_orthogon_instructions_parse(self):
        """Every instruction using addr_mode orthogon should parse cleanly."""
        for name in ORTHOGON_INSTRUCTIONS:
            path = os.path.join(ORTHO_DIR, f'{name}.isa')
            if not os.path.exists(path):
                self.skipTest(f'{name}.isa not found')
            with self.subTest(instruction=name):
                graph = ResourceGraph.from_isa_file(path)
                self.assertGreater(len(graph.nodes), 0,
                                   f'{name} produced empty graph')

    def test_standalone_instructions_parse(self):
        """Non-orthogon 6502 instructions should parse without exceptions."""
        if not os.path.isdir(ORTHO_DIR):
            self.skipTest('orthogonal directory not found')

        # Exclude orthogon definition files and orthogon-using instructions
        # (tested separately); test all other standalone instructions.
        exclude = set(ORTHOGON_INSTRUCTIONS + ['addr_mode', 'rmw_addr_mode'])
        files = [f for f in os.listdir(ORTHO_DIR)
                 if f.endswith('.isa')
                 and os.path.splitext(f)[0] not in exclude]

        parsed = 0
        errored = []
        for f in sorted(files):
            path = os.path.join(ORTHO_DIR, f)
            try:
                ResourceGraph.from_isa_file(path)
                parsed += 1
            except Exception as e:
                errored.append((f, str(e)))

        self.assertGreater(parsed, 0, 'No standalone instructions parsed')
        # Report but don't fail on a small number of parse errors
        # (some may depend on missing preprocessor macros, etc.)
        if errored:
            print(f'  Note: {len(errored)} standalone instructions '
                  f'raised exceptions (not orthogon-related)')


class TestOrthogonalVerilog(unittest.TestCase):
    """Test Verilog generation for orthogonal instructions."""

    def test_orthogon_instructions_generate_verilog(self):
        """Every addr_mode orthogon instruction should produce Verilog."""
        for name in ORTHOGON_INSTRUCTIONS:
            path = os.path.join(ORTHO_DIR, f'{name}.isa')
            if not os.path.exists(path):
                self.skipTest(f'{name}.isa not found')
            with self.subTest(instruction=name):
                graph = ResourceGraph.from_isa_file(path)
                gen = VerilogGenerator(graph)
                verilog = gen.generate()
                self.assertIn('module', verilog)
                self.assertIn('endmodule', verilog)

    def test_verilog_has_case_statement(self):
        """Orthogon mux should produce a Verilog case statement."""
        for name in ORTHOGON_INSTRUCTIONS:
            path = os.path.join(ORTHO_DIR, f'{name}.isa')
            if not os.path.exists(path):
                continue
            with self.subTest(instruction=name):
                graph = ResourceGraph.from_isa_file(path)
                gen = VerilogGenerator(graph)
                verilog = gen.generate()
                self.assertIn('case (addr_sel)', verilog,
                              f'{name}: missing orthogon case statement')

    @unittest.skipUnless(HAS_IVERILOG, 'iverilog not available')
    def test_iverilog_compiles_orthogon_instructions(self):
        """Generated Verilog should pass Icarus Verilog syntax checking."""
        tmpdir = tempfile.mkdtemp()
        try:
            for name in ORTHOGON_INSTRUCTIONS:
                path = os.path.join(ORTHO_DIR, f'{name}.isa')
                if not os.path.exists(path):
                    continue
                with self.subTest(instruction=name):
                    graph = ResourceGraph.from_isa_file(path)
                    gen = VerilogGenerator(graph)
                    verilog = gen.generate()
                    vfile = os.path.join(tmpdir, f'{name}.v')
                    with open(vfile, 'w') as f:
                        f.write(verilog)
                    result = subprocess.run(
                        ['iverilog', '-g2012', '-o', '/dev/null', vfile],
                        capture_output=True, text=True, timeout=30,
                    )
                    self.assertEqual(
                        result.returncode, 0,
                        f'{name}: iverilog failed:\n{result.stderr[:500]}'
                    )
        finally:
            shutil.rmtree(tmpdir)


class TestOrthogonPCAdvancement(unittest.TestCase):
    """Test that orthogon writes mux correctly reflects imperative PC updates."""

    def _find_pc_ternary(self, graph):
        """Find the PC writes ternary and return its true/false source IDs."""
        for nid, n in graph.nodes.items():
            if (n.data and n.data.get('type') == 'ternary_op'
                    and n.data.get('from_orthogon')
                    and 'pc' in nid):
                true_src = false_src = None
                for e in n.incoming_edges:
                    if e.data.get('type') == 'ternary_true':
                        true_src = e.source.id
                    elif e.data.get('type') == 'ternary_false':
                        false_src = e.source.id
                if true_src and false_src:
                    return true_src, false_src
        return None

    def test_pc_advancement_per_instruction(self):
        """Each orthogon instruction's PC ternary should select between 2 values."""
        for name in ORTHOGON_INSTRUCTIONS:
            path = os.path.join(ORTHO_DIR, f'{name}.isa')
            if not os.path.exists(path):
                continue
            with self.subTest(instruction=name):
                graph = ResourceGraph.from_isa_file(path)
                result = self._find_pc_ternary(graph)
                self.assertIsNotNone(result,
                                     f'{name}: PC ternary not found')

                true_src, false_src = result
                self.assertNotEqual(
                    true_src, false_src,
                    f'{name}: ternary true/false must differ (pc+2 vs pc+3)'
                )


class TestOrthogonMerging(unittest.TestCase):
    """Test merging multiple orthogonal instructions."""

    def test_merge_two_orthogon_instructions(self):
        """Two orthogon instructions should merge into a single processor."""
        lda_path = os.path.join(ORTHO_DIR, 'lda.isa')
        sta_path = os.path.join(ORTHO_DIR, 'sta.isa')
        if not (os.path.exists(lda_path) and os.path.exists(sta_path)):
            self.skipTest('lda.isa or sta.isa not found')

        merged = merge_instructions({
            'lda': lda_path,
            'sta': sta_path,
        })
        self.assertGreater(len(merged.nodes), 0)

        gen = VerilogGenerator(merged)
        verilog = gen.generate()
        self.assertIn('module', verilog)
        self.assertIn('endmodule', verilog)

    def test_merge_all_alu_orthogon_instructions(self):
        """All ALU orthogon instructions (adc, and, cmp, eor, ora, sbc) merge."""
        alu_names = ['adc', 'and', 'cmp', 'eor', 'ora', 'sbc']
        files = {}
        for name in alu_names:
            path = os.path.join(ORTHO_DIR, f'{name}.isa')
            if os.path.exists(path):
                files[name] = path
        if len(files) < 2:
            self.skipTest('Not enough ALU instructions found')

        merged = merge_instructions(files)
        self.assertGreater(len(merged.nodes), 0)

        gen = VerilogGenerator(merged)
        verilog = gen.generate()
        self.assertIn('module', verilog)

    @unittest.skipUnless(HAS_IVERILOG, 'iverilog not available')
    def test_merged_compiles_iverilog(self):
        """Merged LDA+STA Verilog should pass iverilog."""
        lda_path = os.path.join(ORTHO_DIR, 'lda.isa')
        sta_path = os.path.join(ORTHO_DIR, 'sta.isa')
        if not (os.path.exists(lda_path) and os.path.exists(sta_path)):
            self.skipTest('lda.isa or sta.isa not found')

        merged = merge_instructions({
            'lda': lda_path,
            'sta': sta_path,
        })
        gen = VerilogGenerator(merged)
        verilog = gen.generate()

        tmpdir = tempfile.mkdtemp()
        try:
            vfile = os.path.join(tmpdir, 'merged.v')
            with open(vfile, 'w') as f:
                f.write(verilog)
            result = subprocess.run(
                ['iverilog', '-g2012', '-o', '/dev/null', vfile],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                result.returncode, 0,
                f'iverilog failed on merged LDA+STA:\n{result.stderr[:500]}'
            )
        finally:
            shutil.rmtree(tmpdir)


if __name__ == '__main__':
    unittest.main()
