/* OpenPOWER B (Branch) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * B (unconditional branch) tests
     *-------------------------------------------------------------*/

    /* Test 2: Simple forward branch */
test_2:
    li TESTNUM, 2
    b test_2_target
    b fail              /* Should never execute */
test_2_target:

    /* Test 3: Branch over multiple instructions */
test_3:
    li TESTNUM, 3
    b test_3_target
    b fail
    b fail
    b fail
test_3_target:

    /* Test 4: Multiple branches in sequence */
test_4:
    li TESTNUM, 4
    li %r9, 0
    b test_4a
    b fail
test_4a:
    addi %r9, %r9, 1
    b test_4b
    b fail
test_4b:
    addi %r9, %r9, 1
    b test_4c
    b fail
test_4c:
    addi %r9, %r9, 1
    b test_4d
    b fail
test_4d:
    /* r9 should be 3 */
    li %r25, 3
    cmpw %cr0, %r9, %r25
    bne %cr0, fail

    /* Test 5: Branch backwards */
test_5:
    li TESTNUM, 5
    li %r9, 0
    b test_5_start
test_5_back:
    addi %r9, %r9, 1
    li %r25, 1
    cmpw %cr0, %r9, %r25
    bne %cr0, fail
    b test_5_end
test_5_start:
    b test_5_back
    b fail
test_5_end:

    /* Test 6: Longer forward branch */
test_6:
    li TESTNUM, 6
    li %r9, 0
    b test_6_far
    /* Put some filler instructions */
    addi %r9, %r9, 1
    addi %r9, %r9, 1
    addi %r9, %r9, 1
    addi %r9, %r9, 1
    addi %r9, %r9, 1
    addi %r9, %r9, 1
    addi %r9, %r9, 1
    addi %r9, %r9, 1
    b fail
test_6_far:
    /* r9 should still be 0 */
    li %r25, 0
    cmpw %cr0, %r9, %r25
    bne %cr0, fail

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
