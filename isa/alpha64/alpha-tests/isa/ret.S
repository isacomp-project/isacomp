/*
 * Alpha RET (Return from Subroutine) Test
 * Tests return instruction variants
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Return instruction tests
     *-------------------------------------------------------------*/

    /* Test 2: Simple RET */
    TEST_CASE_START(2)
    bsr $26, ret_sub2
    br $31, 1f
ret_sub2:
    ret $31, ($26), 1
1:

    /* Test 3: RET with different hint values */
    TEST_CASE_START(3)
    bsr $26, ret_sub3a
    bsr $26, ret_sub3b
    br $31, 2f
ret_sub3a:
    ret $31, ($26), 0       /* Hint = 0 */
ret_sub3b:
    ret $31, ($26), 1       /* Hint = 1 (normal return) */
2:

    /* Test 4: RET with link register preservation */
    TEST_CASE_START(4)
    bsr $26, ret_sub4
    /* $26 should still have the return address captured */
    br $31, 3f
ret_sub4:
    /* Save $26, call something, restore and return */
    bis $26, $26, $27
    bsr $26, ret_helper4
    ret $31, ($27), 1
ret_helper4:
    ret $31, ($26), 1
3:

    /* Test 5: RET saving return address in Ra */
    TEST_CASE_START(5)
    bsr $26, ret_sub5
    /* After return, continue here */
    br $31, 4f
ret_sub5:
    /* Use ret but save next address in $1 */
    ret $1, ($26), 1
    /* Note: This saves (pc+4) into $1, which is address after ret */
4:

    /* Test 6: Chain of returns */
    TEST_CASE_START(6)
    lda $1, 0($31)
    bsr $26, ret_chain_a
    /* $1 should be 3 */
    lda $5, 3($31)
    cmpeq $1, $5, $6
    beq $6, fail
    br $31, 5f

ret_chain_a:
    addq $1, 1, $1
    bis $26, $26, $9
    bsr $26, ret_chain_b
    ret $31, ($9), 1

ret_chain_b:
    addq $1, 1, $1
    bis $26, $26, $10
    bsr $26, ret_chain_c
    ret $31, ($10), 1

ret_chain_c:
    addq $1, 1, $1
    ret $31, ($26), 1
5:

ALPHA_TEST_END
