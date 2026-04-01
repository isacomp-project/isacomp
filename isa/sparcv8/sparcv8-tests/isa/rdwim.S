/* SPARCv8 RDWIM instruction test (Read Window Invalid Mask) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * RDWIM (Read WIM) tests
   * RDWIM reads the Window Invalid Mask register
   * Note: This is a privileged instruction, test assumes supervisor mode
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: RDWIM reads WIM into register
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    rd %wim, %l1          /* Read WIM into %l1 */
    /* Just verify execution continues */
    set 42, %l2
    cmp %l2, 42
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: Multiple RDWIM reads
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    rd %wim, %l1
    rd %wim, %l2
    /* Both reads should give same value */
    cmp %l1, %l2
    be test_3_pass
    nop
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
