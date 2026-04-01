# MicroVAX BEQL Test (Branch if Equal)
# Test: if (src1 == src2) branch

.text
.globl _start
_start:
    # Test 1: Branch taken when equal
    movli #5, r0
    movli #5, r1
    beql r0, r1, test2
    brb fail

test2:
    # Test 2: Branch not taken when not equal
    movli #5, r0
    movli #6, r1
    beql r0, r1, fail
    brb test3

test3:
    # Test 3: Equal zeros
    movli #0, r0
    movli #0, r1
    beql r0, r1, pass
    brb fail

pass:
    brb 0

fail:
    brb 0
