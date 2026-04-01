/* SPARCv8 STFSR instruction test (Store Floating-point State Register) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * STFSR (Store FSR) tests
   * STFSR stores the Floating-point State Register to memory
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: STFSR after LDFSR
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set fsr_val, %l1
    ld [%l1], %fsr        /* Load known FSR value */
    set result_buf, %l2
    st %fsr, [%l2]        /* Store FSR */
    ld [%l2], %l3
    ld [%l1], %l4
    /* Compare rounding mode bits */
    srl %l3, 30, %l3
    srl %l4, 30, %l4
    cmp %l3, %l4
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: STFSR to different address
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set fsr_val, %l1
    ld [%l1], %fsr
    set result_buf2, %l2
    st %fsr, [%l2]        /* Store to different location */
    ld [%l2], %l3
    ld [%l1], %l4
    srl %l3, 30, %l3
    srl %l4, 30, %l4
    cmp %l3, %l4
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

  .align 4
fsr_val:
  .word 0x00000000      /* FSR: RD=0 */

  .align 4
result_buf:
  .word 0
result_buf2:
  .word 0

SPARCV8_DATA_END
