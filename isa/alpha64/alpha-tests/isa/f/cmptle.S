/*
 * Alpha CMPTLE (Compare T_floating Less Than or Equal) Test
 * Tests IEEE 754 double-precision less-than-or-equal comparison
 *
 * Alpha FP comparisons return:
 *   2.0 (0x4000000000000000) if true
 *   0.0 (0x0000000000000000) if false
 */

#include "../../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Less-than-or-equal tests - should return true (2.0)
     *-------------------------------------------------------------*/

    /* Test 2: 1.0 <= 2.0 (true) */
    TEST_FP_CMP_T_TRUE(2, cmptle, 0x3FF00000, 0x00000000, 0x40000000, 0x00000000)

    /* Test 3: 1.0 <= 1.0 (true - equal) */
    TEST_FP_CMP_T_TRUE(3, cmptle, 0x3FF00000, 0x00000000, 0x3FF00000, 0x00000000)

    /* Test 4: 0.0 <= 1.0 (true) */
    TEST_FP_CMP_T_TRUE(4, cmptle, 0x00000000, 0x00000000, 0x3FF00000, 0x00000000)

    /* Test 5: 0.0 <= 0.0 (true - equal) */
    TEST_FP_CMP_T_TRUE(5, cmptle, 0x00000000, 0x00000000, 0x00000000, 0x00000000)

    /* Test 6: -1.0 <= 0.0 (true) */
    TEST_FP_CMP_T_TRUE(6, cmptle, 0xBFF00000, 0x00000000, 0x00000000, 0x00000000)

    /* Test 7: -1.0 <= -1.0 (true - equal) */
    TEST_FP_CMP_T_TRUE(7, cmptle, 0xBFF00000, 0x00000000, 0xBFF00000, 0x00000000)

    /* Test 8: -2.0 <= -1.0 (true) */
    TEST_FP_CMP_T_TRUE(8, cmptle, 0xC0000000, 0x00000000, 0xBFF00000, 0x00000000)

    /* Test 9: -1.0 <= 1.0 (true) */
    TEST_FP_CMP_T_TRUE(9, cmptle, 0xBFF00000, 0x00000000, 0x3FF00000, 0x00000000)

    /*-------------------------------------------------------------
     * Greater-than tests - should return false (0.0)
     *-------------------------------------------------------------*/

    /* Test 10: 2.0 <= 1.0 (false) */
    TEST_FP_CMP_T_FALSE(10, cmptle, 0x40000000, 0x00000000, 0x3FF00000, 0x00000000)

    /* Test 11: 1.0 <= 0.0 (false) */
    TEST_FP_CMP_T_FALSE(11, cmptle, 0x3FF00000, 0x00000000, 0x00000000, 0x00000000)

    /* Test 12: 0.0 <= -1.0 (false) */
    TEST_FP_CMP_T_FALSE(12, cmptle, 0x00000000, 0x00000000, 0xBFF00000, 0x00000000)

    /* Test 13: -1.0 <= -2.0 (false) */
    TEST_FP_CMP_T_FALSE(13, cmptle, 0xBFF00000, 0x00000000, 0xC0000000, 0x00000000)

    /* Test 14: 1.0 <= -1.0 (false) */
    TEST_FP_CMP_T_FALSE(14, cmptle, 0x3FF00000, 0x00000000, 0xBFF00000, 0x00000000)

ALPHA_TEST_END
