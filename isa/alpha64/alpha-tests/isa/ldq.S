/*
 * Alpha LDQ (Load Quadword) Test
 * Ra = Memory[Rb + disp]
 * Loads 64-bit value from memory
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * First store some values to memory, then load them back
     * Use address 0x100 as test area
     *-------------------------------------------------------------*/

    /* Test 1: Store and load back 0 */
    TEST_CASE_START(1)
    lda $1, 0x100($31)   /* Base address */
    lda $2, 0($31)       /* Value to store */
    stq $2, 0($1)        /* Store at base */
    ldq $3, 0($1)        /* Load back */
    cmpeq $2, $3, $6
    beq $6, fail

    /* Test 2: Store and load back 42 */
    TEST_CASE_START(2)
    lda $1, 0x100($31)
    lda $2, 42($31)
    stq $2, 8($1)        /* Store at base+8 */
    ldq $3, 8($1)        /* Load back */
    cmpeq $2, $3, $6
    beq $6, fail

    /* Test 3: Store and load back 1000 */
    TEST_CASE_START(3)
    lda $1, 0x100($31)
    lda $2, 1000($31)
    stq $2, 16($1)       /* Store at base+16 */
    ldq $3, 16($1)       /* Load back */
    cmpeq $2, $3, $6
    beq $6, fail

    /* Test 4: Store and load back -1 */
    TEST_CASE_START(4)
    lda $1, 0x100($31)
    lda $2, -1($31)
    stq $2, 24($1)       /* Store at base+24 */
    ldq $3, 24($1)       /* Load back */
    cmpeq $2, $3, $6
    beq $6, fail

    /* Test 5: Negative displacement */
    TEST_CASE_START(5)
    lda $1, 0x110($31)   /* Higher base */
    lda $2, 77($31)
    stq $2, 0($1)        /* Store at 0x110 */
    lda $1, 0x118($31)   /* Move base up */
    ldq $3, -8($1)       /* Load with negative offset */
    lda $5, 77($31)
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
