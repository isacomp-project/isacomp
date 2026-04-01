/*
 * Alpha BSR (Branch to Subroutine) Test
 * Tests branch to subroutine and return
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Branch to subroutine tests
     *-------------------------------------------------------------*/

    /* Test 2: Simple BSR and RET */
    TEST_BSR(2)

    /* Test 3: BSR with work in subroutine */
    TEST_CASE_START(3)
    lda $1, 5($31)
    bsr $26, sub3
    /* After return, $1 should be 10 */
    lda $5, 10($31)
    cmpeq $1, $5, $6
    beq $6, fail
    br $31, 1f

sub3:
    addq $1, $1, $1     /* Double the value */
    ret $31, ($26), 1
1:

    /* Test 4: Nested BSR calls */
    TEST_CASE_START(4)
    lda $1, 1($31)
    bsr $26, sub4a
    /* After return, $1 should be 4 (1+1+1+1) */
    lda $5, 4($31)
    cmpeq $1, $5, $6
    beq $6, fail
    br $31, 2f

sub4a:
    addq $1, 1, $1
    /* Save return address */
    bis $26, $26, $27
    bsr $26, sub4b
    /* Restore and return */
    ret $31, ($27), 1

sub4b:
    addq $1, 1, $1
    bis $26, $26, $28
    bsr $26, sub4c
    ret $31, ($28), 1

sub4c:
    addq $1, 1, $1
    ret $31, ($26), 1
2:

    /* Test 5: BSR with stack-like saves */
    TEST_CASE_START(5)
    lda $1, 100($31)
    bsr $26, sub5
    /* $1 should still be 100 (restored) */
    lda $5, 100($31)
    cmpeq $1, $5, $6
    beq $6, fail
    br $31, 3f

sub5:
    /* Save $1 to scratch register */
    bis $1, $1, $2
    /* Modify $1 */
    lda $1, 0($31)
    /* Restore $1 */
    bis $2, $2, $1
    ret $31, ($26), 1
3:

ALPHA_TEST_END
