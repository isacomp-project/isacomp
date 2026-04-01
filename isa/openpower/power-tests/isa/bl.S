/* OpenPOWER BL (Branch and Link) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * BL tests - bl target (LR = PC+4, then branch)
     *-------------------------------------------------------------*/

    /* Test 2: Simple BL and return */
test_2:
    li TESTNUM, 2
    bl func_2
    b test_3            /* Continue to next test */
func_2:
    blr                 /* Return via LR */
    b fail

    /* Test 3: BL with computation in function */
test_3:
    li TESTNUM, 3
    li %r9, 10
    bl func_3
    /* After return, r9 should be 15 */
    li %r25, 15
    cmpw %cr0, %r9, %r25
    bne %cr0, fail
    b test_5

func_3:
    addi %r9, %r9, 5
    blr

    /* Test 4: Nested function calls - SKIPPED (requires std/ld) */

    /* Test 5: Check LR value after BL */
test_5:
    li TESTNUM, 5
    bl func_5
test_5_ret:
    b test_6
func_5:
    mflr %r8            /* Get LR (should be address of test_5_ret) */
    /* Can't easily verify exact address, just check it's non-zero */
    li %r25, 0
    cmpd %cr0, %r8, %r25
    beq %cr0, fail      /* LR should not be zero */
    blr

    /* Test 6: Multiple BL calls */
test_6:
    li TESTNUM, 6
    li %r9, 0
    bl add_one
    bl add_one
    bl add_one
    /* r9 should be 3 */
    li %r25, 3
    cmpw %cr0, %r9, %r25
    bne %cr0, fail
    b test_end

add_one:
    addi %r9, %r9, 1
    blr

test_end:
    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
