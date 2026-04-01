/*
 * Alpha CMPEQ (Compare Equal) Test
 * Tests: Rc = (Ra == Rb) ? 1 : 0
 * Comprehensive test suite modeled after riscv-tests
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Equal values (result = 1)
     *-------------------------------------------------------------*/

    /* Test 2: 0 == 0 -> 1 */
    TEST_CMP(2, cmpeq, 1, 0, 0)

    /* Test 3: 1 == 1 -> 1 */
    TEST_CMP(3, cmpeq, 1, 1, 1)

    /* Test 4: -1 == -1 -> 1 */
    TEST_CMP(4, cmpeq, 1, -1, -1)

    /* Test 5: 32767 == 32767 -> 1 */
    TEST_CMP(5, cmpeq, 1, 32767, 32767)

    /* Test 6: -32768 == -32768 -> 1 */
    TEST_CMP(6, cmpeq, 1, -32768, -32768)

    /*-------------------------------------------------------------
     * Unequal values (result = 0)
     *-------------------------------------------------------------*/

    /* Test 7: 0 == 1 -> 0 */
    TEST_CMP(7, cmpeq, 0, 0, 1)

    /* Test 8: 1 == 0 -> 0 */
    TEST_CMP(8, cmpeq, 0, 1, 0)

    /* Test 9: -1 == 1 -> 0 */
    TEST_CMP(9, cmpeq, 0, -1, 1)

    /* Test 10: 1 == -1 -> 0 */
    TEST_CMP(10, cmpeq, 0, 1, -1)

    /* Test 11: 0 == -1 -> 0 */
    TEST_CMP(11, cmpeq, 0, 0, -1)

    /* Test 12: -1 == 0 -> 0 */
    TEST_CMP(12, cmpeq, 0, -1, 0)

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

    /* Test 13: src1 = dest */
    TEST_RR_SRC1_EQ_DEST(13, cmpeq, 1, 13, 13)

    /* Test 14: src2 = dest */
    TEST_RR_SRC2_EQ_DEST(14, cmpeq, 1, 14, 14)

    /* Test 15: src1 = src2 = dest (always true: x == x) */
    TEST_RR_SRC12_EQ_DEST(15, cmpeq, 1, 13)

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

    /* Destination bypass tests */
    TEST_RR_DEST_BYPASS(16, 0, cmpeq, 1, 13, 13)
    TEST_RR_DEST_BYPASS(17, 1, cmpeq, 0, 14, 13)
    TEST_RR_DEST_BYPASS(18, 2, cmpeq, 1, 15, 15)

    /* Source 1->2 bypass tests */
    TEST_RR_SRC12_BYPASS(19, 0, 0, cmpeq, 1, 13, 13)
    TEST_RR_SRC12_BYPASS(20, 0, 1, cmpeq, 0, 14, 13)
    TEST_RR_SRC12_BYPASS(21, 0, 2, cmpeq, 1, 15, 15)
    TEST_RR_SRC12_BYPASS(22, 1, 0, cmpeq, 1, 13, 13)
    TEST_RR_SRC12_BYPASS(23, 1, 1, cmpeq, 0, 14, 13)
    TEST_RR_SRC12_BYPASS(24, 2, 0, cmpeq, 1, 15, 15)

    /* Source 2->1 bypass tests */
    TEST_RR_SRC21_BYPASS(25, 0, 0, cmpeq, 1, 13, 13)
    TEST_RR_SRC21_BYPASS(26, 0, 1, cmpeq, 0, 14, 13)
    TEST_RR_SRC21_BYPASS(27, 0, 2, cmpeq, 1, 15, 15)
    TEST_RR_SRC21_BYPASS(28, 1, 0, cmpeq, 1, 13, 13)
    TEST_RR_SRC21_BYPASS(29, 1, 1, cmpeq, 0, 14, 13)
    TEST_RR_SRC21_BYPASS(30, 2, 0, cmpeq, 1, 15, 15)

    /*-------------------------------------------------------------
     * Zero register tests
     *-------------------------------------------------------------*/

    /* Test 31: R31 as src1 (0 == x) */
    TEST_RR_ZEROSRC1(31, cmpeq, 0, 1)

    /* Test 32: R31 as src2 (x == 0) */
    TEST_RR_ZEROSRC2(32, cmpeq, 0, 1)

    /* Test 33: R31 as both sources (0 == 0) */
    TEST_RR_ZEROSRC12(33, cmpeq, 1)

    /* Test 34: R31 as dest */
    TEST_RR_ZERODEST(34, cmpeq, 1, 1)

    /*-------------------------------------------------------------
     * Immediate operand tests
     *-------------------------------------------------------------*/

    /* Test 35: CMPEQ with immediate - 5 == 5 -> 1 */
    TEST_CASE_START(35)
    lda $1, 5($31)
    cmpeq $1, 5, $3
    lda $5, 1($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 36: CMPEQ with immediate - 5 == 10 -> 0 */
    TEST_CASE_START(36)
    lda $1, 5($31)
    cmpeq $1, 10, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * All tests passed
     *-------------------------------------------------------------*/

ALPHA_TEST_END
