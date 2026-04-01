/* OpenPOWER MULLW (Multiply Low Word) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * Multiply tests - mullw rD, rA, rB (rD = (rA * rB)[32:63])
     *-------------------------------------------------------------*/

    /* Basic tests */
    TEST_RR_OP( 2, mullw, 0, 0, 0 )
    TEST_RR_OP( 3, mullw, 1, 1, 1 )
    TEST_RR_OP( 4, mullw, 21, 3, 7 )
    TEST_RR_OP( 5, mullw, 0, 0, 0xffff8000 )
    TEST_RR_OP( 6, mullw, 0, 0x80000000, 0 )

    /* Signed multiplication */
    TEST_RR_OP( 7, mullw, 0xfffffff4, -2, 6 )       /* -2 * 6 = -12 */
    TEST_RR_OP( 8, mullw, 0xfffffff4, 6, -2 )       /* 6 * -2 = -12 */
    TEST_RR_OP( 9, mullw, 12, -2, -6 )              /* -2 * -6 = 12 */

    /* Larger values */
    TEST_RR_OP(10, mullw, 0x00005b04, 0x00001234, 0x00000005 )  /* 0x1234 * 5 = 0x5b04 */
    TEST_RR_OP(11, mullw, 0x00ff0000, 0x0000ff00, 0x00000100 )  /* 0xff00 * 0x100 */
    TEST_RR_OP(12, mullw, 0xff000000, 0x0000ff00, 0x00010000 )  /* 0xff00 * 0x10000, low 32 bits */

    /* Test overflow (lower 32 bits only) */
    TEST_RR_OP(13, mullw, 0x00000001, 0xffffffff, 0xffffffff )  /* -1 * -1 = 1 */

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

    TEST_RR_SRC1_EQ_DEST(14, mullw, 143, 11, 13 )
    TEST_RR_SRC2_EQ_DEST(15, mullw, 154, 14, 11 )
    TEST_RR_SRC12_EQ_DEST(16, mullw, 169, 13 )  /* 13 * 13 = 169 */

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

    TEST_RR_DEST_BYPASS(17, 0, mullw, 143, 11, 13 )
    TEST_RR_DEST_BYPASS(18, 1, mullw, 154, 14, 11 )
    TEST_RR_DEST_BYPASS(19, 2, mullw, 165, 15, 11 )

    TEST_RR_SRC12_BYPASS(20, 0, 0, mullw, 143, 11, 13 )
    TEST_RR_SRC12_BYPASS(21, 0, 1, mullw, 154, 14, 11 )
    TEST_RR_SRC12_BYPASS(22, 0, 2, mullw, 165, 15, 11 )
    TEST_RR_SRC12_BYPASS(23, 1, 0, mullw, 143, 11, 13 )
    TEST_RR_SRC12_BYPASS(24, 1, 1, mullw, 154, 14, 11 )
    TEST_RR_SRC12_BYPASS(25, 2, 0, mullw, 165, 15, 11 )

    /*-------------------------------------------------------------
     * Zero source tests
     *-------------------------------------------------------------*/

    TEST_RR_ZEROSRC1(26, mullw, 0, 31421 )
    TEST_RR_ZEROSRC2(27, mullw, 0, 32341 )
    TEST_RR_ZEROSRC12(28, mullw, 0 )

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
