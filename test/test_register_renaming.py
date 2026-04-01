#!/usr/bin/env python3
"""
Test suite for register renaming optimization.

Tests the register renaming optimization implementation to ensure:
1. Renamer and denamer nodes are created correctly
2. Architectural indices are mapped to microarchitectural indices
3. Dependency analysis uses microarchitectural indices
4. Integration with optimization framework works
"""

import sys
import os

# Add parent and test directories to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from core.resource_graph import ResourceGraph, Node, Edge
from opt.ooo.register_renaming_optimization import (
    RegisterRenamingSpec,
    RegisterRenamingOptimization,
    apply_register_renaming,
    get_microarchitectural_index_nodes,
    has_register_renaming,
    get_renamed_resources
)
from optimization_framework import OptimizationPlan, OptimizationEngine


def create_simple_rf_graph() -> ResourceGraph:
    """
    Create a simple graph with register file accesses.

    Structure:
        rf (base resource)
        ├─ rs (architectural index)
        ├─ rt (architectural index)
        └─ rd (architectural index)

        rf[rs] (read)  ──→ r1 (operation reads from rf[rs])
        rf[rt] (read)  ──→ r2 (operation reads from rf[rt])
        result ──→ rf[rd] (write to rf[rd])
    """
    graph = ResourceGraph()

    # Create base resource (register file)
    rf = Node('rf', {'type': 'architectural_state', 'name': 'rf'}, is_arch_state=True)
    graph.add_node(rf)

    # Create architectural indices
    rs = Node('rs', {'type': 'field', 'name': 'rs'})
    rt = Node('rt', {'type': 'field', 'name': 'rt'})
    rd = Node('rd', {'type': 'field', 'name': 'rd'})
    graph.add_node(rs)
    graph.add_node(rt)
    graph.add_node(rd)

    # Create array access nodes for reads
    rf_rs = Node('rf[rs]_rd', {
        'type': 'array_access',
        'name': 'rf[rs]',
        'base_resource': 'rf'
    })
    graph.add_node(rf_rs)

    rf_rt = Node('rf[rt]_rd', {
        'type': 'array_access',
        'name': 'rf[rt]',
        'base_resource': 'rf'
    })
    graph.add_node(rf_rt)

    # Create array access node for write
    rf_rd = Node('rf[rd]_wr', {
        'type': 'array_access',
        'name': 'rf[rd]',
        'base_resource': 'rf'
    })
    graph.add_node(rf_rd)

    # Wire indices to array accesses
    edge_rs_idx = Edge(rs, rf_rs, data={'type': 'array_index'})
    edge_rt_idx = Edge(rt, rf_rt, data={'type': 'array_index'})
    edge_rd_idx = Edge(rd, rf_rd, data={'type': 'array_index'})
    graph.add_edge(edge_rs_idx)
    graph.add_edge(edge_rt_idx)
    graph.add_edge(edge_rd_idx)

    # Wire base resource to array accesses
    edge_rf_rs = Edge(rf, rf_rs, data={'type': 'base_resource'})
    edge_rf_rt = Edge(rf, rf_rt, data={'type': 'base_resource'})
    edge_rf_rd = Edge(rf, rf_rd, data={'type': 'base_resource'})
    graph.add_edge(edge_rf_rs)
    graph.add_edge(edge_rf_rt)
    graph.add_edge(edge_rf_rd)

    # Create operation that reads from rf[rs] and rf[rt]
    r1 = Node('r1', {'type': 'temporary', 'name': 'r1'})
    r2 = Node('r2', {'type': 'temporary', 'name': 'r2'})
    graph.add_node(r1)
    graph.add_node(r2)

    edge_rf_rs_read = Edge(rf_rs, r1, data={'type': 'assignment'})
    edge_rf_rt_read = Edge(rf_rt, r2, data={'type': 'assignment'})
    graph.add_edge(edge_rf_rs_read)
    graph.add_edge(edge_rf_rt_read)

    # Create operation that produces result
    add_op = Node('add_op', {
        'type': 'operation',
        'operator': '+',
        'display_name': 'r1 + r2'
    })
    graph.add_node(add_op)

    edge_r1_add = Edge(r1, add_op, data={'type': 'operand', 'position': 'left'})
    edge_r2_add = Edge(r2, add_op, data={'type': 'operand', 'position': 'right'})
    graph.add_edge(edge_r1_add)
    graph.add_edge(edge_r2_add)

    # Wire result to rf[rd]
    edge_add_rf_rd = Edge(add_op, rf_rd, data={'type': 'assignment'})
    graph.add_edge(edge_add_rf_rd)

    return graph


def test_basic_renaming():
    """Test basic register renaming on a simple graph."""
    print("=" * 70)
    print("TEST: Basic Register Renaming")
    print("=" * 70)

    graph = create_simple_rf_graph()

    print("\nInitial graph:")
    print(f"  Nodes: {len(graph.nodes)}")
    print(f"  Edges: {len(graph.edges)}")

    # Apply register renaming
    spec = RegisterRenamingSpec(
        resource_name='rf',
        num_physical_regs=64,
        target_indices=None  # Rename all indices
    )

    optimizer = RegisterRenamingOptimization(graph)
    success = optimizer.apply(spec)

    print("\nAfter renaming:")
    print(f"  Success: {success}")
    print(f"  Nodes: {len(graph.nodes)}")
    print(f"  Edges: {len(graph.edges)}")

    # Verify renaming components were created
    renamers = [n for n in graph.nodes.values() if n.data.get('type') == 'renamer']
    rename_tables = [n for n in graph.nodes.values() if n.data.get('type') == 'rename_table']
    uarch_indices = [n for n in graph.nodes.values() if n.data.get('type') == 'uarch_index']
    denamers = [n for n in graph.nodes.values() if n.data.get('type') in ['denamer', 'denamer_instance']]

    print("\nRenaming components:")
    print(f"  Renamers: {len(renamers)}")
    print(f"  Rename tables: {len(rename_tables)}")
    print(f"  Microarch indices: {len(uarch_indices)}")
    print(f"  Denamers: {len(denamers)}")

    # Assertions
    assert success, "Renaming should succeed"
    assert len(renamers) == 1, "Should have 1 renamer"
    assert len(rename_tables) == 1, "Should have 1 rename table"
    assert len(uarch_indices) == 3, "Should have 3 microarch indices (rs, rt, rd)"
    assert len(denamers) >= 1, "Should have at least 1 denamer"

    print("\n✓ Basic renaming test passed")
    return True


def test_microarch_index_retrieval():
    """Test retrieval of microarchitectural index nodes."""
    print("\n" + "=" * 70)
    print("TEST: Microarchitectural Index Retrieval")
    print("=" * 70)

    graph = create_simple_rf_graph()

    # Get original index nodes
    rs_orig = graph.nodes.get('rs')
    rt_orig = graph.nodes.get('rt')
    rd_orig = graph.nodes.get('rd')

    print("\nOriginal architectural indices:")
    print(f"  rs: {rs_orig.id if rs_orig else 'NOT FOUND'}")
    print(f"  rt: {rt_orig.id if rt_orig else 'NOT FOUND'}")
    print(f"  rd: {rd_orig.id if rd_orig else 'NOT FOUND'}")

    # Apply renaming
    spec = RegisterRenamingSpec(resource_name='rf', num_physical_regs=64)
    apply_register_renaming(graph, spec)

    # Get microarchitectural indices
    uarch_indices = get_microarchitectural_index_nodes(graph)

    print("\nMicroarchitectural indices:")
    for arch_name, uarch_node in uarch_indices.items():
        print(f"  {arch_name} → {uarch_node.id}")

    # Assertions
    assert len(uarch_indices) == 3, "Should have 3 microarch indices"
    for arch_name, uarch_node in uarch_indices.items():
        assert uarch_node.id.startswith('uarch_'), f"{arch_name} should map to microarch index"

    print("\n✓ Microarch index retrieval test passed")
    return True


def test_renaming_detection():
    """Test detection of register renaming in graphs."""
    print("\n" + "=" * 70)
    print("TEST: Renaming Detection")
    print("=" * 70)

    graph = create_simple_rf_graph()

    # Before renaming
    has_renaming_before = has_register_renaming(graph)
    renamed_resources_before = get_renamed_resources(graph)

    print("\nBefore renaming:")
    print(f"  Has renaming: {has_renaming_before}")
    print(f"  Renamed resources: {renamed_resources_before}")

    # Apply renaming
    spec = RegisterRenamingSpec(resource_name='rf', num_physical_regs=64)
    apply_register_renaming(graph, spec)

    # After renaming
    has_renaming_after = has_register_renaming(graph)
    renamed_resources_after = get_renamed_resources(graph)

    print("\nAfter renaming:")
    print(f"  Has renaming: {has_renaming_after}")
    print(f"  Renamed resources: {renamed_resources_after}")

    # Assertions
    assert not has_renaming_before, "Should not detect renaming before applying it"
    assert len(renamed_resources_before) == 0, "Should have no renamed resources before"
    assert has_renaming_after, "Should detect renaming after applying it"
    assert 'rf' in renamed_resources_after, "rf should be in renamed resources"

    print("\n✓ Renaming detection test passed")
    return True


def test_optimization_framework_integration():
    """Test integration with optimization framework."""
    print("\n" + "=" * 70)
    print("TEST: Optimization Framework Integration")
    print("=" * 70)

    # Note: This test would require valid ISA files for merging
    # For now, we'll just test the plan creation

    plan = OptimizationPlan()

    # Add register renaming step
    plan.add_register_renaming(
        resource_name='rf',
        num_physical_regs=64,
        target_indices=['rs', 'rt', 'rd']
    )

    print("\nOptimization plan created:")
    print(f"  Number of steps: {len(plan.steps)}")

    steps = plan.get_sorted_steps()
    for i, step in enumerate(steps):
        print(f"  Step {i+1}: {step['type']} (priority: {step['priority']})")

    # Assertions
    assert len(plan.steps) == 1, "Should have 1 step"
    assert plan.steps[0]['type'] == 'register_renaming', "Step should be register_renaming"
    assert plan.steps[0]['resource_name'] == 'rf', "Resource should be rf"
    assert plan.steps[0]['num_physical_regs'] == 64, "Should have 64 physical registers"

    print("\n✓ Optimization framework integration test passed")
    return True


def test_separate_register_files():
    """Test separate architectural and physical register files mode."""
    print("\n" + "=" * 70)
    print("TEST: Separate Register Files Mode")
    print("=" * 70)

    graph = create_simple_rf_graph()

    print("\nInitial graph:")
    print(f"  Nodes: {len(graph.nodes)}")
    print(f"  Edges: {len(graph.edges)}")

    # Apply register renaming with separate_regfiles=True
    spec = RegisterRenamingSpec(
        resource_name='rf',
        num_physical_regs=64,
        target_indices=None,  # Rename all indices
        separate_regfiles=True  # Use separate physical register file
    )

    optimizer = RegisterRenamingOptimization(graph)
    success = optimizer.apply(spec)

    print("\nAfter renaming (separate regfiles mode):")
    print(f"  Success: {success}")
    print(f"  Nodes: {len(graph.nodes)}")
    print(f"  Edges: {len(graph.edges)}")

    # Verify components were created
    renamers = [n for n in graph.nodes.values() if n.data.get('type') == 'renamer']
    rename_tables = [n for n in graph.nodes.values() if n.data.get('type') == 'rename_table']
    uarch_indices = [n for n in graph.nodes.values() if n.data.get('type') == 'uarch_index']
    denamers = [n for n in graph.nodes.values() if n.data.get('type') in ['denamer', 'denamer_instance']]
    physical_regfiles = [n for n in graph.nodes.values() if n.data.get('type') == 'physical_regfile']
    prf_accesses = [n for n in graph.nodes.values() if n.data.get('base_resource', '').startswith('prf_')]

    print("\nComponents created:")
    print(f"  Renamers: {len(renamers)}")
    print(f"  Rename tables: {len(rename_tables)}")
    print(f"  Microarch indices: {len(uarch_indices)}")
    print(f"  Denamers: {len(denamers)}")
    print(f"  Physical register files: {len(physical_regfiles)}")
    print(f"  PRF accesses: {len(prf_accesses)}")

    # Assertions
    assert success, "Renaming should succeed"
    assert len(renamers) == 1, "Should have 1 renamer"
    assert len(rename_tables) == 1, "Should have 1 rename table"
    assert len(uarch_indices) == 3, "Should have 3 microarch indices (rs, rt, rd)"
    assert len(physical_regfiles) == 1, "Should have 1 physical register file"
    assert len(prf_accesses) >= 3, "Should have at least 3 PRF accesses (2 reads + 1 write)"

    # Verify physical register file properties
    prf = physical_regfiles[0]
    print(f"\nPhysical register file:")
    print(f"  ID: {prf.id}")
    print(f"  Name: {prf.data.get('name')}")
    print(f"  Num physical regs: {prf.data.get('num_physical_regs')}")
    print(f"  Is uarch state: {prf.is_uarch_state}")

    assert prf.data.get('num_physical_regs') == 64, "PRF should have 64 registers"
    assert prf.is_uarch_state, "PRF should be uarch state"

    print("\n✓ Separate register files test passed")
    return True


def run_all_tests():
    """Run all register renaming tests."""
    print("\n" + "=" * 70)
    print("REGISTER RENAMING TEST SUITE")
    print("=" * 70)

    tests = [
        ("Basic Renaming", test_basic_renaming),
        ("Microarch Index Retrieval", test_microarch_index_retrieval),
        ("Renaming Detection", test_renaming_detection),
        ("Optimization Framework Integration", test_optimization_framework_integration),
        ("Separate Register Files", test_separate_register_files),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            test_func()
            passed += 1
        except AssertionError as e:
            print(f"\n✗ {name} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"\n✗ {name} ERROR: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Passed: {passed}/{len(tests)}")
    print(f"Failed: {failed}/{len(tests)}")

    if failed == 0:
        print("\n✓ All tests passed!")
        return True
    else:
        print(f"\n✗ {failed} test(s) failed")
        return False


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
