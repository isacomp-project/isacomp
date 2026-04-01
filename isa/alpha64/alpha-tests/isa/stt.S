/*
 * Alpha STT (Store T_floating) Test
 * Tests double-precision FP store to memory
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * Setup: Load FP value into register
     *-------------------------------------------------------------*/

    /* Test 1: Setup - store 1.0 in memory and load to f1 */
    TEST_CASE_START(1)
    lda $1, 0x400($31)
    ldiq $2, 0x00000000
    stq $2, 0($1)
    ldiq $2, 0x3FF00000
    stl $2, 4($1)
    ldt $f1, 0($1)       /* f1 = 1.0 */

    /* Test 2: Store f1 to different location and verify */
    TEST_CASE_START(2)
    lda $1, 0x410($31)
    stt $f1, 0($1)       /* Store 1.0 */
    ldt $f2, 0($1)       /* Load it back */
    cmpteq $f1, $f2, $f3
    fbeq $f3, fail

    /* Test 3: Store 0.0 */
    TEST_CASE_START(3)
    lda $1, 0x420($31)
    stq $31, 0($1)       /* Clear memory first */
    ldt $f1, 0($1)       /* f1 = 0.0 */
    lda $2, 0x430($31)
    stt $f1, 0($2)       /* Store 0.0 */
    ldt $f2, 0($2)       /* Load it back */
    cmpteq $f1, $f2, $f3
    fbeq $f3, fail

    /* Test 4: Store with displacement */
    TEST_CASE_START(4)
    lda $1, 0x400($31)
    /* Load 2.0 to f1 */
    ldiq $2, 0x00000000
    stq $2, 40($1)
    ldiq $2, 0x40000000
    stl $2, 44($1)
    ldt $f1, 40($1)      /* f1 = 2.0 */
    /* Store at different offset */
    stt $f1, 48($1)
    ldt $f2, 48($1)      /* Load back */
    cmpteq $f1, $f2, $f3
    fbeq $f3, fail

ALPHA_TEST_END
