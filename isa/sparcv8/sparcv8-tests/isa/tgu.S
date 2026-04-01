/* SPARCv8 TGU instruction test (Trap on Greater Unsigned) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * TGU (Trap on Greater Unsigned) tests
   * TGU traps if C=0 AND Z=0 (unsigned greater)
   * We test by ensuring execution continues when condition is false
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: TGU should NOT trap when result is equal (Z=1)
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set 10, %l1
    set 10, %l2
    subcc %l1, %l2, %g0   /* 10 - 10 = 0, Z=1 */
    tgu 0                 /* Should NOT trap since Z=1 */
    set 42, %l3
    cmp %l3, 42
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: TGU should NOT trap when result is less (C=1)
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set 5, %l1
    set 10, %l2
    subcc %l1, %l2, %g0   /* 5 - 10 causes borrow, C=1 */
    tgu 0                 /* Should NOT trap since C=1 */
    ba test_3_pass
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: Multiple TGU with not-greater conditions
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set 50, %l1
    set 100, %l2
    subcc %l1, %l2, %g0   /* 50 - 100, unsigned less */
    tgu 0
    tgu 1
    tgu 2
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
