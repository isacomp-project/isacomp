/*
 * Alpha STS (Store S_floating) Test
 * Tests IEEE 754 single-precision floating-point store
 */

#include "../../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic store tests (store and reload to verify)
     *-------------------------------------------------------------*/

    /* Test 2: Store and reload 1.0 */
    TEST_FP_ST_S(2, 0x3F800000, 0, fp_scratch_s)

    /* Test 3: Store and reload 2.0 */
    TEST_FP_ST_S(3, 0x40000000, 4, fp_scratch_s)

    /* Test 4: Store and reload 0.0 */
    TEST_FP_ST_S(4, 0x00000000, 8, fp_scratch_s)

    /* Test 5: Store and reload -1.0 */
    TEST_FP_ST_S(5, 0xBF800000, 12, fp_scratch_s)

    /* Test 6: Store and reload 0.5 */
    TEST_FP_ST_S(6, 0x3F000000, 16, fp_scratch_s)

    /* Test 7: Store and reload 3.0 */
    TEST_FP_ST_S(7, 0x40400000, 20, fp_scratch_s)

ALPHA_TEST_END

    .data
    .align 3

fp_scratch_s:
    .space 32   /* Scratch space for store tests */
