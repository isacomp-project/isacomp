/* SPARCv8 TVC instruction test (Trap on Overflow Clear) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * TVC (Trap on Overflow Clear) tests
   * TVC traps if V=0 (no overflow)
   * We test by ensuring execution continues when V=1
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: TVC should NOT trap when overflow occurs (V=1)
   * Overflow: positive + positive = negative
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set 0x7FFFFFFF, %l1   /* Max positive 32-bit integer */
    set 1, %l2
    addcc %l1, %l2, %g0   /* 0x7FFFFFFF + 1 = 0x80000000, overflow, V=1 */
    tvc 0                 /* Should NOT trap since V=1 */
    set 42, %l3
    cmp %l3, 42
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: TVC should NOT trap with negative overflow
   * Overflow: negative + negative = positive
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set 0x80000000, %l1   /* Min negative 32-bit integer */
    set 0x80000000, %l2
    addcc %l1, %l2, %g0   /* Negative overflow, V=1 */
    tvc 0                 /* Should NOT trap */
    ba test_3_pass
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: Multiple TVC with overflow condition
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set 0x7FFFFFFF, %l1
    set 100, %l2
    addcc %l1, %l2, %g0   /* Overflow, V=1 */
    tvc 0
    tvc 1
    tvc 2
    ba test_4_pass
    nop
test_4_pass:

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
