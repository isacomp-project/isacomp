/*
 * Alpha CMPTLE (Compare T_floating Less Than or Equal) Test
 * Tests double-precision FP less-than-or-equal comparison
 * Result is 2.0 (true) or 0.0 (false) in Alpha convention
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Double-precision less-than-or-equal comparison tests
     *-------------------------------------------------------------*/

    /* Test 1: Initialize FP data at address 0x300 */
    TEST_CASE_START(1)
    lda $1, 0x300($31)
    /* Store 1.0 (0x3FF0000000000000) */
    ldiq $2, 0x00000000
    stq $2, 0($1)
    ldiq $2, 0x3FF00000
    stl $2, 4($1)
    /* Store 2.0 (0x4000000000000000) */
    ldiq $2, 0x00000000
    stq $2, 8($1)
    ldiq $2, 0x40000000
    stl $2, 12($1)
    /* Store 0.0 */
    stq $31, 16($1)

    /* Test 2: 1.0 <= 2.0 (should be true, result = 2.0) */
    TEST_CASE_START(2)
    lda $1, 0x300($31)
    ldt $f1, 0($1)       /* f1 = 1.0 */
    ldt $f2, 8($1)       /* f2 = 2.0 */
    cmptle $f1, $f2, $f3 /* f3 = 2.0 (true) */
    ldt $f5, 8($1)       /* f5 = 2.0 (expected) */
    cmpteq $f3, $f5, $f6
    fbeq $f6, fail

    /* Test 3: 2.0 <= 1.0 (should be false, result = 0.0) */
    TEST_CASE_START(3)
    lda $1, 0x300($31)
    ldt $f1, 8($1)       /* f1 = 2.0 */
    ldt $f2, 0($1)       /* f2 = 1.0 */
    cmptle $f1, $f2, $f3 /* f3 = 0.0 (false) */
    ldt $f5, 16($1)      /* f5 = 0.0 (expected) */
    cmpteq $f3, $f5, $f6
    fbeq $f6, fail

    /* Test 4: 1.0 <= 1.0 (should be true, result = 2.0) */
    TEST_CASE_START(4)
    lda $1, 0x300($31)
    ldt $f1, 0($1)       /* f1 = 1.0 */
    ldt $f2, 0($1)       /* f2 = 1.0 */
    cmptle $f1, $f2, $f3 /* f3 = 2.0 (true) */
    ldt $f5, 8($1)       /* f5 = 2.0 (expected) */
    cmpteq $f3, $f5, $f6
    fbeq $f6, fail

    /* Test 5: 0.0 <= 0.0 (should be true, result = 2.0) */
    TEST_CASE_START(5)
    lda $1, 0x300($31)
    ldt $f1, 16($1)      /* f1 = 0.0 */
    ldt $f2, 16($1)      /* f2 = 0.0 */
    cmptle $f1, $f2, $f3 /* f3 = 2.0 (true) */
    ldt $f5, 8($1)       /* f5 = 2.0 (expected) */
    cmpteq $f3, $f5, $f6
    fbeq $f6, fail

ALPHA_TEST_END
