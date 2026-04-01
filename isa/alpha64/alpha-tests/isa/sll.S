/*
 * Alpha SLL (Shift Left Logical) Test
 * Tests logical left shift: Rc = Ra << (Rb & 63)
 * Comprehensive test suite modeled after riscv-tests
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Arithmetic tests
     *-------------------------------------------------------------*/

    /* Test 2: 1 << 0 = 1 */
    TEST_RR_OP(2, sll, 1, 1, 0)

    /* Test 3: 1 << 1 = 2 */
    TEST_RR_OP(3, sll, 2, 1, 1)

    /* Test 4: 1 << 7 = 128 */
    TEST_RR_OP(4, sll, 128, 1, 7)

    /* Test 5: 1 << 14 = 16384 */
    TEST_RR_OP(5, sll, 16384, 1, 14)

    /* Test 6: 1 << 15 = 32768 */
    TEST_RR_OP(6, sll, 32768, 1, 15)

    /* Test 7: -1 << 0 = -1 */
    TEST_RR_OP(7, sll, -1, -1, 0)

    /* Test 8: -1 << 1 = -2 */
    TEST_RR_OP(8, sll, -2, -1, 1)

    /* Test 9: -1 << 7 = -128 */
    TEST_RR_OP(9, sll, -128, -1, 7)

    /* Test 10: 3 << 5 = 96 */
    TEST_RR_OP(10, sll, 96, 3, 5)

    /* Test 11: 0x55 << 4 = 0x550 */
    TEST_RR_OP(11, sll, 0x550, 0x55, 4)

    /*-------------------------------------------------------------
     * Verify that shifts only use bottom 6 bits (for 64-bit)
     *-------------------------------------------------------------*/

    /* Test 12: Shift amount > 63 should wrap (64 = 0) */
    TEST_CASE_START(12)
    lda $1, 1($31)
    lda $2, 64($31)
    sll $1, $2, $3
    lda $5, 1($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 13: Shift amount 65 = 1 */
    TEST_CASE_START(13)
    lda $1, 1($31)
    lda $2, 65($31)
    sll $1, $2, $3
    lda $5, 2($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

    /* Test 14: src1 = dest */
    TEST_RR_SRC1_EQ_DEST(14, sll, 128, 1, 7)

    /* Test 15: src2 = dest */
    TEST_RR_SRC2_EQ_DEST(15, sll, 16384, 1, 14)

    /* Test 16: src1 = src2 = dest */
    TEST_RR_SRC12_EQ_DEST(16, sll, 24, 3)

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

    /* Destination bypass tests */
    TEST_RR_DEST_BYPASS(17, 0, sll, 128, 1, 7)
    TEST_RR_DEST_BYPASS(18, 1, sll, 16384, 1, 14)
    TEST_RR_DEST_BYPASS(19, 2, sll, 256, 1, 8)

    /* Source 1->2 bypass tests */
    TEST_RR_SRC12_BYPASS(20, 0, 0, sll, 128, 1, 7)
    TEST_RR_SRC12_BYPASS(21, 0, 1, sll, 16384, 1, 14)
    TEST_RR_SRC12_BYPASS(22, 0, 2, sll, 256, 1, 8)
    TEST_RR_SRC12_BYPASS(23, 1, 0, sll, 128, 1, 7)
    TEST_RR_SRC12_BYPASS(24, 1, 1, sll, 16384, 1, 14)
    TEST_RR_SRC12_BYPASS(25, 2, 0, sll, 256, 1, 8)

    /* Source 2->1 bypass tests */
    TEST_RR_SRC21_BYPASS(26, 0, 0, sll, 128, 1, 7)
    TEST_RR_SRC21_BYPASS(27, 0, 1, sll, 16384, 1, 14)
    TEST_RR_SRC21_BYPASS(28, 0, 2, sll, 256, 1, 8)
    TEST_RR_SRC21_BYPASS(29, 1, 0, sll, 128, 1, 7)
    TEST_RR_SRC21_BYPASS(30, 1, 1, sll, 16384, 1, 14)
    TEST_RR_SRC21_BYPASS(31, 2, 0, sll, 256, 1, 8)

    /*-------------------------------------------------------------
     * Zero register tests
     *-------------------------------------------------------------*/

    /* Test 32: R31 as src1 (0 << x = 0) */
    TEST_RR_ZEROSRC1(32, sll, 0, 15)

    /* Test 33: R31 as src2 (x << 0 = x) */
    TEST_RR_ZEROSRC2(33, sll, 32, 32)

    /* Test 34: R31 as both sources (0 << 0 = 0) */
    TEST_RR_ZEROSRC12(34, sll, 0)

    /* Test 35: R31 as dest (result should be discarded) */
    TEST_RR_ZERODEST(35, sll, 1024, 10)

    /*-------------------------------------------------------------
     * Immediate operand tests
     *-------------------------------------------------------------*/

    /* Test 36: SLL with immediate - 1 << 3 = 8 */
    TEST_CASE_START(36)
    lda $1, 1($31)
    sll $1, 3, $3
    lda $5, 8($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 37: SLL with immediate - 0xA << 4 = 0xA0 */
    TEST_CASE_START(37)
    lda $1, 0xA($31)
    sll $1, 4, $3
    lda $5, 0xA0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * All tests passed
     *-------------------------------------------------------------*/

ALPHA_TEST_END
