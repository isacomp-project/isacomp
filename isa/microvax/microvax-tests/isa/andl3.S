# MicroVAX ANDL3 Test
# Test: dst = src1 & src2

.text
.globl _start
_start:
    # Test 1: 0xFF & 0xFF = 0xFF
    movli #0xFF, r0
    movli #0xFF, r1
    andl3 r0, r1, r2
    movli #0xFF, r3
    bneq r2, r3, fail

    # Test 2: 0xF0 & 0x0F = 0
    movli #0xF0, r0
    movli #0x0F, r1
    andl3 r0, r1, r2
    movli #0, r3
    bneq r2, r3, fail

    # Test 3: 0xAA & 0xCC = 0x88
    movli #0xAA, r0
    movli #0xCC, r1
    andl3 r0, r1, r2
    movli #0x88, r3
    bneq r2, r3, fail

pass:
    brb 0

fail:
    brb 0
