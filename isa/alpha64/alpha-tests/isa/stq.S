/*
 * Alpha STQ (Store Quadword) Test
 * Memory[Rb + disp] = Ra
 * Stores 64-bit value to memory
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Store values and verify by loading back
     *-------------------------------------------------------------*/

    /* Test 1: Store 0 */
    TEST_CASE_START(1)
    lda $1, 0x200($31)   /* Base address */
    lda $2, 0($31)       /* Value */
    stq $2, 0($1)        /* Store */
    ldq $3, 0($1)        /* Verify */
    cmpeq $2, $3, $6
    beq $6, fail

    /* Test 2: Store 123 */
    TEST_CASE_START(2)
    lda $1, 0x200($31)
    lda $2, 123($31)
    stq $2, 8($1)
    ldq $3, 8($1)
    cmpeq $2, $3, $6
    beq $6, fail

    /* Test 3: Store different values to different addresses */
    TEST_CASE_START(3)
    lda $1, 0x200($31)
    lda $2, 100($31)
    stq $2, 16($1)
    lda $2, 200($31)
    stq $2, 24($1)
    /* Verify first */
    ldq $3, 16($1)
    lda $5, 100($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: Verify second from Test 3 */
    TEST_CASE_START(4)
    lda $1, 0x200($31)
    ldq $3, 24($1)
    lda $5, 200($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 5: Store negative value */
    TEST_CASE_START(5)
    lda $1, 0x200($31)
    lda $2, -100($31)
    stq $2, 32($1)
    ldq $3, 32($1)
    cmpeq $2, $3, $6
    beq $6, fail

ALPHA_TEST_END
