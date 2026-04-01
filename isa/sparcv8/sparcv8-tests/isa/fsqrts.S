/* SPARCv8 FSQRTS instruction test (Floating-point Square Root Single) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * FSQRTS (FP Square Root Single) tests
   * FSQRTS computes the square root of a single-precision FP value
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: FSQRTS sqrt(4.0) = 2.0
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set float_four, %l1
    ld [%l1], %f0         /* f0 = 4.0 */
    fsqrts %f0, %f1       /* f1 = sqrt(4.0) = 2.0 */
    set result_buf, %l2
    st %f1, [%l2]
    ld [%l2], %l3
    set float_two, %l4
    ld [%l4], %l5
    cmp %l3, %l5
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: FSQRTS sqrt(1.0) = 1.0
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set float_one, %l1
    ld [%l1], %f0         /* f0 = 1.0 */
    fsqrts %f0, %f1       /* f1 = sqrt(1.0) = 1.0 */
    set result_buf, %l2
    st %f1, [%l2]
    ld [%l2], %l3
    ld [%l1], %l4
    cmp %l3, %l4
    be test_3_pass
    nop
    ba fail
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: FSQRTS sqrt(9.0) = 3.0
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set float_nine, %l1
    ld [%l1], %f0         /* f0 = 9.0 */
    fsqrts %f0, %f1       /* f1 = sqrt(9.0) = 3.0 */
    set result_buf, %l2
    st %f1, [%l2]
    ld [%l2], %l3
    set float_three, %l4
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
float_nine:
  .word 0x41100000      /* 9.0f */

  .align 4
result_buf:
  .word 0

SPARCV8_DATA_END
