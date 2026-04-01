/*
 * Alpha BLBC (Branch if Low Bit Clear) Test
 * Tests conditional branching when Ra[0] == 0
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * BLBC taken tests (Ra[0] == 0, i.e., Ra is even)
     *-------------------------------------------------------------*/

    /* Test 1: BLBC taken when Ra = 0 */
    TEST_CASE_START(1)
    lda $1, 0($31)
    blbc $1, 1f
    br $31, fail
1:

    /* Test 2: BLBC taken when Ra = 2 */
    TEST_CASE_START(2)
    lda $1, 2($31)
    blbc $1, 1f
    br $31, fail
1:

    /* Test 3: BLBC taken when Ra = 100 */
    TEST_CASE_START(3)
    lda $1, 100($31)
    blbc $1, 1f
    br $31, fail
1:

    /* Test 4: BLBC taken when Ra = -2 (even negative) */
    TEST_CASE_START(4)
    lda $1, -2($31)
    blbc $1, 1f
    br $31, fail
1:

    /*-------------------------------------------------------------
     * BLBC not taken tests (Ra[0] == 1, i.e., Ra is odd)
     *-------------------------------------------------------------*/

    /* Test 5: BLBC not taken when Ra = 1 */
    TEST_CASE_START(5)
    lda $1, 1($31)
    blbc $1, 1f
    br $31, 2f
1:  br $31, fail
2:

    /* Test 6: BLBC not taken when Ra = 3 */
    TEST_CASE_START(6)
    lda $1, 3($31)
    blbc $1, 1f
    br $31, 2f
1:  br $31, fail
2:

    /* Test 7: BLBC not taken when Ra = -1 (odd negative) */
    TEST_CASE_START(7)
    lda $1, -1($31)
    blbc $1, 1f
    br $31, 2f
1:  br $31, fail
2:

ALPHA_TEST_END
