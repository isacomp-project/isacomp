/* SPARCv8 WRWIM instruction test (Write Window Invalid Mask) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * WRWIM (Write WIM) tests
   * WRWIM writes to the Window Invalid Mask register
   * Note: This is a privileged instruction, test assumes supervisor mode
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: WRWIM preserving current value
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    rd %wim, %l1          /* Read current WIM */
    wr %l1, %wim          /* Write same value back */
    nop                   /* Delay for WIM write */
    nop
    nop
    rd %wim, %l2          /* Read back */
    cmp %l1, %l2
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: WRWIM with immediate
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    rd %wim, %l1          /* Save original */
    wr %g0, 1, %wim       /* Set WIM to 1 */
    nop
    nop
    nop
    rd %wim, %l2
    cmp %l2, 1
    bne test_3_fail
    nop
    wr %l1, %wim          /* Restore original */
    nop
    nop
    nop
    ba test_3_pass
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
