/* SPARCv8 FNEGS instruction test (Floating-point Negate Single) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * FNEGS (FP Negate Single) tests
   * FNEGS negates a single-precision FP value (flips sign bit)
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: FNEGS of positive value
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set float_one, %l1
    ld [%l1], %f0         /* f0 = 1.0 */
    fnegs %f0, %f1        /* f1 = -1.0 */
    set result_buf, %l2
    st %f1, [%l2]
    ld [%l2], %l3
    set float_neg_one, %l4
    ld [%l4], %l5
    cmp %l3, %l5
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: FNEGS of negative value (double negation)
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set float_neg_two, %l1
    ld [%l1], %f0         /* f0 = -2.0 */
    fnegs %f0, %f1        /* f1 = 2.0 */
    set result_buf, %l2
    st %f1, [%l2]
    ld [%l2], %l3
    set float_two, %l4
    ld [%l4], %l5
    cmp %l3, %l5
    be test_3_pass
    nop
    ba fail
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: FNEGS of zero (should give -0.0)
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set float_zero, %l1
    ld [%l1], %f0         /* f0 = 0.0 */
    fnegs %f0, %f1        /* f1 = -0.0 */
    set result_buf, %l2
    st %f1, [%l2]
    ld [%l2], %l3
    set float_neg_zero, %l4
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
float_one:
  .word 0x3F800000      /* 1.0f */
float_neg_one:
  .word 0xBF800000      /* -1.0f */
float_two:
  .word 0x40000000      /* 2.0f */
float_neg_two:
  .word 0xC0000000      /* -2.0f */

  .align 4
result_buf:
  .word 0

SPARCV8_DATA_END
