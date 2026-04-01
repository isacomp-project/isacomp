/* OpenPOWER ANDC (AND with Complement) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * ANDC tests - andc rA, rS, rB  (rA = rS & ~rB)
     *-------------------------------------------------------------*/

    /* Basic tests */
    TEST_RR_OP( 2, andc, 0xf000f000, 0xff00ff00, 0x0f0f0f0f )  /* ff00ff00 & ~0f0f0f0f */
    TEST_RR_OP( 3, andc, 0x0f000f00, 0x0ff00ff0, 0xf0f0f0f0 )
    TEST_RR_OP( 4, andc, 0x00f000f0, 0x00ff00ff, 0x0f0f0f0f )
    TEST_RR_OP( 5, andc, 0x000f000f, 0xf00ff00f, 0xf0f0f0f0 )

    /* ANDC with zero B (result = A & ~0 = A) */
    TEST_RR_OP( 6, andc, 0x12345678, 0x12345678, 0x00000000 )

    /* ANDC with all ones B (result = A & 0 = 0) */
    TEST_RR_OP( 7, andc, 0x00000000, 0x12345678, 0xffffffff )

    /* ANDC with zero A */
    TEST_RR_OP( 8, andc, 0x00000000, 0x00000000, 0x12345678 )

    /* ANDC(x, x) = 0 */
    TEST_RR_OP( 9, andc, 0x00000000, 0xabcdef12, 0xabcdef12 )

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

    TEST_RR_SRC1_EQ_DEST(10, andc, 0xf000f000, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_SRC2_EQ_DEST(11, andc, 0xf000f000, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_SRC12_EQ_DEST(12, andc, 0, 0xff00ff00 )  /* x & ~x = 0 */

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

    TEST_RR_DEST_BYPASS(13, 0, andc, 0xf000f000, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_DEST_BYPASS(14, 1, andc, 0x0f000f00, 0x0ff00ff0, 0xf0f0f0f0 )
    TEST_RR_DEST_BYPASS(15, 2, andc, 0x00f000f0, 0x00ff00ff, 0x0f0f0f0f )

    TEST_RR_SRC12_BYPASS(16, 0, 0, andc, 0xf000f000, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_SRC12_BYPASS(17, 0, 1, andc, 0x0f000f00, 0x0ff00ff0, 0xf0f0f0f0 )
    TEST_RR_SRC12_BYPASS(18, 0, 2, andc, 0x00f000f0, 0x00ff00ff, 0x0f0f0f0f )

    /*-------------------------------------------------------------
     * Zero source tests
     *-------------------------------------------------------------*/

    TEST_RR_ZEROSRC1(19, andc, 0, 0x0f0f0f0f )   /* 0 & ~x = 0 */
    TEST_RR_ZEROSRC2(20, andc, 0xff00ff00, 0xff00ff00 )  /* x & ~0 = x */
    TEST_RR_ZEROSRC12(21, andc, 0 )               /* 0 & ~0 = 0 */

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
