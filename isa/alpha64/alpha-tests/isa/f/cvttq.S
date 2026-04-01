/*
 * Alpha CVTTQ (Convert T_floating to Quadword) Test
 * Converts double-precision floating-point to 64-bit integer
 */

#include "../../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Double to integer conversion tests
     * Note: Result is stored in FP register as bit pattern
     *-------------------------------------------------------------*/

    /* Test 2: Convert 1.0 to 1 */
    TEST_CASE_START(2)
    ldfpt $f1, 0x3FF00000, 0x00000000   /* 1.0 */
    cvttq $f1, $f3
    /* Move FP to integer reg and compare */
    ftoit $f3, $1
    lda $5, 1($31)
    cmpeq $1, $5, $6
    beq $6, fail

    /* Test 3: Convert 2.0 to 2 */
    TEST_CASE_START(3)
    ldfpt $f1, 0x40000000, 0x00000000   /* 2.0 */
    cvttq $f1, $f3
    ftoit $f3, $1
    lda $5, 2($31)
    cmpeq $1, $5, $6
    beq $6, fail

    /* Test 4: Convert 0.0 to 0 */
    TEST_CASE_START(4)
    ldfpt $f1, 0x00000000, 0x00000000   /* 0.0 */
    cvttq $f1, $f3
    ftoit $f3, $1
    lda $5, 0($31)
    cmpeq $1, $5, $6
    beq $6, fail

    /* Test 5: Convert 3.0 to 3 */
    TEST_CASE_START(5)
    ldfpt $f1, 0x40080000, 0x00000000   /* 3.0 */
    cvttq $f1, $f3
    ftoit $f3, $1
    lda $5, 3($31)
    cmpeq $1, $5, $6
    beq $6, fail

    /* Test 6: Convert 100.0 to 100 */
    TEST_CASE_START(6)
    ldfpt $f1, 0x40590000, 0x00000000   /* 100.0 */
    cvttq $f1, $f3
    ftoit $f3, $1
    lda $5, 100($31)
    cmpeq $1, $5, $6
    beq $6, fail

    /* Test 7: Convert -1.0 to -1 */
    TEST_CASE_START(7)
    ldfpt $f1, 0xBFF00000, 0x00000000   /* -1.0 */
    cvttq $f1, $f3
    ftoit $f3, $1
    lda $5, -1($31)
    cmpeq $1, $5, $6
    beq $6, fail

ALPHA_TEST_END
