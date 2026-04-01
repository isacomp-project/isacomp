/* OpenPOWER SUB (subf) instruction tests */
/* Based on riscv-tests/mips-tests patterns */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * Arithmetic tests - subf rD, rA, rB  (rD = rB - rA)
     * Note: PowerPC subf subtracts rA from rB, not rB from rA!
     *-------------------------------------------------------------*/

    /* Basic tests */
    TEST_RR_OP( 2, subf,  0, 0, 0 )
    TEST_RR_OP( 3, subf,  0, 1, 1 )
    TEST_RR_OP( 4, subf,  4, 3, 7 )        /* 7 - 3 = 4 */
    TEST_RR_OP( 5, subf, -4, 7, 3 )        /* 3 - 7 = -4 */

    /* Sign extension tests */
    TEST_RR_OP( 6, subf, 0x00008000, 0xffff8000, 0 )  /* 0 - (-32768) = 32768 */
    TEST_RR_OP( 7, subf, 0x80000000, 0, 0x80000000 )  /* 0x80000000 - 0 */

    /* Boundary tests */
    TEST_RR_OP( 8, subf, 0x7fffffff, 0, 0x7fffffff )
    TEST_RR_OP( 9, subf, 0xffffffff, 0, 0xffffffff )  /* -1 - 0 = -1 */
    TEST_RR_OP(10, subf, 0, 0xffffffff, 0xffffffff )  /* -1 - (-1) = 0 */
    TEST_RR_OP(11, subf, 1, 0xffffffff, 0 )          /* 0 - (-1) = 1 */
    TEST_RR_OP(12, subf, 0xfffffffe, 1, 0xffffffff ) /* -1 - 1 = -2 */

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

    TEST_RR_SRC1_EQ_DEST(13, subf, 2, 11, 13 )
    TEST_RR_SRC2_EQ_DEST(14, subf, 3, 14, 17 )
    TEST_RR_SRC12_EQ_DEST(15, subf, 0, 13 )  /* x - x = 0 */

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

    TEST_RR_DEST_BYPASS(16, 0, subf, 2, 11, 13 )
    TEST_RR_DEST_BYPASS(17, 1, subf, 3, 14, 17 )
    TEST_RR_DEST_BYPASS(18, 2, subf, 4, 15, 19 )

    TEST_RR_SRC12_BYPASS(19, 0, 0, subf, 2, 11, 13 )
    TEST_RR_SRC12_BYPASS(20, 0, 1, subf, 3, 14, 17 )
    TEST_RR_SRC12_BYPASS(21, 0, 2, subf, 4, 15, 19 )
    TEST_RR_SRC12_BYPASS(22, 1, 0, subf, 2, 11, 13 )
    TEST_RR_SRC12_BYPASS(23, 1, 1, subf, 3, 14, 17 )
    TEST_RR_SRC12_BYPASS(24, 2, 0, subf, 4, 15, 19 )

    TEST_RR_SRC21_BYPASS(25, 0, 0, subf, 2, 11, 13 )
    TEST_RR_SRC21_BYPASS(26, 0, 1, subf, 3, 14, 17 )
    TEST_RR_SRC21_BYPASS(27, 0, 2, subf, 4, 15, 19 )
    TEST_RR_SRC21_BYPASS(28, 1, 0, subf, 2, 11, 13 )
    TEST_RR_SRC21_BYPASS(29, 1, 1, subf, 3, 14, 17 )
    TEST_RR_SRC21_BYPASS(30, 2, 0, subf, 4, 15, 19 )

    /*-------------------------------------------------------------
     * Zero source tests
     *-------------------------------------------------------------*/

    TEST_RR_ZEROSRC1(31, subf, 15, 15 )   /* 15 - 0 = 15 */
    TEST_RR_ZEROSRC2(32, subf, -32, 32 )  /* 0 - 32 = -32 */
    TEST_RR_ZEROSRC12(33, subf, 0 )       /* 0 - 0 = 0 */

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
