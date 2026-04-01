# MicroVAX MCOML Test
# Test: dst = ~src (bitwise NOT)

.text
.globl _start
_start:
    # Test 1: ~0 = 0xFFFFFFFF
    movli #0, r0
    mcoml r0, r1
    movli #-1, r2
    bneq r1, r2, fail

    # Test 2: ~0xFF = 0xFFFFFF00 (for 32-bit)
    # We'll check just the low bits pattern
    movli #0xFF, r0
    mcoml r0, r1
    # Expected: ~0x000000FF = 0xFFFFFF00
    # Check if result AND 0xFF == 0
    movli #0xFF, r2
    andl3 r1, r2, r3
    movli #0, r4
    bneq r3, r4, fail

pass:
    brb 0

fail:
    brb 0
