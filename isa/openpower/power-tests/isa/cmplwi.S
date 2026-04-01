/* OpenPOWER CMPLWI (Compare Logical Word Immediate) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * CMPLWI tests - cmplwi BF, rA, UIMM (unsigned comparison)
     * Note: UIMM is 16-bit (0 to 0x7fff in assembler syntax)
     *-------------------------------------------------------------*/

    /* Equal values */
test_2:
    li TESTNUM, 2
    li %r9, 0
    cmplwi %cr0, %r9, 0
    bne %cr0, fail

test_3:
    li TESTNUM, 3
    li %r9, 1
    cmplwi %cr0, %r9, 1
    bne %cr0, fail

test_4:
    li TESTNUM, 4
    li %r9, 0x7fff
    cmplwi %cr0, %r9, 0x7fff
    bne %cr0, fail

    /* Less than */
test_5:
    li TESTNUM, 5
    li %r9, 0
    cmplwi %cr0, %r9, 1
    bge %cr0, fail

test_6:
    li TESTNUM, 6
    li %r9, 100
    cmplwi %cr0, %r9, 200
    bge %cr0, fail

test_7:
    li TESTNUM, 7
    li %r9, 0x1000
    cmplwi %cr0, %r9, 0x7fff
    bge %cr0, fail

    /* Greater than */
test_8:
    li TESTNUM, 8
    li %r9, 1
    cmplwi %cr0, %r9, 0
    ble %cr0, fail

test_9:
    li TESTNUM, 9
    li %r9, 200
    cmplwi %cr0, %r9, 100
    ble %cr0, fail

test_10:
    li TESTNUM, 10
    li %r9, 0x7fff
    cmplwi %cr0, %r9, 0x1000
    ble %cr0, fail

    /* Large values (unsigned) - register can hold large values */
test_11:
    li TESTNUM, 11
    LOAD_IMM(%r9, 0x80000000)
    cmplwi %cr0, %r9, 0
    ble %cr0, fail      /* 0x80000000 > 0 (unsigned) */

test_12:
    li TESTNUM, 12
    LOAD_IMM(%r9, 0xffffffff)
    cmplwi %cr0, %r9, 0x7fff
    ble %cr0, fail      /* 0xffffffff > 0x7fff (unsigned) */

test_13:
    li TESTNUM, 13
    li %r9, 0
    cmplwi %cr0, %r9, 0x7fff
    bge %cr0, fail      /* 0 < 0x7fff */

    /* Values that differ in signed vs unsigned */
test_14:
    li TESTNUM, 14
    li %r9, -1          /* 0xffffffff in register */
    cmplwi %cr0, %r9, 1
    ble %cr0, fail      /* 0xffffffff > 1 (unsigned) */

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
