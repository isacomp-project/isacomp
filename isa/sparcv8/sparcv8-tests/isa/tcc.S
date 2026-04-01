/* SPARCv8 TCC instruction test (Trap on Carry Clear) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * TCC (Trap on Carry Clear) tests
   * TCC traps if C flag is clear
   * We test by ensuring execution continues when C=1
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: TCC should NOT trap when C=1 (carry set)
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set 0xFFFFFFFF, %l1
    set 1, %l2
    addcc %l1, %l2, %g0   /* 0xFFFFFFFF + 1 = overflow, C=1 */
    tcc 0                 /* Should NOT trap since C=1 */
    set 42, %l3
    cmp %l3, 42
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: TCC should NOT trap when C=1 from subtraction
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set 5, %l1
    set 10, %l2
    subcc %l1, %l2, %g0   /* 5 - 10 = borrow, C=1 */
    tcc 0                 /* Should NOT trap since C=1 */
    ba test_3_pass
    nop
test_3_pass:

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
