# MicroVAX CLRL Test
# Test: dst = 0

.text
.globl _start
_start:
    # Test 1: Clear r0
    movli #12345, r0
    clrl r0
    movli #0, r1
    bneq r0, r1, fail

    # Test 2: Clear r5
    movli #0xABCDE, r5
    clrl r5
    movli #0, r6
    bneq r5, r6, fail

pass:
    brb 0

fail:
    brb 0
