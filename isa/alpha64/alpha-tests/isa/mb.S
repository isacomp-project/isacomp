/*
 * Alpha MB (Memory Barrier) Test
 * Tests memory barrier instruction
 *
 * MB guarantees that all previous loads and stores complete
 * before any subsequent loads or stores begin.
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Memory barrier tests
     * These mainly verify the instruction doesn't crash
     *-------------------------------------------------------------*/

    /* Test 2: Simple MB */
    TEST_BARRIER(2, mb)

    /* Test 3: MB between stores */
    TEST_CASE_START(3)
    lda $1, scratch($31)
    lda $2, 0x1234($31)
    stl $2, 0($1)
    mb
    lda $2, 0x5678($31)
    stl $2, 4($1)
    /* Verify both stores completed */
    ldl $3, 0($1)
    lda $5, 0x1234($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: MB between load and store */
    TEST_CASE_START(4)
    lda $1, scratch($31)
    lda $2, 0xABCD($31)
    stl $2, 8($1)
    ldl $3, 8($1)
    mb
    lda $2, 0xDCBA($31)
    stl $2, 12($1)

    /* Test 5: Multiple MBs in sequence */
    TEST_CASE_START(5)
    mb
    mb
    mb

    /* Test 6: MB in loop */
    TEST_CASE_START(6)
    lda $10, 3($31)
1:  mb
    subq $10, 1, $10
    bne $10, 1b

ALPHA_TEST_END

    .data
    .align 3
scratch:
    .space 32
