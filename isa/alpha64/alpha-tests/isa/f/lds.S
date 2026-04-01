/*
 * Alpha LDS (Load S_floating) Test
 * Tests IEEE 754 single-precision floating-point load
 */

#include "../../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic load tests
     *-------------------------------------------------------------*/

    /* Test 2: Load 1.0 */
    TEST_FP_LD_S(2, 0x3F800000, 0, fp_data1)

    /* Test 3: Load 2.0 */
    TEST_FP_LD_S(3, 0x40000000, 0, fp_data2)

    /* Test 4: Load 0.0 */
    TEST_FP_LD_S(4, 0x00000000, 0, fp_data3)

    /* Test 5: Load -1.0 */
    TEST_FP_LD_S(5, 0xBF800000, 0, fp_data4)

    /* Test 6: Load with offset */
    TEST_FP_LD_S(6, 0x40000000, 4, fp_data1)

    /* Test 7: Load 0.5 */
    TEST_FP_LD_S(7, 0x3F000000, 0, fp_data5)

ALPHA_TEST_END

    .data
    .align 3

fp_data1:
    .long 0x3F800000    /* 1.0 */
    .long 0x40000000    /* 2.0 */

fp_data2:
    .long 0x40000000    /* 2.0 */

fp_data3:
    .long 0x00000000    /* 0.0 */

fp_data4:
    .long 0xBF800000    /* -1.0 */

fp_data5:
    .long 0x3F000000    /* 0.5 */
