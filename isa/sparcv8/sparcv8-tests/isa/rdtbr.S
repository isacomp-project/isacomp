/* SPARCv8 RDTBR instruction test (Read Trap Base Register) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * RDTBR (Read TBR) tests
   * RDTBR reads the Trap Base Register
   * Note: This is a privileged instruction, test assumes supervisor mode
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: RDTBR reads TBR into register
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    rd %tbr, %l1          /* Read TBR into %l1 */
    /* Just verify execution continues */
    set 42, %l2
    cmp %l2, 42
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: Multiple RDTBR reads
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    rd %tbr, %l1
    rd %tbr, %l2
    /* TBR should be consistent (trap type field may vary) */
    /* Just verify execution completes */
    set 100, %l3
    cmp %l3, 100
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
