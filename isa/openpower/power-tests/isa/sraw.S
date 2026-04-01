/* OpenPOWER SRAW (Shift Right Algebraic Word) instruction tests */
/* Based on riscv-tests arithmetic shift patterns */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * Shift right arithmetic tests - sraw rA, rS, rB
     * rA = rS >> (rB & 0x3F), arithmetic (sign extend)
     *-------------------------------------------------------------*/

    /* Shift by 0 - negative number */
    TEST_SHIFT_REG_OP( 2, sraw, 0xffffffff80000000, 0x80000000, 0 )
    TEST_SHIFT_REG_OP( 3, sraw, 0xffffffffffffffff, 0xffffffff, 0 )

    /* Shift by 0 - positive number */
    TEST_SHIFT_REG_OP( 4, sraw, 0x000000007fffffff, 0x7fffffff, 0 )
    TEST_SHIFT_REG_OP( 5, sraw, 0x0000000021212121, 0x21212121, 0 )

    /* Shift by 1 - negative */
    TEST_SHIFT_REG_OP( 6, sraw, 0xffffffffc0000000, 0x80000000, 1 )
    TEST_SHIFT_REG_OP( 7, sraw, 0xffffffffffffffff, 0xffffffff, 1 )

    /* Shift by 1 - positive */
    TEST_SHIFT_REG_OP( 8, sraw, 0x000000003fffffff, 0x7fffffff, 1 )
    TEST_SHIFT_REG_OP( 9, sraw, 0x0000000010909090, 0x21212121, 1 )

    /* Shift by 7 - negative */
    TEST_SHIFT_REG_OP(10, sraw, 0xffffffffff000000, 0x80000000, 7 )
    TEST_SHIFT_REG_OP(11, sraw, 0xffffffffffffffff, 0xffffffff, 7 )

    /* Shift by 7 - positive */
    TEST_SHIFT_REG_OP(12, sraw, 0x0000000000ffffff, 0x7fffffff, 7 )
    TEST_SHIFT_REG_OP(13, sraw, 0x0000000000424242, 0x21212121, 7 )

    /* Shift by 14 - negative */
    TEST_SHIFT_REG_OP(14, sraw, 0xfffffffffffe0000, 0x80000000, 14 )
    TEST_SHIFT_REG_OP(15, sraw, 0xffffffffffffffff, 0xffffffff, 14 )

    /* Shift by 14 - positive */
    TEST_SHIFT_REG_OP(16, sraw, 0x000000000001ffff, 0x7fffffff, 14 )
    TEST_SHIFT_REG_OP(17, sraw, 0x0000000000008484, 0x21212121, 14 )

    /* Shift by 31 - negative (all sign bits) */
    TEST_SHIFT_REG_OP(18, sraw, 0xffffffffffffffff, 0x80000000, 31 )
    TEST_SHIFT_REG_OP(19, sraw, 0xffffffffffffffff, 0xffffffff, 31 )

    /* Shift by 31 - positive */
    TEST_SHIFT_REG_OP(20, sraw, 0x0000000000000000, 0x7fffffff, 31 )
    TEST_SHIFT_REG_OP(21, sraw, 0x0000000000000000, 0x21212121, 31 )

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

    TEST_RR_SRC1_EQ_DEST(22, sraw, 0xffffffffff000000, 0x80000000, 7 )
    TEST_RR_SRC2_EQ_DEST(23, sraw, 0xfffffffffffe0000, 0x80000000, 14 )
    TEST_RR_SRC12_EQ_DEST(24, sraw, 0, 7 )  /* 7 >> 7 = 0 */

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

    TEST_RR_DEST_BYPASS(25, 0, sraw, 0xffffffffff000000, 0x80000000, 7 )
    TEST_RR_DEST_BYPASS(26, 1, sraw, 0xfffffffffffe0000, 0x80000000, 14 )
    TEST_RR_DEST_BYPASS(27, 2, sraw, 0xffffffffffffffff, 0x80000000, 31 )

    TEST_RR_SRC12_BYPASS(28, 0, 0, sraw, 0xffffffffff000000, 0x80000000, 7 )
    TEST_RR_SRC12_BYPASS(29, 0, 1, sraw, 0xfffffffffffe0000, 0x80000000, 14 )
    TEST_RR_SRC12_BYPASS(30, 0, 2, sraw, 0xffffffffffffffff, 0x80000000, 31 )

    /*-------------------------------------------------------------
     * Zero source tests
     *-------------------------------------------------------------*/

    TEST_RR_ZEROSRC1(31, sraw, 0, 15 )   /* 0 >> 15 = 0 */
    TEST_RR_ZEROSRC2(32, sraw, 0xffffffff80000000, 0x80000000 )  /* x >> 0 (sign-ext) */
    TEST_RR_ZEROSRC12(33, sraw, 0 )       /* 0 >> 0 = 0 */

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
