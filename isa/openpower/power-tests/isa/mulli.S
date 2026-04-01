/* OpenPOWER MULLI (Multiply Low Immediate) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Basic tests */
test_2:
    li TESTNUM, 2
    li %r9, 0
    mulli %r8, %r9, 0
    li %r25, 0
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    li %r9, 1
    mulli %r8, %r9, 1
    li %r25, 1
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_4:
    li TESTNUM, 4
    li %r9, 3
    mulli %r8, %r9, 7        /* 3 * 7 = 21 */
    li %r25, 21
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_5:
    li TESTNUM, 5
    li %r9, 13
    mulli %r8, %r9, 11       /* 13 * 11 = 143 */
    li %r25, 143
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Negative operands */
test_6:
    li TESTNUM, 6
    li %r9, -2
    mulli %r8, %r9, 6        /* -2 * 6 = -12 */
    li %r25, -12
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_7:
    li TESTNUM, 7
    li %r9, 6
    mulli %r8, %r9, -2       /* 6 * -2 = -12 */
    li %r25, -12
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_8:
    li TESTNUM, 8
    li %r9, -3
    mulli %r8, %r9, -4       /* -3 * -4 = 12 */
    li %r25, 12
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Multiply by zero */
test_9:
    li TESTNUM, 9
    li %r9, 12345
    mulli %r8, %r9, 0
    li %r25, 0
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Larger values */
test_10:
    li TESTNUM, 10
    li %r9, 1000
    mulli %r8, %r9, 1000     /* 1000 * 1000 = 1000000 */
    LOAD_IMM(%r25, 1000000)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Source equals destination */
test_11:
    li TESTNUM, 11
    li %r9, 7
    mulli %r9, %r9, 8        /* 7 * 8 = 56 */
    li %r25, 56
    cmpd %cr0, %r9, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
