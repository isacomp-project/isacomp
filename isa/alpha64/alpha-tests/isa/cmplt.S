/*
 * Alpha CMPLT (Compare Less Than) Test
 * Tests signed comparison: Rc = (Ra < Rb) ? 1 : 0
 * Comprehensive test suite modeled after riscv-tests
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Less than (result = 1)
     *-------------------------------------------------------------*/

    /* Test 2: 0 < 1 -> 1 */
    TEST_CMP(2, cmplt, 1, 0, 1)

    /* Test 3: -1 < 0 -> 1 */
    TEST_CMP(3, cmplt, 1, -1, 0)

    /* Test 4: -1 < 1 -> 1 */
    TEST_CMP(4, cmplt, 1, -1, 1)

    /* Test 5: -32768 < 32767 -> 1 */
    TEST_CMP(5, cmplt, 1, -32768, 32767)

    /* Test 6: -32768 < -1 -> 1 */
    TEST_CMP(6, cmplt, 1, -32768, -1)

    /* Test 7: 0 < 32767 -> 1 */
    TEST_CMP(7, cmplt, 1, 0, 32767)

    /*-------------------------------------------------------------
     * Greater than or equal (result = 0)
     *-------------------------------------------------------------*/

    /* Test 8: 1 < 0 -> 0 */
    TEST_CMP(8, cmplt, 0, 1, 0)

    /* Test 9: 0 < -1 -> 0 */
    TEST_CMP(9, cmplt, 0, 0, -1)

    /* Test 10: 1 < -1 -> 0 */
    TEST_CMP(10, cmplt, 0, 1, -1)

    /* Test 11: 32767 < -32768 -> 0 */
    TEST_CMP(11, cmplt, 0, 32767, -32768)

    /* Test 12: -1 < -32768 -> 0 */
    TEST_CMP(12, cmplt, 0, -1, -32768)

    /*-------------------------------------------------------------
     * Equal values (result = 0)
     *-------------------------------------------------------------*/

    /* Test 13: 0 < 0 -> 0 */
    TEST_CMP(13, cmplt, 0, 0, 0)

    /* Test 14: 1 < 1 -> 0 */
    TEST_CMP(14, cmplt, 0, 1, 1)

    /* Test 15: -1 < -1 -> 0 */
    TEST_CMP(15, cmplt, 0, -1, -1)

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

    /* Test 16: src1 = dest */
    TEST_RR_SRC1_EQ_DEST(16, cmplt, 1, 11, 13)

    /* Test 17: src2 = dest */
    TEST_RR_SRC2_EQ_DEST(17, cmplt, 0, 14, 13)

    /* Test 18: src1 = src2 = dest (x < x = 0) */
    TEST_RR_SRC12_EQ_DEST(18, cmplt, 0, 13)

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

    /* Destination bypass tests */
    TEST_RR_DEST_BYPASS(19, 0, cmplt, 1, 11, 13)
    TEST_RR_DEST_BYPASS(20, 1, cmplt, 0, 14, 13)
    TEST_RR_DEST_BYPASS(21, 2, cmplt, 1, 13, 15)

    /* Source 1->2 bypass tests */
    TEST_RR_SRC12_BYPASS(22, 0, 0, cmplt, 1, 11, 13)
    TEST_RR_SRC12_BYPASS(23, 0, 1, cmplt, 0, 14, 13)
    TEST_RR_SRC12_BYPASS(24, 0, 2, cmplt, 1, 13, 15)
    TEST_RR_SRC12_BYPASS(25, 1, 0, cmplt, 1, 11, 13)
    TEST_RR_SRC12_BYPASS(26, 1, 1, cmplt, 0, 14, 13)
    TEST_RR_SRC12_BYPASS(27, 2, 0, cmplt, 1, 13, 15)

    /* Source 2->1 bypass tests */
    TEST_RR_SRC21_BYPASS(28, 0, 0, cmplt, 1, 11, 13)
    TEST_RR_SRC21_BYPASS(29, 0, 1, cmplt, 0, 14, 13)
    TEST_RR_SRC21_BYPASS(30, 0, 2, cmplt, 1, 13, 15)
    TEST_RR_SRC21_BYPASS(31, 1, 0, cmplt, 1, 11, 13)
    TEST_RR_SRC21_BYPASS(32, 1, 1, cmplt, 0, 14, 13)
    TEST_RR_SRC21_BYPASS(33, 2, 0, cmplt, 1, 13, 15)

    /*-------------------------------------------------------------
     * Zero register tests
     *-------------------------------------------------------------*/

    /* Test 34: R31 as src1 (0 < x = 1 for x > 0) */
    TEST_RR_ZEROSRC1(34, cmplt, 1, 1)

    /* Test 35: R31 as src2 (x < 0 = 1 for x < 0) */
    TEST_RR_ZEROSRC2(35, cmplt, 1, -1)

    /* Test 36: R31 as both sources (0 < 0 = 0) */
    TEST_RR_ZEROSRC12(36, cmplt, 0)

    /* Test 37: R31 as dest */
    TEST_RR_ZERODEST(37, cmplt, 1, 2)

    /*-------------------------------------------------------------
     * Immediate operand tests
     *-------------------------------------------------------------*/

    /* Test 38: CMPLT with immediate - 5 < 10 -> 1 */
    TEST_CASE_START(38)
    lda $1, 5($31)
    cmplt $1, 10, $3
    lda $5, 1($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 39: CMPLT with immediate - 10 < 5 -> 0 */
    TEST_CASE_START(39)
    lda $1, 10($31)
    cmplt $1, 5, $3
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * All tests passed
     *-------------------------------------------------------------*/

ALPHA_TEST_END
