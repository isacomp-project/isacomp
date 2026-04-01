/* OpenPOWER MULLD (Multiply Low Doubleword) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Basic tests */
    TEST_RR_OP( 2, mulld, 0, 0, 0 )
    TEST_RR_OP( 3, mulld, 1, 1, 1 )
    TEST_RR_OP( 4, mulld, 21, 3, 7 )
    TEST_RR_OP( 5, mulld, 143, 11, 13 )

    /* Multiply by zero */
    TEST_RR_OP( 6, mulld, 0, 0, 0x12345678 )
    TEST_RR_OP( 7, mulld, 0, 0x87654321, 0 )

    /* Signed multiplication */
    TEST_RR_OP( 8, mulld, -12, -2, 6 )
    TEST_RR_OP( 9, mulld, -12, 6, -2 )
    TEST_RR_OP(10, mulld, 12, -2, -6 )

    /* Larger values (64-bit) */
test_11:
    li TESTNUM, 11
    lis %r9, 0x1000
    lis %r10, 0x1000
    mulld %r8, %r9, %r10
    /* 0x10000000 * 0x10000000 = 0x0100000000000000 */
    /* To load 0x0100000000000000: lis gives 0x01000000, shift by 32 */
    lis %r25, 0x0100
    sldi %r25, %r25, 32
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Source/Destination tests */
    TEST_RR_SRC1_EQ_DEST(12, mulld, 143, 11, 13 )
    TEST_RR_SRC2_EQ_DEST(13, mulld, 154, 14, 11 )
    TEST_RR_SRC12_EQ_DEST(14, mulld, 169, 13 )

    /* Bypassing tests */
    TEST_RR_DEST_BYPASS(15, 0, mulld, 143, 11, 13 )
    TEST_RR_DEST_BYPASS(16, 1, mulld, 154, 14, 11 )
    TEST_RR_DEST_BYPASS(17, 2, mulld, 165, 15, 11 )

    /* Zero source tests */
    TEST_RR_ZEROSRC1(18, mulld, 0, 31421 )
    TEST_RR_ZEROSRC2(19, mulld, 0, 32341 )
    TEST_RR_ZEROSRC12(20, mulld, 0 )

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
