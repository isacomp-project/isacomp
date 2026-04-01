/* OpenPOWER EXTSB (Extend Sign Byte) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * EXTSB tests - extsb rA, rS (sign-extend byte to 64 bits)
     *-------------------------------------------------------------*/

    /* Positive values (bit 7 = 0) */
test_2:
    li TESTNUM, 2
    li %r9, 0x00
    extsb %r8, %r9
    li %r25, 0x00
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    li %r9, 0x7f
    extsb %r8, %r9
    li %r25, 0x7f
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_4:
    li TESTNUM, 4
    li %r9, 0x01
    extsb %r8, %r9
    li %r25, 0x01
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Negative values (bit 7 = 1) */
test_5:
    li TESTNUM, 5
    li %r9, 0x80
    extsb %r8, %r9
    li %r25, -128
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_6:
    li TESTNUM, 6
    li %r9, 0xff
    extsb %r8, %r9
    li %r25, -1
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_7:
    li TESTNUM, 7
    li %r9, 0xfe
    extsb %r8, %r9
    li %r25, -2
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Upper bits should be ignored */
test_8:
    li TESTNUM, 8
    LOAD_IMM(%r9, 0x12345600)
    extsb %r8, %r9
    li %r25, 0
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_9:
    li TESTNUM, 9
    LOAD_IMM(%r9, 0x123456ff)
    extsb %r8, %r9
    li %r25, -1
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_10:
    li TESTNUM, 10
    LOAD_IMM(%r9, 0xffffff7f)
    extsb %r8, %r9
    li %r25, 0x7f
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Source equals destination */
test_11:
    li TESTNUM, 11
    li %r9, 0xff
    extsb %r9, %r9
    li %r25, -1
    cmpd %cr0, %r9, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
