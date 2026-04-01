/* SPARCv8 FABSS instruction test (Floating-point Absolute Value Single) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * FABSS (FP Absolute Value Single) tests
   * FABSS computes the absolute value (clears sign bit)
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: FABSS of positive value (unchanged)
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set float_two, %l1
    ld [%l1], %f0         /* f0 = 2.0 */
    fabss %f0, %f1        /* f1 = |2.0| = 2.0 */
    set result_buf, %l2
    st %f1, [%l2]
    ld [%l2], %l3
    ld [%l1], %l4
    cmp %l3, %l4
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: FABSS of negative value
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set float_neg_three, %l1
    ld [%l1], %f0         /* f0 = -3.0 */
    fabss %f0, %f1        /* f1 = |-3.0| = 3.0 */
    set result_buf, %l2
    st %f1, [%l2]
    ld [%l2], %l3
    set float_three, %l4
    ld [%l4], %l5
    cmp %l3, %l5
    be test_3_pass
    nop
    ba fail
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: FABSS of negative zero
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set float_neg_zero, %l1
    ld [%l1], %f0         /* f0 = -0.0 */
    fabss %f0, %f1        /* f1 = |-0.0| = 0.0 */
    set result_buf, %l2
    st %f1, [%l2]
    ld [%l2], %l3
    set float_zero, %l4
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
float_zero:
  .word 0x00000000      /* 0.0f */
float_neg_zero:
  .word 0x80000000      /* -0.0f */
float_two:
  .word 0x40000000      /* 2.0f */
float_three:
  .word 0x40400000      /* 3.0f */
float_neg_three:
  .word 0xC0400000      /* -3.0f */

  .align 4
result_buf:
  .word 0

SPARCV8_DATA_END
