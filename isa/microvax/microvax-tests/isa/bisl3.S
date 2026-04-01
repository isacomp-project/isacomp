# MicroVAX BISL3 Test (OR operation)
# Test: dst = src1 | src2

.text
.globl _start
_start:
    # Test 1: 0xF0 | 0x0F = 0xFF
    movli #0xF0, r0
    movli #0x0F, r1
    bisl3 r0, r1, r2
    movli #0xFF, r3
    bneq r2, r3, fail

    # Test 2: 0 | 0 = 0
    movli #0, r0
    movli #0, r1
    bisl3 r0, r1, r2
    movli #0, r3
    bneq r2, r3, fail

    # Test 3: 0xAA | 0x55 = 0xFF
    movli #0xAA, r0
    movli #0x55, r1
    bisl3 r0, r1, r2
    movli #0xFF, r3
    bneq r2, r3, fail

pass:
    brb 0

fail:
    brb 0
