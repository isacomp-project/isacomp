/* SPARCv8 TLE instruction test (Trap on Less or Equal) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * TLE (Trap on Less or Equal) tests
   * TLE traps if Z=1 OR (N xor V)=1 (signed less or equal)
   * We test by ensuring execution continues when condition is false
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: TLE should NOT trap when result is greater (N=V, Z=0)
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set 20, %l1
    set 10, %l2
    subcc %l1, %l2, %g0   /* 20 - 10 = 10, positive, N=0, V=0, Z=0 */
    tle 0                 /* Should NOT trap since N xor V = 0 and Z=0 */
    set 42, %l3
    cmp %l3, 42
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: TLE should NOT trap when clearly greater
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set 100, %l1
    set 50, %l2
    subcc %l1, %l2, %g0   /* 100 - 50 = 50, greater */
    tle 0                 /* Should NOT trap */
    ba test_3_pass
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: Multiple TLE with greater condition
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set 200, %l1
    set 100, %l2
    subcc %l1, %l2, %g0   /* 200 - 100 = 100, greater */
    tle 0
    tle 1
    tle 2
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
