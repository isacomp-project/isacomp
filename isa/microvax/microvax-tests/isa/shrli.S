# MicroVAX SHRLI Test (Shift Right Logical Immediate)
# Test: dst = src >> shamt (logical, zero-fill)

.text
.globl _start
_start:
    # Test 1: 2 >> 1 = 1
    movli #2, r0
    shrli #1, r0, r1
    movli #1, r2
    bneq r1, r2, fail

    # Test 2: 16 >> 4 = 1
    movli #16, r0
    shrli #4, r0, r1
    movli #1, r2
    bneq r1, r2, fail

    # Test 3: 0xF0 >> 4 = 0x0F
    movli #0xF0, r0
    shrli #4, r0, r1
    movli #0x0F, r2
    bneq r1, r2, fail

pass:
    brb 0

fail:
    brb 0
