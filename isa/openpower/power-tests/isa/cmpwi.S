/* OpenPOWER CMPWI (Compare Word Immediate) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * CMPWI tests - cmpwi BF, rA, SIMM (signed comparison)
     * SIMM is sign-extended to 32 bits
     *-------------------------------------------------------------*/

    /* Equal values */
test_2:
    li TESTNUM, 2
    li %r9, 0
    cmpwi %cr0, %r9, 0
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    li %r9, 1
    cmpwi %cr0, %r9, 1
    bne %cr0, fail

test_4:
    li TESTNUM, 4
    li %r9, -1
    cmpwi %cr0, %r9, -1
    bne %cr0, fail

test_5:
    li TESTNUM, 5
    li %r9, 0x7fff
    cmpwi %cr0, %r9, 0x7fff
    bne %cr0, fail

    /* Less than */
test_6:
    li TESTNUM, 6
    li %r9, 0
    cmpwi %cr0, %r9, 1
    bge %cr0, fail

test_7:
    li TESTNUM, 7
    li %r9, -1
    cmpwi %cr0, %r9, 0
    bge %cr0, fail

test_8:
    li TESTNUM, 8
    li %r9, -2
    cmpwi %cr0, %r9, -1
    bge %cr0, fail

test_9:
    li TESTNUM, 9
    li %r9, 100
    cmpwi %cr0, %r9, 200
    bge %cr0, fail

    /* Greater than */
test_10:
    li TESTNUM, 10
    li %r9, 1
    cmpwi %cr0, %r9, 0
    ble %cr0, fail

test_11:
    li TESTNUM, 11
    li %r9, 0
    cmpwi %cr0, %r9, -1
    ble %cr0, fail

test_12:
    li TESTNUM, 12
    li %r9, -1
    cmpwi %cr0, %r9, -2
    ble %cr0, fail

test_13:
    li TESTNUM, 13
    li %r9, 200
    cmpwi %cr0, %r9, 100
    ble %cr0, fail

    /* Negative immediate */
test_14:
    li TESTNUM, 14
    li %r9, -100
    cmpwi %cr0, %r9, -100
    bne %cr0, fail

test_15:
    li TESTNUM, 15
    li %r9, -50
    cmpwi %cr0, %r9, -100
    ble %cr0, fail      /* -50 > -100 */

    /* Large values */
test_16:
    li TESTNUM, 16
    LOAD_IMM(%r9, 0x80000000)
    cmpwi %cr0, %r9, 0
    bge %cr0, fail      /* 0x80000000 is negative, should be < 0 */

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
