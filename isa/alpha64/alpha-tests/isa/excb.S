/*
 * Alpha EXCB (Exception Barrier) Test
 * Tests exception barrier instruction
 *
 * EXCB is similar to TRAPB but specifically ensures that
 * all previous instructions have completed exception processing
 * before any subsequent instructions that depend on exception state.
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Exception barrier tests
     * These mainly verify the instruction doesn't crash
     *-------------------------------------------------------------*/

    /* Test 2: Simple EXCB */
    TEST_BARRIER(2, excb)

    /* Test 3: EXCB after arithmetic */
    TEST_CASE_START(3)
    lda $1, 7($31)
    lda $2, 8($31)
    mulq $1, $2, $3
    excb
    /* Verify result = 56 */
    lda $5, 56($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: Multiple EXCBs in sequence */
    TEST_CASE_START(4)
    excb
    excb
    excb

    /* Test 5: EXCB after shifts (potential exception sources) */
    TEST_CASE_START(5)
    lda $1, 1($31)
    sll $1, 4, $2       /* 16 */
    excb
    srl $2, 2, $3       /* 4 */
    excb
    lda $5, 4($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 6: EXCB with memory operations */
    TEST_CASE_START(6)
    lda $1, scratch_excb($31)
    lda $2, 0xBEEF($31)
    stl $2, 0($1)
    excb
    ldl $3, 0($1)
    excb
    cmpeq $2, $3, $6
    beq $6, fail

ALPHA_TEST_END

    .data
    .align 3
scratch_excb:
    .space 16
