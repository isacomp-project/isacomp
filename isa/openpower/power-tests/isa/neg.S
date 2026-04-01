/* OpenPOWER NEG (Negate) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * Negate tests - neg rD, rA  (rD = ~rA + 1 = -rA)
     *-------------------------------------------------------------*/

    /* Basic tests */
test_2:
    li TESTNUM, 2
    li %r9, 0
    neg %r8, %r9
    li %r25, 0
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    li %r9, 1
    neg %r8, %r9
    li %r25, -1
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_4:
    li TESTNUM, 4
    li %r9, -1
    neg %r8, %r9
    li %r25, 1
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_5:
    li TESTNUM, 5
    li %r9, 100
    neg %r8, %r9
    li %r25, -100
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

test_6:
    li TESTNUM, 6
    li %r9, -100
    neg %r8, %r9
    li %r25, 100
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* Boundary test: most negative number */
test_7:
    li TESTNUM, 7
    lis %r9, 0x8000
    neg %r8, %r9
    lis %r25, 0x8000   /* -(-2^31) overflows to -2^31 in 32-bit */
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* Max positive */
test_8:
    li TESTNUM, 8
    lis %r9, 0x7fff
    ori %r9, %r9, 0xffff
    neg %r8, %r9
    lis %r25, 0x8000
    ori %r25, %r25, 0x0001
    cmpw %cr0, %r8, %r25
    bne %cr0, fail

    /* Source equals destination */
test_9:
    li TESTNUM, 9
    li %r9, 42
    neg %r9, %r9
    li %r25, -42
    cmpw %cr0, %r9, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
