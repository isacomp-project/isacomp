/* SPARCv8 TPOS instruction test (Trap on Positive) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * TPOS (Trap on Positive) tests
   * TPOS traps if N=0 (result was positive or zero)
   * We test by ensuring execution continues when N=1
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: TPOS should NOT trap when result is negative (N=1)
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set 5, %l1
    set 10, %l2
    subcc %l1, %l2, %g0   /* 5 - 10 = -5, N=1 */
    tpos 0                /* Should NOT trap since N=1 */
    set 42, %l3
    cmp %l3, 42
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: TPOS should NOT trap with negative result
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set 0, %l1
    set 1, %l2
    subcc %l1, %l2, %g0   /* 0 - 1 = -1, N=1 */
    tpos 0                /* Should NOT trap */
    ba test_3_pass
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: Multiple TPOS with negative result
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set 10, %l1
    set 100, %l2
    subcc %l1, %l2, %g0   /* 10 - 100 = -90, N=1 */
    tpos 0
    tpos 1
    tpos 2
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
