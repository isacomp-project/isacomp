# MicroVAX BNEQ Test (Branch if Not Equal)
# Test: if (src1 != src2) branch

.text
.globl _start
_start:
    # Test 1: Branch taken when not equal
    movli #5, r0
    movli #6, r1
    bneq r0, r1, test2
    brb fail

test2:
    # Test 2: Branch not taken when equal
    movli #5, r0
    movli #5, r1
    bneq r0, r1, fail
    brb test3

test3:
    # Test 3: Different signs
    movli #1, r0
    movli #-1, r1
    bneq r0, r1, pass
    brb fail

pass:
    brb 0

fail:
    brb 0
