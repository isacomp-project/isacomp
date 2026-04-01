/*
 * Alpha INSLL (Insert Longword Low) Test
 * Rc = Ra[31:0] << (Rb[2:0] * 8)
 * Inserts a 32-bit longword from Ra into a quadword at the byte position specified by Rb
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic longword insertion at different positions
     *-------------------------------------------------------------*/

    /* Test 1: Insert longword at position 0 (no shift) */
    TEST_CASE_START(1)
    lda $1, 0x5678($31)
    ldah $1, 0x1234($1)      /* $1 = 0x12345678 */
    lda $2, 0($31)
    insll $1, $2, $3
    lda $5, 0x5678($31)
    ldah $5, 0x1234($5)      /* Expected: 0x12345678 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: Insert longword at position 1 (shift left 8) */
    TEST_CASE_START(2)
    lda $1, 0xAB($31)        /* Small value for easier testing */
    lda $2, 1($31)
    insll $1, $2, $3
    lda $5, 0xAB00($31)      /* Expected: 0xAB00 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: Insert longword at position 2 (shift left 16) */
    TEST_CASE_START(3)
    lda $1, 0x34($31)
    lda $2, 2($31)
    insll $1, $2, $3
    lda $5, 0($31)
    ldah $5, 0x0034($5)      /* Expected: 0x00340000 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: Insert longword at position 3 (shift left 24) */
    TEST_CASE_START(4)
    lda $1, 0x12($31)
    lda $2, 3($31)
    insll $1, $2, $3
    lda $5, 0($31)
    ldah $5, 0x1200($5)      /* Expected: 0x12000000 */
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Test with immediate form
     *-------------------------------------------------------------*/

    /* Test 5: Insert longword at position 0 using immediate */
    TEST_CASE_START(5)
    lda $1, 0xBCDE($31)
    ldah $1, 0x789A($1)
    insll $1, 0, $3
    lda $5, 0xBCDE($31)
    ldah $5, 0x789A($5)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 6: Insert longword at position 1 using immediate */
    TEST_CASE_START(6)
    lda $1, 0x56($31)
    insll $1, 1, $3
    lda $5, 0x5600($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Edge cases
     *-------------------------------------------------------------*/

    /* Test 7: Insert 0 longword */
    TEST_CASE_START(7)
    lda $1, 0($31)
    insll $1, 1, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 8: Insert all 1s (lower 32 bits) - result is zero-extended */
    TEST_CASE_START(8)
    lda $1, -1($31)
    insll $1, 0, $3
    /* Result should be 0x00000000FFFFFFFF (32 1-bits, zero extended) */
    lda $5, -1($31)
    srl $5, 32, $5
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
