/*
 * Alpha INSQL (Insert Quadword Low) Test
 * Rc = Ra << (Rb[2:0] * 8)
 * Shifts the entire 64-bit Ra left by the byte position specified by Rb
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic quadword insertion at different positions
     *-------------------------------------------------------------*/

    /* Test 1: Insert quadword at position 0 (no shift) */
    TEST_CASE_START(1)
    lda $1, 0x5678($31)
    ldah $1, 0x1234($1)      /* $1 = 0x12345678 */
    lda $2, 0($31)
    insql $1, $2, $3
    lda $5, 0x5678($31)
    ldah $5, 0x1234($5)      /* Expected: same value */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: Insert quadword at position 1 (shift left 8) */
    TEST_CASE_START(2)
    lda $1, 0xAB($31)
    lda $2, 1($31)
    insql $1, $2, $3
    lda $5, 0xAB00($31)      /* Expected: 0xAB00 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: Insert quadword at position 2 (shift left 16) */
    TEST_CASE_START(3)
    lda $1, 0x34($31)
    lda $2, 2($31)
    insql $1, $2, $3
    lda $5, 0($31)
    ldah $5, 0x0034($5)      /* Expected: 0x00340000 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: Insert quadword at position 3 (shift left 24) */
    TEST_CASE_START(4)
    lda $1, 0x12($31)
    lda $2, 3($31)
    insql $1, $2, $3
    lda $5, 0($31)
    ldah $5, 0x1200($5)      /* Expected: 0x12000000 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 5: Insert quadword at position 4 (shift left 32) */
    TEST_CASE_START(5)
    lda $1, 0x01($31)
    lda $2, 4($31)
    insql $1, $2, $3
    /* 1 << 32 = 0x100000000, verify upper 32 bits = 1 */
    srl $3, 32, $4
    lda $5, 1($31)
    cmpeq $4, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Test with immediate form
     *-------------------------------------------------------------*/

    /* Test 6: Insert quadword at position 0 using immediate */
    TEST_CASE_START(6)
    lda $1, 100($31)
    insql $1, 0, $3
    lda $5, 100($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 7: Insert quadword at position 1 using immediate */
    TEST_CASE_START(7)
    lda $1, 0x01($31)        /* Value = 1 */
    insql $1, 1, $3
    lda $5, 0x100($31)       /* Expected: 1 << 8 = 0x100 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 8: Insert quadword at position 2 using immediate */
    TEST_CASE_START(8)
    lda $1, 0x01($31)
    insql $1, 2, $3
    lda $5, 0($31)
    ldah $5, 0x0001($5)      /* Expected: 1 << 16 = 0x10000 */
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Edge cases
     *-------------------------------------------------------------*/

    /* Test 9: Insert 0 */
    TEST_CASE_START(9)
    lda $1, 0($31)
    insql $1, 1, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
