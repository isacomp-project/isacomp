/*
 * Alpha S8SUBQ (Scaled Subtract Quadword by 8) Test
 * Rc = (Ra * 8) - Rb
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic scaled subtraction
     *-------------------------------------------------------------*/

    /* Test 1: 0*8 - 0 = 0 */
    TEST_CASE_START(1)
    lda $1, 0($31)
    lda $2, 0($31)
    s8subq $1, $2, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: 1*8 - 0 = 8 */
    TEST_CASE_START(2)
    lda $1, 1($31)
    lda $2, 0($31)
    s8subq $1, $2, $3
    lda $5, 8($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: 5*8 - 20 = 20 */
    TEST_CASE_START(3)
    lda $1, 5($31)
    lda $2, 20($31)
    s8subq $1, $2, $3
    lda $5, 20($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: 10*8 - 30 = 50 */
    TEST_CASE_START(4)
    lda $1, 10($31)
    lda $2, 30($31)
    s8subq $1, $2, $3
    lda $5, 50($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 5: 2*8 - 20 = -4 */
    TEST_CASE_START(5)
    lda $1, 2($31)
    lda $2, 20($31)
    s8subq $1, $2, $3
    lda $5, -4($31)
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
