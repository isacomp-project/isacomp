/*
 * Alpha CMPTLT (Compare T_floating Less Than) Test
 * Tests IEEE 754 double-precision less-than comparison
 *
 * Alpha FP comparisons return:
 *   2.0 (0x4000000000000000) if true
 *   0.0 (0x0000000000000000) if false
 */

#include "../../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Less-than tests - should return true (2.0)
     *-------------------------------------------------------------*/

    /* Test 2: 1.0 < 2.0 (true) */
    TEST_FP_CMP_T_TRUE(2, cmptlt, 0x3FF00000, 0x00000000, 0x40000000, 0x00000000)

    /* Test 3: 0.0 < 1.0 (true) */
    TEST_FP_CMP_T_TRUE(3, cmptlt, 0x00000000, 0x00000000, 0x3FF00000, 0x00000000)

    /* Test 4: -1.0 < 0.0 (true) */
    TEST_FP_CMP_T_TRUE(4, cmptlt, 0xBFF00000, 0x00000000, 0x00000000, 0x00000000)

    /* Test 5: -2.0 < -1.0 (true) */
    TEST_FP_CMP_T_TRUE(5, cmptlt, 0xC0000000, 0x00000000, 0xBFF00000, 0x00000000)

    /* Test 6: -1.0 < 1.0 (true) */
    TEST_FP_CMP_T_TRUE(6, cmptlt, 0xBFF00000, 0x00000000, 0x3FF00000, 0x00000000)

    /* Test 7: 0.5 < 1.0 (true) */
    TEST_FP_CMP_T_TRUE(7, cmptlt, 0x3FE00000, 0x00000000, 0x3FF00000, 0x00000000)

    /*-------------------------------------------------------------
     * Not less-than tests - should return false (0.0)
     *-------------------------------------------------------------*/

    /* Test 8: 2.0 < 1.0 (false) */
    TEST_FP_CMP_T_FALSE(8, cmptlt, 0x40000000, 0x00000000, 0x3FF00000, 0x00000000)

    /* Test 9: 1.0 < 1.0 (false - equal) */
    TEST_FP_CMP_T_FALSE(9, cmptlt, 0x3FF00000, 0x00000000, 0x3FF00000, 0x00000000)

    /* Test 10: 1.0 < 0.0 (false) */
    TEST_FP_CMP_T_FALSE(10, cmptlt, 0x3FF00000, 0x00000000, 0x00000000, 0x00000000)

    /* Test 11: 0.0 < -1.0 (false) */
    TEST_FP_CMP_T_FALSE(11, cmptlt, 0x00000000, 0x00000000, 0xBFF00000, 0x00000000)

    /* Test 12: -1.0 < -2.0 (false) */
    TEST_FP_CMP_T_FALSE(12, cmptlt, 0xBFF00000, 0x00000000, 0xC0000000, 0x00000000)

    /* Test 13: 0.0 < 0.0 (false - equal) */
    TEST_FP_CMP_T_FALSE(13, cmptlt, 0x00000000, 0x00000000, 0x00000000, 0x00000000)

ALPHA_TEST_END
