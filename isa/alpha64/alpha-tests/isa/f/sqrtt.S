/*
 * Alpha SQRTT (Square Root T_floating) Test
 * Tests IEEE 754 double-precision square root
 *
 * IEEE 754 double-precision hex values:
 *   1.0  = 0x3FF00000_00000000
 *   2.0  = 0x40000000_00000000
 *   4.0  = 0x40100000_00000000
 *   9.0  = 0x40220000_00000000
 *   16.0 = 0x40300000_00000000
 *   25.0 = 0x40390000_00000000
 *   0.25 = 0x3FD00000_00000000
 *   0.5  = 0x3FE00000_00000000
 */

#include "../../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Square root tests
     *-------------------------------------------------------------*/

    /* Test 2: sqrt(1.0) = 1.0 */
    TEST_FP_OP1_T(2, sqrtt, 0x3FF00000, 0x00000000, 0x3FF00000, 0x00000000)

    /* Test 3: sqrt(4.0) = 2.0 */
    TEST_FP_OP1_T(3, sqrtt, 0x40000000, 0x00000000, 0x40100000, 0x00000000)

    /* Test 4: sqrt(9.0) = 3.0 */
    TEST_FP_OP1_T(4, sqrtt, 0x40080000, 0x00000000, 0x40220000, 0x00000000)

    /* Test 5: sqrt(16.0) = 4.0 */
    TEST_FP_OP1_T(5, sqrtt, 0x40100000, 0x00000000, 0x40300000, 0x00000000)

    /* Test 6: sqrt(25.0) = 5.0 */
    TEST_FP_OP1_T(6, sqrtt, 0x40140000, 0x00000000, 0x40390000, 0x00000000)

    /* Test 7: sqrt(0.25) = 0.5 */
    TEST_FP_OP1_T(7, sqrtt, 0x3FE00000, 0x00000000, 0x3FD00000, 0x00000000)

    /* Test 8: sqrt(0.0) = 0.0 */
    TEST_FP_OP1_T(8, sqrtt, 0x00000000, 0x00000000, 0x00000000, 0x00000000)

ALPHA_TEST_END
