# MicroVAX XORL3 Test
# Test: dst = src1 ^ src2

.text
.globl _start
_start:
    # Test 1: 0xFF ^ 0xFF = 0
    movli #0xFF, r0
    movli #0xFF, r1
    xorl3 r0, r1, r2
    movli #0, r3
    bneq r2, r3, fail

    # Test 2: 0xAA ^ 0x55 = 0xFF
    movli #0xAA, r0
    movli #0x55, r1
    xorl3 r0, r1, r2
    movli #0xFF, r3
    bneq r2, r3, fail

    # Test 3: 0 ^ 0x12345 = 0x12345
    movli #0, r0
    movli #0x12345, r1
    xorl3 r0, r1, r2
    movli #0x12345, r3
    bneq r2, r3, fail

pass:
    brb 0

fail:
    brb 0
