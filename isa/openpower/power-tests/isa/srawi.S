/* OpenPOWER SRAWI (Shift Right Algebraic Word Immediate) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * SRAWI tests - srawi rA, rS, SH
     * rA = rS >> SH (arithmetic), with 32-bit word, result sign-extended
     *-------------------------------------------------------------*/

    /* Shift positive by 0 */
test_2:
    li TESTNUM, 2
    LOAD_IMM(%r9, 0x7fffffff)
    srawi %r8, %r9, 0
    LOAD_IMM(%r25, 0x7fffffff)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Shift positive by 1 */
test_3:
    li TESTNUM, 3
    LOAD_IMM(%r9, 0x7fffffff)
    srawi %r8, %r9, 1
    LOAD_IMM(%r25, 0x3fffffff)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Shift positive by 31 */
test_4:
    li TESTNUM, 4
    LOAD_IMM(%r9, 0x7fffffff)
    srawi %r8, %r9, 31
    li %r25, 0
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Shift negative by 0 */
test_5:
    li TESTNUM, 5
    LOAD_IMM(%r9, 0x80000000)
    srawi %r8, %r9, 0
    /* Result should be sign-extended: 0xffffffff80000000 */
    LOAD_IMM(%r25, 0x80000000)
    extsw %r25, %r25
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Shift negative by 1 */
test_6:
    li TESTNUM, 6
    LOAD_IMM(%r9, 0x80000000)
    srawi %r8, %r9, 1
    /* 0x80000000 >> 1 = 0xc0000000, sign-extended */
    LOAD_IMM(%r25, 0xc0000000)
    extsw %r25, %r25
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Shift negative by 7 */
test_7:
    li TESTNUM, 7
    LOAD_IMM(%r9, 0x80000000)
    srawi %r8, %r9, 7
    /* 0x80000000 >> 7 = 0xff000000, sign-extended */
    LOAD_IMM(%r25, 0xff000000)
    extsw %r25, %r25
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Shift negative by 31 (all sign bits) */
test_8:
    li TESTNUM, 8
    LOAD_IMM(%r9, 0x80000000)
    srawi %r8, %r9, 31
    li %r25, -1
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Shift -1 by any amount stays -1 */
test_9:
    li TESTNUM, 9
    li %r9, -1
    srawi %r8, %r9, 15
    li %r25, -1
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Various shifts */
test_10:
    li TESTNUM, 10
    LOAD_IMM(%r9, 0x21212121)
    srawi %r8, %r9, 7
    LOAD_IMM(%r25, 0x00424242)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_11:
    li TESTNUM, 11
    LOAD_IMM(%r9, 0x21212121)
    srawi %r8, %r9, 14
    LOAD_IMM(%r25, 0x00008484)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Source equals destination */
test_12:
    li TESTNUM, 12
    LOAD_IMM(%r9, 0x80000000)
    srawi %r9, %r9, 7
    LOAD_IMM(%r25, 0xff000000)
    extsw %r25, %r25
    cmpd %cr0, %r9, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
