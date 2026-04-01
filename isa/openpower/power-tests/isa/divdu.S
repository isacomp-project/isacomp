/* OpenPOWER DIVDU (Divide Doubleword Unsigned) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /* Basic tests */
    TEST_RR_OP( 2, divdu, 3, 20, 6 )
    TEST_RR_OP( 3, divdu, 100, 1000, 10 )
    TEST_RR_OP( 4, divdu, 0, 5, 10 )

    /* Large unsigned values */
test_5:
    li TESTNUM, 5
    li %r9, -1              /* 0xffffffffffffffff */
    li %r10, 2
    divdu %r8, %r9, %r10
    li %r25, -1
    srdi %r25, %r25, 1      /* 0x7fffffffffffffff */
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

test_6:
    li TESTNUM, 6
    li %r9, -1              /* 0xffffffffffffffff */
    li %r9, -1
    divdu %r8, %r9, %r9     /* x / x = 1 */
    li %r25, 1
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Division by 1 */
test_7:
    li TESTNUM, 7
    LOAD_IMM(%r9, 0x12345678)
    li %r10, 1
    divdu %r8, %r9, %r10
    LOAD_IMM(%r25, 0x12345678)
    cmpd %cr0, %r8, %r25
    bne %cr0, fail

    /* Division resulting in 0 */
    TEST_RR_OP( 8, divdu, 0, 1, 2 )

    /* Source/Destination tests */
    TEST_RR_SRC1_EQ_DEST( 9, divdu, 3, 21, 7 )
    TEST_RR_SRC2_EQ_DEST(10, divdu, 2, 22, 11 )
    TEST_RR_SRC12_EQ_DEST(11, divdu, 1, 13 )

    /* Bypassing tests */
    TEST_RR_DEST_BYPASS(12, 0, divdu, 3, 21, 7 )
    TEST_RR_DEST_BYPASS(13, 1, divdu, 2, 22, 11 )
    TEST_RR_DEST_BYPASS(14, 2, divdu, 4, 24, 6 )

    /* Zero dividend */
    TEST_RR_ZEROSRC1(15, divdu, 0, 10 )

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
