#!/usr/bin/env python3
"""
Test change operation latency with simplified design.
"""

from core.resource_graph import ResourceGraph
from opt.temporal.multi_cycle_operations import change_operation_latency


def test_change_latency():
    """Test changing operation latency."""

    print("=== TESTING CHANGE OPERATION LATENCY ===\n")

    # Load a graph
    print("STEP 1: Loading test graph...")
    graph = ResourceGraph.from_isa_file('isa/mips32/add.isa')
    graph.infer_uarch_time()

    print(f"Original graph: {graph}")
    print(f"Original pipeline depth: {graph.get_max_uarch_time() + 1} cycles\n")

    # Find an operation
    operations = [n for n in graph.nodes.values() if n.data.get('type') == 'operation']

    if not operations:
        print("ERROR: No operations found in graph")
        return False

    target_op = operations[0]
    print(f"Target operation: {target_op.id}")
    print(f"Initial latency: {target_op.latency} cycle(s)\n")

    # Test 1: Increase latency from 0 to 3
    print("="*70)
    print("TEST 1: Increase latency from 0 to 3 cycles")
    print("="*70)

    success = change_operation_latency(graph, target_op.id, target_latency=3)

    if not success:
        print("ERROR: Failed to increase latency")
        return False

    # Verify
    if target_op.latency != 3:
        print(f"ERROR: Expected latency 3, got {target_op.latency}")
        return False

    # Check that operation has complete and cycle outputs
    if not target_op.data.get('has_complete_output'):
        print("ERROR: Operation should have complete output")
        return False

    if not target_op.data.get('has_cycle_output'):
        print("ERROR: Operation should have cycle output")
        return False

    # Check that downstream ISA writes are gated
    # Find ISA writes downstream of this operation
    downstream_isa_writes = []
    for edge in target_op.outgoing_edges:
        if edge.target.is_arch_state and edge.data.get('type') == 'assignment':
            downstream_isa_writes.append(edge.target)

    gated_writes = [n for n in downstream_isa_writes if n.data.get('enable')]

    print(f"\n✓ Latency increased to 3 cycles")
    print(f"✓ Operation has complete output: {target_op.data.get('has_complete_output')}")
    print(f"✓ Operation has cycle output: {target_op.data.get('has_cycle_output')}")
    print(f"✓ Downstream ISA writes gated: {len(gated_writes)} / {len(downstream_isa_writes)}")

    if len(gated_writes) != len(downstream_isa_writes):
        print(f"ERROR: Not all downstream ISA writes are gated")
        return False

    # Test 2: Increase latency further from 3 to 5
    print("\n" + "="*70)
    print("TEST 2: Increase latency from 3 to 5 cycles")
    print("="*70)

    success = change_operation_latency(graph, target_op.id, target_latency=5)

    if not success:
        print("ERROR: Failed to increase latency from 3 to 5")
        return False

    # Verify
    if target_op.latency != 5:
        print(f"ERROR: Expected latency 5, got {target_op.latency}")
        return False

    print(f"\n✓ Latency increased to 5 cycles")

    # Test 3: Decrease latency from 5 to 2
    print("\n" + "="*70)
    print("TEST 3: Decrease latency from 5 to 2 cycles")
    print("="*70)

    success = change_operation_latency(graph, target_op.id, target_latency=2)

    if not success:
        print("ERROR: Failed to decrease latency from 5 to 2")
        return False

    # Verify
    if target_op.latency != 2:
        print(f"ERROR: Expected latency 2, got {target_op.latency}")
        return False

    print(f"\n✓ Latency decreased to 2 cycles")

    # Test 4: Remove multi-cycle logic (set to 0)
    print("\n" + "="*70)
    print("TEST 4: Remove multi-cycle logic (set latency to 0)")
    print("="*70)

    success = change_operation_latency(graph, target_op.id, target_latency=0)

    if not success:
        print("ERROR: Failed to set latency to 0")
        return False

    # Verify
    if target_op.latency != 0:
        print(f"ERROR: Expected latency 0, got {target_op.latency}")
        return False

    if target_op.data.get('multi_cycle') != False:
        print(f"ERROR: Expected multi_cycle=False, got {target_op.data.get('multi_cycle')}")
        return False

    if target_op.data.get('has_complete_output') != False:
        print(f"ERROR: Expected has_complete_output=False")
        return False

    # Check that downstream ISA writes are no longer gated
    downstream_isa_writes = []
    for edge in target_op.outgoing_edges:
        if edge.target.is_arch_state and edge.data.get('type') == 'assignment':
            downstream_isa_writes.append(edge.target)

    gated_writes = [n for n in downstream_isa_writes if n.data.get('enable')]

    print(f"\n✓ Latency set to 0 cycles (combinational)")
    print(f"✓ multi_cycle flag: {target_op.data.get('multi_cycle')}")
    print(f"✓ has_complete_output: {target_op.data.get('has_complete_output')}")
    print(f"✓ Downstream ISA writes gated: {len(gated_writes)} (should be 0)")

    if len(gated_writes) != 0:
        print("ERROR: Downstream ISA writes should not be gated for combinational operation")
        return False

    # Verify timing is based on data dependencies (not enable gating)
    print(f"✓ Operation uarch_time: {target_op.uarch_time}")
    for write in downstream_isa_writes:
        print(f"✓ {write.id} uarch_time: {write.uarch_time} (based on data inputs)")
        # Note: uarch_time reflects data timing, not enable gating timing

    # Test 5: No-op change (already at latency 0)
    print("\n" + "="*70)
    print("TEST 5: No-op change (already at latency 0)")
    print("="*70)

    success = change_operation_latency(graph, target_op.id, target_latency=0)

    if not success:
        print("ERROR: No-op change failed")
        return False

    print(f"\n✓ No-op change handled correctly")

    print("\n" + "="*70)
    print("ALL TESTS PASSED!")
    print("="*70)
    return True


if __name__ == "__main__":
    success = test_change_latency()
    exit(0 if success else 1)
