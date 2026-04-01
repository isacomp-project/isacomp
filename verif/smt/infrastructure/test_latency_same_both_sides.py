#!/usr/bin/env python3
"""Test that SMT verification works when both graphs have the same latency."""

import sys
import copy
from core.resource_graph import ResourceGraph
from opt.temporal.multi_cycle_operations import apply_multi_cycle_operations, OperationLatencySpec
from verif.smt.smt_verification import verify_multicycle_optimization


def main():
    # Create two identical graphs
    graph1 = ResourceGraph.from_isa_file('isa/riscv32/add.isa')
    graph2 = copy.deepcopy(graph1)

    # Apply same latency to both
    op = [n for n in graph1.nodes.values() if n.data.get('type') == 'operation'][0]
    spec = OperationLatencySpec(op.id, 3)

    print("Applying 3-cycle latency to both graphs...")
    apply_multi_cycle_operations(graph1, [spec])
    apply_multi_cycle_operations(graph2, [copy.deepcopy(spec)])

    print(f"Graph1 op latency: {graph1.nodes[op.id].latency}")
    print(f"Graph2 op latency: {graph2.nodes[op.id].latency}")

    print("\nVerifying equivalence...")
    is_equiv, details = verify_multicycle_optimization(
        graph1,
        graph2,
        isa_file_path='isa/riscv32/add.isa',
        solver='z3'
    )

    if is_equiv:
        print("✓ PASSED: Both graphs with same latency are equivalent")
        return 0
    else:
        print("✗ FAILED: Graphs with same latency are not equivalent")
        print(f"Reason: {details[:500]}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
