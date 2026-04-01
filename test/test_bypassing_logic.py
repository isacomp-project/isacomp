#!/usr/bin/env python3
"""
Test bypassing/forwarding logic implementation.

This verifies that the bypass resolver:
1. Creates bypass comparators
2. Creates forwarding muxes at read locations
3. Reroutes read values through mux
4. Adds forwarding paths from write stage to mux
5. Connects comparator to mux select
6. Handles multiple forwarding sources to same mux
"""

from core.resource_graph import ResourceGraph, Node, Edge
from opt.pipeline.hazard_resolution import (
    HazardAnalyzer, HazardResolver, DetectedHazard,
    HazardResolutionStrategy
)
import copy

def test_bypassing_creates_mux():
    """Test that bypassing creates a forwarding mux."""
    print("\n" + "="*60)
    print("TEST: Bypassing creates forwarding mux")
    print("="*60)

    # Create a simple graph with RF read and write
    graph = ResourceGraph()

    # Create RF resource
    rf = Node('rf', {'type': 'resource', 'name': 'rf'})
    graph.add_node(rf)

    # Create index nodes
    rs = Node('rs', {'type': 'variable', 'name': 'rs'})
    rd = Node('rd', {'type': 'variable', 'name': 'rd'})
    graph.add_node(rs)
    graph.add_node(rd)

    # Create RF read: rf[rs]_rd
    rf_rs_rd = Node('rf[rs]_rd', {'type': 'array_access', 'name': 'rf[rs]_rd'})
    graph.add_node(rf_rs_rd)
    graph.add_edge(Edge(rf, rf_rs_rd, data={'type': 'array_index'}))
    graph.add_edge(Edge(rs, rf_rs_rd, data={'type': 'array_index'}))

    # Create target of read
    rs_val = Node('rs_val', {'type': 'variable', 'name': 'rs_val'})
    graph.add_node(rs_val)
    graph.add_edge(Edge(rf_rs_rd, rs_val, data={'type': 'assignment'}))

    # Create RF write: rf[rd]_wr
    rf_rd_wr = Node('rf[rd]_wr', {'type': 'array_access', 'name': 'rf[rd]_wr'})
    graph.add_node(rf_rd_wr)
    graph.add_edge(Edge(rf, rf_rd_wr, data={'type': 'array_index'}))
    graph.add_edge(Edge(rd, rf_rd_wr, data={'type': 'array_index'}))

    # Create source of write
    result = Node('result', {'type': 'variable', 'name': 'result'})
    graph.add_node(result)
    graph.add_edge(Edge(result, rf_rd_wr, data={'type': 'assignment'}))

    # Add pipeline stages manually
    stage0 = Node('PIPE_stage0', {'type': 'pipeline_register', 'stage_name': 'stage0'})
    stage1 = Node('PIPE_stage1', {'type': 'pipeline_register', 'stage_name': 'stage1'})
    graph.add_node(stage0)
    graph.add_node(stage1)

    # Put read in stage 0, write in stage 1
    # (Add edges to simulate pipeline flow)
    graph.add_edge(Edge(rs, stage0, data={'type': 'pipeline_flow'}))
    graph.add_edge(Edge(stage0, result, data={'type': 'pipeline_flow'}))
    graph.add_edge(Edge(result, stage1, data={'type': 'pipeline_flow'}))

    print(f"Initial graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges")

    # Create a hazard
    hazard = DetectedHazard(
        hazard_type='RAW',
        resource='rf',
        write_stage=1,
        write_access_node=rf_rd_wr,
        write_index_node=rd,
        write_index_name='rd',
        read_stage=0,
        read_access_node=rf_rs_rd,
        read_index_node=rs,
        read_index_name='rs',
        resolution=HazardResolutionStrategy.BYPASS
    )

    print(f"\nHazard: {hazard}")
    print(f"Resolution: {hazard.resolution.value}")

    # Apply bypass resolution
    resolver = HazardResolver(graph)
    success = resolver.resolve_with_bypassing(hazard)

    print(f"\nBypass resolution: {'SUCCESS' if success else 'FAILED'}")
    print(f"Final graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges")

    # Verify mux was created
    mux_id = f"bypass_mux_rf_rs_s0"
    mux_node = graph.nodes.get(mux_id)

    if mux_node:
        print(f"\n✓ Forwarding mux created: {mux_id}")
        print(f"  Mux inputs: {mux_node.data.get('num_inputs', 'unknown')}")

        # Check mux connections
        incoming = len(mux_node.incoming_edges)
        outgoing = len(mux_node.outgoing_edges)
        print(f"  Incoming edges: {incoming} (should have normal path + forward path + select)")
        print(f"  Outgoing edges: {outgoing} (should have output to rs_val)")

        # List all incoming edges
        print(f"\n  Mux inputs:")
        for edge in mux_node.incoming_edges:
            edge_type = edge.data.get('type', 'unknown')
            mux_input = edge.data.get('mux_input', 'N/A')
            label = edge.data.get('label', 'N/A')
            print(f"    {edge.source.id:30s} -> mux (type={edge_type}, input={mux_input}, label={label})")

        # List outgoing edges
        print(f"\n  Mux outputs:")
        for edge in mux_node.outgoing_edges:
            edge_type = edge.data.get('type', 'unknown')
            print(f"    mux -> {edge.target.id:30s} (type={edge_type})")

    else:
        print(f"\n✗ Forwarding mux NOT created: {mux_id}")

    # Verify comparator was created
    bypass_comp_id = f"bypass_rf_rd_rs_s1_to_s0_cmp"
    bypass_comp = graph.nodes.get(bypass_comp_id)

    if bypass_comp:
        print(f"\n✓ Bypass comparator created: {bypass_comp_id}")
        print(f"  Operation: {bypass_comp.data.get('operation')}")

        # Check comparator connections
        print(f"  Inputs:")
        for edge in bypass_comp.incoming_edges:
            print(f"    {edge.source.id:30s} -> comparator")

        print(f"  Outputs:")
        for edge in bypass_comp.outgoing_edges:
            edge_type = edge.data.get('type', 'unknown')
            control_type = edge.data.get('control_type', 'N/A')
            print(f"    comparator -> {edge.target.id:30s} (type={edge_type}, control={control_type})")

    else:
        print(f"\n✗ Bypass comparator NOT created: {bypass_comp_id}")

    # Verify forwarding path exists
    forwarding_edges = [e for e in graph.edges.values()
                       if e.data.get('label', '').startswith('forward_s')]

    if forwarding_edges:
        print(f"\n✓ Forwarding paths created: {len(forwarding_edges)}")
        for edge in forwarding_edges:
            label = edge.data.get('label', 'unknown')
            print(f"  {edge.source.id:30s} -> {edge.target.id:30s} ({label})")
    else:
        print(f"\n✗ No forwarding paths created")

    return success


def test_multiple_forwarding_sources():
    """Test that multiple forwarding sources to same mux work correctly."""
    print("\n" + "="*60)
    print("TEST: Multiple forwarding sources to same mux")
    print("="*60)

    # This tests the scenario where:
    # - Stage 1 writes rf[rd_1]
    # - Stage 2 writes rf[rd_2]
    # - Stage 0 reads rf[rs]
    # - Both need to forward to the same read location

    # For simplicity, we'll create two hazards and resolve both with bypassing
    # The second should add to the existing mux

    graph = ResourceGraph()

    # Create RF and indices
    rf = Node('rf', {'type': 'resource', 'name': 'rf'})
    rs = Node('rs', {'type': 'variable', 'name': 'rs'})
    rd = Node('rd', {'type': 'variable', 'name': 'rd'})
    graph.add_node(rf)
    graph.add_node(rs)
    graph.add_node(rd)

    # Read location
    rf_rs_rd = Node('rf[rs]_rd', {'type': 'array_access'})
    rs_val = Node('rs_val', {'type': 'variable'})
    graph.add_node(rf_rs_rd)
    graph.add_node(rs_val)
    graph.add_edge(Edge(rf, rf_rs_rd, data={'type': 'array_index'}))
    graph.add_edge(Edge(rs, rf_rs_rd, data={'type': 'array_index'}))
    graph.add_edge(Edge(rf_rs_rd, rs_val, data={'type': 'assignment'}))

    # Write location 1 (stage 1)
    rf_rd_wr_1 = Node('rf[rd]_wr_s1', {'type': 'array_access'})
    result_1 = Node('result_s1', {'type': 'variable'})
    graph.add_node(rf_rd_wr_1)
    graph.add_node(result_1)
    graph.add_edge(Edge(rf, rf_rd_wr_1, data={'type': 'array_index'}))
    graph.add_edge(Edge(rd, rf_rd_wr_1, data={'type': 'array_index'}))
    graph.add_edge(Edge(result_1, rf_rd_wr_1, data={'type': 'assignment'}))

    # Write location 2 (stage 2)
    rf_rd_wr_2 = Node('rf[rd]_wr_s2', {'type': 'array_access'})
    result_2 = Node('result_s2', {'type': 'variable'})
    graph.add_node(rf_rd_wr_2)
    graph.add_node(result_2)
    graph.add_edge(Edge(rf, rf_rd_wr_2, data={'type': 'array_index'}))
    graph.add_edge(Edge(rd, rf_rd_wr_2, data={'type': 'array_index'}))
    graph.add_edge(Edge(result_2, rf_rd_wr_2, data={'type': 'assignment'}))

    print(f"Initial graph: {len(graph.nodes)} nodes")

    # Create two hazards
    hazard1 = DetectedHazard(
        hazard_type='RAW', resource='rf',
        write_stage=1, write_access_node=rf_rd_wr_1,
        write_index_node=rd, write_index_name='rd',
        read_stage=0, read_access_node=rf_rs_rd,
        read_index_node=rs, read_index_name='rs',
        resolution=HazardResolutionStrategy.BYPASS
    )

    hazard2 = DetectedHazard(
        hazard_type='RAW', resource='rf',
        write_stage=2, write_access_node=rf_rd_wr_2,
        write_index_node=rd, write_index_name='rd',
        read_stage=0, read_access_node=rf_rs_rd,
        read_index_node=rs, read_index_name='rs',
        resolution=HazardResolutionStrategy.BYPASS
    )

    # Resolve first hazard
    resolver = HazardResolver(graph)
    success1 = resolver.resolve_with_bypassing(hazard1)
    print(f"\nFirst bypass: {'SUCCESS' if success1 else 'FAILED'}")

    mux_id = "bypass_mux_rf_rs_s0"
    mux = graph.nodes.get(mux_id)

    if mux:
        inputs_after_first = mux.data.get('num_inputs', 0)
        print(f"Mux inputs after first bypass: {inputs_after_first}")

        # Resolve second hazard (should add to existing mux)
        success2 = resolver.resolve_with_bypassing(hazard2)
        print(f"Second bypass: {'SUCCESS' if success2 else 'FAILED'}")

        inputs_after_second = mux.data.get('num_inputs', 0)
        print(f"Mux inputs after second bypass: {inputs_after_second}")

        if inputs_after_second > inputs_after_first:
            print(f"\n✓ Multiple forwarding sources handled correctly")
            print(f"  Mux grew from {inputs_after_first} to {inputs_after_second} inputs")
        else:
            print(f"\n✗ Mux did not grow as expected")

    else:
        print(f"\n✗ Mux not found")


def run_all_tests():
    """Run all bypassing logic tests."""
    print("="*60)
    print("BYPASSING LOGIC TEST SUITE")
    print("="*60)

    test1_passed = test_bypassing_creates_mux()
    test_multiple_forwarding_sources()

    print("\n" + "="*60)
    print("TEST SUITE COMPLETE")
    print("="*60)


if __name__ == '__main__':
    run_all_tests()
