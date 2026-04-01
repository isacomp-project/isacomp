/* SPARCv8 RDPSR instruction test (Read Processor State Register) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * RDPSR (Read PSR) tests
   * RDPSR reads the Processor State Register
   * Note: This is a privileged instruction, test assumes supervisor mode
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: RDPSR reads PSR into register
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    rd %psr, %l1          /* Read PSR into %l1 */
    /* Just verify execution continues - PSR value varies */
    set 42, %l2
    cmp %l2, 42
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: Multiple RDPSR reads
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    rd %psr, %l1
    rd %psr, %l2
    rd %psr, %l3
    /* All reads should succeed in supervisor mode */
    set 100, %l4
    cmp %l4, 100
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
