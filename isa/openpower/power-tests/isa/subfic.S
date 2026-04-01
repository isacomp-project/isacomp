/* OpenPOWER SUBFIC (Subtract From Immediate Carrying) instruction tests */
/* subfic rD, rA, SIMM computes rD = SIMM - rA */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Basic tests */
test_2:
    li TESTNUM, 2
    li %r9, 0
    subfic %r8, %r9, 0
    li %r25, 0
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    li %r9, 5
    subfic %r8, %r9, 10      /* 10 - 5 = 5 */
    li %r25, 5
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_4:
    li TESTNUM, 4
    li %r9, 10
    subfic %r8, %r9, 5       /* 5 - 10 = -5 */
    li %r25, -5
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_5:
    li TESTNUM, 5
    li %r9, -1
    subfic %r8, %r9, 0       /* 0 - (-1) = 1 */
    li %r25, 1
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_6:
    li TESTNUM, 6
    li %r9, 1
    subfic %r8, %r9, -1      /* -1 - 1 = -2 */
    li %r25, -2
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* Negative immediate */
test_7:
    li TESTNUM, 7
    li %r9, 0
    subfic %r8, %r9, -100    /* -100 - 0 = -100 */
    li %r25, -100
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_8:
    li TESTNUM, 8
    li %r9, -50
    subfic %r8, %r9, -100    /* -100 - (-50) = -50 */
    li %r25, -50
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* Source equals destination */
test_9:
    li TESTNUM, 9
    li %r9, 7
    subfic %r9, %r9, 20      /* 20 - 7 = 13 */
    li %r25, 13
    cmpw %cr0, %r9, %r25
    bne %cr0, fail

    /* Boundary values */
test_10:
    li TESTNUM, 10
    li %r9, 0
    subfic %r8, %r9, 0x7fff  /* max positive immediate */
    li %r25, 0x7fff
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
