# MicroVAX MOVL Test
# Test: dst = src

.text
.globl _start
_start:
    # Test 1: Move 0
    movli #0, r0
    movl r0, r1
    movli #0, r2
    bneq r1, r2, fail

    # Test 2: Move positive value
    movli #42, r0
    movl r0, r1
    movli #42, r2
    bneq r1, r2, fail

    # Test 3: Move larger value
    movli #0x12345, r0
    movl r0, r1
    movli #0x12345, r2
    bneq r1, r2, fail

    # Test 4: Move between different registers
    movli #100, r3
    movl r3, r4
    movli #100, r5
    bneq r4, r5, fail

pass:
    brb 0

fail:
    brb 0
