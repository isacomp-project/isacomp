/*
 * Alpha BGT (Branch if Greater Than Zero) Test
 * Tests conditional branching when Ra > 0
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * BGT taken tests (Ra > 0)
     *-------------------------------------------------------------*/

    /* Test 1: BGT taken when Ra = 1 */
    TEST_CASE_START(1)
    lda $1, 1($31)
    bgt $1, 1f
    br $31, fail
1:

    /* Test 2: BGT taken when Ra = 100 */
    TEST_CASE_START(2)
    lda $1, 100($31)
    bgt $1, 1f
    br $31, fail
1:

    /*-------------------------------------------------------------
     * BGT not taken tests (Ra <= 0)
     *-------------------------------------------------------------*/

    /* Test 3: BGT not taken when Ra = 0 */
    TEST_CASE_START(3)
    lda $1, 0($31)
    bgt $1, 1f
    br $31, 2f
1:  br $31, fail
2:

    /* Test 4: BGT not taken when Ra = -1 */
    TEST_CASE_START(4)
    lda $1, -1($31)
    bgt $1, 1f
    br $31, 2f
1:  br $31, fail
2:

    /* Test 5: BGT not taken when Ra = -100 */
    TEST_CASE_START(5)
    lda $1, -100($31)
    bgt $1, 1f
    br $31, 2f
1:  br $31, fail
2:

ALPHA_TEST_END
