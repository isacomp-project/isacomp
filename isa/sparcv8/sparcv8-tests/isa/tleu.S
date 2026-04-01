/* SPARCv8 TLEU instruction test (Trap on Less or Equal Unsigned) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * TLEU (Trap on Less or Equal Unsigned) tests
   * TLEU traps if C=1 OR Z=1 (unsigned less or equal)
   * We test by ensuring execution continues when condition is false
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: TLEU should NOT trap when result is greater (C=0, Z=0)
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set 20, %l1
    set 10, %l2
    subcc %l1, %l2, %g0   /* 20 - 10 = 10, no borrow, C=0, Z=0 */
    tleu 0                /* Should NOT trap since C=0 and Z=0 */
    set 42, %l3
    cmp %l3, 42
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: TLEU should NOT trap when clearly greater
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set 100, %l1
    set 50, %l2
    subcc %l1, %l2, %g0   /* 100 - 50 = 50, unsigned greater */
    tleu 0                /* Should NOT trap */
    ba test_3_pass
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: Multiple TLEU with greater condition
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set 200, %l1
    set 100, %l2
    subcc %l1, %l2, %g0   /* 200 - 100 = 100, greater */
    tleu 0
    tleu 1
    tleu 2
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
