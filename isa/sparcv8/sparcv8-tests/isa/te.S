/* SPARCv8 TE instruction test (Trap on Equal) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * TE (Trap on Equal) tests
   * TE traps if Z flag is set (result was zero)
   * We test by ensuring execution continues when Z=0
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: TE should NOT trap when Z=0 (values unequal)
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set 10, %l1
    set 5, %l2
    subcc %l1, %l2, %g0   /* 10 - 5 = 5, Z=0 */
    te 0                  /* Should NOT trap since Z=0 */
    set 42, %l3
    cmp %l3, 42
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: Multiple conditional traps with Z=0
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set 100, %l1
    set 50, %l2
    subcc %l1, %l2, %g0   /* 100 - 50 = 50, Z=0 */
    te 0
    te 1
    te 2
    set 99, %l3
    cmp %l3, 99
    be test_3_pass
    nop
    ba fail
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: TE with positive result (Z=0)
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set 1, %l1
    addcc %g0, %l1, %g0   /* 0 + 1 = 1, Z=0 */
    te 0                  /* Should NOT trap */
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
