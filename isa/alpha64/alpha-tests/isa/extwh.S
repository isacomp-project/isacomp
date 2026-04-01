/*
 * Alpha EXTWH (Extract Word High) Test
 * Rc = (Ra << ((64 - Rb[2:0]*8) & 0x3F)) & 0xFFFF
 * Extracts the high part of an unaligned word access
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic word high extraction
     * Formula: (Ra << ((64 - pos*8) & 63)) & 0xFFFF
     *-------------------------------------------------------------*/

    /* Test 1: Position 0 - shift left 64, result is 0 (wrapped to 0) */
    TEST_CASE_START(1)
    lda $1, 0x5678($31)
    ldah $1, 0x1234($1)
    lda $2, 0($31)
    extwh $1, $2, $3
    lda $5, 0($31)           /* (64-0*8)&63 = 0, shift left 0 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: Position 1 - shift left 56 */
    TEST_CASE_START(2)
    lda $1, 0x5678($31)
    ldah $1, 0x1234($1)      /* $1 = 0x12345678 */
    lda $2, 1($31)
    extwh $1, $2, $3
    /* (64-8)&63 = 56, (0x12345678 << 56) & 0xFFFF = 0 (high bits masked) */
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: Position 7 - shift left 8 */
    TEST_CASE_START(3)
    lda $1, 0x00AB($31)      /* Low byte = 0xAB */
    lda $2, 7($31)
    extwh $1, $2, $3
    /* (64-56)&63 = 8, (0xAB << 8) & 0xFFFF = 0xAB00 */
    lda $5, 0xAB00($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: Position 6 - shift left 16 */
    TEST_CASE_START(4)
    lda $1, 0x00CD($31)
    lda $2, 6($31)
    extwh $1, $2, $3
    /* (64-48)&63 = 16, (0xCD << 16) & 0xFFFF = 0 */
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Test with immediate form
     *-------------------------------------------------------------*/

    /* Test 5: Position 7 using immediate */
    TEST_CASE_START(5)
    lda $1, 0x0012($31)
    extwh $1, 7, $3
    /* (64-56)&63 = 8, (0x12 << 8) & 0xFFFF = 0x1200 */
    lda $5, 0x1200($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Edge cases
     *-------------------------------------------------------------*/

    /* Test 6: Extract from zero */
    TEST_CASE_START(6)
    lda $1, 0($31)
    extwh $1, 7, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 7: Extract with all 1s */
    TEST_CASE_START(7)
    lda $1, -1($31)
    extwh $1, 7, $3
    /* (0xFF...FF << 8) & 0xFFFF = 0xFF00 */
    /* Build 0xFF00: load 0xFF then shift left 8 */
    lda $5, -1($31)
    srl $5, 56, $5           /* Get 0xFF in low byte */
    sll $5, 8, $5            /* Shift to get 0xFF00 */
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
