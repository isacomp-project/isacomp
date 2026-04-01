/* OpenPOWER ORC (OR with Complement) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * ORC tests - orc rA, rS, rB  (rA = rS | ~rB)
     *-------------------------------------------------------------*/

    /* Basic tests */
    TEST_RR_OP( 2, orc, 0xfff0fff0, 0xff00ff00, 0x0f0f0f0f )  /* ff00ff00 | ~0f0f0f0f */
    TEST_RR_OP( 3, orc, 0x0fff0fff, 0x0ff00ff0, 0xf0f0f0f0 )
    TEST_RR_OP( 4, orc, 0xf0fff0ff, 0x00ff00ff, 0x0f0f0f0f )
    TEST_RR_OP( 5, orc, 0xff0fff0f, 0xf00ff00f, 0xf0f0f0f0 )

    /* ORC with zero B (result = A | ~0 = all ones) */
    TEST_RR_OP( 6, orc, 0xffffffff, 0x12345678, 0x00000000 )

    /* ORC with all ones B (result = A | 0 = A) */
    TEST_RR_OP( 7, orc, 0x12345678, 0x12345678, 0xffffffff )

    /* ORC with zero A */
    TEST_RR_OP( 8, orc, 0xedcba987, 0x00000000, 0x12345678 )  /* 0 | ~x = ~x */

    /* ORC(x, x) = all ones */
    TEST_RR_OP( 9, orc, 0xffffffff, 0xabcdef12, 0xabcdef12 )  /* x | ~x = all 1s */

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

    TEST_RR_SRC1_EQ_DEST(10, orc, 0xfff0fff0, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_SRC2_EQ_DEST(11, orc, 0xfff0fff0, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_SRC12_EQ_DEST(12, orc, 0xffffffff, 0xff00ff00 )  /* x | ~x = all 1s */

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

    TEST_RR_DEST_BYPASS(13, 0, orc, 0xfff0fff0, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_DEST_BYPASS(14, 1, orc, 0x0fff0fff, 0x0ff00ff0, 0xf0f0f0f0 )
    TEST_RR_DEST_BYPASS(15, 2, orc, 0xf0fff0ff, 0x00ff00ff, 0x0f0f0f0f )

    TEST_RR_SRC12_BYPASS(16, 0, 0, orc, 0xfff0fff0, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_SRC12_BYPASS(17, 0, 1, orc, 0x0fff0fff, 0x0ff00ff0, 0xf0f0f0f0 )
    TEST_RR_SRC12_BYPASS(18, 0, 2, orc, 0xf0fff0ff, 0x00ff00ff, 0x0f0f0f0f )

    /*-------------------------------------------------------------
     * Zero source tests
     *-------------------------------------------------------------*/

    TEST_RR_ZEROSRC1(19, orc, 0xf0f0f0f0, 0x0f0f0f0f )   /* 0 | ~x = ~x */
    TEST_RR_ZEROSRC2(20, orc, 0xffffffff, 0xff00ff00 )   /* x | ~0 = all 1s */
    TEST_RR_ZEROSRC12(21, orc, 0xffffffff )               /* 0 | ~0 = all 1s */

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
