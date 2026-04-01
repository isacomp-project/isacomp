# MicroVAX MNEGL Test
# Test: dst = -src

.text
.globl _start
_start:
    # Test 1: -0 = 0
    movli #0, r0
    mnegl r0, r1
    movli #0, r2
    bneq r1, r2, fail

    # Test 2: -1 = 0xFFFFFFFF
    movli #1, r0
    mnegl r0, r1
    movli #-1, r2
    bneq r1, r2, fail

    # Test 3: -42 = 0xFFFFFFD6
    movli #42, r0
    mnegl r0, r1
    movli #-42, r2
    bneq r1, r2, fail

pass:
    brb 0

fail:
    brb 0
