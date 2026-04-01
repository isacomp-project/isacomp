/* SPARCv8 FBA instruction test (FP Branch Always) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * FBA (FP Branch Always) tests
   * FBA always branches regardless of FP condition codes
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: FBA basic branch
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    fba test_2_target
    nop
    ba fail
    nop
test_2_target:
    ba test_2_pass
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: FBA forward branch with larger offset
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    fba test_3_target     /* Forward branch */
    nop
    ba fail
    nop
    ba fail
    nop
    ba fail
    nop
test_3_target:
    ba test_3_pass
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: FBA delay slot executes
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    mov 0, %l6
    fba test_4_target
    mov 1, %l6            /* Delay slot should execute */
    ba fail
    nop
test_4_target:
    cmp %l6, 1
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
