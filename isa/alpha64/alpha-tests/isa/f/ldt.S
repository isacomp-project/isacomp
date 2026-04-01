/*
 * Alpha LDT (Load T_floating) Test
 * Tests IEEE 754 double-precision floating-point load
 */

#include "../../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic load tests
     *-------------------------------------------------------------*/

    /* Test 2: Load 1.0 */
    TEST_FP_LD_T(2, 0x3FF00000, 0x00000000, 0, fp_data_t1)

    /* Test 3: Load 2.0 */
    TEST_FP_LD_T(3, 0x40000000, 0x00000000, 0, fp_data_t2)

    /* Test 4: Load 0.0 */
    TEST_FP_LD_T(4, 0x00000000, 0x00000000, 0, fp_data_t3)

    /* Test 5: Load -1.0 */
    TEST_FP_LD_T(5, 0xBFF00000, 0x00000000, 0, fp_data_t4)

    /* Test 6: Load with offset */
    TEST_FP_LD_T(6, 0x40000000, 0x00000000, 8, fp_data_t1)

    /* Test 7: Load 0.5 */
    TEST_FP_LD_T(7, 0x3FE00000, 0x00000000, 0, fp_data_t5)

ALPHA_TEST_END

    .data
    .align 3

fp_data_t1:
    .long 0x00000000    /* 1.0 low */
    .long 0x3FF00000    /* 1.0 high */
    .long 0x00000000    /* 2.0 low */
    .long 0x40000000    /* 2.0 high */

fp_data_t2:
    .long 0x00000000    /* 2.0 low */
    .long 0x40000000    /* 2.0 high */

fp_data_t3:
    .long 0x00000000    /* 0.0 low */
    .long 0x00000000    /* 0.0 high */

fp_data_t4:
    .long 0x00000000    /* -1.0 low */
    .long 0xBFF00000    /* -1.0 high */

fp_data_t5:
    .long 0x00000000    /* 0.5 low */
    .long 0x3FE00000    /* 0.5 high */
