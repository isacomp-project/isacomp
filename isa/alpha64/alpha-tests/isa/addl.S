/*
 * Alpha ADDL (Add Longword) Test
 * Rc = sign_extend((Ra + Rb)[31:0])
 * Result is sign-extended from 32 bits to 64 bits
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic 32-bit addition
     *-------------------------------------------------------------*/

    /* Test 1: 0 + 0 = 0 */
    TEST_CASE_START(1)
    lda $1, 0($31)
    lda $2, 0($31)
    addl $1, $2, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: 1 + 1 = 2 */
    TEST_CASE_START(2)
    lda $1, 1($31)
    lda $2, 1($31)
    addl $1, $2, $3
    lda $5, 2($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: 100 + 200 = 300 */
    TEST_CASE_START(3)
    lda $1, 100($31)
    lda $2, 200($31)
    addl $1, $2, $3
    lda $5, 300($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: -1 + 1 = 0 */
    TEST_CASE_START(4)
    lda $1, -1($31)
    lda $2, 1($31)
    addl $1, $2, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Immediate form
     *-------------------------------------------------------------*/

    /* Test 5: 10 + 5 = 15 (immediate) */
    TEST_CASE_START(5)
    lda $1, 10($31)
    addl $1, 5, $3
    lda $5, 15($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Negative results (sign extension)
     *-------------------------------------------------------------*/

    /* Test 6: -10 + -20 = -30 */
    TEST_CASE_START(6)
    lda $1, -10($31)
    lda $2, -20($31)
    addl $1, $2, $3
    lda $5, -30($31)
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
