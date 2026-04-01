/*
 * Alpha CMOVEQ (Conditional Move if Equal to Zero) Test
 * If Ra == 0, Rc = Rb, else Rc unchanged
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * CMOVEQ move taken (Ra == 0)
     *-------------------------------------------------------------*/

    /* Test 1: CMOVEQ moves when Ra = 0 */
    TEST_CASE_START(1)
    lda $1, 0($31)       /* Ra = 0 (condition) */
    lda $2, 42($31)      /* Rb = 42 (source) */
    lda $3, 99($31)      /* Rc = 99 (destination, will be overwritten) */
    cmoveq $1, $2, $3
    lda $5, 42($31)      /* Expected: 42 */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: CMOVEQ with R31 as condition (always zero) */
    TEST_CASE_START(2)
    lda $2, 100($31)     /* Rb = 100 */
    lda $3, 50($31)      /* Rc = 50 */
    cmoveq $31, $2, $3
    lda $5, 100($31)     /* Expected: 100 */
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * CMOVEQ move not taken (Ra != 0)
     *-------------------------------------------------------------*/

    /* Test 3: CMOVEQ doesn't move when Ra = 1 */
    TEST_CASE_START(3)
    lda $1, 1($31)       /* Ra = 1 (non-zero) */
    lda $2, 42($31)      /* Rb = 42 */
    lda $3, 99($31)      /* Rc = 99 (should stay) */
    cmoveq $1, $2, $3
    lda $5, 99($31)      /* Expected: 99 (unchanged) */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: CMOVEQ doesn't move when Ra = -1 */
    TEST_CASE_START(4)
    lda $1, -1($31)      /* Ra = -1 (non-zero) */
    lda $2, 42($31)      /* Rb = 42 */
    lda $3, 77($31)      /* Rc = 77 (should stay) */
    cmoveq $1, $2, $3
    lda $5, 77($31)      /* Expected: 77 (unchanged) */
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 5: CMOVEQ doesn't move when Ra = 100 */
    TEST_CASE_START(5)
    lda $1, 100($31)     /* Ra = 100 (non-zero) */
    lda $2, 55($31)      /* Rb = 55 */
    lda $3, 33($31)      /* Rc = 33 (should stay) */
    cmoveq $1, $2, $3
    lda $5, 33($31)      /* Expected: 33 (unchanged) */
    cmpeq $3, $5, $6
    beq $6, fail

ALPHA_TEST_END
