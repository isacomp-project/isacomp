/*
 * Alpha CMOVGE (Conditional Move if Greater Than or Equal to Zero) Test
 * If Ra >= 0, Rc = Rb, else Rc unchanged
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * CMOVGE move taken (Ra >= 0)
     *-------------------------------------------------------------*/

    /* Test 1: CMOVGE moves when Ra = 0 */
    TEST_CASE_START(1)
    lda $1, 0($31)       /* Ra = 0 */
    lda $2, 42($31)      /* Rb = 42 (source) */
    lda $3, 99($31)      /* Rc = 99 (will be overwritten) */
    cmovge $1, $2, $3
    lda $5, 42($31)      /* Expected: 42 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: CMOVGE moves when Ra = 1 */
    TEST_CASE_START(2)
    lda $1, 1($31)       /* Ra = 1 (positive) */
    lda $2, 77($31)      /* Rb = 77 */
    lda $3, 55($31)      /* Rc = 55 */
    cmovge $1, $2, $3
    lda $5, 77($31)      /* Expected: 77 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: CMOVGE moves when Ra = 100 */
    TEST_CASE_START(3)
    lda $1, 100($31)     /* Ra = 100 (positive) */
    lda $2, 88($31)      /* Rb = 88 */
    lda $3, 11($31)      /* Rc = 11 */
    cmovge $1, $2, $3
    lda $5, 88($31)      /* Expected: 88 */
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * CMOVGE move not taken (Ra < 0)
     *-------------------------------------------------------------*/

    /* Test 4: CMOVGE doesn't move when Ra = -1 */
    TEST_CASE_START(4)
    lda $1, -1($31)      /* Ra = -1 (negative) */
    lda $2, 42($31)      /* Rb = 42 */
    lda $3, 99($31)      /* Rc = 99 (should stay) */
    cmovge $1, $2, $3
    lda $5, 99($31)      /* Expected: 99 (unchanged) */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 5: CMOVGE doesn't move when Ra = -100 */
    TEST_CASE_START(5)
    lda $1, -100($31)    /* Ra = -100 (negative) */
    lda $2, 55($31)      /* Rb = 55 */
    lda $3, 33($31)      /* Rc = 33 (should stay) */
    cmovge $1, $2, $3
    lda $5, 33($31)      /* Expected: 33 (unchanged) */
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
