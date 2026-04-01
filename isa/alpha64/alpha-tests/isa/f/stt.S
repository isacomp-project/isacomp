/*
 * Alpha STT (Store T_floating) Test
 * Tests IEEE 754 double-precision floating-point store
 */

#include "../../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic store tests (store and reload to verify)
     *-------------------------------------------------------------*/

    /* Test 2: Store and reload 1.0 */
    TEST_FP_ST_T(2, 0x3FF00000, 0x00000000, 0, fp_scratch_t)

    /* Test 3: Store and reload 2.0 */
    TEST_FP_ST_T(3, 0x40000000, 0x00000000, 8, fp_scratch_t)

    /* Test 4: Store and reload 0.0 */
    TEST_FP_ST_T(4, 0x00000000, 0x00000000, 16, fp_scratch_t)

    /* Test 5: Store and reload -1.0 */
    TEST_FP_ST_T(5, 0xBFF00000, 0x00000000, 24, fp_scratch_t)

    /* Test 6: Store and reload 0.5 */
    TEST_FP_ST_T(6, 0x3FE00000, 0x00000000, 32, fp_scratch_t)

    /* Test 7: Store and reload 3.0 */
    TEST_FP_ST_T(7, 0x40080000, 0x00000000, 40, fp_scratch_t)

ALPHA_TEST_END

    .data
    .align 3

fp_scratch_t:
    .space 64   /* Scratch space for store tests */
