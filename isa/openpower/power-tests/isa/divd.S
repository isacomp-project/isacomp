/* OpenPOWER DIVD (Divide Doubleword) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Basic tests */
    TEST_RR_OP( 2, divd, 3, 20, 6 )
    TEST_RR_OP( 3, divd, -3, -20, 6 )
    TEST_RR_OP( 4, divd, -3, 20, -6 )
    TEST_RR_OP( 5, divd, 3, -20, -6 )

    /* Division by 1 */
    TEST_RR_OP( 6, divd, 100, 100, 1 )
    TEST_RR_OP( 7, divd, -100, -100, 1 )

    /* Division resulting in 0 */
    TEST_RR_OP( 8, divd, 0, 5, 10 )
    TEST_RR_OP( 9, divd, 0, -5, 10 )

    /* Larger 64-bit values */
test_10:
    li TESTNUM, 10
    lis %r9, 0x1000
    sldi %r9, %r9, 16        /* 0x100000000000 = 2^44 */
    li %r10, 0x1000          /* 0x1000 = 2^12 */
    divd %r8, %r9, %r10
    /* Expected: 2^44 / 2^12 = 2^32 = 0x100000000 */
    lis %r25, 1
    sldi %r25, %r25, 16      /* Expected: 0x100000000 */
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Source/Destination tests */
    TEST_RR_SRC1_EQ_DEST(11, divd, 3, 21, 7 )
    TEST_RR_SRC2_EQ_DEST(12, divd, 2, 22, 11 )
    TEST_RR_SRC12_EQ_DEST(13, divd, 1, 13 )

    /* Bypassing tests */
    TEST_RR_DEST_BYPASS(14, 0, divd, 3, 21, 7 )
    TEST_RR_DEST_BYPASS(15, 1, divd, 2, 22, 11 )
    TEST_RR_DEST_BYPASS(16, 2, divd, 4, 24, 6 )

    /* Zero dividend */
    TEST_RR_ZEROSRC1(17, divd, 0, 10 )

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
