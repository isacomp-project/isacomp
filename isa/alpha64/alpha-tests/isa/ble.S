/*
 * Alpha BLE (Branch if Less Than or Equal to Zero) Test
 * Tests conditional branching when Ra <= 0
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * BLE taken tests (Ra <= 0)
     *-------------------------------------------------------------*/

    /* Test 1: BLE taken when Ra = 0 */
    TEST_CASE_START(1)
    lda $1, 0($31)
    ble $1, 1f
    br $31, fail
1:

    /* Test 2: BLE taken when Ra = -1 */
    TEST_CASE_START(2)
    lda $1, -1($31)
    ble $1, 1f
    br $31, fail
1:

    /* Test 3: BLE taken when Ra = -100 */
    TEST_CASE_START(3)
    lda $1, -100($31)
    ble $1, 1f
    br $31, fail
1:

    /*-------------------------------------------------------------
     * BLE not taken tests (Ra > 0)
     *-------------------------------------------------------------*/

    /* Test 4: BLE not taken when Ra = 1 */
    TEST_CASE_START(4)
    lda $1, 1($31)
    ble $1, 1f
    br $31, 2f
1:  br $31, fail
2:

    /* Test 5: BLE not taken when Ra = 100 */
    TEST_CASE_START(5)
    lda $1, 100($31)
    ble $1, 1f
    br $31, 2f
1:  br $31, fail
2:

ALPHA_TEST_END
