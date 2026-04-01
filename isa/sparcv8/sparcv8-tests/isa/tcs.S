/* SPARCv8 TCS instruction test (Trap on Carry Set) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * TCS (Trap on Carry Set) tests
   * TCS traps if C flag is set
   * We test by ensuring execution continues when C=0
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: TCS should NOT trap when C=0 (no carry)
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set 5, %l1
    set 3, %l2
    addcc %l1, %l2, %g0   /* 5 + 3 = 8, no carry, C=0 */
    tcs 0                 /* Should NOT trap since C=0 */
    set 42, %l3
    cmp %l3, 42
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: TCS should NOT trap when C=0 from subtraction
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set 10, %l1
    set 5, %l2
    subcc %l1, %l2, %g0   /* 10 - 5 = 5, no borrow, C=0 */
    tcs 0                 /* Should NOT trap since C=0 */
    ba test_3_pass
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: Multiple TCS with C=0
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set 100, %l1
    set 50, %l2
    subcc %l1, %l2, %g0   /* 100 - 50 = 50, C=0 */
    tcs 0
    tcs 1
    tcs 2
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
