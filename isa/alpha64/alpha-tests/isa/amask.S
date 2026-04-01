/*
 * Alpha AMASK (Architecture Mask) Test
 * AMASK clears bits in the input corresponding to
 * architectural features that are present.
 *
 * Bits:
 *   0 - BWX (byte/word extension)
 *   1 - FIX (square root and FP-INT moves)
 *   2 - CIX (count extension)
 *   8 - MVI (multimedia extension)
 *   9 - PAT (precise arithmetic trap)
 *   10 - PMI (performance monitoring)
 *
 * If a feature is present, its bit is cleared in the result.
 */

#include "../env/test_macros.h"

ALPHA_TEST_BEGIN

    /*-------------------------------------------------------------
     * AMASK tests
     * The actual result depends on what features are implemented
     * We test that the instruction executes and returns something sensible
     *-------------------------------------------------------------*/

    /* Test 2: AMASK with 0 input should return 0 */
    TEST_AMASK(2, 0, 0)

    /* Test 3: AMASK doesn't crash with all bits set */
    TEST_CASE_START(3)
    lda $1, -1($31)         /* All bits set */
    amask $1, $3
    /* Just verify we got here - result depends on implementation */

    /* Test 4: AMASK with BWX bit (if not supported, bit remains set) */
    TEST_CASE_START(4)
    lda $1, 1($31)          /* Bit 0 = BWX */
    amask $1, $3
    /* Result is 0 if BWX supported, 1 if not */
    /* Just verify it executes */

    /* Test 5: AMASK with FIX bit */
    TEST_CASE_START(5)
    lda $1, 2($31)          /* Bit 1 = FIX */
    amask $1, $3

    /* Test 6: AMASK with CIX bit */
    TEST_CASE_START(6)
    lda $1, 4($31)          /* Bit 2 = CIX */
    amask $1, $3

    /* Test 7: AMASK with multiple feature bits */
    TEST_CASE_START(7)
    lda $1, 7($31)          /* BWX + FIX + CIX */
    amask $1, $3

    /* Test 8: AMASK result goes to R31 (discarded) */
    TEST_CASE_START(8)
    lda $1, 0xFF($31)
    amask $1, $31
    /* R31 should still be 0 */
    bne $31, fail

    /* Test 9: AMASK from R31 */
    TEST_CASE_START(9)
    amask $31, $3
    /* AMASK(0) = 0 */
    bne $3, fail

ALPHA_TEST_END
