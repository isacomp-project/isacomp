/*
 * Alpha ORNOT (Or Not) Test
 * ORNOT Ra, Rb, Rc: Rc = Ra OR NOT(Rb)
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Or-not tests
     *-------------------------------------------------------------*/

    /* Test 2: 0x00 OR NOT(0x00) = 0xFFFFFFFFFFFFFFFF (all 1s) */
    TEST_CASE_START(2)
    lda $1, 0($31)
    lda $2, 0($31)
    ornot $1, $2, $3
    lda $5, -1($31)         /* -1 = all 1s */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: 0xFF OR NOT(0xFF) = all 1s */
    TEST_CASE_START(3)
    lda $1, 0xFF($31)
    lda $2, 0xFF($31)
    ornot $1, $2, $3
    /* Result: 0xFF | ~0xFF = 0xFF | 0xFFFFFFFFFFFFFF00 = all 1s */
    lda $5, -1($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: 0x00 OR NOT(0xFF) */
    TEST_CASE_START(4)
    lda $1, 0($31)
    lda $2, 0xFF($31)
    ornot $1, $2, $3
    /* 0 | ~0xFF = 0xFFFFFFFFFFFFFF00 */
    ldiq $5, 0xFFFFFFFFFFFFFF00
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 5: 0xFF OR NOT(0x00) = all 1s */
    TEST_CASE_START(5)
    lda $1, 0xFF($31)
    lda $2, 0($31)
    ornot $1, $2, $3
    lda $5, -1($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 6: 0x55 OR NOT(0xAA) */
    TEST_CASE_START(6)
    lda $1, 0x55($31)
    lda $2, 0xAA($31)
    ornot $1, $2, $3
    /* 0x55 | ~0xAA = 0x55 | 0xFFFFFFFFFFFFFF55 = 0xFFFFFFFFFFFFFF55 */
    /* Note: ~0xAA has same low byte as 0x55, so OR preserves them */
    ldiq $5, 0xFFFFFFFFFFFFFF55
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 7: R31 as first source */
    TEST_CASE_START(7)
    lda $2, 0($31)
    ornot $31, $2, $3
    /* 0 OR NOT(0) = all 1s */
    lda $5, -1($31)
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
