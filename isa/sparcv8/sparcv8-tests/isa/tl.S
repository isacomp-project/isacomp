/* SPARCv8 TL instruction test (Trap on Less) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * TL (Trap on Less) tests
   * TL traps if (N xor V) = 1 (signed less than)
   * We test by ensuring execution continues when condition is false
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: TL should NOT trap when result is greater (N=V)
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set 20, %l1
    set 10, %l2
    subcc %l1, %l2, %g0   /* 20 - 10 = 10, N=0, V=0, so N xor V = 0 */
    tl 0                  /* Should NOT trap since N xor V = 0 */
    set 42, %l3
    cmp %l3, 42
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: TL should NOT trap when equal (Z=1, N=V)
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set 50, %l1
    set 50, %l2
    subcc %l1, %l2, %g0   /* 50 - 50 = 0, Z=1 */
    tl 0                  /* Should NOT trap since N xor V = 0 */
    ba test_3_pass
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: Multiple TL with greater condition
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set 100, %l1
    set 50, %l2
    subcc %l1, %l2, %g0   /* 100 - 50 = 50, greater */
    tl 0
    tl 1
    tl 2
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
