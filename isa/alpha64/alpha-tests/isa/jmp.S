/*
 * Alpha JMP (Jump) Test
 * Tests indirect jump instruction
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Indirect jump tests
     *-------------------------------------------------------------*/

    /* Test 2: Simple indirect jump */
    TEST_JMP(2)

    /* Test 3: JMP with computed target */
    TEST_CASE_START(3)
    br $27, 1f
1:  lda $27, target3 - 1b($27)
    jmp $31, ($27)
    br $31, fail
target3:

    /* Test 4: JMP through register, save return in $26 */
    TEST_CASE_START(4)
    br $27, 1f
1:  lda $27, target4 - 1b($27)
    jmp $26, ($27)
    br $31, 2f    /* This should execute after ret */
target4:
    ret $31, ($26), 1
2:

    /* Test 5: Multiple consecutive jumps */
    TEST_CASE_START(5)
    br $27, 1f
1:  lda $27, 2f - 1b($27)
    jmp $31, ($27)
    br $31, fail
2:  br $27, 3f
3:  lda $27, 4f - 3b($27)
    jmp $31, ($27)
    br $31, fail
4:

ALPHA_TEST_END
