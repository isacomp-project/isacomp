/* OpenPOWER EQV (Equivalent/XNOR) instruction tests */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * EQV tests - eqv rA, rS, rB  (rA = ~(rS ^ rB) = rS XNOR rB)
     *-------------------------------------------------------------*/

    /* Basic tests */
    TEST_RR_OP( 2, eqv, 0x0ff00ff0, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_OP( 3, eqv, 0x00ff00ff, 0x0ff00ff0, 0xf0f0f0f0 )
    TEST_RR_OP( 4, eqv, 0xf00ff00f, 0x00ff00ff, 0x0f0f0f0f )
    TEST_RR_OP( 5, eqv, 0xff00ff00, 0xf00ff00f, 0xf0f0f0f0 )

    /* EQV with zero (NOT operation) */
    TEST_RR_OP( 6, eqv, 0xedcba987, 0x12345678, 0x00000000 )
    TEST_RR_OP( 7, eqv, 0xedcba987, 0x00000000, 0x12345678 )

    /* EQV with all ones (identity) */
    TEST_RR_OP( 8, eqv, 0x12345678, 0x12345678, 0xffffffff )

    /* EQV with self (always all ones) */
    TEST_RR_OP( 9, eqv, 0xffffffff, 0xabcdef12, 0xabcdef12 )

    /* EQV(0, 0) = all ones */
    TEST_RR_OP(10, eqv, 0xffffffff, 0x00000000, 0x00000000 )

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

    TEST_RR_SRC1_EQ_DEST(11, eqv, 0x0ff00ff0, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_SRC2_EQ_DEST(12, eqv, 0x0ff00ff0, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_SRC12_EQ_DEST(13, eqv, 0xffffffff, 0xff00ff00 )

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

    TEST_RR_DEST_BYPASS(14, 0, eqv, 0x0ff00ff0, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_DEST_BYPASS(15, 1, eqv, 0x00ff00ff, 0x0ff00ff0, 0xf0f0f0f0 )
    TEST_RR_DEST_BYPASS(16, 2, eqv, 0xf00ff00f, 0x00ff00ff, 0x0f0f0f0f )

    TEST_RR_SRC12_BYPASS(17, 0, 0, eqv, 0x0ff00ff0, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_SRC12_BYPASS(18, 0, 1, eqv, 0x00ff00ff, 0x0ff00ff0, 0xf0f0f0f0 )
    TEST_RR_SRC12_BYPASS(19, 0, 2, eqv, 0xf00ff00f, 0x00ff00ff, 0x0f0f0f0f )

    /*-------------------------------------------------------------
     * Zero source tests
     *-------------------------------------------------------------*/

    TEST_RR_ZEROSRC1(20, eqv, 0xf0f0f0f0, 0x0f0f0f0f )   /* ~(0^x) = ~x */
    TEST_RR_ZEROSRC2(21, eqv, 0x00ff00ff, 0xff00ff00 )   /* ~(x^0) = ~x */
    TEST_RR_ZEROSRC12(22, eqv, 0xffffffff )               /* ~(0^0) = all 1s */

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
