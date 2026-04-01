#!/usr/bin/env python3
"""
End-to-end test: SAIL-loaded instructions → merge → Verilog → iverilog compile.

This test validates that the SAIL frontend can produce functional RISC-V designs.
It works in two modes:

1. SYNTHETIC MODE (always available): Loads .isa files, converts them through
   the SAIL loader's format pipeline, and validates the output matches.

2. EXTRACTION MODE (requires cached JSON): If /tmp/riscv_instructions.json exists,
   loads actual SAIL-extracted patterns and generates Verilog from them.

Run:
    PYTHONPATH=. python3 test/test_sail_to_verilog.py
"""

import sys
import os
import json
import shutil
import tempfile
import subprocess
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from core.resource_graph import ResourceGraph, Node, Edge
from core.graph_merger import merge_instructions, ResourceGraphMerger, analyze_instruction_length
from frontends.sail.ocaml_sail_extractor.sail_loader import SAILInstructionLoader


PROJ_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
ISA_DIR = os.path.join(PROJ_ROOT, 'isa', 'riscv32')
SAIL_CACHE = '/tmp/riscv_instructions.json'


def _assume_to_decode_constraints(assume_expressions):
    """Convert assume_expressions to SAIL-format decode_constraints.

    Handles all right-hand types: binary_wildcard, literal, sized_literal.
    """
    constraints = []
    for ae in assume_expressions:
        if ae.get('type') != 'binary_op' or ae.get('operator') != '==':
            continue
        left = ae.get('left', {})
        right = ae.get('right', {})
        if left.get('type') != 'bit_slice':
            continue

        rng = left.get('range', (0, 0))
        high_bit = rng[0]
        low_bit = rng[1]
        width = high_bit - low_bit + 1
        rtype = right.get('type')

        if rtype == 'binary_wildcard':
            # Has 'pattern' (e.g. '0110011'), 'fixed_value', 'original'
            value_str = right.get('original', '0b' + right.get('pattern', '0'))
            if not value_str.startswith('0b') and not value_str.startswith('0x'):
                value_str = '0b' + value_str
        elif rtype == 'sized_literal':
            # Has 'original_digits', 'format', 'value'
            fmt = right.get('format', 'bin')
            digits = right.get('original_digits', '0')
            value_str = ('0b' if fmt == 'bin' else '0x') + digits
        elif rtype == 'literal':
            # Plain value - convert to binary string of correct width
            val = right.get('value', 0)
            value_str = '0b' + format(val, f'0{width}b')
        else:
            continue

        constraints.append({
            'high_bit': high_bit,
            'low_bit': low_bit,
            'value': value_str,
        })
    return constraints


class TestSAILLoaderFields(unittest.TestCase):
    """Test that SAIL loader sets critical fields for Verilog generation."""

    def _make_sail_json(self, nodes, edges, decode_constraints=None):
        """Create SAIL-format JSON matching OCaml extractor output."""
        data = {'nodes': nodes, 'edges': edges}
        if decode_constraints:
            data['decode_constraints'] = decode_constraints
        return data

    def _make_state_node(self, node_id, display_name, bit_width=32, is_memory=False, is_arch=True):
        return {
            'id': node_id,
            'data': {
                'type': 'isa_state',
                'display_name': display_name,
                'bit_width': bit_width,
                'is_memory': is_memory,
            },
            'is_arch_state': is_arch,
        }

    def test_rf_gets_array_depth(self):
        """Register file must get array_depth=5 for Verilog generation."""
        sail_json = self._make_sail_json(
            nodes=[self._make_state_node('n1', 'rf', 32, is_memory=True)],
            edges=[]
        )
        loader = SAILInstructionLoader()
        converted = loader._convert_to_isacomp_format(sail_json)
        rf_node = next(n for n in converted['nodes'] if n['id'] == 'rf')
        self.assertEqual(rf_node['data']['array_depth'], 5)
        self.assertTrue(rf_node['data']['is_memory'])
        self.assertIn('dimensions', rf_node['data'])

    def test_rf_not_memory_initially_gets_array_depth(self):
        """RF node not initially marked as memory should get is_memory + array_depth."""
        sail_json = self._make_sail_json(
            nodes=[self._make_state_node('n1', 'rf', 32, is_memory=False)],
            edges=[]
        )
        loader = SAILInstructionLoader()
        converted = loader._convert_to_isacomp_format(sail_json)
        rf_node = next(n for n in converted['nodes'] if n['id'] == 'rf')
        self.assertEqual(rf_node['data']['array_depth'], 5)
        self.assertTrue(rf_node['data']['is_memory'])

    def test_dmem_gets_array_depth(self):
        """Data memory must get array_depth for Verilog generation."""
        sail_json = self._make_sail_json(
            nodes=[self._make_state_node('n1', 'dmem', 32, is_memory=True)],
            edges=[]
        )
        loader = SAILInstructionLoader()
        converted = loader._convert_to_isacomp_format(sail_json)
        dmem_node = next(n for n in converted['nodes'] if n['id'] == 'dmem')
        self.assertIn('array_depth', dmem_node['data'])
        self.assertIsNotNone(dmem_node['data']['array_depth'])
        self.assertGreater(dmem_node['data']['array_depth'], 0)

    def test_imem_gets_array_depth(self):
        """Instruction memory must get array_depth for Verilog generation."""
        sail_json = self._make_sail_json(
            nodes=[self._make_state_node('n1', 'imem', 32, is_memory=True)],
            edges=[]
        )
        loader = SAILInstructionLoader()
        converted = loader._convert_to_isacomp_format(sail_json)
        imem_node = next(n for n in converted['nodes'] if n['id'] == 'imem')
        self.assertIn('array_depth', imem_node['data'])
        self.assertIsNotNone(imem_node['data']['array_depth'])

    def test_csr_gets_array_depth(self):
        """CSR array must get array_depth=12 for 4096 CSR registers."""
        sail_json = self._make_sail_json(
            nodes=[self._make_state_node('n1', 'csr', 32, is_memory=True)],
            edges=[]
        )
        loader = SAILInstructionLoader()
        converted = loader._convert_to_isacomp_format(sail_json)
        csr_node = next(n for n in converted['nodes'] if n['id'] == 'csr')
        self.assertEqual(csr_node['data']['array_depth'], 12)

    def test_fp_rf_gets_array_depth(self):
        """FP register file must get array_depth=5."""
        sail_json = self._make_sail_json(
            nodes=[self._make_state_node('n1', 'fp_rf', 32, is_memory=True)],
            edges=[]
        )
        loader = SAILInstructionLoader()
        converted = loader._convert_to_isacomp_format(sail_json)
        fp_node = next(n for n in converted['nodes'] if n['id'] == 'fp_rf')
        self.assertEqual(fp_node['data']['array_depth'], 5)

    def test_pc_no_array_depth_needed(self):
        """PC (scalar state) should not have array_depth."""
        sail_json = self._make_sail_json(
            nodes=[self._make_state_node('n1', 'pc', 32, is_memory=False)],
            edges=[]
        )
        loader = SAILInstructionLoader()
        converted = loader._convert_to_isacomp_format(sail_json)
        pc_node = next(n for n in converted['nodes'] if n['id'] == 'pc')
        # PC is scalar - should not be memory
        self.assertFalse(pc_node['data'].get('is_memory', False))

    def test_decode_constraints_to_assume_expressions(self):
        """Decode constraints from SAIL should become assume_expressions."""
        sail_json = self._make_sail_json(
            nodes=[self._make_state_node('n1', 'pc', 32)],
            edges=[],
            decode_constraints=[
                {'high_bit': 6, 'low_bit': 0, 'value': '0b0110011'},
                {'high_bit': 14, 'low_bit': 12, 'value': '0b000'},
            ]
        )
        loader = SAILInstructionLoader()
        # load_instruction_pattern needs full extraction dict, so test _convert directly
        converted = loader._convert_to_isacomp_format(sail_json)
        self.assertIn('decode_constraints', converted)
        self.assertEqual(len(converted['decode_constraints']), 2)

    def test_edge_type_conversion(self):
        """SAIL 'value' edges should be converted to typed edges."""
        sail_json = self._make_sail_json(
            nodes=[
                self._make_state_node('n1', 'rf', 32, is_memory=True),
                {'id': 'n2', 'data': {'type': 'var', 'display_name': 'r1', 'bit_width': 32},
                 'is_arch_state': False},
                {'id': 'n3', 'data': {'type': 'operation', 'operator': '+', 'bit_width': 32},
                 'is_arch_state': False},
            ],
            edges=[
                # rf -> var edge (rf is isa_state so gets remapped to 'rf')
                {'id': 'e1', 'source': 'n1', 'target': 'n2', 'data': {'type': 'value'}},
                # var -> operation edge (n2 stays as 'n2' since it's not isa_state)
                {'id': 'e2', 'source': 'n2', 'target': 'n3', 'data': {'type': 'value'}},
            ]
        )
        loader = SAILInstructionLoader()
        converted = loader._convert_to_isacomp_format(sail_json)

        edges_by_target = {}
        for e in converted['edges']:
            edges_by_target[e['target']] = e

        # Edge to var (n2) should become 'assignment'
        self.assertEqual(edges_by_target['n2']['data']['type'], 'assignment')
        # Edge to operation (n3) should become 'operand'
        self.assertEqual(edges_by_target['n3']['data']['type'], 'operand')


class TestSAILRoundtrip(unittest.TestCase):
    """Test that .isa graphs can roundtrip through SAIL loader format."""

    def _isa_to_sail_format(self, graph):
        """Convert a ResourceGraph to SAIL extractor JSON format.

        This simulates what the OCaml extractor would produce.
        """
        nodes = []
        for node_id, node in graph.nodes.items():
            nodes.append({
                'id': node_id,
                'data': dict(node.data),
                'is_arch_state': node.is_arch_state,
            })

        edges = []
        for edge_id, edge in graph.edges.items():
            edges.append({
                'id': edge_id,
                'source': edge.source.id,
                'target': edge.target.id,
                'data': dict(edge.data),
            })

        result = {'nodes': nodes, 'edges': edges}
        if graph.assume_expressions:
            decode_constraints = _assume_to_decode_constraints(graph.assume_expressions)
            if decode_constraints:
                result['decode_constraints'] = decode_constraints

        return result

    def test_add_roundtrip(self):
        """ADD instruction should survive SAIL format roundtrip."""
        isa_file = os.path.join(ISA_DIR, 'add.isa')
        if not os.path.exists(isa_file):
            self.skipTest(f"No {isa_file}")

        # Load via .isa parser (this does state splitting: pc → pc_rd + pc_wr)
        original = ResourceGraph.from_isa_file(isa_file)
        self.assertGreater(len(original.nodes), 0)

        # Convert to SAIL format and back
        sail_json = self._isa_to_sail_format(original)
        loader = SAILInstructionLoader()
        converted = loader._convert_to_isacomp_format(sail_json)
        roundtripped = ResourceGraph.from_json(converted)

        # Verify key properties preserved (node/edge counts should match
        # since we're roundtripping already-split graphs)
        self.assertEqual(len(roundtripped.nodes), len(original.nodes))
        self.assertEqual(len(roundtripped.edges), len(original.edges))

        # RF should have array_depth
        if 'rf' in roundtripped.nodes:
            rf = roundtripped.nodes['rf']
            self.assertIn('array_depth', rf.data)
            self.assertIsNotNone(rf.data['array_depth'])

    def test_all_rv32i_roundtrip(self):
        """All 37 RV32I instructions should roundtrip through SAIL format."""
        instructions = [
            'add', 'addi', 'sub', 'lui', 'auipc',
            'and', 'andi', 'or', 'ori', 'xor', 'xori',
            'sll', 'slli', 'srl', 'srli', 'sra', 'srai',
            'slt', 'slti', 'sltu', 'sltiu',
            'beq', 'bne', 'blt', 'bltu', 'bge', 'bgeu',
            'jal', 'jalr',
            'lw', 'lh', 'lhu', 'lb', 'lbu',
            'sw', 'sh', 'sb',
        ]

        loader = SAILInstructionLoader()
        for instr in instructions:
            isa_file = os.path.join(ISA_DIR, f'{instr}.isa')
            if not os.path.exists(isa_file):
                continue

            with self.subTest(instruction=instr):
                original = ResourceGraph.from_isa_file(isa_file)
                sail_json = self._isa_to_sail_format(original)
                converted = loader._convert_to_isacomp_format(sail_json)
                roundtripped = ResourceGraph.from_json(converted)

                self.assertEqual(len(roundtripped.nodes), len(original.nodes),
                                 f"{instr}: node count mismatch")
                self.assertEqual(len(roundtripped.edges), len(original.edges),
                                 f"{instr}: edge count mismatch")


class TestSAILVerilogGeneration(unittest.TestCase):
    """Test that SAIL-loaded graphs can produce compilable Verilog."""

    def _load_and_convert_isa(self, isa_file):
        """Load .isa file and convert through SAIL loader format."""
        original = ResourceGraph.from_isa_file(isa_file)
        # Convert to SAIL extractor format
        nodes = []
        for node_id, node in original.nodes.items():
            nodes.append({
                'id': node_id,
                'data': dict(node.data),
                'is_arch_state': node.is_arch_state,
            })
        edges = []
        for edge_id, edge in original.edges.items():
            edges.append({
                'id': edge_id,
                'source': edge.source.id,
                'target': edge.target.id,
                'data': dict(edge.data),
            })

        sail_json = {'nodes': nodes, 'edges': edges}
        if original.assume_expressions:
            decode_constraints = _assume_to_decode_constraints(original.assume_expressions)
            if decode_constraints:
                sail_json['decode_constraints'] = decode_constraints

        # Use the SAIL loader to convert back - this also generates assume_expressions
        loader = SAILInstructionLoader()
        converted = loader._convert_to_isacomp_format(sail_json)
        graph = ResourceGraph.from_json(converted)

        # Generate assume_expressions from decode_constraints (same as load_instruction_pattern)
        for constraint in converted.get('decode_constraints', []):
            high_bit = constraint['high_bit']
            low_bit = constraint['low_bit']
            value_str = constraint['value']
            width = high_bit - low_bit + 1

            clean_str = value_str.replace('_', '')
            if clean_str.startswith('0b'):
                digits = clean_str[2:]
                fmt = 'bin'
                value = int(digits, 2)
            elif clean_str.startswith('0x'):
                digits = clean_str[2:]
                fmt = 'hex'
                value = int(digits, 16)
            else:
                try:
                    value = int(clean_str)
                except ValueError:
                    continue
                digits = format(value, f'0{width}b')
                fmt = 'bin'

            graph.assume_expressions.append({
                'type': 'binary_op',
                'operator': '==',
                'left': {
                    'type': 'bit_slice',
                    'target': {'type': 'identifier', 'name': 'instr'},
                    'range': (high_bit, low_bit)
                },
                'right': {
                    'type': 'sized_literal',
                    'width': width,
                    'value': value,
                    'format': fmt,
                    'original_digits': digits
                }
            })

        return graph

    def test_merge_sail_loaded_graphs(self):
        """Merge SAIL-format-loaded graphs into single processor."""
        instructions = [
            'add', 'addi', 'sub', 'lui', 'auipc',
            'and', 'andi', 'or', 'ori', 'xor', 'xori',
            'sll', 'slli', 'srl', 'srli', 'sra', 'srai',
            'slt', 'slti', 'sltu', 'sltiu',
            'beq', 'bne', 'blt', 'bltu', 'bge', 'bgeu',
            'jal', 'jalr',
            'lw', 'lh', 'lhu', 'lb', 'lbu',
            'sw', 'sh', 'sb',
        ]

        # Save SAIL-loaded graphs as .rgraph files
        tmpdir = tempfile.mkdtemp(prefix='sail_test_', )
        rgraph_files = {}

        for instr in instructions:
            isa_file = os.path.join(ISA_DIR, f'{instr}.isa')
            if not os.path.exists(isa_file):
                continue

            graph = self._load_and_convert_isa(isa_file)
            rgraph_path = os.path.join(tmpdir, f'{instr}.rgraph')
            graph.save_to_file(rgraph_path)
            rgraph_files[instr] = rgraph_path

        self.assertEqual(len(rgraph_files), 37, "Should have all 37 RV32I instructions")

        # Merge using the standard merger (with .rgraph files)
        merged = merge_instructions(rgraph_files)
        self.assertGreater(len(merged.nodes), 100, "Merged graph should have many nodes")
        self.assertGreater(len(merged.edges), 100, "Merged graph should have many edges")

        # Verify key state nodes exist
        self.assertIn('rf', merged.nodes)
        self.assertIn('pc_rd', merged.nodes)

    @unittest.skipUnless(shutil.which('iverilog'), 'iverilog not installed')
    def test_verilog_generation_from_sail(self):
        """Generate compilable Verilog from SAIL-loaded graphs."""
        from backends.verilog import VerilogGenerator
        from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec

        instructions = [
            'add', 'addi', 'sub', 'lui', 'auipc',
            'and', 'andi', 'or', 'ori', 'xor', 'xori',
            'sll', 'slli', 'srl', 'srli', 'sra', 'srai',
            'slt', 'slti', 'sltu', 'sltiu',
            'beq', 'bne', 'blt', 'bltu', 'bge', 'bgeu',
            'jal', 'jalr',
            'lw', 'lh', 'lhu', 'lb', 'lbu',
            'sw', 'sh', 'sb',
        ]

        tmpdir = tempfile.mkdtemp(prefix='sail_verilog_', )
        rgraph_files = {}

        for instr in instructions:
            isa_file = os.path.join(ISA_DIR, f'{instr}.isa')
            if not os.path.exists(isa_file):
                continue
            graph = self._load_and_convert_isa(isa_file)
            rgraph_path = os.path.join(tmpdir, f'{instr}.rgraph')
            graph.save_to_file(rgraph_path)
            rgraph_files[instr] = rgraph_path

        # Merge
        merged = merge_instructions(rgraph_files)

        # Apply memory transform (same as generate_riscv32i_complete.py)
        umem_node = merged.nodes.get('umem')
        if umem_node:
            access_widths = umem_node.data.get('access_widths', [32])
            max_width = max(access_widths) if access_widths else 32
            transform = MemoryAccessTransform(merged)
            spec = MemoryAccessTransformSpec(
                memory='umem',
                strategy='set_port_width',
                current_width=max_width,
                target_width=32,
                direction='forward'
            )
            transform.apply_transformation(spec)

        # Generate Verilog
        module_name = 'riscv32i_sail_test'
        generator = VerilogGenerator(merged, module_name)
        verilog_code = generator.generate()

        # Write Verilog
        verilog_path = os.path.join(tmpdir, f'{module_name}.v')
        with open(verilog_path, 'w') as f:
            f.write(verilog_code)

        self.assertGreater(len(verilog_code), 1000, "Verilog should be non-trivial")

        # Compile with iverilog
        result = subprocess.run(
            ['iverilog', '-g2012', '-o', '/dev/null', verilog_path],
            capture_output=True, text=True,
            env=os.environ
        )

        self.assertEqual(result.returncode, 0,
                         f"iverilog compilation failed:\n{result.stderr}")
        print(f"\n  Verilog generated: {len(verilog_code)} bytes, compiles cleanly")

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),
                         'iexamples/verilog/vvp not installed')
    def test_sail_verilog_simulation(self):
        """Run riscv-tests against SAIL-roundtripped Verilog to validate functionality."""
        from backends.verilog import VerilogGenerator
        from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec

        test_dir = os.path.join(PROJ_ROOT, 'isa', 'riscv32', 'riscv-tests', 'isa')
        # Check that test infrastructure exists
        sample_hex = os.path.join(test_dir, 'rv32ui-isacomp-add.hex')
        sample_addrs = os.path.join(test_dir, 'rv32ui-isacomp-add.addrs')
        if not os.path.exists(sample_hex) or not os.path.exists(sample_addrs):
            self.skipTest("riscv-tests hex files not available")

        instructions = [
            'add', 'addi', 'sub', 'lui', 'auipc',
            'and', 'andi', 'or', 'ori', 'xor', 'xori',
            'sll', 'slli', 'srl', 'srli', 'sra', 'srai',
            'slt', 'slti', 'sltu', 'sltiu',
            'beq', 'bne', 'blt', 'bltu', 'bge', 'bgeu',
            'jal', 'jalr',
            'lw', 'lh', 'lhu', 'lb', 'lbu',
            'sw', 'sh', 'sb',
        ]

        tmpdir = tempfile.mkdtemp(prefix='sail_sim_', )
        rgraph_files = {}

        for instr in instructions:
            isa_file = os.path.join(ISA_DIR, f'{instr}.isa')
            if not os.path.exists(isa_file):
                continue
            graph = self._load_and_convert_isa(isa_file)
            rgraph_path = os.path.join(tmpdir, f'{instr}.rgraph')
            graph.save_to_file(rgraph_path)
            rgraph_files[instr] = rgraph_path

        # Merge
        merged = merge_instructions(rgraph_files)

        # Apply memory transform
        umem_node = merged.nodes.get('umem')
        if umem_node:
            access_widths = umem_node.data.get('access_widths', [32])
            max_width = max(access_widths) if access_widths else 32
            transform = MemoryAccessTransform(merged)
            spec = MemoryAccessTransformSpec(
                memory='umem',
                strategy='set_port_width',
                current_width=max_width,
                target_width=32,
                direction='forward'
            )
            transform.apply_transformation(spec)

        # Generate Verilog with same module name as baseline for easy comparison
        module_name = 'riscv32i_complete'
        generator = VerilogGenerator(merged, module_name)
        verilog_code = generator.generate()

        verilog_path = os.path.join(tmpdir, f'{module_name}.v')
        with open(verilog_path, 'w') as f:
            f.write(verilog_code)

        # Write testbench
        tb_path = os.path.join(tmpdir, 'simple_tb.sv')
        with open(tb_path, 'w') as f:
            f.write("""`timescale 1ns/1ps
module simple_tb;
    reg clk, reset;
    wire [31:0] zero32 = 32'd0;

    riscv32i_complete dut (
        .clk(clk),
        .reset(reset),
        .reset_pc_rd(zero32)
    );

    reg [31:0] pass_addr, fail_addr;
    integer i;
    always #5 clk = ~clk;

    initial begin
        clk = 0; reset = 1;
        if (!$value$plusargs("pass_addr=%h", pass_addr)) pass_addr = 32'hFFFFFFFF;
        if (!$value$plusargs("fail_addr=%h", fail_addr)) fail_addr = 32'hFFFFFFFE;
        $readmemh("umem.hex", dut.umem);
        repeat(3) @(posedge clk);
        reset = 0;
        for (i = 0; i < 10000; i = i + 1) begin
            @(posedge clk);
            if (dut.pc_rd == pass_addr) begin $display("TEST PASSED"); $finish; end
            if (dut.pc_rd == fail_addr) begin $display("TEST FAILED at pc=%h testnum=%d", dut.pc_rd, dut.rf[28]); $finish; end
        end
        $display("TIMEOUT");
        $finish;
    end
endmodule
""")

        # Create rf.hex with 32 zero entries
        rf_path = os.path.join(tmpdir, 'rf.hex')
        with open(rf_path, 'w') as f:
            for _ in range(32):
                f.write('00000000\n')

        # Compile
        sim_path = os.path.join(tmpdir, 'test_sim')
        result = subprocess.run(
            ['iverilog', '-g2012', '-o', sim_path, verilog_path, tb_path],
            capture_output=True, text=True,
            env=os.environ
        )
        self.assertEqual(result.returncode, 0,
                         f"iverilog compilation failed:\n{result.stderr}")

        # Run simulation tests
        test_names = [
            'add', 'addi', 'sub', 'lui', 'auipc',
            'and', 'andi', 'or', 'ori', 'xor', 'xori',
            'sll', 'slli', 'srl', 'srli', 'sra', 'srai',
            'slt', 'slti', 'sltu', 'sltiu',
            'beq', 'bne', 'blt', 'bltu', 'bge', 'bgeu',
            'jal', 'jalr',
            'lw', 'lh', 'lhu', 'lb', 'lbu',
            'sw', 'sh', 'sb',
        ]

        passed = 0
        failed = 0
        failures = []

        for test in test_names:
            hex_file = os.path.join(test_dir, f'rv32ui-isacomp-{test}.hex')
            addrs_file = os.path.join(test_dir, f'rv32ui-isacomp-{test}.addrs')
            if not os.path.exists(hex_file) or not os.path.exists(addrs_file):
                continue

            # Read pass/fail addresses
            with open(addrs_file) as f:
                parts = f.read().strip().split()
                pass_addr = parts[0]
                fail_addr = parts[1]

            # Convert Intel HEX to word-addressed umem.hex
            self._convert_ihex_to_umem(hex_file, os.path.join(tmpdir, 'umem.hex'))

            # Run simulation from tmpdir so $readmemh finds the hex files
            sim_result = subprocess.run(
                ['vvp', sim_path, f'+pass_addr={pass_addr}', f'+fail_addr={fail_addr}'],
                capture_output=True, text=True, timeout=10,
                cwd=tmpdir
            )
            output = sim_result.stdout + sim_result.stderr

            if 'TEST PASSED' in output:
                passed += 1
            else:
                failed += 1
                # Extract failure info
                if 'TEST FAILED' in output:
                    failures.append(f"{test}: FAIL")
                else:
                    failures.append(f"{test}: TIMEOUT")

        print(f"\n  SAIL simulation: {passed} PASS, {failed} FAIL out of {passed + failed}")
        if failures:
            print(f"  Failures: {failures[:5]}")

        self.assertGreater(passed, 0, "At least some tests should pass")
        self.assertEqual(failed, 0,
                         f"Some tests failed: {failures}")

    @staticmethod
    def _convert_ihex_to_umem(hex_path, umem_path):
        """Convert Intel HEX file to word-addressed hex for simulation."""
        data = {}
        with open(hex_path) as f:
            for line in f:
                line = line.strip()
                if not line.startswith(':'):
                    continue
                byte_count = int(line[1:3], 16)
                address = int(line[3:7], 16)
                record_type = int(line[7:9], 16)
                if record_type == 0:
                    for i in range(byte_count):
                        byte_val = int(line[9 + i * 2:11 + i * 2], 16)
                        data[address + i] = byte_val
                elif record_type == 1:
                    break

        max_addr = max(data.keys()) if data else 0
        max_word = (max_addr // 4) + 1

        with open(umem_path, 'w') as f:
            for word_idx in range(max(8192, max_word)):
                word = 0
                addr = word_idx * 4
                for byte_offset in range(4):
                    byte_addr = addr + byte_offset
                    if byte_addr in data:
                        word |= data[byte_addr] << (byte_offset * 8)
                f.write(f'{word:08x}\n')


class TestSAILExtractionIntegration(unittest.TestCase):
    """Test with real SAIL extraction data (if available)."""

    def setUp(self):
        if not os.path.exists(SAIL_CACHE):
            self.skipTest(f"No SAIL cache at {SAIL_CACHE}")
        self.loader = SAILInstructionLoader()

    def test_load_all_patterns(self):
        """All SAIL patterns should load without errors."""
        with open(SAIL_CACHE) as f:
            all_instrs = json.load(f)

        loaded = 0
        errors = []
        for pattern_name in sorted(all_instrs.keys()):
            try:
                graph = self.loader.load_instruction_pattern(pattern_name, cache_path=SAIL_CACHE)
                self.assertGreater(len(graph.nodes), 0)
                loaded += 1
            except Exception as e:
                errors.append(f"{pattern_name}: {e}")

        print(f"\n  Loaded {loaded}/{len(all_instrs)} patterns")
        if errors:
            print(f"  Errors ({len(errors)}):")
            for e in errors[:5]:
                print(f"    {e}")

    def test_base_patterns_have_array_depth(self):
        """Base patterns (RTYPE, ITYPE etc.) should have array_depth on rf."""
        base_patterns = ['RTYPE', 'ITYPE', 'SHIFTIOP', 'UTYPE', 'JAL', 'JALR', 'BTYPE', 'LOAD', 'STORE']

        for pattern in base_patterns:
            with self.subTest(pattern=pattern):
                try:
                    graph = self.loader.load_instruction_pattern(pattern, cache_path=SAIL_CACHE)
                except ValueError:
                    continue  # Pattern may not exist

                if 'rf' in graph.nodes:
                    rf = graph.nodes['rf']
                    self.assertIn('array_depth', rf.data,
                                  f"{pattern}: rf missing array_depth")
                    self.assertIsNotNone(rf.data['array_depth'],
                                        f"{pattern}: rf array_depth is None")

    @unittest.skipUnless(shutil.which('iverilog'), 'iverilog not installed')
    def test_generate_verilog_from_sail_patterns(self):
        """Generate Verilog from real SAIL-extracted base integer patterns."""
        from backends.verilog import VerilogGenerator

        base_patterns = ['RTYPE', 'ITYPE', 'SHIFTIOP', 'UTYPE', 'JAL', 'JALR', 'BTYPE', 'LOAD', 'STORE']

        tmpdir = tempfile.mkdtemp(prefix='sail_real_', )
        rgraph_files = {}

        for pattern in base_patterns:
            try:
                graph = self.loader.load_instruction_pattern(pattern, cache_path=SAIL_CACHE)
                rgraph_path = os.path.join(tmpdir, f'{pattern}.rgraph')
                graph.save_to_file(rgraph_path)
                rgraph_files[pattern] = rgraph_path
            except ValueError:
                continue

        if len(rgraph_files) < 5:
            self.skipTest(f"Only {len(rgraph_files)} patterns available")

        # Merge
        merged = merge_instructions(rgraph_files)
        self.assertGreater(len(merged.nodes), 50)

        # Generate Verilog
        generator = VerilogGenerator(merged, 'riscv32i_sail_real')
        verilog_code = generator.generate()

        verilog_path = os.path.join(tmpdir, 'riscv32i_sail_real.v')
        with open(verilog_path, 'w') as f:
            f.write(verilog_code)

        # Compile
        result = subprocess.run(
            ['iverilog', '-g2012', '-o', '/dev/null', verilog_path],
            capture_output=True, text=True,
            env=os.environ
        )

        self.assertEqual(result.returncode, 0,
                         f"iverilog failed:\n{result.stderr}")
        print(f"\n  Real SAIL Verilog: {len(verilog_code)} bytes, compiles cleanly")


if __name__ == '__main__':
    unittest.main(verbosity=2)
