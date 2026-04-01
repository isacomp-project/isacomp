#!/usr/bin/env python3
"""Load RISC-V instructions from SAIL extraction.

This module provides a Python interface to the OCaml SAIL extractor,
allowing isacomp to load instruction semantics directly from the
official RISC-V SAIL specification (sail-riscv).

Example:
    >>> from frontends.sail.ocaml_sail_extractor.sail_loader import SAILInstructionLoader
    >>> loader = SAILInstructionLoader()
    >>> rtype = loader.load_instruction_pattern('RTYPE')
    >>> print(f"Loaded: {len(rtype.nodes)} nodes")
"""

import json
import subprocess
import sys
from pathlib import Path

# Add isacomp root to path so we can import resource_graph
# frontends/sail/ocaml_sail_extractor/sail_loader.py -> isacomp root is 3 levels up
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from core.resource_graph import ResourceGraph



class SAILInstructionLoader:
    """Load RISC-V instruction patterns from SAIL specification."""

    def __init__(self, sail_project_path=None, extractor_path=None, require_extractor=False):
        """Initialize the SAIL instruction loader.

        Args:
            sail_project_path: Path to riscv.sail_project file.
                             Defaults to sail-riscv submodule.
            extractor_path: Path to sail_to_rgraph.exe.
                           Defaults to ocaml_sail_extractor build output.
            require_extractor: If True, raise error if extractor is not built.
                             If False (default), only warn - allows cached usage.
        """
        # sail/ocaml_sail_extractor/sail_loader.py
        self.extractor_dir = Path(__file__).parent  # ocaml_sail_extractor/
        self.sail_dir = self.extractor_dir.parent    # sail/
        self.extractor_path = extractor_path or (
            self.extractor_dir / "_build/default/sail_to_rgraph.exe"
        )
        self.sail_project = sail_project_path or (
            self.sail_dir / "sail-riscv/model/riscv.sail_project"
        )

        # Check if extractor is built
        if not self.extractor_path.exists():
            if require_extractor:
                raise FileNotFoundError(
                    f"SAIL extractor not found at {self.extractor_path}\n"
                    f"Please build it first:\n"
                    f"  cd {self.extractor_dir} && dune build"
                )
            else:
                # Just warn - we can still use cached data
                import warnings
                warnings.warn(
                    f"SAIL extractor not built at {self.extractor_path}. "
                    f"Only cached data can be used. To extract new data, build with: "
                    f"cd {self.extractor_dir} && dune build"
                )

    def extract_all_instructions(self, output_path=None, force_rebuild=False):
        """Extract all RISC-V instruction patterns from SAIL.

        Args:
            output_path: Where to save the JSON output.
                        Defaults to /tmp/riscv_instructions.json
            force_rebuild: If True, always re-extract. If False, use cached
                          output if it exists.

        Returns:
            dict: Mapping of instruction pattern names to graph data
                 {'RTYPE': {'nodes': [...], 'edges': [...]}, ...}
        """
        if output_path is None:
            output_path = "/tmp/riscv_instructions.json"

        output_file = Path(output_path)

        # Use cached output if available and not forcing rebuild
        if not force_rebuild and output_file.exists():
            with open(output_file) as f:
                return json.load(f)

        # Check if extractor is available
        if not self.extractor_path.exists():
            raise FileNotFoundError(
                f"SAIL extractor not found at {self.extractor_path} and no cache at {output_file}.\n"
                f"Please either:\n"
                f"  1. Build the extractor: cd {self.extractor_dir} && dune build\n"
                f"  2. Provide a cache_path to load_instruction_pattern()"
            )

        # Run the OCaml extractor
        cmd = [
            str(self.extractor_path),
            str(self.sail_project),
            str(output_file),
            "--per-instruction"
        ]

        print(f"Extracting RISC-V instructions from SAIL...")
        print(f"  Running: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            print(result.stdout)
        except subprocess.CalledProcessError as e:
            print(f"Error running SAIL extractor:")
            print(e.stderr)
            raise

        # Load and return the result
        with open(output_file) as f:
            return json.load(f)

    def load_instruction_pattern(self, pattern_name, cache_path=None):
        """Load a specific instruction pattern as ResourceGraph.

        Args:
            pattern_name: Name of the pattern to load (e.g., 'RTYPE', 'ITYPE')
            cache_path: Path to cached extraction JSON

        Returns:
            ResourceGraph: The loaded instruction graph

        Raises:
            ValueError: If pattern_name is not found in extraction

        Example:
            >>> loader = SAILInstructionLoader()
            >>> # RTYPE covers ADD, SUB, AND, OR, XOR, SLT, SLTU, SLL, SRL, SRA
            >>> rtype = loader.load_instruction_pattern('RTYPE')
            >>> print(f"Nodes: {len(rtype.nodes)}, Edges: {len(rtype.edges)}")
        """
        all_instrs = self.extract_all_instructions(cache_path)

        if pattern_name not in all_instrs:
            available = sorted(all_instrs.keys())
            raise ValueError(
                f"Pattern '{pattern_name}' not found in SAIL extraction.\n"
                f"Available patterns ({len(available)}): {', '.join(available[:20])}..."
            )

        instr_data = all_instrs[pattern_name]

        # Convert to isacomp format and load as ResourceGraph
        converted = self._convert_to_isacomp_format(instr_data)
        graph = ResourceGraph.from_json(converted)

        # Generate assume_expressions from decode_constraints
        decode_constraints = converted.get('decode_constraints', [])
        for constraint in decode_constraints:
            high_bit = constraint['high_bit']
            low_bit = constraint['low_bit']
            value_str = constraint['value']
            width = high_bit - low_bit + 1

            # Parse the literal value string from Sail
            # Sail produces: "0b0110011", "0b0000_000", "0x1F", plain numbers, etc.
            # Note: Sail's string_of_lit uses "_" as group separator
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
                    continue  # Skip unparseable values
                # Convert decimal to binary string of correct width
                digits = format(value, f'0{width}b')
                fmt = 'bin'

            # Support != operator from extractor exclusion constraints
            op = constraint.get('operator', '==')

            assume_expr = {
                'type': 'binary_op',
                'operator': op,
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
            }
            graph.assume_expressions.append(assume_expr)

        # NOTE: 2-input mux-to-ternary conversion is now done by the OCaml
        # extractor's normalize_graph. The extractor emits ternary_op nodes
        # with ternary_condition/ternary_true/ternary_false edges directly.

        # NOTE: op_select mapping is now fixed by the OCaml extractor's
        # normalize_graph. It walks the ternary chain feeding the control var,
        # finds op_X literals, and reassigns their values to match mux_input indices.

        return graph

    @staticmethod
    def _convert_sign_extend(graph):
        """Convert sign_extend operations to (v ^ mask) - mask formula.

        SAIL's sign_extend(value, target_width) takes a narrow bitvector and
        sign-extends it. The Verilog generator doesn't handle this operator,
        so we convert it to: (value ^ (1 << (input_width-1))) - (1 << (input_width-1))
        which achieves the same result using XOR and subtraction.

        For sign_extend where input width == target width (no-op), we convert
        to a pass-through by changing the type to 'var' with an assignment edge.
        """
        from core.resource_graph import Node, Edge

        nodes_to_convert = []
        for node_id, node in graph.nodes.items():
            if (node.data.get('type') == 'operation' and
                    node.data.get('operator') == 'sign_extend'):
                nodes_to_convert.append(node_id)

        for node_id in nodes_to_convert:
            node = graph.nodes[node_id]
            target_width = node.data.get('bit_width', 32)

            # Separate input value operands from width parameter operands
            input_node = None
            width_node = None
            input_edge = None
            width_edge = None
            for edge in list(node.incoming_edges):
                src = edge.source
                dn = src.data.get('display_name', '')
                if (dn.startswith('_temp_') and
                        src.data.get('type') in ('literal', 'constant', 'sized_literal')):
                    val = src.data.get('value')
                    if val is not None:
                        try:
                            int_val = int(val)
                            if int_val >= 8 and int_val <= 128:
                                width_node = src
                                width_edge = edge
                                continue
                        except (ValueError, TypeError):
                            pass
                input_node = src
                input_edge = edge

            if not input_node:
                continue

            input_width = input_node.data.get('bit_width')

            # Remove width parameter if present
            if width_edge:
                graph.remove_edge(width_edge.id)
                if not width_node.outgoing_edges:
                    graph.remove_node(width_node.id)

            # If input width is unknown or same as target, convert to pass-through
            if input_width is None or input_width >= target_width:
                # Convert to a var node (pass-through)
                node.data['type'] = 'var'
                node.data['operator'] = None
                if input_edge:
                    input_edge.data['type'] = 'assignment'
                continue

            mask_val = 1 << (input_width - 1)

            # Create mask literal node
            mask_id = f'{node_id}_sext_mask'
            mask_data = {
                'type': 'sized_literal',
                'display_name': f'sext_mask_{mask_val}',
                'value': str(mask_val),
                'bit_width': target_width,
                'width': target_width,
            }
            mask_node = Node(mask_id, mask_data)
            graph.add_node(mask_node)

            # Create XOR node: input ^ mask
            xor_id = f'{node_id}_sext_xor'
            xor_data = {
                'type': 'operation',
                'operator': '^',
                'display_name': f'sext_xor',
                'bit_width': target_width,
            }
            xor_node = Node(xor_id, xor_data)
            graph.add_node(xor_node)

            # Connect input → XOR (left operand)
            graph.add_edge(Edge(input_node, xor_node,
                               edge_id=f'{xor_id}_in1',
                               data={'type': 'operand', 'position': 'left'}))
            # Connect mask → XOR (right operand)
            graph.add_edge(Edge(mask_node, xor_node,
                               edge_id=f'{xor_id}_in2',
                               data={'type': 'operand', 'position': 'right'}))

            # Convert the sign_extend node to a subtraction: xor_result - mask
            node.data['operator'] = '-'
            node.data['display_name'] = node.data.get('display_name', 'sext') + '_sub'

            # Remove old input edge
            graph.remove_edge(input_edge.id)

            # Create second mask literal for the subtraction
            mask2_id = f'{node_id}_sext_mask2'
            mask2_data = {
                'type': 'sized_literal',
                'display_name': f'sext_mask_{mask_val}',
                'value': str(mask_val),
                'bit_width': target_width,
                'width': target_width,
            }
            mask2_node = Node(mask2_id, mask2_data)
            graph.add_node(mask2_node)

            # Connect XOR → subtract (as left operand)
            graph.add_edge(Edge(xor_node, node,
                               edge_id=f'{node_id}_xor_in',
                               data={'type': 'operand', 'position': 'left'}))
            # Connect mask2 → subtract (as right operand)
            graph.add_edge(Edge(mask2_node, node,
                               edge_id=f'{node_id}_mask_in',
                               data={'type': 'operand', 'position': 'right'}))

    @staticmethod
    def _normalize_operators(graph):
        """Normalize SAIL operators to Verilog generator conventions.

        SAIL uses <_s, >=_s for signed and <_u, >=_u for unsigned comparisons.
        The Verilog generator expects <s, >=s for signed (wraps in $signed()),
        and plain <, >= for unsigned.
        """
        op_map = {
            '<_s': '<s', '>_s': '>s', '<=_s': '<=s', '>=_s': '>=s',
            '<_u': '<', '>_u': '>', '<=_u': '<=', '>=_u': '>=',
        }
        for node in graph.nodes.values():
            op = node.data.get('operator')
            if op in op_map:
                node.data['operator'] = op_map[op]

    @staticmethod
    def prepare_for_aspects(graph, aspect_declarations=None):
        """Prepare a sail-extracted ResourceGraph for .isa aspect merging.

        This ensures the graph has the variable names and state nodes that
        MMU and interrupt aspects expect.

        Args:
            graph: ResourceGraph to prepare
            aspect_declarations: Optional list of aspect declaration dicts to add.
                Each dict should have 'file', 'gated_states', 'prioritized_states', 'order'.
        """
        from core.resource_graph import Node

        # Rename dmem -> umem (aspects use unified memory)
        if 'dmem' in graph.nodes and 'umem' not in graph.nodes:
            dmem_node = graph.nodes['dmem']
            # Update node ID and display name
            del graph.nodes['dmem']
            dmem_node.id = 'umem'
            dmem_node.data['display_name'] = 'umem'
            if hasattr(dmem_node, 'display_name'):
                dmem_node.display_name = 'umem'
            graph.nodes['umem'] = dmem_node

        # Ensure privilege state nodes exist
        priv_state_nodes = {
            'priv_mode': 2, 'mstatus': 32, 'mepc': 32, 'mcause': 32,
            'mtval': 32, 'mtvec': 32, 'sepc': 32, 'scause': 32,
            'stval': 32, 'stvec': 32, 'medeleg': 32, 'mie': 32,
            'satp': 32,
        }
        for name, width in priv_state_nodes.items():
            if name not in graph.nodes:
                node_data = {
                    'type': 'isa_state',
                    'display_name': name,
                    'bit_width': width,
                    'is_arch_state': True,
                }
                node = Node(name, node_data, from_isa_spec=True)
                graph.add_node(node)

        # Add aspect declarations if provided
        if aspect_declarations:
            graph.aspect_declarations = aspect_declarations

    def list_available_patterns(self, cache_path=None):
        """List all available instruction patterns.

        Args:
            cache_path: Path to cached extraction JSON

        Returns:
            list: Sorted list of pattern names
        """
        all_instrs = self.extract_all_instructions(cache_path)
        return sorted(all_instrs.keys())

    def get_pattern_info(self, pattern_name, cache_path=None):
        """Get information about a specific pattern.

        Args:
            pattern_name: Name of the pattern
            cache_path: Path to cached extraction JSON

        Returns:
            dict: Pattern statistics {'nodes': int, 'edges': int, 'data': dict}
        """
        all_instrs = self.extract_all_instructions(cache_path)

        if pattern_name not in all_instrs:
            return None

        data = all_instrs[pattern_name]
        return {
            'nodes': len(data['nodes']),
            'edges': len(data['edges']),
            'data': data
        }

    def _convert_to_isacomp_format(self, sail_data):
        """Convert SAIL JSON to isacomp ResourceGraph JSON format.

        Args:
            sail_data: Raw SAIL extraction data

        Returns:
            dict: isacomp-compatible graph data
        """
        nodes = []
        edges = []

        # Build ID mapping: use display_name for isa_state nodes
        # This allows equivalence checking to match ISA node IDs (like 'pc_wr', 'rf')
        # with SAIL nodes that have generic IDs (like 'n515') but meaningful display_names
        id_map = {}  # old_id -> new_id
        for node in sail_data['nodes']:
            old_id = node['id']
            node_data = node['data']

            # For isa_state and key var nodes (instr), use display_name as the new ID
            display_name = node_data.get('display_name')
            if display_name and (node_data.get('type') == 'isa_state' or display_name == 'instr'):
                new_id = display_name
                id_map[old_id] = new_id
            else:
                id_map[old_id] = old_id  # Keep original ID

        # First pass: create edges list with remapped IDs
        for edge in sail_data['edges']:
            new_source = id_map.get(edge['source'], edge['source'])
            new_target = id_map.get(edge['target'], edge['target'])

            edges.append({
                'id': edge['id'],
                'source': new_source,
                'target': new_target,
                'data': edge['data']
            })

        # Second pass: remap node IDs and minimal fixups
        # Most normalization is now done by the OCaml extractor's normalize_graph:
        #   - instr is already 'var' type, not 'isa_state'
        #   - rf/csr/frf already have is_memory=true, array_depth, dimensions
        #   - bitvector_concat already normalized to 'concatenation'
        #   - sized_literal already has 'width' field
        #   - bit_width defaults to 32 for nodes that need it
        #   - state_update edges already dropped
        #   - value edges already converted to assignment/operand
        #   - operand edges on concat targets already converted to concat_input
        #   - pc_plus_4 nodes already canonicalized
        #   - name field defaults to display_name in extractor's make_node
        for node in sail_data['nodes']:
            old_id = node['id']
            new_id = id_map[old_id]  # Use remapped ID
            node_data = node['data'].copy()

            # Resolve symbolic bit_slice ranges from SAIL extraction
            # e.g. subrange_bits(x, log2_xlen - 1, 0) -> [4, 0] for RV32
            if node_data.get('type') == 'bit_slice' and node_data.get('bitslice') is None:
                display = node_data.get('display_name', '')
                if 'log2_xlen' in display:
                    # log2_xlen = 5 for RV32 (log2(32)), so range is [4, 0]
                    node_data['bitslice'] = (4, 0)
                    node_data['bit_width'] = 5

            # Ensure bitslice is always a tuple (JSON deserializes as list)
            if node_data.get('type') == 'bit_slice' and isinstance(node_data.get('bitslice'), list):
                node_data['bitslice'] = tuple(node_data['bitslice'])

            nodes.append({
                'id': new_id,  # Use remapped ID
                'data': node_data,
                'is_arch_state': node.get('is_arch_state', node_data.get('is_arch_state', False)),
                'is_uarch_state': False,
                'used_as_index': False,
                'indexed_by': None,
                'uarch_time': None,
                'latency': 1,
                'variable_latency': False
            })

        # Remap edge IDs
        result = {'nodes': nodes, 'edges': edges}

        # Pass through decode_constraints if present
        if 'decode_constraints' in sail_data:
            result['decode_constraints'] = sail_data['decode_constraints']

        return result


# Command-line interface
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Load RISC-V instructions from SAIL specification'
    )
    parser.add_argument(
        'pattern',
        nargs='?',
        help='Instruction pattern to load (e.g., RTYPE, ITYPE). If omitted, lists all patterns.'
    )
    parser.add_argument(
        '--list', '-l',
        action='store_true',
        help='List all available patterns'
    )
    parser.add_argument(
        '--info', '-i',
        metavar='PATTERN',
        help='Show information about a specific pattern'
    )
    parser.add_argument(
        '--extract', '-e',
        action='store_true',
        help='Force re-extraction from SAIL (ignore cache)'
    )

    args = parser.parse_args()

    loader = SAILInstructionLoader()

    if args.list or (not args.pattern and not args.info):
        # List all patterns
        patterns = loader.list_available_patterns()
        print(f"Available SAIL instruction patterns ({len(patterns)}):\n")

        # Group by category
        categories = {
            'Base Integer': ['RTYPE', 'ITYPE', 'SHIFTIOP', 'UTYPE', 'JAL', 'JALR', 'BTYPE', 'LOAD', 'STORE'],
            'System': ['ECALL', 'EBREAK', 'MRET', 'SRET', 'WFI'],
            'CSR': ['CSRRW', 'CSRRS', 'CSRRC'],
            'Fence': ['FENCE', 'FENCE_TSO'],
        }

        for category, cat_patterns in categories.items():
            found = [p for p in cat_patterns if p in patterns]
            if found:
                print(f"{category}:")
                for p in found:
                    info = loader.get_pattern_info(p)
                    print(f"  {p:15s} - {info['nodes']:3d} nodes, {info['edges']:3d} edges")
                print()

        # Show count of other patterns
        shown = set(sum(categories.values(), []))
        other = [p for p in patterns if p not in shown]
        if other:
            print(f"Plus {len(other)} extension patterns (M, A, F, D, V, C, B, K, etc.)")
            print(f"Use --info <pattern> to see details")

    elif args.info:
        # Show pattern info
        info = loader.get_pattern_info(args.info)
        if info:
            print(f"Pattern: {args.info}")
            print(f"  Nodes: {info['nodes']}")
            print(f"  Edges: {info['edges']}")
        else:
            print(f"Pattern '{args.info}' not found")
            print(f"Use --list to see available patterns")

    elif args.pattern:
        # Load and display pattern
        try:
            graph = loader.load_instruction_pattern(args.pattern)
            print(f"Loaded pattern: {args.pattern}")
            print(f"  Nodes: {len(graph.nodes)}")
            print(f"  Edges: {len(graph.edges)}")
            print(f"\nNode types:")
            node_types = {}
            for node in graph.nodes.values():
                ntype = node.data.get('type', 'unknown')
                node_types[ntype] = node_types.get(ntype, 0) + 1
            for ntype, count in sorted(node_types.items(), key=lambda x: -x[1]):
                print(f"  {ntype:20s}: {count:3d}")
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
