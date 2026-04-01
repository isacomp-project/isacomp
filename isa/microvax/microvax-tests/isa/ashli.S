# MicroVAX ASHLI Test (Shift Left Immediate)
# Test: dst = src << shamt

.text
.globl _start
_start:
    # Test 1: 1 << 0 = 1
    movli #1, r0
    ashli #0, r0, r1
    movli #1, r2
    bneq r1, r2, fail

    # Test 2: 1 << 1 = 2
    movli #1, r0
    ashli #1, r0, r1
    movli #2, r2
    bneq r1, r2, fail

    # Test 3: 1 << 4 = 16
    movli #1, r0
    ashli #4, r0, r1
    movli #16, r2
    bneq r1, r2, fail

    # Test 4: 0x0F << 4 = 0xF0
    movli #0x0F, r0
    ashli #4, r0, r1
    movli #0xF0, r2
    bneq r1, r2, fail

pass:
    brb 0

fail:
    brb 0
