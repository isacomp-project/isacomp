/*
 * Alpha BNE (Branch if Not Equal to Zero) Test
 * Tests conditional branching when Ra != 0
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * BNE taken tests (Ra != 0)
     *-------------------------------------------------------------*/

    /* Test 1: BNE taken when Ra = 1 */
    TEST_CASE_START(1)
    lda $1, 1($31)
    bne $1, 1f
    br $31, fail      /* Should not reach here */
1:

    /* Test 2: BNE taken when Ra = -1 */
    TEST_CASE_START(2)
    lda $1, -1($31)
    bne $1, 1f
    br $31, fail      /* Should not reach here */
1:

    /* Test 3: BNE taken when Ra = 255 */
    TEST_CASE_START(3)
    lda $1, 255($31)
    bne $1, 1f
    br $31, fail      /* Should not reach here */
1:

    /*-------------------------------------------------------------
     * BNE not taken tests (Ra == 0)
     *-------------------------------------------------------------*/

    /* Test 4: BNE not taken when Ra = 0 */
    TEST_CASE_START(4)
    lda $1, 0($31)
    bne $1, 1f
    br $31, 2f        /* Should take this branch */
1:  br $31, fail      /* Should not reach here */
2:

    /* Test 5: BNE not taken when Ra = R31 */
    TEST_CASE_START(5)
    bne $31, 1f
    br $31, 2f        /* Should take this branch */
1:  br $31, fail      /* Should not reach here */
2:

    /*-------------------------------------------------------------
     * Loop test using BNE
     *-------------------------------------------------------------*/

    /* Test 6: Count down loop */
    TEST_CASE_START(6)
    lda $1, 5($31)    /* Counter = 5 */
    lda $2, 0($31)    /* Accumulator = 0 */
loop:
    addq $2, $1, $2   /* acc += counter */
    subq $1, 1, $1    /* counter-- */
    bne $1, loop      /* Loop while counter != 0 */
    /* After loop: 5+4+3+2+1 = 15 */
    lda $5, 15($31)
    cmpeq $2, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * All tests passed - fall through to ALPHA_TEST_END
     *-------------------------------------------------------------*/

ALPHA_TEST_END
