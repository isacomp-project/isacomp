# MicroVAX SUBL3 Test
# Test: dst = src2 - src1

.text
.globl _start
_start:
    # Test 1: 0 - 0 = 0
    movli #0, r0
    movli #0, r1
    subl3 r0, r1, r2
    movli #0, r3
    bneq r2, r3, fail

    # Test 2: 5 - 3 = 2
    movli #3, r0
    movli #5, r1
    subl3 r0, r1, r2
    movli #2, r3
    bneq r2, r3, fail

    # Test 3: 10 - 7 = 3
    movli #7, r0
    movli #10, r1
    subl3 r0, r1, r2
    movli #3, r3
    bneq r2, r3, fail

    # Test 4: Large values
    movli #0x1000, r0
    movli #0x3000, r1
    subl3 r0, r1, r2
    movli #0x2000, r3
    bneq r2, r3, fail

pass:
    brb 0

fail:
    brb 0
