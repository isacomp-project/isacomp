/*
 * Alpha LDT (Load T_floating) Test
 * Tests double-precision FP load from memory
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Setup: Store FP values in memory for loading
     *-------------------------------------------------------------*/

    /* Test 1: Store 1.0 (0x3FF0000000000000) at addr 0x400 */
    TEST_CASE_START(1)
    lda $1, 0x400($31)
    ldiq $2, 0x00000000
    stq $2, 0($1)
    ldiq $2, 0x3FF00000
    stl $2, 4($1)

    /* Test 2: Load 1.0 from memory and verify */
    TEST_CASE_START(2)
    lda $1, 0x400($31)
    ldt $f1, 0($1)       /* f1 = 1.0 */
    /* Store 1.0 again for comparison */
    lda $3, 0x410($31)
    ldiq $2, 0x00000000
    stq $2, 0($3)
    ldiq $2, 0x3FF00000
    stl $2, 4($3)
    ldt $f2, 0($3)
    cmpteq $f1, $f2, $f3
    fbeq $f3, fail

    /* Test 3: Load 0.0 */
    TEST_CASE_START(3)
    lda $1, 0x420($31)
    stq $31, 0($1)       /* Store 0 (which is 0.0 in IEEE FP) */
    ldt $f1, 0($1)
    ldt $f2, 0($1)
    cmpteq $f1, $f2, $f3
    fbeq $f3, fail

    /* Test 4: Load with displacement */
    TEST_CASE_START(4)
    lda $1, 0x400($31)
    /* Store 2.0 (0x4000000000000000) at offset 16 */
    ldiq $2, 0x00000000
    stq $2, 16($1)
    ldiq $2, 0x40000000
    stl $2, 20($1)
    ldt $f1, 16($1)      /* Load 2.0 with displacement */
    /* Store expected at offset 24 */
    ldiq $2, 0x00000000
    stq $2, 24($1)
    ldiq $2, 0x40000000
    stl $2, 28($1)
    ldt $f2, 24($1)
    cmpteq $f1, $f2, $f3
    fbeq $f3, fail

ALPHA_TEST_END
