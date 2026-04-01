/*
 * Alpha JSR (Jump to Subroutine) Test
 * Tests indirect jump to subroutine with return address linkage
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Jump to subroutine tests
     *-------------------------------------------------------------*/

    /* Test 2: Simple JSR and RET */
    TEST_JSR_RET(2)

    /* Test 3: JSR with parameter passing */
    TEST_CASE_START(3)
    lda $16, 10($31)        /* Argument in $16 */
    br $27, 1f
1:  lda $27, jsr_sub3 - 1b($27)
    jsr $26, ($27)
    /* Result should be 20 in $0 */
    lda $5, 20($31)
    cmpeq $0, $5, $6
    beq $6, fail
    br $31, 2f

jsr_sub3:
    addq $16, $16, $0       /* Return 2 * arg */
    ret $31, ($26), 1
2:

    /* Test 4: Nested JSR calls */
    TEST_CASE_START(4)
    lda $16, 5($31)
    br $27, 1f
1:  lda $27, jsr_sub4a - 1b($27)
    jsr $26, ($27)
    /* Result should be 15 (5 * 3) */
    lda $5, 15($31)
    cmpeq $0, $5, $6
    beq $6, fail
    br $31, 3f

jsr_sub4a:
    /* Triple the argument via two nested calls */
    bis $26, $26, $9        /* Save return address */
    br $27, 4f
4:  lda $27, jsr_sub4b - 4b($27)
    jsr $26, ($27)
    /* Now $0 = 2*arg, add arg again */
    addq $0, $16, $0
    ret $31, ($9), 1

jsr_sub4b:
    addq $16, $16, $0       /* Return 2 * arg */
    ret $31, ($26), 1
3:

    /* Test 5: JSR hint field (just verify it doesn't crash) */
    TEST_CASE_START(5)
    br $27, 1f
1:  lda $27, jsr_sub5 - 1b($27)
    jsr $26, ($27), 1       /* Hint = 1 (return) */
    br $31, 5f

jsr_sub5:
    ret $31, ($26), 1
5:

ALPHA_TEST_END
