/*
 * Alpha EXTQH (Extract Quadword High) Test
 * Rc = Ra << ((64 - Rb[2:0]*8) & 0x3F)
 * Extracts the high part of an unaligned quadword access (no mask)
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic quadword high extraction
     * Formula: Ra << ((64 - pos*8) & 63)
     *-------------------------------------------------------------*/

    /* Test 1: Position 0 - shift left (64-0)&63 = 0 */
    TEST_CASE_START(1)
    lda $1, 0x5678($31)
    ldah $1, 0x1234($1)
    lda $2, 0($31)
    extqh $1, $2, $3
    lda $5, 0x5678($31)
    ldah $5, 0x1234($5)      /* No shift, same value */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: Position 1 - shift left 56 */
    TEST_CASE_START(2)
    lda $1, 0x01($31)        /* Value = 1 */
    lda $2, 1($31)
    extqh $1, $2, $3
    /* (64-8)&63 = 56, 1 << 56 = 0x0100000000000000 */
    /* Check upper bits by shifting right 56 and comparing with 1 */
    srl $3, 56, $4
    lda $5, 1($31)
    cmpeq $4, $5, $6
    beq $6, fail

    /* Test 3: Position 7 - shift left 8 */
    TEST_CASE_START(3)
    lda $1, 0x56($31)
    lda $2, 7($31)
    extqh $1, $2, $3
    /* (64-56)&63 = 8, 0x56 << 8 = 0x5600 */
    lda $5, 0x5600($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: Position 6 - shift left 16 */
    TEST_CASE_START(4)
    lda $1, 0x34($31)
    lda $2, 6($31)
    extqh $1, $2, $3
    /* (64-48)&63 = 16, 0x34 << 16 = 0x340000 */
    lda $5, 0($31)
    ldah $5, 0x0034($5)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 5: Position 5 - shift left 24 */
    TEST_CASE_START(5)
    lda $1, 0x12($31)
    lda $2, 5($31)
    extqh $1, $2, $3
    /* (64-40)&63 = 24, 0x12 << 24 = 0x12000000 */
    lda $5, 0($31)
    ldah $5, 0x1200($5)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Test with immediate form
     *-------------------------------------------------------------*/

    /* Test 6: Position 7 using immediate */
    TEST_CASE_START(6)
    lda $1, 0xAB($31)
    extqh $1, 7, $3
    /* 0xAB << 8 = 0xAB00 */
    lda $5, 0xAB00($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 7: Position 4 using immediate - shift left 32 */
    TEST_CASE_START(7)
    lda $1, 0x01($31)
    extqh $1, 4, $3
    /* (64-32)&63 = 32, 1 << 32 = 0x100000000 */
    /* Check upper bits by shifting right 32 and comparing with 1 */
    srl $3, 32, $4
    lda $5, 1($31)
    cmpeq $4, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Edge cases
     *-------------------------------------------------------------*/

    /* Test 8: Extract from zero */
    TEST_CASE_START(8)
    lda $1, 0($31)
    extqh $1, 7, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
