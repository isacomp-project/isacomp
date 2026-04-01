/*
 * Alpha LDQ_L (Load Quadword Locked) Test
 * Tests load-linked instruction for atomic operations on 64-bit values
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Load-locked quadword tests
     *-------------------------------------------------------------*/

    /* Test 2: Simple LDQ_L - compare with regular ldq */
    TEST_CASE_START(2)
    lda $1, atomic_data_q($31)
    ldq_l $3, 0($1)
    ldq $5, 0($1)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: LDQ_L with offset - compare with regular ldq */
    TEST_CASE_START(3)
    lda $1, atomic_data_q($31)
    ldq_l $3, 8($1)
    ldq $5, 8($1)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: LDQ_L / STQ_C sequence (basic atomic) */
    TEST_ATOMIC_STQ_C(4, 0x7777, 16, atomic_data_q)

    /* Test 5: LDQ_L then immediately another LDQ_L */
    TEST_CASE_START(5)
    lda $1, atomic_data_q($31)
    ldq_l $2, 0($1)
    ldq_l $3, 8($1)
    /* Second load-locked cancels first */

ALPHA_TEST_END

    .data
    .align 3
atomic_data_q:
    .quad 0x123456789ABCDEF0
    .quad 0xDEADBEEFCAFEBABE
    .quad 0x0000000000000000
    .quad 0x0000000000000000
