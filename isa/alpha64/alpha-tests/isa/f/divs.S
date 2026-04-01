/*
 * Alpha DIVS (Divide S_floating) Test
 * Tests IEEE 754 single-precision division
 *
 * IEEE 754 single-precision hex values:
 *   1.0  = 0x3F800000
 *   2.0  = 0x40000000
 *   3.0  = 0x40400000
 *   4.0  = 0x40800000
 *   0.5  = 0x3F000000
 *   0.25 = 0x3E800000
 *   -1.0 = 0xBF800000
 *   -2.0 = 0xC0000000
 *   0.0  = 0x00000000
 */

#include "../../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic arithmetic tests
     *-------------------------------------------------------------*/

    /* Test 2: 4.0 / 2.0 = 2.0 */
    TEST_FP_OP2_S(2, divs, 0x40000000, 0x40800000, 0x40000000)

    /* Test 3: 2.0 / 1.0 = 2.0 */
    TEST_FP_OP2_S(3, divs, 0x40000000, 0x40000000, 0x3F800000)

    /* Test 4: 1.0 / 1.0 = 1.0 */
    TEST_FP_OP2_S(4, divs, 0x3F800000, 0x3F800000, 0x3F800000)

    /* Test 5: 1.0 / 2.0 = 0.5 */
    TEST_FP_OP2_S(5, divs, 0x3F000000, 0x3F800000, 0x40000000)

    /* Test 6: 1.0 / 4.0 = 0.25 */
    TEST_FP_OP2_S(6, divs, 0x3E800000, 0x3F800000, 0x40800000)

    /* Test 7: 0.0 / 1.0 = 0.0 */
    TEST_FP_OP2_S(7, divs, 0x00000000, 0x00000000, 0x3F800000)

    /* Test 8: 0.0 / 2.0 = 0.0 */
    TEST_FP_OP2_S(8, divs, 0x00000000, 0x00000000, 0x40000000)

    /* Test 9: 2.0 / (-1.0) = -2.0 */
    TEST_FP_OP2_S(9, divs, 0xC0000000, 0x40000000, 0xBF800000)

    /* Test 10: (-2.0) / (-1.0) = 2.0 */
    TEST_FP_OP2_S(10, divs, 0x40000000, 0xC0000000, 0xBF800000)

    /* Test 11: (-1.0) / 2.0 = -0.5 */
    TEST_FP_OP2_S(11, divs, 0xBF000000, 0xBF800000, 0x40000000)

    /* Test 12: 3.0 / 2.0 = 1.5 (0x3FC00000) */
    TEST_FP_OP2_S(12, divs, 0x3FC00000, 0x40400000, 0x40000000)

ALPHA_TEST_END
