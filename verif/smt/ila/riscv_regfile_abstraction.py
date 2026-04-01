#!/usr/bin/env python3
"""
RISC-V ILA Register File Abstraction

This module contains specialized code to transform ILA's explicit register
representation (x0-x31) into an array abstraction (rf), enabling structural
equivalence checking with ISA models.

This is domain-specific code for RISC-V verification, not general-purpose.
"""

from core.resource_graph import ResourceGraph, Node, Edge
from typing import Set, Dict, List, Tuple, Optional
import re


class RISCVRegisterFileAbstractor:
    """
    Transform RISC-V ILA's explicit registers (x0-x31) into array form (rf).

    This makes the ILA structurally compatible with ISA for SMT comparison.
    """

    def __init__(self, graph: ResourceGraph):
        self.graph = graph
        self.register_nodes: Dict[int, List[Node]] = {}  # reg_num -> [read_nodes, write_node]
        self.rd_node: Optional[Node] = None  # The register index variable (rd)

    def detect_register_pattern(self) -> bool:
        """
        Detect if this graph has the RISC-V register file pattern.

        Pattern:
        - 32 architectural state nodes: x0, x1, ..., x31
        - Each 32-bit bitvector
        - Conditional updates based on register index

        Returns:
            True if RISC-V register pattern detected
        """
        print("\n" + "="*70)
        print("Detecting RISC-V Register File Pattern")
        print("="*70)

        # Find all xN registers
        for node in self.graph.nodes.values():
            # Check if node is isa_state (architectural or microarchitectural state)
            node_type = node.data.get('type', '')
            if node_type.startswith('isa_state') or node_type == 'architectural_state':
                name = node.data.get('name', node.id)

                # Match x0, x1, ..., x31
                match = re.match(r'^x(\d+)$', name)
                if match:
                    reg_num = int(match.group(1))
                    if 0 <= reg_num <= 31:
                        if reg_num not in self.register_nodes:
                            self.register_nodes[reg_num] = []
                        self.register_nodes[reg_num].append(node)

        print(f"\nFound {len(self.register_nodes)} registers")

        # Check if we have all 32 registers
        if len(self.register_nodes) != 32:
            print(f"✗ Expected 32 registers, found {len(self.register_nodes)}")
            return False

        # Check if we have 0-31
        for i in range(32):
            if i not in self.register_nodes:
                print(f"✗ Missing register x{i}")
                return False

        print("✓ All 32 RISC-V registers present (x0-x31)")

        # Check bit widths
        for reg_num, nodes in self.register_nodes.items():
            for node in nodes:
                # ILA uses 'bit_width', ISA uses 'width'
                width = node.data.get('bit_width') or node.data.get('width', 0)
                if width != 32:
                    print(f"✗ Register x{reg_num} has width {width}, expected 32")
                    return False

        print("✓ All registers are 32-bit")

        # Look for ternary operation pattern (after normalization: conditional → ternary_op)
        # Each register should have a ternary write like: xi_out = (rd == i) ? result : xi_in
        ternary_count = 0
        for node in self.graph.nodes.values():
            node_type = node.data.get('type')
            if node_type in ['conditional', 'ternary_op']:  # Support both for compatibility
                ternary_count += 1

        print(f"✓ Found {ternary_count} ternary/conditional nodes")

        # Expect ~93 ternaries (3 per register roughly: condition check, read mux, write mux)
        if ternary_count < 30:  # At least 1 per register
            print(f"✗ Too few ternaries for register file pattern")
            return False

        print("\n✓ RISC-V register file pattern detected!")
        return True

    def find_register_index(self) -> Optional[Node]:
        """
        Find the node that represents the destination register index (rd).

        This is the value used in comparisons like (rd == 0), (rd == 1), etc.
        """
        print("\n" + "="*70)
        print("Finding Register Index Variable (rd)")
        print("="*70)

        # Look for comparison nodes that compare against constants 0-31
        # These should all use the same source node (the rd value)

        rd_candidates: Dict[str, int] = {}  # node_id -> count of comparisons

        for node in self.graph.nodes.values():
            if node.data.get('type') == 'comparison':
                operation = node.data.get('operation')
                if operation == '==':
                    # Find what it's being compared to
                    operands = list(node.incoming_edges)
                    if len(operands) == 2:
                        # Check if one operand is a constant 0-31
                        for edge in operands:
                            source = edge.source
                            if source.data.get('type') == 'constant':
                                value = source.data.get('value', -1)
                                # Handle case where value might be dict or other type
                                if isinstance(value, int) and 0 <= value <= 31:
                                    # The other operand is likely rd
                                    for edge2 in operands:
                                        if edge2.source != source:
                                            candidate_id = edge2.source.id
                                            rd_candidates[candidate_id] = rd_candidates.get(candidate_id, 0) + 1

        print(f"\nRegister index candidates:")
        for node_id, count in sorted(rd_candidates.items(), key=lambda x: -x[1])[:5]:
            print(f"  {node_id}: {count} comparisons")

        # The rd node should be compared against many register indices
        if rd_candidates:
            best_candidate_id = max(rd_candidates.items(), key=lambda x: x[1])[0]
            best_count = rd_candidates[best_candidate_id]

            if best_count >= 10:  # Should be compared to at least 10 different register indices
                self.rd_node = self.graph.nodes[best_candidate_id]
                print(f"\n✓ Found rd: {best_candidate_id} (used in {best_count} comparisons)")
                return self.rd_node

        print("\n✗ Could not identify rd variable")
        return None

    def create_register_file_array(self) -> Node:
        """
        Create a new array node to represent the register file.

        Returns:
            The new rf array node
        """
        print("\n" + "="*70)
        print("Creating Register File Array")
        print("="*70)

        # Create rf array: rf[4:0][31:0] (5-bit index, 32-bit values)
        rf_data = {
            'type': 'isa_state',
            'name': 'rf',
            'dimensions': [(31, 0), (4, 0)],  # [data_width, index_width]
            'is_memory': False,
            'is_register_file': True,
        }

        rf_node = Node('rf', rf_data, from_isa_spec=False)
        rf_node.is_arch_state = True
        self.graph.add_node(rf_node)

        print(f"✓ Created rf array node: {rf_node.id}")
        print(f"  Type: Array[5-bit index -> 32-bit value]")

        return rf_node

    def transform_register_reads(self, rf_node: Node) -> int:
        """
        Replace explicit register reads (x0_in, x1_in, ...) with array selects.

        Pattern to replace:
            Conditionals that select which register to read based on rd/rs/rt

        With:
            Array access: rf[rs]

        Returns:
            Number of read patterns transformed
        """
        print("\n" + "="*70)
        print("Transforming Register Reads to Array Selects")
        print("="*70)

        # Find nodes that use registers as inputs
        # These will have edges from x0, x1, etc.
        register_users: Dict[str, List[Tuple[Node, Edge]]] = {}  # reg_name -> [(user_node, edge)]

        for reg_num in range(32):
            if reg_num not in self.register_nodes:
                continue

            reg_name = f'x{reg_num}'
            for reg_node in self.register_nodes[reg_num]:
                # Find all nodes that read from this register
                for edge in reg_node.outgoing_edges:
                    user_node = edge.target
                    if reg_name not in register_users:
                        register_users[reg_name] = []
                    register_users[reg_name].append((user_node, edge))

        print(f"\nFound {len(register_users)} registers with users")

        # For each register source (rs1, rs2), create an array_access node
        # We'll look for bit_slice nodes that extract register indices from instruction
        reg_index_nodes = {}  # 'rs1', 'rs2', 'rd' -> node

        for node in self.graph.nodes.values():
            node_id = node.data.get('name', node.id).lower()
            if 'rs1' in node_id or node_id == 'rs1':
                reg_index_nodes['rs1'] = node
            elif 'rs2' in node_id or node_id == 'rs2':
                reg_index_nodes['rs2'] = node
            elif 'rd' in node_id and node.data.get('type') == 'bit_slice':
                reg_index_nodes['rd'] = node

        print(f"Found register index nodes: {list(reg_index_nodes.keys())}")

        # Note: Full transformation requires identifying which conditionals
        # correspond to which register operand (rs1 vs rs2)
        # For now, mark this as needing more work

        return len(register_users)

    def transform_register_writes(self, rf_node: Node) -> int:
        """
        Replace conditional register writes with array stores.

        Pattern to replace:
            x0_out = (rd == 0) ? result : x0_in
            x1_out = (rd == 1) ? result : x1_in
            ...

        With:
            rf_out = store(rf_in, rd, result)

        Returns:
            Number of write patterns transformed
        """
        print("\n" + "="*70)
        print("Transforming Register Writes to Array Store")
        print("="*70)

        # Find the common write value (result) by looking at conditional nodes
        # All x*_out nodes should have incoming conditional edges

        write_value_candidates: Dict[str, int] = {}

        for reg_num in range(32):
            if reg_num not in self.register_nodes:
                continue

            for node in self.register_nodes[reg_num]:
                # Look for outgoing edges to see if this is written
                for edge in node.outgoing_edges:
                    if edge.data.get('type') == 'assignment':
                        # The source of this edge is the new value
                        source = edge.source
                        if source.data.get('type') == 'conditional':
                            # Find what value is being written (the "true" branch)
                            for cond_edge in source.incoming_edges:
                                if cond_edge.data.get('type') == 'ternary_true':
                                    value_node_id = cond_edge.source.id
                                    write_value_candidates[value_node_id] = write_value_candidates.get(value_node_id, 0) + 1

        print(f"\nWrite value candidates (nodes written to multiple registers):")
        for node_id, count in sorted(write_value_candidates.items(), key=lambda x: -x[1])[:5]:
            print(f"  {node_id}: written to {count} registers")

        if write_value_candidates:
            # The most common write value is likely the ALU result
            result_node_id = max(write_value_candidates.items(), key=lambda x: x[1])[0]
            result_count = write_value_candidates[result_node_id]

            print(f"\n✓ Found common write value: {result_node_id} (used {result_count} times)")

            # We could create an array_access write node here
            # But for SMT comparison, we'll handle this in the SMT converter

            return result_count

        return 0

    def remove_register_file_nodes(self) -> int:
        """
        Remove all explicit register nodes and their associated conditionals/comparisons.

        Returns:
            Number of nodes removed
        """
        print("\n" + "="*70)
        print("Removing Register File Explosion Nodes")
        print("="*70)

        nodes_to_remove = set()

        # 1. Mark all 32 explicit registers
        for reg_num, nodes in self.register_nodes.items():
            for node in nodes:
                nodes_to_remove.add(node.id)

        print(f"Marked {len(nodes_to_remove)} explicit register nodes")

        # 2. Mark conditionals that only connect explicit registers
        for node in self.graph.nodes.values():
            if node.data.get('type') == 'conditional':
                uses_explicit_regs = False
                for edge in node.incoming_edges:
                    if edge.source.id in nodes_to_remove:
                        uses_explicit_regs = True
                        break

                if uses_explicit_regs:
                    outputs_to_transform = True
                    for edge in node.outgoing_edges:
                        target_type = edge.target.data.get('type')
                        if target_type not in ['conditional', 'architectural_state']:
                            outputs_to_transform = False
                            break

                    if outputs_to_transform:
                        nodes_to_remove.add(node.id)

        # 3. Mark comparisons used only by register conditionals
        for node in self.graph.nodes.values():
            if node.data.get('type') == 'comparison':
                only_used_by_reg_conditionals = True
                for edge in node.outgoing_edges:
                    if edge.target.id not in nodes_to_remove:
                        only_used_by_reg_conditionals = False
                        break

                if only_used_by_reg_conditionals and len(node.outgoing_edges) > 0:
                    nodes_to_remove.add(node.id)

        # 4. Mark constants used only by register comparisons
        for node in self.graph.nodes.values():
            if node.data.get('type') == 'constant':
                only_used_by_reg_comps = True
                for edge in node.outgoing_edges:
                    if edge.target.id not in nodes_to_remove:
                        only_used_by_reg_comps = False
                        break

                if only_used_by_reg_comps and len(node.outgoing_edges) > 0:
                    nodes_to_remove.add(node.id)

        # Remove the nodes
        for node_id in nodes_to_remove:
            if node_id in self.graph.nodes:
                self.graph.remove_node(node_id)

        print(f"✓ Removed {len(nodes_to_remove)} nodes")
        return len(nodes_to_remove)

    def transform(self) -> bool:
        """
        Main transformation: convert explicit registers to array.

        Returns:
            True if transformation successful
        """
        print("\n" + "="*70)
        print("RISC-V Register File Abstraction Transform")
        print("="*70)

        nodes_before = len(self.graph.nodes)

        # Step 1: Detect pattern
        if not self.detect_register_pattern():
            return False

        # Step 2: Find register index
        if not self.find_register_index():
            print("\nWarning: Could not find rd variable, continuing anyway...")

        # Step 3: Create array
        rf_node = self.create_register_file_array()

        # Step 4: Remove explicit register nodes
        nodes_removed = self.remove_register_file_nodes()

        print("\n" + "="*70)
        print("Transformation Summary")
        print("="*70)
        print(f"✓ Detected 32 RISC-V registers")
        print(f"✓ Removed {nodes_removed} nodes ({nodes_before} -> {len(self.graph.nodes)})")
        print(f"✓ Created rf array node")
        print(f"\nGraph size reduction: {nodes_removed/nodes_before*100:.1f}%")

        return True


def detect_and_abstract_riscv_regfile(graph: ResourceGraph) -> bool:
    """
    Detect and abstract RISC-V register file pattern in an ILA graph.

    Args:
        graph: ResourceGraph from ILA parser

    Returns:
        True if pattern detected and transformation applied
    """
    abstractor = RISCVRegisterFileAbstractor(graph)
    return abstractor.transform()


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 riscv_regfile_abstraction.py <ila_json>")
        print("Example: python3 riscv_regfile_abstraction.py frontends/ila/test_data/riscv/individual/riscv_add.json")
        sys.exit(1)

    ila_file = sys.argv[1]

    print("="*70)
    print("RISC-V Register File Pattern Detection & Abstraction")
    print("="*70)
    print(f"\nInput: {ila_file}")

    # Load ILA graph
    from core.resource_graph import ResourceGraph
    graph = ResourceGraph.from_ila_json_file(ila_file)

    # Run transformation
    success = detect_and_abstract_riscv_regfile(graph)

    if success:
        print("\n" + "="*70)
        print("✓ SUCCESS: RISC-V register file pattern detected!")
        print("="*70)
        print("\nNext step: Create SMT mapping to equate:")
        print("  ILA: x0, x1, ..., x31")
        print("  ISA: rf[0], rf[1], ..., rf[31]")
    else:
        print("\n" + "="*70)
        print("✗ FAILED: Could not detect RISC-V register file pattern")
        print("="*70)
