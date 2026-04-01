/* OpenPOWER SRAD (Shift Right Algebraic Doubleword) instruction tests */
/* srad rA, rS, rB -> rA = rS >> (rB[58:63]), sign extended */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Positive value shifts (same as logical) */
test_2:
    li TESTNUM, 2
    LOAD_IMM(%r9, 0x7fffffff)
    li %r10, 0
    srad %r8, %r9, %r10
    LOAD_IMM(%r25, 0x7fffffff)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    LOAD_IMM(%r9, 0x7fffffff)
    li %r10, 1
    srad %r8, %r9, %r10
    LOAD_IMM(%r25, 0x3fffffff)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Negative value shifts (sign extension) */
test_4:
    li TESTNUM, 4
    li %r9, -1
    li %r10, 1
    srad %r8, %r9, %r10
    li %r25, -1               /* -1 >> any = -1 */
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_5:
    li TESTNUM, 5
    li %r9, -2                /* 0xfffffffffffffffe */
    li %r10, 1
    srad %r8, %r9, %r10
    li %r25, -1               /* -2 >> 1 = -1 */
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_6:
    li TESTNUM, 6
    li %r9, -128              /* 0xffffffffffffff80 */
    li %r10, 3
    srad %r8, %r9, %r10
    li %r25, -16              /* -128 >> 3 = -16 */
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Large negative value */
test_7:
    li TESTNUM, 7
    li %r9, 1
    sldi %r9, %r9, 63        /* 0x8000000000000000 = MIN_INT64 */
    li %r10, 63
    srad %r8, %r9, %r10
    li %r25, -1               /* MIN >> 63 = -1 */
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_8:
    li TESTNUM, 8
    li %r9, 1
    sldi %r9, %r9, 63        /* 0x8000000000000000 */
    li %r10, 1
    srad %r8, %r9, %r10
    li %r25, 1
    sldi %r25, %r25, 62
    neg %r25, %r25            /* 0xc000000000000000 = sign extended */
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Source equals destination */
test_9:
    li TESTNUM, 9
    li %r9, -256
    li %r10, 4
    srad %r9, %r9, %r10
    li %r25, -16              /* -256 >> 4 = -16 */
    cmpd %cr0, %r9, %r25
    bne %cr0, fail

    /* Zero source */
test_10:
    li TESTNUM, 10
    li %r9, 0
    li %r10, 31
    srad %r8, %r9, %r10
    li %r25, 0
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
