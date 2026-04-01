/*
 * Alpha CMPTEQ (Compare T_floating Equal) Test
 * Tests IEEE 754 double-precision equality comparison
 *
 * Alpha FP comparisons return:
 *   2.0 (0x4000000000000000) if true
 *   0.0 (0x0000000000000000) if false
 */

#include "../../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Equality tests - should return true (2.0)
     *-------------------------------------------------------------*/

    /* Test 2: 1.0 == 1.0 (true) */
    TEST_FP_CMP_T_TRUE(2, cmpteq, 0x3FF00000, 0x00000000, 0x3FF00000, 0x00000000)

    /* Test 3: 2.0 == 2.0 (true) */
    TEST_FP_CMP_T_TRUE(3, cmpteq, 0x40000000, 0x00000000, 0x40000000, 0x00000000)

    /* Test 4: 0.0 == 0.0 (true) */
    TEST_FP_CMP_T_TRUE(4, cmpteq, 0x00000000, 0x00000000, 0x00000000, 0x00000000)

    /* Test 5: -1.0 == -1.0 (true) */
    TEST_FP_CMP_T_TRUE(5, cmpteq, 0xBFF00000, 0x00000000, 0xBFF00000, 0x00000000)

    /* Test 6: 0.5 == 0.5 (true) */
    TEST_FP_CMP_T_TRUE(6, cmpteq, 0x3FE00000, 0x00000000, 0x3FE00000, 0x00000000)

    /*-------------------------------------------------------------
     * Inequality tests - should return false (0.0)
     *-------------------------------------------------------------*/

    /* Test 7: 1.0 == 2.0 (false) */
    TEST_FP_CMP_T_FALSE(7, cmpteq, 0x3FF00000, 0x00000000, 0x40000000, 0x00000000)

    /* Test 8: 2.0 == 1.0 (false) */
    TEST_FP_CMP_T_FALSE(8, cmpteq, 0x40000000, 0x00000000, 0x3FF00000, 0x00000000)

    /* Test 9: 1.0 == -1.0 (false) */
    TEST_FP_CMP_T_FALSE(9, cmpteq, 0x3FF00000, 0x00000000, 0xBFF00000, 0x00000000)

    /* Test 10: 0.0 == 1.0 (false) */
    TEST_FP_CMP_T_FALSE(10, cmpteq, 0x00000000, 0x00000000, 0x3FF00000, 0x00000000)

    /* Test 11: -1.0 == 1.0 (false) */
    TEST_FP_CMP_T_FALSE(11, cmpteq, 0xBFF00000, 0x00000000, 0x3FF00000, 0x00000000)

    /* Test 12: 0.5 == 1.5 (false) */
    TEST_FP_CMP_T_FALSE(12, cmpteq, 0x3FE00000, 0x00000000, 0x3FF80000, 0x00000000)

ALPHA_TEST_END
