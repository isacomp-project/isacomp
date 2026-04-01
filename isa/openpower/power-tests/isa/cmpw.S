/* OpenPOWER CMPW (Compare Word) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * CMPW tests - cmpw BF, rA, rB (signed 32-bit comparison)
     * Sets CR field: LT, GT, EQ, SO
     *-------------------------------------------------------------*/

    /* Equal values */
test_2:
    li TESTNUM, 2
    li %r9, 0
    li %r10, 0
    cmpw %cr0, %r9, %r10
    bne %cr0, fail      /* Should be equal */

test_3:
    li TESTNUM, 3
    li %r9, 1
    li %r10, 1
    cmpw %cr0, %r9, %r10
    bne %cr0, fail

test_4:
    li TESTNUM, 4
    li %r9, -1
    li %r10, -1
    cmpw %cr0, %r9, %r10
    bne %cr0, fail

    /* Less than (signed) */
test_5:
    li TESTNUM, 5
    li %r9, 0
    li %r10, 1
    cmpw %cr0, %r9, %r10
    bge %cr0, fail      /* 0 should be < 1 */

test_6:
    li TESTNUM, 6
    li %r9, -1
    li %r10, 0
    cmpw %cr0, %r9, %r10
    bge %cr0, fail      /* -1 should be < 0 */

test_7:
    li TESTNUM, 7
    li %r9, -2
    li %r10, -1
    cmpw %cr0, %r9, %r10
    bge %cr0, fail      /* -2 should be < -1 */

    /* Greater than (signed) */
test_8:
    li TESTNUM, 8
    li %r9, 1
    li %r10, 0
    cmpw %cr0, %r9, %r10
    ble %cr0, fail      /* 1 should be > 0 */

test_9:
    li TESTNUM, 9
    li %r9, 0
    li %r10, -1
    cmpw %cr0, %r9, %r10
    ble %cr0, fail      /* 0 should be > -1 */

test_10:
    li TESTNUM, 10
    li %r9, -1
    li %r10, -2
    cmpw %cr0, %r9, %r10
    ble %cr0, fail      /* -1 should be > -2 */

    /* Boundary values */
test_11:
    li TESTNUM, 11
    LOAD_IMM(%r9, 0x7fffffff)
    LOAD_IMM(%r10, 0x80000000)
    cmpw %cr0, %r9, %r10
    ble %cr0, fail      /* 0x7fffffff should be > 0x80000000 (signed) */

test_12:
    li TESTNUM, 12
    LOAD_IMM(%r9, 0x80000000)
    LOAD_IMM(%r10, 0x7fffffff)
    cmpw %cr0, %r9, %r10
    bge %cr0, fail      /* 0x80000000 should be < 0x7fffffff (signed) */

    /* Use different CR fields */
test_13:
    li TESTNUM, 13
    li %r9, 5
    li %r10, 10
    cmpw %cr1, %r9, %r10
    bge %cr1, fail

test_14:
    li TESTNUM, 14
    li %r9, 10
    li %r10, 5
    cmpw %cr2, %r9, %r10
    ble %cr2, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
