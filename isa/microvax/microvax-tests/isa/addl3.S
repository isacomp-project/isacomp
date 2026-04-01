# MicroVAX ADDL3 Test
# Test: dst = src1 + src2

.text
.globl _start
_start:
    # Test 1: 0 + 0 = 0
    movli #0, r0
    movli #0, r1
    addl3 r0, r1, r2
    movli #0, r3
    bneq r2, r3, fail

    # Test 2: 1 + 1 = 2
    movli #1, r0
    movli #1, r1
    addl3 r0, r1, r2
    movli #2, r3
    bneq r2, r3, fail

    # Test 3: 3 + 7 = 10
    movli #3, r0
    movli #7, r1
    addl3 r0, r1, r2
    movli #10, r3
    bneq r2, r3, fail

    # Test 4: Large values
    movli #0x1000, r0
    movli #0x2000, r1
    addl3 r0, r1, r2
    movli #0x3000, r3
    bneq r2, r3, fail

    # Test 5: Negative + Positive
    movli #-5, r0
    movli #10, r1
    addl3 r0, r1, r2
    movli #5, r3
    bneq r2, r3, fail

pass:
    brb 0

fail:
    brb 0
