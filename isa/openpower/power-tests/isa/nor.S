/* OpenPOWER NOR instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * NOR tests - nor rA, rS, rB  (rA = ~(rS | rB))
     *-------------------------------------------------------------*/

    /* Basic tests */
    TEST_RR_OP( 2, nor, 0x00f000f0, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_OP( 3, nor, 0x000f000f, 0x0ff00ff0, 0xf0f0f0f0 )
    TEST_RR_OP( 4, nor, 0xf000f000, 0x00ff00ff, 0x0f0f0f0f )
    TEST_RR_OP( 5, nor, 0x0f000f00, 0xf00ff00f, 0xf0f0f0f0 )

    /* NOR with zero (NOT operation) */
    TEST_RR_OP( 6, nor, 0xedcba987, 0x12345678, 0x00000000 )
    TEST_RR_OP( 7, nor, 0xedcba987, 0x00000000, 0x12345678 )

    /* NOR with all ones */
    TEST_RR_OP( 8, nor, 0x00000000, 0x12345678, 0xffffffff )
    TEST_RR_OP( 9, nor, 0x00000000, 0xffffffff, 0xffffffff )

    /* NOR(0, 0) = all ones */
    TEST_RR_OP(10, nor, 0xffffffff, 0x00000000, 0x00000000 )

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

    TEST_RR_SRC1_EQ_DEST(11, nor, 0x00f000f0, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_SRC2_EQ_DEST(12, nor, 0x00f000f0, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_SRC12_EQ_DEST(13, nor, 0x00ff00ff, 0xff00ff00 )  /* ~x */

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

    TEST_RR_DEST_BYPASS(14, 0, nor, 0x00f000f0, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_DEST_BYPASS(15, 1, nor, 0x000f000f, 0x0ff00ff0, 0xf0f0f0f0 )
    TEST_RR_DEST_BYPASS(16, 2, nor, 0xf000f000, 0x00ff00ff, 0x0f0f0f0f )

    TEST_RR_SRC12_BYPASS(17, 0, 0, nor, 0x00f000f0, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_SRC12_BYPASS(18, 0, 1, nor, 0x000f000f, 0x0ff00ff0, 0xf0f0f0f0 )
    TEST_RR_SRC12_BYPASS(19, 0, 2, nor, 0xf000f000, 0x00ff00ff, 0x0f0f0f0f )
    TEST_RR_SRC12_BYPASS(20, 1, 0, nor, 0x00f000f0, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_SRC12_BYPASS(21, 1, 1, nor, 0x000f000f, 0x0ff00ff0, 0xf0f0f0f0 )
    TEST_RR_SRC12_BYPASS(22, 2, 0, nor, 0xf000f000, 0x00ff00ff, 0x0f0f0f0f )

    /*-------------------------------------------------------------
     * Zero source tests
     *-------------------------------------------------------------*/

    TEST_RR_ZEROSRC1(23, nor, 0xf0f0f0f0, 0x0f0f0f0f )  /* ~(0|x) = ~x */
    TEST_RR_ZEROSRC2(24, nor, 0x00ff00ff, 0xff00ff00 )  /* ~(x|0) = ~x */
    TEST_RR_ZEROSRC12(25, nor, 0xffffffff )              /* ~(0|0) = all 1s */

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
