/* SPARCv8 TVS instruction test (Trap on Overflow Set) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * TVS (Trap on Overflow Set) tests
   * TVS traps if V=1 (overflow occurred)
   * We test by ensuring execution continues when V=0
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: TVS should NOT trap when no overflow (V=0)
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set 10, %l1
    set 5, %l2
    addcc %l1, %l2, %g0   /* 10 + 5 = 15, no overflow, V=0 */
    tvs 0                 /* Should NOT trap since V=0 */
    set 42, %l3
    cmp %l3, 42
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: TVS should NOT trap with normal subtraction
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set 100, %l1
    set 50, %l2
    subcc %l1, %l2, %g0   /* 100 - 50 = 50, no overflow, V=0 */
    tvs 0                 /* Should NOT trap */
    ba test_3_pass
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: Multiple TVS with no overflow
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set 200, %l1
    set 100, %l2
    subcc %l1, %l2, %g0   /* 200 - 100 = 100, V=0 */
    tvs 0
    tvs 1
    tvs 2
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
