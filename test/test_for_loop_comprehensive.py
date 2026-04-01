#!/usr/bin/env python3
"""Comprehensive test for for loop unrolling functionality"""

from core.isa_parser import ISAParser

def test_basic_for_loop():
    """Test basic for loop with simple iteration"""
    isa_code = """
isa_state pc[31:0];
isa_state rf[31:0][4:0];
var res[31:0];
var temp[31:0];

for(i;0;<4;+1) {
  temp = i;
}
"""
    parser = ISAParser()
    graph = parser.parse(isa_code)

    # Should have 4 assignments of temp (one per iteration)
    temp_assignments = [e for e in graph.edges.values()
                       if e.data and e.data.get('type') == 'assignment'
                       and e.target.id == 'temp']

    print(f"Test 1: Basic for loop")
    print(f"  Created {len(temp_assignments)} assignments (expected 4)")
    assert len(temp_assignments) == 4, f"Expected 4 assignments, got {len(temp_assignments)}"

    # Check that the assignments have different literal values
    values = []
    for edge in temp_assignments:
        src = edge.source
        if src.data and src.data.get('type') == 'literal':
            values.append(src.data['value'])

    print(f"  Literal values assigned: {sorted(values)}")
    assert sorted(values) == [0, 1, 2, 3], f"Expected [0,1,2,3], got {sorted(values)}"
    print("  ✓ PASSED\n")

def test_for_loop_with_expressions():
    """Test for loop with expressions involving loop variable"""
    isa_code = """
isa_state rf[31:0][4:0];
var res[31:0];

for(i;0;<4;+1) {
  res[((i+1)*8)-1:i*8] = i;
}
"""
    parser = ISAParser()
    graph = parser.parse(isa_code)

    print(f"Test 2: For loop with bit slice expressions")

    # Check for the correct bit slices
    bit_slices = [name for name in graph.nodes.keys() if 'res[' in name and ':' in name]
    print(f"  Created bit slices: {sorted(bit_slices)}")

    expected = ['res[15:8]', 'res[23:16]', 'res[31:24]', 'res[7:0]']
    assert sorted(bit_slices) == expected, f"Expected {expected}, got {sorted(bit_slices)}"
    print("  ✓ PASSED\n")

def test_for_loop_decrement():
    """Test for loop with decrement"""
    isa_code = """
var res[31:0];

for(i;10;>5;-1) {
  res = i;
}
"""
    parser = ISAParser()
    graph = parser.parse(isa_code)

    print(f"Test 3: For loop with decrement")

    # Should have 5 assignments (10, 9, 8, 7, 6)
    res_assignments = [e for e in graph.edges.values()
                      if e.data and e.data.get('type') == 'assignment'
                      and e.target.id == 'res']

    print(f"  Created {len(res_assignments)} assignments (expected 5)")
    assert len(res_assignments) == 5, f"Expected 5 assignments, got {len(res_assignments)}"

    values = []
    for edge in res_assignments:
        src = edge.source
        if src.data and src.data.get('type') == 'literal':
            values.append(src.data['value'])

    print(f"  Literal values assigned: {sorted(values, reverse=True)}")
    assert sorted(values, reverse=True) == [10, 9, 8, 7, 6], f"Expected [10,9,8,7,6], got {sorted(values, reverse=True)}"
    print("  ✓ PASSED\n")

if __name__ == '__main__':
    print("=" * 60)
    print("FOR LOOP UNROLLING COMPREHENSIVE TESTS")
    print("=" * 60 + "\n")

    test_basic_for_loop()
    test_for_loop_with_expressions()
    test_for_loop_decrement()

    print("=" * 60)
    print("ALL TESTS PASSED!")
    print("=" * 60)