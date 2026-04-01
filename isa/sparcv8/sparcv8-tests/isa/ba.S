/* SPARCv8 BA instruction tests (branch always) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Basic branch always tests
   *-------------------------------------------------------------*/

test_2:
  mov 2, TESTNUM
  ba test_2_target
  nop
  ba fail
  nop
test_2_target:

test_3:
  mov 3, TESTNUM
  ba test_3_forward
  nop
  ba fail
  nop
test_3_forward:
  ba test_3_done
  nop
  ba fail
  nop
test_3_done:

  /* Test backward branch */
test_4_target:
  ba test_4_done
  nop
test_4:
  mov 4, TESTNUM
  ba test_4_target
  nop
  ba fail
  nop
test_4_done:

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA
SPARCV8_DATA_END
