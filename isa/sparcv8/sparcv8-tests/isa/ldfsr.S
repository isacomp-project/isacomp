/* SPARCv8 LDFSR instruction test (Load Floating-point State Register) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * LDFSR (Load FSR) tests
   * LDFSR loads the Floating-point State Register from memory
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: LDFSR basic load and verify via STFSR
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set fsr_val1, %l1
    ld [%l1], %fsr        /* Load FSR */
    set result_buf, %l2
    st %fsr, [%l2]        /* Store FSR back */
    ld [%l2], %l3
    ld [%l1], %l4
    /* FSR has reserved bits, so just check rounding mode (bits 31:30) */
    srl %l3, 30, %l3
    srl %l4, 30, %l4
    cmp %l3, %l4
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: LDFSR with different rounding mode
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set fsr_val2, %l1
    ld [%l1], %fsr        /* Load FSR with different RM */
    set result_buf, %l2
    st %fsr, [%l2]
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
fsr_val1:
  .word 0x00000000      /* FSR: RD=0 (round to nearest) */
fsr_val2:
  .word 0x40000000      /* FSR: RD=1 (round toward zero) */

  .align 4
result_buf:
  .word 0

SPARCV8_DATA_END
