/* OpenPOWER SLD (Shift Left Doubleword) instruction tests */
/* sld rA, rS, rB -> rA = rS << (rB[58:63]), zeros shifted in */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Basic shifts */
test_2:
    li TESTNUM, 2
    li %r9, 1
    li %r10, 0
    sld %r8, %r9, %r10
    li %r25, 1
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    li %r9, 1
    li %r10, 1
    sld %r8, %r9, %r10
    li %r25, 2
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_4:
    li TESTNUM, 4
    li %r9, 1
    li %r10, 7
    sld %r8, %r9, %r10
    li %r25, 0x80
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_5:
    li TESTNUM, 5
    li %r9, 1
    li %r10, 31
    sld %r8, %r9, %r10
    /* 0x80000000 - use sldi to avoid sign extension */
    li %r25, 1
    sldi %r25, %r25, 31
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* 64-bit shift - shift into high doubleword */
test_6:
    li TESTNUM, 6
    li %r9, 1
    li %r10, 32
    sld %r8, %r9, %r10
    li %r25, 1
    sldi %r25, %r25, 32      /* 0x100000000 */
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_7:
    li TESTNUM, 7
    li %r9, 1
    li %r10, 63
    sld %r8, %r9, %r10
    li %r25, 1
    sldi %r25, %r25, 63      /* 0x8000000000000000 */
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Shift by 64 or more - result is zero */
test_8:
    li TESTNUM, 8
    li %r9, -1               /* All ones */
    li %r10, 64
    sld %r8, %r9, %r10
    li %r25, 0
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Multi-bit pattern - use small values that don't overflow */
test_9:
    li TESTNUM, 9
    li %r9, 0x7FF          /* 11 bits, shift left 4 won't overflow 16 bits */
    li %r10, 4
    sld %r8, %r9, %r10
    li %r25, 0x7FF0        /* 0x7FF << 4 = 0x7FF0 */
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Source equals destination */
test_10:
    li TESTNUM, 10
    li %r9, 0xff
    li %r10, 8
    sld %r9, %r9, %r10
    LOAD_IMM(%r25, 0xff00)
    cmpd %cr0, %r9, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
