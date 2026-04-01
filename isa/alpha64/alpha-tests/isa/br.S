/*
 * Alpha BR (Unconditional Branch) Test
 * Tests unconditional branch instruction
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Unconditional branch tests
     *-------------------------------------------------------------*/

    /* Test 2: Simple forward branch */
    TEST_BR_UNCONDITIONAL(2)

    /* Test 3: Multiple forward branches in sequence */
    TEST_CASE_START(3)
    br $31, 1f
    br $31, fail
1:  br $31, 2f
    br $31, fail
2:  br $31, 3f
    br $31, fail
3:

    /* Test 4: BR with link register (saves return address) */
    TEST_CASE_START(4)
    br $27, 1f
1:  /* $27 should contain address of instruction after BR */
    /* Just verify we got here */

    /* Test 5: Branch over data */
    TEST_CASE_START(5)
    br $31, 1f
    .long 0xDEADBEEF
    .long 0xCAFEBABE
1:

    /* Test 6: Backward branch (simple loop-like) */
    TEST_CASE_START(6)
    lda $1, 0($31)
    br $31, 2f
1:  addq $1, 1, $1
    lda $2, 3($31)
    cmpeq $1, $2, $3
    bne $3, 3f
2:  br $31, 1b
3:

ALPHA_TEST_END
