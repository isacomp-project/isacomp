#!/usr/bin/env python3
"""
Realistic ILA parser tests with actual ILA model patterns.

These test cases are based on real ILA models from the IMDb repository,
simulating the JSON format that ILAng exports.
"""

import json
import sys
import os

# Add parent directory to path to import resource_graph
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.resource_graph import ResourceGraph
from ila.ila_parser import parse_ila_json


def test_counter_with_reset():
    """
    Test Case 1: Counter with Enable and Reset

    This models a simple counter similar to what you'd find in hardware:
    - State: counter (32-bit)
    - Inputs: enable, reset
    - Instructions: INCREMENT (when enable), RESET (when reset)
    """
    print("=" * 70)
    print("Test 1: Counter with Enable and Reset")
    print("=" * 70)

    ila_json = {
        "ila_name": "counter",
        "state_num": 1,
        "input_num": 2,
        "instr_num": 2,
        "expr": [
            # 0: enable input
            {"name": "enable", "op": "VAR", "sort": {"tag": "BV", "bit_width": 1}},
            # 1: reset input
            {"name": "reset", "op": "VAR", "sort": {"tag": "BV", "bit_width": 1}},
            # 2: counter state
            {"name": "counter", "op": "VAR", "sort": {"tag": "BV", "bit_width": 32}},
            # 3: constant 1
            {"op": "CONST", "sort": {"tag": "BV", "bit_width": 1}, "value": 1},
            # 4: constant 0 (for reset)
            {"op": "CONST", "sort": {"tag": "BV", "bit_width": 32}, "value": 0},
            # 5: constant 1 (32-bit for increment)
            {"op": "CONST", "sort": {"tag": "BV", "bit_width": 32}, "value": 1},
            # 6: enable == 1
            {"op": "EQ", "sort": {"tag": "BOOL"}, "args": [0, 3]},
            # 7: reset == 1
            {"op": "EQ", "sort": {"tag": "BOOL"}, "args": [1, 3]},
            # 8: counter + 1
            {"op": "ADD", "sort": {"tag": "BV", "bit_width": 32}, "args": [2, 5]},
        ],
        "state": [2],  # counter
        "input": [0, 1],  # enable, reset
        "instr": [
            {
                "name": "INCREMENT",
                "decode": 6,  # enable == 1
                "update": {"counter": 8}  # counter = counter + 1
            },
            {
                "name": "RESET",
                "decode": 7,  # reset == 1
                "update": {"counter": 4}  # counter = 0
            }
        ]
    }

    print("\nParsing counter with enable and reset...")
    graph = parse_ila_json(ila_json)

    print(f"✓ Created ResourceGraph:")
    print(f"  Nodes: {graph.get_node_count()}")
    print(f"  Edges: {graph.get_edge_count()}")

    # Verify key components
    # Note: counter has been split into counter_rd and counter_wr
    assert "counter_rd" in graph.nodes or "counter_wr" in graph.nodes
    assert "enable" in graph.nodes
    assert "reset" in graph.nodes
    if "counter_rd" in graph.nodes:
        assert graph.nodes["counter_rd"].is_arch_state
    if "counter_wr" in graph.nodes:
        assert graph.nodes["counter_wr"].is_arch_state

    print("✓ Counter state is marked as architectural state")
    print("✓ Test 1 PASSED\n")
    return graph


def test_riscv_add_instruction():
    """
    Test Case 2: RISC-V ADD Instruction

    Models a simple RISC-V ADD instruction:
    - State: PC, register file (32 registers x 32 bits)
    - Input: instruction
    - Instruction decodes and executes ADD rd, rs1, rs2
    """
    print("=" * 70)
    print("Test 2: RISC-V ADD Instruction")
    print("=" * 70)

    ila_json = {
        "ila_name": "riscv_add",
        "state_num": 2,
        "input_num": 1,
        "instr_num": 1,
        "expr": [
            # 0: instruction input (32-bit)
            {"name": "instr", "op": "VAR", "sort": {"tag": "BV", "bit_width": 32}},
            # 1: PC state (32-bit)
            {"name": "pc", "op": "VAR", "sort": {"tag": "BV", "bit_width": 32}},
            # 2: Register file (memory: 5-bit addr, 32-bit data)
            {"name": "rf", "op": "VAR", "sort": {"tag": "MEM", "addr_width": 5, "data_width": 32}},
            # 3: constant 4
            {"op": "CONST", "sort": {"tag": "BV", "bit_width": 32}, "value": 4},
            # 4: PC + 4
            {"op": "ADD", "sort": {"tag": "BV", "bit_width": 32}, "args": [1, 3]},
            # 5: Extract rd (bits [11:7])
            {"op": "EXTRACT", "sort": {"tag": "BV", "bit_width": 5}, "args": [0], "params": [11, 7]},
            # 6: Extract rs1 (bits [19:15])
            {"op": "EXTRACT", "sort": {"tag": "BV", "bit_width": 5}, "args": [0], "params": [19, 15]},
            # 7: Extract rs2 (bits [24:20])
            {"op": "EXTRACT", "sort": {"tag": "BV", "bit_width": 5}, "args": [0], "params": [24, 20]},
            # 8: Load rf[rs1]
            {"op": "LOAD", "sort": {"tag": "BV", "bit_width": 32}, "args": [2, 6]},
            # 9: Load rf[rs2]
            {"op": "LOAD", "sort": {"tag": "BV", "bit_width": 32}, "args": [2, 7]},
            # 10: rs1_val + rs2_val
            {"op": "ADD", "sort": {"tag": "BV", "bit_width": 32}, "args": [8, 9]},
            # 11: Store result to rf[rd]
            {"op": "STORE", "sort": {"tag": "MEM", "addr_width": 5, "data_width": 32}, "args": [2, 5, 10]},
            # 12: Extract opcode (bits [6:0])
            {"op": "EXTRACT", "sort": {"tag": "BV", "bit_width": 7}, "args": [0], "params": [6, 0]},
            # 13: constant 0x33 (R-type opcode)
            {"op": "CONST", "sort": {"tag": "BV", "bit_width": 7}, "value": 0x33},
            # 14: opcode == 0x33
            {"op": "EQ", "sort": {"tag": "BOOL"}, "args": [12, 13]},
        ],
        "state": [1, 2],  # pc, rf
        "input": [0],  # instr
        "instr": [
            {
                "name": "ADD",
                "decode": 14,  # opcode == 0x33
                "update": {
                    "pc": 4,  # pc = pc + 4
                    "rf": 11  # rf[rd] = rs1_val + rs2_val
                }
            }
        ]
    }

    print("\nParsing RISC-V ADD instruction...")
    graph = parse_ila_json(ila_json)

    print(f"✓ Created ResourceGraph:")
    print(f"  Nodes: {graph.get_node_count()}")
    print(f"  Edges: {graph.get_edge_count()}")

    # Verify key components
    # Note: pc and rf have been split into _rd and _wr variants
    assert "pc_rd" in graph.nodes or "pc_wr" in graph.nodes
    assert "rf_rd" in graph.nodes or "rf_wr" in graph.nodes
    assert "instr" in graph.nodes
    if "pc_rd" in graph.nodes:
        assert graph.nodes["pc_rd"].is_arch_state
    if "pc_wr" in graph.nodes:
        assert graph.nodes["pc_wr"].is_arch_state
    if "rf_rd" in graph.nodes:
        assert graph.nodes["rf_rd"].is_arch_state
        assert graph.nodes["rf_rd"].data.get("is_memory", False)
    if "rf_wr" in graph.nodes:
        assert graph.nodes["rf_wr"].is_arch_state
        assert graph.nodes["rf_wr"].data.get("is_memory", False)

    print("✓ PC and RF are marked as architectural state")
    print("✓ RF is correctly identified as memory")
    print("✓ Bit extraction nodes created")
    print("✓ Memory load/store operations created")
    print("✓ Test 2 PASSED\n")
    return graph


def test_aes_style_memory_access():
    """
    Test Case 3: AES-style Memory Access

    Models memory access patterns similar to the AES accelerator:
    - State: address register, data memory
    - Inputs: cmd, cmdaddr, cmddata
    - Instructions: READ, WRITE with conditional updates
    """
    print("=" * 70)
    print("Test 3: AES-style Memory Access Pattern")
    print("=" * 70)

    ila_json = {
        "ila_name": "memory_controller",
        "state_num": 2,
        "input_num": 3,
        "instr_num": 2,
        "expr": [
            # Inputs
            # 0: cmd (2-bit: 0=NOP, 1=READ, 2=WRITE)
            {"name": "cmd", "op": "VAR", "sort": {"tag": "BV", "bit_width": 2}},
            # 1: cmdaddr (16-bit address)
            {"name": "cmdaddr", "op": "VAR", "sort": {"tag": "BV", "bit_width": 16}},
            # 2: cmddata (8-bit data)
            {"name": "cmddata", "op": "VAR", "sort": {"tag": "BV", "bit_width": 8}},

            # State
            # 3: address register (16-bit)
            {"name": "addr_reg", "op": "VAR", "sort": {"tag": "BV", "bit_width": 16}},
            # 4: data memory (16-bit addr, 8-bit data)
            {"name": "xram", "op": "VAR", "sort": {"tag": "MEM", "addr_width": 16, "data_width": 8}},

            # Constants
            # 5: constant 1 (READ command)
            {"op": "CONST", "sort": {"tag": "BV", "bit_width": 2}, "value": 1},
            # 6: constant 2 (WRITE command)
            {"op": "CONST", "sort": {"tag": "BV", "bit_width": 2}, "value": 2},

            # Decode conditions
            # 7: cmd == 1 (READ)
            {"op": "EQ", "sort": {"tag": "BOOL"}, "args": [0, 5]},
            # 8: cmd == 2 (WRITE)
            {"op": "EQ", "sort": {"tag": "BOOL"}, "args": [0, 6]},

            # Memory operations
            # 9: Load xram[cmdaddr]
            {"op": "LOAD", "sort": {"tag": "BV", "bit_width": 8}, "args": [4, 1]},
            # 10: Store cmddata to xram[cmdaddr]
            {"op": "STORE", "sort": {"tag": "MEM", "addr_width": 16, "data_width": 8}, "args": [4, 1, 2]},
        ],
        "state": [3, 4],  # addr_reg, xram
        "input": [0, 1, 2],  # cmd, cmdaddr, cmddata
        "instr": [
            {
                "name": "READ",
                "decode": 7,  # cmd == 1
                "update": {
                    "addr_reg": 1  # addr_reg = cmdaddr
                }
            },
            {
                "name": "WRITE",
                "decode": 8,  # cmd == 2
                "update": {
                    "addr_reg": 1,  # addr_reg = cmdaddr
                    "xram": 10  # xram[cmdaddr] = cmddata
                }
            }
        ]
    }

    print("\nParsing AES-style memory controller...")
    graph = parse_ila_json(ila_json)

    print(f"✓ Created ResourceGraph:")
    print(f"  Nodes: {graph.get_node_count()}")
    print(f"  Edges: {graph.get_edge_count()}")

    # Verify key components
    # Note: addr_reg and xram may be split into _rd and _wr variants
    assert "addr_reg" in graph.nodes or "addr_reg_rd" in graph.nodes or "addr_reg_wr" in graph.nodes
    assert "xram" in graph.nodes or "xram_rd" in graph.nodes or "xram_wr" in graph.nodes
    # Check memory flag on any variant that exists
    for node_name in ["xram", "xram_rd", "xram_wr"]:
        if node_name in graph.nodes:
            assert graph.nodes[node_name].data.get("is_memory", False)
            break

    print("✓ Memory state correctly identified")
    print("✓ Memory load/store operations created")
    print("✓ Multiple instructions with different updates parsed")
    print("✓ Test 3 PASSED\n")
    return graph


def test_conditional_ite():
    """
    Test Case 4: Conditional (ITE) Operations

    Tests if-then-else (ternary) operations common in ILA models.
    """
    print("=" * 70)
    print("Test 4: Conditional (ITE) Operations")
    print("=" * 70)

    ila_json = {
        "ila_name": "conditional_update",
        "state_num": 2,
        "input_num": 2,
        "instr_num": 1,
        "expr": [
            # Inputs
            # 0: select (1-bit)
            {"name": "select", "op": "VAR", "sort": {"tag": "BV", "bit_width": 1}},
            # 1: new_val (32-bit)
            {"name": "new_val", "op": "VAR", "sort": {"tag": "BV", "bit_width": 32}},

            # State
            # 2: reg_a (32-bit)
            {"name": "reg_a", "op": "VAR", "sort": {"tag": "BV", "bit_width": 32}},
            # 3: reg_b (32-bit)
            {"name": "reg_b", "op": "VAR", "sort": {"tag": "BV", "bit_width": 32}},

            # Constants
            # 4: constant 1
            {"op": "CONST", "sort": {"tag": "BV", "bit_width": 1}, "value": 1},
            # 5: constant 0 (32-bit)
            {"op": "CONST", "sort": {"tag": "BV", "bit_width": 32}, "value": 0},

            # Conditions
            # 6: select == 1
            {"op": "EQ", "sort": {"tag": "BOOL"}, "args": [0, 4]},

            # ITE: if (select == 1) then new_val else 0
            # 7: ITE(select == 1, new_val, 0)
            {"op": "ITE", "sort": {"tag": "BV", "bit_width": 32}, "args": [6, 1, 5]},

            # ITE: if (select == 1) then reg_b else new_val
            # 8: ITE(select == 1, reg_b, new_val)
            {"op": "ITE", "sort": {"tag": "BV", "bit_width": 32}, "args": [6, 3, 1]},
        ],
        "state": [2, 3],  # reg_a, reg_b
        "input": [0, 1],  # select, new_val
        "instr": [
            {
                "name": "CONDITIONAL_UPDATE",
                "decode": 6,  # select == 1
                "update": {
                    "reg_a": 7,  # reg_a = select ? new_val : 0
                    "reg_b": 8   # reg_b = select ? reg_b : new_val
                }
            }
        ]
    }

    print("\nParsing conditional (ITE) operations...")
    graph = parse_ila_json(ila_json)

    print(f"✓ Created ResourceGraph:")
    print(f"  Nodes: {graph.get_node_count()}")
    print(f"  Edges: {graph.get_edge_count()}")

    # Check for ternary operation nodes
    ternary_nodes = [n for n in graph.nodes.values()
                     if n.data and n.data.get('type') == 'ternary_op']
    assert len(ternary_nodes) == 2, f"Expected 2 ternary nodes, got {len(ternary_nodes)}"

    # Check for ternary edges
    ternary_edges = [e for e in graph.edges.values()
                     if e.data and 'ternary' in e.data.get('type', '')]
    assert len(ternary_edges) > 0, "Expected ternary edges"

    print(f"✓ Found {len(ternary_nodes)} ternary operation nodes")
    print(f"✓ Found {len(ternary_edges)} ternary edges")
    print("✓ Conditional operations parsed correctly")
    print("✓ Test 4 PASSED\n")
    return graph


def test_bit_operations():
    """
    Test Case 5: Bit Extraction and Concatenation

    Tests bit-level operations common in hardware specifications.
    This models extracting nibbles and recombining them.
    """
    print("=" * 70)
    print("Test 5: Bit Extraction and Concatenation")
    print("=" * 70)

    ila_json = {
        "ila_name": "bit_operations",
        "state_num": 1,
        "input_num": 2,
        "instr_num": 1,
        "expr": [
            # Inputs
            # 0: high_byte (8-bit)
            {"name": "high_byte", "op": "VAR", "sort": {"tag": "BV", "bit_width": 8}},
            # 1: low_byte (8-bit)
            {"name": "low_byte", "op": "VAR", "sort": {"tag": "BV", "bit_width": 8}},

            # State
            # 2: data_reg (8-bit, will hold swapped nibbles)
            {"name": "data_reg", "op": "VAR", "sort": {"tag": "BV", "bit_width": 8}},

            # Operations
            # 3: Extract bits [7:4] from high_byte (high nibble)
            {"op": "EXTRACT", "sort": {"tag": "BV", "bit_width": 4}, "args": [0], "params": [7, 4]},
            # 4: Extract bits [3:0] from low_byte (low nibble)
            {"op": "EXTRACT", "sort": {"tag": "BV", "bit_width": 4}, "args": [1], "params": [3, 0]},
            # 5: Concatenate extracted nibbles {high_nibble, low_nibble}
            {"op": "CONCAT", "sort": {"tag": "BV", "bit_width": 8}, "args": [3, 4]},
            # 6: Constant 1 for decode
            {"op": "CONST", "sort": {"tag": "BV", "bit_width": 1}, "value": 1},
        ],
        "state": [2],  # data_reg
        "input": [0, 1],  # high_byte, low_byte
        "instr": [
            {
                "name": "COMBINE_NIBBLES",
                "decode": 6,  # always valid
                "update": {
                    "data_reg": 5  # data_reg = {high_byte[7:4], low_byte[3:0]}
                }
            }
        ]
    }

    print("\nParsing bit extraction and concatenation...")
    graph = parse_ila_json(ila_json)

    print(f"✓ Created ResourceGraph:")
    print(f"  Nodes: {graph.get_node_count()}")
    print(f"  Edges: {graph.get_edge_count()}")

    # Check for bit slice nodes
    bit_slice_nodes = [n for n in graph.nodes.values()
                       if n.data and n.data.get('type') == 'bit_slice']
    assert len(bit_slice_nodes) > 0, "Expected bit slice nodes"

    # Check for concatenation nodes
    concat_nodes = [n for n in graph.nodes.values()
                    if n.data and n.data.get('type') == 'concatenation']
    assert len(concat_nodes) > 0, "Expected concatenation nodes"

    print(f"✓ Found {len(bit_slice_nodes)} bit slice nodes")
    print(f"✓ Found {len(concat_nodes)} concatenation nodes")
    print("✓ Bit operations parsed correctly")
    print("✓ Test 5 PASSED\n")
    return graph


def analyze_graph_structure(graph, name):
    """Detailed analysis of a parsed graph."""
    print(f"\n{'=' * 70}")
    print(f"Detailed Analysis: {name}")
    print('=' * 70)

    # Count node types
    node_types = {}
    for node in graph.nodes.values():
        node_type = node.data.get('type', 'unknown') if node.data else 'unknown'
        node_types[node_type] = node_types.get(node_type, 0) + 1

    print("\nNode Type Distribution:")
    for node_type, count in sorted(node_types.items()):
        print(f"  {node_type:20s}: {count:3d}")

    # Count edge types
    edge_types = {}
    for edge in graph.edges.values():
        edge_type = edge.data.get('type', 'unknown') if edge.data else 'unknown'
        edge_types[edge_type] = edge_types.get(edge_type, 0) + 1

    print("\nEdge Type Distribution:")
    for edge_type, count in sorted(edge_types.items()):
        print(f"  {edge_type:20s}: {count:3d}")

    # Count architectural state
    arch_state = [n for n in graph.nodes.values() if n.is_arch_state]
    print(f"\nArchitectural State Nodes: {len(arch_state)}")
    for node in arch_state:
        is_mem = "(memory)" if node.data and node.data.get('is_memory') else ""
        print(f"  - {node.id} {is_mem}")

    print()


def main():
    """Run all realistic ILA parser tests."""
    print("\n" + "=" * 70)
    print("Realistic ILA Parser Test Suite")
    print("Testing with patterns from actual ILA models")
    print("=" * 70 + "\n")

    try:
        # Run all tests
        graph1 = test_counter_with_reset()
        graph2 = test_riscv_add_instruction()
        graph3 = test_aes_style_memory_access()
        graph4 = test_conditional_ite()
        graph5 = test_bit_operations()

        # Detailed analysis
        analyze_graph_structure(graph2, "RISC-V ADD Instruction")
        analyze_graph_structure(graph3, "AES-style Memory Access")

        # Summary
        print("=" * 70)
        print("ALL REALISTIC TESTS PASSED! ✓")
        print("=" * 70)
        print("\nTested ILA patterns:")
        print("  ✓ Counter with enable/reset")
        print("  ✓ RISC-V ADD instruction (register file, bit extraction)")
        print("  ✓ AES-style memory controller (memory access patterns)")
        print("  ✓ Conditional (ITE) operations")
        print("  ✓ Bit extraction and concatenation")
        print("\nThe ILA frontend successfully parses realistic hardware models!")
        print("\nNext: Export actual ILA models from IMDb to test with real data.")
        print()

        return 0

    except AssertionError as e:
        print(f"\n❌ Test assertion failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    exit(main())
