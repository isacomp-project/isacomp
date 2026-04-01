/*
 * Alpha LDL (Load Sign-Extended Longword) Test
 * Ra = sign_extend(Memory[Rb + disp][31:0])
 * Loads 32-bit value and sign-extends to 64 bits
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Store 32-bit values and load them back with sign extension
     *-------------------------------------------------------------*/

    /* Test 1: Load positive value (no sign extension needed) */
    TEST_CASE_START(1)
    lda $1, 0x300($31)   /* Base address */
    lda $2, 42($31)      /* Positive value */
    stl $2, 0($1)        /* Store as longword */
    ldl $3, 0($1)        /* Load back */
    cmpeq $2, $3, $6
    beq $6, fail

    /* Test 2: Load 0 */
    TEST_CASE_START(2)
    lda $1, 0x300($31)
    lda $2, 0($31)
    stl $2, 4($1)
    ldl $3, 4($1)
    cmpeq $2, $3, $6
    beq $6, fail

    /* Test 3: Load 1000 */
    TEST_CASE_START(3)
    lda $1, 0x300($31)
    lda $2, 1000($31)
    stl $2, 8($1)
    ldl $3, 8($1)
    cmpeq $2, $3, $6
    beq $6, fail

    /* Test 4: Load -1 (should sign extend) */
    TEST_CASE_START(4)
    lda $1, 0x300($31)
    lda $2, -1($31)
    stl $2, 12($1)
    ldl $3, 12($1)
    lda $5, -1($31)      /* Expected: all 1s (sign extended) */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 5: Load -100 */
    TEST_CASE_START(5)
    lda $1, 0x300($31)
    lda $2, -100($31)
    stl $2, 16($1)
    ldl $3, 16($1)
    lda $5, -100($31)
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
