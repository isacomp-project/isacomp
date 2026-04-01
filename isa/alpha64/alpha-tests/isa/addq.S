/*
 * Alpha ADDQ (Add Quadword) Test
 * Tests 64-bit integer addition
 * Comprehensive test suite modeled after riscv-tests
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Arithmetic tests
     *-------------------------------------------------------------*/

    /* Test 2: 0 + 0 = 0 */
    TEST_RR_OP(2, addq, 0, 0, 0)

    /* Test 3: 1 + 1 = 2 */
    TEST_RR_OP(3, addq, 2, 1, 1)

    /* Test 4: 3 + 7 = 10 */
    TEST_RR_OP(4, addq, 10, 3, 7)

    /* Test 5: 0 + -32768 (sign extension test) */
    TEST_RR_OP(5, addq, -32768, 0, -32768)

    /* Test 6: -32768 + 0 */
    TEST_RR_OP(6, addq, -32768, -32768, 0)

    /* Test 7: -32768 + -32768 */
    TEST_RR_OP(7, addq, -65536, -32768, -32768)

    /* Test 8: 0 + 32767 */
    TEST_RR_OP(8, addq, 32767, 0, 32767)

    /* Test 9: 32767 + 0 */
    TEST_RR_OP(9, addq, 32767, 32767, 0)

    /* Test 10: 32767 + 32767 */
    TEST_RR_OP(10, addq, 65534, 32767, 32767)

    /* Test 11: -32768 + 32767 */
    TEST_RR_OP(11, addq, -1, -32768, 32767)

    /* Test 12: 32767 + -32768 */
    TEST_RR_OP(12, addq, -1, 32767, -32768)

    /* Test 13: 0 + -1 */
    TEST_RR_OP(13, addq, -1, 0, -1)

    /* Test 14: -1 + 1 = 0 */
    TEST_RR_OP(14, addq, 0, -1, 1)

    /* Test 15: -1 + -1 = -2 */
    TEST_RR_OP(15, addq, -2, -1, -1)

    /* Test 16: 1 + 32767 = 32768 (overflow into positive) */
    TEST_RR_OP(16, addq, 32768, 1, 32767)

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

    /* Test 17: src1 = dest */
    TEST_RR_SRC1_EQ_DEST(17, addq, 24, 13, 11)

    /* Test 18: src2 = dest */
    TEST_RR_SRC2_EQ_DEST(18, addq, 25, 14, 11)

    /* Test 19: src1 = src2 = dest */
    TEST_RR_SRC12_EQ_DEST(19, addq, 26, 13)

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

    /* Destination bypass tests */
    TEST_RR_DEST_BYPASS(20, 0, addq, 24, 13, 11)
    TEST_RR_DEST_BYPASS(21, 1, addq, 25, 14, 11)
    TEST_RR_DEST_BYPASS(22, 2, addq, 26, 15, 11)

    /* Source 1->2 bypass tests */
    TEST_RR_SRC12_BYPASS(23, 0, 0, addq, 24, 13, 11)
    TEST_RR_SRC12_BYPASS(24, 0, 1, addq, 25, 14, 11)
    TEST_RR_SRC12_BYPASS(25, 0, 2, addq, 26, 15, 11)
    TEST_RR_SRC12_BYPASS(26, 1, 0, addq, 24, 13, 11)
    TEST_RR_SRC12_BYPASS(27, 1, 1, addq, 25, 14, 11)
    TEST_RR_SRC12_BYPASS(28, 2, 0, addq, 26, 15, 11)

    /* Source 2->1 bypass tests */
    TEST_RR_SRC21_BYPASS(29, 0, 0, addq, 24, 13, 11)
    TEST_RR_SRC21_BYPASS(30, 0, 1, addq, 25, 14, 11)
    TEST_RR_SRC21_BYPASS(31, 0, 2, addq, 26, 15, 11)
    TEST_RR_SRC21_BYPASS(32, 1, 0, addq, 24, 13, 11)
    TEST_RR_SRC21_BYPASS(33, 1, 1, addq, 25, 14, 11)
    TEST_RR_SRC21_BYPASS(34, 2, 0, addq, 26, 15, 11)

    /*-------------------------------------------------------------
     * Zero register tests
     *-------------------------------------------------------------*/

    /* Test 35: R31 as src1 */
    TEST_RR_ZEROSRC1(35, addq, 15, 15)

    /* Test 36: R31 as src2 */
    TEST_RR_ZEROSRC2(36, addq, 32, 32)

    /* Test 37: R31 as both sources */
    TEST_RR_ZEROSRC12(37, addq, 0)

    /* Test 38: R31 as dest (result should be discarded) */
    TEST_RR_ZERODEST(38, addq, 16, 30)

    /*-------------------------------------------------------------
     * Immediate operand tests (using literal form)
     *-------------------------------------------------------------*/

    /* Test 39: ADDQ with immediate - 10 + 5 = 15 */
    TEST_CASE_START(39)
    lda $1, 10($31)
    addq $1, 5, $3
    lda $5, 15($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 40: ADDQ with immediate - 0 + 255 = 255 (max 8-bit literal) */
    TEST_CASE_START(40)
    lda $1, 0($31)
    addq $1, 255, $3
    lda $5, 255($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 41: ADDQ with immediate - 100 + 0 = 100 */
    TEST_CASE_START(41)
    lda $1, 100($31)
    addq $1, 0, $3
    lda $5, 100($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * All tests passed
     *-------------------------------------------------------------*/

ALPHA_TEST_END
