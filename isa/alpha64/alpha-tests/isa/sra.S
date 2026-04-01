/*
 * Alpha SRA (Shift Right Arithmetic) Test
 * Rc = Ra >> Rb[5:0] (arithmetic shift, sign bit preserved)
 * Comprehensive test suite modeled after riscv-tests
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Positive value tests (sign bit = 0)
     *-------------------------------------------------------------*/

    /* Test 2: 1 >> 0 = 1 */
    TEST_RR_OP(2, sra, 1, 1, 0)

    /* Test 3: 2 >> 1 = 1 */
    TEST_RR_OP(3, sra, 1, 2, 1)

    /* Test 4: 128 >> 7 = 1 */
    TEST_RR_OP(4, sra, 1, 128, 7)

    /* Test 5: 16384 >> 14 = 1 */
    TEST_RR_OP(5, sra, 1, 16384, 14)

    /* Test 6: 0x21212121 >> 0 = 0x21212121 */
    TEST_CASE_START(6)
    lda $1, 0x2121($31)
    ldah $1, 0x2121($1)
    lda $2, 0($31)
    sra $1, $2, $3
    lda $5, 0x2121($31)
    ldah $5, 0x2121($5)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 7: 0x21212121 >> 1 = 0x10909090 */
    TEST_CASE_START(7)
    lda $1, 0x2121($31)
    ldah $1, 0x2121($1)
    lda $2, 1($31)
    sra $1, $2, $3
    lda $5, 0x9090($31)
    ldah $5, 0x1090($5)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Negative value tests (sign bit = 1, should be preserved)
     *-------------------------------------------------------------*/

    /* Test 8: -1 >> 0 = -1 */
    TEST_RR_OP(8, sra, -1, -1, 0)

    /* Test 9: -1 >> 1 = -1 (sign-extended) */
    TEST_RR_OP(9, sra, -1, -1, 1)

    /* Test 10: -1 >> 7 = -1 */
    TEST_RR_OP(10, sra, -1, -1, 7)

    /* Test 11: -1 >> 14 = -1 */
    TEST_RR_OP(11, sra, -1, -1, 14)

    /* Test 12: -1 >> 31 = -1 */
    TEST_RR_OP(12, sra, -1, -1, 31)

    /* Test 13: -2 >> 1 = -1 */
    TEST_RR_OP(13, sra, -1, -2, 1)

    /* Test 14: -4 >> 1 = -2 */
    TEST_RR_OP(14, sra, -2, -4, 1)

    /* Test 15: -8 >> 2 = -2 */
    TEST_RR_OP(15, sra, -2, -8, 2)

    /* Test 16: -16 >> 3 = -2 */
    TEST_RR_OP(16, sra, -2, -16, 3)

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

    /* Test 17: src1 = dest */
    TEST_RR_SRC1_EQ_DEST(17, sra, 1, 128, 7)

    /* Test 18: src2 = dest */
    TEST_RR_SRC2_EQ_DEST(18, sra, 1, 16384, 14)

    /* Test 19: src1 = src2 = dest */
    TEST_RR_SRC12_EQ_DEST(19, sra, 0, 7)

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

    /* Destination bypass tests */
    TEST_RR_DEST_BYPASS(20, 0, sra, 1, 128, 7)
    TEST_RR_DEST_BYPASS(21, 1, sra, 1, 16384, 14)
    TEST_RR_DEST_BYPASS(22, 2, sra, 1, 256, 8)

    /* Source 1->2 bypass tests */
    TEST_RR_SRC12_BYPASS(23, 0, 0, sra, 1, 128, 7)
    TEST_RR_SRC12_BYPASS(24, 0, 1, sra, 1, 16384, 14)
    TEST_RR_SRC12_BYPASS(25, 0, 2, sra, 1, 256, 8)
    TEST_RR_SRC12_BYPASS(26, 1, 0, sra, 1, 128, 7)
    TEST_RR_SRC12_BYPASS(27, 1, 1, sra, 1, 16384, 14)
    TEST_RR_SRC12_BYPASS(28, 2, 0, sra, 1, 256, 8)

    /* Source 2->1 bypass tests */
    TEST_RR_SRC21_BYPASS(29, 0, 0, sra, 1, 128, 7)
    TEST_RR_SRC21_BYPASS(30, 0, 1, sra, 1, 16384, 14)
    TEST_RR_SRC21_BYPASS(31, 0, 2, sra, 1, 256, 8)
    TEST_RR_SRC21_BYPASS(32, 1, 0, sra, 1, 128, 7)
    TEST_RR_SRC21_BYPASS(33, 1, 1, sra, 1, 16384, 14)
    TEST_RR_SRC21_BYPASS(34, 2, 0, sra, 1, 256, 8)

    /*-------------------------------------------------------------
     * Zero register tests
     *-------------------------------------------------------------*/

    /* Test 35: R31 as src1 (0 >> x = 0) */
    TEST_RR_ZEROSRC1(35, sra, 0, 15)

    /* Test 36: R31 as src2 (x >> 0 = x) */
    TEST_RR_ZEROSRC2(36, sra, 32, 32)

    /* Test 37: R31 as both sources (0 >> 0 = 0) */
    TEST_RR_ZEROSRC12(37, sra, 0)

    /* Test 38: R31 as dest (result should be discarded) */
    TEST_RR_ZERODEST(38, sra, 1024, 2048)

    /*-------------------------------------------------------------
     * Immediate operand tests
     *-------------------------------------------------------------*/

    /* Test 39: SRA with immediate - 64 >> 4 = 4 */
    TEST_CASE_START(39)
    lda $1, 64($31)
    sra $1, 4, $3
    lda $5, 4($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 40: SRA with immediate - -16 >> 2 = -4 */
    TEST_CASE_START(40)
    lda $1, -16($31)
    sra $1, 2, $3
    lda $5, -4($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * All tests passed
     *-------------------------------------------------------------*/

ALPHA_TEST_END
