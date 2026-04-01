/*
 * Alpha SRL (Shift Right Logical) Test
 * Tests logical right shift: Rc = Ra >> (Rb & 63) (zero-fill)
 * Comprehensive test suite modeled after riscv-tests
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Arithmetic tests (positive values)
     *-------------------------------------------------------------*/

    /* Test 2: 1 >> 0 = 1 */
    TEST_RR_OP(2, srl, 1, 1, 0)

    /* Test 3: 2 >> 1 = 1 */
    TEST_RR_OP(3, srl, 1, 2, 1)

    /* Test 4: 128 >> 7 = 1 */
    TEST_RR_OP(4, srl, 1, 128, 7)

    /* Test 5: 16384 >> 14 = 1 */
    TEST_RR_OP(5, srl, 1, 16384, 14)

    /* Test 6: 32768 >> 15 = 1 */
    TEST_RR_OP(6, srl, 1, 32768, 15)

    /*-------------------------------------------------------------
     * Verify zero-fill (not sign-extend) for negative values
     *-------------------------------------------------------------*/

    /* Test 7: -1 >> 0 = -1 */
    TEST_RR_OP(7, srl, -1, -1, 0)

    /* Test 8: -1 >> 1 should give large positive (zero-fill) */
    TEST_CASE_START(8)
    lda $1, -1($31)
    lda $2, 1($31)
    srl $1, $2, $3
    /* Result should be 0x7FFFFFFFFFFFFFFF - check it's positive */
    cmplt $3, $31, $6    /* Should NOT be negative */
    bne $6, fail

    /* Test 9: 0x550 >> 4 = 0x55 */
    TEST_RR_OP(9, srl, 0x55, 0x550, 4)

    /* Test 10: 96 >> 5 = 3 */
    TEST_RR_OP(10, srl, 3, 96, 5)

    /*-------------------------------------------------------------
     * Verify that shifts only use bottom 6 bits
     *-------------------------------------------------------------*/

    /* Test 11: Shift amount > 63 should wrap (64 = 0) */
    TEST_CASE_START(11)
    lda $1, 1($31)
    lda $2, 64($31)
    srl $1, $2, $3
    lda $5, 1($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

    /* Test 12: src1 = dest */
    TEST_RR_SRC1_EQ_DEST(12, srl, 1, 128, 7)

    /* Test 13: src2 = dest */
    TEST_RR_SRC2_EQ_DEST(13, srl, 1, 16384, 14)

    /* Test 14: src1 = src2 = dest */
    TEST_RR_SRC12_EQ_DEST(14, srl, 0, 7)

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

    /* Destination bypass tests */
    TEST_RR_DEST_BYPASS(15, 0, srl, 1, 128, 7)
    TEST_RR_DEST_BYPASS(16, 1, srl, 1, 16384, 14)
    TEST_RR_DEST_BYPASS(17, 2, srl, 1, 256, 8)

    /* Source 1->2 bypass tests */
    TEST_RR_SRC12_BYPASS(18, 0, 0, srl, 1, 128, 7)
    TEST_RR_SRC12_BYPASS(19, 0, 1, srl, 1, 16384, 14)
    TEST_RR_SRC12_BYPASS(20, 0, 2, srl, 1, 256, 8)
    TEST_RR_SRC12_BYPASS(21, 1, 0, srl, 1, 128, 7)
    TEST_RR_SRC12_BYPASS(22, 1, 1, srl, 1, 16384, 14)
    TEST_RR_SRC12_BYPASS(23, 2, 0, srl, 1, 256, 8)

    /* Source 2->1 bypass tests */
    TEST_RR_SRC21_BYPASS(24, 0, 0, srl, 1, 128, 7)
    TEST_RR_SRC21_BYPASS(25, 0, 1, srl, 1, 16384, 14)
    TEST_RR_SRC21_BYPASS(26, 0, 2, srl, 1, 256, 8)
    TEST_RR_SRC21_BYPASS(27, 1, 0, srl, 1, 128, 7)
    TEST_RR_SRC21_BYPASS(28, 1, 1, srl, 1, 16384, 14)
    TEST_RR_SRC21_BYPASS(29, 2, 0, srl, 1, 256, 8)

    /*-------------------------------------------------------------
     * Zero register tests
     *-------------------------------------------------------------*/

    /* Test 30: R31 as src1 (0 >> x = 0) */
    TEST_RR_ZEROSRC1(30, srl, 0, 15)

    /* Test 31: R31 as src2 (x >> 0 = x) */
    TEST_RR_ZEROSRC2(31, srl, 32, 32)

    /* Test 32: R31 as both sources (0 >> 0 = 0) */
    TEST_RR_ZEROSRC12(32, srl, 0)

    /* Test 33: R31 as dest (result should be discarded) */
    TEST_RR_ZERODEST(33, srl, 1024, 10)

    /*-------------------------------------------------------------
     * Immediate operand tests
     *-------------------------------------------------------------*/

    /* Test 34: SRL with immediate - 8 >> 3 = 1 */
    TEST_CASE_START(34)
    lda $1, 8($31)
    srl $1, 3, $3
    lda $5, 1($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 35: SRL with immediate - 0xA0 >> 4 = 0xA */
    TEST_CASE_START(35)
    lda $1, 0xA0($31)
    srl $1, 4, $3
    lda $5, 0xA($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * All tests passed
     *-------------------------------------------------------------*/

ALPHA_TEST_END
