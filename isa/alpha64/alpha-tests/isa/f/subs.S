/*
 * Alpha SUBS (Subtract S_floating) Test
 * Tests IEEE 754 single-precision subtraction
 *
 * IEEE 754 single-precision hex values:
 *   1.0  = 0x3F800000
 *   2.0  = 0x40000000
 *   3.0  = 0x40400000
 *   0.5  = 0x3F000000
 *   -1.0 = 0xBF800000
 *   0.0  = 0x00000000
 */

#include "../../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic arithmetic tests
     *-------------------------------------------------------------*/

    /* Test 2: 2.0 - 1.0 = 1.0 */
    TEST_FP_OP2_S(2, subs, 0x3F800000, 0x40000000, 0x3F800000)

    /* Test 3: 3.0 - 1.0 = 2.0 */
    TEST_FP_OP2_S(3, subs, 0x40000000, 0x40400000, 0x3F800000)

    /* Test 4: 3.0 - 2.0 = 1.0 */
    TEST_FP_OP2_S(4, subs, 0x3F800000, 0x40400000, 0x40000000)

    /* Test 5: 1.0 - 0.0 = 1.0 */
    TEST_FP_OP2_S(5, subs, 0x3F800000, 0x3F800000, 0x00000000)

    /* Test 6: 0.0 - 1.0 = -1.0 */
    TEST_FP_OP2_S(6, subs, 0xBF800000, 0x00000000, 0x3F800000)

    /* Test 7: 0.0 - 0.0 = 0.0 */
    TEST_FP_OP2_S(7, subs, 0x00000000, 0x00000000, 0x00000000)

    /* Test 8: 1.0 - 1.0 = 0.0 */
    TEST_FP_OP2_S(8, subs, 0x00000000, 0x3F800000, 0x3F800000)

    /* Test 9: 1.0 - (-1.0) = 2.0 */
    TEST_FP_OP2_S(9, subs, 0x40000000, 0x3F800000, 0xBF800000)

    /* Test 10: (-1.0) - (-1.0) = 0.0 */
    TEST_FP_OP2_S(10, subs, 0x00000000, 0xBF800000, 0xBF800000)

    /* Test 11: 2.5 - 0.5 = 2.0 */
    TEST_FP_OP2_S(11, subs, 0x40000000, 0x40200000, 0x3F000000)

ALPHA_TEST_END
