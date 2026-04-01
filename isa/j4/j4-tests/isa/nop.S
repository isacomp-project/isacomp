/* j4 (SuperH-4) NOP instruction tests */

#include "test_macros.h"

J4TEST_CODE_BEGIN

  /* Just execute some NOPs and make sure we get to pass */
  nop
  nop
  nop
  nop
  nop

  /* Verify we can still execute instructions after NOPs */
  mov #5, r1
  mov #5, r2
  cmp/eq r1, r2
  bf fail
  nop

  TEST_PASSFAIL

J4TEST_CODE_END

J4TEST_PASS
J4TEST_FAIL

J4TEST_DATA_BEGIN
  TEST_DATA
J4TEST_DATA_END
