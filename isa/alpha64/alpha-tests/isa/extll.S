/*
 * Alpha EXTLL (Extract Longword Low) Test
 * Rc = (Ra >> (Rb[2:0] * 8)) & 0xFFFFFFFF
 * Extracts a 32-bit longword from Ra at the byte position specified by Rb[2:0]
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic longword extraction at different positions
     *-------------------------------------------------------------*/

    /* Test 1: Extract longword at position 0 (bits 31:0) */
    TEST_CASE_START(1)
    lda $1, 0x5678($31)
    ldah $1, 0x1234($1)      /* $1 = 0x12345678 */
    lda $2, 0($31)
    extll $1, $2, $3
    lda $5, 0x5678($31)
    ldah $5, 0x1234($5)      /* Expected: 0x12345678 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: Extract longword at position 1 */
    TEST_CASE_START(2)
    lda $1, 0x5678($31)
    ldah $1, 0x1234($1)      /* $1 = 0x12345678 */
    lda $2, 1($31)
    extll $1, $2, $3
    lda $5, 0x3456($31)
    ldah $5, 0x0012($5)      /* Expected: 0x00123456 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: Extract longword at position 2 */
    TEST_CASE_START(3)
    lda $1, 0x5678($31)
    ldah $1, 0x1234($1)
    lda $2, 2($31)
    extll $1, $2, $3
    lda $5, 0x1234($31)      /* Expected: 0x00001234 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: Extract longword at position 3 */
    TEST_CASE_START(4)
    lda $1, 0x5678($31)
    ldah $1, 0x1234($1)
    lda $2, 3($31)
    extll $1, $2, $3
    lda $5, 0x12($31)        /* Expected: 0x00000012 */
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Test with immediate form
     *-------------------------------------------------------------*/

    /* Test 5: Extract longword at position 0 using immediate */
    TEST_CASE_START(5)
    lda $1, 0xBCDE($31)
    ldah $1, 0x789A($1)      /* Careful with sign extension */
    extll $1, 0, $3
    lda $5, 0xBCDE($31)
    ldah $5, 0x789A($5)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Edge cases
     *-------------------------------------------------------------*/

    /* Test 6: Extract from zero */
    TEST_CASE_START(6)
    lda $1, 0($31)
    extll $1, 0, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 7: Extract all 1s - result is zero-extended 32-bit mask */
    TEST_CASE_START(7)
    lda $1, -1($31)          /* All 1s */
    extll $1, 0, $3
    lda $5, -1($31)
    srl $5, 32, $5           /* Expected: 0x00000000FFFFFFFF */
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
