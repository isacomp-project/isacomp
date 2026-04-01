/* OpenPOWER BC (Branch Conditional) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * BC tests using bne, beq, blt, bgt, ble, bge
     * (These are extended mnemonics for bc)
     *-------------------------------------------------------------*/

    /* Test 2: BEQ taken */
test_2:
    li TESTNUM, 2
    li %r9, 5
    li %r10, 5
    cmpw %cr0, %r9, %r10
    beq %cr0, test_2_pass
    b fail
test_2_pass:

    /* Test 3: BEQ not taken */
test_3:
    li TESTNUM, 3
    li %r9, 5
    li %r10, 6
    cmpw %cr0, %r9, %r10
    beq %cr0, fail
    /* Fall through is correct */

    /* Test 4: BNE taken */
test_4:
    li TESTNUM, 4
    li %r9, 5
    li %r10, 6
    cmpw %cr0, %r9, %r10
    bne %cr0, test_4_pass
    b fail
test_4_pass:

    /* Test 5: BNE not taken */
test_5:
    li TESTNUM, 5
    li %r9, 5
    li %r10, 5
    cmpw %cr0, %r9, %r10
    bne %cr0, fail

    /* Test 6: BLT taken */
test_6:
    li TESTNUM, 6
    li %r9, 3
    li %r10, 5
    cmpw %cr0, %r9, %r10
    blt %cr0, test_6_pass
    b fail
test_6_pass:

    /* Test 7: BLT not taken (equal) */
test_7:
    li TESTNUM, 7
    li %r9, 5
    li %r10, 5
    cmpw %cr0, %r9, %r10
    blt %cr0, fail

    /* Test 8: BLT not taken (greater) */
test_8:
    li TESTNUM, 8
    li %r9, 7
    li %r10, 5
    cmpw %cr0, %r9, %r10
    blt %cr0, fail

    /* Test 9: BGT taken */
test_9:
    li TESTNUM, 9
    li %r9, 7
    li %r10, 5
    cmpw %cr0, %r9, %r10
    bgt %cr0, test_9_pass
    b fail
test_9_pass:

    /* Test 10: BGT not taken (equal) */
test_10:
    li TESTNUM, 10
    li %r9, 5
    li %r10, 5
    cmpw %cr0, %r9, %r10
    bgt %cr0, fail

    /* Test 11: BGT not taken (less) */
test_11:
    li TESTNUM, 11
    li %r9, 3
    li %r10, 5
    cmpw %cr0, %r9, %r10
    bgt %cr0, fail

    /* Test 12: BLE taken (equal) */
test_12:
    li TESTNUM, 12
    li %r9, 5
    li %r10, 5
    cmpw %cr0, %r9, %r10
    ble %cr0, test_12_pass
    b fail
test_12_pass:

    /* Test 13: BLE taken (less) */
test_13:
    li TESTNUM, 13
    li %r9, 3
    li %r10, 5
    cmpw %cr0, %r9, %r10
    ble %cr0, test_13_pass
    b fail
test_13_pass:

    /* Test 14: BLE not taken */
test_14:
    li TESTNUM, 14
    li %r9, 7
    li %r10, 5
    cmpw %cr0, %r9, %r10
    ble %cr0, fail

    /* Test 15: BGE taken (equal) */
test_15:
    li TESTNUM, 15
    li %r9, 5
    li %r10, 5
    cmpw %cr0, %r9, %r10
    bge %cr0, test_15_pass
    b fail
test_15_pass:

    /* Test 16: BGE taken (greater) */
test_16:
    li TESTNUM, 16
    li %r9, 7
    li %r10, 5
    cmpw %cr0, %r9, %r10
    bge %cr0, test_16_pass
    b fail
test_16_pass:

    /* Test 17: BGE not taken */
test_17:
    li TESTNUM, 17
    li %r9, 3
    li %r10, 5
    cmpw %cr0, %r9, %r10
    bge %cr0, fail

    /* Test 18: Use different CR field */
test_18:
    li TESTNUM, 18
    li %r9, 10
    li %r10, 5
    cmpw %cr1, %r9, %r10
    ble %cr1, fail
    bgt %cr1, test_18_pass
    b fail
test_18_pass:

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
