/*
 * Alpha S4ADDQ (Scaled Add Quadword by 4) Test
 * Rc = (Ra * 4) + Rb
 * Useful for array indexing with 4-byte elements
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic scaled addition
     *-------------------------------------------------------------*/

    /* Test 1: 0*4 + 0 = 0 */
    TEST_CASE_START(1)
    lda $1, 0($31)
    lda $2, 0($31)
    s4addq $1, $2, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: 1*4 + 0 = 4 */
    TEST_CASE_START(2)
    lda $1, 1($31)
    lda $2, 0($31)
    s4addq $1, $2, $3
    lda $5, 4($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: 2*4 + 10 = 18 */
    TEST_CASE_START(3)
    lda $1, 2($31)
    lda $2, 10($31)
    s4addq $1, $2, $3
    lda $5, 18($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: 5*4 + 100 = 120 */
    TEST_CASE_START(4)
    lda $1, 5($31)
    lda $2, 100($31)
    s4addq $1, $2, $3
    lda $5, 120($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 5: 10*4 + 0 = 40 */
    TEST_CASE_START(5)
    lda $1, 10($31)
    lda $2, 0($31)
    s4addq $1, $2, $3
    lda $5, 40($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Negative values
     *-------------------------------------------------------------*/

    /* Test 6: (-1)*4 + 8 = 4 */
    TEST_CASE_START(6)
    lda $1, -1($31)
    lda $2, 8($31)
    s4addq $1, $2, $3
    lda $5, 4($31)
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
