/*
 * Alpha INSBL (Insert Byte Low) Test
 * Rc = Ra[7:0] << (Rb[2:0] * 8)
 * Inserts a byte from Ra into a quadword at the byte position specified by Rb
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic byte insertion at different positions
     *-------------------------------------------------------------*/

    /* Test 1: Insert byte at position 0 (no shift) */
    TEST_CASE_START(1)
    lda $1, 0xAB($31)        /* Byte to insert */
    lda $2, 0($31)           /* Position 0 */
    insbl $1, $2, $3
    lda $5, 0xAB($31)        /* Expected: 0xAB in position 0 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: Insert byte at position 1 (shift left 8) */
    TEST_CASE_START(2)
    lda $1, 0xCD($31)
    lda $2, 1($31)
    insbl $1, $2, $3
    lda $5, 0xCD00($31)      /* Expected: 0xCD00 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: Insert byte at position 2 (shift left 16) */
    TEST_CASE_START(3)
    lda $1, 0xEF($31)
    lda $2, 2($31)
    insbl $1, $2, $3
    lda $5, 0($31)
    ldah $5, 0x00EF($5)      /* Expected: 0x00EF0000 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: Insert byte at position 3 (shift left 24) */
    TEST_CASE_START(4)
    lda $1, 0x12($31)
    lda $2, 3($31)
    insbl $1, $2, $3
    lda $5, 0($31)
    ldah $5, 0x1200($5)      /* Expected: 0x12000000 */
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Test with immediate form
     *-------------------------------------------------------------*/

    /* Test 5: Insert byte at position 0 using immediate */
    TEST_CASE_START(5)
    lda $1, 0x77($31)
    insbl $1, 0, $3
    lda $5, 0x77($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 6: Insert byte at position 1 using immediate */
    TEST_CASE_START(6)
    lda $1, 0x88($31)
    insbl $1, 1, $3
    lda $5, 0x8800($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 7: Insert byte at position 2 using immediate */
    TEST_CASE_START(7)
    lda $1, 0x99($31)
    insbl $1, 2, $3
    lda $5, 0($31)
    ldah $5, 0x0099($5)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Edge cases
     *-------------------------------------------------------------*/

    /* Test 8: Insert 0x00 byte */
    TEST_CASE_START(8)
    lda $1, 0($31)
    insbl $1, 1, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 9: Insert 0xFF byte */
    TEST_CASE_START(9)
    lda $1, 0xFF($31)
    insbl $1, 0, $3
    lda $5, 0xFF($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 10: Only lower byte of Ra is used */
    TEST_CASE_START(10)
    lda $1, 0x1234($31)      /* Has value in bits 15:8 */
    insbl $1, 0, $3
    lda $5, 0x34($31)        /* Only 0x34 should be inserted */
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
