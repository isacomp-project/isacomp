/*
 * Alpha EXTWL (Extract Word Low) Test
 * Rc = (Ra >> (Rb[2:0] * 8)) & 0xFFFF
 * Extracts a 16-bit word from Ra at the byte position specified by Rb[2:0]
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic word extraction at different positions
     *-------------------------------------------------------------*/

    /* Test 1: Extract word at position 0 (bits 15:0) */
    TEST_CASE_START(1)
    lda $1, 0x4567($31)
    ldah $1, 0x0123($1)      /* $1 = 0x01234567 */
    lda $2, 0($31)
    extwl $1, $2, $3
    lda $5, 0x4567($31)      /* Expected: 0x4567 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: Extract word at position 1 (bits 23:8) */
    TEST_CASE_START(2)
    lda $1, 0x4567($31)
    ldah $1, 0x0123($1)
    lda $2, 1($31)
    extwl $1, $2, $3
    lda $5, 0x2345($31)      /* Expected: 0x2345 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: Extract word at position 2 (bits 31:16) */
    TEST_CASE_START(3)
    lda $1, 0x4567($31)
    ldah $1, 0x0123($1)
    lda $2, 2($31)
    extwl $1, $2, $3
    lda $5, 0x0123($31)      /* Expected: 0x0123 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: Extract word at position 3 (bits 39:24) */
    TEST_CASE_START(4)
    lda $1, 0x4567($31)
    ldah $1, 0x0123($1)      /* Lower 32 bits: 0x01234567 */
    lda $2, 3($31)
    extwl $1, $2, $3
    lda $5, 0x01($31)        /* Expected: 0x0001 (upper bytes are 0) */
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Test with immediate form
     *-------------------------------------------------------------*/

    /* Test 5: Extract word at position 0 using immediate */
    TEST_CASE_START(5)
    lda $1, 0x5678($31)
    ldah $1, 0x1234($1)
    extwl $1, 0, $3
    lda $5, 0x5678($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 6: Extract word at position 2 using immediate */
    TEST_CASE_START(6)
    lda $1, 0x5678($31)
    ldah $1, 0x1234($1)
    extwl $1, 2, $3
    lda $5, 0x1234($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Edge cases
     *-------------------------------------------------------------*/

    /* Test 7: Extract from zero */
    TEST_CASE_START(7)
    lda $1, 0($31)
    extwl $1, 0, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 8: Extract 0xFFFF word - result is zero-extended 16-bit mask */
    TEST_CASE_START(8)
    lda $1, -1($31)          /* All 1s */
    extwl $1, 0, $3
    lda $5, -1($31)
    srl $5, 48, $5           /* Expected: 0x000000000000FFFF */
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
