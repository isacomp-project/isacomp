/*
 * Alpha S8ADDQ (Scaled Add Quadword by 8) Test
 * Rc = (Ra * 8) + Rb
 * Useful for array indexing with 8-byte elements (quadwords)
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic scaled addition
     *-------------------------------------------------------------*/

    /* Test 1: 0*8 + 0 = 0 */
    TEST_CASE_START(1)
    lda $1, 0($31)
    lda $2, 0($31)
    s8addq $1, $2, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: 1*8 + 0 = 8 */
    TEST_CASE_START(2)
    lda $1, 1($31)
    lda $2, 0($31)
    s8addq $1, $2, $3
    lda $5, 8($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: 2*8 + 10 = 26 */
    TEST_CASE_START(3)
    lda $1, 2($31)
    lda $2, 10($31)
    s8addq $1, $2, $3
    lda $5, 26($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: 5*8 + 100 = 140 */
    TEST_CASE_START(4)
    lda $1, 5($31)
    lda $2, 100($31)
    s8addq $1, $2, $3
    lda $5, 140($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 5: 10*8 + 0 = 80 */
    TEST_CASE_START(5)
    lda $1, 10($31)
    lda $2, 0($31)
    s8addq $1, $2, $3
    lda $5, 80($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Negative values
     *-------------------------------------------------------------*/

    /* Test 6: (-1)*8 + 16 = 8 */
    TEST_CASE_START(6)
    lda $1, -1($31)
    lda $2, 16($31)
    s8addq $1, $2, $3
    lda $5, 8($31)
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
