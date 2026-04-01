/*
 * Alpha EXTLH (Extract Longword High) Test
 * Rc = (Ra << ((64 - Rb[2:0]*8) & 0x3F)) & 0xFFFFFFFF
 * Extracts the high part of an unaligned longword access
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic longword high extraction
     * Formula: (Ra << ((64 - pos*8) & 63)) & 0xFFFFFFFF
     *-------------------------------------------------------------*/

    /* Test 1: Position 0 - no shift (64&63=0) */
    TEST_CASE_START(1)
    lda $1, 0x5678($31)
    ldah $1, 0x1234($1)
    lda $2, 0($31)
    extlh $1, $2, $3
    lda $5, 0($31)           /* (64-0)&63 = 0 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: Position 1 - shift left 56 */
    TEST_CASE_START(2)
    lda $1, 0x5678($31)
    ldah $1, 0x1234($1)
    lda $2, 1($31)
    extlh $1, $2, $3
    /* (64-8)&63 = 56, (0x12345678 << 56) & 0xFFFFFFFF = 0 */
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: Position 5 - shift left 24 */
    TEST_CASE_START(3)
    lda $1, 0x0012($31)
    lda $2, 5($31)
    extlh $1, $2, $3
    /* (64-40)&63 = 24, (0x12 << 24) & 0xFFFFFFFF = 0x12000000 */
    lda $5, 0($31)
    ldah $5, 0x1200($5)      /* 0x12000000 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: Position 7 - shift left 8 */
    TEST_CASE_START(4)
    lda $1, 0x0056($31)
    lda $2, 7($31)
    extlh $1, $2, $3
    /* (64-56)&63 = 8, (0x56 << 8) & 0xFFFFFFFF = 0x5600 */
    lda $5, 0x5600($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Test with immediate form
     *-------------------------------------------------------------*/

    /* Test 5: Position 7 using immediate */
    TEST_CASE_START(5)
    lda $1, 0x0034($31)
    extlh $1, 7, $3
    /* (64-56)&63 = 8, (0x34 << 8) = 0x3400 */
    lda $5, 0x3400($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 6: Position 6 using immediate - shift left 16 */
    TEST_CASE_START(6)
    lda $1, 0x0012($31)
    extlh $1, 6, $3
    /* (64-48)&63 = 16, (0x12 << 16) = 0x120000 */
    lda $5, 0($31)
    ldah $5, 0x0012($5)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Edge cases
     *-------------------------------------------------------------*/

    /* Test 7: Extract from zero */
    TEST_CASE_START(7)
    lda $1, 0($31)
    extlh $1, 7, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
