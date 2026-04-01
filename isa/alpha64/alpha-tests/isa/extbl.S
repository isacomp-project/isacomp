/*
 * Alpha EXTBL (Extract Byte Low) Test
 * Rc = (Ra >> (Rb[2:0] * 8)) & 0xFF
 * Extracts a byte from Ra at the byte position specified by Rb[2:0]
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic byte extraction at different positions
     *-------------------------------------------------------------*/

    /* Test 1: Extract byte 0 (bits 7:0) from 0x0123456789ABCDEF */
    TEST_CASE_START(1)
    lda $1, 0x4567($31)
    ldah $1, 0x0123($1)      /* $1 = 0x01234567 (lower 32 bits) */
    lda $2, 0($31)           /* Position 0 */
    extbl $1, $2, $3
    lda $5, 0x67($31)        /* Expected: 0x67 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: Extract byte 1 (bits 15:8) */
    TEST_CASE_START(2)
    lda $1, 0x4567($31)
    ldah $1, 0x0123($1)
    lda $2, 1($31)           /* Position 1 */
    extbl $1, $2, $3
    lda $5, 0x45($31)        /* Expected: 0x45 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: Extract byte 2 (bits 23:16) */
    TEST_CASE_START(3)
    lda $1, 0x4567($31)
    ldah $1, 0x0123($1)
    lda $2, 2($31)           /* Position 2 */
    extbl $1, $2, $3
    lda $5, 0x23($31)        /* Expected: 0x23 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: Extract byte 3 (bits 31:24) */
    TEST_CASE_START(4)
    lda $1, 0x4567($31)
    ldah $1, 0x0123($1)
    lda $2, 3($31)           /* Position 3 */
    extbl $1, $2, $3
    lda $5, 0x01($31)        /* Expected: 0x01 */
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Test with immediate form
     *-------------------------------------------------------------*/

    /* Test 5: Extract byte 0 using immediate */
    TEST_CASE_START(5)
    lda $1, 0x7856($31)
    ldah $1, 0x1234($1)      /* $1 = 0x12347856 */
    extbl $1, 0, $3
    lda $5, 0x56($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 6: Extract byte 2 using immediate */
    TEST_CASE_START(6)
    lda $1, 0x7856($31)
    ldah $1, 0x1234($1)
    extbl $1, 2, $3
    lda $5, 0x34($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Edge cases
     *-------------------------------------------------------------*/

    /* Test 7: Extract from zero */
    TEST_CASE_START(7)
    lda $1, 0($31)
    lda $2, 0($31)
    extbl $1, $2, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 8: Extract 0xFF byte */
    TEST_CASE_START(8)
    lda $1, -1($31)          /* All 1s */
    lda $2, 0($31)
    extbl $1, $2, $3
    lda $5, 0xFF($31)        /* Expected: 0xFF */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 9: Position wraps at 8 (only bits 2:0 used) */
    TEST_CASE_START(9)
    lda $1, 0x7856($31)
    ldah $1, 0x1234($1)
    lda $2, 8($31)           /* Should be same as position 0 */
    extbl $1, $2, $3
    lda $5, 0x56($31)
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
