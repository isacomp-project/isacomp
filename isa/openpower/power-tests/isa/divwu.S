/* OpenPOWER DIVWU (Divide Word Unsigned) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * Unsigned divide tests - divwu rD, rA, rB (rD = rA / rB)
     *-------------------------------------------------------------*/

    /* Basic tests */
    TEST_RR_OP( 2, divwu, 3, 20, 6 )
    TEST_RR_OP( 3, divwu, 100, 1000, 10 )
    TEST_RR_OP( 4, divwu, 0, 5, 10 )

    /* Large unsigned values (treated as unsigned, not negative) */
    TEST_RR_OP( 5, divwu, 0x10000000, 0x80000000, 8 )
    TEST_RR_OP( 6, divwu, 0x0fffffff, 0xffffffff, 0x10 )
    TEST_RR_OP( 7, divwu, 1, 0xffffffff, 0xffffffff )

    /* Division by 1 */
    TEST_RR_OP( 8, divwu, 0x12345678, 0x12345678, 1 )
    TEST_RR_OP( 9, divwu, 0xffffffff, 0xffffffff, 1 )

    /* Division resulting in 0 */
    TEST_RR_OP(10, divwu, 0, 1, 2 )
    TEST_RR_OP(11, divwu, 0, 0x7fffffff, 0x80000000 )

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

    TEST_RR_SRC1_EQ_DEST(12, divwu, 3, 21, 7 )
    TEST_RR_SRC2_EQ_DEST(13, divwu, 2, 22, 11 )
    TEST_RR_SRC12_EQ_DEST(14, divwu, 1, 13 )

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

    TEST_RR_DEST_BYPASS(15, 0, divwu, 3, 21, 7 )
    TEST_RR_DEST_BYPASS(16, 1, divwu, 2, 22, 11 )
    TEST_RR_DEST_BYPASS(17, 2, divwu, 4, 24, 6 )

    TEST_RR_SRC12_BYPASS(18, 0, 0, divwu, 3, 21, 7 )
    TEST_RR_SRC12_BYPASS(19, 0, 1, divwu, 2, 22, 11 )
    TEST_RR_SRC12_BYPASS(20, 0, 2, divwu, 4, 24, 6 )

    /*-------------------------------------------------------------
     * Zero dividend tests
     *-------------------------------------------------------------*/

    TEST_RR_ZEROSRC1(21, divwu, 0, 10 )

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
