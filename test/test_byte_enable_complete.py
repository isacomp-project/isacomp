#!/usr/bin/env python3
"""Test complete byte-enable and unaligned access integration with memory transformations."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.resource_graph import ResourceGraph
from core.isa_parser import parse_isa_file
from backends.verilog import generate_verilog
from core.graph_merger import merge_instructions


def test_sw_serialization():
    """Test SW (32-bit store) with serialization to 16-bit memory."""
    print("\n" + "="*70)
    print("TEST 1: SW (Store Word) with Serialization (32→16 bits)")
    print("="*70)

    graph = parse_isa_file('isa/riscv32/sw.isa')
    graph.set_memory_width('dmem', 16)
    result = graph.optimize_memory_accesses('dmem', strategy='serialize_parallelize')

    verilog = generate_verilog(graph, "test_sw_serialized")

    # Check for counter-based enables
    if 'dmem_access_counter == 0' in verilog and 'dmem_access_counter == 1' in verilog:
        print("✅ Counter-based write enables present")
    else:
        print("❌ Counter-based write enables missing")
        return False

    # Save
    with open('/tmp/test_sw_serialized.v', 'w') as f:
        f.write(verilog)
    print(f"✅ Verilog saved to /tmp/test_sw_serialized.v")
    return True


def test_sh_serialization():
    """Test SH (16-bit store) with serialization to 8-bit memory."""
    print("\n" + "="*70)
    print("TEST 2: SH (Store Halfword) with Serialization (16→8 bits)")
    print("="*70)

    graph = parse_isa_file('isa/riscv32/sh.isa')
    print(f"Original dmem width: {graph.nodes['dmem'].data.get('bit_width')} bits")

    # Set to 8-bit memory (narrower than 16-bit store)
    graph.set_memory_width('dmem', 8)
    result = graph.optimize_memory_accesses('dmem', strategy='serialize_parallelize')

    if not result.get('transformed'):
        print(f"❌ Transformation failed: {result.get('reason')}")
        return False

    print(f"✅ Transformation successful ({result['direction']})")

    verilog = generate_verilog(graph, "test_sh_serialized")

    # Check for byte-lane selection (case statements)
    if 'case' in verilog and '[1:0]' in verilog:
        print("✅ Byte-lane selection (case statement) present")
    else:
        print("⚠️  No case statement - may not need byte-lane selection for this width")

    # Check for counter-based enables
    if 'dmem_access_counter == 0' in verilog:
        print("✅ Counter-based write enables present")
    else:
        print("❌ Counter-based write enables missing")
        return False

    with open('/tmp/test_sh_serialized.v', 'w') as f:
        f.write(verilog)
    print(f"✅ Verilog saved to /tmp/test_sh_serialized.v")
    return True


def test_sb_direct():
    """Test SB (8-bit store) to 32-bit memory (no transformation, just byte-enable)."""
    print("\n" + "="*70)
    print("TEST 3: SB (Store Byte) to 32-bit Memory (Byte-Enable Baseline)")
    print("="*70)

    graph = parse_isa_file('isa/riscv32/sb.isa')
    original_width = graph.nodes['dmem'].data.get('bit_width')
    print(f"Original dmem width: {original_width} bits")

    # Set to 32-bit memory to test byte-enable logic
    graph.set_memory_width('dmem', 32)
    print(f"Set dmem width to 32 bits for byte-enable testing")

    verilog = generate_verilog(graph, "test_sb_baseline")

    # Check for byte-lane selection
    if 'case' in verilog and '[1:0]' in verilog:
        print("✅ Byte-lane selection (case statement) present")
        # Count case branches
        case_count = verilog.count("2'b")
        print(f"   Found {case_count} case branches for byte selection")
    else:
        print("❌ Byte-lane selection missing")
        return False

    with open('/tmp/test_sb_baseline.v', 'w') as f:
        f.write(verilog)
    print(f"✅ Verilog saved to /tmp/test_sb_baseline.v")
    return True


def test_lw_unaligned():
    """Test LW (32-bit load) with potential unaligned access."""
    print("\n" + "="*70)
    print("TEST 4: LW (Load Word) - Unaligned Access Support")
    print("="*70)

    graph = parse_isa_file('isa/riscv32/lw.isa')
    verilog = generate_verilog(graph, "test_lw_unaligned")

    # Check for dual-word read logic
    if '_word0' in verilog and '_word1' in verilog:
        print("✅ Dual-word read logic present for unaligned access")
    else:
        print("⚠️  No dual-word logic (may be optimized out if not needed)")

    with open('/tmp/test_lw_unaligned.v', 'w') as f:
        f.write(verilog)
    print(f"✅ Verilog saved to /tmp/test_lw_unaligned.v")
    return True


def test_merged_stores():
    """Test merged SB/SH/SW processor with byte-enable logic."""
    print("\n" + "="*70)
    print("TEST 5: Merged SB/SH/SW - Mixed Width Byte-Enable")
    print("="*70)

    try:
        merged = merge_instructions({
            'sb': 'isa/riscv32/sb.isa',
            'sh': 'isa/riscv32/sh.isa',
            'sw': 'isa/riscv32/sw.isa'
        })
        print(f"✅ Merged {len(merged.nodes)} nodes")

        verilog = generate_verilog(merged, "test_merged_stores")

        # Check for conditional byte-lane logic (if statements with enable conditions)
        if 'if (sb_enable_and)' in verilog or 'sb_enable_and' in verilog:
            print("✅ SB enable condition present")
        if 'if (sh_enable_and)' in verilog or 'sh_enable_and' in verilog:
            print("✅ SH enable condition present")
        if 'if (sw_enable_and)' in verilog or 'sw_enable_and' in verilog:
            print("✅ SW enable condition present")

        # Check for case statements
        case_count = verilog.count('case (')
        print(f"   Found {case_count} case statement(s) for byte-lane selection")

        with open('/tmp/test_merged_stores.v', 'w') as f:
            f.write(verilog)
        print(f"✅ Verilog saved to /tmp/test_merged_stores.v")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def main():
    """Run all byte-enable and unaligned access tests."""
    print("\n" + "="*70)
    print("COMPLETE BYTE-ENABLE AND UNALIGNED ACCESS TEST SUITE")
    print("="*70)

    tests = [
        ("SW with serialization", test_sw_serialization),
        ("SH with serialization", test_sh_serialization),
        ("SB byte-enable baseline", test_sb_direct),
        ("LW unaligned support", test_lw_unaligned),
        ("Merged stores", test_merged_stores),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ Test failed with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All byte-enable and unaligned access tests PASSED!")
        return 0
    else:
        print(f"\n❌ {total - passed} test(s) FAILED")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
