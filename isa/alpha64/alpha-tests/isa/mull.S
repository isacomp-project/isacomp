/*
 * Alpha MULL (Multiply Longword) Test
 * Rc = sign_extend((Ra * Rb)[31:0])
 * Result is sign-extended from 32 bits to 64 bits
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic multiplication
     *-------------------------------------------------------------*/

    /* Test 1: 0 * 0 = 0 */
    TEST_CASE_START(1)
    lda $1, 0($31)
    lda $2, 0($31)
    mull $1, $2, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: 1 * 1 = 1 */
    TEST_CASE_START(2)
    lda $1, 1($31)
    lda $2, 1($31)
    mull $1, $2, $3
    lda $5, 1($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: 5 * 0 = 0 */
    TEST_CASE_START(3)
    lda $1, 5($31)
    lda $2, 0($31)
    mull $1, $2, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: 3 * 4 = 12 */
    TEST_CASE_START(4)
    lda $1, 3($31)
    lda $2, 4($31)
    mull $1, $2, $3
    lda $5, 12($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 5: 7 * 8 = 56 */
    TEST_CASE_START(5)
    lda $1, 7($31)
    lda $2, 8($31)
    mull $1, $2, $3
    lda $5, 56($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Negative values
     *-------------------------------------------------------------*/

    /* Test 6: -1 * 5 = -5 */
    TEST_CASE_START(6)
    lda $1, -1($31)
    lda $2, 5($31)
    mull $1, $2, $3
    lda $5, -5($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 7: -3 * -4 = 12 */
    TEST_CASE_START(7)
    lda $1, -3($31)
    lda $2, -4($31)
    mull $1, $2, $3
    lda $5, 12($31)
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
