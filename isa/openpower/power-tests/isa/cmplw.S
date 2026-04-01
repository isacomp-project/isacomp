/* OpenPOWER CMPLW (Compare Logical Word) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * CMPLW tests - cmplw BF, rA, rB (unsigned 32-bit comparison)
     * Sets CR field: LT, GT, EQ, SO
     *-------------------------------------------------------------*/

    /* Equal values */
test_2:
    li TESTNUM, 2
    li %r9, 0
    li %r10, 0
    cmplw %cr0, %r9, %r10
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    li %r9, 1
    li %r10, 1
    cmplw %cr0, %r9, %r10
    bne %cr0, fail

test_4:
    li TESTNUM, 4
    LOAD_IMM(%r9, 0xffffffff)
    LOAD_IMM(%r10, 0xffffffff)
    cmplw %cr0, %r9, %r10
    bne %cr0, fail

    /* Less than (unsigned) */
test_5:
    li TESTNUM, 5
    li %r9, 0
    li %r10, 1
    cmplw %cr0, %r9, %r10
    bge %cr0, fail

test_6:
    li TESTNUM, 6
    li %r9, 0
    LOAD_IMM(%r10, 0xffffffff)
    cmplw %cr0, %r9, %r10
    bge %cr0, fail      /* 0 should be < 0xffffffff (unsigned) */

test_7:
    li TESTNUM, 7
    LOAD_IMM(%r9, 0x7fffffff)
    LOAD_IMM(%r10, 0x80000000)
    cmplw %cr0, %r9, %r10
    bge %cr0, fail      /* 0x7fffffff should be < 0x80000000 (unsigned) */

    /* Greater than (unsigned) */
test_8:
    li TESTNUM, 8
    li %r9, 1
    li %r10, 0
    cmplw %cr0, %r9, %r10
    ble %cr0, fail

test_9:
    li TESTNUM, 9
    LOAD_IMM(%r9, 0xffffffff)
    li %r10, 0
    cmplw %cr0, %r9, %r10
    ble %cr0, fail      /* 0xffffffff should be > 0 (unsigned) */

test_10:
    li TESTNUM, 10
    LOAD_IMM(%r9, 0x80000000)
    LOAD_IMM(%r10, 0x7fffffff)
    cmplw %cr0, %r9, %r10
    ble %cr0, fail      /* 0x80000000 should be > 0x7fffffff (unsigned) */

    /* Boundary values */
test_11:
    li TESTNUM, 11
    LOAD_IMM(%r9, 0xfffffffe)
    LOAD_IMM(%r10, 0xffffffff)
    cmplw %cr0, %r9, %r10
    bge %cr0, fail

test_12:
    li TESTNUM, 12
    LOAD_IMM(%r9, 0xffffffff)
    LOAD_IMM(%r10, 0xfffffffe)
    cmplw %cr0, %r9, %r10
    ble %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
