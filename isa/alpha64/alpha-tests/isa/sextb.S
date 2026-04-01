/*
 * Alpha SEXTB (Sign Extend Byte) Test
 * Rc = sign_extend(Rb[7:0])
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Positive byte values (bit 7 = 0)
     *-------------------------------------------------------------*/

    /* Test 1: sextb 0 = 0 */
    TEST_CASE_START(1)
    lda $1, 0($31)
    sextb $1, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: sextb 1 = 1 */
    TEST_CASE_START(2)
    lda $1, 1($31)
    sextb $1, $3
    lda $5, 1($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: sextb 127 = 127 (max positive byte) */
    TEST_CASE_START(3)
    lda $1, 127($31)
    sextb $1, $3
    lda $5, 127($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Negative byte values (bit 7 = 1)
     *-------------------------------------------------------------*/

    /* Test 4: sextb 0x80 (128) = -128 */
    TEST_CASE_START(4)
    lda $1, 128($31)
    sextb $1, $3
    lda $5, -128($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 5: sextb 0xFF (255) = -1 */
    TEST_CASE_START(5)
    lda $1, 255($31)
    sextb $1, $3
    lda $5, -1($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 6: sextb 0xFE (254) = -2 */
    TEST_CASE_START(6)
    lda $1, 254($31)
    sextb $1, $3
    lda $5, -2($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Only low byte matters
     *-------------------------------------------------------------*/

    /* Test 7: sextb 0x100 (256) = 0 (only low byte used) */
    TEST_CASE_START(7)
    lda $1, 256($31)
    sextb $1, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
