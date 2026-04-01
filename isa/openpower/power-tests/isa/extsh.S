/* OpenPOWER EXTSH (Extend Sign Halfword) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * EXTSH tests - extsh rA, rS (sign-extend halfword to 64 bits)
     *-------------------------------------------------------------*/

    /* Positive values (bit 15 = 0) */
test_2:
    li TESTNUM, 2
    li %r9, 0x0000
    extsh %r8, %r9
    li %r25, 0x0000
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    li %r9, 0x7fff
    extsh %r8, %r9
    li %r25, 0x7fff
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_4:
    li TESTNUM, 4
    li %r9, 0x0001
    extsh %r8, %r9
    li %r25, 0x0001
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Negative values (bit 15 = 1) */
test_5:
    li TESTNUM, 5
    lis %r9, 0
    ori %r9, %r9, 0x8000
    extsh %r8, %r9
    lis %r25, 0xffff
    ori %r25, %r25, 0x8000
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_6:
    li TESTNUM, 6
    li %r9, -1   /* 0xffff in low 16 bits */
    extsh %r8, %r9
    li %r25, -1
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_7:
    li TESTNUM, 7
    lis %r9, 0
    ori %r9, %r9, 0xfffe
    extsh %r8, %r9
    li %r25, -2
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Upper bits should be ignored */
test_8:
    li TESTNUM, 8
    LOAD_IMM(%r9, 0x12340000)
    extsh %r8, %r9
    li %r25, 0
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_9:
    li TESTNUM, 9
    LOAD_IMM(%r9, 0x1234ffff)
    extsh %r8, %r9
    li %r25, -1
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_10:
    li TESTNUM, 10
    LOAD_IMM(%r9, 0xffff7fff)
    extsh %r8, %r9
    li %r25, 0x7fff
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Source equals destination */
test_11:
    li TESTNUM, 11
    li %r9, -1
    extsh %r9, %r9
    li %r25, -1
    cmpd %cr0, %r9, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
