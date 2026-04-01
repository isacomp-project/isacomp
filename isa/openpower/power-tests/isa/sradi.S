/* OpenPOWER SRADI (Shift Right Algebraic Doubleword Immediate) instruction tests */
/* sradi rA, rS, SH -> rA = rS >> SH, sign extended */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Positive value shifts */
test_2:
    li TESTNUM, 2
    LOAD_IMM(%r9, 0x7fffffff)
    sradi %r8, %r9, 0
    LOAD_IMM(%r25, 0x7fffffff)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    LOAD_IMM(%r9, 0x7fffffff)
    sradi %r8, %r9, 1
    LOAD_IMM(%r25, 0x3fffffff)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_4:
    li TESTNUM, 4
    LOAD_IMM(%r9, 0x12345678)
    sradi %r8, %r9, 4
    LOAD_IMM(%r25, 0x1234567)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Negative value shifts (sign extension) */
test_5:
    li TESTNUM, 5
    li %r9, -1
    sradi %r8, %r9, 1
    li %r25, -1
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_6:
    li TESTNUM, 6
    li %r9, -2
    sradi %r8, %r9, 1
    li %r25, -1
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_7:
    li TESTNUM, 7
    li %r9, -128
    sradi %r8, %r9, 3
    li %r25, -16
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_8:
    li TESTNUM, 8
    li %r9, -256
    sradi %r8, %r9, 4
    li %r25, -16
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Large shift amounts (up to 63 for doubleword) */
test_9:
    li TESTNUM, 9
    li %r9, 1
    sldi %r9, %r9, 63        /* 0x8000000000000000 */
    sradi %r8, %r9, 63
    li %r25, -1
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_10:
    li TESTNUM, 10
    li %r9, 1
    sldi %r9, %r9, 40        /* Large positive number */
    sradi %r8, %r9, 32
    li %r25, 0x100
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Source equals destination */
test_11:
    li TESTNUM, 11
    li %r9, -512
    sradi %r9, %r9, 5
    li %r25, -16
    cmpd %cr0, %r9, %r25
    bne %cr0, fail

    /* Zero source */
test_12:
    li TESTNUM, 12
    li %r9, 0
    sradi %r8, %r9, 31
    li %r25, 0
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
