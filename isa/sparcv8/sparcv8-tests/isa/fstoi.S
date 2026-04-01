/* SPARCv8 FSTOI instruction test (Convert Single FP to Integer) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * FSTOI (Convert Single to Integer) tests
   * FSTOI converts a single FP value to 32-bit integer (truncates)
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: FSTOI convert 1.0f to 1
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set float_one, %l1
    ld [%l1], %f0         /* f0 = 1.0f */
    fstoi %f0, %f1        /* f1 = integer 1 */
    set result_buf, %l2
    st %f1, [%l2]
    ld [%l2], %l3
    set int_one, %l4
    ld [%l4], %l5
    cmp %l3, %l5
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: FSTOI convert 10.0f to 10
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set float_ten, %l1
    ld [%l1], %f0         /* f0 = 10.0f */
    fstoi %f0, %f1        /* f1 = integer 10 */
    set result_buf, %l2
    st %f1, [%l2]
    ld [%l2], %l3
    set int_ten, %l4
    ld [%l4], %l5
    cmp %l3, %l5
    be test_3_pass
    nop
    ba fail
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: FSTOI convert 2.5f to 2 (truncates toward zero)
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set float_two_half, %l1
    ld [%l1], %f0         /* f0 = 2.5f */
    fstoi %f0, %f1        /* f1 = integer 2 */
    set result_buf, %l2
    st %f1, [%l2]
    ld [%l2], %l3
    set int_two, %l4
    ld [%l4], %l5
    cmp %l3, %l5
    be test_4_pass
    nop
    ba fail
    nop
test_4_pass:

  /*-------------------------------------------------------------
   * Test 5: FSTOI convert -1.0f to -1
   *-------------------------------------------------------------*/
test_5:
    mov 5, TESTNUM
    set float_neg_one, %l1
    ld [%l1], %f0         /* f0 = -1.0f */
    fstoi %f0, %f1        /* f1 = integer -1 */
    set result_buf, %l2
    st %f1, [%l2]
    ld [%l2], %l3
    set int_neg_one, %l4
    ld [%l4], %l5
    cmp %l3, %l5
    be test_5_pass
    nop
    ba fail
    nop
test_5_pass:

  TEST_PASSFAIL

SPARCV8_TEST_CODE_END

SPARCV8_PASS
SPARCV8_FAIL

SPARCV8_DATA_BEGIN
  TEST_DATA

  .align 4
float_one:
  .word 0x3F800000      /* 1.0f */
float_ten:
  .word 0x41200000      /* 10.0f */
float_two_half:
  .word 0x40200000      /* 2.5f */
float_neg_one:
  .word 0xBF800000      /* -1.0f */

  .align 4
int_one:
  .word 1
int_two:
  .word 2
int_ten:
  .word 10
int_neg_one:
  .word 0xFFFFFFFF      /* -1 */

  .align 4
result_buf:
  .word 0

SPARCV8_DATA_END
