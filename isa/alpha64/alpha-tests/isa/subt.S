/*
 * Alpha SUBT (Subtract T_floating) Test
 * Tests double-precision FP subtraction
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Double-precision subtraction tests
     *-------------------------------------------------------------*/

    /* Test 1: Initialize FP data at address 0x300 */
    TEST_CASE_START(1)
    lda $1, 0x300($31)
    /* Store 3.0 (0x4008000000000000) */
    ldiq $2, 0x00000000
    stq $2, 0($1)
    ldiq $2, 0x40080000
    stl $2, 4($1)
    /* Store 2.0 (0x4000000000000000) */
    ldiq $2, 0x00000000
    stq $2, 8($1)
    ldiq $2, 0x40000000
    stl $2, 12($1)
    /* Store 1.0 (0x3FF0000000000000) - expected result of 3.0 - 2.0 */
    ldiq $2, 0x00000000
    stq $2, 16($1)
    ldiq $2, 0x3FF00000
    stl $2, 20($1)

    /* Test 2: 3.0 - 2.0 = 1.0 */
    TEST_CASE_START(2)
    lda $1, 0x300($31)
    ldt $f1, 0($1)       /* f1 = 3.0 */
    ldt $f2, 8($1)       /* f2 = 2.0 */
    subt $f1, $f2, $f3   /* f3 = 3.0 - 2.0 = 1.0 */
    ldt $f5, 16($1)      /* f5 = 1.0 (expected) */
    cmpteq $f3, $f5, $f6
    fbeq $f6, fail

    /* Test 3: 0.0 - 0.0 = 0.0 */
    TEST_CASE_START(3)
    lda $1, 0x300($31)
    lda $2, 0($31)
    stq $2, 24($1)       /* Store 0.0 */
    ldt $f1, 24($1)
    ldt $f2, 24($1)
    subt $f1, $f2, $f3
    ldt $f5, 24($1)
    cmpteq $f3, $f5, $f6
    fbeq $f6, fail

    /* Test 4: 2.0 - 2.0 = 0.0 */
    TEST_CASE_START(4)
    lda $1, 0x300($31)
    ldt $f1, 8($1)       /* f1 = 2.0 */
    ldt $f2, 8($1)       /* f2 = 2.0 */
    subt $f1, $f2, $f3   /* f3 = 0.0 */
    lda $2, 0($31)
    stq $2, 32($1)       /* Store 0.0 */
    ldt $f5, 32($1)
    cmpteq $f3, $f5, $f6
    fbeq $f6, fail

ALPHA_TEST_END
