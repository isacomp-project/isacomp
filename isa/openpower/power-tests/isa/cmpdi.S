/* OpenPOWER CMPDI (Compare Doubleword Immediate) instruction tests */
/* cmpdi crfD, rA, SIMM -> Compare rA with sign-extended SIMM as signed 64-bit */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Equal values */
test_2:
    li TESTNUM, 2
    li %r9, 100
    cmpdi %cr0, %r9, 100
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    li %r9, -1
    cmpdi %cr0, %r9, -1
    bne %cr0, fail

test_4:
    li TESTNUM, 4
    li %r9, 0
    cmpdi %cr0, %r9, 0
    bne %cr0, fail

    /* Less than */
test_5:
    li TESTNUM, 5
    li %r9, -100
    cmpdi %cr0, %r9, 100
    bge %cr0, fail

test_6:
    li TESTNUM, 6
    li %r9, 50
    cmpdi %cr0, %r9, 100
    bge %cr0, fail

    /* Greater than */
test_7:
    li TESTNUM, 7
    li %r9, 100
    cmpdi %cr0, %r9, 50
    ble %cr0, fail

test_8:
    li TESTNUM, 8
    li %r9, 100
    cmpdi %cr0, %r9, -100
    ble %cr0, fail

    /* Boundary immediate values */
test_9:
    li TESTNUM, 9
    LOAD_IMM(%r9, 0x7fff)
    cmpdi %cr0, %r9, 0x7fff   /* Max positive immediate */
    bne %cr0, fail

test_10:
    li TESTNUM, 10
    li %r9, -0x8000           /* Min negative immediate */
    cmpdi %cr0, %r9, -0x8000
    bne %cr0, fail

    /* 64-bit value compared to small immediate */
test_11:
    li TESTNUM, 11
    li %r9, 1
    sldi %r9, %r9, 40        /* Large 64-bit value */
    cmpdi %cr0, %r9, 100
    ble %cr0, fail           /* Large > small */

    /* Using different CR fields */
test_12:
    li TESTNUM, 12
    li %r9, 5
    cmpdi %cr6, %r9, 10
    bge %cr6, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
