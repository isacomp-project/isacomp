# MicroVAX DECL Test
# Test: dst = dst - 1

.text
.globl _start
_start:
    # Test 1: 1 - 1 = 0
    movli #1, r0
    decl r0
    movli #0, r1
    bneq r0, r1, fail

    # Test 2: 42 - 1 = 41
    movli #42, r0
    decl r0
    movli #41, r1
    bneq r0, r1, fail

    # Test 3: Multiple decrements
    movli #5, r0
    decl r0
    decl r0
    decl r0
    movli #2, r1
    bneq r0, r1, fail

pass:
    brb 0

fail:
    brb 0
