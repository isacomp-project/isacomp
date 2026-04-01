# MicroVAX MULL3 Test
# Test: dst = src1 * src2

.text
.globl _start
_start:
    # Test 1: 0 * 5 = 0
    movli #0, r0
    movli #5, r1
    mull3 r0, r1, r2
    movli #0, r3
    bneq r2, r3, fail

    # Test 2: 1 * 1 = 1
    movli #1, r0
    movli #1, r1
    mull3 r0, r1, r2
    movli #1, r3
    bneq r2, r3, fail

    # Test 3: 3 * 7 = 21
    movli #3, r0
    movli #7, r1
    mull3 r0, r1, r2
    movli #21, r3
    bneq r2, r3, fail

    # Test 4: 10 * 10 = 100
    movli #10, r0
    movli #10, r1
    mull3 r0, r1, r2
    movli #100, r3
    bneq r2, r3, fail

pass:
    brb 0

fail:
    brb 0
