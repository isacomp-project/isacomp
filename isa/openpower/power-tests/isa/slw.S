/* OpenPOWER SLW (Shift Left Word) instruction tests */
/* Based on riscv-tests shift patterns */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * Shift left tests - slw rA, rS, rB
     * rA = rS << (rB & 0x3F), with 32-bit result zero-extended
     *-------------------------------------------------------------*/

    /* Shift by 0 */
    TEST_SHIFT_REG_OP( 2, slw, 0x00000001, 0x00000001, 0 )
    TEST_SHIFT_REG_OP( 3, slw, 0xffffffff, 0xffffffff, 0 )
    TEST_SHIFT_REG_OP( 4, slw, 0x21212121, 0x21212121, 0 )

    /* Shift by 1 */
    TEST_SHIFT_REG_OP( 5, slw, 0x00000002, 0x00000001, 1 )
    TEST_SHIFT_REG_OP( 6, slw, 0xfffffffe, 0xffffffff, 1 )
    TEST_SHIFT_REG_OP( 7, slw, 0x42424242, 0x21212121, 1 )

    /* Shift by 7 */
    TEST_SHIFT_REG_OP( 8, slw, 0x00000080, 0x00000001, 7 )
    TEST_SHIFT_REG_OP( 9, slw, 0xffffff80, 0xffffffff, 7 )
    TEST_SHIFT_REG_OP(10, slw, 0x90909080, 0x21212121, 7 )

    /* Shift by 14 */
    TEST_SHIFT_REG_OP(11, slw, 0x00004000, 0x00000001, 14 )
    TEST_SHIFT_REG_OP(12, slw, 0xffffc000, 0xffffffff, 14 )
    TEST_SHIFT_REG_OP(13, slw, 0x48484000, 0x21212121, 14 )

    /* Shift by 31 (maximum for 32-bit) */
    TEST_SHIFT_REG_OP(14, slw, 0x80000000, 0x00000001, 31 )
    TEST_SHIFT_REG_OP(15, slw, 0x80000000, 0xffffffff, 31 )
    TEST_SHIFT_REG_OP(16, slw, 0x80000000, 0x21212121, 31 )

    /* Shift by 32+ (result should be 0 for slw) */
    TEST_SHIFT_REG_OP(17, slw, 0x00000000, 0x00000001, 32 )
    TEST_SHIFT_REG_OP(18, slw, 0x00000000, 0xffffffff, 33 )
    TEST_SHIFT_REG_OP(19, slw, 0x00000000, 0x21212121, 63 )

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

    TEST_RR_SRC1_EQ_DEST(20, slw, 0x00000080, 0x00000001, 7 )
    TEST_RR_SRC2_EQ_DEST(21, slw, 0x00004000, 0x00000001, 14 )
    TEST_RR_SRC12_EQ_DEST(22, slw, 24, 3 )  /* 3 << 3 = 24 */

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

    TEST_RR_DEST_BYPASS(23, 0, slw, 0x00000080, 0x00000001, 7 )
    TEST_RR_DEST_BYPASS(24, 1, slw, 0x00004000, 0x00000001, 14 )
    TEST_RR_DEST_BYPASS(25, 2, slw, 0x80000000, 0x00000001, 31 )

    TEST_RR_SRC12_BYPASS(26, 0, 0, slw, 0x00000080, 0x00000001, 7 )
    TEST_RR_SRC12_BYPASS(27, 0, 1, slw, 0x00004000, 0x00000001, 14 )
    TEST_RR_SRC12_BYPASS(28, 0, 2, slw, 0x80000000, 0x00000001, 31 )
    TEST_RR_SRC12_BYPASS(29, 1, 0, slw, 0x00000080, 0x00000001, 7 )
    TEST_RR_SRC12_BYPASS(30, 1, 1, slw, 0x00004000, 0x00000001, 14 )
    TEST_RR_SRC12_BYPASS(31, 2, 0, slw, 0x80000000, 0x00000001, 31 )

    /*-------------------------------------------------------------
     * Zero source tests
     *-------------------------------------------------------------*/

    TEST_RR_ZEROSRC1(32, slw, 0, 15 )   /* 0 << 15 = 0 */
    TEST_RR_ZEROSRC2(33, slw, 0x00000001, 0x00000001 )  /* x << 0 = x */
    TEST_RR_ZEROSRC12(34, slw, 0 )       /* 0 << 0 = 0 */

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
