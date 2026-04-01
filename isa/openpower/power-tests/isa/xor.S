/* OpenPOWER XOR instruction tests */
/* Based on riscv-tests/mips-tests patterns */

#include "test_macros.h"

RVTEST_CODE_BEGIN

    /*-------------------------------------------------------------
     * Logical tests - xor rA, rS, rB
     *-------------------------------------------------------------*/

    /* Basic tests */
    TEST_RR_OP( 2, xor, 0xf00ff00f, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_OP( 3, xor, 0xff00ff00, 0x0ff00ff0, 0xf0f0f0f0 )
    TEST_RR_OP( 4, xor, 0x0ff00ff0, 0x00ff00ff, 0x0f0f0f0f )
    TEST_RR_OP( 5, xor, 0x00ff00ff, 0xf00ff00f, 0xf0f0f0f0 )

    /* XOR with zero */
    TEST_RR_OP( 6, xor, 0x12345678, 0x12345678, 0x00000000 )
    TEST_RR_OP( 7, xor, 0x12345678, 0x00000000, 0x12345678 )

    /* XOR with all ones (NOT operation) */
    TEST_RR_OP( 8, xor, 0xedcba987, 0x12345678, 0xffffffff )

    /* XOR with self (always zero) */
    TEST_RR_OP( 9, xor, 0x00000000, 0xabcdef12, 0xabcdef12 )

    /*-------------------------------------------------------------
     * Source/Destination tests
     *-------------------------------------------------------------*/

    TEST_RR_SRC1_EQ_DEST(10, xor, 0xf00ff00f, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_SRC2_EQ_DEST(11, xor, 0xf00ff00f, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_SRC12_EQ_DEST(12, xor, 0, 0xff00ff00 )  /* x XOR x = 0 */

    /*-------------------------------------------------------------
     * Bypassing tests
     *-------------------------------------------------------------*/

    TEST_RR_DEST_BYPASS(13, 0, xor, 0xf00ff00f, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_DEST_BYPASS(14, 1, xor, 0xff00ff00, 0x0ff00ff0, 0xf0f0f0f0 )
    TEST_RR_DEST_BYPASS(15, 2, xor, 0x0ff00ff0, 0x00ff00ff, 0x0f0f0f0f )

    TEST_RR_SRC12_BYPASS(16, 0, 0, xor, 0xf00ff00f, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_SRC12_BYPASS(17, 0, 1, xor, 0xff00ff00, 0x0ff00ff0, 0xf0f0f0f0 )
    TEST_RR_SRC12_BYPASS(18, 0, 2, xor, 0x0ff00ff0, 0x00ff00ff, 0x0f0f0f0f )
    TEST_RR_SRC12_BYPASS(19, 1, 0, xor, 0xf00ff00f, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_SRC12_BYPASS(20, 1, 1, xor, 0xff00ff00, 0x0ff00ff0, 0xf0f0f0f0 )
    TEST_RR_SRC12_BYPASS(21, 2, 0, xor, 0x0ff00ff0, 0x00ff00ff, 0x0f0f0f0f )

    TEST_RR_SRC21_BYPASS(22, 0, 0, xor, 0xf00ff00f, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_SRC21_BYPASS(23, 0, 1, xor, 0xff00ff00, 0x0ff00ff0, 0xf0f0f0f0 )
    TEST_RR_SRC21_BYPASS(24, 0, 2, xor, 0x0ff00ff0, 0x00ff00ff, 0x0f0f0f0f )
    TEST_RR_SRC21_BYPASS(25, 1, 0, xor, 0xf00ff00f, 0xff00ff00, 0x0f0f0f0f )
    TEST_RR_SRC21_BYPASS(26, 1, 1, xor, 0xff00ff00, 0x0ff00ff0, 0xf0f0f0f0 )
    TEST_RR_SRC21_BYPASS(27, 2, 0, xor, 0x0ff00ff0, 0x00ff00ff, 0x0f0f0f0f )

    /*-------------------------------------------------------------
     * Zero source tests
     *-------------------------------------------------------------*/

    TEST_RR_ZEROSRC1(28, xor, 0x0f0f0f0f, 0x0f0f0f0f )  /* 0 XOR x = x */
    TEST_RR_ZEROSRC2(29, xor, 0xff00ff00, 0xff00ff00 )  /* x XOR 0 = x */
    TEST_RR_ZEROSRC12(30, xor, 0 )                       /* 0 XOR 0 = 0 */

    TEST_PASSFAIL

RVTEST_PASS
RVTEST_FAIL

RVTEST_DATA_BEGIN
RVTEST_DATA_END
