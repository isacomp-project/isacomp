/*
 * Alpha BIS (Bitwise OR) Test
 * Tests bitwise OR operation
 * Note: BIS is Alpha's name for OR
 * Comprehensive test suite modeled after riscv-tests
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Logical tests
     *-------------------------------------------------------------*/

    /* Test 2: 0x00 | 0x00 = 0x00 */
    TEST_RR_OP(2, bis, 0, 0, 0)

    /* Test 3: 0xFF | 0x00 = 0xFF */
    TEST_RR_OP(3, bis, 0xFF, 0xFF, 0)

    /* Test 4: 0x00 | 0xFF = 0xFF */
    TEST_RR_OP(4, bis, 0xFF, 0, 0xFF)

    /* Test 5: 0x0F | 0xF0 = 0xFF */
    TEST_RR_OP(5, bis, 0xFF, 0x0F, 0xF0)

    /* Test 6: 0xAA | 0x55 = 0xFF (alternating bits) */
    TEST_RR_OP(6, bis, 0xFF, 0xAA, 0x55)

    /* Test 7: 0x12 | 0x34 = 0x36 */
    TEST_RR_OP(7, bis, 0x36, 0x12, 0x34)

    /* Test 8: 0x7FFF | 0x00 = 0x7FFF */
    TEST_RR_OP(8, bis, 0x7FFF, 0x7FFF, 0)

    /* Test 9: -1 | 0 = -1 */
    TEST_RR_OP(9, bis, -1, -1, 0)

    /* Test 10: 0 | -1 = -1 */
    TEST_RR_OP(10, bis, -1, 0, -1)

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

    /* Test 11: src1 = dest */
    TEST_RR_SRC1_EQ_DEST(11, bis, 0xFF, 0xF0, 0x0F)

    /* Test 12: src2 = dest */
    TEST_RR_SRC2_EQ_DEST(12, bis, 0xFF, 0xF0, 0x0F)

    /* Test 13: src1 = src2 = dest (x | x = x) */
    TEST_RR_SRC12_EQ_DEST(13, bis, 0xFF, 0xFF)

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

    /* Destination bypass tests */
    TEST_RR_DEST_BYPASS(14, 0, bis, 0xFF, 0xF0, 0x0F)
    TEST_RR_DEST_BYPASS(15, 1, bis, 0xFF, 0xF0, 0x0F)
    TEST_RR_DEST_BYPASS(16, 2, bis, 0xFF, 0xF0, 0x0F)

    /* Source 1->2 bypass tests */
    TEST_RR_SRC12_BYPASS(17, 0, 0, bis, 0xFF, 0xF0, 0x0F)
    TEST_RR_SRC12_BYPASS(18, 0, 1, bis, 0xFF, 0xF0, 0x0F)
    TEST_RR_SRC12_BYPASS(19, 0, 2, bis, 0xFF, 0xF0, 0x0F)
    TEST_RR_SRC12_BYPASS(20, 1, 0, bis, 0xFF, 0xF0, 0x0F)
    TEST_RR_SRC12_BYPASS(21, 1, 1, bis, 0xFF, 0xF0, 0x0F)
    TEST_RR_SRC12_BYPASS(22, 2, 0, bis, 0xFF, 0xF0, 0x0F)

    /* Source 2->1 bypass tests */
    TEST_RR_SRC21_BYPASS(23, 0, 0, bis, 0xFF, 0xF0, 0x0F)
    TEST_RR_SRC21_BYPASS(24, 0, 1, bis, 0xFF, 0xF0, 0x0F)
    TEST_RR_SRC21_BYPASS(25, 0, 2, bis, 0xFF, 0xF0, 0x0F)
    TEST_RR_SRC21_BYPASS(26, 1, 0, bis, 0xFF, 0xF0, 0x0F)
    TEST_RR_SRC21_BYPASS(27, 1, 1, bis, 0xFF, 0xF0, 0x0F)
    TEST_RR_SRC21_BYPASS(28, 2, 0, bis, 0xFF, 0xF0, 0x0F)

    /*-------------------------------------------------------------
     * Zero register tests
     *-------------------------------------------------------------*/

    /* Test 29: R31 as src1 (0 | x = x) */
    TEST_RR_ZEROSRC1(29, bis, 0xFF, 0xFF)

    /* Test 30: R31 as src2 (x | 0 = x) */
    TEST_RR_ZEROSRC2(30, bis, 0xFF, 0xFF)

    /* Test 31: R31 as both sources (0 | 0 = 0) */
    TEST_RR_ZEROSRC12(31, bis, 0)

    /* Test 32: R31 as dest (result should be discarded) */
    TEST_RR_ZERODEST(32, bis, 0x11, 0x22)

    /*-------------------------------------------------------------
     * BIS as MOV (copy register)
     * BIS $src, $31, $dst is commonly used as MOV
     *-------------------------------------------------------------*/

    /* Test 33: MOV via BIS - copy 42 to another register */
    TEST_CASE_START(33)
    lda $1, 42($31)
    bis $1, $31, $3
    lda $5, 42($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 34: MOV via BIS - copy 0 */
    TEST_CASE_START(34)
    lda $1, 100($31)
    bis $31, $31, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Immediate operand tests
     *-------------------------------------------------------------*/

    /* Test 35: BIS with immediate - 0xF0 | 0x0F = 0xFF */
    TEST_CASE_START(35)
    lda $1, 0xF0($31)
    bis $1, 0x0F, $3
    lda $5, 0xFF($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 36: BIS with immediate - 0x00 | 0xFF = 0xFF */
    TEST_CASE_START(36)
    lda $1, 0($31)
    bis $1, 0xFF, $3
    lda $5, 0xFF($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * All tests passed
     *-------------------------------------------------------------*/

ALPHA_TEST_END
