# MicroVAX INCL Test
# Test: dst = dst + 1

.text
.globl _start
_start:
    # Test 1: 0 + 1 = 1
    movli #0, r0
    incl r0
    movli #1, r1
    bneq r0, r1, fail

    # Test 2: 41 + 1 = 42
    movli #41, r0
    incl r0
    movli #42, r1
    bneq r0, r1, fail

    # Test 3: Multiple increments
    movli #0, r0
    incl r0
    incl r0
    incl r0
    movli #3, r1
    bneq r0, r1, fail

    # Test 4: Large value
    movli #0xFFFF, r0
    incl r0
    movli #0x10000, r1
    bneq r0, r1, fail

pass:
    brb 0

fail:
    brb 0
