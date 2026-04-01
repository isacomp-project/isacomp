/*
 * Alpha INSWL (Insert Word Low) Test
 * Rc = Ra[15:0] << (Rb[2:0] * 8)
 * Inserts a 16-bit word from Ra into a quadword at the byte position specified by Rb
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic word insertion at different positions
     *-------------------------------------------------------------*/

    /* Test 1: Insert word at position 0 (no shift) */
    TEST_CASE_START(1)
    lda $1, 0xABCD($31)      /* Word to insert */
    lda $2, 0($31)           /* Position 0 */
    inswl $1, $2, $3
    lda $5, 0xABCD($31)      /* Expected: 0xABCD */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: Insert word at position 1 (shift left 8) */
    TEST_CASE_START(2)
    lda $1, 0x1234($31)
    lda $2, 1($31)
    inswl $1, $2, $3
    lda $5, 0x3400($31)
    ldah $5, 0x0012($5)      /* Expected: 0x00123400 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: Insert word at position 2 (shift left 16) */
    TEST_CASE_START(3)
    lda $1, 0x5678($31)
    lda $2, 2($31)
    inswl $1, $2, $3
    lda $5, 0x0000($31)
    ldah $5, 0x5678($5)      /* Expected: 0x56780000 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: Insert word at position 3 (shift left 24) */
    TEST_CASE_START(4)
    lda $1, 0x0012($31)
    lda $2, 3($31)
    inswl $1, $2, $3
    /* Expected: 0x12000000 - low byte at bits 31:24 */
    lda $5, 0($31)
    ldah $5, 0x1200($5)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Test with immediate form
     *-------------------------------------------------------------*/

    /* Test 5: Insert word at position 0 using immediate */
    TEST_CASE_START(5)
    lda $1, 0x7890($31)
    inswl $1, 0, $3
    lda $5, 0x7890($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 6: Insert word at position 2 using immediate */
    TEST_CASE_START(6)
    lda $1, 0x1122($31)
    inswl $1, 2, $3
    lda $5, 0($31)
    ldah $5, 0x1122($5)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Edge cases
     *-------------------------------------------------------------*/

    /* Test 7: Insert 0x0000 word */
    TEST_CASE_START(7)
    lda $1, 0($31)
    inswl $1, 1, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 8: Insert 0xFFFF word - result is zero-extended */
    TEST_CASE_START(8)
    lda $1, -1($31)          /* All 1s */
    inswl $1, 0, $3
    /* Only bits 15:0 = 0xFFFF should be used, zero extended to 64 bits */
    lda $5, -1($31)
    srl $5, 48, $5           /* Expected: 0x000000000000FFFF */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 9: Only lower 16 bits of Ra are used */
    TEST_CASE_START(9)
    lda $1, 0x5678($31)
    ldah $1, 0x1234($1)      /* $1 = 0x12345678 */
    inswl $1, 0, $3
    lda $5, 0x5678($31)      /* Only 0x5678 should be inserted */
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
