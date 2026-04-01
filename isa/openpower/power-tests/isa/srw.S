/* OpenPOWER SRW (Shift Right Word) instruction tests */
/* Based on riscv-tests shift patterns */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * Shift right logical tests - srw rA, rS, rB
     * rA = rS >> (rB & 0x3F), logical (zero fill)
     *-------------------------------------------------------------*/

    /* Shift by 0 */
    TEST_SHIFT_REG_OP( 2, srw, 0x80000000, 0x80000000, 0 )
    TEST_SHIFT_REG_OP( 3, srw, 0xffffffff, 0xffffffff, 0 )
    TEST_SHIFT_REG_OP( 4, srw, 0x21212121, 0x21212121, 0 )

    /* Shift by 1 */
    TEST_SHIFT_REG_OP( 5, srw, 0x40000000, 0x80000000, 1 )
    TEST_SHIFT_REG_OP( 6, srw, 0x7fffffff, 0xffffffff, 1 )
    TEST_SHIFT_REG_OP( 7, srw, 0x10909090, 0x21212121, 1 )

    /* Shift by 7 */
    TEST_SHIFT_REG_OP( 8, srw, 0x01000000, 0x80000000, 7 )
    TEST_SHIFT_REG_OP( 9, srw, 0x01ffffff, 0xffffffff, 7 )
    TEST_SHIFT_REG_OP(10, srw, 0x00424242, 0x21212121, 7 )

    /* Shift by 14 */
    TEST_SHIFT_REG_OP(11, srw, 0x00020000, 0x80000000, 14 )
    TEST_SHIFT_REG_OP(12, srw, 0x0003ffff, 0xffffffff, 14 )
    TEST_SHIFT_REG_OP(13, srw, 0x00008484, 0x21212121, 14 )

    /* Shift by 31 (maximum for 32-bit) */
    TEST_SHIFT_REG_OP(14, srw, 0x00000001, 0x80000000, 31 )
    TEST_SHIFT_REG_OP(15, srw, 0x00000001, 0xffffffff, 31 )
    TEST_SHIFT_REG_OP(16, srw, 0x00000000, 0x21212121, 31 )

    /* Shift by 32+ (result should be 0 for srw) */
    TEST_SHIFT_REG_OP(17, srw, 0x00000000, 0x80000000, 32 )
    TEST_SHIFT_REG_OP(18, srw, 0x00000000, 0xffffffff, 33 )
    TEST_SHIFT_REG_OP(19, srw, 0x00000000, 0x21212121, 63 )

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

    TEST_RR_SRC1_EQ_DEST(20, srw, 0x01000000, 0x80000000, 7 )
    TEST_RR_SRC2_EQ_DEST(21, srw, 0x00020000, 0x80000000, 14 )
    TEST_RR_SRC12_EQ_DEST(22, srw, 0, 7 )  /* 7 >> 7 = 0 */

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

    TEST_RR_DEST_BYPASS(23, 0, srw, 0x01000000, 0x80000000, 7 )
    TEST_RR_DEST_BYPASS(24, 1, srw, 0x00020000, 0x80000000, 14 )
    TEST_RR_DEST_BYPASS(25, 2, srw, 0x00000001, 0x80000000, 31 )

    TEST_RR_SRC12_BYPASS(26, 0, 0, srw, 0x01000000, 0x80000000, 7 )
    TEST_RR_SRC12_BYPASS(27, 0, 1, srw, 0x00020000, 0x80000000, 14 )
    TEST_RR_SRC12_BYPASS(28, 0, 2, srw, 0x00000001, 0x80000000, 31 )
    TEST_RR_SRC12_BYPASS(29, 1, 0, srw, 0x01000000, 0x80000000, 7 )
    TEST_RR_SRC12_BYPASS(30, 1, 1, srw, 0x00020000, 0x80000000, 14 )
    TEST_RR_SRC12_BYPASS(31, 2, 0, srw, 0x00000001, 0x80000000, 31 )

    /*-------------------------------------------------------------
     * Zero source tests
     *-------------------------------------------------------------*/

    TEST_RR_ZEROSRC1(32, srw, 0, 15 )   /* 0 >> 15 = 0 */
    TEST_RR_ZEROSRC2(33, srw, 0x80000000, 0x80000000 )  /* x >> 0 = x */
    TEST_RR_ZEROSRC12(34, srw, 0 )       /* 0 >> 0 = 0 */

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
