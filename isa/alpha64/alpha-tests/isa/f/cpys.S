/*
 * Alpha CPYS (Copy Sign) Test
 * Copies sign of Fa, magnitude of Fb -> Fc
 */

#include "../../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * CPYS tests: result gets sign of Fa, magnitude of Fb
     *-------------------------------------------------------------*/

    /* Test 2: cpys(+1.0, +2.0) = +2.0 (positive sign, positive magnitude) */
    TEST_FP_CPYS(2, 0x40000000, 0x00000000, 0x3FF00000, 0x00000000, 0x40000000, 0x00000000)

    /* Test 3: cpys(-1.0, +2.0) = -2.0 (negative sign, positive magnitude) */
    TEST_FP_CPYS(3, 0xC0000000, 0x00000000, 0xBFF00000, 0x00000000, 0x40000000, 0x00000000)

    /* Test 4: cpys(+1.0, -2.0) = +2.0 (positive sign, abs of negative) */
    TEST_FP_CPYS(4, 0x40000000, 0x00000000, 0x3FF00000, 0x00000000, 0xC0000000, 0x00000000)

    /* Test 5: cpys(-1.0, -2.0) = -2.0 (negative sign, abs of negative) */
    TEST_FP_CPYS(5, 0xC0000000, 0x00000000, 0xBFF00000, 0x00000000, 0xC0000000, 0x00000000)

    /* Test 6: cpys(+0.0, +3.0) = +3.0 */
    TEST_FP_CPYS(6, 0x40080000, 0x00000000, 0x00000000, 0x00000000, 0x40080000, 0x00000000)

    /* Test 7: cpys(-1.0, +0.5) = -0.5 */
    TEST_FP_CPYS(7, 0xBFE00000, 0x00000000, 0xBFF00000, 0x00000000, 0x3FE00000, 0x00000000)

ALPHA_TEST_END
