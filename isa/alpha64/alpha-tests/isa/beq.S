/*
 * Alpha BEQ (Branch if Equal to Zero) Test
 * Tests conditional branching when Ra == 0
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * BEQ taken tests (Ra == 0)
     *-------------------------------------------------------------*/

    /* Test 1: BEQ taken when Ra = 0 */
    TEST_CASE_START(1)
    lda $1, 0($31)
    beq $1, 1f
    br $31, fail      /* Should not reach here */
1:

    /* Test 2: BEQ taken when Ra = R31 (always 0) */
    TEST_CASE_START(2)
    beq $31, 1f
    br $31, fail      /* Should not reach here */
1:

    /*-------------------------------------------------------------
     * BEQ not taken tests (Ra != 0)
     *-------------------------------------------------------------*/

    /* Test 3: BEQ not taken when Ra = 1 */
    TEST_CASE_START(3)
    lda $1, 1($31)
    beq $1, 1f
    br $31, 2f        /* Should take this branch */
1:  br $31, fail      /* Should not reach here */
2:

    /* Test 4: BEQ not taken when Ra = -1 */
    TEST_CASE_START(4)
    lda $1, -1($31)
    beq $1, 1f
    br $31, 2f        /* Should take this branch */
1:  br $31, fail      /* Should not reach here */
2:

    /* Test 5: BEQ not taken when Ra = 100 */
    TEST_CASE_START(5)
    lda $1, 100($31)
    beq $1, 1f
    br $31, 2f        /* Should take this branch */
1:  br $31, fail      /* Should not reach here */
2:

    /*-------------------------------------------------------------
     * Forward and backward branch tests
     *-------------------------------------------------------------*/

    /* Test 6: Forward branch */
    TEST_CASE_START(6)
    lda $1, 0($31)
    beq $1, forward_target
    br $31, fail
forward_target:

    /* Test 7: Set up for backward branch test */
    TEST_CASE_START(7)
    lda $2, 0($31)    /* Counter */
    lda $3, 3($31)    /* Target count */
    br $31, loop_entry
loop_start:
    addq $2, 1, $2
loop_entry:
    cmplt $2, $3, $1  /* $1 = ($2 < 3) ? 1 : 0 */
    bne $1, loop_start
    /* After loop, $2 should be 3 */
    lda $5, 3($31)
    cmpeq $2, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * All tests passed - fall through to ALPHA_TEST_END
     *-------------------------------------------------------------*/

ALPHA_TEST_END
