/* OpenPOWER CMPLDI (Compare Logical Doubleword Immediate) instruction tests */
/* cmpldi crfD, rA, UIMM -> Compare rA with zero-extended UIMM as unsigned 64-bit */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Equal values */
test_2:
    li TESTNUM, 2
    li %r9, 100
    cmpldi %cr0, %r9, 100
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    li %r9, 0
    cmpldi %cr0, %r9, 0
    bne %cr0, fail

    /* Less than (unsigned) */
test_4:
    li TESTNUM, 4
    li %r9, 50
    cmpldi %cr0, %r9, 100
    bge %cr0, fail

test_5:
    li TESTNUM, 5
    li %r9, 0
    cmpldi %cr0, %r9, 1
    bge %cr0, fail

    /* Greater than (unsigned) */
test_6:
    li TESTNUM, 6
    li %r9, 100
    cmpldi %cr0, %r9, 50
    ble %cr0, fail

test_7:
    li TESTNUM, 7
    li %r9, -1               /* 0xffffffffffffffff (MAX) */
    cmpldi %cr0, %r9, 100
    ble %cr0, fail           /* MAX > 100 */

    /* Large value compared to small immediate */
test_8:
    li TESTNUM, 8
    li %r9, 1
    sldi %r9, %r9, 40        /* Large 64-bit value */
    cmpldi %cr0, %r9, 0x7fff
    ble %cr0, fail

    /* Boundary immediate values */
test_9:
    li TESTNUM, 9
    li %r9, 0x7fff
    cmpldi %cr0, %r9, 0x7fff
    bne %cr0, fail

    /* Zero vs non-zero */
test_10:
    li TESTNUM, 10
    li %r9, 0
    cmpldi %cr0, %r9, 0x100
    bge %cr0, fail

    /* Using different CR fields */
test_11:
    li TESTNUM, 11
    li %r9, 5
    cmpldi %cr4, %r9, 10
    bge %cr4, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
