/* SPARCv8 WRTBR instruction test (Write Trap Base Register) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * WRTBR (Write TBR) tests
   * WRTBR writes to the Trap Base Register
   * Note: This is a privileged instruction, test assumes supervisor mode
   * Only TBA field (bits 31:12) is writable, tt field (11:4) is read-only
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: WRTBR preserving current TBA
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    rd %tbr, %l1          /* Read current TBR */
    set 0xFFFFF000, %l3   /* Mask for TBA field */
    and %l1, %l3, %l1     /* Keep only TBA */
    wr %l1, %tbr          /* Write back TBA */
    nop                   /* Delay for TBR write */
    nop
    nop
    /* Verify execution continues */
    set 42, %l2
    cmp %l2, 42
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: WRTBR with XOR operand
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    rd %tbr, %l1
    set 0xFFFFF000, %l3
    and %l1, %l3, %l1
    wr %l1, %g0, %tbr     /* Write TBR XOR 0 */
    nop
    nop
    nop
    set 100, %l2
    cmp %l2, 100
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
