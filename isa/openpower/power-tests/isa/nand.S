/* OpenPOWER NAND instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * NAND tests - nand rA, rS, rB  (rA = ~(rS & rB))
     *-------------------------------------------------------------*/

    /* Basic tests */
    TEST_RR_OP( 2, nand, 0xf0fff0ff, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_OP( 3, nand, 0xff0fff0f, 0x0ff00ff0, 0xf0f0f0f0 )
    TEST_RR_OP( 4, nand, 0xfff0fff0, 0x00ff00ff, 0x0f0f0f0f )
    TEST_RR_OP( 5, nand, 0x0fff0fff, 0xf00ff00f, 0xf0f0f0f0 )

    /* NAND with zero (always all ones) */
    TEST_RR_OP( 6, nand, 0xffffffff, 0x12345678, 0x00000000 )
    TEST_RR_OP( 7, nand, 0xffffffff, 0x00000000, 0x12345678 )

    /* NAND with all ones (NOT operation) */
    TEST_RR_OP( 8, nand, 0xedcba987, 0x12345678, 0xffffffff )
    TEST_RR_OP( 9, nand, 0x00000000, 0xffffffff, 0xffffffff )

    /* NAND(0, 0) = all ones */
    TEST_RR_OP(10, nand, 0xffffffff, 0x00000000, 0x00000000 )

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

    TEST_RR_SRC1_EQ_DEST(11, nand, 0xf0fff0ff, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_SRC2_EQ_DEST(12, nand, 0xf0fff0ff, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_SRC12_EQ_DEST(13, nand, 0x00ff00ff, 0xff00ff00 )  /* ~x */

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

    TEST_RR_DEST_BYPASS(14, 0, nand, 0xf0fff0ff, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_DEST_BYPASS(15, 1, nand, 0xff0fff0f, 0x0ff00ff0, 0xf0f0f0f0 )
    TEST_RR_DEST_BYPASS(16, 2, nand, 0xfff0fff0, 0x00ff00ff, 0x0f0f0f0f )

    TEST_RR_SRC12_BYPASS(17, 0, 0, nand, 0xf0fff0ff, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_SRC12_BYPASS(18, 0, 1, nand, 0xff0fff0f, 0x0ff00ff0, 0xf0f0f0f0 )
    TEST_RR_SRC12_BYPASS(19, 0, 2, nand, 0xfff0fff0, 0x00ff00ff, 0x0f0f0f0f )

    /*-------------------------------------------------------------
     * Zero source tests
     *-------------------------------------------------------------*/

    TEST_RR_ZEROSRC1(20, nand, 0xffffffff, 0x0f0f0f0f )  /* ~(0&x) = ~0 = all 1s */
    TEST_RR_ZEROSRC2(21, nand, 0xffffffff, 0xff00ff00 )  /* ~(x&0) = all 1s */
    TEST_RR_ZEROSRC12(22, nand, 0xffffffff )              /* ~(0&0) = all 1s */

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
