/*
 * Alpha LDA (Load Address) Test
 * Tests address calculation: Rc = Rb + sext(disp)
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Basic tests with R31 (zero) as base
     *-------------------------------------------------------------*/

    /* Test 1: LDA with 0 displacement */
    TEST_CASE_START(1)
    lda $3, 0($31)
    lda $5, 0($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 2: LDA with positive displacement */
    TEST_CASE_START(2)
    lda $3, 100($31)
    lda $5, 100($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 3: LDA with negative displacement */
    TEST_CASE_START(3)
    lda $3, -1($31)
    lda $5, -1($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 4: LDA with max positive 16-bit displacement (32767) */
    TEST_CASE_START(4)
    lda $3, 32767($31)
    lda $5, 32767($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 5: LDA with max negative 16-bit displacement (-32768) */
    TEST_CASE_START(5)
    lda $3, -32768($31)
    lda $5, -32768($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Tests with non-zero base register
     *-------------------------------------------------------------*/

    /* Test 6: LDA base=100, disp=50 -> 150 */
    TEST_CASE_START(6)
    lda $1, 100($31)
    lda $3, 50($1)
    lda $5, 150($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 7: LDA base=100, disp=-50 -> 50 */
    TEST_CASE_START(7)
    lda $1, 100($31)
    lda $3, -50($1)
    lda $5, 50($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /* Test 8: LDA base=1000, disp=234 -> 1234 */
    TEST_CASE_START(8)
    lda $1, 1000($31)
    lda $3, 234($1)
    lda $5, 1234($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * Sequential LDA to build larger values
     *-------------------------------------------------------------*/

    /* Test 9: Use LDA to set value, then add to it */
    TEST_CASE_START(9)
    lda $1, 500($31)
    lda $3, 500($1)
    lda $5, 1000($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * LDA to same register (Rc = Ra)
     *-------------------------------------------------------------*/

    /* Test 10: LDA to same register */
    TEST_CASE_START(10)
    lda $3, 200($31)
    lda $3, 100($3)
    lda $5, 300($31)
    cmpeq $3, $5, $6
    beq $6, fail

    /*-------------------------------------------------------------
     * All tests passed - fall through to ALPHA_TEST_END
     *-------------------------------------------------------------*/

ALPHA_TEST_END
