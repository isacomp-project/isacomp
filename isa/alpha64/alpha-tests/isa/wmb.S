/*
 * Alpha WMB (Write Memory Barrier) Test
 * Tests write memory barrier instruction
 *
 * WMB guarantees that all previous stores complete
 * before any subsequent stores begin. Does not affect loads.
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Write memory barrier tests
     * These mainly verify the instruction doesn't crash
     *-------------------------------------------------------------*/

    /* Test 2: Simple WMB */
    TEST_BARRIER(2, wmb)

    /* Test 3: WMB between stores */
    TEST_CASE_START(3)
    lda $1, scratch_wmb($31)
    lda $2, 0x1111($31)
    stl $2, 0($1)
    wmb
    lda $2, 0x2222($31)
    stl $2, 4($1)
    wmb
    lda $2, 0x3333($31)
    stl $2, 8($1)
    /* Verify stores */
    ldl $3, 0($1)
    lda $5, 0x1111($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: Multiple WMBs in sequence */
    TEST_CASE_START(4)
    wmb
    wmb
    wmb

    /* Test 5: WMB with quadword stores */
    TEST_CASE_START(5)
    lda $1, scratch_wmb($31)
    lda $2, 0x4444($31)
    stq $2, 16($1)
    wmb
    lda $2, 0x5555($31)
    stq $2, 24($1)

ALPHA_TEST_END

    .data
    .align 3
scratch_wmb:
    .space 32
