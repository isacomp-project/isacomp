/*
 * Alpha EQV (Equivalence / XNOR) Test
 * EQV Ra, Rb, Rc: Rc = Ra XNOR Rb = NOT(Ra XOR Rb)
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Equivalence (XNOR) tests
     *-------------------------------------------------------------*/

    /* Test 2: 0x00 XNOR 0x00 = all 1s */
    TEST_CASE_START(2)
    lda $1, 0($31)
    lda $2, 0($31)
    eqv $1, $2, $3
    lda $5, -1($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: 0xFF XNOR 0xFF = all 1s */
    TEST_CASE_START(3)
    lda $1, 0xFF($31)
    lda $2, 0xFF($31)
    eqv $1, $2, $3
    lda $5, -1($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: 0xFF XNOR 0x00 = NOT(0xFF) */
    TEST_CASE_START(4)
    lda $1, 0xFF($31)
    lda $2, 0($31)
    eqv $1, $2, $3
    /* ~(0xFF ^ 0) = ~0xFF = 0xFFFFFFFFFFFFFF00 */
    ldiq $5, 0xFFFFFFFFFFFFFF00
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 5: 0x00 XNOR 0xFF = NOT(0xFF) */
    TEST_CASE_START(5)
    lda $1, 0($31)
    lda $2, 0xFF($31)
    eqv $1, $2, $3
    ldiq $5, 0xFFFFFFFFFFFFFF00
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 6: 0x55 XNOR 0xAA = NOT(0xFF) in low byte */
    TEST_CASE_START(6)
    lda $1, 0x55($31)
    lda $2, 0xAA($31)
    eqv $1, $2, $3
    /* ~(0x55 ^ 0xAA) = ~0xFF = 0xFFFFFFFFFFFFFF00 */
    ldiq $5, 0xFFFFFFFFFFFFFF00
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 7: 0xAA XNOR 0xAA = all 1s */
    TEST_CASE_START(7)
    lda $1, 0xAA($31)
    lda $2, 0xAA($31)
    eqv $1, $2, $3
    lda $5, -1($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 8: R31 XNOR value = NOT(value) */
    TEST_CASE_START(8)
    lda $2, 0x0F($31)
    eqv $31, $2, $3
    /* ~(0 ^ 0x0F) = ~0x0F = 0xFFFFFFFFFFFFFFF0 */
    ldiq $5, 0xFFFFFFFFFFFFFFF0
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
