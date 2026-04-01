/* OpenPOWER CMPLD (Compare Logical Doubleword) instruction tests */
/* cmpld crfD, rA, rB -> Compare rA with rB as unsigned 64-bit */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Equal values */
test_2:
    li TESTNUM, 2
    li %r9, 100
    li %r10, 100
    cmpld %cr0, %r9, %r10
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    li %r9, -1               /* 0xffffffffffffffff */
    li %r10, -1
    cmpld %cr0, %r9, %r10
    bne %cr0, fail

    /* Less than (unsigned) */
test_4:
    li TESTNUM, 4
    li %r9, 1
    li %r10, -1              /* 0xffffffffffffffff is MAX in unsigned */
    cmpld %cr0, %r9, %r10
    bge %cr0, fail           /* 1 < MAX */

test_5:
    li TESTNUM, 5
    li %r9, 0
    li %r10, 1
    cmpld %cr0, %r9, %r10
    bge %cr0, fail

    /* Greater than (unsigned) */
test_6:
    li TESTNUM, 6
    li %r9, -1               /* MAX in unsigned */
    li %r10, 1
    cmpld %cr0, %r9, %r10
    ble %cr0, fail           /* MAX > 1 */

test_7:
    li TESTNUM, 7
    li %r9, 100
    li %r10, 50
    cmpld %cr0, %r9, %r10
    ble %cr0, fail

    /* Key difference from signed compare */
test_8:
    li TESTNUM, 8
    li %r9, -1               /* In unsigned: 0xffffffffffffffff */
    li %r10, 1
    cmpld %cr0, %r9, %r10    /* Unsigned: -1 > 1 */
    ble %cr0, fail

    /* Large 64-bit unsigned values */
test_9:
    li TESTNUM, 9
    li %r9, 1
    sldi %r9, %r9, 63        /* 0x8000000000000000 */
    li %r10, 1
    sldi %r10, %r10, 62      /* 0x4000000000000000 */
    cmpld %cr0, %r9, %r10
    ble %cr0, fail           /* r9 > r10 in unsigned */

    /* Using different CR fields */
test_10:
    li TESTNUM, 10
    li %r9, 5
    li %r10, 10
    cmpld %cr5, %r9, %r10
    bge %cr5, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
