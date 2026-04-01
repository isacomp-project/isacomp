/*
 * Alpha CVTQT (Convert Quadword to T_floating) Test
 * Converts 64-bit integer to double-precision floating-point
 */

#include "../../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Integer to double conversion tests
     *-------------------------------------------------------------*/

    /* Test 2: Convert 1 to 1.0 */
    TEST_CASE_START(2)
    lda $1, 1($31)
    itoft $1, $f1
    cvtqt $f1, $f3
    ldfpt $f5, 0x3FF00000, 0x00000000   /* 1.0 */
    cmpteq $f3, $f5, $f6
    fbeq $f6, fail

    /* Test 3: Convert 2 to 2.0 */
    TEST_CASE_START(3)
    lda $1, 2($31)
    itoft $1, $f1
    cvtqt $f1, $f3
    ldfpt $f5, 0x40000000, 0x00000000   /* 2.0 */
    cmpteq $f3, $f5, $f6
    fbeq $f6, fail

    /* Test 4: Convert 0 to 0.0 */
    TEST_CASE_START(4)
    lda $1, 0($31)
    itoft $1, $f1
    cvtqt $f1, $f3
    ldfpt $f5, 0x00000000, 0x00000000   /* 0.0 */
    cmpteq $f3, $f5, $f6
    fbeq $f6, fail

    /* Test 5: Convert 3 to 3.0 */
    TEST_CASE_START(5)
    lda $1, 3($31)
    itoft $1, $f1
    cvtqt $f1, $f3
    ldfpt $f5, 0x40080000, 0x00000000   /* 3.0 */
    cmpteq $f3, $f5, $f6
    fbeq $f6, fail

    /* Test 6: Convert 100 to 100.0 */
    TEST_CASE_START(6)
    lda $1, 100($31)
    itoft $1, $f1
    cvtqt $f1, $f3
    ldfpt $f5, 0x40590000, 0x00000000   /* 100.0 */
    cmpteq $f3, $f5, $f6
    fbeq $f6, fail

    /* Test 7: Convert -1 to -1.0 */
    TEST_CASE_START(7)
    lda $1, -1($31)
    itoft $1, $f1
    cvtqt $f1, $f3
    ldfpt $f5, 0xBFF00000, 0x00000000   /* -1.0 */
    cmpteq $f3, $f5, $f6
    fbeq $f6, fail

ALPHA_TEST_END
