/*
 * Alpha AND Test
 * Tests bitwise AND operation
 * Comprehensive test suite modeled after riscv-tests
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Logical tests
     *-------------------------------------------------------------*/

    /* Test 2: 0xFF & 0xFF = 0xFF */
    TEST_RR_OP(2, and, 0xFF, 0xFF, 0xFF)

    /* Test 3: 0xFF & 0x00 = 0x00 */
    TEST_RR_OP(3, and, 0, 0xFF, 0)

    /* Test 4: 0x0F & 0xF0 = 0x00 */
    TEST_RR_OP(4, and, 0, 0x0F, 0xF0)

    /* Test 5: 0xFF & 0x0F = 0x0F */
    TEST_RR_OP(5, and, 0x0F, 0xFF, 0x0F)

    /* Test 6: 0xAA & 0x55 = 0x00 (alternating bits) */
    TEST_RR_OP(6, and, 0, 0xAA, 0x55)

    /* Test 7: 0xAA & 0xAA = 0xAA */
    TEST_RR_OP(7, and, 0xAA, 0xAA, 0xAA)

    /* Test 8: 0x7FFF & 0x7FFF = 0x7FFF (max positive 16-bit) */
    TEST_RR_OP(8, and, 0x7FFF, 0x7FFF, 0x7FFF)

    /* Test 9: -1 & 0xFF = 0xFF */
    TEST_RR_OP(9, and, 0xFF, -1, 0xFF)

    /* Test 10: -1 & -1 = -1 */
    TEST_RR_OP(10, and, -1, -1, -1)

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

    /* Test 11: src1 = dest */
    TEST_RR_SRC1_EQ_DEST(11, and, 0x0F, 0xFF, 0x0F)

    /* Test 12: src2 = dest */
    TEST_RR_SRC2_EQ_DEST(12, and, 0xF0, 0xFF, 0xF0)

    /* Test 13: src1 = src2 = dest (x & x = x) */
    TEST_RR_SRC12_EQ_DEST(13, and, 0xFF, 0xFF)

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

    /* Destination bypass tests */
    TEST_RR_DEST_BYPASS(14, 0, and, 0x0F, 0xFF, 0x0F)
    TEST_RR_DEST_BYPASS(15, 1, and, 0xF0, 0xFF, 0xF0)
    TEST_RR_DEST_BYPASS(16, 2, and, 0x0F, 0x0F, 0x0F)

    /* Source 1->2 bypass tests */
    TEST_RR_SRC12_BYPASS(17, 0, 0, and, 0x0F, 0xFF, 0x0F)
    TEST_RR_SRC12_BYPASS(18, 0, 1, and, 0xF0, 0xFF, 0xF0)
    TEST_RR_SRC12_BYPASS(19, 0, 2, and, 0x0F, 0x0F, 0x0F)
    TEST_RR_SRC12_BYPASS(20, 1, 0, and, 0x0F, 0xFF, 0x0F)
    TEST_RR_SRC12_BYPASS(21, 1, 1, and, 0xF0, 0xFF, 0xF0)
    TEST_RR_SRC12_BYPASS(22, 2, 0, and, 0x0F, 0x0F, 0x0F)

    /* Source 2->1 bypass tests */
    TEST_RR_SRC21_BYPASS(23, 0, 0, and, 0x0F, 0xFF, 0x0F)
    TEST_RR_SRC21_BYPASS(24, 0, 1, and, 0xF0, 0xFF, 0xF0)
    TEST_RR_SRC21_BYPASS(25, 0, 2, and, 0x0F, 0x0F, 0x0F)
    TEST_RR_SRC21_BYPASS(26, 1, 0, and, 0x0F, 0xFF, 0x0F)
    TEST_RR_SRC21_BYPASS(27, 1, 1, and, 0xF0, 0xFF, 0xF0)
    TEST_RR_SRC21_BYPASS(28, 2, 0, and, 0x0F, 0x0F, 0x0F)

    /*-------------------------------------------------------------
     * Zero register tests
     *-------------------------------------------------------------*/

    /* Test 29: R31 as src1 (0 & x = 0) */
    TEST_RR_ZEROSRC1(29, and, 0, 0xFF)

    /* Test 30: R31 as src2 (x & 0 = 0) */
    TEST_RR_ZEROSRC2(30, and, 0, 0xFF)

    /* Test 31: R31 as both sources (0 & 0 = 0) */
    TEST_RR_ZEROSRC12(31, and, 0)

    /* Test 32: R31 as dest (result should be discarded) */
    TEST_RR_ZERODEST(32, and, 0x11, 0x22)

    /*-------------------------------------------------------------
     * Immediate operand tests
     *-------------------------------------------------------------*/

    /* Test 33: AND with immediate - 0xFF & 0x0F = 0x0F */
    TEST_CASE_START(33)
    lda $1, 0xFF($31)
    and $1, 0x0F, $3
    lda $5, 0x0F($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 34: AND with immediate - 0xAB & 0xF0 = 0xA0 */
    TEST_CASE_START(34)
    lda $1, 0xAB($31)
    and $1, 0xF0, $3
    lda $5, 0xA0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * All tests passed
     *-------------------------------------------------------------*/

ALPHA_TEST_END
