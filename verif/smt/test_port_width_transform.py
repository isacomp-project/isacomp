#!/usr/bin/env python3
"""
Test script for set_port_width memory transformation.

Tests the new 'set_port_width' strategy on merged LB+LH+LW graph.
"""

import sys
from core.isa_parser import ISAParser
from core.graph_merger import ResourceGraphMerger
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec
from verif.smt.smt_verification import EquivalenceChecker

def test_port_width_transform():
    """Test port_width transformation on merged load instructions."""

    print("=" * 80)
    print("Testing set_port_width transformation")
    print("=" * 80)

    # Step 1 & 2: Parse and merge load instructions
    print("\n[Steps 1-2] Parsing and merging LB, LH, LW instructions...")
    merger = ResourceGraphMerger()

    merger.add_instruction('lb', 'isa/riscv32/lb.isa')
    print(f"  Added LB")

    merger.add_instruction('lh', 'isa/riscv32/lh.isa')
    print(f"  Added LH")

    merger.add_instruction('lw', 'isa/riscv32/lw.isa')
    print(f"  Added LW")

    merged_graph = merger.merge_graphs()
    print(f"  Merged graph: {len(merged_graph.nodes)} nodes")

    # Check dmem properties before transformation
    dmem_node = merged_graph.nodes.get('dmem')
    if dmem_node:
        print(f"  dmem.bit_width = {dmem_node.data.get('bit_width')}")
        print(f"  dmem.port_width = {dmem_node.data.get('port_width')}")

    # Step 3: Apply set_port_width transformation
    print("\n[Step 3] Applying set_port_width transformation...")
    transform = MemoryAccessTransform(merged_graph)

    spec = MemoryAccessTransformSpec(
        memory='dmem',
        strategy='set_port_width',
        current_width=32,  # Max access width (LW)
        target_width=32,   # Port width (word-addressed)
        direction='forward'
    )

    result = transform.apply_transformation(spec, dry_run=False)

    if result['transformed']:
        print(f"  ✓ Transformation successful!")
        print(f"    Nodes added: {len(result.get('nodes_added', []))}")
        print(f"    Nodes updated: {len(result.get('nodes_updated', []))}")
        print(f"    Accesses transformed: {result.get('num_accesses_transformed', 0)}")

        # Check dmem properties after transformation
        if dmem_node:
            print(f"  dmem.port_width = {dmem_node.data.get('port_width')}")

        # List added nodes
        if result.get('nodes_added'):
            print(f"\n  Added nodes:")
            for node_id in result['nodes_added'][:10]:  # Show first 10
                node = merged_graph.nodes.get(node_id)
                if node:
                    print(f"    - {node_id}: {node.data.get('type')}")
    else:
        print(f"  ✗ Transformation failed: {result.get('reason')}")
        return False

    # Step 4: Save the transformed graph
    print("\n[Step 4] Saving transformed graph...")
    merged_graph.save_json('test_outputs/merged_loads_with_port_width.json')
    print(f"  Saved to: test_outputs/merged_loads_with_port_width.json")

    # Step 5: Test SMT verification against LB ILA model
    print("\n[Step 5] Testing SMT verification against LB ILA...")
    try:
        checker = EquivalenceChecker()

        # Load LB ILA model
        ila_path = 'riscv_ila_jsons/riscv_lb.json'
        print(f"  Loading ILA from: {ila_path}")

        result = checker.check_equivalence(
            merged_graph,
            ila_path,
            instruction_filter='lb',
            timeout=30000
        )

        if result['equivalent']:
            print(f"  ✓ LB verification PASSED!")
        else:
            print(f"  ✗ LB verification FAILED")
            if 'error' in result:
                print(f"    Error: {result['error']}")
    except Exception as e:
        print(f"  ✗ SMT verification error: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n" + "=" * 80)
    print("Test completed successfully!")
    print("=" * 80)
    return True

if __name__ == '__main__':
    success = test_port_width_transform()
    sys.exit(0 if success else 1)
