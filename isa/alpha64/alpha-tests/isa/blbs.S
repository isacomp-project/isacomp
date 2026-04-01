/*
 * Alpha BLBS (Branch if Low Bit Set) Test
 * Tests conditional branching when Ra[0] == 1
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * BLBS taken tests (Ra[0] == 1, i.e., Ra is odd)
     *-------------------------------------------------------------*/

    /* Test 1: BLBS taken when Ra = 1 */
    TEST_CASE_START(1)
    lda $1, 1($31)
    blbs $1, 1f
    br $31, fail
1:

    /* Test 2: BLBS taken when Ra = 3 */
    TEST_CASE_START(2)
    lda $1, 3($31)
    blbs $1, 1f
    br $31, fail
1:

    /* Test 3: BLBS taken when Ra = 101 */
    TEST_CASE_START(3)
    lda $1, 101($31)
    blbs $1, 1f
    br $31, fail
1:

    /* Test 4: BLBS taken when Ra = -1 (odd negative) */
    TEST_CASE_START(4)
    lda $1, -1($31)
    blbs $1, 1f
    br $31, fail
1:

    /*-------------------------------------------------------------
     * BLBS not taken tests (Ra[0] == 0, i.e., Ra is even)
     *-------------------------------------------------------------*/

    /* Test 5: BLBS not taken when Ra = 0 */
    TEST_CASE_START(5)
    lda $1, 0($31)
    blbs $1, 1f
    br $31, 2f
1:  br $31, fail
2:

    /* Test 6: BLBS not taken when Ra = 2 */
    TEST_CASE_START(6)
    lda $1, 2($31)
    blbs $1, 1f
    br $31, 2f
1:  br $31, fail
2:

    /* Test 7: BLBS not taken when Ra = -2 (even negative) */
    TEST_CASE_START(7)
    lda $1, -2($31)
    blbs $1, 1f
    br $31, 2f
1:  br $31, fail
2:

ALPHA_TEST_END
