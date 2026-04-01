/* OpenPOWER CMPD (Compare Doubleword) instruction tests */
/* cmpd crfD, rA, rB -> Compare rA with rB as signed 64-bit */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Equal values */
test_2:
    li TESTNUM, 2
    li %r9, 100
    li %r10, 100
    cmpd %cr0, %r9, %r10
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    li %r9, -1
    li %r10, -1
    cmpd %cr0, %r9, %r10
    bne %cr0, fail

    /* Less than (signed) */
test_4:
    li TESTNUM, 4
    li %r9, -1               /* -1 < 1 in signed */
    li %r10, 1
    cmpd %cr0, %r9, %r10
    bge %cr0, fail           /* Fail if >= */

test_5:
    li TESTNUM, 5
    li %r9, -100
    li %r10, 100
    cmpd %cr0, %r9, %r10
    bge %cr0, fail

    /* Greater than (signed) */
test_6:
    li TESTNUM, 6
    li %r9, 1
    li %r10, -1
    cmpd %cr0, %r9, %r10
    ble %cr0, fail           /* Fail if <= */

test_7:
    li TESTNUM, 7
    li %r9, 100
    li %r10, -100
    cmpd %cr0, %r9, %r10
    ble %cr0, fail

    /* Large 64-bit values */
test_8:
    li TESTNUM, 8
    li %r9, 1
    sldi %r9, %r9, 62        /* Large positive */
    li %r10, 1
    sldi %r10, %r10, 63      /* Large negative (MSB set) */
    cmpd %cr0, %r9, %r10
    ble %cr0, fail           /* r9 > r10 in signed */

test_9:
    li TESTNUM, 9
    li %r9, 1
    sldi %r9, %r9, 63        /* 0x8000000000000000 (MIN_INT64) */
    li %r10, 0
    cmpd %cr0, %r9, %r10
    bge %cr0, fail           /* MIN < 0 */

    /* Using different CR fields */
test_10:
    li TESTNUM, 10
    li %r9, 5
    li %r10, 10
    cmpd %cr7, %r9, %r10
    bge %cr7, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
