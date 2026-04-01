/*
 * Alpha MULQ (Multiply Quadword) Test
 * Tests 64-bit integer multiplication (low 64 bits of result)
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic multiplication tests
     *-------------------------------------------------------------*/

    /* Test 1: 0 * 0 = 0 */
    TEST_CASE_START(1)
    lda $1, 0($31)
    lda $2, 0($31)
    mulq $1, $2, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: 1 * 1 = 1 */
    TEST_CASE_START(2)
    lda $1, 1($31)
    lda $2, 1($31)
    mulq $1, $2, $3
    lda $5, 1($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: 2 * 3 = 6 */
    TEST_CASE_START(3)
    lda $1, 2($31)
    lda $2, 3($31)
    mulq $1, $2, $3
    lda $5, 6($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: 5 * 10 = 50 */
    TEST_CASE_START(4)
    lda $1, 5($31)
    lda $2, 10($31)
    mulq $1, $2, $3
    lda $5, 50($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 5: 12 * 12 = 144 */
    TEST_CASE_START(5)
    lda $1, 12($31)
    lda $2, 12($31)
    mulq $1, $2, $3
    lda $5, 144($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 6: 100 * 0 = 0 */
    TEST_CASE_START(6)
    lda $1, 100($31)
    lda $2, 0($31)
    mulq $1, $2, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Immediate operand tests
     *-------------------------------------------------------------*/

    /* Test 7: MULQ with immediate - 7 * 8 = 56 */
    TEST_CASE_START(7)
    lda $1, 7($31)
    mulq $1, 8, $3
    lda $5, 56($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 8: MULQ with immediate - 25 * 4 = 100 */
    TEST_CASE_START(8)
    lda $1, 25($31)
    mulq $1, 4, $3
    lda $5, 100($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Negative number tests
     *-------------------------------------------------------------*/

    /* Test 9: -1 * 5 = -5 */
    TEST_CASE_START(9)
    lda $1, -1($31)
    lda $2, 5($31)
    mulq $1, $2, $3
    lda $5, -5($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 10: -2 * -3 = 6 */
    TEST_CASE_START(10)
    lda $1, -2($31)
    lda $2, -3($31)
    mulq $1, $2, $3
    lda $5, 6($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * All tests passed - fall through to ALPHA_TEST_END
     *-------------------------------------------------------------*/

ALPHA_TEST_END
