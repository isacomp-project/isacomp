/*
 * Alpha CPYSN (Copy Sign Negated) Test
 * Copies negated sign of Fa, magnitude of Fb -> Fc
 */

#include "../../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * CPYSN tests: result gets negated sign of Fa, magnitude of Fb
     *-------------------------------------------------------------*/

    /* Test 2: cpysn(+1.0, +2.0) = -2.0 (negated positive -> negative) */
    TEST_CASE_START(2)
    ldfpt $f1, 0x3FF00000, 0x00000000
    ldfpt $f2, 0x40000000, 0x00000000
    cpysn $f1, $f2, $f3
    ldfpt $f5, 0xC0000000, 0x00000000
    cmpteq $f3, $f5, $f6
    fbeq $f6, fail

    /* Test 3: cpysn(-1.0, +2.0) = +2.0 (negated negative -> positive) */
    TEST_CASE_START(3)
    ldfpt $f1, 0xBFF00000, 0x00000000
    ldfpt $f2, 0x40000000, 0x00000000
    cpysn $f1, $f2, $f3
    ldfpt $f5, 0x40000000, 0x00000000
    cmpteq $f3, $f5, $f6
    fbeq $f6, fail

    /* Test 4: cpysn(+1.0, -2.0) = -2.0 (negated positive, abs magnitude) */
    TEST_CASE_START(4)
    ldfpt $f1, 0x3FF00000, 0x00000000
    ldfpt $f2, 0xC0000000, 0x00000000
    cpysn $f1, $f2, $f3
    ldfpt $f5, 0xC0000000, 0x00000000
    cmpteq $f3, $f5, $f6
    fbeq $f6, fail

    /* Test 5: cpysn(-1.0, -2.0) = +2.0 (negated negative, abs magnitude) */
    TEST_CASE_START(5)
    ldfpt $f1, 0xBFF00000, 0x00000000
    ldfpt $f2, 0xC0000000, 0x00000000
    cpysn $f1, $f2, $f3
    ldfpt $f5, 0x40000000, 0x00000000
    cmpteq $f3, $f5, $f6
    fbeq $f6, fail

    /* Test 6: cpysn(+0.5, +3.0) = -3.0 */
    TEST_CASE_START(6)
    ldfpt $f1, 0x3FE00000, 0x00000000
    ldfpt $f2, 0x40080000, 0x00000000
    cpysn $f1, $f2, $f3
    ldfpt $f5, 0xC0080000, 0x00000000
    cmpteq $f3, $f5, $f6
    fbeq $f6, fail

ALPHA_TEST_END
