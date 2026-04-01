/*
 * Alpha CPYS (Copy Sign) Test
 * Copies the sign bit from Fa and the exponent/mantissa from Fb
 * Result: sign(Fa) | exponent_mantissa(Fb)
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Copy sign tests
     * Note: For negative values, we use subtraction since ldiq can't
     * handle large positive values needed for negative FP bit patterns
     *-------------------------------------------------------------*/

    /* Test 1: Initialize FP data at address 0x300 */
    TEST_CASE_START(1)
    lda $1, 0x300($31)
    /* Store +1.0 (0x3FF0000000000000) */
    stq $31, 0($1)
    lda $2, 0x3FF0($31)
    sll $2, 16, $2
    sll $2, 16, $2
    sll $2, 16, $2
    stq $2, 0($1)
    /* Store +2.0 (0x4000000000000000) */
    stq $31, 8($1)
    lda $2, 0x4000($31)
    sll $2, 16, $2
    sll $2, 16, $2
    sll $2, 16, $2
    stq $2, 8($1)

    /* Test 2: cpys(+1.0, +2.0) = +2.0 (positive sign, positive value) */
    TEST_CASE_START(2)
    lda $1, 0x300($31)
    ldt $f1, 0($1)       /* f1 = +1.0 (positive sign source) */
    ldt $f2, 8($1)       /* f2 = +2.0 (magnitude source) */
    cpys $f1, $f2, $f3   /* f3 = +2.0 */
    ldt $f5, 8($1)       /* f5 = +2.0 (expected) */
    cmpteq $f3, $f5, $f6
    fbeq $f6, fail

    /* Test 3: Use CPYSN to test negative - cpysn(+1.0, +2.0) = -2.0 */
    TEST_CASE_START(3)
    lda $1, 0x300($31)
    ldt $f1, 0($1)       /* f1 = +1.0 */
    ldt $f2, 8($1)       /* f2 = +2.0 */
    cpysn $f1, $f2, $f3  /* f3 = -2.0 (negate sign of f1, apply to magnitude of f2) */
    /* Verify result is negative by checking if it's less than 0 */
    stq $31, 16($1)      /* Store 0.0 */
    ldt $f4, 16($1)      /* f4 = 0.0 */
    cmptlt $f3, $f4, $f5 /* f5 = 2.0 if f3 < 0, else 0.0 */
    ldt $f6, 8($1)       /* f6 = 2.0 (expected true result) */
    cmpteq $f5, $f6, $f7
    fbeq $f7, fail

    /* Test 4: cpys should preserve magnitude - cpys(val, val2) then check magnitude */
    TEST_CASE_START(4)
    lda $1, 0x300($31)
    ldt $f1, 8($1)       /* f1 = +2.0 */
    ldt $f2, 0($1)       /* f2 = +1.0 */
    cpys $f1, $f2, $f3   /* f3 = +1.0 (sign from 2.0 is +, magnitude from 1.0) */
    ldt $f5, 0($1)       /* f5 = +1.0 (expected) */
    cmpteq $f3, $f5, $f6
    fbeq $f6, fail

ALPHA_TEST_END
