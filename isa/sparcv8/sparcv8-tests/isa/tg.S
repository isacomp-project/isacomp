/* SPARCv8 TG instruction test (Trap on Greater) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * TG (Trap on Greater) tests
   * TG traps if (N xor V) = 0 AND Z = 0 (signed greater)
   * We test by ensuring execution continues when condition is false
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: TG should NOT trap when result is equal (Z=1)
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set 10, %l1
    set 10, %l2
    subcc %l1, %l2, %g0   /* 10 - 10 = 0, Z=1 */
    tg 0                  /* Should NOT trap since Z=1 (not greater) */
    set 42, %l3
    cmp %l3, 42
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: TG should NOT trap when result is less (N!=V)
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set 5, %l1
    set 10, %l2
    subcc %l1, %l2, %g0   /* 5 - 10 = -5, N=1, V=0 */
    tg 0                  /* Should NOT trap since N xor V = 1 */
    ba test_3_pass
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: Multiple TG with not-greater conditions
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set 50, %l1
    set 100, %l2
    subcc %l1, %l2, %g0   /* 50 - 100 = -50, less than */
    tg 0
    tg 1
    tg 2
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
