/* SPARCv8 TNEG instruction test (Trap on Negative) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * TNEG (Trap on Negative) tests
   * TNEG traps if N=1 (result was negative)
   * We test by ensuring execution continues when N=0
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: TNEG should NOT trap when result is positive (N=0)
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set 20, %l1
    set 10, %l2
    subcc %l1, %l2, %g0   /* 20 - 10 = 10, N=0 */
    tneg 0                /* Should NOT trap since N=0 */
    set 42, %l3
    cmp %l3, 42
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: TNEG should NOT trap when result is zero (N=0)
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set 50, %l1
    set 50, %l2
    subcc %l1, %l2, %g0   /* 50 - 50 = 0, N=0, Z=1 */
    tneg 0                /* Should NOT trap */
    ba test_3_pass
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: Multiple TNEG with positive result
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set 100, %l1
    set 50, %l2
    subcc %l1, %l2, %g0   /* 100 - 50 = 50, N=0 */
    tneg 0
    tneg 1
    tneg 2
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
