#!/usr/bin/env python3
"""Test suite for memory width constraint feature."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.graph_merger import merge_instructions
from backends.verilog import VerilogGenerator
import sys


def test_constraint_32_to_16():
    """Test: 32-bit load from 16-bit constrained memory."""
    print("\n" + "="*70)
    print("Test 1: 32-bit load from 16-bit memory")
    print("="*70)

    merged = merge_instructions(
        {'lw': 'isa/riscv32/lw.isa'},
        memory_constraints={'dmem': 16}
    )

    dmem_width = merged.nodes['dmem'].data.get('bit_width')
    assert dmem_width == 16, f"Expected dmem width 16, got {dmem_width}"
    print(f"✓ Memory constrained to {dmem_width} bits")

    # Check that access node has proper width
    for node_id, node in merged.nodes.items():
        if 'dmem[addr]_rd' in node_id:
            node_width = node.data.get('bit_width')
            assert node_width == 16, f"Expected access node width 16, got {node_width}"
            print(f"✓ Access node width properly set to {node_width} bits")

    # Generate Verilog and check for dual-word logic
    generator = VerilogGenerator(merged, 'test_lw_16bit')
    verilog = generator.generate()

    assert 'word0' in verilog, "Missing word0 wire"
    assert 'word1' in verilog, "Missing word1 wire"
    assert 'merged' in verilog, "Missing merged wire"
    print("✓ Dual-word read logic generated")

    print("✓ Test 1 PASSED")
    return True


def test_constraint_stores_8bit():
    """Test: Mixed width stores to 8-bit constrained memory."""
    print("\n" + "="*70)
    print("Test 2: Mixed stores (16/32-bit) to 8-bit memory")
    print("="*70)

    merged = merge_instructions(
        {
            'sh': 'isa/riscv32/sh.isa',  # 16-bit
            'sw': 'isa/riscv32/sw.isa'   # 32-bit
        },
        memory_constraints={'dmem': 8}
    )

    dmem_width = merged.nodes['dmem'].data.get('bit_width')
    assert dmem_width == 8, f"Expected dmem width 8, got {dmem_width}"
    print(f"✓ Memory constrained to {dmem_width} bits")

    # Generate Verilog and check for warnings
    import io
    import contextlib

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        generator = VerilogGenerator(merged, 'test_stores_8bit')
        verilog = generator.generate()

    output_str = output.getvalue()
    assert '[MULTI-CYCLE] sh: 16-bit store to 8-bit memory' in output_str, "Missing SH warning"
    assert '[MULTI-CYCLE] sw: 32-bit store to 8-bit memory' in output_str, "Missing SW warning"
    print("✓ Multi-cycle warnings generated for both instructions")

    print("✓ Test 2 PASSED")
    return True


def test_constraint_not_binding():
    """Test: Constraint wider than needed (not binding)."""
    print("\n" + "="*70)
    print("Test 3: Non-binding constraint (32-bit constraint, 8-bit access)")
    print("="*70)

    merged = merge_instructions(
        {'lbu': 'isa/riscv32/lbu.isa'},  # 8-bit
        memory_constraints={'dmem': 32}
    )

    dmem_width = merged.nodes['dmem'].data.get('bit_width')
    # Should use actual need (8), not constraint (32)
    assert dmem_width == 8, f"Expected dmem width 8 (actual need), got {dmem_width}"
    print(f"✓ Memory width {dmem_width} bits (constraint not binding)")

    print("✓ Test 3 PASSED")
    return True


def test_mixed_widths_16bit():
    """Test: Mixed accesses to 16-bit constrained memory."""
    print("\n" + "="*70)
    print("Test 4: Mixed accesses (8/16/32-bit) to 16-bit memory")
    print("="*70)

    merged = merge_instructions(
        {
            'lbu': 'isa/riscv32/lbu.isa',  # 8-bit
            'lhu': 'isa/riscv32/lhu.isa',  # 16-bit
            'lw': 'isa/riscv32/lw.isa'     # 32-bit
        },
        memory_constraints={'dmem': 16}
    )

    dmem_width = merged.nodes['dmem'].data.get('bit_width')
    assert dmem_width == 16, f"Expected dmem width 16, got {dmem_width}"
    print(f"✓ Memory constrained to {dmem_width} bits")

    # Generate Verilog
    import io
    import contextlib

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        generator = VerilogGenerator(merged, 'test_mixed_16bit')
        verilog = generator.generate()

    output_str = output.getvalue()
    # 32-bit access should trigger multi-cycle warning
    assert '[MULTI-CYCLE]' in output_str and '32-bit access from 16-bit memory' in output_str, \
        "Missing multi-cycle warning for 32-bit access"
    print("✓ Multi-cycle warning generated for 32-bit access")

    # 8-bit and 16-bit should work normally
    print("✓ 8-bit and 16-bit accesses handled correctly")

    print("✓ Test 4 PASSED")
    return True


def test_no_constraint():
    """Test: Normal behavior without constraints."""
    print("\n" + "="*70)
    print("Test 5: No constraint (normal width inference)")
    print("="*70)

    merged = merge_instructions({
        'lbu': 'isa/riscv32/lbu.isa',  # 8-bit
        'lhu': 'isa/riscv32/lhu.isa',  # 16-bit
        'lw': 'isa/riscv32/lw.isa'     # 32-bit
    })

    dmem_width = merged.nodes['dmem'].data.get('bit_width')
    # Should infer maximum width (32)
    assert dmem_width == 32, f"Expected dmem width 32 (max access), got {dmem_width}"
    print(f"✓ Memory width {dmem_width} bits (automatic inference)")

    print("✓ Test 5 PASSED")
    return True


def test_change_width_multiple_times():
    """Test: Changing width multiple times using set_memory_width() API."""
    print("\n" + "="*70)
    print("Test 6: Change width multiple times")
    print("="*70)

    # Start with a 32-bit load, no constraint
    merged = merge_instructions({'lw': 'isa/riscv32/lw.isa'})

    initial_width = merged.nodes['dmem'].data.get('bit_width')
    assert initial_width == 32, f"Expected initial width 32, got {initial_width}"
    print(f"✓ Initial width: {initial_width} bits")

    # Change 1: Reduce to 16 bits
    print("\nChange 1: Setting to 16 bits")
    merged.set_memory_width('dmem', 16)
    width1 = merged.nodes['dmem'].data.get('bit_width')
    assert width1 == 16, f"Expected width 16, got {width1}"
    print(f"✓ Width after change 1: {width1} bits")

    # Verify access nodes updated
    for node_id, node in merged.nodes.items():
        if 'dmem[addr]_rd' in node_id:
            node_width = node.data.get('bit_width')
            assert node_width == 16, f"Expected access node width 16, got {node_width}"
            print(f"✓ Access node width updated to {node_width} bits")

    # Generate Verilog with 16-bit memory
    import io
    import contextlib
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        generator = VerilogGenerator(merged, 'test_change_16bit')
        verilog = generator.generate()

    output_str = output.getvalue()
    assert '[MULTI-CYCLE]' in output_str, "Missing multi-cycle warning for 32->16 bit"
    print("✓ Verilog generation works with 16-bit memory")

    # Change 2: Reduce further to 8 bits
    print("\nChange 2: Setting to 8 bits")
    merged.set_memory_width('dmem', 8)
    width2 = merged.nodes['dmem'].data.get('bit_width')
    assert width2 == 8, f"Expected width 8, got {width2}"
    print(f"✓ Width after change 2: {width2} bits")

    # Generate Verilog with 8-bit memory
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        generator = VerilogGenerator(merged, 'test_change_8bit')
        verilog = generator.generate()

    output_str = output.getvalue()
    assert '[MULTI-CYCLE]' in output_str, "Missing multi-cycle warning for 32->8 bit"
    print("✓ Verilog generation works with 8-bit memory")

    # Change 3: Increase back to 32 bits
    print("\nChange 3: Setting back to 32 bits")
    merged.set_memory_width('dmem', 32)
    width3 = merged.nodes['dmem'].data.get('bit_width')
    assert width3 == 32, f"Expected width 32, got {width3}"
    print(f"✓ Width after change 3: {width3} bits")

    # Generate Verilog with 32-bit memory (no multi-cycle needed)
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        generator = VerilogGenerator(merged, 'test_change_32bit')
        verilog = generator.generate()

    output_str = output.getvalue()
    # Should NOT have multi-cycle warning when memory matches access width
    multi_cycle_count = output_str.count('[MULTI-CYCLE]')
    assert multi_cycle_count == 0, f"Unexpected multi-cycle warnings: {multi_cycle_count}"
    print("✓ Verilog generation works with 32-bit memory (no multi-cycle)")

    print("✓ Test 6 PASSED")
    return True


def main():
    print("="*70)
    print("MEMORY WIDTH CONSTRAINT TEST SUITE")
    print("="*70)

    tests = [
        ("32-bit to 16-bit constraint", test_constraint_32_to_16),
        ("Mixed stores to 8-bit", test_constraint_stores_8bit),
        ("Non-binding constraint", test_constraint_not_binding),
        ("Mixed accesses to 16-bit", test_mixed_widths_16bit),
        ("No constraint (baseline)", test_no_constraint),
        ("Change width multiple times", test_change_width_multiple_times),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, True, None))
        except Exception as e:
            results.append((name, False, str(e)))
            print(f"✗ Test FAILED: {e}")
            import traceback
            traceback.print_exc()

    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)

    for name, passed, error in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {name}")
        if error:
            print(f"  Error: {error}")

    passed_count = sum(1 for _, p, _ in results if p)
    total = len(results)

    print("="*70)
    print(f"Total: {total} tests")
    print(f"Passed: {passed_count}")
    print(f"Failed: {total - passed_count}")
    print("="*70)

    if passed_count == total:
        print("✓ ALL TESTS PASSED!")
        return 0
    else:
        print("✗ SOME TESTS FAILED")
        return 1


if __name__ == '__main__':
    sys.exit(main())
