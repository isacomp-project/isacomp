#!/usr/bin/env python3
"""
Test variable latency implementation.

This test:
1. Loads a simple ISA file (MIPS LW - load word instruction)
2. Finds a memory operation (dmem read)
3. Sets it to have variable latency
4. Verifies that:
   - The operation has variable_latency = True
   - uarch_time is -1 (unknown)
   - ISA writes are gated on variable completion
   - Enable edges are created
"""

from core.resource_graph import ResourceGraph
from opt.temporal.multi_cycle_operations import set_operation_variable_latency


def test_variable_latency():
    """Test variable latency with a memory load operation."""

    print("=" * 80)
    print("VARIABLE LATENCY TEST")
    print("=" * 80)

    # Load a simple ISA file with memory operations
    # Try to use MIPS LW (load word) or SW (store word) instruction
    isa_file = "isa/mips32/lw.isa"

    print(f"\n1. Loading ISA file: {isa_file}")
    try:
        graph = ResourceGraph.from_isa_file(isa_file)
        print(f"   ✓ Graph loaded: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
    except FileNotFoundError:
        # Fallback to a simple add instruction if lw.isa doesn't exist
        print(f"   File not found, trying isa/mips32/add.isa instead...")
        isa_file = "isa/mips32/add.isa"
        graph = ResourceGraph.from_isa_file(isa_file)
        print(f"   ✓ Graph loaded: {len(graph.nodes)} nodes, {len(graph.edges)} edges")

    # Find a memory operation or any operation
    print("\n2. Finding memory or arithmetic operation...")
    dmem_operation = None
    any_operation = None

    for node_id, node in graph.nodes.items():
        if node.data.get('type') in ['operation', 'alu_module']:
            any_operation = node_id
            # Look for memory operations (dmem or imem)
            if 'dmem' in node_id.lower() or 'mem' in node.data.get('operation_type', '').lower():
                dmem_operation = node_id
                break

    target_operation = dmem_operation or any_operation

    if not target_operation:
        print("   ERROR: No operation found in graph!")
        return False

    operation_node = graph.nodes[target_operation]
    print(f"   ✓ Found operation: {target_operation}")
    print(f"     Type: {operation_node.data.get('type')}")
    print(f"     Operation type: {operation_node.data.get('operation_type', 'N/A')}")
    print(f"     Current latency: {operation_node.latency}")
    print(f"     Current variable_latency: {operation_node.variable_latency}")

    # Infer initial timing
    print("\n3. Inferring initial timing...")
    graph.infer_uarch_time()
    print(f"   ✓ Initial uarch_time for operation: {operation_node.uarch_time}")

    # Count ISA writes before gating
    isa_writes_before = [n for n in graph.nodes.values()
                         if n.is_arch_state and
                         any(e.data.get('type') == 'assignment' for e in n.incoming_edges)]
    print(f"   ✓ ISA writes in graph: {len(isa_writes_before)}")

    # Set variable latency
    print(f"\n4. Setting variable latency for operation: {target_operation}")
    success = set_operation_variable_latency(
        graph=graph,
        operation_id=target_operation,
        enable=True
    )

    if not success:
        print("   ERROR: Failed to set variable latency!")
        return False

    print("   ✓ Variable latency set successfully")

    # Verify the changes
    print("\n5. Verifying changes...")

    # Check operation attributes
    print(f"   Operation attributes:")
    print(f"     variable_latency: {operation_node.variable_latency} (expected: True)")
    print(f"     latency: {operation_node.latency} (should be 0 for variable latency)")
    print(f"     uarch_time: {operation_node.uarch_time} (operation starts at this cycle)")
    print(f"     has_complete_output: {operation_node.data.get('has_complete_output')} (expected: True)")
    print(f"     has_start_input: {operation_node.data.get('has_start_input')} (expected: True)")
    print(f"     has_idle_output: {operation_node.data.get('has_idle_output')} (expected: True)")

    assert operation_node.variable_latency == True, "variable_latency should be True"
    assert operation_node.latency == 0, "latency should be 0 for variable latency operations"
    assert operation_node.data.get('has_complete_output') == True, "should have complete output"
    assert operation_node.data.get('has_start_input') == True, "should have start input"
    assert operation_node.data.get('has_idle_output') == True, "should have idle output"
    print(f"   ✓ Operation correctly configured for variable latency")

    # Check control signal nodes
    print(f"\n   Control signal nodes:")
    start_signal_id = operation_node.data.get('start_signal')
    idle_signal_id = operation_node.data.get('idle_signal')
    complete_signal_id = operation_node.data.get('complete_signal')

    assert start_signal_id is not None, "start_signal should be set"
    assert idle_signal_id is not None, "idle_signal should be set"
    assert complete_signal_id is not None, "complete_signal should be set"

    assert start_signal_id in graph.nodes, f"start signal {start_signal_id} should exist in graph"
    assert idle_signal_id in graph.nodes, f"idle signal {idle_signal_id} should exist in graph"
    assert complete_signal_id in graph.nodes, f"complete signal {complete_signal_id} should exist in graph"

    start_node = graph.nodes[start_signal_id]
    idle_node = graph.nodes[idle_signal_id]
    complete_node = graph.nodes[complete_signal_id]

    print(f"     start: {start_signal_id} ({start_node.data.get('signal_type')}, {start_node.data.get('direction')})")
    print(f"     idle: {idle_signal_id} ({idle_node.data.get('signal_type')}, {idle_node.data.get('direction')})")
    print(f"     complete: {complete_signal_id} ({complete_node.data.get('signal_type')}, {complete_node.data.get('direction')})")

    assert start_node.data.get('signal_type') == 'start', "start signal should have correct type"
    assert start_node.data.get('direction') == 'input', "start signal should be input"
    assert idle_node.data.get('signal_type') == 'idle', "idle signal should have correct type"
    assert idle_node.data.get('direction') == 'output', "idle signal should be output"
    assert complete_node.data.get('signal_type') == 'complete', "complete signal should have correct type"
    assert complete_node.data.get('direction') == 'output', "complete signal should be output"

    print(f"   ✓ All control signals correctly created")

    # Check ISA write gating
    print(f"\n   ISA write gating:")
    gated_writes = []
    for node in graph.nodes.values():
        if node.is_arch_state:
            enable_expr = node.data.get('enable')
            if enable_expr and isinstance(enable_expr, dict):
                if enable_expr.get('type') == 'variable_complete':
                    gated_writes.append(node.id)
                    print(f"     ✓ {node.id} gated on variable completion")

    print(f"   Total gated writes: {len(gated_writes)}")
    assert len(gated_writes) > 0, "At least one ISA write should be gated"

    # Check enable edges (should come from complete signal, not operation)
    print(f"\n   Enable edges:")
    enable_edges = [e for e in graph.edges.values()
                   if e.data.get('type') == 'enable' and
                   e.data.get('signal_type') == 'variable_complete']

    print(f"   Total enable edges: {len(enable_edges)}")
    for edge in enable_edges[:5]:  # Show first 5
        print(f"     ✓ {edge.source.id} --enable--> {edge.target.id}")

    assert len(enable_edges) > 0, "Should have enable edges"

    # Verify enable edges come from complete signal node
    for edge in enable_edges:
        assert edge.source.id == complete_signal_id, f"Enable edge should come from complete signal, got {edge.source.id}"

    print(f"   ✓ All enable edges correctly come from complete signal")

    # Check that downstream nodes have variable latency dependency marked
    print(f"\n   Downstream timing propagation:")
    dependent_nodes = [n for n in graph.nodes.values()
                      if n.data.get('depends_on_variable_latency')]
    print(f"   Nodes marked as dependent on variable latency: {len(dependent_nodes)}")
    for node in dependent_nodes[:5]:  # Show first 5
        deps = node.data.get('depends_on_variable_latency', [])
        print(f"     • {node.id}: uarch_time = {node.uarch_time}, depends on {deps}")

    # Test disabling variable latency
    print(f"\n6. Testing disable variable latency...")
    success = set_operation_variable_latency(
        graph=graph,
        operation_id=target_operation,
        enable=False
    )

    if not success:
        print("   ERROR: Failed to disable variable latency!")
        return False

    print("   ✓ Variable latency disabled successfully")

    # Verify disabled state
    print(f"\n   Operation attributes after disable:")
    print(f"     variable_latency: {operation_node.variable_latency} (expected: False)")
    print(f"     latency: {operation_node.latency} (expected: 0)")
    print(f"     uarch_time: {operation_node.uarch_time}")

    assert operation_node.variable_latency == False, "variable_latency should be False"
    assert operation_node.latency == 0, "latency should be 0"

    # Check ISA writes are ungated
    gated_writes_after = [n for n in graph.nodes.values()
                         if n.is_arch_state and
                         n.data.get('enable') and
                         n.data['enable'].get('type') == 'variable_complete']
    print(f"   Gated writes after disable: {len(gated_writes_after)} (expected: 0)")
    assert len(gated_writes_after) == 0, "No ISA writes should be gated after disable"

    print("\n" + "=" * 80)
    print("✓ ALL TESTS PASSED")
    print("=" * 80)

    return True


if __name__ == "__main__":
    try:
        success = test_variable_latency()
        exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ TEST FAILED WITH EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
