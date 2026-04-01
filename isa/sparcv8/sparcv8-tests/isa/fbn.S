/* SPARCv8 FBN instruction test (FP Branch Never) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * FBN (FP Branch Never) tests
   * FBN never branches (acts as a 2-cycle NOP with delay slot)
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: FBN does not branch
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    fbn test_2_fail       /* Should NOT branch */
    nop
    ba test_2_pass
    nop
test_2_fail:
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: FBN delay slot executes
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    mov 0, %l6
    fbn test_3_fail       /* Should NOT branch */
    mov 1, %l6            /* Delay slot should still execute */
    cmp %l6, 1
    be test_3_pass
    nop
    ba fail
    nop
test_3_fail:
    ba fail
    nop
test_3_pass:

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA

SPARCV8_DATA_END
