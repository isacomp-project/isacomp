/*
 * Alpha ADDS (Add S_floating) Test
 * Tests IEEE 754 single-precision addition
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

    /* Test 2: 1.0 + 1.0 = 2.0 */
    TEST_FP_OP2_S(2, adds, 0x40000000, 0x3F800000, 0x3F800000)

    /* Test 3: 1.0 + 2.0 = 3.0 */
    TEST_FP_OP2_S(3, adds, 0x40400000, 0x3F800000, 0x40000000)

    /* Test 4: 2.0 + 1.0 = 3.0 (commutativity) */
    TEST_FP_OP2_S(4, adds, 0x40400000, 0x40000000, 0x3F800000)

    /* Test 5: 0.0 + 1.0 = 1.0 */
    TEST_FP_OP2_S(5, adds, 0x3F800000, 0x00000000, 0x3F800000)

    /* Test 6: 1.0 + 0.0 = 1.0 */
    TEST_FP_OP2_S(6, adds, 0x3F800000, 0x3F800000, 0x00000000)

    /* Test 7: 0.0 + 0.0 = 0.0 */
    TEST_FP_OP2_S(7, adds, 0x00000000, 0x00000000, 0x00000000)

    /* Test 8: 1.0 + (-1.0) = 0.0 */
    TEST_FP_OP2_S(8, adds, 0x00000000, 0x3F800000, 0xBF800000)

    /* Test 9: (-1.0) + (-1.0) = -2.0 */
    TEST_FP_OP2_S(9, adds, 0xC0000000, 0xBF800000, 0xBF800000)

    /* Test 10: 0.5 + 0.5 = 1.0 */
    TEST_FP_OP2_S(10, adds, 0x3F800000, 0x3F000000, 0x3F000000)

    /* Test 11: 2.0 + 0.5 = 2.5 (0x40200000) */
    TEST_FP_OP2_S(11, adds, 0x40200000, 0x40000000, 0x3F000000)

ALPHA_TEST_END
