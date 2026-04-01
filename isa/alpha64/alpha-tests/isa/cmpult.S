/*
 * Alpha CMPULT (Compare Unsigned Less Than) Test
 * Rc = (Ra < Rb) ? 1 : 0 (unsigned comparison)
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic unsigned comparisons
     *-------------------------------------------------------------*/

    /* Test 1: 0 < 1 = true */
    TEST_CASE_START(1)
    lda $1, 0($31)
    lda $2, 1($31)
    cmpult $1, $2, $3
    lda $5, 1($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: 1 < 0 = false */
    TEST_CASE_START(2)
    lda $1, 1($31)
    lda $2, 0($31)
    cmpult $1, $2, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: 5 < 5 = false (equal) */
    TEST_CASE_START(3)
    lda $1, 5($31)
    lda $2, 5($31)
    cmpult $1, $2, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: 10 < 20 = true */
    TEST_CASE_START(4)
    lda $1, 10($31)
    lda $2, 20($31)
    cmpult $1, $2, $3
    lda $5, 1($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Unsigned behavior with "negative" values
     * In unsigned, -1 (all 1s) is the largest value
     *-------------------------------------------------------------*/

    /* Test 5: 0 < -1 = true (0 < max unsigned) */
    TEST_CASE_START(5)
    lda $1, 0($31)
    lda $2, -1($31)
    cmpult $1, $2, $3
    lda $5, 1($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 6: -1 < 0 = false (max unsigned not < 0) */
    TEST_CASE_START(6)
    lda $1, -1($31)
    lda $2, 0($31)
    cmpult $1, $2, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 7: 100 < -1 = true (100 < max unsigned) */
    TEST_CASE_START(7)
    lda $1, 100($31)
    lda $2, -1($31)
    cmpult $1, $2, $3
    lda $5, 1($31)
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
