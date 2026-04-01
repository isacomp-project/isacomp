# MicroVAX BLSS Test (Branch if Less Than Signed)
# Test: if (src1 < src2) branch

.text
.globl _start
_start:
    # Test 1: 5 < 10 should branch
    movli #5, r0
    movli #10, r1
    blss r0, r1, test2
    brb fail

test2:
    # Test 2: 10 < 5 should not branch
    movli #10, r0
    movli #5, r1
    blss r0, r1, fail
    brb test3

test3:
    # Test 3: -1 < 0 should branch (signed)
    movli #-1, r0
    movli #0, r1
    blss r0, r1, test4
    brb fail

test4:
    # Test 4: Equal values should not branch
    movli #5, r0
    movli #5, r1
    blss r0, r1, fail
    brb pass

pass:
    brb 0

fail:
    brb 0
