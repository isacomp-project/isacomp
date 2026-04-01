/* SPARCv8 TNE instruction test (Trap on Not Equal) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * TNE (Trap on Not Equal) tests
   * TNE traps if Z flag is clear (result was non-zero)
   * We test by ensuring execution continues when Z=1
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: TNE should NOT trap when Z=1 (values equal)
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set 10, %l1
    set 10, %l2
    subcc %l1, %l2, %g0   /* 10 - 10 = 0, Z=1 */
    tne 0                 /* Should NOT trap since Z=1 */
    set 42, %l3
    cmp %l3, 42
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: TNE with zero result from add
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    addcc %g0, %g0, %g0   /* 0 + 0 = 0, Z=1 */
    tne 0                 /* Should NOT trap */
    set 100, %l1
    cmp %l1, 100
    be test_3_pass
    nop
    ba fail
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: Multiple TNE with Z=1
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set 5, %l1
    subcc %l1, 5, %g0     /* 5 - 5 = 0, Z=1 */
    tne 0
    tne 1
    tne 2
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
