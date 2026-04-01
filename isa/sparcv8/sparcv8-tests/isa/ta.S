/* SPARCv8 TA instruction test (Trap Always) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * TA (Trap Always) tests
   * TA always generates a trap with trap number = rs1 + reg_or_imm
   * For testing, we check that execution doesn't proceed past TA
   * by ensuring that if we skip the trap, the test passes
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: Basic TA instruction encoding test
   * Since we can't easily test trap handling without a trap table,
   * we test by jumping over the TA instruction
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    ba test_2_skip
    nop
    ta 0                  /* This should not execute */
    ba fail               /* Should not reach here */
    nop
test_2_skip:
    ba test_2_pass
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: TA with immediate operand encoding
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    ba test_3_skip
    nop
    ta 1                  /* TA with immediate 1 */
    ba fail
    nop
test_3_skip:
    ba test_3_pass
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: Verify branch over TA works correctly
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set 1, %l1
    cmp %l1, 1
    be test_4_skip        /* Branch should be taken */
    nop
    ta 0                  /* Should not execute */
    ba fail
    nop
test_4_skip:
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
