/* OpenPOWER SUBF (Subtract From) instruction tests */
/* Note: subf rD, rA, rB computes rD = rB - rA (not rA - rB!) */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Basic tests - subf rD, rA, rB means rD = rB - rA */
    TEST_RR_OP( 2, subf, 0, 0, 0 )
    TEST_RR_OP( 3, subf, 0, 1, 1 )
    TEST_RR_OP( 4, subf, 4, 3, 7 )          /* 7 - 3 = 4 */
    TEST_RR_OP( 5, subf, -4, 7, 3 )         /* 3 - 7 = -4 */
    TEST_RR_OP( 6, subf, 10, 5, 15 )        /* 15 - 5 = 10 */

    /* Boundary tests */
    TEST_RR_OP( 7, subf, 0x7fffffff, 1, 0x80000000 )
    TEST_RR_OP( 8, subf, 0x80000001, 0x7fffffff, 0 )
    TEST_RR_OP( 9, subf, 1, 0xffffffff, 0 )  /* 0 - (-1) = 1 */
    TEST_RR_OP(10, subf, 0xffffffff, 0, 0xffffffff )  /* -1 - 0 = -1 */

    /* Source/Destination tests */
    TEST_RR_SRC1_EQ_DEST(11, subf, 2, 11, 13 )
    TEST_RR_SRC2_EQ_DEST(12, subf, 3, 14, 17 )
    TEST_RR_SRC12_EQ_DEST(13, subf, 0, 13 )

    /* Bypassing tests */
    TEST_RR_DEST_BYPASS(14, 0, subf, 2, 11, 13 )
    TEST_RR_DEST_BYPASS(15, 1, subf, 3, 14, 17 )
    TEST_RR_DEST_BYPASS(16, 2, subf, 4, 15, 19 )

    TEST_RR_SRC12_BYPASS(17, 0, 0, subf, 2, 11, 13 )
    TEST_RR_SRC12_BYPASS(18, 0, 1, subf, 3, 14, 17 )
    TEST_RR_SRC12_BYPASS(19, 1, 0, subf, 2, 11, 13 )

    /* Zero source tests */
    TEST_RR_ZEROSRC1(20, subf, 15, 15 )
    TEST_RR_ZEROSRC2(21, subf, -32, 32 )
    TEST_RR_ZEROSRC12(22, subf, 0 )

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
