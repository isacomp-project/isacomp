# MicroVAX BGEQ Test (Branch if Greater or Equal Signed)
# Test: if (src1 >= src2) branch

.text
.globl _start
_start:
    # Test 1: 10 >= 5 should branch
    movli #10, r0
    movli #5, r1
    bgeq r0, r1, test2
    brb fail

test2:
    # Test 2: 5 >= 5 should branch (equal case)
    movli #5, r0
    movli #5, r1
    bgeq r0, r1, test3
    brb fail

test3:
    # Test 3: 5 >= 10 should not branch
    movli #5, r0
    movli #10, r1
    bgeq r0, r1, fail
    brb test4

test4:
    # Test 4: 0 >= -1 should branch
    movli #0, r0
    movli #-1, r1
    bgeq r0, r1, pass
    brb fail

pass:
    brb 0

fail:
    brb 0
