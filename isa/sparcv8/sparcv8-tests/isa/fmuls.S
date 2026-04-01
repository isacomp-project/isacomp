/* SPARCv8 FMULS instruction test (Floating-point Multiply Single) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * FMULS (FP Multiply Single) tests
   * FMULS multiplies two single-precision FP values
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: FMULS 2.0 * 3.0 = 6.0
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set float_two, %l1
    ld [%l1], %f0         /* f0 = 2.0 */
    set float_three, %l2
    ld [%l2], %f1         /* f1 = 3.0 */
    fmuls %f0, %f1, %f2   /* f2 = 2.0 * 3.0 = 6.0 */
    set result_buf, %l3
    st %f2, [%l3]
    ld [%l3], %l4
    set float_six, %l5
    ld [%l5], %l6
    cmp %l4, %l6
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: FMULS 5.0 * 1.0 = 5.0
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set float_five, %l1
    ld [%l1], %f0         /* f0 = 5.0 */
    set float_one, %l2
    ld [%l2], %f1         /* f1 = 1.0 */
    fmuls %f0, %f1, %f2   /* f2 = 5.0 * 1.0 = 5.0 */
    set result_buf, %l3
    st %f2, [%l3]
    ld [%l3], %l4
    ld [%l1], %l5
    cmp %l4, %l5
    be test_3_pass
    nop
    ba fail
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: FMULS 2.0 * 2.0 = 4.0
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set float_two, %l1
    ld [%l1], %f0
    fmuls %f0, %f0, %f1   /* f1 = 2.0 * 2.0 = 4.0 */
    set result_buf, %l2
    st %f1, [%l2]
    ld [%l2], %l3
    set float_four, %l4
    ld [%l4], %l5
    cmp %l3, %l5
    be test_4_pass
    nop
    ba fail
    nop
test_4_pass:

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA

  .align 4
float_one:
  .word 0x3F800000      /* 1.0f */
float_two:
  .word 0x40000000      /* 2.0f */
float_three:
  .word 0x40400000      /* 3.0f */
float_four:
  .word 0x40800000      /* 4.0f */
float_five:
  .word 0x40A00000      /* 5.0f */
float_six:
  .word 0x40C00000      /* 6.0f */

  .align 4
result_buf:
  .word 0

SPARCV8_DATA_END
