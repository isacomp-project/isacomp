/*
 * Alpha CMPLE (Compare Signed Less Than or Equal) Test
 * Rc = (Ra <= Rb) ? 1 : 0 (signed comparison)
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic signed comparisons
     *-------------------------------------------------------------*/

    /* Test 1: 0 <= 1 = true */
    TEST_CASE_START(1)
    lda $1, 0($31)
    lda $2, 1($31)
    cmple $1, $2, $3
    lda $5, 1($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: 1 <= 0 = false */
    TEST_CASE_START(2)
    lda $1, 1($31)
    lda $2, 0($31)
    cmple $1, $2, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: 5 <= 5 = true (equal) */
    TEST_CASE_START(3)
    lda $1, 5($31)
    lda $2, 5($31)
    cmple $1, $2, $3
    lda $5, 1($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: -1 <= 0 = true (negative <= positive) */
    TEST_CASE_START(4)
    lda $1, -1($31)
    lda $2, 0($31)
    cmple $1, $2, $3
    lda $5, 1($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 5: 0 <= -1 = false (positive not <= negative) */
    TEST_CASE_START(5)
    lda $1, 0($31)
    lda $2, -1($31)
    cmple $1, $2, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 6: -10 <= -5 = true */
    TEST_CASE_START(6)
    lda $1, -10($31)
    lda $2, -5($31)
    cmple $1, $2, $3
    lda $5, 1($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 7: -5 <= -10 = false */
    TEST_CASE_START(7)
    lda $1, -5($31)
    lda $2, -10($31)
    cmple $1, $2, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
