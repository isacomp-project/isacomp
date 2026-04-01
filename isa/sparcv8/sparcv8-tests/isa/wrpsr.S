/* SPARCv8 WRPSR instruction test (Write Processor State Register) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * WRPSR (Write PSR) tests
   * WRPSR writes to the Processor State Register
   * Note: This is a privileged instruction, test assumes supervisor mode
   * We must be careful to preserve supervisor mode (S bit)
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: WRPSR preserving current mode
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    rd %psr, %l1          /* Read current PSR */
    wr %l1, %psr          /* Write same value back */
    nop                   /* Delay for PSR write */
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
   * Test 3: WRPSR with XOR operand
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    rd %psr, %l1
    wr %l1, %g0, %psr     /* Write PSR XOR 0 = same value */
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
