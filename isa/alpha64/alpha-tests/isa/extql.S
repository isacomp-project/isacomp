/*
 * Alpha EXTQL (Extract Quadword Low) Test
 * Rc = Ra >> (Rb[2:0] * 8)
 * Extracts bits from Ra starting at the byte position specified by Rb[2:0]
 * No masking - full quadword shift
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic quadword extraction at different positions
     *-------------------------------------------------------------*/

    /* Test 1: Extract at position 0 (no shift) */
    TEST_CASE_START(1)
    lda $1, 0x5678($31)
    ldah $1, 0x1234($1)      /* $1 = 0x12345678 */
    lda $2, 0($31)
    extql $1, $2, $3
    lda $5, 0x5678($31)
    ldah $5, 0x1234($5)      /* Expected: same value */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: Extract at position 1 (shift right 8) */
    TEST_CASE_START(2)
    lda $1, 0x5678($31)
    ldah $1, 0x1234($1)      /* $1 = 0x12345678 */
    lda $2, 1($31)
    extql $1, $2, $3
    lda $5, 0x3456($31)
    ldah $5, 0x0012($5)      /* Expected: 0x00123456 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: Extract at position 2 (shift right 16) */
    TEST_CASE_START(3)
    lda $1, 0x5678($31)
    ldah $1, 0x1234($1)
    lda $2, 2($31)
    extql $1, $2, $3
    lda $5, 0x1234($31)      /* Expected: 0x00001234 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: Extract at position 3 (shift right 24) */
    TEST_CASE_START(4)
    lda $1, 0x5678($31)
    ldah $1, 0x1234($1)
    lda $2, 3($31)
    extql $1, $2, $3
    lda $5, 0x12($31)        /* Expected: 0x00000012 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 5: Extract at position 4 (shift right 32) */
    TEST_CASE_START(5)
    lda $1, 0x5678($31)
    ldah $1, 0x1234($1)      /* Only lower 32 bits set */
    lda $2, 4($31)
    extql $1, $2, $3
    lda $5, 0($31)           /* Expected: 0 (shifted out) */
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Test with immediate form
     *-------------------------------------------------------------*/

    /* Test 6: Extract at position 0 using immediate */
    TEST_CASE_START(6)
    lda $1, 100($31)
    extql $1, 0, $3
    lda $5, 100($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 7: Extract at position 1 using immediate */
    TEST_CASE_START(7)
    lda $1, 0x100($31)       /* 256 */
    extql $1, 1, $3
    lda $5, 1($31)           /* Expected: 1 */
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Edge cases
     *-------------------------------------------------------------*/

    /* Test 8: Extract from zero */
    TEST_CASE_START(8)
    lda $1, 0($31)
    extql $1, 0, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
