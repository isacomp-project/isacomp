/*
 * Alpha BIC (Bit Clear) Test
 * BIC Ra, Rb, Rc: Rc = Ra AND NOT(Rb)
 * Clears bits in Ra that are set in Rb
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Bit clear tests
     *-------------------------------------------------------------*/

    /* Test 2: Clear all bits - 0xFF AND NOT(0xFF) = 0x00 */
    TEST_LOGIC_OP(2, bic, 0x00, 0xFF, 0xFF)

    /* Test 3: Clear no bits - 0xFF AND NOT(0x00) = 0xFF */
    TEST_LOGIC_OP(3, bic, 0xFF, 0xFF, 0x00)

    /* Test 4: Clear low nibble - 0xFF AND NOT(0x0F) = 0xF0 */
    TEST_LOGIC_OP(4, bic, 0xF0, 0xFF, 0x0F)

    /* Test 5: Clear high nibble - 0xFF AND NOT(0xF0) = 0x0F */
    TEST_LOGIC_OP(5, bic, 0x0F, 0xFF, 0xF0)

    /* Test 6: Alternating bits - 0xFF AND NOT(0xAA) = 0x55 */
    TEST_LOGIC_OP(6, bic, 0x55, 0xFF, 0xAA)

    /* Test 7: Clear single bit - 0xFF AND NOT(0x01) = 0xFE */
    TEST_LOGIC_OP(7, bic, 0xFE, 0xFF, 0x01)

    /* Test 8: Zero source - 0x00 AND NOT(0xFF) = 0x00 */
    TEST_LOGIC_OP(8, bic, 0x00, 0x00, 0xFF)

    /* Test 9: Larger values */
    TEST_LOGIC_OP(9, bic, 0x0F00, 0xFF00, 0xF000)

    /* Test 10: src1 = src2 = dest overlap */
    TEST_CASE_START(10)
    lda $1, 0x5555($31)
    bic $1, $1, $1
    /* Result should be 0 (x AND NOT(x) = 0) */
    bne $1, fail

    /* Test 11: R31 as source */
    TEST_CASE_START(11)
    lda $2, 0xFF($31)
    bic $31, $2, $3
    /* 0 AND NOT(x) = 0 */
    bne $3, fail

    /* Test 12: R31 as mask */
    TEST_CASE_START(12)
    lda $1, 0x1234($31)
    bic $1, $31, $3
    /* x AND NOT(0) = x */
    lda $5, 0x1234($31)
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
