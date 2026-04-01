/* SPARCv8 TADDccTV instruction test (Tagged Add with Trap on Overflow) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * TADDccTV (Tagged Add with CC and Trap on oVerflow) tests
   * TADDccTV traps if tagged overflow occurs (low 2 bits non-zero
   * in either operand, or arithmetic overflow)
   * We test by ensuring no trap when operands are tag-clean
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: TADDccTV with clean tags, no overflow
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set 100, %l1          /* Low 2 bits = 00 (clean tag) */
    set 200, %l2          /* Low 2 bits = 00 (clean tag) */
    taddcctv %l1, %l2, %l3  /* Should NOT trap */
    set 300, %l4
    cmp %l3, %l4
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: TADDccTV with small clean values
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set 4, %l1            /* 4 = 0b100, low bits = 00 */
    set 8, %l2            /* 8 = 0b1000, low bits = 00 */
    taddcctv %l1, %l2, %l3
    set 12, %l4
    cmp %l3, %l4
    be test_3_pass
    nop
    ba fail
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: TADDccTV setting condition codes
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set 0, %l1
    set 0, %l2
    taddcctv %l1, %l2, %l3  /* Result = 0, Z should be set */
    bne test_4_fail         /* Branch if Z=0 (not equal) */
    nop
    ba test_4_pass
    nop
test_4_fail:
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
