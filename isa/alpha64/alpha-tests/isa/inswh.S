/*
 * Alpha INSWH (Insert Word High) Test
 * Rc = bv ? (Ra[15:0] >> (64 - 8*bv)) : 0
 * Inserts the high part of an unaligned word
 * When bv=0, result is 0; otherwise shifts right by (64-8*bv) bits
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic word high insertion
     * Formula: bv ? (Ra[15:0] >> (64 - 8*bv)) : 0
     *-------------------------------------------------------------*/

    /* Test 1: Position 0 - result is 0 */
    TEST_CASE_START(1)
    lda $1, 0x1234($31)
    lda $2, 0($31)
    inswh $1, $2, $3
    lda $5, 0($31)           /* bv=0, result=0 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: Position 1 - shift right (64-8) = 56 */
    TEST_CASE_START(2)
    lda $1, 0x1234($31)
    lda $2, 1($31)
    inswh $1, $2, $3
    /* 0x1234 >> 56 = 0 (shifted out) */
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: Position 7 - shift right (64-56) = 8 */
    TEST_CASE_START(3)
    lda $1, 0x1234($31)
    lda $2, 7($31)
    inswh $1, $2, $3
    /* 0x1234 >> 8 = 0x12 */
    lda $5, 0x12($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: Position 6 - shift right (64-48) = 16 */
    TEST_CASE_START(4)
    lda $1, 0xABCD($31)
    lda $2, 6($31)
    inswh $1, $2, $3
    /* 0xABCD >> 16 = 0 */
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Test with immediate form
     *-------------------------------------------------------------*/

    /* Test 5: Position 7 using immediate */
    TEST_CASE_START(5)
    lda $1, 0x5678($31)
    inswh $1, 7, $3
    /* 0x5678 >> 8 = 0x56 */
    lda $5, 0x56($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 6: Position 0 using immediate - always 0 */
    TEST_CASE_START(6)
    lda $1, -1($31)
    inswh $1, 0, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Edge cases
     *-------------------------------------------------------------*/

    /* Test 7: Insert from zero */
    TEST_CASE_START(7)
    lda $1, 0($31)
    inswh $1, 7, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 8: Insert 0xFFFF at position 7 */
    TEST_CASE_START(8)
    lda $1, -1($31)          /* Will use lower 16 bits = 0xFFFF */
    inswh $1, 7, $3
    /* 0xFFFF >> 8 = 0xFF */
    lda $5, 0xFF($31)
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
