/* SPARCv8 TN instruction test (Trap Never) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * TN (Trap Never) tests
   * TN never generates a trap - effectively a NOP
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: TN should not trap, execution continues
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    tn 0                  /* Should not trap, continue execution */
    set 42, %l1
    cmp %l1, 42
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: Multiple TN instructions should all be NOPs
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    tn 0
    tn 1
    tn 2
    set 100, %l1
    cmp %l1, 100
    be test_3_pass
    nop
    ba fail
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: TN with register operand
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set 5, %l1
    tn %l1                /* TN with register - still should not trap */
    set 200, %l2
    cmp %l2, 200
    be test_4_pass
    nop
    ba fail
    nop
test_4_pass:

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
