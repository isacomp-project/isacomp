/*
 * Alpha SUBQ (Subtract Quadword) Test
 * Tests 64-bit integer subtraction
 * Comprehensive test suite modeled after riscv-tests
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Arithmetic tests
     *-------------------------------------------------------------*/

    /* Test 2: 0 - 0 = 0 */
    TEST_RR_OP(2, subq, 0, 0, 0)

    /* Test 3: 2 - 1 = 1 */
    TEST_RR_OP(3, subq, 1, 2, 1)

    /* Test 4: 10 - 3 = 7 */
    TEST_RR_OP(4, subq, 7, 10, 3)

    /* Test 5: 0 - (-32768) = 32768 */
    TEST_RR_OP(5, subq, 32768, 0, -32768)

    /* Test 6: -32768 - 0 = -32768 */
    TEST_RR_OP(6, subq, -32768, -32768, 0)

    /* Test 7: -32768 - (-32768) = 0 */
    TEST_RR_OP(7, subq, 0, -32768, -32768)

    /* Test 8: 0 - 32767 = -32767 */
    TEST_RR_OP(8, subq, -32767, 0, 32767)

    /* Test 9: 32767 - 0 = 32767 */
    TEST_RR_OP(9, subq, 32767, 32767, 0)

    /* Test 10: 32767 - 32767 = 0 */
    TEST_RR_OP(10, subq, 0, 32767, 32767)

    /* Test 11: -32768 - 32767 = -65535 */
    TEST_RR_OP(11, subq, -65535, -32768, 32767)

    /* Test 12: 32767 - (-32768) = 65535 */
    TEST_RR_OP(12, subq, 65535, 32767, -32768)

    /* Test 13: 0 - (-1) = 1 */
    TEST_RR_OP(13, subq, 1, 0, -1)

    /* Test 14: -1 - 1 = -2 */
    TEST_RR_OP(14, subq, -2, -1, 1)

    /* Test 15: -1 - (-1) = 0 */
    TEST_RR_OP(15, subq, 0, -1, -1)

    /* Test 16: 1 - 32767 = -32766 */
    TEST_RR_OP(16, subq, -32766, 1, 32767)

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

    /* Test 17: src1 = dest */
    TEST_RR_SRC1_EQ_DEST(17, subq, 2, 13, 11)

    /* Test 18: src2 = dest */
    TEST_RR_SRC2_EQ_DEST(18, subq, 3, 14, 11)

    /* Test 19: src1 = src2 = dest (x - x = 0) */
    TEST_RR_SRC12_EQ_DEST(19, subq, 0, 13)

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

    /* Destination bypass tests */
    TEST_RR_DEST_BYPASS(20, 0, subq, 2, 13, 11)
    TEST_RR_DEST_BYPASS(21, 1, subq, 3, 14, 11)
    TEST_RR_DEST_BYPASS(22, 2, subq, 4, 15, 11)

    /* Source 1->2 bypass tests */
    TEST_RR_SRC12_BYPASS(23, 0, 0, subq, 2, 13, 11)
    TEST_RR_SRC12_BYPASS(24, 0, 1, subq, 3, 14, 11)
    TEST_RR_SRC12_BYPASS(25, 0, 2, subq, 4, 15, 11)
    TEST_RR_SRC12_BYPASS(26, 1, 0, subq, 2, 13, 11)
    TEST_RR_SRC12_BYPASS(27, 1, 1, subq, 3, 14, 11)
    TEST_RR_SRC12_BYPASS(28, 2, 0, subq, 4, 15, 11)

    /* Source 2->1 bypass tests */
    TEST_RR_SRC21_BYPASS(29, 0, 0, subq, 2, 13, 11)
    TEST_RR_SRC21_BYPASS(30, 0, 1, subq, 3, 14, 11)
    TEST_RR_SRC21_BYPASS(31, 0, 2, subq, 4, 15, 11)
    TEST_RR_SRC21_BYPASS(32, 1, 0, subq, 2, 13, 11)
    TEST_RR_SRC21_BYPASS(33, 1, 1, subq, 3, 14, 11)
    TEST_RR_SRC21_BYPASS(34, 2, 0, subq, 4, 15, 11)

    /*-------------------------------------------------------------
     * Zero register tests
     *-------------------------------------------------------------*/

    /* Test 35: R31 as src1 (0 - x = -x) */
    TEST_RR_ZEROSRC1(35, subq, -15, 15)

    /* Test 36: R31 as src2 (x - 0 = x) */
    TEST_RR_ZEROSRC2(36, subq, 32, 32)

    /* Test 37: R31 as both sources (0 - 0 = 0) */
    TEST_RR_ZEROSRC12(37, subq, 0)

    /* Test 38: R31 as dest (result should be discarded) */
    TEST_RR_ZERODEST(38, subq, 30, 16)

    /*-------------------------------------------------------------
     * Immediate operand tests (using literal form)
     *-------------------------------------------------------------*/

    /* Test 39: SUBQ with immediate - 20 - 5 = 15 */
    TEST_CASE_START(39)
    lda $1, 20($31)
    subq $1, 5, $3
    lda $5, 15($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 40: SUBQ with immediate - 255 - 255 = 0 */
    TEST_CASE_START(40)
    lda $1, 255($31)
    subq $1, 255, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 41: SUBQ with immediate - 100 - 0 = 100 */
    TEST_CASE_START(41)
    lda $1, 100($31)
    subq $1, 0, $3
    lda $5, 100($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * All tests passed
     *-------------------------------------------------------------*/

ALPHA_TEST_END
