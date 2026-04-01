/*
 * Alpha TRAPB (Trap Barrier) Test
 * Tests trap barrier instruction
 *
 * TRAPB guarantees that all previous instructions have completed
 * without raising any exceptions before any subsequent instructions begin.
 * Used before exception-prone operations.
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Trap barrier tests
     * These mainly verify the instruction doesn't crash
     *-------------------------------------------------------------*/

    /* Test 2: Simple TRAPB */
    TEST_BARRIER(2, trapb)

    /* Test 3: TRAPB after arithmetic */
    TEST_CASE_START(3)
    lda $1, 10($31)
    lda $2, 20($31)
    addq $1, $2, $3
    trapb
    /* Verify result */
    lda $5, 30($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: Multiple TRAPBs in sequence */
    TEST_CASE_START(4)
    trapb
    trapb
    trapb

    /* Test 5: TRAPB after memory operations */
    TEST_CASE_START(5)
    lda $1, scratch_trapb($31)
    lda $2, 0x9999($31)
    stl $2, 0($1)
    ldl $3, 0($1)
    trapb

    /* Test 6: TRAPB in computation sequence */
    TEST_CASE_START(6)
    lda $1, 5($31)
    mulq $1, $1, $2     /* 25 */
    trapb
    addq $2, $1, $3     /* 30 */
    trapb
    lda $5, 30($31)
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END

    .data
    .align 3
scratch_trapb:
    .space 16
