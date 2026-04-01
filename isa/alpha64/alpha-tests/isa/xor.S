/*
 * Alpha XOR Test
 * Tests bitwise XOR operation
 * Comprehensive test suite modeled after riscv-tests
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Logical tests
     *-------------------------------------------------------------*/

    /* Test 2: 0x00 ^ 0x00 = 0x00 */
    TEST_RR_OP(2, xor, 0, 0, 0)

    /* Test 3: 0xFF ^ 0x00 = 0xFF */
    TEST_RR_OP(3, xor, 0xFF, 0xFF, 0)

    /* Test 4: 0x00 ^ 0xFF = 0xFF */
    TEST_RR_OP(4, xor, 0xFF, 0, 0xFF)

    /* Test 5: 0xFF ^ 0xFF = 0x00 */
    TEST_RR_OP(5, xor, 0, 0xFF, 0xFF)

    /* Test 6: 0x0F ^ 0xF0 = 0xFF */
    TEST_RR_OP(6, xor, 0xFF, 0x0F, 0xF0)

    /* Test 7: 0xAA ^ 0x55 = 0xFF (alternating bits) */
    TEST_RR_OP(7, xor, 0xFF, 0xAA, 0x55)

    /* Test 8: 0x12 ^ 0x34 = 0x26 */
    TEST_RR_OP(8, xor, 0x26, 0x12, 0x34)

    /* Test 9: 0x7FFF ^ 0x00 = 0x7FFF */
    TEST_RR_OP(9, xor, 0x7FFF, 0x7FFF, 0)

    /* Test 10: -1 ^ 0 = -1 */
    TEST_RR_OP(10, xor, -1, -1, 0)

    /* Test 11: -1 ^ -1 = 0 */
    TEST_RR_OP(11, xor, 0, -1, -1)

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

    /* Test 12: src1 = dest */
    TEST_RR_SRC1_EQ_DEST(12, xor, 0xFF, 0xF0, 0x0F)

    /* Test 13: src2 = dest */
    TEST_RR_SRC2_EQ_DEST(13, xor, 0xFF, 0xF0, 0x0F)

    /* Test 14: src1 = src2 = dest (x ^ x = 0) */
    TEST_RR_SRC12_EQ_DEST(14, xor, 0, 0xFF)

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

    /* Destination bypass tests */
    TEST_RR_DEST_BYPASS(15, 0, xor, 0xFF, 0xF0, 0x0F)
    TEST_RR_DEST_BYPASS(16, 1, xor, 0xFF, 0xF0, 0x0F)
    TEST_RR_DEST_BYPASS(17, 2, xor, 0xFF, 0xF0, 0x0F)

    /* Source 1->2 bypass tests */
    TEST_RR_SRC12_BYPASS(18, 0, 0, xor, 0xFF, 0xF0, 0x0F)
    TEST_RR_SRC12_BYPASS(19, 0, 1, xor, 0xFF, 0xF0, 0x0F)
    TEST_RR_SRC12_BYPASS(20, 0, 2, xor, 0xFF, 0xF0, 0x0F)
    TEST_RR_SRC12_BYPASS(21, 1, 0, xor, 0xFF, 0xF0, 0x0F)
    TEST_RR_SRC12_BYPASS(22, 1, 1, xor, 0xFF, 0xF0, 0x0F)
    TEST_RR_SRC12_BYPASS(23, 2, 0, xor, 0xFF, 0xF0, 0x0F)

    /* Source 2->1 bypass tests */
    TEST_RR_SRC21_BYPASS(24, 0, 0, xor, 0xFF, 0xF0, 0x0F)
    TEST_RR_SRC21_BYPASS(25, 0, 1, xor, 0xFF, 0xF0, 0x0F)
    TEST_RR_SRC21_BYPASS(26, 0, 2, xor, 0xFF, 0xF0, 0x0F)
    TEST_RR_SRC21_BYPASS(27, 1, 0, xor, 0xFF, 0xF0, 0x0F)
    TEST_RR_SRC21_BYPASS(28, 1, 1, xor, 0xFF, 0xF0, 0x0F)
    TEST_RR_SRC21_BYPASS(29, 2, 0, xor, 0xFF, 0xF0, 0x0F)

    /*-------------------------------------------------------------
     * Zero register tests
     *-------------------------------------------------------------*/

    /* Test 30: R31 as src1 (0 ^ x = x) */
    TEST_RR_ZEROSRC1(30, xor, 0xFF, 0xFF)

    /* Test 31: R31 as src2 (x ^ 0 = x) */
    TEST_RR_ZEROSRC2(31, xor, 0xFF, 0xFF)

    /* Test 32: R31 as both sources (0 ^ 0 = 0) */
    TEST_RR_ZEROSRC12(32, xor, 0)

    /* Test 33: R31 as dest (result should be discarded) */
    TEST_RR_ZERODEST(33, xor, 0x11, 0x22)

    /*-------------------------------------------------------------
     * Self-XOR (should always be 0)
     *-------------------------------------------------------------*/

    /* Test 34: x ^ x = 0 */
    TEST_CASE_START(34)
    lda $1, 0x5A($31)
    xor $1, $1, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Immediate operand tests
     *-------------------------------------------------------------*/

    /* Test 35: XOR with immediate - 0xFF ^ 0x0F = 0xF0 */
    TEST_CASE_START(35)
    lda $1, 0xFF($31)
    xor $1, 0x0F, $3
    lda $5, 0xF0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 36: XOR with immediate - 0x00 ^ 0xFF = 0xFF */
    TEST_CASE_START(36)
    lda $1, 0($31)
    xor $1, 0xFF, $3
    lda $5, 0xFF($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * All tests passed
     *-------------------------------------------------------------*/

ALPHA_TEST_END
