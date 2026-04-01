#!/usr/bin/env python3
"""
Test suite for macro-op fusion optimization pass.

Tests the FusionCandidate / MacroOpFusion infrastructure using RISC-V64
instruction pairs from the fusion proposal.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from opt.macro_op_fusion import MacroOpFusion, FusionCandidate, apply_macro_op_fusion
from core.resource_graph import ResourceGraph


ISA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'isa', 'riscv64')


def isa_path(name: str) -> str:
    return os.path.join(ISA_DIR, f'{name}.isa')


class TestFusionCandidateSpec(unittest.TestCase):
    """Test FusionCandidate data class construction."""

    def test_basic_construction(self):
        c = FusionCandidate(
            name='lui_addi',
            instr1_name='lui', instr1_file=isa_path('lui'),
            instr2_name='addi', instr2_file=isa_path('addi'),
            producer_write='rd', consumer_read='rs1',
        )
        self.assertEqual(c.name, 'lui_addi')
        self.assertEqual(c.regfile_name, 'rf')
        self.assertEqual(c.pc_name, 'pc')
        self.assertEqual(c.pc_increment, 4)

    def test_custom_regfile_name(self):
        c = FusionCandidate(
            name='test',
            instr1_name='a', instr1_file='a.isa',
            instr2_name='b', instr2_file='b.isa',
            producer_write='rd', consumer_read='rs1',
            regfile_name='xregs',
        )
        self.assertEqual(c.regfile_name, 'xregs')


class TestLuiAddiFusion(unittest.TestCase):
    """Test LUI+ADDI fusion (32-bit constant load)."""

    def setUp(self):
        self.candidate = FusionCandidate(
            name='lui_addi',
            instr1_name='lui', instr1_file=isa_path('lui'),
            instr2_name='addi', instr2_file=isa_path('addi'),
            producer_write='rd', consumer_read='rs1',
        )
        self.fusion = MacroOpFusion()

    def test_fuse_produces_graph(self):
        result = self.fusion.fuse(self.candidate)
        self.assertIsNotNone(result.fused_graph)
        self.assertGreater(len(result.fused_graph.nodes), 0)
        self.assertGreater(len(result.fused_graph.edges), 0)

    def test_no_i1_pc_write(self):
        """i1's pc write (pc = pc+4) should be eliminated."""
        result = self.fusion.fuse(self.candidate)
        g = result.fused_graph
        # i1's pc_wr should not exist
        self.assertNotIn('i1_pc_wr', g.nodes,
                         "i1's pc_wr should be eliminated")

    def test_no_i1_rf_write(self):
        """i1's rf write should be eliminated (bypassed)."""
        result = self.fusion.fuse(self.candidate)
        g = result.fused_graph
        # i1's rf[rd]_wr should not exist
        i1_rf_writes = [nid for nid in g.nodes if nid.startswith('i1_') and 'rf[' in nid and '_wr' in nid]
        self.assertEqual(len(i1_rf_writes), 0,
                         f"i1 should have no rf writes, found: {i1_rf_writes}")

    def test_i2_rf_write_exists(self):
        """i2's rf write should still exist (the final architectural write)."""
        result = self.fusion.fuse(self.candidate)
        g = result.fused_graph
        i2_rf_writes = [nid for nid in g.nodes if nid.startswith('i2_') and 'rf[' in nid and '_wr' in nid]
        self.assertGreater(len(i2_rf_writes), 0,
                           "i2 should have an rf write (the architectural commit)")

    def test_destructive_destination_enforced(self):
        """rd2==rd1 should be added as an assume expression."""
        result = self.fusion.fuse(self.candidate)
        self.assertTrue(result.instr2_has_rd,
                        "ADDI has a rd, so destructive dest should be detected")

        # Check that the assume_expressions contain the cross-instruction constraint
        assumes = result.fused_graph.assume_expressions
        cross_assumes = [a for a in assumes
                        if a.get('type') == 'binary_op'
                        and a.get('operator') == '=='
                        and _references_both_instrs(a)]
        self.assertGreater(len(cross_assumes), 0,
                           "Should have cross-instruction assume for rd2==rd1")

    def test_forwarding_link_added(self):
        """instr2.rs1 == instr1.rd should be in the assume expressions."""
        result = self.fusion.fuse(self.candidate)
        assumes = result.fused_graph.assume_expressions
        cross_assumes = [a for a in assumes
                        if a.get('type') == 'binary_op'
                        and a.get('operator') == '=='
                        and _references_both_instrs(a)]
        # Should have at least 2: forwarding link + destructive dest
        self.assertGreaterEqual(len(cross_assumes), 2,
                                "Should have both forwarding link and destructive dest assumes")

    def test_i1_opcode_assume_preserved(self):
        """i1's opcode assume (LUI = 0110111) should be preserved (as instr1 ref)."""
        result = self.fusion.fuse(self.candidate)
        assumes = result.fused_graph.assume_expressions
        # Find assumes that reference 'instr1'
        i1_assumes = [a for a in assumes if _references_instr(a, 'instr1')]
        self.assertGreater(len(i1_assumes), 0,
                           "Should have assumes for instr1 (LUI opcode)")

    def test_i2_opcode_assume_preserved(self):
        """i2's opcode assume (ADDI opcode + funct3) should be preserved (as instr2 ref)."""
        result = self.fusion.fuse(self.candidate)
        assumes = result.fused_graph.assume_expressions
        i2_assumes = [a for a in assumes if _references_instr(a, 'instr2')]
        self.assertGreater(len(i2_assumes), 0,
                           "Should have assumes for instr2 (ADDI opcode)")

    def test_shared_state_exists(self):
        """Shared ISA state (pc_rd, rf, umem) should exist in the fused graph."""
        result = self.fusion.fuse(self.candidate)
        g = result.fused_graph
        self.assertIn('pc_rd', g.nodes, "Shared pc_rd should exist")
        self.assertIn('rf', g.nodes, "Shared rf should exist")
        self.assertIn('umem', g.nodes, "Shared umem should exist")

    def test_dual_fetch(self):
        """Both instructions should be fetched (i1 from pc, i2 from pc+4)."""
        result = self.fusion.fuse(self.candidate)
        g = result.fused_graph
        # i1's instr node should exist
        self.assertIn('i1_instr', g.nodes, "i1's instr node should exist")
        # i2's instr node should exist
        self.assertIn('i2_instr', g.nodes, "i2's instr node should exist")


class TestAuipcJalrFusion(unittest.TestCase):
    """Test AUIPC+JALR fusion (PC-relative call)."""

    def setUp(self):
        self.candidate = FusionCandidate(
            name='auipc_jalr',
            instr1_name='auipc', instr1_file=isa_path('auipc'),
            instr2_name='jalr', instr2_file=isa_path('jalr'),
            producer_write='rd', consumer_read='rs1',
        )

    def test_fuse_produces_graph(self):
        fusion = MacroOpFusion()
        result = fusion.fuse(self.candidate)
        self.assertIsNotNone(result.fused_graph)

    def test_destructive_dest(self):
        """JALR writes rd, so rd2==rd1 should be forced."""
        fusion = MacroOpFusion()
        result = fusion.fuse(self.candidate)
        self.assertTrue(result.instr2_has_rd)

    def test_i2_pc_adjusted_for_branch(self):
        """JALR computes a jump target — i2's PC reads should use pc+4."""
        fusion = MacroOpFusion()
        result = fusion.fuse(self.candidate)
        g = result.fused_graph
        # The fusion_pc_plus_4 node should exist
        self.assertIn('fusion_pc_plus_4', g.nodes,
                      "pc+4 node should exist for i2's PC-relative computations")


class TestStoreFusion(unittest.TestCase):
    """Test fusion where instr2 is a store (no rd)."""

    def setUp(self):
        # AUIPC+SD: instr2 (SD) has no rd
        self.candidate = FusionCandidate(
            name='auipc_sd',
            instr1_name='auipc', instr1_file=isa_path('auipc'),
            instr2_name='sd', instr2_file=isa_path('sd'),
            producer_write='rd', consumer_read='rs1',
        )

    def test_no_destructive_dest(self):
        """SD has no rd — destructive dest should NOT be enforced."""
        fusion = MacroOpFusion()
        result = fusion.fuse(self.candidate)
        self.assertFalse(result.instr2_has_rd,
                         "SD has no rd, so instr2_has_rd should be False")

    def test_i1_rf_write_eliminated(self):
        """AUIPC's rf write should be eliminated (rd is dead after SD)."""
        fusion = MacroOpFusion()
        result = fusion.fuse(self.candidate)
        g = result.fused_graph
        i1_rf_writes = [nid for nid in g.nodes if nid.startswith('i1_') and 'rf[' in nid and '_wr' in nid]
        self.assertEqual(len(i1_rf_writes), 0,
                         f"i1 rf write should be eliminated, found: {i1_rf_writes}")


class TestApplyMacroOpFusion(unittest.TestCase):
    """Test the public apply_macro_op_fusion API."""

    def test_multiple_candidates(self):
        candidates = [
            FusionCandidate(
                name='lui_addi',
                instr1_name='lui', instr1_file=isa_path('lui'),
                instr2_name='addi', instr2_file=isa_path('addi'),
                producer_write='rd', consumer_read='rs1',
            ),
            FusionCandidate(
                name='auipc_addi',
                instr1_name='auipc', instr1_file=isa_path('auipc'),
                instr2_name='addi', instr2_file=isa_path('addi'),
                producer_write='rd', consumer_read='rs1',
            ),
        ]
        results = apply_macro_op_fusion(candidates)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].candidate.name, 'lui_addi')
        self.assertEqual(results[1].candidate.name, 'auipc_addi')


class TestAddLdFusion(unittest.TestCase):
    """Test ADD+LD fusion (register-indexed load)."""

    def setUp(self):
        self.candidate = FusionCandidate(
            name='add_ld',
            instr1_name='add', instr1_file=isa_path('add'),
            instr2_name='ld', instr2_file=isa_path('ld'),
            producer_write='rd', consumer_read='rs1',
        )

    def test_fuse_produces_graph(self):
        fusion = MacroOpFusion()
        result = fusion.fuse(self.candidate)
        self.assertIsNotNone(result.fused_graph)
        self.assertTrue(result.instr2_has_rd)

    def test_i1_rf_write_eliminated(self):
        fusion = MacroOpFusion()
        result = fusion.fuse(self.candidate)
        g = result.fused_graph
        i1_rf_writes = [nid for nid in g.nodes if nid.startswith('i1_') and 'rf[' in nid and '_wr' in nid]
        self.assertEqual(len(i1_rf_writes), 0)


class TestSllSrlFusion(unittest.TestCase):
    """Test SLLI+SRLI fusion (zero-extend 32->64)."""

    def setUp(self):
        self.candidate = FusionCandidate(
            name='slli_srli',
            instr1_name='slli', instr1_file=isa_path('slli'),
            instr2_name='srli', instr2_file=isa_path('srli'),
            producer_write='rd', consumer_read='rs1',
        )

    def test_fuse_produces_graph(self):
        fusion = MacroOpFusion()
        result = fusion.fuse(self.candidate)
        self.assertIsNotNone(result.fused_graph)
        self.assertTrue(result.instr2_has_rd)


# =============================================================================
# Helpers
# =============================================================================

def _references_instr(assume: dict, instr_name: str) -> bool:
    """Check if an assume expression references a given instruction name."""
    if not assume or not isinstance(assume, dict):
        return False
    if assume.get('type') == 'identifier':
        return assume.get('name') == instr_name
    if assume.get('type') == 'bit_slice':
        return _references_instr(assume.get('target', {}), instr_name)
    if assume.get('type') == 'binary_op':
        return (_references_instr(assume.get('left', {}), instr_name) or
                _references_instr(assume.get('right', {}), instr_name))
    return False


def _references_both_instrs(assume: dict) -> bool:
    """Check if an assume references both instr1 and instr2."""
    return (_references_instr(assume, 'instr1') and
            _references_instr(assume, 'instr2'))


if __name__ == '__main__':
    unittest.main()
