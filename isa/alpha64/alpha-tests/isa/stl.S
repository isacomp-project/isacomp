/*
 * Alpha STL (Store Longword) Test
 * Memory[Rb + disp][31:0] = Ra[31:0]
 * Stores lower 32 bits to memory
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Store 32-bit values and verify
     *-------------------------------------------------------------*/

    /* Test 1: Store and verify 0 */
    TEST_CASE_START(1)
    lda $1, 0x400($31)   /* Base address */
    lda $2, 0($31)
    stl $2, 0($1)
    ldl $3, 0($1)
    cmpeq $2, $3, $6
    beq $6, fail

    /* Test 2: Store and verify 99 */
    TEST_CASE_START(2)
    lda $1, 0x400($31)
    lda $2, 99($31)
    stl $2, 4($1)
    ldl $3, 4($1)
    cmpeq $2, $3, $6
    beq $6, fail

    /* Test 3: Store and verify 32767 */
    TEST_CASE_START(3)
    lda $1, 0x400($31)
    lda $2, 32767($31)
    stl $2, 8($1)
    ldl $3, 8($1)
    cmpeq $2, $3, $6
    beq $6, fail

    /* Test 4: Store and verify -1 */
    TEST_CASE_START(4)
    lda $1, 0x400($31)
    lda $2, -1($31)
    stl $2, 12($1)
    ldl $3, 12($1)
    lda $5, -1($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 5: Multiple stores don't interfere */
    TEST_CASE_START(5)
    lda $1, 0x400($31)
    lda $2, 111($31)
    stl $2, 16($1)
    lda $2, 222($31)
    stl $2, 20($1)
    /* Verify first store still correct */
    ldl $3, 16($1)
    lda $5, 111($31)
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
