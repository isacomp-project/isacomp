/* SPARCv8 TGE instruction test (Trap on Greater or Equal) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * TGE (Trap on Greater or Equal) tests
   * TGE traps if (N xor V) = 0 (signed greater or equal)
   * We test by ensuring execution continues when condition is false
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: TGE should NOT trap when result is less (N!=V)
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set 5, %l1
    set 10, %l2
    subcc %l1, %l2, %g0   /* 5 - 10 = -5, N=1, V=0, so N xor V = 1 */
    tge 0                 /* Should NOT trap since N xor V = 1 */
    set 42, %l3
    cmp %l3, 42
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: TGE should NOT trap when clearly less
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set 10, %l1
    set 100, %l2
    subcc %l1, %l2, %g0   /* 10 - 100 = -90, less than */
    tge 0                 /* Should NOT trap */
    ba test_3_pass
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: Multiple TGE with less condition
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set 1, %l1
    set 50, %l2
    subcc %l1, %l2, %g0   /* 1 - 50 = -49, less */
    tge 0
    tge 1
    tge 2
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
