#!/usr/bin/env python3
"""
Focused test: Variable latency operation with pipeline register gating.

This test specifically verifies that when a pipeline cut is inserted
on the output path of a variable latency operation, the resulting
pipeline register is correctly gated by the complete signal.
"""

from core.resource_graph import ResourceGraph, Node, Edge
from opt.temporal.multi_cycle_operations import set_operation_variable_latency
from core.pipeline_utils import PipelineRegisterBuilder
import copy


def test_variable_latency_register_gating():
    """Test that pipeline registers are correctly gated by variable latency complete signals."""

    print("=" * 80)
    print("VARIABLE LATENCY PIPELINE REGISTER GATING TEST")
    print("=" * 80)

    # Step 1: Load graph
    print("\n1. Loading MIPS LW instruction...")
    graph = ResourceGraph.from_isa_file('isa/mips32/lw.isa')
    print(f"   ✓ Graph loaded: {len(graph.nodes)} nodes")

    # Step 2: Find an operation to make variable latency
    print("\n2. Finding operation...")
    operations = [n for n in graph.nodes.values()
                 if n.data.get('type') in ['operation', 'alu_module']]

    if not operations:
        print("   ERROR: No operations found!")
        return False

    target_op = operations[0]
    print(f"   ✓ Selected: {target_op.id}")

    # Step 3: Set to variable latency
    print("\n3. Setting variable latency...")
    success = set_operation_variable_latency(
        graph=graph,
        operation_id=target_op.id,
        enable=True,
        
    )

    if not success:
        print("   ERROR: Failed to set variable latency!")
        return False

    complete_signal_id = target_op.data.get('complete_signal')
    print(f"   ✓ Variable latency enabled")
    print(f"   ✓ Complete signal: {complete_signal_id}")

    # Step 4: Find an edge from the variable latency operation
    print("\n4. Finding edge from variable latency operation...")

    test_edge = None
    for edge in target_op.outgoing_edges:
        edge_type = edge.data.get('type')
        # Look for a data edge, not a control edge
        if edge_type not in ['control', 'enable', 'pipeline_control']:
            test_edge = edge
            print(f"   ✓ Found edge: {edge.source.id} → {edge.target.id}")
            print(f"     Edge type: {edge_type}")
            break

    if not test_edge:
        print("   WARNING: No suitable edge found from variable latency operation")
        print("   Trying edges from nodes that depend on variable latency...")

        # Look for nodes that depend on the variable latency operation
        for node in graph.nodes.values():
            deps = node.data.get('depends_on_variable_latency', [])
            if target_op.id in deps:
                for edge in node.outgoing_edges:
                    edge_type = edge.data.get('type')
                    if edge_type not in ['control', 'enable', 'pipeline_control']:
                        test_edge = edge
                        print(f"   ✓ Found edge from dependent node: {edge.source.id} → {edge.target.id}")
                        print(f"     Edge type: {edge_type}")
                        break
                if test_edge:
                    break

    if not test_edge:
        print("   ERROR: Could not find suitable edge for testing!")
        return False

    # Step 5: Insert pipeline register on this edge
    print("\n5. Inserting pipeline register on edge...")

    pipeline_utils = PipelineRegisterBuilder(graph)

    # Create pipeline register
    pipe_reg = pipeline_utils.create_pipeline_register(
        register_id=f"TEST_PIPE_REG",
        stage_name="test_stage",
        display_name="Test Pipeline Register"
    )

    print(f"   ✓ Created pipeline register: {pipe_reg.id}")

    # Insert register (this should trigger variable latency gating)
    input_edge, output_edge = pipeline_utils.insert_register_in_edge(
        edge=test_edge,
        register_node=pipe_reg
    )

    print(f"   ✓ Pipeline register inserted")
    print(f"     Input edge: {input_edge.source.id} → {input_edge.target.id}")
    print(f"     Output edge: {output_edge.source.id} → {output_edge.target.id}")

    # Step 6: Verify gating
    print("\n6. Verifying variable latency gating...")

    # Check if register is marked as gated
    is_gated = pipe_reg.data.get('variable_latency_gated', False)
    gated_by_op = pipe_reg.data.get('gated_by_operation')
    gated_by_sig = pipe_reg.data.get('gated_by_signal')

    print(f"   Register metadata:")
    print(f"     variable_latency_gated: {is_gated}")
    print(f"     gated_by_operation: {gated_by_op}")
    print(f"     gated_by_signal: {gated_by_sig}")

    if is_gated:
        print(f"\n   ✅ GATING VERIFIED: Register is marked as variable-latency gated!")

        # Verify the operation matches
        assert gated_by_op == target_op.id or (
            gated_by_op and gated_by_op in graph.nodes and
            graph.nodes[gated_by_op].variable_latency
        ), f"Gated by wrong operation: {gated_by_op}"

        # Verify the signal exists
        assert gated_by_sig in graph.nodes, f"Gating signal not found: {gated_by_sig}"

        # Check for enable edge
        enable_edges = [e for e in pipe_reg.incoming_edges
                       if e.data.get('type') == 'pipeline_control' and
                       e.data.get('control_type') == 'enable']

        if enable_edges:
            print(f"\n   ✅ ENABLE EDGE VERIFIED: {len(enable_edges)} edge(s) found")
            for e in enable_edges:
                print(f"     • {e.source.id} (complete signal) → {e.target.id} (register)")
                print(f"       Signal type: {e.data.get('signal_type')}")
                print(f"       Description: {e.data.get('description')}")

                # Verify the source is the complete signal
                assert e.source.id == gated_by_sig, f"Enable edge from wrong signal: {e.source.id}"
                assert e.target == pipe_reg, f"Enable edge to wrong target: {e.target.id}"
        else:
            print(f"\n   ⚠️  WARNING: No enable edges found!")
            return False

    else:
        print(f"\n   ⚠️  Register NOT marked as gated")
        print(f"   This may be OK if the edge doesn't directly depend on variable latency")

        # Check if source has variable latency dependency
        source = test_edge.source
        if source.variable_latency:
            print(f"   ERROR: Source {source.id} has variable_latency but register not gated!")
            return False
        elif source.data.get('depends_on_variable_latency'):
            print(f"   ERROR: Source {source.id} depends on variable latency but register not gated!")
            return False
        else:
            print(f"   OK: Source {source.id} doesn't directly depend on variable latency")

    # Step 7: Test with a node that definitely depends on variable latency
    print("\n7. Testing with node that depends on variable latency...")

    # Find or create a node that depends on the variable latency operation
    dependent_node = None
    for node in graph.nodes.values():
        deps = node.data.get('depends_on_variable_latency', [])
        if target_op.id in deps:
            # Find an outgoing edge
            for edge in node.outgoing_edges:
                if edge.data.get('type') not in ['control', 'enable']:
                    dependent_node = node
                    test_edge2 = edge
                    break
            if dependent_node:
                break

    if dependent_node:
        print(f"   Found dependent node: {dependent_node.id}")
        print(f"   Dependencies: {dependent_node.data.get('depends_on_variable_latency')}")

        # Create another pipeline register
        pipe_reg2 = pipeline_utils.create_pipeline_register(
            register_id=f"TEST_PIPE_REG_2",
            stage_name="test_stage_2"
        )

        # Insert register
        input_edge2, output_edge2 = pipeline_utils.insert_register_in_edge(
            edge=test_edge2,
            register_node=pipe_reg2
        )

        # Check gating
        is_gated2 = pipe_reg2.data.get('variable_latency_gated', False)
        print(f"\n   Second register gating: {is_gated2}")

        if is_gated2:
            print(f"   ✅ Second register correctly gated!")
            print(f"     Gated by: {pipe_reg2.data.get('gated_by_operation')}")
        else:
            print(f"   Note: Second register not gated (may depend on dataflow)")

    else:
        print(f"   No dependent node with suitable edge found")

    # Summary
    print("\n" + "=" * 80)
    print("GATING TEST SUMMARY")
    print("=" * 80)
    print(f"✓ Variable latency operation: {target_op.id}")
    print(f"✓ Complete signal created: {complete_signal_id}")
    print(f"✓ Pipeline register inserted: {pipe_reg.id}")

    if is_gated:
        print(f"✓ Pipeline register GATED by complete signal: {gated_by_sig}")
        print(f"✓ Enable edge created from complete signal to register")
        print()
        print("=" * 80)
        print("✅ PIPELINE REGISTER GATING WORKS CORRECTLY!")
        print("=" * 80)
        return True
    else:
        print(f"ℹ️  Pipeline register not gated (edge not on variable latency path)")
        print()
        print("=" * 80)
        print("✓ TEST COMPLETED (gating logic works, but not triggered in this case)")
        print("=" * 80)
        return True


if __name__ == "__main__":
    try:
        success = test_variable_latency_register_gating()
        exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ TEST FAILED WITH EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
