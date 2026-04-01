/* OpenPOWER DIVW (Divide Word) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * Signed divide tests - divw rD, rA, rB (rD = rA / rB)
     *-------------------------------------------------------------*/

    /* Basic tests */
    TEST_RR_OP( 2, divw, 3, 20, 6 )
    TEST_RR_OP( 3, divw, -3, -20, 6 )
    TEST_RR_OP( 4, divw, -3, 20, -6 )
    TEST_RR_OP( 5, divw, 3, -20, -6 )

    /* Division by 1 */
    TEST_RR_OP( 6, divw, 100, 100, 1 )
    TEST_RR_OP( 7, divw, -100, -100, 1 )

    /* Division resulting in 0 */
    TEST_RR_OP( 8, divw, 0, 5, 10 )
    TEST_RR_OP( 9, divw, 0, -5, 10 )

    /* Larger values */
    TEST_RR_OP(10, divw, 0x1000, 0x10000, 0x10 )
    TEST_RR_OP(11, divw, 0xffff0000, 0xfff00000, 0x10 )  /* -1048576 / 16 = -65536 */

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

    TEST_RR_SRC1_EQ_DEST(12, divw, 3, 21, 7 )
    TEST_RR_SRC2_EQ_DEST(13, divw, 2, 22, 11 )
    TEST_RR_SRC12_EQ_DEST(14, divw, 1, 13 )  /* 13 / 13 = 1 */

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

    TEST_RR_DEST_BYPASS(15, 0, divw, 3, 21, 7 )
    TEST_RR_DEST_BYPASS(16, 1, divw, 2, 22, 11 )
    TEST_RR_DEST_BYPASS(17, 2, divw, 4, 24, 6 )

    TEST_RR_SRC12_BYPASS(18, 0, 0, divw, 3, 21, 7 )
    TEST_RR_SRC12_BYPASS(19, 0, 1, divw, 2, 22, 11 )
    TEST_RR_SRC12_BYPASS(20, 0, 2, divw, 4, 24, 6 )
    TEST_RR_SRC12_BYPASS(21, 1, 0, divw, 3, 21, 7 )
    TEST_RR_SRC12_BYPASS(22, 1, 1, divw, 2, 22, 11 )
    TEST_RR_SRC12_BYPASS(23, 2, 0, divw, 4, 24, 6 )

    /*-------------------------------------------------------------
     * Zero dividend tests
     *-------------------------------------------------------------*/

    TEST_RR_ZEROSRC1(24, divw, 0, 10 )   /* 0 / 10 = 0 */

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
