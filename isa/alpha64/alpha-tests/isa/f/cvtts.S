/*
 * Alpha CVTTS (Convert T_floating to S_floating) Test
 * Converts double-precision to single-precision
 */

#include "../../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Double to single conversion tests
     *-------------------------------------------------------------*/

    /* Test 2: Convert 1.0 (double) to 1.0 (single) */
    TEST_CASE_START(2)
    ldfpt $f1, 0x3FF00000, 0x00000000   /* 1.0 double */
    cvtts $f1, $f3
    ldfps $f5, 0x3F800000               /* 1.0 single */
    /* Compare by converting expected back to double */
    cvtst $f5, $f5
    cmpteq $f3, $f5, $f6
    fbeq $f6, fail

    /* Test 3: Convert 2.0 (double) to 2.0 (single) */
    TEST_CASE_START(3)
    ldfpt $f1, 0x40000000, 0x00000000   /* 2.0 double */
    cvtts $f1, $f3
    ldfps $f5, 0x40000000               /* 2.0 single */
    cvtst $f5, $f5
    cmpteq $f3, $f5, $f6
    fbeq $f6, fail

    /* Test 4: Convert 0.0 (double) to 0.0 (single) */
    TEST_CASE_START(4)
    ldfpt $f1, 0x00000000, 0x00000000   /* 0.0 double */
    cvtts $f1, $f3
    ldfps $f5, 0x00000000               /* 0.0 single */
    cvtst $f5, $f5
    cmpteq $f3, $f5, $f6
    fbeq $f6, fail

    /* Test 5: Convert -1.0 (double) to -1.0 (single) */
    TEST_CASE_START(5)
    ldfpt $f1, 0xBFF00000, 0x00000000   /* -1.0 double */
    cvtts $f1, $f3
    ldfps $f5, 0xBF800000               /* -1.0 single */
    cvtst $f5, $f5
    cmpteq $f3, $f5, $f6
    fbeq $f6, fail

    /* Test 6: Convert 0.5 (double) to 0.5 (single) */
    TEST_CASE_START(6)
    ldfpt $f1, 0x3FE00000, 0x00000000   /* 0.5 double */
    cvtts $f1, $f3
    ldfps $f5, 0x3F000000               /* 0.5 single */
    cvtst $f5, $f5
    cmpteq $f3, $f5, $f6
    fbeq $f6, fail

ALPHA_TEST_END
