/*
 * Alpha SEXTW (Sign Extend Word) Test
 * Rc = sign_extend(Rb[15:0])
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Positive halfword values (bit 15 = 0)
     *-------------------------------------------------------------*/

    /* Test 1: sextw 0 = 0 */
    TEST_CASE_START(1)
    lda $1, 0($31)
    sextw $1, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: sextw 1 = 1 */
    TEST_CASE_START(2)
    lda $1, 1($31)
    sextw $1, $3
    lda $5, 1($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: sextw 32767 = 32767 (max positive 16-bit) */
    TEST_CASE_START(3)
    lda $1, 32767($31)
    sextw $1, $3
    lda $5, 32767($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Negative halfword values (bit 15 = 1)
     * Note: lda sign-extends 16-bit displacement, so we use
     * negative values directly which are already sign-extended
     *-------------------------------------------------------------*/

    /* Test 4: sextw -1 = -1 */
    TEST_CASE_START(4)
    lda $1, -1($31)
    sextw $1, $3
    lda $5, -1($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 5: sextw -100 = -100 */
    TEST_CASE_START(5)
    lda $1, -100($31)
    sextw $1, $3
    lda $5, -100($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 6: sextw -32768 = -32768 (min 16-bit signed) */
    TEST_CASE_START(6)
    lda $1, -32768($31)
    sextw $1, $3
    lda $5, -32768($31)
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
